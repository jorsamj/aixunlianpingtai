"""W5 U1 algorithm-domain read-only shadow projection.

SQLite remains the authoritative owner.  This module only exports a consistent
read-only snapshot and, when an isolated PostgreSQL is provided, imports it into
the prefixed ``w5_algorithm_shadow_*`` tables.  It never writes to SQLite.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sqlite3
import tempfile
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .algorithm_sql_store import AlgorithmSqlStore

CONTRACT_VERSION = "w5-algorithm-shadow-v1"
SCHEMA_VERSION = 1
#: V2 adds the external-algorithm cleanup ledger to the snapshot. V1 remains
#: readable and verifiable with its original digest; it carries no evidence about
#: the cleanup domain and is never silently upgraded.
CONTRACT_VERSION_V2 = "w5-algorithm-shadow-v2"
SCHEMA_VERSION_V2 = 2
_SUPPORTED_CONTRACTS = {CONTRACT_VERSION, CONTRACT_VERSION_V2}
_V1_TABLES = frozenset({"algorithms", "versions", "analyses"})
_V2_TABLES = _V1_TABLES | {"cleanup"}
_CLEANUP_STATES = frozenset({
    "CONFIRMED_DELETED", "CLEANUP_PENDING", "CLEANUP_RUNNING",
    "CLEANUP_FAILED", "CLEANUP_COMPLETED",
})
_CLEANUP_TABLE = "external_algorithm_cleanup"
_CLEANUP_SQL = (
    "SELECT operation_id,algorithm_id,product_id,state,payload_json,"
    "created_at,updated_at FROM external_algorithm_cleanup "
    "ORDER BY created_at,operation_id"
)
_PROJECT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SENSITIVE_KEYS = {"password", "secret", "token", "credential", "api_key", "access_key", "secret_key"}
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
CREATE INDEX IF NOT EXISTS idx_w5_shadow_row_project_kind
    ON w5_shadow.algorithm_row(project_id, kind, natural_key);
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


def _snapshot_body(
    project_id: str,
    revision: int,
    tables: Mapping[str, list[dict]],
    *,
    contract_version: str = CONTRACT_VERSION,
    schema_version: int = SCHEMA_VERSION,
    cleanup_capability: str | None = None,
) -> dict:
    body = {
        "contract_version": contract_version,
        "schema_version": schema_version,
        "project_id": project_id,
        "algorithm_revision": revision,
        "counts": {name: len(rows) for name, rows in tables.items()},
        "tables": tables,
    }
    if cleanup_capability is not None:
        # "ABSENT" is an observed fact (the source has no ledger), not an empty
        # cleanup array pretending to be complete evidence.
        body["cleanup_capability"] = str(cleanup_capability)
    return body


def _cleanup_timestamp(value: Any) -> str | None:
    """UTC-normalised timestamp for cross-engine comparison, None if unparsable."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _read_rows(database: sqlite3.Connection, sql: str) -> list[dict[str, Any]]:
    return [dict(row) for row in database.execute(sql).fetchall()]


