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
    image_id TEXT NOT NULL, label_code TEXT NOT NULL,
    box_count INTEGER NOT NULL DEFAULT 0, scope_ref INTEGER NOT NULL DEFAULT 0,
    annotation_state TEXT NOT NULL, source_kind TEXT NOT NULL,
    PRIMARY KEY(image_id,label_code));
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
        database.execute(
            "INSERT INTO annotation_label_references VALUES "
            "('m1','fire',1,0,'annotated','sqlite')"
        )
        database.execute("UPDATE annotation_meta SET value='4' WHERE key='revision'")
        database.execute("PRAGMA user_version=3")
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


def test_full_snapshot_reflects_source_deletions(pg, tmp_path):
    """A full import must delete rows the source removed, for this project only."""
    project = _fixture(tmp_path, project_id="p3")
    snapshot = export_project_snapshot(project, "p3")
    with psycopg.connect(pg.get_uri()) as connection:
        import_project_snapshot(connection, snapshot)
        assert reconcile(snapshot, read_target_snapshot(connection, "p3"))["same"] is True

    # Remove a category link, the category, a pool member and an annotation.
    with sqlite3.connect(project / "materials.sqlite3") as database:
        database.execute("DELETE FROM negative_pool_links WHERE material_id='m3'")
        database.execute("DELETE FROM negative_pool_algorithm_members WHERE material_id='m3'")
        database.execute("DELETE FROM negative_pool_members WHERE material_id='m3'")
        database.execute("DELETE FROM negative_pool_categories WHERE id='cat-fire'")
        database.execute("DELETE FROM material_labels WHERE material_id='m1'")
    with sqlite3.connect(project / "annotations.sqlite3") as database:
        database.execute("DELETE FROM annotation_label_references WHERE image_id='m1'")

    changed = export_project_snapshot(project, "p3")
    with psycopg.connect(pg.get_uri()) as connection:
        import_project_snapshot(connection, changed)
        target = read_target_snapshot(connection, "p3")
        assert reconcile(changed, target)["same"] is True, reconcile(changed, target)
        with connection.cursor() as cursor:
            for table in ("negative_pool_link", "negative_pool_algorithm_member",
                          "negative_pool_member", "negative_pool_category",
                          "material_label", "annotation_label_reference"):
                cursor.execute(f"SELECT count(*) FROM {SCHEMA_NAME}.{table} WHERE project_id='p3'")
                assert cursor.fetchone()[0] == 0, table
    # Other projects are untouched by a project-scoped full import.
    with psycopg.connect(pg.get_uri()) as verifier:
        assert read_target_snapshot(verifier, "p2")["counts"]["materials.materials"] == 3


def test_schema_checksum_is_stable():
    assert len(schema_checksum()) == 64 and schema_checksum() == schema_checksum()

