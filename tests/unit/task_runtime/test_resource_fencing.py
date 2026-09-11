from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone

from platform_core.task_runtime import (
    FencedTaskRepository,
    TaskKind,
    TaskRecord,
    TaskStatus,
    launch_process,
)


def _task(task_id: str, resource_key: str = "cpu:conversion") -> TaskRecord:
    return TaskRecord.new(
        task_id,
        "project-1",
        TaskKind.MODEL_CONVERSION,
        "payload.json",
        resource_key,
    )


def test_unresolved_expired_process_fences_same_resource(tmp_path):
    repository = FencedTaskRepository(tmp_path / "tasks.sqlite3")
    repository.create(_task("first"))
    repository.create(_task("second"))
    first = repository.claim_next("worker-a", [TaskKind.MODEL_CONVERSION], set())
    assert first is not None
    assert first.task.task_id == "first"

    launched = launch_process(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        cwd=tmp_path,
    )
    try:
        repository.bind_process(
            "first",
            first.lease_token,
            launched.identity,
            execution_generation=first.task.attempt,
        )
        past = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
        with repository._connect() as database:
            database.execute(
                "UPDATE tasks SET lease_expires_at=? WHERE task_id='first'",
                (past,),
            )

        # Direct release cannot prove the live execution is gone, so it holds
        # the task and resource rather than making a conflicting task runnable.
        assert repository.release_expired() == 0
        held = repository.get("first")
        assert held is not None
        assert held.status is TaskStatus.RUNNING
        assert held.stage == "lease_expired_process_alive"
        assert repository.claim_next(
            "worker-b",
            [TaskKind.MODEL_CONVERSION],
            set(),
        ) is None

        waiting = repository.get("second")
        assert waiting is not None
        assert waiting.status is TaskStatus.QUEUED
        assert waiting.stage == "resource_waiting"
        assert "RESOURCE_RECOVERY_FENCE" in str(waiting.resource_wait_reason)

        repository.reap_expired_processes(timeout=1.0)
        launched.process.wait(timeout=5)
        assert repository.release_expired() == 1
        next_lease = repository.claim_next(
            "worker-b",
            [TaskKind.MODEL_CONVERSION],
            set(),
        )
        assert next_lease is not None
    finally:
        if launched.process.poll() is None:
            launched.process.terminate()
            launched.process.wait(timeout=5)
