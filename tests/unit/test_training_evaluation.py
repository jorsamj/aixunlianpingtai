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
