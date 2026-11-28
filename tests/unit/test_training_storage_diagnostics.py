from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from platform_core.task_runtime import (
    ArtifactStore,
    TaskKind,
    TaskRecord,
    TaskRepository,
    TaskStatus,
)
from platform_core.training_storage_diagnostics import training_storage_diagnostics
from platform_core.training_workspace_lifecycle import mark_training_workspace


def _storage(tmp_path):
    data = tmp_path / "data"
    (data / "projects" / "p").mkdir(parents=True)
    artifacts = ArtifactStore(data / "task_runtime" / "artifacts")
    repository = TaskRepository(data / "task_runtime" / "tasks.sqlite3")
    return data, repository, artifacts


def _create_task(repository, artifacts, *, task_id, status, snapshot_id):
    created = TaskRecord.new(
        task_id, "p", TaskKind.TRAINING, "payload.json", f"training:{task_id}",
    )
    task = replace(
        created,
        status=status,
        attempt=1,
        finished_at="2026-11-24T00:00:00+00:00"
        if status in {
            TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED,
        } else None,
    )
    repository.create(task)
    snapshot = {"snapshot_id": snapshot_id, "dataset_revision_id": "b" * 64}
    artifacts.atomic_write_json(task_id, "payload.json", {
        "target": "local", "input_freeze_id": "f", "snapshot_id": snapshot_id,
    })
    mark_training_workspace(artifacts, task, snapshot, "f")
    image = artifacts.artifact_path(task_id, "work/bundle/dataset/images/train/x.jpg")
    image.parent.mkdir(parents=True)
    image.write_bytes(b"task-owned-copy")
    artifacts.atomic_write_json(task_id, "work/bundle/manifest.json", {
        **snapshot, "splits": {},
    })
    checkpoint = artifacts.artifact_path(task_id, "checkpoints/last.pt")
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_bytes(b"checkpoint-bytes")
    artifacts.atomic_write_json(task_id, "failure.json", {
        "task_id": task_id, "project_id": "p", "recoverable": False,
    })
    return image, checkpoint


def test_storage_diagnostics_is_read_only_and_classifies_tasks(tmp_path):
    data, repository, artifacts = _storage(tmp_path)
    image, checkpoint = _create_task(
        repository, artifacts, task_id="terminal-task",
        status=TaskStatus.FAILED, snapshot_id="a" * 64,
    )
    _create_task(
        repository, artifacts, task_id="active-task",
        status=TaskStatus.RUNNING, snapshot_id="c" * 64,
    )

    result = training_storage_diagnostics(data, "p", repository, artifacts)

    assert result["schema_version"] == 1
    assert result["guarantees"]["read_only"] is True
    assert result["guarantees"]["deletion_performed"] is False
    assert result["guarantees"]["automatic_gc_enabled"] is False
    assert result["totals"]["task_count"] == 2
    tasks = {item["task_id"]: item for item in result["tasks"]}
    assert tasks["active-task"]["terminal"] is False
    assert tasks["active-task"]["classification"] == "protected"
    assert "TASK_NOT_TERMINAL" in tasks["active-task"]["blockers"]
    assert tasks["terminal-task"]["terminal"] is True
    assert tasks["terminal-task"]["classification"] in {"protected", "reclaimable", "unknown"}
    assert tasks["terminal-task"]["workspace_bytes"] > 0
    assert tasks["terminal-task"]["checkpoints"] == [{
        "name": "last.pt",
        "size_bytes": len(b"checkpoint-bytes"),
        "modified_at": tasks["terminal-task"]["checkpoints"][0]["modified_at"],
    }]
    # Both tasks own one checkpoint file of the same size.
    assert result["totals"]["checkpoint_bytes"] == 2 * len(b"checkpoint-bytes")
    assert result["cache_preview"]["dry_run"] is True
    # Nothing may be removed by a diagnostic call.
    assert image.is_file()
    assert checkpoint.is_file()
    assert artifacts.artifact_path("terminal-task", "work/bundle").is_dir()


def test_storage_diagnostics_respects_limit_and_is_idempotent(tmp_path):
    data, repository, artifacts = _storage(tmp_path)
    for index in range(3):
        _create_task(
            repository, artifacts, task_id=f"task-{index}",
            status=TaskStatus.SUCCEEDED, snapshot_id=f"{index}" * 64,
        )

    first = training_storage_diagnostics(
        data, "p", repository, artifacts, limit=2, include_cache_preview=False,
    )
    assert len(first["tasks"]) == 2
    assert first["limit"] == 2
    assert first["cache_preview"] is None
    before = json.dumps(first["totals"], sort_keys=True)
    second = training_storage_diagnostics(
        data, "p", repository, artifacts, limit=2, include_cache_preview=False,
    )
    assert json.dumps(second["totals"], sort_keys=True) == before
