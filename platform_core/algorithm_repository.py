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


#: Store method names that mutate algorithm state. Anything reached through the
#: pass-through adapter with one of these prefixes is treated as a write and must
#: pass the authority guard, so an undeclared helper cannot silently bypass it.
_WRITE_NAME_PREFIXES = (
    "replace_", "create_", "patch_", "delete_", "attach_", "rollback_",
    "update_", "sync_", "save_", "write_", "set_", "remap_", "repair_",
)


class SqliteAlgorithmRepository:
    """Default provider: the existing SQLite store, delegated unchanged."""

    provider_name = PROVIDER_SQLITE

    def __init__(
        self,
        json_path: str | Path,
        *,
        admission_path: str | Path | None = None,
    ):
        self.store = AlgorithmSqlStore(Path(json_path))
        self.project_id = self.store.project_id
        self.db_path = self.store.db_path
        self.json_path = self.store.json_path
        self.record_path = (
            Path(admission_path)
            if admission_path
            else admission_record_path(Path(json_path))
        )

    def _guard_write(self) -> None:
        """Re-check authority on every write, not just when the instance opened.

        A long-lived SQLite instance created before a cutover must stop writing
        the moment PostgreSQL becomes authoritative (or while a cutover is
        unresolved), otherwise the factory check only protects new objects.
        """
        _refuse_stale_sqlite(Path(self.json_path), self.record_path)

    # -- provider metadata -------------------------------------------------
    def capabilities(self) -> frozenset[str]:
        return frozenset(CORE_OPERATIONS + PRESENTATION_OPERATIONS)

    def unsupported_operations(self) -> tuple[str, ...]:
        return ()

    def __getattr__(self, name: str) -> Any:
        # Presentation projections and any future store helper keep their exact
        # existing behaviour; the adapter is a pass-through, not a rewrite.
        if name.startswith("_"):
            raise AttributeError(name)
        attribute = getattr(self.store, name)
        if callable(attribute) and name.startswith(_WRITE_NAME_PREFIXES):
            def guarded(*args: Any, **kwargs: Any) -> Any:
                self._guard_write()
                return attribute(*args, **kwargs)
            return guarded
        return attribute

    # -- contract ----------------------------------------------------------
    def ensure_ready(self) -> None:
        self.store.ensure_ready()

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

    def replace_all(self, algorithms: Sequence[Mapping[str, Any]]) -> None:
        self._guard_write()
        self.store.replace_all(algorithms)

    def create_algorithm(self, item: Mapping[str, Any]) -> dict:
        self._guard_write()
        return self.store.create_algorithm(item)

    def patch_algorithm(
        self, algorithm_id: str, patch: Mapping[str, Any], *, replace_analyses: bool = False
    ) -> dict:
        self._guard_write()
        return self.store.patch_algorithm(algorithm_id, patch, replace_analyses=replace_analyses)

    def delete_algorithm(self, algorithm_id: str) -> None:
        self._guard_write()
        self.store.delete_algorithm(algorithm_id)

    def attach_version(self, algorithm_id: str, version: Mapping[str, Any]) -> dict:
        self._guard_write()
        return self.store.attach_version(algorithm_id, version)

    def attach_version_if_current(
        self,
        algorithm_id: str,
        version: Mapping[str, Any],
        *,
        expected_current_version_id: str | None,
    ) -> dict:
        self._guard_write()
        return self.store.attach_version_if_current(
            algorithm_id, version, expected_current_version_id=expected_current_version_id
        )

    def patch_version(
        self, algorithm_id: str, version_id: str, patch: Mapping[str, Any], *, now: str
    ) -> dict:
        self._guard_write()
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
        self._guard_write()
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
        self._guard_write()
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
        self._guard_write()
        self.store.update_version_operation(algorithm_id, operation_id, patch)

    def sync_external_algorithms(
        self, incoming: Mapping[str, Mapping[str, Any]], *, provider: str, synced_at: str
    ) -> dict[str, int]:
        self._guard_write()
        return self.store.sync_external_algorithms(
            incoming, provider=provider, synced_at=synced_at
        )


def admission_record_path(json_path: str | Path) -> Path:
    return Path(json_path).parent / ADMISSION_DIRNAME / ADMISSION_FILENAME


def admission_transition_path(record_path: str | Path) -> Path:
    """Marker written before a cutover/rollback changes the authoritative writer.

    It is published *before* PostgreSQL commits the new authority, so a crash in
    that window leaves "neither side may write" instead of two possible owners.
    """
    target = Path(record_path)
    return target.with_name(target.name + ".transition")


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

    return PostgresAlgorithmRepository(
        resolved_dsn, str(record["project_id"]), admission=record
    )


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
    record = load_admission_record(record_path)
    if record is None:
        return
    if str(record.get("authoritative_provider") or "") != PROVIDER_POSTGRESQL:
        return
    if record.get("revoked_at"):
        return
    if str(record.get("project_id") or "") != json_path.parent.name:
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
