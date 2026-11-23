from __future__ import annotations

import socket
import sys
import threading
import time

import pytest
import uvicorn
from fastapi import FastAPI

from platform_core.agent_execution import AgentExecutionService, agent_executor_router
from platform_core.node_agent_executor_loop import NodeAgentExecutorLoop
from platform_core.node_agent_executor_runtime import NodeExecutorClient
from platform_core.service_nodes import ServiceNodeRepository
from platform_core.task_runtime import ArtifactStore, TaskKind, TaskRecord, TaskRepository
from platform_core.task_runtime.process_control import ProcessController, launch_process


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def payload_resolver(task, payload, assignment):
    return {"schema_version": 1, "task_kind": task.kind.value,
            "transport": "test-safe-v1", "epochs": 1,
            "selected_device": str((assignment.get("resolved_execution_config") or {}).get("selected_device") or "")}


def test_central_http_to_agent_loop_runs_two_real_cpu_slots(tmp_path):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    artifacts = ArtifactStore(tmp_path / "artifacts")
    app = FastAPI()
    app.include_router(agent_executor_router(
        lambda: repository, lambda: artifacts, execution_payload_resolver=payload_resolver,
    ))
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    assert server.started

    nodes = ServiceNodeRepository(repository)
    _node, token = nodes.create({
        "node_id": "dual-http", "display_name": "dual-http",
        "connection_mode": "agent", "allowed_capabilities": ["training", "execution-slots:2"],
    })
    nodes.heartbeat("dual-http", token, {
        "hostname": "dual-http",
        "reported_capabilities": ["training", "execution-slots:2"],
        "resources": {
            "cpu": {"logical_cores": 4}, "memory": {"available_bytes": 16 * 1024**3},
            "disk": {"free_bytes": 10 * 1024**3},
            "gpu": {"gpus": [
                {"id": "cuda:0", "index": 0, "uuid": "GPU-A", "memory_free_bytes": 8 * 1024**3,
                 "memory_total_bytes": 8 * 1024**3},
                {"id": "cuda:1", "index": 1, "uuid": "GPU-B", "memory_free_bytes": 8 * 1024**3,
                 "memory_total_bytes": 8 * 1024**3},
            ]},
        },
    })
    for task_id in ("a", "b", "c"):
        artifacts.atomic_write_json(task_id, "request.json", {
            "epochs": 1, "remote_execution": {
                "version": 1, "task_kind": TaskKind.TRAINING.value,
                "transport": "object-storage-v1"}})
        repository.create(TaskRecord.new(
            task_id=task_id, project_id="project-dual", kind=TaskKind.TRAINING,
            payload_ref="request.json", resource_key=f"training:{task_id}",
        ), artifacts=artifacts)
    service = AgentExecutionService(repository, artifacts)
    assert service.allocator.assign_next() is not None
    assert service.allocator.assign_next() is not None
    assert service.allocator.assign_next() is None

    started, pids, closed = {}, {}, {}
    controller = ProcessController()

    class CpuRunner:
        def __init__(self, on_started, client):
            self.ready = True
            self._on_started = on_started
            self._stop = threading.Event()
            self._client = client

        def request_shutdown(self):
            self._stop.set()

        def run(self, lease):
            handle = launch_process([sys.executable, "-c", "import time; time.sleep(30)"])
            self._on_started(handle.identity)
            started[lease.task_id] = time.monotonic()
            pids[lease.task_id] = handle.process.pid
            while not self._stop.wait(0.02):
                pass
            controller.terminate_tree(handle.identity, timeout=3.0)
            closed[lease.task_id] = time.monotonic()
            try:
                self._client.finish(lease, "CANCELLED")
            except Exception:
                pass
            return type("Outcome", (), {"status": "CANCELLED", "error": ""})()

    client = NodeExecutorClient(f"http://127.0.0.1:{port}", "dual-http", token)
    loop = NodeAgentExecutorLoop(
        client, CpuRunner(lambda _identity: None, client), capabilities=["training"],
        max_slots=2, slot_runner_factory=lambda kind, on_started: CpuRunner(on_started, client),
        slot_controller=controller, poll_interval=0.02,
    )
    try:
        loop.start()
        deadline = time.monotonic() + 10
        while len(started) < 2 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert set(started) == {"a", "b"}
        assert abs(started["a"] - started["b"]) < 5
        assert pids["a"] != pids["b"]
        with repository._connect() as database:
            statuses = dict(database.execute(
                "SELECT task_id,status FROM tasks WHERE task_id IN ('a','b','c')").fetchall())
        assert statuses["a"] == "RUNNING" and statuses["b"] == "RUNNING"
        assert statuses["c"] == "QUEUED"
        uuids = set()
        with repository._connect() as database:
            for row in database.execute(
                "SELECT resolved_execution_config FROM task_node_assignments "
                "WHERE task_id IN ('a','b') AND state='RELEASED'"
            ):
                import json
                cfg = json.loads(row[0])
                uuids.add(cfg["selected_gpu"]["uuid"])
        assert uuids == {"GPU-A", "GPU-B"}

        # Cancel only A; B must keep running and C must take A's slot only
        # after A's process death is proven and central finish is accepted.
        assert loop.cancel_task("a") is True
        deadline = time.monotonic() + 10
        while "a" not in closed and time.monotonic() < deadline:
            time.sleep(0.02)
        assert "a" in closed
        assert pids["b"] and repository.get("b").status.value == "RUNNING"
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            loop._reap_dual_slots()
            if repository.get("a").status.value == "CANCELLED":
                break
            time.sleep(0.02)
        assert repository.get("a").status.value == "CANCELLED"
        assert service.allocator.assign_next() is not None
        deadline = time.monotonic() + 10
        while "c" not in started and time.monotonic() < deadline:
            time.sleep(0.02)
        assert "c" in started
        assert repository.get("c").status.value == "RUNNING"
        assert repository.get("b").status.value == "RUNNING"
    finally:
        loop.stop(timeout=10)
        loop._slots.wait(10)
        server.should_exit = True
        thread.join(timeout=10)
    assert {"a", "b"} <= set(closed)
