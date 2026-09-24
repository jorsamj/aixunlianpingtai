from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from PIL import Image

from platform_core.node_agent_executor_runtime import AgentExecutionWorkdir, RemoteExecutionLease
from platform_core.node_agent_material_runtime import AgentMaterialImportRunner


def _image_bytes():
    stream = io.BytesIO()
    Image.new("RGB", (40, 30), (20, 50, 80)).save(stream, format="JPEG")
    return stream.getvalue()


def _input_zip(*, unsafe=False):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("../escape.jpg" if unsafe else "camera/a.jpg", _image_bytes())
        if not unsafe:
            archive.writestr("readme.txt", b"notes")
    return stream.getvalue()


class FakeResponse:
    def __init__(self, status_code=200, body=b"", headers=None):
        self.status_code = status_code
        self.body = body
        self.headers = dict(headers or {})

    @property
    def ok(self):
        return 200 <= self.status_code < 300

    def iter_content(self, chunk_size=1024 * 1024):
        for offset in range(0, len(self.body), chunk_size):
            yield self.body[offset:offset + chunk_size]

    def close(self):
        pass


class ScanSession:
    def __init__(self, image_bytes):
        self.image_bytes = image_bytes
        self.uploaded = b""
        self.put_headers = {}

    def get(self, url, **kwargs):
        assert url == "https://objects.example.test/a.jpg"
        return FakeResponse(
            200,
            self.image_bytes,
            {
                "Content-Length": str(len(self.image_bytes)),
                "ETag": '"etag-a"',
            },
        )

    def put(self, url, *, headers, data, **kwargs):
        assert url == "https://objects.example.test/review.zip"
        self.put_headers = dict(headers)
        self.uploaded = b"".join(data)
        return FakeResponse(200)


class FakeSession:
    def __init__(self, input_bytes):
        self.input_bytes = input_bytes
        self.uploaded = b""
        self.put_headers = {}

    def get(self, url, **kwargs):
        assert url == "https://objects.example.test/input.zip"
        return FakeResponse(
            200,
            self.input_bytes,
            {"Content-Length": str(len(self.input_bytes))},
        )

    def put(self, url, *, headers, data, **kwargs):
        assert url == "https://objects.example.test/review.zip"
        self.put_headers = dict(headers)
        self.uploaded = b"".join(data)
        return FakeResponse(200)


