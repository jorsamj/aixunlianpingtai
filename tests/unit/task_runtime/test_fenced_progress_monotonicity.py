from platform_core.task_runtime import FencedTaskRepository, TaskKind, TaskRecord


def test_fenced_worker_heartbeat_progress_is_monotonic_and_durable(tmp_path):
    database_path = tmp_path / "tasks.sqlite3"
    repository = FencedTaskRepository(database_path)
    repository.create(
        TaskRecord.new(
            task_id="fenced-progress-monotonic",
            project_id="project-1",
            kind=TaskKind.TRAINING,
            payload_ref="payload.json",
            resource_key="gpu:local:0",
            priority=10,
            required_capabilities=("cuda",),
        )
    )
    lease = repository.claim_next(
        "production-worker-progress",
        [TaskKind.TRAINING],
        {"cuda"},
    )
    assert lease is not None
    generation = lease.task.attempt

    first = repository.heartbeat(
        lease.task.task_id,
        lease.lease_token,
        progress=61,
        stage="training",
        current_item="batch-61",
        execution_generation=generation,
        lease_seconds=30,
    )
    assert first.progress == 61

    stale = repository.heartbeat(
        lease.task.task_id,
        lease.lease_token,
        progress=55,
        execution_generation=generation,
        lease_seconds=30,
    )
    assert stale.progress == 61

    reopened = FencedTaskRepository(database_path)
    persisted = reopened.get(lease.task.task_id)
    assert persisted is not None
    assert persisted.progress == 61

    advanced = repository.heartbeat(
        lease.task.task_id,
        lease.lease_token,
        progress=62.5,
        execution_generation=generation,
        lease_seconds=30,
    )
    assert advanced.progress == 62.5
