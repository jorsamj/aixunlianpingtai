"""U3 shadow schema: real v1 -> v2 upgrade and checksum tamper refusal."""
from __future__ import annotations

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
            raise RuntimeError(f"MC_REQUIRE_POSTGRES=1 but {module_name} is unavailable: {reason}")
        pytest.skip(reason, allow_module_level=True)


psycopg = _require_or_skip("psycopg", "psycopg 3 is required for PostgreSQL contracts")

from platform_core.u3_shadow import (
    SCHEMA_NAME,
    SCHEMA_VERSION,
    U3MigrationError,
    _SCHEMA_V1,
    ensure_schema,
    schema_checksum,
    schema_checksum_for,
)


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

    external = os.environ.get("MC_TEST_POSTGRES_DSN", "").strip()
    if external:
        server = _ExternalPostgres(external)
        yield server
        server.cleanup()
        return
    pgserver = _require_or_skip("pgserver", "an isolated local PostgreSQL server is required")
    root = pathlib.Path(tempfile.mkdtemp(prefix="pgw3up-")) / "data"
    server = pgserver.get_server(root, cleanup_mode="delete")
    yield server
    server.cleanup()


def _exec(database, script: str) -> None:
    for part in [piece for piece in script.split(";") if piece.strip()]:
        database.execute(part)


def _build_v1(connection) -> None:
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.execute(f"DROP SCHEMA IF EXISTS {SCHEMA_NAME} CASCADE")
            for part in [piece for piece in _SCHEMA_V1.split(";") if piece.strip()]:
                cursor.execute(part)
            cursor.execute(
                f"INSERT INTO {SCHEMA_NAME}.schema_migration(version,name,checksum,applied_by) "
                "VALUES (1,'u3-material-gt-v1',%s,'test')",
                (schema_checksum_for(1),),
            )
            cursor.execute(
                f"INSERT INTO {SCHEMA_NAME}.material(project_id,id,filename,payload) "
                "VALUES ('p1','m-old','old.jpg','{}'::jsonb)"
            )


def test_v1_upgrades_to_v2_and_preserves_data(pg):
    with psycopg.connect(pg.get_uri()) as connection:
        _build_v1(connection)
        result = ensure_schema(connection)
        assert result["version"] == SCHEMA_VERSION
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT version,checksum FROM {SCHEMA_NAME}.schema_migration ORDER BY version"
            )
            rows = cursor.fetchall()
            assert [int(row[0]) for row in rows] == [1, 2]
            assert str(rows[1][1]) == schema_checksum()
            cursor.execute(
                f"SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema=%s AND table_name IN ('evidence_row','table_state')",
                (SCHEMA_NAME,),
            )
            assert cursor.fetchone()[0] == 2
            cursor.execute(
                "SELECT count(*) FROM information_schema.columns WHERE table_schema=%s "
                "AND table_name='annotation_label_reference' "
                "AND column_name IN ('box_count','scope_ref','annotation_state','source_kind')",
                (SCHEMA_NAME,),
            )
            assert cursor.fetchone()[0] == 4
            cursor.execute(
                "SELECT count(*) FROM pg_indexes WHERE schemaname=%s "
                "AND indexname='uq_negative_pool_category_name'",
                (SCHEMA_NAME,),
            )
            assert cursor.fetchone()[0] == 1
            cursor.execute(f"SELECT id,filename FROM {SCHEMA_NAME}.material WHERE project_id='p1'")
            assert cursor.fetchone() == ("m-old", "old.jpg")


def test_tampered_or_unknown_versions_are_refused(pg):
    with psycopg.connect(pg.get_uri()) as connection:
        _build_v1(connection)
        ensure_schema(connection)
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    f"UPDATE {SCHEMA_NAME}.schema_migration SET checksum=%s WHERE version=2",
                    ("0" * 64,),
                )
        with pytest.raises(U3MigrationError) as tampered:
            ensure_schema(connection)
        assert tampered.value.code == "U3_SCHEMA_CHECKSUM_MISMATCH"

        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    f"INSERT INTO {SCHEMA_NAME}.schema_migration(version,name,checksum,applied_by) "
                    "VALUES (99,'future',%s,'test')",
                    ("1" * 64,),
                )
        with pytest.raises(U3MigrationError) as newer:
            ensure_schema(connection)
        assert newer.value.code == "U3_SCHEMA_NEWER_THAN_TOOL"

        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    f"DELETE FROM {SCHEMA_NAME}.schema_migration WHERE version=99"
                )
                cursor.execute(
                    f"UPDATE {SCHEMA_NAME}.schema_migration SET checksum=%s WHERE version=1",
                    ("f" * 64,),
                )
        with pytest.raises(U3MigrationError) as historical:
            ensure_schema(connection)
        assert historical.value.code == "U3_SCHEMA_CHECKSUM_MISMATCH"
