from platform_core.training_job_projection import (
    apply_training_display_progress,
    apply_training_task_truth,
    build_training_display_progress,
)


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



def test_training_display_progress_combines_durable_lifecycle_with_worker_telemetry():
    job = {
        "status": "running",
        "progress_percent": 42.5,
        "current_epoch": 5,
        "total_epochs": 10,
        "current_batch": 4,
        "total_batches": 8,
        "elapsed_seconds": 60,
        "eta_seconds": 61,
        "current_item": "Epoch 5/10 · Batch 4/8",
        "updated_at": "2026-09-28 12:00:02",
        "training_progress": {
            "epoch": 5,
            "total_epochs": 10,
            "elapsed_seconds": 60,
            "eta_seconds": 61,
            "images_per_second": 10.25,
        },
    }
    runtime = {
        "status": "RUNNING",
        "persisted_status": "RUNNING",
        "phase": "training",
        "progress_percent": 42.0,
        "current_item": "Epoch 5/10 · Batch 3/8",
        "updated_at": "2026-09-28T04:00:01+00:00",
    }

    display = build_training_display_progress(job, runtime, revision=123)

    assert display["revision"] == 123
    assert display["status"] == "RUNNING"
    assert display["phase"] == "training"
    assert display["phase_progress"] == 45.0
    assert display["overall_progress"] == 42.5
    assert display["current_epoch"] == 5
    assert display["current_batch"] == 4
    assert display["elapsed_seconds"] == 60.0
    assert display["eta_seconds"] == 61.0
    assert display["throughput"] == 10.25
    assert display["message"] == "Epoch 5/10 · Batch 4/8"
    assert display["telemetry_source"] == "worker_training_telemetry"


def test_training_display_progress_reserves_100_for_terminal_durable_truth():
    job = {
        "status": "done",
        "progress_percent": 100,
        "current_epoch": 30,
        "total_epochs": 30,
    }
    active = build_training_display_progress(
        job,
        {"status": "RUNNING", "phase": "finalizing_commit", "progress_percent": 98},
        revision=1,
    )
    terminal = build_training_display_progress(
        job,
        {"status": "SUCCEEDED", "phase": "committed", "progress_percent": 100},
        revision=2,
    )

    assert active["overall_progress"] == 99.0
    assert terminal["overall_progress"] == 100.0
    assert terminal["eta_seconds"] == 0.0


def test_apply_training_display_progress_never_estimates_missing_eta():
    job = {"status": "running", "progress_percent": 25, "current_epoch": 1, "total_epochs": 10}
    runtime = {"status": "RUNNING", "phase": "training", "progress_percent": 25}

    apply_training_display_progress(job, runtime)

    assert job["eta_seconds"] is None
    assert job["elapsed_seconds"] is None
    assert job["training_display_progress"]["telemetry_source"] == "worker_training_telemetry"



def test_display_projection_uses_frozen_worker_telemetry_after_durable_overlay():
    worker = {
        "status": "running",
        "progress_percent": 48.5,
        "current_epoch": 6,
        "total_epochs": 10,
        "current_batch": 7,
        "total_batches": 10,
        "elapsed_seconds": 75,
        "eta_seconds": 80,
        "current_item": "Epoch 6/10 · Batch 7/10",
    }
    overlaid = {
        **worker,
        "progress_percent": 46.0,
        "current_item": "Epoch 6/10 · Batch 4/10",
    }
    runtime = {
        "status": "RUNNING",
        "phase": "training",
        "progress_percent": 46.0,
        "current_item": "Epoch 6/10 · Batch 4/10",
    }

    apply_training_display_progress(overlaid, runtime, telemetry_job=worker)

    assert overlaid["progress_percent"] == 48.5
    assert overlaid["current_item"] == "Epoch 6/10 · Batch 7/10"
    assert overlaid["current_batch"] == 7
    assert overlaid["elapsed_seconds"] == 75.0
    assert overlaid["eta_seconds"] == 80.0
