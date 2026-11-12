"""Regression: the legacy remote uploader must not treat an empty config path as '.'."""

import io
import json
import hashlib
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest

import app as api


def _probe_remote_upload(tmp_path, monkeypatch, params, *, source_override=None):
    job_dir = tmp_path / "remote-job"
    job_dir.mkdir()
    source = job_dir / "source.onnx"
    source.write_bytes(b"fixture-model")
    api.write_json(job_dir / "job.json", {
        "id": "remote-fixture",
        "resource_id": "remote-fixture-resource",
        "source_path": str(source) if source_override is None else source_override,
        "target": "onnx",
        "params": params,
        "status": "queued",
    })
    monkeypatch.setattr(api, "_deploy_job_dir", lambda _project, _job_id: job_dir)
    monkeypatch.setattr(api, "_deploy_resource_by_id", lambda _resource_id: {
        "base_url": "https://remote-fixture.invalid", "api_key": "fixture-key",
    })
    monkeypatch.setattr(
        api, "request_external_auto_publish_for_conversion_if_enabled",
        lambda **_kwargs: None,
    )

    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("converted.onnx", b"fixture-result")
    uploads = []

    def fake_post(_url, *, files, **_kwargs):
        uploads.append({name: part[1].read() for name, part in files.items()})
        return SimpleNamespace(ok=True, text="", json=lambda: {"job_id": "remote-fixture-id"})

    def fake_get(url, **_kwargs):
        if url.endswith("/log"):
            return SimpleNamespace(ok=True, text="remote fixture log")
        if url.endswith("/artifacts.zip"):
            return SimpleNamespace(ok=True, content=archive.getvalue())
        return SimpleNamespace(
            ok=True, text="",
            json=lambda: {"status": "done", "stage": "mocked remote completion", "progress": 100},
        )

    monkeypatch.setattr(api.requests, "post", fake_post)
    monkeypatch.setattr(api.requests, "get", fake_get)
    api._sync_remote_deploy_job("project-fixture", "remote-fixture")
    return json.loads((job_dir / "job.json").read_text(encoding="utf-8")), uploads


@pytest.mark.parametrize("config", [None, "", "  ", "omitted"])
def test_blank_config_does_not_upload_current_directory(tmp_path, monkeypatch, config):
    params = {} if config == "omitted" else {"config_path": config}
    job, uploads = _probe_remote_upload(tmp_path, monkeypatch, params)
    assert job["status"] == "done", job.get("error")
    assert uploads == [{"source_model": b"fixture-model"}]
    assert {entry["name"] for entry in job["outputs"]} == {"converted.onnx"}


def test_valid_explicit_config_uploads_normally(tmp_path, monkeypatch):
    config = tmp_path / "model.yml"
    config.write_bytes(b"model: fixture")
    job, uploads = _probe_remote_upload(tmp_path, monkeypatch, {"config_path": str(config)})
    assert job["status"] == "done", job.get("error")
    assert uploads == [{"source_model": b"fixture-model", "config_file": b"model: fixture"}]


@pytest.mark.parametrize("kind", ["dot", "directory", "missing"])
def test_directory_or_missing_config_fails_before_upload(tmp_path, monkeypatch, kind):
    config = "." if kind == "dot" else str(
        tmp_path if kind == "directory" else tmp_path / "missing-model.yml"
    )
    job, uploads = _probe_remote_upload(tmp_path, monkeypatch, {"config_path": config})
    assert job["status"] == "failed"
    assert "远程转换配置文件不存在或不是有效文件" in job["error"]
    assert "Is a directory" not in job["error"]
    assert uploads == []


def test_blank_source_fails_before_upload(tmp_path, monkeypatch):
    job, uploads = _probe_remote_upload(tmp_path, monkeypatch, {}, source_override="")
    assert job["status"] == "failed"
    assert "远程转换源模型不存在或不是有效文件" in job["error"]
    assert uploads == []



def test_remote_receipt_uses_utc_and_freezes_real_output_identity(tmp_path, monkeypatch):
    job, uploads = _probe_remote_upload(tmp_path, monkeypatch, {})
    assert job["status"] == "done"
    stamp = datetime.fromisoformat(job["conversion_finished_at"])
    assert stamp.tzinfo is not None and stamp.utcoffset().total_seconds() == 0
    assert job["finished_at"] == job["conversion_finished_at"]
    assert job["conversion_completion_source"] == "local_artifact_receipt_utc"
    output = next(row for row in job["outputs"] if row["name"] == "converted.onnx")
    assert output["sha256"] == hashlib.sha256(b"fixture-result").hexdigest()
    assert output["size_bytes"] == len(b"fixture-result")
    assert output["rel"] == "artifacts/converted.onnx"
    assert uploads == [{"source_model": b"fixture-model"}]
