from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

from platform_core.service_nodes import ServiceNodeError, ServiceNodeRepository
from platform_core.task_runtime import TaskRepository, WorkerInstanceService


def registry(tmp_path):
    repository = TaskRepository(tmp_path / "task_runtime" / "tasks.sqlite3")
    return repository, ServiceNodeRepository(repository, heartbeat_ttl_seconds=30)


def test_node_token_is_returned_once_and_only_hash_is_persisted(tmp_path):
    repository, nodes = registry(tmp_path)
    node, token = nodes.create({
        "node_id": "gpu-a800-01",
        "display_name": "A800 训练节点",
        "allowed_capabilities": ["training", "conversion"],
    })
    assert token
    assert node["status"] == "NEVER_CONNECTED"
    assert node["allowed_capabilities"] == ["conversion", "training"]
    assert "token_hash" not in node
    with repository._connect() as database:
        row = database.execute(
            "SELECT token_hash FROM service_nodes WHERE node_id=?",
            ("gpu-a800-01",),
        ).fetchone()
    assert row["token_hash"] != token
    assert token not in row["token_hash"]


def test_heartbeat_is_authenticated_and_projects_effective_capabilities(tmp_path):
    _repository, nodes = registry(tmp_path)
    _node, token = nodes.create({
        "node_id": "node-1",
        "display_name": "Node 1",
        "allowed_capabilities": ["training", "material-import"],
    })
    with pytest.raises(ServiceNodeError) as failure:
        nodes.heartbeat("node-1", "wrong-token", {})
    assert failure.value.code == "INVALID_NODE_TOKEN"
    assert failure.value.status_code == 401

    node = nodes.heartbeat("node-1", token, {
        "hostname": "linux-a800",
        "os_name": "Linux",
        "os_version": "Ubuntu 22.04",
        "architecture": "x86_64",
        "agent_version": "node-agent-v1",
        "build_id": "build-123",
        "reported_capabilities": ["training", "annotation"],
        "resources": {"memory": {"total_bytes": 32 * 1024**3}},
        "runtime": {"torch_version": "2.5.0+cu124", "cuda_version": "12.4"},
        "process": {"pid": 1234, "rss_bytes": 1024},
        "active_tasks": ["train_abc"],
    })
    assert node["status"] == "ONLINE"
    assert node["reachable"] is True
    assert node["effective_capabilities"] == ["training"]
    assert node["resources"]["memory"]["total_bytes"] == 32 * 1024**3
    assert node["runtime"]["cuda_version"] == "12.4"
    assert node["reported_active_tasks"] == ["train_abc"]


def test_stale_heartbeat_and_disabled_state_are_distinct(tmp_path):
    _repository, nodes = registry(tmp_path)
    _node, token = nodes.create({
        "node_id": "node-2",
        "display_name": "Node 2",
        "allowed_capabilities": ["training"],
    })
    nodes.heartbeat("node-2", token, {"reported_capabilities": ["training"]})
    future = datetime.now(timezone.utc) + timedelta(seconds=60)
    stale = nodes.get_public("node-2", now=future)
    assert stale["status"] == "OFFLINE"
    assert stale["reachable"] is False
    assert stale["effective_capabilities"] == []

    disabled = nodes.update("node-2", {"enabled": False})
    assert disabled["status"] == "DISABLED"
    assert disabled["online"] is False
    assert disabled["reachable"] is True


def test_delete_is_blocked_while_node_has_a_live_worker(tmp_path):
    repository, nodes = registry(tmp_path)
    nodes.create({"node_id": "node-live", "display_name": "Live Node"})
    lease = WorkerInstanceService(repository).acquire(
        tmp_path,
        ["training"],
        "default",
        "worker-live",
        pid=os.getpid(),
        lease_seconds=30,
        node_id="node-live",
        hostname="test-host",
        task_kinds=["TRAINING"],
        capabilities=["training.ultralytics"],
    )
    try:
        with pytest.raises(ServiceNodeError) as failure:
            nodes.delete("node-live")
        assert failure.value.code == "SERVICE_NODE_BUSY"
        assert failure.value.status_code == 409
    finally:
        lease.release()
    nodes.delete("node-live")
    with pytest.raises(ServiceNodeError) as missing:
        nodes.get_public("node-live")
    assert missing.value.status_code == 404


def test_capability_contract_rejects_unknown_values(tmp_path):
    _repository, nodes = registry(tmp_path)
    with pytest.raises(ServiceNodeError) as failure:
        nodes.create({
            "node_id": "node-bad-cap",
            "display_name": "Bad capability",
            "allowed_capabilities": ["training", "arbitrary-root-shell"],
        })
    assert failure.value.code == "UNSUPPORTED_NODE_CAPABILITY"


def test_rknn_conversion_capability_requires_both_allow_and_report(tmp_path):
    _repository, nodes = registry(tmp_path)
    _node, token = nodes.create({
        "node_id": "rknn-agent", "display_name": "RKNN Agent",
        "allowed_capabilities": ["conversion.rknn"],
    })
    node = nodes.heartbeat("rknn-agent", token, {
        "reported_capabilities": ["conversion.rknn"],
        "runtime": {"rknn_toolkit2": {
            "available": True, "version": "2.3.2",
            "supported_chips": ["rk3568", "rk3576"],
        }},
    })
    assert node["effective_capabilities"] == ["conversion.rknn"]
    assert node["runtime"]["rknn_toolkit2"]["supported_chips"] == ["rk3568", "rk3576"]
