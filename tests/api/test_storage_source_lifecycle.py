from __future__ import annotations

import sqlite3
import threading
import uuid

from fastapi import HTTPException

import app as app_module
from platform_core.errors import PlatformError
from platform_core.secrets import MemorySecretStore
from platform_core.storage import StorageSourceRepository
from platform_core.task_runtime import TaskKind, TaskRecord, TaskRepository


def _create_local_source(client, tmp_path, *, credentials=None):
    source_id = "lifecycle_" + uuid.uuid4().hex[:8]
    response = client.post(
        "/api/v61/storage-sources",
        json={
            "id": source_id,
            "name": source_id,
            "type": "local",
            "config": {"root": str(tmp_path / source_id / "generation-a")},
            "credentials": credentials or {},
            "enabled": True,
        },
    )
    assert response.status_code == 201, response.text
    return source_id


def _start_local_import(client, project_id, source_id):
    response = client.post(
        f"/api/v61/projects/{project_id}/storage-imports/scan",
        json={
            "mode": "storage_scan",
            "execution_mode": "local",
            "storage_source_id": source_id,
        },
    )
    assert response.status_code == 202, response.text
    return response.json()["task_id"]


def test_destructive_source_update_waits_for_active_import_but_name_remains_editable(
    client, seeded_project, tmp_path,
):
    project_id, _seed = seeded_project
    source_id = _create_local_source(client, tmp_path)
    task_id = _start_local_import(client, project_id, source_id)

    renamed = client.patch(
        f"/api/v61/storage-sources/{source_id}",
        json={"name": "renamed-" + source_id},
    )
    assert renamed.status_code == 200, renamed.text

    blocked = client.patch(
        f"/api/v61/storage-sources/{source_id}",
        json={"config": {"root": str(tmp_path / source_id / "generation-b")}},
    )
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["code"] == "STORAGE_SOURCE_ACTIVE_TASK_DEPENDENCY"
    assert task_id in blocked.text
    clear_blocked = client.patch(
        f"/api/v61/storage-sources/{source_id}",
        json={"clear_credentials": True},
    )
    assert clear_blocked.status_code == 409, clear_blocked.text

    cancelled = app_module.shared_task_repository().request_cancel(task_id)
    assert cancelled.status.value == "CANCELLED"
    changed = client.patch(
        f"/api/v61/storage-sources/{source_id}",
        json={"config": {"root": str(tmp_path / source_id / "generation-b")}},
    )
    assert changed.status_code == 200, changed.text


def test_import_admission_and_source_mutation_share_a_deterministic_fence(
    client, seeded_project, tmp_path, monkeypatch,
):
    project_id, _seed = seeded_project
    source_id = _create_local_source(client, tmp_path)
    create_entered = threading.Event()
    release_create = threading.Event()
    patch_finished = threading.Event()
    original_create = TaskRepository.create

    def gated_create(self, record, *, artifacts=None):
        if record.kind is TaskKind.MATERIAL_IMPORT and record.project_id == project_id:
            create_entered.set()
            assert release_create.wait(5), "test did not release task publication"
        return original_create(self, record, artifacts=artifacts)

    monkeypatch.setattr(TaskRepository, "create", gated_create)
    outcomes = {}

    def admit():
        outcomes["admission"] = app_module.create_storage_import_scan(
            project_id,
            app_module.StorageImportScanReq(
                mode="storage_scan",
                execution_mode="local",
                storage_source_id=source_id,
            ),
        )

    def mutate():
        try:
            outcomes["patch"] = app_module.update_storage_source(
                source_id,
                app_module.StorageSourceUpdateReq(
                    config={"root": str(tmp_path / source_id / "generation-b")},
                ),
            )
        except (HTTPException, PlatformError) as error:
            outcomes["patch_error"] = error
        finally:
            patch_finished.set()

    admission_thread = threading.Thread(target=admit)
    admission_thread.start()
    assert create_entered.wait(5)
    patch_thread = threading.Thread(target=mutate)
    patch_thread.start()
    # The admission callback is paused while holding the lifecycle fence.  A
    # destructive PATCH cannot finish until that durable task is visible.
    assert not patch_finished.wait(0.25)
    release_create.set()
    admission_thread.join(5)
    patch_thread.join(5)
    assert not admission_thread.is_alive()
    assert not patch_thread.is_alive()
    assert outcomes["admission"]["task_id"]
    error = outcomes.get("patch_error")
    assert error is not None
    assert error.status_code == 409


