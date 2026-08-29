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


def test_legacy_training_route_also_requires_strict_latest_iteration_base(client, seeded_project, monkeypatch, tmp_path):
    import app as app_module

    project_id, _ = seeded_project
    seen = {}

    def strict_spy(*args, **kwargs):
        seen.update(kwargs)
        return None

    monkeypatch.setattr(app_module, "_v54_iteration_base", strict_spy)
    monkeypatch.setattr(app_module, "_v48_dispatch_training_queues", lambda _project_id: None)
    monkeypatch.setattr(app_module, "resolve_ultralytics_model_path", lambda value: value)
    monkeypatch.setattr(
        app_module,
        "build_dataset",
        lambda _project_id, _payload: {
            "dataset": str(tmp_path),
            "data_yaml": str(tmp_path / "data.yaml"),
            "counts": {},
            "labels": [],
        },
    )

    response = client.post(
        f"/api/projects/{project_id}/train/start",
        json={
            "framework": "ultralytics",
            "algorithm": "yolo11n_det",
            "algorithm_asset_id": "asset-with-versions",
            "model": "yolo11n.pt",
            "epochs": 1,
            "imgsz": 320,
            "batch": 1,
            "device": "cpu",
        },
    )

    assert response.status_code == 200, response.text
    assert seen["strict_latest"] is True


def test_iteration_base_endpoint_does_not_fall_back_from_broken_latest(client, seeded_project, monkeypatch):
    import app as app_module

    project_id, _ = seeded_project
    algorithm = client.post(
        f"/api/v12/projects/{project_id}/algorithms",
        json={"name": "严格迭代基线", "industry": "测试", "algorithm_type": "yolo_ultralytics"},
    ).json()["algorithm"]
    previous = app_module.project_dir(project_id) / "previous.pt"
    previous.write_bytes(b"previous")
    latest = app_module.project_dir(project_id) / "latest.pt"
    # Deliberately leave the latest path missing: the endpoint must not silently
    # pick the older version or the mother model.
    algorithms = app_module.list_algorithms_internal(project_id)
    target = next(row for row in algorithms if row["id"] == algorithm["id"])
    target["versions"] = [
        {
            "id": "latest",
            "version_name": "20260828120000",
            "finished_at": "2026-08-28T12:00:00",
            "stored_path": str(latest),
            "artifact_verified": False,
        },
        {
            "id": "previous",
            "version_name": "20260827120000",
            "finished_at": "2026-08-27T12:00:00",
            "stored_path": str(previous),
            "artifact_verified": True,
        },
    ]
    app_module.save_algorithms_internal(project_id, algorithms)
    response = client.get(
        f"/api/v54/projects/{project_id}/algorithms/{algorithm['id']}/iteration-base?framework=ultralytics"
    )

    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "ITERATION_BASE_UNAVAILABLE"


def test_training_snapshot_randomly_assigns_selected_materials_to_experiment_split(client, seeded_project):
    import app as app_module

    project_id, train_image = seeded_project
    second = client.post(
        f"/api/projects/{project_id}/images",
        files=[("files", ("second.jpg", _image_bytes("gray"), "image/jpeg"))],
        data={"dataset_id": "default"},
    ).json()["uploaded"][0]
    for image, label, class_id, split in [
        (train_image, "fire", 0, "train"),
        (second, "smoke", 1, "val"),
    ]:
        assert client.post(
            f"/api/projects/{project_id}/annotations/{image['id']}",
            json={"boxes": [{"class_id": class_id, "label": label, "x1": 20, "y1": 20, "x2": 90, "y2": 90}]},
        ).status_code == 200
        assert client.patch(
            f"/api/v12/projects/{project_id}/images/{image['id']}", json={"split": split}
        ).status_code == 200

    payload = app_module.TrainReq(
        selected_image_ids=[train_image["id"], second["id"]],
        random_experiment_split=True,
        experiment_percent=50,
        seed=42,
    )
    build = app_module.build_yolo_dataset_v44(project_id, payload)
    selected = build["selected_ids"]

    assert len(selected["train"]) == 1
    assert len(selected["val"]) == 1
    assert set(selected["train"] + selected["val"]) == {train_image["id"], second["id"]}
    assert build["split_seed"] == 42


def test_training_rejects_random_pool_without_two_valid_annotated_materials(client, seeded_project, monkeypatch):
    import app as app_module

    project_id, image = seeded_project
    monkeypatch.setattr(app_module, "_v48_dispatch_training_queues", lambda _project_id: None)
    monkeypatch.setattr(app_module, "resolve_ultralytics_model_path", lambda value: value)

    response = client.post(
        f"/api/v12/projects/{project_id}/train/start",
        json={
            "framework": "ultralytics",
            "algorithm": "yolo11n_det",
            "model": "yolo11n.pt",
            "selected_image_ids": [image["id"], "not-a-real-image"],
            "random_experiment_split": True,
            "experiment_percent": 20,
        },
    )

    assert response.status_code == 400
    assert "训练集" in response.json()["detail"]
