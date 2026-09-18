from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

from platform_core.node_agent_conversion_runtime import (
    AgentConversionRunner,
    AgentConversionRuntimeError,
)
from platform_core.node_agent_executor_runtime import (
    AgentExecutionWorkdir,
    RemoteExecutionFenced,
    RemoteExecutionLease,
)


class FakeResponse:
    def __init__(self, status_code=200, body=b"", headers=None):
        self.status_code = int(status_code)
        self.body = bytes(body)
        self.headers = dict(headers or {})

    def iter_content(self, chunk_size=1024 * 1024):
        for offset in range(0, len(self.body), max(1, int(chunk_size))):
            yield self.body[offset: offset + chunk_size]

    def close(self):
        pass


class FakeSession:
    def __init__(self, source_bytes):
        self.source_bytes = bytes(source_bytes)
        self.puts = []

    def get(self, _url, *, headers=None, stream=True, timeout=None, allow_redirects=False):
        return FakeResponse(
            200,
            self.source_bytes,
            {"Content-Length": str(len(self.source_bytes))},
        )

    def put(self, url, *, headers=None, data=None, timeout=None, allow_redirects=False):
        payload = b"".join(data) if data is not None else b""
        self.puts.append({
            "url": str(url),
            "headers": dict(headers or {}),
            "body": payload,
        })
        return FakeResponse(200)


class FakeClient:
    def __init__(self):
        self.events = []
        self.finish_calls = []

    def heartbeat(self, lease, **kwargs):
        self.events.append(("heartbeat", dict(kwargs)))
        return {"cancel_requested": False, "task": {"status": "RUNNING"}}

    def append_log(self, lease, text):
        self.events.append(("log", str(text)))
        return {"ok": True}

    def prepare_result_upload(self, lease, *, sha256, size_bytes):
        self.events.append(("prepare", sha256, int(size_bytes)))
        return {
            "already_uploaded": False,
            "sha256": sha256,
            "size_bytes": int(size_bytes),
            "upload": {
                "method": "PUT",
                "url": "https://objects.example.test/result",
                "headers": {
                    "Content-Type": "application/octet-stream",
                    "Content-Length": str(int(size_bytes)),
                    "x-amz-meta-sha256": sha256,
                    "If-None-Match": "*",
                },
            },
        }

    def confirm_result_upload(self, lease, *, runtime_result=None):
        self.events.append(("confirm", dict(runtime_result or {})))
        return {
            "confirmed": True,
            "result_ref": f"remote-results/{lease.generation}/result.json",
        }

    def begin_finalization(self, lease):
        self.events.append(("finalize", lease.task_id))
        return {"task": {"status": "FINALIZING"}}

    def finish(self, lease, status, *, result_ref=None, error=None, accepted=None):
        self.events.append(("finish", status, result_ref, error))
        self.finish_calls.append({
            "status": status,
            "result_ref": result_ref,
            "error": error,
        })
        return {"task": {"status": status}}


def _lease(source_bytes: bytes, *, source_name="source.pt", digest=None):
    sha = digest or hashlib.sha256(source_bytes).hexdigest()
    return RemoteExecutionLease(
        task_id="convert-agent-task",
        kind="MODEL_CONVERSION",
        project_id="project-1",
        generation=3,
        lease_token="execution-secret",
        lease_expires_at="2026-09-18T12:00:00+00:00",
        worker_id="agent:node-1",
        payload={
            "schema_version": 1,
            "task_kind": "MODEL_CONVERSION",
            "transport": "object-storage-v1",
            "target": "onnx",
            "params": {
                "input_size": 640,
                "batch": 1,
                "opset": 12,
                "dynamic": False,
                "simplify": False,
            },
            "source": {
                "type": "object",
                "artifact_id": "artifact-source",
                "download": {
                    "method": "GET",
                    "url": "https://objects.example.test/source",
                    "headers": {},
                    "file_name": source_name,
                    "size_bytes": len(source_bytes),
                    "sha256": sha,
                },
            },
            "source_trace": {
                "source_id": "version::algorithm-a::version-1",
                "algorithm_id": "algorithm-a",
                "version_id": "version-1",
                "sha256": sha,
            },
            "output": {
                "type": "object",
                "storage_ref": {
                    "storage_source_id": "remote-models",
                    "object_key": "remote-execution/result/model.onnx",
                    "file_name": "model.onnx",
                    "content_type": "application/octet-stream",
                },
                "upload_protocol": "prepare-after-local-hash-v1",
            },
        },
        assignment={},
        transport={},
    )


