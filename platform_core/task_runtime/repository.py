from __future__ import annotations

import base64
import json
import sqlite3
import os
import shutil
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from .models import TaskKind, TaskLease, TaskPage, TaskRecord, TaskStatus, utc_now
from .process_control import ProcessIdentity
from ..gpu_resources import GPU_SCHEMA


SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    priority INTEGER NOT NULL CHECK(priority BETWEEN 1 AND 999),
    queue_rank INTEGER NOT NULL DEFAULT 0,
    resource_key TEXT NOT NULL,
    required_capabilities TEXT NOT NULL,
    payload_ref TEXT NOT NULL,
    result_ref TEXT,
    log_ref TEXT NOT NULL,
    progress REAL NOT NULL,
    stage TEXT NOT NULL,
    current_item TEXT,
    attempt INTEGER NOT NULL,
    retry_of TEXT,
    error TEXT,
    accepted INTEGER,
    process_pid INTEGER,
    process_create_time REAL,
    process_command_hash TEXT,
    process_group_id INTEGER,
    process_launch_token TEXT,
    worker_id TEXT,
    lease_token TEXT,
    lease_expires_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_task_claim
    ON tasks(status, priority, created_at, task_id);
CREATE INDEX IF NOT EXISTS idx_task_resource
    ON tasks(resource_key, status, lease_expires_at);
CREATE INDEX IF NOT EXISTS idx_task_project_list
    ON tasks(project_id, created_at DESC, task_id DESC);
