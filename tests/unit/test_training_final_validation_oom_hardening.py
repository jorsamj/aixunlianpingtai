from __future__ import annotations

from pathlib import Path

import pytest

import train_worker_safe
from platform_core import training_hardened_tasks as hardened
from platform_core.task_runtime import TaskKind
from platform_core.worker_registry import resolve_worker_registration


def _resolved(strategy="auto", workers=8):
    return {
        "resource_strategy": strategy,
        "resolved_workers": workers,
        "adjustments": [],
        "reasons": [],
    }


def test_auto_worker_cap_defaults_to_two(monkeypatch):
    monkeypatch.delenv(train_worker_safe.AUTO_WORKER_CAP_ENV, raising=False)

    def original(_request, _context, _model, _torch):
        return _resolved("auto", 8)

    result = train_worker_safe.bounded_resolve_resources(
        original,
        {"resource_strategy": "auto"},
        {},
        object(),
        object(),
    )

    assert result["resolved_workers"] == 2
    assert result["auto_dataloader_worker_cap"] == 2
    assert any("8->2" in item for item in result["adjustments"])


def test_auto_worker_cap_is_operator_configurable(monkeypatch):
    monkeypatch.setenv(train_worker_safe.AUTO_WORKER_CAP_ENV, "3")

    def original(_request, _context, _model, _torch):
        return _resolved("auto", 6)

    result = train_worker_safe.bounded_resolve_resources(
        original,
        {"resource_strategy": "auto"},
        {},
        object(),
        object(),
    )
    assert result["resolved_workers"] == 3
    assert result["auto_dataloader_worker_cap"] == 3


def test_manual_workers_are_not_silently_changed(monkeypatch):
    monkeypatch.setenv(train_worker_safe.AUTO_WORKER_CAP_ENV, "1")

    def original(_request, _context, _model, _torch):
        return _resolved("manual", 6)

    result = train_worker_safe.bounded_resolve_resources(
        original,
        {"resource_strategy": "manual"},
        {},
        object(),
        object(),
    )
    assert result["resolved_workers"] == 6
    assert "auto_dataloader_worker_cap" not in result


def test_invalid_worker_cap_fails_explicitly(monkeypatch):
    monkeypatch.setenv(train_worker_safe.AUTO_WORKER_CAP_ENV, "not-a-number")

    def original(_request, _context, _model, _torch):
        return _resolved("auto", 4)

    with pytest.raises(ValueError, match=train_worker_safe.AUTO_WORKER_CAP_ENV):
        train_worker_safe.bounded_resolve_resources(
            original,
            {"resource_strategy": "auto"},
            {},
            object(),
            object(),
        )


def _incident(tmp_path, task_id="99a99b479ecf", epochs=300):
    project = tmp_path / "projects" / "f1fb1e6fa373"
    job_file = project / "jobs" / task_id / "job.json"
    job_file.parent.mkdir(parents=True)
    weights = project / "runs" / f"train_{task_id}" / "weights"
    weights.mkdir(parents=True)
    (weights / "best.pt").write_bytes(b"best-checkpoint")
    (weights / "last.pt").write_bytes(b"last-checkpoint")
    log_path = job_file.parent / "train.log"
    log_path.write_text(
        f"{epochs} epochs completed in 1.619 hours.\n"
        f"Validating {weights / 'best.pt'}...\n"
        "Class Images Instances Box(P R mAP50 mAP50-95): 71% 5/7\n",
        encoding="utf-8",
    )
    job = {
        "current_epoch": epochs,
        "total_epochs": epochs,
        "status": "running",
        "message": f"训练中 · Epoch {epochs}/{epochs}",
    }
    argv = [
        "python",
        "train_worker_safe.py",
        "--project-dir",
        str(project),
        "--data",
        str(job_file.parent / "runtime-data.yaml"),
        "--job-id",
        task_id,
        "--run-name",
        f"train_{task_id}",
        "--epochs",
        str(epochs),
        "--imgsz",
        "640",
        "--assigned-device",
        "cuda:0",
        "--val-max-samples",
        "0",
    ]
    return project, job_file, weights, log_path, job, argv


