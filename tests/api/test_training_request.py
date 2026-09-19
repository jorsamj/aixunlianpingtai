import io

import pytest
from PIL import Image


def _image_bytes(color: str) -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", (128, 128), color).save(stream, format="JPEG")
    return stream.getvalue()


def test_training_request_normalizes_legacy_boolean_cache_before_string_validation():
    import app as app_module

    assert app_module.TrainReq(cache=False).cache == "False"
    assert app_module.TrainReq(cache=True).cache == "True"
    assert app_module.TrainReq(cache="ram").cache == "ram"
    assert app_module.TrainReq(cache="disk").cache == "disk"


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
    monkeypatch.setattr(app_module, "resolve_ultralytics_model_path", lambda value, _project_id=None: value)
    monkeypatch.setattr(app_module, "check_ultralytics_train_runtime", lambda _python_path: "ok")
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
    from platform_core.algorithms import save_algorithms
    save_algorithms(app_module.algorithms_file(project_id), rows)

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
    assert job["base_selection_reason"] == "current_verified_version"
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
    from platform_core.algorithms import save_algorithms
    save_algorithms(app_module.algorithms_file(project_id), algorithms)
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
    monkeypatch.setattr(app_module, "resolve_ultralytics_model_path", lambda value, _project_id=None: value)

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
            "train_image_ids": ["train-a", "train-b"],
            "test_image_ids": ["test-a"],
            "validation_percent": 20,
            "experiment_percent": None,
            "queue_priority": 7,
        },
    )

    assert response.status_code == 202, response.text
    task = response.json()["task"]
    assert task["task_type"] == "TRAINING"
    assert task["status"] == "QUEUED"
    persisted = app_module.shared_task_repository().get(task["id"])
    assert persisted is not None
    assert persisted.kind is TaskKind.TRAINING
    assert persisted.status is TaskStatus.QUEUED
    assert persisted.priority == 7
    payload = app_module.shared_task_artifacts().read_json(task["id"], "payload.json")
    assert payload["schema_version"] == 3
    assert payload["train_image_ids"] == ["train-a", "train-b"]
    assert payload["test_image_ids"] == ["test-a"]
    assert not payload.get("train_dataset_ids")


def test_explicit_remote_training_enqueues_durable_input_preparation_without_legacy_server_id(
    client, seeded_project
):
    import app as app_module
    from platform_core.task_runtime import TaskKind, TaskStatus

    project_id, _ = seeded_project
    algorithm = client.post(
        f"/api/v12/projects/{project_id}/algorithms",
        json={"name": "远程准备训练", "algorithm_type": "yolo_ultralytics"},
    ).json()["algorithm"]

    response = client.post(
        f"/api/v12/projects/{project_id}/train/start",
        json={
            "framework": "ultralytics",
            "target": "remote",
            "algorithm_asset_id": algorithm["id"],
            "model": "yolo11n.pt",
            "split_mode": "independent_test_set",
            "train_image_ids": ["train-a", "train-b"],
            "test_image_ids": ["test-a"],
            "validation_percent": 20,
            "experiment_percent": None,
            "queue_priority": 9,
        },
    )

    assert response.status_code == 202, response.text
    body = response.json()
    training = body["task"]
    assert training["task_type"] == "TRAINING"
    assert training["status"] == "QUEUED"
    assert body["remote_input_state"] == "PREPARING"
    prep_id = body["preparation_task_id"]

    target = app_module.shared_task_repository().get(training["id"])
    prep = app_module.shared_task_repository().get(prep_id)
    assert target is not None and target.kind is TaskKind.TRAINING
    assert target.status is TaskStatus.QUEUED
    assert prep is not None and prep.kind is TaskKind.TRAINING_PREPARE
    assert prep.status is TaskStatus.QUEUED
    assert prep.required_capabilities == ("training.prepare",)
    assert prep.resource_key == f"training-prepare:{project_id}"

    payload = app_module.shared_task_artifacts().read_json(training["id"], "payload.json")
    assert payload["target"] == "remote"
    assert payload["remote_input_state"] == "PREPARING"
    assert payload["remote_prepare_task_id"] == prep_id
    assert "remote_execution" not in payload
    prep_payload = app_module.shared_task_artifacts().read_json(prep_id, "payload.json")
    assert prep_payload == {
        "schema_version": 1,
        "training_task_id": training["id"],
        "project_id": project_id,
    }


