from __future__ import annotations

import os
from pathlib import Path

import pytest

from platform_core.storage.cache import MaterialCache, resolve_material_cache_location
from platform_core.storage.material_cache_runtime import (
    MaterialCacheRuntimeReporter,
    load_node_cache_reports,
)
from platform_core.task_runtime import TaskRepository, WorkerInstanceService


def test_material_cache_location_can_be_split_from_shared_data_dir(tmp_path, monkeypatch):
    data_dir = tmp_path / "shared-data"
    monkeypatch.delenv("MC_MATERIAL_CACHE_DIR", raising=False)

    fallback = resolve_material_cache_location(data_dir)

    assert fallback.root == (data_dir / "cache" / "materials").resolve()
    assert fallback.cache_scope == "data_dir_cache"
    assert fallback.cache_root_source == "data_dir"

    configured = tmp_path / "node-local-cache"
    monkeypatch.setenv("MC_MATERIAL_CACHE_DIR", str(configured))

    split = resolve_material_cache_location(data_dir)

    assert split.root == configured.resolve()
    assert split.cache_scope == "configured_cache_dir"
    assert split.cache_root_source == "MC_MATERIAL_CACHE_DIR"


def test_worker_cache_report_is_fenced_and_visible_through_existing_worker_runtime(tmp_path, monkeypatch):
    data_dir = tmp_path / "shared-data"
    cache_dir = tmp_path / "node-cache"
    monkeypatch.setenv("MC_MATERIAL_CACHE_DIR", str(cache_dir))
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    service = WorkerInstanceService(repository)
    lease = service.acquire(
        data_dir,
        {"training"},
        "default",
        "worker-cache-a",
        pid=os.getpid(),
        lease_seconds=30,
        node_id="node-cache-a",
        hostname="cache-a.example",
        task_kinds={"TRAINING"},
        capabilities={"training.ultralytics"},
    )
    try:
        location = resolve_material_cache_location(data_dir)
        cache = MaterialCache(
            location.root,
            cache_scope=location.cache_scope,
            cache_root_source=location.cache_root_source,
            maintenance_interval_seconds=0,
        )
        cache.maintain()
        reporter = MaterialCacheRuntimeReporter(repository, lease, data_dir)

        reporter.report()

        rows = service.list_runtime()
        row = next(item for item in rows if item["worker_id"] == "worker-cache-a")
        report = row["material_cache"]
        assert report["reporter_worker_id"] == "worker-cache-a"
        assert report["cache_scope"] == "configured_cache_dir"
        assert report["cache_root_source"] == "MC_MATERIAL_CACHE_DIR"
        assert report["snapshot"]["cache_kind"] == "remote_material_content"
        assert report["snapshot"]["after_bytes"] == 0
        assert report["snapshot"]["schema_version"] == 2
        assert load_node_cache_reports(repository)["node-cache-a"]["reported_at"]
    finally:
        lease.release()


def test_multiple_workers_on_same_node_observe_one_node_cache_report(tmp_path, monkeypatch):
    data_dir = tmp_path / "shared-data"
    monkeypatch.setenv("MC_MATERIAL_CACHE_DIR", str(tmp_path / "node-cache"))
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    service = WorkerInstanceService(repository)
    first = service.acquire(
        data_dir, {"training"}, "default", "worker-training",
        pid=os.getpid(), node_id="node-shared", hostname="same-host",
        task_kinds={"TRAINING"}, capabilities={"training.ultralytics"},
    )
    second = service.acquire(
        data_dir, {"materials"}, "default", "worker-background",
        pid=os.getpid(), node_id="node-shared", hostname="same-host",
        task_kinds={"MATERIAL_BATCH"}, capabilities={"materials.batch"},
    )
    try:
        location = resolve_material_cache_location(data_dir)
        MaterialCache(
            location.root,
            cache_scope=location.cache_scope,
            cache_root_source=location.cache_root_source,
            maintenance_interval_seconds=0,
        ).maintain()
        MaterialCacheRuntimeReporter(repository, second, data_dir).report()

        rows = [item for item in service.list_runtime() if item["node_id"] == "node-shared"]
        assert len(rows) == 2
        assert {item["material_cache"]["reporter_worker_id"] for item in rows} == {"worker-background"}
        assert len(load_node_cache_reports(repository)) == 1
    finally:
        second.release()
        first.release()


def test_cache_report_cannot_publish_after_worker_lease_is_released(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    monkeypatch.setenv("MC_MATERIAL_CACHE_DIR", str(tmp_path / "cache"))
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    service = WorkerInstanceService(repository)
    lease = service.acquire(
        data_dir, {"training"}, "default", "worker-fenced",
        pid=os.getpid(), node_id="node-fenced", hostname="fenced-host",
        task_kinds={"TRAINING"}, capabilities={"training.ultralytics"},
    )
    reporter = MaterialCacheRuntimeReporter(repository, lease, data_dir)
    assert lease.release() is True

    with pytest.raises(PermissionError):
        reporter.report()


def test_worker_renew_hooks_share_existing_heartbeat_and_are_best_effort(tmp_path):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    service = WorkerInstanceService(repository)
    lease = service.acquire(
        tmp_path / "data", {"materials"}, "default", "worker-hooks",
        pid=os.getpid(), node_id="node-hooks", hostname="hooks-host",
        task_kinds={"MATERIAL_BATCH"}, capabilities={"materials.batch"},
    )
    calls: list[str] = []

    def failing_hook():
        calls.append("failed")
        raise RuntimeError("observability failure")

    lease.add_renew_hook(failing_hook)
    lease.add_renew_hook(lambda: calls.append("ok"))
    try:
        before = lease.expires_at
        lease.renew()
        assert calls == ["failed", "ok"]
        assert lease.expires_at >= before
        assert service.list_runtime()[0]["online"] is True
    finally:
        lease.release()
