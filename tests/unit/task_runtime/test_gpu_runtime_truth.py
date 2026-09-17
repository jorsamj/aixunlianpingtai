from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta, timezone

from platform_core.gpu_resources import GPUConfig, GPUResourceManager
from platform_core.task_runtime import TaskRepository, WorkerInstanceService


class _Artifacts:
    def read_json(self, task_id, relative_path, default=None):
        return default


def _gpu(uuid: str, physical_index: int, *, sampled_at: str, source: str = "nvml") -> dict:
    return {
        "gpu_uuid": uuid,
        "physical_index": physical_index,
        "model": "NVIDIA Test GPU",
        "total_bytes": 40 * 1024**3 if source != "torch-identity" else None,
        "free_bytes": 28 * 1024**3 if source != "torch-identity" else None,
        "utilization": 62.0 if source != "torch-identity" else None,
        "sampled_at": sampled_at,
        "telemetry_source": source,
        "telemetry_available": source != "torch-identity",
        "mig_mode": "disabled" if source != "torch-identity" else "unknown",
    }


def test_node_identity_prefers_explicit_id_and_persists_local_fallback(tmp_path, monkeypatch):
    from platform_core.node_identity import resolve_node_identity

    monkeypatch.setenv("MC_NODE_ID", "a800-prod-01")
    explicit = resolve_node_identity(state_dir=tmp_path / "ignored")
    assert explicit.node_id == "a800-prod-01"
    assert explicit.source == "environment"
    assert not (tmp_path / "ignored").exists()

    monkeypatch.delenv("MC_NODE_ID")
    first = resolve_node_identity(state_dir=tmp_path / "node-state")
    second = resolve_node_identity(state_dir=tmp_path / "node-state")
    assert first.node_id == second.node_id
    assert first.source == second.source == "persistent-local"
    assert first.node_id != first.hostname


def test_legacy_gpu_inventory_migrates_without_losing_sample(tmp_path):
    database_path = tmp_path / "tasks.sqlite3"
    with sqlite3.connect(database_path) as database:
        database.executescript(
            """
            CREATE TABLE gpu_inventory (
                uuid TEXT PRIMARY KEY, gpu_index INTEGER NOT NULL, model TEXT NOT NULL,
                total_bytes INTEGER, free_bytes INTEGER, utilization REAL,
                sampled_at TEXT NOT NULL, source TEXT NOT NULL, healthy INTEGER NOT NULL
            );
            CREATE TABLE gpu_samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT, uuid TEXT NOT NULL,
                free_bytes INTEGER, utilization REAL, sampled_at TEXT NOT NULL
            );
            INSERT INTO gpu_inventory VALUES (
                'GPU-legacy',0,'Legacy GPU',1000,750,10.0,
                '2026-09-15T00:00:00+00:00','nvml',1
            );
            INSERT INTO gpu_samples(uuid,free_bytes,utilization,sampled_at)
            VALUES ('GPU-legacy',750,10.0,'2026-09-15T00:00:00+00:00');
            """
        )

    repository = TaskRepository(database_path)
    with repository._connect() as database:
        inventory = database.execute("SELECT * FROM gpu_inventory").fetchone()
        sample = database.execute("SELECT * FROM gpu_samples").fetchone()
        columns = {row[1] for row in database.execute("PRAGMA table_info(gpu_inventory)")}

    assert {"node_id", "gpu_uuid", "physical_index", "telemetry_available", "mig_mode"} <= columns
    assert inventory["node_id"] == "legacy-unscoped"
    assert inventory["gpu_uuid"] == "GPU-legacy"
    assert inventory["telemetry_available"] == 1
    assert sample["node_id"] == "legacy-unscoped"
    assert sample["gpu_uuid"] == "GPU-legacy"


def test_worker_runtime_records_node_without_exposing_lease_secret(tmp_path):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    lease = WorkerInstanceService(repository).acquire(
        tmp_path / "shared-data",
        {"training"},
        "default",
        "worker-a",
        node_id="node-a",
        hostname="same-hostname-is-display-only",
        pid=os.getpid(),
        task_kinds={"TRAINING"},
        capabilities={"training.ultralytics"},
    )
    try:
        row = WorkerInstanceService(repository).list_runtime()[0]
        assert row["node_id"] == "node-a"
        assert row["hostname"] == "same-hostname-is-display-only"
        assert "owner_token" not in row
    finally:
        lease.release()


def test_node_scoped_gpu_refresh_and_worker_visibility(tmp_path, monkeypatch):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    sampled_at = datetime.now(timezone.utc).isoformat()
    artifacts = _Artifacts()
    manager_a = GPUResourceManager(
        repository,
        artifacts,
        node_id="node-a",
        worker_id="worker-a",
        sampler=lambda _python: [_gpu("GPU-A", 0, sampled_at=sampled_at)],
    )
    manager_b = GPUResourceManager(
        repository,
        artifacts,
        node_id="node-b",
        worker_id="worker-b",
        sampler=lambda _python: [_gpu("GPU-B", 0, sampled_at=sampled_at)],
    )

    manager_a.refresh()
    manager_b.refresh()
    truth = manager_a.runtime_truth()

    assert {(gpu["node_id"], gpu["gpu_uuid"], gpu["physical_index"]) for gpu in truth["gpus"]} == {
        ("node-a", "GPU-A", 0),
        ("node-b", "GPU-B", 0),
    }

    manager_a = GPUResourceManager(
        repository,
        artifacts,
        node_id="node-a",
        worker_id="worker-a",
        sampler=lambda _python: [],
    )
    manager_a.refresh()
    after_empty_refresh = manager_a.runtime_truth()
    assert any(gpu["node_id"] == "node-b" and gpu["gpu_uuid"] == "GPU-B" for gpu in after_empty_refresh["gpus"])

    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "GPU-B,GPU-A")
    reordered = GPUResourceManager(
        repository,
        artifacts,
        node_id="node-a",
        worker_id="worker-reordered",
        sampler=lambda _python: [
            _gpu("GPU-A", 0, sampled_at=sampled_at),
            _gpu("GPU-B", 1, sampled_at=sampled_at),
        ],
    )
    reordered.refresh()
    visibility = {
        row["gpu_uuid"]: row["logical_cuda_index"]
        for row in reordered.runtime_truth()["worker_gpu_visibility"]
        if row["worker_id"] == "worker-reordered"
    }
    assert visibility == {"GPU-B": 0, "GPU-A": 1}


def test_stale_and_identity_only_gpu_truth_never_fabricates_telemetry(tmp_path):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    old = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    manager = GPUResourceManager(
        repository,
        _Artifacts(),
        node_id="node-a",
        worker_id="worker-a",
        config=GPUConfig(sample_max_age_seconds=15),
        sampler=lambda _python: [_gpu("GPU-TORCH", 0, sampled_at=old, source="torch-identity")],
    )
    manager.refresh()
    gpu = manager.runtime_truth()["gpus"][0]

    assert gpu["telemetry_available"] is False
    assert gpu["metrics_fresh"] is False
    assert gpu["total_bytes"] is None
    assert gpu["free_bytes"] is None
    assert gpu["used_bytes"] is None
    assert gpu["utilization"] is None
    assert gpu["health_status"] == "unknown"


def test_no_gpu_refresh_returns_empty_inventory_without_synthetic_device(tmp_path):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    manager = GPUResourceManager(
        repository,
        _Artifacts(),
        node_id="windows-node",
        worker_id="windows-worker",
        sampler=lambda _python: [],
    )
    manager.refresh()
    assert manager.runtime_truth()["gpus"] == []