def test_failed_source_sql_update_does_not_replace_the_published_secret(
    client, tmp_path, monkeypatch,
):
    app_module.MODEL_SECRET_STORE = MemorySecretStore()
    source_id = _create_local_source(
        client,
        tmp_path,
        credentials={"access_key_id": "old", "access_key_secret": "old-secret"},
    )
    before = app_module.storage_source_repository().get(source_id)
    assert before is not None and before.secret_ref
    assert app_module.storage_credentials().get(before.secret_ref) == {
        "access_key_id": "old",
        "access_key_secret": "old-secret",
    }
    original_update = StorageSourceRepository.update

    def fail_new_generation(self, target_id, changes):
        if target_id == source_id and changes.get("secret_ref") != before.secret_ref:
            raise sqlite3.IntegrityError("forced update failure")
        return original_update(self, target_id, changes)

    monkeypatch.setattr(StorageSourceRepository, "update", fail_new_generation)
    response = client.patch(
        f"/api/v61/storage-sources/{source_id}",
        json={
            "credentials": {
                "access_key_id": "new",
                "access_key_secret": "new-secret",
            }
        },
    )
    assert response.status_code == 409, response.text
    after = app_module.storage_source_repository().get(source_id)
    assert after is not None
    assert after.secret_ref == before.secret_ref
    assert app_module.storage_credentials().get(before.secret_ref) == {
        "access_key_id": "old",
        "access_key_secret": "old-secret",
    }


def test_training_prepare_uses_parent_input_freeze_as_source_dependency(
    client, seeded_project, tmp_path,
):
    project_id, seed = seeded_project
    source_id = _create_local_source(client, tmp_path)
    image_id = str(seed["id"])
    app_module.material_store(project_id).patch({
        image_id: {"storage_source_id": source_id},
    })
    artifacts = app_module.shared_task_artifacts()
    repository = app_module.shared_task_repository()
    parent_id = "training-source-" + uuid.uuid4().hex[:8]
    prepare_id = "prepare-source-" + uuid.uuid4().hex[:8]
    artifacts.atomic_write_json(parent_id, "payload.json", {"schema_version": 1})
    artifacts.atomic_write_json(
        parent_id,
        "input-freeze.json",
        {"selected_train_image_ids": [image_id]},
    )
    repository.create(TaskRecord.new(
        parent_id,
        project_id,
        TaskKind.TRAINING,
        "payload.json",
        "training:test",
    ), artifacts=artifacts)
    repository.request_cancel(parent_id)
    artifacts.atomic_write_json(
        prepare_id,
        "payload.json",
        {"training_task_id": parent_id, "project_id": project_id},
    )
    repository.create(TaskRecord.new(
        prepare_id,
        project_id,
        TaskKind.TRAINING_PREPARE,
        "payload.json",
        f"training-prepare:{project_id}",
    ), artifacts=artifacts)

    blocked = client.patch(
        f"/api/v61/storage-sources/{source_id}",
        json={"enabled": False},
    )
    assert blocked.status_code == 409, blocked.text
    assert prepare_id in blocked.text

    repository.request_cancel(prepare_id)
    changed = client.patch(
        f"/api/v61/storage-sources/{source_id}",
        json={"enabled": False},
    )
    assert changed.status_code == 200, changed.text


