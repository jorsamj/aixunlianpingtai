"""U5 readiness diagnostics are read-only and never invent a clean state."""
from __future__ import annotations

import sqlite3

from platform_core.task_runtime import TaskKind, TaskRecord, TaskRepository
from platform_core.task_store_readiness import readiness


def _store(tmp_path):
    repository = TaskRepository(tmp_path / "task_runtime" / "tasks.sqlite3")
    task = TaskRecord.new("t-running", "p1", TaskKind.TRAINING, "request.json", "cpu")
    repository.create(task)
    return repository, task


def test_missing_store_is_reported_and_blocks(tmp_path):
    report = readiness(tmp_path)
    assert report["present"] is False
    assert report["blockers"] == ["task_store_missing"]
    assert report["ready_for_cutover"] is False
    assert report["read_only"] is True


def test_readiness_reports_facts_without_writing(tmp_path):
    repository, _task = _store(tmp_path)
    with sqlite3.connect(repository.path) as database:
        before = database.execute("SELECT status,attempt,updated_at FROM tasks").fetchall()
    report = readiness(tmp_path)
    assert report["provider"] == "sqlite"
    assert report["present"] is True and report["tasks"] == 1
    assert report["schema_version"] is not None
    assert report["ready_for_cutover"] is False  # one queued task exists
    with sqlite3.connect(repository.path) as database:
        after = database.execute("SELECT status,attempt,updated_at FROM tasks").fetchall()
    assert before == after  # diagnostics never mutate the task store


def test_unverified_stop_blocks_the_cutover(tmp_path):
    repository, task = _store(tmp_path)
    with sqlite3.connect(repository.path) as database:
        database.execute("UPDATE tasks SET status='cancelling_unverified' WHERE task_id=?", (task.task_id,))
    report = readiness(tmp_path)
    assert report["unverified_stop"] == 1
    assert "unverified_stop_proof" in report["blockers"]
    assert report["ready_for_cutover"] is False
