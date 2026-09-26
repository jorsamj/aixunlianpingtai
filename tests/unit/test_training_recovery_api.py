import hashlib
from types import SimpleNamespace

import pytest

from platform_core.task_runtime import TaskKind, TaskStatus
from platform_core.training_recovery_api import (
    RECOVERY_ACTION_REVALIDATE,
    request_training_recovery,
    training_recovery_truth,
)


class FakeArtifacts:
    def __init__(self, failure):
        self.failure = dict(failure)

    def read_json(self, task_id, ref, default=None):
        if ref == "failure.json":
            return dict(self.failure)
        return default


class FakeRepository:
    def __init__(self, task):
        self.task = task
        self.retry_calls = []

    def get(self, task_id):
        return self.task if task_id == self.task.task_id else None

    def retry(self, task_id):
        self.retry_calls.append(task_id)
        return SimpleNamespace(
            task_id=self.task.task_id,
            project_id=self.task.project_id,
            kind=self.task.kind,
            status=TaskStatus.QUEUED,
            stage="queued",
            retry_of=self.task.task_id,
            attempt=int(self.task.attempt or 0),
        )


def failed_training_task(task_id="train-recovery", project_id="project-recovery"):
    return SimpleNamespace(
        task_id=task_id,
        project_id=project_id,
        kind=TaskKind.TRAINING,
        status=TaskStatus.FAILED,
        error="RuntimeError: final validation failed",
        current_item="最终模型验证失败",
        attempt=1,
        retry_of=None,
    )


def recovery_failure(task, checkpoint_path, sha256, **overrides):
    body = {
        "task_id": task.task_id,
        "project_id": task.project_id,
        "failure_stage": "final_validation",
        "completion_error": "final validation worker returned non-zero",
        "completed_epochs": 100,
        "requested_epochs": 100,
        "training_loop_completed": True,
        "checkpoint_available": True,
        "checkpoints": [
            {
                "kind": "best",
                "path": str(checkpoint_path),
                "size_bytes": checkpoint_path.stat().st_size if checkpoint_path.exists() else 0,
                "sha256": sha256,
            }
        ],
        "recoverable": True,
        "recovery_action": RECOVERY_ACTION_REVALIDATE,
        "recovery_action_available": True,
    }
    body.update(overrides)
    return body


def test_completed_epochs_alone_never_create_recovery_truth(tmp_path):
    task = failed_training_task()
    checkpoint = tmp_path / "best.pt"
    checkpoint.write_bytes(b"checkpoint")
    digest = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    failure = recovery_failure(task, checkpoint, digest)
    failure.pop("task_id")
    failure.pop("project_id")

    truth = training_recovery_truth(task, FakeArtifacts(failure))

    assert truth["completed_epochs"] == 0
    assert truth["training_loop_completed"] is False
    assert truth["checkpoint_available"] is False
    assert truth["recoverable"] is False
    assert truth["available"] is False
    assert truth["recovery_action"] is None


def test_declared_recovery_requires_an_existing_best_checkpoint(tmp_path):
    task = failed_training_task()
    missing = tmp_path / "missing" / "best.pt"
    failure = recovery_failure(task, missing, "a" * 64)

    truth = training_recovery_truth(task, FakeArtifacts(failure))

    assert truth["training_loop_completed"] is True
    assert truth["checkpoint_available"] is False
    assert truth["recoverable"] is False
    assert truth["available"] is False


def test_recovery_action_rejects_checkpoint_hash_mismatch_without_retry(tmp_path):
    task = failed_training_task()
    checkpoint = tmp_path / "best.pt"
    checkpoint.write_bytes(b"real-checkpoint")
    artifacts = FakeArtifacts(recovery_failure(task, checkpoint, "0" * 64))
    repository = FakeRepository(task)

    with pytest.raises(RuntimeError, match="no trusted recoverable checkpoint"):
        request_training_recovery(
            repository,
            artifacts,
            task.project_id,
            task.task_id,
            RECOVERY_ACTION_REVALIDATE,
        )

    assert repository.retry_calls == []


def test_recovery_action_requeues_same_task_after_checkpoint_hash_verification(tmp_path):
    task = failed_training_task()
    checkpoint = tmp_path / "best.pt"
    checkpoint.write_bytes(b"trusted-checkpoint")
    digest = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    artifacts = FakeArtifacts(recovery_failure(task, checkpoint, digest))
    repository = FakeRepository(task)

    retried, before = request_training_recovery(
        repository,
        artifacts,
        task.project_id,
        task.task_id,
        RECOVERY_ACTION_REVALIDATE,
    )

    assert before["available"] is True
    assert before["recoverable"] is True
    assert before["checkpoint_available"] is True
    assert before["recovery_action"] == RECOVERY_ACTION_REVALIDATE
    assert repository.retry_calls == [task.task_id]
    assert retried.task_id == task.task_id
    assert retried.status is TaskStatus.QUEUED
    assert retried.retry_of == task.task_id


def test_recovery_reason_prefers_worker_root_cause_over_completion_handshake(tmp_path):
    task = failed_training_task()
    checkpoint = tmp_path / "best.pt"
    checkpoint.write_bytes(b"checkpoint")
    digest = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    failure = recovery_failure(
        task,
        checkpoint,
        digest,
        last_job_message="训练失败：RESOURCE_RUNTIME_MISMATCH: resolved workers=2; runtime workers=0",
        completion_error="job status is not done",
    )

    truth = training_recovery_truth(task, FakeArtifacts(failure))

    assert truth["failure_reason"].startswith("训练失败：RESOURCE_RUNTIME_MISMATCH")
    assert truth["failure_reason"] != "job status is not done"
    assert truth["completion_handshake"] == "job status is not done"
