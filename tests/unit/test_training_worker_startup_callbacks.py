from __future__ import annotations


def test_pinned_ultralytics_exposes_training_startup_callbacks():
    from ultralytics.utils.callbacks.base import default_callbacks

    assert "on_pretrain_routine_start" in default_callbacks
    assert "on_train_start" in default_callbacks
    assert "on_train_batch_start" in default_callbacks
