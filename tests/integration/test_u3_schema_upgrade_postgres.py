"""U3 shadow schema: authentic v1/v2 -> v3 upgrades and checksum contracts."""
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
    _SCHEMA_V2,
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


def _exec(cursor, script: str) -> None:
    for part in [piece for piece in script.split(";") if piece.strip()]:
        cursor.execute(part)


def _seed(cursor) -> None:
    """Data every historical version must preserve across the upgrade."""
    cursor.execute(
        f"INSERT INTO {SCHEMA_NAME}.material(project_id,id,filename,payload) "
        "VALUES ('p1','m-old','old.jpg','{}'::jsonb)"
    )
    cursor.execute(
        f"INSERT INTO {SCHEMA_NAME}.material_label(project_id,material_id,label_code,box_count) "
        "VALUES ('p1','m-old','fire',2)"
    )
    cursor.execute(
        f"INSERT INTO {SCHEMA_NAME}.annotation(project_id,image_id,annotation_state,version,"
        "content_digest,boxes,scope) VALUES ('p1','m-old','annotated',4,'digest','[]'::jsonb,'[]'::jsonb)"
    )
    cursor.execute(
        f"INSERT INTO {SCHEMA_NAME}.negative_pool_category(project_id,id,name,enabled) "
        "VALUES ('p1','cat-1','FIRE',1)"
    )
    cursor.execute(
        f"INSERT INTO {SCHEMA_NAME}.negative_pool_member(project_id,material_id,joined_at) "
        "VALUES ('p1','m-old','2026-01-01')"
    )
    cursor.execute(
        f"INSERT INTO {SCHEMA_NAME}.negative_pool_link(project_id,material_id,category_id) "
        "VALUES ('p1','m-old','cat-1')"
    )


def _build(connection, schema: str, versions: tuple[int, ...]) -> None:
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.execute(f"DROP SCHEMA IF EXISTS {SCHEMA_NAME} CASCADE")
            _exec(cursor, schema)
            for version in versions:
                cursor.execute(
                    f"INSERT INTO {SCHEMA_NAME}.schema_migration(version,name,checksum,applied_by) "
                    "VALUES (%s,%s,%s,'test')",
                    (version, f"u3-material-gt-v{version}", schema_checksum_for(version)),
                )
            _seed(cursor)


def _assert_upgraded(connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT version,checksum FROM {SCHEMA_NAME}.schema_migration ORDER BY version"
        )
        rows = cursor.fetchall()
        assert [int(row[0]) for row in rows] == [1, 2, 3]
        for version, checksum in rows:
            assert str(checksum) == schema_checksum_for(int(version))
        # All historical data survives.
        cursor.execute(f"SELECT id,filename FROM {SCHEMA_NAME}.material WHERE project_id='p1'")
        assert cursor.fetchone() == ("m-old", "old.jpg")
        cursor.execute(f"SELECT label_code,box_count FROM {SCHEMA_NAME}.material_label WHERE project_id='p1'")
        assert cursor.fetchone() == ("fire", 2)
        cursor.execute(f"SELECT version FROM {SCHEMA_NAME}.annotation WHERE project_id='p1'")
        assert cursor.fetchone() == (4,)
        cursor.execute(f"SELECT count(*) FROM {SCHEMA_NAME}.negative_pool_link WHERE project_id='p1'")
        assert cursor.fetchone()[0] == 1
        # v3 uniqueness uses the locale-independent ASCII fold.
        cursor.execute(
            "SELECT indexdef FROM pg_indexes WHERE schemaname=%s "
            "AND indexname='uq_negative_pool_category_name'",
            (SCHEMA_NAME,),
        )
        indexdef = str(cursor.fetchone()[0])
        assert "COLLATE \"C\"" in indexdef and "lower(" in indexdef, indexdef
        # ASCII case conflict is rejected.
        with pytest.raises(Exception):
            with connection.transaction():
                with connection.cursor() as inner:
                    inner.execute(
                        f"INSERT INTO {SCHEMA_NAME}.negative_pool_category"
                        "(project_id,id,name,enabled) VALUES ('p1','cat-2','fire',1)"
                    )
        # Non-ASCII case is NOT folded, exactly like SQLite COLLATE NOCASE.
        with connection.transaction():
            with connection.cursor() as inner:
                inner.execute(
                    f"INSERT INTO {SCHEMA_NAME}.negative_pool_category"
                    "(project_id,id,name,enabled) VALUES ('p1','cat-3',%s,1),"
                    "('p1','cat-4',%s,1)",
                    ("\u00c4", "\u00e4"),
                )


def test_v1_upgrades_to_v3(pg):
    with psycopg.connect(pg.get_uri()) as connection:
        _build(connection, _SCHEMA_V1, (1,))
        assert ensure_schema(connection)["version"] == SCHEMA_VERSION
        _assert_upgraded(connection)


def test_real_v2_upgrades_to_v3(pg):
    with psycopg.connect(pg.get_uri()) as connection:
        _build(connection, _SCHEMA_V2, (1, 2))
        assert ensure_schema(connection)["version"] == SCHEMA_VERSION
        _assert_upgraded(connection)


def test_tampered_or_unknown_versions_are_refused(pg):
    for version in (1, 2, 3):
        with psycopg.connect(pg.get_uri()) as connection:
            _build(connection, _SCHEMA_V1, (1,))
            ensure_schema(connection)
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"UPDATE {SCHEMA_NAME}.schema_migration SET checksum=%s WHERE version=%s",
                        ("0" * 64, version),
                    )
            with pytest.raises(U3MigrationError) as tampered:
                ensure_schema(connection)
            assert tampered.value.code == "U3_SCHEMA_CHECKSUM_MISMATCH"

    with psycopg.connect(pg.get_uri()) as connection:
        _build(connection, _SCHEMA_V1, (1,))
        ensure_schema(connection)
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    f"INSERT INTO {SCHEMA_NAME}.schema_migration"
                    "(version,name,checksum,applied_by) VALUES (99,'future',%s,'test')",
                    ("1" * 64,),
                )
        with pytest.raises(U3MigrationError) as newer:
            ensure_schema(connection)
        assert newer.value.code == "U3_SCHEMA_NEWER_THAN_TOOL"
