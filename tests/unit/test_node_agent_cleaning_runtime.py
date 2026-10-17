from __future__ import annotations

import hashlib
import io
import json

from PIL import Image

import platform_core.node_agent_cleaning_runtime as cleaning_runtime
from platform_core.node_agent_cleaning_runtime import AgentCleaningRunner
from platform_core.node_agent_executor_runtime import AgentExecutionWorkdir, RemoteExecutionLease


def _image_bytes():
    stream = io.BytesIO()
    Image.new("RGB", (64, 48), (30, 60, 90)).save(stream, format="JPEG")
    return stream.getvalue()


class FakeResponse:
    def __init__(self, status_code=200, body=b"", headers=None):
        self.status_code = status_code
        self.body = body
        self.headers = dict(headers or {})

    def iter_content(self, chunk_size=1024 * 1024):
        for offset in range(0, len(self.body), chunk_size):
            yield self.body[offset:offset + chunk_size]

    def close(self):
        pass


class FakeSession:
    def __init__(self, image):
        self.image = image
        self.uploaded = b""
        self.put_headers = {}

    def get(self, url, **kwargs):
        assert url == "https://objects.example.test/image.jpg"
        return FakeResponse(
            200,
            self.image,
            {"Content-Length": str(len(self.image))},
        )

    def put(self, url, *, headers, data, **kwargs):
        assert url == "https://objects.example.test/clean-review.jsonl"
        self.put_headers = dict(headers)
        self.uploaded = b"".join(data)
        return FakeResponse(200)


class FakeAnalysisRuntime:
    def analyze(self, path, *, require_blur, content_sha256, check_active=None):
        assert path.is_file()
        assert require_blur is True
        if check_active is not None:
            check_active()
        return {
            "width": 64,
            "height": 48,
            "sha256": content_sha256,
            "dhash": 1234,
            "blur_score": 88.0,
            "brightness": 101.0,
            "entropy": 6.0,
            "analysis_downsampled": False,
        }

    def close(self):
        pass


class FakeClient:
    def __init__(self, image):
        self.image = image
        self.sha = hashlib.sha256(image).hexdigest()
        self.prepared = None
        self.confirmed_runtime = None
        self.finished = []
        self.page_calls = 0
        self.read_calls = []

    def heartbeat(self, _lease, **kwargs):
        return {"cancel_requested": False, "task": {"status": "RUNNING"}}

    def clean_selection_page(self, _lease, *, cursor=None, limit=100):
        self.page_calls += 1
        assert cursor is None
        assert limit == 100
        return {
            "items": [{
                "image_id": "img-1",
                "file_name": "image.jpg",
                "storage_source_id": "s3-clean",
                "storage_type": "s3",
                "object_key": "dataset/image.jpg",
                "size_bytes": len(self.image),
                "etag": "etag-1",
                "sha256": self.sha,
            }],
            "next_cursor": None,
            "total": 1,
            "selection_protocol": "exact-material-selection-v1",
        }

    def clean_selection_read(self, _lease, image_id):
        self.read_calls.append(image_id)
        assert image_id == "img-1"
        return {
            "image_id": image_id,
            "source": {
                "image_id": image_id,
                "file_name": "image.jpg",
                "storage_source_id": "s3-clean",
                "storage_type": "s3",
                "object_key": "dataset/image.jpg",
                "size_bytes": len(self.image),
                "etag": "etag-1",
                "sha256": self.sha,
            },
            "download": {
                "method": "GET",
                "url": "https://objects.example.test/image.jpg",
                "headers": {},
                "file_name": "image.jpg",
                "size_bytes": len(self.image),
                "sha256": self.sha,
                "content_type": "image/jpeg",
            },
        }

    def prepare_result_upload(self, _lease, *, sha256, size_bytes):
        self.prepared = {"sha256": sha256, "size_bytes": size_bytes}
        return {
            "already_uploaded": False,
            "upload": {
                "method": "PUT",
                "url": "https://objects.example.test/clean-review.jsonl",
                "headers": {
                    "Content-Length": str(size_bytes),
                    "x-amz-meta-sha256": sha256,
                    "If-None-Match": "*",
                    "Content-Type": "application/x-ndjson",
                },
                "overwrite_protected": True,
            },
        }

    def confirm_result_upload(self, _lease, *, runtime_result=None):
        self.confirmed_runtime = dict(runtime_result or {})
        return {
            "confirmed": True,
            "result_ref": "remote-results/1/result.json",
            "result": {},
        }

    def finish(self, _lease, status, **kwargs):
        self.finished.append((status, dict(kwargs)))
        return {"task": {"status": status}}


