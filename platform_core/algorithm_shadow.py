"""W5 U1 algorithm-domain read-only shadow projection.

SQLite remains the authoritative owner.  This module only exports a consistent
read-only snapshot and, when an isolated PostgreSQL is provided, imports it into
the prefixed ``w5_algorithm_shadow_*`` tables.  It never writes to SQLite.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .algorithm_sql_store import AlgorithmSqlStore

CONTRACT_VERSION = "w5-algorithm-shadow-v1"
SCHEMA_VERSION = 1
_TABLES = (
    ("algorithms", "SELECT * FROM algorithms ORDER BY project_id,id"),
    ("versions", "SELECT * FROM algorithm_versions ORDER BY algorithm_id,id"),
    ("analyses", "SELECT * FROM algorithm_external_analyses "
                 "ORDER BY algorithm_id,external_analysis_id"),
)
_POSTGRES_DDL = """
CREATE SCHEMA IF NOT EXISTS w5_shadow;
CREATE TABLE IF NOT EXISTS w5_shadow.algorithm_snapshot (
    project_id TEXT PRIMARY KEY,
    algorithm_revision BIGINT NOT NULL,
    snapshot_digest CHAR(64) NOT NULL,
    contract_version TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    algorithm_count INTEGER NOT NULL,
    version_count INTEGER NOT NULL,
    analysis_count INTEGER NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS w5_shadow.algorithm_row (
    project_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('algorithm','version','analysis')),
    natural_key TEXT NOT NULL,
    payload JSONB NOT NULL,
    PRIMARY KEY(project_id, kind, natural_key)
);
"""


class AlgorithmShadowError(RuntimeError):
    def __init__(self, code: str, message: str, *, detail: str = ""):
        super().__init__(message)
        self.code = str(code)
        self.detail = str(detail or "")


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _snapshot_body(project_id: str, revision: int, tables: Mapping[str, list[dict]]) -> dict:
    return {
        "contract_version": CONTRACT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "project_id": project_id,
        "algorithm_revision": revision,
        "counts": {name: len(rows) for name, rows in tables.items()},
        "tables": tables,
    }


def _read_rows(database: sqlite3.Connection, sql: str) -> list[dict[str, Any]]:
    return [dict(row) for row in database.execute(sql).fetchall()]


def export_snapshot(store: AlgorithmSqlStore) -> dict[str, Any]:
    """Export one consistent SQLite read transaction without initialization."""
    path = Path(store.db_path)
    if not path.is_file():
        raise AlgorithmShadowError("ALGORITHM_SHADOW_SOURCE_MISSING", "algorithm source database is missing")
    try:
        database = sqlite3.connect(
            path.resolve().as_uri() + "?mode=ro", uri=True,
            timeout=5.0, isolation_level=None,
        )
        database.row_factory = sqlite3.Row
        database.execute("PRAGMA query_only=ON")
        database.execute("PRAGMA busy_timeout=5000")
        database.execute("BEGIN")
        try:
            meta = {str(row["key"]): str(row["value"]) for row in database.execute(
                "SELECT key,value FROM algorithm_store_meta"
            ).fetchall()}
            revision = max(0, int(meta.get("algorithm_revision") or 0))
            tables: dict[str, list[dict]] = {}
            for name, sql in _TABLES:
                tables[name] = _read_rows(database, sql)
        finally:
            database.execute("ROLLBACK")
    except sqlite3.Error as error:
        raise AlgorithmShadowError(
            "ALGORITHM_SHADOW_SOURCE_INVALID", "algorithm source snapshot failed",
            detail=str(error),
        ) from error
    finally:
        try:
            database.close()  # type: ignore[possibly-undefined]
        except (NameError, AttributeError):
            pass
    project_id = str(store.project_id)
    for row in tables["algorithms"]:
        if str(row.get("project_id") or "") != project_id:
            raise AlgorithmShadowError(
                "ALGORITHM_SHADOW_PROJECT_MISMATCH",
                "source rows contain a different project_id",
                detail=f"{row.get('project_id')!r} != {project_id!r}",
            )
    body = _snapshot_body(project_id, revision, tables)
    body["snapshot_digest"] = _digest(body)
    body["captured_at"] = datetime.now(timezone.utc).isoformat()
    return body


def write_snapshot(snapshot: Mapping[str, Any], destination: str | Path) -> Path:
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_canonical(dict(snapshot)), encoding="utf-8")
    return path


def load_snapshot(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AlgorithmShadowError("ALGORITHM_SHADOW_SNAPSHOT_INVALID", "snapshot must be an object")
    return value


def _natural_key(kind: str, row: Mapping[str, Any]) -> str:
    if kind == "algorithm":
        return str(row.get("id"))
    if kind == "version":
        return str(row.get("id"))
    return f"{row.get('algorithm_id')}:{row.get('external_analysis_id')}"


def _shadow_rows(snapshot: Mapping[str, Any]) -> list[tuple[str, str, str, dict]]:
    tables = snapshot.get("tables")
    if not isinstance(tables, Mapping):
        raise AlgorithmShadowError("ALGORITHM_SHADOW_SNAPSHOT_INVALID", "snapshot tables missing")
    rows = []
    for name, kind in (("algorithms", "algorithm"), ("versions", "version"), ("analyses", "analysis")):
        values = tables.get(name)
        if not isinstance(values, list):
            raise AlgorithmShadowError("ALGORITHM_SHADOW_SNAPSHOT_INVALID", f"snapshot {name} missing")
        for row in values:
            if not isinstance(row, Mapping):
                raise AlgorithmShadowError("ALGORITHM_SHADOW_SNAPSHOT_INVALID", f"invalid {name} row")
            key = _natural_key(kind, row)
            if not key or key == ":":
                raise AlgorithmShadowError("ALGORITHM_SHADOW_SNAPSHOT_INVALID", f"invalid {name} identity")
            rows.append((str(snapshot.get("project_id")), kind, key, dict(row)))
    return rows


def import_snapshot(connection, snapshot: Mapping[str, Any]) -> bool:
    """Atomically import into PostgreSQL. Returns True when newly written."""
    project_id = str(snapshot.get("project_id") or "")
    revision = int(snapshot.get("algorithm_revision") or 0)
    digest = str(snapshot.get("snapshot_digest") or "")
    if not project_id or len(digest) != 64:
        raise AlgorithmShadowError("ALGORITHM_SHADOW_SNAPSHOT_INVALID", "snapshot identity incomplete")
    rows = _shadow_rows(snapshot)
    try:
        with connection.cursor() as cursor:
            for statement in (part.strip() for part in _POSTGRES_DDL.split(";")):
                if statement:
                    cursor.execute(statement)
            cursor.execute(
                "SELECT algorithm_revision,snapshot_digest FROM w5_shadow.algorithm_snapshot "
                "WHERE project_id=%s FOR UPDATE", (project_id,),
            )
            existing = cursor.fetchone()
            if existing:
                old_revision, old_digest = int(existing[0]), str(existing[1])
                if old_revision == revision and old_digest == digest:
                    connection.rollback()
                    return False
                if old_revision > revision:
                    raise AlgorithmShadowError(
                        "ALGORITHM_SHADOW_REVISION_REGRESSION",
                        "incoming snapshot revision is older than shadow",
                    )
                if old_revision == revision and old_digest != digest:
                    raise AlgorithmShadowError(
                        "ALGORITHM_SHADOW_DIGEST_CONFLICT",
                        "same revision has a different snapshot digest",
                    )
            cursor.execute("DELETE FROM w5_shadow.algorithm_row WHERE project_id=%s", (project_id,))
            cursor.executemany(
                "INSERT INTO w5_shadow.algorithm_row(project_id,kind,natural_key,payload) "
                "VALUES(%s,%s,%s,%s::jsonb)",
                [(project, kind, key, json.dumps(row, ensure_ascii=False)) for project, kind, key, row in rows],
            )
            counts = snapshot.get("counts") or {}
            cursor.execute(
                "INSERT INTO w5_shadow.algorithm_snapshot"
                "(project_id,algorithm_revision,snapshot_digest,contract_version,schema_version,"
                "algorithm_count,version_count,analysis_count,captured_at) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT(project_id) DO UPDATE SET algorithm_revision=EXCLUDED.algorithm_revision,"
                "snapshot_digest=EXCLUDED.snapshot_digest,contract_version=EXCLUDED.contract_version,"
                "schema_version=EXCLUDED.schema_version,algorithm_count=EXCLUDED.algorithm_count,"
                "version_count=EXCLUDED.version_count,analysis_count=EXCLUDED.analysis_count,"
                "captured_at=EXCLUDED.captured_at",
                (project_id, revision, digest, str(snapshot.get("contract_version") or CONTRACT_VERSION),
                 int(snapshot.get("schema_version") or SCHEMA_VERSION), int(counts.get("algorithms", 0)),
                 int(counts.get("versions", 0)), int(counts.get("analyses", 0)),
                 str(snapshot.get("captured_at") or datetime.now(timezone.utc).isoformat())),
            )
            connection.commit()
            return True
    except Exception:
        connection.rollback()
        raise


def load_shadow_snapshot(connection, project_id: str) -> dict[str, Any] | None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT algorithm_revision,snapshot_digest,contract_version,schema_version,captured_at "
            "FROM w5_shadow.algorithm_snapshot WHERE project_id=%s", (str(project_id),),
        )
        meta = cursor.fetchone()
        if not meta:
            return None
        cursor.execute(
            "SELECT kind,natural_key,payload FROM w5_shadow.algorithm_row "
            "WHERE project_id=%s ORDER BY kind,natural_key", (str(project_id),),
        )
        tables: dict[str, list[dict]] = {"algorithms": [], "versions": [], "analyses": []}
        for kind, _key, payload in cursor.fetchall():
            name = {"algorithm": "algorithms", "version": "versions", "analysis": "analyses"}[str(kind)]
            tables[name].append(payload)
    body = _snapshot_body(
        str(project_id), int(meta[0]),
        tables,
    )
    body["snapshot_digest"] = str(meta[1])
    body["captured_at"] = str(meta[4])
    return body


def reconcile(source: Mapping[str, Any], shadow: Mapping[str, Any] | None) -> dict[str, Any]:
    """Compare two snapshots; never compares different revisions as failure."""
    if shadow is None:
        return {"same": False, "reason": "SHADOW_MISSING", "differences": {}}
    source_revision = int(source.get("algorithm_revision") or 0)
    shadow_revision = int(shadow.get("algorithm_revision") or 0)
    if source_revision != shadow_revision:
        return {
            "same": False, "reason": "SOURCE_REVISION_CHANGED",
            "source_revision": source_revision, "shadow_revision": shadow_revision,
            "differences": {},
        }
    if str(source.get("snapshot_digest")) != str(shadow.get("snapshot_digest")):
        return {"same": False, "reason": "SNAPSHOT_DIGEST_MISMATCH", "differences": {}}
    differences: dict[str, Any] = {}
    for name in ("algorithms", "versions", "analyses"):
        source_rows = {_natural_key(
            {"algorithms": "algorithm", "versions": "version", "analyses": "analysis"}[name], row
        ): row for row in source.get("tables", {}).get(name, [])}
        shadow_rows = {_natural_key(
            {"algorithms": "algorithm", "versions": "version", "analyses": "analysis"}[name], row
        ): row for row in shadow.get("tables", {}).get(name, [])}
        missing = sorted(set(source_rows) - set(shadow_rows))
        extra = sorted(set(shadow_rows) - set(source_rows))
        changed = sorted(key for key in set(source_rows) & set(shadow_rows)
                         if _canonical(source_rows[key]) != _canonical(shadow_rows[key]))
        if missing or extra or changed:
            differences[name] = {"missing": missing, "extra": extra, "changed": changed}
    return {"same": not differences, "reason": "OK" if not differences else "DATA_MISMATCH",
            "source_revision": source_revision, "shadow_revision": shadow_revision,
            "differences": differences}
