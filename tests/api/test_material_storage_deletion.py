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
    assert response.status_code == 200, response.text
    assert response.json()["source_deleted"] is False
    assert app_module.material_store(project_id).get(row["id"]) is None
    assert source_file.read_bytes() == before


def test_explicit_source_delete_requires_confirmation_and_then_removes_object(client, tmp_path):
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
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["source_deleted"] is True
    assert not source_file.exists()
    assert app_module.material_store(project_id).get(row["id"]) is None


def test_batch_external_delete_is_index_only_unless_explicitly_confirmed(client, tmp_path):
    project_id, _source_id, root, first = create_external_material(client, tmp_path)
    second_response = client.post(f"/api/projects/{project_id}/images", files=[("files", ("b.jpg", jpg(), "image/jpeg"))], data={"storage_source_id": first["storage_source_id"]})
    second_response.raise_for_status(); second = second_response.json()["uploaded"][0]

    response = client.post(f"/api/v46/projects/{project_id}/images/batch-delete", json={"image_ids": [first["id"], second["id"]], "delete_source": False})
    assert response.status_code == 200
    assert response.json()["deleted"] == 2
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
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["deleted"] == 1
    assert app_module.material_store(project_id).get(row["id"]) is None
    assert not source_file.exists()


def test_storage_source_with_material_references_cannot_be_deleted(client, tmp_path):
    project_id, source_id, _root, row = create_external_material(client, tmp_path)
    blocked = client.delete(f"/api/v61/storage-sources/{source_id}")
    assert blocked.status_code == 409
    assert row["id"] in blocked.text or "referenced" in blocked.text
    assert app_module.material_store(project_id).get(row["id"]) is not None


def test_source_delete_finishes_index_commit_when_cancel_arrives_after_provider_delete(
    client, tmp_path, monkeypatch
):
    project_id, _source_id, root, row = create_external_material(client, tmp_path)
    source_file = root / row["object_key"]
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    artifacts = ArtifactStore(tmp_path / "artifacts")
    monkeypatch.setattr(app_module, "_SHARED_TASK_REPOSITORY", repository)
    monkeypatch.setattr(app_module, "_SHARED_TASK_ARTIFACTS", artifacts)

    estimate = client.post(
        f"/api/v62/projects/{project_id}/material-batches/estimate",
        json={
            "operation": "DELETE_SOURCE",
            "selection_spec": {"scope": "SELECTED", "image_ids": [row["id"]]},
            "options": {},
        },
    )
    assert estimate.status_code == 200, estimate.text
    created = client.post(
        f"/api/v62/projects/{project_id}/material-batches",
        json={
            "operation": "DELETE_SOURCE",
            "selection_spec": estimate.json()["selection_spec"],
            "options": {"confirmation_token": estimate.json()["confirmation_token"]},
        },
    )
    assert created.status_code == 202, created.text
    task_id = created.json()["task_id"]

    real_provider = material_batches._provider

    class CancelAfterDelete:
        def __init__(self, provider):
            self.provider = provider

        def __getattr__(self, name):
            return getattr(self.provider, name)

        def delete(self, object_key):
            self.provider.delete(object_key)
            repository.request_cancel(task_id)

    monkeypatch.setattr(
        material_batches,
        "_provider",
        lambda *args, **kwargs: CancelAfterDelete(real_provider(*args, **kwargs)),
    )
    scheduler = Scheduler(
        repository,
        artifacts,
        "delete-cancel-worker",
        {TaskKind.MATERIAL_BATCH: MaterialBatchHandler(app_module.DATA_DIR)},
        {"materials.batch"},
        lease_seconds=10,
    )

    assert scheduler.run_once() is True
    assert not source_file.exists()
    assert app_module.material_store(project_id).get(row["id"]) is None
    assert repository.get(task_id).status.value == "CANCELLED"


def test_ambiguous_source_delete_keeps_claim_and_retry_finishes_index(
    client, tmp_path, monkeypatch
):
    project_id, _source_id, root, row = create_external_material(client, tmp_path)
    source_file = root / row["object_key"]
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    artifacts = ArtifactStore(tmp_path / "artifacts")
    monkeypatch.setattr(app_module, "_SHARED_TASK_REPOSITORY", repository)
    monkeypatch.setattr(app_module, "_SHARED_TASK_ARTIFACTS", artifacts)

    estimate = client.post(
        f"/api/v62/projects/{project_id}/material-batches/estimate",
        json={
            "operation": "DELETE_SOURCE",
            "selection_spec": {"scope": "SELECTED", "image_ids": [row["id"]]},
            "options": {},
        },
    ).json()
    created = client.post(
        f"/api/v62/projects/{project_id}/material-batches",
        json={
            "operation": "DELETE_SOURCE",
            "selection_spec": estimate["selection_spec"],
            "options": {"confirmation_token": estimate["confirmation_token"]},
        },
    )
    assert created.status_code == 202, created.text
    task_id = created.json()["task_id"]
    real_provider = material_batches._provider

    class DeleteThenLoseResponse:
        def __init__(self, provider):
            self.provider = provider

        def __getattr__(self, name):
            return getattr(self.provider, name)

        def delete(self, object_key):
            self.provider.delete(object_key)
            raise RuntimeError("simulated worker/provider response loss")

    monkeypatch.setattr(
        material_batches,
        "_provider",
        lambda *args, **kwargs: DeleteThenLoseResponse(real_provider(*args, **kwargs)),
    )
    scheduler = Scheduler(
        repository,
        artifacts,
        "delete-recovery-worker",
        {TaskKind.MATERIAL_BATCH: MaterialBatchHandler(app_module.DATA_DIR)},
        {"materials.batch"},
        lease_seconds=10,
    )
    assert scheduler.run_once() is True
    assert not source_file.exists()
    assert repository.get(task_id).status.value == "FAILED"
    assert app_module.material_store(project_id).get(row["id"]) is not None
    with pytest.raises(BatchRequestError) as blocked:
        assert_material_input_admission(
            project_id,
            [row["id"]],
            app_module.material_store(project_id),
            repository,
            artifacts,
        )
    assert blocked.value.code == "MATERIAL_DELETE_IN_PROGRESS"

    monkeypatch.setattr(material_batches, "_provider", real_provider)
    repository.retry(task_id)
    assert scheduler.run_once() is True
    assert app_module.material_store(project_id).get(row["id"]) is None
    assert repository.get(task_id).status.value == "SUCCEEDED"
