from __future__ import annotations

from contextlib import closing, contextmanager
import json
from contextvars import ContextVar

from datetime import datetime, timedelta, timezone
from typing import Iterable

from .models import TaskKind, TaskStatus, utc_now
from .process_control import (
    ProcessController,
    ProcessIdentity,
    ProcessIdentityMismatchError,
)
from .repository import TERMINAL_STATUSES, TaskRepository, _from_row, _iso, admission_preparer
from .sqlite_busy import retry_busy

_PROCESS_OBSERVATIONS = ContextVar("task_expired_process_observations", default={})


_RECOVERY_HOLD_STAGES = (
    "lease_expired_process_alive",
    "recovery_blocked_process_inspection",
    "recovery_blocked_remote_agent_unverified",
)


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

    def claim_next(
        self,
        worker_id: str,
        kinds: Iterable[TaskKind | str],
        capabilities: Iterable[str],
        lease_seconds: int = 30,
        admission=None,
        *, candidate_budget=256,
    ):
        caller_admission = admission

        def fenced_admission(database, candidate, owner, token, expires_at, now):
            held = database.execute(
                """
                SELECT task_id FROM tasks
                 WHERE task_id<>? AND resource_key=?
                   AND status IN ('RUNNING','CANCEL_REQUESTED')
                   AND stage IN (?,?,?)
                 LIMIT 1
                """,
                (
                    candidate["task_id"],
                    candidate["resource_key"],
                    *_RECOVERY_HOLD_STAGES,
                ),
            ).fetchone()
            if held is not None:
                return False, (
                    "RESOURCE_RECOVERY_FENCE: expired execution still owns "
                    f"resource via task {held['task_id']}"
                )

            # Passing an admission callback makes the legacy claim SQL delegate
            # local TRAINING resource arbitration. If no caller supplied a GPU
            # admission policy, preserve the original single-resource behavior.
            if (
                caller_admission is None
                and str(candidate["kind"]) == TaskKind.TRAINING.value
                and not str(candidate["resource_key"]).startswith("training:remote:")
            ):
                active = database.execute(
                    """
                    SELECT task_id FROM tasks
                     WHERE task_id<>? AND resource_key=?
                       AND status IN ('RUNNING','CANCEL_REQUESTED')
                       AND lease_expires_at>?
                     LIMIT 1
                    """,
                    (candidate["task_id"], candidate["resource_key"], now),
                ).fetchone()
                if active is not None:
                    return False, f"RESOURCE_BUSY: owned by task {active['task_id']}"

            if caller_admission is None:
                return True, None
            return caller_admission(database, candidate, owner, token, expires_at, now)

        fenced_admission.prepare = admission_preparer(caller_admission)
        token = _PROCESS_OBSERVATIONS.set(self._inspect_expired_processes(_iso()))
        try:
            return super().claim_next(worker_id, kinds, capabilities, lease_seconds, admission=fenced_admission,candidate_budget=candidate_budget)
        finally:
            _PROCESS_OBSERVATIONS.reset(token)

    def assert_execution(
        self,
        task_id: str,
        lease_token: str,
        execution_generation: int,
    ):
        now = utc_now()
        with closing(self._connect()) as database:
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

    @staticmethod
    def _formal_bulk_owner(database, lease, execution_generation):
        now = utc_now()
        row = database.execute(
            """SELECT tasks.status, tasks.project_id, tasks.payload_ref,
                      COALESCE(formal_bulk_execution.cancel_requested, 0) AS cancel_requested,
                      formal_bulk_execution.active_batch
                 FROM tasks LEFT JOIN formal_bulk_execution USING (task_id)
                WHERE task_id=? AND kind='ANNOTATION_FORMAL_BULK'
                  AND attempt=? AND lease_token=? AND worker_id=?
                  AND status IN ('RUNNING','CANCEL_REQUESTED') AND lease_expires_at>?
                  AND worker_id NOT LIKE 'agent:%' AND process_pid IS NULL""",
            (lease.task.task_id, execution_generation, lease.lease_token, lease.worker_id, now),
        ).fetchone()
        if (lease.task.kind is not TaskKind.ANNOTATION_FORMAL_BULK
                or lease.task.attempt != execution_generation or row is None
                or row["project_id"] != lease.task.project_id or row["payload_ref"] != lease.task.payload_ref):
            raise PermissionError("formal bulk execution no longer owns its task")
        return row

    @contextmanager
    def formal_bulk_gt_write(self, lease, execution_generation, batch):
        task_id = lease.task.task_id
        with self._formal_bulk_lock(task_id):
            with closing(self._connect()) as database:
                # Drain any expiring worker's transaction before checking the
                # row. Reapers may release the file lock before SQLite COMMIT.
                database.execute("BEGIN IMMEDIATE")
                row = self._formal_bulk_owner(database, lease, execution_generation)
                if row["cancel_requested"] or row["status"] != "RUNNING":
                    raise InterruptedError("formal bulk execution was cancelled")
                if (batch["identity"]["project_id"] != row["project_id"]
                        or batch.get("binding_ref", batch["manifest_ref"]) != row["payload_ref"]):
                    raise PermissionError("formal bulk project or manifest identity mismatch")
                if row["active_batch"]:
                    active = json.loads(row["active_batch"])
                    if any(active[key] != batch[key] for key in ("identity", "operation_id", "manifest_ref")):
                        raise PermissionError("formal bulk batch changed operation identity")
                    if batch["batch_number"] not in (active["batch_number"], active["batch_number"] + 1):
                        raise PermissionError("formal bulk batch ordering mismatch")
                elif batch["batch_number"] != 0:
                    raise PermissionError("formal bulk execution must start at batch zero")
                database.execute(
                    """INSERT INTO formal_bulk_execution(task_id,active_batch) VALUES (?,?)
                       ON CONFLICT(task_id) DO UPDATE SET active_batch=excluded.active_batch""",
                    (task_id, json.dumps(batch, sort_keys=True)),
                )
                database.commit()
            # Keep only this task's cross-process lock through the GT commit.
            yield

    def formal_bulk_cancel_state(self, lease, execution_generation):
        with closing(self._connect()) as database:
            row = self._formal_bulk_owner(database, lease, execution_generation)
            return bool(row["cancel_requested"]), row["active_batch"]

    def _finish_reconciled_formal_bulk_cancel(self, lease, execution_generation, active_batch, evidence):
        task_id = lease.task.task_id
        with self._formal_bulk_lock(task_id), closing(self._connect()) as database:
            database.execute("BEGIN IMMEDIATE")
            row = self._formal_bulk_owner(database, lease, execution_generation)
            if not row["cancel_requested"] or row["active_batch"] != active_batch:
                raise PermissionError("formal bulk cancellation reconciliation became stale")
            database.execute(
                "UPDATE formal_bulk_execution SET reconciliation=? WHERE task_id=?",
                (json.dumps(evidence, sort_keys=True), task_id),
            )
            now = utc_now()
            total = int(evidence.get("total_images") or 0)
            committed = evidence.get("committed_images")
            progress = (100.0 * committed / total) if total and type(committed) is int else None
            database.execute(
                """UPDATE tasks SET status='CANCELLED', stage='cancelled', finished_at=?, updated_at=?,
                       progress=COALESCE(?, progress),
                       worker_id=NULL, lease_token=NULL, lease_expires_at=NULL WHERE task_id=?""",
                (now, now, progress, task_id),
            )
            database.commit()

    def publish_formal_bulk_progress(self, lease, execution_generation, active_batch, evidence, *, status=None):
        if status not in {None, TaskStatus.SUCCEEDED, TaskStatus.PARTIAL_SUCCESS, TaskStatus.FAILED,
                          TaskStatus.CANCELLED}:
            raise ValueError("invalid formal bulk execution status")
        task_id = lease.task.task_id
        with self._formal_bulk_lock(task_id), closing(self._connect()) as database:
            database.execute("BEGIN IMMEDIATE")
            row = self._formal_bulk_owner(database, lease, execution_generation)
            if row["active_batch"] != active_batch:
                raise PermissionError("formal bulk progress became stale")
            if status is not None and bool(row["cancel_requested"]) != (status is TaskStatus.CANCELLED):
                raise InterruptedError("formal bulk cancellation changed before finish")
            database.execute(
                """INSERT INTO formal_bulk_execution(task_id, reconciliation) VALUES (?,?)
                   ON CONFLICT(task_id) DO UPDATE SET reconciliation=excluded.reconciliation""",
                (task_id, json.dumps(evidence, sort_keys=True)),
            )
            if status is not None:
                now = utc_now()
                total = int(evidence.get("total_images") or 0)
                committed = evidence.get("committed_images")
                ratio = (100.0 * committed / total) if total and type(committed) is int else None
                progress = 100.0 if status is TaskStatus.SUCCEEDED else ratio
                database.execute(
                    """UPDATE tasks SET status=?, stage=?, error=?, finished_at=?, updated_at=?,
                              progress=COALESCE(?, progress),
                              worker_id=NULL, lease_token=NULL, lease_expires_at=NULL WHERE task_id=?""",
                    (status.value, status.value.lower(), evidence.get("last_error_message"), now, now,
                     progress, task_id),
                )
            database.commit()

    def resume_blocked_formal_bulk(self, task_id: str, expected_attempt: int) -> None:
        """Release a durable evidence block after an operator re-verified facts.

        This never publishes SUCCEEDED and never writes GT. It only moves the
        task back to QUEUED so the normal Worker re-audits the same operation.
        """
        task_id = str(task_id)
        with self._formal_bulk_lock(task_id), closing(self._connect()) as database:
            database.execute("BEGIN IMMEDIATE")
            row = database.execute(
                "SELECT kind, status, stage, attempt FROM tasks WHERE task_id=?", (task_id,),
            ).fetchone()
            if row is None or str(row["kind"]) != TaskKind.ANNOTATION_FORMAL_BULK.value:
                raise KeyError(task_id)
            if (str(row["status"]) != "RUNNING"
                    or int(row["attempt"]) != int(expected_attempt)
                    or str(row["stage"]) not in {"formal_bulk_blocked", "formal_bulk_attempt_limit"}):
                raise PermissionError("formal bulk task is not in a recoverable blocked state")
            ledger = database.execute(
                "SELECT reconciliation FROM formal_bulk_execution WHERE task_id=?", (task_id,),
            ).fetchone()
            evidence = json.loads(ledger["reconciliation"] or "{}") if ledger is not None else {}
            if evidence.get("state") != "blocked":
                raise PermissionError("formal bulk block marker is missing")
            evidence.update(state="resumed", resumed_at=utc_now())
            now = utc_now()
            database.execute(
                "UPDATE formal_bulk_execution SET reconciliation=? WHERE task_id=?",
                (json.dumps(evidence, sort_keys=True), task_id),
            )
            database.execute(
                """UPDATE tasks SET status='QUEUED', stage='recovery_queued',
                          worker_id=NULL, lease_token=NULL, lease_expires_at=NULL,
                          process_pid=NULL, process_create_time=NULL, process_command_hash=NULL,
                          updated_at=?
                    WHERE task_id=? AND status='RUNNING' AND attempt=?""",
                (now, task_id, int(expected_attempt)),
            )
            database.commit()

    @retry_busy
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
            updates.append("progress=MAX(progress, ?)")
            parameters.append(max(0.0, min(100.0, float(progress))))
        if stage is not None:
            stage_value = str(stage)
            updates.append(
                "stage=CASE WHEN stage IN ('paused','cancelling') AND stage<>? "
                "THEN stage ELSE ? END"
            )
            parameters.extend([stage_value, stage_value])
        if current_item is not None:
            updates.append("current_item=?")
            parameters.append(str(current_item))
        generation_sql, generation_parameters = self._generation_clause(execution_generation)
        parameters.extend([str(task_id), str(lease_token), now_text, *generation_parameters])
        with closing(self._connect()) as database:
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
        with closing(self._connect()) as database:
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
        with closing(self._connect()) as database:
            changed = database.execute(
                """
                UPDATE tasks SET status=?, result_ref=?, error=?, accepted=?, stage=?,
                    progress=CASE
                        WHEN ?='AWAITING_CONFIRMATION' AND kind='MATERIAL_IMPORT'
                            THEN MAX(progress, 50.0)
                        ELSE COALESCE(?, progress)
                    END,
                    finished_at=?, updated_at=?,
                    worker_id=NULL, lease_token=NULL, lease_expires_at=NULL
                 WHERE task_id=? AND lease_token=?
                   AND status IN ('RUNNING','CANCEL_REQUESTED')
                   AND kind<>'ANNOTATION_FORMAL_BULK'
                   AND lease_expires_at IS NOT NULL AND lease_expires_at>?
                """ + generation_sql,
                (
                    status.value,
                    result_ref,
                    error,
                    None if accepted is None else int(accepted),
                    stage,
                    status.value,
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

    @staticmethod
    def _hold_gpu_reservation(database, task_id: str, now: str) -> None:
        try:
            now_dt = datetime.fromisoformat(str(now))
        except ValueError:
            now_dt = datetime.now(timezone.utc)
        if now_dt.tzinfo is None:
            now_dt = now_dt.replace(tzinfo=timezone.utc)
        hold_until = (now_dt.astimezone(timezone.utc) + timedelta(seconds=30)).isoformat()
        database.execute(
            """
            UPDATE gpu_reservations
               SET policy='exclusive', share_eligible=0, sharing_evidence_at=NULL,
                   heartbeat_at=?, expires_at=?
             WHERE task_id=?
            """,
            (now, hold_until, str(task_id)),
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

    @staticmethod
    def _process_observation_key(row):
        return tuple(row[key] for key in ("task_id", "attempt", "lease_token", "lease_expires_at",
                     "process_pid", "process_create_time", "process_command_hash"))

    def _inspect_expired_processes(self, now):
        with closing(self._connect()) as database:
            rows = database.execute("SELECT * FROM tasks WHERE status IN ('RUNNING','CANCEL_REQUESTED') AND lease_expires_at<=?", (now,)).fetchall()
        return {self._process_observation_key(row): self._process_recovery_state(row) for row in rows}

    @retry_busy
    def release_expired(self, now=None):
        now_text = _iso(now)
        token = _PROCESS_OBSERVATIONS.set(self._inspect_expired_processes(now_text))
        try:
            return super().release_expired(now_text)
        finally:
            _PROCESS_OBSERVATIONS.reset(token)

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
            if str(row["worker_id"] or "").startswith("agent:"):
                # A remote Agent may have lost its control-plane connection
                # while its OS process continues to use the GPU. Unlike a
                # local PID, central SQLite cannot prove remote process death.
                # Never requeue (or finalize a cancellation) on TTL alone.
                if str(row["stage"] or "") != "recovery_blocked_remote_agent_unverified":
                    database.execute(
                        """UPDATE tasks
                              SET stage='recovery_blocked_remote_agent_unverified',
                                  resource_wait_reason='REMOTE_AGENT_STOP_UNVERIFIED: remote execution may still be running',
                                  updated_at=?
                            WHERE task_id=? AND status IN ('RUNNING','CANCEL_REQUESTED')""",
                        (now, row["task_id"]),
                    )
                self._hold_gpu_reservation(database, row["task_id"], now)
                continue
            process_state = ("gone" if self._identity_from_row(row) is None else
                             _PROCESS_OBSERVATIONS.get().get(self._process_observation_key(row), "unknown"))
            if process_state == "alive":
                database.execute(
                    "UPDATE tasks SET stage='lease_expired_process_alive', updated_at=? WHERE task_id=?",
                    (now, row["task_id"]),
                )
                self._hold_gpu_reservation(database, row["task_id"], now)
                continue
            if process_state == "unknown":
                database.execute(
                    "UPDATE tasks SET stage='recovery_blocked_process_inspection', updated_at=? WHERE task_id=?",
                    (now, row["task_id"]),
                )
                self._hold_gpu_reservation(database, row["task_id"], now)
                continue
            status = str(row["status"])
            kind = str(row["kind"])
            if kind == TaskKind.ANNOTATION_FORMAL_BULK.value:
                released += self._requeue_expired_formal_bulk(database, row, now)
                continue
            accepted = row["accepted"]
            next_status = "CANCELLED" if status == "CANCEL_REQUESTED" else "QUEUED"
            if status == "CANCEL_REQUESTED":
                stage = "cancelled"
                finished_at = now
            elif kind == "MATERIAL_IMPORT" and accepted == 1 and str(row["stage"]) in {
                "indexing",
                *_RECOVERY_HOLD_STAGES,
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
        # An expired lease with a still-live/uninspectable process remains an
        # active resource owner. Keep its GPU reservation so another task cannot
        # be admitted onto the same memory while the orphan may still execute.
        database.execute(
            """
            DELETE FROM gpu_reservations
             WHERE expires_at<=?
               AND task_id NOT IN (
                    SELECT task_id FROM tasks
                     WHERE status IN ('RUNNING','CANCEL_REQUESTED')
                       AND stage IN (?,?,?)
               )
            """,
            (now, *_RECOVERY_HOLD_STAGES),
        )
        return released

    def reap_expired_processes(self, now=None, *, timeout: float = 5.0) -> int:
        """Terminate exact child process trees for expired executions.

        This runs outside the SQLite claim transaction. PID reuse is fenced by
        create_time + command hash; an unrelated process is never terminated.
        Access-denied inspection fails closed and leaves the task unrecoverable
        until an operator or a later Worker can prove process identity.
        """
        now_text = _iso(now)
        with closing(self._connect()) as database:
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
