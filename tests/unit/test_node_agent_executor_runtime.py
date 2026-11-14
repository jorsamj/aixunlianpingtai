from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
import requests

from platform_core.node_agent_executor_runtime import (
    AgentExecutionWorkdir,
    ExecutionLeaseMonitor,
    NodeExecutorClient,
    NodeExecutorHTTPError,
    RemoteExecutionFenced,
    RemoteExecutionLease,
)
from platform_core.task_runtime.process_control import ProcessIdentity


class FakeResponse:
    def __init__(self, status_code=200, body=None, *, invalid_json=False):
        self.status_code = int(status_code)
        self.ok = 200 <= self.status_code < 400
        self.body = body
        self.invalid_json = invalid_json

    def json(self):
        if self.invalid_json:
            raise ValueError("not json")
        return self.body


class ScriptedSession:
    def __init__(self, *items):
        self.items = list(items)
        self.calls = []

    def post(self, url, *, headers, json, timeout):
        self.calls.append({
            "url": url,
            "headers": dict(headers),
            "json": dict(json),
            "timeout": timeout,
        })
        if not self.items:
            raise AssertionError("unexpected HTTP request")
        item = self.items.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def start_body(task_id="task-1", generation=1):
    return {
        "task": {
            "task_id": task_id,
            "project_id": "project-1",
            "kind": "DEPLOYMENT_TEST",
            "status": "RUNNING",
        },
        "execution": {
            "lease_token": "execution-secret",
            "generation": generation,
            "lease_expires_at": "2026-09-18T00:00:30+00:00",
            "worker_id": "agent:node:1",
        },
        "assignment": {
            "generation": 3,
            "capability": "deployment-test",
            "resolved_execution_config": {"selected_device": "cuda:0"},
        },
        "payload": {"conf": 0.25, "source": "portable"},
        "transport": {
            "protocol": "agent-http-control-v1",
            "shared_sqlite_required": False,
            "shared_nfs_required": False,
        },
    }


def lease(task_id="task-1", generation=1):
    return RemoteExecutionLease.from_start_response(start_body(task_id, generation))


