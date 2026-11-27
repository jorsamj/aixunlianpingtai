"""U3 shadow migration against a real PostgreSQL (isolated; never production)."""
from __future__ import annotations

import json
import pathlib
import sqlite3
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
_EXTERNAL_DSN_ENV = "MC_TEST_POSTGRES_DSN"

from platform_core.material_repository import MaterialRepository
from platform_core.u3_shadow import (
    SCHEMA_NAME,
    export_project_snapshot,
    import_project_snapshot,
    read_target_snapshot,
    reconcile,
)
from platform_core.u3_shadow import schema_checksum  # noqa: E402


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
    root = pathlib.Path(tempfile.mkdtemp(prefix="pgw3-")) / "data"
    server = pgserver.get_server(root, cleanup_mode="delete")
    yield server
    server.cleanup()


_ANNOTATION_DDL = """
CREATE TABLE IF NOT EXISTS annotations (
    image_id TEXT PRIMARY KEY,
    annotation_state TEXT NOT NULL CHECK(annotation_state IN ('unannotated','annotated','confirmed_empty')),
    version INTEGER NOT NULL, content_digest TEXT NOT NULL, boxes_json TEXT NOT NULL,
    scope_json TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS annotation_label_references (
    image_id TEXT NOT NULL, label_code TEXT NOT NULL, source_kind TEXT NOT NULL DEFAULT 'gt',
    updated_at TEXT NOT NULL, PRIMARY KEY(image_id,label_code));
CREATE TABLE IF NOT EXISTS annotation_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT OR IGNORE INTO annotation_meta VALUES ('revision','0');
"""
_POOL_DDL = """
CREATE TABLE IF NOT EXISTS negative_pool_members (
    material_id TEXT PRIMARY KEY REFERENCES materials(id) ON DELETE CASCADE, joined_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS negative_pool_categories (
    id TEXT PRIMARY KEY, name TEXT NOT NULL COLLATE NOCASE UNIQUE, enabled INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS negative_pool_links (
    material_id TEXT NOT NULL REFERENCES negative_pool_members(material_id) ON DELETE CASCADE,
    category_id TEXT NOT NULL REFERENCES negative_pool_categories(id) ON DELETE CASCADE,
    PRIMARY KEY(material_id,category_id));
CREATE TABLE IF NOT EXISTS negative_pool_algorithm_members (
    algorithm_id TEXT NOT NULL,
    material_id TEXT NOT NULL REFERENCES negative_pool_members(material_id) ON DELETE CASCADE,
    joined_at TEXT NOT NULL, PRIMARY KEY(algorithm_id,material_id));
CREATE TABLE IF NOT EXISTS negative_pool_meta (id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL);
INSERT OR IGNORE INTO negative_pool_meta VALUES (1,0);
"""


def _fixture(tmp_path, project_id="p1"):
    project = tmp_path / "projects" / project_id
    project.mkdir(parents=True)
    materials = MaterialRepository(project)
    for index, name in ((1, "fire"), (2, "smoke"), (3, "negative")):
        materials.upsert({
            "id": f"m{index}", "filename": f"{name}.jpg",
            "storage_source_id": "default_local", "object_key": f"uploads/{name}.jpg",
            "content_sha256": f"{index:064x}", "size_bytes": 10 + index,
            "processing_status": "ready", "annotated": index != 3, "box_count": 1 if index != 3 else 0,
            "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00",
        })
    with sqlite3.connect(materials.path) as database:
        database.executescript(_POOL_DDL)
        database.execute("INSERT INTO negative_pool_categories VALUES ('cat-fire','火焰',1)")
        database.execute("INSERT INTO negative_pool_members VALUES ('m3','2026-01-02T00:00:00+00:00')")
        database.execute("INSERT INTO negative_pool_links VALUES ('m3','cat-fire')")
        database.execute("INSERT INTO negative_pool_algorithm_members VALUES ('algo-1','m3','2026-01-02T00:00:00+00:00')")
        database.execute("INSERT INTO material_labels VALUES ('m1','fire',1)")
        database.execute("INSERT INTO material_annotation_scopes VALUES ('m1','fire')")
        database.execute("UPDATE material_meta SET value='7' WHERE key='revision'")
    with sqlite3.connect(project / "annotations.sqlite3") as database:
        database.executescript(_ANNOTATION_DDL)
        database.execute(
            "INSERT INTO annotations VALUES ('m1','annotated',3,'digest-a',?,?,'2026-01-01T00:00:00+00:00','2026-01-01T00:00:00+00:00')",
            (json.dumps([{"label": "fire", "bbox": [1, 2, 3, 4]}]), json.dumps(["fire"])),
        )
        database.execute("INSERT INTO annotation_label_references VALUES ('m1','fire','gt','2026-01-01T00:00:00+00:00')")
        database.execute("UPDATE annotation_meta SET value='4' WHERE key='revision'")
    return project


