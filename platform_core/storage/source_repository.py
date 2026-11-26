from __future__ import annotations

import json
import os
from functools import wraps
import re
import sqlite3
import threading
from contextlib import closing, contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from filelock import FileLock, Timeout as FileLockTimeout

from .errors import redact_storage_error
from .models import StorageType


_SCHEMA = """
CREATE TABLE IF NOT EXISTS storage_sources (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    type TEXT NOT NULL,
    config_json TEXT NOT NULL DEFAULT '{}',
    secret_ref TEXT NOT NULL DEFAULT '',
    runtime_revision INTEGER NOT NULL DEFAULT 1,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    is_default INTEGER NOT NULL DEFAULT 0 CHECK (is_default IN (0, 1)),
    health_status TEXT NOT NULL DEFAULT 'UNKNOWN',
    health_message TEXT NOT NULL DEFAULT '',
    last_checked_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_storage_sources_default
ON storage_sources(is_default) WHERE is_default = 1;
CREATE INDEX IF NOT EXISTS ix_storage_sources_type_enabled
ON storage_sources(type, enabled);
"""

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_SENSITIVE = re.compile(r"(?i)(secret|password|token|api[_-]?key|access[_-]?key)")
_INITIALIZATION_LOCKS: dict[str, threading.Lock] = {}
_INITIALIZATION_LOCKS_GUARD = threading.Lock()
_SOURCE_LIFECYCLE_LOCK = ".storage-source-lifecycle.lock"
_SOURCE_LIFECYCLE_LOCAL = threading.local()
#: One mutex shared by the cutover switch and every SQLite writer. A writer holds
#: it across *(authority check -> write)* and the switch holds it across
#: *(marker publication -> snapshot -> admission)*, so a writer that already
#: passed the check cannot slip a write past the switch boundary.
_SWITCH_LOCK_FILENAME = ".storage-source-switch.lock"
_SWITCH_LOCK_LOCAL = threading.local()

#: Storage-source provider boundary (U2).  The default provider is SQLite and
#: keeps the existing behaviour; PostgreSQL needs an explicit DSN plus a cutover
#: admission record and never falls back.  These names mirror the algorithm
#: domain so operators see one convention across migrated domains.
PROVIDER_SQLITE = "sqlite"
PROVIDER_POSTGRESQL = "postgresql"
SUPPORTED_PROVIDERS = (PROVIDER_SQLITE, PROVIDER_POSTGRESQL)
ENV_PROVIDER = "STORAGE_SOURCE_PROVIDER"
ENV_DSN = "STORAGE_SOURCE_POSTGRES_DSN"
ENV_ADMISSION = "STORAGE_SOURCE_ADMISSION_RECORD"
ENV_DELETE_ADMISSION = "STORAGE_SOURCE_DELETE_ADMISSION"
ADMISSION_DIRNAME = "storage_source_migration"
ADMISSION_FILENAME = "cutover_admission.json"
CONTRACT_VERSION = "storage-source-repository-v1"
#: The platform-wide scope of storage-source metadata (one PostgreSQL database may
#: host several deployments, so every row is scoped explicitly).
DEFAULT_SCOPE = "platform"


class StorageSourceRepositoryError(RuntimeError):
    """Provider-boundary failure with a stable machine-readable code."""

    def __init__(self, code: str, message: str, *, detail: str = ""):
        super().__init__(message)
        self.code = str(code)
        self.detail = str(detail or "")


class StorageSourceProviderConfigError(StorageSourceRepositoryError):
    """Provider selection or DSN configuration is missing/invalid."""


class StorageSourceAdmissionRequired(StorageSourceRepositoryError):
    """A cutover admission record is required but missing/invalid/stale."""


class StorageSourceConflictError(ValueError):
    """A write conflicts with an existing source (duplicate id or name)."""


class StorageSourceOperationBlocked(StorageSourceRepositoryError):
    """A cross-domain operation is withheld until its evidence is admitted."""


