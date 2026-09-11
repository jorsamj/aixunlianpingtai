from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone

import psutil
import pytest

from platform_core.task_runtime import (
    ArtifactStore,
    ExecutionFencedError,
    FencedTaskRepository,
    ProcessIdentity,
    Scheduler,
    TaskKind,
    TaskRecord,
    TaskStatus,
    WorkerContext,
    hash_command,
    launch_process,
)


def _add(repository, task_id="task-1"):
    return repository.create(
        TaskRecord.new(
            task_id,
            "project-1",
            TaskKind.VIDEO_FRAMES,
            "payload.json",
            "cpu:video",
        )
    )


def _expire(repository, task_id: str) -> None:
    past = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    with repository._connect() as database:
        database.execute(
            "UPDATE tasks SET lease_expires_at=? WHERE task_id=?",
            (past, task_id),
        )


def test_expired_heartbeat_cannot_resurrect_execution(tmp_path):
    repository = FencedTaskRepository(tmp_path / "tasks.sqlite3")
    _add(repository)
    lease = repository.claim_next("worker-a", [TaskKind.VIDEO_FRAMES], set(), lease_seconds=30)
    assert lease is not None
    _expire(repository, "task-1")

    with pytest.raises(PermissionError, match="execution"):
        repository.heartbeat(
            "task-1",
            lease.lease_token,
            progress=25,
            execution_generation=lease.task.attempt,
        )

    current = repository.get("task-1")
    assert current is not None
    assert current.status is TaskStatus.RUNNING
    assert current.progress == 0


def test_live_process_blocks_requeue_until_exact_tree_is_reaped(tmp_path):
    repository = FencedTaskRepository(tmp_path / "tasks.sqlite3")
    _add(repository)
    lease = repository.claim_next("worker-a", [TaskKind.VIDEO_FRAMES], set(), lease_seconds=30)
    assert lease is not None
    launched = launch_process(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        cwd=tmp_path,
    )
    try:
        repository.bind_process(
            "task-1",
            lease.lease_token,
            launched.identity,
            execution_generation=lease.task.attempt,
        )
        _expire(repository, "task-1")

        assert repository.release_expired() == 0
        blocked = repository.get("task-1")
        assert blocked is not None
        assert blocked.status is TaskStatus.RUNNING
        assert blocked.stage == "lease_expired_process_alive"
        assert psutil.pid_exists(launched.identity.pid)
        assert repository.claim_next("worker-b", [TaskKind.VIDEO_FRAMES], set()) is None

        assert repository.reap_expired_processes(timeout=1.0) == 1
        assert launched.process.wait(timeout=5) is not None
        assert repository.release_expired() == 1
        recovered = repository.get("task-1")
        assert recovered is not None
        assert recovered.status is TaskStatus.QUEUED
        assert recovered.stage == "recovered"
        assert recovered.process_pid is None
    finally:
        if launched.process.poll() is None:
            launched.process.terminate()
            launched.process.wait(timeout=5)


def test_pid_identity_mismatch_never_kills_unrelated_process_and_allows_recovery(tmp_path):
    repository = FencedTaskRepository(tmp_path / "tasks.sqlite3")
    _add(repository)
    lease = repository.claim_next("worker-a", [TaskKind.VIDEO_FRAMES], set())
    assert lease is not None
    launched = launch_process(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        cwd=tmp_path,
    )
    try:
        wrong_identity = ProcessIdentity(
            launched.identity.pid,
            launched.identity.create_time,
            hash_command([sys.executable, "-c", "print('different command')"]),
        )
        repository.bind_process(
            "task-1",
            lease.lease_token,
            wrong_identity,
            execution_generation=lease.task.attempt,
        )
        _expire(repository, "task-1")

        assert repository.reap_expired_processes(timeout=0.2) == 0
        assert launched.process.poll() is None
        assert repository.release_expired() == 1
        assert repository.get("task-1").status is TaskStatus.QUEUED
        assert launched.process.poll() is None
    finally:
        launched.process.terminate()
        launched.process.wait(timeout=5)


def test_execution_generation_fences_old_attempt_even_if_token_matches(tmp_path):
    repository = FencedTaskRepository(tmp_path / "tasks.sqlite3")
    _add(repository)
    first = repository.claim_next("worker-a", [TaskKind.VIDEO_FRAMES], set())
    assert first is not None
    _expire(repository, "task-1")
    assert repository.release_expired() == 1
    second = repository.claim_next("worker-b", [TaskKind.VIDEO_FRAMES], set())
    assert second is not None
    assert second.task.attempt == first.task.attempt + 1

    # Simulate an impossible token collision to prove attempt/generation is a
    # separate fence rather than relying on UUID uniqueness alone.
    with repository._connect() as database:
        database.execute(
            "UPDATE tasks SET lease_token=? WHERE task_id=?",
            (first.lease_token, "task-1"),
        )

    with pytest.raises(PermissionError, match="execution"):
        repository.finish(
            "task-1",
            first.lease_token,
            TaskStatus.SUCCEEDED,
            execution_generation=first.task.attempt,
        )

    finished = repository.finish(
        "task-1",
        first.lease_token,
        TaskStatus.SUCCEEDED,
        execution_generation=second.task.attempt,
    )
    assert finished.status is TaskStatus.SUCCEEDED


def test_fenced_context_refuses_artifact_publication(tmp_path):
    repository = FencedTaskRepository(tmp_path / "tasks.sqlite3")
    artifacts = ArtifactStore(tmp_path / "artifacts")
    _add(repository)
    lease = repository.claim_next("worker-a", [TaskKind.VIDEO_FRAMES], set())
    assert lease is not None
    context = WorkerContext(lease.task, lease, repository, artifacts)
    context.mark_lease_lost()

    with pytest.raises(ExecutionFencedError):
        context.artifacts.atomic_write_json("task-1", "result.json", {"stale": True})
    assert not artifacts.artifact_path("task-1", "result.json").exists()


def test_scheduler_does_not_publish_success_after_execution_expires(tmp_path):
    repository = FencedTaskRepository(tmp_path / "tasks.sqlite3")
    artifacts = ArtifactStore(tmp_path / "artifacts")
    _add(repository)

    class ExpiringHandler:
        def run(self, context):
            _expire(repository, context.task.task_id)
            return TaskStatus.SUCCEEDED, "result.json"

        recover = run

    scheduler = Scheduler(
        repository,
        artifacts,
        "worker-a",
        {TaskKind.VIDEO_FRAMES: ExpiringHandler()},
        set(),
        lease_seconds=30,
    )
    assert scheduler.run_once() is True
    stale = repository.get("task-1")
    assert stale is not None
    assert stale.status is TaskStatus.RUNNING
    assert stale.finished_at is None

    # On the next scheduling pass the expired process-less attempt is safely
    # recovered before another execution can be claimed.
    assert repository.release_expired() == 1
    recovered = repository.get("task-1")
    assert recovered.status is TaskStatus.QUEUED
    assert recovered.stage == "recovered"
