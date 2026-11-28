"""Algorithm-domain repository port (T8.1).

Business callers depend on this port, never on a SQL dialect.  The default
provider is SQLite and delegates to the existing :class:`AlgorithmSqlStore`
without changing its behaviour.  PostgreSQL is a separate provider that can
only be opened with an explicit cutover admission record, so a stale SQLite
dataset is never served silently after a cutover and PostgreSQL never falls
back to SQLite on error.

Dialect boundary: SQL lives only in ``algorithm_sql_store`` (SQLite) and
``algorithm_postgres_store`` (PostgreSQL).  This module contains no SQL.
"""
from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from .algorithm_sql_store import AlgorithmSqlStore

CONTRACT_VERSION = "algorithm-repository-v1"

#: Operations every provider must implement for a cutover to be admissible.
CORE_OPERATIONS = (
    "ensure_ready",
    "revision",
    "migration_status",
    "read_all",
    "read_one",
    "exists",
    "training_version_refs",
    "replace_all",
    "create_algorithm",
    "patch_algorithm",
    "delete_algorithm",
    "attach_version",
    "attach_version_if_current",
    "patch_version",
    "rollback_version",
    "delete_version_with_operation",
    "update_version_operation",
    "sync_external_algorithms",
)

#: Read-only UI projections that are not part of the cutover contract yet.
PRESENTATION_OPERATIONS = (
    "library_algorithms",
    "asset_algorithms",
    "asset_algorithm_basic",
    "asset_versions",
    "asset_version",
    "bootstrap_summary",
    "training_display_refs",
)

#: Read-only history-reference evidence. Material impact previews, training
#: history freshness and conversion-catalog reference protection all need the
#: authoritative algorithm revision, a bounded version-existence probe and
#: bounded payload pages. These are part of the domain contract: a provider that
#: cannot serve them must refuse the read instead of letting a caller read a
#: stale SQLite catalog directly (which is what the old ATTACH projections did).
HISTORY_EVIDENCE_OPERATIONS = (
    "provider_name",
    "history_revision",
    "history_has_versions",
    "history_algorithm_payloads",
    "history_version_payloads",
)

#: External-algorithm cleanup receipts. The ledger row and the algorithm
#: retirement flags change in one transaction, so this is a real part of the
#: domain contract: the default SQLite provider serves it, and a provider that
#: does not must declare the gap instead of reaching into SQLite behind the
#: caller's back.
CLEANUP_OPERATIONS = (
    "cleanup_ensure_schema",
    "cleanup_get",
    "cleanup_list",
    "cleanup_summary",
    "cleanup_public_operations",
    "cleanup_public_operation",
    "cleanup_confirm_deleted",
    "cleanup_update",
)

PROVIDER_SQLITE = "sqlite"
PROVIDER_POSTGRESQL = "postgresql"
SUPPORTED_PROVIDERS = (PROVIDER_SQLITE, PROVIDER_POSTGRESQL)

ENV_PROVIDER = "ALGORITHM_STORE_PROVIDER"
ENV_DSN = "ALGORITHM_STORE_POSTGRES_DSN"
ENV_ADMISSION = "ALGORITHM_STORE_ADMISSION_RECORD"
ADMISSION_DIRNAME = "algorithm_migration"
ADMISSION_FILENAME = "cutover_admission.json"


class AlgorithmRepositoryError(RuntimeError):
    """Provider-boundary failure with a stable machine-readable code."""

    def __init__(self, code: str, message: str, *, detail: str = ""):
        super().__init__(message)
        self.code = str(code)
        self.detail = str(detail or "")


class AlgorithmProviderConfigError(AlgorithmRepositoryError):
    """Provider selection or DSN configuration is missing/invalid."""


class AlgorithmProviderUnsupported(AlgorithmRepositoryError):
    """The selected provider does not implement this operation (fail closed)."""


class AlgorithmAdmissionRequired(AlgorithmRepositoryError):
    """A cutover admission record is required but missing or stale."""


class AlgorithmSqliteAttachRefused(AlgorithmAdmissionRequired):
    """A SQLite-attach read path cannot serve a project owned by another provider."""


