from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier

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


def test_resume_after_confirmation_requeues_material_import_and_is_idempotent(tmp_path):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    repository.create(
        TaskRecord.new(
            "import-1",
            "project-1",
            TaskKind.MATERIAL_IMPORT,
            "requests/import.json",
            "cpu:local",
            required_capabilities=("archive",),
        )
    )
    lease = repository.claim_next("import-worker", [TaskKind.MATERIAL_IMPORT], {"archive"})
    assert lease is not None
    repository.heartbeat(
        "import-1",
        lease.lease_token,
        progress=75,
        stage="reviewing",
        current_item="batch-7",
    )
    repository.finish(
        "import-1",
        lease.lease_token,
        TaskStatus.AWAITING_CONFIRMATION,
        result_ref="candidates/manifest.json",
        error="needs confirmation",
    )

    resumed = repository.resume_after_confirmation("import-1")

    assert resumed.status is TaskStatus.QUEUED
    assert resumed.stage == "indexing_queued"
    assert resumed.progress == 0
    assert resumed.current_item is None
    assert resumed.error is None
    assert resumed.accepted is True
    assert resumed.finished_at is None
    assert resumed.result_ref == "candidates/manifest.json"
    assert repository.resume_after_confirmation("import-1") == resumed


def test_resume_after_confirmation_rejects_rejected_material_import(tmp_path):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    repository.create(
        TaskRecord.new(
            "import-rejected",
            "project-1",
            TaskKind.MATERIAL_IMPORT,
            "requests/import.json",
            "cpu:local",
            required_capabilities=("archive",),
        )
    )
    lease = repository.claim_next("import-worker", [TaskKind.MATERIAL_IMPORT], {"archive"})
    assert lease is not None
    repository.finish(
        "import-rejected",
        lease.lease_token,
        TaskStatus.AWAITING_CONFIRMATION,
        accepted=False,
    )
    before = repository.get("import-rejected")

    with pytest.raises(ValueError, match="cannot resume"):
        repository.resume_after_confirmation("import-rejected")

    assert repository.get("import-rejected") == before


def test_resume_after_confirmation_is_atomic_for_concurrent_confirmations(tmp_path):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    repository.create(
        TaskRecord.new(
            "import-concurrent",
            "project-1",
            TaskKind.MATERIAL_IMPORT,
            "requests/import.json",
            "cpu:local",
            required_capabilities=("archive",),
        )
    )
    lease = repository.claim_next("import-worker", [TaskKind.MATERIAL_IMPORT], {"archive"})
    assert lease is not None
    repository.finish(
        "import-concurrent",
        lease.lease_token,
        TaskStatus.AWAITING_CONFIRMATION,
    )
    barrier = Barrier(2)

    def confirm():
        barrier.wait()
        return repository.resume_after_confirmation("import-concurrent")

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(confirm) for _ in range(2)]
        results = [future.result() for future in futures]

    assert all(record.accepted is True for record in results)
    assert all(record.status is TaskStatus.QUEUED for record in results)
    assert all(record.stage == "indexing_queued" for record in results)
    assert len({record.updated_at for record in results}) == 1


def test_confirmed_material_import_keeps_indexing_stage_through_claim_and_recovery(tmp_path):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    repository.create(
        TaskRecord.new(
            "import-indexing",
            "project-1",
            TaskKind.MATERIAL_IMPORT,
            "requests/import.json",
            "cpu:import",
            required_capabilities=("archive",),
        )
    )
    initial_lease = repository.claim_next(
        "import-worker", [TaskKind.MATERIAL_IMPORT], {"archive"}
    )
    assert initial_lease is not None
    repository.finish(
        "import-indexing",
        initial_lease.lease_token,
        TaskStatus.AWAITING_CONFIRMATION,
    )
    repository.resume_after_confirmation("import-indexing")
    repository.create(
        TaskRecord.new(
            "training-indexing",
            "project-1",
            TaskKind.TRAINING,
            "requests/training.json",
            "cpu:training",
            required_capabilities=("cuda",),
        )
    )

    import_lease = repository.claim_next(
        "import-worker", [TaskKind.MATERIAL_IMPORT], {"archive"}
    )
    training_lease = repository.claim_next("training-worker", [TaskKind.TRAINING], {"cuda"})

    assert import_lease is not None
    assert import_lease.task.stage == "indexing"
    assert repository.resume_after_confirmation("import-indexing") == import_lease.task
    assert training_lease is not None
    assert training_lease.task.stage == "running"
    assert repository.release_expired(datetime.now(timezone.utc) + timedelta(minutes=1)) == 2
    recovered_import = repository.get("import-indexing")
    recovered_training = repository.get("training-indexing")
    assert recovered_import is not None
    assert recovered_import.stage == "indexing_queued"
    assert repository.resume_after_confirmation("import-indexing") == recovered_import
    assert recovered_training is not None
    assert recovered_training.stage == "recovered"

    running = replace(
        TaskRecord.new(
            "import-running",
            "project-1",
            TaskKind.MATERIAL_IMPORT,
            "requests/import.json",
            "cpu:other",
        ),
        status=TaskStatus.RUNNING,
        stage="running",
        accepted=True,
    )
    repository.create(running)
    with pytest.raises(ValueError, match="cannot resume"):
        repository.resume_after_confirmation("import-running")
    assert repository.get("import-running") == running


def test_promote_can_move_a_task_ahead_even_when_current_priority_is_one(tmp_path):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    add(repository, "first", "project-1", 1, resource="gpu:0")
    add(repository, "promoted", "project-1", 50, resource="gpu:0")

    updated = repository.promote("promoted")
    assert updated.priority == 1
    lease = repository.claim_next("worker", [TaskKind.TRAINING], {"cuda"})
    assert lease is not None
    assert lease.task.task_id == "promoted"
