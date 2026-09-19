from types import SimpleNamespace

from train_worker import (
    decide_training_quality_gate,
    derive_training_completion_metadata,
    effective_training_patience,
    stage_gate_random_eval,
)


def test_patience_early_stop_records_exact_reason_and_best_epoch():
    trainer = SimpleNamespace(
        epoch=179,
        stopper=SimpleNamespace(patience=100, best_epoch=80, possible_stop=True),
    )

    result = derive_training_completion_metadata(
        trainer,
        requested_epochs=300,
        completed_epochs=180,
        gate_reason="",
        ai_plan=None,
    )

    assert result["training_outcome"] == "early_stopping"
    assert result["completion_reason"] == "early_stopping"
    assert result["early_stopping_reason"] == "patience"
    assert result["early_stopping_patience"] == 100
    assert result["best_epoch"] == 80
    assert "连续 100 个 Epoch" in result["completion_message"]


def test_quality_gate_reason_has_priority_over_patience_inference():
    trainer = SimpleNamespace(
        epoch=179,
        stopper=SimpleNamespace(patience=100, best_epoch=80, possible_stop=True),
    )

    result = derive_training_completion_metadata(
        trainer,
        requested_epochs=300,
        completed_epochs=180,
        gate_reason="map50 达到提前完成阈值 0.850",
        ai_plan=None,
    )

    assert result["training_outcome"] == "target_reached"
    assert result["completion_reason"] == "quality_target_reached"
    assert result["early_stopping_reason"] is None
    assert "达到提前完成阈值" in result["completion_message"]



def test_target_mode_pushes_generic_patience_beyond_requested_epochs():
    assert effective_training_patience(20, 100, 0.90) == 101
    assert effective_training_patience(200, 100, 0.90) == 200


def test_no_target_mode_preserves_requested_patience():
    assert effective_training_patience(20, 100, 0.0) == 20


def test_below_target_never_stops_training_even_below_reference_line():
    result = decide_training_quality_gate(
        0.42,
        metric="map50",
        stop_threshold=0.90,
        continue_threshold=0.60,
    )

    assert result["decision"] == "continue_below_target"
    assert result["should_stop"] is False
    assert result["reason"] == ""
    assert "继续训练至达标或最大 Epoch" in result["advisory"]


def test_target_reached_is_the_only_quality_gate_early_stop():
    result = decide_training_quality_gate(
        0.905,
        metric="map50",
        stop_threshold=0.90,
        continue_threshold=0.60,
    )

    assert result["decision"] == "target_reached"
    assert result["should_stop"] is True
    assert "达到提前完成阈值" in result["reason"]



def test_stage_gate_uses_validation_split_not_final_test_split(tmp_path):
    from types import SimpleNamespace

    val_dir = tmp_path / "images" / "val"
    test_dir = tmp_path / "images" / "test"
    val_dir.mkdir(parents=True)
    test_dir.mkdir(parents=True)
    (val_dir / "trial-a.jpg").write_bytes(b"trial")
    (test_dir / "benchmark-hidden.jpg").write_bytes(b"benchmark")
    data_yaml = tmp_path / "data.yaml"
    data_yaml.write_text("path: .\ntrain: images/train\nval: images/val\ntest: images/test\n", encoding="utf-8")

    trainer = SimpleNamespace(metrics={"metrics/mAP50(B)": 0.5})
    args = SimpleNamespace(
        data=str(data_yaml),
        val_max_samples=0,
        seed=7,
        project_dir=str(tmp_path),
        job_id="gate-test",
        imgsz=640,
        device="cpu",
    )

    metrics, sampled, mode, note = stage_gate_random_eval(trainer, args, epoch=10)

    assert metrics == trainer.metrics
    assert sampled == ["trial-a.jpg"]
    assert mode == "all"
    assert note == ""
    assert "benchmark-hidden.jpg" not in sampled
