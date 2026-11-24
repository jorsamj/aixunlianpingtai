from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from platform_core.online_feedback import (
    CANDIDATE_ONLY_FEEDBACK_TYPES,
    CORRECTION_KINDS,
    DIRECT_TRUTH_FEEDBACK_TYPES,
    OnlineFeedbackRepository,
    build_supplement_candidate,
    build_supplement_candidate_set,
    build_supplement_training_provenance,
    normalize_correction_kind,
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


def test_pending_correct_label_reference_is_bounded_and_released(tmp_path: Path):
    repo = OnlineFeedbackRepository(tmp_path)
    staged, _ = repo.stage(
        evidence(), feedback_type="correct", note="review",
        created_at="2026-10-09T00:00:00Z",
    )
    assert repo.pending_label_reference(["smoke", "烟雾"]) == staged["id"]
    assert repo.pending_label_reference(["helmet"]) == ""
    assert repo.pending_label_reference([]) == ""
    repo.finalize(
        staged["id"], expected_feedback_type="correct",
        material_id="material-1", result={"annotation_action": "manual_review"},
        confirmed_at="2026-10-09T00:01:00Z",
    )
    assert repo.pending_label_reference(["smoke"]) == ""


def test_evaluation_feedback_never_becomes_supplement_candidate(tmp_path):
    repo=OnlineFeedbackRepository(tmp_path)
    source=evidence(); source["source_channel"]="evaluation"
    row,_=repo.stage(source,feedback_type="correct",note="",created_at="now")
    row,_=repo.finalize(row["id"],expected_feedback_type="correct",material_id="m1",result={},confirmed_at="now")
    candidate=build_supplement_candidate(row,{"id":"m1","content_sha256":"b"*64},
        {"annotation_state":"annotated","content_digest":"c"*64,"boxes":[{"label":"smoke"}]})
    assert candidate["eligible"] is False
    assert "FROZEN_EVALUATION_TEST" in candidate["reason_codes"]


_LEGACY_SCHEMA = """
CREATE TABLE online_feedback (
    id TEXT PRIMARY KEY,
    prediction_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    feedback_type TEXT NOT NULL,
    algorithm_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    model_sha256 TEXT NOT NULL,
    input_sha256 TEXT NOT NULL,
    material_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    confirmed_at TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL
);
CREATE INDEX ix_online_feedback_status
    ON online_feedback(status, created_at DESC, id DESC);
"""


def test_legacy_feedback_database_is_migrated_additively(tmp_path: Path):
    """Old feedback rows and old queries keep working after optional columns."""
    source = validate_prediction_evidence(evidence())
    payload = {
        "schema_version": 1,
        "source": source,
        "note": "旧记录",
        "result": {},
    }
    legacy_id = "feedback_legacy_row"
    with sqlite3.connect(tmp_path / "online_feedback.sqlite3") as db:
        db.executescript(_LEGACY_SCHEMA)
        db.execute(
            "INSERT INTO online_feedback VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                legacy_id, source["prediction_id"], "pending_review", "needs_correction",
                source["algorithm_id"], source["version_id"], source["model_sha256"],
                source["input_sha256"], "", "2026-09-19T00:00:00+00:00", "",
                json.dumps(payload),
            ),
        )

    repository = OnlineFeedbackRepository(tmp_path)
    legacy = repository.get(legacy_id)
    assert legacy["status"] == "pending_review"
    assert legacy["payload"]["note"] == "旧记录"
    assert legacy["project_id"] == ""
    assert legacy["correction_kind"] == ""
    assert public_feedback(legacy)["correction_kind"] == ""
    assert [row["id"] for row in repository.list(status="pending_review")] == [legacy_id]

    # An old pending row can still be re-staged; the optional defect kind and
    # owning project are filled additively without touching old columns.
    source_with_project = {**source, "project_id": "legacy-project"}
    updated, idempotent = repository.stage(
        source_with_project, feedback_type="needs_correction",
        note="补充问题类型", correction_kind="wrong_class", created_at="2026-09-20T00:00:00+00:00",
    )
    assert idempotent is True
    assert updated["id"] == legacy_id
    assert updated["project_id"] == "legacy-project"
    assert updated["correction_kind"] == "wrong_class"


def test_feedback_retains_original_prediction_and_rejects_evidence_rewrite(tmp_path: Path):
    source = evidence()
    source["project_id"] = "project-1"
    source["detections"] = [
        {"class_id": 0, "label": "smoke", "confidence": 0.91,
         "x1": 10, "y1": 12, "x2": 40, "y2": 50},
        {"class_id": 1, "label": "fire", "confidence": 0.72,
         "x1": 50, "y1": 20, "x2": 90, "y2": 70},
    ]
    repository = OnlineFeedbackRepository(tmp_path)
    row, _ = repository.stage(
        source, feedback_type="needs_correction", note="多目标部分修正",
        created_at="2026-09-19T00:00:00+00:00", correction_kind="partial_correction",
    )
    assert row["project_id"] == "project-1"
    assert row["correction_kind"] == "partial_correction"
    stored = row["payload"]["source"]
    assert stored["prediction_id"] == "abc123def456"
    assert stored["algorithm_id"] == "algorithm-1"
    assert stored["version_id"] == "version-1"
    assert stored["model_sha256"] == "a" * 64
    assert stored["input_sha256"] == "b" * 64
    assert [
        (box["class_id"], box["label"], box["confidence"], box["x1"], box["y2"])
        for box in stored["detections"]
    ] == [(0, "smoke", 0.91, 10, 50), (1, "fire", 0.72, 50, 70)]
    public = public_feedback(row)
    assert public["project_id"] == "project-1"
    assert public["correction_kind"] == "partial_correction"
    assert len(public["source"]["detections"]) == 2

    changed = evidence()
    changed["project_id"] = "project-1"
    changed["detections"] = [{
        "class_id": 0, "label": "smoke", "confidence": 0.99,
        "x1": 1, "y1": 1, "x2": 2, "y2": 2,
    }]
    with pytest.raises(ValueError, match="原始预测证据已变化"):
        repository.stage(
            changed, feedback_type="needs_correction", note="篡改",
            created_at="2026-09-19T00:01:00+00:00",
        )
    assert repository.get(row["id"])["payload"]["source"]["detections"][1]["label"] == "fire"


def test_correction_kind_is_bounded_and_only_for_corrections():
    assert CANDIDATE_ONLY_FEEDBACK_TYPES == {"needs_correction"}
    assert DIRECT_TRUTH_FEEDBACK_TYPES == {"correct", "false_positive"}
    assert "partial_correction" in CORRECTION_KINDS
    for kind in sorted(CORRECTION_KINDS):
        assert normalize_correction_kind("needs_correction", kind) == kind
    assert normalize_correction_kind("needs_correction", "") == ""
    with pytest.raises(ValueError):
        normalize_correction_kind("needs_correction", "not-a-kind")
    with pytest.raises(ValueError, match="只能进入候选"):
        normalize_correction_kind("correct", "wrong_class")
