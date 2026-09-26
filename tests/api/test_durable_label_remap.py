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
    assert task["result"]["changed_scope_images"] == 0
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


def test_label_remap_does_not_write_orphan_annotation_if_material_is_removed(
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

    app_module.material_store(project_id).remove_many([image["id"]])
    assert scheduler.run_once() is True
    task = client.get(
        f"/api/v62/projects/{project_id}/material-batches/{task_id}"
    ).json()
    assert task["status"] == "FAILED"
    assert task["failed"] == 1
    assert task["error_examples"][0]["error"] == "MATERIAL_NOT_FOUND"
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


def test_label_schema_unify_includes_confirmed_empty_scope(
    client, seeded_project, tmp_path, monkeypatch
):
    project_id, image = seeded_project
    AnnotationRepository(app_module.project_dir(project_id)).upsert(
        image["id"],
        [],
        annotation_state="confirmed_empty",
        annotation_scope=["fire"],
    )
    repository, _artifacts, scheduler = _isolated_runtime(tmp_path, monkeypatch)

    schema = client.get(f"/api/v54/projects/{project_id}/label-schema").json()
    fire = next(row for row in schema["items"] if row["code"] == "fire")
    assert fire["scope_images"] == 1
    assert fire["affected_images"] == 1

    created = client.post(
        f"/api/v54/projects/{project_id}/labels/0/unify",
        json={"target_label": "smoke"},
    )
    assert created.status_code == 202, created.text
    assert created.json()["total"] == 1
    assert scheduler.run_once() is True

    final = client.get(
        f"/api/v62/projects/{project_id}/material-batches/{created.json()['task_id']}"
    ).json()
    assert final["status"] == "SUCCEEDED"
    assert final["changed_images"] == 1
    assert final["changed_boxes"] == 0
    assert final["result"]["changed_scope_images"] == 1
    formal = app_module.read_annotation(project_id, image["id"])
    assert formal["annotation_state"] == "confirmed_empty"
    assert formal["annotation_scope"] == ["smoke"]


def test_used_label_code_edit_fails_fast_instead_of_scanning_annotations(
    client, seeded_project, monkeypatch
):
    project_id, image = seeded_project
    app_module.write_annotation(project_id, image["id"], [_box()])
    monkeypatch.setattr(
        app_module,
        "load_images",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("used label edit must not scan all materials")
        ),
    )
    response = client.put(
        f"/api/v12/projects/{project_id}/labels/0",
        json={"code": "fire_renamed"},
    )
    assert response.status_code == 409
    assert "统一标签" in response.text


def test_unused_label_delete_is_soft_and_preserves_other_class_ids(
    client, seeded_project, monkeypatch
):
    project_id, image = seeded_project
    project = app_module.get_project(project_id)
    app_module.add_label(
        project_id,
        app_module.AddLabelReq(label="person", display_name="人员"),
    )
    app_module.write_annotation(
        project_id,
        image["id"],
        [{
            "id": "person-box",
            "class_id": 2,
            "label": "person",
            "x1": 1, "y1": 1, "x2": 20, "y2": 20,
        }],
    )
    monkeypatch.setattr(
        app_module,
        "load_images",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("soft label delete must not scan all materials")
        ),
    )

    deleted = client.delete(f"/api/v12/projects/{project_id}/labels/1")
    assert deleted.status_code == 200, deleted.text
    assert [row["code"] for row in deleted.json()["items"]] == ["fire", "person"]

    stored = app_module.get_project(project_id)
    assert stored["labels"] == ["fire", "smoke", "person"]
    assert stored["label_meta"][1]["status"] == "inactive"
    assert app_module.read_annotation(project_id, image["id"])["boxes"][0]["class_id"] == 2

    recreated = client.post(
        f"/api/projects/{project_id}/labels",
        json={"label": "smoke", "display_name": "烟雾"},
    )
    assert recreated.status_code == 200, recreated.text
    assert recreated.json()["class_id"] == 1
    active = client.get(f"/api/v12/projects/{project_id}/labels").json()["items"]
    assert [row["code"] for row in active] == ["fire", "smoke", "person"]


