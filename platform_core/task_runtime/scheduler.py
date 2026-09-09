from __future__ import annotations

import threading
from collections.abc import Mapping

from .models import TaskKind, TaskStatus
from .worker import TaskHandler, WorkerContext


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

    def run_once(self) -> bool:
        self.repository.release_expired()
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
            if lease.task.kind is TaskKind.TRAINING and not lease.task.resource_key.startswith("training:remote:"):
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
                while not renewal_stop.wait(interval):
                    try:
                        self.worker_instance.renew()
                    except PermissionError:
                        stop_event.set()
                        return

            renewal = threading.Thread(target=renew_instance, name="worker-instance-lease", daemon=True)
            renewal.start()
        try:
            while not stop_event.is_set():
                if not self.run_once():
                    stop_event.wait(self.poll_seconds)
        finally:
            renewal_stop.set()
            if renewal is not None:
                renewal.join(timeout=max(1.0, self.worker_instance.lease_seconds / 3 + 0.5))
            if self.worker_instance is not None:
                self.worker_instance.release()
