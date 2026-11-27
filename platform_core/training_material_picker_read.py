"""U3-P1 Picker read providers: one read contract, two implementations.

The SQLite owners stay the single business authority. ``SQLitePickerReadProvider``
is the semantic baseline: it delegates to the existing picker query engine
(``training_material_picker_api._gt_material_filter_page`` / ``_picker_filter_sql``)
instead of re-implementing SQLite filtering. ``PostgresPickerReadProvider`` runs
independent, project-scoped PostgreSQL queries over the ``w3_material_gt`` read
projection inside ONE ``REPEATABLE READ, READ ONLY`` transaction, and proves that
the published snapshot still matches the current SQLite owner versions before it
returns a page.

Scope of P1 (see docs/architecture/U3_PICKER_P1_READ_PROVIDER_20261127.md):

* supported: material status ``processed``, filename ASCII search, storage
  sources, created time range, labels ANY/ALL, formal-GT presence, annotation
  state, explicit image ids, negative-pool member/category/algorithm filters,
  stable ``(created_at, id)`` ordering, page and keyset cursor pagination,
  exact/deferred counts, bounded batch reads, pool relations, task-level negative
  receipts, and READY/owner-version gating;
* NOT supported here: training history, sample roles, dataset/split filters,
  legacy-GT hydration of unprojected JSON, and any write.  These raise explicit
  errors or return explicit "unproven" markers; nothing is silently ignored.
"""
from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
from contextlib import closing, contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence

SCHEMA_NAME = "w3_material_gt"
DEFAULT_PAGE_SIZE = 60
MAX_PAGE_SIZE = 120
MAX_CANDIDATE_BATCH = 500
MAX_BATCH_IDS = 5000

#: SQLite ``COLLATE NOCASE`` folds ASCII A-Z only. These two equal-length strings
#: reproduce that fold independently of the PostgreSQL cluster locale.
_ASCII_UPPER = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_ASCII_LOWER = "abcdefghijklmnopqrstuvwxyz"

EVIDENCE_TABLES = {
    "materials": (
        "material_migrations", "material_storage_audit", "material_retirements",
        "material_cleanup_deferred", "material_assignment_receipts",
        "negative_pool_operations",
    ),
    "annotations": (
        "annotation_delete_backup", "annotation_negative_reviews",
        "annotation_candidate_commits", "task_negative_confirmations",
    ),
}


# ---------------------------------------------------------------------------
# Errors: one stable code per failure class; never a silent empty result.
# ---------------------------------------------------------------------------
class PickerReadError(RuntimeError):
    code = "PICKER_READ_FAILED"

    def __init__(self, message: str, *, detail: str = ""):
        super().__init__(message)
        self.detail = str(detail or "")


class PickerProjectionUnavailable(PickerReadError):
    code = "PICKER_PROJECTION_UNAVAILABLE"


class PickerQueryFailed(PickerReadError):
    code = "PICKER_QUERY_FAILED"


class PickerSnapshotMissing(PickerReadError):
    code = "PICKER_SNAPSHOT_MISSING"


class PickerSnapshotNotReady(PickerReadError):
    code = "PICKER_SNAPSHOT_NOT_READY"


class PickerSnapshotStale(PickerReadError):
    code = "PICKER_SNAPSHOT_STALE"


class PickerOwnerUnverifiable(PickerReadError):
    code = "PICKER_OWNER_UNVERIFIABLE"


class PickerCursorContextMismatch(PickerReadError):
    code = "PICKER_CURSOR_CONTEXT_MISMATCH"


class PickerUnsupportedFilter(PickerReadError):
    code = "PICKER_FILTER_UNSUPPORTED"


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PickerFilter:
    """P1 base filters; defaults are exactly the existing picker page contract."""

    processing_status: str = "processed"
    query: str = ""
    labels: tuple[str, ...] = ()
    label_mode: str = "any"
    annotation_state: str = ""
    require_ground_truth: bool = False
    storage_source_ids: tuple[str, ...] = ()
    created_from: str = ""
    created_to: str = ""
    image_ids: tuple[str, ...] | None = None
    negative_pool_only: bool = False
    negative_category_ids: tuple[str, ...] = ()
    algorithm_asset_id: str = ""


@dataclass(frozen=True)
class PickerQuery:
    project_id: str
    filters: PickerFilter = field(default_factory=PickerFilter)
    sort_order: str = "oldest"
    count_mode: str = "exact"
    page: int | None = None
    page_size: int = DEFAULT_PAGE_SIZE
    cursor: str | None = None
    include_payload: bool = False
    include_annotations: bool = True
    #: Current-owner equivalence is required unless the caller explicitly reads
    #: the imported snapshot only (diagnostics / snapshot-internal comparisons).
    verify_owner: bool = True


@dataclass(frozen=True)
class PickerMaterial:
    id: str
    filename: str
    storage_source_id: str
    processing_status: str
    content_sha256: str
    size_bytes: int | None
    box_count: int | None
    annotated: bool | None
    created_at: str
    updated_at: str
    payload: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class PickerAnnotation:
    image_id: str
    annotation_state: str
    version: int
    content_digest: str
    box_count: int
    scope_labels: tuple[str, ...]
    legacy_unproven: bool = False


@dataclass(frozen=True)
class PickerAnnotations:
    annotations: Mapping[str, PickerAnnotation]
    missing_ids: tuple[str, ...] = ()
    #: References with ``source_kind='legacy'`` but no projected formal-GT row:
    #: their full content cannot be proven from the PostgreSQL projection.
    unproven_legacy_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class PickerPoolRelation:
    image_id: str
    member: bool
    joined_at: str | None
    category_ids: tuple[str, ...]
    algorithm_ids: tuple[str, ...]


@dataclass(frozen=True)
class PickerNegativeReceipts:
    context_key: str
    generation: int
    #: ``False`` means the source table is absent from the current owner snapshot:
    #: retained PostgreSQL rows are history, not current confirmations.
    authoritative: bool
    receipts: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class PickerSnapshotInfo:
    project_id: str
    source: str
    status: str
    snapshot_id: str | None
    revision_vector: Mapping[str, Any]
    owner_equivalent: bool
    isolation: str = ""
    read_only: bool = False
    read_identity: str = ""


@dataclass(frozen=True)
class PickerPage:
    items: tuple[PickerMaterial, ...]
    annotations: PickerAnnotations
    total: int | None
    has_more: bool
    next_cursor: str | None
    page: int | None
    page_size: int
    count_mode: str
    snapshot: PickerSnapshotInfo


@dataclass(frozen=True)
class OwnerRevisionVector:
    """Versions the SQLite owner can prove without exporting any row."""

    material_revision: int
    annotation_revision: int
    negative_pool_revision: int
    materials_evidence_generation: int
    annotations_evidence_generation: int
    negative_confirmation_generation: int
    materials_structure_generation: int
    annotations_structure_generation: int
    materials_tables: tuple[str, ...]
    annotations_tables: tuple[str, ...]
    materials_structure_certified: bool
    annotations_structure_certified: bool


