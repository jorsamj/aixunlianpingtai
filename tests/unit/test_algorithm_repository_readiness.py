"""Regressions for the default SQLite algorithm provider (work package A).

These are the evidence for three defects that py_compile, import and
``pytest --collect-only`` cannot see:

* ``SqliteAlgorithmRepository`` defined ``ensure_ready`` twice and forwarded it
  back through the guarded store, so a real runtime call recursed;
* persistent initialization (WAL, schema bootstrap, legacy import and backup)
  could run outside the write owner, so a stale SQLite copy could be migrated
  after a cutover;
* the external-algorithm cleanup ledger was written through private SQLite
  connection helpers, which no provider-neutral adapter can serve.
"""
from __future__ import annotations

import ast
import json
import pathlib

import pytest

from platform_core.algorithm_repository import (
    AlgorithmAdmissionRequired,
    admission_record_path,
    admission_transition_path,
    open_algorithm_repository,
)
from platform_core.errors import PlatformError


def _legacy_project(tmp_path, name="p", rows=None):
    """A project that owns only the legacy JSON catalog (no SQLite copy yet)."""
    path = tmp_path / "projects" / name / "algorithms.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(rows or [{"id": "a", "name": "A"}]), encoding="utf-8"
    )
    return path


def _admission(path, *, project_id="p", provider="postgresql"):
    record = admission_record_path(path)
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(
        json.dumps({
            "contract_version": "algorithm-repository-v1",
            "project_id": project_id,
            "admission_id": "admit-x",
            "authoritative_provider": provider,
            "algorithm_revision": 1,
            "snapshot_digest": "0" * 64,
            "content_digest": "0" * 64,
            "writer_generation": 1,
            "admitted_at": "2026-11-24T00:00:00+00:00",
            "revoked_at": None,
            "operation_id": "op-1",
            "maintenance_phase": "POSTGRES_ACTIVE",
            "admission_mode": "maintenance",
        }),
        encoding="utf-8",
    )
    return record


def test_repository_initialization_runs_once_and_never_recurses(tmp_path):
    path = _legacy_project(tmp_path)
    repository = open_algorithm_repository(path)
    repository.ensure_ready()
    assert repository.is_initialized() is True
    assert [row["id"] for row in repository.read_all()] == ["a"]

    # A second instance validates the same catalog without re-importing it.
    second = open_algorithm_repository(path)
    assert [row["id"] for row in second.read_all()] == ["a"]
    assert second.revision() == repository.revision()

    # A write on a *fresh* store initialises inside the same guard: this is the
    # path that used to recurse (repository -> guarded store -> repository).
    fresh = _legacy_project(tmp_path, "q", rows=[])
    third = open_algorithm_repository(fresh)
    assert third.create_algorithm({"id": "b", "name": "B"})["id"] == "b"
    assert third.is_initialized() is True
    assert [row["id"] for row in third.read_all()] == ["b"]


def test_persistent_initialization_is_refused_for_a_stale_writer(tmp_path):
    path = _legacy_project(tmp_path)
    _admission(path)
    with pytest.raises(AlgorithmAdmissionRequired) as blocked:
        open_algorithm_repository(path, provider="sqlite")
    assert blocked.value.code == "ALGORITHM_SQLITE_STALE_AFTER_CUTOVER"

    # A migration tool may hold a stale reader, but no read path may create or
    # migrate the SQLite copy once PostgreSQL is the authoritative writer.
    stale = open_algorithm_repository(path, provider="sqlite", allow_stale_sqlite=True)
    with pytest.raises(AlgorithmAdmissionRequired):
        stale.ensure_ready()
    with pytest.raises(AlgorithmAdmissionRequired):
        stale.read_all()
    assert not (path.parent / "algorithms.sqlite3").exists()
    assert stale.is_initialized() is False


def test_transition_marker_blocks_an_already_open_sqlite_provider(tmp_path):
    path = _legacy_project(tmp_path)
    repository = open_algorithm_repository(path)
    repository.create_algorithm({"id": "first", "name": "first"})
    marker = admission_transition_path(admission_record_path(path))
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        json.dumps({
            "schema": "algorithm-maintenance/1",
            "phase": "QUIESCING",
            "operation_id": "op-open",
            "project_id": "p",
            "generation": 0,
            "source_provider": "sqlite",
            "target_provider": "postgresql",
        }),
        encoding="utf-8",
    )
    # The instance opened before the window must stop writing, so the switch can
    # drain: the guard is re-evaluated for every write, not cached at open time.
    with pytest.raises(AlgorithmAdmissionRequired) as blocked:
        repository.create_algorithm({"id": "late", "name": "late"})
    assert blocked.value.code == "ALGORITHM_CUTOVER_IN_PROGRESS"
    assert [row["id"] for row in open_algorithm_repository(
        path, allow_stale_sqlite=True
    ).read_all()] == ["first"]
    marker.unlink()
    assert repository.create_algorithm({"id": "after", "name": "after"})["id"] == "after"


