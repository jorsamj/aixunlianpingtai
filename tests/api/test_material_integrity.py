import hashlib
import json
import uuid
import pytest
import time
import sqlite3
from contextlib import closing
from types import SimpleNamespace

import app as app_module

from platform_core.annotation_repository import AnnotationRepository
from platform_core.material_batches import MaterialBatchHandler
from platform_core.remote_material_lifecycle import RemoteExecutionStagingLifecycle
import platform_core.material_batches as material_batches_module
from platform_core.task_runtime import (
    ArtifactStore,
    Scheduler,
    TaskKind,
    TaskRecord,
    TaskRepository,
    TaskStatus,
)


def test_anomaly_filtered_plan_freezes_full_scope_and_preserves_protected_items(
    client, seeded_project, tmp_path, monkeypatch
):
    project_id, original = seeded_project
    materials = app_module.material_store(project_id)
    source = materials.get(original['id'])
    materials.upsert_many([
        _duplicate_material(source, f'missing-{index:03}', f'missing-{index}.jpg',
                            content_sha256=hashlib.sha256(str(index).encode()).hexdigest(),
                            split='test' if index == 0 else 'unassigned')
        for index in range(125)
    ])
    original_materialize = material_batches_module.StorageManager.materialize
    def materialize(manager, row):
        if str(row['id']).startswith('missing-'):
            raise FileNotFoundError('isolated missing object')
        return original_materialize(manager, row)
    monkeypatch.setattr(material_batches_module.StorageManager, 'materialize', materialize)
    _repository, _artifacts, scheduler = _runtime(tmp_path, monkeypatch)
    audit_id = _run_integrity_audit(client, scheduler, project_id)
    base = f'/api/v62/projects/{project_id}/material-integrity/audits/{audit_id}'
    groups = client.get(base + '/groups?limit=100&issue_type=MATERIAL_OBJECT_MISSING').json()
    assert groups['total_images'] == 125
    assert groups['stale'] is False
    response = client.post(base + '/dedup-plans', json={
        'scope': 'FILTERED', 'issue_type': 'MATERIAL_OBJECT_MISSING',
    })
    assert response.status_code == 201, response.text
    plan = response.json()
    assert plan['selected_count'] == 125
    assert plan['delete_count'] == 124
    assert plan['protected_item_count'] == 1
    assert len(plan['preview_items']) <= 20
    execute_url = base + f"/dedup-plans/{plan['plan_id']}/execute"
    queued = client.post(execute_url, json={'confirmation_credential': plan['confirmation_credential']})
    assert queued.status_code == 202, queued.text
    # Simulate lost publication acknowledgement before metadata was committed.
    path = _artifacts.artifact_path(audit_id, f"dedup-plans/{plan['plan_id']}.sqlite3")
    with closing(sqlite3.connect(path)) as database:
        database.execute("UPDATE plan_metadata SET value_json='null' WHERE key='execution_task_id'")
        database.commit()
    assert client.post(execute_url, json={'confirmation_credential': plan['confirmation_credential']}).json()['task_id'] == queued.json()['task_id']
    assert scheduler.run_once()
    finished = client.get(f"/api/v62/projects/{project_id}/material-batches/{queued.json()['task_id']}").json()
    assert finished['status'] == 'SUCCEEDED', finished
    assert finished['succeeded'] == 124
    assert materials.get('missing-000') is not None
    assert materials.get('missing-124') is None
    assert client.get(base + '/groups').json()['stale'] is True
    stale_items = client.get(base + '/groups/MATERIAL_OBJECT_MISSING:missing-124/items')
    assert stale_items.status_code == 409
    assert 'MATERIAL_INTEGRITY_AUDIT_STALE' in stale_items.text