class FakeClient:
    def __init__(self):
        self.prepared = None
        self.scan_image = _image_bytes()
        self.confirmed_runtime = None
        self.finished = []

    def heartbeat(self, _lease, **kwargs):
        return {"cancel_requested": False, "task": {"status": "RUNNING"}}

    def prepare_result_upload(self, _lease, *, sha256, size_bytes):
        self.prepared = {"sha256": sha256, "size_bytes": size_bytes}
        return {
            "already_uploaded": False,
            "upload": {
                "method": "PUT",
                "url": "https://objects.example.test/review.zip",
                "headers": {
                    "Content-Length": str(size_bytes),
                    "x-amz-meta-sha256": sha256,
                    "If-None-Match": "*",
                    "Content-Type": "application/zip",
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

    def material_scan_page(self, _lease, *, cursor=None, limit=100):
        assert cursor is None
        return {
            "items": [{
                "key": "incoming/2026/a.jpg",
                "size_bytes": len(self.scan_image),
                "etag": '"etag-a"',
                "content_type": "image/jpeg",
                "sha256": "",
                "last_modified": "1",
            }],
            "next_cursor": None,
        }

    def material_scan_read(self, _lease, object_key):
        assert object_key == "incoming/2026/a.jpg"
        return {
            "method": "GET",
            "url": "https://objects.example.test/a.jpg",
            "headers": {},
            "key": object_key,
            "size_bytes": len(self.scan_image),
            "etag": '"etag-a"',
            "content_type": "image/jpeg",
            "sha256": "",
            "last_modified": "1",
        }

    def finish(self, _lease, status, **kwargs):
        self.finished.append((status, dict(kwargs)))
        return {
            "task": {
                "status": status,
            }
        }


def _lease(zip_bytes, import_format="images"):
    import hashlib
    digest = hashlib.sha256(zip_bytes).hexdigest()
    return RemoteExecutionLease(
        task_id="material-task",
        kind="MATERIAL_IMPORT",
        project_id="project-one",
        generation=1,
        lease_token="lease-secret",
        lease_expires_at="2099-01-01T00:00:00+00:00",
        worker_id="agent:node-one",
        payload={
            "schema_version": 1,
            "task_kind": "MATERIAL_IMPORT",
            "transport": "object-storage-v1",
            "mode": "zip_scan",
            "import_format": import_format,
            "target": {
                "storage_source_id": "s3-target",
                "storage_type": "s3",
                "target_prefix": "incoming/2026",
            },
            "input": {
                "type": "object",
                "download": {
                    "method": "GET",
                    "url": "https://objects.example.test/input.zip",
                    "headers": {},
                    "file_name": "input.zip",
                    "size_bytes": len(zip_bytes),
                    "sha256": digest,
                    "content_type": "application/zip",
                },
            },
            "output": {
                "type": "object",
                "storage_ref": {
                    "storage_source_id": "s3-target",
                    "object_key": "reviews/review.zip",
                    "file_name": "material-review.zip",
                    "content_type": "application/zip",
                },
                "upload_protocol": "prepare-after-local-hash-v1",
            },
        },
        assignment={},
        transport={},
    )


def test_agent_material_runner_reviews_zip_uploads_and_waits_for_confirmation(tmp_path):
    zip_bytes = _input_zip()
    client = FakeClient()
    session = FakeSession(zip_bytes)
    workdirs = AgentExecutionWorkdir(tmp_path / "agent-state")
    runner = AgentMaterialImportRunner(
        client,
        workdirs,
        transfer_session=session,
        heartbeat_interval=60,
    )

    outcome = runner.run(_lease(zip_bytes))

    assert outcome.status == "AWAITING_CONFIRMATION"
    assert outcome.result_ref == "remote-results/1/result.json"
    assert client.finished[-1][0] == "AWAITING_CONFIRMATION"
    assert client.prepared is not None
    assert len(session.uploaded) == client.prepared["size_bytes"]
    assert session.put_headers["x-amz-meta-sha256"] == client.prepared["sha256"]
    assert client.confirmed_runtime == {
        "ok": True,
        "engine": "material-import",
        "note": "review_bundle_verified",
    }

    with zipfile.ZipFile(io.BytesIO(session.uploaded), "r") as review:
        meta = json.loads(review.read("meta.json"))
        rows = [
            json.loads(line)
            for line in review.read("review.jsonl").decode("utf-8").splitlines()
        ]
        assert meta["task_id"] == "material-task"
        assert meta["execution_generation"] == 1
        assert meta["target_prefix"] == "incoming/2026"
        assert {row["status"] for row in rows} == {"IMPORTABLE", "SKIPPED"}
        importable = next(row for row in rows if row["status"] == "IMPORTABLE")
        assert importable["object_key"] == "incoming/2026/camera/a.jpg"
        assert review.read(importable["payload_member"])

    execution_dir = tmp_path / "agent-state" / "executions" / "material-task" / "1"
    assert not execution_dir.exists()


def test_agent_material_runner_rejects_zip_slip_before_result_publication(tmp_path):
    zip_bytes = _input_zip(unsafe=True)
    client = FakeClient()
    session = FakeSession(zip_bytes)
    runner = AgentMaterialImportRunner(
        client,
        AgentExecutionWorkdir(tmp_path / "agent-state"),
        transfer_session=session,
        heartbeat_interval=60,
    )

    outcome = runner.run(_lease(zip_bytes))

    assert outcome.status == "FAILED"
    assert "ZIP safety validation failed" in outcome.error
    assert client.prepared is None
    assert session.uploaded == b""
    assert client.finished[-1][0] == "FAILED"
    assert not (tmp_path / "escape.jpg").exists()



def test_agent_material_runner_brokered_storage_scan_is_metadata_only(tmp_path):
    client = FakeClient()
    session = ScanSession(client.scan_image)
    runner = AgentMaterialImportRunner(
        client,
        AgentExecutionWorkdir(tmp_path / "agent-state"),
        transfer_session=session,
        heartbeat_interval=60,
    )
    lease = RemoteExecutionLease(
        task_id="material-storage-scan",
        kind="MATERIAL_IMPORT",
        project_id="project-one",
        generation=1,
        lease_token="lease-secret",
        lease_expires_at="2099-01-01T00:00:00+00:00",
        worker_id="agent:node-one",
        payload={
            "schema_version": 1,
            "task_kind": "MATERIAL_IMPORT",
            "transport": "object-storage-v1",
            "mode": "storage_scan",
            "import_format": "images",
            "dataset_yaml": "",
            "source": {
                "storage_source_id": "s3-target",
                "storage_type": "s3",
                "prefix": "incoming/2026",
                "recursive": True,
            },
            "target": {
                "storage_source_id": "s3-target",
                "storage_type": "s3",
                "target_prefix": "incoming/2026",
            },
            "output": {
                "type": "object",
                "storage_ref": {
                    "storage_source_id": "s3-target",
                    "object_key": "reviews/review.zip",
                    "file_name": "material-review.zip",
                    "content_type": "application/zip",
                },
                "upload_protocol": "prepare-after-local-hash-v1",
            },
        },
        assignment={},
        transport={},
    )

    outcome = runner.run(lease)

    assert outcome.status == "AWAITING_CONFIRMATION"
    assert client.finished[-1][0] == "AWAITING_CONFIRMATION"
    with zipfile.ZipFile(io.BytesIO(session.uploaded), "r") as review:
        meta = json.loads(review.read("meta.json"))
        row = json.loads(review.read("review.jsonl").decode("utf-8").strip())
        assert meta["mode"] == "storage_scan"
        assert meta["payload_mode"] == "source_reference"
        assert row["object_key"] == "incoming/2026/a.jpg"
        assert row["etag"] == '"etag-a"'
        assert row["payload_member"] == ""
        assert not any(name.startswith("files/") for name in review.namelist())


def test_agent_material_runner_reviews_coco_zip_and_publishes_detection_evidence(tmp_path):
    coco = {
        "images": [{"id": 1, "file_name": "a.jpg", "width": 40, "height": 30}],
        "annotations": [{"id": 1, "image_id": 1, "category_id": 7, "bbox": [4, 5, 20, 10]}],
        "categories": [{"id": 7, "name": "smoke"}],
    }
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("train/a.jpg", _image_bytes())
        archive.writestr("train/_annotations.coco.json", json.dumps(coco).encode("utf-8"))
    zip_bytes = stream.getvalue()

    client = FakeClient()
    session = FakeSession(zip_bytes)
    runner = AgentMaterialImportRunner(
        client,
        AgentExecutionWorkdir(tmp_path / "agent-state"),
        transfer_session=session,
        heartbeat_interval=60,
    )

    outcome = runner.run(_lease(zip_bytes, import_format="coco"))

    assert outcome.status == "AWAITING_CONFIRMATION"
    assert client.finished[-1][0] == "AWAITING_CONFIRMATION"
    with zipfile.ZipFile(io.BytesIO(session.uploaded), "r") as review:
        meta = json.loads(review.read("meta.json"))
        row = json.loads(review.read("review.jsonl").decode("utf-8").strip())
        annotations = [
            json.loads(line)
            for line in review.read("annotations/detection.jsonl").decode("utf-8").splitlines()
        ]
        assert meta["mode"] == "zip_scan"
        assert meta["import_format"] == "coco"
        assert meta["payload_mode"] == "embedded"
        assert row["object_key"] == "incoming/2026/train/a.jpg"
        assert row["payload_member"].startswith("files/")
        assert review.read(row["payload_member"])
        assert annotations[0]["object_key"] == "incoming/2026/train/a.jpg"
        assert annotations[0]["annotation_status"] == "annotated"
        assert annotations[0]["boxes"][0]["class_id"] == 7


def test_agent_material_runner_allows_root_scope_only_for_storage_rescan_intent(tmp_path):
    client = FakeClient()
    session = ScanSession(client.scan_image)
    runner = AgentMaterialImportRunner(
        client,
        AgentExecutionWorkdir(tmp_path / "agent-state"),
        transfer_session=session,
        heartbeat_interval=60,
    )
    payload = {
        "schema_version": 1,
        "task_kind": "MATERIAL_IMPORT",
        "transport": "object-storage-v1",
        "mode": "storage_scan",
        "intent": "storage_rescan",
        "import_format": "images",
        "dataset_yaml": "",
        "source": {
            "storage_source_id": "s3-target",
            "storage_type": "s3",
            "prefix": "",
            "recursive": True,
        },
        "target": {
            "storage_source_id": "s3-target",
            "storage_type": "s3",
            "target_prefix": "",
        },
        "output": {
            "type": "object",
            "storage_ref": {
                "storage_source_id": "s3-target",
                "object_key": "reviews/root-rescan.zip",
                "file_name": "material-review.zip",
                "content_type": "application/zip",
            },
            "upload_protocol": "prepare-after-local-hash-v1",
        },
    }
    lease = RemoteExecutionLease(
        task_id="material-root-rescan",
        kind="MATERIAL_IMPORT",
        project_id="project-one",
        generation=1,
        lease_token="lease-secret",
        lease_expires_at="2099-01-01T00:00:00+00:00",
        worker_id="agent:node-one",
        payload=payload,
        assignment={},
        transport={},
    )

    outcome = runner.run(lease)

    assert outcome.status == "AWAITING_CONFIRMATION"
    assert client.finished[-1][0] == "AWAITING_CONFIRMATION"
    with zipfile.ZipFile(io.BytesIO(session.uploaded), "r") as review:
        row = json.loads(review.read("review.jsonl").decode("utf-8").strip())
        assert row["object_key"] == "incoming/2026/a.jpg"
