from __future__ import annotations

import io
import uuid

from PIL import Image
import pytest

import app as app_module
import platform_core.material_batches as material_batches
from platform_core.material_batches import (
    BatchRequestError,
    MaterialBatchHandler,
    assert_material_input_admission,
)
from platform_core.task_runtime import ArtifactStore, Scheduler, TaskKind, TaskRepository


def jpg():
    stream = io.BytesIO(); Image.new("RGB", (24, 24), "green").save(stream, format="JPEG"); return stream.getvalue()


def create_external_material(client, tmp_path):
    source_id = "external_delete_" + uuid.uuid4().hex[:8]
    root = tmp_path / source_id
    client.post("/api/v61/storage-sources", json={"id": source_id, "name": source_id, "type": "local", "config": {"root": str(root)}}).raise_for_status()
    project = client.post("/api/projects", json={"name": source_id, "labels": []}).json()
    upload = client.post(f"/api/projects/{project['id']}/images", files=[("files", ("a.jpg", jpg(), "image/jpeg"))], data={"storage_source_id": source_id})
    upload.raise_for_status()
    return project["id"], source_id, root, upload.json()["uploaded"][0]


def test_external_material_delete_defaults_to_index_only(client, tmp_path):
    project_id, _source_id, root, row = create_external_material(client, tmp_path)
    source_file = root / row["object_key"]
    before = source_file.read_bytes()

    response = client.delete(f"/api/projects/{project_id}/images/{row['id']}")
    assert response.status_code == 409, response.text
    assert "MATERIAL_DELETE_PREVIEW_REQUIRED" in response.text
    governed_delete(client, project_id, [row["id"]])
    assert app_module.material_store(project_id).get(row["id"]) is None
    assert source_file.read_bytes() == before


def test_legacy_explicit_source_delete_never_authorizes_physical_reclamation(client, tmp_path):
    project_id, _source_id, root, row = create_external_material(client, tmp_path)
    source_file = root / row["object_key"]

    refused = client.delete(f"/api/projects/{project_id}/images/{row['id']}", params={"delete_source": True})
    assert refused.status_code == 409
    assert app_module.material_store(project_id).get(row["id"]) is not None
    assert source_file.is_file()

    deleted = client.delete(
        f"/api/projects/{project_id}/images/{row['id']}",
        params={"delete_source": True, "confirmation": "DELETE_SOURCE"},
    )
    assert deleted.status_code == 409, deleted.text
    assert "MATERIAL_DELETE_PREVIEW_REQUIRED" in deleted.text
    assert source_file.is_file()
    assert app_module.material_store(project_id).get(row["id"]) is not None


def test_external_batch_delete_requires_governed_plan_and_retains_bytes(client, tmp_path):
    project_id, _source_id, root, first = create_external_material(client, tmp_path)
    second_response = client.post(f"/api/projects/{project_id}/images", files=[("files", ("b.jpg", jpg(), "image/jpeg"))], data={"storage_source_id": first["storage_source_id"]})
    second_response.raise_for_status(); second = second_response.json()["uploaded"][0]

    response = client.post(f"/api/v46/projects/{project_id}/images/batch-delete", json={"image_ids": [first["id"], second["id"]], "delete_source": False})
    assert response.status_code == 409
    assert "MATERIAL_DELETE_PREVIEW_REQUIRED" in response.text
    governed_delete(client, project_id, [first["id"], second["id"]])
    assert (root / first["object_key"]).is_file()
    assert (root / second["object_key"]).is_file()


def test_batch_external_source_delete_requires_confirmation(client, tmp_path):
    project_id, _source_id, root, row = create_external_material(client, tmp_path)
    source_file = root / row["object_key"]

    refused = client.post(
        f"/api/v46/projects/{project_id}/images/batch-delete",
        json={"image_ids": [row["id"]], "delete_source": True},
    )
    assert refused.status_code == 409
    assert app_module.material_store(project_id).get(row["id"]) is not None
    assert source_file.is_file()

    deleted = client.post(
        f"/api/v46/projects/{project_id}/images/batch-delete",
        json={
            "image_ids": [row["id"]],
            "delete_source": True,
            "confirmation": "DELETE_SOURCE",
        },
    )
    assert deleted.status_code == 409, deleted.text
    assert "MATERIAL_DELETE_PREVIEW_REQUIRED" in deleted.text
    assert app_module.material_store(project_id).get(row["id"]) is not None
    assert source_file.is_file()


