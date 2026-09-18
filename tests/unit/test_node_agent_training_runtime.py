from __future__ import annotations

import hashlib
import io
import json
import sys
import time
import zipfile
from pathlib import Path

import pytest
import requests
import yaml

from platform_core.node_agent_executor_runtime import (
    AgentExecutionWorkdir,
    NodeExecutorHTTPError,
    RemoteExecutionFenced,
    RemoteExecutionLease,
)
from platform_core.node_agent_training_runtime import (
    AgentTrainingRunner,
    AgentTrainingRuntimeError,
)
from platform_core.remote_training_transport import create_training_bundle_archive


class FakeResponse:
    def __init__(self, status_code=200, data=b""):
        self.status_code = int(status_code)
        self.data = bytes(data)

    def iter_content(self, chunk_size=1024 * 1024):
        for index in range(0, len(self.data), int(chunk_size)):
            yield self.data[index:index + int(chunk_size)]

    def close(self):
        return None


class FakeTransferSession:
    def __init__(self, downloads=None, *, fail_after_body_urls=None):
        self.downloads = dict(downloads or {})
        self.fail_after_body_urls = set(fail_after_body_urls or ())
        self.failed_after_body_urls = set()
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
        return FakeResponse(200, self.downloads[url])

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
        if (
            url in self.fail_after_body_urls
            and url not in self.failed_after_body_urls
        ):
            self.failed_after_body_urls.add(url)
            raise requests.ConnectionError("response lost after object accepted")
        return FakeResponse(200)