def require_authoritative_sqlite(json_path: str | Path) -> None:
    """Refuse a direct SQLite attachment when another provider is authoritative.

    Several read projections still open the project's SQLite catalog with SQL
    ATTACH, which PostgreSQL cannot serve. Reusing the provider-boundary checks
    here means those readers fail closed after a cutover instead of silently
    returning stale rows.
    """
    path = Path(json_path)
    try:
        _refuse_stale_sqlite(path, admission_record_path(path))
    except AlgorithmAdmissionRequired as error:
        raise AlgorithmSqliteAttachRefused(error.code, str(error), detail=error.detail) from error

class AlgorithmRepository(Protocol):
    """Minimal single-domain contract shared by every provider."""

    project_id: str
    provider_name: str

    def capabilities(self) -> frozenset[str]: ...

    def unsupported_operations(self) -> tuple[str, ...]: ...

    def ensure_ready(self) -> None: ...

    def revision(self) -> int: ...

    def migration_status(self) -> dict[str, Any]: ...

    def read_all(self, *, summary_only: bool = False) -> list[dict]: ...

    def read_one(self, algorithm_id: str) -> dict | None: ...

    def exists(self, algorithm_id: str) -> bool: ...

    def training_version_refs(self, task_id: str) -> list[tuple[str, str]]: ...

    #: Provider identity used in derived-read signatures ("sqlite"/"postgresql").
    @property
    def provider_name(self) -> str: ...

    def history_revision(self) -> str | None:
        """Authoritative algorithm revision, or ``None`` when not yet initialized."""
        ...

    def history_has_versions(self) -> bool | None:
        """Bounded existence probe; ``None`` means "cannot prove this store is empty"."""
        ...

    def history_algorithm_payloads(
        self, *, after: str | None = None, limit: int = 200
    ) -> list[tuple[str, dict]]:
        """One bounded, deterministic page of algorithm payloads (keyset by id)."""
        ...

    def history_version_payloads(
        self, *, after: str | None = None, limit: int = 200
    ) -> list[tuple[str, dict]]:
        """One bounded, deterministic page of version payloads (keyset by id)."""
        ...

    def replace_all(self, algorithms: Sequence[Mapping[str, Any]]) -> None: ...

    def create_algorithm(self, item: Mapping[str, Any]) -> dict: ...

    def patch_algorithm(
        self, algorithm_id: str, patch: Mapping[str, Any], *, replace_analyses: bool = False
    ) -> dict: ...

    def delete_algorithm(self, algorithm_id: str) -> None: ...

    def attach_version(self, algorithm_id: str, version: Mapping[str, Any]) -> dict: ...

    def attach_version_if_current(
        self,
        algorithm_id: str,
        version: Mapping[str, Any],
        *,
        expected_current_version_id: str | None,
    ) -> dict: ...

    def patch_version(
        self, algorithm_id: str, version_id: str, patch: Mapping[str, Any], *, now: str
    ) -> dict: ...

    def rollback_version(
        self,
        algorithm_id: str,
        target_version_id: str,
        *,
        expected_current_version_id: str,
        operation: Mapping[str, Any],
        now: str,
        delete_current_version: bool,
    ) -> dict | None: ...

    def delete_version_with_operation(
        self,
        algorithm_id: str,
        version_id: str,
        *,
        expected_current_version_id: str | None,
        operation: Mapping[str, Any],
        now: str,
    ) -> dict: ...

    def update_version_operation(
        self, algorithm_id: str, operation_id: str, patch: Mapping[str, Any]
    ) -> None: ...

    def sync_external_algorithms(
        self, incoming: Mapping[str, Mapping[str, Any]], *, provider: str, synced_at: str
    ) -> dict[str, int]: ...

    # -- external algorithm cleanup ---------------------------------------
    def cleanup_ensure_schema(self) -> None: ...

    def cleanup_get(self, operation_id: str) -> dict | None: ...

    def cleanup_list(self) -> list[dict]: ...

    def cleanup_summary(self, *, project_id: str, suspected_state: str) -> dict[str, int]: ...

    def cleanup_public_operations(
        self, *, project_id: str, suspected_state: str, limit: int, offset: int
    ) -> list[dict]: ...

    def cleanup_public_operation(
        self, *, project_id: str, operation_id: str, suspected_state: str
    ) -> dict | None: ...

    def cleanup_confirm_deleted(self, **fields: Any) -> dict[str, Any]: ...

    def cleanup_update(self, **fields: Any) -> dict[str, Any]: ...


