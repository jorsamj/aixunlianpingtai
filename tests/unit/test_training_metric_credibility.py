"""TQ-04: high validation mAP is never treated as proven field accuracy.

All fixtures below are artificial unit inputs; no live A800 or production
dataset measurements are implied by passing these contract checks.
"""
from copy import deepcopy

import pytest

from platform_core.training_evaluation import (
    build_iteration_decision,
    build_evaluation_truth,
    build_training_metric_credibility,
)


def _report(map50=0.97):
    return {"metrics": {
        "metrics/mAP50(B)": map50,
        "metrics/mAP50-95(B)": 0.78,
    }}


def _test_result(map50=0.96, *, status="succeeded"):
    return {
        "status": status,
        "metrics": {"metrics/mAP50(B)": map50, "metrics/mAP50-95(B)": 0.7},
        "image_count": 120,
        "per_class": [
            {"class_id": 0, "label": "smoke", "ground_truth_count": 60,
             "evaluation_status": "evaluated", "true_positive": 55,
             "false_positive": 1, "false_negative": 5, "map50": .96},
            {"class_id": 1, "label": "fire", "ground_truth_count": 50,
             "evaluation_status": "evaluated", "true_positive": 47,
             "false_positive": 2, "false_negative": 3, "map50": .96},
        ],
        "class_coverage": {
            "schema_version": 1,
            "source": "declared_model_names",
            "total_classes": 2,
            "macro_average_class_count": 2,
            "scored_class_ids": [0, 1],
            "class_ids_without_test_ground_truth": [],
        },
        "protocol": {
            "mode": "blind_image_only_inference_then_hidden_ground_truth_scoring",
            "predict_imgsz": 800,
            "predict_conf": 0.001,
            "predict_nms_iou": 0.7,
        },
        "benchmark_scope": {
            "binding_level": "bundle_verified",
            "test_image_count": 120,
        },
    }


def _input_quality():
    return {"class_coverage": {
        "schema_version": 1,
        "label_image_counts": {
            "train": {"smoke": 80, "fire": 85},
            "validation": {"smoke": 20, "fire": 19},
            "test": {"smoke": 25, "fire": 23},
        },
        "label_independent_component_counts": {
            "train": {"smoke": 12, "fire": 11},
            "validation": {"smoke": 6, "fire": 5},
            "test": {"smoke": 8, "fire": 7},
        },
        "train_labels_without_validation_positive": [],
        "train_labels_without_test_positive": [],
        "role_known_source_image_counts": {"train": 120, "validation": 40, "test": 120},
        "role_unknown_source_image_counts": {"train": 0, "validation": 0, "test": 0},
        "active_label_codes": ["smoke", "fire"],
    }, "annotation_admission": {"severity_counts": {
        "blocking": 0, "manual_review": 0, "warning": 0,
    }}}


def test_val_97_without_test_is_manual_review_not_proven_quality():
    outcome = build_training_metric_credibility(
        _report(0.97),
        {"status": "not_requested", "metrics": {}},
        input_quality=_input_quality(),
    )
    assert outcome["status"] == "review_required"
    assert outcome["validation_map50"] == 0.97
    assert outcome["independent_test_map50"] is None
    assert "independent_test_unavailable" in outcome["reason_codes"]
    assert outcome["production_accuracy_verified"] is False
    assert outcome["leakage_conclusion"] == "not_determined"
    assert outcome["metric_kind"] == "object_detection_map_not_event_accuracy"


def test_val_test_gap_over_10pp_is_warning_not_proof_of_leakage():
    result = build_training_metric_credibility(
        _report(.97), _test_result(.59),
        input_quality=_input_quality(),
    )
    assert result["val_minus_test_map50"] == .38
    assert result["status"] == "review_required"
    assert "validation_test_map50_gap_at_least_10pp" in result["reason_codes"]
    assert result["leakage_conclusion"] == "not_determined"
    assert result["independent_test_map50"] == .59


def test_high_val_and_test_with_bounded_independent_evidence_is_not_field_accuracy():
    result = build_training_metric_credibility(
        _report(.97), _test_result(.96), input_quality=_input_quality(),
    )
    assert result["high_val_triggered"] is True
    assert result["status"] == "held_out_evidence_present"
    assert result["reason_codes"] == []
    assert result["production_accuracy_verified"] is False
    assert result["val_minus_test_map50"] == .01


def test_high_map_unmeasured_test_classes_and_unknown_video_provenance():
    test = _test_result(.99)
    test["class_coverage"]["class_ids_without_test_ground_truth"] = [1]
    quality = _input_quality()
    quality["class_coverage"]["role_unknown_source_image_counts"]["train"] = 28
    quality["class_coverage"]["train_labels_without_test_positive"] = ["fire"]
    result = build_training_metric_credibility(
        _report(.97), test, input_quality=quality,
    )
    assert result["status"] == "review_required"
    assert "independent_test_classes_without_gt" in result["reason_codes"]
    assert "split_test_classes_without_gt" in result["reason_codes"]
    assert "capture_source_partly_unknown" in result["reason_codes"]


def test_very_sparse_test_groups_and_positive_samples_trigger_manual_evidence_check():
    quality = _input_quality()
    quality["class_coverage"]["label_independent_component_counts"]["test"]["smoke"] = 2
    quality["class_coverage"]["label_image_counts"]["test"]["smoke"] = 4
    result = build_training_metric_credibility(
        _report(.97), _test_result(.99), input_quality=quality,
    )
    assert "test_class_fewer_than_three_independent_groups" in result["reason_codes"]
    assert "test_class_fewer_than_five_positive_images" in result["reason_codes"]