def test_unverified_anomaly_cannot_be_deleted_by_filtered_plan(
    client, seeded_project, tmp_path, monkeypatch
):
    project_id, image = seeded_project
    def unavailable(*_args):
        raise PermissionError('isolated storage temporarily unavailable')
    monkeypatch.setattr(material_batches_module.StorageManager, 'materialize', unavailable)
    _repository, _artifacts, scheduler = _runtime(tmp_path, monkeypatch)
    audit_id = _run_integrity_audit(client, scheduler, project_id)
    response = client.post(
        f'/api/v62/projects/{project_id}/material-integrity/audits/{audit_id}/dedup-plans',
        json={'scope': 'FILTERED', 'issue_type': 'MATERIAL_SCAN_UNVERIFIED'},
    )
    assert response.status_code == 201, response.text
    assert response.json()['delete_count'] == 0
    assert response.json()['unverifiable_count'] == 1


@pytest.mark.parametrize('count', [1000, 10000])
def test_large_anomaly_scope_stays_server_side_and_preview_is_bounded(
    client, seeded_project, tmp_path, monkeypatch, count, record_property
):
    project_id, original = seeded_project
    materials = app_module.material_store(project_id)
    source = materials.get(original['id'])
    materials.upsert_many([
        _duplicate_material(source, f'scale-{index:05}', f'scale-{index}.jpg',
                            content_sha256=hashlib.sha256(str(index).encode()).hexdigest())
        for index in range(count)
    ])
    original_materialize = material_batches_module.StorageManager.materialize
    def materialize(manager, row):
        if str(row['id']).startswith('scale-'):
            raise FileNotFoundError('isolated unavailable object')
        return original_materialize(manager, row)
    monkeypatch.setattr(material_batches_module.StorageManager, 'materialize', materialize)
    _repository, _artifacts, scheduler = _runtime(tmp_path, monkeypatch)
    audit_id = _run_integrity_audit(client, scheduler, project_id)
    start = time.perf_counter()
    response = client.post(
        f'/api/v62/projects/{project_id}/material-integrity/audits/{audit_id}/dedup-plans',
        json={'scope':'FILTERED', 'issue_type':'MATERIAL_OBJECT_MISSING',
              'excluded_group_keys':['MATERIAL_OBJECT_MISSING:scale-00000']},
    )
    elapsed = time.perf_counter() - start
    assert response.status_code == 201, response.text
    plan = response.json()
    assert plan['selected_count'] == count-1
    assert plan['delete_count'] == count-1
    assert len(plan['preview_items']) == 20
    assert len(response.content) < 20000
    assert 'image_ids' not in plan
    record_property('freeze_seconds', elapsed)
    print(f'FILTERED {count}: {elapsed:.3f}s, preview {len(response.content)} bytes')


def test_anomaly_plan_partial_failure_keeps_changed_annotation_and_history(
    client, seeded_project, tmp_path, monkeypatch
):
    project_id, original = seeded_project
    materials = app_module.material_store(project_id)
    source = materials.get(original['id'])
    materials.upsert_many([
        _duplicate_material(source, f'anomaly-{i}', f'anomaly-{i}.jpg',
                            content_sha256=hashlib.sha256(str(i).encode()).hexdigest())
        for i in range(3)
    ])
    snapshots = materials.project_path / 'snapshots'
    snapshots.mkdir(exist_ok=True)
    (snapshots / 'isolated-history.json').write_text(json.dumps({'test_image_ids':['anomaly-0']}))
    def missing(*_args):
        raise FileNotFoundError('isolated missing source')
    monkeypatch.setattr(material_batches_module.StorageManager, 'materialize', missing)
    _repository, _artifacts, scheduler = _runtime(tmp_path, monkeypatch)
    audit_id = _run_integrity_audit(client, scheduler, project_id)
    base = f'/api/v62/projects/{project_id}/material-integrity/audits/{audit_id}'
    plan = client.post(base+'/dedup-plans', json={
        'scope':'SELECTED_IMAGES', 'image_ids':['anomaly-0','anomaly-1','anomaly-2'],
    }).json()
    assert plan['delete_count'] == 2
    assert plan['protected_item_count'] == 1
    queued = client.post(base+f"/dedup-plans/{plan['plan_id']}/execute", json={'confirmation_credential':plan['confirmation_credential']}).json()
    annotations = AnnotationRepository(materials.project_path)
    annotations.upsert('anomaly-1', [], annotation_state='confirmed_empty')
    assert scheduler.run_once()
    finished = client.get(f"/api/v62/projects/{project_id}/material-batches/{queued['task_id']}").json()
    assert finished['status'] == 'PARTIAL_SUCCESS', finished
    assert finished['succeeded'] == 1
    assert finished['failed'] == 1
    assert materials.get('anomaly-0') and materials.get('anomaly-1')
    assert materials.get('anomaly-2') is None
    assert annotations.get('anomaly-1')['annotation_state'] == 'confirmed_empty'
    assert finished['error_examples'][0]['image_id'] == 'anomaly-1'


