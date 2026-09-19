from __future__ import annotations

from pathlib import Path

import pytest

from platform_core.online_feedback import (
    OnlineFeedbackRepository,
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
