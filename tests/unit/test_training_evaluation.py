from pathlib import Path

from PIL import Image

import platform_core.training_evaluation as evaluation


def test_blind_evaluation_finishes_all_predictions_before_reading_hidden_ground_truth(tmp_path: Path, monkeypatch):
    images = tmp_path / "images"
    ground_truth = tmp_path / "hidden"
    images.mkdir()
    ground_truth.mkdir()
    for name in ("a", "b"):
        Image.new("RGB", (100, 100), (20, 30, 40)).save(images / f"{name}.jpg", format="JPEG")
        (ground_truth / f"{name}.txt").write_text("0 0.5 0.5 0.4 0.4\n", encoding="utf-8")

    events = []
    original_read = evaluation._read_ground_truth

    def guarded_read(*args, **kwargs):
        events.append("ground_truth")
        assert events[:2] == ["predict:a.jpg", "predict:b.jpg"]
        return original_read(*args, **kwargs)

    monkeypatch.setattr(evaluation, "_read_ground_truth", guarded_read)

    def predict(image_path: Path):
        events.append(f"predict:{image_path.name}")
        assert "ground_truth" not in events
        return [{"class_id": 0, "confidence": 0.99, "box": [30, 30, 70, 70]}]

    result = evaluation.evaluate_blind_detection(
        images,
        ground_truth,
        predict,
        names={0: "smoke"},
    )

    assert result["status"] == "succeeded"
    assert result["protocol"]["mode"] == "blind_image_only_inference_then_hidden_ground_truth_scoring"
    assert result["metrics"]["metrics/precision(B)"] == 1.0
    assert result["metrics"]["metrics/recall(B)"] == 1.0
    assert result["metrics"]["metrics/mAP50(B)"] == 1.0
    assert result["metrics"]["metrics/mAP50-95(B)"] == 1.0
    assert result["per_class"][0]["label"] == "smoke"


def test_blind_evaluation_reports_test_fp_fn_weak_labels_and_error_samples(tmp_path: Path):
    images = tmp_path / "images"
    ground_truth = tmp_path / "hidden"
    images.mkdir()
    ground_truth.mkdir()
    for name in ("a", "b"):
        Image.new("RGB", (100, 100), (20, 30, 40)).save(images / f"{name}.jpg", format="JPEG")
        (ground_truth / f"{name}.txt").write_text("0 0.5 0.5 0.4 0.4\n", encoding="utf-8")

    def predict(image_path: Path):
        if image_path.name == "a.jpg":
            return [
                {"class_id": 0, "confidence": 0.99, "box": [30, 30, 70, 70]},
                {"class_id": 0, "confidence": 0.80, "box": [0, 0, 10, 10]},
            ]
        return []

    result = evaluation.evaluate_blind_detection(images, ground_truth, predict, names={0: "smoke"})
    row = result["per_class"][0]
    assert row["true_positive"] == 1
    assert row["false_positive"] == 1
    assert row["false_negative"] == 1
    assert row["precision"] == 0.5
    assert row["recall"] == 0.5
    assert result["weak_labels"] == ["smoke"]
    samples = {row["image"]: row for row in result["error_samples"]}
    assert samples["a.jpg"]["fp_count"] == 1
    assert samples["b.jpg"]["fn_count"] == 1


