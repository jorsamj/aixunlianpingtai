"""Real, isolated FastAPI evidence for the Vue training stop / recovery contract.

These tests do not start a trainer, scheduler or GPU.  They use the real
TaskRepository SQLite store and the real recovery router, so the assertions are
about persisted task identity rather than mock responses.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app as platform_app
from platform_core.task_runtime import TaskKind, TaskRecord, TaskStatus
from platform_core.task_runtime.artifacts import ArtifactStore
from platform_core.task_runtime.repository import TaskRepository
from platform_core.training_recovery_api import training_recovery_router


def _repository(tmp_path: Path) -> TaskRepository:
    return TaskRepository(tmp_path / "tasks.sqlite3")


def _failed_training(repository: TaskRepository, artifacts: ArtifactStore, project_id: str,
                     task_id: str, *, checkpoint: Path | None, digest: str,
                     failure_stage: str = "final_validation") -> TaskRecord:
    repository.create(TaskRecord.new(
        task_id=task_id, project_id=project_id, kind=TaskKind.TRAINING,
        payload_ref="request.json", resource_key="training:isolated:contract", priority=10,
    ))
    lease = repository.claim_next("vue-contract-worker", [TaskKind.TRAINING], set())
    assert lease is not None and lease.task.task_id == task_id
    repository.finish(task_id, lease.lease_token, TaskStatus.FAILED,
                      error="RuntimeError: final validation failed")
    body = {
        "task_id": task_id,
        "project_id": project_id,
        "failure_stage": failure_stage,
        "completion_error": "final validation worker returned non-zero",
        "completed_epochs": 100,
        "requested_epochs": 100,
        "training_loop_completed": True,
        "checkpoint_available": checkpoint is not None,
        "checkpoints": ([{
            "kind": "best", "path": str(checkpoint),
            "size_bytes": checkpoint.stat().st_size if checkpoint.exists() else 0,
            "sha256": digest,
        }] if checkpoint is not None else []),
        "recoverable": True,
        "recovery_action": "revalidate_checkpoint",
        "recovery_action_available": True,
    }
    artifacts.atomic_write_json(task_id, "failure.json", body)
    task = repository.get(task_id)
    assert task is not None and task.status is TaskStatus.FAILED
    return task


def _client(tmp_path: Path) -> tuple[TestClient, TaskRepository, ArtifactStore]:
    repository = _repository(tmp_path)
    artifacts = ArtifactStore(tmp_path / "artifacts")
    isolated = FastAPI()
    isolated.include_router(training_recovery_router(
        lambda project_id: {"id": project_id},
        lambda: repository,
        lambda: artifacts,
    ))
    return TestClient(isolated), repository, artifacts


def test_vue_stop_persists_the_server_terminal_state_on_the_original_task(client, seeded_project):
    project_id, _image = seeded_project
    repository = platform_app.shared_task_repository()
    task_id = "vue-contract-stop"
    repository.create(TaskRecord.new(
        task_id=task_id, project_id=project_id, kind=TaskKind.TRAINING,
        payload_ref="request.json", resource_key="training:isolated:stop", priority=10,
    ))

    response = client.post(f"/api/v62/projects/{project_id}/tasks/{task_id}/cancel")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["task_id"] == task_id
    assert body["project_id"] == project_id
    # A never-claimed training task can be cancelled without a worker, so the
    # server truth is already terminal.  A claimed/running task keeps the
    # CANCEL_REQUESTED phase covered by tests/api/test_unified_task_process_cancel.py.
    assert body["status"] == "CANCELLED"
    assert body["phase"] == "cancelled"
    assert body["finished_at"]

    persisted = repository.get(task_id)
    assert persisted is not None and persisted.status is TaskStatus.CANCELLED

    detail = client.get(
        f"/api/v62/projects/{project_id}/tasks/{task_id}?reader_view=true"
    ).json()
    assert detail["task"]["task_id"] == task_id
    assert detail["task"]["status"] == "CANCELLED"

    repeated = client.post(f"/api/v62/projects/{project_id}/tasks/{task_id}/cancel")
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["status"] == "CANCELLED"
    assert repository.get(task_id).status is TaskStatus.CANCELLED

    foreign = client.post(f"/api/v62/projects/foreign-project/tasks/{task_id}/cancel")
    assert foreign.status_code == 404
    assert repository.get(task_id).status is TaskStatus.CANCELLED


def test_vue_recovery_truth_requires_a_real_trusted_checkpoint_and_persists_task_identity(tmp_path):
    client, repository, artifacts = _client(tmp_path)
    project_id, task_id = "project-vue-recovery", "vue-contract-recovery"
    checkpoint = tmp_path / "best.pt"
    checkpoint.write_bytes(b"trusted-checkpoint")
    digest = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    before = _failed_training(repository, artifacts, project_id, task_id,
                              checkpoint=checkpoint, digest=digest)

    truth_response = client.get(
        f"/api/v62/projects/{project_id}/training-tasks/{task_id}/recovery")
    assert truth_response.status_code == 200, truth_response.text
    truth = truth_response.json()["recovery"]
    assert truth["task_id"] == task_id
    assert truth["project_id"] == project_id
    assert truth["task_status"] == "FAILED"
    assert truth["available"] is True
    assert truth["recoverable"] is True
    assert truth["checkpoint_available"] is True
    assert truth["recovery_action"] == "revalidate_checkpoint"
    assert truth["failure_stage"] == "final_validation"

    unsupported = client.post(
        f"/api/v62/projects/{project_id}/training-tasks/{task_id}/recovery",
        json={"action": "continue_training"},
    )
    assert unsupported.status_code == 409
    assert repository.get(task_id).status is TaskStatus.FAILED

    accepted = client.post(
        f"/api/v62/projects/{project_id}/training-tasks/{task_id}/recovery",
        json={"action": "revalidate_checkpoint"},
    )
    assert accepted.status_code == 202, accepted.text
    body = accepted.json()
    assert body["ok"] is True
    assert body["task_id"] == task_id
    assert body["status"] == "QUEUED"
    assert body["retry_of"] == task_id
    assert body["attempt"] == before.attempt
    assert body["recovery_requested"] is True
    assert body["recovery_action"] == "revalidate_checkpoint"

    requeued = repository.get(task_id)
    assert requeued.task_id == task_id
    assert requeued.status is TaskStatus.QUEUED
    assert requeued.retry_of == task_id
    assert requeued.attempt == before.attempt
    assert repository.get(f"{task_id}-copy") is None

    after = client.get(
        f"/api/v62/projects/{project_id}/training-tasks/{task_id}/recovery").json()["recovery"]
    assert after["task_status"] == "QUEUED"
    assert after["available"] is False
    assert after["recovery_action"] is None

    duplicate = client.post(
        f"/api/v62/projects/{project_id}/training-tasks/{task_id}/recovery",
        json={"action": "revalidate_checkpoint"},
    )
    assert duplicate.status_code == 409
    assert repository.get(task_id).status is TaskStatus.QUEUED


def test_vue_recovery_rejects_untrusted_hash_unknown_task_and_foreign_project(tmp_path):
    client, repository, artifacts = _client(tmp_path)
    project_id, task_id = "project-vue-recovery-bad", "vue-contract-untrusted"
    checkpoint = tmp_path / "best.pt"
    checkpoint.write_bytes(b"real-checkpoint")
    _failed_training(repository, artifacts, project_id, task_id,
                     checkpoint=checkpoint, digest="0" * 64)

    truth = client.get(
        f"/api/v62/projects/{project_id}/training-tasks/{task_id}/recovery").json()["recovery"]
    assert truth["available"] is False
    assert truth["recoverable"] is False
    assert truth["recovery_action"] is None

    rejected = client.post(
        f"/api/v62/projects/{project_id}/training-tasks/{task_id}/recovery",
        json={"action": "revalidate_checkpoint"},
    )
    assert rejected.status_code == 409
    assert repository.get(task_id).status is TaskStatus.FAILED
    assert repository.get(task_id).retry_of is None

    assert client.get(
        f"/api/v62/projects/{project_id}/training-tasks/unknown-task/recovery"
    ).status_code == 404
    assert client.post(
        f"/api/v62/projects/{project_id}/training-tasks/unknown-task/recovery",
        json={"action": "revalidate_checkpoint"},
    ).status_code == 404
    assert client.get(
        f"/api/v62/projects/foreign-project/training-tasks/{task_id}/recovery"
    ).status_code == 404

    repository.create(TaskRecord.new(
        task_id="vue-contract-batch", project_id=project_id, kind=TaskKind.MATERIAL_BATCH,
        payload_ref="request.json", resource_key="materials:isolated", priority=10,
    ))
    assert client.get(
        f"/api/v62/projects/{project_id}/training-tasks/vue-contract-batch/recovery"
    ).status_code == 404