def test_executor_client_uses_only_http_control_contract_and_bearer_node_token():
    session = ScriptedSession(
        FakeResponse(200, {
            "claimed": True,
            "item": {
                "assignment": {
                    "task_id": "task-1",
                    "assignment_lease_token": "assignment-secret",
                },
                "task": {"task_id": "task-1", "kind": "DEPLOYMENT_TEST"},
            },
        }),
        FakeResponse(200, start_body()),
        FakeResponse(200, {"task": {"progress": 25}, "cancel_requested": False}),
        FakeResponse(200, {"ok": True, "bytes": 8}),
        FakeResponse(200, {
            "already_uploaded": False,
            "confirmed": False,
            "sha256": "a" * 64,
            "size_bytes": 123,
            "storage_ref": {"object_key": "results/generation-1/result.jpg"},
            "upload": {
                "method": "PUT",
                "url": "https://signed.example.test/result",
                "headers": {"Content-Length": "123", "x-amz-meta-sha256": "a" * 64},
            },
        }),
        FakeResponse(200, {
            "confirmed": True,
            "result_ref": "remote-results/1/result.json",
            "result": {"output_sha256": "a" * 64},
        }),
        FakeResponse(200, {"task": {"stage": "finalizing_commit"}}),
        FakeResponse(200, {"task": {"status": "SUCCEEDED"}}),
    )
    client = NodeExecutorClient(
        "https://control.example.test/",
        "node:1",
        "node-secret",
        session=session,
        timeout=7,
    )

    claimed = client.claim_assignment()
    assert claimed["assignment"]["assignment_lease_token"] == "assignment-secret"
    current = client.start_execution("task-1", "assignment-secret")
    heartbeat = client.heartbeat(
        current,
        progress=25,
        stage="running",
        resource_resolution={
            "resource_strategy": "auto",
            "resolved_batch": 32,
            "resolved_workers": 4,
            "resolved_cache": False,
            "node_id": "node:1",
            "execution_generation": 1,
            "assigned_device": "cuda:0",
            "gpu_uuid": "GPU-node-1",
        },
    )
    logged = client.append_log(current, "hello\n")
    prepared = client.prepare_result_upload(current, sha256="a" * 64, size_bytes=123)
    confirmed = client.confirm_result_upload(
        current,
        runtime_result={
            "engine": "ultralytics",
            "inference_ms": 12.5,
            "detections": [{"class_id": 0, "label": "person", "confidence": 0.9}],
        },
    )
    finalizing = client.begin_finalization(current)
    finished = client.finish(current, "SUCCEEDED", result_ref="result.json")

    assert heartbeat["cancel_requested"] is False
    assert logged["ok"] is True
    assert prepared["upload"]["method"] == "PUT"
    assert confirmed["result_ref"] == "remote-results/1/result.json"
    assert finalizing["task"]["stage"] == "finalizing_commit"
    assert finished["task"]["status"] == "SUCCEEDED"
    assert all(call["headers"] == {"Authorization": "Bearer node-secret"} for call in session.calls)
    assert all(call["timeout"] == 7 for index, call in enumerate(session.calls) if index != 5)
    assert session.calls[5]["timeout"] == 300.0
    assert session.calls[0]["url"].endswith("/api/v63/node-executor/node%3A1/assignments/claim")
    assert session.calls[1]["url"].endswith("/assignments/task-1/start")
    assert session.calls[2]["json"]["execution_generation"] == 1
    assert session.calls[2]["json"]["execution_lease_token"] == "execution-secret"
    assert session.calls[2]["json"]["resource_resolution"]["resolved_batch"] == 32
    assert session.calls[4]["url"].endswith("/executions/task-1/result-upload/prepare")
    assert session.calls[4]["json"]["sha256"] == "a" * 64
    assert session.calls[4]["json"]["size_bytes"] == 123
    assert session.calls[5]["url"].endswith("/executions/task-1/result-upload/confirm")
    assert session.calls[5]["json"]["runtime_result"]["engine"] == "ultralytics"


def test_executor_client_heartbeat_projects_live_training_runtime_resources():
    current = lease("train-runtime", generation=7)
    session = ScriptedSession(
        FakeResponse(200, {"task": {"progress": 5}, "cancel_requested": False}),
    )
    client = NodeExecutorClient(
        "https://control.example.test",
        "node:1",
        "node-secret",
        session=session,
        timeout=7,
    )
    runtime_resources = {
        "node_id": "node:1",
        "execution_generation": 7,
        "actual_device": "cuda:0",
        "actual_batch": 32,
        "actual_workers": 4,
        "actual_cache": False,
        "actual_precision": "fp16",
        "runtime_batch": 32,
        "runtime_workers": 4,
        "runtime_cache": False,
    }

    body = client.heartbeat(current, runtime_resources=runtime_resources)

    assert body["cancel_requested"] is False
    assert session.calls[0]["json"]["runtime_resources"] == runtime_resources
    assert session.calls[0]["json"]["execution_generation"] == 7
    assert session.calls[0]["json"]["execution_lease_token"] == "execution-secret"


