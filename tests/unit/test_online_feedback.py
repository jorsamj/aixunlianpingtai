from __future__ import annotations

from pathlib import Path

import pytest

from platform_core.online_feedback import (
    OnlineFeedbackRepository,
    build_supplement_candidate,
    build_supplement_candidate_set,
    build_supplement_training_provenance,
    public_feedback,
    validate_prediction_evidence,
)
from platform_core.material_repository import MaterialRepository


def evidence():
    return {
        "schema_version": 1,
        "prediction_id": "abc123def456",
        "algorithm_id": "algorithm-1",
        "version_id": "version-1",
        "model_sha256": "a" * 64,
        "input_sha256": "b" * 64,
        "original_filename": "sample.jpg",
        "input_file": "abc123def456_input.jpg",
        "width": 100,
        "height": 80,
        "confidence": 0.25,
        "engine": "ultralytics",
        "detections": [{
            "class_id": 0, "label": "smoke", "confidence": 0.91,
            "x1": 10, "y1": 12, "x2": 40, "y2": 50,
        }],
        "created_at": "2026-09-19T00:00:00+00:00",
    }


def test_prediction_evidence_is_bounded_and_normalized():
    value = validate_prediction_evidence(evidence())
    assert value["prediction_id"] == "abc123def456"
    assert value["detections"][0]["label"] == "smoke"
    broken = evidence()
    broken["detections"][0]["x2"] = 101
    with pytest.raises(ValueError, match="outside image bounds"):
        validate_prediction_evidence(broken)


def test_feedback_stage_and_finalize_are_idempotent(tmp_path: Path):
    repo = OnlineFeedbackRepository(tmp_path)
    first, repeated = repo.stage(
        evidence(), feedback_type="needs_correction", note="漏检",
        created_at="2026-09-19T00:00:00+00:00",
    )
    assert repeated is False
    second, repeated = repo.stage(
        evidence(), feedback_type="needs_correction", note="漏检",
        created_at="2026-09-19T00:01:00+00:00",
    )
    assert repeated is True
    assert second["id"] == first["id"]

    finalized, repeated = repo.finalize(
        first["id"], expected_feedback_type="needs_correction",
        material_id="material-1", result={"annotation_action": "manual_review"},
        confirmed_at="2026-09-19T00:02:00+00:00",
    )
    assert repeated is False
    assert finalized["status"] == "confirmed"
    again, repeated = repo.finalize(
        first["id"], expected_feedback_type="needs_correction",
        material_id="material-1", result={"annotation_action": "manual_review"},
        confirmed_at="2026-09-19T00:03:00+00:00",
    )
    assert repeated is True
    assert again["material_id"] == "material-1"


def test_feedback_public_projection_never_exposes_internal_input_file(tmp_path: Path):
    repo = OnlineFeedbackRepository(tmp_path)
    row, _ = repo.stage(
        evidence(), feedback_type="correct", note="抽检正确",
        created_at="now",
    )
    public = public_feedback(row)
    assert "input_file" not in public["source"]
    assert public["source"]["input_sha256"] == "b" * 64


def test_material_lookup_reuses_content_identity(tmp_path: Path):
    repo = MaterialRepository(tmp_path)
    repo.upsert({
        "id": "material-1", "filename": "one.jpg",
        "storage_source_id": "default_local", "storage_type": "local",
        "object_key": "uploads/material-1.jpg", "content_sha256": "c" * 64,
    })
    assert repo.get_by_content_sha256("C" * 64)["id"] == "material-1"
    assert repo.get_by_content_sha256("bad") is None


def test_prediction_evidence_preserves_bounded_external_provenance():
    value = evidence()
    value.update({
        "source_channel": "external_upload",
        "external_source": "edge-gateway-01",
        "external_sample_id": "camera-12-0001",
    })
    normalized = validate_prediction_evidence(value)
    assert normalized["source_channel"] == "external_upload"
    assert normalized["external_source"] == "edge-gateway-01"
    assert normalized["external_sample_id"] == "camera-12-0001"