# ---------------------------------------------------------------------------
# Owner version source (read-only, never initializes or writes the owners)
# ---------------------------------------------------------------------------
def _read_meta(database: sqlite3.Connection, table: str, key: str) -> int | None:
    row = database.execute(
        f"SELECT value FROM {table} WHERE key=?", (str(key),)
    ).fetchone()
    if row is None:
        return None
    try:
        return int(row[0])
    except (TypeError, ValueError):
        return None


def _table_presence(database: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in database.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }


def _recorded_structure(database: sqlite3.Connection, table: str, key: str) -> list[str] | None:
    row = database.execute(
        f"SELECT value FROM {table} WHERE key=?", (str(key),)
    ).fetchone()
    if row is None:
        return None
    try:
        value = json.loads(row[0])
    except (TypeError, ValueError):
        return None
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return None
    return sorted(value)


@dataclass(frozen=True)
class _StoreEvidence:
    generation: int
    structure_generation: int
    tables: tuple[str, ...]
    certified: bool


def _read_store_evidence(
    path: Path, meta_table: str, tables: Sequence[str], *, include_generation: bool = True,
) -> _StoreEvidence:
    with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as database:
        database.row_factory = sqlite3.Row
        present = _table_presence(database)
        generation = _read_meta(database, meta_table, "evidence_generation")
        structure_generation = _read_meta(database, meta_table, "evidence_structure_generation")
        recorded = _recorded_structure(database, meta_table, "evidence_structure")
    observed = tuple(sorted(table for table in tables if table in present))
    certified = recorded is not None and tuple(recorded) == observed
    return _StoreEvidence(
        generation=int(generation or 0),
        structure_generation=int(structure_generation or 0),
        tables=observed,
        certified=bool(certified),
    )


def sqlite_owner_revision_source(project_path: str | Path) -> Callable[[], OwnerRevisionVector]:
    """Build a read-only Owner version source for current-equivalence checks.

    Only revision/generation counters and evidence-table presence are read: no
    row export, no content digest, no evidence-table count, and no write.
    """
    project = Path(project_path)

    def read() -> OwnerRevisionVector:
        materials_db = project / "materials.sqlite3"
        annotations_db = project / "annotations.sqlite3"
        if not materials_db.is_file() or not annotations_db.is_file():
            raise PickerOwnerUnverifiable(
                "the SQLite owners are not readable",
                detail=f"project={project.name}",
            )
        try:
            with closing(sqlite3.connect(f"{materials_db.resolve().as_uri()}?mode=ro", uri=True)) as database:
                database.row_factory = sqlite3.Row
                material_revision = _read_meta(database, "material_meta", "revision")
                pool_present = "negative_pool_meta" in _table_presence(database)
                pool_revision = (
                    int(database.execute(
                        "SELECT revision FROM negative_pool_meta WHERE id=1"
                    ).fetchone()[0])
                    if pool_present else 0
                )
            materials_evidence = _read_store_evidence(
                materials_db, "material_meta", EVIDENCE_TABLES["materials"],
            )
            with closing(sqlite3.connect(f"{annotations_db.resolve().as_uri()}?mode=ro", uri=True)) as database:
                database.row_factory = sqlite3.Row
                annotation_revision = _read_meta(database, "annotation_meta", "revision")
                confirmation_generation = _read_meta(
                    database, "annotation_meta", "task_negative_confirmation_generation",
                )
            annotations_evidence = _read_store_evidence(
                annotations_db, "annotation_meta", EVIDENCE_TABLES["annotations"],
            )
        except PickerReadError:
            raise
        except sqlite3.Error as error:
            raise PickerOwnerUnverifiable(
                "the SQLite owner versions could not be read",
                detail=str(error),
            ) from error
        if material_revision is None or annotation_revision is None or pool_revision is None:
            raise PickerOwnerUnverifiable(
                "the SQLite owner revision markers are missing",
                detail=f"materials={material_revision} annotations={annotation_revision} pool={pool_revision}",
            )
        return OwnerRevisionVector(
            material_revision=int(material_revision),
            annotation_revision=int(annotation_revision),
            negative_pool_revision=int(pool_revision),
            materials_evidence_generation=materials_evidence.generation,
            annotations_evidence_generation=annotations_evidence.generation,
            negative_confirmation_generation=int(confirmation_generation or 0),
            materials_structure_generation=materials_evidence.structure_generation,
            annotations_structure_generation=annotations_evidence.structure_generation,
            materials_tables=materials_evidence.tables,
            annotations_tables=annotations_evidence.tables,
            materials_structure_certified=materials_evidence.certified,
            annotations_structure_certified=annotations_evidence.certified,
        )

    return read


# ---------------------------------------------------------------------------
# Cursor: bound to the query fingerprint and the snapshot identity
# ---------------------------------------------------------------------------
def _query_fingerprint(query: PickerQuery) -> str:
    filters = query.filters
    body = {
        "project": query.project_id,
        "processing_status": filters.processing_status,
        "query": filters.query,
        "labels": sorted(set(filters.labels)),
        "label_mode": filters.label_mode,
        "annotation_state": filters.annotation_state,
        "require_ground_truth": filters.require_ground_truth,
        "sources": sorted(set(filters.storage_source_ids)),
        "created_from": filters.created_from,
        "created_to": filters.created_to,
        "image_ids": None if filters.image_ids is None else sorted(set(filters.image_ids)),
        "negative_pool_only": filters.negative_pool_only,
        "negative_categories": sorted(set(filters.negative_category_ids)),
        "algorithm_asset_id": filters.algorithm_asset_id,
        "sort_order": query.sort_order,
    }
    return hashlib.sha256(
        json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:32]


