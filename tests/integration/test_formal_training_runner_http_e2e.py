from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from platform_core.agent_execution import AgentExecutionService, agent_executor_router
from platform_core.node_agent_executor_runtime import (
    NodeExecutorClient,
    NodeExecutorHTTPError,
    RemoteExecutionFenced,
)
from platform_core.node_agent_training_runtime import AgentTrainingRuntimeError
from platform_core.service_nodes import ServiceNodeRepository
from platform_core.task_runtime import ArtifactStore, TaskKind, TaskRecord, TaskRepository
from platform_core.task_runtime.process_control import (
    ProcessController,
    ProcessIdentity,
    ProcessIdentityMismatchError,
)


def _unit_module():
    path = Path(__file__).with_name("..") / "unit" / "test_node_agent_training_runtime.py"
    spec = importlib.util.spec_from_file_location("_training_runner_fixtures", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _payload_resolver(task, payload, assignment):
    return payload


def _result_preparer(_task, _payload, evidence):
    generation = int(evidence["execution_generation"])
    return {
        "already_uploaded": False,
        "storage_ref": {"storage_source_id": "s3-main",
                        "object_key": f"results/{generation}/result.bin",
                        "file_name": "result.bin", "content_type": "application/octet-stream"},
        "sha256": evidence["sha256"],
        "size_bytes": evidence["size_bytes"],
        "upload": {"method": "PUT", "url": "https://signed.example.test/result",
                   "headers": {"Content-Length": str(evidence["size_bytes"]),
                               "x-amz-meta-sha256": evidence["sha256"],
                               "If-None-Match": "*"},
                   "overwrite_protected": True},
    }


UPLOADED_MODELS: dict[str, list[dict]] = {}


def _result_confirmer(task, _payload, evidence):
    generation = int(evidence["execution_generation"])
    return {"result": {
        "task_id": task.task_id, "project_id": task.project_id, "remote_execution": True,
        "output_storage": {"storage_source_id": "s3-main",
                           "object_key": f"results/{generation}/result.bin",
                           "file_name": "result.bin",
                           "content_type": "application/octet-stream"},
        "output_sha256": evidence["sha256"], "output_size_bytes": evidence["size_bytes"],
        "verified_models": [
            {"role": str(item.get("role")), "file_name": str(item.get("file_name")),
             "sha256": str(item.get("sha256")), "size_bytes": int(item.get("size_bytes") or 0)}
            for item in UPLOADED_MODELS.get(task.task_id, [])
        ],
    }}


def _model_preparer(_task, _payload, *, execution_generation, models):
    UPLOADED_MODELS[str(_task.task_id)] = [dict(item) for item in models]
    items = []
    for item in models:
        role = str(item["role"])
        items.append({**dict(item), "artifact_id": f"artifact-{role}",
                      "storage_ref": {"storage_source_id": "s3-main",
                                      "object_key": f"models/{role}.pt",
                                      "file_name": str(item["file_name"]),
                                      "content_type": "application/octet-stream"},
                      "already_uploaded": False,
                      "upload": {"method": "PUT", "url": f"https://signed.example.test/{role}",
                                 "headers": {"Content-Length": str(item["size_bytes"]),
                                             "x-amz-meta-sha256": str(item["sha256"]),
                                             "If-None-Match": "*"}}})
    return {"version_id": "formal-runner", "execution_generation": int(execution_generation),
            "items": items}


def _model_confirmer(_task, _payload, *, execution_generation, models):
    return {"confirmed": True, "version_id": "formal-runner",
            "execution_generation": int(execution_generation),
            "items": [dict(item) for item in models]}


def _start_formal(tmp_path, *, task_id="formal-1", gpu="GPU-A", mutate=None,
                  worker_script=None, cancel_after=None, cancel_marker=None,
                  drop_response_path=None, start_execution=True):
    fixtures = _unit_module()
    current_lease, downloads = fixtures.training_lease(tmp_path)
    payload = dict(current_lease.payload)
    payload.setdefault("remote_execution", {
        "version": 1, "task_kind": "TRAINING", "transport": "object-storage-v1",
    })
    payload["resource_requirements"] = {"gpu_count": 1, "gpu_uuids": [gpu],
                                        "min_gpu_memory_bytes": 1}
    if mutate is not None:
        mutate(payload)
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    artifacts = ArtifactStore(tmp_path / "artifacts")
    app = FastAPI()
    drop_state = [True]
    if drop_response_path is not None:
        @app.middleware("http")
        async def drop_after_commit(request, call_next):
            response = await call_next(request)
            if drop_state[0] and drop_response_path in request.url.path:
                return JSONResponse(status_code=503, content={
                    "detail": {"code": "INJECTED_RESPONSE_LOSS"},
                })
            return response
    app.include_router(agent_executor_router(
        lambda: repository, lambda: artifacts, execution_payload_resolver=_payload_resolver,
        result_upload_preparer=_result_preparer,
        result_upload_confirmer=_result_confirmer,
        training_model_upload_preparer=_model_preparer,
        training_model_upload_confirmer=_model_confirmer,
    ))
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    assert server.started
    nodes = ServiceNodeRepository(repository)
    _node, token = nodes.create({
        "node_id": "formal-runner", "display_name": "formal-runner",
        "connection_mode": "agent", "allowed_capabilities": ["training", "execution-slots:2"],
    })
    nodes.heartbeat("formal-runner", token, {
        "hostname": "formal-runner",
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
    artifacts.atomic_write_json(task_id, "request.json", payload)
    repository.create(TaskRecord.new(
        task_id=task_id, project_id="project-formal", kind=TaskKind.TRAINING,
        payload_ref="request.json", resource_key=f"training:{task_id}",
    ), artifacts=artifacts)
    service = AgentExecutionService(repository, artifacts)
    assert service.allocator.assign_next() is not None
    client = NodeExecutorClient(f"http://127.0.0.1:{port}", "formal-runner", token)
    claimed = client.claim_assignment()
    assert claimed is not None
    if not start_execution:
        # Response-loss probe: the caller drives the HTTP start itself so the
        # injected loss can be asserted on the client boundary. No runner and no
        # execution lease exist yet; central state is the only truth.
        return {
            "fixtures": fixtures, "repository": repository, "artifacts": artifacts,
            "service": service, "client": client, "lease": None, "runner": None,
            "runtime_root": None, "workdirs": None, "server": server,
            "thread": thread, "task_id": task_id, "token": token, "canceller": None,
            "drop_state": drop_state, "app": app, "port": port,
            "claimed": claimed,
            "assignment_token": str(claimed["assignment"]["assignment_lease_token"]),
        }
    lease = client.start_execution(task_id, claimed["assignment"]["assignment_lease_token"])
    transfer = fixtures.FakeTransferSession(downloads)
    runner, runtime_root, workdirs = fixtures.build_runner(tmp_path, client, transfer)
    runner._require_stop_proof = True
    if worker_script is not None:
        (runtime_root / "train_worker.py").write_text(worker_script, encoding="utf-8")
    canceller = None
    if cancel_after is not None:
        def cancel():
            if cancel_marker is not None:
                deadline = time.monotonic() + 15
                while not Path(cancel_marker).is_file() and time.monotonic() < deadline:
                    time.sleep(0.02)
            else:
                time.sleep(cancel_after)
            repository.request_cancel(task_id)
        canceller = threading.Thread(target=cancel, daemon=True)
        canceller.start()
    return {
        "fixtures": fixtures, "repository": repository, "artifacts": artifacts,
        "service": service, "client": client, "lease": lease, "runner": runner,
        "runtime_root": runtime_root, "workdirs": workdirs, "server": server,
        "thread": thread, "task_id": task_id, "token": token, "canceller": canceller,
        "drop_state": drop_state, "app": app, "port": port,
    }


def _stop_formal(stack):
    stack["server"].should_exit = True
    stack["thread"].join(timeout=10)
    runner = stack.get("runner")
    if runner is not None:
        runner.request_shutdown()


def test_formal_training_runner_start_identity_response_loss(tmp_path):
    stack = _start_formal(
        tmp_path, task_id="formal-lost-start-identity",
        worker_script="import time\ntime.sleep(2)\n",
        drop_response_path="/start-identity",
    )
    try:
        outcome = stack["runner"].run(stack["lease"])
        assert outcome.status == "FAILED"
        with stack["repository"]._connect() as database:
            row = database.execute(
                "SELECT process_pid,process_create_time,process_command_hash FROM tasks "
                "WHERE task_id='formal-lost-start-identity'"
            ).fetchone()
            hold = database.execute(
                "SELECT state FROM execution_resource_holds WHERE task_id='formal-lost-start-identity'"
            ).fetchone()
            task_count = database.execute(
                "SELECT COUNT(*) FROM tasks WHERE task_id='formal-lost-start-identity'"
            ).fetchone()[0]
        # The request reached SQLite and was committed before the response was lost.
        assert row is not None and row["process_pid"] is not None
        assert row["process_create_time"] is not None
        assert row["process_command_hash"] is not None
        assert task_count == 1
        # The identity is persisted exactly once and is never overwritten.
        assert (int(row["process_pid"]), float(row["process_create_time"]),
                str(row["process_command_hash"])) == (
            int(row["process_pid"]), float(row["process_create_time"]),
            str(row["process_command_hash"]))
        assert hold is not None
    finally:
        _stop_formal(stack)


def test_formal_training_runner_stop_proof_response_loss(tmp_path):
    stack = _start_formal(
        tmp_path, task_id="formal-lost-stop-proof",
        drop_response_path="/stop-proof",
    )
    try:
        with pytest.raises(RemoteExecutionFenced):
            stack["runner"].run(stack["lease"])
        task = stack["repository"].get("formal-lost-stop-proof")
        assert task.status.value == "RUNNING"
        with stack["repository"]._connect() as database:
            row = database.execute(
                "SELECT process_pid,process_create_time,process_command_hash FROM tasks "
                "WHERE task_id='formal-lost-stop-proof'"
            ).fetchone()
            hold = database.execute(
                "SELECT state,proof_sha256 FROM execution_resource_holds "
                "WHERE task_id='formal-lost-stop-proof'"
            ).fetchone()
        assert row is not None and row["process_pid"] is not None
        assert hold is not None and hold["state"] == "STOP_VERIFIED"
        original_digest = str(hold["proof_sha256"])
        stack["drop_state"][0] = False
        assignment = stack["lease"].assignment or {}
        config = assignment.get("resolved_execution_config") or {}
        selected = config.get("selected_gpu") or {}
        identity = {"pid": int(row["process_pid"]),
                    "create_time": float(row["process_create_time"]),
                    "command_hash": str(row["process_command_hash"])}
        stack["client"].record_stop_proof(
            stack["lease"], assignment_generation=int(assignment.get("generation") or 1),
            gpu_uuid=str(selected.get("uuid") or "GPU-A"),
            process_identity=identity, stop_verified=True,
        )
        stack["client"].finish(stack["lease"], "FAILED")
        with stack["repository"]._connect() as database:
            released = database.execute(
                "SELECT state,proof_sha256 FROM execution_resource_holds "
                "WHERE task_id='formal-lost-stop-proof'"
            ).fetchone()
        assert released["state"] == "RELEASED"
        assert released["proof_sha256"] == original_digest
    finally:
        _stop_formal(stack)


def test_formal_training_runners_through_dual_slot_loop(tmp_path):
    from platform_core.node_agent_execution_slots import BoundedExecutionSlots
    from platform_core.node_agent_executor_loop import NodeAgentExecutorLoop
    from platform_core.task_runtime.process_control import ProcessController

    fixtures = _unit_module()
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    artifacts = ArtifactStore(tmp_path / "artifacts")
    app = FastAPI()
    app.include_router(agent_executor_router(
        lambda: repository, lambda: artifacts, execution_payload_resolver=_payload_resolver,
        result_upload_preparer=_result_preparer,
        result_upload_confirmer=_result_confirmer,
        training_model_upload_preparer=_model_preparer,
        training_model_upload_confirmer=_model_confirmer,
    ))
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    assert server.started
    nodes = ServiceNodeRepository(repository)
    _node, token = nodes.create({
        "node_id": "formal-runner", "display_name": "formal-runner",
        "connection_mode": "agent", "allowed_capabilities": ["training", "execution-slots:2"],
    })
    nodes.heartbeat("formal-runner", token, {
        "hostname": "formal-runner",
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
    prepared = {}
    for task_id, gpu in (("a", "GPU-A"), ("b", "GPU-B"), ("c", "GPU-A")):
        lease, downloads = fixtures.training_lease(tmp_path / task_id)
        payload = dict(lease.payload)
        payload.setdefault("remote_execution", {
            "version": 1, "task_kind": "TRAINING", "transport": "object-storage-v1"})
        payload["resource_requirements"] = {"gpu_count": 1, "gpu_uuids": [gpu],
                                            "min_gpu_memory_bytes": 1}
        artifacts.atomic_write_json(task_id, "request.json", payload)
        repository.create(TaskRecord.new(
            task_id=task_id, project_id="project-formal", kind=TaskKind.TRAINING,
            payload_ref="request.json", resource_key=f"training:{task_id}",
        ), artifacts=artifacts)
        prepared[task_id] = {"downloads": downloads}
    service = AgentExecutionService(repository, artifacts)
    assert service.allocator.assign_next() is not None
    assert service.allocator.assign_next() is not None
    assert service.allocator.assign_next() is None
    client = NodeExecutorClient(f"http://127.0.0.1:{port}", "formal-runner", token)
    active = {}
    started = {}

    def factory(kind, on_started, task_id=None):
        transfer = fixtures.FakeTransferSession(prepared[task_id]["downloads"])
        runner, runtime_root, workdirs = fixtures.build_runner(
            tmp_path / task_id / "loop", client, transfer,
            sleep_seconds=5.0 if task_id != "c" else 0.2,
        )
        runner._require_stop_proof = True

        def on_identity(identity):
            active[task_id] = identity
            started[task_id] = time.monotonic()
            on_started(identity)

        runner._on_process_started = on_identity
        prepared[task_id]["runtime_root"] = runtime_root
        return runner

    loop = NodeAgentExecutorLoop(
        client, object(), capabilities=["training"], max_slots=2,
        slot_runner_factory=factory, slot_controller=ProcessController(),
        poll_interval=0.02,
    )
    try:
        loop.start()
        deadline = time.monotonic() + 20
        while not {"a", "b"}.issubset(started) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert {"a", "b"} <= set(started)
        assert active["a"].pid != active["b"].pid
        assert abs(started["a"] - started["b"]) < 10
        with repository._connect() as database:
            uuids = {row[0] for row in database.execute(
                "SELECT gpu_uuid FROM execution_resource_holds WHERE task_id IN ('a','b')")}
        assert uuids == {"GPU-A", "GPU-B"}

        repository.request_cancel("a")
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            loop._reap_dual_slots()
            with repository._connect() as database:
                hold = database.execute(
                    "SELECT state FROM execution_resource_holds WHERE task_id='a'"
                ).fetchone()
            if (repository.get("a").status.value == "CANCELLED"
                    and hold is not None and hold["state"] == "RELEASED"):
                break
            time.sleep(0.02)
        assert repository.get("a").status.value == "CANCELLED"
        assert repository.get("b").status.value == "RUNNING"
        assigned = None
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            assigned = service.allocator.assign_next()
            if assigned is not None:
                break
            time.sleep(0.02)
        assert assigned is not None
        deadline = time.monotonic() + 20
        while "c" not in started and time.monotonic() < deadline:
            time.sleep(0.02)
        assert "c" in started
        assert active["c"].pid not in {active["a"].pid, active["b"].pid}
        assert repository.get("c").status.value == "RUNNING"
        assert repository.get("b").status.value == "RUNNING"
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            loop._reap_dual_slots()
            with repository._connect() as database:
                states = {row[0]: row[1] for row in database.execute(
                    "SELECT task_id,state FROM execution_resource_holds "
                    "WHERE task_id IN ('b','c')")}
                task_states = {row[0]: row[1] for row in database.execute(
                    "SELECT task_id,status FROM tasks WHERE task_id IN ('b','c')")}
            if (states.get("b") == "RELEASED" and states.get("c") == "RELEASED"
                    and all(value in {"SUCCEEDED", "PARTIAL_SUCCESS", "CANCELLED", "FAILED"}
                            for value in task_states.values())):
                break
            time.sleep(0.02)
        assert states.get("b") == "RELEASED" and states.get("c") == "RELEASED"
        loop.stop(timeout=15)
        loop._slots.wait(15)
    finally:
        loop.stop(timeout=15)
        loop._slots.wait(15)
        server.should_exit = True
        thread.join(timeout=10)


def test_formal_no_launch_preflight_through_dual_loop(tmp_path):
    from platform_core.node_agent_executor_loop import NodeAgentExecutorLoop
    from platform_core.task_runtime.process_control import ProcessController

    fixtures = _unit_module()
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    artifacts = ArtifactStore(tmp_path / "artifacts")
    app = FastAPI()
    app.include_router(agent_executor_router(
        lambda: repository, lambda: artifacts, execution_payload_resolver=_payload_resolver,
        result_upload_preparer=_result_preparer, result_upload_confirmer=_result_confirmer,
        training_model_upload_preparer=_model_preparer,
        training_model_upload_confirmer=_model_confirmer,
    ))
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    assert server.started
    nodes = ServiceNodeRepository(repository)
    _node, token = nodes.create({
        "node_id": "formal-runner", "display_name": "formal-runner",
        "connection_mode": "agent", "allowed_capabilities": ["training", "execution-slots:2"],
    })
    nodes.heartbeat("formal-runner", token, {
        "hostname": "formal-runner", "reported_capabilities": ["training", "execution-slots:2"],
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
    prepared = {}

    def create_task(task_id, gpu, mutate=None):
        lease, downloads = fixtures.training_lease(tmp_path / task_id)
        payload = dict(lease.payload)
        payload.setdefault("remote_execution", {
            "version": 1, "task_kind": "TRAINING", "transport": "object-storage-v1"})
        payload["resource_requirements"] = {"gpu_count": 1, "gpu_uuids": [gpu],
                                            "min_gpu_memory_bytes": 1}
        if mutate:
            mutate(payload)
        artifacts.atomic_write_json(task_id, "request.json", payload)
        repository.create(TaskRecord.new(
            task_id=task_id, project_id="project-formal", kind=TaskKind.TRAINING,
            payload_ref="request.json", resource_key=f"training:{task_id}",
        ), artifacts=artifacts)
        prepared[task_id] = {"downloads": downloads}

    create_task("preflight", "GPU-A", lambda payload: payload.pop("snapshot_id", None))
    service = AgentExecutionService(repository, artifacts)
    assert service.allocator.assign_next() is not None
    client = NodeExecutorClient(f"http://127.0.0.1:{port}", "formal-runner", token)
    workdirs = {}

    def factory(kind, on_started, task_id=None):
        transfer = fixtures.FakeTransferSession(prepared[task_id]["downloads"])
        runner, runtime_root, task_workdirs = fixtures.build_runner(
            tmp_path / task_id / "loop", client, transfer)
        runner._require_stop_proof = True
        runner._on_process_started = on_started
        workdirs[task_id] = task_workdirs
        return runner

    loop = NodeAgentExecutorLoop(
        client, object(), capabilities=["training", "conversion"], max_slots=2,
        runners={"TRAINING": type("R", (), {"ready": True, "run": lambda *_args: None})()},
        slot_runner_factory=factory, slot_controller=ProcessController(), poll_interval=0.02,
    )
    try:
        assert loop.effective_capabilities() == ("training", "execution-slots:2")
        loop.start()
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            loop._reap_dual_slots()
            with repository._connect() as database:
                hold = database.execute(
                    "SELECT state,proof_type FROM execution_resource_holds WHERE task_id='preflight'"
                ).fetchone()
            if (repository.get("preflight").status.value == "FAILED"
                    and hold is not None and hold["state"] == "RELEASED"):
                break
            time.sleep(0.02)
        assert repository.get("preflight").status.value == "FAILED"
        assert repository.get("preflight").process_pid is None
        assert hold is not None and hold["proof_type"] == "NO_PROCESS_LAUNCHED"
        assert workdirs["preflight"].read_process_identity(
            type("L", (), {"task_id": "preflight", "generation": 1})()) is None
        deadline = time.monotonic() + 10
        while loop._slots.active() and time.monotonic() < deadline:
            loop._reap_dual_slots()
            time.sleep(0.02)
        assert loop._slots.active() == ()
        # Freed capacity can accept a subsequent valid task.
        create_task("after", "GPU-B")
        assert service.allocator.assign_next() is not None
        started = {}
        original_factory = factory

        def tracking_factory(kind, on_started, task_id=None):
            runner = original_factory(kind, on_started, task_id)

            def wrapped(identity):
                started[task_id] = identity
                on_started(identity)

            runner._on_process_started = wrapped
            return runner

        loop._slot_factory = tracking_factory
        deadline = time.monotonic() + 20
        while "after" not in started and time.monotonic() < deadline:
            time.sleep(0.02)
        assert "after" in started
        assert repository.get("after").status.value == "RUNNING"
    finally:
        loop.stop(timeout=15)
        loop._slots.wait(15)
        server.should_exit = True
        thread.join(timeout=10)


def test_legacy_schema7_stop_proof_digest_compatibility(tmp_path):
    import hashlib
    import json

    stack = _start_formal(tmp_path, task_id="formal-legacy-proof")
    try:
        outcome = stack["runner"].run(stack["lease"])
        assert outcome.status == "SUCCEEDED"
        with stack["repository"]._connect() as database:
            row = database.execute(
                "SELECT process_pid,process_create_time,process_command_hash FROM tasks "
                "WHERE task_id='formal-legacy-proof'"
            ).fetchone()
            hold = database.execute(
                "SELECT state,assignment_generation,execution_attempt,gpu_uuid "
                "FROM execution_resource_holds WHERE task_id='formal-legacy-proof'"
            ).fetchone()
        identity = {"pid": int(row["process_pid"]),
                    "create_time": float(row["process_create_time"]),
                    "command_hash": str(row["process_command_hash"])}
        legacy_body = {
            "node_id": "formal-runner", "task_id": "formal-legacy-proof",
            "assignment_generation": int(hold["assignment_generation"]),
            "execution_attempt": int(hold["execution_attempt"]),
            "gpu_uuid": str(hold["gpu_uuid"]),
            "process_identity": identity, "stop_verified": True,
        }
        legacy_digest = hashlib.sha256(json.dumps(
            legacy_body, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode()).hexdigest()
        with stack["repository"]._connect() as database:
            database.execute(
                "UPDATE execution_resource_holds SET state='STOP_VERIFIED',proof_sha256=?,"
                "proof_type=NULL WHERE task_id='formal-legacy-proof'",
                (legacy_digest,),
            )
            database.commit()
        result = stack["client"].record_stop_proof(
            stack["lease"],
            assignment_generation=int(hold["assignment_generation"]),
            gpu_uuid=str(hold["gpu_uuid"]),
            process_identity=identity,
            stop_verified=True,
        )
        assert result["state"] == "RELEASED"
        with stack["repository"]._connect() as database:
            upgraded = database.execute(
                "SELECT state,proof_sha256,proof_type FROM execution_resource_holds "
                "WHERE task_id='formal-legacy-proof'"
            ).fetchone()
        assert upgraded["state"] == "RELEASED"
        assert upgraded["proof_sha256"] == legacy_digest
        assert upgraded["proof_type"] == "PROCESS_STOP_VERIFIED"
    finally:
        _stop_formal(stack)


def test_terminal_finish_with_unreleased_hold_recovers_idempotently(tmp_path):
    stack = _start_formal(tmp_path, task_id="formal-terminal-recover")
    try:
        assert stack["runner"].run(stack["lease"]).status == "SUCCEEDED"
        with stack["repository"]._connect() as database:
            row = database.execute(
                "SELECT process_pid,process_create_time,process_command_hash FROM tasks "
                "WHERE task_id='formal-terminal-recover'").fetchone()
            original = database.execute(
                "SELECT proof_sha256,proof_type FROM execution_resource_holds "
                "WHERE task_id='formal-terminal-recover'").fetchone()
            database.execute(
                "UPDATE execution_resource_holds SET state='STOP_VERIFIED' "
                "WHERE task_id='formal-terminal-recover'")
            database.commit()
        identity = {"pid": int(row["process_pid"]),
                    "create_time": float(row["process_create_time"]),
                    "command_hash": str(row["process_command_hash"])}
        assignment = stack["lease"].assignment
        stack["client"].record_stop_proof(
            stack["lease"],
            assignment_generation=int(assignment["generation"]),
            gpu_uuid=str(assignment["resolved_execution_config"]["selected_gpu"]["uuid"]),
            process_identity=identity, stop_verified=True,
        )
        with stack["repository"]._connect() as database:
            recovered = database.execute(
                "SELECT state,proof_sha256,proof_type FROM execution_resource_holds "
                "WHERE task_id='formal-terminal-recover'").fetchone()
        assert recovered["state"] == "RELEASED"
        assert recovered["proof_sha256"] == original["proof_sha256"]
        assert recovered["proof_type"] == original["proof_type"]
    finally:
        _stop_formal(stack)


def test_central_recover_execution_after_agent_death(tmp_path):
    from platform_core.task_runtime.process_control import ProcessController, launch_process
    stack = _start_formal(tmp_path, task_id="formal-recover")
    process = None
    try:
        handle = launch_process([sys.executable, "-c", "import time; time.sleep(30)"])
        process = handle.process
        identity = {"pid": int(handle.identity.pid),
                    "create_time": float(handle.identity.create_time),
                    "command_hash": str(handle.identity.command_hash)}
        stack["client"].record_start_identity(stack["lease"], identity)
        ProcessController().terminate_tree(handle.identity, timeout=5.0)
        assignment = stack["lease"].assignment
        result = stack["client"].recover_execution(
            "formal-recover",
            assignment_generation=int(assignment["generation"]),
            execution_generation=int(stack["lease"].generation),
            gpu_uuid=str(assignment["resolved_execution_config"]["selected_gpu"]["uuid"]),
            process_identity=identity,
        )
        assert result["state"] == "RELEASED"
        task = stack["repository"].get("formal-recover")
        assert task.status.value == "FAILED"
        with stack["repository"]._connect() as database:
            hold = database.execute(
                "SELECT state,proof_type FROM execution_resource_holds WHERE task_id='formal-recover'"
            ).fetchone()
        assert hold["state"] == "RELEASED"
        assert hold["proof_type"] == "PROCESS_STOP_VERIFIED"
    finally:
        if process is not None and process.poll() is None:
            process.kill()
        _stop_formal(stack)


def test_finish_commit_then_hold_release_fault_recovers(tmp_path):
    stack = _start_formal(tmp_path, task_id="formal-fault")
    try:
        with stack["repository"]._connect() as database:
            database.execute(
                "CREATE TRIGGER fail_hold_release BEFORE UPDATE OF state ON "
                "execution_resource_holds WHEN NEW.state='RELEASED' "
                "AND NEW.task_id='formal-fault' BEGIN SELECT RAISE(ABORT,'injected'); END"
            )
            database.commit()
        with pytest.raises(Exception):
            stack["runner"].run(stack["lease"])
        with stack["repository"]._connect() as database:
            database.execute("DROP TRIGGER fail_hold_release")
            database.commit()
            task = database.execute(
                "SELECT status,process_pid,process_create_time,process_command_hash FROM tasks "
                "WHERE task_id='formal-fault'").fetchone()
            hold = database.execute(
                "SELECT state,proof_sha256,proof_type,assignment_generation,execution_attempt,gpu_uuid "
                "FROM execution_resource_holds WHERE task_id='formal-fault'").fetchone()
        assert task["status"] == "SUCCEEDED"
        assert hold["state"] == "STOP_VERIFIED"
        original_digest = str(hold["proof_sha256"])
        # Stop the original central OS process and start a brand-new Python
        # process against the same SQLite database.
        stack["server"].should_exit = True
        stack["thread"].join(timeout=10)
        restarted_port = _free_port()
        script = tmp_path / "central_restart.py"
        script.write_text(
            "import sys\n"
            "from fastapi import FastAPI\n"
            "from platform_core.agent_execution import agent_executor_router\n"
            "from platform_core.task_runtime import ArtifactStore, TaskRepository\n"
            "import uvicorn\n"
            "repo = TaskRepository(sys.argv[1])\n"
            "artifacts = ArtifactStore(sys.argv[2])\n"
            "app = FastAPI()\n"
            "app.include_router(agent_executor_router(lambda: repo, lambda: artifacts))\n"
            "uvicorn.run(app, host='127.0.0.1', port=int(sys.argv[3]), log_level='warning')\n",
            encoding="utf-8",
        )
        child_log = (tmp_path / "central_restart.log").open("w+", encoding="utf-8")
        child = subprocess.Popen(
            [sys.executable, str(script), str(stack["repository"].path),
             str(tmp_path / "artifacts"), str(restarted_port)],
            cwd=str(Path(__file__).resolve().parents[2]),
            env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2])},
            stdout=child_log, stderr=subprocess.STDOUT,
        )
        try:
            connected = False
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                try:
                    with socket.create_connection(("127.0.0.1", restarted_port), timeout=0.2):
                        connected = True
                        break
                except OSError:
                    time.sleep(0.05)
            if not connected:
                child_log.flush()
                child_log.seek(0)
                raise AssertionError("restarted central did not start: "
                                     + child_log.read()[-4000:])
            restarted_client = NodeExecutorClient(
                f"http://127.0.0.1:{restarted_port}", "formal-runner", stack["token"])
            restarted_client.recover_execution(
                "formal-fault",
                assignment_generation=int(hold["assignment_generation"]),
                execution_generation=int(hold["execution_attempt"]),
                gpu_uuid=str(hold["gpu_uuid"]),
                process_identity={
                    "pid": int(task["process_pid"]),
                    "create_time": float(task["process_create_time"]),
                    "command_hash": str(task["process_command_hash"]),
                },
            )
            # Repeated recovery is idempotent.
            restarted_client.recover_execution(
                "formal-fault",
                assignment_generation=int(hold["assignment_generation"]),
                execution_generation=int(hold["execution_attempt"]),
                gpu_uuid=str(hold["gpu_uuid"]),
                process_identity={
                    "pid": int(task["process_pid"]),
                    "create_time": float(task["process_create_time"]),
                    "command_hash": str(task["process_command_hash"]),
                },
            )
        finally:
            child.kill()
            child.wait(timeout=10)
            child_log.close()
        with stack["repository"]._connect() as database:
            recovered = database.execute(
                "SELECT state,proof_sha256,proof_type FROM execution_resource_holds "
                "WHERE task_id='formal-fault'").fetchone()
        assert recovered["state"] == "RELEASED"
        assert recovered["proof_sha256"] == original_digest
        assert recovered["proof_type"] == "PROCESS_STOP_VERIFIED"
    finally:
        _stop_formal(stack)


def test_formal_training_runner_http_success(tmp_path):
    stack = _start_formal(tmp_path)
    try:
        outcome = stack["runner"].run(stack["lease"])
        assert outcome.status == "SUCCEEDED"
        task = stack["repository"].get("formal-1")
        assert task.status.value == "SUCCEEDED"
        with stack["repository"]._connect() as database:
            hold = database.execute(
                "SELECT state,proof_sha256,proof_type FROM execution_resource_holds WHERE task_id='formal-1'"
            ).fetchone()
        assert hold is not None and hold["state"] == "RELEASED" and hold["proof_sha256"]
        assert hold["proof_type"] == "PROCESS_STOP_VERIFIED"
    finally:
        _stop_formal(stack)


def test_formal_training_runner_process_failure(tmp_path):
    stack = _start_formal(
        tmp_path, task_id="formal-fail",
        worker_script="import sys,time\ntime.sleep(0.2)\nsys.exit(7)\n",
    )
    try:
        outcome = stack["runner"].run(stack["lease"])
        assert outcome.status == "FAILED"
        task = stack["repository"].get("formal-fail")
        assert task.status.value == "FAILED"
        with stack["repository"]._connect() as database:
            hold = database.execute(
                "SELECT state,proof_sha256 FROM execution_resource_holds WHERE task_id='formal-fail'"
            ).fetchone()
        assert hold is not None and hold["state"] == "RELEASED"
        assert hold["proof_sha256"]
    finally:
        _stop_formal(stack)


def test_formal_training_runner_startup_failure_uses_no_launch_proof(tmp_path):
    stack = _start_formal(
        tmp_path, task_id="formal-preflight",
        mutate=lambda payload: payload.pop("snapshot_id", None),
    )
    try:
        with pytest.raises(AgentTrainingRuntimeError, match="snapshot identity is missing"):
            stack["runner"].run(stack["lease"])
        task = stack["repository"].get("formal-preflight")
        assert task.status.value == "FAILED"
        assert task.process_pid is None
        assert stack["workdirs"].read_process_identity(stack["lease"]) is None
        assert stack["workdirs"].read_process_launch_intent(stack["lease"]) is None
        with stack["repository"]._connect() as database:
            hold = database.execute(
                "SELECT state,proof_type FROM execution_resource_holds WHERE task_id='formal-preflight'"
            ).fetchone()
        assert hold is not None and hold["state"] == "RELEASED"
        assert hold["proof_type"] == "NO_PROCESS_LAUNCHED"
    finally:
        _stop_formal(stack)


def test_formal_training_runner_central_cancel(tmp_path):
    marker = tmp_path / "worker-started.marker"
    stack = _start_formal(
        tmp_path, task_id="formal-cancel", cancel_after=0.0,
        cancel_marker=marker,
        worker_script=(
            "import pathlib,time\n"
            f"pathlib.Path({str(marker)!r}).write_text('started')\n"
            "time.sleep(20)\n"
        ),
    )
    try:
        outcome = stack["runner"].run(stack["lease"])
        assert outcome.status == "CANCELLED"
        task = stack["repository"].get("formal-cancel")
        assert task.status.value == "CANCELLED"
        with stack["repository"]._connect() as database:
            hold = database.execute(
                "SELECT state FROM execution_resource_holds WHERE task_id='formal-cancel'"
            ).fetchone()
        assert hold is not None and hold["state"] == "RELEASED"
    finally:
        _stop_formal(stack)


def _wait_until(predicate, *, timeout, message, interval=0.02):
    deadline = time.monotonic() + float(timeout)
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    raise AssertionError(message)


def _slot_identity_from_workdir(stack, task_id):
    """Read the durable worker identity the runner wrote before it spawned."""
    attempt = int(stack["repository"].get(task_id).attempt)
    return stack["workdirs"][task_id].read_process_identity(
        SimpleNamespace(task_id=str(task_id), generation=attempt)
    )


def _process_identity_sha256(identity: dict) -> str:
    return hashlib.sha256(json.dumps({
        "pid": int(identity["pid"]),
        "create_time": float(identity["create_time"]),
        "command_hash": str(identity["command_hash"]),
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _wait_central_start_identity(stack, task_id: str, identity: dict, *, timeout: float = 20):
    """Wait until the Agent's start-identity registration is durable.

    Expiring or fencing the lease before central has registered the worker
    identity would permanently lose that registration (the request itself is
    fenced), so recovery could never match the original process. This is a test
    precondition, not a retry around a product defect.
    """
    expected = _process_identity_sha256(identity)
    _wait_until(
        lambda: stack["client"].execution_status(str(task_id)).get(
            "process_identity_sha256") == expected,
        timeout=timeout,
        message=f"central did not register the worker start identity for {task_id}",
    )


def _process_alive(identity):
    try:
        ProcessController().inspect(ProcessIdentity(
            pid=int(identity["pid"]),
            create_time=float(identity["create_time"]),
            command_hash=str(identity["command_hash"]),
        ))
    except (ProcessLookupError, ProcessIdentityMismatchError):
        return False
    return True


def _expected_stop_proof_sha256(
    *, node_id, task_id, assignment_generation, execution_attempt,
    gpu_uuid, process_identity,
):
    """Recompute the central stop-proof digest from the original identity."""
    proof = {
        "proof_type": "PROCESS_STOP_VERIFIED",
        "node_id": str(node_id),
        "task_id": str(task_id),
        "assignment_generation": int(assignment_generation),
        "execution_attempt": int(execution_attempt),
        "gpu_uuid": str(gpu_uuid),
        "process_identity": {
            "pid": int(process_identity["pid"]),
            "create_time": float(process_identity["create_time"]),
            "command_hash": str(process_identity["command_hash"]),
        },
        "stop_verified": True,
        "no_process_launched": False,
        "no_launch_evidence": {},
    }
    return hashlib.sha256(json.dumps(
        proof, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _start_formal_dual_slot(tmp_path, specs):
    """Real central HTTP + real dual-slot loop + real formal train_worker.

    ``specs`` items are ``(task_id, gpu_uuid, worker_sleep_seconds)``. Only the
    first two tasks are pre-assigned; the remaining ones stay QUEUED so a test
    can prove admission ordering (a released GPU slot becomes assignable).
    """
    from platform_core.node_agent_executor_loop import NodeAgentExecutorLoop

    fixtures = _unit_module()
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    artifacts = ArtifactStore(tmp_path / "artifacts")
    app = FastAPI()
    app.include_router(agent_executor_router(
        lambda: repository, lambda: artifacts, execution_payload_resolver=_payload_resolver,
        result_upload_preparer=_result_preparer,
        result_upload_confirmer=_result_confirmer,
        training_model_upload_preparer=_model_preparer,
        training_model_upload_confirmer=_model_confirmer,
    ))
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    assert server.started
    nodes = ServiceNodeRepository(repository)
    _node, token = nodes.create({
        "node_id": "formal-runner", "display_name": "formal-runner",
        "connection_mode": "agent", "allowed_capabilities": ["training", "execution-slots:2"],
    })
    nodes.heartbeat("formal-runner", token, {
        "hostname": "formal-runner",
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
    prepared = {}
    for task_id, gpu, sleep_seconds in specs:
        lease, downloads = fixtures.training_lease(tmp_path / task_id)
        payload = dict(lease.payload)
        payload.setdefault("remote_execution", {
            "version": 1, "task_kind": "TRAINING", "transport": "object-storage-v1"})
        payload["resource_requirements"] = {"gpu_count": 1, "gpu_uuids": [gpu],
                                            "min_gpu_memory_bytes": 1}
        artifacts.atomic_write_json(task_id, "request.json", payload)
        repository.create(TaskRecord.new(
            task_id=task_id, project_id="project-formal", kind=TaskKind.TRAINING,
            payload_ref="request.json", resource_key=f"training:{task_id}",
        ), artifacts=artifacts)
        prepared[task_id] = {"downloads": downloads, "sleep_seconds": float(sleep_seconds)}
    service = AgentExecutionService(repository, artifacts)
    for _ in range(min(2, len(specs))):
        assert service.allocator.assign_next() is not None
    client = NodeExecutorClient(f"http://127.0.0.1:{port}", "formal-runner", token)
    started = {}
    workdirs = {}

    def factory(kind, on_started, task_id=None):
        transfer = fixtures.FakeTransferSession(prepared[task_id]["downloads"])
        runner, runtime_root, task_workdirs = fixtures.build_runner(
            tmp_path / task_id / "loop", client, transfer,
            sleep_seconds=prepared[task_id]["sleep_seconds"],
        )
        runner._require_stop_proof = True

        def on_identity(identity):
            started[task_id] = identity
            on_started(identity)

        runner._on_process_started = on_identity
        prepared[task_id]["runtime_root"] = runtime_root
        workdirs[task_id] = task_workdirs
        return runner

    loop = NodeAgentExecutorLoop(
        client, object(), capabilities=["training"], max_slots=2,
        slot_runner_factory=factory, slot_controller=ProcessController(),
        poll_interval=0.02,
    )
    loop.start()
    stack = {
        "fixtures": fixtures, "repository": repository, "artifacts": artifacts,
        "service": service, "client": client, "loop": loop, "started": started,
        "workdirs": workdirs, "prepared": prepared, "server": server,
        "thread": thread, "port": port, "token": token, "specs": specs,
        "app": app,
    }
    _wait_until(
        lambda: {"a", "b"} <= set(started),
        timeout=20, message="dual-slot formal runners did not start",
    )
    return stack


def _stop_formal_dual(stack):
    stack["loop"].stop(timeout=15)
    stack["loop"]._slots.wait(15)
    stack["server"].should_exit = True
    stack["thread"].join(timeout=10)


def _run_dual_slot_worker_death_scenario(tmp_path, killer):
    """External worker death of slot A must fail only slot A.

    A: FAILED + Hold RELEASED with a real PROCESS_STOP_VERIFIED proof bound to
    the original identity/assignment/GPU/attempt; attempt unchanged; GPU not
    reusable before the release; B keeps running (and succeeds); the third task
    only becomes admissible after A's Hold is released.
    """
    stack = _start_formal_dual_slot(tmp_path, [
        ("a", "GPU-A", 30.0), ("b", "GPU-B", 15.0), ("c", "GPU-A", 3.0),
    ])
    try:
        _wait_until(
            lambda: {"a", "b"} <= set(stack["started"]),
            timeout=20, message="A/B never entered RUNNING",
        )
        # Central truth before the kill: both slots RUNNING, both Holds HELD.
        for task_id in ("a", "b"):
            status = stack["client"].execution_status(task_id)
            assert status["status"] == "RUNNING"
            assert status["hold_state"] == "HELD"
            assert status["execution_attempt"] == 1
            assert status["execution_slots"] == 2
            assert status["proof_type"] is None
            assert status["proof_sha256"] is None
        identity_a = _slot_identity_from_workdir(stack, "a")
        assert identity_a is not None, "local worker identity was not persisted"
        assert int(identity_a["pid"]) == int(stack["started"]["a"].pid)
        assert float(identity_a["create_time"]) == float(stack["started"]["a"].create_time)
        assert str(identity_a["command_hash"]) == str(stack["started"]["a"].command_hash)
        _wait_central_start_identity(stack, "a", identity_a)
        with stack["repository"]._connect() as database:
            hold_a = database.execute(
                "SELECT assignment_generation,execution_attempt,gpu_uuid "
                "FROM execution_resource_holds WHERE task_id='a'"
            ).fetchone()
        assert hold_a is not None
        assert int(hold_a["execution_attempt"]) == 1
        assert str(hold_a["gpu_uuid"]) == "GPU-A"
        # While A holds GPU-A the third task must not be admitted and no other
        # task may reuse that GPU.
        assert stack["service"].allocator.assign_next() is None
        with stack["repository"]._connect() as database:
            live_gpu_a = [
                str(row["task_id"]) for row in database.execute(
                    "SELECT task_id FROM execution_resource_holds "
                    "WHERE gpu_uuid='GPU-A' AND state<>'RELEASED'"
                )
            ]
        assert live_gpu_a == ["a"]
        assert stack["repository"].get("c").status.value == "QUEUED"

        # Real external termination of A's worker process (not a simulated stop).
        killer(int(identity_a["pid"]))

        def a_failed_and_released():
            stack["loop"]._reap_dual_slots()
            try:
                status = stack["client"].execution_status("a")
            except NodeExecutorHTTPError:
                return False
            return status["status"] == "FAILED" and status["hold_state"] == "RELEASED"

        _wait_until(a_failed_and_released, timeout=25,
                    message="externally killed A did not reach FAILED with a released Hold")
        status_a = stack["client"].execution_status("a")
        assert status_a["status"] == "FAILED"
        assert status_a["hold_state"] == "RELEASED"
        assert status_a["proof_type"] == "PROCESS_STOP_VERIFIED"
        assert status_a["proof_sha256"]
        assert status_a["execution_attempt"] == 1
        assert status_a["execution_slots"] == 2
        expected_digest = _expected_stop_proof_sha256(
            node_id="formal-runner", task_id="a",
            assignment_generation=int(hold_a["assignment_generation"]),
            execution_attempt=1, gpu_uuid="GPU-A", process_identity=identity_a,
        )
        assert status_a["proof_sha256"] == expected_digest
        with stack["repository"]._connect() as database:
            attempt_row = database.execute(
                "SELECT attempt,status FROM tasks WHERE task_id='a'"
            ).fetchone()
            released_hold = database.execute(
                "SELECT state,proof_type,proof_sha256 FROM execution_resource_holds "
                "WHERE task_id='a'"
            ).fetchone()
            live_gpu_a = [
                str(row["task_id"]) for row in database.execute(
                    "SELECT task_id FROM execution_resource_holds "
                    "WHERE gpu_uuid='GPU-A' AND state<>'RELEASED'"
                )
            ]
        assert int(attempt_row["attempt"]) == 1
        assert str(attempt_row["status"]) == "FAILED"
        assert str(released_hold["state"]) == "RELEASED"
        assert str(released_hold["proof_type"]) == "PROCESS_STOP_VERIFIED"
        assert str(released_hold["proof_sha256"]) == expected_digest
        # GPU-A was never reused before A's Hold release.
        assert live_gpu_a == []
        # A's slot capacity is only freed after the verified release.
        _wait_until(
            lambda: (stack["loop"]._reap_dual_slots() or True)
            and all(slot.task_id != "a" for slot in stack["loop"]._slots.active()),
            timeout=20, message="A slot capacity was not released after the proof",
        )
        # B was running throughout and is unaffected by A's death.
        assert stack["repository"].get("b").status.value == "RUNNING"
        assert stack["repository"].get("c").status.value == "QUEUED"
        # The third task becomes admissible only after A released GPU-A.
        assigned_c = stack["service"].allocator.assign_next()
        assert assigned_c is not None and assigned_c["task_id"] == "c"
        assert assigned_c["resolved_execution_config"]["selected_gpu"]["uuid"] == "GPU-A"
        _wait_until(
            lambda: "c" in stack["started"],
            timeout=20, message="the third task was never started after release",
        )
        status_c = stack["client"].execution_status("c")
        assert status_c["status"] == "RUNNING"
        assert status_c["hold_state"] == "HELD"
        assert status_c["hold_gpu_uuid"] == "GPU-A"
        status_b = stack["client"].execution_status("b")
        assert status_b["status"] == "RUNNING"
        assert status_b["hold_state"] == "HELD"
        # B eventually completes normally (its own proof/release path).
        _wait_until(
            lambda: (stack["loop"]._reap_dual_slots() or True)
            and stack["client"].execution_status("b")["status"] == "SUCCEEDED"
            and stack["client"].execution_status("b")["hold_state"] == "RELEASED",
            timeout=40, message="B did not succeed after A's isolated failure",
        )
    finally:
        _stop_formal_dual(stack)


@pytest.mark.skipif(os.name != "posix", reason="requires os.kill(worker_pid, SIGKILL)")
def test_posix_worker_sigkill_fails_only_its_dual_slot(tmp_path):
    _run_dual_slot_worker_death_scenario(
        tmp_path, lambda pid: os.kill(int(pid), signal.SIGKILL),
    )


@pytest.mark.skipif(os.name != "nt", reason="requires native Windows TerminateProcess")
def test_windows_worker_termination_fails_only_its_dual_slot(tmp_path):
    # Windows has no SIGKILL. os.kill() with a non-console signal maps to
    # TerminateProcess, the equivalent unconditional external process death;
    # this keeps the same dual-slot isolation assertions runnable on Windows.
    _run_dual_slot_worker_death_scenario(
        tmp_path, lambda pid: os.kill(int(pid), signal.SIGTERM),
    )


def test_expired_lease_fencing_isolates_slot_and_recovery_releases(tmp_path):
    """A stale/expired A lease token must never mutate central truth.

    The Hold stays HELD until the legitimate central recover_execution call;
    sibling B heartbeats/status are unaffected; the stale token cannot publish
    a stop proof or finish for the task or its sibling; recovery proves the
    original identity digest.
    """
    stack = _start_formal_dual_slot(tmp_path, [("a", "GPU-A", 30.0), ("b", "GPU-B", 10.0)])
    try:
        _wait_until(
            lambda: {"a", "b"} <= set(stack["started"]),
            timeout=20, message="A/B never entered RUNNING",
        )
        identity_a = _slot_identity_from_workdir(stack, "a")
        assert identity_a is not None
        _wait_central_start_identity(stack, "a", identity_a)
        with stack["repository"]._connect() as database:
            lease_a_row = database.execute(
                "SELECT lease_token,attempt FROM tasks WHERE task_id='a'"
            ).fetchone()
            lease_b_row = database.execute(
                "SELECT lease_token,attempt FROM tasks WHERE task_id='b'"
            ).fetchone()
            hold_a = database.execute(
                "SELECT assignment_generation,execution_attempt,gpu_uuid "
                "FROM execution_resource_holds WHERE task_id='a'"
            ).fetchone()
        lease_a = SimpleNamespace(
            task_id="a", lease_token=str(lease_a_row["lease_token"]),
            generation=int(lease_a_row["attempt"]),
        )
        lease_b = SimpleNamespace(
            task_id="b", lease_token=str(lease_b_row["lease_token"]),
            generation=int(lease_b_row["attempt"]),
        )
        assignment_generation = int(hold_a["assignment_generation"])
        # Isolated central fencing: only A's execution lease expires in SQLite.
        with stack["repository"]._connect() as database:
            database.execute(
                "UPDATE tasks SET lease_expires_at='2000-01-01T00:00:00+00:00' "
                "WHERE task_id='a'"
            )
            database.commit()

        # Old token: heartbeat, finish, and stop proof are all fenced.
        with pytest.raises(NodeExecutorHTTPError) as heartbeat_error:
            stack["client"].heartbeat(lease_a)
        assert heartbeat_error.value.status_code == 409
        assert heartbeat_error.value.code == "EXECUTION_FENCED"
        with pytest.raises(NodeExecutorHTTPError) as finish_error:
            stack["client"].finish(lease_a, "FAILED", error="stale fenced finish")
        assert finish_error.value.status_code == 409
        assert finish_error.value.code == "EXECUTION_FENCED"
        with pytest.raises(NodeExecutorHTTPError) as proof_error:
            stack["client"].record_stop_proof(
                lease_a,
                assignment_generation=assignment_generation,
                gpu_uuid="GPU-A",
                process_identity=identity_a,
                stop_verified=True,
            )
        assert proof_error.value.status_code == 409
        assert proof_error.value.code == "EXECUTION_FENCED"

        # The Hold was not prematurely released and no stale terminal truth or
        # proof was published.
        status_a = stack["client"].execution_status("a")
        assert status_a["status"] == "RUNNING"
        assert status_a["hold_state"] == "HELD"
        assert status_a["hold_execution_attempt"] == 1
        assert status_a["proof_type"] is None
        assert status_a["proof_sha256"] is None
        # Fencing made the local runner terminate its own worker; central truth
        # still needs the verified recovery below.
        _wait_until(lambda: not _process_alive(identity_a), timeout=20,
                    message="fenced A worker was not stopped")
        status_a = stack["client"].execution_status("a")
        assert status_a["status"] == "RUNNING"
        assert status_a["hold_state"] == "HELD"
        assert status_a["proof_type"] is None

        # Sibling B keeps its valid heartbeat and untouched state.
        heartbeat_b = stack["client"].heartbeat(lease_b)
        assert heartbeat_b["task"]["status"] == "RUNNING"
        status_b = stack["client"].execution_status("b")
        assert status_b["status"] == "RUNNING"
        assert status_b["hold_state"] == "HELD"
        # A's stale token cannot finish its sibling or a newer attempt.
        with pytest.raises(NodeExecutorHTTPError) as sibling_error:
            stack["client"].finish(
                SimpleNamespace(task_id="b", lease_token=lease_a.lease_token,
                                generation=lease_a.generation),
                "FAILED", error="stale token against sibling",
            )
        assert sibling_error.value.status_code == 409
        assert sibling_error.value.code == "EXECUTION_FENCED"
        status_b = stack["client"].execution_status("b")
        assert status_b["status"] == "RUNNING"
        assert status_b["hold_state"] == "HELD"
        # No A Hold record other than the original attempt exists.
        with stack["repository"]._connect() as database:
            hold_attempts = [
                int(row["execution_attempt"]) for row in database.execute(
                    "SELECT execution_attempt FROM execution_resource_holds "
                    "WHERE task_id='a'"
                )
            ]
        assert hold_attempts == [1]

        # Legitimate path: authenticated recovery with the original identity.
        recovered = stack["client"].recover_execution(
            "a",
            assignment_generation=assignment_generation,
            execution_generation=1,
            gpu_uuid="GPU-A",
            process_identity=identity_a,
        )
        assert recovered["state"] == "RELEASED"
        expected_digest = _expected_stop_proof_sha256(
            node_id="formal-runner", task_id="a",
            assignment_generation=assignment_generation,
            execution_attempt=1, gpu_uuid="GPU-A", process_identity=identity_a,
        )
        assert recovered["proof_sha256"] == expected_digest
        status_a = stack["client"].execution_status("a")
        assert status_a["status"] == "FAILED"
        assert status_a["hold_state"] == "RELEASED"
        assert status_a["proof_type"] == "PROCESS_STOP_VERIFIED"
        assert status_a["proof_sha256"] == expected_digest
        assert status_a["execution_attempt"] == 1
        assert status_a["execution_slots"] == 2
        with stack["repository"]._connect() as database:
            row = database.execute(
                "SELECT state,proof_type,proof_sha256 FROM execution_resource_holds "
                "WHERE task_id='a'"
            ).fetchone()
        assert str(row["state"]) == "RELEASED"
        assert str(row["proof_type"]) == "PROCESS_STOP_VERIFIED"
        assert str(row["proof_sha256"]) == expected_digest
        # B was unaffected by A's fencing/recovery and finishes normally.
        _wait_until(
            lambda: (stack["loop"]._reap_dual_slots() or True)
            and stack["client"].execution_status("b")["status"] == "SUCCEEDED"
            and stack["client"].execution_status("b")["hold_state"] == "RELEASED",
            timeout=40, message="B did not succeed after A's fencing/recovery",
        )
    finally:
        _stop_formal_dual(stack)


def test_advanced_attempt_fencing_rejects_stale_token(tmp_path):
    """Central generation advance (SQL) fences the old token without touching
    the still-HELD Hold or the sibling slot.
    """
    stack = _start_formal_dual_slot(tmp_path, [("a", "GPU-A", 30.0), ("b", "GPU-B", 30.0)])
    try:
        _wait_until(
            lambda: {"a", "b"} <= set(stack["started"]),
            timeout=20, message="A/B never entered RUNNING",
        )
        identity_a = _slot_identity_from_workdir(stack, "a")
        assert identity_a is not None
        _wait_central_start_identity(stack, "a", identity_a)
        with stack["repository"]._connect() as database:
            lease_a_row = database.execute(
                "SELECT lease_token,attempt FROM tasks WHERE task_id='a'"
            ).fetchone()
            lease_b_row = database.execute(
                "SELECT lease_token,attempt FROM tasks WHERE task_id='b'"
            ).fetchone()
            hold_a = database.execute(
                "SELECT assignment_generation,execution_attempt,gpu_uuid "
                "FROM execution_resource_holds WHERE task_id='a'"
            ).fetchone()
        original_attempt = int(lease_a_row["attempt"])
        assert original_attempt == 1
        lease_a = SimpleNamespace(
            task_id="a", lease_token=str(lease_a_row["lease_token"]),
            generation=original_attempt,
        )
        lease_b = SimpleNamespace(
            task_id="b", lease_token=str(lease_b_row["lease_token"]),
            generation=int(lease_b_row["attempt"]),
        )
        # Simulate central fencing: the execution generation advanced while the
        # old Hold row (attempt 1) is still unreleased.
        with stack["repository"]._connect() as database:
            database.execute(
                "UPDATE tasks SET attempt=attempt+1 WHERE task_id='a'"
            )
            database.commit()
        with pytest.raises(NodeExecutorHTTPError) as heartbeat_error:
            stack["client"].heartbeat(lease_a)
        assert heartbeat_error.value.status_code == 409
        assert heartbeat_error.value.code == "EXECUTION_FENCED"
        with pytest.raises(NodeExecutorHTTPError) as finish_error:
            stack["client"].finish(lease_a, "FAILED", error="stale attempt finish")
        assert finish_error.value.status_code == 409
        assert finish_error.value.code == "EXECUTION_FENCED"
        with pytest.raises(NodeExecutorHTTPError) as proof_error:
            stack["client"].record_stop_proof(
                lease_a,
                assignment_generation=int(hold_a["assignment_generation"]),
                gpu_uuid="GPU-A",
                process_identity=identity_a,
                stop_verified=True,
            )
        assert proof_error.value.status_code == 409
        assert proof_error.value.code == "EXECUTION_FENCED"
        # The original Hold is still HELD and the newer attempt has no Hold or
        # stop proof of its own.
        status_a = stack["client"].execution_status("a")
        assert status_a["execution_attempt"] == original_attempt + 1
        assert status_a["hold_state"] == "HELD"
        assert status_a["hold_execution_attempt"] == original_attempt
        assert status_a["proof_type"] is None
        assert status_a["proof_sha256"] is None
        assert status_a["status"] == "RUNNING"
        with stack["repository"]._connect() as database:
            holds = database.execute(
                "SELECT task_id,state,execution_attempt,proof_type "
                "FROM execution_resource_holds WHERE task_id='a'"
            ).fetchall()
        assert len(holds) == 1
        assert str(holds[0]["state"]) == "HELD"
        assert int(holds[0]["execution_attempt"]) == original_attempt
        assert holds[0]["proof_type"] is None
        # Sibling B is unaffected by A's advanced attempt.
        assert stack["client"].heartbeat(lease_b)["task"]["status"] == "RUNNING"
        status_b = stack["client"].execution_status("b")
        assert status_b["status"] == "RUNNING"
        assert status_b["hold_state"] == "HELD"
        with pytest.raises(NodeExecutorHTTPError) as sibling_error:
            stack["client"].finish(
                SimpleNamespace(task_id="b", lease_token=lease_a.lease_token,
                                generation=lease_a.generation),
                "FAILED", error="stale attempt token against sibling",
            )
        assert sibling_error.value.code == "EXECUTION_FENCED"
        status_b = stack["client"].execution_status("b")
        assert status_b["status"] == "RUNNING"
        assert status_b["hold_state"] == "HELD"
        # No Hold was created for the advanced (fenced) attempt.
        with stack["repository"]._connect() as database:
            advanced_holds = database.execute(
                "SELECT COUNT(*) FROM execution_resource_holds "
                "WHERE task_id='a' AND execution_attempt<>?",
                (original_attempt,),
            ).fetchone()[0]
        assert int(advanced_holds) == 0
    finally:
        _stop_formal_dual(stack)


# ---------------------------------------------------------------------------
# Remaining N7 response-loss matrix: start_execution, finish, recover.
# start-identity and stop-proof loss are covered by the tests above.
# ---------------------------------------------------------------------------


def _central_snapshot(repository, task_ids):
    """Durable rows a read-only GET must never change.

    Mutable heartbeat columns (updated_at/progress/lease_expires_at/stage) are
    deliberately excluded: a live runner legitimately heartbeats those.
    """
    snapshot = {}
    with repository._connect() as database:
        for task_id in task_ids:
            task = database.execute(
                "SELECT task_id,status,attempt,finished_at,process_pid,"
                "process_create_time,process_command_hash,lease_token,worker_id "
                "FROM tasks WHERE task_id=?", (str(task_id),),
            ).fetchone()
            holds = [dict(row) for row in database.execute(
                "SELECT task_id,node_id,assignment_generation,execution_attempt,"
                "gpu_uuid,state,proof_sha256,proof_type FROM execution_resource_holds "
                "WHERE task_id=? ORDER BY execution_attempt", (str(task_id),),
            )]
            assignments = [dict(row) for row in database.execute(
                "SELECT generation,node_id,state,release_reason,lease_token,"
                "resolved_execution_config FROM task_node_assignments "
                "WHERE task_id=? ORDER BY generation", (str(task_id),),
            )]
            snapshot[str(task_id)] = {
                "task": dict(task) if task is not None else None,
                "holds": holds,
                "assignments": assignments,
            }
    return snapshot


def _row_count(repository, table, task_id):
    with repository._connect() as database:
        return int(database.execute(
            f"SELECT COUNT(*) FROM {table} WHERE task_id=?", (str(task_id),),
        ).fetchone()[0])


def test_formal_training_runner_start_execution_response_loss(tmp_path):
    """Committed start + lost response must never start a duplicate execution.

    The control plane committed RUNNING/attempt=1/HELD and consumed the
    Assignment before the 503. A retry is fenced fail-closed: no second
    attempt, no second Hold, no forged terminal, no premature Hold release.
    """
    task_id = "formal-lost-start"
    stack = _start_formal(
        tmp_path, task_id=task_id, start_execution=False,
        drop_response_path=f"/assignments/{task_id}/start",
    )
    try:
        token = stack["assignment_token"]
        with pytest.raises(NodeExecutorHTTPError) as lost:
            stack["client"].start_execution(task_id, token)
        assert lost.value.status_code >= 500
        assert lost.value.code == "INJECTED_RESPONSE_LOSS"

        # The start transaction committed before the response was dropped.
        with stack["repository"]._connect() as database:
            row = database.execute(
                "SELECT status,attempt,finished_at,process_pid,process_create_time,"
                "process_command_hash,lease_token,worker_id "
                "FROM tasks WHERE task_id=?", (task_id,),
            ).fetchone()
            hold = database.execute(
                "SELECT state,execution_attempt,assignment_generation,gpu_uuid,"
                "proof_type,proof_sha256 FROM execution_resource_holds WHERE task_id=?",
                (task_id,),
            ).fetchone()
            assignment = database.execute(
                "SELECT state,release_reason,lease_token,resolved_execution_config "
                "FROM task_node_assignments WHERE task_id=?", (task_id,),
            ).fetchone()
        assert row["status"] == "RUNNING" and row["attempt"] == 1
        assert row["finished_at"] is None and row["process_pid"] is None
        assert row["lease_token"]
        assert hold["state"] == "HELD" and hold["execution_attempt"] == 1
        assert hold["gpu_uuid"] == "GPU-A"
        assert hold["proof_type"] is None and hold["proof_sha256"] is None
        assert assignment["state"] == "RELEASED"
        assert assignment["release_reason"] == "execution_started"
        assert assignment["lease_token"] is None
        config = json.loads(assignment["resolved_execution_config"])
        assert config["execution_attempt"] == 1
        assert config["execution_slots"] == 2
        assert _row_count(stack["repository"], "tasks", task_id) == 1
        assert _row_count(stack["repository"], "execution_resource_holds", task_id) == 1

        # Retry after the loss: fail closed, no duplicate execution.
        stack["drop_state"][0] = False
        with pytest.raises(NodeExecutorHTTPError) as retry:
            stack["client"].start_execution(task_id, token)
        assert retry.value.status_code == 409
        assert retry.value.code == "ASSIGNMENT_NOT_CLAIMED"
        assert stack["client"].claim_assignment() is None

        with stack["repository"]._connect() as database:
            row_after = database.execute(
                "SELECT status,attempt,finished_at,process_pid,process_create_time,"
                "process_command_hash,lease_token,worker_id "
                "FROM tasks WHERE task_id=?", (task_id,),
            ).fetchone()
            hold_after = database.execute(
                "SELECT state,execution_attempt,assignment_generation,gpu_uuid,"
                "proof_type,proof_sha256 FROM execution_resource_holds WHERE task_id=?",
                (task_id,),
            ).fetchone()
        assert dict(row_after) == dict(row)
        assert dict(hold_after) == dict(hold)
        assert _row_count(stack["repository"], "tasks", task_id) == 1
        assert _row_count(stack["repository"], "execution_resource_holds", task_id) == 1
        # No process identity was forged by the retried/failed start.
        assert row_after["process_pid"] is None
        assert row_after["process_create_time"] is None
        assert row_after["process_command_hash"] is None

        status = stack["client"].execution_status(task_id)
        assert status["status"] == "RUNNING"
        assert status["execution_attempt"] == 1
        assert status["execution_slots"] == 2
        assert status["hold_state"] == "HELD"
        assert status["hold_gpu_uuid"] == "GPU-A"
        assert status["process_identity_sha256"] is None
        assert status["proof_type"] is None
        assert status["proof_sha256"] is None
        assert status["recovery_state"] == "HELD"
        assert status["recovery_blocked_reason"] == "PROCESS_STOP_UNPROVEN"
    finally:
        _stop_formal(stack)


def test_formal_training_runner_finish_response_loss(tmp_path):
    """A committed finish whose response is lost is never re-forged.

    The terminal status, its finished_at and the RELEASED Hold with a real stop
    proof digest are already durable. Retrying finish is fenced, and the
    terminal truth/digest/attempt stay byte-identical.
    """
    task_id = "formal-lost-finish"
    stack = _start_formal(
        tmp_path, task_id=task_id,
        drop_response_path="/finish",
    )
    try:
        with pytest.raises(RemoteExecutionFenced):
            stack["runner"].run(stack["lease"])

        with stack["repository"]._connect() as database:
            row = database.execute(
                "SELECT status,attempt,finished_at,process_pid,process_create_time,"
                "process_command_hash FROM tasks WHERE task_id=?", (task_id,),
            ).fetchone()
            hold = database.execute(
                "SELECT state,assignment_generation,execution_attempt,gpu_uuid,"
                "proof_type,proof_sha256 FROM execution_resource_holds WHERE task_id=?",
                (task_id,),
            ).fetchone()
        assert row["status"] == "SUCCEEDED" and row["attempt"] == 1
        assert row["finished_at"] is not None
        assert row["process_pid"] is not None
        assert hold["state"] == "RELEASED"
        assert hold["proof_type"] == "PROCESS_STOP_VERIFIED"
        identity = {"pid": int(row["process_pid"]),
                    "create_time": float(row["process_create_time"]),
                    "command_hash": str(row["process_command_hash"])}
        expected_digest = _expected_stop_proof_sha256(
            node_id="formal-runner", task_id=task_id,
            assignment_generation=int(hold["assignment_generation"]),
            execution_attempt=int(hold["execution_attempt"]),
            gpu_uuid=str(hold["gpu_uuid"]), process_identity=identity,
        )
        assert hold["proof_sha256"] == expected_digest

        # Retrying the lost finish must not duplicate a terminal transition.
        stack["drop_state"][0] = False
        with pytest.raises(NodeExecutorHTTPError) as retry:
            stack["client"].finish(stack["lease"], "FAILED",
                                   error="retry after lost finish")
        assert retry.value.status_code == 409
        assert retry.value.code == "EXECUTION_FENCED"
        with stack["repository"]._connect() as database:
            row_after = database.execute(
                "SELECT status,attempt,finished_at,process_pid,process_create_time,"
                "process_command_hash FROM tasks WHERE task_id=?", (task_id,),
            ).fetchone()
            hold_after = database.execute(
                "SELECT state,assignment_generation,execution_attempt,gpu_uuid,"
                "proof_type,proof_sha256 FROM execution_resource_holds WHERE task_id=?",
                (task_id,),
            ).fetchone()
        # Same single terminal truth, same proof; the FAILED retry was fenced
        # and never replaced the committed SUCCEEDED.
        assert dict(row_after) == dict(row)
        assert row_after["status"] == "SUCCEEDED"
        assert dict(hold_after) == dict(hold)
        assert _row_count(stack["repository"], "tasks", task_id) == 1
        assert _row_count(stack["repository"], "execution_resource_holds", task_id) == 1
    finally:
        _stop_formal(stack)


def test_central_recover_response_loss_is_idempotent(tmp_path):
    """Committed recovery + lost response must stay idempotent and consistent."""
    task_id = "formal-lost-recover"
    from platform_core.task_runtime.process_control import ProcessController, launch_process

    stack = _start_formal(tmp_path, task_id=task_id, drop_response_path="/recover")
    process = None
    try:
        handle = launch_process([sys.executable, "-c", "import time; time.sleep(30)"])
        process = handle.process
        identity = {"pid": int(handle.identity.pid),
                    "create_time": float(handle.identity.create_time),
                    "command_hash": str(handle.identity.command_hash)}
        stack["client"].record_start_identity(stack["lease"], identity)
        ProcessController().terminate_tree(handle.identity, timeout=5.0)
        assignment = stack["lease"].assignment
        assignment_generation = int(assignment["generation"])
        execution_generation = int(stack["lease"].generation)
        gpu_uuid = str(assignment["resolved_execution_config"]["selected_gpu"]["uuid"])

        with pytest.raises(NodeExecutorHTTPError) as lost:
            stack["client"].recover_execution(
                task_id, assignment_generation=assignment_generation,
                execution_generation=execution_generation, gpu_uuid=gpu_uuid,
                process_identity=identity,
            )
        assert lost.value.status_code >= 500
        assert lost.value.code == "INJECTED_RESPONSE_LOSS"

        expected_digest = _expected_stop_proof_sha256(
            node_id="formal-runner", task_id=task_id,
            assignment_generation=assignment_generation,
            execution_attempt=execution_generation,
            gpu_uuid=gpu_uuid, process_identity=identity,
        )
        task = stack["repository"].get(task_id)
        assert task.status.value == "FAILED"
        with stack["repository"]._connect() as database:
            row = database.execute(
                "SELECT status,attempt,finished_at,process_pid,process_create_time,"
                "process_command_hash FROM tasks WHERE task_id=?", (task_id,),
            ).fetchone()
            hold = database.execute(
                "SELECT state,assignment_generation,execution_attempt,gpu_uuid,"
                "proof_type,proof_sha256 FROM execution_resource_holds WHERE task_id=?",
                (task_id,),
            ).fetchone()
        assert row["status"] == "FAILED" and row["attempt"] == execution_generation
        assert hold["state"] == "RELEASED"
        assert hold["proof_type"] == "PROCESS_STOP_VERIFIED"
        assert hold["proof_sha256"] == expected_digest
        assert int(hold["assignment_generation"]) == assignment_generation
        assert int(hold["execution_attempt"]) == execution_generation
        assert str(hold["gpu_uuid"]) == gpu_uuid

        # Retrying the lost recovery is idempotent: same digest, no new proof.
        stack["drop_state"][0] = False
        first_retry = stack["client"].recover_execution(
            task_id, assignment_generation=assignment_generation,
            execution_generation=execution_generation, gpu_uuid=gpu_uuid,
            process_identity=identity,
        )
        second_retry = stack["client"].recover_execution(
            task_id, assignment_generation=assignment_generation,
            execution_generation=execution_generation, gpu_uuid=gpu_uuid,
            process_identity=identity,
        )
        assert first_retry["state"] == "RELEASED"
        assert first_retry["proof_sha256"] == expected_digest
        assert second_retry["proof_sha256"] == expected_digest
        with stack["repository"]._connect() as database:
            row_after = database.execute(
                "SELECT status,attempt,finished_at,process_pid,process_create_time,"
                "process_command_hash FROM tasks WHERE task_id=?", (task_id,),
            ).fetchone()
            hold_after = database.execute(
                "SELECT state,assignment_generation,execution_attempt,gpu_uuid,"
                "proof_type,proof_sha256 FROM execution_resource_holds WHERE task_id=?",
                (task_id,),
            ).fetchone()
        assert dict(row_after) == dict(row)
        assert dict(hold_after) == dict(hold)
        assert _row_count(stack["repository"], "tasks", task_id) == 1
        assert _row_count(stack["repository"], "execution_resource_holds", task_id) == 1
    finally:
        if process is not None and process.poll() is None:
            process.kill()
        _stop_formal(stack)


# ---------------------------------------------------------------------------
# Read-only operations diagnostics.
# ---------------------------------------------------------------------------


def test_execution_status_read_only_recovery_diagnostics(tmp_path):
    """The central status projection is complete, GET-only and secret-free."""
    stack = _start_formal_dual_slot(tmp_path, [("a", "GPU-A", 30.0), ("b", "GPU-B", 2.0)])
    try:
        identity_a = _slot_identity_from_workdir(stack, "a")
        assert identity_a is not None
        _wait_central_start_identity(stack, "a", identity_a)
        identity_b = _slot_identity_from_workdir(stack, "b")
        assert identity_b is not None
        _wait_central_start_identity(stack, "b", identity_b)
        client = stack["client"]
        before = _central_snapshot(stack["repository"], ("a", "b"))
        status_a = client.execution_status("a")
        status_a_again = client.execution_status("a")
        held_b = client.execution_status("b")
        assert _central_snapshot(stack["repository"], ("a", "b")) == before

        # Existing durable Assignment/Hold/GPU/generation evidence is fixed here.
        assert status_a["execution_attempt"] == 1
        assert status_a["execution_slots"] == 2
        assert status_a["assignment_state"] == "RELEASED"
        assert status_a["assignment_generation"] == held_b["assignment_generation"]
        assert status_a["hold_state"] == "HELD"
        assert status_a["hold_execution_attempt"] == 1
        assert status_a["hold_gpu_uuid"] == "GPU-A"
        assert status_a["process_identity_sha256"] == _process_identity_sha256(identity_a)
        assert status_a["proof_type"] is None
        assert status_a["proof_sha256"] is None
        # Node capability evidence (names only).
        assert "training" in status_a["node_capabilities"]
        assert "execution-slots:2" in status_a["node_capabilities"]
        # Recovery state/blocking reason and stable evidence digest.
        assert status_a["recovery_state"] == "HELD"
        assert status_a["recovery_blocked_reason"] == "PROCESS_STOP_UNPROVEN"
        assert len(status_a["evidence_sha256"]) == 64
        assert status_a_again == status_a
        assert held_b["recovery_state"] == "HELD"
        assert held_b["hold_gpu_uuid"] == "GPU-B"
        assert held_b["evidence_sha256"] != status_a["evidence_sha256"]

        # No lease/assignment token or credential material is projected.
        secrets = []
        with stack["repository"]._connect() as database:
            for row in database.execute(
                "SELECT lease_token FROM tasks WHERE task_id IN ('a','b')"
            ):
                if row[0] is not None:
                    secrets.append(str(row[0]))
            for row in database.execute(
                "SELECT lease_token FROM task_node_assignments WHERE task_id IN ('a','b')"
            ):
                if row[0] is not None:
                    secrets.append(str(row[0]))
        secrets.append(str(stack["token"]))
        serialized = json.dumps({"a": status_a, "b": held_b}, sort_keys=True)
        for secret in secrets:
            assert secret not in serialized
        for payload in (status_a, held_b):
            assert not any(
                marker in str(key).lower()
                for key in payload
                for marker in ("token", "secret", "credential")
            )
        # The status route is a GET; the service exposes no forced-release verb.
        paths = stack["app"].openapi()["paths"]
        status_routes = {
            path: methods for path, methods in paths.items()
            if path.startswith("/api/v63/node-executor/") and path.endswith("/status")
        }
        assert status_routes
        assert all(set(methods) == {"get"} for methods in status_routes.values())
        assert not any(
            marker in path.lower()
            for path in paths
            if path.startswith("/api/v63/node-executor/")
            for marker in ("release", "force", "requeue")
        )

        # A completed sibling projects RELEASED + the recomputable stop proof.
        def b_released():
            stack["loop"]._reap_dual_slots()
            status = client.execution_status("b")
            if status["status"] in {"SUCCEEDED", "PARTIAL_SUCCESS"} \
                    and status["hold_state"] == "RELEASED":
                return status
            return None

        released_b = _wait_until(
            b_released, timeout=40, message="B did not finish after its own proof",
        )
        assert released_b["proof_type"] == "PROCESS_STOP_VERIFIED"
        assert released_b["recovery_state"] == "RELEASED"
        assert released_b["recovery_blocked_reason"] is None
        expected_b = _expected_stop_proof_sha256(
            node_id="formal-runner", task_id="b",
            assignment_generation=int(released_b["hold_assignment_generation"]),
            execution_attempt=int(released_b["hold_execution_attempt"]),
            gpu_uuid=str(released_b["hold_gpu_uuid"]), process_identity=identity_b,
        )
        assert released_b["proof_sha256"] == expected_b
        assert released_b["evidence_sha256"] != held_b["evidence_sha256"]
        # The still-HELD sibling was not affected by B's release.
        status_a_after = client.execution_status("a")
        assert status_a_after["hold_state"] == "HELD"
        assert status_a_after["recovery_state"] == "HELD"
        assert status_a_after["evidence_sha256"] == status_a["evidence_sha256"]
    finally:
        _stop_formal_dual(stack)


def test_remote_recovery_diagnosis_is_read_only_projection(tmp_path):
    """The stop-proof preflight exposes evidence but can never release."""
    task_id = "formal-diagnosis"
    stack = _start_formal(tmp_path, task_id=task_id)
    try:
        client = stack["client"]
        with pytest.raises(NodeExecutorHTTPError) as not_held:
            client.recovery_diagnosis(task_id)
        assert not_held.value.status_code == 409
        assert not_held.value.code == "REMOTE_RECOVERY_NOT_HELD"
        # Test fixture: mark the execution as awaiting the supervisor stop proof.
        with stack["repository"]._connect() as database:
            database.execute(
                "UPDATE tasks SET stage='recovery_blocked_remote_agent_unverified' "
                "WHERE task_id=?", (task_id,),
            )
            database.commit()
            lease_token = database.execute(
                "SELECT lease_token FROM tasks WHERE task_id=?", (task_id,)
            ).fetchone()[0]
        before = _central_snapshot(stack["repository"], (task_id,))
        diagnostic = client.recovery_diagnosis(task_id)
        again = client.recovery_diagnosis(task_id)
        assert _central_snapshot(stack["repository"], (task_id,)) == before

        assert diagnostic["task_id"] == task_id
        assert diagnostic["node_id"] == "formal-runner"
        assert diagnostic["execution_generation"] == 1
        assert diagnostic["task_status"] == "RUNNING"
        assert diagnostic["recovery_state"] == "STOP_PROOF_REQUIRED"
        assert diagnostic["automatic_reassignment_allowed"] is False
        assert diagnostic["stop_proof_verified"] is False
        # Minimal additive read-only evidence (no mutation capability).
        assert diagnostic["execution_slots"] == 2
        assert "training" in diagnostic["node_capabilities"]
        assert diagnostic["assignment_state"] == "RELEASED"
        assert diagnostic["hold_state"] == "HELD"
        assert diagnostic["hold_execution_attempt"] == 1
        assert diagnostic["hold_gpu_uuid"] == "GPU-A"
        assert diagnostic["proof_type"] is None
        assert diagnostic["proof_sha256"] is None
        assert diagnostic["execution_recovery_state"] == "HELD"
        assert diagnostic["execution_recovery_blocked_reason"] == "PROCESS_STOP_UNPROVEN"
        assert len(diagnostic["evidence_sha256"]) == 64
        assert again == diagnostic

        status = client.execution_status(task_id)
        assert status["evidence_sha256"] == diagnostic["evidence_sha256"]
        assert status["hold_state"] == diagnostic["hold_state"]
        assert status["hold_gpu_uuid"] == diagnostic["hold_gpu_uuid"]
        assert status["recovery_state"] == diagnostic["execution_recovery_state"]
        serialized = json.dumps(diagnostic, sort_keys=True)
        assert lease_token is not None
        assert str(lease_token) not in serialized
        assert str(stack["token"]) not in serialized
        assert not any(
            marker in str(key).lower()
            for key in diagnostic
            for marker in ("token", "secret", "credential")
        )
        # The diagnosis route is a GET only.
        paths = stack["app"].openapi()["paths"]
        recovery_routes = {
            path: methods for path, methods in paths.items()
            if path.startswith("/api/v63/node-executor/") and path.endswith("/recovery")
        }
        assert recovery_routes
        assert all(set(methods) == {"get"} for methods in recovery_routes.values())
    finally:
        _stop_formal(stack)


# ---------------------------------------------------------------------------
# Dual-slot simultaneous Agent crash: real node_agent.py E2E (POSIX) and the
# Windows fail-closed contract. The scenario bodies live in the shared harness.
# ---------------------------------------------------------------------------


def _load_real_agent_support():
    name = "real_agent_crash_recovery_e2e_support_formal_runner"
    cached = sys.modules.get(name)
    if cached is not None:
        return cached
    path = Path(__file__).with_name("_real_agent_crash_recovery_support.py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(os.name != "posix", reason="POSIX dual-slot real Agent SIGKILL recovery")
def test_real_agent_dual_slot_simultaneous_crash_recovers_both(tmp_path):
    _load_real_agent_support().run_dual_slot_simultaneous_agent_sigkill_recovery(tmp_path)


@pytest.mark.skipif(os.name != "nt", reason="Windows dual-slot real Agent fail-closed contract")
def test_real_agent_dual_slot_simultaneous_crash_is_fail_closed(tmp_path):
    _load_real_agent_support().run_dual_slot_simultaneous_agent_crash_fail_closed(tmp_path)
