"""U3 shadow migration against a real PostgreSQL (isolated; never production)."""
from __future__ import annotations

import copy
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

from platform_core.annotation_repository import AnnotationRepository
from platform_core.material_repository import MaterialRepository
from platform_core.negative_pool import NegativePool
from platform_core.u3_shadow import (
    _digest,
    _snapshot_identity,
    snapshot_evidence_streams,
    U3MigrationError,
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
    # A real owner database: initializing the repository installs the evidence and
    # confirmation generation triggers that every genuine write path relies on.
    AnnotationRepository(project)
    return project


def _clear(connection):
    from platform_core.u3_incremental_sync import ensure_incremental_schema
    ensure_incremental_schema(connection)
    with connection.cursor() as cursor:
        for table in ("u3_shadow_import", "u3_projection_cursor", "u3_projection_baseline",
                      "picker_snapshot_state", "task_negative_confirmation",
                      "negative_pool_algorithm_member", "negative_pool_link", "negative_pool_member",
                      "negative_pool_category", "annotation_label_reference", "annotation",
                      "material_annotation_scope", "material_label", "material", "store_revision"):
            cursor.execute(f"DELETE FROM {SCHEMA_NAME}.{table}")
    connection.commit()


def _state(connection, project_id):
    # One explicit transaction: an uncommitted implicit read would leave the
    # connection busy for the next REPEATABLE READ snapshot.
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT snapshot_id,content_digest,material_revision,annotation_revision,"
                "negative_pool_revision,negative_confirmation_revision,"
                "negative_confirmation_generation,status "
                f"FROM {SCHEMA_NAME}.picker_snapshot_state WHERE project_id=%s",
                (project_id,),
            )
            return cursor.fetchone()


def _cursors(connection, project_id):
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT store,last_applied_seq,source_revision FROM {SCHEMA_NAME}.u3_projection_cursor "
                "WHERE project_id=%s ORDER BY store",
                (project_id,),
            )
            return cursor.fetchall()


