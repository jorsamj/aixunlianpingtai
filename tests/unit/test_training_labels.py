import pytest

from platform_core.training_labels import freeze_training_labels


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