# ---------------------------------------------------------------------------
# Evidence identity, pool constraints, owner field contract, snapshot isolation
# ---------------------------------------------------------------------------
def _seed_evidence(project):
    with sqlite3.connect(project / "materials.sqlite3") as database:
        database.executescript("""
        CREATE TABLE IF NOT EXISTS material_storage_audit (
            task_id TEXT NOT NULL, image_id TEXT NOT NULL, action TEXT NOT NULL,
            old_sha256 TEXT NOT NULL, new_sha256 TEXT NOT NULL, recorded_at TEXT NOT NULL,
            PRIMARY KEY(task_id,image_id));
        CREATE TABLE IF NOT EXISTS material_retirements (
            task_id TEXT NOT NULL, image_id TEXT NOT NULL, actor_id TEXT NOT NULL,
            storage_source_id TEXT NOT NULL, object_key TEXT NOT NULL,
            content_sha256 TEXT NOT NULL, payload_json TEXT NOT NULL,
            annotation_json TEXT NOT NULL, retired_at TEXT NOT NULL,
            reclamation_state TEXT NOT NULL DEFAULT 'DEFERRED_SAFETY_UNVERIFIED',
            reclaimed_bytes INTEGER NOT NULL DEFAULT 0 CHECK(reclaimed_bytes=0),
            PRIMARY KEY(task_id,image_id));
        """)
        # Two rows with the same payload but different keys must stay distinct.
        for image_id in ("m1", "m2"):
            database.execute(
                "INSERT INTO material_storage_audit VALUES ('t1',?,'move','a','b','2026-01-01')",
                (image_id,),
            )
        for image_id in ("m1", "m2", "m3"):
            database.execute(
                "INSERT INTO material_retirements VALUES "
                "('t1',?,'actor','default_local','uploads/x.jpg','a','{}','{}','2026-01-01',"
                "'DEFERRED_SAFETY_UNVERIFIED',0)",
                (image_id,),
            )
    with sqlite3.connect(project / "annotations.sqlite3") as database:
        database.executescript("""
        CREATE TABLE IF NOT EXISTS annotation_delete_backup (
            token TEXT NOT NULL, image_id TEXT NOT NULL, annotation_state TEXT NOT NULL,
            version INTEGER NOT NULL, content_digest TEXT NOT NULL, boxes_json TEXT NOT NULL,
            scope_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            PRIMARY KEY(token, image_id));
        CREATE TABLE IF NOT EXISTS task_negative_confirmations (
            receipt_id TEXT PRIMARY KEY, context_key TEXT NOT NULL, evidence_json TEXT NOT NULL);
        """)
        for token in ("tok-a", "tok-b"):
            database.execute(
                "INSERT INTO annotation_delete_backup VALUES "
                "(?,'m1','annotated',1,'d','[]','[]','2026-01-01','2026-01-01')",
                (token,),
            )
        for receipt in ("r1", "r2", "r3"):
            database.execute(
                "INSERT INTO task_negative_confirmations VALUES (?, 'ctx', '{\"ok\":true}')",
                (receipt,),
            )


def test_evidence_tables_import_independently_and_survive_partial_deletes(pg, tmp_path):
    target = _fixture(tmp_path / "target", project_id="p4")
    _seed_evidence(target)
    control = _fixture(tmp_path / "control", project_id="p4b")
    _seed_evidence(control)
    first = export_project_snapshot(target, "p4")
    other = export_project_snapshot(control, "p4b")
    assert first["counts"]["materials.evidence.material_storage_audit"] == 2
    assert first["counts"]["materials.evidence.material_retirements"] == 3
    assert first["counts"]["annotations.evidence.annotation_delete_backup"] == 2
    assert first["counts"]["annotations.evidence.task_negative_confirmations"] == 3

    with psycopg.connect(pg.get_uri()) as connection:
        import_project_snapshot(connection, first)
        import_project_snapshot(connection, other)
        assert reconcile(first, read_target_snapshot(connection, "p4"))["same"] is True
        assert reconcile(other, read_target_snapshot(connection, "p4b"))["same"] is True

    # Delete one audit row and one negative confirmation; everything else stays.
    with sqlite3.connect(target / "materials.sqlite3") as database:
        database.execute("DELETE FROM material_storage_audit WHERE image_id='m2'")
    with sqlite3.connect(target / "annotations.sqlite3") as database:
        database.execute("DELETE FROM task_negative_confirmations WHERE receipt_id='r2'")
    changed = export_project_snapshot(target, "p4")
    with psycopg.connect(pg.get_uri()) as connection:
        import_project_snapshot(connection, changed)
        snapshot = read_target_snapshot(connection, "p4")
        assert snapshot["counts"]["materials.evidence.material_storage_audit"] == 1
        assert snapshot["counts"]["materials.evidence.material_retirements"] == 3
        assert snapshot["counts"]["annotations.evidence.task_negative_confirmations"] == 2
        assert snapshot["counts"]["annotations.evidence.annotation_delete_backup"] == 2
        assert reconcile(changed, snapshot)["same"] is True, reconcile(changed, snapshot)
        # The untouched project keeps every evidence row.
        control_snapshot = read_target_snapshot(connection, "p4b")
        assert control_snapshot["counts"]["materials.evidence.material_storage_audit"] == 2
        assert reconcile(other, control_snapshot)["same"] is True

    # Replaying the same snapshot is idempotent.
    with psycopg.connect(pg.get_uri()) as connection:
        import_project_snapshot(connection, changed)
        assert reconcile(changed, read_target_snapshot(connection, "p4"))["same"] is True


