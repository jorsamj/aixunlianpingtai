from pathlib import Path

import app as app_module
from platform_core.remote_execution_transport import RemoteExecutionTransportError
from platform_core.task_runtime import TaskKind


def _create_deployment_task(client, seeded_project, tmp_path, monkeypatch, extra_data=None):
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
    payload = {"model_name": "model.onnx", "model_source": "project", "inference_framework": "ultralytics"}
    payload.update(extra_data or {})
    response = client.post(
        f"/api/v61/projects/{project_id}/deployment-tests",
        data=payload,
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
    error = response.json()
    assert error["ok"] is False
    assert error["code"] == "REMOTE_INPUT_UPLOAD_INVALID"
    assert error["message"] == "远程部署准备失败"
    assert "verification failed" in error["detail"]

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



def test_detection_batch_metadata_history_and_review_are_durable(
    client, seeded_project, tmp_path, monkeypatch
):
    batch_id = "bench-api-test-1"
    project_id, _model, task = _create_deployment_task(
        client,
        seeded_project,
        tmp_path,
        monkeypatch,
        extra_data={
            "detection_batch_id": batch_id,
            "detection_item_index": "0",
            "detection_item_total": "1",
            "detection_side": "A",
            "model_label": "算法版本：烟火 / v1",
            "model_source": "algorithm_version",
            "algorithm_id": "algo-feedback",
            "version_id": "ver-feedback",
            "original_filename": "folder/fire-001.jpg",
        },
    )
    request = app_module.shared_task_artifacts().read_json(task["id"], "request.json")
    assert request["detection_batch"] == {
        "batch_id": batch_id,
        "item_index": 0,
        "item_total": 1,
        "side": "A",
        "original_filename": "fire-001.jpg",
    }
    assert request["model_identity"]["label"] == "算法版本：烟火 / v1"
    assert request["input_image_url"].endswith(f"/predictions/{task['id']}/input.jpg")

    blocked = client.post(
        f"/api/v64/projects/{project_id}/detection-batches/{batch_id}/items/0/review",
        json={"review": "correct", "note": "尚未结束"},
    )
    assert blocked.status_code == 409
    assert "尚未结束" in blocked.text

    repository = app_module.shared_task_repository()
    # This integration test shares the durable task repository with earlier cases.
    # Promote only this task through the real queue contract instead of assuming
    # it happens to be the next previously-created deployment task.
    promoted = repository.promote(task["id"])
    assert promoted.task_id == task["id"]
    lease = repository.claim_next(
        "deployment-batch-test-worker",
        [TaskKind.DEPLOYMENT_TEST],
        {"deployment.runtime"},
    )
    assert lease is not None
    assert lease.task.task_id == task["id"]
    result_ref = "result.json"
    app_module.shared_task_artifacts().atomic_write_json(
        task["id"],
        result_ref,
        {
            "task_id": task["id"],
            "image_url": f"/data/projects/{project_id}/predictions/{task['id']}/result.jpg",
            "detections": [{
                "label": "smoke", "confidence": 0.91,
                "x1": 5, "y1": 6, "x2": 50, "y2": 60,
            }],
            "inference_ms": 12.5,
            "total_elapsed_ms": 18.0,
        },
    )
    repository.finish(
        task["id"],
        lease.lease_token,
        app_module.TaskStatus.SUCCEEDED,
        result_ref=result_ref,
    )

    # A completed formal algorithm-version detection can be explicitly promoted
    # to the existing v63 human-review evidence chain. The promotion is a
    # separate action from running detection and is idempotent.
    Path(request["output_path"]).write_bytes(b"result-image")
    monkeypatch.setattr(
        app_module,
        "_algorithm_version_for_action",
        lambda project_id, algorithm_id, version_id: (
            {"id": algorithm_id},
            {"id": version_id, "stored_path": request["model_path"]},
        ),
    )
    tested_model_sha = app_module.sha256_file(Path(request["model_path"]))
    assert request["model_identity"]["model_sha256"] == tested_model_sha
    monkeypatch.setattr(
        app_module,
        "_online_feedback_version_model_sha256",
        lambda _version: tested_model_sha,
    )
    monkeypatch.setattr(
        app_module,
        "image_info",
        lambda _path: {"width": 96, "height": 72},
    )
    evidence = client.post(
        f"/api/v64/projects/{project_id}/deployment-tests/{task['id']}/feedback-evidence"
    )
    assert evidence.status_code == 200, evidence.text
    promoted = evidence.json()
    assert promoted["feedback_eligible"] is True
    assert promoted["prediction_id"] == task["id"]
    assert promoted["algorithm_id"] == "algo-feedback"
    assert promoted["version_id"] == "ver-feedback"
    assert promoted["detections"][0]["label"] == "smoke"

    repeated_evidence = client.post(
        f"/api/v64/projects/{project_id}/deployment-tests/{task['id']}/feedback-evidence"
    )
    assert repeated_evidence.status_code == 200, repeated_evidence.text
    assert repeated_evidence.json()["idempotent"] is True

    detail = client.get(
        f"/api/v64/projects/{project_id}/detection-batches/{batch_id}"
    )
    assert detail.status_code == 200, detail.text
    batch = detail.json()["batch"]
    assert batch["batch_id"] == batch_id
    assert batch["total"] == 1
    assert batch["completed_items"] == 1
    assert batch["failed_items"] == 0
    assert batch["items"][0]["original_filename"] == "fire-001.jpg"
    assert batch["items"][0]["models"]["A"]["detections"][0]["label"] == "smoke"
    assert batch["items"][0]["models"]["A"]["model"]["label"] == "算法版本：烟火 / v1"
    assert batch["items"][0]["models"]["A"]["input_image_url"].endswith(
        f"/predictions/{task['id']}/input.jpg"
    )

    review = client.post(
        f"/api/v64/projects/{project_id}/detection-batches/{batch_id}/items/0/review",
        json={"review": "box_inaccurate", "note": "框偏大"},
    )
    assert review.status_code == 200, review.text
    assert review.json()["review"]["review"] == "box_inaccurate"

    repeated = client.get(
        f"/api/v64/projects/{project_id}/detection-batches/{batch_id}"
    ).json()["batch"]
    assert repeated["items"][0]["review"]["review"] == "box_inaccurate"
    assert repeated["items"][0]["review"]["note"] == "框偏大"

    history = client.get(
        f"/api/v64/projects/{project_id}/detection-batches?limit=12"
    )
    assert history.status_code == 200, history.text
    row = next(item for item in history.json()["items"] if item["batch_id"] == batch_id)
    assert row["completed_items"] == 1
    assert row["created_items"] == 1


def test_detection_batch_rejects_invalid_identity(client, seeded_project, tmp_path, monkeypatch):
    project_id, _image = seeded_project
    model = tmp_path / "model-invalid.onnx"
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
        data={
            "model_name": "model-invalid.onnx",
            "model_source": "project",
            "detection_batch_id": "bad batch id!",
            "detection_item_index": "0",
            "detection_item_total": "1",
            "detection_side": "A",
        },
        files={"file": ("test.jpg", b"real-image-bytes", "image/jpeg")},
    )
    assert response.status_code == 400
    assert "批次 ID" in response.text
