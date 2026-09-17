from pathlib import Path

import app as app_module
from platform_core.task_runtime import TaskKind


def _create_deployment_task(client, seeded_project, tmp_path, monkeypatch):
    project_id, _image = seeded_project
    model = tmp_path / "model.onnx"
    model.write_bytes(b"onnx-test-model")
    resolution = app_module.ModelResolution(
        status="FOUND",
        path=model,
        reference=model.name,
        source="project",
        downloadable=False,
        environment_status="AVAILABLE",
        searched_locations=(str(model),),
    )
    monkeypatch.setattr(app_module, "_resolve_v61_test_model", lambda *args, **kwargs: resolution)
    monkeypatch.setattr(app_module, "resolve_inference_python", lambda *args, **kwargs: str(Path(app_module.sys.executable)))
    response = client.post(
        f"/api/v61/projects/{project_id}/deployment-tests",
        data={"model_name": "model.onnx", "model_source": "project", "inference_framework": "ultralytics"},
        files={"file": ("test.jpg", b"real-image-bytes", "image/jpeg")},
    )
    assert response.status_code == 202, response.text
    return project_id, model, response.json()


def test_deployment_test_upload_creates_persistent_worker_task(client, seeded_project, tmp_path, monkeypatch):
    project_id, model, task = _create_deployment_task(client, seeded_project, tmp_path, monkeypatch)
    assert task["status"] == "QUEUED"
    stored = app_module.shared_task_artifacts().read_json(task["id"], "request.json")
    assert Path(stored["input_path"]).read_bytes() == b"real-image-bytes"
    assert stored["model_path"] == str(model)


def test_deployment_test_business_projection_preserves_durable_resource_wait_truth(
    client, seeded_project, tmp_path, monkeypatch
):
    project_id, _model, created = _create_deployment_task(client, seeded_project, tmp_path, monkeypatch)
    repository = app_module.shared_task_repository()

    def deny(_database, _candidate, _worker_id, _token, _expires_at, _now):
        return False, "DEPLOYMENT_RUNTIME_BUSY"

    assert repository.claim_next(
        "deployment-worker",
        [TaskKind.DEPLOYMENT_TEST],
        {"deployment.runtime"},
        admission=deny,
    ) is None

    unified_response = client.get(f"/api/v62/projects/{project_id}/tasks/{created['id']}")
    unified_response.raise_for_status()
    unified = unified_response.json()
    assert unified["status"] == "WAITING_RESOURCE"
    assert unified["persisted_status"] == "QUEUED"
    assert isinstance(unified["resource_queue_position"], int)
    assert unified["resource_queue_position"] >= 1
    assert unified["resource_wait_reason"] == "DEPLOYMENT_RUNTIME_BUSY"

    business_response = client.get(f"/api/v61/projects/{project_id}/deployment-tests/{created['id']}")
    business_response.raise_for_status()
    business = business_response.json()
    assert business["status"] == unified["status"]
    assert business["persisted_status"] == unified["persisted_status"]
    assert business["resource_queue_position"] == unified["resource_queue_position"]
    assert business["resource_wait_reason"] == unified["resource_wait_reason"]
    assert business["worker_id"] == unified["worker_id"]
    assert business["progress"] == unified["progress_percent"]
    assert business["stage"] == unified["phase"]
