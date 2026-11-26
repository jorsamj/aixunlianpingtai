"""U2 storage-source PostgreSQL contracts against a real PostgreSQL server.

Runs against ``pgserver`` (or the CI service container via
``MC_TEST_POSTGRES_DSN``). It never claims anything about SQLite-only runs.
"""
from __future__ import annotations

import json
import pathlib
import tempfile

import pytest


def _require_or_skip(module_name: str, reason: str):
    import importlib
    import os

    try:
        return importlib.import_module(module_name)
    except ImportError:
        if os.environ.get("MC_REQUIRE_POSTGRES", "").strip() == "1":
            raise RuntimeError(
                f"MC_REQUIRE_POSTGRES=1 but {module_name} is unavailable: {reason}"
            )
        pytest.skip(reason, allow_module_level=True)


psycopg = _require_or_skip("psycopg", "psycopg 3 is required for PostgreSQL contracts")
_EXTERNAL_DSN_ENV = "MC_TEST_POSTGRES_DSN"

from platform_core.storage.source_repository import (
    StorageSourceConflictError,
    StorageSourceOperationBlocked,
    StorageSourceRepository,
    admission_record_path,
    admission_transition_path,
)
from platform_core.storage_source_cutover import (
    STATE_INCONSISTENT,
    STATE_POSTGRES,
    STATE_SQLITE,
    abort_cutover,
    admit_cutover,
    cutover_status,
    finish_cutover,
)
from platform_core.storage_source_migration import (
    StorageSourceMigrationError,
    export_snapshot,
    export_target_snapshot,
    import_snapshot,
    reconcile,
)
from platform_core.storage_source_postgres_schema import (
    SCHEMA_NAME,
    ensure_schema,
    schema_status,
)
from platform_core.storage_source_postgres_store import PostgresStorageSourceRepository

SCOPE = "platform"


class _ExternalPostgres:
    def __init__(self, dsn: str):
        self._dsn = dsn

    def get_uri(self) -> str:
        return self._dsn

    def cleanup(self) -> None:
        try:
            with psycopg.connect(self._dsn) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(f"DROP SCHEMA IF EXISTS {SCHEMA_NAME} CASCADE")
                connection.commit()
        except Exception:
            pass


@pytest.fixture(scope="module")
def pg():
    import os

    external = os.environ.get(_EXTERNAL_DSN_ENV, "").strip()
    if external:
        server = _ExternalPostgres(external)
        yield server
        server.cleanup()
        return
    pgserver = _require_or_skip("pgserver", "an isolated local PostgreSQL server is required")
    root = pathlib.Path(tempfile.mkdtemp(prefix="pgw4-")) / "data"
    server = pgserver.get_server(root, cleanup_mode="delete")
    yield server
    server.cleanup()


def _sqlite_owner(tmp_path, *, name="NAS"):
    """A real SQLite owner with one extra source, ready to be switched."""
    repository = StorageSourceRepository(
        tmp_path / "storage" / "storage_sources.sqlite3",
        reference_counter=lambda _source_id: 0,
    )
    repository.create(
        {
            "id": "nas-1",
            "name": name,
            "type": "remote",
            "config": {"root": "/mnt/nas"},
            "secret_ref": "secret://storage-source/nas-1",
        }
    )
    return repository


def _provider(pg, tmp_path, *, scope=SCOPE, reference_counter=None, allow_delete=False):
    path = admission_record_path(tmp_path / "storage" / "storage_sources.sqlite3")
    record = json.loads(path.read_text(encoding="utf-8"))
    return PostgresStorageSourceRepository(
        pg.get_uri(),
        scope,
        admission=record,
        admission_path=path,
        reference_counter=reference_counter,
        allow_cross_domain_delete=allow_delete,
    )


def _clear(connection):
    with connection.cursor() as cursor:
        cursor.execute(f"DELETE FROM {SCHEMA_NAME}.storage_source WHERE scope=%s", (SCOPE,))
        cursor.execute(f"DELETE FROM {SCHEMA_NAME}.cutover_state WHERE scope=%s", (SCOPE,))
    connection.commit()