class FakeControlClient:
    def __init__(
        self,
        transfer=None,
        *,
        cancel_at_heartbeat=None,
        fence_at_heartbeat=None,
    ):
        self.transfer = transfer
        self.cancel_at_heartbeat = cancel_at_heartbeat
        self.fence_at_heartbeat = fence_at_heartbeat
        self.heartbeat_calls = 0
        self.heartbeats = []
        self.logs = []
        self.model_prepare_calls = []
        self.model_confirm_calls = 0
        self.prepare_calls = []
        self.confirm_calls = []
        self.begin_calls = 0
        self.finish_calls = []

    def heartbeat(self, _lease, **kwargs):
        self.heartbeat_calls += 1
        self.heartbeats.append(dict(kwargs))
        if (
            self.fence_at_heartbeat
            and self.heartbeat_calls >= self.fence_at_heartbeat
        ):
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
            },
        }

    def append_log(self, _lease, text):
        self.logs.append(str(text))
        return {"ok": True}

    def prepare_training_model_uploads(self, lease, models):
        evidence = [
            {
                "role": str(item["role"]),
                "file_name": str(item["file_name"]),
                "sha256": str(item["sha256"]),
                "size_bytes": int(item["size_bytes"]),
            }
            for item in models
        ]
        self.model_prepare_calls.append(evidence)
        items = []
        for item in evidence:
            role = item["role"]
            url = f"https://storage.example.test/training-model-{role}"
            already_uploaded = (
                self.transfer is not None
                and url in self.transfer.uploaded
            )
            items.append({
                **item,
                "artifact_id": f"artifact-{role}",
                "storage_ref": {
                    "storage_source_id": "s3-main",
                    "object_key": (
                        f"model-assets/generation-{lease.generation}/{role}.pt"
                    ),
                    "file_name": item["file_name"],
                    "content_type": "application/octet-stream",
                },
                "already_uploaded": already_uploaded,
                "upload": None if already_uploaded else {
                    "method": "PUT",
                    "url": url,
                    "headers": {
                        "Content-Type": "application/octet-stream",
                        "Content-Length": str(item["size_bytes"]),
                        "x-amz-meta-sha256": item["sha256"],
                        "If-None-Match": "*",
                    },
                },
            })
        return {
            "version_id": f"rt-generation-{lease.generation}",
            "execution_generation": lease.generation,
            "items": items,
        }

    def confirm_training_model_uploads(self, lease):
        self.model_confirm_calls += 1
        if not self.model_prepare_calls:
            raise AssertionError("models were not prepared")
        evidence = self.model_prepare_calls[-1]
        items = []
        for item in evidence:
            role = item["role"]
            url = f"https://storage.example.test/training-model-{role}"
            if self.transfer is not None and url not in self.transfer.uploaded:
                raise AssertionError(f"{role} model was not uploaded")
            items.append({
                **item,
                "artifact_id": f"artifact-{role}",
                "storage_ref": {
                    "storage_source_id": "s3-main",
                    "object_key": (
                        f"model-assets/generation-{lease.generation}/{role}.pt"
                    ),
                    "file_name": item["file_name"],
                    "content_type": "application/octet-stream",
                },
            })
        return {
            "confirmed": True,
            "version_id": f"rt-generation-{lease.generation}",
            "items": items,
        }

    def prepare_result_upload(self, lease, *, sha256, size_bytes):
        self.prepare_calls.append({
            "generation": lease.generation,
            "sha256": sha256,
            "size_bytes": int(size_bytes),
        })
        if (
            self.transfer is not None
            and "https://storage.example.test/training-result"
            in self.transfer.uploaded
        ):
            return {
                "already_uploaded": True,
                "confirmed": False,
                "sha256": sha256,
                "size_bytes": int(size_bytes),
                "storage_ref": {
                    "storage_source_id": "s3-main",
                    "object_key": (
                        f"training/generation-{lease.generation}/result.zip"
                    ),
                    "file_name": "training-result.zip",
                    "content_type": "application/zip",
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
                "object_key": (
                    f"training/generation-{lease.generation}/result.zip"
                ),
                "file_name": "training-result.zip",
                "content_type": "application/zip",
            },
            "upload": {
                "method": "PUT",
                "url": "https://storage.example.test/training-result",
                "headers": {
                    "Content-Type": "application/zip",
                    "Content-Length": str(int(size_bytes)),
                    "x-amz-meta-sha256": sha256,
                    "If-None-Match": "*",
                },
            },
        }

    def confirm_result_upload(self, lease, *, runtime_result=None):
        self.confirm_calls.append(dict(runtime_result or {}))
        return {
            "confirmed": True,
            "result_ref": (
                f"remote-results/{lease.generation}/result.json"
            ),
            "result": {
                **dict(runtime_result or {}),
                "execution_generation": lease.generation,
            },
        }

    def begin_finalization(self, _lease):
        self.begin_calls += 1
        return {"task": {"stage": "finalizing_commit"}}

    def finish(
        self,
        lease,
        status,
        *,
        result_ref=None,
        error=None,
        accepted=None,
    ):
        self.finish_calls.append({
            "generation": lease.generation,
            "status": status,
            "result_ref": result_ref,
            "error": error,
            "accepted": accepted,
        })
        return {"task": {"status": status}}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bundle(root: Path, *, snapshot_id="snapshot-agent") -> Path:
    (root / "dataset" / "images" / "train").mkdir(parents=True)
    (root / "dataset" / "labels" / "train").mkdir(parents=True)
    image = root / "dataset" / "images" / "train" / "one.jpg"
    label = root / "dataset" / "labels" / "train" / "one.txt"
    image.write_bytes(b"portable-agent-image")
    label.write_text("0 0.5 0.5 0.25 0.25", encoding="utf-8")
    data_yaml = root / "dataset" / "data.yaml"
    data_yaml.write_text(
        yaml.safe_dump({
            "path": ".",
            "train": "images/train",
            "val": "images/train",
            "names": {0: "fire"},
        }, sort_keys=False),
        encoding="utf-8",
    )
    snapshot = root / "snapshot.json"
    snapshot.write_text(
        json.dumps({"snapshot_id": snapshot_id}, sort_keys=True),
        encoding="utf-8",
    )
    manifest = {
        "schema_version": 3,
        "snapshot_id": snapshot_id,
        "training_input_policy": "ultralytics_jpeg_repair_v1",
        "snapshot_ref": "snapshot.json",
        "snapshot_sha256": _sha(snapshot),
        "data_yaml_ref": "dataset/data.yaml",
        "total_size_bytes": image.stat().st_size,
        "splits": {
            "train": [{
                "image_id": "one",
                "image_ref": "dataset/images/train/one.jpg",
                "label_ref": "dataset/labels/train/one.txt",
                "source_content_sha256": _sha(image),
                "source_size_bytes": image.stat().st_size,
                "content_sha256": _sha(image),
                "size_bytes": image.stat().st_size,
                "training_input_policy": "ultralytics_jpeg_repair_v1",
                "normalized": False,
                "normalization_reason": "",
                "label_sha256": _sha(label),
            }],
            "validation": [],
            "test": [],
        },
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True),
        encoding="utf-8",
    )
    return root


