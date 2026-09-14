import io
import uuid

from PIL import Image

import app as app_module
from platform_core.task_runtime import (
    ArtifactStore, FencedTaskRepository, Scheduler, TaskKind, TaskStatus,
)
from platform_core.worker_registry import build_worker_registration


def _png_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (400, 300), "gray").save(output, format="PNG")
    return output.getvalue()


def _create_project(client, name: str) -> str:
    response = client.post("/api/projects", json={"name": name, "labels": []})
    response.raise_for_status()
    return response.json()["id"]


def _upload(client, project_id: str, *names: str) -> dict:
    response = client.post(
        f"/api/projects/{project_id}/images",
        files=[("files", (name, _png_bytes(), "image/png")) for name in names],
        data={"dataset_id": "default"},
    )
    response.raise_for_status()
    return response.json()


def _assert_durable_clean_task(project_id: str, task_id: str, expected_ids: list[str]):
    repository = app_module.shared_task_repository()
    task = repository.get(task_id)
    assert task is not None, "cleaning execution must be published to TaskRepository"
    assert task.project_id == project_id
    assert task.kind is TaskKind.MATERIAL_BATCH
    assert task.status is TaskStatus.QUEUED
    assert task.resource_key == f"materials:{project_id}"
    request = app_module.shared_task_artifacts().read_json(task_id, task.payload_ref, default={})
    assert request["operation"] == "CLEAN"
    assert sorted(request["selection_spec"]["image_ids"]) == sorted(expected_ids)


def test_v47_manual_clean_creation_publishes_material_batch_truth(client):
    project_id = _create_project(client, "manual-clean-unified-truth")
    uploaded = _upload(client, project_id, "manual-clean.png")
    image_id = uploaded["uploaded"][0]["id"]

    response = client.post(
        f"/api/v47/projects/{project_id}/clean-tasks",
        json={"image_ids": [image_id], "task_name": "manual durable clean"},
    )
    response.raise_for_status()
    body = response.json()
    task_id = body["id"]
    assert "resource_queue_position" in body
    assert "resource_wait_reason" in body
    queue_position = body["resource_queue_position"]
    if queue_position is not None:
        assert isinstance(queue_position, int)
        assert queue_position >= 1
    wait_reason = body["resource_wait_reason"]
    if wait_reason is not None:
        assert isinstance(wait_reason, str)

    _assert_durable_clean_task(project_id, task_id, [image_id])


def test_upload_batch_clean_association_points_to_same_durable_task(client):
    project_id = _create_project(client, "upload-clean-unified-truth")
    uploaded = _upload(client, project_id, "needs-clean.png", "ready.png")
    clean_id = uploaded["uploaded"][0]["id"]
    ready_id = uploaded["uploaded"][1]["id"]

    response = client.post(
        f"/api/v55/projects/{project_id}/upload-batches/{uploaded['batch_id']}/decisions",
        json={"clean_image_ids": [clean_id], "ready_image_ids": [ready_id]},
    )
    response.raise_for_status()
    task_id = response.json()["clean_task_id"]
    assert task_id

    _assert_durable_clean_task(project_id, task_id, [clean_id])
    repeated = client.post(
        f"/api/v55/projects/{project_id}/upload-batches/{uploaded['batch_id']}/decisions",
        json={"clean_image_ids": [clean_id], "ready_image_ids": [ready_id]},
    )
    repeated.raise_for_status()
    assert repeated.json()["clean_task_id"] == task_id
    assert app_module.shared_task_repository().get(task_id).task_id == task_id


def test_clean_executes_through_real_fenced_material_worker(client):
    project_id = _create_project(client, "clean-real-fenced-worker")
    uploaded = _upload(client, project_id, "real-worker.png")
    image_id = uploaded["uploaded"][0]["id"]
    response = client.post(
        f"/api/v47/projects/{project_id}/clean-tasks",
        json={"image_ids": [image_id], "task_name": "real worker clean"},
    )
    response.raise_for_status()
    task_id = response.json()["id"]

    runtime = app_module.DATA_DIR / "task_runtime"
    repository = FencedTaskRepository(runtime / "tasks.sqlite3")
    artifacts = ArtifactStore(runtime / "artifacts")
    handlers, capabilities = build_worker_registration(app_module.DATA_DIR, {"materials"})
    scheduler = Scheduler(
        repository,
        artifacts,
        f"clean-contract-{uuid.uuid4().hex[:8]}",
        handlers,
        capabilities,
        lease_seconds=5,
        poll_seconds=0.01,
    )
    for _ in range(10):
        current = app_module.shared_task_repository().get(task_id)
        assert current is not None
        if current.status in {TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.PARTIAL_SUCCESS}:
            break
        assert scheduler.run_once() is True
    current = app_module.shared_task_repository().get(task_id)
    assert current is not None
    assert current.status is TaskStatus.SUCCEEDED, current.error
    assert current.stage == "succeeded"
    assert current.progress == 100

    result_response = client.get(f"/api/v47/projects/{project_id}/clean-tasks/{task_id}/result")
    result_response.raise_for_status()
    body = result_response.json()
    assert body["task"]["status"] == "awaiting_confirmation"
    assert body["task"]["stage"] == "review"
    assert body["task"]["processed_images"] == 1
    assert body["task"]["progress"] == 100
    assert [item["image_id"] for item in body["result"]["items"]] == [image_id]

    durable_after_projection = app_module.shared_task_repository().get(task_id)
    assert durable_after_projection is not None
    assert durable_after_projection.status is TaskStatus.SUCCEEDED
    assert durable_after_projection.stage == "succeeded"
