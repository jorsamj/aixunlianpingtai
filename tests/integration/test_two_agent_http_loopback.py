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

from fastapi import FastAPI, Request
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


def test_two_real_node_agent_processes_heartbeat_claim_and_fail_safely(tmp_path, monkeypatch):
    """Two *real* node_agent.py OS processes use HTTP and distinct state dirs.

    Negative-path runtime contract: task execution begins, the real deployment
    runner rejects deliberately missing input, reports FAILED and frees its
    executor slot. This is NOT GPU training or a successful inference test.
    """
    import os
    from pathlib import Path
    import subprocess
    import sys

    from platform_core.service_nodes import service_node_router

    monkeypatch.setenv("CHANGLIAN_AGENT_AUTO_ASSIGN_ON_CLAIM", "1")
    runtime = tmp_path / "task_runtime"
    repo = TaskRepository(runtime / "tasks.sqlite3")
    artifacts = ArtifactStore(runtime / "artifacts")
    nodes = ServiceNodeRepository(repo)
    tokens = {}
    for name in ("process-agent-a", "process-agent-b"):
        _, token = nodes.create({
            "node_id": name,
            "display_name": name,
            "connection_mode": "agent",
            "allowed_capabilities": ["deployment-test"],
        })
        tokens[name] = token
        task_id = "process-task-" + name[-1]
        artifacts.atomic_write_json(task_id, "request.json", {
            "execution_mode": "agent",
            "scheduling": {"mode": "node", "node_id": name, "queue_policy": "wait"},
            "remote_execution": {
                "version": 1, "task_kind": "DEPLOYMENT_TEST",
                "transport": "object-storage-v1",
            },
        })
        repo.create(TaskRecord.new(
            task_id=task_id,
            project_id="isolated-real-agent-processes",
            kind=TaskKind.DEPLOYMENT_TEST,
            payload_ref="request.json",
            resource_key="deployment-test:remote:" + task_id,
        ), artifacts=artifacts)

    def safe_negative_payload(task, payload, assignment):
        # Valid portable envelope, intentionally missing input: real runner
        # must never download data or invoke inference and must report FAILED.
        return {
            "schema_version": 1,
            "task_kind": "DEPLOYMENT_TEST",
            "transport": "object-storage-v1",
        }

    app = FastAPI()
    app.include_router(service_node_router(lambda: repo))
    app.include_router(agent_executor_router(
        lambda: repo,
        lambda: artifacts,
        execution_payload_resolver=safe_negative_payload,
    ))

    root = Path(__file__).resolve().parents[2]
    running = []
    handles = []
    with _loopback_server(app) as address:
        try:
            for name in tokens:
                path = tmp_path / (name + ".log")
                handle = path.open("w+", encoding="utf-8")
                handles.append(handle)
                env = os.environ.copy()
                env["MC_NODE_AGENT_TOKEN"] = tokens[name]
                env["MC_CONTROL_PLANE_URL"] = address
                env["MC_NODE_ID"] = name
                env["MC_NODE_CAPABILITIES"] = "deployment-test"
                env["PYTHONUNBUFFERED"] = "1"
                command = [
                    sys.executable, "-u", str(root / "node_agent.py"),
                    "--state-dir", str(tmp_path / (name + "-private-state")),
                    "--interval", "3",
                    "--executor-poll-interval", "0.5",
                    "--execution-heartbeat-interval", "1",
                ]
                process = subprocess.Popen(
                    command,
                    cwd=str(root),
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=handle,
                    stderr=subprocess.STDOUT,
                    close_fds=True,
                )
                running.append((name, process, path))

            deadline = time.monotonic() + 100
            observed = {}
            while time.monotonic() < deadline:
                for name, process, path in running:
                    assert process.poll() is None, (
                        "Real Agent process exited before completing task: "
                        + name + " " + path.read_text(encoding="utf-8", errors="replace")[-1600:]
                    )
                    task_id = "process-task-" + name[-1]
                    current = repo.get(task_id)
                    if current.status.value == "FAILED":
                        observed[name] = current
                if len(observed) == 2:
                    break
                time.sleep(0.2)
            assert len(observed) == 2, {
                name: {
                    "status": repo.get("process-task-" + name[-1]).status.value,
                    "log_tail": path.read_text(encoding="utf-8", errors="replace")[-1800:],
                }
                for name, _, path in running
            }

            for name, process, path in running:
                task = observed[name]
                assert task.status.value == "FAILED"
                # The canonical terminal transition intentionally clears
                # tasks.worker_id/lease_token; inspect durable assignment history
                # to prove which Agent actually started this generation.
                assert task.worker_id is None
                with repo._connect() as database:
                    history = database.execute(
                        """SELECT node_id, state, release_reason
                           FROM task_node_assignments
                          WHERE task_id=? ORDER BY generation DESC LIMIT 1""",
                        ("process-task-" + name[-1],),
                    ).fetchone()
                assert history is not None
                assert history["node_id"] == name
                assert history["state"] == "RELEASED"
                assert history["release_reason"] == "execution_started"
                assert task.attempt == 1, "Each task must execute exactly once"
                assert "portable deployment input contract is missing" in (task.error or "")
                node = nodes.get_public(name)
                assert node["reported_capabilities"] == ["deployment-test"]
                assert node["status"] == "ONLINE"
                assert process.poll() is None
                log = path.read_text(encoding="utf-8", errors="replace")
                assert '"ok": true' in log.lower(), log[-1800:]
        finally:
            for _, process, _ in running:
                if process.poll() is None:
                    process.terminate()
            for _, process, _ in running:
                try:
                    process.wait(timeout=12)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            for handle in handles:
                handle.close()