def test_evaluation_truth_is_deterministic_public_safe_and_bound_to_model_revision():
    raw = {
        "status": "succeeded",
        "metrics": {"metrics/mAP50(B)": 0.75},
        "per_class": [{"class_id": 0, "label": "smoke", "map50": 0.75}],
        "weak_labels": ["smoke"],
        "error_samples": [{
            "image": "/private/test/a.jpg", "fp_count": 2, "fn_count": 3,
            "fp_labels": ["smoke"], "fn_labels": ["smoke"],
            "signed_url": "https://forbidden.example/object",
        }],
        "image_count": 5,
        "protocol": {
            "mode": "blind_image_only_inference_then_hidden_ground_truth_scoring",
            "operating_conf": 0.25,
            "matching_iou": 0.5,
            "weak_label_threshold": 0.75,
        },
    }
    first = evaluation.build_evaluation_truth(
        raw, task_id="train-1", snapshot_id="snapshot-1",
        dataset_revision_id="a" * 64, model_sha256="b" * 64,
        finished_at="2026-09-19T12:00:00Z",
    )
    second = evaluation.build_evaluation_truth(
        raw, task_id="train-1", snapshot_id="snapshot-1",
        dataset_revision_id="a" * 64, model_sha256="b" * 64, finished_at="later",
    )
    assert first["evaluation_id"] == second["evaluation_id"]
    assert first["error_samples"][0]["image"] == "a.jpg"
    assert "signed_url" not in str(first)
    assert first["dataset_revision_id"] == "a" * 64
    assert first["model_sha256"] == "b" * 64


def test_evaluation_truth_rejects_invalid_content_identity():
    import pytest
    with pytest.raises(ValueError, match="dataset_revision_id"):
        evaluation.build_evaluation_truth(
            {"status": "not_requested"}, task_id="train-2", dataset_revision_id="not-a-sha",
        )
    with pytest.raises(ValueError, match="model_sha256"):
        evaluation.build_evaluation_truth(
            {"status": "not_requested"}, task_id="train-2", model_sha256="not-a-sha",
        )


def test_evaluation_truth_normalizes_legacy_passed_status():
    value = evaluation.build_evaluation_truth(
        {"status": "passed", "metrics": {"metrics/mAP50(B)": 0.8}},
        task_id="legacy-remote-task",
        model_sha256="c" * 64,
    )
    assert value["status"] == "succeeded"
    assert value["metrics"]["metrics/mAP50(B)"] == 0.8


def test_iteration_decision_reuses_training_gate_and_prioritizes_weak_label_data():
    truth = evaluation.build_evaluation_truth(
        {
            "status": "succeeded",
            "metrics": {"metrics/mAP50(B)": 0.78},
            "per_class": [{
                "class_id": 0, "label": "smoke", "precision": 0.8, "recall": 0.6,
                "map50": 0.7, "false_positive": 2, "false_negative": 3,
            }],
            "weak_labels": ["smoke", "fire", "smoke"],
            "error_samples": [{"image": "a.jpg", "fp_count": 2, "fn_count": 3}],
        },
        task_id="train-decision-1",
    )
    decision = evaluation.build_iteration_decision(
        truth,
        quality_gate={"metric": "map50", "continue_threshold": 0.65, "stop_threshold": 0.90},
    )
    assert decision["decision"] == "needs_data"
    assert decision["quality_gate"]["metric_key"] == "metrics/mAP50(B)"
    assert decision["quality_gate"]["metric_value"] == 0.78
    assert decision["weak_labels"] == ["smoke", "fire"]
    assert decision["signals"]["false_positive"] == 2
    assert decision["signals"]["false_negative"] == 3
    assert "supplement_weak_label_data" in decision["recommended_actions"]
    assert decision["automatic_execution"] is False
    assert decision["requires_confirmation"] is True


def test_iteration_decision_ready_continue_and_manual_review_are_explicit():
    ready = evaluation.build_iteration_decision(
        evaluation.build_evaluation_truth(
            {"status": "succeeded", "metrics": {"metrics/mAP50(B)": 0.92}},
            task_id="train-ready",
        ),
        quality_gate={"metric": "map50", "continue_threshold": 0.70, "stop_threshold": 0.90},
    )
    assert ready["decision"] == "ready_for_business_validation"

    ongoing = evaluation.build_iteration_decision(
        evaluation.build_evaluation_truth(
            {"status": "succeeded", "metrics": {"metrics/mAP50(B)": 0.82}},
            task_id="train-ongoing",
        ),
        quality_gate={"metric": "map50", "continue_threshold": 0.70, "stop_threshold": 0.90},
    )
    assert ongoing["decision"] == "continue_training"
    assert ongoing["recommended_actions"] == ["continue_from_current_version"]

    no_gate = evaluation.build_iteration_decision(
        evaluation.build_evaluation_truth(
            {"status": "succeeded", "metrics": {"metrics/mAP50(B)": 0.82}},
            task_id="train-no-gate",
        ),
    )
    assert no_gate["decision"] == "review_required"
    assert no_gate["reason_codes"] == ["stop_threshold_not_configured"]


