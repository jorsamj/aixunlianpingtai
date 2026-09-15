from __future__ import annotations

import os
from datetime import datetime, timedelta

import platform_core.task_runtime.worker_instances as worker_instances_module
from platform_core.task_runtime import TaskRepository, WorkerInstanceService


def test_registered_worker_runtime_is_durable_and_online(tmp_path):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    service = WorkerInstanceService(repository)

    lease = service.acquire(
        tmp_path / "data",
        {"training", "convert"},
        "default",
        "worker-runtime-a",
        pid=os.getpid(),
        lease_seconds=30,
        node_id="node-worker-a",
        hostname="worker-a.example",
        build_id="build-actual-a",
        task_kinds={"TRAINING", "CONVERSION"},
        capabilities={"training", "cuda", "cuda"},
    )

    rows = service.list_runtime()

    assert len(rows) == 1
    assert rows[0] == {
        "worker_id": "worker-runtime-a",
        "node_id": "node-worker-a",
        "hostname": "worker-a.example",
        "pid": os.getpid(),
        "build_id": "build-actual-a",
        "roles": ["convert", "training"],
        "task_kinds": ["CONVERSION", "TRAINING"],
        "capabilities": ["cuda", "training"],
        "started_at": rows[0]["started_at"],
        "heartbeat_at": rows[0]["heartbeat_at"],
        "expires_at": lease.expires_at,
        "online": True,
    }
    assert rows[0]["started_at"] == rows[0]["heartbeat_at"]


def test_expired_worker_runtime_is_offline_without_pid_liveness(tmp_path, monkeypatch):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    service = WorkerInstanceService(repository)
    lease = service.acquire(
        tmp_path / "data",
        {"training"},
        "default",
        "worker-runtime-expired",
        pid=os.getpid(),
        lease_seconds=3,
        node_id="node-worker-expired",
        hostname="worker-expired.example",
        build_id="build-expired",
        task_kinds={"TRAINING"},
        capabilities={"training"},
    )

    def fail_if_pid_is_checked(_pid):
        raise AssertionError("runtime online state must not inspect worker PID")

    monkeypatch.setattr(worker_instances_module, "_pid_is_definitely_dead", fail_if_pid_is_checked)
    after_expiry = datetime.fromisoformat(lease.expires_at) + timedelta(microseconds=1)

    rows = service.list_runtime(now=after_expiry)

    assert len(rows) == 1
    assert rows[0]["worker_id"] == "worker-runtime-expired"
    assert rows[0]["expires_at"] == lease.expires_at
    assert rows[0]["online"] is False