def test_real_http_agent_deployment_success_upload_confirm_and_durable_result(tmp_path, monkeypatch):
    """Genuine HTTP control plane + actual isolated child process + fake object store.

    Uses the production NodeExecutorClient, AgentDeploymentRunner and
    NodeAgentExecutorLoop, with a synthetic inference entrypoint confined to
    tmp_path. This proves the full result publication protocol, NOT actual
    YOLO inference, GPU readiness or an external OSS account.
    """
    import hashlib
    from pathlib import Path
    import sys

    from fastapi import HTTPException, Response
    from platform_core.node_agent_deployment_runtime import AgentDeploymentRunner
    from platform_core.node_agent_executor_loop import NodeAgentExecutorLoop
    from platform_core.node_agent_executor_runtime import AgentExecutionWorkdir
    from platform_core.task_runtime import TaskStatus

    monkeypatch.setenv("CHANGLIAN_AGENT_AUTO_ASSIGN_ON_CLAIM", "1")
    repository = TaskRepository(tmp_path / "task_runtime" / "tasks.sqlite3")
    artifacts = ArtifactStore(tmp_path / "task_runtime" / "artifacts")
    nodes = ServiceNodeRepository(repository)
    input_bytes = b"isolated-small-image-fixture"
    output_bytes = b"isolated-rendered-result"
    payloads = {}
    uploads = {}
    base = {"url": ""}
    source_reads = []
    signed_prepares = []
    upload_confirms = []

    def sha(value):
        return hashlib.sha256(value).hexdigest()

    for name in ("positive-agent-a", "positive-agent-b"):
        _, token = nodes.create({
            "node_id": name,
            "display_name": name,
            "connection_mode": "agent",
            "allowed_capabilities": ["deployment-test"],
        })
        nodes.heartbeat(name, token, {
            "reported_capabilities": ["deployment-test"],
            "resources": {
                "cpu": {"logical_cores": 4},
                "memory": {"available_bytes": 16 * 1024**3},
                "disk": {"free_bytes": 50 * 1024**3},
                "gpu": {"available": False, "gpus": []},
            },
        })
        payloads[name] = token
        key = "positive-task-" + name[-1]
        artifacts.atomic_write_json(key, "request.json", {
            "execution_mode": "agent",
            "scheduling": {"mode": "node", "node_id": name},
            "remote_execution": {
                "version": 1, "task_kind": "DEPLOYMENT_TEST",
                "transport": "object-storage-v1",
            },
        })
        repository.create(TaskRecord.new(
            task_id=key,
            project_id="isolated-positive-result",
            kind=TaskKind.DEPLOYMENT_TEST,
            payload_ref="request.json",
            resource_key="deployment-test:remote:" + key,
        ), artifacts=artifacts)

    def portable_payload(task, _payload, assignment):
        return {
            "schema_version": 1,
            "task_kind": "DEPLOYMENT_TEST",
            "transport": "object-storage-v1",
            "framework": "ultralytics",
            "runtime_format": "pt",
            "confidence": 0.25,
            "input": {
                "type": "object",
                "download": {
                    "method": "GET",
                    "url": base["url"] + "/isolated-objects/input/" + task.task_id,
                    "headers": {},
                    "size_bytes": len(input_bytes),
                    "sha256": sha(input_bytes),
                    "file_name": "input.jpg",
                },
            },
            # The temporary child runner below only records this model name.
            "model": {"type": "official", "reference": "yolo11n.pt"},
            "output": {
                "type": "object",
                "storage_ref": {
                    "storage_source_id": "isolated-object-store",
                    "object_key": task.task_id + "/result.jpg",
                    "file_name": "result.jpg",
                    "content_type": "image/jpeg",
                },
                "upload_protocol": "prepare-after-local-hash-v1",
            },
            "selected_device": "cpu",
        }

    def prepare_upload(task, _payload, evidence):
        key = (task.task_id, int(evidence["execution_generation"]))
        signed_prepares.append(key)
        return {
            "already_uploaded": key in uploads,
            "sha256": evidence["sha256"],
            "size_bytes": evidence["size_bytes"],
            "storage_ref": {
                "storage_source_id": "isolated-object-store",
                "object_key": task.task_id + "/result.jpg",
                "file_name": "result.jpg",
                "content_type": "image/jpeg",
            },
            "upload": None if key in uploads else {
                "method": "PUT",
                "url": base["url"] + f"/isolated-objects/output/{task.task_id}/{key[1]}",
                "headers": {
                    "Content-Length": str(evidence["size_bytes"]),
                    "x-amz-meta-sha256": evidence["sha256"],
                    "If-None-Match": "*",
                },
                "overwrite_protected": True,
            },
        }

    def confirm_upload(task, _payload, evidence):
        key = (task.task_id, int(evidence["execution_generation"]))
        content = uploads.get(key)
        if (
            content is None
            or len(content) != evidence["size_bytes"]
            or sha(content) != evidence["sha256"]
        ):
            raise ValueError("isolated uploaded object evidence mismatch")
        upload_confirms.append(key)
        return {"result": {
            "output_storage": {
                "storage_source_id": "isolated-object-store",
                "object_key": task.task_id + "/result.jpg",
                "file_name": "result.jpg",
                "content_type": "image/jpeg",
            },
        }}

    app = FastAPI()
    app.include_router(agent_executor_router(
        lambda: repository, lambda: artifacts,
        execution_payload_resolver=portable_payload,
        result_upload_preparer=prepare_upload,
        result_upload_confirmer=confirm_upload,
    ))

    @app.get("/isolated-objects/input/{task_id}")
    def download_input(task_id: str):
        source_reads.append(task_id)
        return Response(
            input_bytes, media_type="image/jpeg",
            headers={"Content-Length": str(len(input_bytes))},
        )

    @app.put("/isolated-objects/output/{task_id}/{generation}")
    async def upload_result(task_id: str, generation: int, request: Request):
        content = await request.body()
        if (
            request.headers.get("if-none-match") != "*"
            or request.headers.get("x-amz-meta-sha256") != sha(content)
            or request.headers.get("content-length") != str(len(content))
            or (task_id, generation) in uploads
        ):
            raise HTTPException(409, "isolated upload evidence or overwrite guard failed")
        uploads[(task_id, generation)] = content
        return {"ok": True}

    with _loopback_server(app) as address:
        base["url"] = address
        for name, token in payloads.items():
            runtime_root = tmp_path / ("sandbox-runtime-" + name)
            runtime_root.mkdir()
            (runtime_root / "predict_ultralytics_runner.py").write_text(
                """
import argparse
import json
from pathlib import Path
parser = argparse.ArgumentParser()
parser.add_argument("--model", required=True)
parser.add_argument("--input", required=True)
parser.add_argument("--output", required=True)
parser.add_argument("--conf")
parser.add_argument("--device", default="")
options = parser.parse_args()
assert Path(options.input).read_bytes() == b"isolated-small-image-fixture"
assert options.device == "cpu"
Path(options.output).parent.mkdir(parents=True, exist_ok=True)
Path(options.output).write_bytes(b"isolated-rendered-result")
print(json.dumps({"ok": True, "engine": "isolated-test-runner", "model": options.model}))
""".strip() + "\n", encoding="utf-8",
            )
            client = NodeExecutorClient(address, name, token)
            runner = AgentDeploymentRunner(
                client,
                AgentExecutionWorkdir(tmp_path / ("private-workdir-" + name)),
                runtime_root=runtime_root,
                python_by_framework={"ultralytics": sys.executable},
                heartbeat_interval=1.0,
                process_poll_interval=0.05,
            )
            executor = NodeAgentExecutorLoop(
                client, runner, capabilities=["deployment-test"],
            )
            assert executor.run_once() is True
            task_id = "positive-task-" + name[-1]
            task = repository.get(task_id)
            assert task is not None
            assert task.status is TaskStatus.SUCCEEDED
            assert task.worker_id is None
            assert task.attempt == 1
            assert task.result_ref == "remote-results/1/result.json"
            result = artifacts.read_json(task_id, task.result_ref, default={})
            assert result["engine"] == "isolated-test-runner"
            assert result["output_size_bytes"] == len(output_bytes)
            assert result["output_sha256"] == sha(output_bytes)
            assert result["execution_generation"] == 1
            evidence = artifacts.read_json(
                task_id, "remote-results/1/upload.json", default={},
            )
            assert evidence["confirmed"] is True
            assert evidence["node_id"] == name
            assert uploads[(task_id, 1)] == output_bytes
            assert executor.status().completed_tasks == 1
            assert executor.status().last_outcome == "SUCCEEDED"
            assert client.claim_assignment() is None

    assert sorted(source_reads) == ["positive-task-a", "positive-task-b"]
    assert sorted(signed_prepares) == [
        ("positive-task-a", 1), ("positive-task-b", 1),
    ]
    assert sorted(upload_confirms) == sorted(signed_prepares)