def test_training_route_rejects_dataset_group_contract(client, seeded_project):
    project_id, _ = seeded_project
    response = client.post(
        f"/api/v12/projects/{project_id}/train/start",
        json={
            "split_mode": "random_test_from_training_pool",
            "train_dataset_ids": ["legacy-dataset"],
            "train_image_ids": ["train-a", "train-b"],
            "experiment_percent": 20,
            "validation_percent": 20,
        },
    )
    assert response.status_code == 422
    assert "image_id" in response.text


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
            "train_image_ids": ["one", "two", "three"],
            "test_image_ids": [],
            "experiment_percent": percent,
            "validation_percent": 20,
        },
    )
    assert response.status_code == 202, response.text


@pytest.mark.parametrize(
    "body, message",
    [
        (
            {
                "split_mode": "random_test_from_training_pool",
                "train_image_ids": [],
                "test_image_ids": [],
                "experiment_percent": 20,
            },
            "train_image_ids",
        ),
        (
            {
                "split_mode": "independent_test_set",
                "train_image_ids": ["same"],
                "test_image_ids": ["same"],
                "experiment_percent": None,
            },
            "不能重复",
        ),
    ],
)
def test_explicit_material_selection_rejects_invalid_requests(client, seeded_project, body, message):
    project_id, _ = seeded_project
    algorithm = client.post(
        f"/api/v12/projects/{project_id}/algorithms",
        json={"name": f"素材校验-{message}", "algorithm_type": "yolo_ultralytics"},
    ).json()["algorithm"]
    response = client.post(
        f"/api/v12/projects/{project_id}/train/start",
        json={
            "framework": "ultralytics",
            "algorithm_asset_id": algorithm["id"],
            "model": "yolo11n.pt",
            "validation_percent": 20,
            **body,
        },
    )
    assert response.status_code == 400
    assert message in response.json()["detail"]


def _iteration_version(version_id, *, decision_id, evaluation_id, decision="continue_training"):
    return {
        "id": version_id,
        "version_name": f"20260919-{version_id}",
        "training_status": "SUCCEEDED",
        "artifact_verified": True,
        "trainable": True,
        "framework": "ultralytics",
        "stored_path": f"/models/{version_id}/best.pt",
        "dataset_revision_id": "a" * 64,
        "snapshot_id": f"snapshot-{version_id}",
        "evaluation": {
            "schema_version": 1, "evaluation_id": evaluation_id, "status": "succeeded",
            "dataset_revision_id": "a" * 64, "snapshot_id": f"snapshot-{version_id}",
            "model_sha256": "b" * 64, "metrics": {"metrics/mAP50(B)": 0.82},
            "error_samples": [],
        },
        "iteration_decision": {
            "schema_version": 1, "decision_id": decision_id, "evaluation_id": evaluation_id,
            "decision": decision, "weak_labels": [], "recommended_actions": ["continue_from_current_version"],
            "automatic_execution": False, "requires_confirmation": True,
        },
    }


def test_iteration_action_confirmation_is_version_owned_and_fenced(client, seeded_project):
    import app as app_module
    from platform_core.algorithms import attach_version

    project_id, _ = seeded_project
    algorithm = client.post(
        f"/api/v12/projects/{project_id}/algorithms",
        json={"name": "确认动作验收", "industry": "测试", "algorithm_type": "yolo_ultralytics"},
    ).json()["algorithm"]
    attach_version(
        app_module.algorithms_file(project_id), algorithm["id"],
        _iteration_version("v-action-1", decision_id="c" * 64, evaluation_id="d" * 64),
    )
    url = f"/api/v12/projects/{project_id}/algorithms/{algorithm['id']}/versions/v-action-1/iteration-actions/confirm"
    response = client.post(url, json={"decision_id": "c" * 64, "action": "continue_training"})
    assert response.status_code == 200, response.text
    action = response.json()["action"]
    assert action["action"] == "continue_training"
    assert action["automatic_execution"] is False
    assert action["requires_user_submit"] is True
    assert action["source"]["version_id"] == "v-action-1"
    repeated = client.post(url, json={"decision_id": "c" * 64, "action": "continue_training"})
    assert repeated.status_code == 200
    assert repeated.json()["idempotent"] is True
    assert repeated.json()["action"] == action

    persisted = next(
        row for row in app_module.list_algorithms_internal(project_id) if row["id"] == algorithm["id"]
    )["versions"][0]
    assert persisted["confirmed_iteration_action"]["action_id"] == action["action_id"]

    stale = client.post(url, json={"decision_id": "e" * 64, "action": "continue_training"})
    assert stale.status_code == 409
    assert "decision changed" in stale.text
    wrong = client.post(url, json={"decision_id": "c" * 64, "action": "supplement_data"})
    assert wrong.status_code == 409
    assert "does not match" in wrong.text