def test_executor_client_uses_fenced_training_model_upload_routes():
    current = lease("train-one", generation=4)
    current = RemoteExecutionLease(
        task_id=current.task_id,
        kind="TRAINING",
        project_id=current.project_id,
        generation=current.generation,
        lease_token=current.lease_token,
        lease_expires_at=current.lease_expires_at,
        worker_id=current.worker_id,
        payload={},
        assignment={},
        transport={},
    )
    prepared_body = {
        "version_id": "rt123",
        "execution_generation": 4,
        "items": [{
            "role": "best",
            "file_name": "best.pt",
            "sha256": "b" * 64,
            "size_bytes": 456,
            "artifact_id": "artifact-best",
            "storage_ref": {
                "storage_source_id": "s3-main",
                "object_key": "model-assets/rt123/best.pt",
                "file_name": "best.pt",
                "content_type": "application/octet-stream",
            },
            "already_uploaded": False,
            "upload": {
                "method": "PUT",
                "url": "https://signed.example.test/best",
                "headers": {
                    "Content-Length": "456",
                    "x-amz-meta-sha256": "b" * 64,
                    "If-None-Match": "*",
                },
            },
        }],
    }
    confirmed_body = {
        "confirmed": True,
        "version_id": "rt123",
        "items": [prepared_body["items"][0] | {"upload": None, "already_uploaded": True}],
    }
    session = ScriptedSession(
        FakeResponse(200, prepared_body),
        FakeResponse(200, confirmed_body),
    )
    client = NodeExecutorClient(
        "https://control.example.test",
        "node:1",
        "node-secret",
        session=session,
        timeout=7,
    )

    prepared = client.prepare_training_model_uploads(
        current,
        [{
            "role": "best",
            "file_name": "best.pt",
            "sha256": "b" * 64,
            "size_bytes": 456,
        }],
    )
    confirmed = client.confirm_training_model_uploads(current)

    assert prepared["version_id"] == "rt123"
    assert confirmed["confirmed"] is True
    assert session.calls[0]["url"].endswith(
        "/executions/train-one/training-models/prepare"
    )
    assert session.calls[0]["json"]["execution_generation"] == 4
    assert session.calls[0]["json"]["models"][0]["sha256"] == "b" * 64
    assert session.calls[1]["url"].endswith(
        "/executions/train-one/training-models/confirm"
    )
    assert session.calls[1]["json"] == {
        "execution_lease_token": "execution-secret",
        "execution_generation": 4,
    }
    assert [call["timeout"] for call in session.calls] == [7, 7]


def test_executor_client_fails_closed_on_successful_non_json_response():
    session = ScriptedSession(FakeResponse(200, invalid_json=True))
    client = NodeExecutorClient(
        "https://control.example.test",
        "node-1",
        "node-secret",
        session=session,
    )
    with pytest.raises(NodeExecutorHTTPError) as invalid:
        client.claim_assignment()
    assert invalid.value.code == "NODE_EXECUTOR_INVALID_RESPONSE"
    assert invalid.value.status_code == 200


def test_executor_client_maps_structured_server_error_and_transport_failure():
    denied = ScriptedSession(FakeResponse(409, {
        "detail": {"code": "EXECUTION_FENCED", "message": "stale generation"}
    }))
    client = NodeExecutorClient(
        "https://control.example.test",
        "node-1",
        "node-secret",
        session=denied,
    )
    with pytest.raises(NodeExecutorHTTPError) as fenced:
        client.claim_assignment()
    assert fenced.value.code == "EXECUTION_FENCED"
    assert fenced.value.status_code == 409
    assert fenced.value.retryable is False

    broken = ScriptedSession(requests.ConnectionError("network down"))
    client = NodeExecutorClient(
        "https://control.example.test",
        "node-1",
        "node-secret",
        session=broken,
    )
    with pytest.raises(NodeExecutorHTTPError) as transport:
        client.claim_assignment()
    assert transport.value.code == "NODE_EXECUTOR_TRANSPORT_FAILED"
    assert transport.value.retryable is True


@pytest.mark.parametrize("url", [
    "",
    "control.example.test",
    "file:///tmp/control",
    "https://user:secret@control.example.test",
])
def test_executor_client_rejects_unsafe_control_plane_urls(url):
    with pytest.raises(ValueError):
        NodeExecutorClient(url, "node-1", "secret")


def test_start_response_rejects_unsafe_task_identity():
    body = start_body("../escape")
    with pytest.raises(ValueError):
        RemoteExecutionLease.from_start_response(body)