def test_high_score_without_frozen_split_protocol_or_benchmark_is_not_approved():
    test = _test_result(.98)
    test.pop("benchmark_scope")
    test["protocol"] = {"mode": "blind_image_only_inference_then_hidden_ground_truth_scoring"}
    result = build_training_metric_credibility(
        _report(.97), test, input_quality={},
    )
    assert "frozen_split_coverage_unavailable" in result["reason_codes"]
    assert "test_class_coverage_unverified" not in result["reason_codes"]
    assert "independent_test_inference_protocol_incomplete" in result["reason_codes"]
    assert "independent_test_input_binding_unverified" in result["reason_codes"]


def test_class_coverage_not_declared_does_not_invent_evaluated_classes():
    test = _test_result(.97)
    test["class_coverage"] = {"source": "observed_only"}
    result = build_training_metric_credibility(
        _report(.97), test, input_quality=_input_quality(),
    )
    assert "test_class_coverage_unverified" in result["reason_codes"]


def test_gt_manual_review_is_visible_without_mutating_formal_gt():
    quality = _input_quality()
    quality["source_ground_truth_admission"] = {
        "severity_counts": {"manual_review": 5, "blocking": 0},
    }
    result = build_training_metric_credibility(
        _report(.97), _test_result(.95), input_quality=quality,
    )
    assert "source_or_projected_gt_needs_review" in result["reason_codes"]


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -0.1, 1.01, "", None, True])
def test_invalid_validation_map_is_missing_not_97_percent(invalid):
    result = build_training_metric_credibility(
        _report(invalid), _test_result(.99), input_quality=_input_quality(),
    )
    assert result["validation_map50"] is None
    assert result["status"] == "val_metric_unavailable"
    assert result["high_val_triggered"] is False


def test_below_high_val_threshold_does_not_create_fake_warning():
    result = build_training_metric_credibility(
        _report(.949999), _test_result(.99), input_quality=_input_quality(),
    )
    assert result["status"] == "not_high_val_trigger"
    assert result["reason_codes"] == []


def test_high_val_credibility_review_prevents_automatic_ready_advice():
    evaluation = build_evaluation_truth(
        _test_result(.98), task_id="tq-04-decision",
    )
    review = build_training_metric_credibility(
        _report(.97), evaluation, input_quality={},
    )
    gate = {"metric": "map50", "stop_threshold": 0.95}
    legacy = build_iteration_decision(evaluation, quality_gate=gate)
    assert legacy["decision"] == "ready_for_business_validation"

    checked = build_iteration_decision(
        evaluation, quality_gate=gate, metric_credibility=review,
    )
    assert checked["decision"] == "review_required"
    assert "high_validation_map_evidence_needs_review" in checked["reason_codes"]
    assert "inspect_metric_credibility" in checked["recommended_actions"]
    assert checked["automatic_execution"] is False


def test_complete_high_val_evidence_keeps_business_validation_advisory():
    evidence = build_evaluation_truth(_test_result(.96), task_id="tq-04-bounded")
    # Normalization carries the declared classes and inference protocol.
    # Attach only a test binding that can genuinely be verified separately.
    evidence["benchmark_scope"] = {"binding_level": "bundle_verified"}
    confidence = build_training_metric_credibility(
        _report(.97), evidence, input_quality=_input_quality(),
    )
    assert confidence["status"] == "held_out_evidence_present"
    result = build_iteration_decision(
        evidence,
        quality_gate={"metric": "map50", "stop_threshold": .95},
        metric_credibility=confidence,
    )
    assert result["decision"] == "ready_for_business_validation"
    assert confidence["production_accuracy_verified"] is False


def test_metric_credibility_is_repeatable_and_does_not_change_input_evidence():
    report = _report(.97)
    test = _test_result(.96)
    quality = _input_quality()
    originals = deepcopy((report, test, quality))
    first = build_training_metric_credibility(report, test, input_quality=quality)
    second = build_training_metric_credibility(report, test, input_quality=quality)
    assert first == second
    assert first["diagnostic_id"] == second["diagnostic_id"]
    assert (report, test, quality) == originals



def test_high_test_map_without_scored_gt_classes_is_not_trusted():
    test = _test_result(.99)
    test["class_coverage"]["scored_class_ids"] = []
    test["class_coverage"]["macro_average_class_count"] = 0
    result = build_training_metric_credibility(
        _report(.97), test, input_quality=_input_quality(),
    )
    assert "independent_test_no_scored_positive_classes" in result["reason_codes"]
    assert result["status"] == "review_required"


def test_high_map_with_partial_test_execution_is_not_trusted():
    test = _test_result(.99)
    test["image_count"] = 60
    result = build_training_metric_credibility(
        _report(.97), test, input_quality=_input_quality(),
    )
    assert "test_scored_images_differ_from_frozen_selection" in result["reason_codes"]


def test_model_catalog_must_match_frozen_classes_for_high_map():
    test = _test_result(.99)
    test["class_coverage"]["total_classes"] = 1
    result = build_training_metric_credibility(
        _report(.97), test, input_quality=_input_quality(),
    )
    assert "model_class_catalog_differs_from_frozen_training_labels" in result["reason_codes"]
