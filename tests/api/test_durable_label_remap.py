import app as app_module

from platform_core.annotation_repository import AnnotationRepository
from platform_core.material_batches import (
    BatchSelection,
    MaterialBatchHandler,
    create_annotation_remap_batch,
)
from platform_core.task_runtime import (
    ArtifactStore,
    Scheduler,
    TaskKind,
    TaskRepository,
)


def _box(label="fire", class_id=0, x1=1):
    return {
        "id": "box-1",
        "class_id": class_id,
        "label": label,
        "x1": x1,
        "y1": 1,
        "x2": 30,
        "y2": 30,
    }


def _isolated_runtime(tmp_path, monkeypatch):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    artifacts = ArtifactStore(tmp_path / "artifacts")
    monkeypatch.setattr(app_module, "_SHARED_TASK_REPOSITORY", repository)
    monkeypatch.setattr(app_module, "_SHARED_TASK_ARTIFACTS", artifacts)
    scheduler = Scheduler(
        repository,
        artifacts,
        "label-remap-worker",
        {TaskKind.MATERIAL_BATCH: MaterialBatchHandler(app_module.DATA_DIR)},
        {"materials.batch"},
        lease_seconds=10,
    )
    return repository, artifacts, scheduler


def test_v52_label_remap_is_durable_and_mutates_only_in_worker(
    client, seeded_project, tmp_path, monkeypatch
):
    project_id, image = seeded_project
    app_module.write_annotation(project_id, image["id"], [_box()])
    repository, _artifacts, scheduler = _isolated_runtime(tmp_path, monkeypatch)

    created = client.post(
        f"/api/v52/projects/{project_id}/labels/remap",
        json={
            "image_ids": [image["id"]],
            "source_label": "fire",
            "target_label": "smoke",
        },
    )
    assert created.status_code == 202, created.text
    task_id = created.json()["task_id"]
    assert created.json()["operation"] == "REMAP_ANNOTATION_LABELS"
    assert created.json()["total"] == 1
    assert app_module.read_annotation(project_id, image["id"])["boxes"][0]["label"] == "fire"

    assert scheduler.run_once() is True
    task = client.get(
        f"/api/v62/projects/{project_id}/material-batches/{task_id}"
    ).json()
    assert task["status"] == "SUCCEEDED"
    assert task["processed"] == 1
    assert task["changed_images"] == 1
    assert task["changed_boxes"] == 1
    assert task["progress_percent"] == 100

    formal = app_module.read_annotation(project_id, image["id"])
    assert formal["boxes"][0]["label"] == "smoke"
    assert formal["boxes"][0]["class_id"] == 1
    material = app_module.material_store(project_id).get_many([image["id"]])[0]
    assert material["labels"] == ["smoke"]
    assert repository.get(task_id).result_ref == "result.json"


def test_label_remap_fails_closed_if_target_is_disabled_before_worker(
    client, seeded_project, tmp_path, monkeypatch
):
    project_id, image = seeded_project
    app_module.write_annotation(project_id, image["id"], [_box()])
    _repository, _artifacts, scheduler = _isolated_runtime(tmp_path, monkeypatch)

    created = client.post(
        f"/api/v52/projects/{project_id}/labels/remap",
        json={
            "image_ids": [image["id"]],
            "source_label": "fire",
            "target_label": "smoke",
        },
    )
    assert created.status_code == 202, created.text
    task_id = created.json()["task_id"]

    project = app_module.get_project(project_id)
    project["label_meta"][1]["status"] = "inactive"
    app_module.save_project(project)

    assert scheduler.run_once() is True
    task = client.get(
        f"/api/v62/projects/{project_id}/material-batches/{task_id}"
    ).json()
    assert task["status"] == "FAILED"
    assert app_module.read_annotation(project_id, image["id"])["boxes"][0]["label"] == "fire"