def test_sigkilled_real_agent_releases_expired_execution_and_fences_old_generation(
    tmp_path, monkeypatch,
):
    """Kill a real Node Agent while its source GET is blocked, then recover.

    Simulate expiry deterministically after the *actual process is dead*.
    A second real Agent executes generation 2; the stale generation cannot
    heartbeat or finish. No GPU, model invocation or external storage occurs.
    This does NOT model a live Agent cut off by a network partition.
    """
    import os
    from pathlib import Path
    import subprocess
    import sys

    from fastapi import Response
    from platform_core.service_nodes import service_node_router
    from platform_core.task_runtime.fenced_repository import FencedTaskRepository

    monkeypatch.setenv("CHANGLIAN_AGENT_AUTO_ASSIGN_ON_CLAIM", "1")
    repo = TaskRepository(tmp_path / "task_runtime" / "tasks.sqlite3")
    artifacts = ArtifactStore(tmp_path / "task_runtime" / "artifacts")
    nodes = ServiceNodeRepository(repo)
    tokens = {}
    for name in ("crash-agent-a", "crash-agent-b"):
        _, tokens[name] = nodes.create({
            "node_id": name,
            "display_name": name,
            "connection_mode": "agent",
            "allowed_capabilities": ["deployment-test"],
        })
    task_id = "isolated-crash-task"
    artifacts.atomic_write_json(task_id, "request.json", {
        "execution_mode": "agent",
        "remote_execution": {
            "version": 1, "task_kind": "DEPLOYMENT_TEST",
            "transport": "object-storage-v1",
        },
    })
    repo.create(TaskRecord.new(
        task_id=task_id, project_id="isolated-crash-recovery",
        kind=TaskKind.DEPLOYMENT_TEST, payload_ref="request.json",
        resource_key="deployment-test:isolated-crash",
    ), artifacts=artifacts)

    entered_download = threading.Event()
    release_download = threading.Event()
    base = {"url": ""}

    def portable_payload(task, _payload, assignment):
        node_id = str(assignment["node_id"])
        if node_id != "crash-agent-a":
            # Second Agent proves retry can complete safely without touching
            # any external inputs or launching a model subprocess.
            return {
                "schema_version": 1, "task_kind": "DEPLOYMENT_TEST",
                "transport": "object-storage-v1",
            }
        payload = {
            "schema_version": 1, "task_kind": "DEPLOYMENT_TEST",
            "transport": "object-storage-v1",
            "framework": "ultralytics", "runtime_format": "pt",
            "input": {
                "type": "object",
                "download": {
                    "method": "GET",
                    "url": base["url"] + "/isolated-crash/slow-input",
                    "headers": {},
                    "file_name": "input.jpg",
                    "size_bytes": 8,
                    "sha256": "0" * 64,
                },
            },
        }
        return payload

    app = FastAPI()
    app.include_router(service_node_router(lambda: repo))
    app.include_router(agent_executor_router(
        lambda: repo, lambda: artifacts,
        execution_payload_resolver=portable_payload,
    ))

    @app.get("/isolated-crash/slow-input")
    def blocked_download():
        entered_download.set()
        release_download.wait(timeout=25)
        return Response(b"aborted!", media_type="image/jpeg")

    processes = []
    handles = []
    root = Path(__file__).resolve().parents[2]

    def start_agent(name, address):
        handle = (tmp_path / (name + ".log")).open("w+", encoding="utf-8")
        handles.append(handle)
        environment = os.environ.copy()
        environment.update({
            "MC_NODE_AGENT_TOKEN": tokens[name],
            "MC_CONTROL_PLANE_URL": address,
            "MC_NODE_ID": name,
            "MC_NODE_CAPABILITIES": "deployment-test",
            "PYTHONUNBUFFERED": "1",
        })
        process = subprocess.Popen(
            [
                sys.executable, "-u", str(root / "node_agent.py"),
                "--state-dir", str(tmp_path / ("state-" + name)),
                "--interval", "3", "--executor-poll-interval", "0.5",
                "--execution-heartbeat-interval", "1",
            ],
            env=environment, cwd=str(root), stdin=subprocess.DEVNULL,
            stdout=handle, stderr=subprocess.STDOUT, close_fds=True,
        )
        processes.append((name, process))
        return process

    with _loopback_server(app) as address:
        base["url"] = address
        try:
            first_agent = start_agent("crash-agent-a", address)
            assert entered_download.wait(timeout=35), (
                "first real Agent never reached the blocked remote source"
            )
            assert repo.get(task_id).status.value == "RUNNING"
            with repo._connect() as db:
                old = db.execute(
                    "SELECT attempt,lease_token,worker_id FROM tasks WHERE task_id=?",
                    (task_id,),
                ).fetchone()
            assert old["attempt"] == 1
            assert old["worker_id"] == "agent:crash-agent-a"
            assert old["lease_token"]

            # Force an actual OS-level crash, not a graceful stop handler.
            first_agent.kill()
            first_agent.wait(timeout=12)
            assert first_agent.returncode != 0
            release_download.set()

            # Fast-forward only isolated timestamps; no production clock,
            # external service or actual lease interval is changed.
            expired = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
            stale_heartbeat = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
            with repo._connect() as db:
                db.execute(
                    "UPDATE tasks SET lease_expires_at=? WHERE task_id=?",
                    (expired, task_id),
                )
                db.execute(
                    "UPDATE service_nodes SET last_heartbeat_at=? WHERE node_id=?",
                    (stale_heartbeat, "crash-agent-a"),
                )
            assert FencedTaskRepository(repo.path).release_expired() == 1
            assert repo.get(task_id).status.value == "QUEUED"

            second_agent = start_agent("crash-agent-b", address)
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                assert second_agent.poll() is None, "recovery Agent exited unexpectedly"
                if repo.get(task_id).status.value == "FAILED":
                    break
                time.sleep(0.15)
            recovered = repo.get(task_id)
            assert recovered.status.value == "FAILED"
            assert recovered.attempt == 2
            with repo._connect() as db:
                ownership = db.execute(
                    """SELECT node_id FROM task_node_assignments
                       WHERE task_id=? AND release_reason='execution_started'
                       ORDER BY generation""", (task_id,),
                ).fetchall()
            assert [row["node_id"] for row in ownership] == [
                "crash-agent-a", "crash-agent-b",
            ]
            assert recovered.worker_id is None
            assert "portable deployment input contract is missing" in (recovered.error or "")

            # Node A cannot revive a previous generation even after its
            # heartbeat reconnects: the task token and generation were fenced.
            stale = requests.post(
                f"{address}/api/v63/node-executor/crash-agent-a/"
                f"executions/{task_id}/heartbeat",
                headers={"Authorization": f"Bearer {tokens['crash-agent-a']}"},
                json={
                    "execution_lease_token": old["lease_token"],
                    "execution_generation": old["attempt"], "progress": 99,
                },
                timeout=5,
            )
            assert stale.status_code == 409, stale.text
            assert stale.json()["detail"]["code"] == "EXECUTION_FENCED"
            stale_finish = requests.post(
                f"{address}/api/v63/node-executor/crash-agent-a/"
                f"executions/{task_id}/finish",
                headers={"Authorization": f"Bearer {tokens['crash-agent-a']}"},
                json={
                    "execution_lease_token": old["lease_token"],
                    "execution_generation": old["attempt"],
                    "status": "SUCCEEDED",
                },
                timeout=5,
            )
            assert stale_finish.status_code == 409, stale_finish.text
            assert stale_finish.json()["detail"]["code"] == "EXECUTION_FENCED"
            assert repo.get(task_id).attempt == 2
            assert repo.get(task_id).status.value == "FAILED"
        finally:
            release_download.set()
            for _name, process in processes:
                if process.poll() is None:
                    process.kill()
            for _name, process in processes:
                process.wait(timeout=12)
            for handle in handles:
                handle.close()