def test_iteration_decision_is_deterministic_for_same_version_truth():
    truth = evaluation.build_evaluation_truth(
        {"status": "succeeded", "metrics": {"metrics/recall(B)": 0.81}},
        task_id="train-deterministic",
    )
    first = evaluation.build_iteration_decision(
        truth,
        quality_gate={"metric": "recall", "continue_threshold": 0.7, "stop_threshold": 0.9},
    )
    second = evaluation.build_iteration_decision(
        truth,
        quality_gate={"metric": "recall", "continue_threshold": 0.7, "stop_threshold": 0.9},
    )
    assert first["decision_id"] == second["decision_id"]
    assert first["decision"] == "continue_training"


def test_feedback_adoption_outcome_compares_persisted_evaluations_and_source_weak_labels():
    source = evaluation.build_evaluation_truth({
        "status": "succeeded",
        "metrics": {
            "metrics/precision(B)": 0.70,
            "metrics/recall(B)": 0.52,
            "metrics/mAP50(B)": 0.60,
            "metrics/mAP50-95(B)": 0.40,
        },
        "per_class": [{
            "class_id": 0, "label": "smoke", "precision": 0.70, "recall": 0.52,
            "map50": 0.60, "map50_95": 0.40, "true_positive": 10,
            "false_positive": 4, "false_negative": 8, "ground_truth_count": 18,
            "prediction_count": 14,
        }],
        "weak_labels": ["smoke"],
    }, task_id="source-task", model_sha256="1" * 64)
    current = evaluation.build_evaluation_truth({
        "status": "succeeded",
        "metrics": {
            "metrics/precision(B)": 0.82,
            "metrics/recall(B)": 0.72,
            "metrics/mAP50(B)": 0.78,
            "metrics/mAP50-95(B)": 0.55,
        },
        "per_class": [{
            "class_id": 0, "label": "smoke", "precision": 0.82, "recall": 0.72,
            "map50": 0.78, "map50_95": 0.55, "true_positive": 14,
            "false_positive": 2, "false_negative": 4, "ground_truth_count": 18,
            "prediction_count": 16,
        }],
        "weak_labels": [],
    }, task_id="new-task", model_sha256="2" * 64)
    provenance = {
        "schema_version": 1,
        "candidate_set_id": "a" * 64,
        "adoption_id": "b" * 64,
        "action_id": "c" * 64,
        "algorithm_id": "algo-1",
        "version_id": "source-v1",
        "source_candidate_count": 3,
        "adopted_candidate_count": 2,
        "adopted_feedback_ids": ["feedback-1", "feedback-2"],
    }
    outcome = evaluation.build_feedback_adoption_outcome(
        source, current, provenance,
        source_version_id="source-v1",
        new_version_id="new-v2",
    )
    assert outcome["status"] == "comparable"
    assert outcome["comparison_mode"] == "descriptive"
    assert outcome["strictly_comparable"] is False
    assert "benchmark_scope_missing" in outcome["comparison_reason_codes"]
    assert outcome["automatic_execution"] is False
    assert outcome["descriptive_only"] is True
    assert outcome["overall_metrics"]["metrics/mAP50(B)"]["delta"] == 0.18
    effect = outcome["weak_label_effects"][0]
    assert effect["label"] == "smoke"
    assert effect["direction"] == "improved"
    assert effect["metrics"]["recall"]["delta"] == 0.2
    assert effect["weak_signal"]["delta"] == 0.2
    assert effect["false_negative"] == {"before": 8, "after": 4}
    assert len(outcome["outcome_id"]) == 64