def test_workdir_is_task_local_atomic_and_does_not_persist_execution_secret(tmp_path):
    current = lease()
    workdirs = AgentExecutionWorkdir(tmp_path / "agent-state")
    target = workdirs.prepare(current)

    assert target == (tmp_path / "agent-state" / "executions" / "task-1" / "1").resolve()
    persisted_request = json.loads((target / "request.json").read_text(encoding="utf-8"))
    assert persisted_request == current.payload
    metadata = json.loads((target / "execution.json").read_text(encoding="utf-8"))
    assert metadata["task_id"] == "task-1"
    assert metadata["generation"] == 1
    serialized = (target / "execution.json").read_text(encoding="utf-8")
    assert current.lease_token not in serialized
    assert "node-secret" not in serialized
    assert "assignment-secret" not in serialized

    workdirs.cleanup(current)
    assert not target.exists()


def test_workdir_persists_only_exact_nonsecret_process_identity_for_recovery(tmp_path):
    current = lease()
    workdirs = AgentExecutionWorkdir(tmp_path / "agent-state")
    target = workdirs.prepare(current)
    identity = ProcessIdentity(
        pid=4321,
        create_time=12345.5,
        command_hash="a" * 64,
    )

    path = workdirs.persist_process_identity(current, identity)
    persisted = json.loads(path.read_text(encoding="utf-8"))

    assert persisted == {
        "task_id": current.task_id,
        "generation": current.generation,
        "pid": 4321,
        "create_time": 12345.5,
        "command_hash": "a" * 64,
    }
    assert workdirs.read_process_identity(current) == {
        "pid": 4321,
        "create_time": 12345.5,
        "command_hash": "a" * 64,
    }
    assert workdirs.list_process_identities() == [{
        "task_id": current.task_id,
        "generation": current.generation,
        "pid": 4321,
        "create_time": 12345.5,
        "command_hash": "a" * 64,
    }]
    serialized = path.read_text(encoding="utf-8")
    assert current.lease_token not in serialized
    assert "node-secret" not in serialized
    assert "assignment-secret" not in serialized

    workdirs.clear_process_identity(current)
    assert not path.exists()
    workdirs.cleanup(current)
    assert not target.exists()


def test_workdir_never_persists_signed_transport_urls_or_headers(tmp_path):
    body = start_body()
    body["payload"] = {
        "input": {
            "download": {
                "method": "GET",
                "url": "https://signed.example.test/input?secret=temporary",
                "headers": {"Authorization": "Bearer storage-secret", "X-Signed": "yes"},
                "size_bytes": 10,
                "sha256": "a" * 64,
            }
        },
        "output": {
            "storage_ref": {"object_key": "results/result.jpg"},
            "upload_protocol": "prepare-after-local-hash-v1",
        },
    }
    current = RemoteExecutionLease.from_start_response(body)
    target = AgentExecutionWorkdir(tmp_path / "agent-state").prepare(current)
    persisted = json.loads((target / "request.json").read_text(encoding="utf-8"))

    serialized = json.dumps(persisted, ensure_ascii=False)
    assert "signed.example.test" not in serialized
    assert "storage-secret" not in serialized
    assert "temporary" not in serialized
    assert persisted["input"]["download"]["header_names"] == ["Authorization", "X-Signed"]
    assert persisted["input"]["download"]["size_bytes"] == 10
    assert persisted["output"]["upload_protocol"] == "prepare-after-local-hash-v1"


def test_workdir_rejects_preexisting_symlink_escape_when_supported(tmp_path):
    state = tmp_path / "agent-state"
    workdirs = AgentExecutionWorkdir(state)
    executions = state / "executions"
    executions.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    task_link = executions / "task-1"
    try:
        task_link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("platform does not permit test symlink creation")

    with pytest.raises(ValueError, match="unsafe path component"):
        workdirs.prepare(lease())


