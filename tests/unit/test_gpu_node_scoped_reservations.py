from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from platform_core.gpu_resources import GPUConfig
from platform_core.gpu_reservations_v2 import (
    LEGACY_UNSCOPED_NODE,
    NodeScopedGPUResourceManager,
)
from platform_core.task_runtime import TaskRepository


GIB = 1024 ** 3


class _Artifacts:
    def __init__(self, payloads=None):
        self.payloads = payloads or {}

    def read_json(self, task_id, relative_path, default=None):
        return dict(self.payloads.get(task_id, default or {}))


def _config():
    return GPUConfig(
        max_concurrent=2,
        safety_bytes=GIB,
        max_reserved_ratio=0.9,
        sample_max_age_seconds=60,
        shared_utilization_limit=35.0,
        small_job_ratio=0.25,
    )


def _add_gpu(repository, *, node_id, worker_id, gpu_uuid, physical_index, logical_index=0):
    stamp = datetime.now(timezone.utc).isoformat()
    with closing(repository._connect()) as database:
        database.execute(
            """
            INSERT OR REPLACE INTO gpu_inventory(
                node_id,gpu_uuid,physical_index,model,total_bytes,free_bytes,
                utilization,sampled_at,telemetry_source,telemetry_available,mig_mode
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                node_id, gpu_uuid, physical_index, "Synthetic GPU", 16 * GIB,
                14 * GIB, 5.0, stamp, "nvml", 1, "disabled",
            ),
        )
        database.execute(
            """
            INSERT OR REPLACE INTO worker_gpu_visibility(
                worker_id,node_id,gpu_uuid,logical_cuda_index,observed_at
            ) VALUES (?,?,?,?,?)
            """,
            (worker_id, node_id, gpu_uuid, logical_index, stamp),
        )


def _admit(manager, repository, task_id, worker_id, *, lease_token=None):
    now = datetime.now(timezone.utc)
    task = {
        "task_id": task_id,
        "kind": "TRAINING",
        "resource_key": f"training:{task_id}",
        "payload_ref": "payload.json",
    }
    with closing(repository._connect()) as database:
        database.execute("BEGIN IMMEDIATE")
        allowed, reason = manager.admit(
            database,
            task,
            worker_id,
            lease_token or f"lease-{task_id}",
            (now + timedelta(seconds=30)).isoformat(),
            now.isoformat(),
        )
        database.commit()
    return allowed, reason


def test_legacy_reservation_migrates_only_with_proven_worker_node(tmp_path):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    now = datetime.now(timezone.utc)
    expires = (now + timedelta(minutes=5)).isoformat()
    stamp = now.isoformat()
    with closing(repository._connect()) as database:
        database.execute(
            """
            INSERT INTO worker_instances(
                instance_key,owner_token,worker_id,node_id,pid,hostname,build_id,roles,
                task_kinds,capabilities,started_at,heartbeat_at,expires_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "instance-a", "owner-a", "worker-a", "node-a", 1234, "host-a", "build",
                '["training"]', '["TRAINING"]', '["training.ultralytics"]',
                stamp, stamp, expires,
            ),
        )
        database.execute(
            """
            INSERT INTO gpu_inventory(
                node_id,gpu_uuid,physical_index,model,total_bytes,free_bytes,
                utilization,sampled_at,telemetry_source,telemetry_available,mig_mode
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            ("node-a", "GPU-LEGACY", 4, "Legacy GPU", 16 * GIB, 14 * GIB, 3.0, stamp, "nvml", 1, "disabled"),
        )
        database.execute(
            """
            INSERT INTO gpu_reservations(
                task_id,gpu_uuid,gpu_index,reserved_bytes,estimated_bytes,worker_id,
                worker_slot,lease_token,policy,share_eligible,sharing_evidence_at,
                created_at,heartbeat_at,expires_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "legacy-task", "GPU-LEGACY", 0, 2 * GIB, 2 * GIB, "worker-a",
                "default", "legacy-lease", "exclusive", 0, None, stamp, stamp, expires,
            ),
        )

    NodeScopedGPUResourceManager(
        repository,
        _Artifacts(),
        node_id="node-a",
        worker_id="worker-a",
        sampler=lambda _python: [],
        config=_config(),
    )

    with closing(repository._connect()) as database:
        row = database.execute(
            "SELECT * FROM gpu_reservations WHERE task_id='legacy-task'"
        ).fetchone()
        table_sql = database.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='gpu_reservations'"
        ).fetchone()[0]
    assert row["node_id"] == "node-a"
    assert row["gpu_uuid"] == "GPU-LEGACY"
    assert row["physical_index"] == 4
    assert row["logical_cuda_index"] == 0
    assert row["gpu_index"] == 0
    assert "UNIQUE(node_id, worker_slot)" in table_sql


