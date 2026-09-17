import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from platform_core import training_tasks
from platform_core.task_runtime import ArtifactStore, TaskKind, TaskRecord, TaskRepository
from platform_core.task_runtime.process_control import ProcessIdentity
from platform_core.task_runtime.worker import WorkerContext


def _running_context(tmp_path: Path):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    artifacts = ArtifactStore(tmp_path / "artifacts")
    task = TaskRecord.new(
        "train-terminal",
        "project-one",
        TaskKind.TRAINING,
        "payload.json",
        "training:cpu",
        required_capabilities=("training.ultralytics",),
    )
    repository.create(task)
    lease = repository.claim_next(
        "worker-one",
        (TaskKind.TRAINING,),
        {"training.ultralytics"},
    )
    assert lease is not None
    return repository, WorkerContext(lease.task, lease, repository, artifacts)


def test_trusted_target_reached_job_terminates_lingering_child_then_finalizes(tmp_path, monkeypatch):
    _, context = _running_context(tmp_path)
    model = tmp_path / "project" / "models" / "train_terminal_best.pt"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"verified-model")
    job_file = tmp_path / "project" / "jobs" / "train-terminal" / "job.json"
    job_file.parent.mkdir(parents=True)
    job_file.write_text(
        json.dumps(
            {
                "id": "train-terminal",
                "task_id": "train-terminal",
                "status": "done",
                "artifact_verified": True,
                "verified_models": [str(model)],
                "best_path": str(model),
                "last_path": "",
                "training_outcome": "target_reached",
                "completion_reason": "quality_target_reached",
                "finished_at": "2026-09-15T01:02:03+00:00",
                "message": "训练提前完成，模型产物校验通过",
            }
        ),
        encoding="utf-8",
    )

    class LingeringProcess:
        returncode = None

        def __init__(self):
            self.poll_count = 0

        def poll(self):
            self.poll_count += 1
            if self.poll_count >= 5 and self.returncode is None:
                self.returncode = 9
            return self.returncode

    process = LingeringProcess()
    identity = ProcessIdentity(12345, 1.0, "command-hash")
    monkeypatch.setattr(
        training_tasks,
        "launch_process",
        lambda *_args, **_kwargs: SimpleNamespace(process=process, identity=identity),
    )
    monkeypatch.setattr(training_tasks, "TRAINING_COMPLETION_GRACE_SECONDS", 0.0, raising=False)
    terminated = []

    class RecordingController:
        def terminate_tree(self, observed, timeout=5.0):
            terminated.append((observed, timeout))
            process.returncode = -15

    monkeypatch.setattr(training_tasks, "ProcessController", RecordingController)

    job = training_tasks._run_training_process(context, ["python", "train_worker.py"], job_file)

    assert job["training_outcome"] == "target_reached"
    assert terminated == [(identity, 5.0)]


def test_done_job_without_verified_artifact_is_not_a_success_handshake(tmp_path, monkeypatch):
    _, context = _running_context(tmp_path)
    job_file = tmp_path / "project" / "jobs" / "train-terminal" / "job.json"
    job_file.parent.mkdir(parents=True)
    job_file.write_text(
        json.dumps(
            {
                "id": "train-terminal",
                "status": "done",
                "artifact_verified": False,
                "verified_models": [],
                "training_outcome": "completed",
                "finished_at": "2026-09-15T01:02:03+00:00",
                "message": "产物未验证",
            }
        ),
        encoding="utf-8",
    )

    process = SimpleNamespace(returncode=1, poll=lambda: 1)
    monkeypatch.setattr(
        training_tasks,
        "launch_process",
        lambda *_args, **_kwargs: SimpleNamespace(
            process=process,
            identity=ProcessIdentity(12345, 1.0, "command-hash"),
        ),
    )

    with pytest.raises(RuntimeError, match="产物未验证"):
        training_tasks._run_training_process(context, ["python", "train_worker.py"], job_file)


def test_terminal_job_for_another_task_never_stops_current_process(tmp_path, monkeypatch):
    _, context = _running_context(tmp_path)
    model = tmp_path / "project" / "models" / "other_best.pt"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"verified-model")
    job_file = tmp_path / "project" / "jobs" / "train-terminal" / "job.json"
    job_file.parent.mkdir(parents=True)
    job_file.write_text(
        json.dumps(
            {
                "task_id": "another-task",
                "status": "done",
                "artifact_verified": True,
                "verified_models": [str(model)],
                "best_path": str(model),
                "training_outcome": "completed",
                "finished_at": "2026-09-15T01:02:03+00:00",
            }
        ),
        encoding="utf-8",
    )

    class ExitingProcess:
        returncode = None

        def __init__(self):
            self.poll_count = 0

        def poll(self):
            self.poll_count += 1
            if self.poll_count >= 2:
                self.returncode = 1
            return self.returncode

    process = ExitingProcess()
    identity = ProcessIdentity(12345, 1.0, "command-hash")
    monkeypatch.setattr(
        training_tasks,
        "launch_process",
        lambda *_args, **_kwargs: SimpleNamespace(process=process, identity=identity),
    )
    terminated = []

    class RecordingController:
        def terminate_tree(self, observed, timeout=5.0):
            terminated.append((observed, timeout))

    monkeypatch.setattr(training_tasks, "ProcessController", RecordingController)

    with pytest.raises(RuntimeError):
        training_tasks._run_training_process(context, ["python", "train_worker.py"], job_file)

    assert terminated == []


def test_finalization_and_cancel_have_one_atomic_winner(tmp_path):
    repository, cancelled_context = _running_context(tmp_path / "cancel-first")
    repository.request_cancel(cancelled_context.task.task_id)

    with pytest.raises(InterruptedError):
        cancelled_context.begin_finalization()

    repository, completed_context = _running_context(tmp_path / "complete-first")
    completed_context.begin_finalization()

    with pytest.raises(ValueError, match="正在归档"):
        repository.request_cancel(completed_context.task.task_id)

    current = repository.get(completed_context.task.task_id)
    assert current.status.value == "RUNNING"
    assert current.stage == "finalizing_commit"


def test_result_without_committed_checkpoint_cannot_skip_version_archive(tmp_path):
    _, context = _running_context(tmp_path)
    output = context.artifacts.artifact_path(context.task.task_id, "outputs/00_best.pt")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"verified-model")
    context.artifacts.atomic_write_json(
        context.task.task_id,
        "result.json",
        {
            "verified_models": [
                {
                    "ref": "outputs/00_best.pt",
                    "sha256": hashlib.sha256(b"verified-model").hexdigest(),
                    "size_bytes": len(b"verified-model"),
                }
            ]
        },
    )

    assert training_tasks.TrainingHandler(tmp_path)._committed(context) is None