def _worker_script(root: Path, *, runtime_verified=True, exit_code=0):
    script = root / "deployment_worker.py"
    script.write_text(
        f"""
import argparse, json
from pathlib import Path

p=argparse.ArgumentParser()
p.add_argument('--job-dir', required=True)
args=p.parse_args()
job_dir=Path(args.job_dir)
job=json.loads((job_dir/'job.json').read_text(encoding='utf-8'))
artifacts=job_dir/'artifacts'
artifacts.mkdir(parents=True, exist_ok=True)
(artifacts/'model.onnx').write_bytes(b'verified-onnx-result')
manifest={{
    'status': {'"runtime_verified"' if runtime_verified else '"converted_unverified"'},
    'runtime_verified': {str(bool(runtime_verified))},
    'target': {{'kind': 'onnx'}},
    'outputs': [{{'name':'model.onnx'}}],
}}
(artifacts/'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
job.update(
    status='done',
    progress=100,
    stage='done',
    runtime_verified={str(bool(runtime_verified))},
    validation_status={'"runtime_verified"' if runtime_verified else '"converted_unverified"'},
)
(job_dir/'job.json').write_text(json.dumps(job), encoding='utf-8')
(job_dir/'convert.log').write_text('conversion worker complete\\n', encoding='utf-8')
raise SystemExit({int(exit_code)})
""",
        encoding="utf-8",
    )
    return script


def test_agent_conversion_runner_executes_real_subprocess_and_publishes_verified_onnx(tmp_path):
    source = b"portable-source-model"
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    _worker_script(runtime_root)
    client = FakeClient()
    session = FakeSession(source)
    workdirs = AgentExecutionWorkdir(tmp_path / "state")
    runner = AgentConversionRunner(
        client,
        workdirs,
        runtime_root=runtime_root,
        ultralytics_python=sys.executable,
        transfer_session=session,
        heartbeat_interval=60,
        process_poll_interval=0.05,
    )

    outcome = runner.run(_lease(source))

    assert outcome.status == "SUCCEEDED"
    assert outcome.result_ref == "remote-results/3/result.json"
    assert len(session.puts) == 1
    uploaded = session.puts[0]["body"]
    assert uploaded == b"verified-onnx-result"
    digest = hashlib.sha256(uploaded).hexdigest()
    prepare = next(event for event in client.events if event[0] == "prepare")
    assert prepare[1:] == (digest, len(uploaded))
    names = [event[0] for event in client.events]
    assert names.index("prepare") < names.index("confirm") < names.index("finalize") < names.index("finish")
    confirm = next(event for event in client.events if event[0] == "confirm")
    assert confirm[1] == {
        "ok": True,
        "engine": "onnxruntime",
        "model": "model.onnx",
        "note": "runtime_verified",
        "target": "onnx",
    }
    assert client.finish_calls[-1]["status"] == "SUCCEEDED"
    assert not (
        tmp_path / "state" / "executions" / "convert-agent-task" / "3"
    ).exists()


def test_agent_conversion_runner_rejects_source_hash_mismatch_before_worker_launch(tmp_path):
    source = b"portable-source-model"
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    marker = runtime_root / "worker-ran"
    script = runtime_root / "deployment_worker.py"
    script.write_text(
        "from pathlib import Path; Path(r'%s').write_text('ran')" % str(marker),
        encoding="utf-8",
    )
    client = FakeClient()
    runner = AgentConversionRunner(
        client,
        AgentExecutionWorkdir(tmp_path / "state"),
        runtime_root=runtime_root,
        ultralytics_python=sys.executable,
        transfer_session=FakeSession(source),
        heartbeat_interval=60,
    )

    outcome = runner.run(_lease(source, digest="0" * 64))

    assert outcome.status == "FAILED"
    assert not marker.exists()
    assert not any(event[0] == "prepare" for event in client.events)
    assert client.finish_calls[-1]["status"] == "FAILED"


