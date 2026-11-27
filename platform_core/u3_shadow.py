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
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Iterable, Mapping

SCHEMA_NAME = "w3_material_gt"
SCHEMA_VERSION = 1
CONTRACT_VERSION = "u3-shadow-snapshot-v1"
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
    try:
        return {str(row[1]) for row in database.execute(f"PRAGMA table_info({table})")}
    except sqlite3.Error:
        return set()


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
        output[name] = _read_rows(database, table, columns, key_columns=key_columns)
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
    "annotation_label_references": (
        "annotation_label_references", ("image_id", "label_code", "source_kind"),
        ("image_id", "label_code", "source_kind"),
    ),
}


def export_project_snapshot(project_dir: str | Path, project_id: str) -> dict[str, Any]:
    """Deterministic snapshot of the authoritative SQLite owners (read-only)."""
    project = Path(project_dir)
    materials_db = project / "materials.sqlite3"
    annotations_db = project / "annotations.sqlite3"
    if not materials_db.is_file():
        raise U3MigrationError(
            "U3_MATERIALS_STORE_MISSING", "the material store does not exist",
            detail=str(materials_db),
        )
    stores: dict[str, Any] = {}
    with closing(_open_read_only(materials_db)) as database:
        stores["materials"] = _store_snapshot(database, project_id, tables=_MATERIAL_TABLES)
        revision_row = database.execute(
            "SELECT value FROM material_meta WHERE key='revision'"
        ).fetchone()
        material_revision = int(revision_row[0]) if revision_row else None
        pool_revision_row = None
        if _sqlite_columns(database, "negative_pool_meta"):
            pool_revision_row = database.execute(
                "SELECT revision FROM negative_pool_meta WHERE id=1"
            ).fetchone()
        pool_revision = int(pool_revision_row[0]) if pool_revision_row else None
    if annotations_db.is_file():
        with closing(_open_read_only(annotations_db)) as database:
            stores["annotations"] = _store_snapshot(
                database, project_id, tables=_ANNOTATION_TABLES
            )
            meta = None
            if _sqlite_columns(database, "annotation_meta"):
                meta = database.execute(
                    "SELECT value FROM annotation_meta WHERE key='revision'"
                ).fetchone()
            annotation_revision = int(meta[0]) if meta else None
    else:
        stores["annotations"] = {"annotations": [], "annotation_label_references": []}
        annotation_revision = None
    counts = {f"{store}.{table}": len(rows) for store, tables in stores.items() for table, rows in tables.items()}
    digests = {f"{store}.{table}": _digest(rows) for store, tables in stores.items() for table, rows in tables.items()}
    return {
        "contract_version": CONTRACT_VERSION,
        "project_id": str(project_id),
        "stores": stores,
        "counts": counts,
        "digests": digests,
        "revisions": {
            "materials": material_revision,
            "annotations": annotation_revision,
            "negative_pool": pool_revision,
        },
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


def schema_checksum() -> str:
    return hashlib.sha256(_SCHEMA.encode("utf-8")).hexdigest()


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
            if version < SCHEMA_VERSION:
                for statement in [part for part in _SCHEMA.split(";") if part.strip()]:
                    cursor.execute(statement)
                cursor.execute(
                    f"INSERT INTO {SCHEMA_NAME}.schema_migration(version,name,checksum,applied_by) "
                    "VALUES(%s,%s,%s,%s) ON CONFLICT (version) DO NOTHING",
                    (SCHEMA_VERSION, "u3-material-gt-v1", schema_checksum(), "u3-shadow"),
                )
    return {"schema": SCHEMA_NAME, "version": SCHEMA_VERSION}


def import_project_snapshot(connection, snapshot: Mapping[str, Any]) -> dict[str, int]:
    """Import one snapshot in a single transaction (idempotent replay)."""
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
                    f"INSERT INTO {SCHEMA_NAME}.annotation_label_reference(project_id,image_id,label_code,source_kind) "
                    "VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                    (project_id, row.get("image_id"), row.get("label_code"), row.get("source_kind")),
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
            for store, revision in (snapshot.get("revisions") or {}).items():
                cursor.execute(
                    f"INSERT INTO {SCHEMA_NAME}.store_revision(project_id,store,revision) "
                    "VALUES(%s,%s,%s) ON CONFLICT (project_id,store) DO UPDATE SET "
                    "revision=EXCLUDED.revision, recorded_at=now()",
                    (project_id, str(store), revision),
                )
    return counters


def read_target_snapshot(connection, project_id: str) -> dict[str, Any]:
    from psycopg.rows import dict_row

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
            "SELECT image_id,label_code,source_kind FROM {schema}.annotation_label_reference "
            "WHERE project_id=%s ORDER BY image_id,label_code,source_kind", None,
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
            stores["annotations"][name] = rows
        cursor.execute(
            f"SELECT store,revision FROM {SCHEMA_NAME}.store_revision WHERE project_id=%s",
            (project_id,),
        )
        revisions = {str(row["store"]): row["revision"] for row in cursor.fetchall()}
    counts = {f"{store}.{table}": len(rows) for store, tables in stores.items() for table, rows in tables.items()}
    digests = {f"{store}.{table}": _digest(rows) for store, tables in stores.items() for table, rows in tables.items()}
    return {
        "contract_version": CONTRACT_VERSION,
        "project_id": str(project_id),
        "stores": stores,
        "counts": counts,
        "digests": digests,
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
    for table in sorted(set(source_counts) | set(target_counts)):
        left = source_counts.get(table, 0)
        right = target_counts.get(table, 0)
        same_digest = (source.get("digests") or {}).get(table) == (target.get("digests") or {}).get(table)
        checks["tables"][table] = {
            "source": left, "target": right, "digest_equal": same_digest,
        }
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
    return {
        "same": not blocking,
        "verdict": "OK" if not blocking else "MISMATCH",
        "blocking_findings": blocking,
        "checks": checks,
        "source_digest": source.get("content_digest"),
        "target_digest": target.get("content_digest"),
    }
