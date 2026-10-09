import hashlib
import io
import json
import re
from types import SimpleNamespace

import pytest
from PIL import Image


@pytest.fixture(scope="module", autouse=True)
def _preinstalled_mother_model_for_existing_training_contracts():
    """The training API suite uses a preloaded fixture rather than the retired
    implicit GitHub download from an official model name."""
    import app as platform

    target = platform.DATA_DIR / "models" / "yolo11n.pt"
    target.parent.mkdir(parents=True, exist_ok=True)
    previous = target.read_bytes() if target.is_file() else None
    target.write_bytes(b"preinstalled-test-mother" * 128)
    try:
        yield
    finally:
        if previous is None:
            target.unlink(missing_ok=True)
        else:
            target.write_bytes(previous)


def test_server_generated_training_task_id_uses_canonical_contract():
    import app as app_module

    generated = {app_module._new_training_task_id() for _ in range(8)}

    assert len(generated) == 8
    assert all(re.fullmatch(r"train_[0-9a-f]{16,32}", value) for value in generated)


def _image_bytes(color: str | tuple[int, int, int]) -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", (128, 128), color).save(stream, format="JPEG")
    return stream.getvalue()


def _mark_training_ready(client, project_id: str, image: dict, *, label: str = "fire", class_id: int = 0) -> dict:
    import app as app_module

    current = client.get(
        f"/api/projects/{project_id}/annotations/{image['id']}"
    ).json()
    response = client.post(
        f"/api/projects/{project_id}/annotations/{image['id']}",
        json={
            "boxes": [{
                "class_id": class_id, "label": label,
                "x1": 10, "y1": 10, "x2": 80, "y2": 80,
            }],
            "expected_version": current["annotation"]["version"],
            "source_content_sha256": current["image"]["content_sha256"],
            "reviewed_label_codes": [label],
        },
    )
    assert response.status_code == 200, response.text
    app_module.material_store(project_id).patch({
        image["id"]: {"processing_status": "processed"},
    })
    return image


def _upload_training_ready(client, project_id: str, name: str, color: tuple[int, int, int]) -> dict:
    image = client.post(
        f"/api/projects/{project_id}/images",
        files=[("files", (name, _image_bytes(color), "image/jpeg"))],
        data={"dataset_id": "default"},
    ).json()["uploaded"][0]
    return _mark_training_ready(client, project_id, image)


def _freeze_admitted_training(app_module, task_id: str):
    """Run only the TRAINING_PREPARE contract phase, without trainer startup."""
    from platform_core.remote_training_tasks import TrainingPrepareHandler

    target = app_module.shared_task_repository().get(task_id)
    assert target is not None
    payload = app_module.shared_task_artifacts().read_json(task_id, target.payload_ref)
    handler = TrainingPrepareHandler(app_module.DATA_DIR)
    context = SimpleNamespace(
        artifacts=app_module.shared_task_artifacts(),
        repository=app_module.shared_task_repository(),
    )
    frozen_payload = handler._freeze_request_contract(context, target, payload)
    app_module.shared_task_artifacts().atomic_write_json(
        task_id, target.payload_ref, frozen_payload,
    )
    handler._publish_prepared_job(target, frozen_payload)
    return frozen_payload


def test_training_target_contract_rejects_invalid_metric_threshold_and_interval():
    import app as app_module
    from fastapi import HTTPException

    with pytest.raises(HTTPException, match="目标指标只支持"):
        app_module.validate_train_request(app_module.TrainReq(eval_metric="accuracy"))

    with pytest.raises(HTTPException, match="目标正确率必须在 0~1"):
        app_module.validate_train_request(app_module.TrainReq(stop_threshold=90, eval_interval=10))

    with pytest.raises(HTTPException, match="eval_interval 必须大于 0"):
        app_module.validate_train_request(app_module.TrainReq(stop_threshold=0.9, eval_interval=0))

    valid = app_module.TrainReq(stop_threshold=0.9, eval_interval=10, eval_metric="map50")
    app_module.validate_train_request(valid)
    assert valid.stop_threshold == 0.9
    assert valid.eval_interval == 10


def test_training_precision_rejects_bf16_until_runtime_support_is_real():
    import app as app_module
    from fastapi import HTTPException

    with pytest.raises(HTTPException, match="暂不支持 BF16"):
        app_module.validate_train_request(app_module.TrainReq(precision="bf16"))

    for precision in ("auto", "fp16", "fp32"):
        app_module.validate_train_request(app_module.TrainReq(precision=precision))


def test_training_request_normalizes_legacy_boolean_cache_before_string_validation():
    import app as app_module

    assert app_module.TrainReq(cache=False).cache == "False"
    assert app_module.TrainReq(cache=True).cache == "True"
    assert app_module.TrainReq(cache="ram").cache == "ram"
    assert app_module.TrainReq(cache="disk").cache == "disk"


