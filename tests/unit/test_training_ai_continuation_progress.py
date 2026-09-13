from __future__ import annotations

import json
from types import SimpleNamespace

import train_worker


class _Telemetry:
    def __init__(self):
        self.latest_epoch = None

    def on_epoch_end(self, trainer):
        completed = int(getattr(trainer, "epoch", 0)) + 1
        total = int(getattr(trainer, "epochs", 2))
        self.latest_epoch = {
            "epoch": completed,
            "total_epochs": total,
            "elapsed_seconds": 30.0,
            "eta_seconds": 30.0 * max(0, total - completed),
            "images_per_second": 18.0,
            "losses": {"box_loss": 0.4},
            "metrics": {"metrics/mAP50(B)": 0.7},
            "learning_rates": {"lr/pg0": 0.001},
        }


class _Model:
    def __init__(self):
        self.callbacks = {}

    def add_callback(self, event, callback):
        self.callbacks[event] = callback


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_ai_continuation_batch_progress_uses_90_95_and_cumulative_epochs(tmp_path):
    job_file = tmp_path / "job.json"
    job_file.write_text('{"id":"ai-cont","progress_percent":90}', encoding="utf-8")
    trainer = SimpleNamespace(epoch=0, epochs=2)

    train_worker.publish_batch_progress(
        job_file,
        trainer,
        requested_total_epochs=2,
        completed_batches=5,
        total_batches=10,
        phase_start=90.0,
        phase_end=95.0,
        epoch_offset=10,
        display_total_epochs=12,
        item_prefix="AI追加训练",
    )

    job = _read(job_file)
    assert job["progress_percent"] == 91.25
    assert job["current_epoch"] == 11
    assert job["total_epochs"] == 12
    assert job["current_batch"] == 5
    assert job["total_batches"] == 10
    assert job["current_item"] == "AI追加训练 · Epoch 11/12 · Batch 5/10"


def test_ai_continuation_epoch_progress_preserves_cumulative_epoch_truth(tmp_path):
    job_file = tmp_path / "job.json"
    job_file.write_text('{"id":"ai-cont","progress_percent":90}', encoding="utf-8")
    telemetry = _Telemetry()
    trainer = SimpleNamespace(epoch=0, epochs=2)

    progress = train_worker.publish_ai_continuation_epoch_progress(
        job_file,
        telemetry,
        trainer,
        base_completed_epochs=10,
        extra_epochs=2,
    )

    job = _read(job_file)
    assert job["progress_percent"] == 92.5
    assert job["current_epoch"] == 11
    assert job["total_epochs"] == 12
    assert job["current_item"] == "AI追加训练 · Epoch 11/12"
    assert progress["epoch"] == 11
    assert progress["total_epochs"] == 12
    assert progress["phase_epoch"] == 1
    assert progress["phase_total_epochs"] == 2


def test_ai_continuation_model_rebinds_epoch_batch_and_resource_callbacks(tmp_path):
    job_file = tmp_path / "job.json"
    job_file.write_text('{"id":"ai-cont","progress_percent":90}', encoding="utf-8")
    telemetry = _Telemetry()
    model = _Model()
    resource_calls = []

    train_worker.attach_ai_continuation_callbacks(
        model,
        job_file,
        telemetry,
        base_completed_epochs=10,
        extra_epochs=2,
        attach_resource_callbacks=lambda target: resource_calls.append(target),
    )

    assert resource_calls == [model]
    assert "on_fit_epoch_end" in model.callbacks
    assert "on_train_batch_end" in model.callbacks

    batch_trainer = SimpleNamespace(epoch=0, epochs=2, train_loader=[1, 2])
    model.callbacks["on_train_batch_end"](batch_trainer)
    batch_job = _read(job_file)
    assert batch_job["progress_percent"] == 91.25
    assert batch_job["current_item"] == "AI追加训练 · Epoch 11/12 · Batch 1/2"

    model.callbacks["on_fit_epoch_end"](SimpleNamespace(epoch=0, epochs=2))
    epoch_job = _read(job_file)
    assert epoch_job["progress_percent"] == 92.5
    assert epoch_job["current_item"] == "AI追加训练 · Epoch 11/12"
