import hashlib
import json
import uuid
from types import SimpleNamespace

import app as app_module

from platform_core.annotation_repository import AnnotationRepository
from platform_core.material_batches import MaterialBatchHandler
import platform_core.material_batches as material_batches_module
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


def _run_integrity_audit(client, scheduler, project_id):
    created = client.post(f"/api/v62/projects/{project_id}/material-integrity/audits")
    assert created.status_code == 202, created.text
    assert scheduler.run_once() is True
    return created.json()["task_id"]


def _duplicate_material(source, image_id, filename, **changes):
    """Clone source identity without copying derived annotation projections."""
    row = {
        key: value for key, value in source.items()
        if not key.startswith("annotation_")
        and key not in {"annotated", "box_count", "labels", "updated_at"}
    }
    row.update({"id": image_id, "filename": filename, **changes})
    return row


def test_material_integrity_audit_groups_duplicate_annotation_conflicts(
    client, seeded_project, tmp_path, monkeypatch
):
    project_id, first = seeded_project
    materials = app_module.material_store(project_id)
    first = materials.get(first["id"])
    second = _duplicate_material(
        first, "duplicate-conflict",
        "duplicate-conflict" + (first.get("filename") or ".jpg")[-4:],
    )
    materials.upsert(second)
    annotations = AnnotationRepository(app_module.project_dir(project_id))
    annotations.upsert(
        first["id"],
        [{"label": "fire", "class_id": 0, "x1": 1, "y1": 1, "x2": 12, "y2": 12}],
        annotation_state="annotated",
    )
    annotations.upsert(
        second["id"],
        [{"label": "fire", "class_id": 0, "x1": 4, "y1": 4, "x2": 20, "y2": 20}],
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

    automatic = client.post(
        f"/api/v62/projects/{project_id}/material-integrity/audits/{task_id}/dedup-plans",
        json={"scope": "SAFE_ALL"},
    )
    assert automatic.status_code == 201, automatic.text
    assert automatic.json()["delete_count"] == 0
    assert automatic.json()["manual_required_groups"] == 1

    manual = client.post(
        f"/api/v62/projects/{project_id}/material-integrity/audits/{task_id}/dedup-plans",
        json={
            "scope": "MANUAL_GROUPS",
            "group_keys": [conflict["group_key"]],
            "manual_decisions": {conflict["group_key"]: first["id"]},
        },
    )
    assert manual.status_code == 201, manual.text
    assert manual.json()["delete_count"] == 1
    execute = client.post(
        f"/api/v62/projects/{project_id}/material-integrity/audits/{task_id}/"
        f"dedup-plans/{manual.json()['plan_id']}/execute",
        json={"confirmation_credential": manual.json()["confirmation_credential"]},
    )
    assert execute.status_code == 202, execute.text
    assert execute.json()["operation"] == "DELETE_INDEX"


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
    second = _duplicate_material(first, "shared-object-copy", "shared-object-copy.jpg")
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


def test_filtered_dog_delete_removes_only_dog_material_and_its_annotation_files(
    client, seeded_project, tmp_path, monkeypatch
):
    project_id, original = seeded_project
    materials = app_module.material_store(project_id)
    source = materials.get(original["id"])
    project = app_module.project_dir(project_id)
    annotations = AnnotationRepository(project)
    rows = [
        _duplicate_material(
            source, f"filtered-{name}", f"{name}.jpg",
            processing_status="processed",
        )
        for name in ("fire", "smoke")
    ]
    materials.upsert_many(rows)
    for name in ("fire", "smoke"):
        image_id = f"filtered-{name}"
        annotations.upsert(
            image_id,
            [{"label": name, "class_id": 0, "x1": 1, "y1": 1,
              "x2": 12, "y2": 12}],
            annotation_state="annotated",
        )
        legacy = project / "annotations" / f"{image_id}.json"
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_text('{"boxes":[]}', encoding="utf-8")
    _repo, _artifacts, scheduler = _runtime(tmp_path, monkeypatch)
    payload = {
        "operation": "DELETE_INDEX",
        "selection_spec": {"scope": "FILTERED", "filters": {
            "labels": ["fire"], "processing_status": "processed",
        }},
    }
    estimate = client.post(
        f"/api/v62/projects/{project_id}/material-batches/estimate",
        json=payload,
    )
    assert estimate.status_code == 200, estimate.text
    assert estimate.json()["count"] == 1
    payload["selection_spec"] = estimate.json()["selection_spec"]
    task = client.post(f"/api/v62/projects/{project_id}/material-batches", json=payload)
    assert task.status_code == 202, task.text
    assert scheduler.run_once() is True
    assert materials.get("filtered-fire") is None
    assert not annotations.exists("filtered-fire")
    assert not (project / "annotations" / "filtered-fire.json").exists()
    assert materials.get("filtered-smoke") is not None
    assert annotations.exists("filtered-smoke")
    assert (project / "annotations" / "filtered-smoke.json").exists()
    assert materials.get(original["id"]) is not None


def test_material_integrity_safe_plan_keeps_one_and_executes_existing_delete_index(
    client, seeded_project, tmp_path, monkeypatch
):
    project_id, original = seeded_project
    materials = app_module.material_store(project_id)
    source = materials.get(original["id"])
    copies = [
        _duplicate_material(source, f"safe-duplicate-{index}", f"safe-{index}.jpg")
        for index in range(4)
    ]
    materials.upsert_many(copies)
    annotations = AnnotationRepository(app_module.project_dir(project_id))
    for image_id in [original["id"], *(row["id"] for row in copies)]:
        annotations.upsert(image_id, [], annotation_state="confirmed_empty")
    _repository, _artifacts, scheduler = _runtime(tmp_path, monkeypatch)
    audit_id = _run_integrity_audit(client, scheduler, project_id)

    preview = client.post(
        f"/api/v62/projects/{project_id}/material-integrity/audits/{audit_id}/dedup-plans",
        json={"scope": "SAFE_ALL"},
    )
    assert preview.status_code == 201, preview.text
    plan = preview.json()
    assert plan["included_groups"] == 1
    assert plan["delete_count"] == 4
    assert plan["kept_count"] == 1
    assert plan["operation"] == "DELETE_INDEX"

    queued = client.post(
        f"/api/v62/projects/{project_id}/material-integrity/audits/{audit_id}/"
        f"dedup-plans/{plan['plan_id']}/execute",
        json={"confirmation_credential": plan["confirmation_credential"]},
    )
    assert queued.status_code == 202, queued.text
    assert queued.json()["total"] == 4
    assert queued.json()["planned_groups"] == 1
    assert queued.json()["completed_groups"] == 0
    assert queued.json()["kept_count"] == 1
    repeated = client.post(
        f"/api/v62/projects/{project_id}/material-integrity/audits/{audit_id}/"
        f"dedup-plans/{plan['plan_id']}/execute",
        json={"confirmation_credential": plan["confirmation_credential"]},
    )
    assert repeated.status_code == 202, repeated.text
    assert repeated.json()["task_id"] == queued.json()["task_id"]
    assert scheduler.run_once() is True
    finished = client.get(
        f"/api/v62/projects/{project_id}/material-batches/{queued.json()['task_id']}"
    )
    assert finished.status_code == 200, finished.text
    assert finished.json()["status"] == "SUCCEEDED", finished.text
    assert finished.json()["completed_groups"] == 1
    assert finished.json()["failed_groups"] == 0
    remaining = [
        image_id for image_id in [original["id"], *(row["id"] for row in copies)]
        if materials.get(image_id) is not None
    ]
    assert len(remaining) == 1


def test_material_integrity_plan_rejects_stale_material_revision(
    client, seeded_project, tmp_path, monkeypatch
):
    project_id, original = seeded_project
    materials = app_module.material_store(project_id)
    source = materials.get(original["id"])
    materials.upsert(_duplicate_material(source, "stale-duplicate", "stale.jpg"))
    _repository, _artifacts, scheduler = _runtime(tmp_path, monkeypatch)
    audit_id = _run_integrity_audit(client, scheduler, project_id)
    preview = client.post(
        f"/api/v62/projects/{project_id}/material-integrity/audits/{audit_id}/dedup-plans",
        json={"scope": "SAFE_ALL"},
    ).json()
    materials.upsert(_duplicate_material(source, "revision-bump", "revision-bump.jpg"))

    response = client.post(
        f"/api/v62/projects/{project_id}/material-integrity/audits/{audit_id}/"
        f"dedup-plans/{preview['plan_id']}/execute",
        json={"confirmation_credential": preview["confirmation_credential"]},
    )
    assert response.status_code == 409, response.text
    assert "MATERIAL_INTEGRITY_PLAN_STALE" in response.text


def test_material_integrity_worker_skips_group_when_keeper_changes_after_queue(
    client, seeded_project, tmp_path, monkeypatch
):
    project_id, original = seeded_project
    materials = app_module.material_store(project_id)
    source = materials.get(original["id"])
    copies = [
        _duplicate_material(source, f"late-duplicate-{index}", f"late-{index}.jpg")
        for index in range(2)
    ]
    materials.upsert_many(copies)
    _repository, _artifacts, scheduler = _runtime(tmp_path, monkeypatch)
    audit_id = _run_integrity_audit(client, scheduler, project_id)
    plan = client.post(
        f"/api/v62/projects/{project_id}/material-integrity/audits/{audit_id}/dedup-plans",
        json={"scope": "SAFE_ALL"},
    ).json()
    queued = client.post(
        f"/api/v62/projects/{project_id}/material-integrity/audits/{audit_id}/"
        f"dedup-plans/{plan['plan_id']}/execute",
        json={"confirmation_credential": plan["confirmation_credential"]},
    )
    assert queued.status_code == 202, queued.text
    keeper_id = plan["preview_groups"][0]["keeper_image_id"]
    materials.remove_many([keeper_id], batch_size=1)

    assert scheduler.run_once() is True
    finished = client.get(
        f"/api/v62/projects/{project_id}/material-batches/{queued.json()['task_id']}"
    ).json()
    assert finished["status"] == "FAILED"
    assert finished["failed_groups"] == 1
    assert finished["succeeded"] == 0
    planned_deletes = {
        original["id"], *(row["id"] for row in copies)
    } - {keeper_id}
    assert all(materials.get(image_id) is not None for image_id in planned_deletes)


def test_material_integrity_safe_plan_skips_groups_with_multiple_training_references(
    client, seeded_project, tmp_path, monkeypatch
):
    project_id, original = seeded_project
    materials = app_module.material_store(project_id)
    source = materials.get(original["id"])
    duplicate_id = "protected-duplicate"
    materials.upsert(_duplicate_material(source, duplicate_id, "protected.jpg"))
    repository, artifacts, scheduler = _runtime(tmp_path, monkeypatch)
    training_id = "train_" + uuid.uuid4().hex[:20]
    artifacts.atomic_write_json(
        training_id, "payload.json",
        {"train_image_ids": [original["id"], duplicate_id]},
    )
    repository.create(TaskRecord.new(
        training_id, project_id, TaskKind.TRAINING, "payload.json", "training-protected",
        required_capabilities=("training.input.ready",),
    ), artifacts=artifacts)
    audit_id = _run_integrity_audit(client, scheduler, project_id)

    response = client.post(
        f"/api/v62/projects/{project_id}/material-integrity/audits/{audit_id}/dedup-plans",
        json={"scope": "SAFE_ALL"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["delete_count"] == 0
    assert response.json()["protected_groups"] == 1
    assert response.json()["skip_reasons"]["MULTIPLE_PROTECTED_REFERENCES"] == 1


def test_material_integrity_plan_keeps_snapshot_referenced_identity(
    client, seeded_project, tmp_path, monkeypatch
):
    project_id, original = seeded_project
    materials = app_module.material_store(project_id)
    source = materials.get(original["id"])
    duplicate_id = "snapshot-duplicate"
    materials.upsert(_duplicate_material(source, duplicate_id, "snapshot.jpg"))
    snapshots = app_module.project_dir(project_id) / "snapshots"
    snapshots.mkdir(parents=True, exist_ok=True)
    (snapshots / "training.json").write_text(
        json.dumps({"train_image_ids": [original["id"]]}), encoding="utf-8"
    )
    _repository, _artifacts, scheduler = _runtime(tmp_path, monkeypatch)
    audit_id = _run_integrity_audit(client, scheduler, project_id)

    plan = client.post(
        f"/api/v62/projects/{project_id}/material-integrity/audits/{audit_id}/dedup-plans",
        json={"scope": "SAFE_ALL"},
    ).json()
    assert plan["delete_count"] == 1
    assert plan["preview_groups"][0]["keeper_image_id"] == original["id"]
    assert plan["preview_groups"][0]["keeper_reason"] == "HISTORICAL_REFERENCE"


def test_material_integrity_plan_can_freeze_more_than_500_deletes_without_browser_ids(
    client, seeded_project, tmp_path, monkeypatch
):
    project_id, original = seeded_project
    materials = app_module.material_store(project_id)
    source = materials.get(original["id"])
    materials.upsert_many([
        _duplicate_material(
            source, f"scale-duplicate-{index:04d}", f"scale-{index:04d}.jpg"
        )
        for index in range(501)
    ])
    _repository, _artifacts, scheduler = _runtime(tmp_path, monkeypatch)
    audit_id = _run_integrity_audit(client, scheduler, project_id)

    response = client.post(
        f"/api/v62/projects/{project_id}/material-integrity/audits/{audit_id}/dedup-plans",
        json={"scope": "SAFE_ALL"},
    )
    assert response.status_code == 201, response.text
    plan = response.json()
    assert plan["delete_count"] == 501
    assert "image_ids" not in plan
    rejected = client.post(
        f"/api/v62/projects/{project_id}/material-integrity/audits/{audit_id}/"
        f"dedup-plans/{plan['plan_id']}/execute",
        json={"confirmation_credential": "wrong-credential"},
    )
    assert rejected.status_code == 409, rejected.text
    queued = client.post(
        f"/api/v62/projects/{project_id}/material-integrity/audits/{audit_id}/"
        f"dedup-plans/{plan['plan_id']}/execute",
        json={"confirmation_credential": plan["confirmation_credential"]},
    )
    assert queued.status_code == 202, queued.text
    assert queued.json()["total"] == 501
    assert scheduler.run_once() is True
    candidate_ids = [
        original["id"],
        *(f"scale-duplicate-{index:04d}" for index in range(501)),
    ]
    remaining = []
    for offset in range(0, len(candidate_ids), 500):
        remaining.extend(materials.get_many(candidate_ids[offset:offset + 500]))
    assert len(remaining) == 1


def test_material_integrity_server_plan_covers_more_than_100_groups_across_sources(
    client, seeded_project, tmp_path, monkeypatch
):
    project_id, original = seeded_project
    materials = app_module.material_store(project_id)
    source = materials.get(original["id"])
    rows = []
    for group_index in range(120):
        digest = hashlib.sha256(f"integrity-group-{group_index}".encode()).hexdigest()
        for copy_index in range(2):
            rows.append(_duplicate_material(
                source,
                f"many-{group_index:03d}-{copy_index}",
                f"many-{group_index:03d}-{copy_index}.jpg",
                content_sha256=digest,
                storage_source_id=("source-a" if copy_index == 0 else "source-b"),
            ))
    materials.upsert_many(rows)
    object_path = app_module.project_dir(project_id) / str(source["object_key"])
    monkeypatch.setattr(
        material_batches_module.StorageManager,
        "materialize",
        lambda _self, row: SimpleNamespace(
            path=object_path, content_sha256=str(row.get("content_sha256") or "")
        ),
    )
    monkeypatch.setattr(
        material_batches_module.CleaningAnalysisRuntime,
        "analyze",
        lambda _self, *_args, **_kwargs: {},
    )
    _repository, _artifacts, scheduler = _runtime(tmp_path, monkeypatch)
    audit_id = _run_integrity_audit(client, scheduler, project_id)

    first_page = client.get(
        f"/api/v62/projects/{project_id}/material-integrity/audits/{audit_id}/groups?"
        "limit=100&issue_type=DUPLICATE_IDENTICAL"
    ).json()
    assert len(first_page["items"]) == 100
    assert first_page["next_cursor"]
    second_page = client.get(
        f"/api/v62/projects/{project_id}/material-integrity/audits/{audit_id}/groups?"
        f"limit=100&issue_type=DUPLICATE_IDENTICAL&cursor={first_page['next_cursor']}"
    ).json()
    assert len(second_page["items"]) == 20

    plan = client.post(
        f"/api/v62/projects/{project_id}/material-integrity/audits/{audit_id}/dedup-plans",
        json={"scope": "SAFE_ALL"},
    ).json()
    assert plan["included_groups"] == 120
    assert plan["delete_count"] == 120
    assert len(plan["preview_groups"]) == 20
    assert plan["preview_groups_truncated"] is True