def test_storage_source_owner_contract(pg, tmp_path):
    with psycopg.connect(pg.get_uri()) as connection:
        ensure_schema(connection, allow_upgrade=True)
        assert schema_status(connection)["up_to_date"] is True
        _clear(connection)

    owner = _sqlite_owner(tmp_path)
    with psycopg.connect(pg.get_uri()) as connection:
        admitted = admit_cutover(
            connection,
            owner.path,
            operator="ops",
            reason="pilot",
        )
    assert admitted["admitted"] is True and admitted["writer_generation"] == 1
    assert not admission_transition_path(
        admission_record_path(owner.path)
    ).exists()

    repository = _provider(pg, tmp_path)
    assert repository.provider_name == "postgresql"
    assert [source.id for source in repository.list()] == ["default_local", "nas-1"]
    assert repository.default().id == "default_local"

    nas = repository.create(
        {
            "id": "nas-2",
            "name": "NAS 2",
            "type": "remote",
            "config": {"root": "/mnt/nas2"},
            "secret_ref": "secret://storage-source/nas-2",
        }
    )
    assert nas.secret_ref == "secret://storage-source/nas-2"
    assert [source.id for source in repository.list()] == [
        "default_local", "nas-1", "nas-2",
    ]
    assert repository.get("nas-1").secret_ref == "secret://storage-source/nas-1"

    # Duplicate name is the owner's conflict error, not a raw driver exception.
    with pytest.raises(StorageSourceConflictError):
        repository.create({"id": "nas-3", "name": "NAS 2", "type": "remote"})

    # Default switching is atomic and refuses a disabled source.
    assert repository.set_default("nas-1").is_default is True
    assert repository.default().id == "nas-1"
    assert repository.get("default_local").is_default is False
    repository.update("nas-1", {"enabled": False})
    with pytest.raises(ValueError):
        repository.set_default("nas-1")
    repository.update("nas-1", {"enabled": True})
    repository.set_default("default_local")

    # A rename keeps the runtime epoch; a config/secret/enabled change bumps it.
    before_rename = repository.get("nas-1").runtime_revision
    renamed = repository.update("nas-1", {"name": "NAS renamed"})
    assert renamed.name == "NAS renamed"
    assert renamed.runtime_revision == before_rename
    bumped = repository.update("nas-1", {"config": {"root": "/mnt/nas2"}})
    assert bumped.runtime_revision == before_rename + 1
    # A->B->A must still bump the epoch.
    back = repository.update("nas-1", {"config": {"root": "/mnt/nas"}})
    assert back.runtime_revision == bumped.runtime_revision + 1
    with pytest.raises(ValueError):
        repository.update("default_local", {"enabled": False})
    with pytest.raises(ValueError):
        repository.update("nas-1", {"unsupported": 1})

    health = repository.record_health("nas-1", ok=True, message="杩炴帴姝ｅ父 api_key=sk-live-secret")
    assert health.health_status == "AVAILABLE"
    assert "[REDACTED]" in health.health_message
    with pytest.raises(KeyError):
        repository.record_health("missing", ok=True, message="ok")

    with pytest.raises(StorageSourceOperationBlocked):
        repository.delete("nas-1")


def test_migration_export_import_is_idempotent_and_reconciles(pg, tmp_path):
    with psycopg.connect(pg.get_uri()) as connection:
        ensure_schema(connection, allow_upgrade=True)
        _clear(connection)

    sqlite_repository = StorageSourceRepository(
        tmp_path / "storage" / "storage_sources.sqlite3",
        reference_counter=lambda _source_id: 0,
    )
    sqlite_repository.create(
        {
            "id": "oss-1",
            "name": "瀵硅薄瀛樺偍",
            "type": "s3",
            "config": {"bucket": "changlian"},
            "secret_ref": "secret://storage-source/oss-1",
        }
    )
    sqlite_repository.set_default("oss-1")
    snapshot = export_snapshot(sqlite_repository.path, SCOPE)
    assert snapshot["counts"]["sources"] == 2

    with psycopg.connect(pg.get_uri()) as connection:
        with connection.transaction():
            first = import_snapshot(connection, snapshot)
        assert first["inserted"] == 2
        # A second identical import changes nothing (idempotent).
        with connection.transaction():
            again = import_snapshot(connection, snapshot)
        assert again["applied"] is False
        assert again["unchanged"] == 2
        assert again["inserted"] == 0 and again["updated"] == 0

        target = export_target_snapshot(connection, SCOPE)
        report = reconcile(snapshot, target)
        assert report["same"] is True, report
        assert report["checks"]["target_default"] == "oss-1"

        # A newer target generation is never overwritten by the old snapshot.
        newer = json.loads(json.dumps(snapshot))
        for row in newer["rows"]:
            if row["id"] == "oss-1":
                row["runtime_revision"] = 5
                row["config"] = {"bucket": "changlian-new"}
        with connection.transaction():
            import_snapshot(connection, newer)
        with pytest.raises(StorageSourceMigrationError) as regression:
            with connection.transaction():
                import_snapshot(connection, snapshot)
        assert regression.value.code == "STORAGE_SOURCE_MIGRATION_REVISION_REGRESSION"
        after = export_target_snapshot(connection, SCOPE)
        assert any(
            row["id"] == "oss-1" and row["runtime_revision"] == 5
            for row in after["rows"]
        )
        mismatch = reconcile(snapshot, after)
        assert mismatch["verdict"] == "MISMATCH"
        assert "identity_differences" in mismatch["blocking_findings"]

