"""Versioned PostgreSQL schema for the algorithm-domain cutover (T8.2/T8.4).

The schema lives in its own ``w5_algorithm`` schema and is created or upgraded
only by an explicit tool call.  Nothing here runs at application startup: the
repository refuses to work unless the recorded schema version is exactly the
version this build knows.

Version identity is explicit: every applied migration is recorded with its
version, name, checksum and actor.  Re-running an up-to-date schema is a no-op,
a newer schema is refused (never downgraded), and an edited migration is
refused through its checksum.
"""
from __future__ import annotations

import hashlib
from typing import Any

SCHEMA_NAME = "w5_algorithm"
SCHEMA_VERSION = 2
LOCK_KEY = "w5_algorithm:schema"
APPLIED_BY_DEFAULT = "algorithm-migration-cli"

_TABLE_NAMES = (
    "schema_migration",
    "algorithm",
    "algorithm_version",
    "algorithm_external_analysis",
    "store_revision",
    "migration_run",
    "cutover_state",
    "external_algorithm_cleanup",
)

_V1 = (
    1,
    "algorithm-domain-relational-v1",
    (
        "CREATE SCHEMA IF NOT EXISTS w5_algorithm",
        """
        CREATE TABLE IF NOT EXISTS w5_algorithm.schema_migration (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            checksum CHAR(64) NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            applied_by TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS w5_algorithm.algorithm (
            project_id TEXT NOT NULL,
            id TEXT NOT NULL,
            name TEXT NOT NULL,
            remark TEXT NOT NULL DEFAULT '',
            industry TEXT NOT NULL DEFAULT '',
            algorithm_type TEXT NOT NULL DEFAULT '',
            current_version_id TEXT,
            source_type TEXT,
            provider_type TEXT,
            external_product_id TEXT,
            external_product_code TEXT,
            external_category_id TEXT,
            external_analysis_id TEXT,
            external_active BOOLEAN,
            master_data_readonly BOOLEAN,
            external_last_synced_at TEXT,
            created_at TEXT,
            updated_at TEXT,
            sort_index BIGINT NOT NULL DEFAULT 0,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            PRIMARY KEY (project_id, id)
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_w5_algorithm_project_sort
            ON w5_algorithm.algorithm(project_id, sort_index, created_at, id)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_w5_algorithm_source
            ON w5_algorithm.algorithm(project_id, source_type)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_w5_algorithm_external_product
            ON w5_algorithm.algorithm(project_id, provider_type, external_product_id)
        """,
        """
        CREATE TABLE IF NOT EXISTS w5_algorithm.algorithm_version (
            project_id TEXT NOT NULL,
            id TEXT NOT NULL,
            algorithm_id TEXT NOT NULL,
            version_name TEXT,
            version_no TEXT,
            training_job_id TEXT,
            framework TEXT,
            training_status TEXT,
            stored_path TEXT,
            model_name TEXT,
            artifact_verified BOOLEAN,
            trainable BOOLEAN,
            external_analysis_id TEXT,
            external_algo_version_id TEXT,
            external_publish_status TEXT,
            created_at TEXT,
            finished_at TEXT,
            sort_index BIGINT NOT NULL DEFAULT 0,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            PRIMARY KEY (project_id, id),
            FOREIGN KEY (project_id, algorithm_id)
                REFERENCES w5_algorithm.algorithm(project_id, id) ON DELETE CASCADE
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_w5_algorithm_version_owner
            ON w5_algorithm.algorithm_version(project_id, algorithm_id, sort_index)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_w5_algorithm_version_job
            ON w5_algorithm.algorithm_version(project_id, training_job_id)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_w5_algorithm_version_external
            ON w5_algorithm.algorithm_version(project_id, external_algo_version_id)
        """,
        """
        CREATE TABLE IF NOT EXISTS w5_algorithm.algorithm_external_analysis (
            project_id TEXT NOT NULL,
            algorithm_id TEXT NOT NULL,
            external_analysis_id TEXT NOT NULL,
            analysis_name TEXT,
            analysis_type TEXT,
            is_default BOOLEAN NOT NULL DEFAULT FALSE,
            active BOOLEAN NOT NULL DEFAULT TRUE,
            compute_platform_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
            sort_index BIGINT NOT NULL DEFAULT 0,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            PRIMARY KEY (project_id, algorithm_id, external_analysis_id),
            FOREIGN KEY (project_id, algorithm_id)
                REFERENCES w5_algorithm.algorithm(project_id, id) ON DELETE CASCADE
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_w5_algorithm_analysis_sort
            ON w5_algorithm.algorithm_external_analysis(
                project_id, algorithm_id, sort_index, external_analysis_id
            )
        """,
        """
        CREATE TABLE IF NOT EXISTS w5_algorithm.store_revision (
            project_id TEXT PRIMARY KEY,
            algorithm_revision BIGINT NOT NULL DEFAULT 0,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS w5_algorithm.migration_run (
            run_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            snapshot_digest CHAR(64) NOT NULL,
            content_digest CHAR(64) NOT NULL,
            algorithm_revision BIGINT NOT NULL,
            mode TEXT NOT NULL CHECK (mode IN ('DRY_RUN','APPLY')),
            status TEXT NOT NULL
                CHECK (status IN ('RUNNING','COMPLETED','FAILED','ABORTED')),
            actor TEXT NOT NULL,
            started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            heartbeat_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            finished_at TIMESTAMPTZ,
            detail JSONB NOT NULL DEFAULT '{}'::jsonb
        )
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_w5_algorithm_run_active
            ON w5_algorithm.migration_run(project_id) WHERE status = 'RUNNING'
        """,
        """
        CREATE TABLE IF NOT EXISTS w5_algorithm.cutover_state (
            project_id TEXT PRIMARY KEY,
            authoritative_provider TEXT NOT NULL
                CHECK (authoritative_provider IN ('sqlite','postgresql')),
            algorithm_revision BIGINT NOT NULL,
            snapshot_digest CHAR(64) NOT NULL,
            content_digest CHAR(64) NOT NULL,
            writer_generation INTEGER NOT NULL CHECK (writer_generation >= 0),
            admission_id TEXT NOT NULL,
            admitted_at TIMESTAMPTZ NOT NULL,
            revoked_at TIMESTAMPTZ,
            evidence JSONB NOT NULL DEFAULT '{}'::jsonb
        )
        """,
    ),
)

