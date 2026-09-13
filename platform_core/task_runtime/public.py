from __future__ import annotations

from typing import Any

from .models import TaskRecord, TaskStatus
from .repository import TaskRepository


def effective_task_status(task: TaskRecord) -> str:
    if task.status is TaskStatus.QUEUED and task.stage == "resource_waiting":
        return "WAITING_RESOURCE"
    return task.status.value


def task_to_public(task: TaskRecord, repository: TaskRepository | None = None) -> dict[str, Any]:
    queue_position = None
    if repository is not None and task.status is TaskStatus.QUEUED:
        queue_position = repository.resource_queue_position(task.task_id)
    return {
        "task_id": task.task_id,
        "project_id": task.project_id,
        "task_type": task.kind.value,
        "status": effective_task_status(task),
        "persisted_status": task.status.value,
        "phase": task.stage,
        "progress_percent": max(0.0, min(100.0, float(task.progress))),
        "current_item": task.current_item,
        "priority": int(task.priority),
        "queue_rank": int(task.queue_rank),
        "resource_queue_position": queue_position,
        "resource_key": task.resource_key,
        "resource_wait_reason": task.resource_wait_reason,
        "required_capabilities": list(task.required_capabilities),
        "worker_id": task.worker_id,
        "lease_expires_at": task.lease_expires_at,
        "attempt": int(task.attempt),
        "retry_of": task.retry_of,
        "error": task.error,
        "accepted": task.accepted,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "finished_at": task.finished_at,
    }
