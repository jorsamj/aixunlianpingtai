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
    heartbeat = client.heartbeat(current, progress=25, stage="running")
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
    assert all(call["timeout"] == 7 for call in session.calls)
    assert session.calls[0]["url"].endswith("/api/v63/node-executor/node%3A1/assignments/claim")
    assert session.calls[1]["url"].endswith("/assignments/task-1/start")
    assert session.calls[2]["json"]["execution_generation"] == 1
    assert session.calls[2]["json"]["execution_lease_token"] == "execution-secret"
    assert session.calls[4]["url"].endswith("/executions/task-1/result-upload/prepare")
    assert session.calls[4]["json"]["sha256"] == "a" * 64
    assert session.calls[4]["json"]["size_bytes"] == 123
    assert session.calls[5]["url"].endswith("/executions/task-1/result-upload/confirm")
    assert session.calls[5]["json"]["runtime_result"]["engine"] == "ultralytics"


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