CREATE TABLE IF NOT EXISTS worker_instances (
    instance_key TEXT PRIMARY KEY,
    owner_token TEXT NOT NULL,
    worker_id TEXT NOT NULL,
    pid INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    heartbeat_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_worker_instances_expiry
    ON worker_instances(expires_at);
"""


TERMINAL_STATUSES = {
    TaskStatus.PARTIAL_SUCCESS,
    TaskStatus.POST_PROCESSING_FAILED,
    TaskStatus.SUCCEEDED,
    TaskStatus.CANCELLED,
    TaskStatus.FAILED,
    TaskStatus.BLOCKED_BY_ENVIRONMENT,
    TaskStatus.BLOCKED_BY_HARDWARE,
}


def _iso(value: datetime | str | None = None) -> str:
    if value is None:
        return utc_now()
    if isinstance(value, str):
        return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _to_values(record: TaskRecord) -> dict:
    values = asdict(record)
    values["kind"] = record.kind.value
    values["status"] = record.status.value
    values["required_capabilities"] = json.dumps(
        list(record.required_capabilities),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    values["accepted"] = None if record.accepted is None else int(record.accepted)
    return values


def _from_row(row: sqlite3.Row) -> TaskRecord:
    return TaskRecord(
        task_id=str(row["task_id"]),
        project_id=str(row["project_id"]),
        kind=TaskKind(str(row["kind"])),
        status=TaskStatus(str(row["status"])),
        priority=int(row["priority"]),
        resource_key=str(row["resource_key"]),
        required_capabilities=tuple(json.loads(row["required_capabilities"] or "[]")),
        payload_ref=str(row["payload_ref"]),
        result_ref=row["result_ref"],
        log_ref=str(row["log_ref"]),
        progress=float(row["progress"]),
        stage=str(row["stage"]),
        current_item=row["current_item"],
        attempt=int(row["attempt"]),
        retry_of=row["retry_of"],
        error=row["error"],
        accepted=None if row["accepted"] is None else bool(row["accepted"]),
        process_pid=row["process_pid"],
        process_create_time=row["process_create_time"],
        process_command_hash=row["process_command_hash"],
        process_group_id=row["process_group_id"],
        process_launch_token=row["process_launch_token"],
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        finished_at=row["finished_at"],
        resource_wait_reason=row["resource_wait_reason"],
    )


def _encode_cursor(created_at: str, task_id: str) -> str:
    raw = json.dumps([created_at, task_id], separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> tuple[str, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        value = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        if not isinstance(value, list) or len(value) != 2:
            raise ValueError
        return str(value[0]), str(value[1])
    except Exception as error:
        raise ValueError("invalid task cursor") from error


class TaskRepository:
    def __init__(self, path: str | Path, *, allow_create: bool = True):
        self.path = Path(path).resolve()
        self._allow_create = bool(allow_create)
        self._identity_marker = self.path.with_suffix(self.path.suffix + ".initialized")
        database_existed = self.path.is_file()
        if not database_existed and self._identity_marker.is_file():
            raise sqlite3.OperationalError(
                f"task database is missing but its initialization marker exists: {self.path}"
            )
        self._creation_authorized = self._allow_create and not database_existed
        self._initialized = False
        if self._creation_authorized:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as database:
            database.executescript(SCHEMA)
            columns = {str(row[1]) for row in database.execute("PRAGMA table_info(tasks)").fetchall()}
            if "queue_rank" not in columns:
                database.execute("ALTER TABLE tasks ADD COLUMN queue_rank INTEGER NOT NULL DEFAULT 0")
            if "resource_wait_reason" not in columns:
                database.execute("ALTER TABLE tasks ADD COLUMN resource_wait_reason TEXT")
            if "process_group_id" not in columns:
                database.execute("ALTER TABLE tasks ADD COLUMN process_group_id INTEGER")
            if "process_launch_token" not in columns:
                database.execute("ALTER TABLE tasks ADD COLUMN process_launch_token TEXT")
            database.executescript(GPU_SCHEMA)
        marker_tmp = self._identity_marker.with_suffix(self._identity_marker.suffix + ".tmp")
        try:
            marker_tmp.write_text(str(self.path), encoding="utf-8")
            marker_tmp.replace(self._identity_marker)
        except OSError as error:
            raise sqlite3.OperationalError(
                f"cannot persist task database identity marker: {self._identity_marker}: {error}"
            ) from error
        self._initialized = True

    def database_diagnostic(self, error: Exception | None = None) -> dict:
        parent = self.path.parent
        mount = None
        try:
            import psutil
            matches = [row for row in psutil.disk_partitions(all=True)
                       if str(parent).casefold().startswith(str(Path(row.mountpoint).resolve()).casefold())]
            if matches:
                row = max(matches, key=lambda value: len(str(value.mountpoint)))
                mount = {"mountpoint": row.mountpoint, "filesystem": row.fstype, "options": row.opts}
        except (ImportError, OSError):
            pass
        try:
            usage = shutil.disk_usage(parent)
            disk = {"free_bytes": int(usage.free), "total_bytes": int(usage.total)}
        except OSError as disk_error:
            disk = {"error": str(disk_error)}
        return {
            "status": "ERROR" if error else "AVAILABLE",
            "database": str(self.path), "database_exists": self.path.is_file(),
            "parent": str(parent), "parent_exists": parent.is_dir(),
            "parent_readable": os.access(parent, os.R_OK), "parent_writable": os.access(parent, os.W_OK),
            "disk": disk, "mount": mount,
            "error": None if error is None else f"{type(error).__name__}: {error}",
            "updated_at": utc_now(),
        }

    def _write_diagnostic(self, error: Exception | None = None) -> None:
        target = self.path.with_suffix(self.path.suffix + ".health.json")
        try:
            temporary = target.with_suffix(target.suffix + ".tmp")
            temporary.write_text(json.dumps(self.database_diagnostic(error), ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(target)
        except OSError:
            pass

    def _connect(self) -> sqlite3.Connection:
        may_create = self._creation_authorized and not self._initialized
        if not may_create and not self.path.is_file():
            error = sqlite3.OperationalError(f"task database disappeared: {self.path}")
            self._write_diagnostic(error)
            raise error
        last_error = None
        for delay in (0.0, 0.1, 0.4, 1.0):
            if delay:
                time.sleep(delay)
            database = None
            try:
                # mode=rw closes the check/open race: once initialized (and for
                # Worker processes) SQLite is forbidden from recreating a
                # missing database at the configured path.
                mode = "rwc" if may_create else "rw"
                database = sqlite3.connect(f"{self.path.as_uri()}?mode={mode}", uri=True,
                                           timeout=5, isolation_level=None)
                database.row_factory = sqlite3.Row
                database.execute("PRAGMA journal_mode=WAL")
                database.execute("PRAGMA synchronous=FULL")
                database.execute("PRAGMA busy_timeout=5000")
                health = self.path.with_suffix(self.path.suffix + ".health.json")
                if health.exists():
                    try:
                        health.unlink()
                    except OSError:
                        pass
                return database
            except sqlite3.OperationalError as error:
                last_error = error
                if database is not None:
                    database.close()
        self._write_diagnostic(last_error)
        raise last_error or sqlite3.OperationalError(f"unable to open task database: {self.path}")

    def journal_mode(self) -> str:
        with self._connect() as database:
            return str(database.execute("PRAGMA journal_mode").fetchone()[0]).lower()

    def create(self, record: TaskRecord, *, artifacts=None) -> TaskRecord:
        from .artifacts import ArtifactStore
        from .task_logs import create_task_log

        # Persist the real artifact before exposing its reference in a task row.
        create_task_log(artifacts or ArtifactStore(self.path.parent / "artifacts"), record.task_id, record.log_ref)
        values = _to_values(record)
        columns = ",".join(values)
        placeholders = ",".join("?" for _ in values)
        with self._connect() as database:
            database.execute("BEGIN IMMEDIATE")
            database.execute(
                f"INSERT INTO tasks ({columns}) VALUES ({placeholders})",
                tuple(values.values()),
            )
            row = database.execute("SELECT * FROM tasks WHERE task_id=?", (record.task_id,)).fetchone()
            if row is None:
                raise RuntimeError("task insert did not persist")
            # Resolve the return value before publishing the row. A failed read
            # must roll back rather than report failure for a claimable task.
            created = _from_row(row)
            database.commit()
        return created

    def get(self, task_id: str) -> TaskRecord | None:
        with self._connect() as database:
            row = database.execute(
                "SELECT * FROM tasks WHERE task_id=?",
                (str(task_id),),
            ).fetchone()
        return _from_row(row) if row is not None else None

    def list(
        self,
        project_id: str | None = None,
        kinds: Iterable[TaskKind | str] | None = None,
        statuses: Iterable[TaskStatus | str] | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> TaskPage:
        bounded_limit = max(1, min(100, int(limit)))
        clauses: list[str] = []
        parameters: list[object] = []
        if project_id is not None:
            clauses.append("project_id=?")
            parameters.append(str(project_id))
        if kinds:
            values = [item.value if isinstance(item, TaskKind) else str(item) for item in kinds]
            clauses.append(f"kind IN ({','.join('?' for _ in values)})")
            parameters.extend(values)
        if statuses:
            values = [item.value if isinstance(item, TaskStatus) else str(item) for item in statuses]
            clauses.append(f"status IN ({','.join('?' for _ in values)})")
            parameters.extend(values)
        if cursor:
            created_at, task_id = _decode_cursor(cursor)
            clauses.append("(created_at < ? OR (created_at = ? AND task_id < ?))")
            parameters.extend([created_at, created_at, task_id])
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as database:
            rows = database.execute(
                f"SELECT * FROM tasks {where} ORDER BY created_at DESC, task_id DESC LIMIT ?",
                (*parameters, bounded_limit + 1),
            ).fetchall()
        has_more = len(rows) > bounded_limit
        visible = rows[:bounded_limit]
        next_cursor = None
        if has_more and visible:
            next_cursor = _encode_cursor(visible[-1]["created_at"], visible[-1]["task_id"])
        return TaskPage(tuple(_from_row(row) for row in visible), next_cursor)

    def _release_expired_in(self, database: sqlite3.Connection, now: str) -> int:
        count = database.execute(
            """
            UPDATE tasks
               SET status=CASE WHEN status='CANCEL_REQUESTED' AND kind<>'TRAINING' THEN 'CANCELLED' ELSE 'QUEUED' END,
                   stage=CASE
                       WHEN kind='TRAINING' AND (status='CANCEL_REQUESTED' OR stage='cancel_recovery')
                           THEN 'cancel_recovery'
                       WHEN status='CANCEL_REQUESTED' THEN 'cancelled'
                       WHEN kind='MATERIAL_IMPORT' AND accepted=1 AND stage='indexing'
                           THEN 'indexing_queued'
                       ELSE 'recovered'
                   END,
                   finished_at=CASE WHEN status='CANCEL_REQUESTED' AND kind<>'TRAINING' THEN ? ELSE NULL END,
                   worker_id=NULL,
                   lease_token=NULL, lease_expires_at=NULL, updated_at=?
             WHERE status IN ('RUNNING','CANCEL_REQUESTED')
               AND lease_expires_at IS NOT NULL AND lease_expires_at<=?
            """,
            (now, now, now),
        ).rowcount
        database.execute("DELETE FROM gpu_reservations WHERE expires_at<=?", (now,))
        return count

    def release_expired(self, now: datetime | str | None = None) -> int:
        now_text = _iso(now)
        with self._connect() as database:
            database.execute("BEGIN IMMEDIATE")
            count = self._release_expired_in(database, now_text)
            database.commit()
        return count

    def claim_next(
        self,
        worker_id: str,
        kinds: Iterable[TaskKind | str],
        capabilities: Iterable[str],
        lease_seconds: int = 30,
        admission=None,
    ) -> TaskLease | None:
        kind_values = tuple(
            item.value if isinstance(item, TaskKind) else str(item) for item in kinds
        )
        if not kind_values:
            return None
        available = set(capabilities)
        now = datetime.now(timezone.utc)
        now_text = now.isoformat()
        expires_at = (now + timedelta(seconds=max(1, int(lease_seconds)))).isoformat()
        token = uuid.uuid4().hex
        placeholders = ",".join("?" for _ in kind_values)
        with self._connect() as database:
            database.execute("BEGIN IMMEDIATE")
            self._release_expired_in(database, now_text)
            rows = database.execute(
                f"""
                SELECT candidate.* FROM tasks candidate
                 WHERE candidate.status='QUEUED'
                   AND candidate.kind IN ({placeholders})
                   AND ((? AND candidate.kind='TRAINING'
                         AND candidate.resource_key NOT LIKE 'training:remote:%') OR NOT EXISTS (
                       SELECT 1 FROM tasks active
                        WHERE active.resource_key=candidate.resource_key
                          AND active.status IN ('RUNNING','CANCEL_REQUESTED')
                          AND active.lease_expires_at>?
                   ))
                 ORDER BY candidate.priority ASC, candidate.queue_rank DESC, candidate.created_at ASC,
                          candidate.task_id ASC
                """,
                (*kind_values, int(admission is not None), now_text),
            ).fetchall()
            chosen = None
            for candidate in rows:
                if not set(json.loads(candidate["required_capabilities"] or "[]")) <= available:
                    continue
                # A recovered cancellation only needs to verify/stop its bound
                # process and finalize CANCELLED.  It must never wait for (or
                # reserve) a GPU, otherwise resource_waiting would erase the
                # durable cancellation intent and could restart training.
                if admission is not None and candidate["stage"] != "cancel_recovery":
                    allowed, reason = admission(database, candidate, worker_id, token, expires_at, now_text)
                    if not allowed:
                        database.execute("UPDATE tasks SET stage='resource_waiting', resource_wait_reason=?, updated_at=? "
                                         "WHERE task_id=? AND (stage<>'resource_waiting' OR resource_wait_reason IS NOT ?)",
                                         (reason, now_text, candidate["task_id"], reason))
                        continue
                chosen = candidate
                break
            if chosen is None:
                database.commit()
                return None
            changed = database.execute(
                """
                UPDATE tasks
                   SET status='RUNNING',
                       stage=CASE
                           WHEN stage='cancel_recovery' THEN 'cancel_recovery'
                           WHEN stage='post_processing_queued' THEN 'post_processing'
                           WHEN kind='MATERIAL_IMPORT' AND accepted=1 AND stage='indexing_queued'
                               THEN 'indexing'
                           ELSE 'running'
                       END,
                       worker_id=?, lease_token=?,
                       lease_expires_at=?, attempt=attempt+1, updated_at=?, finished_at=NULL, resource_wait_reason=NULL
                 WHERE task_id=? AND status='QUEUED'
                """,
                (worker_id, token, expires_at, now_text, chosen["task_id"]),
            ).rowcount
            if changed != 1:
                database.rollback()
                return None
            row = database.execute(
                "SELECT * FROM tasks WHERE task_id=?",
                (chosen["task_id"],),
            ).fetchone()
            database.commit()
        task = _from_row(row)
        return TaskLease(task, token, str(worker_id), expires_at)

    def heartbeat(
        self,
        task_id: str,
        lease_token: str,
        progress=None,
        stage=None,
        current_item=None,
    ) -> TaskRecord:
        updates = ["updated_at=?", "lease_expires_at=?"]
        now = datetime.now(timezone.utc)
        parameters: list[object] = [now.isoformat(), (now + timedelta(seconds=30)).isoformat()]
        if progress is not None:
            updates.append("progress=?")
            parameters.append(max(0.0, min(100.0, float(progress))))
        if stage is not None:
            updates.append("stage=?")
            parameters.append(str(stage))
        if current_item is not None:
            updates.append("current_item=?")
            parameters.append(str(current_item))
        parameters.extend([str(task_id), str(lease_token)])
        with self._connect() as database:
            changed = database.execute(
                f"UPDATE tasks SET {','.join(updates)} "
                "WHERE task_id=? AND lease_token=? AND status IN ('RUNNING','CANCEL_REQUESTED')",
                parameters,
            ).rowcount
        if changed != 1:
            raise PermissionError("task lease does not own heartbeat")
        result = self.get(task_id)
        if result is None:
            raise KeyError(task_id)
        return result

    def bind_process(
        self,
        task_id: str,
        lease_token: str,
        identity: ProcessIdentity,
    ) -> TaskRecord:
        now = utc_now()
        with self._connect() as database:
            changed = database.execute(
                """
                UPDATE tasks SET process_pid=?, process_create_time=?,
                    process_command_hash=?, process_group_id=?, process_launch_token=?, updated_at=?
                 WHERE task_id=? AND lease_token=?
                   AND status IN ('RUNNING','CANCEL_REQUESTED')
                """,
                (
                    int(identity.pid),
                    float(identity.create_time),
                    str(identity.command_hash),
                    identity.process_group_id,
                    identity.launch_token,
                    now,
                    str(task_id),
                    str(lease_token),
                ),
            ).rowcount
        if changed != 1:
            raise PermissionError("task lease does not own process identity")
        result = self.get(task_id)
        if result is None:
            raise KeyError(task_id)
        return result

    def set_stage(self, task_id: str, stage: str) -> TaskRecord:
        value = str(stage or "").strip()
        if not value:
            raise ValueError("task stage cannot be empty")
        now = utc_now()
        with self._connect() as database:
            changed = database.execute(
                "UPDATE tasks SET stage=?, updated_at=? WHERE task_id=? AND status IN ('RUNNING','CANCEL_REQUESTED')",
                (value, now, str(task_id)),
            ).rowcount
        if changed != 1:
            raise ValueError("only active tasks can change stage")
        result = self.get(task_id)
        if result is None:
            raise KeyError(task_id)
        return result

    def promote(self, task_id: str) -> TaskRecord:
        now = utc_now()
        with self._connect() as database:
            database.execute("BEGIN IMMEDIATE")
            row = database.execute(
                "SELECT status, resource_key FROM tasks WHERE task_id=?",
                (str(task_id),),
            ).fetchone()
            if row is None:
                database.rollback()
                raise KeyError(task_id)
            if str(row["status"]) != TaskStatus.QUEUED.value:
                database.rollback()
                raise ValueError("only queued tasks can be promoted")
            peers = database.execute(
                "SELECT MIN(priority), MAX(queue_rank) FROM tasks WHERE resource_key=? AND status='QUEUED'",
                (str(row["resource_key"]),),
            ).fetchone()
            minimum = int(peers[0] if peers and peers[0] is not None else 50)
            maximum_rank = int(peers[1] if peers and peers[1] is not None else 0)
            priority = max(1, minimum - 1)
            rank = maximum_rank + 1 if priority == minimum else 0
            database.execute(
                "UPDATE tasks SET priority=?, queue_rank=?, updated_at=? WHERE task_id=?",
                (priority, rank, now, str(task_id)),
            )
            database.commit()
        result = self.get(task_id)
        if result is None:
            raise KeyError(task_id)
        return result

    def request_cancel(self, task_id: str) -> TaskRecord:
        now = utc_now()
        with self._connect() as database:
            database.execute("BEGIN IMMEDIATE")
            row = database.execute(
                "SELECT status, kind, process_pid FROM tasks WHERE task_id=?",
                (str(task_id),),
            ).fetchone()
            if row is None:
                database.rollback()
                raise KeyError(task_id)
            status = TaskStatus(row["status"])
            if (status is TaskStatus.QUEUED and row["kind"] == TaskKind.TRAINING.value
                    and row["process_pid"] is not None):
                database.execute(
                    "UPDATE tasks SET stage='cancel_recovery', finished_at=NULL, updated_at=?, "
                    "resource_wait_reason=NULL WHERE task_id=?",
                    (now, str(task_id)),
                )
            elif status is TaskStatus.QUEUED or status is TaskStatus.AWAITING_CONFIRMATION:
                database.execute(
                    """
                    UPDATE tasks SET status='CANCELLED', stage='cancelled', accepted=COALESCE(accepted,0),
                        finished_at=?, updated_at=?, worker_id=NULL, lease_token=NULL,
                        lease_expires_at=NULL WHERE task_id=?
                    """,
                    (now, now, str(task_id)),
                )
            elif status is TaskStatus.RUNNING:
                database.execute(
                    "UPDATE tasks SET status='CANCEL_REQUESTED', stage='cancelling', updated_at=? WHERE task_id=?",
                    (now, str(task_id)),
                )
            database.commit()
        result = self.get(task_id)
        if result is None:
            raise KeyError(task_id)
        return result

    def finish(
        self,
        task_id: str,
        lease_token: str,
        status: TaskStatus,
        result_ref: str | None = None,
        error: str | None = None,
        accepted: bool | None = None,
    ) -> TaskRecord:
        if status not in TERMINAL_STATUSES | {TaskStatus.AWAITING_CONFIRMATION}:
            raise ValueError("invalid worker finish status")
        now = utc_now()
        finished_at = None if status is TaskStatus.AWAITING_CONFIRMATION else now
        stage = "awaiting_confirmation" if status is TaskStatus.AWAITING_CONFIRMATION else status.value.lower()
        progress = 100.0 if status in {
            TaskStatus.AWAITING_CONFIRMATION,
            TaskStatus.PARTIAL_SUCCESS,
            TaskStatus.SUCCEEDED,
        } else None
        with self._connect() as database:
            changed = database.execute(
                """
                UPDATE tasks SET status=?, result_ref=?, error=?, accepted=?, stage=?,
                    progress=COALESCE(?, progress), finished_at=?, updated_at=?,
                    worker_id=NULL, lease_token=NULL, lease_expires_at=NULL
                 WHERE task_id=? AND lease_token=?
                   AND status IN ('RUNNING','CANCEL_REQUESTED')
                """,
                (
                    status.value,
                    result_ref,
                    error,
                    None if accepted is None else int(accepted),
                    stage,
                    progress,
                    finished_at,
                    now,
                    str(task_id),
                    str(lease_token),
                ),
            ).rowcount
        if changed != 1:
            raise PermissionError("task lease does not own finish")
        result = self.get(task_id)
        if result is None:
            raise KeyError(task_id)
        return result

    def complete_review(
        self,
        task_id: str,
        status: TaskStatus,
        result_ref: str,
        accepted: bool,
        error: str | None = None,
    ) -> TaskRecord:
        if status not in {TaskStatus.SUCCEEDED, TaskStatus.PARTIAL_SUCCESS}:
            raise ValueError("review must finish as success or partial success")
        now = utc_now()
        with self._connect() as database:
            database.execute("BEGIN IMMEDIATE")
            row = database.execute(
                "SELECT * FROM tasks WHERE task_id=?",
                (str(task_id),),
            ).fetchone()
            if row is None:
                database.rollback()
                raise KeyError(task_id)
            current = _from_row(row)
            if current.status in {TaskStatus.SUCCEEDED, TaskStatus.PARTIAL_SUCCESS}:
                if (
                    current.status is status
                    and current.result_ref == result_ref
                    and current.accepted is bool(accepted)
                    and current.error == error
                ):
                    database.commit()
                    return current
                database.rollback()
                raise ValueError("conflicting review completion")
            if current.status is not TaskStatus.AWAITING_CONFIRMATION:
                database.rollback()
                raise ValueError("task is not awaiting confirmation")
            database.execute(
                """
                UPDATE tasks SET status=?, result_ref=?, accepted=?, error=?, progress=100,
                    stage=?, finished_at=?, updated_at=? WHERE task_id=?
                """,
                (
                    status.value,
                    result_ref,
                    int(accepted),
                    error,
                    status.value.lower(),
                    now,
                    now,
                    str(task_id),
                ),
            )
            database.commit()
        result = self.get(task_id)
        if result is None:
            raise KeyError(task_id)
        return result

    def resume_after_confirmation(self, task_id: str) -> TaskRecord:
        now = utc_now()
        with self._connect() as database:
            database.execute("BEGIN IMMEDIATE")
            row = database.execute(
                "SELECT * FROM tasks WHERE task_id=?",
                (str(task_id),),
            ).fetchone()
            if row is None:
                database.rollback()
                raise KeyError(task_id)
            current = _from_row(row)
            if current.kind is not TaskKind.MATERIAL_IMPORT:
                database.rollback()
                raise ValueError("only material import tasks can resume after confirmation")
            if current.accepted is False:
                database.rollback()
                raise ValueError("task cannot resume after confirmation")
            if current.status is TaskStatus.AWAITING_CONFIRMATION:
                database.execute(
                    """
                    UPDATE tasks SET status='QUEUED', stage='indexing_queued', progress=0,
                        current_item=NULL, error=NULL, accepted=1, finished_at=NULL,
                        updated_at=?, worker_id=NULL, lease_token=NULL, lease_expires_at=NULL
                     WHERE task_id=? AND status='AWAITING_CONFIRMATION'
                    """,
                    (now, str(task_id)),
                )
                row = database.execute(
                    "SELECT * FROM tasks WHERE task_id=?",
                    (str(task_id),),
                ).fetchone()
                database.commit()
                return _from_row(row)
            if current.accepted is True and (
                (current.status is TaskStatus.QUEUED and current.stage == "indexing_queued")
                or (current.status is TaskStatus.RUNNING and current.stage == "indexing")
                or current.status in {TaskStatus.SUCCEEDED, TaskStatus.PARTIAL_SUCCESS}
            ):
                database.commit()
                return current
            database.rollback()
            raise ValueError("task cannot resume after confirmation")

    def retry(self, task_id: str) -> TaskRecord:
        now = utc_now()
        # A completed training whose post-processing failed must retain its
        # result_ref and verified weights; only retry_post_processing may
        # requeue it.  Generic retry would otherwise erase those artifacts and
        # accidentally launch model training again.
        terminal_values = tuple(status.value for status in TERMINAL_STATUSES
                                if status is not TaskStatus.POST_PROCESSING_FAILED)
        placeholders = ",".join("?" for _ in terminal_values)
        with self._connect() as database:
            changed = database.execute(
                f"""
                UPDATE tasks SET status='QUEUED', stage='queued', progress=0,
                    current_item=NULL, retry_of=task_id, error=NULL, accepted=NULL,
                    result_ref=NULL, worker_id=NULL, lease_token=NULL,
                    lease_expires_at=NULL, process_pid=NULL, process_create_time=NULL,
                    process_command_hash=NULL, process_group_id=NULL, process_launch_token=NULL,
                    finished_at=NULL, updated_at=?
                 WHERE task_id=? AND status IN ({placeholders})
                """,
                (now, str(task_id), *terminal_values),
            ).rowcount
        if changed != 1:
            raise ValueError("only terminal tasks can be retried")
        result = self.get(task_id)
        if result is None:
            raise KeyError(task_id)
        return result

    def retry_post_processing(self, task_id: str) -> TaskRecord:
        """Atomically requeue only the post-training stages; model training is immutable."""
        now = utc_now()
        with self._connect() as database:
            changed = database.execute(
                """
                UPDATE tasks SET status='QUEUED', stage='post_processing_queued', progress=95,
                    current_item=NULL, retry_of=task_id, error=NULL, finished_at=NULL,
                    worker_id=NULL, lease_token=NULL, lease_expires_at=NULL, updated_at=?
                 WHERE task_id=? AND status='POST_PROCESSING_FAILED' AND result_ref IS NOT NULL
                """,
                (now, str(task_id)),
            ).rowcount
        if changed != 1:
            current = self.get(task_id)
            if current is not None and current.stage in {"post_processing_queued", "post_processing"} and current.status in {
                TaskStatus.QUEUED, TaskStatus.RUNNING
            }:
                return current
            raise ValueError("only post-processing failures with preserved training artifacts can be retried")
        result = self.get(task_id)
        if result is None:
            raise KeyError(task_id)
        return result