def test_lost_admission_keeps_a_switched_project_closed(tmp_path):
    """The barrier lives in the catalog: losing the admission file must not reopen SQLite."""
    from platform_core.algorithm_repository import (
        authority_barrier_path,
        write_authority_barrier,
    )

    path = _legacy_project(tmp_path)
    repository = open_algorithm_repository(path)
    repository.create_algorithm({"id": "first", "name": "first"})
    assert authority_barrier_path(path).is_file()
    assert write_authority_barrier(
        path, project_id="p", phase="POSTGRES_ACTIVE", operation_id="op-switch",
        writer_generation=2, admission_id="admit-1",
    ) is True

    # No admission record exists at all: the catalog barrier alone must refuse.
    assert not admission_record_path(path).exists()
    with pytest.raises(AlgorithmAdmissionRequired) as blocked:
        repository.create_algorithm({"id": "stale", "name": "stale"})
    assert blocked.value.code == "ALGORITHM_SQLITE_STALE_AFTER_CUTOVER"
    assert [row["id"] for row in open_algorithm_repository(
        path, allow_stale_sqlite=True
    ).read_all()] == ["first"]

    # A verified rollback rewrites the barrier; only then does SQLite write again.
    assert write_authority_barrier(
        path, project_id="p", phase="ROLLBACK_APPLIED", operation_id="op-rollback",
        writer_generation=3, admission_id="admit-1",
    ) is True
    assert repository.create_algorithm({"id": "restored", "name": "restored"})["id"] == "restored"

    # A barrier that names another project, or is damaged, fails closed.
    authority_barrier_path(path).unlink()
    fresh = _legacy_project(tmp_path, "q")
    fresh_repository = open_algorithm_repository(fresh)
    fresh_repository.create_algorithm({"id": "base", "name": "base"})
    assert write_authority_barrier(
        fresh, project_id="other", phase="SQLITE_ACTIVE"
    ) is True
    with pytest.raises(AlgorithmAdmissionRequired) as foreign:
        fresh_repository.create_algorithm({"id": "cross", "name": "cross"})
    assert foreign.value.code == "ALGORITHM_SQLITE_CUTOVER_BARRIER_INVALID"

    from platform_core.errors import PlatformError
    from platform_core.algorithm_sql_store import AlgorithmSqlStore

    store = AlgorithmSqlStore(fresh)
    with store._connect() as connection:
        with connection:
            store._set_meta(connection, store.BARRIER_KEY, "{not json")
    with pytest.raises(PlatformError) as damaged:
        fresh_repository.create_algorithm({"id": "broken", "name": "broken"})
    assert damaged.value.code == "ALGORITHM_CUTOVER_BARRIER_INVALID"


def test_cleanup_domain_is_served_by_the_contract_and_fails_closed(tmp_path):
    path = _legacy_project(tmp_path)
    from platform_core.external_algorithm_cleanup import CleanupRepository

    # The default SQLite provider serves the cleanup ledger through the declared
    # operations (no private connection helpers).
    repository = CleanupRepository(path)
    assert repository.list_operations() == []
    assert repository.summary()["SUSPECTED_DELETED"] == 0

    # A provider that does not own the cleanup ledger refuses the whole domain
    # instead of writing to the stale SQLite copy behind the caller's back.
    from platform_core import external_algorithm_cleanup as cleanup
    from platform_core.algorithm_postgres_store import PostgresAlgorithmRepository

    monkeypatch_repository = PostgresAlgorithmRepository(
        "postgresql://example.invalid/db", "p"
    )
    original = cleanup.open_algorithm_repository
    cleanup.open_algorithm_repository = lambda *_args, **_kwargs: monkeypatch_repository
    try:
        with pytest.raises(PlatformError) as blocked:
            CleanupRepository(path)
    finally:
        cleanup.open_algorithm_repository = original
    assert blocked.value.code == "EXTERNAL_ALGORITHM_CLEANUP_PROVIDER_UNSUPPORTED"


def test_no_module_defines_the_same_class_method_twice():
    """A later definition silently replacing an earlier one is not detectable at
    import time; this guards the class of defect that produced the recursion."""
    root = pathlib.Path(__file__).resolve().parents[2]
    offenders = []
    for path in sorted((root / "platform_core").rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:  # pragma: no cover - a syntax error fails elsewhere
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            seen: dict[str, int] = {}
            for item in node.body:
                if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if item.name in seen:
                    offenders.append(
                        f"{path.name}:{node.name}.{item.name}"
                        f"@{seen[item.name]}@{item.lineno}"
                    )
                seen[item.name] = item.lineno
    assert offenders == []
