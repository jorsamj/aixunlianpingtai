import io

import pytest
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
    assert job["queue_priority"] == 50
    assert job["priority_scheme"] == "lower_number_first"
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


def test_product_training_ignores_requested_mother_model_when_latest_version_exists(client, seeded_project, monkeypatch):
    import app as app_module

    project_id, train_image = seeded_project
    monkeypatch.setattr(app_module, "_v48_dispatch_training_queues", lambda _project_id: None)
    monkeypatch.setattr(app_module, "_v54_validate_iteration_artifact", lambda _path, _framework: True)
    val_image = client.post(
        f"/api/projects/{project_id}/images",
        files=[("files", ("iteration-val.jpg", _image_bytes("gray"), "image/jpeg"))],
        data={"dataset_id": "default"},
    ).json()["uploaded"][0]
    for image, label, class_id, split in [
        (train_image, "fire", 0, "train"),
        (val_image, "smoke", 1, "val"),
    ]:
        assert client.post(
            f"/api/projects/{project_id}/annotations/{image['id']}",
            json={"boxes": [{"class_id": class_id, "label": label, "x1": 10, "y1": 10, "x2": 90, "y2": 90}]},
        ).status_code == 200
        assert client.patch(
            f"/api/v12/projects/{project_id}/images/{image['id']}", json={"split": split}
        ).status_code == 200
    algorithm = client.post(
        f"/api/v12/projects/{project_id}/algorithms",
        json={"name": "严格最新版本训练", "algorithm_type": "yolo_ultralytics"},
    ).json()["algorithm"]
    latest_model = app_module.project_dir(project_id) / "latest-iteration.pt"
    latest_model.write_bytes(b"latest")
    rows = app_module.list_algorithms_internal(project_id)
    target = next(row for row in rows if row["id"] == algorithm["id"])
    target["versions"] = [{
        "id": "latest-version",
        "version_name": "20260830120000",
        "finished_at": "2026-08-30T12:00:00",
        "stored_path": str(latest_model),
        "artifact_verified": True,
        "training_status": "SUCCEEDED",
        "trainable": True,
        "framework": "ultralytics",
    }]
    app_module.save_algorithms_internal(project_id, rows)

    response = client.post(
        f"/api/v12/projects/{project_id}/train/start",
        json={
            "framework": "ultralytics",
            "algorithm": "yolo11n_det",
            "algorithm_asset_id": algorithm["id"],
            "model": "yolo11n.pt",
            "train_image_ids": [train_image["id"]],
            "val_image_ids": [val_image["id"]],
        },
    )

    assert response.status_code == 200, response.text
    job = response.json()["job"]
    assert job["base_version_id"] == "latest-version"
    assert job["base_selection_reason"] == "latest_verified_version"
    assert job["model"] == str(latest_model.resolve())