def test_anomaly_filter_cannot_bypass_duplicate_keeper_or_conflicting_gt(
    client, seeded_project, tmp_path, monkeypatch
):
    project_id, original = seeded_project
    materials = app_module.material_store(project_id)
    materials.upsert(_duplicate_material(materials.get(original['id']), 'also-missing', 'also-missing.jpg'))
    annotations = AnnotationRepository(materials.project_path)
    annotations.upsert('also-missing', [], annotation_state='confirmed_empty')
    def missing(*_args):
        raise FileNotFoundError('isolated missing shared source')
    monkeypatch.setattr(material_batches_module.StorageManager, 'materialize', missing)
    _repository, _artifacts, scheduler = _runtime(tmp_path, monkeypatch)
    audit_id = _run_integrity_audit(client, scheduler, project_id)
    response = client.post(
        f'/api/v62/projects/{project_id}/material-integrity/audits/{audit_id}/dedup-plans',
        json={'scope':'FILTERED','issue_type':'MATERIAL_OBJECT_MISSING'},
    )
    assert response.status_code == 201, response.text
    assert response.json()['selected_count'] == 2
    assert response.json()['delete_count'] == 0
    assert response.json()['manual_required_count'] == 2


@pytest.mark.parametrize('tamper_manifest', [False, True])
def test_frozen_plan_retries_same_task_after_publication_failure(
    client, seeded_project, tmp_path, monkeypatch, tamper_manifest
):
    project_id, original = seeded_project
    materials = app_module.material_store(project_id)
    materials.upsert(_duplicate_material(materials.get(original['id']), 'publication-copy', 'publication.jpg'))
    repository, _artifacts, scheduler = _runtime(tmp_path, monkeypatch)
    audit_id = _run_integrity_audit(client, scheduler, project_id)
    base=f'/api/v62/projects/{project_id}/material-integrity/audits/{audit_id}'
    plan=client.post(base+'/dedup-plans',json={'scope':'SAFE_ALL'}).json()
    publish=material_batches_module.publish_prepared_batch
    attempts=[]
    def flaky_publish(task, *args):
        attempts.append(task.task_id)
        if len(attempts)==1:
            raise material_batches_module.BatchRequestError('BATCH_PUBLICATION_FAILED','isolated publication unavailable',503)
        return publish(task,*args)
    monkeypatch.setattr(material_batches_module,'publish_prepared_batch',flaky_publish)
    url=base+f"/dedup-plans/{plan['plan_id']}/execute"
    payload={'confirmation_credential':plan['confirmation_credential']}
    assert client.post(url,json=payload).status_code==503
    assert repository.get(plan['plan_id']) is None
    if tamper_manifest:
        path=_artifacts.artifact_path(plan['plan_id'],material_batches_module.SELECTION_REF)
        with closing(sqlite3.connect(path)) as database:
            database.execute("UPDATE integrity_plan_items SET annotation_digest='isolated-tamper'")
            database.commit()
    retry=client.post(url,json=payload)
    if tamper_manifest:
        assert retry.status_code==409,retry.text
        assert 'MATERIAL_INTEGRITY_EXECUTION_CONFLICT' in retry.text
        assert repository.get(plan['plan_id']) is None
        assert len(attempts)==1
        return
    assert retry.status_code==202,retry.text
    assert retry.json()['task_id']==plan['plan_id']
    assert attempts==[plan['plan_id'],plan['plan_id']]
    assert scheduler.run_once()
    assert client.get(f"/api/v62/projects/{project_id}/material-batches/{plan['plan_id']}").json()['succeeded']==1


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
    audit_id = _run_integrity_audit(client, scheduler, project_id)

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
    stale = client.get(f'/api/v62/projects/{project_id}/material-integrity/audits/{audit_id}/groups').json()
    assert stale['stale'] is True
    repeated = client.post(f'/api/v62/projects/{project_id}/material-batches', json={
        'operation':'DELETE_INDEX', 'selection_spec':estimate.json()['selection_spec'],
    })
    assert repeated.status_code == 409
    assert 'MATERIAL_REVISION_CHANGED' in repeated.text


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
    assert response.json()["review_groups"][0]["group_key"].startswith('DUPLICATE_')
    assert response.json()["review_groups"][0]["reason"] == 'MULTIPLE_PROTECTED_REFERENCES'
    assert {item['image_id'] for item in response.json()['preview_items']} == {original['id'], duplicate_id}
    assert all(item['protection_reasons'] for item in response.json()['preview_items'])