#: Store method names that mutate algorithm state. Anything reached through the
#: pass-through adapter with one of these prefixes is treated as a write and must
#: pass the authority guard, so an undeclared helper cannot silently bypass it.
#: The explicit mutating contract of the algorithm repository. Write authority
#: is decided by membership here, never by guessing from a method name.
WRITE_OPERATIONS = frozenset({
    "replace_all",
    "create_algorithm",
    "patch_algorithm",
    "delete_algorithm",
    "attach_version",
    "attach_version_if_current",
    "patch_version",
    "rollback_version",
    "delete_version_with_operation",
    "update_version_operation",
    "sync_external_algorithms",
    "cleanup_ensure_schema",
    "cleanup_confirm_deleted",
    "cleanup_update",
})

#: Operations a pass-through adapter may serve without a write check. Anything
#: outside this set is treated as a write (fail closed), so an undeclared helper
#: cannot bypass the authority guard.
_KNOWN_READ_OPERATIONS = (
    frozenset(CORE_OPERATIONS)
    | frozenset(PRESENTATION_OPERATIONS)
    | frozenset(HISTORY_EVIDENCE_OPERATIONS)
    | frozenset(CLEANUP_OPERATIONS)
    | frozenset()
)


def is_write_operation(name: str) -> bool:
    """Explicit write-authority contract (never inferred from the method name).

    Anything outside the known read set is treated as a write, so an undeclared
    helper cannot reach storage without passing the authority guard.
    """
    return name in WRITE_OPERATIONS or name not in _KNOWN_READ_OPERATIONS


class _GuardedStore:
    """Pass-through store wrapper that gates mutating calls on write authority."""

    def __init__(self, store: Any, guard: Any) -> None:
        object.__setattr__(self, "_wrapped_store", store)
        object.__setattr__(self, "_wrapped_guard", guard)

    def __getattr__(self, name: str) -> Any:
        store = object.__getattribute__(self, "_wrapped_store")
        if name == "ensure_ready":
            # Initialization is *not* forwarded back to the repository (that
            # cycle made every call recurse). It goes straight to the store,
            # whose persistent path already runs inside the write owner that the
            # repository installed as ``initialization_guard``.
            return store.ensure_ready
        attribute = getattr(store, name)
        if name.startswith("_"):
            return attribute
        if callable(attribute) and is_write_operation(name):
            guard = object.__getattribute__(self, "_wrapped_guard")

            def guarded(*args: Any, **kwargs: Any) -> Any:
                with guard():
                    return attribute(*args, **kwargs)
            return guarded
        return attribute

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(object.__getattribute__(self, "_wrapped_store"), name, value)


