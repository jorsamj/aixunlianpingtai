"""U3 shadow migration: materials, formal GT and the negative pool.

Read model only. The SQLite owners stay the single production authority: this
module exports a deterministic snapshot from their files, imports it into an
isolated PostgreSQL schema and reconciles the two sides. It never writes SQLite,
never registers a production provider and never becomes a second authority.

Contract notes (see docs/architecture/U3_MATERIAL_GT_NEGATIVE_POOL_MIGRATION_INVENTORY_20261126.md):

* every store is read inside ONE SQLite read transaction, so paging cannot mix
  generations of the same store; paging is keyset (bounded page size);
* the digest is canonical over normalized rows (sorted JSON, no locale), so a
  reordered payload or a different key order hashes the same;
* NULL / '' / 0 / false are preserved: nullable columns stay NULL, JSON text is
  parsed into JSONB without coercion, and integer flags stay integers;
* historical annotation versions and content digests are carried verbatim;
* negative-pool membership keeps the SQLite ``ON DELETE CASCADE`` semantics;
* a replay of the same snapshot changes nothing;
* reconcile explains every difference and treats an unprovable owner as a failure,
  never as "zero".

Schema V4 (this build) adds the read-side identity contracts only: a published
snapshot state, an import ledger, projection cursors, a query projection of the
task-level negative confirmations, and the label-first / owner-order indexes the
Picker needs. It never adds a write authority: the SQLite owners stay the source
of truth, ``task_negative_confirmation`` is derived read-only data (the verbatim
evidence stays in ``evidence_row``) and an owner revision may not go backwards.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any, Iterable, Mapping

SCHEMA_NAME = "w3_material_gt"
SCHEMA_VERSION = 4
#: Pseudo store-revision key recording that v1 reference rows were upgraded with
#: provisional counters and must be replaced by a full authoritative SQLite import
#: before the target may be considered complete.
LEGACY_REFERENCE_PENDING_STORE = "legacy_reference_pending_import"
CONTRACT_VERSION = "u3-shadow-snapshot-v2"
REQUIRED_TABLES = {
    "materials": ("materials", "material_meta", "material_labels",
                  "material_annotation_scopes", "negative_pool_members",
                  "negative_pool_categories", "negative_pool_links",
                  "negative_pool_algorithm_members", "negative_pool_meta"),
    "annotations": ("annotations", "annotation_meta", "annotation_label_references"),
}
#: Structural contract of every migrated table: a table that exists without these
#: fields cannot be exported (a missing field is not "empty data").
REQUIRED_COLUMNS = {
    "materials": ("id", "storage_source_id", "object_key", "content_sha256", "payload_json"),
    "material_labels": ("material_id", "label_code"),
    "material_annotation_scopes": ("material_id", "label_code"),
    "annotations": ("image_id", "annotation_state", "version", "content_digest", "boxes_json"),
    "annotation_label_references": (
        "image_id", "label_code", "box_count", "scope_ref", "annotation_state", "source_kind",
    ),
    "negative_pool_members": ("material_id", "joined_at"),
    "negative_pool_categories": ("id", "name", "enabled"),
    "negative_pool_links": ("material_id", "category_id"),
    "negative_pool_algorithm_members": ("algorithm_id", "material_id"),
}
#: Meta tables whose shape the export depends on.
REQUIRED_META_COLUMNS = {
    "material_meta": ("key", "value"),
    "annotation_meta": ("key", "value"),
    "negative_pool_meta": ("revision",),
}

#: Historical evidence preserved verbatim (exact rows, JSON) rather than re-typed.
EVIDENCE_TABLES = {
    "materials": ("material_migrations", "material_storage_audit", "material_retirements",
                  "material_cleanup_deferred", "material_assignment_receipts",
                  "negative_pool_operations"),
    "annotations": ("annotation_delete_backup", "annotation_negative_reviews",
                    "annotation_candidate_commits", "task_negative_confirmations"),
}
PAGE_SIZE = 500

MATERIAL_COLUMNS = (
    "id", "filename", "storage_source_id", "storage_type", "object_key",
    "content_sha256", "size_bytes", "etag", "processing_status", "box_count",
    "annotated", "created_at", "updated_at", "payload_json",
)
ANNOTATION_COLUMNS = (
    "image_id", "annotation_state", "version", "content_digest", "boxes_json",
    "scope_json", "created_at", "updated_at",
)


class U3MigrationError(RuntimeError):
    """Shadow migration failure with a stable machine-readable code."""

    def __init__(self, code: str, message: str, *, detail: str = ""):
        super().__init__(message)
        self.code = str(code)
        self.detail = str(detail or "")


def _sqlite_columns(database, table: str) -> set[str]:
    """Table columns; an empty set means the table does not exist.

    SQLite errors are NOT caught here: a metadata read failure must not look like
    "table absent" (which would silently keep retained evidence instead of failing
    the export).
    """
    return {str(row[1]) for row in database.execute(f"PRAGMA table_info({table})")}


def _canonical(value: Any) -> Any:
    """JSON-safe canonical value that keeps NULL apart from '' and 0."""
    if isinstance(value, Mapping):
        return {str(key): _canonical(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    return value


def _digest(rows: Iterable[Mapping[str, Any]]) -> str:
    body = json.dumps(
        [_canonical(dict(row)) for row in rows],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _read_rows(
    database, table: str, columns: Iterable[str], *, key_columns: tuple[str, ...],
    page_size: int = PAGE_SIZE,
) -> list[dict[str, Any]]:
    """Keyset-paged read inside the caller's transaction (row-value comparison).

    Every table has a deterministic composite key, so a page never repeats or skips
    a row and the read stays bounded even for a very large label/reference table.
    """
    names = [name for name in columns if name in _sqlite_columns(database, table)]
    if not names or any(name not in names for name in key_columns):
        return []
    order = ",".join(key_columns)
    placeholders = ",".join("?" for _ in key_columns)
    rows: list[dict[str, Any]] = []
    after: tuple[Any, ...] | None = None
    while True:
        if after is None:
            statement = f"SELECT {','.join(names)} FROM {table} ORDER BY {order} LIMIT ?"
            page = database.execute(statement, (page_size,)).fetchall()
        else:
            statement = (
                f"SELECT {','.join(names)} FROM {table} "
                f"WHERE ({order}) > ({placeholders}) ORDER BY {order} LIMIT ?"
            )
            page = database.execute(statement, (*after, page_size)).fetchall()
        for raw in page:
            record = dict(raw)
            for json_key in ("payload_json", "boxes_json", "scope_json"):
                if json_key in record:
                    text_value = record.pop(json_key)
                    record[json_key.removesuffix("_json")] = (
                        None if text_value is None else json.loads(text_value)
                    )
            rows.append(record)
        if len(page) < page_size:
            break
        after = tuple(page[-1][name] for name in key_columns)
    return rows


def _open_read_only(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(
        path.resolve().as_uri() + "?mode=ro", uri=True, timeout=30, isolation_level=None
    )
    connection.row_factory = sqlite3.Row
    connection.execute("BEGIN")
    return connection


def _store_snapshot(
    database, project_id: str,
    *, tables: Mapping[str, tuple[str, Iterable[str], tuple[str, ...]]],
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for name, (table, columns, key_columns) in tables.items():
        present = _sqlite_columns(database, table)
        if not present:
            raise U3MigrationError(
                "U3_OWNER_INCOMPLETE",
                "a required table is missing",
                detail=f"table={table}",
            )
        missing = [column for column in REQUIRED_COLUMNS.get(name, ()) if column not in present]
        if missing:
            raise U3MigrationError(
                "U3_OWNER_INCOMPLETE",
                "a required table is missing required fields",
                detail=f"table={table} missing={missing}",
            )
        rows = _read_rows(database, table, columns, key_columns=key_columns)
        if REQUIRED_COLUMNS.get(name) and not rows and not present:
            raise U3MigrationError(
                "U3_OWNER_INCOMPLETE",
                "a required table cannot be read",
                detail=f"table={table}",
            )
        output[name] = rows
    return output


_MATERIAL_TABLES = {
    "materials": ("materials", MATERIAL_COLUMNS, ("id",)),
    "material_labels": (
        "material_labels", ("material_id", "label_code", "box_count"),
        ("material_id", "label_code"),
    ),
    "material_annotation_scopes": (
        "material_annotation_scopes", ("material_id", "label_code"),
        ("material_id", "label_code"),
    ),
    "negative_pool_members": (
        "negative_pool_members", ("material_id", "joined_at"), ("material_id",),
    ),
    "negative_pool_categories": (
        "negative_pool_categories", ("id", "name", "enabled"), ("id",),
    ),
    "negative_pool_links": (
        "negative_pool_links", ("material_id", "category_id"),
        ("material_id", "category_id"),
    ),
    "negative_pool_algorithm_members": (
        "negative_pool_algorithm_members", ("algorithm_id", "material_id", "joined_at"),
        ("algorithm_id", "material_id"),
    ),
}
_ANNOTATION_TABLES = {
    "annotations": ("annotations", ANNOTATION_COLUMNS, ("image_id",)),
    # The real owner keeps box_count/scope_ref/annotation_state/source_kind with
    # PRIMARY KEY(image_id,label_code); all of them are part of the evidence.
    "annotation_label_references": (
        "annotation_label_references",
        ("image_id", "label_code", "box_count", "scope_ref", "annotation_state", "source_kind"),
        ("image_id", "label_code"),
    ),
}


def _table_rows_all(database, table: str, *, page_size: int = PAGE_SIZE) -> tuple[list[str], list[dict[str, Any]]]:
    """Verbatim rows for a historical evidence table.

    Rowid tables page by rowid; ``WITHOUT ROWID`` tables (composite primary keys,
    e.g. material_assignment_receipts) page by their primary-key row value, so an
    evidence table is never read unbounded.
    """
    columns = _sqlite_columns(database, table)
    if not columns:
        return [], []
    pk = [str(row[1]) for row in database.execute(f"PRAGMA table_info({table})") if int(row[5])]
    rows: list[dict[str, Any]] = []
    if not pk:
        after = 0
        while True:
            page = database.execute(
                f"SELECT rowid AS __rowid, * FROM {table} WHERE rowid > ? ORDER BY rowid LIMIT ?",
                (after, page_size),
            ).fetchall()
            for raw in page:
                record = dict(raw)
                record.pop("__rowid", None)
                rows.append(record)
            if len(page) < page_size:
                break
            after = int(page[-1]["__rowid"])
        return pk, rows
    order = ",".join(pk)
    placeholders = ",".join("?" for _ in pk)
    after_values: tuple[Any, ...] | None = None
    while True:
        if after_values is None:
            page = database.execute(
                f"SELECT * FROM {table} ORDER BY {order} LIMIT ?", (page_size,)
            ).fetchall()
        else:
            page = database.execute(
                f"SELECT * FROM {table} WHERE ({order}) > ({placeholders}) "
                f"ORDER BY {order} LIMIT ?",
                (*after_values, page_size),
            ).fetchall()
        for raw in page:
            rows.append(dict(raw))
        if len(page) < page_size:
            break
        after_values = tuple(page[-1][name] for name in pk)
    return pk, rows


def _evidence_identity(pk_columns: list[str], row: Mapping[str, Any]) -> str:
    """Stable identity of one historical evidence row.

    Built from the row's real primary key (or its whole canonical content when the
    table has no primary key), never from a content digest alone: two rows with the
    same payload but different keys must remain two distinct rows.
    """
    values = (
        [row.get(name) for name in pk_columns]
        if pk_columns else [_canonical(dict(row))]
    )
    body = json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _schema_version(database) -> int | None:
    try:
        return int(database.execute("PRAGMA user_version").fetchone()[0])
    except sqlite3.Error:
        return None


def export_project_snapshot(project_dir: str | Path, project_id: str) -> dict[str, Any]:
    """Public wrapper: any SQLite read failure fails the export closed."""
    try:
        return _export_project_snapshot(project_dir, project_id)
    except sqlite3.Error as error:
        raise U3MigrationError(
            "U3_OWNER_UNREADABLE",
            "a source store or metadata could not be read",
            detail=str(error),
        ) from error


def _export_project_snapshot(project_dir: str | Path, project_id: str) -> dict[str, Any]:
    """Deterministic snapshot of the authoritative SQLite owners (read-only).

    Cross-store consistency is *barrier based*, not a claim of a global atomic
    snapshot: the export runs inside the owners' existing
    ``material_annotation_lifecycle_fence`` (the lock that serializes material
    lifecycle commits with formal annotation writes), reads each store inside one
    SQLite read transaction, and then re-reads both revision high-water marks.
    A revision that moved during the export makes the snapshot unusable and the
    export is refused. Owners that do not take that fence are therefore detected,
    never silently mixed into an "admitted" snapshot.
    """
    from .material_repository import material_annotation_lifecycle_fence

    project = Path(project_dir)
    materials_db = project / "materials.sqlite3"
    annotations_db = project / "annotations.sqlite3"
    if not materials_db.is_file():
        raise U3MigrationError(
            "U3_MATERIALS_STORE_MISSING", "the material store does not exist",
            detail=str(materials_db),
        )
    from .annotation_repository import _SCHEMA_VERSION as ANNOTATION_SCHEMA_VERSION
    from .material_repository import MATERIAL_READ_SCHEMA_VERSIONS

    def _require_schema(database, *, allowed: set[int] | frozenset[int], store: str) -> int:
        version = _schema_version(database)
        if version is None or int(version) not in allowed:
            raise U3MigrationError(
                "U3_SCHEMA_VERSION_UNSUPPORTED",
                "the source store schema version is not supported by this tool",
                detail=f"store={store} version={version} allowed={sorted(allowed)}",
            )
        return int(version)

    def _require_meta(database, table: str) -> None:
        present = _sqlite_columns(database, table)
        missing = [name for name in REQUIRED_META_COLUMNS[table] if name not in present]
        if missing:
            raise U3MigrationError(
                "U3_OWNER_INCOMPLETE",
                "a required meta table is missing required fields",
                detail=f"table={table} missing={missing}",
            )

    table_state: dict[str, dict[str, Any]] = {}
    stores: dict[str, Any] = {}
    materials_change: dict[str, Any] = {}
    annotations_change: dict[str, Any] = {}
    with material_annotation_lifecycle_fence(project, timeout=60):
        with closing(_open_read_only(materials_db)) as database:
            materials_schema_version = _require_schema(
                database, allowed=set(MATERIAL_READ_SCHEMA_VERSIONS), store="materials"
            )
            _require_meta(database, "material_meta")
            _require_meta(database, "negative_pool_meta")
            present = _sqlite_columns(database, "materials") != set()
            missing = [
                name for name in REQUIRED_TABLES["materials"]
                if not _sqlite_columns(database, name)
            ]
            if missing:
                raise U3MigrationError(
                    "U3_OWNER_INCOMPLETE",
                    "the material owner is missing required tables",
                    detail=f"missing={missing} present={present}",
                )
            stores["materials"] = _store_snapshot(
                database, project_id, tables=_MATERIAL_TABLES
            )
            evidence: dict[str, Any] = {}
            for table in EVIDENCE_TABLES["materials"]:
                exists = bool(_sqlite_columns(database, table))
                table_state[f"materials.{table}"] = {
                    "present": exists,
                    "schema_version": _schema_version(database),
                    "row_count": 0,
                }
                if exists:
                    pk_columns, raw_rows = _table_rows_all(database, table)
                    evidence[table] = sorted(
                        (
                            {"row_key": _evidence_identity(pk_columns, row), "payload": row}
                            for row in raw_rows
                        ),
                        key=lambda item: item["row_key"],
                    )
                    table_state[f"materials.{table}"]["row_count"] = len(evidence[table])
            stores["materials"]["evidence"] = evidence
            for name, (table, _columns, _keys) in _MATERIAL_TABLES.items():
                table_state[f"materials.{table}"] = {
                    "present": True,
                    "schema_version": _schema_version(database),
                    "row_count": len(stores["materials"].get(name) or []),
                }
            for meta_table in ("material_meta", "negative_pool_meta"):
                table_state[f"materials.{meta_table}"] = {
                    "present": True,
                    "schema_version": _schema_version(database),
                    "row_count": int(
                        database.execute(f"SELECT COUNT(*) FROM {meta_table}").fetchone()[0]
                    ),
                }
            revision_row = database.execute(
                "SELECT value FROM material_meta WHERE key='revision'"
            ).fetchone()
            material_revision = int(revision_row[0]) if revision_row else None
            generation_row = database.execute(
                "SELECT value FROM material_meta WHERE key=?",
                (MATERIAL_EVIDENCE_GENERATION_KEY,),
            ).fetchone()
            # An owner database from before the counter existed observed every
            # historical evidence row at generation 0.
            material_evidence_generation = int(generation_row[0]) if generation_row else 0
            materials_structure_row = database.execute(
                "SELECT value FROM material_meta WHERE key=?",
                (MATERIAL_EVIDENCE_STRUCTURE_KEY,),
            ).fetchone()
            materials_structure_generation_row = database.execute(
                "SELECT value FROM material_meta WHERE key=?",
                (EVIDENCE_STRUCTURE_GENERATION_KEY,),
            ).fetchone()
            materials_structure_generation = (
                int(materials_structure_generation_row[0])
                if materials_structure_generation_row else 0
            )
            pool_row = database.execute(
                "SELECT revision FROM negative_pool_meta WHERE id=1"
            ).fetchone()
            pool_revision = int(pool_row[0]) if pool_row else None
            materials_change = _owner_change_marks(
                database, ("materials", "negative_pool")
            )
            materials_schema = materials_schema_version
        if not annotations_db.is_file():
            raise U3MigrationError(
                "U3_ANNOTATIONS_STORE_MISSING",
                "the formal annotation store does not exist",
                detail=str(annotations_db),
            )
        with closing(_open_read_only(annotations_db)) as database:
            annotations_schema_version = _require_schema(
                database, allowed={int(ANNOTATION_SCHEMA_VERSION)}, store="annotations"
            )
            _require_meta(database, "annotation_meta")
            missing = [
                name for name in REQUIRED_TABLES["annotations"]
                if not _sqlite_columns(database, name)
            ]
            if missing:
                raise U3MigrationError(
                    "U3_OWNER_INCOMPLETE",
                    "the annotation owner is missing required tables",
                    detail=f"missing={missing}",
                )
            stores["annotations"] = _store_snapshot(
                database, project_id, tables=_ANNOTATION_TABLES
            )
            evidence = {}
            for table in EVIDENCE_TABLES["annotations"]:
                exists = bool(_sqlite_columns(database, table))
                table_state[f"annotations.{table}"] = {
                    "present": exists,
                    "schema_version": _schema_version(database),
                    "row_count": 0,
                }
                if exists:
                    pk_columns, raw_rows = _table_rows_all(database, table)
                    evidence[table] = sorted(
                        (
                            {"row_key": _evidence_identity(pk_columns, row), "payload": row}
                            for row in raw_rows
                        ),
                        key=lambda item: item["row_key"],
                    )
                    table_state[f"annotations.{table}"]["row_count"] = len(evidence[table])
            stores["annotations"]["evidence"] = evidence
            for name, (table, _columns, _keys) in _ANNOTATION_TABLES.items():
                table_state[f"annotations.{table}"] = {
                    "present": True,
                    "schema_version": _schema_version(database),
                    "row_count": len(stores["annotations"].get(name) or []),
                }
            table_state["annotations.annotation_meta"] = {
                "present": True,
                "schema_version": _schema_version(database),
                "row_count": int(
                    database.execute("SELECT COUNT(*) FROM annotation_meta").fetchone()[0]
                ),
            }
            meta = database.execute(
                "SELECT value FROM annotation_meta WHERE key='revision'"
            ).fetchone()
            annotation_revision = int(meta[0]) if meta else None
            annotation_generation_row = database.execute(
                "SELECT value FROM annotation_meta WHERE key=?",
                (ANNOTATION_EVIDENCE_GENERATION_KEY,),
            ).fetchone()
            annotation_evidence_generation = (
                int(annotation_generation_row[0]) if annotation_generation_row else 0
            )
            confirmation_generation_row = database.execute(
                "SELECT value FROM annotation_meta WHERE key=?",
                (CONFIRMATION_GENERATION_KEY,),
            ).fetchone()
            confirmation_generation = (
                int(confirmation_generation_row[0]) if confirmation_generation_row else 0
            )
            annotations_structure_row = database.execute(
                "SELECT value FROM annotation_meta WHERE key=?",
                (ANNOTATION_EVIDENCE_STRUCTURE_KEY,),
            ).fetchone()
            annotations_structure_generation_row = database.execute(
                "SELECT value FROM annotation_meta WHERE key=?",
                (EVIDENCE_STRUCTURE_GENERATION_KEY,),
            ).fetchone()
            annotations_structure_generation = (
                int(annotations_structure_generation_row[0])
                if annotations_structure_generation_row else 0
            )
            annotations_schema = annotations_schema_version
            annotations_change = _owner_change_marks(
                database, ("annotations",)
            )
        # The owner must be able to prove its evidence-table set. A table created or
        # dropped outside the owner (raw SQL, external migration) is not inferred to
        # be safe: the export fails closed until the owner certifies it.
        materials_observed = sorted(
            table for table in EVIDENCE_TABLES["materials"]
            if bool(table_state[f"materials.{table}"]["present"])
        )
        annotations_observed = sorted(
            table for table in EVIDENCE_TABLES["annotations"]
            if bool(table_state[f"annotations.{table}"]["present"])
        )
        materials_recorded = recorded_structure(materials_structure_row)
        if materials_recorded is not None and materials_recorded != materials_observed:
            raise U3MigrationError(
                "U3_OWNER_STRUCTURE_UNVERIFIED",
                "the material evidence-table set changed without owner certification",
                detail=(
                    f"recorded={materials_recorded} observed={materials_observed}; "
                    "run MaterialRepository.reconcile_evidence_structure() first"
                ),
            )
        annotations_recorded = recorded_structure(annotations_structure_row)
        if annotations_recorded is not None and annotations_recorded != annotations_observed:
            raise U3MigrationError(
                "U3_OWNER_STRUCTURE_UNVERIFIED",
                "the annotation evidence-table set changed without owner certification",
                detail=(
                    f"recorded={annotations_recorded} observed={annotations_observed}; "
                    "run AnnotationRepository.reconcile_evidence_structure() first"
                ),
            )
        materials_structure_certified = materials_recorded is not None
        annotations_structure_certified = annotations_recorded is not None
        # Revision re-check: a store that moved during the export invalidates it.
        with closing(_open_read_only(materials_db)) as database:
            after_row = database.execute(
                "SELECT value FROM material_meta WHERE key='revision'"
            ).fetchone()
            after_pool = database.execute(
                "SELECT revision FROM negative_pool_meta WHERE id=1"
            ).fetchone()
            after_generation = database.execute(
                "SELECT value FROM material_meta WHERE key=?",
                (MATERIAL_EVIDENCE_GENERATION_KEY,),
            ).fetchone()
            after_structure = database.execute(
                "SELECT value FROM material_meta WHERE key=?",
                (MATERIAL_EVIDENCE_STRUCTURE_KEY,),
            ).fetchone()
            after_structure_generation = database.execute(
                "SELECT value FROM material_meta WHERE key=?",
                (EVIDENCE_STRUCTURE_GENERATION_KEY,),
            ).fetchone()
            after_materials_tables = {
                str(row[0])
                for row in database.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            after_materials_observed = sorted(
                table for table in EVIDENCE_TABLES["materials"]
                if table in after_materials_tables
            )
            after_materials_revision = int(after_row[0]) if after_row else None
            after_pool_revision = int(after_pool[0]) if after_pool else None
            after_materials_change = _owner_change_marks(
                database, ("materials", "negative_pool")
            )
            after_material_evidence_generation = (
                int(after_generation[0]) if after_generation else 0
            )
            after_materials_structure_generation = (
                int(after_structure_generation[0])
                if after_structure_generation else 0
            )
        with closing(_open_read_only(annotations_db)) as database:
            after_meta = database.execute(
                "SELECT value FROM annotation_meta WHERE key='revision'"
            ).fetchone()
            after_annotation_revision = int(after_meta[0]) if after_meta else None
            after_annotation_generation = database.execute(
                "SELECT value FROM annotation_meta WHERE key=?",
                (ANNOTATION_EVIDENCE_GENERATION_KEY,),
            ).fetchone()
            after_confirmation_generation = database.execute(
                "SELECT value FROM annotation_meta WHERE key=?",
                (CONFIRMATION_GENERATION_KEY,),
            ).fetchone()
            after_annotation_structure = database.execute(
                "SELECT value FROM annotation_meta WHERE key=?",
                (ANNOTATION_EVIDENCE_STRUCTURE_KEY,),
            ).fetchone()
            after_annotation_structure_generation = database.execute(
                "SELECT value FROM annotation_meta WHERE key=?",
                (EVIDENCE_STRUCTURE_GENERATION_KEY,),
            ).fetchone()
            after_annotations_tables = {
                str(row[0])
                for row in database.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            after_annotations_observed = sorted(
                table for table in EVIDENCE_TABLES["annotations"]
                if table in after_annotations_tables
            )
            after_annotation_evidence_generation = (
                int(after_annotation_generation[0]) if after_annotation_generation else 0
            )
            after_confirmation_generation_value = (
                int(after_confirmation_generation[0]) if after_confirmation_generation else 0
            )
            after_annotations_structure_generation = (
                int(after_annotation_structure_generation[0])
                if after_annotation_structure_generation else 0
            )
            after_annotations_change = _owner_change_marks(
                database, ("annotations",)
            )
    if (after_materials_revision, after_pool_revision, after_annotation_revision) != (
        material_revision, pool_revision, annotation_revision
    ) or (
        after_material_evidence_generation,
        after_annotation_evidence_generation,
        after_confirmation_generation_value,
    ) != (
        material_evidence_generation,
        annotation_evidence_generation,
        confirmation_generation,
    ) or (
        after_materials_observed, after_annotations_observed,
        after_materials_structure_generation, after_annotations_structure_generation,
        recorded_structure(after_structure),
        recorded_structure(after_annotation_structure),
    ) != (
        materials_observed, annotations_observed,
        materials_structure_generation, annotations_structure_generation,
        materials_recorded, annotations_recorded,
    ) or (
        after_materials_change, after_annotations_change
    ) != (
        materials_change, annotations_change
    ):
        raise U3MigrationError(
            "U3_SNAPSHOT_SOURCE_CHANGED",
            "a source owner changed during the snapshot export",
            detail=(
                f"materials={material_revision}->{after_materials_revision} "
                f"pool={pool_revision}->{after_pool_revision} "
                f"annotations={annotation_revision}->{after_annotation_revision} "
                f"evidence_generations="
                f"({material_evidence_generation},{annotation_evidence_generation},"
                f"{confirmation_generation})->"
                f"({after_material_evidence_generation},"
                f"{after_annotation_evidence_generation},"
                f"{after_confirmation_generation_value})"
                f" structures=({materials_observed},{annotations_observed},"
                f"{materials_structure_generation},"
                f"{annotations_structure_generation})->"
                f"({after_materials_observed},{after_annotations_observed},"
                f"{after_materials_structure_generation},"
                f"{after_annotations_structure_generation})"
            ),
        )
    counts = {f"{store}.{table}": len(rows) for store, tables in stores.items()
              for table, rows in tables.items() if table != "evidence"}
    digests = {f"{store}.{table}": _digest(rows) for store, tables in stores.items()
               for table, rows in tables.items() if table != "evidence"}
    for store, tables in stores.items():
        for table, rows in (tables.get("evidence") or {}).items():
            counts[f"{store}.evidence.{table}"] = len(rows)
            digests[f"{store}.evidence.{table}"] = _digest(rows)
    content_digest = _digest(
        [{"table": name, "digest": value} for name, value in sorted(digests.items())]
    )
    revisions = {
        "materials": material_revision,
        "annotations": annotation_revision,
        "negative_pool": pool_revision,
    }
    # One shape for both the exporter and the importer: the generations come from
    # the owner counters, everything else is recomputed from the exported rows.
    evidence_streams = snapshot_evidence_streams({"stores": stores})
    evidence_streams["materials_evidence"].update({
        "generation": material_evidence_generation,
        "structure_generation": materials_structure_generation,
        "structure_certified": materials_structure_certified,
    })
    evidence_streams["annotations_evidence"].update({
        "generation": annotation_evidence_generation,
        "structure_generation": annotations_structure_generation,
        "structure_certified": annotations_structure_certified,
    })
    evidence_streams["negative_confirmation"].update({
        "generation": confirmation_generation,
        "structure_generation": annotations_structure_generation,
        "structure_certified": annotations_structure_certified,
    })
    change_marks = {
        **materials_change["marks"],
        **annotations_change["marks"],
    }
    change_log_present = {
        "materials": bool(materials_change["present"]),
        "annotations": bool(annotations_change["present"]),
    }
    snapshot_id = _snapshot_identity(
        project_id, content_digest, revisions, evidence_streams
    )
    return {
        "contract_version": CONTRACT_VERSION,
        "project_id": str(project_id),
        "stores": stores,
        "counts": counts,
        "digests": digests,
        "table_state": table_state,
        "schema_versions": {"materials": materials_schema, "annotations": annotations_schema},
        "revisions": revisions,
        "evidence_streams": evidence_streams,
        "change_high_water_marks": change_marks,
        "change_log_present": change_log_present,
        "consistency": "MATERIAL_ANNOTATION_LIFECYCLE_FENCE+REVISION_RECHECK",
        "content_digest": content_digest,
        # Deterministic identity: the same owner state always names the same
        # snapshot, so a replay is recognisable without a random token.
        "snapshot_id": snapshot_id,
        "baseline_id": _baseline_identity(
            snapshot_id, change_marks, change_log_present
        ),
    }


#: The exact v3 DDL this tool applied. Kept verbatim so a v3 database can be
#: validated against its own contract before it is upgraded to v4.
_SCHEMA_V3 = """
CREATE SCHEMA IF NOT EXISTS w3_material_gt;
CREATE TABLE IF NOT EXISTS w3_material_gt.schema_migration (
    version INTEGER PRIMARY KEY, name TEXT NOT NULL, checksum CHAR(64) NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now(), applied_by TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS w3_material_gt.material (
    project_id TEXT NOT NULL, id TEXT NOT NULL, filename TEXT, storage_source_id TEXT,
    storage_type TEXT, object_key TEXT, content_sha256 TEXT, size_bytes BIGINT,
    etag TEXT, processing_status TEXT, box_count INTEGER, annotated INTEGER,
    created_at TEXT, updated_at TEXT, payload JSONB,
    PRIMARY KEY (project_id, id));
CREATE TABLE IF NOT EXISTS w3_material_gt.material_label (
    project_id TEXT NOT NULL, material_id TEXT NOT NULL, label_code TEXT NOT NULL,
    box_count INTEGER, PRIMARY KEY (project_id, material_id, label_code),
    FOREIGN KEY (project_id, material_id)
        REFERENCES w3_material_gt.material(project_id, id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS w3_material_gt.material_annotation_scope (
    project_id TEXT NOT NULL, material_id TEXT NOT NULL, label_code TEXT NOT NULL,
    PRIMARY KEY (project_id, material_id, label_code),
    FOREIGN KEY (project_id, material_id)
        REFERENCES w3_material_gt.material(project_id, id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS w3_material_gt.annotation (
    project_id TEXT NOT NULL, image_id TEXT NOT NULL, annotation_state TEXT NOT NULL,
    version INTEGER NOT NULL, content_digest TEXT NOT NULL, boxes JSONB NOT NULL,
    scope JSONB NOT NULL, created_at TEXT, updated_at TEXT,
    PRIMARY KEY (project_id, image_id));
CREATE TABLE IF NOT EXISTS w3_material_gt.annotation_label_reference (
    project_id TEXT NOT NULL, image_id TEXT NOT NULL, label_code TEXT NOT NULL,
    box_count INTEGER NOT NULL DEFAULT 0, scope_ref INTEGER NOT NULL DEFAULT 0,
    annotation_state TEXT NOT NULL, source_kind TEXT NOT NULL,
    PRIMARY KEY (project_id, image_id, label_code));
CREATE TABLE IF NOT EXISTS w3_material_gt.negative_pool_member (
    project_id TEXT NOT NULL, material_id TEXT NOT NULL, joined_at TEXT,
    PRIMARY KEY (project_id, material_id),
    FOREIGN KEY (project_id, material_id)
        REFERENCES w3_material_gt.material(project_id, id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS w3_material_gt.negative_pool_category (
    project_id TEXT NOT NULL, id TEXT NOT NULL, name TEXT NOT NULL, enabled INTEGER,
    PRIMARY KEY (project_id, id));
-- SQLite's COLLATE NOCASE folds ASCII A-Z only. PostgreSQL lower() follows the
-- database locale, so a UTF-8 cluster would also fold non-ASCII characters and
-- reject names SQLite accepts. COLLATE "C" keeps the fold ASCII-only, which is
-- the equivalent contract independent of the cluster locale.
CREATE UNIQUE INDEX IF NOT EXISTS uq_negative_pool_category_name
    ON w3_material_gt.negative_pool_category(project_id, lower(name COLLATE "C"));
CREATE TABLE IF NOT EXISTS w3_material_gt.negative_pool_link (
    project_id TEXT NOT NULL, material_id TEXT NOT NULL, category_id TEXT NOT NULL,
    PRIMARY KEY (project_id, material_id, category_id),
    FOREIGN KEY (project_id, material_id)
        REFERENCES w3_material_gt.negative_pool_member(project_id, material_id)
        ON DELETE CASCADE,
    FOREIGN KEY (project_id, category_id)
        REFERENCES w3_material_gt.negative_pool_category(project_id, id)
        ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS w3_material_gt.negative_pool_algorithm_member (
    project_id TEXT NOT NULL, algorithm_id TEXT NOT NULL, material_id TEXT NOT NULL,
    joined_at TEXT, PRIMARY KEY (project_id, algorithm_id, material_id),
    FOREIGN KEY (project_id, material_id)
        REFERENCES w3_material_gt.negative_pool_member(project_id, material_id)
        ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS w3_material_gt.evidence_row (
    project_id TEXT NOT NULL, store TEXT NOT NULL, table_name TEXT NOT NULL,
    row_key TEXT NOT NULL, payload JSONB NOT NULL,
    PRIMARY KEY (project_id, store, table_name, row_key));
CREATE TABLE IF NOT EXISTS w3_material_gt.table_state (
    project_id TEXT NOT NULL, store TEXT NOT NULL, table_name TEXT NOT NULL,
    present BOOLEAN NOT NULL, schema_version INTEGER, row_count INTEGER NOT NULL,
    PRIMARY KEY (project_id, store, table_name));
CREATE TABLE IF NOT EXISTS w3_material_gt.store_revision (
    project_id TEXT NOT NULL, store TEXT NOT NULL, revision BIGINT, recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, store));
"""


#: V4 read-side contract. Every object is additive: no business table is rebuilt,
#: no historical evidence changes meaning and a database created directly at v4
#: gets the same objects as an upgraded v3 one.
_SCHEMA_V4_ADDITIONS = """
CREATE TABLE IF NOT EXISTS w3_material_gt.picker_snapshot_state (
    project_id TEXT PRIMARY KEY,
    snapshot_id TEXT NOT NULL,
    content_digest CHAR(64) NOT NULL,
    material_revision BIGINT,
    annotation_revision BIGINT,
    negative_pool_revision BIGINT,
    materials_digest CHAR(64),
    annotations_digest CHAR(64),
    negative_pool_digest CHAR(64),
    negative_confirmation_revision BIGINT NOT NULL,
    negative_confirmation_generation BIGINT NOT NULL DEFAULT 0,
    negative_confirmation_digest CHAR(64),
    revision_vector JSONB NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('READY', 'STALE', 'INCOMPLETE')),
    captured_at TIMESTAMPTZ,
    published_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS w3_material_gt.u3_shadow_import (
    import_id BIGSERIAL PRIMARY KEY,
    project_id TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    snapshot_digest TEXT NOT NULL,
    revision_vector JSONB NOT NULL,
    import_mode TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('APPLIED', 'ALREADY_APPLIED', 'REFUSED', 'FAILED')),
    error_code TEXT,
    detail TEXT,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE INDEX IF NOT EXISTS idx_u3_shadow_import_project
    ON w3_material_gt.u3_shadow_import(project_id, snapshot_digest, outcome);
CREATE TABLE IF NOT EXISTS w3_material_gt.u3_projection_cursor (
    project_id TEXT NOT NULL,
    store TEXT NOT NULL,
    last_applied_seq BIGINT,
    source_revision BIGINT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, store));
-- Derived read-only projection of annotations.task_negative_confirmations. The
-- original row (receipt_id, context_key, evidence_json) stays verbatim in
-- evidence_row, and this table only makes the receipt queryable by context/image.
CREATE TABLE IF NOT EXISTS w3_material_gt.task_negative_confirmation (
    project_id TEXT NOT NULL,
    receipt_id TEXT NOT NULL,
    context_key TEXT NOT NULL,
    image_id TEXT,
    evidence JSONB NOT NULL,
    PRIMARY KEY (project_id, receipt_id));
CREATE INDEX IF NOT EXISTS idx_picker_negative_receipt
    ON w3_material_gt.task_negative_confirmation(project_id, context_key, image_id);
CREATE INDEX IF NOT EXISTS idx_picker_material_order
    ON w3_material_gt.material(project_id, processing_status, created_at, id);
CREATE INDEX IF NOT EXISTS idx_picker_material_source_order
    ON w3_material_gt.material(project_id, storage_source_id, processing_status, created_at, id);
CREATE INDEX IF NOT EXISTS idx_picker_material_label
    ON w3_material_gt.material_label(project_id, label_code, material_id);
CREATE INDEX IF NOT EXISTS idx_picker_material_scope
    ON w3_material_gt.material_annotation_scope(project_id, label_code, material_id);
CREATE INDEX IF NOT EXISTS idx_picker_gt_label
    ON w3_material_gt.annotation_label_reference(project_id, label_code, image_id);
CREATE INDEX IF NOT EXISTS idx_picker_gt_state
    ON w3_material_gt.annotation(project_id, annotation_state, image_id);
CREATE INDEX IF NOT EXISTS idx_picker_pool_joined
    ON w3_material_gt.negative_pool_member(project_id, joined_at, material_id);
CREATE INDEX IF NOT EXISTS idx_picker_pool_category
    ON w3_material_gt.negative_pool_link(project_id, category_id, material_id);
"""

#: The current DDL. A fresh target executes this text; an older target applies
#: ``_SCHEMA_UPGRADES`` one version at a time.
_SCHEMA = _SCHEMA_V3 + _SCHEMA_V4_ADDITIONS


#: The exact v1 DDL this tool once applied. Historical migration rows are
#: validated against *their own* version; validating v1 with the v2 checksum
#: would block every legitimate upgrade (and would bless a tampered record).
_SCHEMA_V1 = """
CREATE SCHEMA IF NOT EXISTS w3_material_gt;
CREATE TABLE IF NOT EXISTS w3_material_gt.schema_migration (
    version INTEGER PRIMARY KEY, name TEXT NOT NULL, checksum CHAR(64) NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now(), applied_by TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS w3_material_gt.material (
    project_id TEXT NOT NULL, id TEXT NOT NULL, filename TEXT, storage_source_id TEXT,
    storage_type TEXT, object_key TEXT, content_sha256 TEXT, size_bytes BIGINT,
    etag TEXT, processing_status TEXT, box_count INTEGER, annotated INTEGER,
    created_at TEXT, updated_at TEXT, payload JSONB,
    PRIMARY KEY (project_id, id));
CREATE TABLE IF NOT EXISTS w3_material_gt.material_label (
    project_id TEXT NOT NULL, material_id TEXT NOT NULL, label_code TEXT NOT NULL,
    box_count INTEGER, PRIMARY KEY (project_id, material_id, label_code),
    FOREIGN KEY (project_id, material_id)
        REFERENCES w3_material_gt.material(project_id, id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS w3_material_gt.material_annotation_scope (
    project_id TEXT NOT NULL, material_id TEXT NOT NULL, label_code TEXT NOT NULL,
    PRIMARY KEY (project_id, material_id, label_code),
    FOREIGN KEY (project_id, material_id)
        REFERENCES w3_material_gt.material(project_id, id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS w3_material_gt.annotation (
    project_id TEXT NOT NULL, image_id TEXT NOT NULL, annotation_state TEXT NOT NULL,
    version INTEGER NOT NULL, content_digest TEXT NOT NULL, boxes JSONB NOT NULL,
    scope JSONB NOT NULL, created_at TEXT, updated_at TEXT,
    PRIMARY KEY (project_id, image_id));
CREATE TABLE IF NOT EXISTS w3_material_gt.annotation_label_reference (
    project_id TEXT NOT NULL, image_id TEXT NOT NULL, label_code TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    PRIMARY KEY (project_id, image_id, label_code, source_kind));
CREATE TABLE IF NOT EXISTS w3_material_gt.negative_pool_member (
    project_id TEXT NOT NULL, material_id TEXT NOT NULL, joined_at TEXT,
    PRIMARY KEY (project_id, material_id),
    FOREIGN KEY (project_id, material_id)
        REFERENCES w3_material_gt.material(project_id, id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS w3_material_gt.negative_pool_category (
    project_id TEXT NOT NULL, id TEXT NOT NULL, name TEXT NOT NULL, enabled INTEGER,
    PRIMARY KEY (project_id, id));
CREATE TABLE IF NOT EXISTS w3_material_gt.negative_pool_link (
    project_id TEXT NOT NULL, material_id TEXT NOT NULL, category_id TEXT NOT NULL,
    PRIMARY KEY (project_id, material_id, category_id),
    FOREIGN KEY (project_id, material_id)
        REFERENCES w3_material_gt.negative_pool_member(project_id, material_id)
        ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS w3_material_gt.negative_pool_algorithm_member (
    project_id TEXT NOT NULL, algorithm_id TEXT NOT NULL, material_id TEXT NOT NULL,
    joined_at TEXT, PRIMARY KEY (project_id, algorithm_id, material_id),
    FOREIGN KEY (project_id, material_id)
        REFERENCES w3_material_gt.negative_pool_member(project_id, material_id)
        ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS w3_material_gt.store_revision (
    project_id TEXT NOT NULL, store TEXT NOT NULL, revision BIGINT, recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, store));
"""


#: The authentic v2 DDL (commit c6a94215). Historical rows are validated
#: against this exact text, never against the current (v3) DDL.
_SCHEMA_V2 = """
CREATE SCHEMA IF NOT EXISTS w3_material_gt;
CREATE TABLE IF NOT EXISTS w3_material_gt.schema_migration (
    version INTEGER PRIMARY KEY, name TEXT NOT NULL, checksum CHAR(64) NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now(), applied_by TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS w3_material_gt.material (
    project_id TEXT NOT NULL, id TEXT NOT NULL, filename TEXT, storage_source_id TEXT,
    storage_type TEXT, object_key TEXT, content_sha256 TEXT, size_bytes BIGINT,
    etag TEXT, processing_status TEXT, box_count INTEGER, annotated INTEGER,
    created_at TEXT, updated_at TEXT, payload JSONB,
    PRIMARY KEY (project_id, id));
CREATE TABLE IF NOT EXISTS w3_material_gt.material_label (
    project_id TEXT NOT NULL, material_id TEXT NOT NULL, label_code TEXT NOT NULL,
    box_count INTEGER, PRIMARY KEY (project_id, material_id, label_code),
    FOREIGN KEY (project_id, material_id)
        REFERENCES w3_material_gt.material(project_id, id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS w3_material_gt.material_annotation_scope (
    project_id TEXT NOT NULL, material_id TEXT NOT NULL, label_code TEXT NOT NULL,
    PRIMARY KEY (project_id, material_id, label_code),
    FOREIGN KEY (project_id, material_id)
        REFERENCES w3_material_gt.material(project_id, id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS w3_material_gt.annotation (
    project_id TEXT NOT NULL, image_id TEXT NOT NULL, annotation_state TEXT NOT NULL,
    version INTEGER NOT NULL, content_digest TEXT NOT NULL, boxes JSONB NOT NULL,
    scope JSONB NOT NULL, created_at TEXT, updated_at TEXT,
    PRIMARY KEY (project_id, image_id));
CREATE TABLE IF NOT EXISTS w3_material_gt.annotation_label_reference (
    project_id TEXT NOT NULL, image_id TEXT NOT NULL, label_code TEXT NOT NULL,
    box_count INTEGER NOT NULL DEFAULT 0, scope_ref INTEGER NOT NULL DEFAULT 0,
    annotation_state TEXT NOT NULL, source_kind TEXT NOT NULL,
    PRIMARY KEY (project_id, image_id, label_code));
CREATE TABLE IF NOT EXISTS w3_material_gt.negative_pool_member (
    project_id TEXT NOT NULL, material_id TEXT NOT NULL, joined_at TEXT,
    PRIMARY KEY (project_id, material_id),
    FOREIGN KEY (project_id, material_id)
        REFERENCES w3_material_gt.material(project_id, id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS w3_material_gt.negative_pool_category (
    project_id TEXT NOT NULL, id TEXT NOT NULL, name TEXT NOT NULL, enabled INTEGER,
    PRIMARY KEY (project_id, id));
CREATE UNIQUE INDEX IF NOT EXISTS uq_negative_pool_category_name
    ON w3_material_gt.negative_pool_category(project_id, lower(name));
CREATE TABLE IF NOT EXISTS w3_material_gt.negative_pool_link (
    project_id TEXT NOT NULL, material_id TEXT NOT NULL, category_id TEXT NOT NULL,
    PRIMARY KEY (project_id, material_id, category_id),
    FOREIGN KEY (project_id, material_id)
        REFERENCES w3_material_gt.negative_pool_member(project_id, material_id)
        ON DELETE CASCADE,
    FOREIGN KEY (project_id, category_id)
        REFERENCES w3_material_gt.negative_pool_category(project_id, id)
        ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS w3_material_gt.negative_pool_algorithm_member (
    project_id TEXT NOT NULL, algorithm_id TEXT NOT NULL, material_id TEXT NOT NULL,
    joined_at TEXT, PRIMARY KEY (project_id, algorithm_id, material_id),
    FOREIGN KEY (project_id, material_id)
        REFERENCES w3_material_gt.negative_pool_member(project_id, material_id)
        ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS w3_material_gt.evidence_row (
    project_id TEXT NOT NULL, store TEXT NOT NULL, table_name TEXT NOT NULL,
    row_key TEXT NOT NULL, payload JSONB NOT NULL,
    PRIMARY KEY (project_id, store, table_name, row_key));
CREATE TABLE IF NOT EXISTS w3_material_gt.table_state (
    project_id TEXT NOT NULL, store TEXT NOT NULL, table_name TEXT NOT NULL,
    present BOOLEAN NOT NULL, schema_version INTEGER, row_count INTEGER NOT NULL,
    PRIMARY KEY (project_id, store, table_name));
CREATE TABLE IF NOT EXISTS w3_material_gt.store_revision (
    project_id TEXT NOT NULL, store TEXT NOT NULL, revision BIGINT, recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, store));
"""


def schema_checksum() -> str:
    return hashlib.sha256(_SCHEMA.encode("utf-8")).hexdigest()


_HISTORICAL_SCHEMAS = {1: _SCHEMA_V1, 2: _SCHEMA_V2, 3: _SCHEMA_V3}


def schema_checksum_for(version: int) -> str:
    """Checksum of the DDL that version actually applied (never the current one)."""
    if version in _HISTORICAL_SCHEMAS:
        return hashlib.sha256(_HISTORICAL_SCHEMAS[version].encode("utf-8")).hexdigest()
    if version == SCHEMA_VERSION:
        return schema_checksum()
    raise U3MigrationError(
        "U3_SCHEMA_VERSION_UNKNOWN", "no checksum contract for this schema version",
        detail=str(version),
    )


#: Structural corrections of the shadow schema itself (no production data lives
#: here). Version 2 corrects the reference-table key, adds the evidence/table
#: state tables and restores the pool constraints.
_SCHEMA_UPGRADES = {
    # v1 -> v2: the typed reference table gains box_count/scope_ref/
    # annotation_state and drops source_kind from its key, so the original rows are
    # first retained verbatim and then mapped; a key that v1 stored twice with
    # different source_kind cannot be mapped losslessly and fails with
    # U3_UPGRADE_REFERENCE_CONFLICT (the primary key rejects it) instead of being
    # silently deduplicated. ``negative_pool_link`` is rebuilt with both foreign
    # keys, so a dangling category reference fails with U3_UPGRADE_LINK_ORPHAN.
    2: (
        """CREATE TABLE IF NOT EXISTS w3_material_gt.annotation_label_reference_legacy (
            project_id TEXT NOT NULL, image_id TEXT NOT NULL, label_code TEXT NOT NULL,
            source_kind TEXT NOT NULL,
            PRIMARY KEY (project_id, image_id, label_code, source_kind))""",
        """INSERT INTO w3_material_gt.annotation_label_reference_legacy
            (project_id, image_id, label_code, source_kind)
           SELECT project_id, image_id, label_code, source_kind
             FROM w3_material_gt.annotation_label_reference
           ON CONFLICT DO NOTHING""",
        """CREATE TABLE w3_material_gt.annotation_label_reference_v2 (
            project_id TEXT NOT NULL, image_id TEXT NOT NULL, label_code TEXT NOT NULL,
            box_count INTEGER NOT NULL DEFAULT 0, scope_ref INTEGER NOT NULL DEFAULT 0,
            annotation_state TEXT NOT NULL, source_kind TEXT NOT NULL,
            PRIMARY KEY (project_id, image_id, label_code))""",
        # The counters never existed in v1, so they keep the historical default 0;
        # the annotation state comes from the trusted formal GT row.
        """INSERT INTO w3_material_gt.annotation_label_reference_v2
            (project_id, image_id, label_code, box_count, scope_ref, annotation_state, source_kind)
           SELECT legacy.project_id, legacy.image_id, legacy.label_code, 0, 0,
                  COALESCE(annotation.annotation_state, 'unannotated'), legacy.source_kind
             FROM w3_material_gt.annotation_label_reference_legacy AS legacy
             LEFT JOIN w3_material_gt.annotation AS annotation
               ON annotation.project_id = legacy.project_id
              AND annotation.image_id = legacy.image_id""",
        "DROP TABLE w3_material_gt.annotation_label_reference",
        """ALTER TABLE w3_material_gt.annotation_label_reference_v2
            RENAME TO annotation_label_reference""",
        """CREATE TABLE w3_material_gt.negative_pool_link_v2 (
            project_id TEXT NOT NULL, material_id TEXT NOT NULL, category_id TEXT NOT NULL,
            PRIMARY KEY (project_id, material_id, category_id),
            FOREIGN KEY (project_id, material_id)
                REFERENCES w3_material_gt.negative_pool_member(project_id, material_id)
                ON DELETE CASCADE,
            FOREIGN KEY (project_id, category_id)
                REFERENCES w3_material_gt.negative_pool_category(project_id, id)
                ON DELETE CASCADE)""",
        """INSERT INTO w3_material_gt.negative_pool_link_v2
            (project_id, material_id, category_id)
           SELECT project_id, material_id, category_id
             FROM w3_material_gt.negative_pool_link""",
        "DROP TABLE w3_material_gt.negative_pool_link",
        """ALTER TABLE w3_material_gt.negative_pool_link_v2 RENAME TO negative_pool_link""",
        _SCHEMA_V2,
    ),
    # v2 -> v3: the category uniqueness fold becomes locale independent (ASCII
    # only, matching SQLite COLLATE NOCASE) and the legacy retention table exists
    # for databases created directly at v2. Only the index is rebuilt.
    3: (
        """CREATE TABLE IF NOT EXISTS w3_material_gt.annotation_label_reference_legacy (
            project_id TEXT NOT NULL, image_id TEXT NOT NULL, label_code TEXT NOT NULL,
            source_kind TEXT NOT NULL,
            PRIMARY KEY (project_id, image_id, label_code, source_kind))""",
        "DROP INDEX IF EXISTS w3_material_gt.uq_negative_pool_category_name",
        """CREATE UNIQUE INDEX IF NOT EXISTS uq_negative_pool_category_name
    ON w3_material_gt.negative_pool_category(project_id, lower(name COLLATE "C"))""",
    ),
    # v3 -> v4: purely additive read-side contract (state, ledger, cursors,
    # confirmation projection and the Picker indexes). No existing table, row or
    # historical evidence is touched, so the upgrade is safe to re-run and a
    # failure rolls the whole migration back.
    4: (_SCHEMA_V4_ADDITIONS,),
}


#: Structural contract of the v4 read-side objects (verified against the real
#: catalog, never inferred from the migration rows).
V4_TABLES = {
    "picker_snapshot_state": (
        "project_id", "snapshot_id", "content_digest", "material_revision",
        "annotation_revision", "negative_pool_revision", "materials_digest",
        "annotations_digest", "negative_pool_digest",
        "negative_confirmation_revision", "negative_confirmation_generation",
        "negative_confirmation_digest", "revision_vector", "status",
        "captured_at", "published_at",
    ),
    "u3_shadow_import": (
        "import_id", "project_id", "snapshot_id", "snapshot_digest",
        "revision_vector", "import_mode", "outcome", "error_code", "detail",
        "imported_at",
    ),
    "u3_projection_cursor": (
        "project_id", "store", "last_applied_seq", "source_revision", "updated_at",
    ),
    "task_negative_confirmation": (
        "project_id", "receipt_id", "context_key", "image_id", "evidence",
    ),
}
#: ``udt_name`` per column: a table with the right column names but the wrong
#: types is not the contract (text vs char(64), int8 vs int4, jsonb vs json).
V4_COLUMN_TYPES = {
    "picker_snapshot_state": {
        "project_id": "text", "snapshot_id": "text", "content_digest": "bpchar",
        "material_revision": "int8", "annotation_revision": "int8",
        "negative_pool_revision": "int8", "materials_digest": "bpchar",
        "annotations_digest": "bpchar", "negative_pool_digest": "bpchar",
        "negative_confirmation_revision": "int8",
        "negative_confirmation_generation": "int8",
        "negative_confirmation_digest": "bpchar", "revision_vector": "jsonb",
        "status": "text", "captured_at": "timestamptz",
        "published_at": "timestamptz",
    },
    "u3_shadow_import": {
        "import_id": "int8", "project_id": "text", "snapshot_id": "text",
        "snapshot_digest": "text", "revision_vector": "jsonb",
        "import_mode": "text", "outcome": "text", "error_code": "text",
        "detail": "text", "imported_at": "timestamptz",
    },
    "u3_projection_cursor": {
        "project_id": "text", "store": "text", "last_applied_seq": "int8",
        "source_revision": "int8", "updated_at": "timestamptz",
    },
    "task_negative_confirmation": {
        "project_id": "text", "receipt_id": "text", "context_key": "text",
        "image_id": "text", "evidence": "jsonb",
    },
}
#: Columns the read contract must never see as NULL.
V4_NOT_NULL = {
    "picker_snapshot_state": (
        "project_id", "snapshot_id", "content_digest",
        "negative_confirmation_revision", "negative_confirmation_generation",
        "revision_vector", "status", "published_at",
    ),
    "u3_shadow_import": (
        "import_id", "project_id", "snapshot_id", "snapshot_digest",
        "revision_vector", "import_mode", "outcome", "imported_at",
    ),
    "u3_projection_cursor": ("project_id", "store", "updated_at"),
    "task_negative_confirmation": (
        "project_id", "receipt_id", "context_key", "evidence",
    ),
}
V4_PRIMARY_KEYS = {
    "picker_snapshot_state": ("project_id",),
    "u3_shadow_import": ("import_id",),
    "u3_projection_cursor": ("project_id", "store"),
    "task_negative_confirmation": ("project_id", "receipt_id"),
}
#: Every CHECK constraint that carries business meaning must still exist with all
#: of its allowed values (a dropped or weakened CHECK changes the contract).
V4_CHECKS = {
    "picker_snapshot_state": ("status", ("READY", "STALE", "INCOMPLETE")),
    "u3_shadow_import": (
        "outcome", ("APPLIED", "ALREADY_APPLIED", "REFUSED", "FAILED"),
    ),
}
#: Index -> (owning table, column order). ``negative_pool_algorithm_member``
#: already has (project_id, algorithm_id, material_id) as its primary key, so no
#: second algorithm-first index exists.
V4_INDEXES = {
    "idx_u3_shadow_import_project": (
        "u3_shadow_import", ("project_id", "snapshot_digest", "outcome"),
    ),
    "idx_picker_negative_receipt": (
        "task_negative_confirmation", ("project_id", "context_key", "image_id"),
    ),
    "idx_picker_material_order": (
        "material", ("project_id", "processing_status", "created_at", "id"),
    ),
    "idx_picker_material_source_order": (
        "material",
        ("project_id", "storage_source_id", "processing_status", "created_at", "id"),
    ),
    "idx_picker_material_label": (
        "material_label", ("project_id", "label_code", "material_id"),
    ),
    "idx_picker_material_scope": (
        "material_annotation_scope", ("project_id", "label_code", "material_id"),
    ),
    "idx_picker_gt_label": (
        "annotation_label_reference", ("project_id", "label_code", "image_id"),
    ),
    "idx_picker_gt_state": (
        "annotation", ("project_id", "annotation_state", "image_id"),
    ),
    "idx_picker_pool_joined": (
        "negative_pool_member", ("project_id", "joined_at", "material_id"),
    ),
    "idx_picker_pool_category": (
        "negative_pool_link", ("project_id", "category_id", "material_id"),
    ),
}


def _check_literal_values(definition: str) -> set[str]:
    """Quoted literals of a CHECK constraint, for an exact allowed-value match."""
    return set(re.findall(r"'([^']*)'", definition))


def _primary_key_columns(cursor, table: str) -> tuple[str, ...]:
    cursor.execute(
        """
        SELECT ARRAY(
                   SELECT a.attname FROM unnest(c.conkey) WITH ORDINALITY AS u(attnum, ord)
                   JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = u.attnum
                   ORDER BY u.ord
               ) AS columns
          FROM pg_constraint c
         WHERE c.conrelid = (%s)::regclass AND c.contype = 'p'
        """,
        (f"{SCHEMA_NAME}.{table}",),
    )
    row = cursor.fetchone()
    return tuple(str(name) for name in row["columns"]) if row else ()


def _v4_structure_findings(cursor) -> list[str]:
    """Compare the real catalog with the v4 contract (PK, type, NULL, CHECK, index)."""
    findings: list[str] = []
    cursor.execute(
        "SELECT table_name,column_name,udt_name,is_nullable FROM information_schema.columns "
        "WHERE table_schema=%s AND table_name = ANY(%s)",
        (SCHEMA_NAME, list(V4_TABLES)),
    )
    columns = {
        (str(row["table_name"]), str(row["column_name"])): (
            str(row["udt_name"]), str(row["is_nullable"]),
        )
        for row in cursor.fetchall()
    }
    for table, spec in V4_COLUMN_TYPES.items():
        for column, expected_type in spec.items():
            info = columns.get((table, column))
            if info is None:
                findings.append(f"v4_column={table}.{column}")
            elif info[0] != expected_type:
                findings.append(f"v4_type={table}.{column}:{info[0]}")
    for table, required in V4_NOT_NULL.items():
        for column in required:
            info = columns.get((table, column))
            if info is not None and info[1] != "NO":
                findings.append(f"v4_not_null={table}.{column}")
    for table, expected_primary in V4_PRIMARY_KEYS.items():
        if table not in {name for (name, _column) in columns}:
            continue  # already reported as a missing v4 table
        actual_primary = _primary_key_columns(cursor, table)
        if actual_primary != expected_primary:
            findings.append(f"v4_primary_key={table}:{actual_primary}")
    cursor.execute(
        "SELECT c.relname AS table_name, pg_get_constraintdef(con.oid) AS definition "
        "FROM pg_constraint con JOIN pg_class c ON c.oid = con.conrelid "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname=%s AND con.contype='c'",
        (SCHEMA_NAME,),
    )
    checks: dict[str, list[str]] = {}
    for row in cursor.fetchall():
        checks.setdefault(str(row["table_name"]), []).append(str(row["definition"]))
    for table, (column, values) in V4_CHECKS.items():
        expected = set(values)
        matching = [
            definition for definition in checks.get(table, [])
            if column in definition
            and _check_literal_values(definition) == expected
        ]
        if not matching:
            findings.append(f"v4_check={table}.{column}")
    cursor.execute(
        "SELECT c.relname AS table_name, i.relname AS index_name, "
        "ix.indisunique AS is_unique, "
        "ARRAY(SELECT a.attname FROM unnest(ix.indkey) WITH ORDINALITY AS u(attnum, ord) "
        "JOIN pg_attribute a ON a.attrelid = ix.indrelid AND a.attnum = u.attnum "
        "ORDER BY u.ord) AS columns "
        "FROM pg_index ix "
        "JOIN pg_class i ON i.oid = ix.indexrelid "
        "JOIN pg_class c ON c.oid = ix.indrelid "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname=%s",
        (SCHEMA_NAME,),
    )
    actual_indexes = {
        str(row["index_name"]): (
            str(row["table_name"]),
            tuple(str(name) for name in row["columns"]),
            bool(row["is_unique"]),
        )
        for row in cursor.fetchall()
    }
    for name, (table, expected_columns) in V4_INDEXES.items():
        actual = actual_indexes.get(name)
        if actual is None:
            findings.append(f"v4_index={name}")
            continue
        if actual[0] != table:
            findings.append(f"v4_index_table={name}:{actual[0]}")
        if actual[1] != tuple(expected_columns):
            findings.append(f"v4_index_columns={name}:{actual[1]}")
        if actual[2]:
            findings.append(f"v4_index_unique={name}")
    return findings


def _assert_target_structure(cursor) -> None:
    """Verify the real PostgreSQL shape, not only the recorded checksums.

    A database upgraded by an earlier build can record v3 while still missing
    ``source_kind`` or the category foreign key. Those states are refused with a
    controlled instruction to rebuild the shadow schema from an authoritative
    SQLite export; nothing is repaired or deleted automatically.
    """
    cursor.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema=%s AND table_name='annotation_label_reference'",
        (SCHEMA_NAME,),
    )
    columns = {str(row["column_name"]) for row in cursor.fetchall()}
    missing = [
        name for name in REQUIRED_COLUMNS["annotation_label_references"]
        if name not in columns
    ]
    cursor.execute(
        """
        SELECT c.confrelid::regclass::text AS target, c.confdeltype AS delete_action,
               c.convalidated AS validated,
               ARRAY(
                   SELECT a.attname FROM unnest(c.conkey) WITH ORDINALITY AS u(attnum, ord)
                   JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = u.attnum
                   ORDER BY u.ord
               ) AS local_columns,
               ARRAY(
                   SELECT a.attname FROM unnest(c.confkey) WITH ORDINALITY AS u(attnum, ord)
                   JOIN pg_attribute a ON a.attrelid = c.confrelid AND a.attnum = u.attnum
                   ORDER BY u.ord
               ) AS remote_columns
          FROM pg_constraint c
         WHERE c.conrelid = (%s)::regclass AND c.contype = 'f'
        """,
        (f"{SCHEMA_NAME}.negative_pool_link",),
    )
    foreign_keys = {
        (
            str(row["target"]),
            str(row["delete_action"]),
            tuple(str(name) for name in row["local_columns"]),
            tuple(str(name) for name in row["remote_columns"]),
            bool(row["validated"]),
        )
        for row in cursor.fetchall()
    }
    expected = {
        (f"{SCHEMA_NAME}.negative_pool_member", "c",
         ("project_id", "material_id"), ("project_id", "material_id"), True),
        (f"{SCHEMA_NAME}.negative_pool_category", "c",
         ("project_id", "category_id"), ("project_id", "id"), True),
    }
    absent = sorted(expected - foreign_keys)
    cursor.execute(
        """
        SELECT ARRAY(
                   SELECT a.attname FROM unnest(c.conkey) WITH ORDINALITY AS u(attnum, ord)
                   JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = u.attnum
                   ORDER BY u.ord
               ) AS columns
          FROM pg_constraint c
         WHERE c.conrelid = (%s)::regclass AND c.contype = 'p'
        """,
        (f"{SCHEMA_NAME}.annotation_label_reference",),
    )
    primary_key = cursor.fetchone()
    primary_columns = (
        tuple(str(name) for name in primary_key["columns"]) if primary_key else ()
    )
    expected_primary = ("project_id", "image_id", "label_code")
    if primary_columns != expected_primary:
        missing = list(missing) + [f"primary_key={primary_columns}"]
    # V4 objects: a migration row alone never proves the read-side contract exists.
    cursor.execute(
        "SELECT table_name, column_name FROM information_schema.columns "
        "WHERE table_schema=%s AND table_name = ANY(%s)",
        (SCHEMA_NAME, list(V4_TABLES)),
    )
    v4_columns: dict[str, set[str]] = {}
    for row in cursor.fetchall():
        v4_columns.setdefault(str(row["table_name"]), set()).add(str(row["column_name"]))
    for table in V4_TABLES:
        if table not in v4_columns:
            missing = list(missing) + [f"v4_table={table}"]
    # PKs, column types, NOT NULL, CHECK constraints, index table/column order.
    missing = list(missing) + _v4_structure_findings(cursor)
    if missing or absent:
        raise U3MigrationError(
            "U3_SCHEMA_STRUCTURE_INVALID",
            "the shadow schema was recorded but its real structure is incomplete",
            detail=(
                f"missing_columns={missing} missing_foreign_keys={absent}; "
                "rebuild w3_material_gt from an authoritative SQLite export "
                "(u3_shadow_cli export then import); no automatic repair is attempted"
            ),
        )


def ensure_schema(connection) -> dict[str, Any]:
    from psycopg.rows import dict_row

    with connection.transaction():
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"{SCHEMA_NAME}:schema",))
            cursor.execute(
                "SELECT to_regclass(%s) AS present", (f"{SCHEMA_NAME}.schema_migration",)
            )
            present_row = cursor.fetchone()
            present = bool(present_row) and present_row["present"] is not None
            version = 0
            if present:
                cursor.execute(
                    f"SELECT max(version) AS version FROM {SCHEMA_NAME}.schema_migration"
                )
                row = cursor.fetchone()
                version = int(row["version"] or 0) if row else 0
            if version > SCHEMA_VERSION:
                raise U3MigrationError(
                    "U3_SCHEMA_NEWER_THAN_TOOL",
                    "the shadow schema is newer than this tool",
                    detail=f"database={version} tool={SCHEMA_VERSION}",
                )
            if present:
                cursor.execute(
                    f"SELECT version,checksum FROM {SCHEMA_NAME}.schema_migration ORDER BY version"
                )
                for row in cursor.fetchall():
                    recorded = int(row["version"])
                    # Every applied row is validated against ITS OWN version
                    # contract; v1 must never be validated with the v2 checksum.
                    expected = schema_checksum_for(recorded)
                    if str(row["checksum"]) != expected:
                        raise U3MigrationError(
                            "U3_SCHEMA_CHECKSUM_MISMATCH",
                            "an applied shadow migration no longer matches this tool",
                            detail=f"version={recorded}",
                        )
            if version < SCHEMA_VERSION:
                if version == 0:
                    statements: tuple[str, ...] = (_SCHEMA,)
                else:
                    statements = ()
                    for target in range(version + 1, SCHEMA_VERSION + 1):
                        if target not in _SCHEMA_UPGRADES:
                            raise U3MigrationError(
                                "U3_SCHEMA_UPGRADE_PATH_MISSING",
                                "no explicit upgrade path from this version",
                                detail=f"from={version} to={target}",
                            )
                        statements += _SCHEMA_UPGRADES[target]
                applied_versions = (
                    [SCHEMA_VERSION] if version == 0
                    else list(range(version + 1, SCHEMA_VERSION + 1))
                )
                import psycopg

                try:
                    for statement in statements:
                        for part in [piece for piece in statement.split(";") if piece.strip()]:
                            cursor.execute(part)
                except psycopg.errors.UniqueViolation as error:
                    raise U3MigrationError(
                        "U3_UPGRADE_REFERENCE_CONFLICT",
                        "a v1 reference key has several source kinds and cannot be mapped",
                        detail=str(error),
                    ) from error
                except psycopg.errors.ForeignKeyViolation as error:
                    raise U3MigrationError(
                        "U3_UPGRADE_LINK_ORPHAN",
                        "a v1 pool link references a missing member or category",
                        detail=str(error),
                    ) from error
                if version == 1:
                    cursor.execute(
                        f"SELECT (SELECT count(*) FROM {SCHEMA_NAME}.annotation_label_reference_legacy) "
                        f"AS legacy, (SELECT count(*) FROM {SCHEMA_NAME}.annotation_label_reference) AS typed"
                    )
                    migrated = cursor.fetchone()
                    if int(migrated["legacy"]) != int(migrated["typed"]):
                        raise U3MigrationError(
                            "U3_UPGRADE_REFERENCE_LOSS",
                            "the reference upgrade lost rows",
                            detail=f"legacy={migrated['legacy']} typed={migrated['typed']}",
                        )
                    cursor.execute(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema=%s AND table_name='annotation_label_reference'",
                        (SCHEMA_NAME,),
                    )
                    columns = {str(row["column_name"]) for row in cursor.fetchall()}
                    missing = [
                        name for name in REQUIRED_COLUMNS["annotation_label_references"]
                        if name not in columns
                    ]
                    if missing:
                        raise U3MigrationError(
                            "U3_UPGRADE_REFERENCE_SCHEMA_INVALID",
                            "the upgraded reference table does not match the v2 contract",
                            detail=f"missing={missing}",
                        )
                    # The counters were never stored by v1 and the state may come
                    # from the 'unannotated' fallback: this target is NOT complete
                    # until the authoritative SQLite owner is imported in full.
                    cursor.execute(
                        f"INSERT INTO {SCHEMA_NAME}.store_revision(project_id,store,revision) "
                        "SELECT DISTINCT project_id, %s, 0 "
                        f"FROM {SCHEMA_NAME}.annotation_label_reference_legacy "
                        "ON CONFLICT (project_id,store) DO NOTHING",
                        (LEGACY_REFERENCE_PENDING_STORE,),
                    )
                for applied in applied_versions:
                    if applied == 0:
                        continue
                    cursor.execute(
                        f"INSERT INTO {SCHEMA_NAME}.schema_migration"
                        "(version,name,checksum,applied_by) VALUES(%s,%s,%s,%s) "
                        "ON CONFLICT (version) DO UPDATE SET checksum=EXCLUDED.checksum, "
                        "applied_at=now()",
                        (
                            applied,
                            f"u3-material-gt-v{applied}",
                            schema_checksum_for(applied),
                            "u3-shadow",
                        ),
                    )
            _assert_target_structure(cursor)

    return {"schema": SCHEMA_NAME, "version": SCHEMA_VERSION}


def _material_store_rows(stores: Mapping[str, Any], name: str) -> list[Mapping[str, Any]]:
    return list((stores.get("materials") or {}).get(name) or [])


def material_stores_links(stores: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return _material_store_rows(stores, "negative_pool_links")


def material_stores_algo(stores: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return _material_store_rows(stores, "negative_pool_algorithm_members")


def material_stores_pool(stores: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return _material_store_rows(stores, "negative_pool_members")


def material_stores_cats(stores: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return _material_store_rows(stores, "negative_pool_categories")


def material_stores_scopes(stores: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return _material_store_rows(stores, "material_annotation_scopes")


def material_stores_labels(stores: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return _material_store_rows(stores, "material_labels")


def _delete_absent(cursor, schema: str, table: str, project_id: str,
                   key_columns: tuple[str, ...], values: list[tuple[Any, ...]]) -> None:
    """Delete project rows whose key is not in the snapshot (bounded batches)."""
    cursor.execute("CREATE TEMP TABLE IF NOT EXISTS u3_keep (k1 text, k2 text, PRIMARY KEY (k1, k2))")
    cursor.execute("DELETE FROM u3_keep")
    for value in values:
        cursor.execute(
            "INSERT INTO u3_keep VALUES (%s,%s) ON CONFLICT DO NOTHING",
            (str(value[0]), str(value[1]) if len(value) > 1 else ""),
        )
    if len(key_columns) == 1:
        condition = "t.%s::text NOT IN (SELECT k1 FROM u3_keep)" % key_columns[0]
    else:
        condition = ("NOT EXISTS (SELECT 1 FROM u3_keep AS k WHERE k.k1=t.%s::text "
                     "AND k.k2=t.%s::text)") % (key_columns[0], key_columns[1])
    cursor.execute(f"DELETE FROM {schema}.{table} AS t WHERE t.project_id=%s AND {condition}",
                   (project_id,))


def evidence_namespace_error(snapshot: Mapping[str, Any]) -> str | None:
    """Reject any evidence structure outside the ten historical tables.

    Used by both the import boundary (all modes, all projects) and the pending
    completeness gate, so unknown evidence can never reach ``evidence_row``.
    """
    stores = snapshot.get("stores") or {}
    counts = snapshot.get("counts") or {}
    digests = snapshot.get("digests") or {}
    allowed = {
        f"{store}.evidence.{table}"
        for store, tables in EVIDENCE_TABLES.items()
        for table in tables
    }
    for source_name, source in (("counts", counts), ("digests", digests)):
        stray = [
            name for name in (source or {})
            if ".evidence." in str(name) and name not in allowed
        ]
        if stray:
            return f"unknown_{source_name}:{','.join(sorted(stray))}"
    for store, payload in stores.items():
        if not isinstance(payload, dict):
            return f"store_payload:{store}"
        if "evidence" not in payload:
            continue
        evidence = payload.get("evidence")
        if store not in EVIDENCE_TABLES:
            return f"unknown_store:{store}"
        if not isinstance(evidence, dict):
            return f"evidence_shape:{store}"
        for table, rows in evidence.items():
            if table not in EVIDENCE_TABLES[store]:
                return f"unknown_table:{store}.{table}"
            if not isinstance(rows, list):
                return f"evidence_table_type:{store}.{table}"
    return None


def pending_clear_eligible(snapshot: Mapping[str, Any], project_id: str) -> tuple[bool, str]:
    """Only a provably complete, self-consistent export may clear the marker.

    The trust chain is: ``export_project_snapshot`` (SQLite owners read inside the
    lifecycle fence with a revision re-check) produces the snapshot, and this
    module's import applies it. A hand-built mapping can fake the fields, so the
    import cannot prove provenance by itself - it only proves completeness and
    content consistency. Callers that clear the marker must come through the
    documented export -> import path.
    """
    if str(snapshot.get("contract_version") or "") != CONTRACT_VERSION:
        return False, "contract_version"
    if str(snapshot.get("project_id") or "") != str(project_id):
        return False, "project_id"
    consistency = str(snapshot.get("consistency") or "")
    if not consistency.startswith("MATERIAL_ANNOTATION_LIFECYCLE_FENCE"):
        return False, "consistency"
    stores = snapshot.get("stores") or {}
    state = snapshot.get("table_state") or {}
    counts = snapshot.get("counts") or {}
    digests = snapshot.get("digests") or {}
    for store, tables in REQUIRED_TABLES.items():
        for table in tables:
            entry = state.get(f"{store}.{table}")
            if not entry or entry.get("present") is not True:
                return False, f"table_state:{store}.{table}"
    for store, mapping in (("materials", _MATERIAL_TABLES), ("annotations", _ANNOTATION_TABLES)):
        for name in mapping:
            rows = (stores.get(store) or {}).get(name)
            if not isinstance(rows, list):
                return False, f"data:{store}.{name}"
            key = f"{store}.{name}"
            if int((counts or {}).get(key, -1)) != len(rows):
                return False, f"count:{key}"
            if (digests or {}).get(key) != _digest(rows):
                return False, f"digest:{key}"
    namespace_error = evidence_namespace_error(snapshot)
    if namespace_error:
        return False, f"evidence_namespace:{namespace_error}"
    for store, tables in EVIDENCE_TABLES.items():
        evidence = (stores.get(store) or {}).get("evidence") or {}
        for table in tables:
            name = f"{store}.{table}"
            key = f"{store}.evidence.{table}"
            entry = state.get(name)
            if not entry or "present" not in entry:
                return False, f"evidence_state:{name}"
            present = entry.get("present")
            if not isinstance(present, bool):
                return False, f"evidence_present_type:{name}"
            rows = evidence.get(table)
            if present:
                if not isinstance(rows, list):
                    return False, f"evidence_missing:{key}"
                if int((counts or {}).get(key, -1)) != len(rows):
                    return False, f"evidence_count:{key}"
                if (digests or {}).get(key) != _digest(rows):
                    return False, f"evidence_digest:{key}"
                row_count = entry.get("row_count")
                if isinstance(row_count, bool) or not isinstance(row_count, int) or row_count != len(rows):
                    return False, f"evidence_row_count:{key}"
            else:
                row_count = entry.get("row_count")
                if "row_count" not in entry or isinstance(row_count, bool) or not isinstance(row_count, int):
                    return False, f"evidence_absent_row_count_type:{name}"
                if row_count != 0:
                    return False, f"evidence_absent_row_count:{name}"
                if table in evidence or key in (counts or {}) or key in (digests or {}):
                    return False, f"evidence_absent_fabricated:{key}"
    expected_content = _digest(
        [{"table": name, "digest": value} for name, value in sorted(digests.items())]
    )
    if str(snapshot.get("content_digest") or "") != expected_content:
        return False, "content_digest"
    revisions = snapshot.get("revisions") or {}
    for store in ("materials", "annotations", "negative_pool"):
        value = revisions.get(store)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return False, f"revision:{store}"
    return True, "complete"


#: Read-side revision streams. Only the tables below are covered by a monotonic
#: owner revision. Historical evidence and ``table_state`` may change without one,
#: so they never participate in the regression / same-revision-digest comparison.
REVISION_STORES = {
    "materials": (
        "materials.materials", "materials.material_labels",
        "materials.material_annotation_scopes",
    ),
    "annotations": (
        "annotations.annotations", "annotations.annotation_label_references",
    ),
    "negative_pool": (
        "materials.negative_pool_members", "materials.negative_pool_categories",
        "materials.negative_pool_links", "materials.negative_pool_algorithm_members",
    ),
}

#: Policy refusals worth an audit row. They happen after the target schema exists,
#: so the ledger insert itself is safe; every other failure rolls back completely
#: (including the ledger row), which is the atomicity contract.
REFUSAL_LEDGER_CODES = frozenset({
    "U3_SNAPSHOT_INTEGRITY_FAILED",
    "U3_SNAPSHOT_REVISION_REGRESSION",
    "U3_SNAPSHOT_REVISION_DIVERGED",
    "U3_SNAPSHOT_STRUCTURE_REGRESSION",
    "U3_SNAPSHOT_STRUCTURE_UNVERIFIED",
})

_STATE_COLUMNS = (
    "material_revision", "annotation_revision", "negative_pool_revision",
    "materials_digest", "annotations_digest", "negative_pool_digest",
    "negative_confirmation_revision", "negative_confirmation_generation",
    "negative_confirmation_digest", "content_digest", "snapshot_id", "status",
    "revision_vector",
)

#: Owner-side generation keys, owned by the two SQLite repositories.
MATERIAL_EVIDENCE_GENERATION_KEY = "evidence_generation"
ANNOTATION_EVIDENCE_GENERATION_KEY = "evidence_generation"
CONFIRMATION_GENERATION_KEY = "task_negative_confirmation_generation"
MATERIAL_EVIDENCE_STRUCTURE_KEY = "evidence_structure"
ANNOTATION_EVIDENCE_STRUCTURE_KEY = "evidence_structure"
EVIDENCE_STRUCTURE_GENERATION_KEY = "evidence_structure_generation"

#: Evidence streams that have no monotonic Owner revision of their own and are
#: therefore protected by their Owner generation plus a content digest. The
#: task-confirmation stream is checked first: it is the most specific one.
EVIDENCE_STREAMS = (
    "negative_confirmation", "annotations_evidence", "materials_evidence",
)


def _snapshot_identity(
    project_id: str, content_digest: str, revisions: Mapping[str, Any],
    streams: Mapping[str, Any] | None = None,
) -> str:
    """Deterministic snapshot id: the same payload always names the same snapshot.

    Determinism matters because an export must stay byte-identical when nothing
    changed, and because a replay must be recognisable without a random token.
    """
    body = json.dumps(
        {
            "project_id": str(project_id),
            "contract_version": CONTRACT_VERSION,
            "content_digest": str(content_digest),
            "revisions": dict(revisions or {}),
            "evidence_streams": dict(streams or {}),
        },
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "u3-shadow:" + body))


def _owner_change_marks(database, streams: tuple[str, ...]) -> dict[str, Any]:
    """Read B1 change-log high-water marks inside the caller's read transaction.

    An owner database created before P3-B1 has no log table. That is recorded as
    ``present=False`` and a zero baseline; it is never interpreted as "no data".
    """
    table = database.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='owner_change_meta'"
    ).fetchone()
    if table is None:
        return {"present": False, "marks": {stream: 0 for stream in streams}}
    rows = {
        str(row[0]): int(row[1])
        for row in database.execute(
            "SELECT stream,last_sequence FROM owner_change_meta"
        ).fetchall()
    }
    return {
        "present": True,
        "marks": {stream: int(rows.get(stream, 0)) for stream in streams},
    }


def _baseline_identity(
    snapshot_id: str, marks: Mapping[str, Any], present: Mapping[str, Any],
) -> str:
    body = json.dumps(
        {
            "snapshot_id": str(snapshot_id),
            "change_high_water_marks": dict(marks or {}),
            "change_log_present": dict(present or {}),
        },
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "u3-baseline:" + body))


def _declared_snapshot_id(snapshot: Mapping[str, Any]) -> str:
    declared = str(snapshot.get("snapshot_id") or "")
    if declared:
        return declared
    return _snapshot_identity(
        str(snapshot.get("project_id") or ""),
        str(snapshot.get("content_digest") or ""),
        snapshot.get("revisions") or {},
        snapshot.get("evidence_streams") or {},
    )


def evidence_stream_digest(stores: Mapping[str, Any], store: str) -> str:
    """Stable digest of one store's historical evidence rows."""
    evidence = (stores.get(store) or {}).get("evidence") or {}
    return _digest(
        [{"table": name, "digest": _digest(evidence[name])} for name in sorted(evidence)]
    )


def evidence_stream_tables(stores: Mapping[str, Any], store: str) -> list[str]:
    """Evidence tables the snapshot actually carries (structure, not content)."""
    evidence = (stores.get(store) or {}).get("evidence") or {}
    return sorted(str(name) for name in evidence)


def recorded_structure(row) -> list[str] | None:
    """Parse an owner's persisted evidence-table set (``None`` = never recorded)."""
    if row is None:
        return None
    try:
        value = json.loads(row[0])
    except (TypeError, ValueError):
        return None
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return None
    return sorted(value)


def _confirmation_evidence(stores: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return (
        (((stores.get("annotations") or {}).get("evidence") or {})
         .get("task_negative_confirmations")) or []
    )


def snapshot_evidence_streams(
    snapshot: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    """Owner generation + content digest for every mutable evidence stream.

    Generations are Owner-side counters (0 for a snapshot exported before the
    counter existed); digests are always recomputed from the rows, so a stale or
    tampered snapshot cannot claim a generation it did not observe. The structure
    version and its certified flag travel with the stream, so a table lifecycle
    change is provable instead of being inferred from the table set.
    """
    stores = snapshot.get("stores") or {}
    declared = snapshot.get("evidence_streams") or {}

    def declared_value(name: str, key: str) -> Any:
        return (declared.get(name) or {}).get(key)

    def generation(name: str) -> int:
        value = declared_value(name, "generation")
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
        return 0

    def structure_generation(name: str) -> int:
        value = declared_value(name, "structure_generation")
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
        return 0

    def structure_certified(name: str) -> bool:
        return bool(declared_value(name, "structure_certified"))

    confirmations = _confirmation_evidence(stores)
    annotation_structure_generation = structure_generation("annotations_evidence")
    annotation_structure_certified = structure_certified("annotations_evidence")
    return {
        "materials_evidence": {
            "generation": generation("materials_evidence"),
            "structure_generation": structure_generation("materials_evidence"),
            "structure_certified": structure_certified("materials_evidence"),
            "digest": evidence_stream_digest(stores, "materials"),
            "tables": evidence_stream_tables(stores, "materials"),
        },
        "annotations_evidence": {
            "generation": generation("annotations_evidence"),
            "structure_generation": annotation_structure_generation,
            "structure_certified": annotation_structure_certified,
            "digest": evidence_stream_digest(stores, "annotations"),
            "tables": evidence_stream_tables(stores, "annotations"),
        },
        "negative_confirmation": {
            "generation": generation("negative_confirmation"),
            "structure_generation": annotation_structure_generation,
            "structure_certified": annotation_structure_certified,
            "revision": len(confirmations),
            "digest": _digest(confirmations),
            "tables": (
                ["task_negative_confirmations"]
                if ((stores.get("annotations") or {}).get("evidence") or {})
                .get("task_negative_confirmations") is not None else []
            ),
        },
    }


def _count_matches(value: Any, length: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value == length


def snapshot_integrity_error(snapshot: Mapping[str, Any]) -> str | None:
    """Recompute the declared counts/digests instead of trusting them.

    Returns a stable reason (or ``None``). A snapshot that claims integrity but
    does not match its own rows is refused before anything is written; a snapshot
    with no integrity metadata at all is reported as ``metadata_missing`` so the
    full-import path can require it.
    """
    digests = snapshot.get("digests")
    counts = snapshot.get("counts")
    if not isinstance(digests, dict) or not isinstance(counts, dict):
        return "metadata_missing"
    stores = snapshot.get("stores") or {}
    for store, payload in stores.items():
        if not isinstance(payload, dict):
            return f"store_payload:{store}"
        for table, rows in payload.items():
            if table == "evidence":
                if not isinstance(rows, dict):
                    return f"evidence_shape:{store}"
                for name, items in rows.items():
                    key = f"{store}.evidence.{name}"
                    if not isinstance(items, list):
                        return f"shape:{key}"
                    if not _count_matches(counts.get(key), len(items)):
                        return f"count:{key}"
                    if digests.get(key) != _digest(items):
                        return f"digest:{key}"
                continue
            key = f"{store}.{table}"
            if not isinstance(rows, list):
                return f"shape:{key}"
            if not _count_matches(counts.get(key), len(rows)):
                return f"count:{key}"
            if digests.get(key) != _digest(rows):
                return f"digest:{key}"
    expected = _digest(
        [{"table": name, "digest": value} for name, value in sorted(digests.items())]
    )
    if str(snapshot.get("content_digest") or "") != expected:
        return "content_digest"
    if str(snapshot.get("snapshot_id") or "") and str(snapshot["snapshot_id"]) != (
        _snapshot_identity(
            str(snapshot.get("project_id") or ""), expected,
            snapshot.get("revisions") or {}, snapshot_evidence_streams(snapshot),
        )
    ):
        return "snapshot_id"
    return None


def _store_digest(digests: Mapping[str, Any], store: str) -> str | None:
    tables = REVISION_STORES[store]
    if any(not isinstance(digests.get(name), str) for name in tables):
        return None
    return _digest([{"table": name, "digest": digests[name]} for name in sorted(tables)])


def _revision_vector(
    revisions: Mapping[str, Any], store_digests: Mapping[str, Any],
    streams: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    vector: dict[str, dict[str, Any]] = {}
    for store in REVISION_STORES:
        revision = (revisions or {}).get(store)
        if isinstance(revision, int) and not isinstance(revision, bool):
            vector[store] = {"revision": revision, "digest": (store_digests or {}).get(store)}
    for name, stream in (streams or {}).items():
        vector[name] = dict(stream)
    return vector


def _confirmation_projection(snapshot: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Derive the queryable confirmation rows from the verbatim evidence rows.

    The original ``(receipt_id, context_key, evidence_json)`` row is already in the
    snapshot as evidence; this projection never invents a receipt and never becomes
    the owner of the confirmation.
    """
    annotations = (snapshot.get("stores") or {}).get("annotations") or {}
    rows = (annotations.get("evidence") or {}).get("task_negative_confirmations") or []
    projection: list[dict[str, Any]] = []
    for item in rows:
        payload = item.get("payload") if isinstance(item, dict) else None
        if not isinstance(payload, dict):
            raise U3MigrationError(
                "U3_NEGATIVE_CONFIRMATION_INVALID",
                "a task negative confirmation has no verbatim payload",
                detail="payload",
            )
        receipt = payload.get("receipt_id")
        context = payload.get("context_key")
        if not isinstance(receipt, str) or not receipt:
            raise U3MigrationError(
                "U3_NEGATIVE_CONFIRMATION_INVALID",
                "a task negative confirmation has no receipt id",
                detail="receipt_id",
            )
        if not isinstance(context, str) or not context:
            raise U3MigrationError(
                "U3_NEGATIVE_CONFIRMATION_INVALID",
                "a task negative confirmation has no context key",
                detail=f"receipt={receipt}",
            )
        raw = payload.get("evidence_json")
        if isinstance(raw, (str, bytes, bytearray)):
            try:
                evidence = json.loads(raw)
            except (TypeError, ValueError) as error:
                raise U3MigrationError(
                    "U3_NEGATIVE_CONFIRMATION_INVALID",
                    "a task negative confirmation is not valid JSON",
                    detail=f"receipt={receipt}",
                ) from error
        else:
            evidence = raw
        if not isinstance(evidence, dict):
            raise U3MigrationError(
                "U3_NEGATIVE_CONFIRMATION_INVALID",
                "a task negative confirmation is not a JSON object",
                detail=f"receipt={receipt}",
            )
        image_id = evidence.get("image_id")
        projection.append({
            "receipt_id": receipt,
            "context_key": context,
            "image_id": None if image_id is None else str(image_id),
            "evidence": evidence,
        })
    projection.sort(key=lambda row: row["receipt_id"])
    return projection


def _read_snapshot_state(cursor, project_id: str) -> dict[str, Any] | None:
    cursor.execute(
        f"SELECT {','.join(_STATE_COLUMNS)} FROM {SCHEMA_NAME}.picker_snapshot_state "
        "WHERE project_id=%s",
        (project_id,),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    return dict(zip(_STATE_COLUMNS, row))


def _read_legacy_revisions(cursor, project_id: str) -> dict[str, Any]:
    """Pre-v4 targets record their high-water marks only in ``store_revision``."""
    cursor.execute(
        f"SELECT store, revision FROM {SCHEMA_NAME}.store_revision WHERE project_id=%s",
        (project_id,),
    )
    return {
        str(store): revision for store, revision in cursor.fetchall()
        if str(store) != LEGACY_REFERENCE_PENDING_STORE and revision is not None
    }


def _insert_import_ledger(
    cursor, *, project_id: str, snapshot_id: str, snapshot_digest: str,
    revision_vector: Mapping[str, Any], mode: str, outcome: str,
    error_code: str | None = None, detail: str = "",
) -> None:
    cursor.execute(
        f"INSERT INTO {SCHEMA_NAME}.u3_shadow_import(project_id,snapshot_id,"
        "snapshot_digest,revision_vector,import_mode,outcome,error_code,detail) "
        "VALUES(%s,%s,%s,%s::jsonb,%s,%s,%s,%s)",
        (
            project_id, snapshot_id, snapshot_digest,
            json.dumps(_canonical(dict(revision_vector)), ensure_ascii=False, sort_keys=True),
            mode, outcome, error_code, detail or None,
        ),
    )


def _record_refusal(connection, snapshot: Mapping[str, Any], mode: str,
                    error: U3MigrationError) -> None:
    """Best-effort audit row for a policy refusal (never for a rolled-back write)."""
    project_id = str(snapshot.get("project_id") or "")
    if not project_id:
        return
    try:
        with connection.transaction():
            with connection.cursor() as cursor:
                _insert_import_ledger(
                    cursor,
                    project_id=project_id,
                    snapshot_id=_declared_snapshot_id(snapshot),
                    snapshot_digest=str(snapshot.get("content_digest") or ""),
                    revision_vector=_revision_vector(
                        snapshot.get("revisions") or {}, snapshot.get("digests") or {}
                    ),
                    mode=mode,
                    outcome="REFUSED",
                    error_code=error.code,
                    detail=error.detail,
                )
    except Exception:  # noqa: BLE001 - the refusal itself must not be masked
        return


def import_project_snapshot(
    connection, snapshot: Mapping[str, Any], *, mode: str = "full",
    status_override: str | None = None,
) -> dict[str, Any]:
    """Import one snapshot in a single transaction.

    ``mode="full"`` (default) makes the target project *equal* to the snapshot:
    rows of this project that the snapshot no longer contains are deleted
    (children before parents) and everything else is upserted. ``incremental``
    only upserts. Both are idempotent, both are scoped to one ``project_id`` and
    both roll back completely on any failure.

    Identity contract (v4): a snapshot that claims integrity must match its own
    counts/digests; an owner revision may never regress; the same revision with a
    different projection digest is refused; a replay of an already applied full
    snapshot returns ``outcome="ALREADY_APPLIED"`` without touching business rows.
    The published state, the projection cursors and the ledger row are committed in
    the same transaction as the data, so a partial import cannot advance them.
    """
    ensure_schema(connection)
    try:
        return _apply_project_snapshot(
            connection, snapshot, str(mode), status_override=status_override
        )
    except U3MigrationError as error:
        if error.code in REFUSAL_LEDGER_CODES:
            _record_refusal(connection, snapshot, str(mode), error)
        raise


def _apply_project_snapshot(
    connection, snapshot: Mapping[str, Any], mode: str,
    *, status_override: str | None = None,
) -> dict[str, Any]:
    """Apply one validated snapshot inside a single PostgreSQL transaction."""
    if str(mode) not in {"full", "incremental"}:
        raise U3MigrationError(
            "U3_IMPORT_MODE_INVALID", "unsupported import mode", detail=str(mode)
        )
    if str(snapshot.get("contract_version") or "") != CONTRACT_VERSION:
        raise U3MigrationError(
            "U3_SNAPSHOT_CONTRACT_MISMATCH", "snapshot contract does not match",
            detail=str(snapshot.get("contract_version")),
        )
    project_id = str(snapshot.get("project_id") or "")
    if not project_id:
        raise U3MigrationError("U3_SNAPSHOT_PROJECT_MISSING", "snapshot has no project id")
    stores = snapshot.get("stores") or {}
    materials = (stores.get("materials") or {}).get("materials") or []
    counters = {"materials": 0, "labels": 0, "scopes": 0, "annotations": 0,
                "references": 0, "pool_members": 0, "pool_categories": 0,
                "pool_links": 0, "pool_algorithm_members": 0}
    from psycopg.rows import tuple_row

    # Every read below is positional, so the cursor pins the tuple factory
    # explicitly: callers may connect with ``dict_row`` (the operator CLI does).
    with connection.transaction():
        with connection.cursor(row_factory=tuple_row) as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"u3_import:{project_id}",))
            cursor.execute(
                f"SELECT 1 AS pending FROM {SCHEMA_NAME}.store_revision "
                "WHERE project_id=%s AND store=%s",
                (project_id, LEGACY_REFERENCE_PENDING_STORE),
            )
            project_pending = cursor.fetchone() is not None
            namespace_error = evidence_namespace_error(snapshot)
            if namespace_error:
                code = (
                    "U3_PENDING_IMPORT_INCOMPLETE"
                    if project_pending
                    else "U3_EVIDENCE_NAMESPACE_INVALID"
                )
                raise U3MigrationError(
                    code,
                    "the snapshot carries evidence outside the historical tables",
                    detail=f"reason={namespace_error}",
                )
            if mode == "full":
                if project_pending:
                    eligible, reason = pending_clear_eligible(snapshot, project_id)
                    if not eligible:
                        # No DELETE/INSERT/UPDATE has run yet, so the transaction
                        # leaves every business row, table_state, revision and
                        # evidence row of this project untouched.
                        raise U3MigrationError(
                            "U3_PENDING_IMPORT_INCOMPLETE",
                            "a pending project requires a complete authoritative snapshot",
                            detail=f"reason={reason}",
                        )
            # Snapshot integrity is verified before any write. A full import must
            # declare it (it claims to be the authoritative state of the project).
            if mode == "full" or isinstance(snapshot.get("digests"), dict):
                integrity = snapshot_integrity_error(snapshot)
                if integrity:
                    raise U3MigrationError(
                        "U3_SNAPSHOT_INTEGRITY_FAILED",
                        "the snapshot does not match its own identity",
                        detail=f"reason={integrity}",
                    )
            if mode == "full" and not project_pending:
                # Every full import (not only a legacy-pending one) proves the
                # snapshot is complete BEFORE the first destructive write: the
                # same contract the pending gate uses. A snapshot that cannot
                # prove completeness must never delete first and be labelled
                # INCOMPLETE afterwards.
                complete, reason = pending_clear_eligible(snapshot, project_id)
                if not complete:
                    raise U3MigrationError(
                        "U3_SNAPSHOT_INCOMPLETE",
                        "a full import requires a complete authoritative snapshot",
                        detail=f"reason={reason}",
                    )
            revisions = snapshot.get("revisions") or {}
            store_digests = {
                store: _store_digest(snapshot.get("digests") or {}, store)
                for store in REVISION_STORES
            }
            streams = snapshot_evidence_streams(snapshot)
            revision_vector = _revision_vector(revisions, store_digests, streams)
            prior_state = _read_snapshot_state(cursor, project_id)
            prior_vector = {}
            if prior_state is not None:
                prior_vector = prior_state["revision_vector"] or {}
                if isinstance(prior_vector, str):
                    prior_vector = json.loads(prior_vector)
            if prior_state is None:
                # A pre-v4 target only has store_revision high-water marks; it has
                # no digest yet, so the first v4 import re-establishes identity.
                baseline = _read_legacy_revisions(cursor, project_id)
                baseline_digests = {store: None for store in REVISION_STORES}
            else:
                baseline = {
                    "materials": prior_state["material_revision"],
                    "annotations": prior_state["annotation_revision"],
                    "negative_pool": prior_state["negative_pool_revision"],
                }
                baseline_digests = {
                    "materials": prior_state["materials_digest"],
                    "annotations": prior_state["annotations_digest"],
                    "negative_pool": prior_state["negative_pool_digest"],
                }
            # Evidence streams (mutable historical evidence without an owner
            # revision) are protected by two Owner-side versions:
            #   * the table lifecycle version, which must advance before a
            #     different evidence-table set may be applied at all;
            #   * the row generation, which must advance before different content
            #     within the same structure may be applied.
            # A structure change is never "assumed safe": if the Owner cannot prove
            # it (an older snapshot, or a legacy target without a structure
            # version), the import is refused.
            for name in EVIDENCE_STREAMS:
                source = streams[name]
                target = prior_vector.get(name) or {}
                source_structure = source.get("structure_generation", 0)
                target_structure = target.get("structure_generation")
                same_structure = sorted(target.get("tables") or []) == sorted(
                    source.get("tables") or []
                )
                if (
                    isinstance(target_structure, int)
                    and not isinstance(target_structure, bool)
                ):
                    if source_structure < target_structure:
                        raise U3MigrationError(
                            "U3_SNAPSHOT_STRUCTURE_REGRESSION",
                            f"the {name} evidence structure may not regress",
                            detail=(
                                f"stream={name} target={target_structure} "
                                f"source={source_structure}"
                            ),
                        )
                    if source_structure == target_structure and not same_structure:
                        raise U3MigrationError(
                            "U3_SNAPSHOT_STRUCTURE_UNVERIFIED",
                            f"the {name} evidence structure changed without a new "
                            "structure version",
                            detail=(
                                f"stream={name} structure={source_structure} "
                                f"target={sorted(target.get('tables') or [])} "
                                f"source={sorted(source.get('tables') or [])}"
                            ),
                        )
                elif (
                    prior_state is not None
                    and not same_structure
                    and not (source.get("structure_certified") and source_structure > 0)
                ):
                    # Legacy target without a structure version: only a certified
                    # structure transition may change the table set.
                    raise U3MigrationError(
                        "U3_SNAPSHOT_STRUCTURE_UNVERIFIED",
                        f"the {name} evidence structure cannot be proven against "
                        "the published state",
                        detail=f"stream={name}",
                    )
                target_generation = target.get("generation")
                if (
                    isinstance(target_generation, int)
                    and not isinstance(target_generation, bool)
                    and source["generation"] < target_generation
                ):
                    raise U3MigrationError(
                        "U3_SNAPSHOT_REVISION_REGRESSION",
                        f"the {name} evidence stream may not regress",
                        detail=(
                            f"stream={name} target={target_generation} "
                            f"source={source['generation']}"
                        ),
                    )
                if (
                    same_structure
                    and source["generation"] == target_generation
                    and isinstance(target.get("digest"), str)
                    and target["digest"] != source["digest"]
                ):
                    raise U3MigrationError(
                        "U3_SNAPSHOT_REVISION_DIVERGED",
                        f"the {name} evidence stream changed without a new generation",
                        detail=f"stream={name} generation={source['generation']}",
                    )
            for store in REVISION_STORES:
                source_revision = revisions.get(store)
                if (
                    isinstance(source_revision, bool)
                    or not isinstance(source_revision, int)
                    or source_revision < 0
                ):
                    raise U3MigrationError(
                        "U3_SNAPSHOT_INTEGRITY_FAILED",
                        "the snapshot carries no usable owner revision",
                        detail=f"reason=revision:{store}",
                    )
                target_revision = baseline.get(store)
                if isinstance(target_revision, int) and not isinstance(target_revision, bool):
                    if source_revision < target_revision:
                        raise U3MigrationError(
                            "U3_SNAPSHOT_REVISION_REGRESSION",
                            "an older owner revision may not replace a newer projection",
                            detail=(
                                f"store={store} target={target_revision} "
                                f"source={source_revision}"
                            ),
                        )
                    target_digest = baseline_digests.get(store)
                    if (
                        source_revision == target_revision
                        and isinstance(target_digest, str) and target_digest
                        and isinstance(store_digests.get(store), str)
                        and store_digests[store] != target_digest
                    ):
                        raise U3MigrationError(
                            "U3_SNAPSHOT_REVISION_DIVERGED",
                            "the same owner revision carries different content",
                            detail=f"store={store} revision={source_revision}",
                        )
            already_applied = (
                mode == "full"
                and prior_state is not None
                and not project_pending
                and str(prior_state["status"]) == "READY"
                and all(
                    revisions.get(store) == baseline.get(store)
                    and store_digests.get(store) == baseline_digests.get(store)
                    for store in REVISION_STORES
                )
                and all(
                    (prior_vector.get(name) or {}).get("generation") == streams[name]["generation"]
                    and (prior_vector.get(name) or {}).get("digest") == streams[name]["digest"]
                    and (prior_vector.get(name) or {}).get("structure_generation", 0)
                    == streams[name].get("structure_generation", 0)
                    and sorted((prior_vector.get(name) or {}).get("tables") or [])
                    == sorted(streams[name].get("tables") or [])
                    for name in EVIDENCE_STREAMS
                )
                and str(prior_state["content_digest"]) == str(snapshot.get("content_digest") or "")
            )
            if already_applied:
                # A replay of the exact snapshot that is already published: the
                # target already equals it, so only the audit row is appended.
                _insert_import_ledger(
                    cursor, project_id=project_id,
                    snapshot_id=_declared_snapshot_id(snapshot),
                    snapshot_digest=str(snapshot.get("content_digest") or ""),
                    revision_vector=revision_vector, mode=mode,
                    outcome="ALREADY_APPLIED",
                )
                counters["outcome"] = "ALREADY_APPLIED"
                counters["negative_confirmation_revision"] = int(
                    prior_state["negative_confirmation_revision"]
                )
                counters["negative_confirmation_generation"] = int(
                    prior_state["negative_confirmation_generation"]
                )
                return counters
            if mode == "full":
                # Delete only rows of THIS project that the snapshot dropped.
                for table, key_columns, values in (
                    ("negative_pool_link", ("material_id", "category_id"),
                     [(row.get("material_id"), row.get("category_id")) for row in material_stores_links(stores)]),
                    ("negative_pool_algorithm_member", ("algorithm_id", "material_id"),
                     [(row.get("algorithm_id"), row.get("material_id")) for row in material_stores_algo(stores)]),
                    ("negative_pool_member", ("material_id",),
                     [(row.get("material_id"),) for row in material_stores_pool(stores)]),
                    ("negative_pool_category", ("id",),
                     [(row.get("id"),) for row in material_stores_cats(stores)]),
                    ("material_annotation_scope", ("material_id", "label_code"),
                     [(row.get("material_id"), row.get("label_code")) for row in material_stores_scopes(stores)]),
                    ("material_label", ("material_id", "label_code"),
                     [(row.get("material_id"), row.get("label_code")) for row in material_stores_labels(stores)]),
                    ("annotation_label_reference", ("image_id", "label_code"),
                     [(row.get("image_id"), row.get("label_code"))
                      for row in (stores.get("annotations") or {}).get("annotation_label_references") or []]),
                    ("annotation", ("image_id",),
                     [(row.get("image_id"),)
                      for row in (stores.get("annotations") or {}).get("annotations") or []]),
                    ("material", ("id",),
                     [(row.get("id"),) for row in materials]),
                ):
                    _delete_absent(
                        cursor, SCHEMA_NAME, table, project_id, key_columns, values,
                    )
            material_sql = (
                f"INSERT INTO {SCHEMA_NAME}.material(project_id,id,filename,storage_source_id,"
                "storage_type,object_key,content_sha256,size_bytes,etag,processing_status,"
                "box_count,annotated,created_at,updated_at,payload) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb) "
                "ON CONFLICT (project_id,id) DO UPDATE SET filename=EXCLUDED.filename,"
                "storage_source_id=EXCLUDED.storage_source_id,storage_type=EXCLUDED.storage_type,"
                "object_key=EXCLUDED.object_key,content_sha256=EXCLUDED.content_sha256,"
                "size_bytes=EXCLUDED.size_bytes,etag=EXCLUDED.etag,"
                "processing_status=EXCLUDED.processing_status,box_count=EXCLUDED.box_count,"
                "annotated=EXCLUDED.annotated,created_at=EXCLUDED.created_at,"
                "updated_at=EXCLUDED.updated_at,payload=EXCLUDED.payload"
            )
            for row in materials:
                cursor.execute(material_sql, (
                    project_id, row.get("id"), row.get("filename"), row.get("storage_source_id"),
                    row.get("storage_type"), row.get("object_key"), row.get("content_sha256"),
                    row.get("size_bytes"), row.get("etag"), row.get("processing_status"),
                    row.get("box_count"), row.get("annotated"), row.get("created_at"),
                    row.get("updated_at"),
                    json.dumps(row.get("payload"), ensure_ascii=False, sort_keys=True),
                ))
                counters["materials"] += 1
            material_stores = stores.get("materials") or {}
            for row in material_stores.get("material_labels") or []:
                cursor.execute(
                    f"INSERT INTO {SCHEMA_NAME}.material_label(project_id,material_id,label_code,box_count) "
                    "VALUES(%s,%s,%s,%s) ON CONFLICT (project_id,material_id,label_code) "
                    "DO UPDATE SET box_count=EXCLUDED.box_count",
                    (project_id, row.get("material_id"), row.get("label_code"), row.get("box_count")),
                )
                counters["labels"] += 1
            for row in material_stores.get("material_annotation_scopes") or []:
                cursor.execute(
                    f"INSERT INTO {SCHEMA_NAME}.material_annotation_scope(project_id,material_id,label_code) "
                    "VALUES(%s,%s,%s) ON CONFLICT DO NOTHING",
                    (project_id, row.get("material_id"), row.get("label_code")),
                )
                counters["scopes"] += 1
            for row in (stores.get("annotations") or {}).get("annotations") or []:
                cursor.execute(
                    f"INSERT INTO {SCHEMA_NAME}.annotation(project_id,image_id,annotation_state,version,"
                    "content_digest,boxes,scope,created_at,updated_at) "
                    "VALUES(%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s) "
                    "ON CONFLICT (project_id,image_id) DO UPDATE SET "
                    "annotation_state=EXCLUDED.annotation_state,version=EXCLUDED.version,"
                    "content_digest=EXCLUDED.content_digest,boxes=EXCLUDED.boxes,"
                    "scope=EXCLUDED.scope,created_at=EXCLUDED.created_at,updated_at=EXCLUDED.updated_at",
                    (
                        project_id, row.get("image_id"), row.get("annotation_state"),
                        row.get("version"), row.get("content_digest"),
                        json.dumps(row.get("boxes"), ensure_ascii=False, sort_keys=True),
                        json.dumps(row.get("scope"), ensure_ascii=False, sort_keys=True),
                        row.get("created_at"), row.get("updated_at"),
                    ),
                )
                counters["annotations"] += 1
            for row in (stores.get("annotations") or {}).get("annotation_label_references") or []:
                cursor.execute(
                    f"INSERT INTO {SCHEMA_NAME}.annotation_label_reference(project_id,image_id,"
                    "label_code,box_count,scope_ref,annotation_state,source_kind) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (project_id,image_id,label_code) "
                    "DO UPDATE SET box_count=EXCLUDED.box_count,scope_ref=EXCLUDED.scope_ref,"
                    "annotation_state=EXCLUDED.annotation_state,source_kind=EXCLUDED.source_kind",
                    (project_id, row.get("image_id"), row.get("label_code"),
                     row.get("box_count"), row.get("scope_ref"),
                     row.get("annotation_state"), row.get("source_kind")),
                )
                counters["references"] += 1
            for row in material_stores.get("negative_pool_members") or []:
                cursor.execute(
                    f"INSERT INTO {SCHEMA_NAME}.negative_pool_member(project_id,material_id,joined_at) "
                    "VALUES(%s,%s,%s) ON CONFLICT DO NOTHING",
                    (project_id, row.get("material_id"), row.get("joined_at")),
                )
                counters["pool_members"] += 1
            for row in material_stores.get("negative_pool_categories") or []:
                cursor.execute(
                    f"INSERT INTO {SCHEMA_NAME}.negative_pool_category(project_id,id,name,enabled) "
                    "VALUES(%s,%s,%s,%s) ON CONFLICT (project_id,id) DO UPDATE SET "
                    "name=EXCLUDED.name,enabled=EXCLUDED.enabled",
                    (project_id, row.get("id"), row.get("name"), row.get("enabled")),
                )
                counters["pool_categories"] += 1
            for row in material_stores.get("negative_pool_links") or []:
                cursor.execute(
                    f"INSERT INTO {SCHEMA_NAME}.negative_pool_link(project_id,material_id,category_id) "
                    "VALUES(%s,%s,%s) ON CONFLICT DO NOTHING",
                    (project_id, row.get("material_id"), row.get("category_id")),
                )
                counters["pool_links"] += 1
            for row in material_stores.get("negative_pool_algorithm_members") or []:
                cursor.execute(
                    f"INSERT INTO {SCHEMA_NAME}.negative_pool_algorithm_member"
                    "(project_id,algorithm_id,material_id,joined_at) VALUES(%s,%s,%s,%s) "
                    "ON CONFLICT DO NOTHING",
                    (project_id, row.get("algorithm_id"), row.get("material_id"), row.get("joined_at")),
                )
                counters["pool_algorithm_members"] += 1
            evidence_state = snapshot.get("table_state") or {}
            for store, tables in (stores or {}).items():
                for table, rows in (tables.get("evidence") or {}).items():
                    state = evidence_state.get(f"{store}.{table}") or {}
                    if mode == "full":
                        # Only this project's rows of THIS store/table are in
                        # scope: a table that exists but is empty clears exactly
                        # its own rows, and other evidence tables keep all rows.
                        cursor.execute(
                            f"DELETE FROM {SCHEMA_NAME}.evidence_row WHERE project_id=%s "
                            "AND store=%s AND table_name=%s",
                            (project_id, str(store), str(table)),
                        )
                    for item in rows:
                        row_key = str(item.get("row_key") or "")
                        payload = item.get("payload") if isinstance(item, dict) else None
                        if not row_key or not isinstance(payload, dict):
                            raise U3MigrationError(
                                "U3_EVIDENCE_ROW_INVALID",
                                "an evidence row has no verifiable identity",
                                detail=f"{store}.{table}",
                            )
                        cursor.execute(
                            f"INSERT INTO {SCHEMA_NAME}.evidence_row(project_id,store,table_name,row_key,payload) "
                            "VALUES(%s,%s,%s,%s,%s::jsonb) ON CONFLICT "
                            "(project_id,store,table_name,row_key) DO UPDATE SET payload=EXCLUDED.payload",
                            (project_id, str(store), str(table), row_key,
                             json.dumps(_canonical(payload), ensure_ascii=False, sort_keys=True)),
                        )
                        counters.setdefault("evidence", 0)
                        counters["evidence"] += 1
                    if mode == "full" and not bool(state.get("present")):
                        # The source table is absent: keep the retained target
                        # rows (explicit historical-evidence retention) instead of
                        # pretending the table was empty.
                        pass
            for name, state in (snapshot.get("table_state") or {}).items():
                store, _, table = name.partition(".")
                cursor.execute(
                    f"INSERT INTO {SCHEMA_NAME}.table_state(project_id,store,table_name,present,"
                    "schema_version,row_count) VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT "
                    "(project_id,store,table_name) DO UPDATE SET present=EXCLUDED.present,"
                    "schema_version=EXCLUDED.schema_version,row_count=EXCLUDED.row_count",
                    (project_id, store, table, bool(state.get("present")),
                     state.get("schema_version"), int(state.get("row_count") or 0)),
                )
                counters.setdefault("table_state", 0)
                counters["table_state"] += 1
            for store, revision in (snapshot.get("revisions") or {}).items():
                cursor.execute(
                    f"INSERT INTO {SCHEMA_NAME}.store_revision(project_id,store,revision) "
                    "VALUES(%s,%s,%s) ON CONFLICT (project_id,store) DO UPDATE SET "
                    "revision=EXCLUDED.revision, recorded_at=now()",
                    (project_id, str(store), revision),
                )
            if mode == "full":
                # Only a provably complete snapshot may replace the provisional v1
                # rows. An incomplete/hand-built mapping keeps the marker so the
                # target stays explicitly "not complete".
                eligible, reason = pending_clear_eligible(snapshot, project_id)
                if eligible:
                    cursor.execute(
                        f"DELETE FROM {SCHEMA_NAME}.store_revision "
                        "WHERE project_id=%s AND store=%s",
                        (project_id, LEGACY_REFERENCE_PENDING_STORE),
                    )
                    counters["legacy_pending_cleared"] = int(cursor.rowcount == 1)
                else:
                    counters["legacy_pending_cleared"] = 0
                    counters["legacy_pending_retained"] = reason
            # Derived confirmation projection: queryable rows only, the verbatim
            # owner evidence stays in evidence_row and is never rewritten here.
            confirmation_rows = _confirmation_projection(snapshot)
            # A present-but-empty source table is authoritative emptiness and clears
            # the projection (same semantics as evidence_row). An ABSENT source table
            # retains both the historical evidence rows and their projection, so the
            # two never disagree: one is never cleared while the other is retained.
            confirmation_present = bool(streams["negative_confirmation"]["tables"])
            if mode == "full" and confirmation_present:
                cursor.execute(
                    f"DELETE FROM {SCHEMA_NAME}.task_negative_confirmation "
                    "WHERE project_id=%s",
                    (project_id,),
                )
            for row in confirmation_rows:
                cursor.execute(
                    f"INSERT INTO {SCHEMA_NAME}.task_negative_confirmation"
                    "(project_id,receipt_id,context_key,image_id,evidence) "
                    "VALUES(%s,%s,%s,%s,%s::jsonb) ON CONFLICT (project_id,receipt_id) "
                    "DO UPDATE SET context_key=EXCLUDED.context_key,"
                    "image_id=EXCLUDED.image_id,evidence=EXCLUDED.evidence",
                    (
                        project_id, row["receipt_id"], row["context_key"], row["image_id"],
                        json.dumps(_canonical(row["evidence"]), ensure_ascii=False, sort_keys=True),
                    ),
                )
                counters["negative_confirmations"] = (
                    counters.get("negative_confirmations", 0) + 1
                )
            cursor.execute(
                f"SELECT receipt_id,context_key,image_id,evidence "
                f"FROM {SCHEMA_NAME}.task_negative_confirmation "
                "WHERE project_id=%s ORDER BY receipt_id",
                (project_id,),
            )
            confirmation_rows_in_target = []
            for receipt_id, context_key, image_id, evidence in cursor.fetchall():
                confirmation_rows_in_target.append({
                    "receipt_id": str(receipt_id),
                    "context_key": str(context_key),
                    "image_id": None if image_id is None else str(image_id),
                    "evidence": evidence if isinstance(evidence, dict) else json.loads(evidence),
                })
            counters["negative_confirmation_rows"] = len(confirmation_rows_in_target)
            # The published state describes the OWNER snapshot: the Owner
            # generation and COUNT are used as-is. An incremental apply leaves
            # the state STALE, so a union target is never advertised as READY.
            confirmation_count = int(streams["negative_confirmation"]["revision"])
            confirmation_generation = int(streams["negative_confirmation"]["generation"])
            confirmation_digest = str(streams["negative_confirmation"]["digest"])
            complete, _reason = pending_clear_eligible(snapshot, project_id)
            if mode == "full":
                if status_override is not None:
                    if str(status_override) not in {"READY", "STALE", "INCOMPLETE"}:
                        raise U3MigrationError(
                            "U3_IMPORT_STATUS_INVALID",
                            "the requested publication status is invalid",
                            detail=str(status_override),
                        )
                    status = str(status_override)
                else:
                    status = "READY" if complete else "INCOMPLETE"
            else:
                # An incremental apply only proves that the target contains the
                # snapshot; it cannot prove that the target equals it.
                status = (
                    "STALE"
                    if prior_state is not None and str(prior_state["status"]) == "READY"
                    else "INCOMPLETE"
                )
            snapshot_identity = _declared_snapshot_id(snapshot)
            cursor.execute(
                f"INSERT INTO {SCHEMA_NAME}.picker_snapshot_state(project_id,snapshot_id,"
                "content_digest,material_revision,annotation_revision,negative_pool_revision,"
                "materials_digest,annotations_digest,negative_pool_digest,"
                "negative_confirmation_revision,negative_confirmation_generation,"
                "negative_confirmation_digest,revision_vector,status,captured_at,published_at) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,NULL,now()) "
                "ON CONFLICT (project_id) DO UPDATE SET snapshot_id=EXCLUDED.snapshot_id,"
                "content_digest=EXCLUDED.content_digest,"
                "material_revision=EXCLUDED.material_revision,"
                "annotation_revision=EXCLUDED.annotation_revision,"
                "negative_pool_revision=EXCLUDED.negative_pool_revision,"
                "materials_digest=EXCLUDED.materials_digest,"
                "annotations_digest=EXCLUDED.annotations_digest,"
                "negative_pool_digest=EXCLUDED.negative_pool_digest,"
                "negative_confirmation_revision=EXCLUDED.negative_confirmation_revision,"
                "negative_confirmation_generation=EXCLUDED.negative_confirmation_generation,"
                "negative_confirmation_digest=EXCLUDED.negative_confirmation_digest,"
                "revision_vector=EXCLUDED.revision_vector,status=EXCLUDED.status,"
                "published_at=now()",
                (
                    project_id, snapshot_identity, str(snapshot.get("content_digest") or ""),
                    revisions.get("materials"), revisions.get("annotations"),
                    revisions.get("negative_pool"),
                    store_digests["materials"], store_digests["annotations"],
                    store_digests["negative_pool"],
                    confirmation_count, confirmation_generation, confirmation_digest,
                    json.dumps(_canonical(revision_vector), ensure_ascii=False, sort_keys=True),
                    status,
                ),
            )
            # The cursors and baseline are part of the same commit: a failed
            # import cannot leave a cursor ahead of the data. A B3 snapshot binds
            # each stream to its high-water mark; a legacy snapshot without marks
            # keeps the nullable cursor and no incremental baseline.
            if mode == "full":
                from .u3_incremental_sync import establish_baseline_from_snapshot
                baseline_established = establish_baseline_from_snapshot(
                    cursor, project_id, snapshot, revisions
                )
            else:
                baseline_established = False
            if not baseline_established:
                for store in REVISION_STORES:
                    cursor.execute(
                        f"INSERT INTO {SCHEMA_NAME}.u3_projection_cursor"
                        "(project_id,store,last_applied_seq,source_revision) "
                        "VALUES(%s,%s,NULL,%s) ON CONFLICT (project_id,store) DO UPDATE SET "
                        "source_revision=EXCLUDED.source_revision, updated_at=now()",
                        (project_id, store, revisions.get(store)),
                    )
            _insert_import_ledger(
                cursor, project_id=project_id, snapshot_id=snapshot_identity,
                snapshot_digest=str(snapshot.get("content_digest") or ""),
                revision_vector=revision_vector, mode=mode, outcome="APPLIED",
            )
            counters["outcome"] = "APPLIED"
            counters["snapshot_id"] = snapshot_identity
            counters["snapshot_status"] = status
            counters["negative_confirmation_revision"] = confirmation_count
            counters["negative_confirmation_generation"] = confirmation_generation
    return counters


def _read_target_snapshot_in_transaction(connection, project_id: str) -> dict[str, Any]:
    """Read the target inside the caller's transaction (no nested transaction).

    The caller must hold the project-level advisory lock and set the isolation
    level before the first query. Public ``read_target_snapshot`` keeps its
    idle-connection REPEATABLE READ READ ONLY contract.
    """
    from psycopg.rows import dict_row, tuple_row

    snapshot_identity = ""
    with connection.cursor(row_factory=tuple_row) as identity:
        identity.execute("SELECT pg_current_snapshot() AS snapshot")
        snapshot_identity = str(identity.fetchone()[0])
    stores: dict[str, Any] = {"materials": {}, "annotations": {}}
    queries = {
        "materials": (
            "SELECT id,filename,storage_source_id,storage_type,object_key,content_sha256,"
            "size_bytes,etag,processing_status,box_count,annotated,created_at,updated_at,"
            "payload AS payload_json FROM {schema}.material WHERE project_id=%s ORDER BY id",
            MATERIAL_COLUMNS,
        ),
        "material_labels": (
            "SELECT material_id,label_code,box_count FROM {schema}.material_label "
            "WHERE project_id=%s ORDER BY material_id,label_code", None,
        ),
        "material_annotation_scopes": (
            "SELECT material_id,label_code FROM {schema}.material_annotation_scope "
            "WHERE project_id=%s ORDER BY material_id,label_code", None,
        ),
        "negative_pool_members": (
            "SELECT material_id,joined_at FROM {schema}.negative_pool_member "
            "WHERE project_id=%s ORDER BY material_id", None,
        ),
        "negative_pool_categories": (
            "SELECT id,name,enabled FROM {schema}.negative_pool_category "
            "WHERE project_id=%s ORDER BY id", None,
        ),
        "negative_pool_links": (
            "SELECT material_id,category_id FROM {schema}.negative_pool_link "
            "WHERE project_id=%s ORDER BY material_id,category_id", None,
        ),
        "negative_pool_algorithm_members": (
            "SELECT algorithm_id,material_id,joined_at FROM {schema}.negative_pool_algorithm_member "
            "WHERE project_id=%s ORDER BY algorithm_id,material_id", None,
        ),
    }
    annotation_queries = {
        "annotations": (
            "SELECT image_id,annotation_state,version,content_digest,boxes AS boxes_json,"
            "scope AS scope_json,created_at,updated_at FROM {schema}.annotation "
            "WHERE project_id=%s ORDER BY image_id", ANNOTATION_COLUMNS,
        ),
        "annotation_label_references": (
            "SELECT image_id,label_code,box_count,scope_ref,annotation_state,source_kind "
            "FROM {schema}.annotation_label_reference "
            "WHERE project_id=%s ORDER BY image_id,label_code", None,
        ),
        "evidence": (
            "SELECT store,table_name,row_key,payload AS payload_json FROM {schema}.evidence_row "
            "WHERE project_id=%s ORDER BY store,table_name,row_key", None,
        ),
    }
    with connection.cursor(row_factory=dict_row) as cursor:
        for name, (statement, _columns) in queries.items():
            cursor.execute(statement.format(schema=SCHEMA_NAME), (project_id,))
            rows = []
            for row in cursor.fetchall():
                record = dict(row)
                if "payload_json" in record:
                    value = record.pop("payload_json")
                    record["payload"] = (
                        None if value is None
                        else json.loads(value) if isinstance(value, (str, bytes, bytearray))
                        else value
                    )
                rows.append(record)
            stores["materials"][name] = rows
        for name, (statement, _columns) in annotation_queries.items():
            cursor.execute(statement.format(schema=SCHEMA_NAME), (project_id,))
            rows = []
            for row in cursor.fetchall():
                record = dict(row)
                for json_key in ("boxes_json", "scope_json"):
                    if json_key in record:
                        value = record.pop(json_key)
                        record[json_key.removesuffix("_json")] = (
                            None if value is None
                            else json.loads(value) if isinstance(value, (str, bytes, bytearray))
                            else value
                        )
                rows.append(record)
            if name == "evidence":
                # Regroup verbatim evidence rows by their original store/table.
                grouped: dict[str, dict[str, list[dict[str, Any]]]] = {"materials": {}, "annotations": {}}
                for record in rows:
                    store = str(record.pop("store"))
                    table = str(record.pop("table_name"))
                    row_key = str(record.pop("row_key"))
                    value = record.pop("payload_json")
                    grouped.setdefault(store, {}).setdefault(table, []).append(
                        {
                            "row_key": row_key,
                            "payload": value if isinstance(value, dict) else json.loads(value),
                        }
                    )
                for tables in grouped.values():
                    for table_rows in tables.values():
                        table_rows.sort(key=lambda item: item["row_key"])
                for store, tables in grouped.items():
                    stores.setdefault(store, {})["evidence"] = tables
                continue
            stores["annotations"][name] = rows
        cursor.execute(
            f"SELECT store,revision FROM {SCHEMA_NAME}.store_revision WHERE project_id=%s",
            (project_id,),
        )
        revision_rows = cursor.fetchall()
        legacy_pending = any(
            str(row["store"]) == LEGACY_REFERENCE_PENDING_STORE
            for row in revision_rows
        )
        revisions = {
            str(row["store"]): row["revision"]
            for row in revision_rows
            if str(row["store"]) != LEGACY_REFERENCE_PENDING_STORE
        }
        cursor.execute(
            f"SELECT store,table_name,present,schema_version,row_count FROM {SCHEMA_NAME}.table_state "
            "WHERE project_id=%s ORDER BY store,table_name",
            (project_id,),
        )
        table_state = {
            f"{row['store']}.{row['table_name']}": {
                "present": bool(row["present"]),
                "schema_version": row["schema_version"],
                "row_count": int(row["row_count"]),
            }
            for row in cursor.fetchall()
        }
    # Present-but-empty evidence tables must exist as keys on both sides, otherwise
    # an empty historical table would look like a mismatch instead of "zero rows".
    for name, state in table_state.items():
        store, _, table = name.partition(".")
        if state.get("present") and store in EVIDENCE_TABLES and table in EVIDENCE_TABLES[store]:
            stores.setdefault(store, {}).setdefault("evidence", {}).setdefault(table, [])
    counts = {f"{store}.{table}": len(rows) for store, tables in stores.items()
              for table, rows in tables.items() if table != "evidence"}
    digests = {f"{store}.{table}": _digest(rows) for store, tables in stores.items()
               for table, rows in tables.items() if table != "evidence"}
    for store, tables in {k: v.get("evidence") or {} for k, v in stores.items()}.items():
        for table, rows in tables.items():
            counts[f"{store}.evidence.{table}"] = len(rows)
            digests[f"{store}.evidence.{table}"] = _digest(rows)
    return {
        "contract_version": CONTRACT_VERSION,
        "project_id": str(project_id),
        "stores": stores,
        "counts": counts,
        "digests": digests,
        "snapshot": {
            "isolation": "REPEATABLE READ",
            "read_only": True,
            "identity": snapshot_identity,
        },
        "legacy_reference_pending_import": legacy_pending,
        "table_state": table_state,
        "revisions": revisions,
        "content_digest": _digest(
            [{"table": name, "digest": value} for name, value in sorted(digests.items())]
        ),
    }




def read_target_snapshot(connection, project_id: str) -> dict[str, Any]:
    """Read the PostgreSQL target from ONE repeatable-read, read-only snapshot.

    Public contract: the connection must be idle; this wrapper opens its own
    REPEATABLE READ READ ONLY transaction. The internal split is reused by the
    controlled READY publication transaction without nesting transactions.
    """
    from psycopg.pq import TransactionStatus

    if connection.info.transaction_status != TransactionStatus.IDLE:
        raise U3MigrationError(
            "U3_TARGET_SNAPSHOT_TRANSACTION_BUSY",
            "the target snapshot requires an idle PostgreSQL connection",
            detail=f"transaction_status={connection.info.transaction_status!r}",
        )
    with connection.transaction():
        with connection.cursor() as setup:
            setup.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        return _read_target_snapshot_in_transaction(connection, project_id)


def reconcile(source: Mapping[str, Any], target: Mapping[str, Any]) -> dict[str, Any]:
    """Explain every difference; integrity failures never become "zero"."""
    blocking: list[str] = []
    checks: dict[str, Any] = {"tables": {}, "integrity": {}}
    source_counts = source.get("counts") or {}
    target_counts = target.get("counts") or {}
    source_state = source.get("table_state") or {}
    retained: list[str] = []
    for table in sorted(set(source_counts) | set(target_counts)):
        left = source_counts.get(table, 0)
        right = target_counts.get(table, 0)
        same_digest = (source.get("digests") or {}).get(table) == (target.get("digests") or {}).get(table)
        checks["tables"][table] = {
            "source": left, "target": right, "digest_equal": same_digest,
        }
        if table.startswith("materials.evidence.") or table.startswith("annotations.evidence."):
            store, _, rest = table.partition(".evidence.")
            state = source_state.get(f"{store}.{rest}") or {}
            if not state.get("present"):
                # The source table does not exist any more: the retained target
                # rows are an explicit retention contract, not a mismatch.
                retained.append(table)
                continue
        if left != right or not same_digest:
            blocking.append(f"table_mismatch:{table}")
    source_materials = {
        str(row["id"]) for row in (source.get("stores") or {}).get("materials", {}).get("materials", [])
    }
    target_materials = {
        str(row["id"]) for row in (target.get("stores") or {}).get("materials", {}).get("materials", [])
    }
    missing = sorted(source_materials - target_materials)
    extra = sorted(target_materials - source_materials)
    checks["material_ids"] = {"missing": missing[:50], "extra": extra[:50]}
    if missing or extra:
        blocking.append("material_ids")
    pool_members = {
        str(row["material_id"])
        for row in (target.get("stores") or {}).get("materials", {}).get("negative_pool_members", [])
    }
    orphan_members = sorted(pool_members - target_materials)
    checks["integrity"]["pool_member_without_material"] = orphan_members[:50]
    if orphan_members:
        blocking.append("pool_member_without_material")
    algorithm_members = {
        str(row["material_id"])
        for row in (target.get("stores") or {}).get("materials", {}).get("negative_pool_algorithm_members", [])
    }
    checks["integrity"]["algorithm_member_without_pool_member"] = sorted(
        algorithm_members - pool_members
    )[:50]
    if algorithm_members - pool_members:
        blocking.append("algorithm_member_without_pool_member")
    annotation_images = {
        str(row["image_id"])
        for row in (target.get("stores") or {}).get("annotations", {}).get("annotations", [])
    }
    # A formal GT row whose material is absent is a legitimate pre-existing state
    # (legacy per-image JSON was migrated separately); it is reported, not fatal.
    checks["integrity"]["annotation_without_material"] = sorted(
        annotation_images - target_materials
    )[:50]
    if (source.get("revisions") or {}) != (target.get("revisions") or {}):
        blocking.append("revision_high_water_mismatch")
    if target.get("legacy_reference_pending_import"):
        # v1 could not prove box_count/scope_ref/annotation_state, so the target is
        # not complete until a full authoritative SQLite import replaces them.
        blocking.append("legacy_reference_pending_import")
    source_state = source.get("table_state") or {}
    target_state = target.get("table_state") or {}
    for name, state in source_state.items():
        present = (target_state.get(name) or {}).get("present")
        if bool(state.get("present")) != bool(present):
            blocking.append(f"table_presence_mismatch:{name}")
    for store, tables in REQUIRED_TABLES.items():
        for table in tables:
            key = f"{store}.{table}"
            if not (source_state.get(key) or {}).get("present"):
                blocking.append(f"required_table_missing_source:{key}")
            if not (target_state.get(key) or {}).get("present"):
                blocking.append(f"required_table_missing_target:{key}")
    return {
        "same": not blocking,
        "verdict": "OK" if not blocking else "MISMATCH",
        "blocking_findings": blocking,
        "retained_target_evidence": retained,
        "checks": checks,
        "source_digest": source.get("content_digest"),
        "target_digest": target.get("content_digest"),
    }