@pytest.mark.parametrize('diagnostics', [False, True])
def test_failed_request_only_releases_index_and_retains_original_evidence(
    client, seeded_project, tmp_path, monkeypatch, diagnostics
):
    project_id, original = seeded_project
    materials = app_module.material_store(project_id)
    materials.upsert(_duplicate_material(materials.get(original['id']), 'request-copy', 'request.jpg'))
    repository, artifacts, scheduler = _runtime(tmp_path, monkeypatch)
    task_id = 'failed-request'
    request = {'task_id': task_id, 'train_image_ids': [original['id'], 'request-copy']}
    artifacts.atomic_write_json(task_id, 'payload.json', request)
    repository.create(TaskRecord.new(task_id, project_id, TaskKind.TRAINING, 'payload.json', 'training'), artifacts=artifacts)
    repository.fail_queued_precondition(task_id, 'input conflict', status=TaskStatus.FAILED)
    if diagnostics:
        artifacts.atomic_write_json(task_id, 'input-preparation-error.json', {
            'schema_version': 1, 'task_id': task_id, 'project_id': project_id,
            'stage': 'training_input_preparation_failed', 'input_freeze_created': False,
            'issues_ref': 'input-compatibility/manifest.json',
        })
        artifacts.atomic_write_json(task_id, 'input-compatibility/manifest.json', {
            'pages': [{'page': 1, 'ref': 'input-compatibility/pages/000001.json'}],
        })
        artifacts.atomic_write_json(task_id, 'input-compatibility/pages/000001.json', [
            {'image_id': 'request-copy', 'issue_type': 'duplicate_annotation_conflict'},
        ])
        artifacts.atomic_write_json('prepare-child', 'payload.json', {'training_task_id': task_id})
        repository.create(TaskRecord.new('prepare-child', project_id, TaskKind.TRAINING_PREPARE, 'payload.json', 'prepare'), artifacts=artifacts)
        repository.fail_queued_precondition('prepare-child', 'input conflict', status=TaskStatus.FAILED)
    audit_id = _run_integrity_audit(client, scheduler, project_id)
    base = f'/api/v62/projects/{project_id}/material-integrity/audits/{audit_id}'
    def no_provider(project_id, reference):
        pytest.fail('request-only cleanup must not access storage')

    lifecycle = RemoteExecutionStagingLifecycle(repository, artifacts, no_provider)
    build_ledger = lifecycle._build_terminal_ledger
    previews = []

    def preview_during_cleanup(task, **kwargs):
        assert build_ledger(task, **kwargs) is None
        assert artifacts.artifact_path(task_id, 'remote-material/staging-cleanup.json.lock').is_file()
        previews.append(client.post(base + '/dedup-plans', json={'scope': 'SAFE_ALL'}))
        return None

    monkeypatch.setattr(lifecycle, '_build_terminal_ledger', preview_during_cleanup)
    assert lifecycle.cleanup_task(repository.get(task_id))['status'] == 'NO_OBJECTS'
    evidence_before = {path.relative_to(artifacts.root).as_posix(): path.read_bytes()
                       for path in artifacts.artifact_path(task_id, '.').rglob('*') if path.is_file()}
    response, = previews
    assert response.status_code == 201, response.text
    plan = response.json()
    assert plan['delete_count'] == 1
    assert plan['protected_item_count'] == 0
    assert all(any(reason['reason'] == 'TRAINING_FAILED_REQUEST_ONLY'
                   and reason['protected'] is False for reason in item['protection_reasons'])
               for item in plan['preview_items'])
    keeper = plan['preview_groups'][0]['keeper_image_id']
    before = client.get(f'/api/v61/projects/{project_id}/materials/{keeper}/content')
    assert before.status_code == 200
    queued = client.post(base + f"/dedup-plans/{plan['plan_id']}/execute", json={
        'confirmation_credential': plan['confirmation_credential'],
    })
    assert queued.status_code == 202, queued.text
    assert scheduler.run_once()
    assert materials.count() == 1
    assert client.get(f'/api/v61/projects/{project_id}/materials/{keeper}/content').content == before.content
    assert artifacts.read_json(task_id, 'payload.json') == request
    assert repository.get(task_id).status is TaskStatus.FAILED
    assert {path.relative_to(artifacts.root).as_posix(): path.read_bytes()
            for path in artifacts.artifact_path(task_id, '.').rglob('*') if path.is_file()} == evidence_before


