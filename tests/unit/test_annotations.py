import pytest

from platform_core.annotations import annotation_summary, normalize_boxes


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
        [{"label": "fire", "x1": 1, "y1": 2, "x2": 20, "y2": 30}],
        100,
        100,
        {"fire": 0},
    )
    summary = annotation_summary(boxes)
    assert summary["labels"] == ["fire"]
    assert summary["box_count"] == 1
    assert summary["annotation_status"] == "annotated"
    assert summary["annotation_preview"][0]["label"] == "fire"

