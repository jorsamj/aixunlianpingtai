from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from platform_core.service_nodes import ServiceNodeRepository
from platform_core.task_node_assignments import (
    CentralTaskAllocator,
    _active_assignment_configs,
    _hard_admission,
    _task_resource_requirements,
)
from platform_core.task_runtime import ArtifactStore, TaskKind, TaskRecord, TaskRepository


def runtime(tmp_path):
    repository = TaskRepository(tmp_path / "task_runtime" / "tasks.sqlite3")
    artifacts = ArtifactStore(tmp_path / "task_runtime" / "artifacts")
    return repository, artifacts


def create_task(repository, artifacts, task_id, payload=None):
    artifacts.atomic_write_json(task_id, "request.json", payload or {})
    return repository.create(
        TaskRecord.new(
            task_id=task_id, project_id="project-1", kind=TaskKind.TRAINING,
            payload_ref="request.json", resource_key=f"training:{task_id}", priority=50,
        ),
        artifacts=artifacts,
    )


def node_resources(*, free0=20 * 1024**3, free1=0, uuid0="GPU-0", uuid1="GPU-1",
                   cpu=8, memory=32 * 1024**3, disk=100 * 1024**3, util0=0, util1=0):
    gpus = [{
        "id": "cuda:0", "index": 0, "uuid": uuid0, "name": "A800",
        "memory_free_bytes": free0, "memory_total_bytes": 40 * 1024**3,
        "utilization_percent": util0,
    }]
    if free1:
        gpus.append({
            "id": "cuda:1", "index": 1, "uuid": uuid1, "name": "A800",
            "memory_free_bytes": free1, "memory_total_bytes": 40 * 1024**3,
            "utilization_percent": util1,
        })
    return {
        "cpu": {"logical_cores": cpu, "usage_percent": 0},
        "memory": {"total_bytes": memory, "available_bytes": memory, "used_bytes": 0},
        "disk": {"path": "/scratch", "total_bytes": disk, "free_bytes": disk},
        "gpu": {"gpus": gpus},
    }


def online_node(repository, node_id, resources, *, connection_mode="local"):
    nodes = ServiceNodeRepository(repository)
    _, token = nodes.create({
        "node_id": node_id, "display_name": node_id, "enabled": True,
        "connection_mode": connection_mode, "allowed_capabilities": ["training"],
    })
    nodes.heartbeat(node_id, token, {
        "hostname": node_id, "build_id": f"build-{node_id}",
        "reported_capabilities": ["training"], "resources": resources,
    })


def requirement(**values):
    return {"resource_requirements": {"gpu_count": 1, **values}}


def test_free_gpu_and_hard_budget_is_admitted(tmp_path):
    repository, artifacts = runtime(tmp_path)
    create_task(repository, artifacts, "t1", requirement(
        min_gpu_memory_bytes=8 * 1024**3, cpu_cores=2,
        ram_bytes=4 * 1024**3, scratch_bytes=1 * 1024**3,
    ))
    online_node(repository, "node-a", node_resources(free0=16 * 1024**3))
    assignment = CentralTaskAllocator(repository, artifacts).assign_next()
    assert assignment is not None
    resolved = assignment["resolved_execution_config"]
    assert resolved["hard_admission"] == "verified"
    assert resolved["selected_gpu"]["uuid"] == "GPU-0"
    assert resolved["resource_requirements"]["gpu_count"] == 1


def test_vram_and_high_utilization_are_hard_rejections(tmp_path):
    repository, artifacts = runtime(tmp_path)
    create_task(repository, artifacts, "vram", requirement(
        min_gpu_memory_bytes=24 * 1024**3,
    ))
    online_node(repository, "node-vram", node_resources(free0=16 * 1024**3))
    assert CentralTaskAllocator(repository, artifacts).assign_next() is None

    repository2, artifacts2 = runtime(tmp_path / "util")
    create_task(repository2, artifacts2, "busy", requirement(min_gpu_memory_bytes=1))
    online_node(repository2, "node-busy", node_resources(free0=32 * 1024**3, util0=95))
    assert CentralTaskAllocator(repository2, artifacts2).assign_next() is None


