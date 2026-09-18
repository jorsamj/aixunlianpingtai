from __future__ import annotations

import hashlib
import json
import sys
import threading
import time
from pathlib import Path

import pytest
import requests

from platform_core.node_agent_deployment_runtime import (
    AgentDeploymentRunner,
    AgentDeploymentRuntimeError,
)
from platform_core.node_agent_executor_runtime import (
    AgentExecutionWorkdir,
    NodeExecutorHTTPError,
    RemoteExecutionFenced,
    RemoteExecutionLease,
)


class FakeResponse:
    def __init__(self, status_code=200, data=b"", headers=None):
        self.status_code = int(status_code)
        self.data = bytes(data)
        self.headers = dict(headers or {})

    def iter_content(self, chunk_size=1024 * 1024):
        for index in range(0, len(self.data), int(chunk_size)):
            yield self.data[index:index + int(chunk_size)]

    def close(self):
        return None


class FakeTransferSession:
    def __init__(self, downloads=None, *, fail_first_put_after_body=False):
        self.downloads = dict(downloads or {})
        self.fail_first_put_after_body = bool(fail_first_put_after_body)
        self.get_calls = []
        self.put_calls = []
        self.uploaded = {}

    def get(self, url, *, headers, stream, timeout, allow_redirects):
        self.get_calls.append({
            "url": url,
            "headers": dict(headers),
            "stream": stream,
            "timeout": timeout,
            "allow_redirects": allow_redirects,
        })
        data = self.downloads[url]
        return FakeResponse(
            200,
            data,
            {"Content-Length": str(len(data))},
        )

    def put(self, url, *, headers, data, timeout, allow_redirects):
        body = b"".join(data)
        self.put_calls.append({
            "url": url,
            "headers": dict(headers),
            "body": body,
            "timeout": timeout,
            "allow_redirects": allow_redirects,
        })
        self.uploaded[url] = body
        if self.fail_first_put_after_body and len(self.put_calls) == 1:
            raise requests.ConnectionError("response lost after object accepted")
        return FakeResponse(200)


class FakeControlClient:
    def __init__(self, transfer=None, *, cancel_at_heartbeat=None, fence_at_heartbeat=None):
        self.transfer = transfer
        self.cancel_at_heartbeat = cancel_at_heartbeat
        self.fence_at_heartbeat = fence_at_heartbeat
        self.heartbeat_calls = 0
        self.logs = []
        self.prepare_calls = []
        self.confirm_calls = []
        self.begin_calls = 0
        self.finish_calls = []

    def heartbeat(self, _lease, **kwargs):
        self.heartbeat_calls += 1
        if self.fence_at_heartbeat and self.heartbeat_calls >= self.fence_at_heartbeat:
            raise NodeExecutorHTTPError(
                "EXECUTION_FENCED",
                "generation lost",
                status_code=409,
            )
        cancelled = bool(
            self.cancel_at_heartbeat
            and self.heartbeat_calls >= self.cancel_at_heartbeat
        )
        return {
            "cancel_requested": cancelled,
            "task": {
                "status": "CANCEL_REQUESTED" if cancelled else "RUNNING",
                "progress": kwargs.get("progress"),
                "stage": kwargs.get("stage"),
            },
        }

    def append_log(self, _lease, text):
        self.logs.append(str(text))
        return {"ok": True, "bytes": len(str(text).encode("utf-8"))}

    def prepare_result_upload(self, lease, *, sha256, size_bytes):
        self.prepare_calls.append({
            "generation": lease.generation,
            "sha256": sha256,
            "size_bytes": int(size_bytes),
        })
        if (
            self.transfer is not None
            and self.transfer.fail_first_put_after_body
            and self.transfer.put_calls
        ):
            return {
                "already_uploaded": True,
                "confirmed": False,
                "sha256": sha256,
                "size_bytes": int(size_bytes),
                "storage_ref": {
                    "storage_source_id": "s3-main",
                    "object_key": f"results/generation-{lease.generation}/result.jpg",
                    "file_name": "result.jpg",
                    "content_type": "image/jpeg",
                },
                "upload": None,
            }
        return {
            "already_uploaded": False,
            "confirmed": False,
            "sha256": sha256,
            "size_bytes": int(size_bytes),
            "storage_ref": {
                "storage_source_id": "s3-main",
                "object_key": f"results/generation-{lease.generation}/result.jpg",
                "file_name": "result.jpg",
                "content_type": "image/jpeg",
            },
            "upload": {
                "method": "PUT",
                "url": "https://storage.example.test/result",
                "headers": {
                    "Content-Type": "image/jpeg",
                    "Content-Length": str(int(size_bytes)),
                    "x-amz-meta-sha256": sha256,
                    "If-None-Match": "*",
                },
                "overwrite_protected": True,
            },
        }

    def confirm_result_upload(self, lease, *, runtime_result=None):
        self.confirm_calls.append(dict(runtime_result or {}))
        return {
            "confirmed": True,
            "result_ref": f"remote-results/{lease.generation}/result.json",
            "result": {
                **dict(runtime_result or {}),
                "execution_generation": lease.generation,
            },
        }

    def begin_finalization(self, _lease):
        self.begin_calls += 1
        return {"task": {"stage": "finalizing_commit"}}

    def finish(self, lease, status, *, result_ref=None, error=None, accepted=None):
        self.finish_calls.append({
            "generation": lease.generation,
            "status": status,
            "result_ref": result_ref,
            "error": error,
            "accepted": accepted,
        })
        return {"task": {"status": status}}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _download(url: str, name: str, data: bytes, *, sha256=None, size_bytes=None):
    return {
        "method": "GET",
        "url": url,
        "headers": {},
        "expires_seconds": 900,
        "file_name": name,
        "size_bytes": len(data) if size_bytes is None else size_bytes,
        "sha256": _sha(data) if sha256 is None else sha256,
        "content_type": "application/octet-stream",
    }