class FakeHeartbeatClient:
    def __init__(self, *items):
        self.items = list(items)
        self.calls = 0

    def heartbeat(self, _lease, **_kwargs):
        self.calls += 1
        item = self.items.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def test_lease_monitor_observes_cancel_without_falsely_marking_fenced():
    client = FakeHeartbeatClient({"cancel_requested": True, "task": {"status": "CANCEL_REQUESTED"}})
    monitor = ExecutionLeaseMonitor(client, lease())

    body = monitor.beat(progress=10)
    assert body["cancel_requested"] is True
    assert monitor.cancel_requested.is_set()
    assert not monitor.fenced.is_set()
    with pytest.raises(InterruptedError):
        monitor.assert_active()


def test_lease_monitor_fails_closed_on_any_unproven_renewal_and_runs_cleanup_callback():
    calls = []
    client = FakeHeartbeatClient(
        NodeExecutorHTTPError(
            "NODE_EXECUTOR_TRANSPORT_FAILED",
            "timeout",
            retryable=True,
        )
    )
    monitor = ExecutionLeaseMonitor(client, lease(), on_fenced=lambda: calls.append("terminate"))

    with pytest.raises(RemoteExecutionFenced):
        monitor.beat()
    assert monitor.fenced.is_set()
    assert calls == ["terminate"]
    with pytest.raises(RemoteExecutionFenced):
        monitor.assert_active()


