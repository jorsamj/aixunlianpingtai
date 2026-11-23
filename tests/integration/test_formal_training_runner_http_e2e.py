from __future__ import annotations

import importlib.util
import socket
import sys
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from platform_core.agent_execution import AgentExecutionService, agent_executor_router
from platform_core.node_agent_executor_runtime import NodeExecutorClient, RemoteExecutionFenced
from platform_core.node_agent_training_runtime import AgentTrainingRuntimeError
from platform_core.service_nodes import ServiceNodeRepository
from platform_core.task_runtime import ArtifactStore, TaskKind, TaskRecord, TaskRepository


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


UPLOADED_MODELS: list[dict] = []


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
            for item in UPLOADED_MODELS
        ],
    }}


def _model_preparer(_task, _payload, *, execution_generation, models):
    UPLOADED_MODELS[:] = [dict(item) for item in models]
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
                  drop_response_path=None):
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
        "drop_state": drop_state,
    }


def _stop_formal(stack):
    stack["server"].should_exit = True
    stack["thread"].join(timeout=10)
    stack["runner"].request_shutdown()


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


def test_formal_training_runner_http_success(tmp_path):
    stack = _start_formal(tmp_path)
    try:
        outcome = stack["runner"].run(stack["lease"])
        assert outcome.status == "SUCCEEDED"
        task = stack["repository"].get("formal-1")
        assert task.status.value == "SUCCEEDED"
        with stack["repository"]._connect() as database:
            hold = database.execute(
                "SELECT state,proof_sha256 FROM execution_resource_holds WHERE task_id='formal-1'"
            ).fetchone()
        assert hold is not None and hold["state"] == "RELEASED" and hold["proof_sha256"]
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
                "SELECT state FROM execution_resource_holds WHERE task_id='formal-preflight'"
            ).fetchone()
        assert hold is not None and hold["state"] == "RELEASED"
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