def _download_contract(url, name, data, archive):
    return {
        "method": "GET",
        "url": url,
        "headers": {},
        "expires_seconds": 900,
        "file_name": name,
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "content_type": "application/zip",
        "uncompressed_size_bytes": archive.uncompressed_size_bytes,
        "member_count": archive.member_count,
        "snapshot_id": archive.snapshot_id,
    }


def training_lease(tmp_path, *, generation=3, model=None):
    archive = create_training_bundle_archive(
        _bundle(tmp_path / "source-bundle"),
        tmp_path / "source-bundle.zip",
    )
    bundle_bytes = archive.path.read_bytes()
    bundle_url = "https://storage.example.test/training-bundle"
    payload = {
        "schema_version": 1,
        "task_kind": "TRAINING",
        "transport": "object-storage-v1",
        "framework": "ultralytics",
        "algorithm_id": "algorithm-fire",
        "snapshot_id": archive.snapshot_id,
        "requested_device": "auto",
        "selected_device": "cuda:1",
        "selected_gpu": {
            "id": "cuda:1",
            "index": 1,
            "uuid": "GPU-agent-uuid",
            "name": "NVIDIA Test GPU",
            "memory_free_bytes": 20 * 1024**3,
            "memory_total_bytes": 24 * 1024**3,
        },
        "bundle": {
            "type": "object",
            "download": _download_contract(
                bundle_url,
                "training-bundle.zip",
                bundle_bytes,
                archive,
            ),
        },
        "model": model or {
            "type": "official",
            "reference": "yolo11n.pt",
            "base_selection_reason": "mother_model",
        },
        "params": {
            "epochs": 3,
            "imgsz": 640,
            "batch": 4,
            "workers": 0,
            "optimizer": "auto",
            "seed": 9,
            "resource_strategy": "auto",
        },
        "result": {
            "type": "object",
            "storage_ref": {
                "storage_source_id": "s3-main",
                "object_key": "training/result.zip",
                "file_name": "training-result.zip",
                "content_type": "application/zip",
            },
            "upload_protocol": "prepare-after-local-hash-v1",
        },
    }
    lease = RemoteExecutionLease(
        task_id="train-agent-task",
        kind="TRAINING",
        project_id="project-1",
        generation=generation,
        lease_token="execution-secret",
        lease_expires_at="2026-09-18T11:00:00+00:00",
        worker_id="agent:node-1",
        payload=payload,
        assignment={},
        transport={
            "shared_sqlite_required": False,
            "shared_nfs_required": False,
        },
    )
    return lease, {bundle_url: bundle_bytes}


