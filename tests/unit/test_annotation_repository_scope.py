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


def test_annotation_reference_index_covers_annotated_scope_and_material_projection(tmp_path):
    materials = MaterialRepository(tmp_path)
    materials.upsert(
        {
            "id": "scope-only",
            "filename": "scope-only.jpg",
            "stored_name": "scope-only.jpg",
            "object_key": "uploads/scope-only.jpg",
            "processing_status": "processed",
        }
    )
    repository = AnnotationRepository(tmp_path)
    repository.upsert(
        "scope-only",
        [{"label": "helmet", "class_id": 8}],
        annotation_state="annotated",
        annotation_scope=["head", "helmet"],
    )

    truth = repository.label_reference_preview(["head"])
    projection = materials.label_reference_preview(["head"])

    assert truth == {
        "positive_images": 0,
        "scope_images": 1,
        "affected_images": 1,
        "boxes": 0,
    }
    assert projection == truth


def test_annotation_reference_index_rebuilds_legacy_fallback_and_tracks_mutations(tmp_path):
    legacy_dir = tmp_path / "annotations"
    legacy_dir.mkdir()
    (legacy_dir / "legacy.json").write_text(
        json.dumps(
            {
                "image_id": "legacy",
                "annotation_state": "annotated",
                "annotation_scope": ["head"],
                "boxes": [
                    {"label": "head", "class_id": 12},
                    {"code": "head", "class_id": 12},
                ],
            }
        ),
        encoding="utf-8",
    )
    repository = AnnotationRepository(tmp_path)

    repository.rebuild_reference_index()
    assert repository.label_reference_preview(["head"]) == {
        "positive_images": 1,
        "scope_images": 1,
        "affected_images": 1,
        "boxes": 2,
    }
    assert repository.reference_image_ids(["head"]) == ["legacy"]

    current = repository.get("legacy")
    applied = repository.remap_labels_if_digests(
        [{"image_id": "legacy", "expected_digest": repository.record_digest(current)}],
        source_label="head",
        target_label="safetyhelmet",
        target_class_id=8,
        project_material=False,
    )
    assert applied[0]["status"] == "applied"
    assert repository.label_reference_preview(["head"])["affected_images"] == 0
    assert repository.label_reference_preview(["safetyhelmet"])["boxes"] == 2

    repository.remove(["legacy"])
    assert repository.label_reference_preview(["safetyhelmet"])["affected_images"] == 0


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
    assert loaded["annotation_scope"] == ["fire"]
    with sqlite3.connect(path) as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(annotations)")}
    assert "scope_json" in columns
