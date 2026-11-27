"""U3-P2 business read contract.

PostgreSQL (or SQLite) supplies the bounded base candidate stream; the SQLite
Task store remains the only authority for training history, sample roles,
training usage and task negative confirmations. This module composes those
authorities instead of re-implementing any of their rules:

* history      -> ``TrainingMaterialUsage.query_filter`` (tokens, coverage, tasks)
* roles        -> ``training_label_tasks.training_material_role`` (+ promotions)
* confirmations-> P1 ``get_task_negative_receipts`` re-validated against current GT
* labels/GT    -> the caller's contract (``effective_label_codes``)

Pagination is applied AFTER every business predicate, over a bounded stream.
"""
from __future__ import annotations

import base64
import hashlib
import json
from contextlib import closing
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from .annotation_repository import AnnotationRepository
from .material_repository import MaterialRepository
from .training_label_tasks import (
    task_negative_confirmable,
    task_negative_context,
    task_partial_scope_confirmable,
    training_material_role,
)
from .training_material_picker_read import (
    DEFAULT_PAGE_SIZE,
    MAX_BATCH_IDS,
    MAX_PAGE_SIZE,
    PickerCursorContextMismatch,
    PickerFilter,
    PickerMaterial,
    PickerProjectMismatch,
    PickerQuery,
    PickerReadError,
    PickerSnapshotStale,
    PickerUnsupportedFilter,
    _chunks,
    _normalize_ids,
)
from .training_material_usage import TrainingMaterialUsage

MAX_SELECTION_IDS = 50000


# ---------------------------------------------------------------------------
# Errors: explicit, never converted into an empty page or "unused"
# ---------------------------------------------------------------------------
class BusinessReadError(PickerReadError):
    code = "PICKER_BUSINESS_READ_FAILED"


class BusinessHistoryUnavailable(BusinessReadError):
    code = "PICKER_HISTORY_UNAVAILABLE"


class BusinessHistoryIncomplete(BusinessReadError):
    code = "PICKER_HISTORY_INCOMPLETE"


class BusinessHistoryChanged(BusinessReadError):
    code = "PICKER_HISTORY_CHANGED"


class BusinessConfirmationUnavailable(BusinessReadError):
    code = "PICKER_CONFIRMATION_UNAVAILABLE"


class BusinessCandidateMismatch(BusinessReadError):
    code = "PICKER_CANDIDATE_MISMATCH"


_HISTORY_POLICIES = ("new_for_algorithm", "include_history")
_HISTORY_SCOPES = ("", "current_only", "other_only")
_USAGE_STATES = (
    "", "used", "possible", "selected", "unused", "unknown",
    "eval_only", "test_reserved",
)
_SAMPLE_ROLES = ("", "positive", "confirmed_negative", "pending_negative", "pending_review")
_USAGE_ROLES = ("train", "test")
_UNUSABLE_HEALTH = ("incompatible", "corrupt", "unavailable")


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class BusinessFilter:
    """Business predicates on top of the P1 base filter, mirroring the picker."""

    base: PickerFilter = field(default_factory=PickerFilter)
    history_policy: str = "new_for_algorithm"
    history_scope: str = ""
    usage_state: str = ""
    algorithm_asset_id: str = ""
    sample_role: str = ""
    usage_role: str = "train"
    #: Browse keeps used rows visible (they carry a state) exactly like the
    #: existing picker page; a formal selection excludes them by policy.
    browse_only: bool = False
    #: Target/effective label contract for role judgment (not the GT filter).
    label_codes: tuple[str, ...] = ()
    strict_target_negative_scope: bool = False


@dataclass(frozen=True)
class BusinessQuery:
    project_id: str
    filters: BusinessFilter = field(default_factory=BusinessFilter)
    sort_order: str = "oldest"
    #: ``None`` streams; ``read_page`` treats None as page 1.
    page: int | None = None
    page_size: int = DEFAULT_PAGE_SIZE
    cursor: str | None = None
    count_mode: str = "exact"
    include_payload: bool = False
    verify_owner: bool = True


@dataclass(frozen=True)
class BusinessSnapshot:
    project_id: str
    source: str
    picker_snapshot_id: str
    owner_equivalent: bool
    usage_revision: str
    task_evidence: str
    count_mode: str
    read_identity: str = ""