def write_fake_train_worker(
    runtime_root: Path,
    *,
    sleep_seconds=0.0,
    test_result_status="passed",
):
    runtime_root.mkdir(parents=True, exist_ok=True)
    script = runtime_root / "train_worker.py"
    script.write_text(
        f"""
import argparse
import json
import time
from pathlib import Path

parser = argparse.ArgumentParser(add_help=False)
parser.add_argument("--project-dir", required=True)
parser.add_argument("--data", required=True)
parser.add_argument("--model", required=True)
parser.add_argument("--epochs", required=True)
parser.add_argument("--device", required=True)
parser.add_argument("--assigned-device", required=True)
parser.add_argument("--requested-device", required=True)
parser.add_argument("--job-id", required=True)
parser.add_argument("--run-name", required=True)
args, _unknown = parser.parse_known_args()

runtime_root = Path(__file__).resolve().parent
runtime_root.joinpath("started.marker").write_text("started", encoding="utf-8")
runtime_root.joinpath("worker-args.json").write_text(
    json.dumps({{
        "project_dir": args.project_dir,
        "data": args.data,
        "model": args.model,
        "epochs": args.epochs,
        "device": args.device,
        "assigned_device": args.assigned_device,
        "requested_device": args.requested_device,
        "job_id": args.job_id,
        "run_name": args.run_name,
    }}, sort_keys=True),
    encoding="utf-8",
)
project = Path(args.project_dir)
job_file = project / "jobs" / args.job_id / "job.json"
job = json.loads(job_file.read_text(encoding="utf-8"))
job.update({{
    "status": "running",
    "progress_percent": 42,
    "startup_stage": "first_batch",
    "current_item": "Epoch 1/3",
}})
job_file.write_text(json.dumps(job), encoding="utf-8")
print("fake training started", flush=True)
time.sleep({float(sleep_seconds)!r})

models = project / "models"
models.mkdir(parents=True, exist_ok=True)
best = models / (args.run_name + "_best.pt")
last = models / (args.run_name + "_last.pt")
best.write_bytes(b"verified-best-model")
last.write_bytes(b"verified-last-model")
job.update({{
    "status": "done",
    "progress_percent": 100,
    "artifact_verified": True,
    "verified_models": [str(best), str(last)],
    "best_path": str(best),
    "last_path": str(last),
    "training_report": {{
        "metrics": {{"map50": 0.91}},
        "test_result": {{"status": {str(test_result_status)!r}}},
    }},
    "training_outcome": "completed",
    "completion_reason": "requested_epochs_completed",
    "completed_epochs": 3,
    "requested_epochs": 3,
    "requested_device": args.requested_device,
    "assigned_device": args.assigned_device,
    "actual_device": args.assigned_device,
    "finished_at": "2026-09-18 10:00:00",
}})
job_file.write_text(json.dumps(job), encoding="utf-8")
print("fake training completed", flush=True)
runtime_root.joinpath("completed.marker").write_text("completed", encoding="utf-8")
""".strip(),
        encoding="utf-8",
    )
    return script


def build_runner(
    tmp_path,
    client,
    transfer,
    *,
    sleep_seconds=0.0,
    test_result_status="passed",
):
    runtime_root = tmp_path / "runtime"
    write_fake_train_worker(
        runtime_root,
        sleep_seconds=sleep_seconds,
        test_result_status=test_result_status,
    )
    workdirs = AgentExecutionWorkdir(tmp_path / "agent-state")
    runner = AgentTrainingRunner(
        client,
        workdirs,
        runtime_root=runtime_root,
        ultralytics_python=sys.executable,
        transfer_session=transfer,
        heartbeat_interval=1.0,
        process_poll_interval=0.05,
        transfer_timeout=10,
    )
    return runner, runtime_root, workdirs