class SqliteAlgorithmRepository:
    """Default provider: the existing SQLite store, delegated unchanged."""

    provider_name = PROVIDER_SQLITE
    #: The cleanup ledger lives in this store's schema, so this provider serves
    #: the whole cleanup domain (PostgreSQL declares it unsupported instead).
    cleanup_supported = True

    def __init__(
        self,
        json_path: str | Path,
        *,
        admission_path: str | Path | None = None,
    ):
        path = Path(json_path)
        # The guard needs the paths first: the store is handed
        # ``self._initialization_guard`` at construction time, so persistent
        # initialization always runs as the admitted writer.
        self.json_path = path
        self.record_path = (
            Path(admission_path) if admission_path else admission_record_path(path)
        )
        store = AlgorithmSqlStore(
            path, initialization_guard=self._initialization_guard
        )
        self.project_id = store.project_id
        self.db_path = store.db_path
        self._store = store
        # Re-entrancy bookkeeping for this project's write authority. A write
        # can legitimately call another write on the same connection path (a
        # store call that must first initialise the catalog, for instance);
        # taking the same cross-process file lock twice on Windows self-deadlocks,
        # so the thread that already owns the guard keeps it.
        self._guard_state = threading.local()
        # Every mutating store call is routed through the authority guard *and*
        # the shared switch lock, so the check and the write cannot be separated
        # by a cutover that lands in between.
        self.store = _GuardedStore(store, self._write_guard)

    @contextmanager
    def _write_guard(self):
        """Hold the switch mutex across (authority check -> store write)."""
        depth = int(getattr(self._guard_state, "depth", 0) or 0)
        if depth:
            self._guard_state.depth = depth + 1
            try:
                yield
            finally:
                self._guard_state.depth -= 1
            return
        with admission_switch_lock(self.record_path):
            _refuse_stale_sqlite(Path(self.json_path), self.record_path)
            self._guard_state.depth = 1
            try:
                yield
            finally:
                self._guard_state.depth = 0

    @contextmanager
    def _initialization_guard(self):
        """Write owner around the store's persistent initialization boundary."""
        with self._write_guard():
            yield

    def ensure_ready(self) -> None:
        """Create/migrate the catalog under the write owner; validate otherwise.

        The store performs a short read-only readiness probe. Only a store that
        cannot prove readiness (missing database, non-WAL journal, incomplete
        schema/history import) enters the persistent initialization body, which
        runs inside ``_initialization_guard`` - i.e. under the same switch mutex
        and stale-writer refusal as any other algorithm write. A steady-state
        catalog therefore costs one probe and takes no exclusive lock.
        """
        self._store.ensure_ready()

    def is_initialized(self) -> bool:
        """True when this project's algorithm catalog is already serviceable.

        Provider-neutral replacement for the SQLite-only ``db_path.is_file()``
        probe: file existence alone proves nothing (an empty or half-migrated
        database exists too), so readiness is decided by the same short probe
        the store uses before it refuses the persistent initialization path.
        """
        return self._store._ready_without_init_lock()

    def _guard_write(self) -> None:
        """Compatibility helper: check authority under the switch mutex."""
        with self._write_guard():
            pass

    # -- provider metadata -------------------------------------------------
    def capabilities(self) -> frozenset[str]:
        return frozenset(
            CORE_OPERATIONS
            + PRESENTATION_OPERATIONS
            + HISTORY_EVIDENCE_OPERATIONS
            + CLEANUP_OPERATIONS
        )

    def unsupported_operations(self) -> tuple[str, ...]:
        return ()

    def __getattr__(self, name: str) -> Any:
        # Presentation projections and any future store helper keep their exact
        # existing behaviour; the adapter is a pass-through, not a rewrite.
        if name.startswith("_"):
            raise AttributeError(name)
        attribute = getattr(self.store, name)
        if callable(attribute) and is_write_operation(name):
            def guarded(*args: Any, **kwargs: Any) -> Any:
                self._guard_write()
                return attribute(*args, **kwargs)
            return guarded
        return attribute

    # -- contract ----------------------------------------------------------
    def revision(self) -> int:
        return self.store.revision()

    def migration_status(self) -> dict[str, Any]:
        return self.store.migration_status()

    def read_all(self, *, summary_only: bool = False) -> list[dict]:
        return self.store.read_all(summary_only=summary_only)

    def read_one(self, algorithm_id: str) -> dict | None:
        return self.store.read_one(algorithm_id)

    def exists(self, algorithm_id: str) -> bool:
        return self.store.exists(algorithm_id)

    def training_version_refs(self, task_id: str) -> list[tuple[str, str]]:
        return self.store.training_version_refs(task_id)

    # -- history-reference evidence (read-only, never initializes) ---------
    def history_revision(self) -> str | None:
        return self.store.history_revision()

    def history_has_versions(self) -> bool | None:
        return self.store.history_has_versions()

    def history_algorithm_payloads(
        self, *, after: str | None = None, limit: int = 200
    ) -> list[tuple[str, dict]]:
        return self.store.history_algorithm_payloads(after=after, limit=limit)

    def history_version_payloads(
        self, *, after: str | None = None, limit: int = 200
    ) -> list[tuple[str, dict]]:
        return self.store.history_version_payloads(after=after, limit=limit)

    def replace_all(self, algorithms: Sequence[Mapping[str, Any]]) -> None:
        self.store.replace_all(algorithms)

    def create_algorithm(self, item: Mapping[str, Any]) -> dict:
        return self.store.create_algorithm(item)

    def patch_algorithm(
        self, algorithm_id: str, patch: Mapping[str, Any], *, replace_analyses: bool = False
    ) -> dict:
        return self.store.patch_algorithm(algorithm_id, patch, replace_analyses=replace_analyses)

    def delete_algorithm(self, algorithm_id: str) -> None:
        self.store.delete_algorithm(algorithm_id)

    def attach_version(self, algorithm_id: str, version: Mapping[str, Any]) -> dict:
        return self.store.attach_version(algorithm_id, version)

    def attach_version_if_current(
        self,
        algorithm_id: str,
        version: Mapping[str, Any],
        *,
        expected_current_version_id: str | None,
    ) -> dict:
        return self.store.attach_version_if_current(
            algorithm_id, version, expected_current_version_id=expected_current_version_id
        )

    def patch_version(
        self, algorithm_id: str, version_id: str, patch: Mapping[str, Any], *, now: str
    ) -> dict:
        return self.store.patch_version(algorithm_id, version_id, patch, now=now)

    def rollback_version(
        self,
        algorithm_id: str,
        target_version_id: str,
        *,
        expected_current_version_id: str,
        operation: Mapping[str, Any],
        now: str,
        delete_current_version: bool,
    ) -> dict | None:
        return self.store.rollback_version(
            algorithm_id,
            target_version_id,
            expected_current_version_id=expected_current_version_id,
            operation=operation,
            now=now,
            delete_current_version=delete_current_version,
        )

    def delete_version_with_operation(
        self,
        algorithm_id: str,
        version_id: str,
        *,
        expected_current_version_id: str | None,
        operation: Mapping[str, Any],
        now: str,
    ) -> dict:
        return self.store.delete_version_with_operation(
            algorithm_id,
            version_id,
            expected_current_version_id=expected_current_version_id,
            operation=operation,
            now=now,
        )

    def update_version_operation(
        self, algorithm_id: str, operation_id: str, patch: Mapping[str, Any]
    ) -> None:
        self.store.update_version_operation(algorithm_id, operation_id, patch)

    def sync_external_algorithms(
        self, incoming: Mapping[str, Mapping[str, Any]], *, provider: str, synced_at: str
    ) -> dict[str, int]:
        return self.store.sync_external_algorithms(
            incoming, provider=provider, synced_at=synced_at
        )

    # -- external algorithm cleanup ---------------------------------------
    def cleanup_ensure_schema(self) -> None:
        self.store.cleanup_ensure_schema()

    def cleanup_get(self, operation_id: str) -> dict | None:
        return self.store.cleanup_get(operation_id)

    def cleanup_list(self) -> list[dict]:
        return self.store.cleanup_list()

    def cleanup_summary(self, *, project_id: str, suspected_state: str) -> dict[str, int]:
        return self.store.cleanup_summary(
            project_id=project_id, suspected_state=suspected_state
        )

    def cleanup_public_operations(
        self, *, project_id: str, suspected_state: str, limit: int, offset: int
    ) -> list[dict]:
        return self.store.cleanup_public_operations(
            project_id=project_id,
            suspected_state=suspected_state,
            limit=limit,
            offset=offset,
        )

    def cleanup_public_operation(
        self, *, project_id: str, operation_id: str, suspected_state: str
    ) -> dict | None:
        return self.store.cleanup_public_operation(
            project_id=project_id,
            operation_id=operation_id,
            suspected_state=suspected_state,
        )

    def cleanup_confirm_deleted(self, **fields: Any) -> dict[str, Any]:
        return self.store.cleanup_confirm_deleted(**fields)

    def cleanup_update(self, **fields: Any) -> dict[str, Any]:
        return self.store.cleanup_update(**fields)