def test_ambiguous_legacy_reservation_blocks_new_gpu_admission(tmp_path):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    now = datetime.now(timezone.utc)
    expires = (now + timedelta(minutes=5)).isoformat()
    stamp = now.isoformat()
    with closing(repository._connect()) as database:
        database.execute(
            """
            INSERT INTO gpu_reservations(
                task_id,gpu_uuid,gpu_index,reserved_bytes,estimated_bytes,worker_id,
                worker_slot,lease_token,policy,share_eligible,sharing_evidence_at,
                created_at,heartbeat_at,expires_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "legacy-unknown", "GPU-UNKNOWN", 0, 2 * GIB, 2 * GIB, "missing-worker",
                "default", "legacy-lease", "exclusive", 0, None, stamp, stamp, expires,
            ),
        )

    artifacts = _Artifacts({
        "task-new": {"device": "cuda:0", "gpu_policy": "exclusive", "estimated_gpu_memory_bytes": 2 * GIB},
    })
    manager = NodeScopedGPUResourceManager(
        repository,
        artifacts,
        node_id="node-a",
        worker_id="worker-a",
        sampler=lambda _python: [],
        config=_config(),
    )
    _add_gpu(repository, node_id="node-a", worker_id="worker-a", gpu_uuid="GPU-A", physical_index=2)

    allowed, reason = _admit(manager, repository, "task-new", "worker-a")
    assert allowed is False
    assert reason.startswith("GPU_LEGACY_RESERVATION_UNSCOPED")
    with closing(repository._connect()) as database:
        row = database.execute(
            "SELECT node_id FROM gpu_reservations WHERE task_id='legacy-unknown'"
        ).fetchone()
    assert row["node_id"] == LEGACY_UNSCOPED_NODE


def test_same_slot_and_gpu_uuid_are_independent_across_nodes(tmp_path):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    artifacts = _Artifacts({
        "task-a": {"device": "cuda:0", "gpu_policy": "exclusive", "estimated_gpu_memory_bytes": 2 * GIB},
        "task-b": {"device": "cuda:0", "gpu_policy": "exclusive", "estimated_gpu_memory_bytes": 2 * GIB},
        "task-c": {"device": "cuda:0", "gpu_policy": "exclusive", "estimated_gpu_memory_bytes": 2 * GIB},
    })
    manager_a = NodeScopedGPUResourceManager(
        repository, artifacts, node_id="node-a", worker_id="worker-a",
        worker_slot="default", sampler=lambda _python: [], config=_config(),
    )
    manager_b = NodeScopedGPUResourceManager(
        repository, artifacts, node_id="node-b", worker_id="worker-b",
        worker_slot="default", sampler=lambda _python: [], config=_config(),
    )
    manager_c = NodeScopedGPUResourceManager(
        repository, artifacts, node_id="node-a", worker_id="worker-c",
        worker_slot="default", sampler=lambda _python: [], config=_config(),
    )
    _add_gpu(repository, node_id="node-a", worker_id="worker-a", gpu_uuid="GPU-SAME", physical_index=3)
    _add_gpu(repository, node_id="node-b", worker_id="worker-b", gpu_uuid="GPU-SAME", physical_index=7)
    _add_gpu(repository, node_id="node-a", worker_id="worker-c", gpu_uuid="GPU-SAME", physical_index=3)

    assert _admit(manager_a, repository, "task-a", "worker-a") == (True, None)
    assert _admit(manager_b, repository, "task-b", "worker-b") == (True, None)
    allowed, reason = _admit(manager_c, repository, "task-c", "worker-c")
    assert allowed is False
    assert reason.startswith("GPU_WORKER_SLOT_BUSY")

    with closing(repository._connect()) as database:
        rows = database.execute(
            "SELECT node_id,gpu_uuid,worker_slot FROM gpu_reservations ORDER BY node_id"
        ).fetchall()
    assert [(row["node_id"], row["gpu_uuid"], row["worker_slot"]) for row in rows] == [
        ("node-a", "GPU-SAME", "default"),
        ("node-b", "GPU-SAME", "default"),
    ]


def test_assignment_binds_node_uuid_physical_and_worker_logical_index(tmp_path):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    artifacts = _Artifacts({
        "task-a": {"device": "cuda:1", "gpu_policy": "exclusive", "estimated_gpu_memory_bytes": 2 * GIB},
    })
    manager = NodeScopedGPUResourceManager(
        repository, artifacts, node_id="node-a", worker_id="worker-a",
        worker_slot="slot-a", sampler=lambda _python: [], config=_config(),
    )
    _add_gpu(
        repository,
        node_id="node-a",
        worker_id="worker-a",
        gpu_uuid="GPU-MAPPED",
        physical_index=6,
        logical_index=1,
    )

    assert _admit(manager, repository, "task-a", "worker-a", lease_token="lease-a") == (True, None)
    lease = SimpleNamespace(
        task=SimpleNamespace(task_id="task-a", payload_ref="payload.json"),
        lease_token="lease-a",
        worker_id="worker-a",
    )
    assignment = manager.assignment(lease)
    assert assignment["node_id"] == "node-a"
    assert assignment["gpu_uuid"] == "GPU-MAPPED"
    assert assignment["physical_index"] == 6
    assert assignment["logical_index"] == 1
    assert assignment["logical_cuda_index"] == 1
    assert assignment["gpu_index"] == 1
    assert assignment["assigned_device"] == "cuda:1"

    with closing(repository._connect()) as database:
        database.execute(
            "DELETE FROM worker_gpu_visibility WHERE worker_id='worker-a' AND node_id='node-a'"
        )
    with pytest.raises(EnvironmentError, match="GPU_ASSIGNMENT_FENCED"):
        manager.assignment(lease)


def test_summary_does_not_count_same_uuid_reservation_from_other_node(tmp_path):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    artifacts = _Artifacts({
        "task-b": {"device": "cuda:0", "gpu_policy": "exclusive", "estimated_gpu_memory_bytes": 2 * GIB},
    })
    manager_a = NodeScopedGPUResourceManager(
        repository, artifacts, node_id="node-a", worker_id="worker-a",
        sampler=lambda _python: [], config=_config(),
    )
    manager_b = NodeScopedGPUResourceManager(
        repository, artifacts, node_id="node-b", worker_id="worker-b",
        sampler=lambda _python: [], config=_config(),
    )
    _add_gpu(repository, node_id="node-a", worker_id="worker-a", gpu_uuid="GPU-SAME", physical_index=0)
    _add_gpu(repository, node_id="node-b", worker_id="worker-b", gpu_uuid="GPU-SAME", physical_index=0)
    assert _admit(manager_b, repository, "task-b", "worker-b") == (True, None)

    summary = manager_a.summary()
    assert summary["node_id"] == "node-a"
    assert summary["gpus"][0]["gpu_uuid"] == "GPU-SAME"
    assert summary["gpus"][0]["active_tasks"] == 0
    assert summary["gpus"][0]["reserved_bytes"] == 0