@pytest.mark.parametrize('dependency', [
    'input-freeze.json', 'snapshot.json', 'work/bundle/manifest.json',
    'checkpoints/worker.json', 'checkpoint-resume.json', 'result.json',
    'unknown-dependency.json', 'payload_ref', 'retry', 'test', 'snapshot_test',
    'model_task_reference', 'evaluation_ids', 'active_prepare',
    'remote-material/staging-cleanup.json', 'unknown.lock',
    'remote-material/unknown.json.lock',
])
def test_failed_no_freeze_dependencies_remain_protected(
    client, seeded_project, tmp_path, monkeypatch, dependency
):
    project_id, original = seeded_project
    materials = app_module.material_store(project_id)
    materials.upsert(_duplicate_material(materials.get(original['id']), 'dependency-copy', 'dependency.jpg'))
    repository, artifacts, scheduler = _runtime(tmp_path, monkeypatch)
    task_id = 'failed-dependency'
    payload = {'train_image_ids': [original['id'], 'dependency-copy']}
    if dependency == 'payload_ref':
        payload['prepared_input_ref'] = 'missing-prepared-input.json'
    artifacts.atomic_write_json(task_id, 'payload.json', payload)
    repository.create(TaskRecord.new(task_id, project_id, TaskKind.TRAINING, 'payload.json', 'training'), artifacts=artifacts)
    repository.fail_queued_precondition(task_id, 'input failure', status=TaskStatus.FAILED)
    if dependency == 'retry':
        repository.retry(task_id)
        repository.fail_queued_precondition(task_id, 'retry failure', status=TaskStatus.FAILED)
    elif dependency == 'test':
        materials.patch({image_id: {'split': 'test'} for image_id in payload['train_image_ids']})
    elif dependency == 'snapshot_test':
        snapshots = materials.project_path / 'snapshots'
        snapshots.mkdir(exist_ok=True)
        from platform_core.annotations import atomic_write_json
        atomic_write_json(snapshots / 'test.json', {'test_image_ids': payload['train_image_ids']})
    elif dependency in {'model_task_reference', 'evaluation_ids'}:
        from platform_core.algorithms import save_algorithms
        save_algorithms(materials.project_path / 'algorithms.json', [{
            'id': 'historical-model', 'name': 'Historical model', 'versions': [{
                'id': 'historical-version',
                'training_lineage': {'task_id': task_id} if dependency == 'model_task_reference' else {},
                'evaluation': {'test_image_ids': payload['train_image_ids']} if dependency == 'evaluation_ids' else {},
            }],
        }])
    elif dependency == 'active_prepare':
        artifacts.atomic_write_json('prepare-child', 'payload.json', {'training_task_id': task_id})
        repository.create(TaskRecord.new('prepare-child', project_id, TaskKind.TRAINING_PREPARE, 'payload.json', 'prepare'), artifacts=artifacts)
    elif dependency != 'payload_ref':
        artifacts.atomic_write_json(task_id, dependency, {'train_image_ids': payload['train_image_ids']})
    audit_id = _run_integrity_audit(client, scheduler, project_id)
    response = client.post(f'/api/v62/projects/{project_id}/material-integrity/audits/{audit_id}/dedup-plans', json={'scope': 'SAFE_ALL'})
    assert response.status_code == 201, response.text
    assert response.json()['delete_count'] == 0
    assert response.json()['protected_item_count'] == 2