def _clear(connection):
    with connection.cursor() as cursor:
        for table in ("negative_pool_algorithm_member", "negative_pool_link", "negative_pool_member",
                      "negative_pool_category", "annotation_label_reference", "annotation",
                      "material_annotation_scope", "material_label", "material", "store_revision"):
            cursor.execute(f"DELETE FROM {SCHEMA_NAME}.{table}")
    connection.commit()


def test_shadow_export_import_reconcile(pg, tmp_path):
    project = _fixture(tmp_path)
    first = export_project_snapshot(project, "p1")
    second = export_project_snapshot(project, "p1")
    assert first == second  # deterministic
    assert first["counts"]["materials.materials"] == 3
    assert first["counts"]["annotations.annotations"] == 1
    assert first["revisions"] == {"materials": 7, "annotations": 4, "negative_pool": 0}

    with psycopg.connect(pg.get_uri()) as connection:
        from platform_core.u3_shadow import ensure_schema

        ensure_schema(connection)
        _clear(connection)
        counters = import_project_snapshot(connection, first)
        assert counters["materials"] == 3 and counters["annotations"] == 1
        target = read_target_snapshot(connection, "p1")
    report = reconcile(first, target)
    assert report["same"] is True, report
    assert report["checks"]["integrity"]["pool_member_without_material"] == []

    # Replay is a no-op: the same snapshot reconciles again and changes nothing.
    with psycopg.connect(pg.get_uri()) as connection:
        import_project_snapshot(connection, first)
        assert reconcile(first, read_target_snapshot(connection, "p1"))["same"] is True

    # A source change is reported instead of silently accepted.
    materials = MaterialRepository(project)
    materials.upsert({**materials.get("m2"), "filename": "smoke-renamed.jpg"})
    changed = export_project_snapshot(project, "p1")
    with psycopg.connect(pg.get_uri()) as connection:
        stale = reconcile(changed, read_target_snapshot(connection, "p1"))
        assert stale["verdict"] == "MISMATCH"
        assert "table_mismatch:materials.materials" in stale["blocking_findings"]
        import_project_snapshot(connection, changed)
        assert reconcile(changed, read_target_snapshot(connection, "p1"))["same"] is True

    # The negative-pool FK cascade is real on the PostgreSQL side.
    with psycopg.connect(pg.get_uri()) as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(f"DELETE FROM {SCHEMA_NAME}.material WHERE project_id='p1' AND id='m3'")
        with connection.cursor() as cursor:
            cursor.execute(f"SELECT count(*) FROM {SCHEMA_NAME}.negative_pool_member WHERE project_id='p1'")
            assert cursor.fetchone()[0] == 0
            cursor.execute(f"SELECT count(*) FROM {SCHEMA_NAME}.negative_pool_link WHERE project_id='p1'")
            assert cursor.fetchone()[0] == 0


def test_import_rolls_back_completely_on_an_integrity_failure(pg, tmp_path):
    project = _fixture(tmp_path, project_id="p2")
    snapshot = export_project_snapshot(project, "p2")
    # A pool member whose material does not exist must fail the whole import.
    broken = json.loads(json.dumps(snapshot))
    broken["stores"]["materials"]["negative_pool_members"].append(
        {"material_id": "ghost", "joined_at": "2026-01-01T00:00:00+00:00"}
    )
    with psycopg.connect(pg.get_uri()) as connection:
        with pytest.raises(Exception) as failure:
            import_project_snapshot(connection, broken)
        assert "foreign key" in str(failure.value).lower() or "violates" in str(failure.value).lower()
        target = read_target_snapshot(connection, "p2")
    assert target["counts"]["materials.materials"] == 0
    assert target["counts"]["materials.negative_pool_members"] == 0
    # The valid snapshot still imports afterwards.
    with psycopg.connect(pg.get_uri()) as connection:
        import_project_snapshot(connection, snapshot)
        assert reconcile(snapshot, read_target_snapshot(connection, "p2"))["same"] is True


def test_schema_checksum_is_stable():
    assert len(schema_checksum()) == 64 and schema_checksum() == schema_checksum()
