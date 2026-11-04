import hashlib
import io
import json
from pathlib import Path

from fastapi import HTTPException, UploadFile
from PIL import Image
import pytest

import app as api


class FakeTasks:
    def __init__(self):
        self.records = {}
        self.created = 0

    def create(self, task):
        self.records[task.task_id] = task
        self.created += 1

    def get(self, task_id):
        return self.records.get(task_id)


class FakeArtifacts:
    def __init__(self):
        self.writes = {}

    def atomic_write_json(self, task_id, name, data):
        self.writes[(task_id, name)] = data


def _setup(monkeypatch, tmp_path):
    root = tmp_path / "deployment"
    job_dir = root / "jobs" / "j1"
    (job_dir / "source").mkdir(parents=True)
    (job_dir / "artifacts").mkdir(parents=True)
    pt = job_dir / "source" / "original.pt"
    onnx = job_dir / "artifacts" / "model.onnx"
    pt.write_bytes(b"frozen-source")
    onnx.write_bytes(b"frozen-onnx")
    job = {"id": "j1", "status": "blocked_by_hardware", "target": "sophon",
           "source_path": str(pt), "params": {"precision": "fp16", "input_color_order": "rgb"},
           "source_trace": {"sha256": api.sha256_file(pt)}}
    tasks, artifacts = FakeTasks(), FakeArtifacts()
    monkeypatch.setattr(api, "DATA_DIR", tmp_path)
    monkeypatch.setattr(api, "deploy_root", lambda project_id: root)
    monkeypatch.setattr(api, "_deploy_job_dir", lambda project_id, job_id: job_dir)
    monkeypatch.setattr(api, "_read_deploy_job", lambda project_id, job_id: job)
    monkeypatch.setattr(api, "shared_task_repository", lambda: tasks)
    monkeypatch.setattr(api, "shared_task_artifacts", lambda: artifacts)
    monkeypatch.setattr(api, "task_to_public", lambda task, repository: {"status": task.status.value})
    return root, tasks, artifacts


def _image(name="test.png", invalid=False):
    if invalid:
        return UploadFile(file=io.BytesIO(b"broken image"), filename=name)
    output = io.BytesIO()
    Image.new("RGB", (32, 32), (20, 40, 60)).save(output, format="PNG")
    output.seek(0)
    return UploadFile(file=output, filename=name)


def test_numeric_verification_has_one_durable_task_and_idempotent_retry(monkeypatch, tmp_path):
    root, tasks, artifacts = _setup(monkeypatch, tmp_path)
    first = api.v39_create_numeric_validation("p1", "j1", [_image()], request_id="stable-verification-1")
    second = api.v39_create_numeric_validation("p1", "j1", [_image()], request_id="stable-verification-1")
    assert first["id"] == second["id"]
    assert second["idempotent"] is True
    assert tasks.created == 1
    receipt = api.read_json(root / "numeric-validations" / first["id"] / "request.json", {})
    assert receipt["source_sha256"]
    assert receipt["onnx_sha256"] == api.sha256_file(root / "jobs" / "j1" / "artifacts" / "model.onnx")
    assert receipt["bmodel_expected"] is True
    assert receipt["bmodel_path"] == ""
    assert receipt["image_names"] == ["image_01.png"]
    assert artifacts.writes[(first["id"], "request.json")]["execution_mode"] == "numeric_verification"
    assert api.v39_get_numeric_validation("p1", "j1", first["id"])["id"] == first["id"]
    assert len(api.v39_list_numeric_validations("p1", "j1")["items"]) == 1


def test_conflicting_idempotency_receipt_returns_409_and_preserves_existing_task(monkeypatch, tmp_path):
    root, tasks, _ = _setup(monkeypatch, tmp_path)
    first = api.v39_create_numeric_validation("p1", "j1", [_image()], request_id="conflict-verification-01")
    path = root / "numeric-validations" / first["id"] / "request.json"
    receipt = api.read_json(path, {})
    receipt["request_id"] = "another-request-identity"
    path.write_text(json.dumps(receipt, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(HTTPException) as raised:
        api.v39_create_numeric_validation("p1", "j1", [_image()], request_id="conflict-verification-01")
    assert raised.value.status_code == 409
    assert path.is_file()
    assert tasks.created == 1


def test_orphaned_numeric_directory_fails_closed_without_deleting_evidence(monkeypatch, tmp_path):
    root, tasks, _ = _setup(monkeypatch, tmp_path)
    request_id = "orphan-verification-01"
    verification_id = "nv_" + hashlib.sha256(f"p1:j1:{request_id}".encode()).hexdigest()[:24]
    existing = root / "numeric-validations" / verification_id
    existing.mkdir(parents=True)
    (existing / "forensics.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(HTTPException) as raised:
        api.v39_create_numeric_validation("p1", "j1", [_image()], request_id=request_id)
    assert raised.value.status_code == 409
    assert (existing / "forensics.txt").read_text(encoding="utf-8") == "keep"
    assert tasks.created == 0


def test_corrupt_image_is_rejected_without_leaking_partial_files(monkeypatch, tmp_path):
    root, tasks, _ = _setup(monkeypatch, tmp_path)
    try:
        api.v39_create_numeric_validation("p1", "j1", [_image(invalid=True)], request_id="invalid-verification-1")
        assert False, "broken image should be rejected"
    except HTTPException as error:
        assert error.status_code == 422
    assert tasks.created == 0
    assert not list((root / "numeric-validations").glob("nv_*"))


def test_numeric_verification_identifier_cannot_traverse(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    try:
        api._numeric_conversion_dir("p1", "../../other")
        assert False, "traversal must reject"
    except HTTPException as error:
        assert error.status_code == 422


def test_numeric_report_cannot_be_reused_across_project(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    receipt = api.v39_create_numeric_validation("p1", "j1", [_image()], request_id="project-isolation-0001")
    try:
        api.v39_get_numeric_validation("another-project", "j1", receipt["id"])
        assert False, "different project should not receive the report"
    except HTTPException as error:
        assert error.status_code == 404
