from platform_core.task_runtime import TaskKind, TaskRecord, TaskRepository


def test_worker_heartbeat_progress_is_monotonic_and_durable(tmp_path):
    database_path = tmp_path / "tasks.sqlite3"
    repository = TaskRepository(database_path)
    repository.create(
        TaskRecord.new(
            task_id="progress-monotonic",
            project_id="project-1",
            kind=TaskKind.TRAINING,
            payload_ref="payload.json",
            resource_key="gpu:local:0",
            priority=10,
            required_capabilities=("cuda",),
        )
    )
    lease = repository.claim_next(
        "worker-progress",
        [TaskKind.TRAINING],
        {"cuda"},
    )
    assert lease is not None

    first = repository.heartbeat(
        lease.task.task_id,
        lease.lease_token,
        progress=61,
        stage="training",
        current_item="batch-61",
    )
    assert first.progress == 61

    # A delayed/stale heartbeat from the same current lease must never make
    # durable worker truth move backwards.
    stale = repository.heartbeat(
        lease.task.task_id,
        lease.lease_token,
        progress=55,
    )
    assert stale.progress == 61

    # Reopening the repository must expose the same monotonic durable truth.
    reopened = TaskRepository(database_path)
    persisted = reopened.get(lease.task.task_id)
    assert persisted is not None
    assert persisted.progress == 61

    advanced = repository.heartbeat(
        lease.task.task_id,
        lease.lease_token,
        progress=62.5,
    )
    assert advanced.progress == 62.5
