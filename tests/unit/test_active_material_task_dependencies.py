from __future__ import annotations

import threading

import pytest

from platform_core.material_batches import (
    BatchRequestError,
    assert_material_input_admission,
    create_batch,
    estimate_batch,
)
from platform_core.material_repository import (
    MaterialRepository,
    material_annotation_lifecycle_fence,
)
from platform_core.task_runtime import ArtifactStore, TaskKind, TaskRecord, TaskRepository


def _material(image_id: str = "image-1") -> dict:
    return {
        "id": image_id,
        "filename": f"{image_id}.jpg",
        "storage_source_id": "source-1",
        "storage_type": "s3",
        "object_key": f"dataset/{image_id}.jpg",
        "content_sha256": "a" * 64,
        "size_bytes": 123,
        "source_available": True,
        "annotation_state": "confirmed_empty",
        "annotation_scope": ["target"],
    }


def _runtime(tmp_path):
    project = tmp_path / "projects" / "project-1"
    materials = MaterialRepository(project)
    materials.upsert(_material())
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    artifacts = ArtifactStore(tmp_path / "artifacts")
    return project, materials, repository, artifacts


def _delete_payload(project_id: str, materials: MaterialRepository, *, source=False):
    payload = {
        "operation": "DELETE_SOURCE" if source else "DELETE_INDEX",
        "selection_spec": {"scope": "SELECTED", "image_ids": ["image-1"]},
        "options": {},
    }
    estimate = estimate_batch(project_id, materials, payload)
    payload["selection_spec"] = estimate["selection_spec"]
    if source:
        payload["options"]["confirmation_token"] = estimate["confirmation_token"]
    return payload


def _conversion_payload() -> dict:
    return {
        "execution_mode": "agent",
        "remote_execution": {
            "version": 1,
            "task_kind": "MODEL_CONVERSION",
            "transport": "object-storage-v1",
            "conversion": {
                "schema_version": 1,
                "target": "rockchip",
                "params": {
                    "precision": "int8",
                    "calibration_count": 1,
                    "calibration_snapshot": "c" * 64,
                },
                "calibration": {
                    "schema_version": 1,
                    "snapshot_id": "c" * 64,
                    "dataset_id": "default",
                    "split": "train",
                    "material_revision": 1,
                    "requested_count": 1,
                    "item_count": 1,
                    "items": [{
                        "image_id": "image-1",
                        "file_name": "image-1.jpg",
                        "storage_source_id": "source-1",
                        "storage_type": "s3",
                        "object_key": "dataset/image-1.jpg",
                        "size_bytes": 123,
                        "etag": "",
                        "sha256": "a" * 64,
                    }],
                },
            },
        },
    }


def test_active_rknn_calibration_blocks_delete_until_conversion_is_terminal(tmp_path):
    _project, materials, repository, artifacts = _runtime(tmp_path)
    task_id = "conversion-1"
    artifacts.atomic_write_json(task_id, "request.json", _conversion_payload())
    repository.create(TaskRecord.new(
        task_id,
        "project-1",
        TaskKind.MODEL_CONVERSION,
        "request.json",
        "conversion:rknn",
    ), artifacts=artifacts)

    with pytest.raises(BatchRequestError) as blocked:
        create_batch(
            "project-1",
            materials,
            repository,
            artifacts,
            _delete_payload("project-1", materials, source=True),
        )
    assert blocked.value.code == "MATERIAL_ACTIVE_CONVERSION_REFERENCE"

    repository.request_cancel(task_id)
    created = create_batch(
        "project-1",
        materials,
        repository,
        artifacts,
        _delete_payload("project-1", materials, source=True),
    )
    assert created.kind is TaskKind.MATERIAL_BATCH


def test_active_delete_selection_blocks_new_input_admission_and_terminal_releases_it(tmp_path):
    _project, materials, repository, artifacts = _runtime(tmp_path)
    deletion = create_batch(
        "project-1",
        materials,
        repository,
        artifacts,
        _delete_payload("project-1", materials),
    )

    with pytest.raises(BatchRequestError) as blocked:
        assert_material_input_admission(
            "project-1", ["image-1"], materials, repository, artifacts,
        )
    assert blocked.value.code == "MATERIAL_ACTIVE_DELETE_REFERENCE"

    repository.request_cancel(deletion.task_id)
    assert_material_input_admission(
        "project-1", ["image-1"], materials, repository, artifacts,
    )


def test_training_admission_and_delete_publication_share_one_deterministic_fence(tmp_path):
    project, materials, repository, artifacts = _runtime(tmp_path)
    admission_holds_fence = threading.Event()
    release_admission = threading.Event()
    delete_started = threading.Event()
    results = {}

    def admit_training():
        with material_annotation_lifecycle_fence(project):
            assert_material_input_admission(
                "project-1", ["image-1"], materials, repository, artifacts,
            )
            admission_holds_fence.set()
            assert release_admission.wait(5)
            artifacts.atomic_write_json(
                "training-1", "payload.json", {"train_image_ids": ["image-1"]},
            )
            repository.create(TaskRecord.new(
                "training-1",
                "project-1",
                TaskKind.TRAINING,
                "payload.json",
                "training:cpu",
            ), artifacts=artifacts)

    def publish_delete():
        assert admission_holds_fence.wait(5)
        delete_started.set()
        try:
            create_batch(
                "project-1",
                materials,
                repository,
                artifacts,
                _delete_payload("project-1", materials),
            )
        except Exception as error:  # captured for the coordinating thread
            results["error"] = error

    training_thread = threading.Thread(target=admit_training)
    delete_thread = threading.Thread(target=publish_delete)
    training_thread.start()
    delete_thread.start()
    assert delete_started.wait(5)
    assert repository.get("training-1") is None
    release_admission.set()
    training_thread.join(5)
    delete_thread.join(5)

    assert not training_thread.is_alive()
    assert not delete_thread.is_alive()
    assert repository.get("training-1") is not None
    assert isinstance(results.get("error"), BatchRequestError)
    assert results["error"].code == "MATERIAL_ACTIVE_TRAINING_REFERENCE"


def test_frozen_calibration_identity_is_revalidated_at_final_admission(tmp_path):
    _project, materials, repository, artifacts = _runtime(tmp_path)
    expected = _conversion_payload()["remote_execution"]["conversion"]["calibration"]["items"]
    materials.patch({"image-1": {"content_sha256": "b" * 64}})

    with pytest.raises(BatchRequestError) as blocked:
        assert_material_input_admission(
            "project-1",
            ["image-1"],
            materials,
            repository,
            artifacts,
            expected_inputs=expected,
        )
    assert blocked.value.code == "MATERIAL_INPUT_IDENTITY_CHANGED"
