from datetime import datetime, timedelta, timezone

import pytest

from platform_core.task_runtime import TaskKind, TaskRecord, TaskRepository, TaskStatus


def add(
    repository,
    task_id,
    project_id,
    priority,
    resource="gpu:local:0",
    capability="cuda",
):
    return repository.create(
        TaskRecord.new(
            task_id=task_id,
            project_id=project_id,
            kind=TaskKind.TRAINING,
            payload_ref="payload.json",
            resource_key=resource,
            priority=priority,
            required_capabilities=(capability,),
        )
    )


def test_wal_claim_is_global_low_number_first_and_fifo(tmp_path):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    add(repository, "late", "project-1", 20)
    add(repository, "first", "project-2", 3)
    add(repository, "second", "project-3", 3)

    assert repository.journal_mode() == "wal"
    first = repository.claim_next("worker-1", [TaskKind.TRAINING], {"cuda"}, 30)
    assert first is not None
    assert first.task.task_id == "first"
    assert first.task.attempt == 1
    assert repository.claim_next("worker-2", [TaskKind.TRAINING], {"cuda"}, 30) is None

    repository.finish("first", first.lease_token, TaskStatus.SUCCEEDED, "result.json")
    second = repository.claim_next("worker-2", [TaskKind.TRAINING], {"cuda"}, 30)
    assert second is not None
    assert second.task.task_id == "second"


def test_capability_cancel_retry_cursor_and_expired_lease(tmp_path):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    add(repository, "cpu-only", "project-1", 1, "cpu:local", "opencv")
    assert repository.claim_next("gpu", [TaskKind.TRAINING], {"cuda"}) is None

    page = repository.list(project_id="project-1", limit=1)
    assert page.items[0].task_id == "cpu-only"
    cancelled = repository.request_cancel("cpu-only")
    assert cancelled.status is TaskStatus.CANCELLED
    assert cancelled.finished_at is not None

    retried = repository.retry("cpu-only")
    assert retried.task_id == "cpu-only"
    assert retried.status is TaskStatus.QUEUED
    assert retried.retry_of == "cpu-only"
    assert retried.error is None
    assert retried.finished_at is None

    lease = repository.claim_next("cpu", [TaskKind.TRAINING], {"opencv"}, lease_seconds=1)
    assert lease is not None
    future = datetime.now(timezone.utc) + timedelta(seconds=2)
    assert repository.release_expired(future) == 1
    recovered = repository.get(lease.task.task_id)
    assert recovered is not None
    assert recovered.status is TaskStatus.QUEUED
    assert recovered.stage == "recovered"
    assert recovered.attempt == 1


def test_heartbeat_and_finish_require_the_current_lease(tmp_path):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    add(repository, "task-1", "project-1", 5)
    lease = repository.claim_next("worker", [TaskKind.TRAINING], {"cuda"})
    assert lease is not None

    with pytest.raises(PermissionError, match="lease"):
        repository.heartbeat("task-1", "wrong", progress=25)

    running = repository.heartbeat(
        "task-1",
        lease.lease_token,
        progress=25,
        stage="preparing",
        current_item="image-3",
    )
    assert (running.progress, running.stage, running.current_item) == (
        25,
        "preparing",
        "image-3",
    )

    with pytest.raises(PermissionError, match="lease"):
        repository.finish("task-1", "wrong", TaskStatus.SUCCEEDED)

    finished = repository.finish(
        "task-1",
        lease.lease_token,
        TaskStatus.SUCCEEDED,
        result_ref="result.json",
    )
    assert finished.status is TaskStatus.SUCCEEDED
    assert finished.progress == 100
    assert finished.finished_at is not None


def test_list_cursor_is_bounded_and_deterministic(tmp_path):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    for index in range(5):
        add(repository, f"task-{index}", "project-1", index + 1, resource=f"cpu:{index}")

    first = repository.list(project_id="project-1", limit=2)
    second = repository.list(project_id="project-1", limit=2, cursor=first.next_cursor)
    third = repository.list(project_id="project-1", limit=2, cursor=second.next_cursor)
    ids = [item.task_id for page in (first, second, third) for item in page.items]
    assert len(ids) == 5
    assert len(set(ids)) == 5
    assert third.next_cursor is None


def test_complete_review_is_guarded_idempotent_and_keeps_explicit_rejection(tmp_path):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    record = TaskRecord.new(
        "ai-1",
        "project-1",
        TaskKind.AI_ANNOTATION,
        "request.json",
        "vision:model-1",
        required_capabilities=("vision_provider",),
    )
    repository.create(record)
    lease = repository.claim_next(
        "vision-worker",
        [TaskKind.AI_ANNOTATION],
        {"vision_provider"},
    )
    assert lease is not None
    awaiting = repository.finish(
        "ai-1",
        lease.lease_token,
        TaskStatus.AWAITING_CONFIRMATION,
        "candidates/manifest.json",
    )
    assert awaiting.finished_at is None

    rejected = repository.complete_review(
        "ai-1",
        TaskStatus.SUCCEEDED,
        "review/result.json",
        accepted=False,
    )
    assert rejected.accepted is False
    assert rejected.finished_at is not None
    same = repository.complete_review(
        "ai-1",
        TaskStatus.SUCCEEDED,
        "review/result.json",
        accepted=False,
    )
    assert same == rejected

    with pytest.raises(ValueError, match="conflicting review"):
        repository.complete_review(
            "ai-1",
            TaskStatus.PARTIAL_SUCCESS,
            "review/other.json",
            accepted=True,
        )