def test_confirmed_feedback_candidate_freezes_current_annotation_identity(tmp_path: Path):
    repo = OnlineFeedbackRepository(tmp_path)
    staged, _ = repo.stage(
        evidence(), feedback_type="correct", note="可补数据",
        created_at="2026-09-19T00:00:00+00:00",
    )
    confirmed, _ = repo.finalize(
        staged["id"], expected_feedback_type="correct",
        material_id="material-1",
        result={"annotation_action": "prediction_confirmed_as_truth"},
        confirmed_at="2026-09-19T00:01:00+00:00",
    )
    material = {
        "id": "material-1",
        "content_sha256": "b" * 64,
        "annotation_state": "annotated",
        "annotation_hash": "c" * 64,
    }
    annotation = {
        "annotation_state": "annotated",
        "content_digest": "c" * 64,
        "annotation_scope": ["smoke"],
        "boxes": [{"label": "smoke"}],
    }
    candidate = build_supplement_candidate(confirmed, material, annotation)
    assert candidate["eligible"] is True
    assert candidate["annotation_hash"] == "c" * 64
    assert candidate["labels"] == ["smoke"]
    assert len(candidate["candidate_digest"]) == 64

    action = {
        "status": "confirmed", "action": "supplement_data",
        "action_id": "d" * 64,
        "source": {"algorithm_id": "algorithm-1", "version_id": "version-1"},
    }
    frozen = build_supplement_candidate_set(
        action, [candidate], frozen_at="2026-09-19T00:02:00+00:00",
    )
    assert frozen["feedback_ids"] == [confirmed["id"]]
    assert frozen["material_ids"] == ["material-1"]
    assert frozen["automatic_execution"] is False


def test_needs_correction_candidate_waits_for_formal_annotation(tmp_path: Path):
    repo = OnlineFeedbackRepository(tmp_path)
    staged, _ = repo.stage(
        evidence(), feedback_type="needs_correction", note="漏检",
        created_at="2026-09-19T00:00:00+00:00",
    )
    confirmed, _ = repo.finalize(
        staged["id"], expected_feedback_type="needs_correction",
        material_id="material-1",
        result={"annotation_action": "manual_annotation_required"},
        confirmed_at="2026-09-19T00:01:00+00:00",
    )
    material = {"id": "material-1", "content_sha256": "b" * 64}
    pending = build_supplement_candidate(
        confirmed, material, {"annotation_state": "unannotated", "boxes": []},
    )
    assert pending["eligible"] is False
    assert "ANNOTATION_REQUIRED" in pending["reason_codes"]


def test_supplement_training_provenance_freezes_actual_subset_and_rejects_stale_truth():
    action = {
        "status": "confirmed", "action": "supplement_data", "action_id": "1" * 64,
        "source": {"algorithm_id": "alg-1", "version_id": "ver-1"},
    }
    candidates = []
    for index in range(2):
        candidates.append({
            "eligible": True,
            "feedback_id": f"feedback-{index}",
            "feedback_type": "correct",
            "material_id": f"material-{index}",
            "candidate_digest": str(index + 2) * 64,
            "annotation_hash": str(index + 4) * 64,
            "annotation_state": "annotated",
            "labels": ["smoke"],
            "model_sha256": "a" * 64,
            "input_sha256": str(index + 6) * 64,
            "confirmed_at": "2026-09-19T00:00:00Z",
            "algorithm_id": "alg-1",
            "version_id": "ver-1",
        })
    candidate_set = build_supplement_candidate_set(
        action, candidates, frozen_at="2026-09-19T00:01:00Z",
    )
    truth = [{
        "id": "material-1", "content_sha256": "7" * 64,
        "annotation_hash": "5" * 64, "annotation_state": "annotated",
    }]
    provenance = build_supplement_training_provenance(
        candidate_set, ["material-1", "normal-material"], truth,
    )
    assert provenance["candidate_set_id"] == candidate_set["candidate_set_id"]
    assert provenance["adopted_feedback_ids"] == ["feedback-1"]
    assert provenance["adopted_material_ids"] == ["material-1"]
    assert provenance["adopted_candidate_count"] == 1
    assert provenance["source_candidate_count"] == 2
    assert provenance["automatic_execution"] is False

    with pytest.raises(ValueError, match="annotation changed"):
        build_supplement_training_provenance(
            candidate_set,
            ["material-1"],
            [dict(truth[0], annotation_hash="f" * 64)],
        )