def admission_record_path(json_path: str | Path) -> Path:
    return Path(json_path).parent / ADMISSION_DIRNAME / ADMISSION_FILENAME


def admission_transition_path(record_path: str | Path) -> Path:
    """Marker written before a cutover/rollback changes the authoritative writer.

    It is published *before* PostgreSQL commits the new authority, so a crash in
    that window leaves "neither side may write" instead of two possible owners.
    """
    target = Path(record_path)
    return target.with_name(target.name + ".transition")


#: Suffix of the transition marker that sits next to an admission record.
_TRANSITION_SUFFIX = ".transition"


def _lock_owner_path(path: str | Path) -> Path:
    """The admission record a lock path belongs to (marker paths included).

    A SQLite writer and the marker publication must contend on the *same* file
    lock, otherwise publishing the marker does not wait for an already admitted
    write transaction and the "drain, then block" guarantee is void.
    """
    target = Path(path)
    if target.name.endswith(_TRANSITION_SUFFIX):
        return target.with_name(target.name[: -len(_TRANSITION_SUFFIX)])
    return target


def admission_switch_lock(path: str | Path, *, timeout: float = 5.0):
    """One mutex shared by a switch publication and every SQLite write.

    A SQLite writer holds it across (authority check -> store write) and a
    cutover/rollback holds it across (marker/record publication), so a writer
    that already passed the check cannot slip a write past the switch boundary
    and a marker publish always happens after admitted writers drained.
    """
    from filelock import FileLock

    target = _lock_owner_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    return FileLock(str(target) + ".switch.lock", timeout=timeout, thread_local=False)