def scope_for_path(path: str | Path, *, default: str = DEFAULT_SCOPE) -> str:
    """The business scope of one storage-source database path."""
    Path(path)
    return str(default)


def admission_record_path(path: str | Path) -> Path:
    return Path(path).parent / ADMISSION_DIRNAME / ADMISSION_FILENAME


def admission_transition_path(record_path: str | Path) -> Path:
    """Marker published before a cutover changes the authoritative writer."""
    target = Path(record_path)
    return target.with_name(target.name + ".transition")


def load_storage_source_admission_record(path: str | Path) -> dict[str, Any] | None:
    """Read the local admission record; a malformed record is refused."""
    target = Path(path)
    if not target.is_file():
        return None
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise StorageSourceAdmissionRequired(
            "STORAGE_SOURCE_ADMISSION_RECORD_INVALID",
            "cutover admission record cannot be read",
            detail=str(error),
        ) from error
    if not isinstance(value, dict):
        raise StorageSourceAdmissionRequired(
            "STORAGE_SOURCE_ADMISSION_RECORD_INVALID",
            "cutover admission record is not an object",
        )
    if str(value.get("contract_version") or "") != CONTRACT_VERSION:
        raise StorageSourceAdmissionRequired(
            "STORAGE_SOURCE_ADMISSION_RECORD_INVALID",
            "cutover admission record contract does not match",
            detail=f"contract={value.get('contract_version')!r}",
        )
    return value


def resolve_provider(
    provider: str | None = None, *, environ: Mapping[str, str] | None = None
) -> str:
    environment = os.environ if environ is None else environ
    selected = str(
        provider or environment.get(ENV_PROVIDER) or PROVIDER_SQLITE
    ).strip().lower()
    if selected not in SUPPORTED_PROVIDERS:
        raise StorageSourceProviderConfigError(
            "STORAGE_SOURCE_PROVIDER_UNKNOWN",
            "unknown storage-source provider",
            detail=f"provider={selected!r} supported={list(SUPPORTED_PROVIDERS)}",
        )
    return selected


def _refuse_stale_sqlite(
    path: str | Path, record_path: str | Path | None = None
) -> None:
    """Refuse a SQLite write/read when PostgreSQL owns this source metadata.

    Every SQLite write path calls this under the same lifecycle fence it already
    uses, so a cutover cannot leave two admitted writers; a transition marker
    blocks both sides until the cutover is finished or rolled back.
    """
    target = Path(path)
    record = Path(record_path) if record_path else admission_record_path(target)
    if admission_transition_path(record).exists():
        raise StorageSourceAdmissionRequired(
            "STORAGE_SOURCE_CUTOVER_IN_PROGRESS",
            "a storage-source cutover is unresolved; neither provider may write",
            detail=(
                "a transition marker is present next to the admission record; "
                "inspect it and finish or roll back the cutover before writing"
            ),
        )
    value = load_storage_source_admission_record(record)
    if value is None:
        return
    if value.get("revoked_at"):
        return
    if str(value.get("authoritative_provider") or "") != PROVIDER_POSTGRESQL:
        return
    raise StorageSourceAdmissionRequired(
        "STORAGE_SOURCE_SQLITE_STALE_AFTER_CUTOVER",
        "SQLite is no longer the authoritative storage-source writer",
        detail=(
            f"PostgreSQL admission {value.get('admission_id')} is active; run the "
            "rollback assessment before serving SQLite again"
        ),
    )