def test_feedback_adoption_outcome_is_descriptive_when_evaluation_is_not_comparable():
    source = evaluation.build_evaluation_truth({"status": "not_requested"}, task_id="source-task")
    current = evaluation.build_evaluation_truth({"status": "failed"}, task_id="new-task")
    provenance = {
        "schema_version": 1,
        "candidate_set_id": "a" * 64,
        "adoption_id": "b" * 64,
        "action_id": "c" * 64,
        "algorithm_id": "algo-1",
        "version_id": "source-v1",
        "source_candidate_count": 1,
        "adopted_candidate_count": 1,
        "adopted_feedback_ids": ["feedback-1"],
    }
    outcome = evaluation.build_feedback_adoption_outcome(
        source, current, provenance,
        source_version_id="source-v1",
        new_version_id="new-v2",
    )
    assert outcome["status"] == "not_comparable"
    assert "source_evaluation_not_succeeded" in outcome["reason_codes"]
    assert "new_evaluation_not_succeeded" in outcome["reason_codes"]
    assert outcome["overall_metrics"] == {}
    assert outcome["automatic_execution"] is False


def test_feedback_adoption_outcome_rejects_source_version_mismatch():
    import pytest
    with pytest.raises(ValueError, match="source version"):
        evaluation.build_feedback_adoption_outcome(
            {"status": "succeeded", "evaluation_id": "1" * 64},
            {"status": "succeeded", "evaluation_id": "2" * 64},
            {
                "schema_version": 1,
                "candidate_set_id": "a" * 64,
                "adoption_id": "b" * 64,
                "action_id": "c" * 64,
                "version_id": "source-v1",
            },
            source_version_id="other-version",
            new_version_id="new-v2",
        )


def test_feedback_adoption_outcome_requires_training_base_to_match_provenance():
    provenance = {
        "schema_version": 1,
        "candidate_set_id": "a" * 64,
        "adoption_id": "b" * 64,
        "action_id": "c" * 64,
        "version_id": "candidate-source-v1",
    }
    import pytest
    with pytest.raises(ValueError, match="source version"):
        evaluation.build_feedback_adoption_outcome(
            {"status": "succeeded", "evaluation_id": "1" * 64},
            {"status": "succeeded", "evaluation_id": "2" * 64},
            provenance,
            source_version_id="actual-training-base-v2",
            new_version_id="new-v3",
        )


def _benchmark_snapshot(*, test_annotation_hash="b" * 64, train_hash="9" * 64):
    return {
        "schema_version": 3,
        "test_image_ids": ["test-1"],
        "label_schema": [{"class_id": 0, "code": "smoke"}],
        "images": [
            {
                "image_id": "train-1", "role": "train",
                "content_sha256": train_hash,
                "annotation_hash": "8" * 64,
                "annotation_state": "annotated",
            },
            {
                "image_id": "test-1", "role": "test",
                "content_sha256": "a" * 64,
                "annotation_hash": test_annotation_hash,
                "annotation_state": "annotated",
            },
        ],
    }




def _benchmark_manifest(*, test_content_hash="d" * 64, label_hash="e" * 64):
    return {
        "schema_version": 3,
        "snapshot_id": "",
        "training_input_policy": "ultralytics_jpeg_repair_v1",
        "splits": {
            "test": [{
                "image_id": "test-1",
                "source_content_sha256": "a" * 64,
                "content_sha256": test_content_hash,
                "label_sha256": label_hash,
                "training_input_policy": "ultralytics_jpeg_repair_v1",
            }],
        },
    }