def test_iteration_action_confirmation_rejects_non_current_version(client, seeded_project):
    import app as app_module
    from platform_core.algorithms import attach_version

    project_id, _ = seeded_project
    algorithm = client.post(
        f"/api/v12/projects/{project_id}/algorithms",
        json={"name": "旧版本动作拒绝", "algorithm_type": "yolo_ultralytics"},
    ).json()["algorithm"]
    attach_version(app_module.algorithms_file(project_id), algorithm["id"],
                   _iteration_version("v-old", decision_id="1" * 64, evaluation_id="2" * 64))
    attach_version(app_module.algorithms_file(project_id), algorithm["id"],
                   _iteration_version("v-current", decision_id="3" * 64, evaluation_id="4" * 64))
    response = client.post(
        f"/api/v12/projects/{project_id}/algorithms/{algorithm['id']}/versions/v-old/iteration-actions/confirm",
        json={"decision_id": "1" * 64, "action": "continue_training"},
    )
    assert response.status_code == 409
    assert "当前版本" in response.text


def test_training_iteration_action_context_must_equal_persisted_confirmation(client, seeded_project):
    import app as app_module
    from platform_core.algorithms import attach_version

    project_id, _ = seeded_project
    algorithm = client.post(
        f"/api/v12/projects/{project_id}/algorithms",
        json={"name": "训练动作溯源", "algorithm_type": "yolo_ultralytics"},
    ).json()["algorithm"]
    attach_version(app_module.algorithms_file(project_id), algorithm["id"],
                   _iteration_version("v-current", decision_id="5" * 64, evaluation_id="6" * 64))
    confirm = client.post(
        f"/api/v12/projects/{project_id}/algorithms/{algorithm['id']}/versions/v-current/iteration-actions/confirm",
        json={"decision_id": "5" * 64, "action": "continue_training"},
    )
    assert confirm.status_code == 200, confirm.text
    action = confirm.json()["action"]
    context = {
        "action_id": action["action_id"],
        "decision_id": action["source"]["decision_id"],
        "evaluation_id": action["source"]["evaluation_id"],
        "version_id": action["source"]["version_id"],
        "dataset_revision_id": action["source"]["dataset_revision_id"],
        "snapshot_id": action["source"]["snapshot_id"],
    }
    current = next(
        row for row in app_module.list_algorithms_internal(project_id) if row["id"] == algorithm["id"]
    )
    accepted = app_module._validated_training_iteration_action(
        current,
        app_module.TrainReq(
            task_id=action["training_draft"]["task_id"],
            algorithm_asset_id=algorithm["id"],
            iteration_action=context,
        ),
    )
    assert accepted["action_id"] == action["action_id"]

    tampered = dict(context, decision_id="7" * 64)
    with pytest.raises(app_module.HTTPException) as error:
        app_module._validated_training_iteration_action(
            current,
            app_module.TrainReq(
                task_id=action["training_draft"]["task_id"],
                algorithm_asset_id=algorithm["id"],
                iteration_action=tampered,
            ),
        )
    assert error.value.status_code == 409