def test_training_start_rejects_partial_review_scope_before_task_creation(
    client, seeded_project, monkeypatch,
):
    import app as app_module
    from platform_core.annotation_repository import AnnotationRepository
    from platform_core.task_runtime import TaskKind

    project_id, first = seeded_project
    monkeypatch.setattr(app_module, "_v48_dispatch_training_queues", lambda _project_id: None)
    second = client.post(
        f"/api/projects/{project_id}/images",
        files=[("files", ("scope-smoke.jpg", _image_bytes("gray"), "image/jpeg"))],
        data={"dataset_id": "default"},
    ).json()["uploaded"][0]
    third = client.post(
        f"/api/projects/{project_id}/images",
        files=[("files", ("scope-fire.jpg", _image_bytes("black"), "image/jpeg"))],
        data={"dataset_id": "default"},
    ).json()["uploaded"][0]
    annotations = AnnotationRepository(app_module.project_dir(project_id))
    annotations.upsert(
        first["id"],
        [{"class_id": 0, "label": "fire", "x1": 10, "y1": 10, "x2": 80, "y2": 80}],
        annotation_state="annotated",
        annotation_scope=["fire"],
    )
    annotations.upsert(
        second["id"],
        [{"class_id": 1, "label": "smoke", "x1": 10, "y1": 10, "x2": 80, "y2": 80}],
        annotation_state="annotated",
        annotation_scope=["fire", "smoke"],
    )
    annotations.upsert(
        third["id"],
        [{"class_id": 0, "label": "fire", "x1": 10, "y1": 10, "x2": 80, "y2": 80}],
        annotation_state="annotated",
        annotation_scope=["fire", "smoke"],
    )
    app_module.material_store(project_id).patch({
        image["id"]: {"processing_status": "processed"}
        for image in (first, second, third)
    })
    algorithm = client.post(
        f"/api/v12/projects/{project_id}/algorithms",
        json={"name": "审核范围准入", "algorithm_type": "yolo_ultralytics"},
    ).json()["algorithm"]
    repository = app_module.shared_task_repository()
    before = len(repository.list(project_id=project_id, kinds=(TaskKind.TRAINING,), limit=100).items)

    response = client.post(
        f"/api/v12/projects/{project_id}/train/start",
        json={
            "framework": "ultralytics",
            "algorithm_asset_id": algorithm["id"],
            "algorithm": "yolo11n_det",
            "model": "yolo11n.pt",
            "split_mode": "random_test_from_training_pool",
            "train_image_ids": [first["id"], second["id"], third["id"]],
            "test_image_ids": [],
            "train_labels": ["fire", "smoke"],
            "experiment_percent": 20,
            "validation_percent": 20,
            "device": "cpu",
        },
    )

    assert response.status_code == 409, response.text
    detail = json.loads(response.json()["detail"])
    assert detail["code"] == "TRAINING_MATERIAL_SCOPE_INCOMPATIBLE"
    assert detail["issue_count"] == 1
    assert detail["items"][0]["image_id"] == first["id"]
    assert detail["items"][0]["missing_label_codes"] == ["smoke"]
    after = len(repository.list(project_id=project_id, kinds=(TaskKind.TRAINING,), limit=100).items)
    assert after == before


def test_training_start_checks_server_resolved_benchmark_scope_before_task_creation(
    client, seeded_project, monkeypatch,
):
    import app as app_module
    from platform_core.annotation_repository import AnnotationRepository
    from platform_core.task_runtime import TaskKind

    project_id, seed_image = seeded_project
    first = _mark_training_ready(client, project_id, seed_image)
    second = client.post(
        f"/api/projects/{project_id}/images",
        files=[("files", ("benchmark-train.jpg", _image_bytes((31, 53, 79)), "image/jpeg"))],
        data={"dataset_id": "default"},
    ).json()["uploaded"][0]
    _mark_training_ready(client, project_id, second, label="smoke", class_id=1)
    benchmark = client.post(
        f"/api/projects/{project_id}/images",
        files=[("files", ("benchmark-partial.jpg", _image_bytes("gray"), "image/jpeg"))],
        data={"dataset_id": "default"},
    ).json()["uploaded"][0]
    annotations = AnnotationRepository(app_module.project_dir(project_id))
    for image in (first, second):
        current = annotations.get(image["id"])
        annotations.upsert(
            image["id"],
            current["boxes"],
            annotation_state="annotated",
            annotation_scope=["fire", "smoke"],
            expected_version=current["version"],
        )
    annotations.upsert(
        benchmark["id"],
        [{"class_id": 0, "label": "fire", "x1": 10, "y1": 10, "x2": 80, "y2": 80}],
        annotation_state="annotated",
        annotation_scope=[],
    )
    app_module.material_store(project_id).patch({
        benchmark["id"]: {"processing_status": "processed"},
    })
    monkeypatch.setattr(
        app_module,
        "_training_reusable_benchmark",
        lambda *_args: {
            "test_image_ids": (benchmark["id"],),
            "source_version_id": "benchmark-v1",
            "scope_id": "b" * 64,
        },
    )
    algorithm = client.post(
        f"/api/v12/projects/{project_id}/algorithms",
        json={"name": "Benchmark 补审准入", "algorithm_type": "yolo_ultralytics"},
    ).json()["algorithm"]
    repository = app_module.shared_task_repository()
    before = len(repository.list(project_id=project_id, kinds=(TaskKind.TRAINING,), limit=100).items)

    response = client.post(
        f"/api/v12/projects/{project_id}/train/start",
        json={
            "framework": "ultralytics",
            "algorithm_asset_id": algorithm["id"],
            "model": "yolo11n.pt",
            "train_labels": ["fire", "smoke"],
            "split_mode": "random_test_from_training_pool",
            "train_image_ids": [first["id"], second["id"]],
            "test_image_ids": [],
            "experiment_percent": 20,
            "validation_percent": 20,
            "benchmark_source_version_id": "benchmark-v1",
            "benchmark_scope_id": "b" * 64,
        },
    )

    assert response.status_code == 409, response.text
    detail = json.loads(response.json()["detail"])
    assert detail["code"] == "TRAINING_MATERIAL_SCOPE_INCOMPATIBLE"
    assert detail["items"][0]["image_id"] == benchmark["id"]
    after = len(repository.list(project_id=project_id, kinds=(TaskKind.TRAINING,), limit=100).items)
    assert after == before


