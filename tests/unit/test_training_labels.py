import json

import pytest

from platform_core.annotation_repository import AnnotationRepository
from platform_core.material_repository import MaterialRepository
from platform_core.training_labels import aggregate_training_labels, freeze_training_labels


def report(groups):
    return {
        "available_training_labels": [
            {"label_id": "fire-id", "code": "fire", "display_name": "明火", "class_id": 0},
            {"label_id": "face-id", "code": "face", "display_name": "人脸", "class_id": 1},
        ],
        "duplicate_content_groups": groups,
    }


def member(image_id, scope, boxes, state="annotated"):
    return {
        "image_id": image_id,
        "annotation_state": state,
        "annotation_scope": scope,
        "boxes": boxes,
    }


def box(label_id, x1):
    return {"label_id": label_id, "x1": x1, "y1": 1.0, "x2": x1 + 10.0, "y2": 11.0}


def test_selected_duplicate_gt_conflict_is_rejected_before_training_task_creation():
    value = report([
        {
            "content_sha256": "same-image",
            "members": [
                member("a", ["fire-id"], [box("fire-id", 1.0)]),
                member("b", ["fire-id"], [box("fire-id", 2.0)]),
            ],
        }
    ])
    with pytest.raises(ValueError, match="duplicate annotation conflict"):
        freeze_training_labels(value, ["fire-id"])


def test_duplicate_difference_in_unselected_label_does_not_block_training():
    value = report([
        {
            "content_sha256": "same-image",
            "members": [
                member("a", ["fire-id", "face-id"], [box("fire-id", 1.0), box("face-id", 5.0)]),
                member("b", ["fire-id", "face-id"], [box("fire-id", 1.0)]),
            ],
        }
    ])
    frozen = freeze_training_labels(value, ["fire-id"])
    assert [row["label_id"] for row in frozen["labels"]] == ["fire-id"]


def test_duplicate_member_with_incomplete_scope_is_not_compared_as_legal_gt():
    value = report([
        {
            "content_sha256": "same-image",
            "members": [
                member("a", ["fire-id", "face-id"], [box("fire-id", 1.0), box("face-id", 5.0)]),
                member("b", ["fire-id"], [box("fire-id", 2.0)]),
            ],
        }
    ])
    frozen = freeze_training_labels(value, ["fire-id", "face-id"])
    assert [row["label_id"] for row in frozen["labels"]] == ["fire-id", "face-id"]


def test_equal_selected_duplicate_gt_is_allowed_for_worker_canonical_dedupe():
    value = report([
        {
            "content_sha256": "same-image",
            "members": [
                member("a", ["fire-id"], [box("fire-id", 1.0)]),
                member("b", ["fire-id"], [box("fire-id", 1.0)]),
            ],
        }
    ])
    frozen = freeze_training_labels(value, ["fire-id"])
    assert frozen["labels"][0]["yolo_class_id"] == 0


def _label_schema():
    return [
        {
            "label_id": "fire-id",
            "code": "fire",
            "display_name": "明火",
            "class_id": 0,
            "status": "active",
        }
    ]


def _material(project_path, *, labels=None, label_ids=None):
    return MaterialRepository(project_path).upsert(
        {
            "id": "image-a",
            "filename": "a.jpg",
            "object_key": "uploads/a.jpg",
            "content_sha256": "a" * 64,
            "size_bytes": 123,
            "width": 100,
            "height": 100,
            "labels": list(labels or []),
            "label_ids": list(label_ids or []),
        }
    )


def _write_project_label_schema(project_path):
    (project_path / "meta.json").write_text(
        json.dumps(
            {
                "id": "project-1",
                "labels": ["fire"],
                "label_meta": [
                    {"code": "fire", "label_id": "fire-id", "status": "active"}
                ],
            }
        ),
        encoding="utf-8",
    )


def test_material_labels_alone_never_create_training_ground_truth(tmp_path):
    """Material tags are search/filter metadata, not a second GT source."""
    _material(tmp_path, labels=["fire"], label_ids=["fire-id"])

    aggregated = aggregate_training_labels(tmp_path, ["image-a"], [], _label_schema())

    assert aggregated["available_training_labels"] == []
    with pytest.raises(ValueError, match="训练标签不属于本次所选素材"):
        freeze_training_labels(aggregated, ["fire-id"])


def test_annotation_repository_gt_is_trainable_even_without_material_label_tags(tmp_path):
    """Training semantics come from AnnotationRepository state/scope/boxes only."""
    _write_project_label_schema(tmp_path)
    _material(tmp_path, labels=[], label_ids=[])
    AnnotationRepository(tmp_path).upsert(
        "image-a",
        [
            {
                "id": "box-1",
                "label_id": "fire-id",
                "label": "fire",
                "class_id": 0,
                "x1": 10,
                "y1": 10,
                "x2": 30,
                "y2": 40,
            }
        ],
        annotation_state="annotated",
        annotation_scope=["fire-id"],
    )

    aggregated = aggregate_training_labels(tmp_path, ["image-a"], [], _label_schema())
    frozen = freeze_training_labels(aggregated, ["fire-id"])

    assert aggregated["available_training_labels"][0]["positive_images"] == 1
    assert aggregated["available_training_labels"][0]["boxes"] == 1
    assert frozen["labels"][0]["label_id"] == "fire-id"
    assert frozen["labels"][0]["yolo_class_id"] == 0