def test_agent_conversion_runner_requires_runtime_verified_manifest(tmp_path):
    source = b"portable-source-model"
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    _worker_script(runtime_root, runtime_verified=False)
    client = FakeClient()
    runner = AgentConversionRunner(
        client,
        AgentExecutionWorkdir(tmp_path / "state"),
        runtime_root=runtime_root,
        ultralytics_python=sys.executable,
        transfer_session=FakeSession(source),
        heartbeat_interval=60,
        process_poll_interval=0.05,
    )

    outcome = runner.run(_lease(source))

    assert outcome.status == "FAILED"
    assert not any(event[0] == "prepare" for event in client.events)
    assert client.finish_calls[-1]["status"] == "FAILED"


def test_agent_conversion_runner_rejects_unsupported_source_suffix(tmp_path):
    source = b"engine"
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    _worker_script(runtime_root)
    client = FakeClient()
    runner = AgentConversionRunner(
        client,
        AgentExecutionWorkdir(tmp_path / "state"),
        runtime_root=runtime_root,
        ultralytics_python=sys.executable,
        transfer_session=FakeSession(source),
        heartbeat_interval=60,
    )

    outcome = runner.run(_lease(source, source_name="source.engine"))

    assert outcome.status == "FAILED"
    assert not any(event[0] == "prepare" for event in client.events)


def test_agent_conversion_runner_fails_closed_when_process_identity_cannot_be_persisted(
    tmp_path, monkeypatch
):
    source = b"portable-source-model"
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    _worker_script(runtime_root)
    workdirs = AgentExecutionWorkdir(tmp_path / "state")
    monkeypatch.setattr(
        workdirs,
        "persist_process_identity",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk failure")),
    )
    client = FakeClient()
    runner = AgentConversionRunner(
        client,
        workdirs,
        runtime_root=runtime_root,
        ultralytics_python=sys.executable,
        transfer_session=FakeSession(source),
        heartbeat_interval=60,
        process_poll_interval=0.05,
    )

    with pytest.raises(RemoteExecutionFenced):
        runner.run(_lease(source))

    assert client.finish_calls == []
    assert not any(event[0] == "prepare" for event in client.events)


def test_conversion_runner_source_has_no_control_plane_database_dependency():
    source = (
        Path(__file__).resolve().parents[2]
        / "platform_core"
        / "node_agent_conversion_runtime.py"
    ).read_text(encoding="utf-8")
    assert "sqlite3" not in source
    assert "TaskRepository" not in source
    assert "tasks.sqlite3" not in source


def _rknn_lease(source_bytes: bytes, *, chip="rk3568", digest=None):
    base = _lease(source_bytes, source_name="source.pt", digest=digest)
    payload = dict(base.payload)
    payload["target"] = "rockchip"
    payload["params"] = {
        "input_size": 640,
        "batch": 1,
        "opset": 12,
        "dynamic": False,
        "simplify": False,
        "chip": chip,
        "precision": "fp16",
        "mean": "0,0,0",
        "rknn_std": "255,255,255",
    }
    payload["output"] = {
        "type": "object",
        "storage_ref": {
            "storage_source_id": "remote-models",
            "object_key": f"remote-execution/result/model_{chip}.rknn",
            "file_name": f"model_{chip}.rknn",
            "content_type": "application/octet-stream",
        },
        "upload_protocol": "prepare-after-local-hash-v1",
    }
    return RemoteExecutionLease(
        task_id=base.task_id,
        kind=base.kind,
        project_id=base.project_id,
        generation=base.generation,
        lease_token=base.lease_token,
        lease_expires_at=base.lease_expires_at,
        worker_id=base.worker_id,
        payload=payload,
        assignment={"capability": "conversion.rknn"},
        transport=base.transport,
    )


