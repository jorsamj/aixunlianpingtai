"""U3-P2 business read contract (audit-remediated).

PostgreSQL (or SQLite) supplies the bounded base candidate stream; the SQLite
Task/Annotation owners remain the only authority for history, sample roles,
usage and task negative confirmations. One explicit business read session owns
the candidate stream, the GT/confirmation reads and the final consistency
checks, so an early stop can never skip verification.
"""
from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
import sys
from contextlib import closing, contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from .annotation_repository import AnnotationRepository
from .material_repository import MaterialRepository
from .training_label_tasks import (
    task_negative_confirmable,
    task_negative_context,
    task_negative_identity,
    training_material_role,
)
from .training_material_picker_read import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    PickerCursorContextMismatch,
    PickerFilter,
    PickerMaterial,
    PickerProjectMismatch,
    PickerQuery,
    PickerReadError,
    PickerSnapshotStale,
    PickerUnsupportedFilter,
)
from .training_material_usage import TrainingMaterialUsage

#: Report-only cap for ``compare_candidate_sets``; normal streaming is unbounded
#: (bounded per batch, not per project).
MAX_COMPARISON_IDS = 200000


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class BusinessReadError(PickerReadError):
    code = "PICKER_BUSINESS_READ_FAILED"


class BusinessHistoryUnavailable(BusinessReadError):
    code = "PICKER_HISTORY_UNAVAILABLE"


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
    base: PickerFilter = field(default_factory=PickerFilter)
    history_policy: str = "new_for_algorithm"
    history_scope: str = ""
    usage_state: str = ""
    algorithm_asset_id: str = ""
    sample_role: str = ""
    usage_role: str = "train"
    browse_only: bool = False
    label_codes: tuple[str, ...] = ()
    strict_target_negative_scope: bool = False


@dataclass(frozen=True)
class BusinessQuery:
    project_id: str
    filters: BusinessFilter = field(default_factory=BusinessFilter)
    sort_order: str = "oldest"
    page: int | None = None
    page_size: int = DEFAULT_PAGE_SIZE
    cursor: str | None = None
    count_mode: str = "deferred"
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
# Cursor / fingerprint
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
    created_at: str, image_id: str, *, fingerprint: str, snapshot: str,
    usage: str, task_evidence: str,
) -> str:
    payload = {
        "t": str(created_at), "i": str(image_id), "q": str(fingerprint),
        "s": str(snapshot), "u": str(usage), "e": str(task_evidence),
    }
    return base64.urlsafe_b64encode(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).decode("ascii").rstrip("=")


