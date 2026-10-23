from __future__ import annotations

import json
from pathlib import Path

import pytest

from platform_core.hard_sample_mining import (
    HardSampleSafetyError, assert_not_frozen_test, difficulty_signals, sha256_file,
)


def test_frozen_test_ids_and_duplicate_hashes_are_never_mining_inputs(tmp_path):
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir()
    (snapshots / ("a" * 64 + ".json")).write_text(json.dumps({
        "test_image_ids": ["frozen-test"],
        "images": [{"image_id": "frozen-test", "content_sha256": "b" * 64}],
    }))
    assert_not_frozen_test(tmp_path, ["train-1"], {"train-1": "c" * 64})
    with pytest.raises(HardSampleSafetyError, match="FROZEN_TEST_FORBIDDEN"):
        assert_not_frozen_test(tmp_path, ["frozen-test"])
    with pytest.raises(HardSampleSafetyError, match="DUPLICATE_FORBIDDEN"):
        assert_not_frozen_test(tmp_path, ["new-copy"], {"new-copy": "b" * 64})


def test_unreadable_snapshot_fails_closed_without_mutating_truth(tmp_path):
    directory = tmp_path / "snapshots"
    directory.mkdir()
    (directory / "corrupt.json").write_text("{broken", encoding="utf-8")
    with pytest.raises(HardSampleSafetyError, match="SNAPSHOT_UNREADABLE"):
        assert_not_frozen_test(tmp_path, ["sample"])
    assert (directory / "corrupt.json").read_text() == "{broken"


def test_no_gt_never_fabricates_false_positive_or_false_negative():
    empty = difficulty_signals([], width=640, height=480)
    assert empty["signals"] == ["no_detection_unverified"]
    assert empty["ground_truth_compared"] is False
    assert empty["root_cause_confirmed"] is False
    rows = [{"confidence": 0.31, "box": [10, 10, 20, 20]}]
    analysis = difficulty_signals(rows, width=640, height=480)
    assert "low_confidence" in analysis["signals"]
    assert "small_target" in analysis["signals"]
    assert "false_negative" not in str(analysis)


def test_source_file_hash_is_reproducible(tmp_path):
    file = tmp_path / "model.pt"
    file.write_bytes(b"frozen-model")
    assert sha256_file(file) == __import__("hashlib").sha256(b"frozen-model").hexdigest()


def test_frozen_yolo_inference_produces_reviewable_canonical_candidates(monkeypatch, tmp_path):
    import sys
    from types import SimpleNamespace
    from platform_core.hard_sample_mining import infer_with_frozen_yolo

    model = tmp_path / "best.pt"
    model.write_bytes(b"verified trusted internal PT")
    image = tmp_path / "unlabeled.jpg"
    image.write_bytes(b"image passed as filepath, not raw GT")

    class Tensor:
        def __init__(self, rows):
            self.rows = rows
        def cpu(self):
            return self
        def tolist(self):
            return self.rows

    class YOLO:
        names = {0: "person"}
        def __init__(self, filename):
            assert filename == str(model)
        def predict(self, **kwargs):
            assert kwargs["source"] == str(image)
            assert kwargs["save"] is False
            assert kwargs["device"] == 0
            return [SimpleNamespace(boxes=SimpleNamespace(
                xyxy=Tensor([[10, 20, 40, 50]]),
                conf=Tensor([0.32]), cls=Tensor([0.0]),
            ))]

    monkeypatch.setitem(sys.modules, "torch",
                        SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True)))
    monkeypatch.setitem(sys.modules, "ultralytics", SimpleNamespace(YOLO=YOLO))
    request = {
        "mining_model_path": str(model), "mining_model_sha256": sha256_file(model),
        "mining_version_id": "v1", "labels": ["person"],
    }
    result = infer_with_frozen_yolo(request, {
        "id": "material-1", "path": str(image), "width": 640, "height": 480,
    })
    assert result["provider"] == "ultralytics"
    assert result["hard_sample_signals"] == ["low_confidence", "small_target"]
    assert result["root_cause_confirmed"] is False
    assert result["boxes"][0]["label"] == "person"
    assert result["boxes"][0]["source"] == "ai_candidate"
    assert result["boxes"][0]["confidence"] == 0.32


