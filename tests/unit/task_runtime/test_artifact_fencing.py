from __future__ import annotations

import pytest

from platform_core.task_runtime import (
    ArtifactStore,
    ExecutionFencedError,
    FencedTaskRepository,
    TaskKind,
    TaskRecord,
    WorkerContext,
)


def test_atomic_artifact_rechecks_execution_before_publish(tmp_path):
    repository = FencedTaskRepository(tmp_path / "tasks.sqlite3")
    artifacts = ArtifactStore(tmp_path / "artifacts")
    repository.create(
        TaskRecord.new(
            "artifact-task",
            "project-1",
            TaskKind.VIDEO_FRAMES,
            "payload.json",
            "cpu:video",
        )
    )
    lease = repository.claim_next("worker-a", [TaskKind.VIDEO_FRAMES], set())
    assert lease is not None
    context = WorkerContext(lease.task, lease, repository, artifacts)

    real_assert = context.assert_current_execution
    calls = 0

    def fence_at_publish():
        nonlocal calls
        calls += 1
        if calls >= 2:
            context.mark_lease_lost()
            raise ExecutionFencedError("lost immediately before publish")
        return real_assert()

    context.assert_current_execution = fence_at_publish  # type: ignore[method-assign]
    with pytest.raises(ExecutionFencedError, match="before publish"):
        context.artifacts.atomic_write_json(
            "artifact-task",
            "result.json",
            {"must_not_publish": True},
        )

    result = artifacts.artifact_path("artifact-task", "result.json")
    assert not result.exists()
    assert not list(result.parent.glob(".result.json.*.tmp"))