def test_cpu_ram_and_scratch_hard_rejections(tmp_path):
    cases = [
        ("cpu", {"cpu_cores": 20}, node_resources(cpu=8), "CPU_INSUFFICIENT"),
        ("ram", {"ram_bytes": 64 * 1024**3}, node_resources(memory=8 * 1024**3), "RAM_INSUFFICIENT"),
        ("disk", {"scratch_bytes": 200 * 1024**3}, node_resources(disk=10 * 1024**3), "SCRATCH_INSUFFICIENT"),
    ]
    for name, values, resources, expected_reason in cases:
        repository, artifacts = runtime(tmp_path / name)
        create_task(repository, artifacts, name, requirement(min_gpu_memory_bytes=1, **values))
        online_node(repository, f"node-{name}", resources)
        allocator = CentralTaskAllocator(repository, artifacts)
        assert allocator.assign_next() is None, name
        with allocator.repository._connect() as database:
            node = database.execute("SELECT * FROM service_nodes LIMIT 1").fetchone()
            ok, actual_reason, _ = _hard_admission(
                database, node, "training",
                {"gpu_count": 1, "min_gpu_memory_bytes": 1, **values},
            )
        assert not ok and actual_reason == expected_reason


def test_storage_reachability_must_be_reported(tmp_path):
    repository, artifacts = runtime(tmp_path)
    create_task(repository, artifacts, "storage", requirement(
        min_gpu_memory_bytes=1, storage_source_ids=["nas-a"],
    ))
    online_node(repository, "node-storage", node_resources())
    assert CentralTaskAllocator(repository, artifacts).assign_next() is None


def test_two_gpus_are_distinct_and_requested_uuid_wins(tmp_path):
    repository, artifacts = runtime(tmp_path)
    create_task(repository, artifacts, "second", requirement(
        min_gpu_memory_bytes=1, gpu_uuids=["GPU-1"],
    ))
    online_node(repository, "node-two", node_resources(free0=16 * 1024**3, free1=16 * 1024**3))
    first = CentralTaskAllocator(repository, artifacts).assign_next()
    assert first["resolved_execution_config"]["selected_gpu"]["uuid"] == "GPU-1"

    create_task(repository, artifacts, "first", requirement(min_gpu_memory_bytes=1))
    second = CentralTaskAllocator(repository, artifacts).assign_next()
    assert second["resolved_execution_config"]["selected_gpu"]["uuid"] != "GPU-1"
    assert second["resolved_execution_config"]["selected_gpu"]["uuid"] == "GPU-0"


def test_duplicate_uuid_fails_closed(tmp_path):
    repository, artifacts = runtime(tmp_path)
    create_task(repository, artifacts, "duplicate", requirement(min_gpu_memory_bytes=1))
    online_node(repository, "node-duplicate", node_resources(
        free0=16 * 1024**3, free1=16 * 1024**3, uuid0="GPU-X", uuid1="GPU-X",
    ))
    allocator = CentralTaskAllocator(repository, artifacts)
    assert allocator.assign_next() is None
    with allocator.repository._connect() as database:
        node = database.execute("SELECT * FROM service_nodes LIMIT 1").fetchone()
        ok, reason, _ = _hard_admission(database, node, "training", {"gpu_count": 1})
    assert not ok and reason == "DUPLICATE_GPU_IDENTITY"


def test_unknown_active_resource_fails_closed_but_legacy_task_still_runs(tmp_path):
    repository, artifacts = runtime(tmp_path)
    allocator = CentralTaskAllocator(repository, artifacts)
    # An old assignment without frozen requirements blocks a new opt-in task.
    now = datetime.now(timezone.utc).isoformat()
    with repository._connect() as database:
        database.execute(
            "INSERT OR IGNORE INTO task_node_assignments "
            "(task_id,generation,node_id,capability,state,assigned_at,updated_at,resolved_execution_config) "
            "VALUES ('legacy','1','node-a','training','ASSIGNED',?,?,'{}')",
            (now, now),
        )
        database.commit()
    create_task(repository, artifacts, "opt-in", requirement(min_gpu_memory_bytes=1))
    online_node(repository, "node-a", node_resources())
    assert allocator.assign_next() is None

    # The same node can still run a legacy task without requirements.
    repository2, artifacts2 = runtime(tmp_path / "legacy")
    create_task(repository2, artifacts2, "legacy-only")
    online_node(repository2, "node-legacy", node_resources(cpu=1, memory=1024**3, disk=1024**3))
    assert CentralTaskAllocator(repository2, artifacts2).assign_next() is not None