def open_storage_source_repository(
    path: str | Path,
    *,
    provider: str | None = None,
    dsn: str | None = None,
    reference_counter: Callable[[str], int] | None = None,
    environ: Mapping[str, str] | None = None,
    admission_path: str | Path | None = None,
    allow_stale_sqlite: bool = False,
    allow_cross_domain_delete: bool | None = None,
    scope: str | None = None,
):
    """Open the storage-source owner for one deployment.

    Default: SQLite with the existing behaviour.  PostgreSQL requires a DSN and a
    cutover admission record; selecting it never falls back to SQLite.  Selecting
    SQLite while a PostgreSQL admission is active is refused unless a migration
    tool passes ``allow_stale_sqlite``.
    """
    environment = os.environ if environ is None else environ
    selected = resolve_provider(provider, environ=environment)
    target = Path(path)
    record_path = Path(admission_path) if admission_path else admission_record_path(target)

    if selected == PROVIDER_SQLITE:
        if not allow_stale_sqlite:
            _refuse_stale_sqlite(target, record_path)
        return StorageSourceRepository(target, reference_counter=reference_counter)

    resolved_dsn = str(dsn or environment.get(ENV_DSN) or "").strip()
    if not resolved_dsn:
        raise StorageSourceProviderConfigError(
            "STORAGE_SOURCE_POSTGRES_DSN_MISSING",
            "PostgreSQL provider requires a DSN",
            detail=f"pass dsn= or set {ENV_DSN}",
        )
    record = load_storage_source_admission_record(record_path)
    if record is None:
        raise StorageSourceAdmissionRequired(
            "STORAGE_SOURCE_POSTGRES_ADMISSION_REQUIRED",
            "PostgreSQL provider requires a cutover admission record",
            detail=f"expected {record_path}",
        )
    resolved_scope = str(scope or record.get("scope") or scope_for_path(target))
    if allow_cross_domain_delete is None:
        allow_cross_domain_delete = (
            str(environment.get(ENV_DELETE_ADMISSION) or "").strip() == "1"
        )
    from ..storage_source_postgres_store import PostgresStorageSourceRepository

    return PostgresStorageSourceRepository(
        resolved_dsn,
        resolved_scope,
        admission=record,
        admission_path=record_path,
        reference_counter=reference_counter,
        allow_cross_domain_delete=bool(allow_cross_domain_delete),
    )


@contextmanager
def storage_source_lifecycle_fence(
    repository_path: str | Path, *, timeout: float = 60,
):
    """Serialize short source-config commits with durable task admission.

    The fence owns no business state.  Network/storage I/O must stay outside;
    callers use it only for a final source-generation check plus Task/Source
    repository commits.
    """
    database_path = Path(repository_path).resolve()
    lock_path = str(database_path.parent / _SOURCE_LIFECYCLE_LOCK)
    held = getattr(_SOURCE_LIFECYCLE_LOCAL, "held", None)
    if held is None:
        held = {}
        _SOURCE_LIFECYCLE_LOCAL.held = held
    depth = held.get(lock_path)
    if depth is not None:
        held[lock_path] = depth + 1
        try:
            yield
        finally:
            held[lock_path] -= 1
        return
    with FileLock(lock_path, timeout=timeout):
        held[lock_path] = 1
        try:
            yield
        finally:
            held.pop(lock_path, None)


@contextmanager
def storage_source_switch_lock(
    path: str | Path, *, timeout: float = 5.0,
):
    """The writer/switch mutex described by the cutover protocol.

    Re-entrant inside one thread (a writer may trigger another writer, e.g. the
    constructor bootstrap followed by a create).  A writer that cannot enter
    within ``timeout`` fails closed with ``STORAGE_SOURCE_CUTOVER_IN_PROGRESS``
    instead of writing while a switch is deciding authority.
    """
    lock_path = str(Path(path).resolve().parent / _SWITCH_LOCK_FILENAME)
    held = getattr(_SWITCH_LOCK_LOCAL, "held", None)
    if held is None:
        held = {}
        _SWITCH_LOCK_LOCAL.held = held
    depth = held.get(lock_path)
    if depth is not None:
        held[lock_path] = depth + 1
        try:
            yield
        finally:
            held[lock_path] -= 1
        return
    Path(lock_path).parent.mkdir(parents=True, exist_ok=True)
    try:
        with FileLock(lock_path, timeout=timeout, thread_local=False):
            held[lock_path] = 1
            try:
                yield
            finally:
                held.pop(lock_path, None)
    except FileLockTimeout as error:
        raise StorageSourceAdmissionRequired(
            "STORAGE_SOURCE_CUTOVER_IN_PROGRESS",
            "a storage-source cutover is in progress",
            detail="the storage-source switch lock is held by another writer",
        ) from error