def resolve_provider(
    provider: str | None = None, *, environ: Mapping[str, str] | None = None
) -> str:
    environment = os.environ if environ is None else environ
    selected = str(provider or environment.get(ENV_PROVIDER) or PROVIDER_SQLITE).strip().lower()
    if selected not in SUPPORTED_PROVIDERS:
        raise AlgorithmProviderConfigError(
            "ALGORITHM_PROVIDER_UNKNOWN",
            "unknown algorithm store provider",
            detail=f"provider={selected!r} supported={list(SUPPORTED_PROVIDERS)}",
        )
    return selected


def open_algorithm_repository(
    json_path: str | Path,
    *,
    provider: str | None = None,
    dsn: str | None = None,
    environ: Mapping[str, str] | None = None,
    admission_path: str | Path | None = None,
    allow_stale_sqlite: bool = False,
) -> AlgorithmRepository:
    """Open the algorithm repository for one project.

    Default: SQLite with the existing behaviour.  PostgreSQL requires an
    admission record written by ``algorithm_migration_cli cutover-admit``;
    selecting it never falls back to SQLite.  Selecting SQLite while a
    PostgreSQL admission is active is refused unless ``allow_stale_sqlite`` is
    passed explicitly by a migration tool.
    """
    environment = os.environ if environ is None else environ
    selected = resolve_provider(provider, environ=environment)
    json_path = Path(json_path)
    record_path = Path(admission_path) if admission_path else admission_record_path(json_path)

    if selected == PROVIDER_SQLITE:
        if not allow_stale_sqlite:
            _refuse_stale_sqlite(json_path, record_path)
        return SqliteAlgorithmRepository(json_path, admission_path=record_path)

    # PostgreSQL selection is fail-closed: no DSN and no admission means no
    # provider, never a silent SQLite fallback.
    resolved_dsn = str(dsn or environment.get(ENV_DSN) or "").strip()
    if not resolved_dsn:
        raise AlgorithmProviderConfigError(
            "ALGORITHM_POSTGRES_DSN_MISSING",
            "PostgreSQL provider requires a DSN",
            detail=f"pass dsn= or set {ENV_DSN}",
        )
    record = load_admission_record(record_path)
    if record is None:
        raise AlgorithmAdmissionRequired(
            "ALGORITHM_POSTGRES_ADMISSION_REQUIRED",
            "PostgreSQL provider requires a cutover admission record",
            detail=f"expected {record_path}",
        )
    if str(record.get("project_id") or "") != json_path.parent.name:
        raise AlgorithmAdmissionRequired(
            "ALGORITHM_POSTGRES_ADMISSION_PROJECT_MISMATCH",
            "admission record belongs to another project",
            detail=f"record={record.get('project_id')!r} project={json_path.parent.name!r}",
        )
    from .algorithm_postgres_store import PostgresAlgorithmRepository

    # This factory only *selects* the provider; it has no authority to write or
    # release the SQLite barrier. Changing that persistent evidence requires a
    # verified maintenance settlement (switch_maintenance_owner / rollback /
    # recover_maintenance), which proves the durable PostgreSQL state first.
    # Opening a provider from a stale local admission record must never be able
    # to release a newer generation's blocking barrier.
    return PostgresAlgorithmRepository(
        resolved_dsn, str(record["project_id"]), admission=record
    )


