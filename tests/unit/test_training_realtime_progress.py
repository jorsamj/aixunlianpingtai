from __future__ import annotations

import json
from types import SimpleNamespace

import train_worker


class _Telemetry:
    latest_epoch = None

    def on_epoch_end(self, trainer):
        epoch = int(getattr(trainer, "epoch", 0)) + 1
        total = int(getattr(trainer, "epochs", 10))
        self.latest_epoch = {
            "epoch": epoch,
            "total_epochs": total,
            "elapsed_seconds": 12.0,
            "eta_seconds": 108.0,
            "images_per_second": 20.0,
            "losses": {"box_loss": 0.5},
            "metrics": {},
            "learning_rates": {},
        }


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_first_completed_epoch_advances_beyond_preparation_floor(tmp_path):
    job_file = tmp_path / "job.json"
    job_file.write_text('{"id":"train-live","progress_percent":20}', encoding="utf-8")
    trainer = SimpleNamespace(epoch=0, epochs=10)

    train_worker.publish_epoch_progress(job_file, _Telemetry(), trainer, 10)

    job = _read(job_file)
    # Preparation owns 0..20; actual training owns 20..90. Finishing epoch 1/10
    # must therefore move the durable source above the 20% preparation floor.
    assert job["progress_percent"] == 27.0
    assert job["current_epoch"] == 1
    assert job["total_epochs"] == 10


def test_batch_progress_moves_inside_an_epoch_and_never_claims_epoch_metrics(tmp_path):
    job_file = tmp_path / "job.json"
    job_file.write_text('{"id":"train-live","progress_percent":20}', encoding="utf-8")
    trainer = SimpleNamespace(epoch=0, epochs=10)

    train_worker.publish_batch_progress(
        job_file,
        trainer,
        requested_total_epochs=10,
        completed_batches=5,
        total_batches=10,
    )

    job = _read(job_file)
    assert job["progress_percent"] == 23.5
    assert job["current_epoch"] == 1
    assert job["current_batch"] == 5
    assert job["total_batches"] == 10
    assert job["current_item"] == "Epoch 1/10 · Batch 5/10"
    # Batch callbacks do not manufacture validation metrics; the last completed
    # epoch snapshot remains authoritative for losses/mAP/ETA.
    assert "training_progress" not in job


def test_batch_progress_callback_is_throttled_but_flushes_the_last_batch(tmp_path, monkeypatch):
    job_file = tmp_path / "job.json"
    job_file.write_text('{"id":"train-live","progress_percent":20}', encoding="utf-8")
    callbacks = {}

    class Model:
        def add_callback(self, event, callback):
            callbacks[event] = callback

    clock = iter([100.0, 100.1, 100.2, 100.3])
    monkeypatch.setattr(train_worker.time, "monotonic", lambda: next(clock))
    train_worker.attach_training_batch_progress(Model(), job_file, requested_total_epochs=10)
    assert "on_train_batch_end" in callbacks

    trainer = SimpleNamespace(epoch=0, epochs=10, train_loader=[1, 2, 3])
    callback = callbacks["on_train_batch_end"]
    callback(trainer)
    first = _read(job_file)
    callback(trainer)
    second = _read(job_file)
    callback(trainer)
    final = _read(job_file)

    assert first["current_batch"] == 1
    # Second batch is inside the 250ms write throttle, so disk truth stays on batch 1.
    assert second["current_batch"] == 1
    # Last batch must always flush even inside the throttle window.
    assert final["current_batch"] == 3
    assert final["progress_percent"] == 27.0