def test_iteration_base_endpoint_ignores_failed_attempt_and_uses_latest_success(client, seeded_project, monkeypatch):
    import app as app_module

    project_id, _ = seeded_project
    monkeypatch.setattr(app_module, "_v54_validate_iteration_artifact", lambda _path, _framework: True)
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
            "training_status": "FAILED",
            "trainable": False,
            "framework": "ultralytics",
        },
        {
            "id": "previous",
            "version_name": "20260827120000",
            "finished_at": "2026-08-27T12:00:00",
            "stored_path": str(previous),
            "artifact_verified": True,
            "training_status": "SUCCEEDED",
            "trainable": True,
            "framework": "ultralytics",
        },
    ]
    app_module.save_algorithms_internal(project_id, algorithms)
    response = client.get(
        f"/api/v54/projects/{project_id}/algorithms/{algorithm['id']}/iteration-base?framework=ultralytics"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["base"]["version_id"] == "previous"


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

    algorithm = client.post(
        f"/api/v12/projects/{project_id}/algorithms",
        json={"name": "素材不足回归", "algorithm_type": "yolo_ultralytics"},
    ).json()["algorithm"]
    response = client.post(
        f"/api/v12/projects/{project_id}/train/start",
        json={
            "framework": "ultralytics",
            "algorithm": "yolo11n_det",
            "algorithm_asset_id": algorithm["id"],
            "model": "yolo11n.pt",
            "selected_image_ids": [image["id"], "not-a-real-image"],
            "random_experiment_split": True,
            "experiment_percent": 20,
        },
    )

    assert response.status_code == 400
    assert "训练集" in response.json()["detail"]


def test_product_training_route_rejects_unknown_algorithm_asset(client, seeded_project):
    project_id, _ = seeded_project
    response = client.post(
        f"/api/v12/projects/{project_id}/train/start",
        json={
            "framework": "ultralytics",
            "algorithm": "yolo11n_det",
            "algorithm_asset_id": "not-a-real-algorithm",
            "model": "yolo11n.pt",
        },
    )

    assert response.status_code == 404
    assert "算法" in response.json()["detail"]


def test_success_without_verified_model_is_not_archived_as_algorithm_version(client, seeded_project):
    import app as app_module

    project_id, _ = seeded_project
    algorithm = client.post(
        f"/api/v12/projects/{project_id}/algorithms",
        json={"name": "无产物不归档", "algorithm_type": "yolo_ultralytics"},
    ).json()["algorithm"]
    job = {
        "id": "missing-artifact",
        "status": "completed",
        "asset_algorithm_id": algorithm["id"],
        "framework": "ultralytics",
        "artifact_verified": False,
    }

    assert app_module._v48_archive_training_version(project_id, job) is None
    stored = next(
        row for row in app_module.list_algorithms_internal(project_id) if row["id"] == algorithm["id"]
    )
    assert stored["versions"] == []


def test_explicit_split_training_route_only_enqueues_durable_task(client, seeded_project, monkeypatch):
    import app as app_module
    from platform_core.task_runtime import TaskKind, TaskStatus

    project_id, _ = seeded_project
    algorithm = client.post(
        f"/api/v12/projects/{project_id}/algorithms",
        json={"name": "异步训练请求", "algorithm_type": "yolo_ultralytics"},
    ).json()["algorithm"]
    monkeypatch.setattr(
        app_module,
        "_v48_dispatch_training_queues",
        lambda *_args: (_ for _ in ()).throw(AssertionError("web route dispatched training")),
    )
    response = client.post(
        f"/api/v12/projects/{project_id}/train/start",
        json={
            "framework": "ultralytics",
            "algorithm_asset_id": algorithm["id"],
            "model": "yolo11n.pt",
            "split_mode": "independent_test_set",
            "train_dataset_ids": ["train-ds"],
            "test_dataset_ids": ["test-ds"],
            "validation_percent": 20,
            "experiment_percent": None,
            "queue_priority": 7,
        },
    )

    assert response.status_code == 202, response.text
    task = response.json()["task"]
    assert task["kind"] == "TRAINING"
    assert task["status"] == "QUEUED"
    persisted = app_module.shared_task_repository().get(task["id"])
    assert persisted is not None
    assert persisted.kind is TaskKind.TRAINING
    assert persisted.status is TaskStatus.QUEUED
    assert persisted.priority == 7


@pytest.mark.parametrize("percent", [1, 12.5, 37, 99])
def test_explicit_random_test_percentage_is_accepted(client, seeded_project, percent):
    project_id, _ = seeded_project
    algorithm = client.post(
        f"/api/v12/projects/{project_id}/algorithms",
        json={"name": f"随机试验集 {percent}", "algorithm_type": "yolo_ultralytics"},
    ).json()["algorithm"]
    response = client.post(
        f"/api/v12/projects/{project_id}/train/start",
        json={
            "framework": "ultralytics",
            "algorithm_asset_id": algorithm["id"],
            "model": "yolo11n.pt",
            "split_mode": "random_test_from_training_pool",
            "train_dataset_ids": ["source"],
            "test_dataset_ids": [],
            "experiment_percent": percent,
            "validation_percent": 20,
        },
    )
    assert response.status_code == 202, response.text
