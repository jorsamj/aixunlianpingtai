from dataclasses import replace

from platform_core.material_batches import public_batch
from platform_core.task_runtime import ArtifactStore, TaskKind, TaskRecord, TaskRepository


def test_material_batch_projection_exposes_waiting_resource_truth(tmp_path):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    artifacts = ArtifactStore(tmp_path / "artifacts")
    task_id = "clean-waiting"
    artifacts.atomic_write_json(task_id, "request.json", {"operation": "CLEAN", "options": {}})
    queued = replace(
        TaskRecord.new(task_id, "project-1", TaskKind.MATERIAL_BATCH, "request.json", "materials:project-1", priority=18),
        stage="resource_waiting", resource_wait_reason="MATERIAL_WORKER_BUSY", queue_rank=2,
    )
    task = repository.create(queued, artifacts=artifacts)
    body = public_batch(task, artifacts, repository)
    assert body["operation"] == "CLEAN"
    assert body["status"] == "WAITING_RESOURCE"
    assert body["persisted_status"] == "QUEUED"
    assert body["priority"] == 18
    assert body["queue_rank"] == 2
    assert body["resource_queue_position"] == 1
    assert body["resource_wait_reason"] == "MATERIAL_WORKER_BUSY"
    assert body["progress_percent"] == 0
    assert body["phase"] == "resource_waiting"
    assert body["scan_only"] is True
