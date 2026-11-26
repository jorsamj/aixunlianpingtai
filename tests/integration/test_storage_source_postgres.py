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
