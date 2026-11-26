"""Storage-source snapshot export, idempotent import and reconciliation (U2).

The migration unit is small but the safety rules are the same as every other
domain cutover:

* the export is a deterministic snapshot of the authoritative SQLite owner —
  no export timestamps, content digest over normalized rows;
* the import is idempotent (a second identical import changes nothing), never
  overwrites a *newer* target row, and keeps the "at most one default source"
  invariant inside one transaction;
* reconciliation explains every difference instead of guessing, and health
  evidence (which legitimately changes per process) is reported separately from
  the configuration identity that must match.

Credential material is never exported: only the SecretStore reference.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Mapping

from .storage.source_repository import _safe_config
from .storage_source_postgres_schema import SCHEMA_NAME

CONTRACT_VERSION = "storage-source-migration-v1"
#: Columns whose value defines the business identity of a storage source.
IDENTITY_FIELDS = (
    "id",
    "name",
    "type",
    "config",
    "secret_ref",
    "enabled",
    "is_default",
    "runtime_revision",
)
#: Evidence that legitimately differs between two live owners.
HEALTH_FIELDS = (
    "health_status",
    "health_message",
    "last_checked_at",
    "updated_at",
    "created_at",
)

_COLUMNS = (
    "id,name,type,config,secret_ref,runtime_revision,enabled,is_default,"
    "health_status,health_message,last_checked_at,created_at,updated_at"
)
#: The SQLite owner keeps the config as JSON text in ``config_json``.
_SQLITE_COLUMNS = _COLUMNS.replace("type,config,", "type,config_json AS config,")


class StorageSourceMigrationError(RuntimeError):
    """Migration failure with a stable machine-readable code."""

    def __init__(self, code: str, message: str, *, detail: str = ""):
        super().__init__(message)
        self.code = str(code)
        self.detail = str(detail or "")


def _digest(rows: list[dict[str, Any]]) -> str:
    """Digest of the business identity only.

    Health evidence and timestamps legitimately differ between two live owners
    (a health check runs per process), so they are exported for transparency but
    never affect whether the migration is the same configuration.
    """
    body = json.dumps(
        {
            "rows": sorted(
                (
                    {field: row[field] for field in IDENTITY_FIELDS}
                    for row in rows
                ),
                key=lambda row: str(row["id"]),
            )
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _snapshot(scope: str, backend: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: str(row["id"]))
    return {
        "contract_version": CONTRACT_VERSION,
        "scope": str(scope),
        "backend": str(backend),
        "counts": {"sources": len(ordered)},
        "rows": ordered,
        "content_digest": _digest(ordered),
    }


def _normalize_row(row: Mapping[str, Any]) -> dict[str, Any]:
    config = row.get("config")
    if isinstance(config, str):
        try:
            config = json.loads(config or "{}")
        except ValueError as error:
            raise StorageSourceMigrationError(
                "STORAGE_SOURCE_MIGRATION_CONFIG_INVALID",
                "storage source config is not valid JSON",
                detail=f"id={row.get('id')!r} {error}",
            ) from error
    if not isinstance(config, Mapping):
        raise StorageSourceMigrationError(
            "STORAGE_SOURCE_MIGRATION_CONFIG_INVALID",
            "storage source config is not an object",
            detail=f"id={row.get('id')!r}",
        )
    # The export/import path must never introduce credential material that the
    # live owner would have refused, even if an old row somehow holds it.
    safe_config = _safe_config(config)
    return {
        "id": str(row["id"]),
        "name": str(row["name"]),
        "type": str(row["type"]),
        "config": safe_config,
        "secret_ref": str(row.get("secret_ref") or ""),
        "runtime_revision": int(row.get("runtime_revision") or 1),
        "enabled": bool(row.get("enabled")),
        "is_default": bool(row.get("is_default")),
        "health_status": str(row.get("health_status") or "UNKNOWN"),
        "health_message": str(row.get("health_message") or ""),
        "last_checked_at": row.get("last_checked_at"),
        "created_at": str(row.get("created_at") or ""),
        "updated_at": str(row.get("updated_at") or ""),
    }


def _read_sqlite_snapshot(path: str | Path, scope: str) -> list[dict[str, Any]]:
    database_path = Path(path)
    if not database_path.is_file():
        raise StorageSourceMigrationError(
            "STORAGE_SOURCE_MIGRATION_SOURCE_MISSING",
            "the SQLite storage-source database does not exist",
            detail=str(database_path),
        )
    try:
        with closing(
            sqlite3.connect(
                database_path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5
            )
        ) as database:
            database.row_factory = sqlite3.Row
            rows = database.execute(
                f"SELECT {_SQLITE_COLUMNS} FROM storage_sources ORDER BY id"
            ).fetchall()
    except sqlite3.Error as error:
        raise StorageSourceMigrationError(
            "STORAGE_SOURCE_MIGRATION_SOURCE_UNREADABLE",
            "the SQLite storage-source database cannot be read",
            detail=str(error),
        ) from error
    return [_normalize_row(dict(row)) for row in rows]


def export_snapshot(path: str | Path, scope: str) -> dict[str, Any]:
    """Deterministic snapshot of the authoritative SQLite owner."""
    return _snapshot(str(scope), "sqlite", _read_sqlite_snapshot(path, scope))


def export_target_snapshot(connection, scope: str) -> dict[str, Any]:
    """The same snapshot shape, read from the PostgreSQL target."""
    from psycopg.rows import dict_row

    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            f"SELECT {_COLUMNS} FROM {SCHEMA_NAME}.storage_source "
            "WHERE scope=%s ORDER BY id",
            (str(scope),),
        )
        rows = cursor.fetchall()
    return _snapshot(str(scope), "postgresql", [_normalize_row(row) for row in rows])


def _existing_rows(connection, scope: str) -> dict[str, dict[str, Any]]:
    return {
        str(row["id"]): row
        for row in export_target_snapshot(connection, scope)["rows"]
    }


def import_snapshot(connection, snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Idempotently publish one snapshot into the PostgreSQL target.

    Returns the applied counters. A second identical import changes nothing; a
    target row that is *newer* than the snapshot is never overwritten (the import
    raises instead, because that means the snapshot is not the same lineage).
    """
    if str(snapshot.get("contract_version") or "") != CONTRACT_VERSION:
        raise StorageSourceMigrationError(
            "STORAGE_SOURCE_MIGRATION_CONTRACT_MISMATCH",
            "storage-source snapshot contract does not match this tool",
            detail=f"contract={snapshot.get('contract_version')!r}",
        )
    scope = str(snapshot.get("scope") or "")
    if not scope:
        raise StorageSourceMigrationError(
            "STORAGE_SOURCE_MIGRATION_SCOPE_MISSING",
            "storage-source snapshot has no scope",
        )
    rows = [_normalize_row(row) for row in snapshot.get("rows") or []]
    ids = [row["id"] for row in rows]
    if len(set(ids)) != len(ids):
        raise StorageSourceMigrationError(
            "STORAGE_SOURCE_MIGRATION_DUPLICATE_ID",
            "storage-source snapshot repeats a source id",
        )
    defaults = [row["id"] for row in rows if row["is_default"]]
    if len(defaults) > 1:
        raise StorageSourceMigrationError(
            "STORAGE_SOURCE_MIGRATION_DUPLICATE_DEFAULT",
            "storage-source snapshot declares more than one default source",
            detail=f"ids={defaults}",
        )
    counters = {
        "scope": scope,
        "inserted": 0,
        "updated": 0,
        "unchanged": 0,
        "applied": False,
    }
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))",
            (f"storage_source_migration:{scope}",),
        )
        existing = _existing_rows(connection, scope)
        newer = [
            row["id"]
            for row in rows
            if row["id"] in existing
            and int(existing[row["id"]]["runtime_revision"]) > row["runtime_revision"]
        ]
        if newer:
            raise StorageSourceMigrationError(
                "STORAGE_SOURCE_MIGRATION_REVISION_REGRESSION",
                "the target already holds a newer storage-source generation",
                detail=f"ids={newer}",
            )
        # Publish the default flag last and atomically: clearing first keeps the
        # partial unique index satisfied inside the transaction.
        if defaults:
            cursor.execute(
                f"UPDATE {SCHEMA_NAME}.storage_source SET is_default=FALSE "
                "WHERE scope=%s AND is_default AND id<>%s",
                (scope, defaults[0]),
            )
        for row in rows:
            current = existing.get(row["id"])
            values = (
                scope,
                row["id"],
                row["name"],
                row["type"],
                json.dumps(row["config"], ensure_ascii=False, sort_keys=True),
                row["secret_ref"],
                row["runtime_revision"],
                row["enabled"],
                row["is_default"],
                row["health_status"],
                row["health_message"],
                row["last_checked_at"],
                row["created_at"],
                row["updated_at"],
            )
            if current is None:
                cursor.execute(
                    f"INSERT INTO {SCHEMA_NAME}.storage_source"
                    "(scope,id,name,type,config,secret_ref,runtime_revision,"
                    "enabled,is_default,health_status,health_message,"
                    "last_checked_at,created_at,updated_at) "
                    "VALUES(%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    values,
                )
                counters["inserted"] += 1
                continue
            if _identity(current) == _identity(row):
                counters["unchanged"] += 1
                continue
            cursor.execute(
                f"UPDATE {SCHEMA_NAME}.storage_source SET "
                "name=%s, type=%s, config=%s::jsonb, secret_ref=%s, "
                "runtime_revision=%s, enabled=%s, is_default=%s, "
                "health_status=%s, health_message=%s, last_checked_at=%s, "
                "created_at=%s, updated_at=%s "
                "WHERE scope=%s AND id=%s",
                (
                    row["name"],
                    row["type"],
                    json.dumps(row["config"], ensure_ascii=False, sort_keys=True),
                    row["secret_ref"],
                    row["runtime_revision"],
                    row["enabled"],
                    row["is_default"],
                    row["health_status"],
                    row["health_message"],
                    row["last_checked_at"],
                    row["created_at"],
                    row["updated_at"],
                    scope,
                    row["id"],
                ),
            )
            counters["updated"] += 1
    counters["applied"] = bool(counters["inserted"] or counters["updated"])
    return counters