def test_same_gt_mixed_protected_group_deletes_only_unprotected_redundants(
    client, seeded_project, tmp_path, monkeypatch
):
    project_id, original = seeded_project
    materials = app_module.material_store(project_id)
    materials.upsert_many([_duplicate_material(materials.get(original['id']), image_id, image_id + '.jpg')
                           for image_id in ['protected-copy', 'safe-copy-a', 'safe-copy-b']])
    repository, artifacts, scheduler = _runtime(tmp_path, monkeypatch)
    artifacts.atomic_write_json('active-training', 'payload.json', {'train_image_ids': [original['id'], 'protected-copy']})
    repository.create(TaskRecord.new('active-training', project_id, TaskKind.TRAINING, 'payload.json', 'training'), artifacts=artifacts)
    audit_id = _run_integrity_audit(client, scheduler, project_id)
    base = f'/api/v62/projects/{project_id}/material-integrity/audits/{audit_id}'
    response = client.post(base + '/dedup-plans', json={'scope': 'SAFE_ALL'})
    assert response.status_code == 201, response.text
    plan = response.json()
    assert plan['delete_count'] == 2
    assert plan['kept_count'] == 2
    assert plan['protected_item_count'] == 2
    assert plan['protection_reason_counts'] == {'ACTIVE_TASK_INPUT': 2}
    queued = client.post(base + f"/dedup-plans/{plan['plan_id']}/execute", json={'confirmation_credential': plan['confirmation_credential']})
    assert queued.status_code == 202, queued.text
    assert scheduler.run_once()
    assert materials.get(original['id']) and materials.get('protected-copy')
    assert materials.get('safe-copy-a') is None and materials.get('safe-copy-b') is None


def test_governance_summary_uses_plan_rules_without_persisting_a_plan(
    client, seeded_project, tmp_path, monkeypatch
):
    project_id, original = seeded_project
    materials = app_module.material_store(project_id)
    materials.upsert(_duplicate_material(materials.get(original['id']), 'summary-copy', 'summary.jpg'))
    repository, artifacts, scheduler = _runtime(tmp_path, monkeypatch)
    audit_id = _run_integrity_audit(client, scheduler, project_id)
    before = {path.relative_to(artifacts.root).as_posix() for path in artifacts.root.rglob('*')}
    summary = material_batches_module.create_material_integrity_plan(
        project_id, repository.get(audit_id), materials, repository, artifacts,
        {'scope': 'SAFE_ALL'}, persist=False,
    )
    assert summary['delete_count'] == 1
    assert summary['selected_count'] == 2
    assert 'plan_id' not in summary and 'confirmation_credential' not in summary
    assert {path.relative_to(artifacts.root).as_posix() for path in artifacts.root.rglob('*')} == before


