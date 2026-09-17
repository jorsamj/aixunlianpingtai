from __future__ import annotations

from platform_core.training_job_projection import apply_training_task_truth


def test_training_job_projection_preserves_checkpoint_resume_fields():
    job = {
        "id": "train-task-1",
        "recovery_mode": "training_checkpoint_resume",
        "recovery_state": "training",
        "recovery_auto": True,
        "resume_from_epoch": 36,
        "resume_checkpoint": "/data/projects/p1/runs/train_train-task-1/weights/last.pt",
        "resume_checkpoint_sha256": "a" * 64,
        "current_epoch": 41,
        "total_epochs": 100,
    }
    public_runtime = {
        "status": "RUNNING",
        "persisted_status": "RUNNING",
        "phase": "resuming_training",
        "progress_percent": 48,
        "current_item": "断点续训 · Epoch 41/100",
        "resource_queue_position": None,
        "resource_queue_position_exact": False,
        "resource_pool_key": "gpu",
        "resource_pool_label": "GPU 训练资源",
        "resource_wait_reason": None,
        "worker_id": "gpu-worker-a",
        "lease_expires_at": "2026-09-17T00:30:00Z",
    }

    projected = apply_training_task_truth(job, public_runtime, legacy_status="running")

    assert projected is job
    assert projected["status"] == "running"
    assert projected["task_status"] == "RUNNING"
    assert projected["phase"] == "resuming_training"
    assert projected["progress_percent"] == 48
    assert projected["task_worker_id"] == "gpu-worker-a"
    assert projected["recovery_mode"] == "training_checkpoint_resume"
    assert projected["recovery_state"] == "training"
    assert projected["recovery_auto"] is True
    assert projected["resume_from_epoch"] == 36
    assert projected["resume_checkpoint"].endswith("/weights/last.pt")
    assert projected["resume_checkpoint_sha256"] == "a" * 64
    assert projected["current_epoch"] == 41
    assert projected["total_epochs"] == 100


def test_training_job_projection_preserves_finalization_replay_fields():
    job = {
        "id": "train-task-2",
        "recovery_mode": "finalization_replay",
        "recovery_state": "finalizing_commit",
        "recovery_auto": True,
        "recovery_attempted": True,
        "recovery_completed": False,
        "final_validation_reused": True,
        "current_epoch": 100,
        "total_epochs": 100,
    }
    public_runtime = {
        "status": "RUNNING",
        "persisted_status": "RUNNING",
        "phase": "finalizing_commit",
        "progress_percent": 98,
        "current_item": "最终验证已完成，正在继续归档训练结果与算法版本",
        "resource_queue_position": None,
        "resource_queue_position_exact": False,
        "resource_pool_key": "gpu",
        "resource_pool_label": "GPU 训练资源",
        "resource_wait_reason": None,
        "worker_id": "gpu-worker-b",
        "lease_expires_at": "2026-09-17T00:31:00Z",
    }

    projected = apply_training_task_truth(job, public_runtime, legacy_status="running")

    assert projected is job
    assert projected["task_status"] == "RUNNING"
    assert projected["phase"] == "finalizing_commit"
    assert projected["progress_percent"] == 98
    assert projected["task_worker_id"] == "gpu-worker-b"
    assert projected["recovery_mode"] == "finalization_replay"
    assert projected["recovery_state"] == "finalizing_commit"
    assert projected["recovery_auto"] is True
    assert projected["recovery_attempted"] is True
    assert projected["recovery_completed"] is False
    assert projected["final_validation_reused"] is True
    assert projected["current_epoch"] == 100
    assert projected["total_epochs"] == 100