def _identity(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return tuple(
        json.dumps(row[field], sort_keys=True, ensure_ascii=False)
        if field == "config"
        else row[field]
        for field in IDENTITY_FIELDS
    )


def reconcile(source: Mapping[str, Any], target: Mapping[str, Any] | None) -> dict[str, Any]:
    """Explain every difference between the snapshot and the target."""
    if target is None:
        return {
            "same": False,
            "verdict": "TARGET_MISSING",
            "checks": {},
            "blocking_findings": ["target_missing"],
            "informational_differences": [],
        }
    source_rows = {str(row["id"]): _normalize_row(row) for row in source.get("rows") or []}
    target_rows = {str(row["id"]): _normalize_row(row) for row in target.get("rows") or []}
    missing = sorted(set(source_rows) - set(target_rows))
    extra = sorted(set(target_rows) - set(source_rows))
    field_differences: list[dict[str, Any]] = []
    health_differences: list[dict[str, Any]] = []
    for source_id in sorted(set(source_rows) & set(target_rows)):
        left, right = source_rows[source_id], target_rows[source_id]
        for field in IDENTITY_FIELDS:
            if left[field] != right[field]:
                field_differences.append(
                    {"id": source_id, "field": field, "source": left[field], "target": right[field]}
                )
        for field in HEALTH_FIELDS:
            if left[field] != right[field]:
                health_differences.append(
                    {"id": source_id, "field": field, "source": left[field], "target": right[field]}
                )
    source_defaults = [row["id"] for row in source_rows.values() if row["is_default"]]
    target_defaults = [row["id"] for row in target_rows.values() if row["is_default"]]
    blocking: list[str] = []
    if missing:
        blocking.append("missing_rows")
    if extra:
        blocking.append("extra_rows")
    if field_differences:
        blocking.append("identity_differences")
    if len(target_defaults) != 1:
        blocking.append("target_default_not_unique")
    if source_defaults and target_defaults and source_defaults != target_defaults:
        blocking.append("default_mismatch")
    if str(source.get("content_digest") or "") != str(target.get("content_digest") or ""):
        blocking.append("content_digest_mismatch")
    return {
        "same": not blocking,
        "verdict": "OK" if not blocking else "MISMATCH",
        "checks": {
            "counts": {"source": len(source_rows), "target": len(target_rows)},
            "missing_ids": missing,
            "extra_ids": extra,
            "identity_differences": field_differences,
            "source_default": source_defaults[0] if source_defaults else None,
            "target_default": target_defaults[0] if len(target_defaults) == 1 else None,
            "source_content_digest": source.get("content_digest"),
            "target_content_digest": target.get("content_digest"),
        },
        "blocking_findings": blocking,
        "informational_differences": health_differences,
    }