def test_real_subprocess_remote_training_success(tmp_path):
    current, downloads = training_lease(tmp_path)
    transfer = FakeTransferSession(downloads)
    client = FakeControlClient(transfer)
    runner, runtime_root, workdirs = build_runner(
        tmp_path,
        client,
        transfer,
        sleep_seconds=1.2,
    )

    outcome = runner.run(current)

    assert outcome.status == "SUCCEEDED"
    assert outcome.result_ref == "remote-results/3/result.json"
    assert client.prepare_calls[0]["generation"] == 3
    assert client.confirm_calls[0]["training_outcome"] == "completed"
    assert client.confirm_calls[0]["actual_device"] == "cuda:1"
    assert client.begin_calls == 1
    assert client.finish_calls[-1]["status"] == "SUCCEEDED"
    assert client.finish_calls[-1]["result_ref"] == outcome.result_ref
    assert len(transfer.put_calls) == 3
    assert client.model_prepare_calls
    assert client.model_confirm_calls == 1
    assert transfer.put_calls[0]["url"].startswith(
        "https://storage.example.test/training-model-"
    )
    assert transfer.put_calls[1]["url"].startswith(
        "https://storage.example.test/training-model-"
    )
    assert transfer.put_calls[-1]["url"] == (
        "https://storage.example.test/training-result"
    )
    assert transfer.put_calls[-1]["headers"]["If-None-Match"] == "*"

    args = json.loads(
        (runtime_root / "worker-args.json").read_text(encoding="utf-8")
    )
    assert args["device"] == "cuda:1"
    assert args["assigned_device"] == "cuda:1"
    assert args["requested_device"] == "auto"
    assert args["model"] == "yolo11n.pt"
    assert Path(args["data"]).name == "data.yaml"

    uploaded = transfer.put_calls[-1]["body"]
    with zipfile.ZipFile(io.BytesIO(uploaded), "r") as archive:
        manifest = json.loads(
            archive.read("manifest.json").decode("utf-8")
        )
        assert manifest["task_id"] == current.task_id
        assert manifest["execution_generation"] == current.generation
        assert manifest["snapshot_id"] == "snapshot-agent"
        assert manifest["model_transport"] == "separate-object-v1"
        assert len(manifest["models"]) == 2
        assert archive.namelist() == ["manifest.json"]

    assert (runtime_root / "completed.marker").is_file()
    assert not (
        workdirs.root
        / "executions"
        / current.task_id
        / str(current.generation)
    ).exists()
    assert any(
        "starting training worker" in line
        for line in client.logs
    )
    assert any(
        (heartbeat.get("stage") or "") == "first_batch"
        for heartbeat in client.heartbeats
    )


def test_training_object_model_is_downloaded_before_worker(tmp_path):
    model_data = b"portable-base-model"
    model_url = "https://storage.example.test/base-model"
    model = {
        "type": "object",
        "download": {
            "method": "GET",
            "url": model_url,
            "headers": {},
            "file_name": "base.pt",
            "size_bytes": len(model_data),
            "sha256": hashlib.sha256(model_data).hexdigest(),
            "content_type": "application/octet-stream",
        },
        "base_version_id": "v10",
        "base_selection_reason": "current_verified_version",
    }
    current, downloads = training_lease(
        tmp_path,
        model=model,
    )
    downloads[model_url] = model_data
    transfer = FakeTransferSession(downloads)
    client = FakeControlClient(transfer)
    runner, runtime_root, _workdirs = build_runner(
        tmp_path,
        client,
        transfer,
    )

    outcome = runner.run(current)

    assert outcome.status == "SUCCEEDED"
    assert [call["url"] for call in transfer.get_calls] == [
        "https://storage.example.test/training-bundle",
        model_url,
    ]
    args = json.loads(
        (runtime_root / "worker-args.json").read_text(encoding="utf-8")
    )
    assert Path(args["model"]).name == "base.pt"


def test_training_cancellation_kills_worker_and_never_publishes_success(tmp_path):
    current, downloads = training_lease(tmp_path)
    transfer = FakeTransferSession(downloads)
    client = FakeControlClient(
        transfer,
        cancel_at_heartbeat=6,
    )
    runner, runtime_root, _workdirs = build_runner(
        tmp_path,
        client,
        transfer,
        sleep_seconds=10,
    )

    started = time.monotonic()
    outcome = runner.run(current)

    assert time.monotonic() - started < 8
    assert outcome.status == "CANCELLED"
    assert client.finish_calls[-1]["status"] == "CANCELLED"
    assert not client.model_prepare_calls
    assert not client.prepare_calls
    assert (runtime_root / "started.marker").is_file()
    assert not (runtime_root / "completed.marker").exists()


