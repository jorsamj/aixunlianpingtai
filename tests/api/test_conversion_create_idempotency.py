"""P0: a lost conversion-create HTTP response must not create a second job."""

import pytest
from fastapi import HTTPException

import app as api


def _request(**overrides):
    return api.DeployJobReq(
        source_id="version::a1::v1", target="onnx", resource_id="local-onnx",
        params={"opset": 12}, request_id="conversion-request-00001", **overrides,
    )


def test_conversion_create_replay_uses_durable_receipt(monkeypatch, tmp_path):
    monkeypatch.setattr(api, "DATA_DIR", tmp_path)
    submitted = []

    def create(project_id, payload):
        submitted.append(payload.request_id)
        job = {
            "id": api._deploy_request_job_id(project_id, payload.request_id),
            "project_id": project_id, "request_id": payload.request_id,
            "request_identity": api._deploy_request_identity(payload),
            "status": "queued", "source_id": payload.source_id,
        }
        api._write_deploy_job(project_id, job)
        return {"ok": True, "job": job}

    monkeypatch.setattr(api, "_v39_create_deploy_job_with_version_fence", create)
    monkeypatch.setattr(api, "get_project", lambda _: {"id": "p1"})
    monkeypatch.setattr(api, "_overlay_durable_deploy_job", lambda job: job)
    first = api.v39_create_deploy_job("p1", _request())
    repeated = api.v39_create_deploy_job("p1", _request())
    by_request = api.v39_conversion_job_by_request("p1", "conversion-request-00001")

    assert first["job"]["id"] == repeated["job"]["id"]
    assert repeated["idempotent"] is True
    assert submitted == ["conversion-request-00001"]
    assert by_request["found"] is True
    assert by_request["job"]["id"] == first["job"]["id"]


def test_conversion_replay_rejects_different_body(monkeypatch, tmp_path):
    monkeypatch.setattr(api, "DATA_DIR", tmp_path)
    monkeypatch.setattr(api, "get_project", lambda _: {"id": "p1"})
    request = _request()
    job_id = api._deploy_request_job_id("p1", request.request_id)
    api._write_deploy_job("p1", {
        "id": job_id, "project_id": "p1", "request_id": request.request_id,
        "request_identity": api._deploy_request_identity(request),
    })
    with pytest.raises(HTTPException) as raised:
        api.v39_create_deploy_job("p1", request.model_copy(update={"target": "rockchip"}))
    assert raised.value.status_code == 409


def test_conversion_partial_preparation_is_never_restarted(monkeypatch, tmp_path):
    monkeypatch.setattr(api, "DATA_DIR", tmp_path)
    monkeypatch.setattr(api, "get_project", lambda _: {"id": "p1"})
    request = _request()
    path = api._deploy_job_dir("p1", api._deploy_request_job_id("p1", request.request_id))
    (path / "source").mkdir(parents=True)
    with pytest.raises(HTTPException) as raised:
        api.v39_create_deploy_job("p1", request)
    assert raised.value.status_code == 409
    status = api.v39_conversion_job_by_request("p1", request.request_id)
    assert status == {"ok": True, "found": False, "pending": True}


def test_conversion_request_id_requires_safe_token():
    with pytest.raises(HTTPException) as raised:
        api._deploy_request_job_id("p1", "../escape")
    assert raised.value.status_code == 422


def test_legacy_conversion_request_id_is_optional():
    assert _request().request_id
    assert api.DeployJobReq(source_id="src", target="onnx", resource_id="local").request_id == ""
