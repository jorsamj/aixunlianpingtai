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
            "weak_labels": ["smoke"],
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
    assert decision["weak_labels"] == ["smoke"]
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
