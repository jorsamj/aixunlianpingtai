"""U3-P3-B2 incremental consumption against a real PostgreSQL (isolated)."""
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

from platform_core import u3_incremental_sync as sync
from platform_core import material_repository_batch as material_batch_module
from platform_core.annotation_repository import AnnotationRepository
from platform_core.material_repository import MaterialRepository
from platform_core.negative_pool import NegativePool
from platform_core.u3_owner_change_log import (
    ANNOTATION_STREAM,
    MATERIAL_STREAM,
    NEGATIVE_POOL_STREAM,
    high_water_marks,
)
from platform_core.u3_shadow import (
    SCHEMA_NAME,
    ensure_schema,
    export_project_snapshot,
    import_project_snapshot,
    read_target_snapshot,
    reconcile,
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

    external = os.environ.get(_EXTERNAL_DSN_ENV, "").strip()
    if external:
        server = _ExternalPostgres(external)
        yield server
        server.cleanup()
        return
    pgserver = _require_or_skip("pgserver", "an isolated local PostgreSQL server is required")
    root = pathlib.Path(tempfile.mkdtemp(prefix="pgw3-incremental-")) / "data"
    server = pgserver.get_server(root, cleanup_mode="delete")
    yield server
    server.cleanup()


def _project(tmp_path, name="p1"):
    project = tmp_path / "projects" / name
    project.mkdir(parents=True)
    materials = MaterialRepository(project)
    materials.upsert({
        "id": "m1", "filename": "fire.jpg", "object_key": "uploads/fire.jpg",
        "content_sha256": "1" * 64, "processing_status": "ready",
        "labels": ["fire"], "label_counts": {"fire": 1},
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    })
    materials.upsert({
        "id": "m2", "filename": "smoke.jpg", "object_key": "uploads/smoke.jpg",
        "content_sha256": "2" * 64, "processing_status": "ready",
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    })
    annotations = AnnotationRepository(project)
    annotations.upsert(
        "m1", [{"label": "fire", "bbox": [1, 2, 3, 4]}],
        annotation_scope=["fire"], project_material=False,
    )
    pool = NegativePool(materials)
    category = pool.category(name="fire")
    pool.members(["m1"], category_ids=[category["id"]])
    return project, materials, annotations, pool, category["id"]


def _baseline(connection, project, project_id="p1"):
    snapshot = export_project_snapshot(project, project_id)
    import_project_snapshot(connection, snapshot)
    marks = snapshot["change_high_water_marks"]
    for stream, sequence in marks.items():
        connection.execute(
            f"INSERT INTO {SCHEMA_NAME}.u3_projection_baseline"
            "(project_id,store,baseline_id,snapshot_id,high_water_sequence) "
            "VALUES (%s,%s,%s,%s,%s) ON CONFLICT (project_id,store) DO UPDATE SET "
            "baseline_id=EXCLUDED.baseline_id, snapshot_id=EXCLUDED.snapshot_id, "
            "high_water_sequence=EXCLUDED.high_water_sequence",
            (
                project_id, stream, snapshot["baseline_id"],
                snapshot["snapshot_id"], sequence,
            ),
        )
    connection.commit()
    return marks


def _marks(project):
    marks = {}
    with sqlite3.connect(project / "materials.sqlite3") as database:
        marks.update(high_water_marks(database))
    with sqlite3.connect(project / "annotations.sqlite3") as database:
        marks.update(high_water_marks(database))
    return marks


def _cursor(connection, project_id, stream):
    return connection.execute(
        f"SELECT last_applied_seq FROM {SCHEMA_NAME}.u3_projection_cursor "
        "WHERE project_id=%s AND store=%s",
        (project_id, stream),
    ).fetchone()[0]


def _apply(connection, project, stream, project_id="p1", limit=100):
    return sync.apply_incremental_batch(
        connection, project_dir=project, project_id=project_id,
        stream=stream, limit=limit,
    )


def test_material_batch_advances_cursor_and_invalidates_ready(pg, tmp_path):
    project, materials, _, _, _ = _project(tmp_path)
    with psycopg.connect(pg.get_uri()) as connection:
        ensure_schema(connection)
        marks = _baseline(connection, project)
        assert connection.execute(
            f"SELECT status FROM {SCHEMA_NAME}.picker_snapshot_state WHERE project_id='p1'"
        ).fetchone()[0] == "READY"

        row = materials.get("m1")
        row.update(filename="fire-renamed.jpg", updated_at="2026-01-02T00:00:00+00:00")
        materials.upsert(row)
        result = _apply(connection, project, MATERIAL_STREAM)
        assert result["applied"] > 0
        assert connection.execute(
            f"SELECT filename FROM {SCHEMA_NAME}.material WHERE project_id='p1' AND id='m1'"
        ).fetchone()[0] == "fire-renamed.jpg"
        assert connection.execute(
            f"SELECT status FROM {SCHEMA_NAME}.picker_snapshot_state WHERE project_id='p1'"
        ).fetchone()[0] == "STALE"

        # Replaying the same identities from a rewound cursor is idempotent.
        connection.execute(
            f"UPDATE {SCHEMA_NAME}.u3_projection_cursor SET last_applied_seq=%s "
            "WHERE project_id='p1' AND store=%s",
            (marks[MATERIAL_STREAM], MATERIAL_STREAM),
        )
        connection.commit()
        replay = _apply(connection, project, MATERIAL_STREAM)
        assert replay["applied"] == 0 and replay["skipped"] == result["applied"]
        assert _cursor(connection, "p1", MATERIAL_STREAM) == _marks(project)[MATERIAL_STREAM]


def test_digest_conflict_and_sequence_gap_do_not_advance_the_cursor(pg, tmp_path):
    project, materials, _, _, _ = _project(tmp_path, "p2")
    with psycopg.connect(pg.get_uri()) as connection:
        ensure_schema(connection)
        marks = _baseline(connection, project, "p2")
        row = materials.get("m1")
        row.update(filename="conflict.jpg")
        materials.upsert(row)
        row = materials.get("m1")
        row.update(filename="conflict-2.jpg")
        materials.upsert(row)
        result = _apply(connection, project, MATERIAL_STREAM, "p2")
        first_sequence = marks[MATERIAL_STREAM] + 1
        assert result["applied"] >= 2
        first_digest = connection.execute(
            f"SELECT payload_digest FROM {SCHEMA_NAME}.u3_applied_owner_event "
            "WHERE project_id='p2' AND store=%s AND sequence=%s",
            (MATERIAL_STREAM, first_sequence),
        ).fetchone()[0]
        before = materials.get("m1")["filename"]

        connection.execute(
            f"UPDATE {SCHEMA_NAME}.u3_applied_owner_event SET payload_digest=%s "
            "WHERE project_id='p2' AND store=%s AND sequence=%s",
            ("0" * 64, MATERIAL_STREAM, first_sequence),
        )
        connection.execute(
            f"UPDATE {SCHEMA_NAME}.u3_projection_cursor SET last_applied_seq=%s "
            "WHERE project_id='p2' AND store=%s",
            (marks[MATERIAL_STREAM], MATERIAL_STREAM),
        )
        connection.commit()
        with pytest.raises(sync.U3IncrementalSyncError) as conflict:
            _apply(connection, project, MATERIAL_STREAM, "p2")
        assert conflict.value.code == "U3_INCREMENTAL_EVENT_DIGEST_CONFLICT"
        assert _cursor(connection, "p2", MATERIAL_STREAM) == marks[MATERIAL_STREAM]
        assert materials.get("m1")["filename"] == before

        # A real gap in the owner log is refused without advancing the cursor.
        connection.execute(
            f"UPDATE {SCHEMA_NAME}.u3_applied_owner_event SET payload_digest=%s "
            "WHERE project_id='p2' AND store=%s AND sequence=%s",
            (first_digest, MATERIAL_STREAM, first_sequence),
        )
        connection.execute(
            f"UPDATE {SCHEMA_NAME}.u3_projection_cursor SET last_applied_seq=%s "
            "WHERE project_id='p2' AND store=%s",
            (marks[MATERIAL_STREAM], MATERIAL_STREAM),
        )
        connection.commit()
        with sqlite3.connect(materials.path) as database:
            database.execute("DROP TRIGGER owner_change_log_no_delete")
            database.execute(
                "DELETE FROM owner_change_log WHERE stream=? AND sequence=?",
                (MATERIAL_STREAM, first_sequence),
            )
            database.commit()
        with pytest.raises(sync.U3IncrementalSyncError) as gap:
            _apply(connection, project, MATERIAL_STREAM, "p2")
        assert gap.value.code == "U3_INCREMENTAL_SEQUENCE_GAP"
        assert _cursor(connection, "p2", MATERIAL_STREAM) == marks[MATERIAL_STREAM]


def test_annotation_and_confirmation_events_apply_in_order(pg, tmp_path):
    project, _, annotations, _, _ = _project(tmp_path, "p3")
    with psycopg.connect(pg.get_uri()) as connection:
        ensure_schema(connection)
        _baseline(connection, project, "p3")
        gt = annotations.get("m1")
        annotations.upsert(
            "m1",
            [{"label": "fire", "bbox": [5, 6, 7, 8]}, {"label": "smoke", "bbox": [9, 9, 10, 10]}],
            annotation_scope=["fire", "smoke"], expected_version=gt["version"],
            project_material=False,
        )
        updated = annotations.get("m1")
        annotations.confirm_task_negatives(
            "task-context",
            [{
                "receipt_id": "receipt-1", "image_id": "m1",
                "annotation_version": updated["version"],
                "annotation_hash": updated["content_digest"],
            }],
            "actor-1",
        )
        result = _apply(connection, project, ANNOTATION_STREAM, "p3")
        assert result["applied"] >= 2
        assert connection.execute(
            f"SELECT version, jsonb_array_length(boxes) FROM {SCHEMA_NAME}.annotation "
            "WHERE project_id='p3' AND image_id='m1'"
        ).fetchone() == (updated["version"], 2)
        assert connection.execute(
            f"SELECT context_key, image_id FROM {SCHEMA_NAME}.task_negative_confirmation "
            "WHERE project_id='p3' AND receipt_id='receipt-1'"
        ).fetchone() == ("task-context", "m1")

        annotations.remove(["m1"])
        _apply(connection, project, ANNOTATION_STREAM, "p3")
        assert connection.execute(
            f"SELECT 1 FROM {SCHEMA_NAME}.annotation WHERE project_id='p3' AND image_id='m1'"
        ).fetchone() is None
        assert connection.execute(
            f"SELECT 1 FROM {SCHEMA_NAME}.annotation_label_reference "
            "WHERE project_id='p3' AND image_id='m1'"
        ).fetchone() is None


def test_negative_pool_and_project_isolation(pg, tmp_path):
    project_a, materials_a, _, _, category_a = _project(tmp_path, "p4a")
    project_b, materials_b, _, _, category_b = _project(tmp_path, "p4b")
    with psycopg.connect(pg.get_uri()) as connection:
        ensure_schema(connection)
        _baseline(connection, project_a, "p4a")
        _baseline(connection, project_b, "p4b")

        NegativePool(materials_a).category(category_a, name="fire-renamed")
        _apply(connection, project_a, NEGATIVE_POOL_STREAM, "p4a")
        assert connection.execute(
            f"SELECT name FROM {SCHEMA_NAME}.negative_pool_category "
            "WHERE project_id='p4a' AND id=%s", (category_a,)
        ).fetchone()[0] == "fire-renamed"
        assert connection.execute(
            f"SELECT name FROM {SCHEMA_NAME}.negative_pool_category "
            "WHERE project_id='p4b' AND id=%s", (category_b,)
        ).fetchone()[0] == "fire"

        materials_a.remove(["m1"])
        _apply(connection, project_a, MATERIAL_STREAM, "p4a")
        assert connection.execute(
            f"SELECT 1 FROM {SCHEMA_NAME}.material WHERE project_id='p4a' AND id='m1'"
        ).fetchone() is None
        assert connection.execute(
            f"SELECT 1 FROM {SCHEMA_NAME}.material WHERE project_id='p4b' AND id='m1'"
        ).fetchone() is not None

        with pytest.raises(sync.U3IncrementalSyncError) as wrong_project:
            _apply(connection, project_a, MATERIAL_STREAM, "p4b")
        assert wrong_project.value.code == "U3_INCREMENTAL_PROJECT_MISMATCH"


def test_failure_before_cursor_advance_rolls_back_the_projection(pg, tmp_path, monkeypatch):
    project, materials, _, _, _ = _project(tmp_path, "p5")
    with psycopg.connect(pg.get_uri()) as connection:
        ensure_schema(connection)
        marks = _baseline(connection, project, "p5")
        row = materials.get("m1")
        row.update(filename="rollback.jpg")
        materials.upsert(row)

        def boom(*args, **kwargs):
            raise RuntimeError("simulated cursor failure")

        monkeypatch.setattr(sync, "_advance_cursor", boom)
        with pytest.raises(RuntimeError):
            _apply(connection, project, MATERIAL_STREAM, "p5")
        assert connection.execute(
            f"SELECT filename FROM {SCHEMA_NAME}.material WHERE project_id='p5' AND id='m1'"
        ).fetchone()[0] == "fire.jpg"
        assert _cursor(connection, "p5", MATERIAL_STREAM) == marks[MATERIAL_STREAM]

        monkeypatch.undo()
        _apply(connection, project, MATERIAL_STREAM, "p5")
        assert connection.execute(
            f"SELECT filename FROM {SCHEMA_NAME}.material WHERE project_id='p5' AND id='m1'"
        ).fetchone()[0] == "rollback.jpg"


def test_b3_publish_ready_after_all_streams_align(pg, tmp_path):
    project, materials, annotations, pool, category = _project(tmp_path, "p6")
    with psycopg.connect(pg.get_uri()) as connection:
        ensure_schema(connection)
        _baseline(connection, project, "p6")
        before = connection.execute(
            f"SELECT snapshot_id FROM {SCHEMA_NAME}.picker_snapshot_state WHERE project_id='p6'"
        ).fetchone()[0]
        connection.commit()

        row = materials.get("m1")
        row.update(filename="ready-after-sync.jpg")
        materials.upsert(row)
        gt = annotations.get("m1")
        annotations.upsert(
            "m1", [{"label": "fire", "bbox": [2, 3, 4, 5]}],
            annotation_scope=["fire"], expected_version=gt["version"],
            project_material=False,
        )
        NegativePool(materials).category(category, name="fire-ready")

        early = sync.publish_ready(connection, project_dir=project, project_id="p6")
        assert early["published"] is False
        result = sync.synchronize_project(
            connection, project_dir=project, project_id="p6", limit=10
        )
        assert result["status"] == "READY", result
        state = connection.execute(
            f"SELECT snapshot_id,status FROM {SCHEMA_NAME}.picker_snapshot_state "
            "WHERE project_id='p6'"
        ).fetchone()
        assert state[1] == "READY" and state[0] != before
        marks = _marks(project)
        for stream, sequence in marks.items():
            assert _cursor(connection, "p6", stream) == sequence

def test_b3_export_high_water_then_new_event_is_not_lost(pg, tmp_path):
    project, materials, _, _, _ = _project(tmp_path, "p7")
    with psycopg.connect(pg.get_uri()) as connection:
        ensure_schema(connection)
        baseline = export_project_snapshot(project, "p7")
        assert baseline["change_high_water_marks"][MATERIAL_STREAM] >= 1
        import_project_snapshot(connection, baseline)
        baseline_marks = baseline["change_high_water_marks"]

        row = materials.get("m1")
        row.update(filename="after-export.jpg")
        materials.upsert(row)
        assert _marks(project)[MATERIAL_STREAM] > baseline_marks[MATERIAL_STREAM]

        _apply(connection, project, MATERIAL_STREAM, "p7")
        assert connection.execute(
            f"SELECT filename FROM {SCHEMA_NAME}.material WHERE project_id='p7' AND id='m1'"
        ).fetchone()[0] == "after-export.jpg"