def _ledger(connection, project_id):
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT outcome,error_code,snapshot_digest FROM {SCHEMA_NAME}.u3_shadow_import "
                "WHERE project_id=%s ORDER BY import_id",
                (project_id,),
            )
            return cursor.fetchall()


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
    # A pool member whose material does not exist must fail the whole import. The
    # snapshot is resealed so the failure is the real foreign-key write, not the
    # (separately tested) integrity gate.
    broken = json.loads(json.dumps(snapshot))
    broken["stores"]["materials"]["negative_pool_members"].append(
        {"material_id": "ghost", "joined_at": "2026-01-01T00:00:00+00:00"}
    )
    _reseal(broken)
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

    # Remove a category link, the category, a pool member and an annotation. The
    # owner revisions move with the data: a source row that changed without a new
    # revision is refused by the v4 identity contract.
    with sqlite3.connect(project / "materials.sqlite3") as database:
        database.execute("DELETE FROM negative_pool_links WHERE material_id='m3'")
        database.execute("DELETE FROM negative_pool_algorithm_members WHERE material_id='m3'")
        database.execute("DELETE FROM negative_pool_members WHERE material_id='m3'")
        database.execute("DELETE FROM negative_pool_categories WHERE id='cat-fire'")
        database.execute("DELETE FROM material_labels WHERE material_id='m1'")
        database.execute("UPDATE material_meta SET value='8' WHERE key='revision'")
        database.execute("UPDATE negative_pool_meta SET revision=revision+1 WHERE id=1")
    with sqlite3.connect(project / "annotations.sqlite3") as database:
        database.execute("DELETE FROM annotation_label_references WHERE image_id='m1'")
        database.execute("UPDATE annotation_meta SET value='5' WHERE key='revision'")

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
EVIDENCE_ROWS = {
    "material_storage_audit": 2,
    "material_retirements": 3,
    "material_migrations": 1,
    "material_cleanup_deferred": 2,
    "material_assignment_receipts": 2,
    "negative_pool_operations": 1,
    "annotation_delete_backup": 2,
    "annotation_negative_reviews": 2,
    "annotation_candidate_commits": 2,
    "task_negative_confirmations": 3,
}


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
        CREATE TABLE IF NOT EXISTS material_migrations (
            source TEXT PRIMARY KEY, signature TEXT NOT NULL,
            imported_count INTEGER NOT NULL, imported_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS material_cleanup_deferred (
            cleanup_id TEXT PRIMARY KEY, image_id TEXT NOT NULL, owner TEXT NOT NULL,
            payload_json TEXT NOT NULL, last_error TEXT NOT NULL, recorded_at TEXT NOT NULL,
            reclamation_state TEXT NOT NULL DEFAULT 'DEFERRED_SAFETY_UNVERIFIED');
        CREATE TABLE IF NOT EXISTS material_assignment_receipts (
            task_id TEXT NOT NULL, image_id TEXT NOT NULL, outcome TEXT NOT NULL, error TEXT,
            PRIMARY KEY(task_id,image_id)) WITHOUT ROWID;
        CREATE TABLE IF NOT EXISTS negative_pool_operations (
            operation_id TEXT PRIMARY KEY, identity TEXT NOT NULL, result_json TEXT NOT NULL);
        """)
        # Two rows with the same payload but different keys must stay distinct.
        for image_id in ("m1", "m2"):
            database.execute(
                "INSERT INTO material_storage_audit VALUES ('t1',?,'move','a','b','2026-01-01')",
                (image_id,),
            )
        database.execute(
            "INSERT INTO material_migrations VALUES ('legacy-json','sig',2,'2026-01-01')"
        )
        for cleanup_id in ("c1", "c2"):
            database.execute(
                "INSERT INTO material_cleanup_deferred VALUES (?,?, 'owner','{}','err','2026-01-01',"
                "'DEFERRED_SAFETY_UNVERIFIED')",
                (cleanup_id, "m1"),
            )
        for image_id in ("m1", "m2"):
            database.execute(
                "INSERT INTO material_assignment_receipts VALUES ('t1',?,'APPLIED',NULL)",
                (image_id,),
            )
        database.execute(
            "INSERT INTO negative_pool_operations VALUES ('op-1','identity','{\"ok\":true}')"
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
        database.execute("""
        CREATE TABLE IF NOT EXISTS annotation_candidate_commits (
            task_id TEXT NOT NULL, operation_id TEXT NOT NULL, image_id TEXT NOT NULL,
            receipt_json TEXT NOT NULL, PRIMARY KEY(task_id, image_id))""")
        for image_id in ("m1", "m2"):
            database.execute(
                "INSERT INTO annotation_candidate_commits VALUES ('t1','op1',?,'{}')",
                (image_id,),
            )
        database.execute("""
        CREATE TABLE IF NOT EXISTS annotation_negative_reviews (
            image_id TEXT NOT NULL, source_version INTEGER NOT NULL, actor_id TEXT NOT NULL,
            reviewed_scope_json TEXT NOT NULL, source_content_sha256 TEXT NOT NULL,
            annotation_version INTEGER NOT NULL, annotation_digest TEXT NOT NULL,
            reviewed_at TEXT NOT NULL,
            PRIMARY KEY(image_id,source_version,actor_id,reviewed_scope_json,source_content_sha256))""")
        for version in (1, 2):
            database.execute(
                "INSERT INTO annotation_negative_reviews VALUES "
                "('m1',?,'actor','[\"fire\"]','sha',?,'digest','2026-01-01')",
                (version, version),
            )
    # The owner observes the tables created above (structure certification). The
    # explicit entry is used because the process-level init cache intentionally
    # makes a second construction a no-op.
    MaterialRepository(project).reconcile_evidence_structure()
    # The confirmation table is created lazily by the owner; install its triggers
    # the same way a real write path does (rows above stay at generation 0).
    repository = AnnotationRepository(project)
    with repository._connect() as database:
        with database:
            repository._ensure_generation_objects(database)


def test_evidence_tables_import_independently_and_survive_partial_deletes(pg, tmp_path):
    target = _fixture(tmp_path / "target", project_id="p4")
    _seed_evidence(target)
    control = _fixture(tmp_path / "control", project_id="p4b")
    _seed_evidence(control)
    first = export_project_snapshot(target, "p4")
    other = export_project_snapshot(control, "p4b")
    for table, expected in EVIDENCE_ROWS.items():
        prefix = (
            "annotations.evidence."
            if table in {"annotation_delete_backup", "annotation_negative_reviews",
                         "annotation_candidate_commits", "task_negative_confirmations"}
            else "materials.evidence."
        )
        assert first["counts"][prefix + table] == expected, table
    assert first["table_state"]["materials.material_migrations"]["present"] is True

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
        for table in ("material_retirements", "material_migrations",
                      "material_cleanup_deferred", "material_assignment_receipts",
                      "negative_pool_operations"):
            assert snapshot["counts"]["materials.evidence." + table] == EVIDENCE_ROWS[table], table
        assert snapshot["counts"]["annotations.evidence.task_negative_confirmations"] == 2
        for table in ("annotation_delete_backup", "annotation_negative_reviews",
                      "annotation_candidate_commits"):
            assert snapshot["counts"]["annotations.evidence." + table] == EVIDENCE_ROWS[table], table
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

        # ASCII case folds exactly like SQLite COLLATE NOCASE.
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    f"INSERT INTO {SCHEMA_NAME}.negative_pool_category"
                    "(project_id,id,name,enabled) VALUES ('p5','cat-ascii','FIRE',1)"
                )
        with pytest.raises(Exception) as ascii_case:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"INSERT INTO {SCHEMA_NAME}.negative_pool_category"
                        "(project_id,id,name,enabled) VALUES ('p5','cat-ascii-2','fire',1)"
                    )
        assert "unique" in str(ascii_case.value).lower() or "duplicate" in str(ascii_case.value).lower()
        # Non-ASCII characters are NOT folded (SQLite NOCASE folds ASCII only).
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    f"INSERT INTO {SCHEMA_NAME}.negative_pool_category"
                    "(project_id,id,name,enabled) VALUES ('p5','cat-umlaut-1',%s,1)",
                    ("\u00c4",),
                )
                cursor.execute(
                    f"INSERT INTO {SCHEMA_NAME}.negative_pool_category"
                    "(project_id,id,name,enabled) VALUES ('p5','cat-umlaut-2',%s,1)",
                    ("\u00e4",),
                )

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

def test_evidence_absent_and_empty_tables_are_distinct(pg, tmp_path):
    """An empty source table clears; a missing source table retains."""
    project = _fixture(tmp_path, project_id="p7")
    _seed_evidence(project)
    first = export_project_snapshot(project, "p7")
    with psycopg.connect(pg.get_uri()) as connection:
        import_project_snapshot(connection, first)
        assert reconcile(first, read_target_snapshot(connection, "p7"))["same"] is True

    # (1) Table exists but is empty: the target table must be cleared.
    with sqlite3.connect(project / "materials.sqlite3") as database:
        database.execute("DELETE FROM material_migrations")
    emptied = export_project_snapshot(project, "p7")
    assert emptied["table_state"]["materials.material_migrations"]["present"] is True
    assert emptied["counts"]["materials.evidence.material_migrations"] == 0
    with psycopg.connect(pg.get_uri()) as connection:
        import_project_snapshot(connection, emptied)
        snapshot = read_target_snapshot(connection, "p7")
        assert snapshot["counts"]["materials.evidence.material_migrations"] == 0
        assert reconcile(emptied, snapshot)["same"] is True

    # (2) Table absent: the target keeps the retained history (explicit contract).
    with sqlite3.connect(project / "materials.sqlite3") as database:
        database.execute("DROP TABLE material_cleanup_deferred")
    MaterialRepository(project).reconcile_evidence_structure()
    absent = export_project_snapshot(project, "p7")
    assert absent["table_state"]["materials.material_cleanup_deferred"]["present"] is False
    assert "materials.evidence.material_cleanup_deferred" not in absent["counts"]
    with psycopg.connect(pg.get_uri()) as connection:
        import_project_snapshot(connection, absent)
        snapshot = read_target_snapshot(connection, "p7")
        assert (
            snapshot["counts"]["materials.evidence.material_cleanup_deferred"]
            == EVIDENCE_ROWS["material_cleanup_deferred"]
        )
        report = reconcile(absent, snapshot)
        assert report["same"] is True, report
        assert "materials.evidence.material_cleanup_deferred" in report["retained_target_evidence"]
        # Replay stays idempotent.
        import_project_snapshot(connection, absent)
        assert (
            read_target_snapshot(connection, "p7")["counts"][
                "materials.evidence.material_cleanup_deferred"
            ]
            == EVIDENCE_ROWS["material_cleanup_deferred"]
        )

def test_evidence_metadata_error_fails_closed_instead_of_retaining(tmp_path, monkeypatch):
    """A metadata read failure is not "table absent": the export must refuse."""
    from platform_core import u3_shadow as u3_module

    project = _fixture(tmp_path, project_id="p8")
    _seed_evidence(project)
    real_columns = u3_module._sqlite_columns

    def failing(database, table):
        if table == "material_storage_audit":
            raise sqlite3.OperationalError("database disk image is malformed")
        return real_columns(database, table)

    monkeypatch.setattr(u3_module, "_sqlite_columns", failing)
    with pytest.raises(u3_module.U3MigrationError) as failure:
        u3_module.export_project_snapshot(project, "p8")
    assert failure.value.code == "U3_OWNER_UNREADABLE"
    # Nothing was produced, so no snapshot can later be treated as retained.
    assert not (project / "u3-snapshot.json").exists()

def test_legacy_json_projection_comes_from_the_annotation_owner(pg, tmp_path):
    """The projection is produced by AnnotationRepository, not asserted by hand."""
    project = _fixture(tmp_path, project_id="p9")
    repository = AnnotationRepository(project)
    legacy = project / "annotations"
    legacy.mkdir(parents=True, exist_ok=True)
    (legacy / "m2.json").write_text(
        json.dumps({
            "boxes": [{"label": "fire"}, {"label": "fire"}, {"label": "fire"},
                      {"label": "smoke"}],
            "annotation_state": "annotated",
        }),
        encoding="utf-8",
    )
    (legacy / "m3.json").write_text(json.dumps({}), encoding="utf-8")
    rebuilt = repository.rebuild_reference_index()
    assert rebuilt["legacy_records"] == 2

    snapshot = export_project_snapshot(project, "p9")
    exported = {
        (row["image_id"], row["label_code"]): (
            row["box_count"], row["scope_ref"], row["annotation_state"], row["source_kind"],
        )
        for row in snapshot["stores"]["annotations"]["annotation_label_references"]
    }
    # m1 has a formal annotation (SQLite wins); m2 is legacy JSON with boxes and no
    # explicit scope (owner derives scope from the boxed labels); m3 has no boxes.
    assert exported[("m1", "fire")] == (1, 1, "annotated", "sqlite")
    assert exported[("m2", "fire")] == (3, 1, "annotated", "legacy")
    assert exported[("m2", "smoke")] == (1, 1, "annotated", "legacy")
    assert not any(image == "m3" for image, _ in exported)
    assert all(value[1] in (0, 1) for value in exported.values())

    with psycopg.connect(pg.get_uri()) as connection:
        import_project_snapshot(connection, snapshot)
        target = read_target_snapshot(connection, "p9")
        stored = {
            (row["image_id"], row["label_code"]): (
                row["box_count"], row["scope_ref"], row["annotation_state"],
                row["source_kind"],
            )
            for row in target["stores"]["annotations"]["annotation_label_references"]
        }
        assert stored == exported
        assert target["legacy_reference_pending_import"] is False
        assert reconcile(snapshot, target)["same"] is True

        # A v1-upgraded project is explicitly incomplete until a complete export
        # arrives: reconcile refuses it and an incomplete full import keeps it.
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    f"INSERT INTO {SCHEMA_NAME}.store_revision(project_id,store,revision) "
                    "VALUES ('p9','legacy_reference_pending_import',0) "
                    "ON CONFLICT (project_id,store) DO NOTHING"
                )
        pending = read_target_snapshot(connection, "p9")
        assert pending["legacy_reference_pending_import"] is True
        report = reconcile(snapshot, pending)
        assert report["same"] is False
        assert "legacy_reference_pending_import" in report["blocking_findings"]

        incomplete = dict(snapshot)
        incomplete["table_state"] = {}
        before_refusal = read_target_snapshot(connection, "p9")
        with pytest.raises(U3MigrationError) as refused:
            import_project_snapshot(connection, incomplete, mode="full")
        assert refused.value.code == "U3_PENDING_IMPORT_INCOMPLETE"
        after_refusal = read_target_snapshot(connection, "p9")
        assert after_refusal["stores"] == before_refusal["stores"]
        assert after_refusal["table_state"] == before_refusal["table_state"]
        assert after_refusal["revisions"] == before_refusal["revisions"]
        assert after_refusal["legacy_reference_pending_import"] is True

        cleared = import_project_snapshot(connection, snapshot, mode="full")
        assert cleared["legacy_pending_cleared"] == 1
        final = read_target_snapshot(connection, "p9")
        assert final["legacy_reference_pending_import"] is False
        assert reconcile(snapshot, final)["same"] is True

def _pending_marker(connection, project_id):
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.execute(
                f"INSERT INTO {SCHEMA_NAME}.store_revision(project_id,store,revision) "
                "VALUES (%s,'legacy_reference_pending_import',0) "
                "ON CONFLICT (project_id,store) DO NOTHING",
                (project_id,),
            )


def _recompute_content_digest(snapshot):
    snapshot["content_digest"] = _digest(
        [{"table": name, "digest": value} for name, value in sorted(snapshot["digests"].items())]
    )
    return snapshot


def _reseal(snapshot):
    """Recompute counts/digests/identity, as an honest exporter would.

    Used when a test needs a snapshot that is *self-consistent but invalid* (for
    example a pool member whose material does not exist): the integrity gate must
    pass so the write-level failure being tested is the one that surfaces.
    """
    counts, digests = {}, {}
    for store, tables in snapshot["stores"].items():
        for table, rows in tables.items():
            if table == "evidence":
                for name, items in rows.items():
                    counts[f"{store}.evidence.{name}"] = len(items)
                    digests[f"{store}.evidence.{name}"] = _digest(items)
                continue
            counts[f"{store}.{table}"] = len(rows)
            digests[f"{store}.{table}"] = _digest(rows)
    snapshot["counts"] = counts
    snapshot["digests"] = digests
    snapshot["content_digest"] = _digest(
        [{"table": name, "digest": value} for name, value in sorted(digests.items())]
    )
    declared = snapshot.get("evidence_streams") or {}
    streams = snapshot_evidence_streams(snapshot)
    for name, stream in streams.items():
        stream["generation"] = (declared.get(name) or {}).get("generation", 0)
    snapshot["evidence_streams"] = streams
    snapshot["snapshot_id"] = _snapshot_identity(
        snapshot["project_id"], snapshot["content_digest"], snapshot["revisions"],
        snapshot["evidence_streams"],
    )
    return snapshot


def test_pending_import_refuses_snapshot_missing_an_evidence_table(pg, tmp_path):
    project = _fixture(tmp_path, project_id="p10")
    _seed_evidence(project)
    snapshot = export_project_snapshot(project, "p10")
    with psycopg.connect(pg.get_uri()) as connection:
        import_project_snapshot(connection, snapshot)
        _pending_marker(connection, "p10")
        before = read_target_snapshot(connection, "p10")
        assert before["counts"]["materials.evidence.material_storage_audit"] == 2

        damaged = _recompute_content_digest(copy.deepcopy(snapshot))
        table = "material_storage_audit"
        damaged["stores"]["materials"]["evidence"].pop(table)
        damaged["table_state"].pop(f"materials.{table}")
        damaged["counts"].pop(f"materials.evidence.{table}")
        damaged["digests"].pop(f"materials.evidence.{table}")
        with pytest.raises(U3MigrationError) as refused:
            import_project_snapshot(connection, damaged, mode="full")
        assert refused.value.code == "U3_PENDING_IMPORT_INCOMPLETE"
        after = read_target_snapshot(connection, "p10")
        assert after["stores"] == before["stores"]
        assert after["table_state"] == before["table_state"]
        assert after["revisions"] == before["revisions"]
        assert after["legacy_reference_pending_import"] is True

        # An unknown evidence table is also refused instead of being smuggled in.
        unknown = _recompute_content_digest(copy.deepcopy(snapshot))
        unknown["stores"]["materials"]["evidence"]["material_unknown_table"] = []
        unknown["counts"]["materials.evidence.material_unknown_table"] = 0
        unknown["digests"]["materials.evidence.material_unknown_table"] = _digest([])
        unknown = _recompute_content_digest(unknown)
        with pytest.raises(U3MigrationError) as unknown_refused:
            import_project_snapshot(connection, unknown, mode="full")
        assert unknown_refused.value.code == "U3_PENDING_IMPORT_INCOMPLETE"
        assert "unknown_counts" in unknown_refused.value.detail

        cleared = import_project_snapshot(connection, snapshot, mode="full")
        assert cleared["legacy_pending_cleared"] == 1
        final = read_target_snapshot(connection, "p10")
        assert final["legacy_reference_pending_import"] is False
        assert reconcile(snapshot, final)["same"] is True


def test_pending_import_rejects_a_missing_negative_pool_revision(pg, tmp_path):
    project = _fixture(tmp_path, project_id="p11")
    snapshot = export_project_snapshot(project, "p11")
    with psycopg.connect(pg.get_uri()) as connection:
        import_project_snapshot(connection, snapshot)
        _pending_marker(connection, "p11")
        damaged = copy.deepcopy(snapshot)
        damaged["revisions"].pop("negative_pool")
        damaged = _recompute_content_digest(damaged)
        with pytest.raises(U3MigrationError) as refused:
            import_project_snapshot(connection, damaged, mode="full")
        assert refused.value.code == "U3_PENDING_IMPORT_INCOMPLETE"
        assert "negative_pool" in refused.value.detail
        assert read_target_snapshot(connection, "p11")["legacy_reference_pending_import"] is True


def test_pending_import_keeps_retained_evidence_for_an_absent_source_table(pg, tmp_path):
    project = _fixture(tmp_path, project_id="p12")
    _seed_evidence(project)
    snapshot = export_project_snapshot(project, "p12")
    with psycopg.connect(pg.get_uri()) as connection:
        import_project_snapshot(connection, snapshot)
        _pending_marker(connection, "p12")
    with sqlite3.connect(project / "materials.sqlite3") as database:
        database.execute("DROP TABLE material_cleanup_deferred")
    MaterialRepository(project).reconcile_evidence_structure()
    absent = export_project_snapshot(project, "p12")
    assert absent["table_state"]["materials.material_cleanup_deferred"]["present"] is False
    with psycopg.connect(pg.get_uri()) as connection:
        cleared = import_project_snapshot(connection, absent, mode="full")
        assert cleared["legacy_pending_cleared"] == 1
        final = read_target_snapshot(connection, "p12")
        assert final["legacy_reference_pending_import"] is False
        # The target keeps the historical rows of the missing source table.
        assert final["counts"]["materials.evidence.material_cleanup_deferred"] == 2
        report = reconcile(absent, final)
        assert report["same"] is True
        assert "materials.evidence.material_cleanup_deferred" in report["retained_target_evidence"]

def test_pending_import_rejects_invalid_evidence_state_shapes(pg, tmp_path):
    project = _fixture(tmp_path, project_id="p13")
    _seed_evidence(project)
    snapshot = export_project_snapshot(project, "p13")
    table = "material_storage_audit"
    state_name = f"materials.{table}"
    key = f"materials.evidence.{table}"
    with psycopg.connect(pg.get_uri()) as connection:
        import_project_snapshot(connection, snapshot)
        _pending_marker(connection, "p13")
        before = read_target_snapshot(connection, "p13")

        def damaged():
            return _recompute_content_digest(copy.deepcopy(snapshot))

        variants = {}
        candidate = damaged()
        candidate["table_state"][state_name]["present"] = None
        variants["present_none"] = candidate
        candidate = damaged()
        candidate["table_state"][state_name]["present"] = 1
        variants["present_int"] = candidate
        # An absent table must still carry an integer row_count.
        absent = copy.deepcopy(snapshot)
        absent["stores"]["materials"]["evidence"].pop(table)
        absent["counts"].pop(key)
        absent["digests"].pop(key)
        absent["table_state"][state_name] = {"present": False, "schema_version": 8}
        variants["absent_row_count_missing"] = _recompute_content_digest(absent)
        absent = copy.deepcopy(snapshot)
        absent["stores"]["materials"]["evidence"].pop(table)
        absent["counts"].pop(key)
        absent["digests"].pop(key)
        absent["table_state"][state_name]["present"] = False
        absent["table_state"][state_name]["row_count"] = True
        variants["absent_row_count_bool"] = _recompute_content_digest(absent)
        absent = copy.deepcopy(snapshot)
        absent["stores"]["materials"]["evidence"].pop(table)
        absent["counts"].pop(key)
        absent["digests"].pop(key)
        absent["table_state"][state_name]["present"] = False
        absent["table_state"][state_name]["row_count"] = 1
        variants["absent_row_count_nonzero"] = _recompute_content_digest(absent)
        # Even a None value counts as a fabricated key.
        absent = copy.deepcopy(snapshot)
        absent["stores"]["materials"]["evidence"][table] = None
        absent["counts"].pop(key)
        absent["digests"].pop(key)
        absent["table_state"][state_name] = {"present": False, "schema_version": 8, "row_count": 0}
        variants["absent_evidence_none"] = _recompute_content_digest(absent)
        absent = copy.deepcopy(snapshot)
        absent["stores"]["materials"]["evidence"].pop(table)
        absent["table_state"][state_name] = {"present": False, "schema_version": 8, "row_count": 0}
        variants["absent_counts_key"] = _recompute_content_digest(absent)
        absent = copy.deepcopy(snapshot)
        absent["stores"]["materials"]["evidence"].pop(table)
        absent["table_state"][state_name] = {"present": False, "schema_version": 8, "row_count": 0}
        absent["counts"].pop(key)
        variants["absent_digests_key"] = _recompute_content_digest(absent)
        # Unknown evidence names inside counts/digests are refused as well.
        stray = damaged()
        stray["counts"]["materials.evidence.material_unknown"] = 0
        variants["unknown_counts_key"] = _recompute_content_digest(stray)
        stray = damaged()
        stray["digests"]["materials.evidence.material_unknown"] = _digest([])
        variants["unknown_digests_key"] = _recompute_content_digest(stray)
        # Unknown *store* namespaces are refused in all three places.
        stray = damaged()
        stray["counts"]["other.evidence.unknown_table"] = 0
        variants["unknown_store_counts_key"] = _recompute_content_digest(stray)
        stray = damaged()
        stray["digests"]["other.evidence.unknown_table"] = _digest([])
        variants["unknown_store_digests_key"] = _recompute_content_digest(stray)
        stray = damaged()
        stray["stores"]["other"] = {"evidence": {"unknown_table": []}}
        variants["unknown_store_evidence_data"] = _recompute_content_digest(stray)

        for name, candidate in variants.items():
            with pytest.raises(U3MigrationError) as refused:
                import_project_snapshot(connection, candidate, mode="full")
            assert refused.value.code == "U3_PENDING_IMPORT_INCOMPLETE", name
            after = read_target_snapshot(connection, "p13")
            assert after["stores"] == before["stores"], name
            assert after["table_state"] == before["table_state"], name
            assert after["revisions"] == before["revisions"], name
            assert after["legacy_reference_pending_import"] is True, name

        assert import_project_snapshot(connection, snapshot, mode="full")["legacy_pending_cleared"] == 1

def test_evidence_namespace_is_enforced_for_every_import_mode(pg, tmp_path):
    project = _fixture(tmp_path, project_id="p14")
    _seed_evidence(project)
    snapshot = export_project_snapshot(project, "p14")
    with psycopg.connect(pg.get_uri()) as connection:
        import_project_snapshot(connection, snapshot)

        def with_unknown_store(evidence):
            damaged = copy.deepcopy(snapshot)
            damaged["stores"]["other"] = {"evidence": evidence}
            return _recompute_content_digest(damaged)

        def with_non_dict_store():
            damaged = copy.deepcopy(snapshot)
            damaged["stores"]["other"] = []
            return _recompute_content_digest(damaged)

        cases = (
            ("unknown_store_data", with_unknown_store({"unknown_table": []})),
            ("unknown_store_empty_evidence", with_unknown_store({})),
            ("non_dict_store", with_non_dict_store()),
        )

        # Pending project: every mode is refused before anything is written.
        _pending_marker(connection, "p14")
        baseline = read_target_snapshot(connection, "p14")
        for mode in ("full", "incremental"):
            for name, candidate in cases:
                with pytest.raises(U3MigrationError) as refused:
                    import_project_snapshot(connection, candidate, mode=mode)
                assert refused.value.code == "U3_PENDING_IMPORT_INCOMPLETE", (mode, name)
                after = read_target_snapshot(connection, "p14")
                assert after["stores"] == baseline["stores"], (mode, name)
                assert after["table_state"] == baseline["table_state"], (mode, name)
                assert after["revisions"] == baseline["revisions"], (mode, name)
                assert after["legacy_reference_pending_import"] is True, (mode, name)

        # Non-pending project: a stable evidence-namespace code is used.
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    f"DELETE FROM {SCHEMA_NAME}.store_revision "
                    "WHERE project_id='p14' AND store='legacy_reference_pending_import'"
                )
        baseline = read_target_snapshot(connection, "p14")
        for mode in ("full", "incremental"):
            for name, candidate in cases:
                with pytest.raises(U3MigrationError) as refused:
                    import_project_snapshot(connection, candidate, mode=mode)
                assert refused.value.code == "U3_EVIDENCE_NAMESPACE_INVALID", (mode, name)
                after = read_target_snapshot(connection, "p14")
                assert after["stores"] == baseline["stores"], (mode, name)
                assert after["table_state"] == baseline["table_state"], (mode, name)
                assert after["revisions"] == baseline["revisions"], (mode, name)

        # The legal snapshot is still accepted in both modes.
        assert import_project_snapshot(connection, snapshot, mode="incremental")["evidence"] >= 10
        assert reconcile(snapshot, read_target_snapshot(connection, "p14"))["same"] is True

# ---------------------------------------------------------------------------
# U3 Picker P0: snapshot identity, revision protection, atomic cursor/ledger
# ---------------------------------------------------------------------------
def test_replaying_an_applied_full_snapshot_changes_no_business_row(pg, tmp_path):
    project = _fixture(tmp_path, project_id="q1")
    snapshot = export_project_snapshot(project, "q1")
    with psycopg.connect(pg.get_uri()) as connection:
        first = import_project_snapshot(connection, snapshot)
        assert first["outcome"] == "APPLIED"
        assert first["snapshot_status"] == "READY"
        before = read_target_snapshot(connection, "q1")
        state_before = _state(connection, "q1")
        assert state_before[7] == "READY"
        assert state_before[5] == 0  # no confirmation receipts in this fixture

        replay = import_project_snapshot(connection, snapshot)
        assert replay["outcome"] == "ALREADY_APPLIED"
        after = read_target_snapshot(connection, "q1")
        assert after["stores"] == before["stores"]
        assert after["counts"] == before["counts"]
        assert after["table_state"] == before["table_state"]
        assert _state(connection, "q1") == state_before
        outcomes = [row[0] for row in _ledger(connection, "q1")]
        assert outcomes == ["APPLIED", "ALREADY_APPLIED"]


def test_owner_revision_regression_is_refused_and_audited(pg, tmp_path):
    project = _fixture(tmp_path, project_id="q2")
    snapshot = export_project_snapshot(project, "q2")
    with psycopg.connect(pg.get_uri()) as connection:
        import_project_snapshot(connection, snapshot)
        baseline = read_target_snapshot(connection, "q2")

        older = _reseal(copy.deepcopy(snapshot))
        older["revisions"]["materials"] = snapshot["revisions"]["materials"] - 1
        _reseal(older)
        with pytest.raises(U3MigrationError) as refused:
            import_project_snapshot(connection, older)
        assert refused.value.code == "U3_SNAPSHOT_REVISION_REGRESSION"
        assert "store=materials" in refused.value.detail
        after = read_target_snapshot(connection, "q2")
        assert after["stores"] == baseline["stores"]
        assert after["revisions"] == baseline["revisions"]
        ledger = _ledger(connection, "q2")
        assert [row[0] for row in ledger] == ["APPLIED", "REFUSED"]
        assert ledger[1][1] == "U3_SNAPSHOT_REVISION_REGRESSION"


def test_same_revision_with_different_content_is_refused(pg, tmp_path):
    project = _fixture(tmp_path, project_id="q3")
    snapshot = export_project_snapshot(project, "q3")
    with psycopg.connect(pg.get_uri()) as connection:
        import_project_snapshot(connection, snapshot)
        baseline = read_target_snapshot(connection, "q3")

        diverged = copy.deepcopy(snapshot)
        diverged["stores"]["materials"]["materials"][0]["filename"] = "renamed-without-revision.jpg"
        _reseal(diverged)
        assert diverged["revisions"] == snapshot["revisions"]
        with pytest.raises(U3MigrationError) as refused:
            import_project_snapshot(connection, diverged)
        assert refused.value.code == "U3_SNAPSHOT_REVISION_DIVERGED"
        after = read_target_snapshot(connection, "q3")
        assert after["stores"] == baseline["stores"]


def test_a_snapshot_that_does_not_match_its_own_identity_is_refused(pg, tmp_path):
    project = _fixture(tmp_path, project_id="q4")
    snapshot = export_project_snapshot(project, "q4")
    with psycopg.connect(pg.get_uri()) as connection:
        tampered = copy.deepcopy(snapshot)
        tampered["stores"]["materials"]["materials"][0]["filename"] = "tampered.jpg"
        with pytest.raises(U3MigrationError) as digest_failure:
            import_project_snapshot(connection, tampered)
        assert digest_failure.value.code == "U3_SNAPSHOT_INTEGRITY_FAILED"
        assert "digest:materials.materials" in digest_failure.value.detail

        # Counts/digests recomputed for the changed row but the declared snapshot
        # identity kept: the identity itself no longer matches.
        relabelled = copy.deepcopy(snapshot)
        relabelled["stores"]["materials"]["materials"][0]["filename"] = "relabelled.jpg"
        relabelled["digests"] = dict(relabelled["digests"])
        relabelled["digests"]["materials.materials"] = _digest(
            relabelled["stores"]["materials"]["materials"]
        )
        relabelled["content_digest"] = _digest(
            [{"table": name, "digest": value}
             for name, value in sorted(relabelled["digests"].items())]
        )
        with pytest.raises(U3MigrationError) as id_failure:
            import_project_snapshot(connection, relabelled)
        assert id_failure.value.code == "U3_SNAPSHOT_INTEGRITY_FAILED"
        assert "reason=snapshot_id" in id_failure.value.detail

        # A full import must declare integrity metadata at all.
        stripped = copy.deepcopy(snapshot)
        for key in ("counts", "digests", "content_digest", "snapshot_id"):
            stripped.pop(key, None)
        with pytest.raises(U3MigrationError) as metadata_failure:
            import_project_snapshot(connection, stripped)
        assert metadata_failure.value.code == "U3_SNAPSHOT_INTEGRITY_FAILED"
        assert "metadata_missing" in metadata_failure.value.detail
        assert read_target_snapshot(connection, "q4")["counts"]["materials.materials"] == 0


def test_failed_import_rolls_back_rows_cursors_state_and_ledger(pg, tmp_path):
    project = _fixture(tmp_path, project_id="q5")
    snapshot = export_project_snapshot(project, "q5")
    with psycopg.connect(pg.get_uri()) as connection:
        import_project_snapshot(connection, snapshot)
        baseline = read_target_snapshot(connection, "q5")
        state_before = _state(connection, "q5")
        cursors_before = _cursors(connection, "q5")
        ledger_before = _ledger(connection, "q5")
        # Every cursor was committed with the data and the B3 baseline.
        assert cursors_before == [
            ("annotations", snapshot["change_high_water_marks"]["annotations"], 4),
            ("materials", snapshot["change_high_water_marks"]["materials"], 7),
            ("negative_pool", snapshot["change_high_water_marks"]["negative_pool"], 0),
        ]

        newer = copy.deepcopy(snapshot)
        newer["stores"]["materials"]["materials"][0]["filename"] = "must-not-land.jpg"
        newer["stores"]["materials"]["negative_pool_members"].append(
            {"material_id": "ghost", "joined_at": "2026-01-01T00:00:00+00:00"}
        )
        newer["revisions"] = {"materials": 8, "annotations": 4, "negative_pool": 1}
        _reseal(newer)
        with pytest.raises(Exception) as failure:
            import_project_snapshot(connection, newer)
        assert "foreign key" in str(failure.value).lower() or "violates" in str(failure.value).lower()

        after = read_target_snapshot(connection, "q5")
        assert after["stores"] == baseline["stores"]
        assert after["revisions"] == baseline["revisions"]
        assert _state(connection, "q5") == state_before
        assert _cursors(connection, "q5") == cursors_before
        assert _ledger(connection, "q5") == ledger_before


def test_projects_keep_independent_identity_and_ledgers(pg, tmp_path):
    first = _fixture(tmp_path / "a", project_id="q6a")
    second = _fixture(tmp_path / "b", project_id="q6b")
    with sqlite3.connect(second / "materials.sqlite3") as database:
        database.execute("UPDATE material_meta SET value='1' WHERE key='revision'")
    second_snapshot = export_project_snapshot(second, "q6b")
    first_snapshot = export_project_snapshot(first, "q6a")
    assert second_snapshot["revisions"]["materials"] == 1 < first_snapshot["revisions"]["materials"]

    with psycopg.connect(pg.get_uri()) as connection:
        import_project_snapshot(connection, first_snapshot)
        # A lower revision in ANOTHER project is not a regression.
        assert import_project_snapshot(connection, second_snapshot)["outcome"] == "APPLIED"
        # A regression in one project leaves the other untouched.
        older = _reseal(copy.deepcopy(second_snapshot))
        older["revisions"]["materials"] = 0
        _reseal(older)
        with pytest.raises(U3MigrationError) as refused:
            import_project_snapshot(connection, older)
        assert refused.value.code == "U3_SNAPSHOT_REVISION_REGRESSION"
        assert read_target_snapshot(connection, "q6a")["counts"]["materials.materials"] == 3
        assert _state(connection, "q6a")[2] == 7
        assert _state(connection, "q6b")[2] == 1
        assert [row[0] for row in _ledger(connection, "q6a")] == ["APPLIED"]
        assert [row[0] for row in _ledger(connection, "q6b")] == ["APPLIED", "REFUSED"]


def test_incremental_apply_marks_the_published_state_stale(pg, tmp_path):
    project = _fixture(tmp_path, project_id="q7")
    snapshot = export_project_snapshot(project, "q7")
    with psycopg.connect(pg.get_uri()) as connection:
        import_project_snapshot(connection, snapshot)
        assert _state(connection, "q7")[7] == "READY"
        import_project_snapshot(connection, snapshot, mode="incremental")
        assert _state(connection, "q7")[7] == "STALE"
        # A full republish of the same snapshot restores READY (it re-verifies).
        assert import_project_snapshot(connection, snapshot)["outcome"] == "APPLIED"
        assert _state(connection, "q7")[7] == "READY"


def _seed_confirmations(project):
    with sqlite3.connect(project / "annotations.sqlite3") as database:
        database.execute(
            "CREATE TABLE IF NOT EXISTS task_negative_confirmations ("
            "receipt_id TEXT PRIMARY KEY, context_key TEXT NOT NULL, evidence_json TEXT NOT NULL)"
        )
        for receipt, context, image in (("r-1", "ctx-a", "m1"), ("r-2", "ctx-a", "m2")):
            evidence = {
                "image_id": image, "annotation_version": 3, "annotation_hash": "digest-a",
                "receipt_id": receipt, "context_key": context,
            }
            database.execute(
                "INSERT INTO task_negative_confirmations VALUES (?,?,?)",
                (receipt, context, json.dumps(evidence, sort_keys=True)),
            )
    # Install the owner generation contract for the lazily created table (the two
    # seeded rows stay at generation 0, exactly like a pre-upgrade owner).
    repository = AnnotationRepository(project)
    with repository._connect() as database:
        with database:
            repository._ensure_generation_objects(database)


def test_task_negative_confirmation_projection_matches_the_owner_receipts(pg, tmp_path):
    project = _fixture(tmp_path, project_id="q8")
    _seed_confirmations(project)
    snapshot = export_project_snapshot(project, "q8")
    with psycopg.connect(pg.get_uri()) as connection:
        import_project_snapshot(connection, snapshot)
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT receipt_id,context_key,image_id,evidence "
                f"FROM {SCHEMA_NAME}.task_negative_confirmation WHERE project_id=%s "
                "ORDER BY receipt_id",
                ("q8",),
            )
            rows = cursor.fetchall()
            assert [(row[0], row[1], row[2]) for row in rows] == [
                ("r-1", "ctx-a", "m1"), ("r-2", "ctx-a", "m2"),
            ]
            assert rows[0][3]["receipt_id"] == "r-1"
            # The verbatim owner row is still retained as historical evidence.
            cursor.execute(
                f"SELECT count(*) FROM {SCHEMA_NAME}.evidence_row WHERE project_id=%s "
                "AND store='annotations' AND table_name='task_negative_confirmations'",
                ("q8",),
            )
            assert cursor.fetchone()[0] == 2
        state = _state(connection, "q8")
        assert state[5] == 2  # COUNT(*) compatibility revision
        assert state[6] == 0  # generation starts at the first published snapshot

    # Deleting a receipt changes the generation without changing an owner revision.
    with sqlite3.connect(project / "annotations.sqlite3") as database:
        database.execute("DELETE FROM task_negative_confirmations WHERE receipt_id='r-2'")
    smaller = export_project_snapshot(project, "q8")
    assert smaller["revisions"] == snapshot["revisions"]
    with psycopg.connect(pg.get_uri()) as connection:
        import_project_snapshot(connection, smaller)
        state = _state(connection, "q8")
        assert state[5] == 1
        assert state[6] == 1
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT receipt_id FROM {SCHEMA_NAME}.task_negative_confirmation "
                "WHERE project_id=%s ORDER BY receipt_id",
                ("q8",),
            )
            assert [row[0] for row in cursor.fetchall()] == ["r-1"]


def test_malformed_confirmation_evidence_fails_closed_and_rolls_back(pg, tmp_path):
    project = _fixture(tmp_path, project_id="q9")
    with sqlite3.connect(project / "annotations.sqlite3") as database:
        database.execute(
            "CREATE TABLE task_negative_confirmations ("
            "receipt_id TEXT PRIMARY KEY, context_key TEXT NOT NULL, evidence_json TEXT NOT NULL)"
        )
        database.execute(
            "INSERT INTO task_negative_confirmations VALUES ('','ctx','{\"image_id\": \"m1\"}')"
        )
    AnnotationRepository(project).reconcile_evidence_structure()
    snapshot = export_project_snapshot(project, "q9")
    with psycopg.connect(pg.get_uri()) as connection:
        with pytest.raises(U3MigrationError) as refused:
            import_project_snapshot(connection, snapshot)
        assert refused.value.code == "U3_NEGATIVE_CONFIRMATION_INVALID"
        assert read_target_snapshot(connection, "q9")["counts"]["materials.materials"] == 0
        assert _state(connection, "q9") is None
        assert _cursors(connection, "q9") == []
        assert _ledger(connection, "q9") == []


def test_snapshot_identity_is_deterministic_and_matches_the_export(pg, tmp_path):
    project = _fixture(tmp_path, project_id="q10")
    first = export_project_snapshot(project, "q10")
    second = export_project_snapshot(project, "q10")
    assert first["snapshot_id"] == second["snapshot_id"]
    assert len(first["snapshot_id"]) == 36
    with psycopg.connect(pg.get_uri()) as connection:
        import_project_snapshot(connection, first)
        assert _state(connection, "q10")[0] == first["snapshot_id"]

# ---------------------------------------------------------------------------
# Owner-side evidence generations: stale snapshots may never replace newer
# evidence, even when the three owner revisions are identical.
# ---------------------------------------------------------------------------
def _u3_rows(connection, project_id):
    """Every U3 table row of one project (deterministic order), for equality."""
    tables = (
        ("material", "id"),
        ("material_label", "material_id,label_code"),
        ("material_annotation_scope", "material_id,label_code"),
        ("annotation", "image_id"),
        ("annotation_label_reference", "image_id,label_code"),
        ("negative_pool_member", "material_id"),
        ("negative_pool_category", "id"),
        ("negative_pool_link", "material_id,category_id"),
        ("negative_pool_algorithm_member", "algorithm_id,material_id"),
        ("evidence_row", "store,table_name,row_key"),
        ("table_state", "store,table_name"),
        ("store_revision", "store"),
        ("picker_snapshot_state", "project_id"),
        ("u3_projection_cursor", "store"),
        ("u3_projection_baseline", "store"),
        ("task_negative_confirmation", "receipt_id"),
    )
    rows = {}
    with connection.transaction():
        with connection.cursor() as cursor:
            for table, order in tables:
                cursor.execute(
                    f"SELECT * FROM {SCHEMA_NAME}.{table} WHERE project_id=%s ORDER BY {order}",
                    (project_id,),
                )
                rows[table] = cursor.fetchall()
    return rows


def _confirm(repository, receipt, image="m1", version=3, digest="digest-a", context="ctx-a"):
    return repository.confirm_task_negatives(
        context,
        [{
            "receipt_id": receipt,
            "context_key": context,
            "image_id": image,
            "annotation_version": version,
            "annotation_hash": digest,
        }],
        {"actor_id": "tester"},
    )


def test_confirmation_generation_counts_insert_update_and_delete(tmp_path):
    project = _fixture(tmp_path, project_id="g1")
    repository = AnnotationRepository(project)
    assert repository.task_negative_confirmation_generation() == 0
    assert repository.task_negative_confirmation_revision() == 0

    _confirm(repository, "r-1")
    assert repository.task_negative_confirmation_generation() == 1
    assert repository.task_negative_confirmation_revision() == 1

    # Same COUNT, different receipt content: the generation still moves.
    with sqlite3.connect(project / "annotations.sqlite3") as database:
        database.execute(
            "UPDATE task_negative_confirmations SET evidence_json=? WHERE receipt_id='r-1'",
            (json.dumps({"image_id": "m1", "note": "revised"}, sort_keys=True),),
        )
    assert repository.task_negative_confirmation_generation() == 2
    assert repository.task_negative_confirmation_revision() == 1

    with sqlite3.connect(project / "annotations.sqlite3") as database:
        database.execute("DELETE FROM task_negative_confirmations WHERE receipt_id='r-1'")
    assert repository.task_negative_confirmation_generation() == 3
    assert repository.task_negative_confirmation_revision() == 0


def test_stale_confirmation_snapshot_is_refused_without_touching_the_projection(pg, tmp_path):
    project = _fixture(tmp_path, project_id="g2")
    repository = AnnotationRepository(project)
    before_first = repository.task_negative_confirmation_generation()
    first = export_project_snapshot(project, "g2")

    _confirm(repository, "r-1")
    later = export_project_snapshot(project, "g2")
    # The three owner revisions did not move: the generation is the only version.
    assert later["revisions"] == first["revisions"]
    assert later["evidence_streams"]["negative_confirmation"]["generation"] == before_first + 1
    assert later["evidence_streams"]["negative_confirmation"]["revision"] == 1

    with psycopg.connect(pg.get_uri()) as connection:
        assert import_project_snapshot(connection, later)["outcome"] == "APPLIED"
        state = _state(connection, "g2")
        assert state[5] == 1  # COUNT compatibility semantics
        assert state[6] == before_first + 1  # Owner generation, not a local counter
        assert state[7] == "READY"
        baseline = _u3_rows(connection, "g2")
        ledger_before = _ledger(connection, "g2")

        with pytest.raises(U3MigrationError) as refused:
            import_project_snapshot(connection, first)
        # S1 predates the lazily created confirmation table: its certified
        # structure version is lower, so the replay is refused on structure.
        assert refused.value.code == "U3_SNAPSHOT_STRUCTURE_REGRESSION"
        assert "stream=negative_confirmation" in refused.value.detail

        assert _u3_rows(connection, "g2") == baseline
        ledger_after = _ledger(connection, "g2")
        assert ledger_after[: len(ledger_before)] == ledger_before
        assert [row[0] for row in ledger_after[len(ledger_before):]] == ["REFUSED"]


def test_same_count_with_new_receipt_content_is_still_protected(pg, tmp_path):
    project = _fixture(tmp_path, project_id="g3")
    repository = AnnotationRepository(project)
    _confirm(repository, "r-1")
    second = export_project_snapshot(project, "g3")
    with psycopg.connect(pg.get_uri()) as connection:
        import_project_snapshot(connection, second)

    with sqlite3.connect(project / "annotations.sqlite3") as database:
        database.execute(
            "UPDATE task_negative_confirmations SET evidence_json=? WHERE receipt_id='r-1'",
            (json.dumps({"image_id": "m1", "note": "revised"}, sort_keys=True),),
        )
    third = export_project_snapshot(project, "g3")
    assert (
        third["evidence_streams"]["negative_confirmation"]["revision"]
        == second["evidence_streams"]["negative_confirmation"]["revision"]
    )
    assert (
        third["evidence_streams"]["negative_confirmation"]["generation"]
        == second["evidence_streams"]["negative_confirmation"]["generation"] + 1
    )
    with psycopg.connect(pg.get_uri()) as connection:
        assert import_project_snapshot(connection, third)["outcome"] == "APPLIED"
        baseline = _u3_rows(connection, "g3")
        with pytest.raises(U3MigrationError) as refused:
            import_project_snapshot(connection, second)
        assert refused.value.code == "U3_SNAPSHOT_REVISION_REGRESSION"
        assert "stream=negative_confirmation" in refused.value.detail
        assert _u3_rows(connection, "g3") == baseline


def test_confirmation_write_waits_for_the_lifecycle_fence(tmp_path):
    import threading
    import time

    from platform_core.material_repository import material_annotation_lifecycle_fence

    project = _fixture(tmp_path, project_id="g4")
    repository = AnnotationRepository(project)
    holding = threading.Event()
    release = threading.Event()

    def hold():
        with material_annotation_lifecycle_fence(project, timeout=10):
            holding.set()
            release.wait(10)

    thread = threading.Thread(target=hold)
    thread.start()
    assert holding.wait(10)
    started = time.monotonic()
    timer = threading.Timer(0.8, release.set)
    timer.start()
    _confirm(repository, "r-1")
    elapsed = time.monotonic() - started
    thread.join(10)
    timer.cancel()
    # The confirmation could not commit while the export fence was held.
    assert elapsed >= 0.5, elapsed
    assert repository.task_negative_confirmation_generation() >= 1


def test_material_evidence_generation_protects_no_revision_evidence(pg, tmp_path):
    project = _fixture(tmp_path, project_id="g5")
    materials = MaterialRepository(project)
    first = export_project_snapshot(project, "g5")
    generation = first["evidence_streams"]["materials_evidence"]["generation"]

    # A real owner write that deliberately does NOT advance material_meta.revision.
    materials.record_deferred_cleanup(
        {"id": "m1", "filename": "fire.jpg"}, owner="tester", error="boom"
    )
    later = export_project_snapshot(project, "g5")
    assert later["revisions"] == first["revisions"]
    assert later["evidence_streams"]["materials_evidence"]["generation"] == generation + 1

    with psycopg.connect(pg.get_uri()) as connection:
        assert import_project_snapshot(connection, later)["outcome"] == "APPLIED"
        baseline = _u3_rows(connection, "g5")
        with pytest.raises(U3MigrationError) as refused:
            import_project_snapshot(connection, first)
        assert refused.value.code == "U3_SNAPSHOT_REVISION_REGRESSION"
        assert "stream=materials_evidence" in refused.value.detail
        assert _u3_rows(connection, "g5") == baseline


def test_full_import_rejects_an_unproven_snapshot_before_any_write(pg, tmp_path):
    """Two distinct cases are kept apart on purpose.

    A physically absent evidence table (``table_state.present=false``) is a legal
    owner structure and is accepted (see the structure-lifecycle tests). The
    ``missing_evidence`` variant below removes the ``table_state`` METADATA while
    the snapshot still carries no evidence for that table: that is a malformed
    snapshot, not an absent table, and must be refused.
    """
    project = _fixture(tmp_path, project_id="g6")
    _seed_evidence(project)
    snapshot = export_project_snapshot(project, "g6")
    with psycopg.connect(pg.get_uri()) as connection:
        import_project_snapshot(connection, snapshot)
        assert _state(connection, "g6")[7] == "READY"
        baseline = _u3_rows(connection, "g6")
        ledger_before = _ledger(connection, "g6")

        missing_materials = copy.deepcopy(snapshot)
        missing_materials["stores"]["materials"].pop("materials")
        _reseal(missing_materials)

        missing_annotations = copy.deepcopy(snapshot)
        missing_annotations["stores"]["annotations"].pop("annotations")
        _reseal(missing_annotations)

        missing_metadata = copy.deepcopy(snapshot)
        table = "material_storage_audit"
        missing_metadata["stores"]["materials"]["evidence"].pop(table)
        missing_metadata["table_state"].pop(f"materials.{table}")
        missing_metadata["counts"].pop(f"materials.evidence.{table}", None)
        missing_metadata["digests"].pop(f"materials.evidence.{table}", None)
        _reseal(missing_metadata)

        for name, candidate in (
            ("materials", missing_materials),
            ("annotations", missing_annotations),
            ("evidence_metadata", missing_metadata),
        ):
            with pytest.raises(U3MigrationError) as refused:
                import_project_snapshot(connection, candidate, mode="full")
            assert refused.value.code == "U3_SNAPSHOT_INCOMPLETE", name
            assert "reason=" in refused.value.detail, name
            # Business rows / evidence / table_state / revisions / cursors / state.
            assert _u3_rows(connection, "g6") == baseline, name
            # The audit ledger is a SEPARATE assertion: an incomplete snapshot is
            # not a policy refusal, so it records nothing at all.
            assert _ledger(connection, "g6") == ledger_before, name

        # A policy refusal (integrity) instead leaves the business state intact
        # and appends exactly one REFUSED audit row.
        tampered = copy.deepcopy(snapshot)
        tampered["stores"]["materials"]["materials"][0]["filename"] = "tampered.jpg"
        ledger_before = _ledger(connection, "g6")
        with pytest.raises(U3MigrationError) as refused:
            import_project_snapshot(connection, tampered, mode="full")
        assert refused.value.code == "U3_SNAPSHOT_INTEGRITY_FAILED"
        assert _u3_rows(connection, "g6") == baseline
        ledger_after = _ledger(connection, "g6")
        assert ledger_after[:-1] == ledger_before
        assert ledger_after[-1][0] == "REFUSED"
        assert ledger_after[-1][1] == "U3_SNAPSHOT_INTEGRITY_FAILED"

def test_resealed_evidence_without_a_new_generation_is_refused(pg, tmp_path):
    project = _fixture(tmp_path, project_id="g7")
    repository = AnnotationRepository(project)
    _confirm(repository, "r-1")
    snapshot = export_project_snapshot(project, "g7")
    with psycopg.connect(pg.get_uri()) as connection:
        import_project_snapshot(connection, snapshot)
        baseline = _u3_rows(connection, "g7")

    # Self-consistent (resealed) but the Owner generation did not move: the
    # content cannot be newer than the published snapshot.
    tampered = copy.deepcopy(snapshot)
    evidence = tampered["stores"]["annotations"]["evidence"]["task_negative_confirmations"]
    evidence[0]["payload"] = dict(
        evidence[0]["payload"],
        evidence_json=json.dumps({"image_id": "m1", "note": "rewritten"}, sort_keys=True),
    )
    _reseal(tampered)
    with psycopg.connect(pg.get_uri()) as connection:
        with pytest.raises(U3MigrationError) as refused:
            import_project_snapshot(connection, tampered)
        assert refused.value.code == "U3_SNAPSHOT_REVISION_DIVERGED"
        assert "stream=negative_confirmation" in refused.value.detail
        assert _u3_rows(connection, "g7") == baseline

# ---------------------------------------------------------------------------
# Evidence-table lifecycle: a structure change must advance the persisted
# structure version, and a pre-change snapshot must never be replayed.
# ---------------------------------------------------------------------------
def _evidence_rows(connection, project_id, table):
    with connection.transaction():
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT count(*) FROM {SCHEMA_NAME}.evidence_row "
                "WHERE project_id=%s AND store='materials' AND table_name=%s",
                (project_id, table),
            )
            return cursor.fetchone()[0]


def test_structure_change_rejects_the_pre_change_snapshot(pg, tmp_path):
    project = _fixture(tmp_path, project_id="s1")
    _seed_evidence(project)
    first = export_project_snapshot(project, "s1")
    with psycopg.connect(pg.get_uri()) as connection:
        import_project_snapshot(connection, first)
        before = _u3_rows(connection, "s1")
        ledger_before = _ledger(connection, "s1")

        with sqlite3.connect(project / "materials.sqlite3") as database:
            database.execute("DROP TABLE material_cleanup_deferred")
        # Uncertified raw DDL: the export fails closed instead of guessing safety.
        with pytest.raises(U3MigrationError) as unverified:
            export_project_snapshot(project, "s1")
        assert unverified.value.code == "U3_OWNER_STRUCTURE_UNVERIFIED"
        assert "material_cleanup_deferred" in unverified.value.detail

        reconciled = MaterialRepository(project).reconcile_evidence_structure()
        assert reconciled["changed"] is True
        assert reconciled["generation"] > 0
        second = export_project_snapshot(project, "s1")
        assert (
            second["evidence_streams"]["materials_evidence"]["structure_generation"]
            > first["evidence_streams"]["materials_evidence"]["structure_generation"]
        )
        import_project_snapshot(connection, second)
        baseline = _u3_rows(connection, "s1")
        # absent keeps the historical evidence rows
        assert _evidence_rows(connection, "s1", "material_cleanup_deferred") == 2
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT present FROM {SCHEMA_NAME}.table_state "
                    "WHERE project_id='s1' AND store='materials' "
                    "AND table_name='material_cleanup_deferred'"
                )
                assert cursor.fetchone()[0] is False

        ledger_before_refusal = _ledger(connection, "s1")
        with pytest.raises(U3MigrationError) as refused:
            import_project_snapshot(connection, first)
        assert refused.value.code == "U3_SNAPSHOT_STRUCTURE_REGRESSION"
        assert "stream=materials_evidence" in refused.value.detail
        # Business rows, evidence, table_state, revisions, cursors and state are
        # untouched by the refusal.
        assert _u3_rows(connection, "s1") == baseline
        # The audit ledger is asserted separately: it only gains one REFUSED row.
        ledger_after = _ledger(connection, "s1")
        assert ledger_after[:-1] == ledger_before_refusal
        assert ledger_after[-1][0] == "REFUSED"
        assert ledger_after[-1][1] == "U3_SNAPSHOT_STRUCTURE_REGRESSION"


def test_recreated_table_newer_evidence_rejects_older_snapshots(pg, tmp_path):
    project = _fixture(tmp_path, project_id="s2")
    _seed_evidence(project)
    first = export_project_snapshot(project, "s2")
    with psycopg.connect(pg.get_uri()) as connection:
        import_project_snapshot(connection, first)

        with sqlite3.connect(project / "materials.sqlite3") as database:
            database.execute("DROP TABLE material_cleanup_deferred")
        MaterialRepository(project).reconcile_evidence_structure()
        second = export_project_snapshot(project, "s2")
        import_project_snapshot(connection, second)

        # Recreate the table through the owner DDL and write NEW evidence; the
        # reconcile installs the triggers before the row exists.
        with sqlite3.connect(project / "materials.sqlite3") as database:
            database.execute(
                "CREATE TABLE material_cleanup_deferred ("
                "cleanup_id TEXT PRIMARY KEY, image_id TEXT NOT NULL, owner TEXT NOT NULL, "
                "payload_json TEXT NOT NULL, last_error TEXT NOT NULL, recorded_at TEXT NOT NULL, "
                "reclamation_state TEXT NOT NULL DEFAULT 'DEFERRED_SAFETY_UNVERIFIED')"
            )
        MaterialRepository(project).reconcile_evidence_structure()
        with sqlite3.connect(project / "materials.sqlite3") as database:
            database.execute(
                "INSERT INTO material_cleanup_deferred"
                "(cleanup_id,image_id,owner,payload_json,last_error,recorded_at) "
                "VALUES ('c-new','m1','owner','{}','err','2026-01-01')"
            )
        third = export_project_snapshot(project, "s2")
        assert (
            third["evidence_streams"]["materials_evidence"]["structure_generation"]
            > second["evidence_streams"]["materials_evidence"]["structure_generation"]
        )
        import_project_snapshot(connection, third)
        baseline = _u3_rows(connection, "s2")
        for stale in (first, second):
            with pytest.raises(U3MigrationError) as refused:
                import_project_snapshot(connection, stale)
            assert refused.value.code == "U3_SNAPSHOT_STRUCTURE_REGRESSION"
            assert _u3_rows(connection, "s2") == baseline


def test_absent_retains_and_empty_clears_across_structure_changes(pg, tmp_path):
    project = _fixture(tmp_path, project_id="s3")
    _seed_evidence(project)
    with psycopg.connect(pg.get_uri()) as connection:
        import_project_snapshot(connection, export_project_snapshot(project, "s3"))
        assert _evidence_rows(connection, "s3", "material_cleanup_deferred") == 2

        # (1) Present but empty: authoritative emptiness clears the target rows.
        with sqlite3.connect(project / "materials.sqlite3") as database:
            database.execute("DELETE FROM material_cleanup_deferred")
        emptied = export_project_snapshot(project, "s3")
        import_project_snapshot(connection, emptied)
        assert _evidence_rows(connection, "s3", "material_cleanup_deferred") == 0

        # (2) Re-add rows, then drop the table: the absent source retains them.
        with sqlite3.connect(project / "materials.sqlite3") as database:
            for cleanup_id in ("c-1", "c-2"):
                database.execute(
                    "INSERT INTO material_cleanup_deferred"
                    "(cleanup_id,image_id,owner,payload_json,last_error,recorded_at) "
                    "VALUES (?,?, 'owner','{}','err','2026-01-01')",
                    (cleanup_id, "m1"),
                )
        with_rows = export_project_snapshot(project, "s3")
        import_project_snapshot(connection, with_rows)
        assert _evidence_rows(connection, "s3", "material_cleanup_deferred") == 2

        with sqlite3.connect(project / "materials.sqlite3") as database:
            database.execute("DROP TABLE material_cleanup_deferred")
        MaterialRepository(project).reconcile_evidence_structure()
        absent = export_project_snapshot(project, "s3")
        import_project_snapshot(connection, absent)
        assert _evidence_rows(connection, "s3", "material_cleanup_deferred") == 2
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT present FROM {SCHEMA_NAME}.table_state "
                    "WHERE project_id='s3' AND table_name='material_cleanup_deferred'"
                )
                assert cursor.fetchone()[0] is False

        # (3) Recreate empty: present-and-empty clears again.
        with sqlite3.connect(project / "materials.sqlite3") as database:
            database.execute(
                "CREATE TABLE material_cleanup_deferred ("
                "cleanup_id TEXT PRIMARY KEY, image_id TEXT NOT NULL, owner TEXT NOT NULL, "
                "payload_json TEXT NOT NULL, last_error TEXT NOT NULL, recorded_at TEXT NOT NULL, "
                "reclamation_state TEXT NOT NULL DEFAULT 'DEFERRED_SAFETY_UNVERIFIED')"
            )
        MaterialRepository(project).reconcile_evidence_structure()
        empty_again = export_project_snapshot(project, "s3")
        import_project_snapshot(connection, empty_again)
        assert _evidence_rows(connection, "s3", "material_cleanup_deferred") == 0


def test_annotation_structure_change_keeps_confirmation_projection_consistent(pg, tmp_path):
    project = _fixture(tmp_path, project_id="s4")
    repository = AnnotationRepository(project)
    _confirm(repository, "r-1")
    _confirm(repository, "r-2")
    first = export_project_snapshot(project, "s4")
    with psycopg.connect(pg.get_uri()) as connection:
        import_project_snapshot(connection, first)
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT count(*) FROM {SCHEMA_NAME}.evidence_row WHERE project_id='s4' "
                    "AND table_name='task_negative_confirmations'"
                )
                assert cursor.fetchone()[0] == 2
                cursor.execute(
                    f"SELECT count(*) FROM {SCHEMA_NAME}.task_negative_confirmation "
                    "WHERE project_id='s4'"
                )
                assert cursor.fetchone()[0] == 2

        with sqlite3.connect(project / "annotations.sqlite3") as database:
            database.execute("DROP TABLE task_negative_confirmations")
        with pytest.raises(U3MigrationError) as unverified:
            export_project_snapshot(project, "s4")
        assert unverified.value.code == "U3_OWNER_STRUCTURE_UNVERIFIED"
        AnnotationRepository(project).reconcile_evidence_structure()
        second = export_project_snapshot(project, "s4")
        import_project_snapshot(connection, second)

        # P1: an absent source table retains BOTH the evidence rows and the
        # derived projection -- one is never cleared while the other is retained.
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT count(*) FROM {SCHEMA_NAME}.evidence_row WHERE project_id='s4' "
                    "AND table_name='task_negative_confirmations'"
                )
                assert cursor.fetchone()[0] == 2
                cursor.execute(
                    f"SELECT count(*) FROM {SCHEMA_NAME}.task_negative_confirmation "
                    "WHERE project_id='s4'"
                )
                assert cursor.fetchone()[0] == 2
                cursor.execute(
                    f"SELECT negative_confirmation_revision, revision_vector "
                    f"FROM {SCHEMA_NAME}.picker_snapshot_state WHERE project_id='s4'"
                )
                revision, vector = cursor.fetchone()
                assert revision == 0  # owner COUNT(*) compatibility semantics
                assert vector["negative_confirmation"]["tables"] == []
                assert vector["negative_confirmation"]["structure_generation"] > 0
        baseline = _u3_rows(connection, "s4")
        with pytest.raises(U3MigrationError) as refused:
            import_project_snapshot(connection, first)
        assert refused.value.code == "U3_SNAPSHOT_STRUCTURE_REGRESSION"
        assert _u3_rows(connection, "s4") == baseline

def test_import_refuses_an_uncertified_structure_change(pg, tmp_path):
    """Defense in depth: a crafted snapshot cannot invent a structure change."""
    project = _fixture(tmp_path, project_id="s5")
    _seed_evidence(project)
    snapshot = export_project_snapshot(project, "s5")
    with psycopg.connect(pg.get_uri()) as connection:
        import_project_snapshot(connection, snapshot)
        baseline = _u3_rows(connection, "s5")
        ledger_before = _ledger(connection, "s5")

        crafted = copy.deepcopy(snapshot)
        table = "material_cleanup_deferred"
        crafted["stores"]["materials"]["evidence"].pop(table)
        crafted["table_state"][f"materials.{table}"]["present"] = False
        crafted["table_state"][f"materials.{table}"]["row_count"] = 0
        crafted["counts"].pop(f"materials.evidence.{table}", None)
        crafted["digests"].pop(f"materials.evidence.{table}", None)
        crafted["evidence_streams"]["materials_evidence"]["structure_certified"] = False
        _reseal(crafted)

        with pytest.raises(U3MigrationError) as refused:
            import_project_snapshot(connection, crafted, mode="full")
        assert refused.value.code == "U3_SNAPSHOT_STRUCTURE_UNVERIFIED"
        assert "stream=materials_evidence" in refused.value.detail
        assert _u3_rows(connection, "s5") == baseline
        ledger_after = _ledger(connection, "s5")
        assert ledger_after[:-1] == ledger_before
        assert ledger_after[-1][0] == "REFUSED"
        assert ledger_after[-1][1] == "U3_SNAPSHOT_STRUCTURE_UNVERIFIED"

def _materials_generation(project):
    with sqlite3.connect(project / "materials.sqlite3") as database:
        return int(database.execute(
            "SELECT value FROM material_meta WHERE key='evidence_generation'"
        ).fetchone()[0])


def test_pool_receipts_advance_evidence_generation_and_reject_stale_snapshot(pg, tmp_path):
    """Two legitimate member operations differ only by their receipt rows."""
    project = _fixture(tmp_path, project_id="n1")
    materials = MaterialRepository(project)
    pool = NegativePool(materials)
    first = export_project_snapshot(project, "n1")
    with psycopg.connect(pg.get_uri()) as connection:
        import_project_snapshot(connection, first)

        pool.members(
            ["m1"], action="add", expected_revision=pool.revision(),
            operation_id="op-1", project_id="n1",
            operation_kind="negative_pool.members.v2",
        )
        second = export_project_snapshot(project, "n1")
        assert import_project_snapshot(connection, second)["outcome"] == "APPLIED"

        generation_before = _materials_generation(project)
        revision_for_op2 = pool.revision()
        pool.members(
            ["m2"], action="add", expected_revision=revision_for_op2,
            operation_id="op-2", project_id="n1",
            operation_kind="negative_pool.members.v2",
        )
        third = export_project_snapshot(project, "n1")
        # Same evidence-table structure, different receipts: the generation must
        # advance, otherwise this legitimate import would be refused as
        # U3_SNAPSHOT_REVISION_DIVERGED.
        assert (
            third["evidence_streams"]["materials_evidence"]["tables"]
            == second["evidence_streams"]["materials_evidence"]["tables"]
        )
        assert (
            third["evidence_streams"]["materials_evidence"]["generation"]
            == second["evidence_streams"]["materials_evidence"]["generation"] + 1
        )
        assert (
            third["evidence_streams"]["materials_evidence"]["structure_generation"]
            == second["evidence_streams"]["materials_evidence"]["structure_generation"]
        )
        assert _materials_generation(project) == generation_before + 1
        assert import_project_snapshot(connection, third)["outcome"] == "APPLIED"
        baseline = _u3_rows(connection, "n1")
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT count(*) FROM {SCHEMA_NAME}.evidence_row WHERE project_id='n1' "
                    "AND table_name='negative_pool_operations'"
                )
                assert cursor.fetchone()[0] == 2

        # Idempotent replay of the same operation_id writes no new receipt and
        # therefore must not advance the generation.
        generation_before = _materials_generation(project)
        pool.members(
            ["m2"], action="add", expected_revision=revision_for_op2,
            operation_id="op-2", project_id="n1",
            operation_kind="negative_pool.members.v2",
        )
        assert _materials_generation(project) == generation_before

        with pytest.raises(U3MigrationError) as refused:
            import_project_snapshot(connection, second)
        assert refused.value.code == "U3_SNAPSHOT_REVISION_REGRESSION"
        assert "stream=materials_evidence" in refused.value.detail
        assert _u3_rows(connection, "n1") == baseline


def test_export_detects_a_materials_structure_generation_change(tmp_path, monkeypatch):
    """Only the persisted materials structure version changes mid-export."""
    from platform_core import u3_shadow as u3_module

    project = _fixture(tmp_path, project_id="n2")
    real_columns = u3_module._sqlite_columns
    fired = {"done": False}

    def hook(database, table):
        if not fired["done"] and table == "annotation_delete_backup":
            # The annotations phase runs after the materials phase and before the
            # closing re-check; bump ONLY the materials structure version so the
            # table set, recorded structure and row generations stay identical.
            fired["done"] = True
            with sqlite3.connect(project / "materials.sqlite3") as materials_db:
                materials_db.execute(
                    "UPDATE material_meta SET value = CAST(value AS INTEGER) + 1 "
                    "WHERE key='evidence_structure_generation'"
                )
        return real_columns(database, table)

    monkeypatch.setattr(u3_module, "_sqlite_columns", hook)
    with pytest.raises(U3MigrationError) as changed:
        export_project_snapshot(project, "n2")
    assert changed.value.code == "U3_SNAPSHOT_SOURCE_CHANGED"
    assert "structures=" in changed.value.detail
    assert fired["done"] is True
