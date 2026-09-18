from pathlib import Path

import app as app_module
from platform_core.remote_execution_transport import RemoteExecutionTransportError
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


def test_deployment_test_creation_persists_portable_contract_when_transport_is_available(
    client, seeded_project, tmp_path, monkeypatch
):
    class FakeRemoteTransport:
        def stage_deployment_test(self, **kwargs):
            assert Path(kwargs["input_path"]).read_bytes() == b"real-image-bytes"
            return {
                "version": 1,
                "task_kind": "DEPLOYMENT_TEST",
                "transport": "object-storage-v1",
                "deployment": {
                    "framework": kwargs["framework"],
                    "runtime_format": kwargs["runtime_format"],
                    "confidence": kwargs["confidence"],
                    "input": {
                        "storage_source_id": "s3-main",
                        "object_key": "remote-execution/input.jpg",
                        "file_name": "input.jpg",
                        "size_bytes": 16,
                        "sha256": "a" * 64,
                        "content_type": "image/jpeg",
                    },
                    "model": {"type": "official", "reference": "yolo11n.pt"},
                    "output": {
                        "storage_source_id": "s3-main",
                        "object_key": "remote-execution/result.jpg",
                        "file_name": "result.jpg",
                        "content_type": "image/jpeg",
                    },
                },
            }

    monkeypatch.setattr(
        app_module,
        "_remote_execution_transport_service",
        lambda: FakeRemoteTransport(),
    )
    project_id, _model, task = _create_deployment_task(
        client, seeded_project, tmp_path, monkeypatch
    )
    stored = app_module.shared_task_artifacts().read_json(task["id"], "request.json")

    assert stored["remote_execution"]["version"] == 1
    assert stored["remote_execution"]["task_kind"] == "DEPLOYMENT_TEST"
    assert stored["remote_execution"]["transport"] == "object-storage-v1"
    # Legacy local fields remain for a local Worker, but the Agent start path
    # is now required to resolve a separate sanitized execution payload.
    assert Path(stored["input_path"]).is_file()
    assert stored["runner_path"].endswith("predict_ultralytics_runner.py")


def test_deployment_test_transport_error_does_not_publish_durable_task(
    client, seeded_project, tmp_path, monkeypatch
):
    class FailingRemoteTransport:
        def stage_deployment_test(self, **_kwargs):
            raise RemoteExecutionTransportError(
                "REMOTE_INPUT_UPLOAD_INVALID",
                "staged deployment input verification failed",
                502,
            )

    monkeypatch.setattr(
        app_module,
        "_remote_execution_transport_service",
        lambda: FailingRemoteTransport(),
    )
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
    monkeypatch.setattr(
        app_module,
        "_resolve_v61_test_model",
        lambda *args, **kwargs: resolution,
    )
    monkeypatch.setattr(
        app_module,
        "resolve_inference_python",
        lambda *args, **kwargs: str(Path(app_module.sys.executable)),
    )

    before = app_module.shared_task_repository().list(
        project_id=project_id,
        kinds=(TaskKind.DEPLOYMENT_TEST,),
        limit=100,
    )
    response = client.post(
        f"/api/v61/projects/{project_id}/deployment-tests",
        data={"model_name": "model.onnx", "model_source": "project"},
        files={"file": ("test.jpg", b"real-image-bytes", "image/jpeg")},
    )
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "REMOTE_INPUT_UPLOAD_INVALID"

    after = app_module.shared_task_repository().list(
        project_id=project_id,
        kinds=(TaskKind.DEPLOYMENT_TEST,),
        limit=100,
    )
    assert len(after.items) == len(before.items)


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
