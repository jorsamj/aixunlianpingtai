"""Loopback TCP integration for the real Agent HTTP client and control plane.

All database, tokens, artifacts and GPU facts are synthetic and temp-local.
The only listener is 127.0.0.1 on an ephemeral OS-assigned port. No OSS,
production Agent, external network or actual training process is involved.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import socket
import threading
import time

from fastapi import FastAPI
import pytest
import requests
import uvicorn

from platform_core.agent_execution import agent_executor_router
from platform_core.node_agent_executor_runtime import (
    NodeExecutorClient,
    NodeExecutorHTTPError,
)
from platform_core.service_nodes import ServiceNodeRepository
from platform_core.task_runtime import ArtifactStore, TaskKind, TaskRecord, TaskRepository


def _remote_payload(task, payload, assignment):
    return {
        "schema_version": 1,
        "task_kind": task.kind.value,
        "transport": "test-safe-v1",
        "selected_device": (assignment.get("resolved_execution_config") or {}).get("selected_device"),
    }


def _node(nodes, name):
    _, token = nodes.create({
        "node_id": name,
        "display_name": name,
        "connection_mode": "agent",
        "allowed_capabilities": ["training"],
    })
    _heartbeat(nodes, name, token)
    return token


def _heartbeat(nodes, node_id, token):
    nodes.heartbeat(node_id, token, {
        "hostname": node_id,
        "reported_capabilities": ["training"],
        "resources": {
            "memory": {"available_bytes": 32 * 1024**3},
            "gpu": {"available": True, "gpus": [{
                "id": "cuda:0", "index": 0,
                "name": "isolated-no-real-gpu",
                "memory_total_bytes": 40 * 1024**3,
                "memory_free_bytes": 30 * 1024**3,
            }]},
        },
    })


def _task(repo, artifacts, task_id, pin):
    artifacts.atomic_write_json(task_id, "request.json", {
        "target": "remote",
        "epochs": 2,
        "scheduling": {"mode": "node", "node_id": pin, "queue_policy": "wait"},
        "remote_execution": {
            "version": 1,
            "task_kind": "TRAINING",
            "transport": "object-storage-v1",
        },
    })
    repo.create(TaskRecord.new(
        task_id=task_id,
        project_id="isolated-multinode",
        kind=TaskKind.TRAINING,
        payload_ref="request.json",
        resource_key=f"training:remote:{task_id}",
    ), artifacts=artifacts)


@contextmanager
def _loopback_server(app):
    """Serve genuine HTTP over an ephemeral loopback socket, no fixed ports."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    sock.setblocking(False)
    address = f"http://127.0.0.1:{sock.getsockname()[1]}"
    server = uvicorn.Server(uvicorn.Config(
        app, log_level="error", lifespan="off", access_log=False,
    ))
    thread = threading.Thread(
        target=server.run, kwargs={"sockets": [sock]}, daemon=True,
    )
    thread.start()
    try:
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            try:
                response = requests.get(f"{address}/openapi.json", timeout=0.5)
                if response.status_code == 200:
                    break
            except requests.RequestException:
                pass
            time.sleep(0.05)
        else:
            pytest.fail("Isolated loopback HTTP server did not become ready")
        yield address
    finally:
        server.should_exit = True
        thread.join(timeout=8)
        sock.close()
        assert not thread.is_alive(), "Isolated control-plane HTTP server must shut down"


def test_two_real_http_agent_clients_share_queue_and_obey_node_fencing(tmp_path, monkeypatch):
    """Real requests.Session HTTP -> FastAPI, with two distinct Agent clients.

    Verifies actual NodeExecutorClient parsing/fencing rather than calling
    AgentExecutionService directly. No real Agent runner or GPU is started.
    """
    monkeypatch.setenv("CHANGLIAN_AGENT_AUTO_ASSIGN_ON_CLAIM", "1")
    runtime = tmp_path / "task_runtime"
    repo = TaskRepository(runtime / "tasks.sqlite3")
    artifacts = ArtifactStore(runtime / "artifacts")
    nodes = ServiceNodeRepository(repo)
    token_a = _node(nodes, "loopback-agent-a")
    token_b = _node(nodes, "loopback-agent-b")

    app = FastAPI()
    app.include_router(agent_executor_router(
        lambda: repo, lambda: artifacts,
        execution_payload_resolver=_remote_payload,
    ))

    with _loopback_server(app) as address:
        agent_a = NodeExecutorClient(address, "loopback-agent-a", token_a)
        agent_b = NodeExecutorClient(address, "loopback-agent-b", token_b)
        _task(repo, artifacts, "loopback-task-a", "loopback-agent-a")

        first = agent_a.claim_assignment()
        assert first and first["task"]["task_id"] == "loopback-task-a"
        assert first["assignment"]["node_id"] == "loopback-agent-a"
        assert agent_b.claim_assignment() is None
        with pytest.raises(NodeExecutorHTTPError) as wrong_node:
            agent_b.start_execution(
                "loopback-task-a", first["assignment"]["assignment_lease_token"]
            )
        assert wrong_node.value.status_code in {401, 403, 404, 409}
        lease_a = agent_a.start_execution(
            "loopback-task-a", first["assignment"]["assignment_lease_token"]
        )
        assert lease_a.task_id == "loopback-task-a"
        assert lease_a.worker_id == "agent:loopback-agent-a"
        assert lease_a.transport["shared_sqlite_required"] is False
        assert lease_a.transport["shared_nfs_required"] is False

        _task(repo, artifacts, "loopback-task-b", "loopback-agent-b")
        second = agent_b.claim_assignment()
        assert second and second["task"]["task_id"] == "loopback-task-b"
        lease_b = agent_b.start_execution(
            "loopback-task-b", second["assignment"]["assignment_lease_token"]
        )
        assert lease_b.worker_id == "agent:loopback-agent-b"
        assert agent_a.claim_assignment() is None
        assert agent_b.claim_assignment() is None

        # A finished/failed Agent gives back its executor slot; B is still
        # running so a later task pinned to B must not move to A.
        finished_b = agent_b.finish(lease_b, "FAILED", error="isolated intentional stop")
        assert finished_b["task"]["status"] == "FAILED"
        with repo._connect() as database:
            database.execute(
                "UPDATE service_nodes SET last_heartbeat_at=? WHERE node_id=?",
                ((datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
                 "loopback-agent-b"),
            )
        _task(repo, artifacts, "loopback-task-b-retry", "loopback-agent-b")
        assert agent_a.claim_assignment() is None
        with pytest.raises(NodeExecutorHTTPError) as offline:
            agent_b.claim_assignment()
        assert offline.value.status_code == 409
        assert repo.get("loopback-task-b-retry").status.value == "QUEUED"

        _heartbeat(nodes, "loopback-agent-b", token_b)
        recovered = agent_b.claim_assignment()
        assert recovered and recovered["task"]["task_id"] == "loopback-task-b-retry"
        assert recovered["assignment"]["node_id"] == "loopback-agent-b"
        assert repo.get("loopback-task-a").status.value == "RUNNING"