def export_snapshot(store: AlgorithmSqlStore, *, include_cleanup: bool = False) -> dict[str, Any]:
    """Export one consistent SQLite read transaction without initialization.

    ``include_cleanup`` produces the V2 contract: the ledger is read inside the
    same transaction, and a source without the ledger table is recorded as
    ``cleanup_capability = "ABSENT"`` rather than filled with an empty array.
    """
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
            cleanup_capability = None
            if include_cleanup:
                present = database.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                    (_CLEANUP_TABLE,),
                ).fetchone()
                cleanup_capability = "PRESENT" if present is not None else "ABSENT"
                tables["cleanup"] = (
                    _read_rows(database, _CLEANUP_SQL) if present is not None else []
                )
                for row in tables["cleanup"]:
                    # The SQLite ledger is per project; the snapshot carries the
                    # project identity explicitly like every other row.
                    row["project_id"] = str(store.project_id)
                    try:
                        payload = json.loads(str(row.get("payload_json") or "{}"))
                    except ValueError as error:
                        raise AlgorithmShadowError(
                            "ALGORITHM_SHADOW_CLEANUP_PAYLOAD_INVALID",
                            "cleanup payload is not valid JSON",
                            detail=str(error),
                        ) from error
                    if not isinstance(payload, Mapping):
                        raise AlgorithmShadowError(
                            "ALGORITHM_SHADOW_CLEANUP_PAYLOAD_INVALID",
                            "cleanup payload is not an object",
                        )
                    generation = str(payload.get("generation") or "").strip()
                    if not generation:
                        raise AlgorithmShadowError(
                            "ALGORITHM_SHADOW_CLEANUP_GENERATION_MISSING",
                            "cleanup payload carries no generation",
                            detail=str(row.get("operation_id") or ""),
                        )
                    # The ledger column does not exist in SQLite: the real
                    # generation comes from the persisted payload, never "".
                    row["generation"] = generation
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
    body = _snapshot_body(
        project_id, revision, tables,
        contract_version=CONTRACT_VERSION_V2 if include_cleanup else CONTRACT_VERSION,
        schema_version=SCHEMA_VERSION_V2 if include_cleanup else SCHEMA_VERSION,
        cleanup_capability=cleanup_capability,
    )
    body["snapshot_digest"] = _digest(body)
    body["captured_at"] = datetime.now(timezone.utc).isoformat()
    return body


def _invalid(message: str, detail: str = "") -> AlgorithmShadowError:
    return AlgorithmShadowError("ALGORITHM_SHADOW_SNAPSHOT_INVALID", message, detail=detail)


def _integer(value: Any) -> int:
    if type(value) is not int or value < 0:
        raise _invalid("snapshot integer field is invalid")
    return value