def test_active_rknn_calibration_blocks_source_generation_change(
    client, seeded_project, tmp_path,
):
    project_id, seed = seeded_project
    source_id = _create_local_source(client, tmp_path)
    task_id = "conversion-source-" + uuid.uuid4().hex[:8]
    request = {
        "execution_mode": "agent",
        "remote_execution": {
            "task_kind": "MODEL_CONVERSION",
            "conversion": {
                "target": "rockchip",
                "params": {"precision": "int8"},
                "calibration": {
                    "items": [{
                        "image_id": str(seed["id"]),
                        "storage_source_id": source_id,
                        "object_key": "calibration/seed.jpg",
                        "size_bytes": 1,
                        "sha256": "a" * 64,
                    }],
                },
            },
        },
    }
    artifacts = app_module.shared_task_artifacts()
    repository = app_module.shared_task_repository()
    artifacts.atomic_write_json(task_id, "request.json", request)
    repository.create(TaskRecord.new(
        task_id,
        project_id,
        TaskKind.MODEL_CONVERSION,
        "request.json",
        "conversion:rknn",
    ), artifacts=artifacts)

    blocked = client.patch(
        f"/api/v61/storage-sources/{source_id}",
        json={"config": {"root": str(tmp_path / source_id / "generation-b")}},
    )
    assert blocked.status_code == 409, blocked.text
    assert task_id in blocked.text

    repository.request_cancel(task_id)
    changed = client.patch(
        f"/api/v61/storage-sources/{source_id}",
        json={"config": {"root": str(tmp_path / source_id / "generation-b")}},
    )
    assert changed.status_code == 200, changed.text


def test_canonical_clean_selection_blocks_source_change_until_terminal(
    client, seeded_project, tmp_path,
):
    project_id, seed = seeded_project
    source_id = _create_local_source(client, tmp_path)
    image_id = str(seed["id"])
    app_module.material_store(project_id).patch({
        image_id: {"storage_source_id": source_id},
    })
    draft = {
        "operation": "CLEAN",
        "selection_spec": {"scope": "SELECTED", "image_ids": [image_id]},
        "options": {},
    }
    estimate = client.post(
        f"/api/v62/projects/{project_id}/material-batches/estimate",
        json=draft,
    )
    assert estimate.status_code == 200, estimate.text
    draft["selection_spec"] = estimate.json()["selection_spec"]
    created = client.post(
        f"/api/v62/projects/{project_id}/material-batches",
        json=draft,
    )
    assert created.status_code == 202, created.text
    task_id = created.json()["task_id"]

    blocked = client.patch(
        f"/api/v61/storage-sources/{source_id}",
        json={"enabled": False},
    )
    assert blocked.status_code == 409, blocked.text
    assert task_id in blocked.text

    cancelled = client.post(
        f"/api/v62/projects/{project_id}/material-batches/{task_id}/cancel"
    )
    assert cancelled.status_code == 200, cancelled.text
    changed = client.patch(
        f"/api/v61/storage-sources/{source_id}",
        json={"enabled": False},
    )
    assert changed.status_code == 200, changed.text


def test_active_ai_annotation_image_ids_block_source_credentials_change(
    client, seeded_project, tmp_path,
):
    project_id, seed = seeded_project
    source_id = _create_local_source(client, tmp_path)
    image_id = str(seed["id"])
    app_module.material_store(project_id).patch({
        image_id: {"storage_source_id": source_id},
    })
    task_id = "annotation-source-" + uuid.uuid4().hex[:8]
    artifacts = app_module.shared_task_artifacts()
    repository = app_module.shared_task_repository()
    artifacts.atomic_write_json(
        task_id,
        "request.json",
        {"image_ids": [image_id], "model_config_id": "model-a"},
    )
    repository.create(TaskRecord.new(
        task_id,
        project_id,
        TaskKind.AI_ANNOTATION,
        "request.json",
        "vision:model-a",
    ), artifacts=artifacts)

    blocked = client.patch(
        f"/api/v61/storage-sources/{source_id}",
        json={"credentials": {"token": "rotated"}},
    )
    assert blocked.status_code == 409, blocked.text
    assert task_id in blocked.text

    repository.request_cancel(task_id)
    changed = client.patch(
        f"/api/v61/storage-sources/{source_id}",
        json={"credentials": {"token": "rotated"}},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["secret_configured"] is True
