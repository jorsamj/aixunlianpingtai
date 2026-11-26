"""PostgreSQL implementation of the storage-source metadata owner (U2).

Same public contract as :class:`StorageSourceRepository` (SQLite): ``list``,
``get``, ``default``, ``create``, ``update``, ``set_default``, ``record_health``,
``delete``, ``reference_counter`` and the ``runtime_revision`` semantics that
tasks use to detect configuration drift.

Deliberate boundaries:

* credentials are never copied here — only the existing SecretStore reference
  (``secret_ref``) is stored, and a sensitive config key is still refused;
* cross-domain deletion stays blocked unless the operator admitted it: the
  material reference evidence and the storage-provider decommissioning proof are
  owned by other domains, so removing a row here without that evidence would
  orphan objects.  Ordinary configuration reads/writes are fully served;
* this provider never opens SQLite and never falls back to it.  A missing
  admission record or schema fails closed.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Mapping

from .storage.errors import redact_storage_error
from .storage.models import StorageType
from .storage.source_repository import (
    PROVIDER_POSTGRESQL,
    StorageSource,
    StorageSourceAdmissionRequired,
    StorageSourceConflictError,
    StorageSourceOperationBlocked,
    StorageSourceRepositoryError,
    _IDENTIFIER,
    _now,
    _safe_config,
)
from .storage_source_postgres_schema import (
    SCHEMA_NAME,
    StorageSourceSchemaError,
    require_current_schema,
)

_UNIQUE_VIOLATION = "23505"


def _psycopg():
    try:
        import psycopg
    except ImportError as error:  # pragma: no cover - depends on environment
        raise StorageSourceRepositoryError(
            "STORAGE_SOURCE_POSTGRES_DRIVER_MISSING",
            "psycopg 3 is required for the PostgreSQL storage-source provider",
        ) from error
    return psycopg


def _from_row(row: Mapping[str, Any]) -> StorageSource:
    config = row["config"]
    if isinstance(config, str):
        config = json.loads(config or "{}")
    return StorageSource(
        id=str(row["id"]),
        name=str(row["name"]),
        type=str(row["type"]),
        config=dict(config or {}),
        secret_ref=str(row["secret_ref"] or ""),
        runtime_revision=int(row["runtime_revision"]),
        enabled=bool(row["enabled"]),
        is_default=bool(row["is_default"]),
        health_status=str(row["health_status"] or "UNKNOWN"),
        health_message=str(row["health_message"] or ""),
        last_checked_at=row["last_checked_at"],
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


class PostgresStorageSourceRepository:
    """Storage-source owner backed by ``w4_storage_source``."""

    provider_name = PROVIDER_POSTGRESQL
    #: Declared capability gap: cross-domain deletion needs reference evidence.
    delete_supported = False

    def __init__(
        self,
        dsn: str,
        scope: str,
        *,
        admission: Mapping[str, Any] | None = None,
        admission_path: str | Path | None = None,
        reference_counter: Callable[[str], int] | None = None,
        allow_cross_domain_delete: bool = False,
    ) -> None:
        self._dsn = str(dsn)
        self.scope = str(scope)
        self._admission = dict(admission) if admission else None
        self._admission_path = Path(admission_path) if admission_path else None
        self.reference_counter = reference_counter or (lambda _source_id: 0)
        self.delete_supported = bool(allow_cross_domain_delete)
        self._ready = False

    def __repr__(self) -> str:  # never render the DSN
        return f"PostgresStorageSourceRepository(scope={self.scope!r})"

    # -- connection plumbing ----------------------------------------------
    def _connect(self):
        psycopg = _psycopg()
        from psycopg.rows import dict_row

        return psycopg.connect(self._dsn, row_factory=dict_row)

    @contextmanager
    def _read(self):
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                yield cursor
        finally:
            connection.close()

    @contextmanager
    def _write(self):
        # Re-validate the local admission right before opening the write
        # transaction, so a revoked or replaced admission stops an already-open
        # instance instead of leaving two possible owners.
        self._refresh_admission()
        self._require_admission()
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                yield cursor
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _refresh_admission(self) -> None:
        if self._admission_path is None:
            return
        from .storage.source_repository import load_storage_source_admission_record

        self._admission = load_storage_source_admission_record(self._admission_path)

    # -- admission / schema ------------------------------------------------
    def _require_admission(self) -> None:
        if not self._admission:
            raise StorageSourceAdmissionRequired(
                "STORAGE_SOURCE_POSTGRES_ADMISSION_REQUIRED",
                "PostgreSQL storage-source provider requires a cutover admission record",
                detail=f"scope={self.scope!r}",
            )
        if self._admission.get("revoked_at"):
            raise StorageSourceAdmissionRequired(
                "STORAGE_SOURCE_POSTGRES_ADMISSION_REVOKED",
                "the storage-source cutover admission was revoked",
                detail=f"revoked_at={self._admission.get('revoked_at')!r}",
            )
        if str(self._admission.get("scope") or "") != self.scope:
            raise StorageSourceAdmissionRequired(
                "STORAGE_SOURCE_POSTGRES_ADMISSION_SCOPE_MISMATCH",
                "admission record belongs to another storage-source scope",
                detail=(
                    f"record={self._admission.get('scope')!r} "
                    f"scope={self.scope!r}"
                ),
            )
        if str(self._admission.get("authoritative_provider") or "") != PROVIDER_POSTGRESQL:
            raise StorageSourceAdmissionRequired(
                "STORAGE_SOURCE_POSTGRES_ADMISSION_PROVIDER_MISMATCH",
                "admission record does not name PostgreSQL as the authority",
            )

    def ensure_ready(self) -> None:
        """Validate admission and schema once per instance; never create schema.

        The SQLite owner bootstraps its ``default_local`` row in the constructor so
        a fresh deployment always has a default storage source.  The provider
        keeps that product invariant with the same idempotent bootstrap; it never
        creates the *schema* (that is an explicit migration step).
        """
        if self._ready:
            return
        self._require_admission()
        with self._read() as cursor:
            try:
                require_current_schema(cursor.connection)
            except StorageSourceSchemaError as error:
                raise StorageSourceRepositoryError(
                    "STORAGE_SOURCE_POSTGRES_SCHEMA_NOT_CURRENT",
                    str(error),
                    detail=error.detail,
                ) from error
        self._bootstrap_default_source()
        self._ready = True

    def _bootstrap_default_source(self) -> None:
        """Idempotent default source, mirroring the SQLite constructor."""
        stamp = _now()
        with self._write() as cursor:
            cursor.execute(
                f"INSERT INTO {SCHEMA_NAME}.storage_source"
                "(scope,id,name,type,config,secret_ref,runtime_revision,enabled,"
                "is_default,created_at,updated_at) "
                "VALUES(%s,'default_local','平台本地存储','local','{}'::jsonb,'',1,"
                "TRUE,FALSE,%s,%s) ON CONFLICT (scope,id) DO NOTHING",
                (self.scope, stamp, stamp),
            )
            cursor.execute(
                f"UPDATE {SCHEMA_NAME}.storage_source SET is_default=TRUE "
                "WHERE scope=%s AND id='default_local' AND NOT EXISTS ("
                f"SELECT 1 FROM {SCHEMA_NAME}.storage_source "
                "WHERE scope=%s AND is_default)",
                (self.scope, self.scope),
            )

    def migration_status(self) -> dict[str, Any]:
        from .storage_source_postgres_schema import schema_status

        with self._read() as cursor:
            status = schema_status(cursor.connection)
            cursor.execute(
                "SELECT count(*) AS total FROM w4_storage_source.storage_source "
                "WHERE scope=%s",
                (self.scope,),
            )
            row = cursor.fetchone()
        return {
            "backend": PROVIDER_POSTGRESQL,
            "scope": self.scope,
            "source_count": int(row["total"]) if row else 0,
            "schema": status,
        }

    def capabilities(self) -> frozenset[str]:
        operations = {
            "list",
            "get",
            "default",
            "create",
            "update",
            "set_default",
            "record_health",
            "migration_status",
        }
        if self.delete_supported:
            operations.add("delete")
        return frozenset(operations)

    def unsupported_operations(self) -> tuple[str, ...]:
        return () if self.delete_supported else ("delete",)

    def journal_mode(self) -> str:
        return "postgresql"

    # -- reads -------------------------------------------------------------
    def list(self) -> list[StorageSource]:
        self.ensure_ready()
        with self._read() as cursor:
            cursor.execute(
                f"SELECT {self._COLUMNS} FROM {SCHEMA_NAME}.storage_source "
                "WHERE scope=%s ORDER BY is_default DESC, created_at, id",
                (self.scope,),
            )
            rows = cursor.fetchall()
        return [_from_row(row) for row in rows]

    def get(self, source_id: str) -> StorageSource | None:
        self.ensure_ready()
        with self._read() as cursor:
            cursor.execute(
                f"SELECT {self._COLUMNS} FROM {SCHEMA_NAME}.storage_source "
                "WHERE scope=%s AND id=%s",
                (self.scope, str(source_id)),
            )
            row = cursor.fetchone()
        return _from_row(row) if row else None

    def default(self) -> StorageSource:
        self.ensure_ready()
        with self._read() as cursor:
            cursor.execute(
                f"SELECT {self._COLUMNS} FROM {SCHEMA_NAME}.storage_source "
                "WHERE scope=%s AND is_default",
                (self.scope,),
            )
            row = cursor.fetchone()
        if not row:
            raise StorageSourceRepositoryError(
                "STORAGE_SOURCE_DEFAULT_MISSING",
                "storage source repository has no default source",
                detail=f"scope={self.scope!r}",
            )
        return _from_row(row)

    # -- writes ------------------------------------------------------------
    def create(self, value: Mapping[str, Any]) -> StorageSource:
        self.ensure_ready()
        source_id = str(value.get("id") or "").strip()
        name = str(value.get("name") or "").strip()
        if not _IDENTIFIER.fullmatch(source_id):
            raise ValueError("storage source id is invalid")
        if not name:
            raise ValueError("storage source name is required")
        source_type = StorageType.parse(value.get("type")).value
        config = _safe_config(
            value.get("config") if isinstance(value.get("config"), Mapping) else {}
        )
        stamp = _now()
        with self._write() as cursor:
            self._lock_scope(cursor)
            self._unique_guard(
                cursor,
                source_id,
                name,
                lambda: cursor.execute(
                    f"INSERT INTO {SCHEMA_NAME}.storage_source"
                    "(scope,id,name,type,config,secret_ref,runtime_revision,enabled,"
                    "is_default,created_at,updated_at) "
                    "VALUES(%s,%s,%s,%s,%s::jsonb,%s,1,%s,FALSE,%s,%s)",
                    (
                        self.scope,
                        source_id,
                        name,
                        source_type,
                        json.dumps(config, ensure_ascii=False, sort_keys=True),
                        str(value.get("secret_ref") or ""),
                        bool(value.get("enabled", True)),
                        stamp,
                        stamp,
                    ),
                ),
            )
        created = self.get(source_id)
        if created is None:  # pragma: no cover - write/read in the same authority
            raise StorageSourceRepositoryError(
                "STORAGE_SOURCE_CREATE_NOT_VISIBLE",
                "the created storage source is not visible",
                detail=f"id={source_id!r}",
            )
        return created

    def update(self, source_id: str, changes: Mapping[str, Any]) -> StorageSource:
        self.ensure_ready()
        allowed = {"name", "config", "secret_ref", "enabled"}
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError(
                "unsupported storage source fields: " + ", ".join(sorted(unknown))
            )
        with self._write() as cursor:
            self._lock_scope(cursor)
            # Read the current row inside the same transaction: the revision
            # bump must be computed from the state this UPDATE really replaces.
            cursor.execute(
                f"SELECT {self._COLUMNS} FROM {SCHEMA_NAME}.storage_source "
                "WHERE scope=%s AND id=%s",
                (self.scope, str(source_id)),
            )
            row = cursor.fetchone()
            if not row:
                raise KeyError(f"storage source does not exist: {source_id}")
            current = _from_row(row)
            if current.id == "default_local" and changes.get("enabled") is False:
                raise ValueError("default local storage cannot be disabled")
            name = str(changes.get("name", current.name)).strip()
            config = _safe_config(changes.get("config", current.config))
            secret_ref = str(changes.get("secret_ref", current.secret_ref) or "")
            enabled = bool(changes.get("enabled", current.enabled))
            # A->B->A must change the durable epoch even when the final config
            # bytes match the original; a rename alone keeps the epoch stable.
            bump = int(
                config != current.config
                or secret_ref != current.secret_ref
                or enabled != current.enabled
            )
            stamp = _now()
            self._unique_guard(
                cursor,
                source_id,
                name,
                lambda: cursor.execute(
                    f"UPDATE {SCHEMA_NAME}.storage_source SET "
                    "name=%s, config=%s::jsonb, secret_ref=%s, enabled=%s, "
                    "updated_at=%s, runtime_revision=runtime_revision+%s "
                    "WHERE scope=%s AND id=%s",
                    (
                        name,
                        json.dumps(config, ensure_ascii=False, sort_keys=True),
                        secret_ref,
                        enabled,
                        stamp,
                        bump,
                        self.scope,
                        str(source_id),
                    ),
                ),
            )
            cursor.execute(
                f"SELECT {self._COLUMNS} FROM {SCHEMA_NAME}.storage_source "
                "WHERE scope=%s AND id=%s",
                (self.scope, str(source_id)),
            )
            updated = cursor.fetchone()
        if not updated:
            raise KeyError(f"storage source does not exist: {source_id}")
        return _from_row(updated)

    def set_default(self, source_id: str) -> StorageSource:
        self.ensure_ready()
        with self._write() as cursor:
            self._lock_scope(cursor)
            cursor.execute(
                f"SELECT {self._COLUMNS} FROM {SCHEMA_NAME}.storage_source "
                "WHERE scope=%s AND id=%s",
                (self.scope, str(source_id)),
            )
            row = cursor.fetchone()
            if not row:
                raise KeyError(f"storage source does not exist: {source_id}")
            if not bool(row["enabled"]):
                raise ValueError("disabled storage source cannot be the default")
            stamp = _now()
            cursor.execute(
                f"UPDATE {SCHEMA_NAME}.storage_source SET is_default=FALSE "
                "WHERE scope=%s AND is_default",
                (self.scope,),
            )
            cursor.execute(
                f"UPDATE {SCHEMA_NAME}.storage_source "
                "SET is_default=TRUE, updated_at=%s WHERE scope=%s AND id=%s",
                (stamp, self.scope, str(source_id)),
            )
            cursor.execute(
                f"SELECT {self._COLUMNS} FROM {SCHEMA_NAME}.storage_source "
                "WHERE scope=%s AND id=%s",
                (self.scope, str(source_id)),
            )
            updated = cursor.fetchone()
        if not updated:
            raise KeyError(f"storage source does not exist: {source_id}")
        return _from_row(updated)

    def record_health(self, source_id: str, *, ok: bool, message: str) -> StorageSource:
        self.ensure_ready()
        checked = _now()
        safe_message = redact_storage_error(message)
        with self._write() as cursor:
            cursor.execute(
                f"UPDATE {SCHEMA_NAME}.storage_source SET "
                "health_status=%s, health_message=%s, last_checked_at=%s, updated_at=%s "
                "WHERE scope=%s AND id=%s",
                (
                    "AVAILABLE" if ok else "UNAVAILABLE",
                    safe_message,
                    checked,
                    checked,
                    self.scope,
                    str(source_id),
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"storage source does not exist: {source_id}")
            cursor.execute(
                f"SELECT {self._COLUMNS} FROM {SCHEMA_NAME}.storage_source "
                "WHERE scope=%s AND id=%s",
                (self.scope, str(source_id)),
            )
            row = cursor.fetchone()
        if not row:  # pragma: no cover - rowcount already proved existence
            raise KeyError(f"storage source does not exist: {source_id}")
        return _from_row(row)

    def delete(self, source_id: str) -> bool:
        """Cross-domain deletion stays blocked without admitted evidence."""
        if not self.delete_supported:
            raise StorageSourceOperationBlocked(
                "STORAGE_SOURCE_DELETE_REQUIRES_CROSS_DOMAIN_EVIDENCE",
                "storage source deletion needs material-reference evidence and the "
                "storage decommissioning proof, which this provider does not own",
                detail=(
                    "configuration reads/writes are served; deleting the row would "
                    "orphan objects referenced by other domains"
                ),
            )
        self.ensure_ready()
        with self._write() as cursor:
            self._lock_scope(cursor)
            cursor.execute(
                f"SELECT {self._COLUMNS} FROM {SCHEMA_NAME}.storage_source "
                "WHERE scope=%s AND id=%s",
                (self.scope, str(source_id)),
            )
            row = cursor.fetchone()
            if not row:
                return False
            current = _from_row(row)
            if current.id == "default_local":
                raise ValueError("default local storage cannot be deleted")
            references = int(self.reference_counter(str(source_id)))
            if references:
                raise ValueError(
                    f"storage source is referenced by {references} materials"
                )
            if current.is_default:
                raise ValueError("default storage source cannot be deleted")
            cursor.execute(
                f"DELETE FROM {SCHEMA_NAME}.storage_source WHERE scope=%s AND id=%s",
                (self.scope, str(source_id)),
            )
            return cursor.rowcount == 1

    # -- helpers -----------------------------------------------------------
    _COLUMNS = (
        "id,name,type,config,secret_ref,runtime_revision,enabled,is_default,"
        "health_status,health_message,last_checked_at,created_at,updated_at"
    )

    def _lock_scope(self, cursor) -> None:
        """Serialize lifecycle writes for one scope (create/update/default/delete).

        The unique indexes remain the final invariant; this lock only makes the
        read-then-write sequences (default switch, name uniqueness) deterministic
        instead of deadlocking on the partial default index.
        """
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))",
            (f"storage_source:{self.scope}",),
        )

    def _unique_guard(self, cursor, source_id: str, name: str, write: Callable[[], Any]) -> None:
        try:
            write()
        except Exception as error:  # translate the DB conflict into the owner's error
            if getattr(error, "sqlstate", "") == _UNIQUE_VIOLATION:
                raise StorageSourceConflictError(
                    f"storage source id or name already exists: {source_id}/{name}"
                ) from error
            raise
