from __future__ import annotations

import os
import uuid

from app import DATA_DIR, shared_task_repository
from platform_core.task_runtime import WorkerInstanceService


def test_worker_runtime_api_returns_sanitized_durable_truth(client):
    service = WorkerInstanceService(shared_task_repository())
    worker_id = f"api-worker-{uuid.uuid4().hex}"
    lease = service.acquire(
        DATA_DIR,
        {"training"},
        f"api-test-{uuid.uuid4().hex}",
        worker_id,
        pid=os.getpid(),
        lease_seconds=30,
        node_id="api-node-actual",
        hostname="api-worker.example",
        build_id="api-build-actual",
        task_kinds={"TRAINING"},
        capabilities={"training", "cuda"},
    )
    try:
        response = client.get("/api/v62/workers")
        response.raise_for_status()
        row = next(item for item in response.json()["items"] if item["worker_id"] == worker_id)

        assert row["hostname"] == "api-worker.example"
        assert row["node_id"] == "api-node-actual"
        assert row["pid"] == os.getpid()
        assert row["build_id"] == "api-build-actual"
        assert row["roles"] == ["training"]
        assert row["task_kinds"] == ["TRAINING"]
        assert row["capabilities"] == ["cuda", "training"]
        assert row["online"] is True
        assert row["heartbeat_at"] == row["started_at"]
        assert row["expires_at"] == lease.expires_at
        assert "owner_token" not in row
        assert "instance_key" not in row
    finally:
        lease.release()