def test_changed_model_hash_fails_before_loading_or_downloading(monkeypatch, tmp_path):
    from platform_core.hard_sample_mining import infer_with_frozen_yolo

    model = tmp_path / "best.pt"
    model.write_bytes(b"original")
    with pytest.raises(HardSampleSafetyError, match="MODEL_IDENTITY_CHANGED"):
        infer_with_frozen_yolo({
            "mining_model_path": str(model),
            "mining_model_sha256": "f" * 64, "labels": ["person"],
        }, {"width": 100, "height": 100})


def test_confidence_first_formal_gt_detects_both_fp_and_fn_without_guessing_cause():
    from platform_core.hard_sample_mining import compare_formal_gt

    gt = [
        {"label": "person", "x1": 20, "y1": 20, "x2": 60, "y2": 60},
        {"label": "person", "x1": 40, "y1": 20, "x2": 80, "y2": 60},
    ]
    predictions = [
        {"label": "person", "box": [30, 20, 70, 60], "confidence": 0.95},
        {"label": "person", "box": [20, 20, 60, 60], "confidence": 0.65},
    ]
    assert compare_formal_gt(predictions, gt) == {
        "true_positive": 1, "false_positive": 1, "false_negative": 1,
    }


def test_formal_gt_requires_complete_label_scope_before_claiming_comparison(monkeypatch, tmp_path):
    from platform_core.hard_sample_mining import inspect_formal_annotation

    class Repository:
        def __init__(self, path):
            assert Path(path) == tmp_path
        def get(self, image_id):
            return {"annotation_state": "annotated",
                    "annotation_scope": ["person"],
                    "boxes": [{"label": "person", "x1": 5, "y1": 5, "x2": 30, "y2": 30}]}
    monkeypatch.setattr("platform_core.annotation_repository.AnnotationRepository", Repository)
    base = difficulty_signals([], width=100, height=100)
    incomplete = inspect_formal_annotation(tmp_path, "sample", [], ["person", "helmet"], base)
    assert incomplete["ground_truth_compared"] is False
    complete = inspect_formal_annotation(tmp_path, "sample", [], ["person"], base)
    assert complete["ground_truth_compared"] is True
    assert complete["gt_comparison"]["false_negative"] == 1
    assert "gt_disagreement_fn" in complete["signals"]
    assert complete["root_cause_confirmed"] is False


def reviewed_inputs():
    return dict(task_id="task-1", request={"mode":"hard_sample_yolo", "image_ids":["i1"],
        "source_hashes":{"i1":"b"*64}, "mining_algorithm_id":"a1", "mining_version_id":"v1",
        "mining_model_sha256":"a"*64}, candidate={"image_id":"i1", "accepted":True, "status":"success",
        "boxes":[{"label":"smoke", "x1":1,"y1":1,"x2":20,"y2":20,"confidence":.9}]},
        material={"id":"i1", "content_sha256":"b"*64,"width":100,"height":80},
        annotation={"annotation_state":"annotated","content_digest":"c"*64,
            "annotation_origin":"ai_confirmed","boxes":[{"label":"smoke"}]},
        commit_summary={"image_id":"i1","box_count":1,"labels":["smoke"],
            "annotation_state":"annotated","annotation_origin":"ai_confirmed"})


def test_reviewed_mining_evidence_is_stable_and_never_treats_review_boxes_as_predictions():
    from platform_core.hard_sample_mining import reviewed_mining_feedback_evidence
    args=reviewed_inputs()
    first=reviewed_mining_feedback_evidence(**args)
    assert first == reviewed_mining_feedback_evidence(**args)
    assert first["evidence"]["detections"] == []
    assert first["evidence"]["source_channel"] == "hard_sample_review"
    assert first["evidence"]["input_file"] == ""
    assert first["evidence"]["prediction_id"].startswith("hmreview_")
    assert len(first["candidate_digest"]) == 64
    args["annotation"]["content_digest"]="d"*64
    assert first["candidate_digest"] != reviewed_mining_feedback_evidence(**args)["candidate_digest"]


@pytest.mark.parametrize("field,patch", [
    ("candidate",{"accepted":False}), ("candidate",{"status":"failed"}),
    ("material",{"content_sha256":"d"*64}),
    ("annotation",{"annotation_state":"unannotated"}),
    ("annotation",{"content_digest":""}),
    ("commit_summary",{"box_count":2}), ("commit_summary",{"image_id":"other"}),
])
def test_reviewed_mining_evidence_rejects_unreviewed_changed_or_unjournaled_truth(field,patch):
    from platform_core.hard_sample_mining import reviewed_mining_feedback_evidence
    args=reviewed_inputs(); args[field].update(patch)
    with pytest.raises(ValueError):
        reviewed_mining_feedback_evidence(**args)
