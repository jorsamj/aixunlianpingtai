from dataclasses import replace

import app as platform_app
from platform_core.task_runtime import ArtifactStore, TaskKind, TaskRecord, TaskRepository


def test_annotation_business_projection_exposes_waiting_resource_truth(tmp_path, monkeypatch):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    artifacts = ArtifactStore(tmp_path / "artifacts")
    monkeypatch.setattr(platform_app, "_SHARED_TASK_REPOSITORY", repository)
    monkeypatch.setattr(platform_app, "_SHARED_TASK_ARTIFACTS", artifacts)
    task_id = "annotation-waiting"
    artifacts.atomic_write_json(task_id, "request.json", {
        "image_ids": ["a", "b"], "labels": ["fire"], "task_name": "烟火标注",
    })
    queued = replace(
        TaskRecord.new(task_id, "project-1", TaskKind.AI_ANNOTATION, "request.json", "vision:model-a", priority=12),
        stage="resource_waiting", resource_wait_reason="VISION_CAPACITY_BUSY", queue_rank=3,
    )
    task = repository.create(queued, artifacts=artifacts)
    body = platform_app.public_annotation_task(task)
    assert body["status"] == "WAITING_RESOURCE"
    assert body["persisted_status"] == "QUEUED"
    assert body["priority"] == 12
    assert body["queue_rank"] == 3
    assert body["resource_queue_position"] == 1
    assert body["resource_wait_reason"] == "VISION_CAPACITY_BUSY"
    assert body["progress_percent"] == 0
    assert body["phase"] == "resource_waiting"
    assert body["total_count"] == 2