def lease(input_data=b"input-image", *, model=None, generation=1, selected_device=""):
    input_url = "https://storage.example.test/input"
    payload = {
        "schema_version": 1,
        "task_kind": "DEPLOYMENT_TEST",
        "transport": "object-storage-v1",
        "framework": "ultralytics",
        "runtime_format": "pt",
        "confidence": 0.25,
        "selected_device": selected_device,
        "input": {
            "type": "object",
            "download": _download(input_url, "input.jpg", input_data),
        },
        "model": model or {"type": "official", "reference": "yolo11n.pt"},
        "output": {
            "type": "object",
            "storage_ref": {
                "storage_source_id": "s3-main",
                "object_key": "results/result.jpg",
                "file_name": "result.jpg",
                "content_type": "image/jpeg",
            },
            "upload_protocol": "prepare-after-local-hash-v1",
        },
    }
    current = RemoteExecutionLease(
        task_id="deploy-task",
        kind="DEPLOYMENT_TEST",
        project_id="project-1",
        generation=generation,
        lease_token="execution-secret",
        lease_expires_at="2026-09-18T10:00:00+00:00",
        worker_id="agent:node-1",
        payload=payload,
        assignment={},
        transport={"shared_sqlite_required": False, "shared_nfs_required": False},
    )
    return current, {input_url: input_data}


def write_runner(runtime_root: Path, *, sleep_seconds=0.0):
    runtime_root.mkdir(parents=True, exist_ok=True)
    script = runtime_root / "predict_ultralytics_runner.py"
    script.write_text(
        f"""
import argparse
import json
import time
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--model", required=True)
parser.add_argument("--input", required=True)
parser.add_argument("--output", required=True)
parser.add_argument("--conf", type=float, default=0.25)
parser.add_argument("--device", default="")
args = parser.parse_args()
Path(__file__).with_name("started.marker").write_text("started", encoding="utf-8")
time.sleep({float(sleep_seconds)!r})
Path(args.output).parent.mkdir(parents=True, exist_ok=True)
Path(args.output).write_bytes(b"rendered-result-image")
Path(__file__).with_name("completed.marker").write_text("completed", encoding="utf-8")
print(json.dumps({{
    "ok": True,
    "engine": "ultralytics",
    "model": Path(args.model).name,
    "inference_ms": 12.5,
    "detections": [{{"class_id": 0, "label": "person", "confidence": 0.91}}],
    "note": "device=" + args.device,
}}))
""".strip(),
        encoding="utf-8",
    )
    return script


