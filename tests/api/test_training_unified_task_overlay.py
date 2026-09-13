from platform_core.task_runtime import TaskKind, TaskRecord, TaskRepository


def test_training_job_overlay_uses_unified_resource_waiting_truth(tmp_path, monkeypatch):
    import app as app_module

    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    repository.create(TaskRecord.new(
        "train-wait", "project-1", TaskKind.TRAINING, "payload.json", "training:gpu:0",
        priority=7, required_capabilities=("training.ultralytics",),
    ))

    def deny(database, candidate, worker_id, token, expires_at, now):
        return False, "GPU_MEMORY_BUSY"

    assert repository.claim_next(
        "a800-worker", [TaskKind.TRAINING], {"training.ultralytics"}, admission=deny,
    ) is None
    monkeypatch.setattr(app_module, "shared_task_repository", lambda: repository)

    job = app_module.enrich_job_runtime("project-1", {
        "id": "train-wait", "status": "queued", "queue_priority": 50,
        "framework": "ultralytics",
    })

    assert job["status"] == "waiting"
    assert job["task_status"] == "WAITING_RESOURCE"
    assert job["queue_priority"] == 7
    assert job["priority_scheme"] == "lower_number_first"
    assert job["resource_queue_position"] == 1
    assert job["resource_wait_reason"] == "GPU_MEMORY_BUSY"
    assert job["task_worker_id"] is None


def test_training_job_overlay_exposes_worker_and_lease_for_running_task(tmp_path, monkeypatch):
    import app as app_module

    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    repository.create(TaskRecord.new(
        "train-run", "project-1", TaskKind.TRAINING, "payload.json", "training:gpu:0",
        priority=1, required_capabilities=("training.ultralytics",),
    ))
    lease = repository.claim_next("a800-worker-01", [TaskKind.TRAINING], {"training.ultralytics"})
    assert lease is not None
    repository.heartbeat("train-run", lease.lease_token, progress=18, stage="training", current_item="epoch 2/10")
    monkeypatch.setattr(app_module, "shared_task_repository", lambda: repository)

    job = app_module.enrich_job_runtime("project-1", {"id": "train-run", "status": "queued"})
    assert job["status"] == "running"
    assert job["progress_percent"] == 18
    assert job["current_item"] == "epoch 2/10"
    assert job["task_worker_id"] == "a800-worker-01"
    assert job["task_lease_expires_at"]
