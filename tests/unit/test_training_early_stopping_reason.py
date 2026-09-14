from types import SimpleNamespace

from train_worker import derive_training_completion_metadata


def test_patience_early_stop_records_exact_reason_and_best_epoch():
    trainer = SimpleNamespace(
        epoch=179,
        stopper=SimpleNamespace(patience=100, best_epoch=79, possible_stop=True),
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
        stopper=SimpleNamespace(patience=100, best_epoch=79, possible_stop=True),
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