def test_agent_executor_runtime_has_no_control_plane_database_imports():
    source_path = Path(__file__).resolve().parents[2] / "platform_core" / "node_agent_executor_runtime.py"
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden_modules = {
        "sqlite3",
        "platform_core.task_runtime.repository",
        "platform_core.task_node_assignments",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not any(alias.name in forbidden_modules for alias in node.names)
        if isinstance(node, ast.ImportFrom):
            assert str(node.module or "") not in forbidden_modules
    assert "tasks.sqlite3" not in source


def test_executor_client_uses_fenced_clean_selection_routes():
    current = lease("clean-one", generation=3)
    current = RemoteExecutionLease(
        task_id=current.task_id,
        kind="MATERIAL_BATCH",
        project_id=current.project_id,
        generation=current.generation,
        lease_token=current.lease_token,
        lease_expires_at=current.lease_expires_at,
        worker_id=current.worker_id,
        payload={},
        assignment={},
        transport={},
    )
    session = ScriptedSession(
        FakeResponse(200, {"items": [{"image_id": "img-1"}], "next_cursor": None, "total": 1}),
        FakeResponse(200, {
            "image_id": "img-1",
            "source": {"image_id": "img-1"},
            "download": {"method": "GET", "url": "https://objects.example.test/img-1.jpg"},
        }),
    )
    client = NodeExecutorClient(
        "https://control.example.test",
        "node:1",
        "node-secret",
        session=session,
        timeout=7,
    )

    page = client.clean_selection_page(current, cursor="img-0", limit=250)
    read = client.clean_selection_read(current, "img-1")

    assert page["total"] == 1
    assert read["image_id"] == "img-1"
    assert session.calls[0]["url"].endswith("/executions/clean-one/clean-selection/page")
    assert session.calls[0]["json"] == {
        "execution_lease_token": current.lease_token,
        "execution_generation": 3,
        "limit": 250,
        "cursor": "img-0",
    }
    assert session.calls[1]["url"].endswith("/executions/clean-one/clean-selection/read")
    assert session.calls[1]["json"]["image_id"] == "img-1"


class ReadOnlyScriptedSession(ScriptedSession):
    def get(self, url, *, headers, timeout):
        self.calls.append({
            "method": "GET", "url": url,
            "headers": dict(headers), "timeout": timeout,
        })
        if not self.items:
            raise AssertionError("unexpected recovery GET request")
        item = self.items.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def _safe_recovery_diagnosis(**overrides):
    body = {
        "task_id": "task-1",
        "node_id": "node:1",
        "execution_generation": 3,
        "task_status": "CANCEL_REQUESTED",
        "recovery_state": "STOP_PROOF_REQUIRED",
        "automatic_reassignment_allowed": False,
        "stop_proof_verified": False,
        "resource_wait_reason": "REMOTE_AGENT_STOP_UNVERIFIED",
    }
    body.update(overrides)
    return body


def test_executor_client_recovery_diagnosis_is_get_only_and_fails_closed():
    session = ReadOnlyScriptedSession(FakeResponse(200, _safe_recovery_diagnosis()))
    client = NodeExecutorClient(
        "https://control.example.test", "node:1", "node-secret",
        session=session, timeout=7,
    )
    result = client.recovery_diagnosis("task-1")
    assert result["execution_generation"] == 3
    assert result["recovery_state"] == "STOP_PROOF_REQUIRED"
    assert result["automatic_reassignment_allowed"] is False
    assert result["stop_proof_verified"] is False
    assert session.calls == [{
        "method": "GET",
        "url": "https://control.example.test/api/v63/node-executor/node%3A1/executions/task-1/recovery",
        "headers": {"Authorization": "Bearer node-secret"},
        "timeout": 7,
    }]


@pytest.mark.parametrize("bad_body", [
    {"stop_proof_verified": True},
    {"automatic_reassignment_allowed": True},
    {"recovery_state": "PROVEN_STOPPED"},
    {"execution_generation": 0},
    {"execution_generation": "3"},
    {"node_id": "other-node"},
    {"task_id": "other-task"},
    {"task_status": "SUCCEEDED"},
])
def test_executor_client_recovery_diagnosis_rejects_misleading_success(bad_body):
    valid = _safe_recovery_diagnosis()
    valid.update(bad_body)
    session = ReadOnlyScriptedSession(FakeResponse(200, valid))
    client = NodeExecutorClient(
        "https://control.example.test", "node:1", "node-secret", session=session,
    )
    with pytest.raises(NodeExecutorHTTPError) as error:
        client.recovery_diagnosis("task-1")
    assert error.value.code == "NODE_EXECUTOR_INVALID_RESPONSE"


def test_executor_client_recovery_diagnosis_requires_an_object_response():
    session = ReadOnlyScriptedSession(FakeResponse(200, {}))
    client = NodeExecutorClient(
        "https://control.example.test", "node:1", "node-secret", session=session,
    )
    with pytest.raises(NodeExecutorHTTPError) as error:
        client.recovery_diagnosis("task-1")
    assert error.value.code == "NODE_EXECUTOR_INVALID_RESPONSE"


def test_executor_client_recovery_diagnosis_rejects_auth_and_transport_failures():
    denied = ReadOnlyScriptedSession(FakeResponse(404, {
        "detail": {"code": "TASK_NOT_FOUND", "message": "not owned by node"},
    }))
    client = NodeExecutorClient(
        "https://control.example.test", "node:1", "node-secret", session=denied,
    )
    with pytest.raises(NodeExecutorHTTPError) as denied_error:
        client.recovery_diagnosis("task-1")
    assert denied_error.value.code == "TASK_NOT_FOUND"
    assert denied_error.value.retryable is False

    disconnected = ReadOnlyScriptedSession(requests.ConnectionError("partition"))
    client = NodeExecutorClient(
        "https://control.example.test", "node:1", "node-secret",
        session=disconnected,
    )
    with pytest.raises(NodeExecutorHTTPError) as connection_error:
        client.recovery_diagnosis("task-1")
    assert connection_error.value.code == "NODE_EXECUTOR_TRANSPORT_FAILED"
    assert connection_error.value.retryable is True

    malformed = ReadOnlyScriptedSession(FakeResponse(200, invalid_json=True))
    client = NodeExecutorClient(
        "https://control.example.test", "node:1", "node-secret",
        session=malformed,
    )
    with pytest.raises(NodeExecutorHTTPError) as parse_error:
        client.recovery_diagnosis("task-1")
    assert parse_error.value.code == "NODE_EXECUTOR_INVALID_RESPONSE"


def test_launch_intent_is_pre_spawn_hazard_and_blocks_unverified_cleanup(tmp_path):
    body = start_body()
    body["task"]["kind"] = "TRAINING"
    current = RemoteExecutionLease.from_start_response(body)
    workdirs = AgentExecutionWorkdir(tmp_path / "state")
    workdirs.prepare(current)

    marker = workdirs.begin_process_launch(current)
    item = json.loads(marker.read_text(encoding="utf-8"))
    assert item == {
        "task_id": current.task_id,
        "generation": current.generation,
        "kind": "TRAINING",
    }
    assert workdirs.list_unverified_process_launch_intents("TRAINING") == [item]
    assert workdirs.list_unverified_process_launch_intents("MODEL_CONVERSION") == []
    assert current.lease_token not in marker.read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="unverified process launch"):
        workdirs.cleanup(current)

    identity = ProcessIdentity(pid=4321, create_time=12345.5, command_hash="a" * 64)
    workdirs.persist_process_identity(current, identity)
    assert workdirs.list_unverified_process_launch_intents("TRAINING") == []
    with pytest.raises(ValueError, match="unverified process launch"):
        workdirs.cleanup(current)
    workdirs.clear_process_identity(current)
    assert not marker.exists()
    workdirs.cleanup(current)