def test_pool_constraints_match_the_sqlite_contract(pg, tmp_path):
    project = _fixture(tmp_path, project_id="p5")
    snapshot = export_project_snapshot(project, "p5")
    with psycopg.connect(pg.get_uri()) as connection:
        import_project_snapshot(connection, snapshot)
        with pytest.raises(Exception) as duplicate:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"INSERT INTO {SCHEMA_NAME}.negative_pool_category"
                        "(project_id,id,name,enabled) VALUES ('p5','cat-other','火焰',1)"
                    )
        assert "unique" in str(duplicate.value).lower() or "duplicate" in str(duplicate.value).lower()

        # Deleting the category cascades its links.
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    f"DELETE FROM {SCHEMA_NAME}.negative_pool_category WHERE project_id='p5' AND id='cat-fire'"
                )
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT count(*) FROM {SCHEMA_NAME}.negative_pool_link WHERE project_id='p5'"
            )
            assert cursor.fetchone()[0] == 0
        # The member row itself is independent of the category.
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT count(*) FROM {SCHEMA_NAME}.negative_pool_member WHERE project_id='p5'"
            )
            assert cursor.fetchone()[0] == 1

        # Deleting the material cascades member, link and algorithm membership.
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    f"INSERT INTO {SCHEMA_NAME}.negative_pool_category"
                    "(project_id,id,name,enabled) VALUES ('p5','cat-2','其他',1)"
                )
                cursor.execute(
                    f"INSERT INTO {SCHEMA_NAME}.negative_pool_link"
                    "(project_id,material_id,category_id) VALUES ('p5','m3','cat-2')"
                )
                cursor.execute(
                    f"DELETE FROM {SCHEMA_NAME}.material WHERE project_id='p5' AND id='m3'"
                )
        with connection.cursor() as cursor:
            for table in ("negative_pool_member", "negative_pool_link",
                          "negative_pool_algorithm_member"):
                cursor.execute(f"SELECT count(*) FROM {SCHEMA_NAME}.{table} WHERE project_id='p5'")
                assert cursor.fetchone()[0] == 0, table


def test_owner_missing_required_fields_is_refused(tmp_path):
    from platform_core.u3_shadow import U3MigrationError

    def materials_owner(project):
        project.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(project / "materials.sqlite3") as database:
            database.executescript("""
            CREATE TABLE material_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO material_meta VALUES ('revision','1');
            CREATE TABLE negative_pool_meta (id INTEGER PRIMARY KEY, revision INTEGER NOT NULL);
            INSERT INTO negative_pool_meta VALUES (1,0);
            """)
            database.execute("PRAGMA user_version=8")
        return project

    cases = {}
    broken = materials_owner(tmp_path / "no-id")
    with sqlite3.connect(broken / "materials.sqlite3") as database:
        database.execute(
            "CREATE TABLE materials (storage_source_id TEXT, object_key TEXT, "
            "content_sha256 TEXT, payload_json TEXT)"
        )
    cases["materials missing id"] = broken

    for name, project in (("annotations missing image_id", tmp_path / "ann"),
                          ("label references missing label_code", tmp_path / "refs")):
        MaterialRepository(project).upsert({"id": "m1", "object_key": "uploads/m1.jpg"})
        with sqlite3.connect(project / "annotations.sqlite3") as database:
            database.execute("CREATE TABLE annotation_meta (key TEXT PRIMARY KEY, value TEXT)")
            database.execute("INSERT INTO annotation_meta VALUES ('revision','1')")
            database.execute("CREATE TABLE annotation_label_references (image_id TEXT, label_code TEXT)")
            database.execute(
                "CREATE TABLE annotations (image_id TEXT PRIMARY KEY, annotation_state TEXT, "
                "version INTEGER, content_digest TEXT, boxes_json TEXT)"
            )
            database.execute("PRAGMA user_version=3")
        cases[name] = project

    labels = tmp_path / "labels"
    MaterialRepository(labels).upsert({"id": "m1", "object_key": "uploads/m1.jpg"})
    with sqlite3.connect(labels / "materials.sqlite3") as database:
        database.execute("DROP TABLE material_labels")
        database.execute("CREATE TABLE material_labels (label_code TEXT, box_count INTEGER)")
    with sqlite3.connect(labels / "annotations.sqlite3") as database:
        database.execute("CREATE TABLE annotation_meta (key TEXT PRIMARY KEY, value TEXT)")
        database.execute("INSERT INTO annotation_meta VALUES ('revision','1')")
        database.execute(
            "CREATE TABLE annotations (image_id TEXT PRIMARY KEY, annotation_state TEXT, "
            "version INTEGER, content_digest TEXT, boxes_json TEXT)"
        )
        database.execute(
            "CREATE TABLE annotation_label_references (image_id TEXT, label_code TEXT, "
            "box_count INTEGER, scope_ref INTEGER, annotation_state TEXT, source_kind TEXT, "
            "PRIMARY KEY(image_id,label_code))"
        )
        database.execute("PRAGMA user_version=3")
    cases["material_labels missing material_id"] = labels

    for name, project in cases.items():
        with pytest.raises(U3MigrationError) as failure:
            export_project_snapshot(project, project.name)
        assert failure.value.code in {"U3_OWNER_INCOMPLETE", "U3_SCHEMA_VERSION_UNSUPPORTED"}, name