def test_release_allows_reuse_and_expired_lease_does_not_double_assign(tmp_path):
    repository, artifacts = runtime(tmp_path)
    create_task(repository, artifacts, "one", requirement(min_gpu_memory_bytes=1))
    online_node(repository, "node-a", node_resources())
    allocator = CentralTaskAllocator(repository, artifacts)
    first = allocator.assign_next()
    assert first is not None
    create_task(repository, artifacts, "two", requirement(min_gpu_memory_bytes=1))
    assert allocator.assign_next() is None
    allocator.release("one", reason="test")
    with repository._connect() as database:
        database.execute("UPDATE tasks SET status='CANCELLED' WHERE task_id='one'")
        database.commit()
    second = allocator.assign_next()
    assert second["task_id"] == "two"

    # Expired-but-still-active reservations remain guarded.
    now = datetime.now(timezone.utc)
    with repository._connect() as database:
        database.execute(
            "UPDATE task_node_assignments SET state='ASSIGNED',lease_expires_at=? "
            "WHERE task_id=? AND state='RELEASED'",
            ((now - timedelta(hours=1)).isoformat(), "one"),
        )
        database.commit()
    create_task(repository, artifacts, "three", requirement(min_gpu_memory_bytes=1))
    assert allocator.assign_next() is None


def test_multi_gpu_and_malformed_requirements_stay_queued(tmp_path):
    repository, artifacts = runtime(tmp_path)
    create_task(repository, artifacts, "multi", {"resource_requirements": {
        "gpu_count": 2, "min_gpu_memory_bytes": 1,
    }})
    create_task(repository, artifacts, "bad", {"resource_requirements": {
        "gpu_count": 1, "unknown_field": 1,
    }})
    online_node(repository, "node-a", node_resources(free0=16 * 1024**3, free1=16 * 1024**3))
    allocator = CentralTaskAllocator(repository, artifacts)
    assert allocator.assign_next() is None
    with repository._connect() as database:
        assert database.execute(
            "SELECT COUNT(*) FROM task_node_assignments WHERE state IN ('ASSIGNED','CLAIMED')"
        ).fetchone()[0] == 0


def test_same_cuda_index_on_different_nodes_is_resolved_by_uuid(tmp_path):
    repository, artifacts = runtime(tmp_path)
    create_task(repository, artifacts, "uuid-task", requirement(
        min_gpu_memory_bytes=1, gpu_uuids=["GPU-B"],
    ))
    online_node(repository, "node-a", node_resources(uuid0="GPU-A"))
    online_node(repository, "node-b", node_resources(uuid0="GPU-B"))
    assignment = CentralTaskAllocator(repository, artifacts).assign_next()
    assert assignment["node_id"] == "node-b"
    assert assignment["resolved_execution_config"]["selected_gpu"]["uuid"] == "GPU-B"


def test_stale_heartbeat_never_admits_an_opt_in_task(tmp_path):
    repository, artifacts = runtime(tmp_path)
    create_task(repository, artifacts, "stale", requirement(min_gpu_memory_bytes=1))
    online_node(repository, "node-stale", node_resources())
    old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    with repository._connect() as database:
        database.execute("UPDATE service_nodes SET last_heartbeat_at=? WHERE node_id='node-stale'", (old,))
        database.commit()
    assert CentralTaskAllocator(repository, artifacts).assign_next() is None


def test_concurrent_allocators_do_not_share_one_gpu(tmp_path):
    repository, artifacts = runtime(tmp_path)
    create_task(repository, artifacts, "a", requirement(min_gpu_memory_bytes=1))
    create_task(repository, artifacts, "b", requirement(min_gpu_memory_bytes=1))
    online_node(repository, "node-a", node_resources())
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: CentralTaskAllocator(repository, artifacts).assign_next(), range(2)))
    assigned = [item for item in results if item is not None]
    assert len(assigned) == 1
    with repository._connect() as database:
        active = database.execute(
            "SELECT COUNT(*) FROM task_node_assignments WHERE state IN ('ASSIGNED','CLAIMED')"
        ).fetchone()[0]
    assert active == 1