def test_launch_intent_lineage_tampering_is_rejected_not_ignored(tmp_path):
    body = start_body()
    body["task"]["kind"] = "MODEL_CONVERSION"
    current = RemoteExecutionLease.from_start_response(body)
    workdirs = AgentExecutionWorkdir(tmp_path / "state")
    workdirs.prepare(current)
    marker = workdirs.begin_process_launch(current)
    marker.write_text(json.dumps({
        "task_id": current.task_id,
        "generation": current.generation + 1,
        "kind": "MODEL_CONVERSION",
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="lineage mismatch"):
        workdirs.list_unverified_process_launch_intents("MODEL_CONVERSION")
    assert marker.exists()

def test_unverified_launch_intent_shared_across_training_and_conversion(tmp_path):
    body = start_body("training-hazard")
    body["task"]["kind"] = "TRAINING"
    current = RemoteExecutionLease.from_start_response(body)
    workdirs = AgentExecutionWorkdir(tmp_path / "shared-agent-state")
    workdirs.prepare(current)
    marker = workdirs.begin_process_launch(current)

    all_hazards = workdirs.list_unverified_process_launch_intents()
    assert all_hazards == [{
        "task_id": current.task_id,
        "generation": current.generation,
        "kind": "TRAINING",
    }]
    assert workdirs.list_unverified_process_launch_intents("MODEL_CONVERSION") == []
    assert workdirs.list_unverified_process_launch_intents("TRAINING") == all_hazards
    assert marker.is_file()

@pytest.mark.parametrize("bad_created", [float("nan"), float("inf"), float("-inf"), "NaN", "Infinity"])
def test_process_identity_rejects_nonfinite_create_time_without_dropping_evidence(
    tmp_path, bad_created,
):
    current = lease()
    workdirs = AgentExecutionWorkdir(tmp_path / "agent-state")
    target = workdirs.prepare(current)
    with pytest.raises(ValueError, match="incomplete"):
        workdirs.persist_process_identity(
            current,
            ProcessIdentity(
                pid=4321, create_time=bad_created, command_hash="a" * 64,
            ),
        )
    path = target / "process-identity.json"
    assert not path.exists()

    # Malformed data may originate from an interrupted or tampered file,
    # not only from the writer. Both recovery read paths must fail closed.
    path.write_text(json.dumps({
        "task_id": current.task_id,
        "generation": current.generation,
        "pid": 4321,
        "create_time": bad_created,
        "command_hash": "a" * 64,
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="incomplete"):
        workdirs.read_process_identity(current)
    with pytest.raises(ValueError, match="incomplete"):
        workdirs.list_process_identities()
    assert path.exists()