@pytest.mark.parametrize('all_protected', [False, True])
def test_conflicting_gt_manual_keeper_preserves_all_protected_identities(
    client, seeded_project, tmp_path, monkeypatch, all_protected
):
    project_id, original = seeded_project
    materials = app_module.material_store(project_id)
    materials.upsert_many([_duplicate_material(materials.get(original['id']), image_id, image_id + '.jpg')
                           for image_id in ['protected-copy', 'manual-keeper', 'safe-copy']])
    AnnotationRepository(materials.project_path).upsert('manual-keeper', [], annotation_state='confirmed_empty')
    repository, artifacts, scheduler = _runtime(tmp_path, monkeypatch)
    protected_ids = [original['id'], 'protected-copy', 'manual-keeper', 'safe-copy'] if all_protected else [original['id'], 'protected-copy']
    artifacts.atomic_write_json('active-training', 'payload.json', {'train_image_ids': protected_ids})
    repository.create(TaskRecord.new('active-training', project_id, TaskKind.TRAINING, 'payload.json', 'training'), artifacts=artifacts)
    audit_id = _run_integrity_audit(client, scheduler, project_id)
    base = f'/api/v62/projects/{project_id}/material-integrity/audits/{audit_id}'
    automatic = client.post(base + '/dedup-plans', json={'scope': 'SAFE_ALL'}).json()
    assert automatic['delete_count'] == 0
    assert automatic['manual_required_groups'] == 1
    group_key = automatic['review_groups'][0]['group_key']
    manual = client.post(base + '/dedup-plans', json={
        'scope': 'MANUAL_GROUPS', 'group_keys': [group_key],
        'manual_decisions': {group_key: 'manual-keeper'},
    })
    assert manual.status_code == 201, manual.text
    plan = manual.json()
    if all_protected:
        assert plan['delete_count'] == 0 and plan['protected_item_count'] == 4
        return
    assert plan['delete_count'] == 1 and plan['kept_count'] == 3
    queued = client.post(base + f"/dedup-plans/{plan['plan_id']}/execute", json={'confirmation_credential': plan['confirmation_credential']})
    assert queued.status_code == 202, queued.text
    assert scheduler.run_once()
    assert materials.get(original['id']) and materials.get('protected-copy') and materials.get('manual-keeper')
    assert materials.get('safe-copy') is None


@pytest.mark.parametrize('changed_at', ['execute', 'worker'])
def test_request_only_release_is_revalidated_when_durable_reference_appears(
    client, seeded_project, tmp_path, monkeypatch, changed_at
):
    project_id, original = seeded_project
    materials = app_module.material_store(project_id)
    materials.upsert(_duplicate_material(materials.get(original['id']), 'changing-copy', 'changing.jpg'))
    repository, artifacts, scheduler = _runtime(tmp_path, monkeypatch)
    artifacts.atomic_write_json('failed-request', 'payload.json', {'train_image_ids': [original['id'], 'changing-copy']})
    repository.create(TaskRecord.new('failed-request', project_id, TaskKind.TRAINING, 'payload.json', 'training'), artifacts=artifacts)
    repository.fail_queued_precondition('failed-request', 'input conflict', status=TaskStatus.FAILED)
    audit_id = _run_integrity_audit(client, scheduler, project_id)
    base = f'/api/v62/projects/{project_id}/material-integrity/audits/{audit_id}'
    plan = client.post(base + '/dedup-plans', json={'scope': 'SAFE_ALL'}).json()
    assert plan['delete_count'] == 1
    url = base + f"/dedup-plans/{plan['plan_id']}/execute"
    credential = {'confirmation_credential': plan['confirmation_credential']}
    if changed_at == 'worker':
        queued = client.post(url, json=credential)
        assert queued.status_code == 202, queued.text
    artifacts.atomic_write_json('failed-request', 'snapshot.json', {'train_image_ids': [original['id'], 'changing-copy']})
    if changed_at == 'execute':
        blocked = client.post(url, json=credential)
        assert blocked.status_code == 409, blocked.text
        assert 'MATERIAL_INTEGRITY_REFERENCE_CHANGED' in blocked.text
    else:
        assert scheduler.run_once()
        finished = repository.get(queued.json()['task_id'])
        assert finished.status is TaskStatus.FAILED
    assert materials.get(original['id']) and materials.get('changing-copy')


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
