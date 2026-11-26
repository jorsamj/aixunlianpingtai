"""PostgreSQL schema for storage-source metadata (U2).

Storage sources are platform-scoped configuration: a stable source id, a
default-source flag with at-most-one invariant, a runtime revision used by tasks
to detect configuration drift, health evidence and a SecretStore *reference*
(never a plaintext credential).  This module owns the schema only; SQL for the
business reads/writes lives in :mod:`platform_core.storage_source_postgres_store`.

The project scope is explicit because one PostgreSQL database can host several
deployments (the SQLite file was per data directory).  ``STORAGE_SOURCE_SCOPE``
is the platform-wide scope used by the business code; migration tooling may pass
another scope for an isolated verification database.
"""
from __future__ import annotations

import hashlib
from typing import Any

SCHEMA_NAME = "w4_storage_source"
SCHEMA_VERSION = 1
LOCK_KEY = "w4_storage_source:schema"
APPLIED_BY_DEFAULT = "storage-source-migration-cli"

_TABLE_NAMES = (
    "schema_migration",
    "storage_source",
)

_V1 = (
    1,
    "storage-source-relational-v1",
    (
        "CREATE SCHEMA IF NOT EXISTS w4_storage_source",
        """
        CREATE TABLE IF NOT EXISTS w4_storage_source.schema_migration (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            checksum CHAR(64) NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            applied_by TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS w4_storage_source.storage_source (
            scope TEXT NOT NULL,
            id TEXT NOT NULL,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            config JSONB NOT NULL DEFAULT '{}'::jsonb,
            secret_ref TEXT NOT NULL DEFAULT '',
            runtime_revision BIGINT NOT NULL DEFAULT 1,
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            is_default BOOLEAN NOT NULL DEFAULT FALSE,
            health_status TEXT NOT NULL DEFAULT 'UNKNOWN',
            health_message TEXT NOT NULL DEFAULT '',
            last_checked_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (scope, id),
            CONSTRAINT storage_source_id_format
                CHECK (id ~ '^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$'),
            CONSTRAINT storage_source_runtime_revision_positive
                CHECK (runtime_revision >= 1)
        )
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_storage_source_name
            ON w4_storage_source.storage_source(scope, name)
        """,
        # At most one default source per scope.  The SQLite owner used the same
        # partial unique index, so a concurrent switch cannot publish two.
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_storage_source_default
            ON w4_storage_source.storage_source(scope) WHERE is_default
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_storage_source_type_enabled
            ON w4_storage_source.storage_source(scope, type, enabled)
        """,
    ),
)

MIGRATIONS = (_V1,)
_MIGRATIONS_BY_VERSION = {
    version: (name, statements) for version, name, statements in MIGRATIONS
}


class StorageSourceSchemaError(RuntimeError):
    """Schema failure with a stable machine-readable code."""

    def __init__(self, code: str, message: str, *, detail: str = ""):
        super().__init__(message)
        self.code = str(code)
        self.detail = str(detail or "")


class _SchemaDryRun(Exception):
    pass


def migration_checksum(version: int) -> str:
    name, statements = _MIGRATIONS_BY_VERSION[version]
    body = name + "\n" + "\n".join(statements)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def expected_tables() -> tuple[str, ...]:
    return _TABLE_NAMES


def require_idle_transaction(connection, *, purpose: str = "tool operation") -> None:
    """Same guard as the algorithm schema: the tool owns its transaction."""
    from psycopg.pq import TransactionStatus

    status = connection.info.transaction_status
    if status == TransactionStatus.IDLE:
        return
    if status in (TransactionStatus.INTRANS, TransactionStatus.INERROR):
        connection.rollback()
        return
    raise StorageSourceSchemaError(
        "STORAGE_SOURCE_PG_TRANSACTION_BUSY",
        f"{purpose} requires an idle PostgreSQL connection",
        detail=f"transaction_status={status!r}",
    )


def _status(cursor) -> dict[str, Any]:
    cursor.execute(
        "SELECT to_regclass(%s) AS present", (f"{SCHEMA_NAME}.schema_migration",)
    )
    present = cursor.fetchone()["present"] is not None
    applied: list[dict[str, Any]] = []
    version = 0
    if present:
        cursor.execute(
            "SELECT version,name,checksum,applied_at,applied_by "
            "FROM w4_storage_source.schema_migration ORDER BY version"
        )
        applied = [dict(row) for row in cursor.fetchall()]
        version = max((int(row["version"]) for row in applied), default=0)
    pending = [item for item in _MIGRATIONS_BY_VERSION if item > version]
    mismatched = [
        row["version"]
        for row in applied
        if int(row["version"]) in _MIGRATIONS_BY_VERSION
        and str(row["checksum"]) != migration_checksum(int(row["version"]))
    ]
    missing_tables: list[str] = []
    if present:
        cursor.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = %s",
            (SCHEMA_NAME,),
        )
        existing = {str(row["table_name"]) for row in cursor.fetchall()}
        missing_tables = sorted(set(_TABLE_NAMES) - existing)
    return {
        "schema": SCHEMA_NAME,
        "present": present,
        "version": version,
        "target_version": SCHEMA_VERSION,
        "pending": pending,
        "applied": [
            {
                "version": int(row["version"]),
                "name": str(row["name"]),
                "checksum": str(row["checksum"]),
                "applied_at": str(row["applied_at"]),
                "applied_by": str(row["applied_by"]),
            }
            for row in applied
        ],
        "checksum_mismatch": mismatched,
        "missing_tables": missing_tables,
        "up_to_date": (
            present
            and version == SCHEMA_VERSION
            and not pending
            and not missing_tables
            and not mismatched
        ),
    }


def schema_status(connection) -> dict[str, Any]:
    from psycopg.rows import dict_row

    with connection.cursor(row_factory=dict_row) as cursor:
        return _status(cursor)


def ensure_schema(
    connection,
    *,
    allow_upgrade: bool = False,
    dry_run: bool = False,
    actor: str = APPLIED_BY_DEFAULT,
) -> dict[str, Any]:
    """Create or upgrade the schema explicitly; never called at startup."""
    from psycopg.rows import dict_row

    if bool(getattr(connection, "autocommit", False)):
        raise StorageSourceSchemaError(
            "STORAGE_SOURCE_PG_SCHEMA_AUTOCOMMIT_UNSUPPORTED",
            "schema migration requires an explicit transaction",
        )
    actor = str(actor or APPLIED_BY_DEFAULT)
    require_idle_transaction(connection, purpose="schema migration")
    result: dict[str, Any] = {
        "schema": SCHEMA_NAME,
        "target_version": SCHEMA_VERSION,
        "applied": [],
        "already_current": False,
        "dry_run": bool(dry_run),
    }
    try:
        with connection.transaction():
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (LOCK_KEY,))
                status = _status(cursor)
                if status["checksum_mismatch"]:
                    raise StorageSourceSchemaError(
                        "STORAGE_SOURCE_PG_SCHEMA_CHECKSUM_MISMATCH",
                        "an applied schema migration no longer matches this tool",
                        detail=f"versions={status['checksum_mismatch']}",
                    )
                if status["version"] > SCHEMA_VERSION:
                    raise StorageSourceSchemaError(
                        "STORAGE_SOURCE_PG_SCHEMA_NEWER_THAN_TOOL",
                        "database schema is newer than this tool; refusing downgrade",
                        detail=f"database={status['version']} tool={SCHEMA_VERSION}",
                    )
                pending = list(status["pending"])
                if status["present"] and not pending and status["missing_tables"]:
                    raise StorageSourceSchemaError(
                        "STORAGE_SOURCE_PG_SCHEMA_INCOMPLETE",
                        "recorded schema version is missing required tables",
                        detail=f"missing_tables={status['missing_tables']}",
                    )
                if not pending:
                    result["already_current"] = True
                    result["version"] = status["version"]
                    result["status"] = status
                    return result
                if not allow_upgrade:
                    raise StorageSourceSchemaError(
                        "STORAGE_SOURCE_PG_SCHEMA_UPGRADE_REQUIRED",
                        "explicit --allow-upgrade is required to change the schema",
                        detail=f"current={status['version']} pending={pending}",
                    )
                for version in pending:
                    name, statements = _MIGRATIONS_BY_VERSION[version]
                    for statement in statements:
                        cursor.execute(statement)
                    cursor.execute(
                        "INSERT INTO w4_storage_source.schema_migration"
                        "(version,name,checksum,applied_by) VALUES(%s,%s,%s,%s)",
                        (version, name, migration_checksum(version), actor),
                    )
                    result["applied"].append({"version": version, "name": name})
                result["version"] = pending[-1] if pending else status["version"]
                result["status"] = _status(cursor)
                if dry_run:
                    raise _SchemaDryRun()
    except _SchemaDryRun:
        result["dry_run"] = True
        result["rolled_back"] = True
    return result


def require_current_schema(connection) -> dict[str, Any]:
    status = schema_status(connection)
    if not status["up_to_date"]:
        raise StorageSourceSchemaError(
            "STORAGE_SOURCE_PG_SCHEMA_NOT_CURRENT",
            "PostgreSQL storage-source schema is missing or not at the target version",
            detail=(
                f"version={status['version']} target={status['target_version']} "
                f"pending={status['pending']} missing_tables={status['missing_tables']}"
            ),
        )
    return status