def _initialization_lock(path: Path) -> threading.Lock:
    key = str(path.resolve())
    with _INITIALIZATION_LOCKS_GUARD:
        return _INITIALIZATION_LOCKS.setdefault(key, threading.Lock())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_config(config: Mapping[str, Any] | None) -> dict[str, Any]:
    value = dict(config or {})
    pending: list[tuple[str, Any]] = list(value.items())
    while pending:
        key, item = pending.pop()
        if _SENSITIVE.search(str(key)):
            raise ValueError(f"sensitive storage config key is not allowed: {key}")
        if isinstance(item, Mapping):
            pending.extend((str(child_key), child) for child_key, child in item.items())
    json.dumps(value, ensure_ascii=False)
    return value


@dataclass(frozen=True)
class StorageSource:
    id: str
    name: str
    type: str
    config: dict[str, Any]
    secret_ref: str = ""
    enabled: bool = True
    is_default: bool = False
    health_status: str = "UNKNOWN"
    health_message: str = ""
    last_checked_at: str | None = None
    created_at: str = ""
    updated_at: str = ""
    runtime_revision: int = 1

    def to_public_dict(
        self, *, secret_configured: bool = False, secret_masked: str = ""
    ) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "config": dict(self.config),
            "secret_ref": self.secret_ref,
            "secret_configured": bool(secret_configured),
            "secret_masked": str(secret_masked),
            "enabled": self.enabled,
            "is_default": self.is_default,
            "health_status": self.health_status,
            "health_message": self.health_message,
            "last_checked_at": self.last_checked_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def _from_row(row: sqlite3.Row) -> StorageSource:
    return StorageSource(
        id=str(row["id"]),
        name=str(row["name"]),
        type=str(row["type"]),
        config=dict(json.loads(row["config_json"] or "{}")),
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


def _controlled_source_write(function):
    @wraps(function)
    def fenced(self, *args, **kwargs):
        # Two locks, always in this order (lifecycle -> switch):
        #  * the switch mutex makes *(authority check -> write)* atomic against a
        #    cutover that publishes the transition marker and the admission;
        #  * the lifecycle fence keeps the existing material-commit serialization
        #    the controlled local GC mode requires.
        path = getattr(self, "path", None)
        if path is None and args:
            path = Path(args[0])
        if path is None:
            return function(self, *args, **kwargs)
        path = Path(path)
        controlled = os.environ.get("MC_CONTROLLED_LOCAL_MATERIAL_GC") == "1"

        def write() -> Any:
            with storage_source_switch_lock(path):
                _refuse_stale_sqlite(path)
                return function(self, *args, **kwargs)

        if not controlled:
            return write()
        path.parent.mkdir(parents=True, exist_ok=True)
        from ..material_repository import _LIFECYCLE_LOCAL
        # Existing flows can hold project->source while compatibility holds
        # source->project. Never wait on the reverse edge in controlled mode.
        timeout = 0 if getattr(_LIFECYCLE_LOCAL, "held", {}) else 60
        with storage_source_lifecycle_fence(path, timeout=timeout):
            return write()
    return fenced


class StorageSourceRepository:
    @classmethod
    def open_readonly(cls, path: str | Path):
        """No source defaults, schema upgrade, lifecycle write lock or mkdir."""
        owner = cls.__new__(cls)
        owner.path = Path(path)
        owner._read_only = True
        owner.reference_counter = lambda _source_id: 0
        with closing(owner._connect()) as database:
            database.execute("SELECT id,runtime_revision FROM storage_sources LIMIT 0")
        return owner

    @_controlled_source_write
    def __init__(
        self,
        path: str | Path,
        *,
        reference_counter: Callable[[str], int] | None = None,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.reference_counter = reference_counter or (lambda _source_id: 0)
        # The storage page can load source and artifact configuration in
        # parallel. Serialize only first/schema initialization for this exact
        # database path so concurrent constructors cannot race the WAL switch.
        with _initialization_lock(self.path):
            with closing(self._connect()) as database:
                database.executescript(_SCHEMA)
                # Upgrade existing Storage Source owner in place. SQLite's
                # RESERVED write lock serializes schema admission across Web
                # workers, without introducing another revision table.
                database.execute("BEGIN IMMEDIATE")
                try:
                    columns = {
                        str(column["name"])
                        for column in database.execute("PRAGMA table_info(storage_sources)").fetchall()
                    }
                    if "runtime_revision" not in columns:
                        database.execute(
                            "ALTER TABLE storage_sources "
                            "ADD COLUMN runtime_revision INTEGER NOT NULL DEFAULT 1"
                        )
                    stamp = _now()
                    database.execute(
                        """
                        INSERT OR IGNORE INTO storage_sources
                        (id, name, type, config_json, enabled, is_default, created_at, updated_at)
                        VALUES ('default_local', '平台本地存储', 'local', '{}', 1, 1, ?, ?)
                        """,
                        (stamp, stamp),
                    )
                    database.execute("COMMIT")
                except Exception:
                    database.execute("ROLLBACK")
                    raise

    def _connect(self) -> sqlite3.Connection:
        if getattr(self, "_read_only", False):
            database = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5, isolation_level=None)
            database.row_factory = sqlite3.Row
            return database
        database = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        database.row_factory = sqlite3.Row
        # Configure lock waiting before any pragma that may need a schema/write
        # lock. Re-applying journal_mode=WAL on every short-lived repository
        # connection can itself contend with concurrent requests.
        database.execute("PRAGMA busy_timeout=5000")
        current_mode = str(database.execute("PRAGMA journal_mode").fetchone()[0]).lower()
        if current_mode != "wal":
            database.execute("PRAGMA journal_mode=WAL")
        database.execute("PRAGMA foreign_keys=ON")
        return database

    def journal_mode(self) -> str:
        with closing(self._connect()) as database:
            return str(database.execute("PRAGMA journal_mode").fetchone()[0]).lower()

    def list(self) -> list[StorageSource]:
        with closing(self._connect()) as database:
            rows = database.execute(
                "SELECT * FROM storage_sources ORDER BY is_default DESC, created_at, id"
            ).fetchall()
        return [_from_row(row) for row in rows]

    def get(self, source_id: str) -> StorageSource | None:
        with closing(self._connect()) as database:
            row = database.execute(
                "SELECT * FROM storage_sources WHERE id = ?", (str(source_id),)
            ).fetchone()
        return _from_row(row) if row else None

    def default(self) -> StorageSource:
        with closing(self._connect()) as database:
            row = database.execute(
                "SELECT * FROM storage_sources WHERE is_default = 1"
            ).fetchone()
        if not row:
            raise RuntimeError("storage source repository has no default source")
        return _from_row(row)

    @_controlled_source_write
    def create(self, value: Mapping[str, Any]) -> StorageSource:
        source_id = str(value.get("id") or "").strip()
        name = str(value.get("name") or "").strip()
        if not _IDENTIFIER.fullmatch(source_id):
            raise ValueError("storage source id is invalid")
        if not name:
            raise ValueError("storage source name is required")
        source_type = StorageType.parse(value.get("type")).value
        config = _safe_config(value.get("config") if isinstance(value.get("config"), Mapping) else {})
        stamp = _now()
        with closing(self._connect()) as database:
            database.execute("BEGIN IMMEDIATE")
            try:
                database.execute(
                    """
                    INSERT INTO storage_sources
                    (id, name, type, config_json, secret_ref, enabled, is_default, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)
                    """,
                    (
                        source_id,
                        name,
                        source_type,
                        json.dumps(config, ensure_ascii=False, sort_keys=True),
                        str(value.get("secret_ref") or ""),
                        int(bool(value.get("enabled", True))),
                        stamp,
                        stamp,
                    ),
                )
                database.execute("COMMIT")
            except Exception:
                database.execute("ROLLBACK")
                raise
        return self.get(source_id)  # type: ignore[return-value]

    @_controlled_source_write
    def update(self, source_id: str, changes: Mapping[str, Any]) -> StorageSource:
        current = self.get(source_id)
        if current is None:
            raise KeyError(f"storage source does not exist: {source_id}")
        if current.id == "default_local" and changes.get("enabled") is False:
            raise ValueError("default local storage cannot be disabled")
        allowed = {"name", "config", "secret_ref", "enabled"}
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError("unsupported storage source fields: " + ", ".join(sorted(unknown)))
        updated = replace(
            current,
            name=str(changes.get("name", current.name)).strip(),
            config=_safe_config(changes.get("config", current.config)),
            secret_ref=str(changes.get("secret_ref", current.secret_ref) or ""),
            enabled=bool(changes.get("enabled", current.enabled)),
            updated_at=_now(),
        )
        # A->B->A must change the durable epoch even if the final config
        # bytes match the original. Renaming alone leaves this epoch stable.
        bump_runtime_revision = int(
            updated.config != current.config
            or updated.secret_ref != current.secret_ref
            or updated.enabled != current.enabled
        )
        with closing(self._connect()) as database:
            database.execute(
                """
                UPDATE storage_sources
                SET name = ?, config_json = ?, secret_ref = ?, enabled = ?,
                    updated_at = ?, runtime_revision = runtime_revision + ?
                WHERE id = ?
                """,
                (
                    updated.name,
                    json.dumps(updated.config, ensure_ascii=False, sort_keys=True),
                    updated.secret_ref,
                    int(updated.enabled),
                    updated.updated_at,
                    bump_runtime_revision,
                    updated.id,
                ),
            )
        return self.get(source_id)  # type: ignore[return-value]

    @_controlled_source_write
    def set_default(self, source_id: str) -> StorageSource:
        source = self.get(source_id)
        if source is None:
            raise KeyError(f"storage source does not exist: {source_id}")
        if not source.enabled:
            raise ValueError("disabled storage source cannot be the default")
        with closing(self._connect()) as database:
            database.execute("BEGIN IMMEDIATE")
            try:
                database.execute("UPDATE storage_sources SET is_default = 0 WHERE is_default = 1")
                database.execute(
                    "UPDATE storage_sources SET is_default = 1, updated_at = ? WHERE id = ?",
                    (_now(), source_id),
                )
                database.execute("COMMIT")
            except Exception:
                database.execute("ROLLBACK")
                raise
        return self.get(source_id)  # type: ignore[return-value]

    def record_health(self, source_id: str, *, ok: bool, message: str) -> StorageSource:
        with storage_source_switch_lock(self.path):
            _refuse_stale_sqlite(self.path)
            return self._record_health(source_id, ok=ok, message=message)

    def _record_health(self, source_id: str, *, ok: bool, message: str) -> StorageSource:
        checked = _now()
        safe_message = redact_storage_error(message)
        with closing(self._connect()) as database:
            cursor = database.execute(
                """
                UPDATE storage_sources
                SET health_status = ?, health_message = ?, last_checked_at = ?, updated_at = ?
                WHERE id = ?
                """,
                ("AVAILABLE" if ok else "UNAVAILABLE", safe_message, checked, checked, source_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"storage source does not exist: {source_id}")
        return self.get(source_id)  # type: ignore[return-value]

    @_controlled_source_write
    def delete(self, source_id: str) -> bool:
        if str(source_id) == "default_local":
            raise ValueError("default local storage cannot be deleted")
        source = self.get(source_id)
        if source is None:
            return False
        references = int(self.reference_counter(str(source_id)))
        if references:
            raise ValueError(f"storage source is referenced by {references} materials")
        if source.is_default:
            raise ValueError("default storage source cannot be deleted")
        with closing(self._connect()) as database:
            cursor = database.execute(
                "DELETE FROM storage_sources WHERE id = ?", (str(source_id),)
            )
        return cursor.rowcount == 1

