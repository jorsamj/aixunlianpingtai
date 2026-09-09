from pathlib import Path

import app as app_module


def test_deployment_test_upload_creates_persistent_worker_task(client, seeded_project, tmp_path, monkeypatch):
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
    task = response.json()
    assert task["status"] == "QUEUED"
    stored = app_module.shared_task_artifacts().read_json(task["id"], "request.json")
    assert Path(stored["input_path"]).read_bytes() == b"real-image-bytes"
    assert stored["model_path"] == str(model)