def build_runner(tmp_path, client, transfer, *, sleep_seconds=0.0):
    runtime_root = tmp_path / "runtime"
    write_runner(runtime_root, sleep_seconds=sleep_seconds)
    workdirs = AgentExecutionWorkdir(tmp_path / "agent-state")
    runner = AgentDeploymentRunner(
        client,
        workdirs,
        runtime_root=runtime_root,
        transfer_session=transfer,
        python_by_framework={"ultralytics": sys.executable},
        heartbeat_interval=1.0,
        process_poll_interval=0.05,
        transfer_timeout=10,
    )
    return runner, runtime_root, workdirs


def test_real_subprocess_portable_deployment_success(tmp_path):
    current, downloads = lease(selected_device="cuda:0")
    transfer = FakeTransferSession(downloads)
    client = FakeControlClient(transfer)
    runner, runtime_root, workdirs = build_runner(tmp_path, client, transfer)

    outcome = runner.run(current)

    assert outcome.status == "SUCCEEDED"
    assert outcome.result_ref == "remote-results/1/result.json"
    assert client.prepare_calls[0]["generation"] == 1
    assert client.confirm_calls[0]["engine"] == "ultralytics"
    assert client.confirm_calls[0]["model"] == "yolo11n.pt"
    assert client.confirm_calls[0]["note"] == "device=cuda:0"
    assert client.begin_calls == 1
    assert client.finish_calls[-1]["status"] == "SUCCEEDED"
    assert client.finish_calls[-1]["result_ref"] == "remote-results/1/result.json"
    assert transfer.put_calls[0]["body"] == b"rendered-result-image"
    assert transfer.put_calls[0]["headers"]["If-None-Match"] == "*"
    assert (runtime_root / "completed.marker").is_file()
    assert not (workdirs.root / "executions" / current.task_id / "1").exists()
    assert any("starting deployment runner" in line for line in client.logs)


def test_object_model_is_downloaded_and_verified_before_process(tmp_path):
    input_data = b"input-image"
    model_data = b"portable-model"
    model_url = "https://storage.example.test/model"
    model = {
        "type": "object",
        "artifact_id": "artifact-1",
        "download": _download(model_url, "best.pt", model_data),
    }
    current, downloads = lease(input_data, model=model)
    downloads[model_url] = model_data
    transfer = FakeTransferSession(downloads)
    client = FakeControlClient(transfer)
    runner, _runtime_root, _workdirs = build_runner(tmp_path, client, transfer)

    outcome = runner.run(current)

    assert outcome.status == "SUCCEEDED"
    assert [call["url"] for call in transfer.get_calls] == [
        "https://storage.example.test/input",
        model_url,
    ]
    assert client.confirm_calls[0]["model"] == "best.pt"


def test_download_hash_mismatch_fails_without_starting_process(tmp_path):
    current, downloads = lease()
    current.payload["input"]["download"]["sha256"] = "f" * 64
    transfer = FakeTransferSession(downloads)
    client = FakeControlClient(transfer)
    runner, runtime_root, workdirs = build_runner(tmp_path, client, transfer)

    outcome = runner.run(current)

    assert outcome.status == "FAILED"
    assert "sha256" in outcome.error
    assert client.finish_calls[-1]["status"] == "FAILED"
    assert not (runtime_root / "started.marker").exists()
    assert not (workdirs.root / "executions" / current.task_id / "1").exists()


