from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .artifacts import ArtifactStore
from .models import TaskLease, TaskRecord, TaskStatus


class RepositoryPort(Protocol):
    def get(self, task_id: str) -> TaskRecord | None: ...

    def heartbeat(
        self,
        task_id: str,
        lease_token: str,
        progress=None,
        stage=None,
        current_item=None,
    ) -> TaskRecord: ...


@dataclass(frozen=True)
class WorkerContext:
    task: TaskRecord
    lease: TaskLease
    repository: RepositoryPort
    artifacts: ArtifactStore

    def cancel_requested(self) -> bool:
        current = self.repository.get(self.task.task_id)
        return current is not None and current.status is TaskStatus.CANCEL_REQUESTED

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
