import json
import sqlite3

from platform_core.annotation_repository import AnnotationRepository
from platform_core.material_repository import MaterialRepository


def test_confirmed_empty_scope_is_persisted_and_changes_digest(tmp_path):
    repository = AnnotationRepository(tmp_path)
    first = repository.upsert(
        "image-1",
        [],
        annotation_state="confirmed_empty",
        annotation_scope=["cigarette"],
    )
    first_digest = first["content_digest"]

    second = repository.upsert(
        "image-1",
        [],
        annotation_state="confirmed_empty",
        annotation_scope=["smoke", "cigarette", "smoke"],
    )

    assert second["annotation_scope"] == ["cigarette", "smoke"]
    assert second["version"] == 2
    assert second["content_digest"] != first_digest


def test_confirmed_empty_without_explicit_scope_uses_global_scope(tmp_path):
    repository = AnnotationRepository(tmp_path)
    saved = repository.upsert(
        "image-global-negative",
        [],
        annotation_state="confirmed_empty",
    )

    assert saved["annotation_scope"] == ["*"]


def test_annotated_scope_defaults_to_box_labels(tmp_path):
    repository = AnnotationRepository(tmp_path)
    saved = repository.upsert(
        "image-2",
        [
            {
                "label": "cigarette",
                "class_id": 0,
                "x1": 1,
                "y1": 2,
                "x2": 10,
                "y2": 12,
            }
        ],
        annotation_state="annotated",
    )

    assert saved["annotation_scope"] == ["cigarette"]


def test_unannotated_never_keeps_scope(tmp_path):
    repository = AnnotationRepository(tmp_path)
    saved = repository.upsert(
        "image-3",
        [],
        annotation_state="unannotated",
        annotation_scope=["cigarette"],
    )

    assert saved["annotation_scope"] == []


def test_annotation_scope_and_digest_are_projected_to_material_repository(tmp_path):
    materials = MaterialRepository(tmp_path)
    materials.upsert(
        {
            "id": "image-4",
            "filename": "image-4.jpg",
            "stored_name": "image-4.jpg",
            "object_key": "uploads/image-4.jpg",
            "processing_status": "processed",
        }
    )
    repository = AnnotationRepository(tmp_path)
    saved = repository.upsert(
        "image-4",
        [],
        annotation_state="confirmed_empty",
        annotation_scope=["cigarette"],
    )

    material = materials.get("image-4")
    assert material is not None
    assert material["annotation_state"] == "confirmed_empty"
    assert material["annotation_scope"] == ["cigarette"]
    assert material["annotation_hash"] == saved["content_digest"]
    assert material["annotated"] is True
    assert material["box_count"] == 0


def test_existing_annotation_database_is_migrated_without_rebuild(tmp_path):
    path = tmp_path / "annotations.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute(
            """
            CREATE TABLE annotations (
                image_id TEXT PRIMARY KEY,
                annotation_state TEXT NOT NULL,
                version INTEGER NOT NULL,
                content_digest TEXT NOT NULL,
                boxes_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        db.execute(
            "INSERT INTO annotations VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "legacy",
                "annotated",
                4,
                "legacy-digest",
                json.dumps([
                    {
                        "label": "fire",
                        "class_id": 0,
                        "x1": 1,
                        "y1": 1,
                        "x2": 5,
                        "y2": 5,
                    }
                ]),
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
            ),
        )

    repository = AnnotationRepository(tmp_path)
    loaded = repository.get("legacy")

    assert loaded["version"] == 4
    assert loaded["boxes"][0]["label"] == "fire"
    assert loaded["annotation_scope"] == []
    with sqlite3.connect(path) as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(annotations)")}
    assert "scope_json" in columns
