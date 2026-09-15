from __future__ import annotations

import threading
from collections.abc import Mapping

from .models import TaskKind, TaskStatus
from .worker import ExecutionFencedError, TaskHandler, WorkerContext


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
                context.heartbeat()
            except ExecutionFencedError:
                context.terminate_bound_process()
                return
            except Exception:
                # If the Worker cannot prove that its lease was renewed (for
                # example because the local task DB became unavailable), fail
                # closed. Continuing a child process would reopen split-brain
                # execution once another Worker can recover the expired task.
                context.mark_lease_lost()
                context.terminate_bound_process()
                return

    def _reap_before_claim(self) -> None:
        reaper = getattr(self.repository, "reap_expired_processes", None)
        if callable(reaper):
            reaper()
        self.repository.release_expired()

    @staticmethod
    def _finish_if_owned(
        context: WorkerContext,
        status: TaskStatus,
        result_ref: str | None = None,
        *,
        error: str | None = None,
    ) -> None:
        try:
            context.finish(status, result_ref, error=error)
        except ExecutionFencedError:
            context.terminate_bound_process()

    @classmethod
    def _finish_cancel_if_safe(
        cls,
        context: WorkerContext,
        current=None,
    ) -> bool:
        try:
            observed = current or context.assert_current_execution()
        except ExecutionFencedError:
            context.terminate_bound_process()
            return False
        if observed is None or observed.status is not TaskStatus.CANCEL_REQUESTED:
            return False
        if not cls._cleanup_bound_process_if_needed(
            context,
            observed,
            stage="cancelling",
            current_item="正在确认训练进程已安全停止",
        ):
            return False
        cls._finish_if_owned(context, TaskStatus.CANCELLED)
        return True

    @staticmethod
    def _has_bound_process(observed) -> bool:
        return (
            observed.process_pid is not None
            and observed.process_create_time is not None
            and bool(str(observed.process_command_hash or "").strip())
        )

    @classmethod
    def _cleanup_bound_process_if_needed(
        cls,
        context: WorkerContext,
        observed,
        *,
        stage: str,
        current_item: str,
    ) -> bool:
        if cls._has_bound_process(observed) and not context.terminate_bound_process():
            # Keep status, lease and GPU reservation intact. Lease recovery will
            # continue exact process cleanup; publishing any terminal state here
            # could admit the next GPU task while the previous process is alive.
            try:
                context.heartbeat(
                    stage=stage,
                    current_item=current_item,
                )
            except ExecutionFencedError:
                pass
            return False
        return True

    @classmethod
    def _finish_error_or_cancel(
        cls,
        context: WorkerContext,
        status: TaskStatus,
        error: Exception,
    ) -> None:
        try:
            current = context.assert_current_execution()
        except ExecutionFencedError:
            context.terminate_bound_process()
            return
        if current is not None and current.status is TaskStatus.CANCEL_REQUESTED:
            cls._finish_cancel_if_safe(context, current)
            return
        if current is not None and not cls._cleanup_bound_process_if_needed(
            context,
            current,
            stage="process_cleanup_blocked",
            current_item=f"任务异常，正在确认训练进程已安全停止：{type(error).__name__}: {error}",
        ):
            return
        cls._finish_if_owned(context, status, error=f"{type(error).__name__}: {error}")

    def run_once(self) -> bool:
        self._reap_before_claim()
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

        context = WorkerContext(
            lease.task,
            lease,
            self.repository,
            self.artifacts,
            lease_seconds=self.lease_seconds,
        )
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
                context.artifacts.atomic_write_json(lease.task.task_id, "assignment.json", assignment)
            recovered = lease.task.attempt > 1 or bool(context.load_checkpoint())
            status, result_ref = (
                handler.recover(context) if recovered else handler.run(context)
            )
            current = context.assert_current_execution()
            if current is not None and current.status is TaskStatus.CANCEL_REQUESTED:
                self._finish_cancel_if_safe(context, current)
            else:
                context.finish(status, result_ref)
        except ExecutionFencedError:
            # Never let a stale generation publish FAILED/SUCCEEDED over the
            # execution that replaced it. Bound child processes are terminated
            # by exact PID/create_time/command-hash identity.
            context.terminate_bound_process()
        except InterruptedError as error:
            if context.lease_lost:
                context.terminate_bound_process()
            else:
                try:
                    current = context.assert_current_execution()
                except ExecutionFencedError:
                    context.terminate_bound_process()
                else:
                    if current is not None and current.status is TaskStatus.CANCEL_REQUESTED:
                        self._finish_cancel_if_safe(context, current)
                    else:
                        self._finish_error_or_cancel(context, TaskStatus.FAILED, error)
        except HardwareUnavailableError as error:
            self._finish_error_or_cancel(context, TaskStatus.BLOCKED_BY_HARDWARE, error)
        except EnvironmentError as error:
            self._finish_error_or_cancel(context, TaskStatus.BLOCKED_BY_ENVIRONMENT, error)
        except Exception as error:
            self._finish_error_or_cancel(context, TaskStatus.FAILED, error)
        finally:
            stop_renewal.set()
            renewal.join(timeout=max(1.0, self.lease_seconds / 3 + 0.5))
            if context.lease_lost:
                context.terminate_bound_process()
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
                    if self.gpu_resources is not None:
                        try:
                            self.gpu_resources.refresh()
                        except Exception:
                            # GPU telemetry failure must not silently end the
                            # Worker heartbeat. The next cycle retries; stale
                            # sampled_at remains visible through runtime truth.
                            continue

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