def _decode_business_cursor(
    cursor: str, *, fingerprint: str, snapshot: str, usage: str, task_evidence: str,
) -> tuple[str, str]:
    try:
        padded = str(cursor) + "=" * (-len(str(cursor)) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
        created_at = str(payload["t"])
        image_id = str(payload["i"])
        recorded = (str(payload["q"]), str(payload["s"]), str(payload["u"]), str(payload["e"]))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise PickerCursorContextMismatch("the business cursor is not readable") from error
    if recorded[0] != str(fingerprint) or recorded[1] != str(snapshot):
        raise PickerCursorContextMismatch(
            "the business cursor belongs to another query or snapshot",
        )
    if recorded[2] != str(usage) or recorded[3] != str(task_evidence):
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
    if query.cursor and query.count_mode == "exact":
        # A cursor resumes mid-stream; the remaining matches are not the total.
        raise PickerUnsupportedFilter(
            "cursor pagination supports deferred counting only",
        )
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
    from .training_material_picker_read import _validate_query

    _validate_query(PickerQuery(
        project_id=query.project_id, filters=filters.base,
        sort_order=query.sort_order, count_mode="deferred", page=None,
        page_size=size, include_payload=False, include_annotations=False,
    ))
    return size, page


# ---------------------------------------------------------------------------
# Provider
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
        tasks_path: str | Path | None = None,
    ):
        self.picker = picker
        self.project_path = Path(project_path)
        self.project_id = str(project_id or "")
        if not self.project_id:
            raise ValueError("the business read provider requires an explicit project id")
        bound = str(getattr(picker, "project_id", self.project_id) or "")
        if bound and bound != self.project_id:
            raise PickerProjectMismatch(
                "the picker is bound to another project",
                detail=f"picker={bound} requested={self.project_id}",
            )
        if materials is not None and Path(materials.path).parent != self.project_path:
            raise PickerProjectMismatch("the material repository belongs to another project")
        if annotations is not None and Path(annotations.project_path) != self.project_path:
            raise PickerProjectMismatch("the annotation repository belongs to another project")
        self.materials = materials or MaterialRepository(self.project_path)
        self.annotations = annotations or AnnotationRepository(self.project_path)
        # The Task store is a single central owner: <DATA_DIR>/task_runtime/tasks.sqlite3,
        # never a per-project file. ``project.id`` scoping happens in SQL.
        default_tasks = self.project_path.parent.parent / "task_runtime" / "tasks.sqlite3"
        self.tasks_path = Path(tasks_path) if tasks_path else default_tasks
        if usage is not None:
            usage_path = Path(getattr(usage, "path", self.tasks_path))
            if usage_path != self.tasks_path:
                raise PickerProjectMismatch(
                    "the injected usage owner is not the central Task store",
                    detail=f"usage={usage_path} tasks={self.tasks_path}",
                )
        self.usage = usage or TrainingMaterialUsage(self.tasks_path)

    # -- helpers ---------------------------------------------------------
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

    def _usage_revision(self) -> str:
        try:
            return str(self.usage.read_revision())
        except Exception as error:  # noqa: BLE001 - history boundary
            raise BusinessHistoryUnavailable(
                "the training history revision could not be read", detail=str(error),
            ) from error

    def _task_evidence_digest(self, connection=None) -> str:
        """Identity digest of every Task that can hold an active reservation.

        Only non-terminal statuses affect eligibility (``query_filter`` treats
        exactly these as active), so ``(task_id, status)`` pairs for that bounded
        set prove identity: a task leaving the set, entering it, or changing
        between active statuses always changes the digest, even when per-status
        counts are unchanged. No history rows are loaded and no per-material
        query is issued.
        """
        try:
            database = connection or self._tasks_connection()
            try:
                rows = database.execute(
                    "SELECT task_id, status FROM tasks WHERE status IN "
                    "('QUEUED','RUNNING','CANCEL_REQUESTED','AWAITING_CONFIRMATION') "
                    "ORDER BY task_id"
                ).fetchall()
            finally:
                if connection is None:
                    database.close()
        except sqlite3.Error as error:
            raise BusinessHistoryUnavailable(
                "the Task eligibility evidence could not be read", detail=str(error),
            ) from error
        return hashlib.sha256(
            json.dumps([[str(row["task_id"]), str(row["status"])] for row in rows]).encode("utf-8")
        ).hexdigest()

    def _tasks_connection(self) -> sqlite3.Connection:
        if not self.tasks_path.is_file():
            raise BusinessHistoryUnavailable(
                "the central Task store does not exist", detail=str(self.tasks_path),
            )
        connection = sqlite3.connect(
            f"{self.tasks_path.resolve().as_uri()}?mode=ro", uri=True, timeout=5,
        )
        connection.row_factory = sqlite3.Row
        return connection

    def _picker_context(self) -> Any:
        return self.picker.snapshot_context(self.project_id)

    def _base_query(self, query: BusinessQuery, *, cursor: str | None) -> PickerQuery:
        return PickerQuery(
            project_id=query.project_id, filters=query.filters.base,
            sort_order=query.sort_order, count_mode="deferred", page=None,
            page_size=MAX_PAGE_SIZE, cursor=cursor, include_payload=True,
            include_annotations=False, verify_owner=query.verify_owner,
        )

    def _history_facts(self, query: BusinessQuery, rows: Sequence[Mapping[str, Any]]) -> dict:
        try:
            facts = self.usage.query_filter(
                self.project_id, str(query.filters.algorithm_asset_id or ""), list(rows),
                exclude_used=False, role=query.filters.usage_role,
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
        receipts,
    ) -> list[Mapping[str, Any]]:
        if not contract.get("effective_label_codes"):
            return []
        if not query.verify_owner:
            # A diagnostic read is not a current-owner proof.
            return []
        if receipts is None or not receipts.authoritative or not receipts.owner_equivalent:
            # Uncertified or diagnostic-only reads never prove current eligibility.
            return []
        context_key = task_negative_context(contract)
        valid: list[Mapping[str, Any]] = []
        for receipt in receipts.receipts:
            evidence = dict(receipt.evidence or {})
            image_id = str(evidence.get("image_id") or "")
            row = rows.get(image_id)
            annotation = annotations.get(image_id)
            if row is None or annotation is None:
                continue
            if str(receipt.context_key) != context_key or str(receipt.image_id or "") != image_id:
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
            role_row = _role_row(row, annotation)
            recomputed = str(
                task_negative_identity(role_row, contract).get("receipt_id") or ""
            )
            if recomputed and (
                recomputed != str(receipt.receipt_id)
                or recomputed != str(evidence.get("receipt_id") or "")
            ):
                continue
            valid.append(evidence)
        return valid

    @staticmethod
    def _role_row(
        material: Mapping[str, Any], annotation: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        record = {key: value for key, value in material.items() if key != "payload"}
        if annotation:
            record.update(dict(annotation))
            record["id"] = str(annotation.get("image_id") or material.get("id") or "")
            record["annotation_version"] = int(annotation.get("version") or 0)
            record["annotation_hash"] = str(annotation.get("content_digest") or "")
        return record

    def _evaluate_batch(self, query: BusinessQuery, session, batch: Sequence[PickerMaterial], *, materialize: bool = True):
        filters = query.filters
        ids = [item.id for item in batch]
        # The candidate page already carries the owner payload when available.
        # Reuse it instead of a second per-batch material hydration; fall back to
        # the repository for any item that did not expose a payload.
        material_rows = {
            item.id: dict(item.payload)
            for item in batch
            if isinstance(item.payload, Mapping) and item.payload
        }
        missing_ids = [item.id for item in batch if item.id not in material_rows]
        if missing_ids:
            material_rows.update({
                str(row.get("id")): row for row in self.materials.get_many(missing_ids)
            })
        annotation_rows = self.annotations.get_many(ids)
        pg_annotations = session.annotations(ids) if materialize else None
        contract = self._contract(filters)
        receipts = session.receipts(task_negative_context(contract), ids)
        contract = {
            **contract,
            "task_negative_confirmations": self._valid_receipts(
                query, contract, material_rows, annotation_rows, receipts,
            ),
        }
        facts = self._history_facts(query, list(material_rows.values()))
        by_id = facts.get("by_image_id") or {}
        receipt_ids = {str(receipt.get("receipt_id") or "") for receipt in
                       contract["task_negative_confirmations"]}
        unproven_legacy = set(pg_annotations.unproven_legacy_ids) if pg_annotations is not None else set()
        items: list[BusinessMaterial] = []
        matched = 0
        for item in batch:
            material = material_rows.get(item.id)
            if material is None:
                continue
            annotation = annotation_rows.get(item.id)
            fact = by_id.get(item.id) or {}
            state = str(fact.get("state") or "unknown")
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
            # Formal selection always applies the existing history/Test exclusion;
            # only browsing may show used or protected rows. An explicit
            # usage_state/history_scope narrows the population but never bypasses
            # the exclusion (the existing picker does the same).
            if filters.usage_role == "test":
                excluded = state in {"used", "possible"}
            elif filters.history_policy == "include_history":
                excluded = bool(fact.get("benchmark_protected")) or state == "test_reserved"
            else:
                excluded = state in {"used", "possible", "test_reserved"}
            if excluded and not filters.browse_only:
                continue
            role_row = _role_row(material, annotation)
            try:
                decision = training_material_role(role_row, contract)
            except ValueError as error:
                raise BusinessReadError(
                    "a material role could not be determined", detail=str(error),
                ) from error
            sample_role = str(decision.get("role") or "pending_review")
            if sample_role == "pending_review" and task_negative_confirmable(role_row, contract):
                # Confirmable, not confirmed: a preview role, never positive.
                sample_role = "pending_negative"
            if filters.sample_role and sample_role != filters.sample_role:
                continue
            matched += 1
            if not materialize:
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
                identity = str(task_negative_identity(role_row, contract).get("receipt_id") or "")
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
        return items if materialize else matched

    # -- read session ----------------------------------------------------
    @contextmanager
    def read_session(self, query: BusinessQuery) -> Iterator["_BusinessSession"]:
        """One business read session with a single, exclusively borrowed Task read.

        The central Task store is opened in ONE read-only transaction and every
        batch reuses it. A second overlapping session on the same provider is
        rejected (the borrow is exclusive); release happens on normal and error
        exit. The final current-version recheck uses ONE new Task transaction.
        """
        self._require_project(query.project_id)
        if not query.verify_owner:
            raise PickerUnsupportedFilter(
                "formal business sessions require current-owner verification",
            )
        _validate_business_query(replace(query, page=None, count_mode="deferred"))
        tasks = self._tasks_connection()
        tasks.execute("BEGIN")
        try:
            token = self._borrow_tasks(tasks)
        except BusinessReadError:
            tasks.close()
            raise

        def end_task_transaction() -> None:
            self._release_tasks(token)
            try:
                tasks.execute("COMMIT")
            except sqlite3.Error:
                pass
            finally:
                tasks.close()

        closed = {"value": False}

        def close_once() -> None:
            if not closed["value"]:
                closed["value"] = True
                end_task_transaction()

        inner_context = None
        entered = False
        try:
            if hasattr(self.picker, "read_session"):
                inner_context = self.picker.read_session(
                    query.project_id, verify_owner=query.verify_owner,
                )
                inner = inner_context.__enter__()
                entered = True
                picker_snapshot = inner.snapshot
                session = _PostgresSession(
                    self, query, inner, picker_snapshot,
                    self._usage_revision(), self._task_evidence_digest(tasks),
                )
            else:
                picker_snapshot = self._picker_context()
                session = _SQLiteSession(
                    self, query, picker_snapshot,
                    self._usage_revision(), self._task_evidence_digest(tasks),
                )
            session._picker_snapshot = picker_snapshot
            yield session
            close_once()
            session.verify()
        finally:
            close_once()
            if entered and inner_context is not None:
                inner_context.__exit__(*sys.exc_info())

    def _borrow_tasks(self, connection):
        """Atomic exclusive borrow: check, token and connection under one lock."""
        lock = getattr(self.usage, "_borrow_lock", None)
        if lock is None:
            raise BusinessReadError("the usage owner has no borrow lock")
        with lock:
            if getattr(self.usage, "_borrowed_connection", None) is not None:
                raise BusinessReadError(
                    "another business read session is already using the Task store",
                )
            token = object()
            self.usage._borrowed_connection = connection
            self.usage._borrowed_token = token
            return token

    def _release_tasks(self, token) -> None:
        lock = getattr(self.usage, "_borrow_lock", None)
        if lock is None:
            return
        with lock:
            if getattr(self.usage, "_borrowed_token", None) is token:
                self.usage._borrowed_connection = None
                self.usage._borrowed_token = None

    def _verify_current(self) -> tuple[str, str]:
        """One new Task read transaction: revision + active Task digest together."""
        connection = self._tasks_connection()
        try:
            connection.execute("BEGIN")
            return self.usage.read_revision(connection), self._task_evidence_digest(connection)
        except sqlite3.Error as error:
            raise BusinessHistoryUnavailable(
                "the current Task version could not be re-read", detail=str(error),
            ) from error
        finally:
            try:
                connection.execute("COMMIT")
            finally:
                connection.close()

    def iter_candidates(
        self, query: BusinessQuery, *, batch_size: int = MAX_PAGE_SIZE,
    ) -> Iterator[tuple[BusinessMaterial, ...]]:
        if query.page is not None:
            raise PickerUnsupportedFilter("candidate streaming does not support page mode")
        if not query.verify_owner:
            raise PickerUnsupportedFilter(
                "formal candidate streaming requires current-owner verification",
            )
        fingerprint = _business_fingerprint(query)
        with self.read_session(query) as session:
            base_cursor = None
            if query.cursor:
                start = _decode_business_cursor(
                    query.cursor, fingerprint=fingerprint,
                    snapshot=session.snapshot_id, usage=session.usage_revision,
                    task_evidence=session.task_evidence,
                )
                base_cursor = _picker_cursor_for(session, query, start)
            yield from session.batches(batch_size=batch_size, cursor=base_cursor)

    def read_page(self, query: BusinessQuery) -> BusinessPage:
        self._require_project(query.project_id)
        if not query.verify_owner:
            raise PickerUnsupportedFilter(
                "formal business reads require current-owner verification",
            )
        size, page = _validate_business_query(query)
        page_number = 1 if page is None else page
        fingerprint = _business_fingerprint(query)
        with self.read_session(query) as session:
            skip = 0
            start = None
            if query.cursor:
                start = _decode_business_cursor(
                    query.cursor, fingerprint=fingerprint,
                    snapshot=session.snapshot_id, usage=session.usage_revision,
                    task_evidence=session.task_evidence,
                )
            elif page_number > 1:
                skip = (page_number - 1) * size
            if start is not None:
                base_cursor = _picker_cursor_for(session, query, start)
            else:
                base_cursor = None
            items: list[BusinessMaterial] = []
            total: int | None = None
            matched = 0
            skipped = 0
            last: BusinessMaterial | None = None
            has_more = False
            resume_exact = False
            for batch in session.batches(cursor=base_cursor):
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
                    else:
                        # Only a stable (created_at, id) cursor can resume the
                        # exact count. A legacy row without created_at must keep
                        # the original full materialization path, never silently
                        # drop the remainder.
                        if last is not None and last.material.created_at:
                            resume_exact = True
                            break
                        continue
                if has_more or resume_exact:
                    break
            if query.count_mode == "exact" and last is not None and last.material.created_at:
                matched = skipped + len(items)
                count_cursor = _picker_cursor_for(
                    session, query,
                    (last.material.created_at, last.material.id),
                )
                for count in session.batches(
                    cursor=count_cursor, materialize=False,
                ):
                    matched += int(count)
                has_more = matched > skipped + len(items)
            elif query.count_mode == "exact":
                has_more = matched > skipped + len(items)
            if query.count_mode == "exact":
                total = matched
            # ``session.verify()`` runs on context exit and fails closed if the
            # owner, history or Task status evidence changed -- even for an early
            # deferred stop.
            snapshot = session.snapshot()
        next_cursor = None
        if has_more and last is not None and last.material.created_at:
            next_cursor = _encode_business_cursor(
                last.material.created_at, last.material.id,
                fingerprint=fingerprint, snapshot=session.snapshot_id,
                usage=session.usage_revision, task_evidence=session.task_evidence,
            )
        return BusinessPage(
            items=tuple(items), total=total, has_more=has_more,
            next_cursor=next_cursor, page=page_number, page_size=size,
            count_mode=query.count_mode, snapshot=snapshot,
        )


class _BusinessSession:
    """Shared candidate/evaluate/verify logic for both pickers."""

    def __init__(self, provider, query, token, usage_revision, task_evidence,
                 owner_equivalent: bool = False):
        self.provider = provider
        self.query = query
        self.snapshot_id = token
        self.usage_revision = usage_revision
        self.task_evidence = task_evidence
        self._owner_equivalent = owner_equivalent
        self._picker_snapshot = None

    # -- recording -------------------------------------------------------
    @property
    def owner_equivalent(self) -> bool:
        return bool(self._owner_equivalent)

    def observe(self, image_id: str, fact: Mapping[str, Any]) -> None:
        # No per-material fact accumulation and no per-material Task read: the
        # session-level history/Task revisions below are the consistency proof.
        return None

    # -- verification ----------------------------------------------------
    def verify(self) -> None:
        """Bounded final proof on a NEW connection: no candidate re-read."""
        current_revision, current_task_evidence = self.provider._verify_current()
        if current_revision != self.usage_revision:
            raise BusinessHistoryChanged(
                "the training history changed during the business read",
            )
        if current_task_evidence != self.task_evidence:
            raise BusinessHistoryChanged(
                "the active Task eligibility evidence changed during the business read",
            )
        if self.provider._picker_context().snapshot_id != self.snapshot_id:
            raise PickerSnapshotStale(
                "the picker snapshot changed during the business read",
            )

    def snapshot(self) -> BusinessSnapshot:
        context = self._picker_snapshot
        return BusinessSnapshot(
            project_id=self.provider.project_id,
            source=str(getattr(self.provider.picker, "name", "")),
            picker_snapshot_id=self.snapshot_id,
            owner_equivalent=self._owner_equivalent,
            usage_revision=self.usage_revision,
            task_evidence=self.task_evidence,
            count_mode=self.query.count_mode,
            read_identity=str(getattr(context, "read_identity", "") or ""),
        )


class _PostgresSession(_BusinessSession):
    def __init__(self, provider, query, inner, picker_snapshot, usage_revision, task_evidence):
        super().__init__(
            provider, query, picker_snapshot.snapshot_id, usage_revision, task_evidence,
            owner_equivalent=bool(getattr(picker_snapshot, "owner_equivalent", False)),
        )
        self.inner = inner
        self._picker_snapshot = picker_snapshot

    def annotations(self, ids):
        return self.inner.get_annotations(ids)

    def receipts(self, context_key, ids):
        return self.inner.receipts(context_key, ids)

    def batches(self, *, batch_size=MAX_PAGE_SIZE, cursor=None, materialize=True):
        base = self.provider._base_query(self.query, cursor=cursor)
        for batch in self.inner.candidates(base, batch_size=batch_size):
            yield self.provider._evaluate_batch(
                self.query, self, batch, materialize=materialize
            )

    def verify(self) -> None:
        # The P1 session verifies the Owner on exit; re-check the business facts
        # and the picker snapshot before publishing anything.
        super().verify()


class _SQLiteSession(_BusinessSession):
    def __init__(self, provider, query, picker_snapshot, usage_revision, task_evidence):
        super().__init__(
            provider, query, picker_snapshot.snapshot_id, usage_revision, task_evidence,
            # The SQLite picker re-reads the owner; the token comparison in
            # verify() is what proves current equivalence.
            owner_equivalent=bool(query.verify_owner),
        )
        self._picker_snapshot = picker_snapshot

    def annotations(self, ids):
        return self.provider.picker.get_annotations(self.provider.project_id, ids)

    def receipts(self, context_key, ids):
        return self.provider.picker.get_task_negative_receipts(
            self.provider.project_id, context_key, ids,
        )

    def batches(self, *, batch_size=MAX_PAGE_SIZE, cursor=None, materialize=True):
        base = self.provider._base_query(self.query, cursor=cursor)
        for batch in self.provider.picker.iter_candidates(base, batch_size=batch_size):
            yield self.provider._evaluate_batch(
                self.query, self, batch, materialize=materialize
            )


def _role_row(material: Mapping[str, Any], annotation: Mapping[str, Any] | None) -> dict[str, Any]:
    return BusinessReadProvider._role_row(material, annotation)


def _picker_cursor_for(session, query: BusinessQuery, start: tuple[str, str]) -> str:
    from .training_material_picker_read import encode_picker_cursor

    base = session.provider._base_query(query, cursor=None)
    from .training_material_picker_read import _query_fingerprint

    return encode_picker_cursor(
        start[0], start[1], fingerprint=_query_fingerprint(base),
        snapshot=session.snapshot_id,
    )


def selection_digest(image_ids: Sequence[str]) -> str:
    """The existing frozen-selection digest: sorted ids, each followed by NUL."""
    digest = hashlib.sha256()
    for image_id in sorted({str(value) for value in image_ids}):
        digest.update((image_id + "\0").encode("utf-8"))
    return digest.hexdigest()


def compare_candidate_sets(
    first: BusinessReadProvider, second: BusinessReadProvider, query: BusinessQuery,
    *, limit: int = MAX_COMPARISON_IDS,
) -> dict[str, Any]:
    """Read-only equivalence over the same business query.

    Both streams must be fully consumed, both sessions must verify (owner,
    history, active Task evidence), and both must observe the same owner
    revision vector, history revision and Task evidence; only then is a
    count/digest published.
    """
    first_ids, first_meta = _collect(first, query, limit)
    second_ids, second_meta = _collect(second, query, limit)
    if not (first_meta["owner_equivalent"] and second_meta["owner_equivalent"]):
        raise BusinessReadError("a candidate set was not proven current")
    if first_meta["owner_vector"] != second_meta["owner_vector"]:
        raise BusinessCandidateMismatch(
            "the two reads observed different owner revision vectors",
        )
    if (first_meta["usage_revision"] != second_meta["usage_revision"]
            or first_meta["task_evidence"] != second_meta["task_evidence"]):
        raise BusinessHistoryChanged(
            "the two reads observed different Task history evidence",
        )
    if first_ids != second_ids:
        raise BusinessCandidateMismatch(
            "candidate sets differ",
            detail=f"first={len(first_ids)} second={len(second_ids)}",
        )
    return {
        "count": len(first_ids),
        "digest": selection_digest(first_ids),
        "ids": first_ids,
        "owner_vector": first_meta["owner_vector"],
        "usage_revision": first_meta["usage_revision"],
        "task_evidence": first_meta["task_evidence"],
    }


def _collect(provider: BusinessReadProvider, query: BusinessQuery, limit: int):
    if not query.verify_owner:
        raise PickerUnsupportedFilter(
            "freeze comparison requires current-owner verification",
        )
    ids: list[str] = []
    with provider.read_session(query) as session:
        meta = {
            "owner_equivalent": bool(session.owner_equivalent),
            "owner_vector": _canonical_vector(
                getattr(session._picker_snapshot, "revision_vector", None)
            ),
            "usage_revision": session.usage_revision,
            "task_evidence": session.task_evidence,
        }
        for batch in session.batches():
            for item in batch:
                ids.append(item.material.id)
                if len(ids) > limit:
                    raise PickerUnsupportedFilter(
                        f"candidate comparison is limited to {limit} materials",
                    )
        session.verify()
    return ids, meta


def _canonical_vector(vector: Mapping[str, Any] | None) -> str:
    """Project only the versions both sides can prove (PG/SQLite share these)."""
    value = dict(vector or {})

    def stream(name: str) -> Mapping[str, Any]:
        item = value.get(name)
        return item if isinstance(item, Mapping) else {}

    proof = {
        "materials.revision": stream("materials").get("revision"),
        "annotations.revision": stream("annotations").get("revision"),
        "negative_pool.revision": stream("negative_pool").get("revision"),
        "materials_evidence.generation": stream("materials_evidence").get("generation"),
        "materials_evidence.structure_generation": stream("materials_evidence").get("structure_generation"),
        "annotations_evidence.generation": stream("annotations_evidence").get("generation"),
        "annotations_evidence.structure_generation": stream("annotations_evidence").get("structure_generation"),
        "negative_confirmation.generation": stream("negative_confirmation").get("generation"),
        "negative_confirmation.structure_generation": stream("negative_confirmation").get("structure_generation"),
    }
    return json.dumps(proof, ensure_ascii=False, sort_keys=True)
