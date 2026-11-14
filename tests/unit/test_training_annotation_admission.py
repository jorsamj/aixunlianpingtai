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



def _original_row(image_id, labels, *, dataset="pool"):
    import hashlib
    return {
        "id": image_id,
        "dataset_id": dataset,
        "filename": image_id + ".jpg",
        "stored_name": image_id + ".jpg",
        "content_sha256": hashlib.sha256(image_id.encode()).hexdigest(),
        "size_bytes": 512,
        "width": 100, "height": 100,
        "annotation_state": "annotated",
        "annotation_scope": ["fire", "person"],
        "annotated": True,
        "boxes": [box(label) for label in labels],
    }


def _catalog_project(tmp_path):
    import json
    project = tmp_path / "project"
    project.mkdir()
    (project / "meta.json").write_text(
        json.dumps({"labels": ["fire", "person"], "label_meta": [
            {"code": "fire", "active": True}, {"code": "person", "active": True},
        ]}),
        encoding="utf-8",
    )
    return project


def _projected_contract():
    return {
        "effective_label_codes": ["fire"],
        "effective_label_schema": [{"code": "fire", "class_id": 0}],
    }


def test_source_audit_catches_bad_excluded_box_before_task_projection(tmp_path):
    from platform_core.training_tasks import _training_source_projection_admission
    from platform_core.training_label_tasks import project_training_rows

    project = _catalog_project(tmp_path)
    source = [_original_row("mixed", ["fire", "person"])]
    source[0]["boxes"][1]["x2"] = source[0]["boxes"][1]["x1"]
    contract = _projected_contract()
    projected = project_training_rows(source, contract)
    assert len(projected[0]["boxes"]) == 1
    with pytest.raises(ValueError, match="TRAINING_ANNOTATION_ADMISSION_BLOCKED"):
        _training_source_projection_admission(
            project, source, projected, contract["effective_label_schema"], contract,
        )


def test_legitimate_excluded_person_and_task_negative_are_verified(tmp_path):
    from platform_core.training_tasks import _training_source_projection_admission
    from platform_core.training_label_tasks import project_training_rows

    project = _catalog_project(tmp_path)
    original = [_original_row("mixed", ["fire", "person"]),
                _original_row("person-only", ["person"])]
    contract = _projected_contract()
    projected = project_training_rows(original, contract)
    assert projected[1]["annotation_state"] == "confirmed_empty"
    assert projected[1]["negative_origin"] == "redacted_unselected_labels"
    proof = _training_source_projection_admission(
        project, original, projected, contract["effective_label_schema"], contract,
    )
    assert proof["source_ground_truth_admission"]["severity_counts"]["blocking"] == 0
    assert proof["projection_consistency"]["verified_images"] == 2
    assert proof["projection_consistency"]["excluded_source_object_count"] == 2
    assert proof["projection_consistency"]["redacted_task_negative_image_count"] == 1


@pytest.mark.parametrize("field", [
    "boxes", "training_excluded_boxes",
    "training_projection_digest", "negative_origin", "annotation_scope",
])
def test_forged_projection_is_not_accepted_even_if_labels_seem_valid(tmp_path, field):
    from platform_core.training_tasks import _training_source_projection_admission
    from platform_core.training_label_tasks import project_training_rows

    project = _catalog_project(tmp_path)
    source = [_original_row("mixed", ["fire", "person"])]
    contract = _projected_contract()
    projected = project_training_rows(source, contract)
    if field in {"boxes", "training_excluded_boxes"}:
        projected[0][field] = []
    elif field == "annotation_scope":
        projected[0][field] = ["fire", "person"]
    else:
        projected[0][field] = "forged"
    with pytest.raises(ValueError, match="TRAINING_PROJECTION_MISMATCH"):
        _training_source_projection_admission(
            project, source, projected, contract["effective_label_schema"], contract,
        )


def test_new_freeze_source_projection_evidence_replays_after_original_gt_changes(tmp_path):
    from platform_core.training_splits import SplitMode, SplitRequest
    from platform_core.training_label_tasks import project_training_rows
    from platform_core.training_tasks import (
        TrainingSelectionResolution, freeze_training_inputs,
        resolve_training_input_freeze,
    )

    project = _catalog_project(tmp_path)
    originals = [_original_row("train-" + str(i), ["fire", "person"])
                 for i in range(4)]
    originals.append(_original_row("test-0", ["fire", "person"]))
    contract = _projected_contract()
    projected = project_training_rows(originals, contract)
    request = SplitRequest(
        mode=SplitMode.INDEPENDENT_TEST_SET,
        train_image_ids=tuple(row["id"] for row in originals[:4]),
        test_image_ids=("test-0",),
        validation_percent=25,
    )
    resolution = TrainingSelectionResolution(
        requested_split=request, effective_split=request,
        effective_images=tuple(originals),
        selected_train_image_ids=request.train_image_ids,
        pending_annotation_image_ids=(),
    )
    frozen = freeze_training_inputs(
        project, request, seed=17, selection_resolution=resolution,
        effective_images=projected,
        label_schema_override=contract["effective_label_schema"],
        label_contract=contract,
    )
    assert frozen["input_quality"]["projection_consistency"]["verified_images"] == 5
    assert frozen["input_quality"]["source_ground_truth_admission"]["audited_images"] == 5
    originals[0]["boxes"][0]["label"] = "person"
    _, _, _, snapshot = resolve_training_input_freeze(frozen, request, seed=17)
    assert snapshot["snapshot_id"] == frozen["snapshot_id"]



def test_disabled_entire_project_catalog_cannot_approve_excluded_source_gt(tmp_path):
    import json
    from platform_core.training_tasks import _training_source_projection_admission
    from platform_core.training_label_tasks import project_training_rows

    project = _catalog_project(tmp_path)
    meta_file = project / "meta.json"
    catalog = json.loads(meta_file.read_text(encoding="utf-8"))
    for label in catalog["label_meta"]:
        label["active"] = False
    meta_file.write_text(json.dumps(catalog), encoding="utf-8")
    source = [_original_row("inactive-source", ["fire", "person"])]
    contract = _projected_contract()
    projected = project_training_rows(source, contract)
    with pytest.raises(ValueError, match="TRAINING_ANNOTATION_ADMISSION_BLOCKED"):
        _training_source_projection_admission(
            project, source, projected, contract["effective_label_schema"], contract,
        )