def test_confirmed_continue_training_rejects_arbitrary_task_id(client, seeded_project):
    import app as app_module
    from platform_core.algorithms import attach_version

    project_id, _ = seeded_project
    algorithm = client.post(
        f"/api/v12/projects/{project_id}/algorithms",
        json={"name": "动作任务幂等", "algorithm_type": "yolo_ultralytics"},
    ).json()["algorithm"]
    attach_version(
        app_module.algorithms_file(project_id), algorithm["id"],
        _iteration_version("v-current", decision_id="8" * 64, evaluation_id="9" * 64),
    )
    confirm = client.post(
        f"/api/v12/projects/{project_id}/algorithms/{algorithm['id']}/versions/v-current/iteration-actions/confirm",
        json={"decision_id": "8" * 64, "action": "continue_training"},
    )
    action = confirm.json()["action"]
    context = {
        "action_id": action["action_id"],
        "decision_id": action["source"]["decision_id"],
        "evaluation_id": action["source"]["evaluation_id"],
        "version_id": action["source"]["version_id"],
        "dataset_revision_id": action["source"]["dataset_revision_id"],
        "snapshot_id": action["source"]["snapshot_id"],
    }
    current = next(
        row for row in app_module.list_algorithms_internal(project_id) if row["id"] == algorithm["id"]
    )
    with pytest.raises(app_module.HTTPException) as error:
        app_module._validated_training_iteration_action(
            current,
            app_module.TrainReq(
                task_id="train_" + "f" * 24,
                algorithm_asset_id=algorithm["id"],
                iteration_action=context,
            ),
        )
    assert error.value.status_code == 409
    assert "固定任务 ID" in str(error.value.detail)


def test_confirmed_continue_training_reuses_same_durable_task(client, seeded_project):
    import app as app_module
    from platform_core.algorithms import attach_version

    project_id, train_image = seeded_project
    second = client.post(
        f"/api/projects/{project_id}/images",
        files=[("files", ("second-action.jpg", _image_bytes("navy"), "image/jpeg"))],
        data={"dataset_id": "default"},
    ).json()["uploaded"][0]
    algorithm = client.post(
        f"/api/v12/projects/{project_id}/algorithms",
        json={"name": "确认动作幂等训练", "algorithm_type": "yolo_ultralytics"},
    ).json()["algorithm"]
    attach_version(
        app_module.algorithms_file(project_id), algorithm["id"],
        _iteration_version("v-current", decision_id="a" * 64, evaluation_id="b" * 64),
    )
    confirm = client.post(
        f"/api/v12/projects/{project_id}/algorithms/{algorithm['id']}/versions/v-current/iteration-actions/confirm",
        json={"decision_id": "a" * 64, "action": "continue_training"},
    )
    assert confirm.status_code == 200, confirm.text
    action = confirm.json()["action"]
    task_id = action["training_draft"]["task_id"]
    context = {
        "action_id": action["action_id"],
        "decision_id": action["source"]["decision_id"],
        "evaluation_id": action["source"]["evaluation_id"],
        "version_id": action["source"]["version_id"],
        "dataset_revision_id": action["source"]["dataset_revision_id"],
        "snapshot_id": action["source"]["snapshot_id"],
    }
    payload = {
        "task_id": task_id,
        "framework": "ultralytics",
        "algorithm": "yolo11n_det",
        "algorithm_asset_id": algorithm["id"],
        "model": "yolo11n.pt",
        "split_mode": "random_test_from_training_pool",
        "train_image_ids": [train_image["id"], second["id"]],
        "test_image_ids": [],
        "experiment_percent": 20,
        "validation_percent": 20,
        "device": "cpu",
        "iteration_action": context,
    }
    first = client.post(f"/api/v12/projects/{project_id}/train/start", json=payload)
    assert first.status_code == 202, first.text
    assert first.json()["task"]["task_id"] == task_id

    repeated = client.post(f"/api/v12/projects/{project_id}/train/start", json=payload)
    assert repeated.status_code == 202, repeated.text
    assert repeated.json()["idempotent"] is True
    assert repeated.json()["task"]["task_id"] == task_id

    job = app_module.read_json(app_module.project_dir(project_id) / "jobs" / task_id / "job.json", {})
    assert job["confirmed_iteration_action"]["action_id"] == action["action_id"]
    request = app_module.shared_task_artifacts().read_json(task_id, "payload.json")
    assert request["iteration_action"] == context