def validate_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Recompute and validate the complete U1 snapshot contract."""
    if not isinstance(snapshot, Mapping):
        raise _invalid("snapshot must be an object")
    contract_version = str(snapshot.get("contract_version") or "")
    if contract_version not in _SUPPORTED_CONTRACTS:
        raise _invalid("unsupported snapshot contract_version")
    is_v2 = contract_version == CONTRACT_VERSION_V2
    expected_schema = SCHEMA_VERSION_V2 if is_v2 else SCHEMA_VERSION
    if _integer(snapshot.get("schema_version")) != expected_schema:
        raise _invalid("unsupported snapshot schema_version")
    project_id = str(snapshot.get("project_id") or "")
    if not _PROJECT_ID.fullmatch(project_id):
        raise _invalid("snapshot project_id is invalid")
    revision = _integer(snapshot.get("algorithm_revision"))
    try:
        captured = datetime.fromisoformat(str(snapshot.get("captured_at") or "").replace("Z", "+00:00"))
        if captured.tzinfo is None:
            raise ValueError
    except ValueError as error:
        raise _invalid("snapshot captured_at is invalid") from error
    expected_tables = _V2_TABLES if is_v2 else _V1_TABLES
    tables = snapshot.get("tables")
    if not isinstance(tables, Mapping) or set(tables) != set(expected_tables):
        raise _invalid("snapshot tables are incomplete or contain unrelated data")
    counts = snapshot.get("counts")
    if not isinstance(counts, Mapping) or set(counts) != set(expected_tables):
        raise _invalid("snapshot counts are invalid")
    if is_v2:
        capability = str(snapshot.get("cleanup_capability") or "")
        if capability not in {"PRESENT", "ABSENT"}:
            raise _invalid("snapshot cleanup capability is missing")
        if capability == "ABSENT" and tables["cleanup"]:
            raise _invalid("an absent cleanup domain cannot carry rows")
    elif "cleanup_capability" in snapshot or "cleanup" in tables:
        # V1 carries no cleanup evidence: an empty array must not impersonate a
        # complete V2 document.
        raise _invalid("a V1 snapshot cannot claim cleanup evidence")
    for name in expected_tables:
        values = tables.get(name)
        if not isinstance(values, list):
            raise _invalid(f"snapshot {name} must be a list")
        if _integer(counts.get(name)) != len(values):
            raise _invalid(f"snapshot {name} count does not match rows")
        for row in values:
            if not isinstance(row, Mapping):
                raise _invalid(f"snapshot {name} row is not an object")
            if any(str(key).lower() in _SENSITIVE_KEYS for key in row):
                raise _invalid("snapshot contains credential-bearing fields")

    algorithms = {}
    for row in tables["algorithms"]:
        algorithm_id = str(row.get("id") or "").strip()
        if not algorithm_id or algorithm_id in algorithms:
            raise _invalid("algorithm natural key is empty or duplicated")
        if str(row.get("project_id") or "") != project_id:
            raise _invalid("algorithm project ownership mismatch")
        algorithms[algorithm_id] = row
    version_ids: set[str] = set()
    for row in tables["versions"]:
        version_id = str(row.get("id") or "").strip()
        algorithm_id = str(row.get("algorithm_id") or "").strip()
        if not version_id or version_id in version_ids:
            raise _invalid("version natural key is empty or duplicated")
        version_ids.add(version_id)
        if algorithm_id not in algorithms:
            raise _invalid("version references an algorithm outside the snapshot")
    analyses: set[str] = set()
    for row in tables["analyses"]:
        algorithm_id = str(row.get("algorithm_id") or "").strip()
        analysis_id = str(row.get("external_analysis_id") or "").strip()
        key = f"{algorithm_id}:{analysis_id}"
        if not algorithm_id or not analysis_id or key in analyses:
            raise _invalid("external analysis natural key is empty or duplicated")
        analyses.add(key)
        if algorithm_id not in algorithms:
            raise _invalid("external analysis references an algorithm outside the snapshot")
    if is_v2:
        operations: set[str] = set()
        active_cycles: dict[tuple[str, str], str] = {}
        for row in tables["cleanup"]:
            operation_id = str(row.get("operation_id") or "").strip()
            algorithm_id = str(row.get("algorithm_id") or "").strip()
            product_id = str(row.get("product_id") or "").strip()
            generation = str(row.get("generation") or "").strip()
            state = str(row.get("state") or "").strip()
            if not operation_id or not algorithm_id or not product_id or not state:
                raise _invalid("cleanup natural key or state is empty")
            if not generation:
                raise _invalid("cleanup generation is missing")
            if operation_id in operations:
                raise _invalid("cleanup operation id is duplicated")
            operations.add(operation_id)
            if str(row.get("project_id") or "") != project_id:
                raise _invalid("cleanup project ownership mismatch")
            if state not in _CLEANUP_STATES:
                raise _invalid("cleanup state is not recognised")
            payload = row.get("payload")
            if payload is None and isinstance(row.get("payload_json"), str):
                try:
                    payload = json.loads(row["payload_json"])
                except ValueError as error:
                    raise _invalid("cleanup payload is not valid JSON") from error
            if not isinstance(payload, Mapping):
                raise _invalid("cleanup payload is missing or not an object")
            if (
                str(payload.get("project_id") or "") != project_id
                or str(payload.get("operation_id") or "") != operation_id
                or str(payload.get("algorithm_id") or "") != algorithm_id
                or str(payload.get("product_id") or "") != product_id
                or str(payload.get("generation") or "") != generation
                or str(payload.get("state") or "") != state
            ):
                raise _invalid("cleanup SQL projection disagrees with its payload")
            for field in ("created_at", "updated_at"):
                if payload.get(field) and row.get(field):
                    left = _cleanup_timestamp(payload.get(field))
                    right = _cleanup_timestamp(row.get(field))
                    if left is not None and right is not None and left != right:
                        raise _invalid(f"cleanup SQL {field} disagrees with its payload")
            if state != "CLEANUP_COMPLETED":
                if algorithm_id not in algorithms:
                    raise _invalid("active cleanup references an algorithm outside the snapshot")
                # The active ledger must be bound to the algorithm's real
                # retirement state, not just to an algorithm id that exists.
                algorithm_row = algorithms[algorithm_id]
                algorithm_payload = algorithm_row.get("payload_json")
                if isinstance(algorithm_payload, str):
                    try:
                        algorithm_payload = json.loads(algorithm_payload)
                    except ValueError as error:
                        raise _invalid("algorithm payload is not valid JSON") from error
                if not isinstance(algorithm_payload, Mapping):
                    raise _invalid("cleanup algorithm payload is missing")
                # Product/provider/active are relational columns; only the
                # extended retirement fields live in the payload.
                if (
                    str(algorithm_payload.get("external_cleanup_operation_id") or "")
                    != operation_id
                    or not algorithm_payload.get("external_delete_pending")
                    or str(algorithm_row.get("external_product_id") or "") != product_id
                    or str(algorithm_payload.get("external_deletion_status") or "") != state
                    or str(algorithm_row.get("source_type") or "") != "EXTERNAL"
                    or str(algorithm_row.get("provider_type") or "") != str(
                        (payload.get("evidence") or {}).get("provider") or ""
                    )
                    or bool(algorithm_row.get("external_active"))
                ):
                    raise _invalid("active cleanup is not bound to the algorithm retirement")
                cycle = (algorithm_id, product_id)
                owner = active_cycles.get(cycle)
                if owner is not None and owner != operation_id:
                    raise _invalid("two active cleanup cycles for one product")
                active_cycles[cycle] = operation_id
            else:
                # A completed receipt may outlive its algorithm, but it must
                # carry the trusted DeletionEvidence the contract requires.
                evidence = payload.get("evidence")
                if not isinstance(evidence, Mapping) or not all(
                    str(evidence.get(key) or "").strip()
                    for key in ("provider", "product_id", "source", "contract_id",
                                "evidence_id", "observed_at")
                ):
                    raise _invalid("completed cleanup receipt has no trusted deletion evidence")
                if str(evidence.get("product_id")) != product_id:
                    raise _invalid("completed receipt evidence names another product")
        if capability == "ABSENT":
            for row in tables["algorithms"]:
                algorithm_payload = row.get("payload_json")
                if isinstance(algorithm_payload, str):
                    try:
                        algorithm_payload = json.loads(algorithm_payload)
                    except ValueError as error:
                        raise _invalid("algorithm payload is not valid JSON") from error
                if not isinstance(algorithm_payload, Mapping):
                    continue
                if algorithm_payload.get("external_delete_pending"):
                    raise _invalid("an absent cleanup domain cannot hide a pending deletion")
    body_tables = {
        name: [dict(row) for row in tables[name]]
        for name in (expected_tables if is_v2 else _V1_TABLES)
    }
    body = _snapshot_body(
        project_id, revision, body_tables,
        contract_version=CONTRACT_VERSION_V2 if is_v2 else CONTRACT_VERSION,
        schema_version=SCHEMA_VERSION_V2 if is_v2 else SCHEMA_VERSION,
        cleanup_capability=str(snapshot.get("cleanup_capability") or "") or None,
    )
    expected = _digest(body)
    supplied = str(snapshot.get("snapshot_digest") or "")
    if len(supplied) != 64 or not hmac.compare_digest(expected, supplied):
        raise AlgorithmShadowError(
            "ALGORITHM_SHADOW_CONTENT_DIGEST_INVALID",
            "snapshot content digest does not match its contents",
            detail=f"expected {expected}",
        )
    return dict(snapshot)


def export_snapshot_from_path(
    db_path: str | Path, project_id: str, *, include_cleanup: bool = False,
) -> dict[str, Any]:
    """Export without constructing AlgorithmSqlStore (no mkdir/initialization)."""
    database_path = Path(db_path)
    probe = AlgorithmSqlStore.__new__(AlgorithmSqlStore)
    probe.json_path = database_path.parent / "algorithms.json"
    probe.project_dir = database_path.parent
    probe.db_path = database_path
    probe.project_id = str(project_id)
    return export_snapshot(probe, include_cleanup=include_cleanup)


def write_snapshot(snapshot: Mapping[str, Any], destination: str | Path) -> Path:
    validated = validate_snapshot(snapshot)
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent),
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(_canonical(validated))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return path


def load_snapshot(path: str | Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise _invalid("snapshot file cannot be read") from error
    return validate_snapshot(value)


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
    if str(snapshot.get("contract_version") or "") == CONTRACT_VERSION_V2:
        raise AlgorithmShadowError(
            "ALGORITHM_SHADOW_V2_NOT_SUPPORTED",
            "the shadow store does not persist the cleanup domain yet",
        )
    """Atomically import one validated project snapshot into PostgreSQL.

    The connection must be an idle, non-autocommit Psycopg 3 connection; the
    importer owns this transaction and rolls it back on every failure.
    """
    snapshot = validate_snapshot(snapshot)
    if bool(getattr(connection, "autocommit", False)):
        raise AlgorithmShadowError(
            "ALGORITHM_SHADOW_AUTOCOMMIT_UNSUPPORTED",
            "snapshot import requires an explicit non-autocommit transaction",
        )
    try:
        from psycopg.pq import TransactionStatus
        if connection.info.transaction_status != TransactionStatus.IDLE:
            raise AlgorithmShadowError(
                "ALGORITHM_SHADOW_TRANSACTION_BUSY",
                "snapshot import requires an idle connection",
            )
    except ImportError:
        pass
    project_id = str(snapshot["project_id"])
    revision = int(snapshot["algorithm_revision"])
    digest = str(snapshot["snapshot_digest"])
    rows = _shadow_rows(snapshot)
    try:
        with connection.cursor() as cursor:
            # Serialize the whole project import (DDL included) before reading
            # any revision. Locking after DDL can deadlock two first importers.
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (project_id,))
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
            counts = snapshot["counts"]
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
                (project_id, revision, digest, str(snapshot["contract_version"]),
                 int(snapshot["schema_version"]), int(counts["algorithms"]),
                 int(counts["versions"]), int(counts["analyses"]),
                 str(snapshot["captured_at"])),
            )
            connection.commit()
            return True
    except Exception:
        connection.rollback()
        raise


def load_shadow_snapshot(connection, project_id: str) -> dict[str, Any] | None:
    project_id = str(project_id)
    meta = None
    tables: dict[str, list[dict]] = {"algorithms": [], "versions": [], "analyses": []}
    idle = True
    try:
        from psycopg.pq import TransactionStatus
        idle = connection.info.transaction_status == TransactionStatus.IDLE
    except ImportError:
        pass
    # Idle: own and commit only the read transaction. Non-idle: never wrap the
    # caller's transaction in connection.transaction(), because that context may
    # commit it; only inspect and read inside the existing transaction.
    manager = connection.transaction() if idle and hasattr(connection, "transaction") else nullcontext()
    with manager:
        with connection.cursor() as cursor:
            if idle and hasattr(connection, "transaction"):
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            elif hasattr(connection, "transaction"):
                cursor.execute("SHOW transaction_isolation")
                level = str(cursor.fetchone()[0]).strip().lower()
                if level not in {"repeatable read", "serializable"}:
                    raise AlgorithmShadowError(
                        "ALGORITHM_SHADOW_TRANSACTION_ISOLATION_UNSUPPORTED",
                        "non-idle shadow reads require REPEATABLE READ or SERIALIZABLE",
                        detail=f"current={level}",
                    )
            cursor.execute(
                "SELECT algorithm_revision,snapshot_digest,contract_version,schema_version,captured_at,"
                "algorithm_count,version_count,analysis_count "
                "FROM w5_shadow.algorithm_snapshot WHERE project_id=%s", (project_id,),
            )
            meta = cursor.fetchone()
            if meta:
                order_by = {
                    "algorithm": "natural_key",
                    "version": "payload->>'algorithm_id', natural_key",
                    "analysis": "payload->>'algorithm_id', payload->>'external_analysis_id'",
                }
                for kind, name in (("algorithm", "algorithms"), ("version", "versions"), ("analysis", "analyses")):
                    cursor.execute(
                        "SELECT payload FROM w5_shadow.algorithm_row "
                        "WHERE project_id=%s AND kind=%s ORDER BY " + order_by[kind],
                        (project_id, kind),
                    )
                    tables[name] = [dict(payload) for (payload,) in cursor.fetchall()]
    if not meta:
        return None
    if (int(meta[5]), int(meta[6]), int(meta[7])) != (
        len(tables["algorithms"]), len(tables["versions"]), len(tables["analyses"]),
    ):
        raise AlgorithmShadowError(
            "ALGORITHM_SHADOW_METADATA_MISMATCH",
            "shadow metadata counts do not match its rows",
        )
    body = _snapshot_body(project_id, int(meta[0]), tables)
    actual_digest = _digest(body)
    stored_digest = str(meta[1])
    if not hmac.compare_digest(actual_digest, stored_digest):
        raise AlgorithmShadowError(
            "ALGORITHM_SHADOW_CONTENT_DIGEST_INVALID",
            "shadow row content no longer matches its stored digest",
            detail=f"stored={stored_digest} actual={actual_digest}",
        )
    body["snapshot_digest"] = stored_digest
    body["contract_version"] = str(meta[2])
    body["schema_version"] = int(meta[3])
    body["captured_at"] = str(meta[4])
    validate_snapshot(body)
    return body


def _snapshot_differences(source: Mapping[str, Any], shadow: Mapping[str, Any]) -> dict[str, Any]:
    differences: dict[str, Any] = {}
    for name in ("algorithms", "versions", "analyses"):
        kind = {"algorithms": "algorithm", "versions": "version", "analyses": "analysis"}[name]
        source_rows = {_natural_key(kind, row): row for row in source.get("tables", {}).get(name, [])}
        shadow_rows = {_natural_key(kind, row): row for row in shadow.get("tables", {}).get(name, [])}
        missing = sorted(set(source_rows) - set(shadow_rows))
        extra = sorted(set(shadow_rows) - set(source_rows))
        changed = sorted(key for key in set(source_rows) & set(shadow_rows)
                         if _canonical(source_rows[key]) != _canonical(shadow_rows[key]))
        if missing or extra or changed:
            differences[name] = {"missing": missing, "extra": extra, "changed": changed}
    return differences


def reconcile(source: Mapping[str, Any], shadow: Mapping[str, Any] | None) -> dict[str, Any]:
    """Compare two snapshots; report detailed differences when both are valid."""
    source = validate_snapshot(source)
    if shadow is None:
        return {"same": False, "reason": "SHADOW_MISSING", "differences": {}}
    shadow = validate_snapshot(shadow)
    source_revision = int(source.get("algorithm_revision") or 0)
    shadow_revision = int(shadow.get("algorithm_revision") or 0)
    if source_revision != shadow_revision:
        return {
            "same": False, "reason": "SOURCE_REVISION_CHANGED",
            "source_revision": source_revision, "shadow_revision": shadow_revision,
            "differences": {},
        }
    differences = _snapshot_differences(source, shadow)
    if str(source.get("snapshot_digest")) != str(shadow.get("snapshot_digest")):
        return {"same": False, "reason": "SNAPSHOT_DIGEST_MISMATCH",
                "source_revision": source_revision, "shadow_revision": shadow_revision,
                "differences": differences}
    if differences:
        return {"same": False, "reason": "DATA_MISMATCH",
                "source_revision": source_revision, "shadow_revision": shadow_revision,
                "differences": differences}
    return {"same": True, "reason": "OK", "source_revision": source_revision,
            "shadow_revision": shadow_revision, "differences": {}}