def test_fenced_cutover_blocks_writes_and_recovers(pg, tmp_path):
    """The switch fence, the durable cutover row and the crash recovery paths."""
    with psycopg.connect(pg.get_uri()) as connection:
        ensure_schema(connection, allow_upgrade=True)
        _clear(connection)

    owner = _sqlite_owner(tmp_path)
    record_path = admission_record_path(owner.path)
    marker_path = admission_transition_path(record_path)
    assert cutover_status(owner.path)["state"] == STATE_SQLITE

    with psycopg.connect(pg.get_uri()) as connection:
        admitted = admit_cutover(connection, owner.path, operator="ops", reason="pilot")
    assert admitted["writer_generation"] == 1
    assert not marker_path.exists()
    assert cutover_status(owner.path)["state"] == STATE_POSTGRES

    # SQLite can no longer write, and PostgreSQL is the admitted writer.
    with pytest.raises(Exception) as stale:
        owner.create({"id": "nas-9", "name": "NAS 9", "type": "remote"})
    assert getattr(stale.value, "code", "") == "STORAGE_SOURCE_SQLITE_STALE_AFTER_CUTOVER"
    repository = _provider(pg, tmp_path)
    assert [source.id for source in repository.list()] == ["default_local", "nas-1"]

    # Crash after the durable publication but before the marker was released:
    # both providers must stay blocked until finish proves the published state.
    record = json.loads(record_path.read_text(encoding="utf-8"))
    marker_path.write_text(
        json.dumps(
            {
                "contract_version": "storage-source-cutover-transition-v1",
                "operation_id": record["operation_id"],
                "scope": record["scope"],
                "phase": "POSTGRES_ACTIVE",
                "writer_generation": record["writer_generation"],
            }
        ),
        encoding="utf-8",
    )
    assert cutover_status(owner.path)["state"] == STATE_INCONSISTENT
    with pytest.raises(Exception) as blocked:
        repository.create({"id": "nas-8", "name": "NAS 8", "type": "remote"})
    assert getattr(blocked.value, "code", "") == "STORAGE_SOURCE_CUTOVER_IN_PROGRESS"
    with pytest.raises(Exception) as published:
        abort_cutover(owner.path)
    assert getattr(published.value, "code", "") == "STORAGE_SOURCE_CUTOVER_ALREADY_ADMITTED"

    with psycopg.connect(pg.get_uri()) as connection:
        finished = finish_cutover(connection, owner.path)
    assert finished["finished"] is True
    assert not marker_path.exists()
    assert cutover_status(owner.path)["state"] == STATE_POSTGRES
    assert repository.create(
        {"id": "nas-8", "name": "NAS 8", "type": "remote"}
    ).id == "nas-8"

    # A switch that crashed before publishing the record can be aborted: SQLite
    # becomes writable again and PostgreSQL still has no admission record.
    record_path.unlink()
    on_disk = admission_transition_path(admission_record_path(owner.path))
    on_disk.write_text(
        json.dumps(
            {
                "contract_version": "storage-source-cutover-transition-v1",
                "operation_id": "crashed-switch",
                "scope": SCOPE,
                "phase": "SWITCHING",
                "writer_generation": 2,
            }
        ),
        encoding="utf-8",
    )
    assert cutover_status(owner.path)["state"] == "SWITCHING"
    assert abort_cutover(owner.path)["aborted"] is True
    assert not on_disk.exists()
    assert cutover_status(owner.path)["state"] == STATE_SQLITE
    assert owner.update("nas-1", {"name": "NAS again"}).name == "NAS again"

    # Re-admission after a verified rollback uses a real monotonic generation.
    # A rollback re-aligns PostgreSQL with SQLite and records the rolled-back
    # phase before the local admission is cleared; admitting again must then use
    # the next durable generation instead of restarting at 1.
    with psycopg.connect(pg.get_uri()) as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    f"DELETE FROM {SCHEMA_NAME}.storage_source "
                    "WHERE scope=%s AND id='nas-8'",
                    (SCOPE,),
                )
                cursor.execute(
                    f"UPDATE {SCHEMA_NAME}.cutover_state SET phase='ROLLBACK_APPLIED' "
                    "WHERE scope=%s",
                    (SCOPE,),
                )
        with connection.transaction():
            import_snapshot(connection, export_snapshot(owner.path, SCOPE))
        second = admit_cutover(connection, owner.path, operator="ops", reason="re-run")
    assert second["writer_generation"] == 2
    assert second["admission_id"] != admitted["admission_id"]