def _rknn_worker_script(root: Path, *, manifest_chip="rk3568", hardware_verified=False):
    script = root / "deployment_worker.py"
    script.write_text(
        f"""
import argparse, json
from pathlib import Path

p=argparse.ArgumentParser()
p.add_argument('--job-dir', required=True)
args=p.parse_args()
job_dir=Path(args.job_dir)
job=json.loads((job_dir/'job.json').read_text(encoding='utf-8'))
artifacts=job_dir/'artifacts'
artifacts.mkdir(parents=True, exist_ok=True)
chip=str((job.get('params') or {{}}).get('chip') or 'rk3568')
out=artifacts/f'model_{{chip}}.rknn'
out.write_bytes(b'verified-rknn-result')
manifest={{
    'status': 'converted_unverified',
    'runtime_verified': False,
    'hardware_verified': {str(bool(hardware_verified))},
    'target': {{'kind': 'rockchip', 'chip': {manifest_chip!r}, 'precision': 'fp16'}},
    'outputs': [{{'name': out.name}}],
}}
(artifacts/'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
job.update(
    status='done',
    progress=100,
    stage='done',
    runtime_verified=False,
    hardware_verified={str(bool(hardware_verified))},
    validation_status='converted_unverified',
)
(job_dir/'job.json').write_text(json.dumps(job), encoding='utf-8')
(job_dir/'convert.log').write_text('rknn conversion worker complete\\n', encoding='utf-8')
""",
        encoding="utf-8",
    )
    return script


def test_agent_conversion_runner_publishes_rknn_as_hardware_unverified(tmp_path):
    source = b"portable-rknn-source-model"
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    _rknn_worker_script(runtime_root)
    client = FakeClient()
    session = FakeSession(source)
    runner = AgentConversionRunner(
        client,
        AgentExecutionWorkdir(tmp_path / "state"),
        runtime_root=runtime_root,
        ultralytics_python=sys.executable,
        rknn_python=sys.executable,
        transfer_session=session,
        heartbeat_interval=60,
        process_poll_interval=0.05,
    )

    outcome = runner.run(_rknn_lease(source, chip="rk3568"))

    assert outcome.status == "BLOCKED_BY_HARDWARE"
    assert outcome.result_ref == "remote-results/3/result.json"
    assert len(session.puts) == 1
    assert session.puts[0]["body"] == b"verified-rknn-result"
    confirm = next(event for event in client.events if event[0] == "confirm")
    assert confirm[1] == {
        "ok": True,
        "engine": "rknn-toolkit2",
        "model": "model_rk3568.rknn",
        "note": "converted_unverified",
        "target": "rockchip",
        "chip": "rk3568",
    }
    assert client.finish_calls[-1]["status"] == "BLOCKED_BY_HARDWARE"


def test_agent_conversion_runner_rejects_rknn_manifest_chip_mismatch_before_upload(tmp_path):
    source = b"portable-rknn-source-model"
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    _rknn_worker_script(runtime_root, manifest_chip="rk3576")
    client = FakeClient()
    runner = AgentConversionRunner(
        client,
        AgentExecutionWorkdir(tmp_path / "state"),
        runtime_root=runtime_root,
        ultralytics_python=sys.executable,
        rknn_python=sys.executable,
        transfer_session=FakeSession(source),
        heartbeat_interval=60,
        process_poll_interval=0.05,
    )

    outcome = runner.run(_rknn_lease(source, chip="rk3568"))

    assert outcome.status == "FAILED"
    assert not any(event[0] == "prepare" for event in client.events)
    assert client.finish_calls[-1]["status"] == "FAILED"


def test_agent_conversion_runner_rejects_rknn_claimed_as_hardware_verified(tmp_path):
    source = b"portable-rknn-source-model"
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    _rknn_worker_script(runtime_root, hardware_verified=True)
    client = FakeClient()
    runner = AgentConversionRunner(
        client,
        AgentExecutionWorkdir(tmp_path / "state"),
        runtime_root=runtime_root,
        ultralytics_python=sys.executable,
        rknn_python=sys.executable,
        transfer_session=FakeSession(source),
        heartbeat_interval=60,
        process_poll_interval=0.05,
    )

    outcome = runner.run(_rknn_lease(source))

    assert outcome.status == "FAILED"
    assert not any(event[0] == "prepare" for event in client.events)