def test_real_incident_shape_is_recoverable_final_validation_failure(tmp_path):
    _project, job_file, weights, log_path, job, argv = _incident(tmp_path)

    evidence = hardened.build_training_failure_evidence(
        task_id="99a99b479ecf",
        project_id="f1fb1e6fa373",
        argv=argv,
        job_file=job_file,
        job=job,
        returncode=-9,
        completion_error="job status is not done",
        log_path=log_path,
    )

    assert evidence["failure_stage"] == "final_validation"
    assert evidence["process_signal"] == "SIGKILL"
    assert evidence["training_loop_completed"] is True
    assert evidence["checkpoint_available"] is True
    assert evidence["recoverable"] is True
    assert evidence["recovery_action"] == "revalidate_checkpoint"
    assert evidence["recovery_action_available"] is True
    assert {item["kind"] for item in evidence["checkpoints"]} == {"best", "last"}

    message = hardened._failure_message(evidence)
    assert "SIGKILL" in message
    assert "returncode=-9" in message
    assert "stage=final_validation" in message
    assert "completion_handshake=job status is not done" in message
    assert "训练中 · Epoch 300/300" not in message
    assert "OOM" not in message


def test_training_loop_checkpoint_ready_before_final_validation_finishes(tmp_path):
    _project, job_file, _weights, log_path, job, argv = _incident(tmp_path, task_id="45d5851805c3", epochs=30)

    ready = hardened._training_loop_checkpoint_ready(
        argv=argv,
        job_file=job_file,
        job=job,
        log_path=log_path,
    )

    assert ready is not None
    assert ready["training_loop_completed"] is True
    assert ready["completed_epochs"] == 30
    assert any(item["kind"] == "best" for item in ready["checkpoints"])


def test_final_validation_defaults_are_isolated_and_low_memory(monkeypatch):
    monkeypatch.delenv(hardened.FINAL_VALIDATION_WORKERS_ENV, raising=False)
    monkeypatch.delenv(hardened.FINAL_VALIDATION_BATCH_ENV, raising=False)

    profile = hardened.final_validation_resource_profile()

    assert profile["workers"] == 0
    assert profile["batch"] == 1
    assert profile["cache"] is False


def test_validation_argv_uses_checkpoint_and_safe_profile(tmp_path):
    project, job_file, weights, _log_path, _job, argv = _incident(tmp_path, task_id="45d5851805c3", epochs=30)
    script = Path(hardened.__file__).resolve().parent.parent / "checkpoint_validation_worker.py"
    if not script.is_file():
        pytest.skip("checkpoint validation worker is not available in this source layout")
    checkpoint = {
        "kind": "best",
        "path": str(weights / "best.pt"),
        "sha256": hardened.base._sha256(weights / "best.pt"),
    }

    result = hardened.build_checkpoint_validation_argv(
        training_argv=argv,
        job_file=job_file,
        task_id="45d5851805c3",
        snapshot_id="snapshot-1",
        checkpoint=checkpoint,
        recovery=True,
        profile={"workers": 0, "batch": 1, "cache": False},
    )

    assert Path(result[1]).name == "checkpoint_validation_worker.py"
    assert result[result.index("--workers") + 1] == "0"
    assert result[result.index("--batch") + 1] == "1"
    assert result[result.index("--checkpoint") + 1] == str(weights / "best.pt")
    assert "--recovery" in result
    assert str(project) == result[result.index("--project-dir") + 1]


def test_checkpoint_alone_does_not_fabricate_recoverable_completion(tmp_path):
    project = tmp_path / "projects" / "p1"
    task_id = "t1"
    job_file = project / "jobs" / task_id / "job.json"
    job_file.parent.mkdir(parents=True)
    weights = project / "runs" / f"train_{task_id}" / "weights"
    weights.mkdir(parents=True)
    (weights / "best.pt").write_bytes(b"partial")
    log_path = job_file.parent / "train.log"
    log_path.write_text("Epoch 10/300\n", encoding="utf-8")

    evidence = hardened.build_training_failure_evidence(
        task_id=task_id,
        project_id="p1",
        argv=["python", "train_worker_safe.py", "--run-name", f"train_{task_id}", "--epochs", "300"],
        job_file=job_file,
        job={"current_epoch": 10, "total_epochs": 300},
        returncode=1,
        completion_error="job status is not done",
        log_path=log_path,
    )

    assert evidence["failure_stage"] == "training_process"
    assert evidence["checkpoint_available"] is True
    assert evidence["training_loop_completed"] is False
    assert evidence["recoverable"] is False
    assert evidence["recovery_action"] is None
    assert evidence["recovery_action_available"] is False


def test_training_role_uses_hardened_label_contract_handler(tmp_path):
    registration = resolve_worker_registration(tmp_path, {"training"})
    handler = registration.handlers[TaskKind.TRAINING]

    assert handler.__class__.__name__ == "HardenedLabelContractTrainingHandler"
    assert handler.__class__.__module__ == "platform_core.training_hardened_tasks"
    assert "training.ultralytics" in registration.capabilities