def test_v12_rejects_paddle_before_algorithm_or_material_io(client, seeded_project):
    project_id, _ = seeded_project

    response = client.post(
        f"/api/v12/projects/{project_id}/train/start",
        json={
            "framework": "paddle",
            "algorithm_asset_id": "does-not-need-to-exist",
            "model": "PP-YOLOE",
            "split_mode": "random_test_from_training_pool",
            "train_image_ids": ["does-not-need-to-exist"],
            "experiment_percent": 20,
            "validation_percent": 20,
        },
    )

    assert response.status_code == 409, response.text
    assert "Durable Training" in response.json()["detail"]
    assert "PaddleDetection" in response.json()["detail"]


def test_v12_product_training_rejects_legacy_unsplit_request(client, seeded_project, monkeypatch):
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
        _mark_training_ready(
            client, project_id, image, label=label, class_id=class_id,
        )
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
            "train_labels": ["fire", "smoke"],
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

    assert response.status_code == 409, response.text
    assert "split_mode" in response.json()["detail"]
    assert "Durable Training" in response.json()["detail"]


def test_legacy_training_route_never_runs_its_own_iteration_selector(
    client, seeded_project, monkeypatch
):
    import app as app_module

    project_id, _ = seeded_project
    algorithm = client.post(
        f"/api/v12/projects/{project_id}/algorithms",
        json={"name": "旧入口单 Owner", "algorithm_type": "yolo_ultralytics"},
    ).json()["algorithm"]
    seen = {"called": False}

    def strict_spy(*_args, **_kwargs):
        seen["called"] = True
        raise AssertionError("legacy URL must not own iteration-base selection")

    monkeypatch.setattr(app_module, "_v54_iteration_base", strict_spy)

    response = client.post(
        f"/api/projects/{project_id}/train/start",
        json={
            "framework": "ultralytics",
            "algorithm_asset_id": algorithm["id"],
            "model": "yolo11n.pt",
        },
    )

    assert response.status_code == 409, response.text
    assert "split_mode" in response.json()["detail"]
    assert seen["called"] is False


def test_v12_iteration_cannot_bypass_durable_split_with_latest_version(client, seeded_project, monkeypatch):
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
        _mark_training_ready(
            client, project_id, image, label=label, class_id=class_id,
        )
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

    assert response.status_code == 409, response.text
    assert "split_mode" in response.json()["detail"]
    assert "Durable Training" in response.json()["detail"]



def test_unversioned_training_url_delegates_to_durable_v12_owner(client, seeded_project):
    project_id, _ = seeded_project
    algorithm = client.post(
        f"/api/v12/projects/{project_id}/algorithms",
        json={"name": "旧入口兼容别名", "algorithm_type": "yolo_ultralytics"},
    ).json()["algorithm"]

    response = client.post(
        f"/api/projects/{project_id}/train/start",
        json={
            "framework": "ultralytics",
            "algorithm_asset_id": algorithm["id"],
            "model": "yolo11n.pt",
        },
    )

    assert response.status_code == 409, response.text
    assert "split_mode" in response.json()["detail"]
    assert "Durable Training" in response.json()["detail"]


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
        _mark_training_ready(
            client, project_id, image, label=label, class_id=class_id,
        )
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


def test_training_rejects_random_pool_with_missing_material_truth(client, seeded_project, monkeypatch):
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
            "train_labels": ["fire"],
            "split_mode": "random_test_from_training_pool",
            "train_image_ids": [image["id"], "not-a-real-image"],
            "test_image_ids": [],
            "experiment_percent": 20,
            "validation_percent": 20,
        },
    )

    assert response.status_code == 409, response.text
    assert "not-a-real-image" in response.json()["detail"]


def test_product_training_submit_freezes_server_authoritative_label_contract(
    client, seeded_project
):
    import app as app_module

    project_id, seed_image = seeded_project
    one = _mark_training_ready(client, project_id, seed_image)
    two = _upload_training_ready(client, project_id, "label-contract-two.jpg", (31, 47, 63))
    three = _upload_training_ready(client, project_id, "label-contract-three.jpg", (79, 97, 113))
    algorithm = client.post(
        f"/api/v12/projects/{project_id}/algorithms",
        json={"name": "标签冻结合同", "algorithm_type": "yolo_ultralytics"},
    ).json()["algorithm"]
    base_request = {
        "framework": "ultralytics",
        "algorithm_asset_id": algorithm["id"],
        "model": "yolo11n.pt",
        "split_mode": "random_test_from_training_pool",
        "train_image_ids": [one["id"], two["id"], three["id"]],
        "test_image_ids": [],
        "experiment_percent": 20,
        "validation_percent": 20,
    }

    missing = client.post(
        f"/api/v12/projects/{project_id}/train/start",
        json=base_request,
    )
    assert missing.status_code == 409
    assert "首次训练必须" in missing.text

    bypass = client.post(
        f"/api/v12/projects/{project_id}/train/start",
        json={**base_request, "train_labels": ["smoke"]},
    )
    assert bypass.status_code == 409
    assert "不在已选素材" in bypass.text

    accepted = client.post(
        f"/api/v12/projects/{project_id}/train/start",
        json={**base_request, "train_labels": ["fire"]},
    )
    assert accepted.status_code == 202, accepted.text
    task = accepted.json()["task"]
    _freeze_admitted_training(app_module, task["id"])
    frozen = app_module.shared_task_artifacts().read_json(
        task["id"], "input-freeze.json", default={}
    )
    assert [row["code"] for row in frozen["label_schema"]] == ["fire"]
    assert frozen["label_contract"]["requested_label_codes"] == ["fire"]
    assert frozen["label_contract"]["inherited_label_codes"] == []
    assert frozen["label_contract"]["effective_label_codes"] == ["fire"]
    assert frozen["label_contract"]["strict_resume"] is False
    assert frozen["label_contract"]["optimizer_state_resumed"] is False


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

    project_id, seed_image = seeded_project
    train_a = _mark_training_ready(client, project_id, seed_image)
    train_b = _upload_training_ready(client, project_id, "durable-train-b.jpg", (17, 31, 47))
    test_a = _upload_training_ready(client, project_id, "durable-test-a.jpg", (61, 73, 89))
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
            "train_labels": ["fire"],
            "split_mode": "independent_test_set",
            "train_image_ids": [train_a["id"], train_b["id"]],
            "test_image_ids": [test_a["id"]],
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
    assert payload["schema_version"] == 4
    assert payload["training_input_state"] == "PREPARING"
    assert payload["asset_algorithm_name"] == "异步训练请求"
    assert payload["train_image_ids"] == [train_a["id"], train_b["id"]]
    assert payload["test_image_ids"] == [test_a["id"]]
    assert not payload.get("train_dataset_ids")
    prepare = app_module.shared_task_repository().get(
        response.json()["preparation_task_id"]
    )
    assert prepare is not None and prepare.kind is TaskKind.TRAINING_PREPARE
    assert persisted.stage == "training_input_pending"
    assert persisted.required_capabilities == ("training.input.ready",)