#: Barrier phases that prove this SQLite copy is not the admitted writer.
_BARRIER_BLOCKING_PHASES = frozenset({"SWITCHING", "POSTGRES_ACTIVE"})
#: Barrier phases that prove SQLite is the writer again (or never left it).
_BARRIER_RELEASED_PHASES = frozenset({"SQLITE_ACTIVE", "ROLLBACK_APPLIED"})


def authority_barrier_path(json_path: str | Path) -> Path:
    """The SQLite file that carries the local authority barrier."""
    from .algorithm_sql_store import DB_FILENAME

    return Path(json_path).parent / DB_FILENAME


def write_authority_barrier(
    json_path: str | Path,
    *,
    project_id: str,
    phase: str,
    operation_id: str = "",
    writer_generation: int = 0,
    admission_id: str = "",
    record_path: str | Path | None = None,
    require_operation: str | None = None,
    require_phase: str | None = None,
    allowed_phases: Sequence[str] | None = None,
    require_existing: bool = False,
) -> bool:
    """Record this project's local authority state inside the SQLite catalog.

    The write takes the same switch mutex every SQLite writer takes (the mutex of
    the *same* admission record the caller uses, so a project never ends up with
    two lock identities). It is compare-and-swap: a barrier recording a *higher*
    writer generation is never overwritten by an older one, and a caller that
    names the operation/phase it settles must match what is recorded. Releasing a
    blocking barrier (SQLITE_ACTIVE / ROLLBACK_APPLIED) therefore requires the
    exact predecessor the maintenance contract proved.

    ``writer_generation`` is the generation the barrier *claims* - the committed
    durable generation, never a not-yet-committed target. A switch therefore
    records its attempt at the current generation and only settles at the
    committed one after the admission transaction succeeds.
    """
    from .algorithm_sql_store import AlgorithmSqlStore

    path = Path(json_path)
    lock_owner = Path(record_path) if record_path else admission_record_path(path)
    with admission_switch_lock(lock_owner):
        store = AlgorithmSqlStore(path)
        current = store.read_authority_barrier()
        if current is None and (
            require_existing or require_operation is not None or require_phase is not None
            or allowed_phases is not None
        ):
            # A settlement must prove the blocker it releases; a missing barrier
            # is not "nothing to check".
            raise AlgorithmAdmissionRequired(
                "ALGORITHM_SQLITE_CUTOVER_BARRIER_MISSING",
                "no local authority barrier records this operation",
                detail=f"project={project_id!r} expected={require_operation!r}",
            )
        if current is not None:
            if str(current.get("project_id") or "") != str(project_id):
                raise AlgorithmAdmissionRequired(
                    "ALGORITHM_SQLITE_CUTOVER_BARRIER_INVALID",
                    "the local authority barrier belongs to another project",
                    detail=f"barrier={current.get('project_id')!r} project={project_id!r}",
                )
            recorded_generation = int(current.get("writer_generation") or 0)
            if int(writer_generation or 0) < recorded_generation:
                raise AlgorithmAdmissionRequired(
                    "ALGORITHM_SQLITE_CUTOVER_BARRIER_STALE",
                    "a newer generation owns the local authority barrier",
                    detail=(
                        f"recorded={recorded_generation} requested={int(writer_generation or 0)}"
                    ),
                )
            if require_operation is not None and str(
                current.get("operation_id") or ""
            ) != str(require_operation):
                raise AlgorithmAdmissionRequired(
                    "ALGORITHM_SQLITE_CUTOVER_BARRIER_OPERATION_MISMATCH",
                    "the local authority barrier names another operation",
                    detail=(
                        f"recorded={current.get('operation_id')!r} "
                        f"expected={require_operation!r}"
                    ),
                )
            recorded_phase = str(current.get("phase") or "")
            if require_phase is not None and recorded_phase != str(require_phase):
                raise AlgorithmAdmissionRequired(
                    "ALGORITHM_SQLITE_CUTOVER_BARRIER_PHASE_MISMATCH",
                    "the local authority barrier is not in the expected phase",
                    detail=f"recorded={recorded_phase!r} expected={require_phase!r}",
                )
            if allowed_phases is not None and recorded_phase not in {
                str(value) for value in allowed_phases
            }:
                raise AlgorithmAdmissionRequired(
                    "ALGORITHM_SQLITE_CUTOVER_BARRIER_PHASE_MISMATCH",
                    "the local authority barrier is not in an allowed phase",
                    detail=(
                        f"recorded={recorded_phase!r} "
                        f"allowed={[str(value) for value in allowed_phases]}"
                    ),
                )
        return store.write_authority_barrier({
            "schema": "algorithm-authority-barrier/1",
            "project_id": str(project_id),
            "phase": str(phase),
            "operation_id": str(operation_id or ""),
            "writer_generation": int(writer_generation or 0),
            "admission_id": str(admission_id or ""),
        })


