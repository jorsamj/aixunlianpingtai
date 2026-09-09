from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class TaskStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    AWAITING_CONFIRMATION = "AWAITING_CONFIRMATION"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    SUCCEEDED = "SUCCEEDED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"
    BLOCKED_BY_ENVIRONMENT = "BLOCKED_BY_ENVIRONMENT"
    BLOCKED_BY_HARDWARE = "BLOCKED_BY_HARDWARE"


class TaskKind(str, Enum):
    RESOURCE_DISCOVERY = "RESOURCE_DISCOVERY"
    MATERIAL_IMPORT = "MATERIAL_IMPORT"
    CLEANING = "CLEANING"
    AI_ANNOTATION = "AI_ANNOTATION"
    VIDEO_FRAMES = "VIDEO_FRAMES"
    TRAINING = "TRAINING"
    MODEL_CONVERSION = "MODEL_CONVERSION"
    DEPLOYMENT_TEST = "DEPLOYMENT_TEST"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class TaskRecord:
    task_id: str
    project_id: str
    kind: TaskKind
    status: TaskStatus
    priority: int
    resource_key: str
    required_capabilities: tuple[str, ...]
    payload_ref: str
    result_ref: str | None = None
    log_ref: str = "logs/task.log"
    progress: float = 0.0
    stage: str = "queued"
    current_item: str | None = None
    attempt: int = 0
    retry_of: str | None = None
    error: str | None = None
    accepted: bool | None = None
    process_pid: int | None = None
    process_create_time: float | None = None
    process_command_hash: str | None = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    finished_at: str | None = None

    @classmethod
    def new(
        cls,
        task_id: str,
        project_id: str,
        kind: TaskKind,
        payload_ref: str,
        resource_key: str,
        priority: int = 50,
        required_capabilities: tuple[str, ...] = (),
    ) -> "TaskRecord":
        return cls(
            task_id=task_id,
            project_id=project_id,
            kind=kind,
            status=TaskStatus.QUEUED,
            priority=max(1, min(999, int(priority))),
            resource_key=resource_key,
            required_capabilities=tuple(sorted(set(required_capabilities))),
            payload_ref=payload_ref,
        )


@dataclass(frozen=True)
class TaskLease:
    task: TaskRecord
    lease_token: str
    worker_id: str
    expires_at: str


@dataclass(frozen=True)
class TaskPage:
    items: tuple[TaskRecord, ...]
    next_cursor: str | None
