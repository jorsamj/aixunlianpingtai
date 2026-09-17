from dataclasses import replace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from platform_core.material_batches import material_batch_router
from platform_core.task_runtime import ArtifactStore, TaskKind, TaskRecord, TaskRepository


def test_material_batch_business_route_exposes_waiting_resource_truth(tmp_path):
    runtime = tmp_path / "task_runtime"
    repository = TaskRepository(runtime / "tasks.sqlite3")
    artifacts = ArtifactStore(runtime / "artifacts")
    project_id = "project-1"
    task_id = "clean-route-waiting"
    artifacts.atomic_write_json(task_id, "request.json", {"operation": "CLEAN", "options": {}})
    task = replace(
        TaskRecord.new(
            task_id, project_id, TaskKind.MATERIAL_BATCH, "request.json",
            "materials:project-1", priority=9, required_capabilities=("materials.batch",),
        ),
        stage="resource_waiting",
        resource_wait_reason="MATERIAL_WORKER_BUSY",
        queue_rank=7,
    )
    repository.create(task, artifacts=artifacts)

    api = FastAPI()
    api.include_router(material_batch_router(
        lambda requested: {"id": requested},
        lambda _requested: None,
        lambda: repository,
        lambda: artifacts,
    ))
    client = TestClient(api)

    response = client.get(f"/api/v62/projects/{project_id}/material-batches/{task_id}")
    response.raise_for_status()
    body = response.json()
    assert body["operation"] == "CLEAN"
    assert body["status"] == "WAITING_RESOURCE"
    assert body["persisted_status"] == "QUEUED"
    assert body["priority"] == 9
    assert body["queue_rank"] == 7
    assert body["resource_queue_position"] == 1
    assert body["resource_wait_reason"] == "MATERIAL_WORKER_BUSY"
    assert body["progress_percent"] == 0
    assert body["phase"] == "resource_waiting"
    assert body["scan_only"] is True