def _refuse_stale_sqlite(json_path: Path, record_path: Path) -> None:
    if admission_transition_path(record_path).exists():
        raise AlgorithmAdmissionRequired(
            "ALGORITHM_CUTOVER_IN_PROGRESS",
            "an algorithm cutover is unresolved; neither provider may write",
            detail=(
                "a transition marker is present next to the admission record; "
                "inspect it and finish or roll back the cutover before writing"
            ),
        )
    project_id = json_path.parent.name
    # The barrier lives in the SQLite catalog itself, so it survives a lost or
    # damaged admission record: once the switch recorded "not SQLite", only a
    # verified rollback (which rewrites the barrier) may re-open writing.
    from .algorithm_sql_store import AlgorithmSqlStore

    barrier = AlgorithmSqlStore.read_authority_barrier_file(
        authority_barrier_path(json_path)
    )
    if barrier is not None:
        barrier_project = str(barrier.get("project_id") or "")
        barrier_phase = str(barrier.get("phase") or "")
        if barrier_project != project_id:
            raise AlgorithmAdmissionRequired(
                "ALGORITHM_SQLITE_CUTOVER_BARRIER_INVALID",
                "the local authority barrier belongs to another project",
                detail=f"barrier={barrier_project!r} project={project_id!r}",
            )
        if barrier_phase not in _BARRIER_RELEASED_PHASES:
            raise AlgorithmAdmissionRequired(
                "ALGORITHM_SQLITE_STALE_AFTER_CUTOVER",
                "SQLite is no longer the authoritative algorithm writer",
                detail=(
                    f"local authority barrier phase={barrier_phase or 'UNKNOWN'} "
                    f"operation={barrier.get('operation_id')} "
                    f"generation={barrier.get('writer_generation')}; a verified "
                    "rollback must rewrite the barrier before SQLite writes again"
                ),
            )
    record = load_admission_record(record_path)
    if record is None:
        return
    if str(record.get("authoritative_provider") or "") != PROVIDER_POSTGRESQL:
        return
    if record.get("revoked_at"):
        return
    if str(record.get("project_id") or "") != project_id:
        return
    raise AlgorithmAdmissionRequired(
        "ALGORITHM_SQLITE_STALE_AFTER_CUTOVER",
        "SQLite is no longer the authoritative algorithm writer",
        detail=(
            "PostgreSQL admission "
            f"{record.get('admission_id')} is active; run the rollback assessment "
            "before serving SQLite again"
        ),
    )


def load_admission_record(path: str | Path) -> dict[str, Any] | None:
    """Read a local admission record; malformed records are refused."""
    import json

    target = Path(path)
    if not target.is_file():
        return None
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise AlgorithmAdmissionRequired(
            "ALGORITHM_ADMISSION_RECORD_INVALID",
            "cutover admission record cannot be read",
            detail=str(error),
        ) from error
    if not isinstance(value, dict):
        raise AlgorithmAdmissionRequired(
            "ALGORITHM_ADMISSION_RECORD_INVALID",
            "cutover admission record is not an object",
        )
    if str(value.get("contract_version") or "") != CONTRACT_VERSION:
        raise AlgorithmAdmissionRequired(
            "ALGORITHM_ADMISSION_RECORD_INVALID",
            "cutover admission record contract does not match",
            detail=f"contract={value.get('contract_version')!r}",
        )
    return value
