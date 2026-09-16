from platform_core.training_job_projection import apply_training_task_truth


def test_training_job_projection_keeps_legacy_aliases_but_exposes_canonical_truth():
    job = {"id": "job-1", "status": "queued", "task_stage": "queued"}
    runtime = {
        "status": "WAITING_RESOURCE",
        "persisted_status": "QUEUED",
        "phase": "resource_waiting",
        "progress_percent": 37.5,
        "current_item": "等待 GPU",
        "resource_queue_position": 2,
        "resource_queue_position_exact": False,
        "resource_pool_key": "gpu:auto",
        "resource_pool_label": "GPU 自动",
        "resource_wait_reason": "GPU_MEMORY_BUSY",
        "worker_id": None,
        "lease_expires_at": None,
    }

    apply_training_task_truth(job, runtime, legacy_status="waiting")

    assert job["status"] == "waiting"
    assert job["task_status"] == "WAITING_RESOURCE"
    assert job["persisted_status"] == "QUEUED"
    assert job["phase"] == "resource_waiting"
    assert job["task_stage"] == "resource_waiting"
    assert job["progress_percent"] == 37.5
    assert job["current_item"] == "等待 GPU"
    assert job["resource_queue_position"] == 2
    assert job["resource_queue_position_exact"] is False
    assert job["resource_pool_key"] == "gpu:auto"
    assert job["resource_pool_label"] == "GPU 自动"
    assert job["resource_wait_reason"] == "GPU_MEMORY_BUSY"


def test_training_job_projection_clamps_progress_and_never_invents_queue_exactness():
    job = {}
    runtime = {
        "status": "RUNNING",
        "persisted_status": "RUNNING",
        "phase": "training",
        "progress_percent": 180,
        "current_item": "Epoch 1/10",
        "resource_queue_position": None,
        "worker_id": "worker-a",
        "lease_expires_at": "2026-09-16T00:00:00Z",
    }
    apply_training_task_truth(job, runtime, legacy_status="running")

    assert job["progress_percent"] == 100.0
    assert job["resource_queue_position_exact"] is False
    assert job["task_worker_id"] == "worker-a"