def test_explicit_remote_training_enqueues_durable_input_preparation_without_legacy_server_id(
    client, seeded_project
):
    import app as app_module
    from platform_core.task_runtime import TaskKind, TaskStatus

    project_id, seed_image = seeded_project
    train_a = _mark_training_ready(client, project_id, seed_image)
    train_b = _upload_training_ready(client, project_id, "remote-train-b.jpg", (23, 41, 59))
    test_a = _upload_training_ready(client, project_id, "remote-test-a.jpg", (67, 83, 101))
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
            "train_labels": ["fire"],
            "split_mode": "independent_test_set",
            "train_image_ids": [train_a["id"], train_b["id"]],
            "test_image_ids": [test_a["id"]],
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
        "schema_version": 2,
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
    project_id, seed_image = seeded_project
    one = _mark_training_ready(client, project_id, seed_image)
    two = _upload_training_ready(client, project_id, "random-two.jpg", (29, 43, 71))
    three = _upload_training_ready(client, project_id, "random-three.jpg", (79, 97, 113))
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
            "train_labels": ["fire"],
            "split_mode": "random_test_from_training_pool",
            "train_image_ids": [one["id"], two["id"], three["id"]],
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


def _iteration_version(
    version_id, *, decision_id, evaluation_id, decision="continue_training", stored_path=None
):
    return {
        "id": version_id,
        "version_name": f"20260919-{version_id}",
        "training_status": "SUCCEEDED",
        "artifact_verified": True,
        "trainable": True,
        "framework": "ultralytics",
        "stored_path": str(stored_path or f"/models/{version_id}/best.pt"),
        "label_schema": [{"code": "fire", "class_id": 0, "canonical_project_class_id": 0}],
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
    third = _upload_training_ready(client, project_id, "third-action.jpg", (109, 127, 149))
    _mark_training_ready(client, project_id, train_image)
    _mark_training_ready(client, project_id, second)
    algorithm = client.post(
        f"/api/v12/projects/{project_id}/algorithms",
        json={"name": "确认动作幂等训练", "algorithm_type": "yolo_ultralytics"},
    ).json()["algorithm"]
    base_model = app_module.project_dir(project_id) / "v-current-base.pt"
    base_model.write_bytes(b"verified-iteration-base")
    attach_version(
        app_module.algorithms_file(project_id), algorithm["id"],
        _iteration_version(
            "v-current",
            decision_id="a" * 64,
            evaluation_id="b" * 64,
            stored_path=base_model,
        ),
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
        "train_image_ids": [train_image["id"], second["id"], third["id"]],
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
    request = _freeze_admitted_training(app_module, task_id)
    assert request["iteration_action"] == context
    assert request["base_version_id"] == "v-current"
    assert request["base_model_reference"] == str(base_model.resolve())
    assert request["base_model_sha256"] == hashlib.sha256(base_model.read_bytes()).hexdigest()


def test_durable_training_requires_matching_supplement_candidate_set_identity(
    client, seeded_project,
):
    import app as app_module
    from platform_core.algorithms import save_algorithms
    from platform_core.annotation_repository import AnnotationRepository
    from platform_core.online_feedback import build_supplement_candidate_set

    project_id, candidate_image = seeded_project
    second = client.post(
        f"/api/projects/{project_id}/images",
        files=[("files", ("normal.jpg", _image_bytes("blue"), "image/jpeg"))],
        data={"dataset_id": "default"},
    ).json()["uploaded"][0]
    for image in (candidate_image, second):
        _mark_training_ready(client, project_id, image)
    third = _upload_training_ready(client, project_id, "feedback-third.jpg", (131, 151, 173))

    algorithm = client.post(
        f"/api/v12/projects/{project_id}/algorithms",
        json={"name": "反馈补数据训练", "algorithm_type": "yolo_ultralytics"},
    ).json()["algorithm"]
    version_id = "feedback-base"
    material = app_module.material_store(project_id).get(candidate_image["id"])
    annotation = AnnotationRepository(
        app_module.project_dir(project_id)
    ).get(candidate_image["id"])
    action = {
        "status": "confirmed",
        "action": "supplement_data",
        "action_id": "a" * 64,
        "source": {"algorithm_id": algorithm["id"], "version_id": version_id},
    }
    candidate_set = build_supplement_candidate_set(
        action,
        [{
            "eligible": True,
            "feedback_id": "feedback-1",
            "feedback_type": "correct",
            "material_id": candidate_image["id"],
            "candidate_digest": "b" * 64,
            "annotation_hash": annotation["content_digest"],
            "annotation_state": annotation["annotation_state"],
            "labels": ["fire"],
            "model_sha256": "c" * 64,
            "input_sha256": material["content_sha256"],
            "confirmed_at": "2026-09-19T00:00:00Z",
            "algorithm_id": algorithm["id"],
            "version_id": version_id,
        }],
        frozen_at="2026-09-19T00:01:00Z",
    )
    algorithms = app_module.list_algorithms_internal(project_id)
    target = next(row for row in algorithms if row["id"] == algorithm["id"])
    base_model = app_module.project_dir(project_id) / "feedback-base.pt"
    base_model.write_bytes(b"verified-feedback-base")
    target["current_version_id"] = version_id
    target["versions"] = [{
        "id": version_id,
        "version_name": "20260919000100",
        "training_status": "SUCCEEDED",
        "artifact_verified": True,
        "trainable": True,
        "framework": "ultralytics",
        "stored_path": str(base_model),
        "label_schema": [
            {"code": "fire", "class_id": 0, "canonical_project_class_id": 0}
        ],
        "supplement_data_candidate_set": candidate_set,
    }]
    save_algorithms(app_module.algorithms_file(project_id), algorithms)

    base_request = {
        "framework": "ultralytics",
        "algorithm_asset_id": algorithm["id"],
        "model": "yolo11n.pt",
        "split_mode": "random_test_from_training_pool",
        "train_image_ids": [candidate_image["id"], second["id"], third["id"]],
        "test_image_ids": [],
        "experiment_percent": 20,
        "validation_percent": 20,
        "device": "cpu",
    }
    missing = client.post(
        f"/api/v12/projects/{project_id}/train/start",
        json=base_request,
    )
    assert missing.status_code == 202
    from platform_core.remote_training_tasks import RemoteTrainingPreparationError
    with pytest.raises(RemoteTrainingPreparationError, match="Candidate Set"):
        _freeze_admitted_training(app_module, missing.json()["task"]["task_id"])

    accepted = client.post(
        f"/api/v12/projects/{project_id}/train/start",
        json={
            **base_request,
            "supplement_candidate_set_id": candidate_set["candidate_set_id"],
        },
    )
    assert accepted.status_code == 202, accepted.text
    task_id = accepted.json()["task"]["task_id"]
    payload = _freeze_admitted_training(app_module, task_id)
    assert payload["supplement_candidate_set_id"] == candidate_set["candidate_set_id"]
    assert payload["supplement_candidate_set"]["candidate_set_id"] == candidate_set["candidate_set_id"]
    frozen = app_module.shared_task_artifacts().read_json(
        task_id, "input-freeze.json", default={},
    )
    frozen_candidate = next(
        row for row in frozen["images"]
        if row["id"] == candidate_image["id"]
    )
    assert frozen_candidate["source_annotation_hash"] == annotation["content_digest"]
    assert frozen_candidate["source_annotation_state"] == annotation["annotation_state"]
    job = app_module.read_json(
        app_module.project_dir(project_id) / "jobs" / task_id / "job.json", {}
    )
    assert job["supplement_candidate_set_id"] == candidate_set["candidate_set_id"]


def test_reusable_benchmark_is_resolved_server_side_into_exact_test_ids(
    client, seeded_project,
):
    import app as app_module
    from platform_core.algorithms import save_algorithms
    from platform_core.training_evaluation import build_evaluation_benchmark_scope

    project_id, benchmark_image = seeded_project
    train_image = client.post(
        f"/api/projects/{project_id}/images",
        files=[("files", ("benchmark-train.jpg", _image_bytes("blue"), "image/jpeg"))],
        data={"dataset_id": "default"},
    ).json()["uploaded"][0]
    train_image_2 = client.post(
        f"/api/projects/{project_id}/images",
        files=[("files", ("benchmark-train-2.jpg", _image_bytes("green"), "image/jpeg"))],
        data={"dataset_id": "default"},
    ).json()["uploaded"][0]
    for image in (benchmark_image, train_image, train_image_2):
        _mark_training_ready(client, project_id, image)

    material = app_module.MaterialRepository(
        app_module.project_dir(project_id)
    ).get(benchmark_image["id"])
    annotation = app_module.AnnotationRepository(
        app_module.project_dir(project_id)
    ).get(benchmark_image["id"])
    snapshot_id = "a" * 64
    snapshot = {
        "schema_version": 3,
        "snapshot_id": snapshot_id,
        "test_image_ids": [benchmark_image["id"]],
        "label_schema": [{"class_id": 0, "code": "fire"}],
        "images": [{
            "image_id": benchmark_image["id"],
            "role": "test",
            "content_sha256": material["content_sha256"],
            "annotation_hash": annotation["content_digest"],
            "annotation_state": annotation["annotation_state"],
        }],
    }
    snapshot_dir = app_module.project_dir(project_id) / "snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    app_module.atomic_write_json(snapshot_dir / f"{snapshot_id}.json", snapshot)
    snapshot_scope = build_evaluation_benchmark_scope(snapshot)
    scope_id = "b" * 64
    scope = {
        **snapshot_scope,
        "scope_id": scope_id,
        "binding_level": "bundle_verified",
        "evaluation_input_digest": "c" * 64,
        "training_input_policy": "ultralytics_jpeg_repair_v1",
    }

    algorithm = client.post(
        f"/api/v12/projects/{project_id}/algorithms",
        json={"name": "固定评测基准训练", "algorithm_type": "yolo_ultralytics"},
    ).json()["algorithm"]
    rows = app_module.list_algorithms_internal(project_id)
    target = next(row for row in rows if row["id"] == algorithm["id"])
    benchmark_model = app_module.project_dir(project_id) / "benchmark-v1.pt"
    benchmark_model.write_bytes(b"verified-benchmark-base")
    target["current_version_id"] = "benchmark-v1"
    target["versions"] = [{
        "id": "benchmark-v1",
        "version_name": "benchmark-v1",
        "snapshot_id": snapshot_id,
        "training_status": "SUCCEEDED",
        "artifact_verified": True,
        "trainable": True,
        "framework": "ultralytics",
        "stored_path": str(benchmark_model),
        "label_schema": [
            {"code": "fire", "class_id": 0, "canonical_project_class_id": 0}
        ],
        "evaluation": {
            "status": "succeeded",
            "snapshot_id": snapshot_id,
            "benchmark_scope": scope,
        },
    }]
    save_algorithms(app_module.algorithms_file(project_id), rows)

    availability = client.get(
        f"/api/v12/projects/{project_id}/algorithms/{algorithm['id']}/benchmark-reuse"
    )
    assert availability.status_code == 200
    assert availability.json()["available"] is True
    assert availability.json()["test_image_count"] == 1
    assert "test_image_ids" not in availability.json()

    response = client.post(
        f"/api/v12/projects/{project_id}/train/start",
        json={
            "framework": "ultralytics",
            "algorithm_asset_id": algorithm["id"],
            "model": "yolo11n.pt",
            "train_labels": ["fire"],
            "split_mode": "random_test_from_training_pool",
            "train_image_ids": [benchmark_image["id"], train_image["id"], train_image_2["id"]],
            "validation_percent": 20,
            "experiment_percent": 20,
            "benchmark_source_version_id": "benchmark-v1",
            "benchmark_scope_id": scope_id,
        },
    )
    assert response.status_code == 202, response.text
    task_id = response.json()["task"]["id"]
    payload = _freeze_admitted_training(app_module, task_id)
    assert payload["split_mode"] == "independent_test_set"
    assert payload["train_image_ids"] == [train_image["id"], train_image_2["id"]]
    assert payload["test_image_ids"] == [benchmark_image["id"]]
    assert payload["benchmark_reuse"]["source_version_id"] == "benchmark-v1"
    assert payload["benchmark_reuse"]["scope_id"] == scope_id
    assert payload["benchmark_reuse"]["test_image_count"] == 1
    assert payload["benchmark_reuse"]["selected_training_candidate_count"] == 3
    assert payload["benchmark_reuse"]["reserved_training_candidate_count"] == 1
    assert payload["benchmark_reuse"]["effective_training_candidate_count"] == 2


def test_reusable_benchmark_rejects_stale_observed_scope_at_admission(
    client, seeded_project,
):
    import app as app_module

    project_id, seed_image = seeded_project
    first = _mark_training_ready(client, project_id, seed_image)
    second = _upload_training_ready(client, project_id, "stale-scope-two.jpg", (41, 61, 83))
    third = _upload_training_ready(client, project_id, "stale-scope-three.jpg", (101, 121, 143))
    algorithm = client.post(
        f"/api/v12/projects/{project_id}/algorithms",
        json={"name": "过期评测基准", "algorithm_type": "yolo_ultralytics"},
    ).json()["algorithm"]
    response = client.post(
        f"/api/v12/projects/{project_id}/train/start",
        json={
            "framework": "ultralytics",
            "algorithm_asset_id": algorithm["id"],
            "train_labels": ["fire"],
            "split_mode": "random_test_from_training_pool",
            "train_image_ids": [first["id"], second["id"], third["id"]],
            "validation_percent": 20,
            "experiment_percent": 20,
            "benchmark_source_version_id": "version-old",
            "benchmark_scope_id": "d" * 64,
        },
    )
    assert response.status_code == 409, response.text
    assert "当前版本已变化" in response.text



def test_rockchip_auto_conversion_uses_single_detected_supported_chip(monkeypatch):
    import app as app_module

    created = []

    monkeypatch.setattr(app_module, "_v48_quality_reached", lambda _job: True)
    monkeypatch.setattr(
        app_module,
        "_builtin_deploy_resources",
        lambda: [{
            "id": "rk-agent",
            "name": "RKNN Agent",
            "status": "ready",
            "targets": ["rockchip"],
            "supported_chips": ["rk3568"],
        }],
    )
    monkeypatch.setattr(app_module, "_load_saved_deploy_resources", lambda: [])
    monkeypatch.setattr(
        app_module,
        "v39_create_deploy_job",
        lambda project_id, payload: created.append((project_id, payload)) or {"job": {"id": "convert-rk3568"}},
    )

    result = app_module._v48_auto_convert_version(
        "p1",
        "a1",
        {"id": "v1", "stored_path": "/models/best.pt"},
        {"imgsz": 640, "auto_convert_targets": ["rockchip"]},
    )

    assert not result["errors"]
    assert result["jobs"][0]["job_id"] == "convert-rk3568"
    assert len(created) == 1
    assert created[0][1].params["chip"] == "rk3568"


def test_rockchip_auto_conversion_fails_closed_when_chip_is_ambiguous(monkeypatch):
    import app as app_module

    created = []

    monkeypatch.setattr(app_module, "_v48_quality_reached", lambda _job: True)
    monkeypatch.setattr(
        app_module,
        "_builtin_deploy_resources",
        lambda: [{
            "id": "rk-agent",
            "name": "RKNN Agent",
            "status": "ready",
            "targets": ["rockchip"],
            "supported_chips": ["rk3568", "rk3576", "rk3588"],
        }],
    )
    monkeypatch.setattr(app_module, "_load_saved_deploy_resources", lambda: [])
    monkeypatch.setattr(
        app_module,
        "v39_create_deploy_job",
        lambda project_id, payload: created.append((project_id, payload)) or {"job": {"id": "should-not-run"}},
    )

    result = app_module._v48_auto_convert_version(
        "p1",
        "a1",
        {"id": "v1", "stored_path": "/models/best.pt"},
        {"imgsz": 640, "auto_convert_targets": ["rockchip"]},
    )

    assert created == []
    assert result["jobs"] == []
    assert len(result["errors"]) == 1
    assert "RK3568" in result["errors"][0]["message"]
    assert "RK3576" in result["errors"][0]["message"]
    assert "RK3588" not in result["errors"][0]["message"]


def test_training_truth_validation_keeps_material_reads_batched():
    import inspect
    import app as app_module

    for function in (
        app_module._training_reusable_benchmark,
        app_module._training_supplement_candidate_set,
    ):
        source = inspect.getsource(function)
        assert "materials.get_many(" in source
        assert "materials.get(" not in source
        assert "AnnotationRepository(project_dir(project_id)).get_many(" in source


def test_explicit_training_rejects_cleaned_unannotated_selection_before_snapshot(
    client, seeded_project
):
    import app as app_module
    from platform_core.material_repository import MaterialRepository

    project_id, _ = seeded_project
    colors = ["red", "green", "blue", "yellow", "purple", "orange"]
    formal = []
    for index, color in enumerate(colors):
        uploaded = client.post(
            f"/api/projects/{project_id}/images",
            files=[("files", (f"formal-{index}.jpg", _image_bytes(color), "image/jpeg"))],
            data={"dataset_id": "default"},
        ).json()["uploaded"][0]
        formal.append(_mark_training_ready(client, project_id, uploaded))

    pending = client.post(
        f"/api/projects/{project_id}/images",
        files=[("files", ("pending-cleaned.jpg", _image_bytes("gray"), "image/jpeg"))],
        data={"dataset_id": "default"},
    ).json()["uploaded"][0]
    MaterialRepository(app_module.project_dir(project_id)).patch({
        pending["id"]: {
            "processing_status": "processed",
            "cleaned_at": "2026-09-28T00:00:00+00:00",
        }
    })

    algorithm = client.post(
        f"/api/v12/projects/{project_id}/algorithms",
        json={"name": "待标注候选训练", "algorithm_type": "yolo_ultralytics"},
    ).json()["algorithm"]
    selected_ids = [row["id"] for row in formal] + [pending["id"]]

    response = client.post(
        f"/api/v12/projects/{project_id}/train/start",
        json={
            "framework": "ultralytics",
            "algorithm_asset_id": algorithm["id"],
            "model": "yolo11n.pt",
            "train_labels": ["fire"],
            "split_mode": "random_test_from_training_pool",
            "train_image_ids": selected_ids,
            "test_image_ids": [],
            "experiment_percent": 20,
            "validation_percent": 20,
            "device": "cpu",
        },
    )

    assert response.status_code == 409, response.text
    detail = json.loads(response.json()["detail"])
    assert detail["code"] == "TRAINING_MATERIAL_SCOPE_INCOMPATIBLE"
    pending_issue = next(
        item for item in detail["items"] if item["image_id"] == pending["id"]
    )
    assert pending_issue["issue_type"] == "missing_annotation"
    assert pending_issue["missing_label_codes"] == ["fire"]


def _training_create_replay_fixture(client, seeded_project):
    """One real project and an admitted material selection; no training worker is started."""
    project_id, first = seeded_project
    train_a = _mark_training_ready(client, project_id, first)
    train_b = _upload_training_ready(client, project_id, "idempotent-b.jpg", (33, 74, 110))
    test_a = _upload_training_ready(client, project_id, "idempotent-test.jpg", (90, 41, 77))
    algorithm = client.post(
        f"/api/v12/projects/{project_id}/algorithms",
        json={"name": "训练创建并发保护", "algorithm_type": "yolo_ultralytics"},
    ).json()["algorithm"]
    return project_id, {
        "task_id": "train_" + hashlib.sha256(project_id.encode()).hexdigest()[:24],
        "framework": "ultralytics",
        "algorithm_asset_id": algorithm["id"],
        "model": "yolo11n.pt",
        "train_labels": ["fire"],
        "split_mode": "independent_test_set",
        "train_image_ids": [train_a["id"], train_b["id"]],
        "test_image_ids": [test_a["id"]],
        "validation_percent": 20,
        "experiment_percent": None,
        "queue_priority": 7,
    }


def test_concurrent_same_training_id_does_not_overwrite_winner_immutable_payload(
    client, seeded_project, monkeypatch,
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from platform_core.task_runtime import TaskKind, TaskRepository
    import app as app_module

    project_id, request = _training_create_replay_fixture(client, seeded_project)
    entered_after_parent_insert = Event()
    allow_first_to_finish = Event()
    second_started = Event()
    original_create = TaskRepository.create

    def pause_after_first_parent_insert(repository, record, *args, **kwargs):
        result = original_create(repository, record, *args, **kwargs)
        if record.task_id == request["task_id"] and record.kind is TaskKind.TRAINING:
            entered_after_parent_insert.set()
            assert allow_first_to_finish.wait(12), "first create never released"
        return result

    monkeypatch.setattr(TaskRepository, "create", pause_after_first_parent_insert)
    url = f"/api/v12/projects/{project_id}/train/start"
    different = {**request, "queue_priority": 8}

    def second_call():
        second_started.set()
        return client.post(url, json=different)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(client.post, url, json=request)
        try:
            assert entered_after_parent_insert.wait(12)
            second = executor.submit(second_call)
            assert second_started.wait(12)
            # An old check-before-lock implementation would already return
            # after observing the inserted parent, before its child is ready.
            assert not second.done()
        finally:
            allow_first_to_finish.set()
        accepted = first.result(timeout=20)
        conflicting = second.result(timeout=20)

    assert accepted.status_code == 202, accepted.text
    assert conflicting.status_code == 409, conflicting.text
    stored = app_module.shared_task_artifacts().read_json(request["task_id"], "payload.json")
    assert stored["queue_priority"] == 7
    assert stored["admission_request"]["queue_priority"] == 7
    assert stored["training_prepare_task_id"] == f"trainprep_{request['task_id']}"
    parent = app_module.shared_task_repository().get(request["task_id"])
    assert parent.priority == 7
    assert app_module.shared_task_repository().get(stored["training_prepare_task_id"]) is not None
    repeated = client.post(url, json=request)
    assert repeated.status_code == 202, repeated.text
    assert repeated.json()["idempotent"] is True
    assert app_module.shared_task_artifacts().read_json(request["task_id"], "payload.json") == stored


def test_training_prepare_child_creation_failure_recovers_with_same_task_id(
    client, seeded_project, monkeypatch,
):
    from platform_core.task_runtime import TaskKind, TaskRepository, TaskStatus
    import app as app_module

    project_id, request = _training_create_replay_fixture(client, seeded_project)
    original_create = TaskRepository.create
    failed_once = {"value": False}

    def fail_child_once(repository, record, *args, **kwargs):
        if (
            record.kind is TaskKind.TRAINING_PREPARE
            and record.task_id == f"trainprep_{request['task_id']}"
            and not failed_once["value"]
        ):
            failed_once["value"] = True
            raise RuntimeError("injected child SQLite failure")
        return original_create(repository, record, *args, **kwargs)

    monkeypatch.setattr(TaskRepository, "create", fail_child_once)
    with pytest.raises(RuntimeError, match="injected child SQLite failure"):
        app_module.v12_start_train(project_id, app_module.TrainReq(**request))
    assert failed_once["value"]
    parent = app_module.shared_task_repository().get(request["task_id"])
    assert parent.status is TaskStatus.BLOCKED_BY_ENVIRONMENT
    assert parent.stage == "training_input_preparation_failed"
    assert app_module.shared_task_repository().get(f"trainprep_{request['task_id']}") is None
    before = app_module.shared_task_artifacts().read_json(request["task_id"], "payload.json")
    assert (app_module.project_dir(project_id) / "jobs" / request["task_id"] / "job.json").is_file()

    monkeypatch.setattr(TaskRepository, "create", original_create)
    response = client.post(f"/api/v12/projects/{project_id}/train/start", json=request)
    assert response.status_code == 202, response.text
    assert response.json()["idempotent"] is True
    parent = app_module.shared_task_repository().get(request["task_id"])
    child = app_module.shared_task_repository().get(f"trainprep_{request['task_id']}")
    assert parent.status is TaskStatus.QUEUED
    assert child.kind is TaskKind.TRAINING_PREPARE
    assert child.status is TaskStatus.QUEUED
    assert app_module.shared_task_artifacts().read_json(request["task_id"], "payload.json") == before
    assert app_module.shared_task_artifacts().read_json(child.task_id, "payload.json") == {
        "schema_version": 2,
        "training_task_id": request["task_id"],
        "project_id": project_id,
    }
    mismatched = client.post(
        f"/api/v12/projects/{project_id}/train/start",
        json={**request, "queue_priority": 5},
    )
    assert mismatched.status_code == 409


def test_training_parent_insert_crash_recovers_missing_job_and_prepare_child(
    client, seeded_project, monkeypatch,
):
    from platform_core.task_runtime import TaskKind, TaskRepository, TaskStatus
    import app as app_module

    project_id, request = _training_create_replay_fixture(client, seeded_project)
    original_create = TaskRepository.create

    def crash_after_parent_insert(repository, record, *args, **kwargs):
        result = original_create(repository, record, *args, **kwargs)
        if record.kind is TaskKind.TRAINING and record.task_id == request["task_id"]:
            raise SystemExit("injected crash after parent INSERT")
        return result

    monkeypatch.setattr(TaskRepository, "create", crash_after_parent_insert)
    with pytest.raises(SystemExit, match="injected crash"):
        app_module.v12_start_train(project_id, app_module.TrainReq(**request))
    parent = app_module.shared_task_repository().get(request["task_id"])
    assert parent.status is TaskStatus.QUEUED
    assert app_module.shared_task_repository().get(f"trainprep_{request['task_id']}") is None
    job_path = app_module.project_dir(project_id) / "jobs" / request["task_id"] / "job.json"
    assert not job_path.is_file()
    frozen = app_module.shared_task_artifacts().read_json(request["task_id"], "payload.json")

    monkeypatch.setattr(TaskRepository, "create", original_create)
    replay = client.post(f"/api/v12/projects/{project_id}/train/start", json=request)
    assert replay.status_code == 202, replay.text
    assert replay.json()["idempotent"] is True
    assert job_path.is_file()
    assert app_module.shared_task_repository().get(f"trainprep_{request['task_id']}").status is TaskStatus.QUEUED
    assert app_module.shared_task_artifacts().read_json(request["task_id"], "payload.json") == frozen