def test_evaluation_benchmark_scope_is_stable_for_same_test_truth_only():
    first = evaluation.build_evaluation_benchmark_scope(_benchmark_snapshot())
    train_changed = evaluation.build_evaluation_benchmark_scope(
        _benchmark_snapshot(train_hash="7" * 64)
    )
    ground_truth_changed = evaluation.build_evaluation_benchmark_scope(
        _benchmark_snapshot(test_annotation_hash="c" * 64)
    )
    assert first["scope_id"] == train_changed["scope_id"]
    assert first["scope_id"] != ground_truth_changed["scope_id"]
    assert first["test_image_count"] == 1
    assert first["binding_level"] == "snapshot_truth"
    assert len(first["content_digest"]) == 64
    assert len(first["ground_truth_digest"]) == 64
    bound = evaluation.build_evaluation_benchmark_scope(
        _benchmark_snapshot(), _benchmark_manifest(),
    )
    assert bound["binding_level"] == "bundle_verified"
    assert len(bound["evaluation_input_digest"]) == 64
    assert bound["training_input_policy"] == "ultralytics_jpeg_repair_v1"
    assert bound["scope_id"] != first["scope_id"]


def test_evaluation_truth_persists_benchmark_and_rejects_partial_test_execution():
    import pytest
    scope = evaluation.build_evaluation_benchmark_scope(_benchmark_snapshot())
    result = evaluation.build_evaluation_truth(
        {
            "status": "succeeded",
            "image_count": 1,
            "metrics": {"metrics/mAP50(B)": 0.8},
            "protocol": {
                "mode": "blind_image_only_inference_then_hidden_ground_truth_scoring",
                "operating_conf": 0.25,
                "matching_iou": 0.5,
                "iou_thresholds": [0.5, 0.55],
            },
        },
        task_id="benchmark-task",
        snapshot_id="1" * 64,
        model_sha256="2" * 64,
        benchmark_scope=scope,
    )
    assert result["benchmark_scope"]["scope_id"] == scope["scope_id"]
    assert result["evaluation_protocol_version"] == 1
    assert len(result["evaluation_protocol_id"]) == 64
    with pytest.raises(ValueError, match="image_count"):
        evaluation.build_evaluation_truth(
            {"status": "succeeded", "image_count": 0},
            task_id="partial-benchmark-task",
            benchmark_scope=scope,
        )


def test_feedback_adoption_outcome_marks_same_benchmark_and_protocol_strictly_comparable():
    scope = evaluation.build_evaluation_benchmark_scope(
        _benchmark_snapshot(), _benchmark_manifest(),
    )
    raw = {
        "status": "succeeded",
        "image_count": 1,
        "metrics": {
            "metrics/precision(B)": 0.7,
            "metrics/recall(B)": 0.6,
            "metrics/mAP50(B)": 0.65,
            "metrics/mAP50-95(B)": 0.4,
        },
        "protocol": {
            "mode": "blind_image_only_inference_then_hidden_ground_truth_scoring",
            "operating_conf": 0.25,
            "matching_iou": 0.5,
            "iou_thresholds": [0.5, 0.55],
        },
    }
    source = evaluation.build_evaluation_truth(
        raw, task_id="strict-source", model_sha256="1" * 64,
        benchmark_scope=scope,
    )
    current_raw = dict(raw)
    current_raw["metrics"] = {
        **raw["metrics"],
        "metrics/recall(B)": 0.75,
        "metrics/mAP50(B)": 0.8,
    }
    current = evaluation.build_evaluation_truth(
        current_raw, task_id="strict-new", model_sha256="2" * 64,
        benchmark_scope=scope,
    )
    provenance = {
        "schema_version": 1,
        "candidate_set_id": "a" * 64,
        "adoption_id": "b" * 64,
        "action_id": "c" * 64,
        "version_id": "source-v1",
    }
    outcome = evaluation.build_feedback_adoption_outcome(
        source, current, provenance,
        source_version_id="source-v1", new_version_id="new-v2",
    )
    assert outcome["status"] == "comparable"
    assert outcome["comparison_mode"] == "strict"
    assert outcome["strictly_comparable"] is True
    assert outcome["comparison_reason_codes"] == []
    assert outcome["source_benchmark_scope_id"] == scope["scope_id"]
    assert outcome["new_benchmark_scope_id"] == scope["scope_id"]


