import pytest

from platform_core.annotations import annotation_summary, normalize_boxes, restore_box_provenance


def test_invalid_coordinates_are_rejected():
    with pytest.raises(ValueError, match="坐标"):
        normalize_boxes(
            [{"label": "fire", "x1": 20, "y1": 10, "x2": 10, "y2": 30}],
            100,
            100,
            {"fire": 0},
        )


def test_summary_contains_preview_and_status():
    boxes = normalize_boxes(
        [
            {"label": "fire", "x1": 1, "y1": 2, "x2": 20, "y2": 30},
            {"label": "fire", "x1": 30, "y1": 2, "x2": 50, "y2": 30},
            {"label": "smoke", "x1": 2, "y1": 40, "x2": 40, "y2": 70},
        ],
        100,
        100,
        {"fire": 0, "smoke": 1},
    )
    summary = annotation_summary(boxes)
    assert summary["labels"] == ["fire", "smoke"]
    assert summary["label_counts"] == {"fire": 2, "smoke": 1}
    assert summary["box_count"] == 3
    assert summary["annotation_status"] == "annotated"
    assert summary["annotation_preview"][0]["label"] == "fire"



def test_restore_box_provenance_preserves_server_truth_and_marks_new_boxes_manual():
    existing = [{
        "id": "ai-box",
        "class_id": 0,
        "label": "fire",
        "x1": 1,
        "y1": 2,
        "x2": 20,
        "y2": 30,
        "source": "ai_candidate_confirmed",
        "source_task_id": "task-1",
        "candidate_id": "candidate-1",
        "confidence": 0.91,
    }]
    normalized = normalize_boxes(
        [
            {"id": "ai-box", "label": "fire", "x1": 2, "y1": 3, "x2": 22, "y2": 32},
            {"id": "manual-box", "label": "smoke", "x1": 30, "y1": 10, "x2": 60, "y2": 40,
             "source": "ai_candidate_confirmed"},
        ],
        100,
        100,
        {"fire": 0, "smoke": 1},
    )

    restored = restore_box_provenance(normalized, existing)

    assert restored[0]["source"] == "ai_candidate_confirmed"
    assert restored[0]["source_task_id"] == "task-1"
    assert restored[0]["candidate_id"] == "candidate-1"
    assert restored[0]["confidence"] == 0.91
    assert restored[1]["source"] == "manual"
    assert annotation_summary(restored)["annotation_origin"] == "mixed"
