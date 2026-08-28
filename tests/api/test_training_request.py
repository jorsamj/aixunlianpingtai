import io

from PIL import Image


def _image_bytes(color: str) -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", (128, 128), color).save(stream, format="JPEG")
    return stream.getvalue()


def test_training_job_locks_snapshot_base_and_requested_parameters(client, seeded_project, monkeypatch):
    import app as app_module

    project_id, train_image = seeded_project
    monkeypatch.setattr(app_module, "_v48_dispatch_training_queues", lambda _project_id: None)
    val_upload = client.post(
        f"/api/projects/{project_id}/images",
        files=[("files", ("val.jpg", _image_bytes("gray"), "image/jpeg"))],
        data={"dataset_id": "default"},
    ).json()
    val_image = val_upload["uploaded"][0]
    for image, label, class_id, split in [
        (train_image, "fire", 0, "train"),
        (val_image, "smoke", 1, "val"),
    ]:
        annotation = client.post(
            f"/api/projects/{project_id}/annotations/{image['id']}",
            json={"boxes": [{"class_id": class_id, "label": label, "x1": 20, "y1": 20, "x2": 90, "y2": 90}]},
        )
        assert annotation.status_code == 200
        assert client.patch(
            f"/api/v12/projects/{project_id}/images/{image['id']}", json={"split": split}
        ).status_code == 200
    algorithm_response = client.post(
        f"/api/v12/projects/{project_id}/algorithms",
        json={"name": "训练请求回归", "industry": "测试", "algorithm_type": "yolo_ultralytics", "remark": ""},
    )
    algorithm_id = algorithm_response.json()["algorithm"]["id"]

    response = client.post(
        f"/api/v12/projects/{project_id}/train/start",
        json={
            "framework": "ultralytics",
            "algorithm": "yolo11n_det",
            "algorithm_asset_id": algorithm_id,
            "model": "yolo11n.pt",
            "epochs": 3,
            "imgsz": 320,
            "batch": 2,
            "device": "cpu",
            "workers": 0,
            "optimizer": "AdamW",
            "lr0": 0.002,
            "weight_decay": 0.001,
            "seed": 42,
            "train_image_ids": [train_image["id"]],
            "val_image_ids": [val_image["id"]],
        },
    )

    assert response.status_code == 200, response.text
    job = response.json()["job"]
    assert job["model"] == job["base_model_path"]
    assert job["base_version_id"] is None
    assert job["base_selection_reason"] == "mother_model"
    assert len(job["snapshot_id"]) == 64
    expected = {
        "epochs": 3,
        "imgsz": 320,
        "batch": 2,
        "device": "cpu",
        "workers": 0,
        "optimizer": "AdamW",
        "lr0": 0.002,
        "weight_decay": 0.001,
        "seed": 42,
    }
    for key, value in expected.items():
        assert job["requested_train_params"][key] == value
    assert "mosaic" in job["requested_train_params"]
    assert "amp" in job["requested_train_params"]
