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
    CONTRACT_VERSION,
    StorageSourceConflictError,
    StorageSourceOperationBlocked,
    StorageSourceRepository,
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


def _admission(tmp_path, *, scope=SCOPE, revoked=None):
    path = tmp_path / "storage_source_migration" / "cutover_admission.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "contract_version": CONTRACT_VERSION,
                "admission_id": "admit-w4",
                "scope": scope,
                "authoritative_provider": "postgresql",
                "writer_generation": 1,
                "admitted_at": "2026-11-26T00:00:00+00:00",
                "revoked_at": revoked,
                "operator": "ops",
                "reason": "pilot",
            }
        ),
        encoding="utf-8",
    )
    return path


def _provider(pg, tmp_path, *, reference_counter=None, allow_delete=False):
    record = _admission(tmp_path)
    record_data = json.loads(record.read_text(encoding="utf-8"))
    return PostgresStorageSourceRepository(
        pg.get_uri(),
        SCOPE,
        admission=record_data,
        admission_path=record,
        reference_counter=reference_counter,
        allow_cross_domain_delete=allow_delete,
    )


def _clear(connection):
    with connection.cursor() as cursor:
        cursor.execute(f"DELETE FROM {SCHEMA_NAME}.storage_source WHERE scope=%s", (SCOPE,))
    connection.commit()


def test_storage_source_owner_contract(pg, tmp_path):
    with psycopg.connect(pg.get_uri()) as connection:
        ensure_schema(connection, allow_upgrade=True)
        assert schema_status(connection)["up_to_date"] is True
        _clear(connection)

    repository = _provider(pg, tmp_path)
    assert repository.provider_name == "postgresql"
    # The provider keeps the SQLite product invariant: a fresh scope always has
    # the platform local default source.
    assert [source.id for source in repository.list()] == ["default_local"]
    assert repository.default().id == "default_local"

    nas = repository.create(
        {
            "id": "nas-1",
            "name": "NAS",
            "type": "remote",
            "config": {"root": "/mnt/nas"},
            "secret_ref": "secret://storage-source/nas-1",
        }
    )
    assert nas.secret_ref == "secret://storage-source/nas-1"
    assert [source.id for source in repository.list()] == ["default_local", "nas-1"]

    # Duplicate name is the owner's conflict error, not a raw driver exception.
    with pytest.raises(StorageSourceConflictError):
        repository.create({"id": "nas-2", "name": "NAS", "type": "remote"})

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

    health = repository.record_health("nas-1", ok=True, message="连接正常 api_key=sk-live-secret")
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
            "name": "对象存储",
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
