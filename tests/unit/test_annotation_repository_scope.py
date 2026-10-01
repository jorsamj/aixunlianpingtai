import json
import sqlite3
import threading
import time

import pytest

from platform_core.annotation_repository import (
    AnnotationLabelStateError,
    AnnotationRepository,
)
from platform_core.labels import label_governance_fence
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



def _write_project_labels(project, *, smoke_active=True):
    project.mkdir(parents=True, exist_ok=True)
    (project / "meta.json").write_text(
        json.dumps({
            "labels": ["fire", "smoke"],
            "label_meta": [
                {"code": "fire", "status": "active", "active": True},
                {
                    "code": "smoke",
                    "status": "active" if smoke_active else "inactive",
                    "active": bool(smoke_active),
                },
            ],
        }),
        encoding="utf-8",
    )


def test_annotation_upsert_rechecks_active_labels_after_governance_wait(tmp_path):
    project = tmp_path / "project"
    _write_project_labels(project, smoke_active=True)
    repository = AnnotationRepository(project)
    started = threading.Event()
    outcome = {}

    def writer():
        started.set()
        try:
            repository.upsert(
                "race-image",
                [{"label": "smoke", "class_id": 1}],
                annotation_state="annotated",
                annotation_scope=["smoke"],
                project_material=False,
            )
        except BaseException as error:
            outcome["error"] = error

    with label_governance_fence(project, timeout=5):
        worker = threading.Thread(target=writer, daemon=True)
        worker.start()
        assert started.wait(1)
        time.sleep(0.05)
        assert worker.is_alive()
        _write_project_labels(project, smoke_active=False)

    worker.join(5)
    assert not worker.is_alive()
    assert isinstance(outcome.get("error"), AnnotationLabelStateError)
    assert not repository.exists("race-image")


def test_remap_rejects_target_that_became_inactive(tmp_path):
    project = tmp_path / "project"
    _write_project_labels(project, smoke_active=True)
    repository = AnnotationRepository(project)
    repository.upsert(
        "image-1",
        [{"label": "fire", "class_id": 0}],
        annotation_state="annotated",
        annotation_scope=["fire"],
        project_material=False,
    )
    current = repository.get("image-1")
    digest = repository.record_digest(current)
    _write_project_labels(project, smoke_active=False)

    with pytest.raises(AnnotationLabelStateError, match="smoke"):
        repository.remap_labels_if_digests(
            [{"image_id": "image-1", "expected_digest": digest}],
            source_label="fire",
            target_label="smoke",
            target_class_id=1,
            project_material=False,
        )

    assert repository.get("image-1")["boxes"][0]["label"] == "fire"


def test_delete_backup_remains_label_reference_and_restore_fails_closed(tmp_path):
    project = tmp_path / "project"
    _write_project_labels(project, smoke_active=True)
    repository = AnnotationRepository(project)
    repository.upsert(
        "delete-me",
        [{"label": "smoke", "class_id": 1}],
        annotation_state="annotated",
        annotation_scope=["smoke"],
        project_material=False,
    )
    token = "delete-token"
    assert repository.prepare_delete(token, ["delete-me"]) == 1
    assert repository.finalize_delete(token) == 1
    assert not repository.exists("delete-me")

    assert repository.label_reference_preview(["smoke"]) == {
        "positive_images": 1,
        "scope_images": 1,
        "affected_images": 1,
        "boxes": 1,
    }
    assert repository.reference_image_ids(["smoke"]) == ["delete-me"]

    _write_project_labels(project, smoke_active=False)
    with pytest.raises(AnnotationLabelStateError, match="smoke"):
        repository.restore_delete(token)
    assert repository.delete_backup_count(token) == 1
    assert not repository.exists("delete-me")

    _write_project_labels(project, smoke_active=True)
    assert repository.restore_delete(token) == 1
    assert repository.exists("delete-me")
    assert repository.delete_backup_count(token) == 0
