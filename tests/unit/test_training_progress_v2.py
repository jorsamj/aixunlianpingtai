from types import SimpleNamespace

import platform_core.training_metrics as training_metrics
from train_worker import publish_epoch_progress, read_json


def _resolved():
    return {"resolved_batch": 4, "resolved_workers": 0, "resolved_cache": False}


def _trainer():
    return SimpleNamespace(
        epoch=4,
        epochs=10,
        args=SimpleNamespace(epochs=10),
        train_loader=SimpleNamespace(dataset=list(range(120))),
        loss_names=("box_loss", "cls_loss", "dfl_loss"),
        tloss=[0.51, 0.22, 0.17],
        metrics={
            "metrics/precision(B)": 0.81,
            "metrics/recall(B)": 0.73,
            "metrics/mAP50(B)": 0.66,
            "metrics/mAP50-95(B)": 0.41,
            "ignored/non_numeric": object(),
        },
        lr={"lr/pg0": 0.001, "lr/pg1": 0.0005},
        optimizer=None,
    )


def test_epoch_completion_persists_truthful_progress_without_an_extra_db_connection(tmp_path, monkeypatch):
    db_path = tmp_path / "training-metrics.sqlite3"
    monkeypatch.setattr(training_metrics.time, "monotonic", lambda: 100.0)
    metrics = training_metrics.TrainingMetrics(db_path, _resolved(), interval=999)
    metrics.psutil = None
    metrics.started = 40.0
    metrics.epoch_started = 88.0

    metrics.on_epoch_end(_trainer())

    progress = metrics.latest_epoch
    assert progress["epoch"] == 5
    assert progress["total_epochs"] == 10
    assert progress["duration_seconds"] == 12.0
    assert progress["average_epoch_duration_seconds"] == 12.0
    assert progress["elapsed_seconds"] == 60.0
    assert progress["eta_seconds"] == 60.0
    assert progress["images_per_second"] == 10.0
    assert progress["losses"] == {"box_loss": 0.51, "cls_loss": 0.22, "dfl_loss": 0.17}
    assert progress["metrics"]["metrics/mAP50(B)"] == 0.66
    assert "ignored/non_numeric" not in progress["metrics"]
    assert progress["learning_rates"]["lr/pg0"] == 0.001
    assert progress["eta_basis"] == "rolling_last_5_epochs"

    summary = training_metrics.read_metrics(db_path)
    assert summary["latest_epoch"] == progress
    assert summary["epoch_duration_seconds"] == 12.0
    assert summary["images_per_second"] == 10.0


def test_worker_publishes_epoch_snapshot_to_existing_job_contract(tmp_path):
    job_file = tmp_path / "job.json"
    job_file.write_text('{"id":"job-1","status":"running"}', encoding="utf-8")

    class Telemetry:
        latest_epoch = None
        def on_epoch_end(self, trainer):
            self.latest_epoch = {
                "epoch": 3, "total_epochs": 8, "elapsed_seconds": 44.5, "eta_seconds": 75.0,
                "images_per_second": 22.0, "losses": {"box_loss": 0.4},
                "metrics": {"metrics/mAP50(B)": 0.7}, "learning_rates": {"lr/pg0": 0.001},
            }

    progress = publish_epoch_progress(job_file, Telemetry(), SimpleNamespace(epoch=2), 8)
    job = read_json(job_file, {})
    assert progress["epoch"] == 3
    assert job["current_epoch"] == 3
    assert job["total_epochs"] == 8
    assert job["progress_percent"] == 33.75
    assert job["elapsed_seconds"] == 44.5
    assert job["eta_seconds"] == 75.0
    assert job["training_progress"]["metrics"]["metrics/mAP50(B)"] == 0.7
    assert job["message"] == "训练中 · Epoch 3/8"
