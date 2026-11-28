from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from platform_core import training_tasks


def _context(task_id="task-1"):
    return SimpleNamespace(task=SimpleNamespace(task_id=task_id))


def _job_file(tmp_path: Path, *, task_id="task-1", **extra) -> Path:
    path = tmp_path / "jobs" / task_id / "job.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "id": task_id, "task_id": task_id, "status": "running", **extra,
    }, ensure_ascii=False), encoding="utf-8")
    return path


def test_cancel_verification_grace_environment(monkeypatch):
    monkeypatch.delenv(
        training_tasks.TRAINING_CANCEL_VERIFICATION_GRACE_ENV, raising=False)
    assert (
        training_tasks.training_cancel_verification_grace_seconds()
        == training_tasks.DEFAULT_TRAINING_CANCEL_VERIFICATION_GRACE_SECONDS
    )
    monkeypatch.setenv(
        training_tasks.TRAINING_CANCEL_VERIFICATION_GRACE_ENV, "5")
    assert training_tasks.training_cancel_verification_grace_seconds() == 5.0
    monkeypatch.setenv(
        training_tasks.TRAINING_CANCEL_VERIFICATION_GRACE_ENV, "-1")
    assert (
        training_tasks.training_cancel_verification_grace_seconds()
        == training_tasks.DEFAULT_TRAINING_CANCEL_VERIFICATION_GRACE_SECONDS
    )
    monkeypatch.setenv(
        training_tasks.TRAINING_CANCEL_VERIFICATION_GRACE_ENV, "invalid")
    assert (
        training_tasks.training_cancel_verification_grace_seconds()
        == training_tasks.DEFAULT_TRAINING_CANCEL_VERIFICATION_GRACE_SECONDS
    )


def test_cancel_wait_diagnostic_records_unverified_state_without_terminal(tmp_path):
    job_file = _job_file(tmp_path)
    training_tasks._record_cancel_wait_diagnostic(
        _context(), job_file,
        stage=training_tasks.CANCEL_STAGE_UNVERIFIED,
        attempts=3, elapsed_seconds=91.25,
        last_error="PermissionError: cannot verify",
    )
    job = json.loads(job_file.read_text(encoding="utf-8"))
    assert job["status"] == "running", "a diagnostic must not publish a terminal state"
    assert job["cancel_stop_state"] == "unverified"
    assert job["cancel_stage"] == training_tasks.CANCEL_STAGE_UNVERIFIED
    assert job["cancel_stop_attempts"] == 3
    assert job["cancel_wait_seconds"] == 91.25
    assert job["cancel_stop_last_error"] == "PermissionError: cannot verify"
    assert job["cancel_requested_at"]
    assert job["cancel_diagnostic_at"]

    # A second update keeps the original request time and only moves the state.
    training_tasks._record_cancel_wait_diagnostic(
        _context(), job_file,
        stage=training_tasks.CANCEL_STAGE_VERIFYING,
        attempts=0, elapsed_seconds=0.5, last_error="",
    )
    updated = json.loads(job_file.read_text(encoding="utf-8"))
    assert updated["cancel_requested_at"] == job["cancel_requested_at"]
    assert updated["cancel_stop_state"] == "waiting_verified_stop"
    assert updated["cancel_stage"] == training_tasks.CANCEL_STAGE_VERIFYING


def test_cancel_wait_diagnostic_ignores_foreign_job_identity(tmp_path):
    job_file = _job_file(tmp_path, task_id="other-task")
    original = job_file.read_text(encoding="utf-8")
    training_tasks._record_cancel_wait_diagnostic(
        _context("task-1"), job_file,
        stage=training_tasks.CANCEL_STAGE_VERIFYING,
        attempts=1, elapsed_seconds=2.0, last_error="x",
    )
    assert job_file.read_text(encoding="utf-8") == original


def _observed_with_process():
    return SimpleNamespace(
        process_pid=4321,
        process_create_time=12345.5,
        process_command_hash="a" * 64,
    )


def _fake_worker_context(task_id="task-cancel"):
    heartbeats = []

    def heartbeat(**kwargs):
        heartbeats.append(dict(kwargs))

    context = SimpleNamespace(
        task=SimpleNamespace(task_id=task_id),
        terminate_result=False,
        heartbeats=heartbeats,
        heartbeat=heartbeat,
    )

    def terminate_bound_process():
        return context.terminate_result

    context.terminate_bound_process = terminate_bound_process
    return context


def test_scheduler_cancel_cleanup_marks_unverified_after_grace(monkeypatch):
    import time as time_module

    from platform_core.task_runtime.scheduler import Scheduler

    monkeypatch.setenv(
        training_tasks.TRAINING_CANCEL_VERIFICATION_GRACE_ENV, "1")
    context = _fake_worker_context()
    Scheduler._cancel_wait_started.clear()

    assert Scheduler._cleanup_bound_process_if_needed(
        context, _observed_with_process(),
        stage="cancelling", current_item="waiting",
    ) is False
    assert context.heartbeats[0]["stage"] == "cancelling"

    Scheduler._cancel_wait_started[context.task.task_id] = (
        time_module.monotonic() - 5)
    assert Scheduler._cleanup_bound_process_if_needed(
        context, _observed_with_process(),
        stage="cancelling", current_item="waiting",
    ) is False
    # Past the grace the stage becomes explicit and the GPU/task stay reserved.
    assert context.heartbeats[-1]["stage"] == "cancelling_unverified"
    assert "not verified" in context.heartbeats[-1]["current_item"]
    assert Scheduler._cancel_wait_started[context.task.task_id]


def test_scheduler_cancel_cleanup_clears_wait_marker_after_verified_stop():
    from platform_core.task_runtime.scheduler import Scheduler

    context = _fake_worker_context()
    Scheduler._cancel_wait_started.clear()
    Scheduler._cancel_wait_started[context.task.task_id] = 123.0
    context.terminate_result = True

    assert Scheduler._cleanup_bound_process_if_needed(
        context, _observed_with_process(),
        stage="cancelling", current_item="waiting",
    ) is True
    assert context.task.task_id not in Scheduler._cancel_wait_started
    assert context.heartbeats == []
