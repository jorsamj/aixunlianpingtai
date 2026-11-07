from types import SimpleNamespace

from train_worker import derive_training_completion_metadata


def test_time_limit_is_reported_as_time_limit_not_patience_early_stop():
    trainer = SimpleNamespace(
        stopper=SimpleNamespace(patience=100, best_epoch=20),
    )
    result = derive_training_completion_metadata(
        trainer,
        requested_epochs=100,
        completed_epochs=30,
        gate_reason="",
        max_train_hours=2.0,
        elapsed_hours=2.01,
    )
    assert result["training_outcome"] == "completed"
    assert result["completion_reason"] == "time_limit_reached"
    assert result["early_stopping_reason"] is None
    assert "最大训练时长" in result["completion_message"]


def test_patience_remains_authoritative_when_time_limit_was_not_reached():
    trainer = SimpleNamespace(
        stopper=SimpleNamespace(patience=10, best_epoch=15),
    )
    result = derive_training_completion_metadata(
        trainer,
        requested_epochs=100,
        completed_epochs=30,
        gate_reason="",
        max_train_hours=2.0,
        elapsed_hours=1.0,
    )
    assert result["training_outcome"] == "early_stopping"
    assert result["completion_reason"] == "early_stopping"
    assert result["early_stopping_reason"] == "patience"
