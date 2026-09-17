from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

from app import DATA_DIR, shared_task_artifacts, shared_task_repository
from platform_core.gpu_resources import GPUResourceManager
from platform_core.task_runtime import WorkerInstanceService


def test_gpu_runtime_api_returns_node_scoped_read_only_truth(client):
    suffix = uuid.uuid4().hex
    node_id = f"api-node-{suffix}"
    worker_id = f"api-worker-{suffix}"
    gpu_uuid = f"GPU-{suffix}"
    repository = shared_task_repository()
    lease = WorkerInstanceService(repository).acquire(
        DATA_DIR,
        {"training"},
        f"gpu-runtime-{suffix}",
        worker_id,
        node_id=node_id,
        hostname="api-node.example",
        pid=os.getpid(),
        task_kinds={"TRAINING"},
        capabilities={"training.ultralytics"},
    )
    sampled_at = datetime.now(timezone.utc).isoformat()
    manager = GPUResourceManager(
        repository,
        shared_task_artifacts(),
        node_id=node_id,
        worker_id=worker_id,
        sampler=lambda _python: [
            {
                "gpu_uuid": gpu_uuid,
                "physical_index": 0,
                "model": "NVIDIA A800-SXM4-40GB",
                "total_bytes": 40 * 1024**3,
                "free_bytes": 28 * 1024**3,
                "utilization": 62,
                "sampled_at": sampled_at,
                "telemetry_source": "nvml",
                "telemetry_available": True,
                "mig_mode": "disabled",
            }
        ],
    )
    try:
        manager.refresh()
        response = client.get("/api/v62/gpu-runtime")
        response.raise_for_status()
        body = response.json()

        worker = next(row for row in body["workers"] if row["worker_id"] == worker_id)
        gpu = next(row for row in body["gpus"] if row["node_id"] == node_id and row["gpu_uuid"] == gpu_uuid)
        visibility = next(
            row for row in body["worker_gpu_visibility"]
            if row["worker_id"] == worker_id and row["gpu_uuid"] == gpu_uuid
        )

        assert worker["node_id"] == node_id
        assert gpu["physical_index"] == 0
        assert gpu["used_bytes"] == 12 * 1024**3
        assert gpu["metrics_fresh"] is True
        assert gpu["telemetry_available"] is True
        assert gpu["telemetry_source"] == "nvml"
        assert gpu["health_status"] == "unknown"
        assert visibility["node_id"] == node_id
        assert visibility["logical_cuda_index"] == 0
        assert any(node["node_id"] == node_id for node in body["nodes"])
        assert "reservations" not in body
    finally:
        lease.release()
        with repository._connect() as database:
            database.execute("DELETE FROM worker_gpu_visibility WHERE worker_id=?", (worker_id,))
            database.execute("DELETE FROM gpu_samples WHERE node_id=? AND gpu_uuid=?", (node_id, gpu_uuid))
            database.execute("DELETE FROM gpu_inventory WHERE node_id=? AND gpu_uuid=?", (node_id, gpu_uuid))
