from __future__ import annotations

import threading
import json
import sqlite3
from datetime import datetime, timezone
from collections.abc import Mapping

from .models import TaskKind, TaskStatus
from .worker import TaskHandler, WorkerContext
from .process_control import ProcessController, ProcessIdentity


class HardwareUnavailableError(RuntimeError):
    pass


class Scheduler:
    def __init__(
        self,
        repository,
        artifacts,
        worker_id: str,
        handlers: Mapping[TaskKind, TaskHandler],
        capabilities: set[str],
        lease_seconds: int = 30,
        poll_seconds: float = 0.25,
        gpu_resources=None,
        worker_instance=None,
    ):
        self.repository = repository
        self.artifacts = artifacts
        self.worker_id = str(worker_id)
        self.handlers = dict(handlers)
        self.capabilities = set(capabilities)
        self.lease_seconds = max(3, int(lease_seconds))
        self.poll_seconds = max(0.05, float(poll_seconds))
        self.gpu_resources = gpu_resources
        self.worker_instance = worker_instance
        if self.gpu_resources is None and TaskKind.TRAINING in self.handlers:
            from ..gpu_resources import GPUResourceManager
            self.gpu_resources = GPUResourceManager(repository, artifacts)

    def _write_worker_state(self, status: str, error: Exception | None = None, failures: int = 0) -> None:
        target = self.repository.path.parent / "worker-status.json"
        value = {
            "worker_id": self.worker_id,
            "status": status,
            "database": str(self.repository.path),
            "database_diagnostic": self.repository.database_diagnostic(error),
            "consecutive_database_failures": failures,
            "error": None if error is None else f"{type(error).__name__}: {error}",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        temporary = target.with_suffix(".json.tmp")
        try:
            temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(target)
        except OSError:
            pass

    def _renew_lease(self, context: WorkerContext, stop: threading.Event) -> None:
        interval = max(1.0, self.lease_seconds / 3)
        while not stop.wait(interval):
            try:
                self.repository.heartbeat(
                    context.task.task_id,
                    context.lease.lease_token,
                )
            except (KeyError, PermissionError):
                return
            except sqlite3.Error:
                # The handler performs its own fenced heartbeat; a transient DB
                # outage must not crash this renewal thread or the whole Worker.
                continue

    def run_once(self) -> bool:
        self.repository.release_expired()
        # Reap verified training processes before GPU admission.  A stale PID is
        # never acted on because ProcessController validates birth time, command
        # fingerprint, process group and launch token first.
        page = self.repository.list(kinds=(TaskKind.TRAINING,), statuses=(TaskStatus.QUEUED,), limit=100)
        for task in page.items:
            if task.stage not in {"recovered", "cancel_recovery"} or not task.process_pid:
                continue
            identity = ProcessIdentity(task.process_pid, task.process_create_time or 0,
                                       task.process_command_hash or "", task.process_group_id,
                                       task.process_launch_token)
            try:
                controller = ProcessController()
                controller.inspect(identity)
                controller.terminate_tree(identity)
                self.artifacts.atomic_write_json(task.task_id, "process-recovery.json", {
                    "task_id": task.task_id, "pid": task.process_pid,
                    "action": "verified_process_terminated",
                    "at": datetime.now(timezone.utc).isoformat(),
                })
            except ProcessLookupError:
                pass
            except PermissionError as error:
                self.artifacts.atomic_write_json(task.task_id, "process-recovery.json", {
                    "task_id": task.task_id, "pid": task.process_pid,
                    "action": "identity_verification_failed", "error": str(error),
                    "at": datetime.now(timezone.utc).isoformat(),
                })
        if self.gpu_resources is not None:
            self.gpu_resources.refresh()
        lease = self.repository.claim_next(
            self.worker_id,
            tuple(self.handlers),
            self.capabilities,
            self.lease_seconds,
            admission=self.gpu_resources.admit if self.gpu_resources else None,
        )
        if lease is None:
            return False

        context = WorkerContext(lease.task, lease, self.repository, self.artifacts)
        handler = self.handlers[lease.task.kind]
        stop_renewal = threading.Event()
        renewal = threading.Thread(
            target=self._renew_lease,
            args=(context, stop_renewal),
            name=f"task-lease-{lease.task.task_id}",
            daemon=True,
        )
        renewal.start()
        try:
            if (lease.task.kind is TaskKind.TRAINING
                    and lease.task.stage != "cancel_recovery"
                    and not lease.task.resource_key.startswith("training:remote:")):
                assignment = self.gpu_resources.assignment(lease)
                self.artifacts.atomic_write_json(lease.task.task_id, "assignment.json", assignment)
            recovered = lease.task.attempt > 1 or bool(context.load_checkpoint())
            status, result_ref = (
                handler.recover(context) if recovered else handler.run(context)
            )
            current = self.repository.get(lease.task.task_id)
            if current is not None and current.status is TaskStatus.CANCEL_REQUESTED:
                status, result_ref = TaskStatus.CANCELLED, None
            self.repository.finish(
                lease.task.task_id,
                lease.lease_token,
                status,
                result_ref,
            )
        except InterruptedError as error:
            current = self.repository.get(lease.task.task_id)
            if current is not None and current.status is TaskStatus.CANCEL_REQUESTED:
                self.repository.finish(
                    lease.task.task_id,
                    lease.lease_token,
                    TaskStatus.CANCELLED,
                )
            else:
                self.repository.finish(
                    lease.task.task_id,
                    lease.lease_token,
                    TaskStatus.FAILED,
                    error=str(error),
                )
        except HardwareUnavailableError as error:
            self.repository.finish(
                lease.task.task_id,
                lease.lease_token,
                TaskStatus.BLOCKED_BY_HARDWARE,
                error=str(error),
            )
        except EnvironmentError as error:
            self.repository.finish(
                lease.task.task_id,
                lease.lease_token,
                TaskStatus.BLOCKED_BY_ENVIRONMENT,
                error=str(error),
            )
        except Exception as error:
            self.repository.finish(
                lease.task.task_id,
                lease.lease_token,
                TaskStatus.FAILED,
                error=f"{type(error).__name__}: {error}",
            )
        finally:
            stop_renewal.set()
            renewal.join(timeout=max(1.0, self.lease_seconds / 3 + 0.5))
        return True

    def serve_forever(self, stop: threading.Event | None = None) -> None:
        stop_event = stop or threading.Event()
        renewal_stop = threading.Event()
        renewal = None
        if self.worker_instance is not None:
            def renew_instance() -> None:
                interval = max(1.0, self.worker_instance.lease_seconds / 3)
                failures = 0
                while not renewal_stop.wait(interval):
                    try:
                        self.worker_instance.renew()
                        failures = 0
                    except PermissionError:
                        stop_event.set()
                        return
                    except sqlite3.Error as error:
                        failures += 1
                        self._write_worker_state(
                            "DATABASE_ERROR" if failures >= 3 else "DEGRADED",
                            error,
                            failures,
                        )
                        renewal_stop.wait(min(5.0, 0.25 * (2 ** min(failures, 5))))

            renewal = threading.Thread(target=renew_instance, name="worker-instance-lease", daemon=True)
            renewal.start()
        try:
            database_failures = 0
            while not stop_event.is_set():
                try:
                    if not self.run_once():
                        stop_event.wait(self.poll_seconds)
                    if database_failures:
                        database_failures = 0
                        self._write_worker_state("RUNNING")
                except sqlite3.Error as error:
                    database_failures += 1
                    self._write_worker_state(
                        "DATABASE_ERROR" if database_failures >= 3 else "DEGRADED",
                        error,
                        database_failures,
                    )
                    stop_event.wait(min(5.0, 0.25 * (2 ** min(database_failures, 5))))
        finally:
            renewal_stop.set()
            if renewal is not None:
                renewal.join(timeout=max(1.0, self.worker_instance.lease_seconds / 3 + 0.5))
            if self.worker_instance is not None:
                self.worker_instance.release()
