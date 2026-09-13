from platform_core.task_runtime import FencedTaskRepository, TaskKind, TaskRecord, TaskRepository


def _claim(repository, task_id: str):
    repository.create(
        TaskRecord.new(
            task_id=task_id,
            project_id="project-1",
            kind=TaskKind.TRAINING,
            payload_ref="payload.json",
            resource_key=f"gpu:{task_id}",
            priority=10,
            required_capabilities=("cuda",),
        )
    )
    lease = repository.claim_next("worker-control-stage", [TaskKind.TRAINING], {"cuda"})
    assert lease is not None
    return lease


def test_base_worker_heartbeat_cannot_override_control_plane_stage(tmp_path):
    repository = TaskRepository(tmp_path / "base.sqlite3")
    lease = _claim(repository, "base-control-stage")

    paused = repository.set_stage(lease.task.task_id, "paused")
    assert paused.stage == "paused"

    stale = repository.heartbeat(
        lease.task.task_id,
        lease.lease_token,
        progress=61,
        stage="training",
        current_item="epoch-6",
    )
    assert stale.stage == "paused"
    assert stale.progress == 61
    assert stale.current_item == "epoch-6"

    resumed = repository.set_stage(lease.task.task_id, "training")
    assert resumed.stage == "training"
    current = repository.heartbeat(
        lease.task.task_id,
        lease.lease_token,
        progress=62,
        stage="training",
    )
    assert current.stage == "training"

    cancelling = repository.request_cancel(lease.task.task_id)
    assert cancelling.stage == "cancelling"
    stale_after_cancel = repository.heartbeat(
        lease.task.task_id,
        lease.lease_token,
        progress=63,
        stage="training",
    )
    assert stale_after_cancel.status.value == "CANCEL_REQUESTED"
    assert stale_after_cancel.stage == "cancelling"
    assert stale_after_cancel.progress == 63


def test_fenced_worker_heartbeat_cannot_override_control_plane_stage(tmp_path):
    repository = FencedTaskRepository(tmp_path / "fenced.sqlite3")
    lease = _claim(repository, "fenced-control-stage")
    generation = lease.task.attempt

    paused = repository.set_stage(lease.task.task_id, "paused")
    assert paused.stage == "paused"

    stale = repository.heartbeat(
        lease.task.task_id,
        lease.lease_token,
        progress=61,
        stage="training",
        current_item="epoch-6",
        execution_generation=generation,
        lease_seconds=30,
    )
    assert stale.stage == "paused"
    assert stale.progress == 61
    assert stale.current_item == "epoch-6"

    resumed = repository.set_stage(lease.task.task_id, "training")
    assert resumed.stage == "training"
    current = repository.heartbeat(
        lease.task.task_id,
        lease.lease_token,
        progress=62,
        stage="training",
        execution_generation=generation,
        lease_seconds=30,
    )
    assert current.stage == "training"

    cancelling = repository.request_cancel(lease.task.task_id)
    assert cancelling.stage == "cancelling"
    stale_after_cancel = repository.heartbeat(
        lease.task.task_id,
        lease.lease_token,
        progress=63,
        stage="training",
        execution_generation=generation,
        lease_seconds=30,
    )
    assert stale_after_cancel.status.value == "CANCEL_REQUESTED"
    assert stale_after_cancel.stage == "cancelling"
    assert stale_after_cancel.progress == 63