def test_training_fencing_kills_worker_without_stale_terminal_write(tmp_path):
    current, downloads = training_lease(tmp_path)
    transfer = FakeTransferSession(downloads)
    client = FakeControlClient(
        transfer,
        fence_at_heartbeat=6,
    )
    runner, runtime_root, _workdirs = build_runner(
        tmp_path,
        client,
        transfer,
        sleep_seconds=10,
    )

    started = time.monotonic()
    with pytest.raises(RemoteExecutionFenced):
        runner.run(current)

    assert time.monotonic() - started < 8
    assert not client.finish_calls
    assert not client.model_prepare_calls
    assert not client.prepare_calls
    assert (runtime_root / "started.marker").is_file()
    assert not (runtime_root / "completed.marker").exists()


def test_training_result_put_can_recover_after_lost_response(tmp_path):
    current, downloads = training_lease(tmp_path)
    transfer = FakeTransferSession(
        downloads,
        fail_after_body_urls={
            "https://storage.example.test/training-result"
        },
    )
    client = FakeControlClient(transfer)
    runner, _runtime_root, _workdirs = build_runner(
        tmp_path,
        client,
        transfer,
    )

    outcome = runner.run(current)

    assert outcome.status == "SUCCEEDED"
    assert len(client.prepare_calls) == 2
    assert len(transfer.put_calls) == 3
    assert transfer.put_calls[-1]["url"] == (
        "https://storage.example.test/training-result"
    )
    assert client.confirm_calls
    assert client.finish_calls[-1]["status"] == "SUCCEEDED"


def test_training_runtime_rejects_device_evidence_mismatch_before_worker(tmp_path):
    current, downloads = training_lease(tmp_path)
    current.payload["selected_gpu"]["id"] = "cuda:0"
    transfer = FakeTransferSession(downloads)
    client = FakeControlClient(transfer)
    runner, runtime_root, _workdirs = build_runner(
        tmp_path,
        client,
        transfer,
    )

    outcome = runner.run(current)

    assert outcome.status == "FAILED"
    assert "selected GPU identity" in outcome.error
    assert client.finish_calls[-1]["status"] == "FAILED"
    assert not (runtime_root / "started.marker").exists()


def test_training_runtime_source_stays_database_free():
    source = Path(
        "platform_core/node_agent_training_runtime.py"
    ).read_text(encoding="utf-8")
    assert "import sqlite3" not in source
    assert "TaskRepository" not in source
    assert "tasks.sqlite3" not in source
    assert "shared_nfs" not in source.lower()


def test_remote_training_rejects_nonportable_ai_or_supplement_configuration(tmp_path):
    current, downloads = training_lease(tmp_path)
    payload = dict(current.payload)
    payload["params"] = {
        **dict(payload["params"]),
        "ai_intervention_enabled": True,
    }
    current = RemoteExecutionLease(
        task_id=current.task_id,
        kind=current.kind,
        project_id=current.project_id,
        generation=current.generation,
        lease_token=current.lease_token,
        lease_expires_at=current.lease_expires_at,
        worker_id=current.worker_id,
        payload=payload,
        assignment=current.assignment,
        transport=current.transport,
    )
    transfer = FakeTransferSession(downloads)
    client = FakeControlClient(transfer)
    runner, runtime_root, _workdirs = build_runner(tmp_path, client, transfer)

    outcome = runner.run(current)

    assert outcome.status == "FAILED"
    assert "not portable yet" in outcome.error
    assert client.finish_calls[-1]["status"] == "FAILED"
    assert not client.model_prepare_calls
    assert not client.prepare_calls
    assert not (runtime_root / "started.marker").exists()


def test_remote_training_preserves_partial_success_when_independent_test_fails(tmp_path):
    current, downloads = training_lease(tmp_path)
    transfer = FakeTransferSession(downloads)
    client = FakeControlClient(transfer)
    runner, _runtime_root, _workdirs = build_runner(
        tmp_path,
        client,
        transfer,
        test_result_status="failed",
    )

    outcome = runner.run(current)

    assert outcome.status == "PARTIAL_SUCCESS"
    assert client.finish_calls[-1]["status"] == "PARTIAL_SUCCESS"
    assert client.model_confirm_calls == 1
    assert client.confirm_calls
