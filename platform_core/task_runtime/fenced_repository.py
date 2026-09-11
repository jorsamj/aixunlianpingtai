from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .models import TaskStatus, utc_now
from .process_control import (
    ProcessController,
    ProcessIdentity,
    ProcessIdentityMismatchError,
)
from .repository import TERMINAL_STATUSES, TaskRepository, _from_row, _iso


class FencedTaskRepository(TaskRepository):
    """Production task repository with lease-expiry and generation fencing.

    ``tasks.attempt`` is the persisted execution generation. Every successful
    claim increments it, so an older Worker can never mutate a newer execution
    even if it still has a stale lease token in memory.
    """

    @staticmethod
    def _generation_clause(execution_generation: int | None) -> tuple[str, tuple[object, ...]]:
        if execution_generation is None:
            return "", ()
        return " AND attempt=?", (int(execution_generation),)

    def assert_execution(
        self,
        task_id: str,
        lease_token: str,
        execution_generation: int,
    ):
        now = utc_now()
        with self._connect() as database:
            row = database.execute(
                """
                SELECT * FROM tasks
                 WHERE task_id=? AND lease_token=? AND attempt=?
                   AND status IN ('RUNNING','CANCEL_REQUESTED')
                   AND lease_expires_at IS NOT NULL AND lease_expires_at>?
                """,
                (str(task_id), str(lease_token), int(execution_generation), now),
            ).fetchone()
        if row is None:
            raise PermissionError("task execution is fenced")
        return _from_row(row)

    def heartbeat(
        self,
        task_id: str,
        lease_token: str,
        progress=None,
        stage=None,
        current_item=None,
        *,
        execution_generation: int | None = None,
        lease_seconds: int = 30,
    ):
        now = datetime.now(timezone.utc)
        now_text = now.isoformat()
        expires_at = (now + timedelta(seconds=max(1, int(lease_seconds)))).isoformat()
        updates = ["updated_at=?", "lease_expires_at=?"]
        parameters: list[object] = [now_text, expires_at]
        if progress is not None:
            updates.append("progress=?")
            parameters.append(max(0.0, min(100.0, float(progress))))
        if stage is not None:
            updates.append("stage=?")
            parameters.append(str(stage))
        if current_item is not None:
            updates.append("current_item=?")
            parameters.append(str(current_item))
        generation_sql, generation_parameters = self._generation_clause(execution_generation)
        parameters.extend([str(task_id), str(lease_token), now_text, *generation_parameters])
        with self._connect() as database:
            changed = database.execute(
                f"UPDATE tasks SET {','.join(updates)} "
                "WHERE task_id=? AND lease_token=? "
                "AND status IN ('RUNNING','CANCEL_REQUESTED') "
                "AND lease_expires_at IS NOT NULL AND lease_expires_at>?"
                f"{generation_sql}",
                parameters,
            ).rowcount
        if changed != 1:
            raise PermissionError("task execution does not own heartbeat")
        result = self.get(task_id)
        if result is None:
            raise KeyError(task_id)
        return result

    def bind_process(
        self,
        task_id: str,
        lease_token: str,
        identity: ProcessIdentity,
        *,
        execution_generation: int | None = None,
    ):
        now = utc_now()
        generation_sql, generation_parameters = self._generation_clause(execution_generation)
        with self._connect() as database:
            changed = database.execute(
                """
                UPDATE tasks SET process_pid=?, process_create_time=?,
                    process_command_hash=?, updated_at=?
                 WHERE task_id=? AND lease_token=?
                   AND status IN ('RUNNING','CANCEL_REQUESTED')
                   AND lease_expires_at IS NOT NULL AND lease_expires_at>?
                """ + generation_sql,
                (
                    int(identity.pid),
                    float(identity.create_time),
                    str(identity.command_hash),
                    now,
                    str(task_id),
                    str(lease_token),
                    now,
                    *generation_parameters,
                ),
            ).rowcount
        if changed != 1:
            raise PermissionError("task execution does not own process identity")
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
        *,
        execution_generation: int | None = None,
    ):
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
        generation_sql, generation_parameters = self._generation_clause(execution_generation)
        with self._connect() as database:
            changed = database.execute(
                """
                UPDATE tasks SET status=?, result_ref=?, error=?, accepted=?, stage=?,
                    progress=COALESCE(?, progress), finished_at=?, updated_at=?,
                    worker_id=NULL, lease_token=NULL, lease_expires_at=NULL
                 WHERE task_id=? AND lease_token=?
                   AND status IN ('RUNNING','CANCEL_REQUESTED')
                   AND lease_expires_at IS NOT NULL AND lease_expires_at>?
                """ + generation_sql,
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
                    now,
                    *generation_parameters,
                ),
            ).rowcount
        if changed != 1:
            raise PermissionError("task execution does not own finish")
        result = self.get(task_id)
        if result is None:
            raise KeyError(task_id)
        return result

    @staticmethod
    def _identity_from_row(row) -> ProcessIdentity | None:
        if (
            row["process_pid"] is None
            or row["process_create_time"] is None
            or not str(row["process_command_hash"] or "").strip()
        ):
            return None
        return ProcessIdentity(
            int(row["process_pid"]),
            float(row["process_create_time"]),
            str(row["process_command_hash"]),
        )

    def _process_recovery_state(self, row) -> str:
        identity = self._identity_from_row(row)
        if identity is None:
            return "gone"
        try:
            ProcessController().inspect(identity)
        except ProcessIdentityMismatchError:
            # The persisted PID was reused or the command changed. The exact
            # process this task owned no longer exists; never signal the new PID.
            return "gone"
        except ProcessLookupError:
            return "gone"
        except PermissionError:
            return "unknown"
        return "alive"

    def _release_expired_in(self, database, now: str) -> int:
        rows = database.execute(
            """
            SELECT * FROM tasks
             WHERE status IN ('RUNNING','CANCEL_REQUESTED')
               AND lease_expires_at IS NOT NULL AND lease_expires_at<=?
             ORDER BY updated_at, task_id
            """,
            (now,),
        ).fetchall()
        released = 0
        for row in rows:
            process_state = self._process_recovery_state(row)
            if process_state == "alive":
                database.execute(
                    "UPDATE tasks SET stage='lease_expired_process_alive', updated_at=? WHERE task_id=?",
                    (now, row["task_id"]),
                )
                continue
            if process_state == "unknown":
                database.execute(
                    "UPDATE tasks SET stage='recovery_blocked_process_inspection', updated_at=? WHERE task_id=?",
                    (now, row["task_id"]),
                )
                continue
            status = str(row["status"])
            kind = str(row["kind"])
            accepted = row["accepted"]
            next_status = "CANCELLED" if status == "CANCEL_REQUESTED" else "QUEUED"
            if status == "CANCEL_REQUESTED":
                stage = "cancelled"
                finished_at = now
            elif kind == "MATERIAL_IMPORT" and accepted == 1 and str(row["stage"]) in {
                "indexing",
                "lease_expired_process_alive",
                "recovery_blocked_process_inspection",
            }:
                stage = "indexing_queued"
                finished_at = row["finished_at"]
            else:
                stage = "recovered"
                finished_at = row["finished_at"]
            database.execute(
                """
                UPDATE tasks SET status=?, stage=?, finished_at=?, worker_id=NULL,
                    lease_token=NULL, lease_expires_at=NULL,
                    process_pid=NULL, process_create_time=NULL, process_command_hash=NULL,
                    updated_at=?
                 WHERE task_id=? AND status IN ('RUNNING','CANCEL_REQUESTED')
                   AND lease_expires_at IS NOT NULL AND lease_expires_at<=?
                """,
                (next_status, stage, finished_at, now, row["task_id"], now),
            )
            released += 1
        database.execute("DELETE FROM gpu_reservations WHERE expires_at<=?", (now,))
        return released

    def reap_expired_processes(self, now=None, *, timeout: float = 5.0) -> int:
        """Terminate exact child process trees for expired executions.

        This runs outside the SQLite claim transaction. PID reuse is fenced by
        create_time + command hash; an unrelated process is never terminated.
        Access-denied inspection fails closed and leaves the task unrecoverable
        until an operator or a later Worker can prove process identity.
        """
        now_text = _iso(now)
        with self._connect() as database:
            rows = database.execute(
                """
                SELECT * FROM tasks
                 WHERE status IN ('RUNNING','CANCEL_REQUESTED')
                   AND lease_expires_at IS NOT NULL AND lease_expires_at<=?
                   AND process_pid IS NOT NULL
                   AND process_create_time IS NOT NULL
                   AND process_command_hash IS NOT NULL
                """,
                (now_text,),
            ).fetchall()
        controller = ProcessController()
        reaped = 0
        for row in rows:
            identity = self._identity_from_row(row)
            if identity is None:
                continue
            try:
                controller.terminate_tree(identity, timeout=timeout)
            except ProcessIdentityMismatchError:
                # PID reuse / changed command proves the exact owned process is gone.
                continue
            except ProcessLookupError:
                continue
            except PermissionError:
                continue
            reaped += 1
        return reaped
