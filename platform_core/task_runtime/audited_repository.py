from __future__ import annotations

import shutil
import sqlite3
import uuid
from dataclasses import replace
from pathlib import Path

from .artifacts import ArtifactStore
from .models import TaskKind, TaskRecord, TaskStatus, utc_now
from .repository import TERMINAL_STATUSES, TaskRepository as _TaskRepository, _from_row, _to_values
from .task_logs import create_task_log


_ACTIVE_RETRY_STATUSES = {
    TaskStatus.QUEUED.value,
    TaskStatus.RUNNING.value,
    TaskStatus.CANCEL_REQUESTED.value,
    TaskStatus.AWAITING_CONFIRMATION.value,
}


def _clone_sqlite_database(source: Path, destination: Path) -> None:
    """Create a transactionally consistent SQLite clone, including WAL state."""
    if not source.is_file():
        raise ValueError(f"required retry state is missing: {source.name}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_uri = f"{source.resolve().as_uri()}?mode=ro"
    with sqlite3.connect(source_uri, uri=True, timeout=5) as input_db:
        with sqlite3.connect(destination, timeout=5) as output_db:
            input_db.backup(output_db)
            output_db.commit()


class TaskRepository(_TaskRepository):
    """Task repository with immutable retry-attempt history.

    Generic retry creates a new task row and a fresh task-artifact namespace.
    The terminal source row is never rewritten. ``retry_of`` points to the
    immediately preceding attempt, which keeps a linear, auditable chain.

    Material batches additionally clone their frozen ``selection.sqlite3`` via
    SQLite backup so successful rows remain successful and only failed rows are
    replayed by the new attempt. This avoids copying a live WAL file blindly.

    Training post-processing recovery intentionally remains a same-task
    operation because it resumes preserved best/last artifacts rather than
    launching a new training attempt.
    """

    def retry(self, task_id: str) -> TaskRecord:
        source_id = str(task_id)
        terminal_values = tuple(
            status.value
            for status in TERMINAL_STATUSES
            if status is not TaskStatus.POST_PROCESSING_FAILED
        )
        artifacts = ArtifactStore(self.path.parent / "artifacts")
        created_root: Path | None = None

        with self._connect() as database:
            database.execute("BEGIN IMMEDIATE")
            source_row = database.execute(
                "SELECT * FROM tasks WHERE task_id=?",
                (source_id,),
            ).fetchone()
            if source_row is None:
                database.rollback()
                raise KeyError(source_id)
            if str(source_row["status"]) not in terminal_values:
                database.rollback()
                raise ValueError("only terminal tasks can be retried")

            # Prevent accidental branching when users double-click Retry or
            # retry an older ancestor after a later attempt already exists.
            child = database.execute(
                "SELECT * FROM tasks WHERE retry_of=? "
                "ORDER BY created_at DESC, task_id DESC LIMIT 1",
                (source_id,),
            ).fetchone()
            if child is not None:
                child_record = _from_row(child)
                if str(child["status"]) in _ACTIVE_RETRY_STATUSES:
                    database.commit()
                    return child_record
                database.rollback()
                raise ValueError(
                    f"task already has retry attempt {child_record.task_id}; retry the latest attempt instead"
                )

            source = _from_row(source_row)
            source_payload = artifacts.artifact_path(source.task_id, source.payload_ref)
            if not source_payload.is_file():
                database.rollback()
                raise ValueError("task payload artifact is missing; retry cannot reproduce the original request")

            new_id = uuid.uuid4().hex
            created_root = artifacts.root / new_id
            destination = artifacts.artifact_path(new_id, source.payload_ref)
            try:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_payload, destination)

                if source.kind is TaskKind.MATERIAL_BATCH:
                    _clone_sqlite_database(
                        artifacts.artifact_path(source.task_id, "selection.sqlite3"),
                        artifacts.artifact_path(new_id, "selection.sqlite3"),
                    )

                create_task_log(artifacts, new_id, source.log_ref)

                created_at = utc_now()
                new_record = replace(
                    TaskRecord.new(
                        task_id=new_id,
                        project_id=source.project_id,
                        kind=source.kind,
                        payload_ref=source.payload_ref,
                        resource_key=source.resource_key,
                        priority=source.priority,
                        required_capabilities=source.required_capabilities,
                    ),
                    retry_of=source.task_id,
                    created_at=created_at,
                    updated_at=created_at,
                )
                values = _to_values(new_record)
                columns = ",".join(values)
                placeholders = ",".join("?" for _ in values)
                database.execute(
                    f"INSERT INTO tasks ({columns}) VALUES ({placeholders})",
                    tuple(values.values()),
                )
                row = database.execute(
                    "SELECT * FROM tasks WHERE task_id=?",
                    (new_id,),
                ).fetchone()
                if row is None:
                    raise RuntimeError("retry task insert did not persist")
                result = _from_row(row)
                database.commit()
                return result
            except BaseException:
                database.rollback()
                if created_root is not None:
                    shutil.rmtree(created_root, ignore_errors=True)
                raise