def test_feedback_adoption_outcome_keeps_different_benchmarks_descriptive():
    source_scope = evaluation.build_evaluation_benchmark_scope(
        _benchmark_snapshot(), _benchmark_manifest(),
    )
    new_scope = evaluation.build_evaluation_benchmark_scope(
        _benchmark_snapshot(test_annotation_hash="c" * 64),
        _benchmark_manifest(),
    )
    raw = {
        "status": "succeeded", "image_count": 1,
        "metrics": {"metrics/mAP50(B)": 0.7},
        "protocol": {
            "mode": "blind_image_only_inference_then_hidden_ground_truth_scoring",
            "operating_conf": 0.25, "matching_iou": 0.5,
        },
    }
    source = evaluation.build_evaluation_truth(
        raw, task_id="descriptive-source", benchmark_scope=source_scope,
    )
    current = evaluation.build_evaluation_truth(
        raw, task_id="descriptive-new", benchmark_scope=new_scope,
    )
    outcome = evaluation.build_feedback_adoption_outcome(
        source, current,
        {
            "schema_version": 1,
            "candidate_set_id": "a" * 64,
            "adoption_id": "b" * 64,
            "action_id": "c" * 64,
            "version_id": "source-v1",
        },
        source_version_id="source-v1", new_version_id="new-v2",
    )
    assert outcome["status"] == "comparable"
    assert outcome["comparison_mode"] == "descriptive"
    assert outcome["strictly_comparable"] is False
    assert "benchmark_scope_mismatch" in outcome["comparison_reason_codes"]


def test_feedback_adoption_outcome_keeps_snapshot_only_benchmark_descriptive():
    scope = evaluation.build_evaluation_benchmark_scope(_benchmark_snapshot())
    raw = {
        "status": "succeeded",
        "image_count": 1,
        "metrics": {"metrics/mAP50(B)": 0.7},
        "protocol": {
            "mode": "blind_image_only_inference_then_hidden_ground_truth_scoring",
            "operating_conf": 0.25,
            "matching_iou": 0.5,
        },
    }
    source = evaluation.build_evaluation_truth(
        raw, task_id="snapshot-only-source", benchmark_scope=scope,
    )
    current = evaluation.build_evaluation_truth(
        raw, task_id="snapshot-only-new", benchmark_scope=scope,
    )
    outcome = evaluation.build_feedback_adoption_outcome(
        source,
        current,
        {
            "schema_version": 1,
            "candidate_set_id": "a" * 64,
            "adoption_id": "b" * 64,
            "action_id": "c" * 64,
            "version_id": "source-v1",
        },
        source_version_id="source-v1",
        new_version_id="new-v2",
    )
    assert outcome["comparison_mode"] == "descriptive"
    assert outcome["strictly_comparable"] is False
    assert "benchmark_input_binding_missing" in outcome["comparison_reason_codes"]


def test_evaluation_benchmark_scope_rejects_manifest_cohort_or_source_mismatch():
    import pytest
    wrong_cohort = _benchmark_manifest()
    wrong_cohort["splits"]["test"][0]["image_id"] = "other-test"
    with pytest.raises(ValueError, match="unknown test image|cohort"):
        evaluation.build_evaluation_benchmark_scope(
            _benchmark_snapshot(), wrong_cohort,
        )

    wrong_source = _benchmark_manifest()
    wrong_source["splits"]["test"][0]["source_content_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="differs from snapshot truth"):
        evaluation.build_evaluation_benchmark_scope(
            _benchmark_snapshot(), wrong_source,
        )
