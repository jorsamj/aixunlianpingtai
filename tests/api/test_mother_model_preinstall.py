from __future__ import annotations

import asyncio
import hashlib
from io import BytesIO

import pytest
from fastapi import HTTPException, UploadFile


def _upload(app_module, name: str, payload: bytes):
    return asyncio.run(
        app_module.upload_preinstalled_base_model(
            UploadFile(filename=name, file=BytesIO(payload))
        )
    )


def test_preinstall_is_durable_and_the_same_file_is_idempotent(tmp_path, monkeypatch):
    import app as platform
    monkeypatch.setattr(platform, "DATA_DIR", tmp_path)
    monkeypatch.setattr(platform, "get_active_ultralytics_env", lambda: {})
    monkeypatch.setattr(platform, "_discovery_cache", lambda: None)
    payload = b"trusted-model-fixture" * 128
    uploaded = _upload(platform, "yolo11n.pt", payload)
    assert uploaded["model_status"] == "FOUND"
    assert uploaded["size_bytes"] == len(payload)
    assert uploaded["sha256"] == hashlib.sha256(payload).hexdigest()
    assert uploaded["reused"] is False
    path = tmp_path / "models" / "yolo11n.pt"
    assert path.read_bytes() == payload

    repeated = _upload(platform, "yolo11n.pt", payload)
    assert repeated["reused"] is True
    assert path.read_bytes() == payload
    assert platform._ready_ultralytics_mother_model("project-test", "yolo11n.pt") == str(path.resolve())
    rows = platform.list_base_models().get("items", [])
    assert any(row.get("source") == "preinstalled" and row.get("value") == str(path.resolve()) for row in rows)


def test_preinstalled_weight_never_overwrites_another_digest(tmp_path, monkeypatch):
    import app as platform
    monkeypatch.setattr(platform, "DATA_DIR", tmp_path)
    first = b"first" * 256
    _upload(platform, "base.pt", first)
    with pytest.raises(HTTPException) as captured:
        _upload(platform, "base.pt", b"different" * 256)
    assert captured.value.status_code == 409
    assert (tmp_path / "models" / "base.pt").read_bytes() == first
    assert not list((tmp_path / "models").glob("*.model-upload"))


@pytest.mark.parametrize("filename", [
    "../yolo11n.pt", "/tmp/yolo11n.pt", "bad.onnx", "weights/other.pt", ".secret.pt",
])
def test_preinstall_rejects_unsupported_and_unsafe_names(tmp_path, monkeypatch, filename):
    import app as platform
    monkeypatch.setattr(platform, "DATA_DIR", tmp_path)
    with pytest.raises(HTTPException) as captured:
        _upload(platform, filename, b"file" * 512)
    assert captured.value.status_code == 422


def test_training_requires_available_mother_before_creating_job(tmp_path, monkeypatch):
    import app as platform
    monkeypatch.setattr(platform, "DATA_DIR", tmp_path)
    monkeypatch.setattr(platform, "get_active_ultralytics_env", lambda: {})
    monkeypatch.setattr(platform, "_discovery_cache", lambda: None)
    with pytest.raises(HTTPException) as captured:
        platform._ready_ultralytics_mother_model("project-test", "yolo11n.pt")
    assert captured.value.status_code == 409
    assert "预置" in str(captured.value.detail)


def test_too_small_model_rejected_without_publishing_model(tmp_path, monkeypatch):
    import app as platform
    monkeypatch.setattr(platform, "DATA_DIR", tmp_path)
    with pytest.raises(HTTPException) as captured:
        _upload(platform, "tiny.pt", b"hi")
    assert captured.value.status_code == 422
    assert not (tmp_path / "models" / "tiny.pt").exists()