def test_storage_source_with_material_references_cannot_be_deleted(client, tmp_path):
    project_id, source_id, _root, row = create_external_material(client, tmp_path)
    blocked = client.delete(f"/api/v61/storage-sources/{source_id}")
    assert blocked.status_code == 409
    assert row["id"] in blocked.text or "referenced" in blocked.text
    assert app_module.material_store(project_id).get(row["id"]) is not None


def test_source_delete_create_refuses_even_with_old_confirmation_before_provider(client, tmp_path, monkeypatch):
    project_id, _source_id, root, row = create_external_material(client, tmp_path)
    calls = []
    monkeypatch.setattr(material_batches, '_provider', lambda *_a, **_k: calls.append('provider'))
    base = f'/api/v62/projects/{project_id}/material-batches'
    estimate = client.post(base + '/estimate', json={'operation':'DELETE_SOURCE',
        'selection_spec':{'scope':'SELECTED','image_ids':[row['id']]},'options':{}})
    assert estimate.status_code == 200, estimate.text
    created = client.post(base, json={'operation':'DELETE_SOURCE', 'selection_spec':estimate.json()['selection_spec'],
        'options':{'confirmation_token':estimate.json()['confirmation_token']}})
    assert created.status_code == 409, created.text
    assert 'PHYSICAL_DELETE_SAFETY_UNVERIFIED' in created.text
    assert calls == []
    assert (root / row['object_key']).is_file()
    assert app_module.material_store(project_id).get(row['id']) is not None


def test_legacy_source_worker_and_repeat_never_call_provider_or_remove_identity(client, tmp_path, monkeypatch):
    from types import SimpleNamespace
    from contextlib import closing
    project_id, _source_id, root, row = create_external_material(client, tmp_path)
    calls = []
    monkeypatch.setattr(material_batches, '_provider', lambda *_a, **_k: calls.append('provider'))
    with closing(material_batches.BatchSelection(tmp_path / 'selection.sqlite3')) as manifest:
        manifest.database.execute('INSERT INTO selection(image_id) VALUES (?)', (row['id'],))
        handler = MaterialBatchHandler(app_module.DATA_DIR)
        for _ in range(2):
            handler._delete_sources(SimpleNamespace(), manifest, app_module.material_store(project_id),
                [{'image_id': row['id']}], None, {}, {})
            state, error = manifest.database.execute('SELECT state,error FROM selection').fetchone()
            assert state == 'failed' and error == 'PHYSICAL_DELETE_SAFETY_UNVERIFIED'
    assert calls == []
    assert (root / row['object_key']).is_file()
    assert app_module.material_store(project_id).get(row['id']) is not None


def governed_delete(client, pid, image_ids):
    import app as app_module
    from platform_core.task_runtime import Scheduler, TaskStatus
    from platform_core.worker_registry import build_worker_registration
    base = f'/api/v62/projects/{pid}/material-batches'
    estimated = client.post(base + '/estimate', json={
        'operation': 'DELETE_INDEX', 'selection_spec': {'scope': 'SELECTED', 'image_ids': image_ids}})
    estimated.raise_for_status()
    preview = estimated.json()['deletion_preview']
    response = client.post(base, json={'operation': 'DELETE_INDEX', 'selection_spec': estimated.json()['selection_spec'],
        'options': {'deletion_plan_id': preview['plan_id'], 'confirmation_credential': preview['confirmation_credential']}})
    assert response.status_code == 202, response.text
    repository, artifacts = app_module.shared_task_repository(), app_module.shared_task_artifacts()
    handlers, capabilities = build_worker_registration(app_module.DATA_DIR, {'materials'})
    scheduler = Scheduler(repository, artifacts, f'governance-clean-{uuid.uuid4().hex}', handlers, capabilities,
        lease_seconds=5, poll_seconds=0.01)
    task_id = response.json()['task_id']
    for _ in range(50):
        if repository.get(task_id).status in {TaskStatus.SUCCEEDED, TaskStatus.FAILED}:
            break
        assert scheduler.run_once()
    assert repository.get(task_id).status is TaskStatus.SUCCEEDED
    return response.json()