@dataclass(frozen=True)
class BusinessMaterial:
    material: PickerMaterial
    sample_role: str
    history_state: str
    history_scope_complete: bool
    current_algorithm_trained: bool
    other_algorithm_trained: bool
    excluded: bool
    confirmation_receipt: str | None
    legacy_unproven: bool


@dataclass(frozen=True)
class BusinessPage:
    items: tuple[BusinessMaterial, ...]
    total: int | None
    has_more: bool
    next_cursor: str | None
    page: int | None
    page_size: int
    count_mode: str
    snapshot: BusinessSnapshot


# ---------------------------------------------------------------------------
# Business cursor: binds the P1 snapshot, the business query and usage revision
# ---------------------------------------------------------------------------
def _business_fingerprint(query: BusinessQuery) -> str:
    filters = query.filters
    base = filters.base
    material = {
        "project": query.project_id,
        "sort": query.sort_order,
        "verify_owner": bool(query.verify_owner),
        "base": {
            "status": base.processing_status,
            "query": base.query,
            "labels": list(base.labels),
            "label_mode": base.label_mode,
            "annotation_state": base.annotation_state,
            "require_gt": bool(base.require_ground_truth),
            "sources": list(base.storage_source_ids),
            "created_from": base.created_from,
            "created_to": base.created_to,
            "image_ids": list(base.image_ids) if base.image_ids is not None else None,
            "pool_only": bool(base.negative_pool_only),
            "categories": list(base.negative_category_ids),
            "pool_algorithm": base.algorithm_asset_id,
        },
        "business": {
            "policy": filters.history_policy,
            "scope": filters.history_scope,
            "usage_state": filters.usage_state,
            "algorithm": filters.algorithm_asset_id,
            "sample_role": filters.sample_role,
            "usage_role": filters.usage_role,
            "browse_only": bool(filters.browse_only),
            "labels": list(filters.label_codes),
            "strict": bool(filters.strict_target_negative_scope),
        },
    }
    return hashlib.sha256(
        json.dumps(material, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _encode_business_cursor(
    created_at: str, image_id: str, *, fingerprint: str, snapshot: str, usage: str,
) -> str:
    payload = {
        "t": str(created_at), "i": str(image_id),
        "q": str(fingerprint), "s": str(snapshot), "u": str(usage),
    }
    return base64.urlsafe_b64encode(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).decode("ascii").rstrip("=")


def _decode_business_cursor(
    cursor: str, *, fingerprint: str, snapshot: str, usage: str,
) -> tuple[str, str]:
    try:
        padded = str(cursor) + "=" * (-len(str(cursor)) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
        created_at = str(payload["t"])
        image_id = str(payload["i"])
        recorded_query = str(payload["q"])
        recorded_snapshot = str(payload["s"])
        recorded_usage = str(payload["u"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise PickerCursorContextMismatch(
            "the business cursor is not readable",
        ) from error
    if recorded_query != str(fingerprint) or recorded_snapshot != str(snapshot):
        raise PickerCursorContextMismatch(
            "the business cursor belongs to another query or snapshot",
        )
    if recorded_usage != str(usage):
        raise BusinessHistoryChanged(
            "the training history changed since this cursor was issued",
        )
    return created_at, image_id


def _validate_business_query(query: BusinessQuery) -> tuple[int, int | None]:
    filters = query.filters
    if filters.history_policy not in _HISTORY_POLICIES:
        raise PickerUnsupportedFilter("invalid history_policy")
    if filters.history_scope not in _HISTORY_SCOPES:
        raise PickerUnsupportedFilter("invalid history_scope")
    if filters.usage_state not in _USAGE_STATES:
        raise PickerUnsupportedFilter("invalid usage_state")
    if filters.sample_role not in _SAMPLE_ROLES:
        raise PickerUnsupportedFilter("invalid sample_role")
    if filters.usage_role not in _USAGE_ROLES:
        raise PickerUnsupportedFilter("invalid usage_role")
    if query.sort_order not in ("oldest", "newest"):
        raise PickerUnsupportedFilter("invalid sort_order")
    if query.count_mode not in ("exact", "deferred"):
        raise PickerUnsupportedFilter("invalid count_mode")
    if query.cursor and query.page is not None:
        raise PickerUnsupportedFilter("page and cursor are mutually exclusive")
    page: int | None = None
    if query.page is not None:
        try:
            page = int(query.page)
        except (TypeError, ValueError) as error:
            raise PickerUnsupportedFilter("page must be an integer") from error
        if page < 1:
            raise PickerUnsupportedFilter("page must be at least 1")
    try:
        size = int(query.page_size)
    except (TypeError, ValueError) as error:
        raise PickerUnsupportedFilter("page_size must be an integer") from error
    if size < 1 or size > MAX_PAGE_SIZE:
        raise PickerUnsupportedFilter(f"page_size must be 1..{MAX_PAGE_SIZE}")
    # The base query keeps the exact P1 validation (dates, status, ids...).
    _validate_base_query(query)
    return size, page


def _validate_base_query(query: BusinessQuery) -> None:
    from .training_material_picker_read import _validate_query

    _validate_query(PickerQuery(
        project_id=query.project_id,
        filters=query.filters.base,
        sort_order=query.sort_order,
        count_mode=query.count_mode,
        page=None,
        page_size=my_page_size(query.page_size),
        include_payload=False,
        include_annotations=False,
    ))


def my_page_size(value: int) -> int:
    try:
        size = int(value)
    except (TypeError, ValueError):
        return DEFAULT_PAGE_SIZE
    return max(1, min(size, MAX_PAGE_SIZE))


# ---------------------------------------------------------------------------
# Provider: bounded stream + authoritative SQLite business evaluation
# ---------------------------------------------------------------------------
class BusinessReadProvider:
    """Composes a P1 picker with the SQLite business authorities."""

    def __init__(
        self,
        picker,
        project_path: str | Path,
        *,
        project_id: str,
        materials: MaterialRepository | None = None,
        annotations: AnnotationRepository | None = None,
        usage: TrainingMaterialUsage | None = None,
    ):
        self.picker = picker
        self.project_path = Path(project_path)
        self.project_id = str(project_id or "")
        if not self.project_id:
            raise ValueError("the business read provider requires an explicit project id")
        self.materials = materials or MaterialRepository(self.project_path)
        self.annotations = annotations or AnnotationRepository(self.project_path)
        self.usage = usage or TrainingMaterialUsage(self.project_path / "tasks.sqlite3")

    # -- small helpers ----------------------------------------------------
    def _require_project(self, project_id: str) -> str:
        if str(project_id) != self.project_id:
            raise PickerProjectMismatch(
                "the business read provider is bound to another project",
                detail=f"requested={project_id} bound={self.project_id}",
            )
        return self.project_id

    def _contract(self, filters: BusinessFilter) -> dict[str, Any]:
        return {
            "algorithm_id": str(filters.algorithm_asset_id or ""),
            "effective_label_codes": sorted({
                str(code).strip() for code in filters.label_codes if str(code).strip()
            }),
            "strict_target_negative_scope": bool(filters.strict_target_negative_scope),
            "task_negative_confirmations": [],
        }

    def _picker_context(self) -> Any:
        return self.picker.snapshot_context(self.project_id)

    def _base_query(
        self, query: BusinessQuery, *, cursor: str | None,
    ) -> PickerQuery:
        return PickerQuery(
            project_id=query.project_id,
            filters=query.filters.base,
            sort_order=query.sort_order,
            count_mode="deferred",
            page=None,
            page_size=MAX_PAGE_SIZE,
            cursor=cursor,
            include_payload=False,
            include_annotations=False,
            verify_owner=query.verify_owner,
        )

    def _history_facts(self, query: BusinessQuery, rows: Sequence[Mapping[str, Any]]) -> dict:
        filters = query.filters
        try:
            facts = self.usage.query_filter(
                self.project_id, str(filters.algorithm_asset_id or ""), list(rows),
                exclude_used=False, role=filters.usage_role,
            )
        except Exception as error:  # noqa: BLE001 - history boundary
            raise BusinessHistoryUnavailable(
                "the training history could not be read", detail=str(error),
            ) from error
        if str(facts.get("index_health") or "") in _UNUSABLE_HEALTH:
            raise BusinessHistoryUnavailable(
                "the training history index is not usable",
                detail=f"index_health={facts.get('index_health')}",
            )
        return facts

    def _valid_receipts(
        self, query: BusinessQuery, contract: Mapping[str, Any],
        rows: Mapping[str, Mapping[str, Any]],
        annotations: Mapping[str, Mapping[str, Any]],
    ) -> list[Mapping[str, Any]]:
        if query.filters.browse_only or not contract.get("effective_label_codes"):
            return []
        context_key = task_negative_context(contract)
        try:
            receipts = self.picker.get_task_negative_receipts(
                self.project_id, context_key, list(rows),
            )
        except PickerReadError:
            raise
        except Exception as error:  # noqa: BLE001 - confirmation boundary
            raise BusinessConfirmationUnavailable(
                "the task negative confirmations could not be read", detail=str(error),
            ) from error
        if not receipts.authoritative or not receipts.owner_equivalent:
            # Uncertified or diagnostic-only reads never prove current eligibility.
            return []
        valid: list[Mapping[str, Any]] = []
        for receipt in receipts.receipts:
            evidence = dict(receipt.evidence or {})
            image_id = str(evidence.get("image_id") or "")
            row = rows.get(image_id)
            annotation = annotations.get(image_id)
            if row is None or annotation is None:
                continue
            if str(evidence.get("context_key") or "") != context_key:
                continue
            if str(evidence.get("source_content_sha256") or "") != str(
                row.get("content_sha256") or ""
            ):
                continue
            if int(evidence.get("annotation_version") or 0) != int(
                annotation.get("version") or 0
            ):
                continue
            if str(evidence.get("annotation_hash") or "") != str(
                annotation.get("content_digest") or ""
            ):
                continue
            valid.append(evidence)
        return valid

    @staticmethod
    def _role_row(
        material: Mapping[str, Any], annotation: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        record = {
            key: value for key, value in material.items() if key != "payload"
        }
        if annotation:
            record.update(dict(annotation))
            record["id"] = str(annotation.get("image_id") or material.get("id") or "")
            record["annotation_version"] = int(annotation.get("version") or 0)
            record["annotation_hash"] = str(annotation.get("content_digest") or "")
        return record

    def _evaluate_batch(
        self, query: BusinessQuery, batch: Sequence[PickerMaterial],
    ) -> tuple[list[BusinessMaterial], dict[str, dict[str, Any]]]:
        filters = query.filters
        ids = [item.id for item in batch]
        material_rows = {str(row.get("id")): row for row in self.materials.get_many(ids)}
        annotation_rows = self.annotations.get_many(ids)
        pg_annotations = self.picker.get_annotations(self.project_id, ids)
        contract = self._contract(filters)
        valid_receipts = self._valid_receipts(query, contract, material_rows, annotation_rows)
        contract = {**contract, "task_negative_confirmations": valid_receipts}
        facts = self._history_facts(query, list(material_rows.values()))
        by_id = facts.get("by_image_id") or {}
        receipt_ids = {str(receipt.get("receipt_id") or "") for receipt in valid_receipts}
        unproven_legacy = set(pg_annotations.unproven_legacy_ids)
        items: list[BusinessMaterial] = []
        state_by_id: dict[str, dict[str, Any]] = {}
        for item in batch:
            material = material_rows.get(item.id)
            if material is None:
                continue
            annotation = annotation_rows.get(item.id)
            fact = by_id.get(item.id) or {}
            state = str(fact.get("state") or "unknown")
            state_by_id[item.id] = fact
            if filters.history_scope == "current_only":
                if not fact.get("current_algorithm_trained"):
                    continue
            elif filters.history_scope == "other_only":
                if not (
                    fact.get("other_algorithm_trained")
                    and not fact.get("current_algorithm_trained")
                ):
                    continue
            if filters.usage_state and state != filters.usage_state:
                continue
            # ``exclude_used=False`` above keeps the facts neutral; the policy is
            # applied here exactly like the existing picker SQL anti-join:
            #   new_for_algorithm -> train/test exposure on this algorithm (or an
            #                        active/observed Test reservation)
            #   include_history   -> only the Test reservation is excluded
            if filters.usage_role == "test":
                excluded = state in {"used", "possible"}
            elif filters.history_policy == "include_history":
                excluded = bool(fact.get("benchmark_protected")) or state == "test_reserved"
            else:
                excluded = state in {"used", "possible", "test_reserved"}
            # An explicit usage_state/history_scope is a whitelist, exactly like
            # the picker's Python fallback: the policy exclusion only applies to
            # an unfiltered selection.
            explicit_scope = bool(filters.usage_state or filters.history_scope)
            if excluded and not filters.browse_only and not explicit_scope:
                continue
            role_row = self._role_row(material, annotation)
            try:
                decision = training_material_role(role_row, contract)
            except ValueError as error:
                raise BusinessReadError(
                    "a material role could not be determined", detail=str(error),
                ) from error
            sample_role = str(decision.get("role") or "pending_review")
            if sample_role == "pending_review":
                if task_negative_confirmable(role_row, contract):
                    sample_role = "pending_negative"
                elif task_partial_scope_confirmable(role_row, contract):
                    sample_role = "positive"
            if filters.sample_role and sample_role != filters.sample_role:
                continue
            base = PickerMaterial(
                id=str(material.get("id") or item.id),
                filename=str(material.get("filename") or item.filename),
                storage_source_id=str(material.get("storage_source_id") or item.storage_source_id),
                processing_status=str(material.get("processing_status") or item.processing_status),
                content_sha256=str(material.get("content_sha256") or item.content_sha256),
                size_bytes=material.get("size_bytes", item.size_bytes),
                box_count=material.get("box_count", item.box_count),
                annotated=material.get("annotated", item.annotated),
                created_at=str(material.get("created_at") or item.created_at),
                updated_at=str(material.get("updated_at") or item.updated_at),
                payload=dict(material) if query.include_payload else None,
            )
            receipt = None
            if annotation is not None:
                identity = _receipt_identity(role_row, contract)
                if identity in receipt_ids:
                    receipt = identity
            items.append(BusinessMaterial(
                material=base,
                sample_role=sample_role,
                history_state=state,
                history_scope_complete=bool(fact.get("history_scope_complete")),
                current_algorithm_trained=bool(fact.get("current_algorithm_trained")),
                other_algorithm_trained=bool(fact.get("other_algorithm_trained")),
                excluded=excluded,
                confirmation_receipt=receipt,
                legacy_unproven=item.id in unproven_legacy,
            ))
        return items, state_by_id

    # -- streaming --------------------------------------------------------
    def iter_candidates(
        self, query: BusinessQuery, *, batch_size: int = MAX_PAGE_SIZE,
    ) -> Iterator[tuple[BusinessMaterial, ...]]:
        self._require_project(query.project_id)
        if query.page is not None:
            raise PickerUnsupportedFilter(
                "candidate streaming does not support page mode",
            )
        _validate_business_query(replace(query, page=None, count_mode="deferred"))
        fingerprint = _business_fingerprint(query)
        context = self._picker_context()
        token = str(context.snapshot_id)
        usage_revision = self._usage_revision()
        start = None
        if query.cursor:
            start = _decode_business_cursor(
                query.cursor, fingerprint=fingerprint, snapshot=token,
                usage=usage_revision,
            )
        base_query = self._base_query(query, cursor=None)
        base_cursor = None
        if start is not None:
            base_cursor = _encode_picker_cursor_for(
                start[0], start[1],
                fingerprint=_base_fingerprint(base_query), snapshot=token,
            )
        base_query = replace(base_query, cursor=base_cursor)
        evaluated = 0
        for batch in self.picker.iter_candidates(base_query, batch_size=batch_size):
            items, _states = self._evaluate_batch(query, batch)
            evaluated += len(batch)
            if items:
                yield tuple(items)
            if evaluated > MAX_SELECTION_IDS:
                raise PickerUnsupportedFilter(
                    f"candidate streaming exceeded {MAX_SELECTION_IDS} materials",
                )
        if self._usage_revision() != usage_revision:
            raise BusinessHistoryChanged(
                "the training history changed while streaming candidates",
            )
        if str(self._picker_context().snapshot_id) != token:
            raise PickerSnapshotStale(
                "the picker snapshot changed while streaming candidates",
            )

    def read_page(self, query: BusinessQuery) -> BusinessPage:
        self._require_project(query.project_id)
        size, page = _validate_business_query(query)
        context = self._picker_context()
        token = str(context.snapshot_id)
        usage_revision = self._usage_revision()
        fingerprint = _business_fingerprint(query)
        start = None
        page_number = 1 if page is None else page
        skip = 0
        if query.cursor:
            start = _decode_business_cursor(
                query.cursor, fingerprint=fingerprint, snapshot=token,
                usage=usage_revision,
            )
        elif page_number > 1:
            skip = (page_number - 1) * size
        items: list[BusinessMaterial] = []
        total: int | None = None
        matched = 0
        skipped = 0
        last: BusinessMaterial | None = None
        has_more = False
        stream = self.iter_candidates(replace(query, page=None, cursor=query.cursor))
        for batch in stream:
            for item in batch:
                matched += 1
                if skipped < skip:
                    skipped += 1
                    continue
                if len(items) < size:
                    items.append(item)
                    last = item
                elif query.count_mode == "deferred":
                    has_more = True
                    break
            if has_more:
                break
        if query.count_mode == "exact":
            # Every match was consumed: the count is exact and the page position
            # is known, with no second full-project COUNT.
            total = matched
            has_more = matched > skipped + len(items)
        else:
            total = None
        next_cursor = None
        if has_more and last is not None and last.material.created_at:
            next_cursor = _encode_business_cursor(
                last.material.created_at, last.material.id,
                fingerprint=fingerprint, snapshot=token, usage=usage_revision,
            )
        return BusinessPage(
            items=tuple(items), total=total, has_more=has_more,
            next_cursor=next_cursor, page=page_number, page_size=size,
            count_mode=query.count_mode,
            snapshot=BusinessSnapshot(
                project_id=self.project_id, source=str(getattr(self.picker, "name", "")),
                picker_snapshot_id=token,
                owner_equivalent=bool(query.verify_owner),
                usage_revision=usage_revision,
                task_evidence=_task_evidence(token, usage_revision, len(items)),
                count_mode=query.count_mode,
                read_identity=str(getattr(context, "read_identity", "") or ""),
            ),
        )

    def _usage_revision(self) -> str:
        try:
            return str(self.usage.read_revision())
        except Exception as error:  # noqa: BLE001 - history boundary
            raise BusinessHistoryUnavailable(
                "the training history revision could not be read", detail=str(error),
            ) from error


def _base_fingerprint(query: PickerQuery) -> str:
    from .training_material_picker_read import _query_fingerprint

    return _query_fingerprint(query)


def _encode_picker_cursor_for(
    created_at: str, image_id: str, *, fingerprint: str, snapshot: str,
) -> str:
    from .training_material_picker_read import encode_picker_cursor

    return encode_picker_cursor(
        created_at, image_id, fingerprint=fingerprint, snapshot=snapshot,
    )


def _receipt_identity(row: Mapping[str, Any], contract: Mapping[str, Any]) -> str:
    from .training_label_tasks import task_negative_identity

    return str(task_negative_identity(row, contract).get("receipt_id") or "")


def _task_evidence(token: str, usage_revision: str, count: int) -> str:
    return hashlib.sha256(
        json.dumps([token, usage_revision, count]).encode("utf-8")
    ).hexdigest()[:32]


def selection_digest(image_ids: Sequence[str]) -> str:
    """The existing frozen-selection digest: sorted ids, each followed by NUL."""
    digest = hashlib.sha256()
    for image_id in sorted({str(value) for value in image_ids}):
        digest.update((image_id + "\0").encode("utf-8"))
    return digest.hexdigest()


def compare_candidate_sets(
    first: BusinessReadProvider, second: BusinessReadProvider, query: BusinessQuery,
    *, limit: int = MAX_SELECTION_IDS,
) -> dict[str, Any]:
    """Read-only equivalence of two providers over the same business query.

    The comparison is only published after BOTH streams are fully consumed and
    each provider's own snapshot/history checks passed; a partial stream or a
    changed owner never yields a "successful" subset.
    """
    first_ids = list(_collect_ids(first, query, limit))
    second_ids = list(_collect_ids(second, query, limit))
    if first_ids != second_ids:
        raise BusinessCandidateMismatch(
            "candidate sets differ",
            detail=f"first={len(first_ids)} second={len(second_ids)}",
        )
    return {
        "count": len(first_ids),
        "digest": selection_digest(first_ids),
        "ids": first_ids,
    }


def _collect_ids(
    provider: BusinessReadProvider, query: BusinessQuery, limit: int,
) -> Iterator[str]:
    seen = 0
    for batch in provider.iter_candidates(query):
        for item in batch:
            seen += 1
            if seen > limit:
                raise PickerUnsupportedFilter(
                    f"candidate comparison is limited to {limit} materials",
                )
            yield item.material.id