#: V2 adds the external-algorithm cleanup ledger to the same domain schema. It
#: is an append-only migration: an upgraded database keeps every V1 row, and the
#: cleanup receipts survive the deletion of their algorithm (the ledger has no
#: foreign key to ``algorithm`` on purpose).
_V2 = (
    2,
    "algorithm-domain-cleanup-v2",
    (
        """
        CREATE TABLE IF NOT EXISTS w5_algorithm.external_algorithm_cleanup (
            project_id TEXT NOT NULL,
            operation_id TEXT NOT NULL,
            algorithm_id TEXT NOT NULL,
            product_id TEXT NOT NULL,
            generation TEXT NOT NULL,
            state TEXT NOT NULL,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (project_id, operation_id)
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_w5_algorithm_cleanup_project_created
            ON w5_algorithm.external_algorithm_cleanup(
                project_id, created_at, operation_id
            )
        """,
        # The same rule as the SQLite ledger: one active cleanup cycle per
        # (project, algorithm, product); completed receipts are history.
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_w5_algorithm_cleanup_active
            ON w5_algorithm.external_algorithm_cleanup(
                project_id, algorithm_id, product_id
            ) WHERE state <> 'CLEANUP_COMPLETED'
        """,
    ),
)

#: Ordered, append-only migration list.  Never edit an applied migration; add a
#: new tuple entry and bump ``SCHEMA_VERSION``.
MIGRATIONS = (_V1, _V2)
_MIGRATIONS_BY_VERSION = {
    version: (name, statements) for version, name, statements in MIGRATIONS
}


class AlgorithmSchemaError(RuntimeError):
    def __init__(self, code: str, message: str, *, detail: str = ""):
        super().__init__(message)
        self.code = str(code)
        self.detail = str(detail or "")


class _SchemaDryRun(Exception):
    pass


def require_idle_transaction(connection, *, purpose: str = "tool operation") -> None:
    """Guarantee that ``connection.transaction()`` is a real transaction.

    psycopg turns ``transaction()`` into a SAVEPOINT when the connection is
    already inside a transaction, which would defer the commit to the caller.
    This tool owns its transactions, so a lingering read transaction is rolled
    back and a write transaction is refused.
    """
    from psycopg.pq import TransactionStatus

    status = connection.info.transaction_status
    if status == TransactionStatus.IDLE:
        return
    if status in (TransactionStatus.INTRANS, TransactionStatus.INERROR):
        connection.rollback()
        return
    raise AlgorithmSchemaError(
        "ALGORITHM_PG_TRANSACTION_BUSY",
        f"{purpose} requires an idle PostgreSQL connection",
        detail=f"transaction_status={status!r}",
    )


def migration_checksum(version: int) -> str:
    name, statements = _MIGRATIONS_BY_VERSION[version]
    body = name + "\n" + "\n".join(statements)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def expected_tables() -> tuple[str, ...]:
    return _TABLE_NAMES


def _status(cursor) -> dict[str, Any]:
    cursor.execute("SELECT to_regclass(%s) AS present", (f"{SCHEMA_NAME}.schema_migration",))
    present = cursor.fetchone()["present"] is not None
    applied: list[dict[str, Any]] = []
    version = 0
    if present:
        cursor.execute(
            "SELECT version,name,checksum,applied_at,applied_by "
            "FROM w5_algorithm.schema_migration ORDER BY version"
        )
        applied = [dict(row) for row in cursor.fetchall()]
        version = max((int(row["version"]) for row in applied), default=0)
    pending = [item for item in _MIGRATIONS_BY_VERSION if item > version]
    mismatched = [
        row["version"] for row in applied
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
            present and version == SCHEMA_VERSION and not pending and not missing_tables
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
        raise AlgorithmSchemaError(
            "ALGORITHM_PG_SCHEMA_AUTOCOMMIT_UNSUPPORTED",
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
                    raise AlgorithmSchemaError(
                        "ALGORITHM_PG_SCHEMA_CHECKSUM_MISMATCH",
                        "an applied schema migration no longer matches this tool",
                        detail=f"versions={status['checksum_mismatch']}",
                    )
                if status["version"] > SCHEMA_VERSION:
                    raise AlgorithmSchemaError(
                        "ALGORITHM_PG_SCHEMA_NEWER_THAN_TOOL",
                        "database schema is newer than this tool; refusing downgrade",
                        detail=f"database={status['version']} tool={SCHEMA_VERSION}",
                    )
                pending = list(status["pending"])
                if status["present"] and not pending and status["missing_tables"]:
                    raise AlgorithmSchemaError(
                        "ALGORITHM_PG_SCHEMA_INCOMPLETE",
                        "recorded schema version is missing required tables",
                        detail=f"missing_tables={status['missing_tables']}",
                    )
                if not pending:
                    result["already_current"] = True
                    result["version"] = status["version"]
                    result["status"] = status
                    return result
                if not allow_upgrade:
                    raise AlgorithmSchemaError(
                        "ALGORITHM_PG_SCHEMA_UPGRADE_REQUIRED",
                        "explicit --allow-upgrade is required to change the schema",
                        detail=f"current={status['version']} pending={pending}",
                    )
                for version in pending:
                    name, statements = _MIGRATIONS_BY_VERSION[version]
                    for statement in statements:
                        cursor.execute(statement)
                    cursor.execute(
                        "INSERT INTO w5_algorithm.schema_migration"
                        "(version,name,checksum,applied_by) VALUES(%s,%s,%s,%s)",
                        (version, name, migration_checksum(version), actor),
                    )
                    result["applied"].append({"version": version, "name": name})
                result["version"] = (pending[-1] if pending else status["version"])
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
        raise AlgorithmSchemaError(
            "ALGORITHM_PG_SCHEMA_NOT_CURRENT",
            "PostgreSQL algorithm schema is missing or not at the target version",
            detail=(
                f"version={status['version']} target={status['target_version']} "
                f"pending={status['pending']} missing_tables={status['missing_tables']}"
            ),
        )
    return status