def _lease():
    return RemoteExecutionLease(
        task_id="clean-task",
        kind="MATERIAL_BATCH",
        project_id="project-clean",
        generation=1,
        lease_token="lease-secret",
        lease_expires_at="2099-01-01T00:00:00+00:00",
        worker_id="agent:clean-node",
        payload={
            "schema_version": 1,
            "task_kind": "MATERIAL_BATCH",
            "transport": "object-storage-v1",
            "operation": "CLEAN",
            "selection": {
                "protocol": "exact-material-selection-v1",
                "page_size": 100,
            },
            "options": {
                "blur_check": True,
            },
            "output": {
                "type": "object",
                "storage_ref": {
                    "storage_source_id": "s3-clean",
                    "object_key": "remote-execution/project-clean/clean-task/cleaning-review/review.jsonl",
                    "file_name": "cleaning-review.jsonl",
                    "content_type": "application/x-ndjson",
                },
                "upload_protocol": "prepare-after-local-hash-v1",
            },
        },
        assignment={},
        transport={},
    )


def test_agent_cleaning_runner_publishes_metrics_only_review(monkeypatch, tmp_path):
    image = _image_bytes()
    client = FakeClient(image)
    session = FakeSession(image)
    monkeypatch.setattr(cleaning_runtime, "CleaningAnalysisRuntime", FakeAnalysisRuntime)
    runner = AgentCleaningRunner(
        client,
        AgentExecutionWorkdir(tmp_path / "agent-state"),
        transfer_session=session,
        heartbeat_interval=60,
    )
    # Runtime readiness is independently tested by production heartbeat. This unit
    # isolates the execution contract from optional local OpenCV installation.
    runner._ready = True
    runner._recovery_error = ""

    outcome = runner.run(_lease())

    assert outcome.status == "SUCCEEDED"
    assert outcome.result_ref == "remote-results/1/result.json"
    assert client.finished[-1][0] == "SUCCEEDED"
    assert client.read_calls == ["img-1"]
    assert client.prepared is not None
    assert len(session.uploaded) == client.prepared["size_bytes"]
    assert hashlib.sha256(session.uploaded).hexdigest() == client.prepared["sha256"]
    assert session.put_headers["x-amz-meta-sha256"] == client.prepared["sha256"]
    assert client.confirmed_runtime == {
        "ok": True,
        "engine": "material-cleaning",
        "processed": 1,
        "succeeded": 1,
        "failed": 0,
    }

    rows = [json.loads(line) for line in session.uploaded.decode("utf-8").splitlines()]
    assert rows[0] == {
        "schema_version": 1,
        "task_id": "clean-task",
        "project_id": "project-clean",
        "execution_generation": 1,
        "operation": "CLEAN",
        "total": 1,
    }
    assert rows[1]["image_id"] == "img-1"
    assert rows[1]["status"] == "analyzed"
    assert rows[1]["metrics"]["sha256"] == hashlib.sha256(image).hexdigest()
    assert "issues" not in rows[1], "Agent must not own cleaning-rule decisions"

    execution_dir = tmp_path / "agent-state" / "executions" / "clean-task" / "1"
    assert not execution_dir.exists()
