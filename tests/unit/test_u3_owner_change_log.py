"""U3-P3-B1 owner change-log contracts (isolated SQLite fixtures only)."""
from contextlib import closing
import json
import sqlite3

from platform_core.annotation_repository import AnnotationRepository
from platform_core import material_repository_batch as material_batch_module
from platform_core.material_repository import MaterialRepository
from platform_core.negative_pool import NegativePool
from platform_core.u3_owner_change_log import (
    ANNOTATION_STREAM,
    MATERIAL_STREAM,
    NEGATIVE_POOL_STREAM,
    high_water_marks,
    read_events,
)


def _events(path, stream):
    with closing(sqlite3.connect(path)) as database:
        database.row_factory = sqlite3.Row
        return read_events(database, stream, 0, 1000)


def _material(materials, image_id="m1", **extra):
    record = {
        "id": image_id,
        "filename": f"{image_id}.jpg",
        "object_key": f"uploads/{image_id}.jpg",
        "content_sha256": f"{int(image_id[-1]):064x}",
        "processing_status": "ready",
    }
    record.update(extra)
    return materials.upsert(record)


def test_material_events_are_immutable_and_share_the_write_transaction(tmp_path):
    materials = MaterialRepository(tmp_path / "project")
    _material(materials, labels=["fire"], label_counts={"fire": 1})
    _material(materials, labels=["fire", "smoke"], label_counts={"fire": 1, "smoke": 1})

    events = _events(materials.path, MATERIAL_STREAM)
    assert [event["sequence"] for event in events] == [1, 2]
    assert events[0]["payload_digest"] != events[1]["payload_digest"]
    assert events[0]["payload"]["labels"] == [{"label_code": "fire", "box_count": 1}]
    assert events[1]["payload"]["labels"] == [
        {"label_code": "fire", "box_count": 1},
        {"label_code": "smoke", "box_count": 1},
    ]

    with closing(materials._connect()) as database:
        before = high_water_marks(database)[MATERIAL_STREAM]
        database.execute("BEGIN IMMEDIATE")
        MaterialRepository._write_row(
            database,
            {
                "id": "rolled-back",
                "filename": "rolled-back.jpg",
                "object_key": "uploads/rolled-back.jpg",
            },
            _previous_payload=None,
        )
        database.execute("ROLLBACK")
        after = high_water_marks(database)[MATERIAL_STREAM]
    assert after == before
    assert not materials.get("rolled-back")


def test_material_delete_writes_a_tombstone(tmp_path):
    materials = MaterialRepository(tmp_path / "project")
    _material(materials, labels=["fire"], label_counts={"fire": 1})
    materials.remove(["m1"])

    events = _events(materials.path, MATERIAL_STREAM)
    assert events[-1]["event_kind"] == "delete"
    assert events[-1]["entity_id"] == "m1"
    assert events[-1]["payload"]["deleted"] is True
    assert events[-1]["payload"]["last_payload"]["labels"] == ["fire"]


def test_annotation_upsert_and_remove_use_the_annotation_stream(tmp_path):
    project = tmp_path / "project"
    annotations = AnnotationRepository(project)
    annotations.upsert(
        "m1",
        [{"label": "fire", "bbox": [1, 2, 3, 4]}],
        annotation_scope=["fire"],
        project_material=False,
    )
    annotations.remove(["m1"])

    events = _events(annotations.path, ANNOTATION_STREAM)
    assert [event["sequence"] for event in events] == [1, 2]
    assert events[0]["payload"]["version"] == 1
    assert events[0]["payload"]["label_references"] == [
        {
            "label_code": "fire",
            "box_count": 1,
            "scope_ref": 1,
            "annotation_state": "annotated",
            "source_kind": "sqlite",
        }
    ]
    assert events[1]["event_kind"] == "delete"


def test_negative_pool_has_its_own_stream_and_snapshots(tmp_path):
    materials = MaterialRepository(tmp_path / "project")
    _material(materials)
    pool = NegativePool(materials)
    category = pool.category(name="fire")
    pool.members(["m1"], category_ids=[category["id"]])

    with closing(materials._connect()) as database:
        marks = high_water_marks(database)
    assert marks == {MATERIAL_STREAM: 1, NEGATIVE_POOL_STREAM: 2}

    events = _events(materials.path, NEGATIVE_POOL_STREAM)
    assert [event["entity_type"] for event in events] == [
        "negative_pool_category",
        "negative_pool_member",
    ]
    member = events[1]["payload"]
    assert member["material_id"] == "m1"
    assert member["member"]["joined_at"]
    assert member["links"] == [{"category_id": category["id"]}]
    assert member["algorithms"] == []


def test_old_database_gets_the_log_additively(tmp_path):
    project = tmp_path / "project"
    materials = MaterialRepository(project)
    _material(materials)
    with closing(sqlite3.connect(materials.path)) as database:
        database.executescript(
            "DROP TABLE owner_change_log; DROP TABLE owner_change_meta;"
        )
        database.commit()

    material_batch_module._MATERIAL_INIT_READY.discard(materials.path.resolve())
    reopened = MaterialRepository(project)
    assert reopened.get("m1")["labels"] == []
    with closing(reopened._connect()) as database:
        marks = high_water_marks(database)
        tables = {
            str(row[0])
            for row in database.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert marks == {MATERIAL_STREAM: 0, NEGATIVE_POOL_STREAM: 0}
    assert {"owner_change_log", "owner_change_meta"} <= tables