def test_multi_source_label_unify_is_one_durable_task_and_retires_sources(
    client, seeded_project, tmp_path, monkeypatch
):
    project_id, image = seeded_project
    created_label = client.post(
        f"/api/projects/{project_id}/labels",
        json={"label": "person", "display_name": "人员"},
    )
    assert created_label.status_code == 200, created_label.text
    app_module.write_annotation(
        project_id,
        image["id"],
        [
            _box(label="fire", class_id=0),
            _box(label="smoke", class_id=1, x1=30, x2=50),
        ],
    )
    second_id = "negative-multi-source"
    app_module.material_store(project_id).upsert({
        "id": second_id,
        "filename": "negative.jpg",
        "stored_name": "negative.jpg",
        "object_key": "uploads/negative.jpg",
    })
    AnnotationRepository(app_module.project_dir(project_id)).upsert(
        second_id,
        [],
        annotation_state="confirmed_empty",
        annotation_scope=["fire", "smoke"],
    )
    # Sync the material projection for the explicit confirmed-empty fixture.
    app_module.material_store(project_id).patch({
        second_id: {
            "annotation_state": "confirmed_empty",
            "annotation_scope": ["fire", "smoke"],
            "annotated": True,
            "labels": [],
            "label_counts": {},
            "box_count": 0,
        }
    })
    repository, _artifacts, scheduler = _isolated_runtime(tmp_path, monkeypatch)

    preview = client.post(
        f"/api/v54/projects/{project_id}/labels/unify/preview",
        json={"source_class_ids": [0, 1]},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["affected_images"] == 2
    assert preview.json()["boxes"] == 2

    created = client.post(
        f"/api/v54/projects/{project_id}/labels/unify",
        json={"source_class_ids": [0, 1], "target_label": "person"},
    )
    assert created.status_code == 202, created.text
    assert created.json()["total"] == 2
    assert scheduler.run_once() is True

    final = client.get(
        f"/api/v62/projects/{project_id}/material-batches/{created.json()['task_id']}"
    ).json()
    assert final["status"] == "SUCCEEDED"
    assert final["changed_boxes"] == 2
    assert final["result"]["changed_scope_images"] == 1
    assert final["result"]["source_labels"] == ["fire", "smoke"]
    assert final["result"]["retired_source_labels"] == ["fire", "smoke"]

    formal = app_module.read_annotation(project_id, image["id"])
    assert [box["label"] for box in formal["boxes"]] == ["person", "person"]
    assert {box["class_id"] for box in formal["boxes"]} == {2}
    negative = app_module.read_annotation(project_id, second_id)
    assert negative["annotation_scope"] == ["person"]

    stored = app_module.get_project(project_id)
    assert stored["labels"] == ["fire", "smoke", "person"]
    assert stored["label_meta"][0]["status"] == "merged"
    assert stored["label_meta"][0]["merged_into"] == "person"
    assert stored["label_meta"][1]["status"] == "merged"
    assert stored["label_meta"][1]["merged_into"] == "person"
    active = client.get(f"/api/v12/projects/{project_id}/labels").json()["items"]
    assert [row["code"] for row in active] == ["person"]


def test_partial_multi_source_unify_does_not_retire_sources(
    client, seeded_project, tmp_path, monkeypatch
):
    project_id, image = seeded_project
    client.post(
        f"/api/projects/{project_id}/labels",
        json={"label": "person", "display_name": "人员"},
    )
    app_module.write_annotation(project_id, image["id"], [_box()])
    second_id = "will-disappear"
    app_module.material_store(project_id).upsert({
        "id": second_id,
        "filename": "gone.jpg",
        "stored_name": "gone.jpg",
        "object_key": "uploads/gone.jpg",
        "labels": ["smoke"],
        "label_counts": {"smoke": 1},
        "box_count": 1,
        "annotated": True,
    })
    AnnotationRepository(app_module.project_dir(project_id)).upsert(
        second_id,
        [_box(label="smoke", class_id=1)],
        annotation_state="annotated",
    )
    repository, _artifacts, scheduler = _isolated_runtime(tmp_path, monkeypatch)

    created = client.post(
        f"/api/v54/projects/{project_id}/labels/unify",
        json={"source_class_ids": [0, 1], "target_label": "person"},
    )
    assert created.status_code == 202, created.text
    app_module.material_store(project_id).remove_many([second_id])
    assert scheduler.run_once() is True

    final = client.get(
        f"/api/v62/projects/{project_id}/material-batches/{created.json()['task_id']}"
    ).json()
    assert final["status"] == "PARTIAL_SUCCESS"
    stored = app_module.get_project(project_id)
    assert stored["label_meta"][0].get("status", "active") == "active"
    assert stored["label_meta"][1].get("status", "active") == "active"
