from pathlib import Path

import pytest

from platform_core.task_runtime import ArtifactStore, TaskKind, TaskRecord, TaskRepository, TaskStatus


def _failed_task(tmp_path: Path, task_id: str = "attempt-1"):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    artifacts = ArtifactStore(tmp_path / "artifacts")
    artifacts.atomic_write_json(task_id, "payload.json", {"image_ids": ["a", "b"], "mode": "real"})
    original = repository.create(
        TaskRecord.new(
            task_id,
            "project-1",
            TaskKind.MATERIAL_BATCH,
            "payload.json",
            "materials:project-1",
            priority=7,
            required_capabilities=("materials.batch",),
        ),
        artifacts=artifacts,
    )
    lease = repository.claim_next(
        "worker-1",
        [TaskKind.MATERIAL_BATCH],
        {"materials.batch"},
    )
    assert lease is not None
    failed = repository.finish(
        task_id,
        lease.lease_token,
        TaskStatus.FAILED,
        error="real failure",
    )
    return repository, artifacts, original, failed


def test_retry_creates_new_task_and_preserves_terminal_source_row(tmp_path: Path):
    repository, artifacts, _original, failed = _failed_task(tmp_path)

    retried = repository.retry(failed.task_id)

    assert retried.task_id != failed.task_id
    assert retried.retry_of == failed.task_id
    assert retried.status is TaskStatus.QUEUED
    assert retried.attempt == 0
    assert retried.priority == failed.priority
    assert retried.resource_key == failed.resource_key
    assert retried.required_capabilities == failed.required_capabilities
    assert retried.error is None
    assert retried.result_ref is None
    assert retried.finished_at is None

    preserved = repository.get(failed.task_id)
    assert preserved == failed
    assert preserved.status is TaskStatus.FAILED
    assert preserved.error == "real failure"
    assert preserved.finished_at is not None

    assert artifacts.read_json(retried.task_id, retried.payload_ref) == {
        "image_ids": ["a", "b"],
        "mode": "real",
    }
    assert artifacts.artifact_path(retried.task_id, retried.log_ref).is_file()


def test_retry_double_submit_is_idempotent_while_child_is_active(tmp_path: Path):
    repository, _artifacts, _original, failed = _failed_task(tmp_path)

    first = repository.retry(failed.task_id)
    second = repository.retry(failed.task_id)

    assert second.task_id == first.task_id
    children = [row for row in repository.list(project_id="project-1", limit=20).items if row.retry_of == failed.task_id]
    assert [row.task_id for row in children] == [first.task_id]


def test_retry_chain_must_continue_from_latest_terminal_attempt(tmp_path: Path):
    repository, _artifacts, _original, failed = _failed_task(tmp_path)
    second = repository.retry(failed.task_id)
    lease = repository.claim_next(
        "worker-2",
        [TaskKind.MATERIAL_BATCH],
        {"materials.batch"},
    )
    assert lease is not None
    assert lease.task.task_id == second.task_id
    second_failed = repository.finish(
        second.task_id,
        lease.lease_token,
        TaskStatus.FAILED,
        error="second failure",
    )

    with pytest.raises(ValueError, match="retry the latest attempt"):
        repository.retry(failed.task_id)

    third = repository.retry(second_failed.task_id)
    assert third.task_id not in {failed.task_id, second_failed.task_id}
    assert third.retry_of == second_failed.task_id


def test_retry_rejects_missing_payload_without_mutating_source(tmp_path: Path):
    repository, artifacts, _original, failed = _failed_task(tmp_path)
    artifacts.artifact_path(failed.task_id, failed.payload_ref).unlink()

    with pytest.raises(ValueError, match="payload artifact is missing"):
        repository.retry(failed.task_id)

    assert repository.get(failed.task_id) == failed
    rows = repository.list(project_id="project-1", limit=20).items
    assert len(rows) == 1


def test_retry_rejects_post_processing_failure_generic_path(tmp_path: Path):
    repository, artifacts, _original, failed = _failed_task(tmp_path)
    with repository._connect() as database:
        database.execute(
            "UPDATE tasks SET status='POST_PROCESSING_FAILED', result_ref='result.json' WHERE task_id=?",
            (failed.task_id,),
        )
    artifacts.atomic_write_json(failed.task_id, "result.json", {"verified_models": ["best.pt"]})

    with pytest.raises(ValueError, match="terminal tasks"):
        repository.retry(failed.task_id)