def test_admission_refuses_a_changed_source_and_unknown_states(pg, tmp_path):
    with psycopg.connect(pg.get_uri()) as connection:
        ensure_schema(connection, allow_upgrade=True)
        _clear(connection)

    owner = _sqlite_owner(tmp_path)
    stale_digest = "0" * 64
    with psycopg.connect(pg.get_uri()) as connection:
        with pytest.raises(Exception) as changed:
            admit_cutover(
                connection,
                owner.path,
                operator="ops",
                reason="pilot",
                expected_source_digest=stale_digest,
            )
    assert getattr(changed.value, "code", "") == "STORAGE_SOURCE_CUTOVER_SOURCE_CHANGED"
    # Nothing was published and no marker may remain: SQLite still owns writes.
    assert cutover_status(owner.path)["state"] == STATE_SQLITE
    assert not admission_transition_path(
        admission_record_path(owner.path)
    ).exists()
    assert owner.update("nas-1", {"name": "NAS safe"}).name == "NAS safe"

    # A malformed marker is unknown state, never "no transition".
    marker = admission_transition_path(admission_record_path(owner.path))
    marker.write_text("{not json", encoding="utf-8")
    with pytest.raises(Exception) as invalid:
        cutover_status(owner.path)
    assert getattr(invalid.value, "code", "") == "STORAGE_SOURCE_CUTOVER_TRANSITION_INVALID"
    with pytest.raises(Exception):
        owner.update("nas-1", {"name": "must not write"})

def _switch_owner(tmp_path):
    """Fresh SQLite owner + cleared PostgreSQL scope for one cutover scenario."""
    return _sqlite_owner(tmp_path)


def _durable_row(dsn, scope=SCOPE):
    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT admission_id,writer_generation,phase "
                f"FROM {SCHEMA_NAME}.cutover_state WHERE scope=%s",
                (scope,),
            )
            row = cursor.fetchone()
        connection.rollback()
    return row


def test_switch_lock_identity_is_shared_by_writers_and_cutover(tmp_path):
    """Writers pass the database file, the cutover passes admission paths."""
    from platform_core.storage.source_repository import storage_source_switch_lock_path

    database = tmp_path / "storage" / "storage_sources.sqlite3"
    record = admission_record_path(database)
    marker = admission_transition_path(record)
    expected = database.parent / ".storage-source-switch.lock"
    assert storage_source_switch_lock_path(database) == expected
    assert storage_source_switch_lock_path(record) == expected
    assert storage_source_switch_lock_path(marker) == expected


