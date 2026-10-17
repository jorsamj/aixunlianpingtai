import sqlite3

from dataclasses import replace

from platform_core.material_batches import estimate_batch, parse_request, prepare_batch, public_batch
from platform_core.material_repository import MaterialRepository
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


def test_large_clean_selection_is_table_frozen_without_sql_variable_limits(tmp_path):
    ids = [f"image-{index:05d}" for index in range(1501)]
    materials = MaterialRepository(tmp_path / "project")
    materials.upsert_many([{"id": image_id, "filename": f"{image_id}.jpg"} for image_id in ids])
    artifacts = ArtifactStore(tmp_path / "artifacts")
    draft = {
        "operation": "CLEAN",
        "selection_spec": {"scope": "SELECTED", "image_ids": ids},
        "options": {},
    }

    estimate = estimate_batch("project-1", materials, draft)
    assert estimate["count"] == len(ids)
    draft["selection_spec"] = estimate["selection_spec"]
    task = prepare_batch("project-1", materials, artifacts, draft, task_id="large-clean-selection")

    selection_path = artifacts.artifact_path(task.task_id, "selection.sqlite3")
    with sqlite3.connect(selection_path) as database:
        assert database.execute("SELECT COUNT(*) FROM selection").fetchone()[0] == len(ids)
        assert database.execute("SELECT COUNT(*) FROM selection WHERE state='pending'").fetchone()[0] == len(ids)


def test_only_clean_and_ready_expand_the_explicit_selection_ceiling():
    ids = [f"image-{index:05d}" for index in range(20_000)]
    for operation in ("CLEAN", "MARK_CLEAN_SKIPPED"):
        parsed, selected, _ = parse_request({
            "operation": operation,
            "selection_spec": {"scope": "SELECTED", "image_ids": ids},
            "options": {},
        })
        assert parsed.value == operation
        assert len(selected.image_ids) == 20_000

    try:
        parse_request({
            "operation": "AI_ANNOTATE",
            "selection_spec": {"scope": "SELECTED", "image_ids": ids[:501]},
            "options": {},
        })
    except ValueError as error:
        assert "limited to 500 IDs" in str(error)
    else:
        raise AssertionError("AI explicit selection must keep the 500-ID safety limit")