def test_target_snapshot_is_one_repeatable_read(pg, tmp_path):
    project = _fixture(tmp_path, project_id="p6")
    snapshot = export_project_snapshot(project, "p6")
    with psycopg.connect(pg.get_uri()) as connection:
        import_project_snapshot(connection, snapshot)

    class _HookCursor:
        def __init__(self, cursor, hook):
            self._cursor, self._hook = cursor, hook

        def __getattr__(self, name):
            return getattr(self._cursor, name)

        def __enter__(self):
            self._cursor.__enter__()
            return self

        def __exit__(self, *exc):
            return self._cursor.__exit__(*exc)

        def fetchall(self):
            rows = self._cursor.fetchall()
            self._hook()
            return rows

    class _HookConnection:
        def __init__(self, connection, hook):
            self._connection, self._hook = connection, hook

        def __getattr__(self, name):
            return getattr(self._connection, name)

        def cursor(self, **kwargs):
            return _HookCursor(self._connection.cursor(**kwargs), self._hook)

    changed = {"done": False}

    def concurrent_commit():
        if changed["done"]:
            return
        changed["done"] = True
        with psycopg.connect(pg.get_uri()) as other:
            with other.transaction():
                with other.cursor() as cursor:
                    cursor.execute(
                        f"INSERT INTO {SCHEMA_NAME}.material_label(project_id,material_id,label_code,box_count) "
                        "VALUES ('p6','m2','concurrent',99)"
                    )

    with psycopg.connect(pg.get_uri()) as connection:
        hooked = _HookConnection(connection, concurrent_commit)
        snapshot_view = read_target_snapshot(hooked, "p6")
        assert snapshot_view["snapshot"]["isolation"] == "REPEATABLE READ"
        assert snapshot_view["snapshot"]["identity"]
        assert changed["done"] is True
        # The concurrently committed label must not appear in this snapshot, even
        # though it was committed before the later tables were read.
        labels = snapshot_view["stores"]["materials"]["material_labels"]
        assert not any(row.get("label_code") == "concurrent" for row in labels)
    with psycopg.connect(pg.get_uri()) as connection:
        fresh = read_target_snapshot(connection, "p6")
        assert any(
            row.get("label_code") == "concurrent"
            for row in fresh["stores"]["materials"]["material_labels"]
        )
        with pytest.raises(Exception) as busy:
            with connection.transaction():
                read_target_snapshot(connection, "p6")
        assert "idle" in str(busy.value).lower()