def test_admit_cannot_pass_an_uncommitted_repository_write(pg, tmp_path, monkeypatch):
    """A real repository write pauses *inside its own fence*, before COMMIT.

    The barrier is the repository's own write path (the timestamp helper called by
    ``create`` while it still holds the switch lock and before the SQLite
    transaction commits). No external lock is taken by the test, so the ordering
    below is produced by the repository's fence itself.
    """
    import threading
    import time

    from platform_core.storage import source_repository as source_repository_module

    with psycopg.connect(pg.get_uri()) as connection:
        ensure_schema(connection, allow_upgrade=True)
        _clear(connection)

    owner = _switch_owner(tmp_path)
    real_now = source_repository_module._now
    writer_paused = threading.Event()
    release_writer = threading.Event()
    outcome = {}

    def blocking_now():
        value = real_now()
        if not writer_paused.is_set():
            writer_paused.set()
            assert release_writer.wait(20), "the in-flight writer was never released"
        return value

    monkeypatch.setattr(source_repository_module, "_now", blocking_now)

    def writer():
        # Runs the real write path: fence -> authority check -> SQLite write.
        outcome["created"] = owner.create(
            {"id": "nas-inflight", "name": "NAS in-flight", "type": "remote"}
        )

    def switcher():
        with psycopg.connect(pg.get_uri()) as connection:
            outcome["admit"] = admit_cutover(
                connection, owner.path, operator="ops", reason="wait for the commit"
            )

    writer_thread = threading.Thread(target=writer)
    writer_thread.start()
    assert writer_paused.wait(10), "the repository write never reached the barrier"
    switcher_thread = threading.Thread(target=switcher)
    switcher_thread.start()
    time.sleep(0.5)
    # The switch may not pass a write that has not committed yet.
    assert "admit" not in outcome
    release_writer.set()
    writer_thread.join(20)
    switcher_thread.join(30)

    assert outcome["created"].id == "nas-inflight"
    assert outcome["admit"]["admitted"] is True
    repository = _provider(pg, tmp_path)
    # The admitted target contains the row committed by the in-flight writer.
    assert repository.get("nas-inflight") is not None


def test_postgres_commit_precedes_the_local_admission(pg, tmp_path, monkeypatch):
    """The record may only appear after a real COMMIT (second connection proof)."""
    from psycopg.pq import TransactionStatus

    from platform_core import storage_source_cutover as cutover_module

    with psycopg.connect(pg.get_uri()) as connection:
        ensure_schema(connection, allow_upgrade=True)
        _clear(connection)

    owner = _switch_owner(tmp_path)
    seen = {"checks": []}
    real_write = cutover_module._write_json_atomic

    def spying_write(path, payload):
        if path.name == "cutover_admission.json":
            # Independent connection: the durable row must already be visible,
            # while the local admission does not exist yet.
            seen["checks"].append(
                {
                    "durable": _durable_row(pg.get_uri()),
                    "marker_present": admission_transition_path(path).exists(),
                    "record_present": path.exists(),
                }
            )
        return real_write(path, payload)

    monkeypatch.setattr(cutover_module, "_write_json_atomic", spying_write)
    with psycopg.connect(pg.get_uri()) as connection:
        admitted = admit_cutover(connection, owner.path, operator="ops", reason="commit order")
        assert connection.info.transaction_status == TransactionStatus.IDLE

    assert admitted["admitted"] is True
    assert seen["checks"], "the admission write was never observed"
    check = seen["checks"][0]
    assert check["durable"] is not None
    assert str(check["durable"][2]) == "POSTGRES_ACTIVE"
    assert int(check["durable"][1]) == admitted["writer_generation"]
    assert check["marker_present"] is True
    assert check["record_present"] is False


def test_import_failure_before_commit_rolls_back_and_releases_the_marker(pg, tmp_path, monkeypatch):
    """Exception injection *before* the COMMIT: the transaction rolls back.

    This is not a real SIGKILL. The failure is raised inside the switch and the
    handler releases the marker; a real process kill in this window leaves the
    marker in place (only pre-commit cleanup removes it), which is the fail-closed
    variant of the same state and is recovered by ``abort_cutover``.
    """
    from platform_core import storage_source_cutover as cutover_module

    with psycopg.connect(pg.get_uri()) as connection:
        ensure_schema(connection, allow_upgrade=True)
        _clear(connection)

    owner = _switch_owner(tmp_path)

    def failing_import(*_args, **_kwargs):
        raise RuntimeError("import interrupted before commit")

    monkeypatch.setattr(cutover_module, "import_snapshot", failing_import)
    with psycopg.connect(pg.get_uri()) as connection:
        with pytest.raises(RuntimeError):
            admit_cutover(connection, owner.path, operator="ops", reason="crash before commit")

    # PostgreSQL rolled back, the marker was released, SQLite owns writes again.
    assert _durable_row(pg.get_uri()) is None
    assert cutover_status(owner.path)["state"] == STATE_SQLITE
    assert not admission_transition_path(admission_record_path(owner.path)).exists()
    assert owner.update("nas-1", {"name": "NAS recovered"}).name == "NAS recovered"


