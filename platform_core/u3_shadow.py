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
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Iterable, Mapping

SCHEMA_NAME = "w3_material_gt"
SCHEMA_VERSION = 3
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
            pool_row = database.execute(
                "SELECT revision FROM negative_pool_meta WHERE id=1"
            ).fetchone()
            pool_revision = int(pool_row[0]) if pool_row else None
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
            annotations_schema = annotations_schema_version
        # Revision re-check: a store that moved during the export invalidates it.
        with closing(_open_read_only(materials_db)) as database:
            after_row = database.execute(
                "SELECT value FROM material_meta WHERE key='revision'"
            ).fetchone()
            after_pool = database.execute(
                "SELECT revision FROM negative_pool_meta WHERE id=1"
            ).fetchone()
            after_materials_revision = int(after_row[0]) if after_row else None
            after_pool_revision = int(after_pool[0]) if after_pool else None
        with closing(_open_read_only(annotations_db)) as database:
            after_meta = database.execute(
                "SELECT value FROM annotation_meta WHERE key='revision'"
            ).fetchone()
            after_annotation_revision = int(after_meta[0]) if after_meta else None
    if (after_materials_revision, after_pool_revision, after_annotation_revision) != (
        material_revision, pool_revision, annotation_revision
    ):
        raise U3MigrationError(
            "U3_SNAPSHOT_SOURCE_CHANGED",
            "a source owner changed during the snapshot export",
            detail=(
                f"materials={material_revision}->{after_materials_revision} "
                f"pool={pool_revision}->{after_pool_revision} "
                f"annotations={annotation_revision}->{after_annotation_revision}"
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
    return {
        "contract_version": CONTRACT_VERSION,
        "project_id": str(project_id),
        "stores": stores,
        "counts": counts,
        "digests": digests,
        "table_state": table_state,
        "schema_versions": {"materials": materials_schema, "annotations": annotations_schema},
        "revisions": {
            "materials": material_revision,
            "annotations": annotation_revision,
            "negative_pool": pool_revision,
        },
        "consistency": "MATERIAL_ANNOTATION_LIFECYCLE_FENCE+REVISION_RECHECK",
        "content_digest": _digest(
            [{"table": name, "digest": value} for name, value in sorted(digests.items())]
        ),
    }


_SCHEMA = """
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


_HISTORICAL_SCHEMAS = {1: _SCHEMA_V1, 2: _SCHEMA_V2}


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
    # v1 -> v2: corrected reference key + evidence/table-state tables.
    2: (
        "DROP TABLE IF EXISTS w3_material_gt.annotation_label_reference CASCADE",
        _SCHEMA_V2,
    ),
    # v2 -> v3: the category uniqueness fold becomes locale independent (ASCII
    # only, matching SQLite COLLATE NOCASE). Only the index changes.
    3: (
        "DROP INDEX IF EXISTS w3_material_gt.uq_negative_pool_category_name",
        """CREATE UNIQUE INDEX IF NOT EXISTS uq_negative_pool_category_name
    ON w3_material_gt.negative_pool_category(project_id, lower(name COLLATE "C"))""",
    ),
}


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
                for statement in statements:
                    for part in [piece for piece in statement.split(";") if piece.strip()]:
                        cursor.execute(part)
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


def import_project_snapshot(
    connection, snapshot: Mapping[str, Any], *, mode: str = "full",
) -> dict[str, int]:
    """Import one snapshot in a single transaction.

    ``mode="full"`` (default) makes the target project *equal* to the snapshot:
    rows of this project that the snapshot no longer contains are deleted
    (children before parents) and everything else is upserted. ``incremental``
    only upserts. Both are idempotent, both are scoped to one ``project_id`` and
    both roll back completely on any failure.
    """
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
    ensure_schema(connection)
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"u3_import:{project_id}",))
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
    return counters


def read_target_snapshot(connection, project_id: str) -> dict[str, Any]:
    """Read the PostgreSQL target from ONE repeatable-read, read-only snapshot.

    The multi-table read must not mix two commit points: the tool requires an idle
    connection, opens its own transaction and sets ``REPEATABLE READ, READ ONLY``
    before the first query. A caller that already holds a transaction is refused
    instead of silently inheriting its (default Read Committed) snapshot.
    """
    from psycopg.pq import TransactionStatus
    from psycopg.rows import dict_row

    if connection.info.transaction_status != TransactionStatus.IDLE:
        raise U3MigrationError(
            "U3_TARGET_SNAPSHOT_TRANSACTION_BUSY",
            "the target snapshot requires an idle PostgreSQL connection",
            detail=f"transaction_status={connection.info.transaction_status!r}",
        )
    snapshot_identity = ""
    with connection.transaction():
        with connection.cursor() as setup:
            setup.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        with connection.cursor() as identity:
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
            revisions = {str(row["store"]): row["revision"] for row in cursor.fetchall()}
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
            "table_state": table_state,
            "revisions": revisions,
            "content_digest": _digest(
                [{"table": name, "digest": value} for name, value in sorted(digests.items())]
            ),
        }




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
