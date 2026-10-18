"""Read-only freeze-time formal Ground Truth admission (TQ-03)."""
import math

import pytest

from platform_core.training_tasks import _training_annotation_admission


SCHEMA = [{"code": "fire", "class_id": 0}, {"code": "smoke", "class_id": 1}]


def image(image_id, boxes, *, state="annotated", width=100, height=100, **extras):
    return {
        "id": image_id,
        "width": width,
        "height": height,
        "annotation_state": state,
        "annotation_scope": ["*"] if state == "confirmed_empty" else ["fire", "smoke"],
        "boxes": boxes,
        **extras,
    }


def box(label="fire", **overrides):
    return {"label": label, "x1": 10, "y1": 10, "x2": 40, "y2": 40, **overrides}


@pytest.mark.parametrize(("candidate", "code"), [
    (box(x1=-1), "box_out_of_bounds"),
    (box(x1=40), "box_invalid"),
    (box(x2=120), "box_out_of_bounds"),
    (box(x1=math.nan), "box_invalid"),
    (box(label="not-an-active-class"), "label_unknown"),
    ({"label": "fire", "cx": 0.95, "cy": 0.5, "w": 0.2, "h": 0.2},
     "box_out_of_bounds"),
    ({"label": "fire", "cx": 0.5, "cy": 0.5, "w": 0, "h": 0.2},
     "box_invalid"),
])
def test_training_freeze_blocks_invalid_active_label_or_geometry(candidate, code):
    with pytest.raises(ValueError, match="TRAINING_ANNOTATION_ADMISSION_BLOCKED") as exc:
        _training_annotation_admission([image("bad-1", [candidate])], SCHEMA)
    assert code in str(exc.value)
    assert "bad-1" in str(exc.value)


def test_duplicate_and_tiny_boxes_require_review_but_do_not_rewrite_gt():
    original = [
        image("normal", [box(), box()]),
        image("tiny", [box(x1=1, y1=1, x2=2, y2=2)]),
    ]
    before = repr(original)
    result = _training_annotation_admission(original, SCHEMA)
    assert result["severity_counts"]["blocking"] == 0
    assert result["severity_counts"]["manual_review"] >= 2
    assert result["issue_counts"]["box_duplicate_exact"] == 1
    assert result["issue_counts"]["box_tiny"] == 1
    assert result["gt_mutated"] is False
    assert repr(original) == before


def test_confirmed_empty_is_valid_negative_and_unverified_dimensions_are_visible():
    rows = [
        image("negative", [], state="confirmed_empty"),
        image("needs-source-dimension", [box()], width=0, height=0),
        image("normalized-positive", [
            {"label": "smoke", "cx": 0.5, "cy": 0.5, "w": 0.25, "h": 0.25},
        ]),
    ]
    result = _training_annotation_admission(rows, SCHEMA)
    assert result["audited_images"] == 3
    assert result["images_with_unverified_dimensions"] == 1
    assert result["severity_counts"]["blocking"] == 0
    assert "needs-source-dimension" in result["sample_image_ids_by_severity"]["manual_review"]


def test_state_mismatch_or_non_mapping_box_is_blocked():
    with pytest.raises(ValueError, match="annotation_state_inconsistent"):
        _training_annotation_admission(
            [image("broken-negative", [box()], state="confirmed_empty")], SCHEMA)
    with pytest.raises(ValueError, match="box_invalid"):
        _training_annotation_admission(
            [image("broken-box", ["broken-object"])], SCHEMA)


def test_busy_frame_skips_quadratic_iou_audit_but_retains_exact_duplicate_checks():
    many = [box(x1=i / 1000, y1=i / 1000,
                x2=20 + i / 1000, y2=20 + i / 1000) for i in range(40)]
    many.append(dict(many[0]))
    result = _training_annotation_admission([image("crowded", many)], SCHEMA)
    assert result["severity_counts"]["blocking"] == 0
    assert result["issue_counts"]["box_pairwise_unchecked"] == 1
    assert result["issue_counts"]["box_duplicate_exact"] >= 1
