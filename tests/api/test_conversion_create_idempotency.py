"""P0: a lost conversion-create HTTP response must not create a second job."""
from platform_core.conversion_management_service import ConversionManagementService

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

    monkeypatch.setattr(ConversionManagementService, "_v39_create_deploy_job_with_version_fence", staticmethod(create))
    monkeypatch.setattr(api, "get_project", lambda _: {"id": "p1"})
    monkeypatch.setattr(ConversionManagementService, "_overlay_durable_deploy_job", staticmethod(lambda job: job))
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


def test_remaining_conversion_management_effective_http_contract():
    import re
    import app as application
    from types import SimpleNamespace
    try:
        from fastapi.routing import iter_route_contexts
        contexts = list(iter_route_contexts(application.app.routes))
    except ImportError:
        contexts = [SimpleNamespace(path=r.path, original_route=r) for r in application.app.routes if hasattr(r, "path")]
    expected = [
        ('post', '/api/v30/projects/{project_id}/model-export', 'v30_export_model_package', 'ModelExportReq', 'conversion_management'),
        ('post', '/api/v32/projects/{project_id}/model-export', 'v32_export_model_package', 'ModelExportReq', 'conversion_management'),
        ('get', '/api/v39/deploy/resources', 'v39_list_deploy_resources', None, 'conversion_management'),
        ('post', '/api/v39/deploy/resources', 'v39_create_deploy_resource', 'DeployResourceReq', 'conversion_management'),
        ('put', '/api/v39/deploy/resources/{resource_id}', 'v39_update_deploy_resource', 'DeployResourceReq', 'conversion_management'),
        ('delete', '/api/v39/deploy/resources/{resource_id}', 'v39_delete_deploy_resource', None, 'conversion_management'),
        ('post', '/api/v39/deploy/resources/{resource_id}/detect', 'v39_detect_deploy_resource', None, 'conversion_management'),
        ('post', '/api/v39/deploy/resources/{resource_id}/detect/start', 'v39_start_deploy_resource_detection', None, 'conversion_management'),
        ('get', '/api/v39/deploy/resources/{resource_id}/detect/status', 'v39_conversion_resource_detection_status', None, 'conversion_management'),
        ('post', '/api/v39/deploy/local/auto-detect', 'v39_detect_local_deploy_resources', None, 'conversion_management'),
        ('get', '/api/v39/projects/{project_id}/deploy/source-models', 'v39_deploy_source_models', None, 'conversion_management'),
        ('post', '/api/v39/projects/{project_id}/deploy/resolve', 'v39_resolve_conversion', 'DeployJobReq', 'conversion_management'),
        ('post', '/api/v39/projects/{project_id}/deploy/jobs', 'v39_create_deploy_job', 'DeployJobReq', 'conversion_management'),
        ('get', '/api/v39/projects/{project_id}/deploy/jobs/by-request/{request_id}', 'v39_conversion_job_by_request', None, 'conversion_management'),
        ('get', '/api/v39/projects/{project_id}/deploy/jobs/{job_id}/hardware-tests/preflight', 'v39_rknn_hardware_test_preflight', None, 'conversion_management'),
        ('get', '/api/v39/projects/{project_id}/deploy/jobs/{job_id}/hardware-tests/report', 'v39_rknn_hardware_acceptance_report', None, 'conversion_management'),
        ('post', '/api/v39/projects/{project_id}/deploy/jobs/{job_id}/hardware-tests', 'v39_create_rknn_hardware_test', None, 'conversion_management'),
        ('get', '/api/v39/projects/{project_id}/deploy/jobs', 'v39_list_deploy_jobs', None, 'conversion_management'),
        ('get', '/api/v39/projects/{project_id}/deploy/jobs/{job_id}', 'v39_get_deploy_job', None, 'conversion_management'),
        ('get', '/api/v39/projects/{project_id}/deploy/jobs/{job_id}/numeric-validations', 'v39_list_numeric_validations', None, 'conversion_management'),
        ('get', '/api/v39/projects/{project_id}/deploy/jobs/{job_id}/numeric-validations/{verification_id}', 'v39_get_numeric_validation', None, 'conversion_management'),
        ('post', '/api/v39/projects/{project_id}/deploy/jobs/{job_id}/numeric-validations', 'v39_create_numeric_validation', None, 'conversion_management'),
        ('get', '/api/v39/projects/{project_id}/deploy/jobs/{job_id}/log', 'v39_deploy_job_log', None, 'conversion_management'),
        ('post', '/api/v39/projects/{project_id}/deploy/jobs/{job_id}/stop', 'v39_stop_deploy_job', None, 'conversion_management'),
        ('delete', '/api/v39/projects/{project_id}/deploy/jobs/{job_id}', 'v39_delete_deploy_job', None, 'conversion_management'),
        ('get', '/api/v39/projects/{project_id}/deploy/jobs/{job_id}/package', 'v39_download_deploy_package', None, 'conversion_management'),
        ('get', '/api/v42/projects/{project_id}/algorithms/{algorithm_id}/versions/{version_id}/deployments', 'v423_version_deployments', None, 'conversion_management'),
        ('post', '/api/v61/projects/{project_id}/deployment-tests', 'create_deployment_test', None, 'deployment_validation'),
        ('get', '/api/v61/projects/{project_id}/deployment-test-creations/{creation_id}', 'get_deployment_creation', None, 'deployment_validation'),
        ('post', '/api/v61/projects/{project_id}/deployment-test-creations/{creation_id}/recover', 'recover_deployment_creation', None, 'deployment_validation'),
        ('get', '/api/v61/projects/{project_id}/deployment-tests/{task_id}', 'get_deployment_test', None, 'deployment_validation'),
        ('post', '/api/v61/projects/{project_id}/deployment-tests/{task_id}/retry', 'retry_deployment_test', None, 'deployment_validation'),
        ('post', '/api/v61/projects/{project_id}/deployment-tests/{task_id}/cancel', 'cancel_deployment_test', None, 'deployment_validation'),
        ('post', '/api/v64/projects/{project_id}/deployment-tests/{task_id}/feedback-evidence', 'promote_deployment_test_to_feedback_evidence', None, 'deployment_validation'),
    ]
    schema = application.app.openapi()
    for method, path, name, payload, owner in expected:
        operation = schema["paths"][path][method]
        assert operation["operationId"] == re.sub(r"\W", "_", name + path) + "_" + method
        matches = [c.original_route for c in contexts if c.path == path and method.upper() in getattr(c.original_route, "methods", set())]
        assert len(matches) == 1
        assert matches[0].endpoint.__module__ == "platform_core." + owner + "_api"
        if payload:
            assert operation["requestBody"]["content"]["application/json"]["schema"]["$ref"] == "#/components/schemas/" + payload