def test_loopback_heartbeat_partition_fences_monitor_and_stops_child_process(
    tmp_path, monkeypatch,
):
    """A real HTTP 503 during lease heartbeat kills an isolated child process.

    The monitor must fail closed without inventing a terminal result. Recovery
    and generation fencing are then verified via the canonical SQLite store.
    No actual inference, accelerator or external network is involved.
    """
    import subprocess
    import sys

    from fastapi.responses import JSONResponse
    from platform_core.node_agent_executor_runtime import (
        ExecutionLeaseMonitor, RemoteExecutionFenced,
    )
    from platform_core.task_runtime.fenced_repository import FencedTaskRepository

    monkeypatch.setenv("CHANGLIAN_AGENT_AUTO_ASSIGN_ON_CLAIM", "1")
    repo = TaskRepository(tmp_path / "task_runtime" / "tasks.sqlite3")
    artifacts = ArtifactStore(tmp_path / "task_runtime" / "artifacts")
    nodes = ServiceNodeRepository(repo)
    _, token = nodes.create({
        "node_id": "partition-agent",
        "display_name": "partition-agent",
        "connection_mode": "agent",
        "allowed_capabilities": ["training"],
    })
    _heartbeat(nodes, "partition-agent", token)
    task_id = "partition-training-task"
    _task(repo, artifacts, task_id, "partition-agent")
    lose_heartbeat = threading.Event()

    app = FastAPI()
    app.include_router(agent_executor_router(
        lambda: repo, lambda: artifacts,
        execution_payload_resolver=_remote_payload,
    ))

    @app.middleware("http")
    async def drop_execution_heartbeat(request, call_next):
        if lose_heartbeat.is_set() and request.url.path.endswith(
            f"/executions/{task_id}/heartbeat"
        ):
            return JSONResponse(
                status_code=503,
                content={"detail": {
                    "code": "CONTROL_PLANE_UNREACHABLE",
                    "message": "isolated heartbeat network partition",
                }},
            )
        return await call_next(request)

    child = None
    monitor = None
    with _loopback_server(app) as address:
        client = NodeExecutorClient(address, "partition-agent", token, timeout=2.0)
        claim = client.claim_assignment()
        assert claim and claim["task"]["task_id"] == task_id
        lease = client.start_execution(
            task_id, claim["assignment"]["assignment_lease_token"],
        )
        assert lease.generation == 1
        try:
            child = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(45)"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            def stop_owned_child():
                if child.poll() is None:
                    child.terminate()

            monitor = ExecutionLeaseMonitor(
                client, lease, interval=1.0, on_fenced=stop_owned_child,
            )
            initial = monitor.beat(progress=5, stage="isolated-active")
            assert initial["task"]["status"] == "RUNNING"
            monitor.start()
            lose_heartbeat.set()
            assert monitor.fenced.wait(timeout=8), (
                "execution monitor did not fence after real HTTP 503"
            )
            child.wait(timeout=6)
            assert child.returncode != 0, "isolated execution child must stop"
            with pytest.raises(RemoteExecutionFenced):
                monitor.assert_active()
            assert repo.get(task_id).status.value == "RUNNING"
            assert repo.get(task_id).attempt == 1

            # Simulate time passage only after the monitored child is dead.
            expired = (datetime.now(timezone.utc) - timedelta(seconds=3)).isoformat()
            with repo._connect() as database:
                database.execute(
                    "UPDATE tasks SET lease_expires_at=? WHERE task_id=?",
                    (expired, task_id),
                )
            assert FencedTaskRepository(repo.path).release_expired() == 1
            assert repo.get(task_id).status.value == "QUEUED"
            assert repo.get(task_id).attempt == 1

            late = requests.post(
                f"{address}/api/v63/node-executor/partition-agent/"
                f"executions/{task_id}/finish",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "execution_lease_token": lease.lease_token,
                    "execution_generation": lease.generation,
                    "status": "SUCCEEDED",
                },
                timeout=5,
            )
            assert late.status_code == 409, late.text
            assert late.json()["detail"]["code"] == "EXECUTION_FENCED"
        finally:
            if monitor is not None:
                monitor.stop()
            if child is not None:
                if child.poll() is None:
                    child.kill()
                child.wait(timeout=6)