def encode_picker_cursor(created_at: str, image_id: str, *, fingerprint: str, snapshot: str) -> str:
    body = json.dumps(
        {"v": 1, "t": str(created_at), "i": str(image_id), "q": fingerprint, "s": snapshot},
        ensure_ascii=False, sort_keys=True,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(body).decode("ascii").rstrip("=")


def decode_picker_cursor(
    cursor: str, *, fingerprint: str, snapshot: str,
) -> tuple[str, str]:
    try:
        padded = str(cursor) + "=" * (-len(str(cursor)) % 4)
        body = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except (ValueError, TypeError, json.JSONDecodeError) as error:
        raise PickerCursorContextMismatch(
            "the cursor is not a valid P1 picker cursor", detail=str(error),
        ) from error
    if not isinstance(body, dict) or body.get("v") != 1:
        raise PickerCursorContextMismatch("the cursor version is not supported")
    if str(body.get("q") or "") != fingerprint:
        raise PickerCursorContextMismatch(
            "the cursor belongs to different query filters",
        )
    if str(body.get("s") or "") != snapshot:
        raise PickerCursorContextMismatch(
            "the cursor belongs to a different snapshot",
            detail=f"cursor={body.get('s')} current={snapshot}",
        )
    created_at, image_id = body.get("t"), body.get("i")
    if not isinstance(created_at, str) or not created_at or not isinstance(image_id, str) or not image_id:
        raise PickerCursorContextMismatch("the cursor has no stable position")
    return created_at, image_id


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def _normalize_ids(values: Sequence[str] | None) -> list[str] | None:
    if values is None:
        return None
    return list(dict.fromkeys(str(value) for value in values if str(value or "").strip()))


def _normalize_labels(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(
        str(value or "").strip() for value in values if str(value or "").strip()
    ))


def _validate_query(query: PickerQuery) -> tuple[int, int | None]:
    if query.sort_order not in {"oldest", "newest"}:
        raise PickerUnsupportedFilter("sort_order must be oldest or newest")
    if query.count_mode not in {"exact", "deferred"}:
        raise PickerUnsupportedFilter("count_mode must be exact or deferred")
    if query.page is not None and query.cursor:
        raise PickerUnsupportedFilter("page and cursor cannot be used together")
    try:
        size = int(query.page_size)
    except (TypeError, ValueError) as error:
        raise PickerUnsupportedFilter("page_size must be an integer") from error
    if not 1 <= size <= MAX_PAGE_SIZE:
        raise PickerUnsupportedFilter(
            f"page_size must be between 1 and {MAX_PAGE_SIZE}",
        )
    if query.filters.processing_status != "processed":
        # The existing picker page contract filters ``processing_status='processed'``.
        raise PickerUnsupportedFilter(
            "P1 picker reads support processing_status='processed' only",
            detail=str(query.filters.processing_status),
        )
    if query.filters.label_mode not in {"any", "all"}:
        raise PickerUnsupportedFilter("label_mode must be any or all")
    state = str(query.filters.annotation_state or "")
    if state and state not in {"annotated", "confirmed_empty", "unannotated"}:
        raise PickerUnsupportedFilter("invalid annotation_state", detail=state)
    page = None
    if query.page is not None:
        try:
            page = int(query.page)
        except (TypeError, ValueError) as error:
            raise PickerUnsupportedFilter("page must be an integer") from error
        if page < 1:
            raise PickerUnsupportedFilter("page must be a positive integer")
    return size, page


def _normalize_created_to(value: str) -> str:
    text = str(value or "").strip()
    if len(text) == 10:
        return text + "T23:59:59.999999+00:00"
    return text


# ---------------------------------------------------------------------------
# Provider contract
# ---------------------------------------------------------------------------
class PickerReadProvider:
    """Internal read contract shared by the SQLite baseline and PostgreSQL."""

    name = "picker-read"

    def read_page(self, query: PickerQuery) -> PickerPage:  # pragma: no cover - contract
        raise NotImplementedError

    def iter_candidates(
        self, query: PickerQuery, *, batch_size: int = 500,
    ) -> Iterator[tuple[PickerMaterial, ...]]:  # pragma: no cover - contract
        raise NotImplementedError

    def get_many(self, project_id: str, image_ids: Sequence[str]) -> dict[str, PickerMaterial]:
        raise NotImplementedError

    def get_annotations(self, project_id: str, image_ids: Sequence[str]) -> PickerAnnotations:
        raise NotImplementedError

    def get_pool_relations(self, project_id: str, image_ids: Sequence[str]) -> dict[str, PickerPoolRelation]:
        raise NotImplementedError

    def get_task_negative_receipts(
        self, project_id: str, context_key: str, image_ids: Sequence[str] | None = None,
    ) -> PickerNegativeReceipts:
        raise NotImplementedError

    def revision_vector(self, project_id: str) -> Mapping[str, Any]:
        raise NotImplementedError

    def snapshot_context(self, project_id: str) -> PickerSnapshotInfo:
        raise NotImplementedError

# ---------------------------------------------------------------------------
# SQLite baseline provider: wraps the existing picker query engine
# ---------------------------------------------------------------------------
class SQLitePickerReadProvider(PickerReadProvider):
    """Semantic baseline; delegates to the existing SQLite picker SQL engine."""

    name = "sqlite-owner"

    def __init__(self, project_path: str | Path, *, repository=None, annotations=None):
        from .annotation_repository import AnnotationRepository
        from .material_repository import MaterialRepository

        self.project_path = Path(project_path)
        self.repository = repository or MaterialRepository(self.project_path)
        self.annotations = annotations or AnnotationRepository(self.project_path)
        self._owner = sqlite_owner_revision_source(self.project_path)

    # -- helpers ---------------------------------------------------------
    @staticmethod
    def _filter_body(filters: PickerFilter) -> dict[str, Any]:
        body: dict[str, Any] = {
            "label_mode": filters.label_mode,
            "annotation_state": filters.annotation_state,
            "require_ground_truth": bool(filters.require_ground_truth),
            "storage_source_ids": list(filters.storage_source_ids),
            "created_from": filters.created_from,
            "created_to": filters.created_to,
            "negative_pool_only": bool(filters.negative_pool_only),
            "negative_category_ids": list(filters.negative_category_ids),
            "algorithm_asset_id": filters.algorithm_asset_id,
            "browse_only": True,
        }
        ids = _normalize_ids(filters.image_ids)
        if ids is not None:
            body["image_ids"] = ids
        return body

    @staticmethod
    def _snapshot_token(vector: Mapping[str, Any]) -> str:
        return "sqlite:" + hashlib.sha256(
            json.dumps(vector, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:32]

    @staticmethod
    def _vector_dict(vector: OwnerRevisionVector) -> dict[str, Any]:
        return {
            "materials": {"revision": vector.material_revision},
            "annotations": {"revision": vector.annotation_revision},
            "negative_pool": {"revision": vector.negative_pool_revision},
            "materials_evidence": {
                "generation": vector.materials_evidence_generation,
                "structure_generation": vector.materials_structure_generation,
                "tables": list(vector.materials_tables),
                "structure_certified": vector.materials_structure_certified,
            },
            "annotations_evidence": {
                "generation": vector.annotations_evidence_generation,
                "structure_generation": vector.annotations_structure_generation,
                "tables": list(vector.annotations_tables),
                "structure_certified": vector.annotations_structure_certified,
            },
            "negative_confirmation": {
                "generation": vector.negative_confirmation_generation,
            },
        }

    @staticmethod
    def _material_from_payload(payload: Mapping[str, Any]) -> PickerMaterial:
        return PickerMaterial(
            id=str(payload.get("id") or ""),
            filename=str(payload.get("filename") or ""),
            storage_source_id=str(payload.get("storage_source_id") or ""),
            processing_status=str(payload.get("processing_status") or ""),
            content_sha256=str(payload.get("content_sha256") or ""),
            size_bytes=payload.get("size_bytes"),
            box_count=payload.get("box_count"),
            annotated=payload.get("annotated"),
            created_at=str(payload.get("created_at") or ""),
            updated_at=str(payload.get("updated_at") or ""),
            payload=payload,
        )

    @staticmethod
    def _is_synthesized_empty(record: Mapping[str, Any]) -> bool:
        """``AnnotationRepository.get_many`` synthesizes an empty legacy record for
        ids without a formal GT row (version 0, no digest, no boxes and no scope).
        The P1 contract reports such ids as missing instead of inventing GT.
        """
        return (
            int(record.get("version") or 0) == 0
            and not str(record.get("content_digest") or "")
            and not (record.get("boxes") or [])
            and not (record.get("annotation_scope") or [])
        )

    def _annotation_dto(self, project_id: str, image_ids: Sequence[str]) -> PickerAnnotations:
        ids = [str(value) for value in image_ids if str(value)]
        records = self.annotations.get_many(ids) if ids else {}
        annotations: dict[str, PickerAnnotation] = {}
        missing: list[str] = []
        for image_id in ids:
            record = records.get(image_id)
            if record is None or self._is_synthesized_empty(record):
                missing.append(image_id)
                continue
            boxes = record.get("boxes") or []
            scope = record.get("annotation_scope") or []
            annotations[image_id] = PickerAnnotation(
                image_id=image_id,
                annotation_state=str(record.get("annotation_state") or "unannotated"),
                version=int(record.get("version") or 0),
                content_digest=str(record.get("content_digest") or ""),
                box_count=len(boxes),
                scope_labels=tuple(str(value) for value in scope),
                legacy_unproven=False,
            )
        return PickerAnnotations(
            annotations=annotations, missing_ids=tuple(missing), unproven_legacy_ids=(),
        )

    # -- contract --------------------------------------------------------
    def read_page(self, query: PickerQuery) -> PickerPage:
        from .training_material_picker_api import _gt_material_filter_page

        size, page = _validate_query(query)
        fingerprint = _query_fingerprint(query)
        before = self._owner()
        before_dict = self._vector_dict(before)
        token = self._snapshot_token(before_dict)
        legacy_cursor = None
        if query.cursor:
            created_at, image_id = decode_picker_cursor(
                query.cursor, fingerprint=fingerprint, snapshot=token,
            )
            from .material_repository import encode_material_cursor
            legacy_cursor = encode_material_cursor(created_at, image_id)
        try:
            result = _gt_material_filter_page(
                self.repository, self.annotations,
                cursor=legacy_cursor, page=None if legacy_cursor else page,
                limit=size,
                query=str(query.filters.query or ""),
                labels=_normalize_labels(query.filters.labels),
                require_ground_truth=bool(query.filters.require_ground_truth),
                include_payload=True,
                sort_order=query.sort_order,
                filters=self._filter_body(query.filters),
                count_mode=query.count_mode,
            )
        except ValueError as error:
            raise PickerUnsupportedFilter(str(error)) from error
        items = tuple(self._material_from_payload(row) for row in result["items"])
        annotations = (
            self._annotation_dto(query.project_id, [item.id for item in items])
            if query.include_annotations else PickerAnnotations({})
        )
        after = self._owner()
        after_dict = self._vector_dict(after)
        if after_dict != before_dict:
            raise PickerSnapshotStale(
                "the SQLite owner changed during the picker read",
                detail="owner revision vector changed",
            )
        next_cursor = None
        if result["next_cursor"] and items:
            from .material_repository import decode_material_cursor
            created_at, image_id = decode_material_cursor(result["next_cursor"])
            next_cursor = encode_picker_cursor(
                created_at, image_id, fingerprint=fingerprint, snapshot=token,
            )
        snapshot = PickerSnapshotInfo(
            project_id=query.project_id, source=self.name, status="OWNER",
            snapshot_id=token, revision_vector=after_dict, owner_equivalent=True,
        )
        return PickerPage(
            items=items, annotations=annotations, total=result["total"],
            has_more=bool(result["has_next"]), next_cursor=next_cursor,
            page=page, page_size=size, count_mode=query.count_mode,
            snapshot=snapshot,
        )

    def iter_candidates(self, query: PickerQuery, *, batch_size: int = 500):
        size, _page = _validate_query(query)
        batch = max(1, min(int(batch_size), MAX_CANDIDATE_BATCH))
        cursor = query.cursor
        while True:
            page = self.read_page(replace(
                query, page=None, page_size=batch, cursor=cursor,
                include_payload=False,
            ))
            if page.items:
                yield page.items
            if not page.has_more or not page.next_cursor:
                return
            cursor = page.next_cursor

    def get_many(self, project_id: str, image_ids: Sequence[str]) -> dict[str, PickerMaterial]:
        ids = _normalize_ids(image_ids) or []
        if len(ids) > MAX_BATCH_IDS:
            raise PickerUnsupportedFilter(
                f"at most {MAX_BATCH_IDS} ids may be read at once",
            )
        rows = self.repository.get_many(ids)
        by_id = {str(row.get("id")): row for row in rows}
        return {
            image_id: self._material_from_payload(by_id[image_id])
            for image_id in ids if image_id in by_id
        }

    def get_annotations(self, project_id: str, image_ids: Sequence[str]) -> PickerAnnotations:
        ids = _normalize_ids(image_ids) or []
        return self._annotation_dto(project_id, ids)

    def get_pool_relations(self, project_id: str, image_ids: Sequence[str]) -> dict[str, PickerPoolRelation]:
        ids = _normalize_ids(image_ids) or []
        result = {
            image_id: {"member": False, "joined_at": None, "categories": set(), "algorithms": set()}
            for image_id in ids
        }
        if not ids:
            return {}
        with closing(self.repository._connect()) as database:
            placeholders = ",".join("?" for _ in ids)
            for row in database.execute(
                "SELECT material_id, joined_at FROM negative_pool_members "
                f"WHERE material_id IN ({placeholders})", ids,
            ):
                entry = result[str(row[0])]
                entry["member"] = True
                entry["joined_at"] = row[1]
            for row in database.execute(
                "SELECT material_id, category_id FROM negative_pool_links "
                f"WHERE material_id IN ({placeholders})", ids,
            ):
                result[str(row[0])]["categories"].add(str(row[1]))
            for row in database.execute(
                "SELECT material_id, algorithm_id FROM negative_pool_algorithm_members "
                f"WHERE material_id IN ({placeholders})", ids,
            ):
                result[str(row[0])]["algorithms"].add(str(row[1]))
        return {
            image_id: PickerPoolRelation(
                image_id=image_id, member=bool(entry["member"]),
                joined_at=entry["joined_at"],
                category_ids=tuple(sorted(entry["categories"])),
                algorithm_ids=tuple(sorted(entry["algorithms"])),
            )
            for image_id, entry in result.items()
        }

    def get_task_negative_receipts(
        self, project_id: str, context_key: str, image_ids: Sequence[str] | None = None,
    ) -> PickerNegativeReceipts:
        ids = _normalize_ids(image_ids)
        receipts = self.annotations.task_negative_receipts(context_key, ids)
        generation = self.annotations.task_negative_confirmation_generation()
        return PickerNegativeReceipts(
            context_key=str(context_key), generation=int(generation),
            authoritative=True, receipts=tuple(receipts),
        )

    def revision_vector(self, project_id: str) -> Mapping[str, Any]:
        return self._vector_dict(self._owner())

    def snapshot_context(self, project_id: str) -> PickerSnapshotInfo:
        vector = self._vector_dict(self._owner())
        return PickerSnapshotInfo(
            project_id=project_id, source=self.name, status="OWNER",
            snapshot_id=self._snapshot_token(vector), revision_vector=vector,
            owner_equivalent=True,
        )


# ---------------------------------------------------------------------------
# PostgreSQL projection provider: independent SQL over w3_material_gt
# ---------------------------------------------------------------------------
#: SQLite ``LIKE ... COLLATE NOCASE`` is ASCII-only and has no escape character.
#: PostgreSQL ``ILIKE`` follows the cluster locale, so the fold is done explicitly
#: and the escape character is disabled to keep wildcard semantics identical.
_ASCII_FILENAME_LIKE = (
    f"translate(m.filename, '{_ASCII_UPPER}', '{_ASCII_LOWER}') "
    f"LIKE translate(%s, '{_ASCII_UPPER}', '{_ASCII_LOWER}') ESCAPE ''"
)

_GT_LABEL_ANY = (
    "EXISTS (SELECT 1 FROM " + SCHEMA_NAME + ".annotation_label_reference gt "
    "WHERE gt.project_id=m.project_id AND gt.image_id=m.id "
    "AND gt.annotation_state='annotated' AND gt.box_count>0 "
    "AND gt.label_code = ANY(%s))"
)
_GT_LABEL_EQ = (
    "EXISTS (SELECT 1 FROM " + SCHEMA_NAME + ".annotation_label_reference gt "
    "WHERE gt.project_id=m.project_id AND gt.image_id=m.id "
    "AND gt.annotation_state='annotated' AND gt.box_count>0 "
    "AND gt.label_code = %s)"
)
_GT_PRESENT = (
    "EXISTS (SELECT 1 FROM " + SCHEMA_NAME + ".annotation_label_reference gt "
    "WHERE gt.project_id=m.project_id AND gt.image_id=m.id AND ("
    "(gt.annotation_state='annotated' AND gt.box_count>0) OR "
    "(gt.annotation_state='confirmed_empty' AND gt.scope_ref=1)))"
)
_POOL_MEMBER = (
    "EXISTS (SELECT 1 FROM " + SCHEMA_NAME + ".negative_pool_member np "
    "WHERE np.project_id=m.project_id AND np.material_id=m.id)"
)
_POOL_CATEGORY = (
    "EXISTS (SELECT 1 FROM " + SCHEMA_NAME + ".negative_pool_link nl "
    "WHERE nl.project_id=m.project_id AND nl.material_id=m.id "
    "AND nl.category_id = ANY(%s))"
)
_POOL_ALGORITHM = (
    "EXISTS (SELECT 1 FROM " + SCHEMA_NAME + ".negative_pool_algorithm_member am "
    "WHERE am.project_id=m.project_id AND am.material_id=m.id AND am.algorithm_id = %s)"
)
#: SQLite ``negative_pool._LIVE`` in PostgreSQL JSONB terms (deleted/claimed rows
#: are not live pool members). Only applied when the pool filter is active.
_PG_LIVE = (
    "(m.payload -> '_dataset_delete_claim') IS NULL "
    "AND (m.payload -> '_material_batch_delete_claim') IS NULL "
    "AND (m.payload -> 'deleted_at') IS NULL "
    "AND ((m.payload -> 'deleted') IS NULL "
    "     OR (m.payload -> 'deleted') IN ('false'::jsonb, '0'::jsonb))"
)
_MATERIAL_SELECT = (
    "m.id, m.filename, m.storage_source_id, m.processing_status, m.content_sha256, "
    "m.size_bytes, m.box_count, m.annotated, m.created_at, m.updated_at"
)


def _chunks(values: Sequence[str], size: int = 500) -> Iterator[list[str]]:
    for offset in range(0, len(values), size):
        yield list(values[offset:offset + size])


class PostgresPickerReadProvider(PickerReadProvider):
    """Independent, project-scoped PostgreSQL reads over the U3 read projection."""

    name = "postgresql-picker"

    def __init__(
        self,
        connect: Callable[[], Any],
        *,
        owner_revisions: Callable[[], OwnerRevisionVector] | None = None,
        statement_timeout_ms: int = 15000,
        schema: str = SCHEMA_NAME,
    ):
        self._connect = connect
        self._owner_revisions = owner_revisions
        self._statement_timeout_ms = int(statement_timeout_ms)
        self._schema = schema

    @classmethod
    def from_dsn(
        cls, dsn: str, *, owner_revisions: Callable[[], OwnerRevisionVector] | None = None,
        statement_timeout_ms: int = 15000,
    ) -> "PostgresPickerReadProvider":
        import psycopg

        class _Connector:
            def __call__(self):
                return psycopg.connect(dsn)

        return cls(
            _Connector(), owner_revisions=owner_revisions,
            statement_timeout_ms=statement_timeout_ms,
        )

    # -- connection / transaction ---------------------------------------
    @contextmanager
    def _read(
        self, project_id: str, *, verify_owner: bool,
    ) -> Iterator[tuple[Any, dict[str, Any], str, Mapping[str, Any] | None]]:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as error:  # pragma: no cover - operator environment
            raise PickerProjectionUnavailable(
                "psycopg 3 is required for the PostgreSQL read provider",
                detail=str(error),
            ) from error
        try:
            connection = self._connect()
        except Exception as error:  # noqa: BLE001 - connection boundary
            raise PickerProjectionUnavailable(
                "the PostgreSQL read projection is unavailable", detail=str(error),
            ) from error
        try:
            try:
                with connection.transaction():
                    with connection.cursor(row_factory=dict_row) as cursor:
                        cursor.execute(
                            "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
                        )
                        cursor.execute("SET LOCAL TIME ZONE '+00:00'")
                        cursor.execute(
                            f"SET LOCAL statement_timeout = {int(self._statement_timeout_ms)}"
                        )
                        cursor.execute("SELECT pg_current_snapshot()::text AS identity")
                        identity = str(cursor.fetchone()["identity"])
                        state = self._state(cursor, project_id)
                        owner_before = None
                        if verify_owner:
                            owner_before = self._owner_vector()
                            self._assert_owner_matches(state, owner_before)
                        yield cursor, state, identity, owner_before
                        if verify_owner and owner_before is not None:
                            owner_after = self._owner_vector()
                            if owner_after != owner_before:
                                raise PickerSnapshotStale(
                                    "the SQLite owner changed during the picker read",
                                )
            except PickerReadError:
                raise
            except psycopg.OperationalError as error:
                raise PickerProjectionUnavailable(
                    "the PostgreSQL read projection is unavailable", detail=str(error),
                ) from error
            except psycopg.Error as error:
                raise PickerQueryFailed(
                    "the PostgreSQL picker query failed", detail=str(error),
                ) from error
        finally:
            try:
                connection.close()
            except Exception:  # noqa: BLE001 - closing must not mask the result
                pass

    def _owner_vector(self) -> OwnerRevisionVector:
        if self._owner_revisions is None:
            raise PickerOwnerUnverifiable(
                "no SQLite owner version source is configured for this provider",
            )
        return self._owner_revisions()

    @staticmethod
    def _assert_owner_matches(state: Mapping[str, Any], owner: OwnerRevisionVector) -> None:
        vector = state.get("revision_vector") or {}
        if not isinstance(vector, Mapping):
            raise PickerSnapshotStale("the published snapshot has no revision vector")
        mismatches: list[str] = []
        expected = (
            ("materials", "revision", owner.material_revision),
            ("annotations", "revision", owner.annotation_revision),
            ("negative_pool", "revision", owner.negative_pool_revision),
            ("materials_evidence", "generation", owner.materials_evidence_generation),
            ("materials_evidence", "structure_generation", owner.materials_structure_generation),
            ("annotations_evidence", "generation", owner.annotations_evidence_generation),
            ("annotations_evidence", "structure_generation", owner.annotations_structure_generation),
            ("negative_confirmation", "generation", owner.negative_confirmation_generation),
        )
        for stream, key, value in expected:
            actual = (vector.get(stream) or {}).get(key)
            if actual is not None and actual != value:
                mismatches.append(f"{stream}.{key}={actual} owner={value}")
        for stream, tables in (
            ("materials_evidence", owner.materials_tables),
            ("annotations_evidence", owner.annotations_tables),
        ):
            published = (vector.get(stream) or {}).get("tables")
            if published is not None and sorted(published) != sorted(tables):
                mismatches.append(f"{stream}.tables changed")
        if not owner.materials_structure_certified or not owner.annotations_structure_certified:
            raise PickerOwnerUnverifiable(
                "the SQLite evidence-table structure is not certified",
            )
        if mismatches:
            raise PickerSnapshotStale(
                "the published PostgreSQL snapshot does not match the current owner",
                detail="; ".join(mismatches[:6]),
            )

    def _state(self, cursor, project_id: str) -> dict[str, Any]:
        cursor.execute(
            "SELECT snapshot_id, content_digest, revision_vector, status, "
            "material_revision, annotation_revision, negative_pool_revision, "
            "negative_confirmation_revision, negative_confirmation_generation "
            f"FROM {self._schema}.picker_snapshot_state WHERE project_id=%s",
            (str(project_id),),
        )
        row = cursor.fetchone()
        if row is None:
            raise PickerSnapshotMissing(
                "no imported picker snapshot exists for this project",
                detail=str(project_id),
            )
        state = dict(row)
        if str(state.get("status") or "") != "READY":
            raise PickerSnapshotNotReady(
                "the picker snapshot is not READY",
                detail=f"status={state.get('status')}",
            )
        return state

    # -- SQL -------------------------------------------------------------
    @staticmethod
    def _where(query: PickerQuery) -> tuple[list[str], list[Any]]:
        filters = query.filters
        clauses = ["m.project_id = %s", "m.processing_status = 'processed'"]
        params: list[Any] = [str(query.project_id)]
        term = str(filters.query or "").strip()
        if term:
            clauses.append(_ASCII_FILENAME_LIKE)
            params.append(f"%{term}%")
        sources = [str(value) for value in filters.storage_source_ids if str(value or "").strip()]
        if sources:
            clauses.append("m.storage_source_id = ANY(%s)")
            params.append(sources)
        created_from = str(filters.created_from or "").strip()
        if created_from:
            clauses.append(
                "(CASE WHEN pg_input_is_valid(m.created_at, 'timestamptz') "
                "THEN m.created_at::timestamptz END) >= %s::timestamptz"
            )
            params.append(created_from)
        created_to = _normalize_created_to(filters.created_to)
        if created_to:
            clauses.append(
                "(CASE WHEN pg_input_is_valid(m.created_at, 'timestamptz') "
                "THEN m.created_at::timestamptz END) <= %s::timestamptz"
            )
            params.append(created_to)
        labels = _normalize_labels(filters.labels)
        if labels and filters.label_mode == "all":
            for code in labels:
                clauses.append(_GT_LABEL_EQ)
                params.append(code)
        elif labels:
            clauses.append(_GT_LABEL_ANY)
            params.append(list(labels))
        elif filters.require_ground_truth:
            clauses.append(_GT_PRESENT)
        state = str(filters.annotation_state or "")
        if state:
            clauses.append(
                "COALESCE((SELECT a.annotation_state FROM "
                f"{SCHEMA_NAME}.annotation a WHERE a.project_id=m.project_id "
                "AND a.image_id=m.id),'unannotated') = %s"
            )
            params.append(state)
        ids = _normalize_ids(filters.image_ids)
        if ids is not None:
            clauses.append("m.id = ANY(%s)")
            params.append(ids)
        categories = sorted({
            str(value) for value in filters.negative_category_ids if str(value or "").strip()
        })
        algorithm = str(filters.algorithm_asset_id or "").strip()
        # Existing contract: the pool branch activates on ``negative_pool_only`` or
        # categories; an algorithm id only narrows an already active pool filter.
        if filters.negative_pool_only or categories:
            clauses.append(_PG_LIVE)
            clauses.append(_POOL_MEMBER)
            if categories:
                clauses.append(_POOL_CATEGORY)
                params.append(categories)
            if algorithm:
                clauses.append(_POOL_ALGORITHM)
                params.append(algorithm)
        return clauses, params

    @staticmethod
    def _order(query: PickerQuery) -> tuple[str, str]:
        descending = query.sort_order == "newest"
        direction = "DESC" if descending else "ASC"
        nulls = "LAST" if descending else "FIRST"
        return (
            f'ORDER BY m.created_at COLLATE "C" {direction} NULLS {nulls}, '
            f'm.id COLLATE "C" {direction}',
            "<" if descending else ">",
        )

    @staticmethod
    def _material(row: Mapping[str, Any], *, payload: bool = False) -> PickerMaterial:
        return PickerMaterial(
            id=str(row["id"]),
            filename=str(row.get("filename") or ""),
            storage_source_id=str(row.get("storage_source_id") or ""),
            processing_status=str(row.get("processing_status") or ""),
            content_sha256=str(row.get("content_sha256") or ""),
            size_bytes=row.get("size_bytes"),
            box_count=row.get("box_count"),
            annotated=None if row.get("annotated") is None else bool(row.get("annotated")),
            created_at=str(row.get("created_at") or ""),
            updated_at=str(row.get("updated_at") or ""),
            payload=row.get("payload") if payload else None,
        )

    # -- contract --------------------------------------------------------
    def read_page(self, query: PickerQuery) -> PickerPage:
        size, page = _validate_query(query)
        fingerprint = _query_fingerprint(query)
        with self._read(query.project_id, verify_owner=query.verify_owner) as (
            cursor, state, identity, _owner,
        ):
            snapshot_id = str(state.get("snapshot_id") or "")
            clauses, params = self._where(query)
            where = " WHERE " + " AND ".join(clauses)
            total = None
            if query.count_mode == "exact":
                cursor.execute(
                    f"SELECT COUNT(*) AS total FROM {self._schema}.material m{where}",
                    params,
                )
                total = int(cursor.fetchone()["total"])
            order, operator = self._order(query)
            page_params = list(params)
            offset = None
            if query.cursor:
                created_at, image_id = decode_picker_cursor(
                    query.cursor, fingerprint=fingerprint, snapshot=snapshot_id,
                )
                clauses.append(
                    f'(m.created_at COLLATE "C" {operator} %s OR '
                    f'(m.created_at = %s AND m.id COLLATE "C" {operator} %s))'
                )
                page_params.extend((created_at, created_at, image_id))
                where = " WHERE " + " AND ".join(clauses)
            elif page is not None:
                if total is not None and page > max(1, (total + size - 1) // size):
                    raise PickerUnsupportedFilter(
                        f"page {page} exceeds total_pages {max(1, (total + size - 1) // size)}"
                    )
                offset = (page - 1) * size
            sql = (
                f"SELECT {_MATERIAL_SELECT}, "
                f"(m.payload) AS payload FROM {self._schema}.material m{where} {order} "
                "LIMIT %s" + (" OFFSET %s" if offset is not None else "")
            )
            page_params.append(size + 1)
            if offset is not None:
                page_params.append(offset)
            cursor.execute(sql, page_params)
            rows = cursor.fetchall()
            visible = rows[:size]
            items = tuple(self._material(row, payload=True) for row in visible)
            next_cursor = None
            if len(rows) > size and visible:
                last = visible[-1]
                created_at = str(last.get("created_at") or "")
                if not created_at:
                    raise PickerUnsupportedFilter(
                        "cursor pagination is not supported over materials without created_at",
                    )
                next_cursor = encode_picker_cursor(
                    created_at, str(last["id"]),
                    fingerprint=fingerprint, snapshot=snapshot_id,
                )
            annotations = (
                self._annotations_on(cursor, query.project_id, [item.id for item in items])
                if query.include_annotations else PickerAnnotations({})
            )
            info = PickerSnapshotInfo(
                project_id=query.project_id, source=self.name, status="READY",
                snapshot_id=snapshot_id,
                revision_vector=dict(state.get("revision_vector") or {}),
                owner_equivalent=query.verify_owner,
                isolation="REPEATABLE READ", read_only=True, read_identity=identity,
            )
        return PickerPage(
            items=items, annotations=annotations, total=total,
            has_more=len(rows) > size, next_cursor=next_cursor, page=page,
            page_size=size, count_mode=query.count_mode, snapshot=info,
        )

    def _annotations_on(self, cursor, project_id: str, image_ids: Sequence[str]) -> PickerAnnotations:
        ids = [str(value) for value in image_ids if str(value)]
        if not ids:
            return PickerAnnotations({})
        rows: dict[str, dict[str, Any]] = {}
        legacy: set[str] = set()
        for chunk in _chunks(ids):
            cursor.execute(
                "SELECT image_id, annotation_state, version, content_digest, boxes, scope "
                f"FROM {self._schema}.annotation WHERE project_id=%s AND image_id = ANY(%s)",
                (str(project_id), chunk),
            )
            for row in cursor.fetchall():
                rows[str(row["image_id"])] = dict(row)
            cursor.execute(
                "SELECT DISTINCT gt.image_id FROM "
                f"{self._schema}.annotation_label_reference gt "
                "WHERE gt.project_id=%s AND gt.image_id = ANY(%s) "
                "AND gt.source_kind='legacy' AND NOT EXISTS ("
                f"SELECT 1 FROM {self._schema}.annotation a WHERE a.project_id=gt.project_id "
                "AND a.image_id=gt.image_id)",
                (str(project_id), chunk),
            )
            legacy.update(str(row["image_id"]) for row in cursor.fetchall())
        annotations: dict[str, PickerAnnotation] = {}
        missing: list[str] = []
        unproven: list[str] = []
        for image_id in ids:
            row = rows.get(image_id)
            if row is None:
                if image_id in legacy:
                    unproven.append(image_id)
                else:
                    missing.append(image_id)
                continue
            boxes = row.get("boxes") or []
            scope = row.get("scope") or []
            if isinstance(boxes, str):
                boxes = json.loads(boxes)
            if isinstance(scope, str):
                scope = json.loads(scope)
            annotations[image_id] = PickerAnnotation(
                image_id=image_id,
                annotation_state=str(row.get("annotation_state") or "unannotated"),
                version=int(row.get("version") or 0),
                content_digest=str(row.get("content_digest") or ""),
                box_count=len(boxes or []),
                scope_labels=tuple(str(value) for value in (scope or [])),
            )
        return PickerAnnotations(
            annotations=annotations, missing_ids=tuple(missing),
            unproven_legacy_ids=tuple(unproven),
        )

    def iter_candidates(self, query: PickerQuery, *, batch_size: int = 500):
        size, _page = _validate_query(query)
        batch = max(1, min(int(batch_size), MAX_CANDIDATE_BATCH))
        with self._read(query.project_id, verify_owner=query.verify_owner) as (
            cursor, state, _identity, _owner,
        ):
            snapshot_id = str(state.get("snapshot_id") or "")
            clauses, params = self._where(query)
            order, operator = self._order(query)
            cursor_position: tuple[str, str] | None = None
            while True:
                page_clauses = list(clauses)
                page_params = list(params)
                if cursor_position is not None:
                    created_at, image_id = cursor_position
                    page_clauses.append(
                        f'(m.created_at COLLATE "C" {operator} %s OR '
                        f'(m.created_at = %s AND m.id COLLATE "C" {operator} %s))'
                    )
                    page_params.extend((created_at, created_at, image_id))
                cursor.execute(
                    f"SELECT {_MATERIAL_SELECT} FROM {self._schema}.material m WHERE "
                    + " AND ".join(page_clauses) + f" {order} LIMIT %s",
                    [*page_params, batch + 1],
                )
                rows = cursor.fetchall()
                visible = rows[:batch]
                if visible:
                    yield tuple(self._material(row) for row in visible)
                if len(rows) <= batch:
                    return
                last = visible[-1]
                created_at = str(last.get("created_at") or "")
                if not created_at:
                    raise PickerUnsupportedFilter(
                        "candidate iteration is not supported over materials without created_at",
                    )
                cursor_position = (created_at, str(last["id"]))

    def get_many(self, project_id: str, image_ids: Sequence[str], *, verify_owner: bool = True) -> dict[str, PickerMaterial]:
        ids = _normalize_ids(image_ids) or []
        if len(ids) > MAX_BATCH_IDS:
            raise PickerUnsupportedFilter(f"at most {MAX_BATCH_IDS} ids may be read at once")
        result: dict[str, PickerMaterial] = {}
        if not ids:
            return result
        with self._read(project_id, verify_owner=verify_owner) as (cursor, _state, _identity, _owner):
            for chunk in _chunks(ids):
                cursor.execute(
                    f"SELECT {_MATERIAL_SELECT} FROM {self._schema}.material m "
                    "WHERE m.project_id=%s AND m.id = ANY(%s)",
                    (str(project_id), chunk),
                )
                for row in cursor.fetchall():
                    material = self._material(row)
                    result[material.id] = material
        return {image_id: result[image_id] for image_id in ids if image_id in result}

    def get_annotations(self, project_id: str, image_ids: Sequence[str], *, verify_owner: bool = True) -> PickerAnnotations:
        ids = _normalize_ids(image_ids) or []
        if len(ids) > MAX_BATCH_IDS:
            raise PickerUnsupportedFilter(f"at most {MAX_BATCH_IDS} ids may be read at once")
        if not ids:
            return PickerAnnotations({})
        with self._read(project_id, verify_owner=verify_owner) as (cursor, _state, _identity, _owner):
            return self._annotations_on(cursor, project_id, ids)

    def get_pool_relations(self, project_id: str, image_ids: Sequence[str], *, verify_owner: bool = True) -> dict[str, PickerPoolRelation]:
        ids = _normalize_ids(image_ids) or []
        if not ids:
            return {}
        state: dict[str, dict[str, Any]] = {
            image_id: {"member": False, "joined_at": None, "categories": set(), "algorithms": set()}
            for image_id in ids
        }
        with self._read(project_id, verify_owner=verify_owner) as (cursor, _state, _identity, _owner):
            for chunk in _chunks(ids):
                cursor.execute(
                    "SELECT material_id, joined_at FROM "
                    f"{self._schema}.negative_pool_member WHERE project_id=%s AND material_id = ANY(%s)",
                    (str(project_id), chunk),
                )
                for row in cursor.fetchall():
                    entry = state[str(row["material_id"])]
                    entry["member"] = True
                    entry["joined_at"] = row["joined_at"]
                cursor.execute(
                    "SELECT material_id, category_id FROM "
                    f"{self._schema}.negative_pool_link WHERE project_id=%s AND material_id = ANY(%s)",
                    (str(project_id), chunk),
                )
                for row in cursor.fetchall():
                    state[str(row["material_id"])]["categories"].add(str(row["category_id"]))
                cursor.execute(
                    "SELECT material_id, algorithm_id FROM "
                    f"{self._schema}.negative_pool_algorithm_member "
                    "WHERE project_id=%s AND material_id = ANY(%s)",
                    (str(project_id), chunk),
                )
                for row in cursor.fetchall():
                    state[str(row["material_id"])]["algorithms"].add(str(row["algorithm_id"]))
        return {
            image_id: PickerPoolRelation(
                image_id=image_id, member=bool(entry["member"]),
                joined_at=entry["joined_at"],
                category_ids=tuple(sorted(entry["categories"])),
                algorithm_ids=tuple(sorted(entry["algorithms"])),
            )
            for image_id, entry in state.items()
        }

    def get_task_negative_receipts(
        self, project_id: str, context_key: str, image_ids: Sequence[str] | None = None,
        *, verify_owner: bool = True,
    ) -> PickerNegativeReceipts:
        ids = _normalize_ids(image_ids)
        with self._read(project_id, verify_owner=verify_owner) as (cursor, state, _identity, _owner):
            vector = state.get("revision_vector") or {}
            tables = ((vector.get("negative_confirmation") or {}).get("tables") or [])
            generation = int(state.get("negative_confirmation_generation") or 0)
            if "task_negative_confirmations" not in tables:
                # The source table is absent: retained projections are history, not
                # current confirmations. Nothing is deleted and nothing is implied.
                return PickerNegativeReceipts(
                    context_key=str(context_key), generation=generation,
                    authoritative=False, receipts=(),
                )
            receipts: list[Mapping[str, Any]] = []
            chunks = _chunks(ids) if ids else [[]]
            for chunk in chunks:
                sql = (
                    "SELECT receipt_id, context_key, image_id, evidence FROM "
                    f"{self._schema}.task_negative_confirmation "
                    "WHERE project_id=%s AND context_key=%s"
                )
                params: list[Any] = [str(project_id), str(context_key)]
                if chunk:
                    sql += " AND image_id = ANY(%s)"
                    params.append(chunk)
                cursor.execute(sql, params)
                receipts.extend(dict(row) for row in cursor.fetchall())
        return PickerNegativeReceipts(
            context_key=str(context_key), generation=generation,
            authoritative=True, receipts=tuple(receipts),
        )

    def revision_vector(self, project_id: str) -> Mapping[str, Any]:
        with self._read(project_id, verify_owner=False) as (_cursor, state, _identity, _owner):
            return dict(state.get("revision_vector") or {})

    def snapshot_context(self, project_id: str) -> PickerSnapshotInfo:
        with self._read(project_id, verify_owner=False) as (cursor, state, identity, _owner):
            cursor.execute("SHOW transaction_isolation")
            isolation = str(cursor.fetchone()["transaction_isolation"]).upper()
            cursor.execute("SHOW transaction_read_only")
            read_only = str(cursor.fetchone()["transaction_read_only"]).lower() == "on"
            return PickerSnapshotInfo(
                project_id=project_id, source=self.name, status="READY",
                snapshot_id=str(state.get("snapshot_id") or ""),
                revision_vector=dict(state.get("revision_vector") or {}),
                owner_equivalent=False, isolation=isolation,
                read_only=read_only, read_identity=identity,
            )
