from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Protocol

from .artifacts import ArtifactStore
from .models import TaskLease, TaskRecord, TaskStatus
from .process_control import ProcessController, ProcessIdentity


class ExecutionFencedError(RuntimeError):
    """Raised when this Worker no longer owns the current task execution."""


class RepositoryPort(Protocol):
    def get(self, task_id: str) -> TaskRecord | None: ...

    def heartbeat(
        self,
        task_id: str,
        lease_token: str,
        progress=None,
        stage=None,
        current_item=None,
        **kwargs,
    ) -> TaskRecord: ...


class FencedArtifactStore:
    """ArtifactStore view that refuses stale execution reads and writes."""

    def __init__(self, context: "WorkerContext", store: ArtifactStore):
        self._context = context
        self._store = store

    @property
    def root(self):
        return self._store.root

    def artifact_path(self, task_id: str, relative_path: str):
        self._context.assert_current_execution()
        return self._store.artifact_path(task_id, relative_path)

    def atomic_write_json(self, task_id: str, relative_path: str, value: Any) -> None:
        self._context.assert_current_execution()
        self._store.atomic_write_json(task_id, relative_path, value)

    def read_json(self, task_id: str, relative_path: str, default: Any = None) -> Any:
        self._context.assert_current_execution()
        return self._store.read_json(task_id, relative_path, default=default)

    def append_log(self, task_id: str, relative_path: str, text: str) -> None:
        self._context.assert_current_execution()
        self._store.append_log(task_id, relative_path, text)


@dataclass
class WorkerContext:
    task: TaskRecord
    lease: TaskLease
    repository: RepositoryPort
    artifacts: ArtifactStore
    lease_seconds: int = 30
    _lease_lost: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _cancel_event: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _process_identity: ProcessIdentity | None = field(default=None, init=False, repr=False)
    _process_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _artifact_store: ArtifactStore = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.lease_seconds = max(1, int(self.lease_seconds))
        self._artifact_store = self.artifacts
        self.artifacts = FencedArtifactStore(self, self._artifact_store)  # type: ignore[assignment]

    @property
    def execution_generation(self) -> int:
        # Claim already increments tasks.attempt. Reuse that persisted monotonic
        # value as the execution generation rather than maintaining two counters.
        return int(self.lease.task.attempt)

    @property
    def lease_lost(self) -> bool:
        return self._lease_lost.is_set()

    def mark_lease_lost(self) -> None:
        self._lease_lost.set()

    def assert_current_execution(self) -> TaskRecord | None:
        if self._lease_lost.is_set():
            raise ExecutionFencedError("task execution lease was lost")
        validator = getattr(self.repository, "assert_execution", None)
        if callable(validator):
            try:
                return validator(
                    self.task.task_id,
                    self.lease.lease_token,
                    self.execution_generation,
                )
            except (KeyError, PermissionError) as error:
                self.mark_lease_lost()
                raise ExecutionFencedError("task execution is fenced") from error
        current = self.repository.get(self.task.task_id)
        if current is None or current.status not in {TaskStatus.RUNNING, TaskStatus.CANCEL_REQUESTED}:
            self.mark_lease_lost()
            raise ExecutionFencedError("task execution is no longer active")
        return current

    def heartbeat(self, progress=None, stage=None, current_item=None) -> TaskRecord:
        self.assert_current_execution()
        try:
            try:
                return self.repository.heartbeat(
                    self.task.task_id,
                    self.lease.lease_token,
                    progress=progress,
                    stage=stage,
                    current_item=current_item,
                    execution_generation=self.execution_generation,
                    lease_seconds=self.lease_seconds,
                )
            except TypeError as error:
                # Compatibility for the legacy TaskRepository used by old tests
                # and read-only callers. Production task_worker uses the fenced
                # repository and therefore takes the branch above.
                if "unexpected keyword" not in str(error):
                    raise
                return self.repository.heartbeat(
                    self.task.task_id,
                    self.lease.lease_token,
                    progress=progress,
                    stage=stage,
                    current_item=current_item,
                )
        except (KeyError, PermissionError) as error:
            self.mark_lease_lost()
            raise ExecutionFencedError("task heartbeat lost execution ownership") from error

    def finish(
        self,
        status: TaskStatus,
        result_ref: str | None = None,
        *,
        error: str | None = None,
        accepted: bool | None = None,
    ) -> TaskRecord:
        self.assert_current_execution()
        finisher = getattr(self.repository, "finish")
        try:
            try:
                return finisher(
                    self.task.task_id,
                    self.lease.lease_token,
                    status,
                    result_ref,
                    error,
                    accepted,
                    execution_generation=self.execution_generation,
                )
            except TypeError as type_error:
                if "unexpected keyword" not in str(type_error):
                    raise
                return finisher(
                    self.task.task_id,
                    self.lease.lease_token,
                    status,
                    result_ref,
                    error,
                    accepted,
                )
        except (KeyError, PermissionError) as execution_error:
            self.mark_lease_lost()
            raise ExecutionFencedError("task finish lost execution ownership") from execution_error

    def bind_process(self, identity: ProcessIdentity) -> TaskRecord:
        self.assert_current_execution()
        binder = getattr(self.repository, "bind_process")
        try:
            try:
                result = binder(
                    self.task.task_id,
                    self.lease.lease_token,
                    identity,
                    execution_generation=self.execution_generation,
                )
            except TypeError as type_error:
                if "unexpected keyword" not in str(type_error):
                    raise
                result = binder(self.task.task_id, self.lease.lease_token, identity)
        except (KeyError, PermissionError) as execution_error:
            self.mark_lease_lost()
            raise ExecutionFencedError("process binding lost execution ownership") from execution_error
        with self._process_lock:
            self._process_identity = identity
        return result

    def terminate_bound_process(self, timeout: float = 5.0) -> bool:
        with self._process_lock:
            identity = self._process_identity
        if identity is None:
            return False
        try:
            ProcessController().terminate_tree(identity, timeout=timeout)
        except (ProcessLookupError, PermissionError):
            # PermissionError also covers identity mismatch. Fail closed rather
            # than ever signalling a PID that cannot be proven to be ours.
            return False
        return True

    def cancel_requested(self) -> bool:
        current = self.assert_current_execution()
        requested = current is not None and current.status is TaskStatus.CANCEL_REQUESTED
        if requested:
            self._cancel_event.set()
        return requested

    def load_checkpoint(self) -> dict:
        return self.artifacts.read_json(
            self.task.task_id,
            "checkpoints/worker.json",
            default={},
        )

    def save_checkpoint(self, value: dict) -> None:
        self.artifacts.atomic_write_json(
            self.task.task_id,
            "checkpoints/worker.json",
            value,
        )


class TaskHandler(Protocol):
    def run(self, context: WorkerContext) -> tuple[TaskStatus, str | None]: ...

    def recover(self, context: WorkerContext) -> tuple[TaskStatus, str | None]: ...