def test_lost_put_response_recovers_through_idempotent_prepare(tmp_path):
    current, downloads = lease()
    transfer = FakeTransferSession(downloads, fail_first_put_after_body=True)
    client = FakeControlClient(transfer)
    runner, _runtime_root, _workdirs = build_runner(tmp_path, client, transfer)

    outcome = runner.run(current)

    assert outcome.status == "SUCCEEDED"
    assert len(client.prepare_calls) == 2
    assert len(transfer.put_calls) == 1
    assert client.confirm_calls
    assert client.finish_calls[-1]["status"] == "SUCCEEDED"


def test_central_cancellation_terminates_real_local_process_tree(tmp_path):
    current, downloads = lease()
    transfer = FakeTransferSession(downloads)
    # Explicit milestone beats are 1..3; the first background beat while the
    # process is sleeping becomes beat 4 and requests cancellation.
    client = FakeControlClient(transfer, cancel_at_heartbeat=4)
    runner, runtime_root, workdirs = build_runner(
        tmp_path,
        client,
        transfer,
        sleep_seconds=5.0,
    )

    started = time.monotonic()
    outcome = runner.run(current)
    elapsed = time.monotonic() - started

    assert outcome.status == "CANCELLED"
    assert elapsed < 4.0
    assert (runtime_root / "started.marker").is_file()
    assert not (runtime_root / "completed.marker").exists()
    assert client.finish_calls[-1]["status"] == "CANCELLED"
    assert not (workdirs.root / "executions" / current.task_id / "1").exists()


def test_execution_fence_terminates_real_process_without_terminal_mutation(tmp_path):
    current, downloads = lease()
    transfer = FakeTransferSession(downloads)
    client = FakeControlClient(transfer, fence_at_heartbeat=4)
    runner, runtime_root, workdirs = build_runner(
        tmp_path,
        client,
        transfer,
        sleep_seconds=5.0,
    )

    started = time.monotonic()
    with pytest.raises(RemoteExecutionFenced):
        runner.run(current)
    elapsed = time.monotonic() - started

    assert elapsed < 4.0
    assert (runtime_root / "started.marker").is_file()
    assert not (runtime_root / "completed.marker").exists()
    assert client.finish_calls == []
    assert not (workdirs.root / "executions" / current.task_id / "1").exists()


def test_local_agent_shutdown_kills_real_process_without_terminal_mutation(tmp_path):
    current, downloads = lease()
    transfer = FakeTransferSession(downloads)
    client = FakeControlClient(transfer)
    runner, runtime_root, workdirs = build_runner(
        tmp_path,
        client,
        transfer,
        sleep_seconds=5.0,
    )
    captured = {}

    def execute():
        try:
            captured["outcome"] = runner.run(current)
        except BaseException as error:
            captured["error"] = error

    thread = threading.Thread(target=execute, daemon=True)
    thread.start()
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline and not (runtime_root / "started.marker").exists():
        time.sleep(0.05)
    assert (runtime_root / "started.marker").is_file()

    runner.request_shutdown()
    thread.join(timeout=4.0)

    assert not thread.is_alive()
    assert isinstance(captured.get("error"), RemoteExecutionFenced)
    assert client.finish_calls == []
    assert not (runtime_root / "completed.marker").exists()
    assert not (workdirs.root / "executions" / current.task_id / "1").exists()


def test_runner_rejects_non_allowlisted_official_model_before_process(tmp_path):
    current, downloads = lease(model={"type": "official", "reference": "private-model.pt"})
    transfer = FakeTransferSession(downloads)
    client = FakeControlClient(transfer)
    runner, runtime_root, _workdirs = build_runner(tmp_path, client, transfer)

    outcome = runner.run(current)

    assert outcome.status == "FAILED"
    assert "allow-listed" in outcome.error
    assert not (runtime_root / "started.marker").exists()


def test_runner_source_has_no_control_plane_database_or_shared_nfs_dependency():
    source = (
        Path(__file__).resolve().parents[2]
        / "platform_core"
        / "node_agent_deployment_runtime.py"
    ).read_text(encoding="utf-8")
    assert "sqlite3" not in source
    assert "TaskRepository" not in source
    assert "tasks.sqlite3" not in source
    assert "shared_nfs" not in source.lower()
