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


def test_training_time_cap_is_a_stop_ceiling_and_does_not_change_epochs():
    from train_worker import attach_training_time_cap

    class Model:
        def __init__(self):
            self.callbacks = {}

        def add_callback(self, name, callback):
            self.callbacks.setdefault(name, []).append(callback)

    now = [100.0]
    model = Model()
    trainer = SimpleNamespace(stop=False, epochs=150)
    budget = attach_training_time_cap(model, 0.1, clock=lambda: now[0])
    for callback in model.callbacks["on_train_batch_start"]:
        callback(trainer)
    now[0] = 459.0
    for callback in model.callbacks["on_train_batch_end"]:
        callback(trainer)
    assert trainer.stop is False
    assert trainer.epochs == 150
    assert budget["reached"] is False

    now[0] = 461.0
    for callback in model.callbacks["on_train_batch_end"]:
        callback(trainer)
    assert trainer.stop is True
    assert trainer.epochs == 150
    assert budget["reached"] is True

    # A continuation run shares the original ceiling rather than resetting it.
    second_model = Model()
    second_trainer = SimpleNamespace(stop=False)
    attach_training_time_cap(second_model, 0.1, budget=budget, clock=lambda: now[0])
    for callback in second_model.callbacks["on_train_batch_start"]:
        callback(second_trainer)
    for callback in second_model.callbacks["on_train_batch_end"]:
        callback(second_trainer)
    assert second_trainer.stop is True


def test_time_cap_completion_has_separate_reason_from_epoch_completion():
    trainer = SimpleNamespace(stopper=SimpleNamespace(patience=100, best_epoch=12))
    result = derive_training_completion_metadata(
        trainer, requested_epochs=150, completed_epochs=20,
        gate_reason="", max_train_hours=0.1, elapsed_hours=0.101,
        time_limit_triggered=True,
    )
    assert result["completion_reason"] == "time_limit_reached"
    assert result["completed_epochs"] == 20
