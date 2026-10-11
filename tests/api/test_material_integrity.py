import json
import uuid

import app as app_module

from platform_core.annotation_repository import AnnotationRepository
from platform_core.material_batches import MaterialBatchHandler
from platform_core.task_runtime import (
    ArtifactStore,
    Scheduler,
    TaskKind,
    TaskRecord,
    TaskRepository,
)


def _runtime(tmp_path, monkeypatch):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    artifacts = ArtifactStore(tmp_path / "artifacts")
    monkeypatch.setattr(app_module, "_SHARED_TASK_REPOSITORY", repository)
    monkeypatch.setattr(app_module, "_SHARED_TASK_ARTIFACTS", artifacts)
    scheduler = Scheduler(
        repository,
        artifacts,
        "material-integrity-worker",
        {TaskKind.MATERIAL_BATCH: MaterialBatchHandler(app_module.DATA_DIR)},
        {"materials.batch"},
        lease_seconds=10,
    )
    return repository, artifacts, scheduler


def test_material_integrity_audit_groups_duplicate_annotation_conflicts(
    client, seeded_project, tmp_path, monkeypatch
):
    project_id, first = seeded_project
    materials = app_module.material_store(project_id)
    first = materials.get(first["id"])
    second = {
        **first,
        "id": "duplicate-conflict",
        "filename": "duplicate-conflict" + (first.get("filename") or ".jpg")[-4:],
    }
    materials.upsert(second)
    annotations = AnnotationRepository(app_module.project_dir(project_id))
    annotations.upsert(
        first["id"],
        [{"label": "target", "class_id": 0, "x1": 1, "y1": 1, "x2": 12, "y2": 12}],
        annotation_state="annotated",
    )
    annotations.upsert(
        second["id"],
        [{"label": "target", "class_id": 0, "x1": 4, "y1": 4, "x2": 20, "y2": 20}],
        annotation_state="annotated",
    )
    _repository, artifacts, scheduler = _runtime(tmp_path, monkeypatch)

    created = client.post(
        f"/api/v62/projects/{project_id}/material-integrity/audits"
    )
    assert created.status_code == 202, created.text
    task_id = created.json()["task_id"]
    assert created.json()["operation"] == "AUDIT_MATERIAL_INTEGRITY"
    assert not artifacts.artifact_path(task_id, "selection.sqlite3").exists()

    assert scheduler.run_once() is True
    groups = client.get(
        f"/api/v62/projects/{project_id}/material-integrity/audits/{task_id}/groups"
    )
    assert groups.status_code == 200, groups.text
    conflict = next(
        row for row in groups.json()["items"]
        if row["issue_type"] == "DUPLICATE_ANNOTATION_CONFLICT"
    )
    assert conflict["image_count"] == 2

    items = client.get(
        f"/api/v62/projects/{project_id}/material-integrity/audits/{task_id}/groups/"
        f"{conflict['group_key']}/items"
    )
    assert items.status_code == 200, items.text
    assert {row["image_id"] for row in items.json()["items"]} == {
        first["id"], second["id"]
    }
    assert all(row["content_url"].startswith("/api/v61/") for row in items.json()["items"])
    assert all(row["boxes"] for row in items.json()["items"])


def test_material_delete_fails_closed_when_active_training_references_selection(
    client, seeded_project, tmp_path, monkeypatch
):
    project_id, image = seeded_project
    repository, artifacts, _scheduler = _runtime(tmp_path, monkeypatch)
    task_id = "train_" + uuid.uuid4().hex[:20]
    artifacts.atomic_write_json(
        task_id,
        "payload.json",
        {"training_input_state": "PREPARING", "train_image_ids": [image["id"]]},
    )
    repository.create(TaskRecord.new(
        task_id,
        project_id,
        TaskKind.TRAINING,
        "payload.json",
        "training-input-pending",
        required_capabilities=("training.input.ready",),
    ), artifacts=artifacts)

    estimate = client.post(
        f"/api/v62/projects/{project_id}/material-batches/estimate",
        json={
            "operation": "DELETE_INDEX",
            "selection_spec": {"scope": "SELECTED", "image_ids": [image["id"]]},
        },
    )
    assert estimate.status_code == 200, estimate.text
    created = client.post(
        f"/api/v62/projects/{project_id}/material-batches",
        json={
            "operation": "DELETE_INDEX",
            "selection_spec": estimate.json()["selection_spec"],
        },
    )
    assert created.status_code == 409, created.text
    assert "MATERIAL_ACTIVE_TRAINING_REFERENCE" in created.text


def test_durable_index_delete_removes_annotation_truth_but_keeps_shared_object(
    client, seeded_project, tmp_path, monkeypatch
):
    project_id, first = seeded_project
    materials = app_module.material_store(project_id)
    first = materials.get(first["id"])
    second = {**first, "id": "shared-object-copy", "filename": "shared-object-copy.jpg"}
    materials.upsert(second)
    annotations = AnnotationRepository(app_module.project_dir(project_id))
    annotations.upsert(first["id"], [], annotation_state="confirmed_empty")
    annotations.upsert(second["id"], [], annotation_state="confirmed_empty")
    object_path = app_module.project_dir(project_id) / str(first["object_key"])
    _repository, _artifacts, scheduler = _runtime(tmp_path, monkeypatch)

    estimate = client.post(
        f"/api/v62/projects/{project_id}/material-batches/estimate",
        json={
            "operation": "DELETE_INDEX",
            "selection_spec": {"scope": "SELECTED", "image_ids": [second["id"]]},
        },
    )
    created = client.post(
        f"/api/v62/projects/{project_id}/material-batches",
        json={
            "operation": "DELETE_INDEX",
            "selection_spec": estimate.json()["selection_spec"],
        },
    )
    assert created.status_code == 202, created.text
    assert scheduler.run_once() is True
    assert materials.get(second["id"]) is None
    assert not annotations.exists(second["id"])
    assert materials.get(first["id"]) is not None
    assert object_path.is_file()