def test_label_remap_does_not_overwrite_concurrent_human_annotation(
    client, seeded_project, tmp_path, monkeypatch
):
    project_id, image = seeded_project
    app_module.write_annotation(project_id, image["id"], [_box()])
    _repository, _artifacts, scheduler = _isolated_runtime(tmp_path, monkeypatch)

    created = client.post(
        f"/api/v52/projects/{project_id}/labels/remap",
        json={
            "image_ids": [image["id"]],
            "source_label": "fire",
            "target_label": "smoke",
        },
    )
    assert created.status_code == 202, created.text
    task_id = created.json()["task_id"]

    original = AnnotationRepository.remap_labels_if_digests
    injected = {"done": False}

    def race(self, requests, **kwargs):
        if not injected["done"]:
            injected["done"] = True
            app_module.write_annotation(project_id, image["id"], [_box(x1=7)])
        return original(self, requests, **kwargs)

    monkeypatch.setattr(AnnotationRepository, "remap_labels_if_digests", race)
    assert scheduler.run_once() is True

    task = client.get(
        f"/api/v62/projects/{project_id}/material-batches/{task_id}"
    ).json()
    assert task["status"] == "FAILED"
    assert task["failed"] == 1
    formal = app_module.read_annotation(project_id, image["id"])
    assert formal["boxes"][0]["label"] == "fire"
    assert formal["boxes"][0]["x1"] == 7


def test_label_remap_retry_is_idempotent_after_ground_truth_commit(
    client, seeded_project, tmp_path, monkeypatch
):
    project_id, image = seeded_project
    app_module.write_annotation(project_id, image["id"], [_box()])
    repository, _artifacts, scheduler = _isolated_runtime(tmp_path, monkeypatch)

    created = client.post(
        f"/api/v52/projects/{project_id}/labels/remap",
        json={
            "image_ids": [image["id"]],
            "source_label": "fire",
            "target_label": "smoke",
        },
    )
    assert created.status_code == 202, created.text
    task_id = created.json()["task_id"]

    original_transition = BatchSelection.transition
    failed_once = {"done": False}

    def interrupt_after_write(self, ids, state, error=None):
        if state == "succeeded" and not failed_once["done"]:
            failed_once["done"] = True
            raise RuntimeError("simulated checkpoint boundary crash")
        return original_transition(self, ids, state, error)

    monkeypatch.setattr(BatchSelection, "transition", interrupt_after_write)
    assert scheduler.run_once() is True
    assert repository.get(task_id).status.value == "FAILED"
    assert app_module.read_annotation(project_id, image["id"])["boxes"][0]["label"] == "smoke"

    monkeypatch.setattr(BatchSelection, "transition", original_transition)
    repository.retry(task_id)
    assert scheduler.run_once() is True
    final = client.get(
        f"/api/v62/projects/{project_id}/material-batches/{task_id}"
    ).json()
    assert final["status"] == "SUCCEEDED"
    assert final["changed_images"] == 1
    assert final["changed_boxes"] == 1
    assert app_module.read_annotation(project_id, image["id"])["boxes"][0]["label"] == "smoke"


def test_specialized_remap_selection_can_freeze_more_than_generic_explicit_limit(
    client, tmp_path, monkeypatch
):
    project = client.post(
        "/api/projects",
        json={
            "name": "large-remap-selection",
            "labels": [
                {"code": "fire", "display_name": "明火"},
                {"code": "smoke", "display_name": "烟雾"},
            ],
        },
    ).json()
    project_id = project["id"]
    materials = app_module.material_store(project_id)
    rows = [
        {"id": f"bulk-{index:04d}", "filename": f"{index:04d}.jpg"}
        for index in range(1501)
    ]
    materials.upsert_many(rows)

    repository = TaskRepository(tmp_path / "large-tasks.sqlite3")
    artifacts = ArtifactStore(tmp_path / "large-artifacts")
    task = create_annotation_remap_batch(
        project_id,
        materials,
        repository,
        artifacts,
        [row["id"] for row in rows],
        "fire",
        "smoke",
    )
    checkpoint = artifacts.read_json(
        task.task_id, "checkpoints/worker.json", default={}
    )
    assert checkpoint["selection_frozen"] is True
    assert checkpoint["total"] == 1501
    assert repository.get(task.task_id).status.value == "QUEUED"
