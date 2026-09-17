from __future__ import annotations

import pytest

from platform_core.task_runtime import (
    FencedTaskRepository,
    TaskKind,
    TaskRecord,
    TaskRepository,
    TaskStatus,
)


@pytest.mark.parametrize("repository_type", [TaskRepository, FencedTaskRepository])
def test_material_import_confirmation_progress_is_partial_and_resume_never_regresses(
    tmp_path, repository_type
):
    repository = repository_type(tmp_path / f"{repository_type.__name__}.sqlite3")
    repository.create(
        TaskRecord.new(
            "material-progress",
            "project-1",
            TaskKind.MATERIAL_IMPORT,
            "request.json",
            "storage:source-a",
            required_capabilities=("storage.import",),
        )
    )
    lease = repository.claim_next(
        "storage-worker",
        [TaskKind.MATERIAL_IMPORT],
        {"storage.import"},
    )
    assert lease is not None
    repository.heartbeat(
        lease.task.task_id,
        lease.lease_token,
        progress=40,
        stage="SCANNING",
        current_item="incoming/a.jpg",
    )

    awaiting = repository.finish(
        lease.task.task_id,
        lease.lease_token,
        TaskStatus.AWAITING_CONFIRMATION,
        result_ref="scan/result.json",
    )
    assert awaiting.status is TaskStatus.AWAITING_CONFIRMATION
    assert awaiting.progress == 50

    resumed = repository.resume_after_confirmation(lease.task.task_id)
    assert resumed.status is TaskStatus.QUEUED
    assert resumed.stage == "indexing_queued"
    assert resumed.progress == awaiting.progress == 50