def test_exception_after_commit_before_record_is_recovered_by_abort(pg, tmp_path, monkeypatch):
    """Exception injection *after* the COMMIT, before the admission record exists.

    The durable cutover row is really committed (verified by an independent
    connection), the local record is absent and the marker is deliberately kept:
    both providers stay blocked. ``finish_cutover`` refuses (nothing is published)
    and ``abort_cutover`` is the documented recovery. A real process kill in this
    window produces the same on-disk state, because the marker is published before
    the transaction starts and removed only after the record exists.
    """
    from platform_core import storage_source_cutover as cutover_module

    with psycopg.connect(pg.get_uri()) as connection:
        ensure_schema(connection, allow_upgrade=True)
        _clear(connection)

    owner = _switch_owner(tmp_path)
    record_path = admission_record_path(owner.path)
    marker_path = admission_transition_path(record_path)
    real_write = cutover_module._write_json_atomic

    def interrupt_record(path, payload):
        if path.name == "cutover_admission.json":
            raise RuntimeError("interrupted after the PostgreSQL commit")
        return real_write(path, payload)

    monkeypatch.setattr(cutover_module, "_write_json_atomic", interrupt_record)
    with psycopg.connect(pg.get_uri()) as connection:
        with pytest.raises(RuntimeError):
            admit_cutover(connection, owner.path, operator="ops", reason="crash window")

    # Durable state exists, the local record does not, and both providers are
    # blocked: no fake STEADY_POSTGRES with a removed marker.
    assert _durable_row(pg.get_uri()) is not None
    assert not record_path.exists()
    assert marker_path.exists()
    status = cutover_status(owner.path)
    # The marker is the only local evidence: the switch is unresolved, so neither
    # provider may write and no state is reported as steady.
    assert status["state"] == "SWITCHING"
    assert status["sqlite_writable"] is False and status["postgres_writable"] is False
    with pytest.raises(Exception) as blocked:
        owner.update("nas-1", {"name": "must stay blocked"})
    assert getattr(blocked.value, "code", "") == "STORAGE_SOURCE_CUTOVER_IN_PROGRESS"
    with psycopg.connect(pg.get_uri()) as connection:
        with pytest.raises(Exception) as no_record:
            finish_cutover(connection, owner.path)
    assert getattr(no_record.value, "code", "") == "STORAGE_SOURCE_CUTOVER_NOT_ADMITTED"

    # Abort is the documented recovery for an unpublished switch, and the
    # still-unpublished PostgreSQL rows cannot be written by the provider.
    assert abort_cutover(owner.path)["aborted"] is True
    assert cutover_status(owner.path)["state"] == STATE_SQLITE
    assert owner.update("nas-1", {"name": "NAS after abort"}).name == "NAS after abort"
    provider = PostgresStorageSourceRepository(
        pg.get_uri(), SCOPE, admission=None
    )
    with pytest.raises(Exception):
        provider.create({"id": "nas-z", "name": "NAS Z", "type": "remote"})


def test_exception_after_record_is_recovered_by_finish_cutover(pg, tmp_path, monkeypatch):
    """Exception injection after the record exists, before the marker is released.

    The durable row and the local record already agree, so ``finish_cutover`` can
    prove the published state and release the marker. A real process kill here
    leaves the same record+marker pair and the same finish recovery; a SIGKILL is
    not simulated by this test.
    """
    from platform_core import storage_source_cutover as cutover_module

    with psycopg.connect(pg.get_uri()) as connection:
        ensure_schema(connection, allow_upgrade=True)
        _clear(connection)

    owner = _switch_owner(tmp_path)
    record_path = admission_record_path(owner.path)
    marker_path = admission_transition_path(record_path)
    real_write = cutover_module._write_json_atomic

    def interrupt_marker_release(path, payload):
        if path.name.endswith(".transition") and str(payload.get("phase")) == "POSTGRES_ACTIVE":
            raise RuntimeError("interrupted after the admission was published")
        return real_write(path, payload)

    monkeypatch.setattr(cutover_module, "_write_json_atomic", interrupt_marker_release)
    with psycopg.connect(pg.get_uri()) as connection:
        with pytest.raises(RuntimeError):
            admit_cutover(connection, owner.path, operator="ops", reason="crash after publish")

    assert record_path.exists() and marker_path.exists()
    assert cutover_status(owner.path)["state"] == STATE_INCONSISTENT

    with psycopg.connect(pg.get_uri()) as connection:
        finished = finish_cutover(connection, owner.path)
    assert finished["finished"] is True
    assert not marker_path.exists()
    assert cutover_status(owner.path)["state"] == STATE_POSTGRES
    repository = _provider(pg, tmp_path)
    assert repository.update("nas-1", {"name": "NAS finished"}).name == "NAS finished"
