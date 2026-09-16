from __future__ import annotations

from typing import Any

from .models import TaskKind, TaskRecord, TaskStatus
from .repository import TaskRepository
from .worker_instances import WorkerInstanceService


def effective_task_status(task: TaskRecord) -> str:
    if task.status is TaskStatus.QUEUED and task.stage == "resource_waiting":
        return "WAITING_RESOURCE"
    if task.status is TaskStatus.RUNNING and task.stage == "paused":
        return "PAUSED"
    return task.status.value


def task_to_public(
    task: TaskRecord,
    repository: TaskRepository | None = None,
    *,
    now=None,
    worker_runtime: list[dict[str, Any]] | None = None,
    queued_candidates: tuple[TaskRecord, ...] | None = None,
) -> dict[str, Any]:
    queue_position = None
    queue_position_exact = False
    if repository is not None and task.status is TaskStatus.QUEUED:
        queue_position = repository.resource_queue_position(task.task_id)
        if task.kind is not TaskKind.TRAINING:
            queue_position_exact = _non_training_queue_position_exact(
                task,
                repository,
                queue_position=queue_position,
                now=now,
                worker_runtime=worker_runtime,
                queued_candidates=queued_candidates,
            )
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
        "resource_queue_position_exact": bool(queue_position_exact),
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


def _training_resource_pool_label(resource_key: str) -> str:
    key = str(resource_key or "")
    if key == "training:cpu":
        return "CPU"
    if key == "training:auto":
        return "GPU 自动"
    if key.startswith("training:cuda:"):
        index = key.removeprefix("training:cuda:").strip()
        return f"GPU {index}" if index else "GPU"
    if key.startswith("training:gpu:"):
        index = key.removeprefix("training:gpu:").strip()
        return f"GPU {index}" if index else "GPU"
    if key.startswith("training:remote:"):
        return "指定远程服务器"
    return "训练资源"


def _worker_can_claim(worker: dict[str, Any], task: TaskRecord) -> bool:
    kinds = {str(value) for value in worker.get("task_kinds") or ()}
    capabilities = {str(value) for value in worker.get("capabilities") or ()}
    return task.kind.value in kinds and set(task.required_capabilities) <= capabilities


def _non_training_queue_position_exact(
    task: TaskRecord,
    repository: TaskRepository,
    *,
    queue_position: int | None,
    now=None,
    worker_runtime: list[dict[str, Any]] | None = None,
    queued_candidates: tuple[TaskRecord, ...] | None = None,
) -> bool:
    """Prove a resource queue rank matches one real Worker claim order.

    Resource-scoped SQL order alone is insufficient because a Worker may skip
    tasks by kind/capability or compete across resource keys. Exactness is
    fail-closed unless one compatible online Worker exists and every queued
    task that Worker could claim belongs to this same resource queue.
    """
    if (
        task.status is not TaskStatus.QUEUED
        or task.kind is TaskKind.TRAINING
        or queue_position is None
    ):
        return False
    runtime = (
        WorkerInstanceService(repository).list_runtime(now=now)
        if worker_runtime is None
        else worker_runtime
    )
    compatible = [
        worker
        for worker in runtime
        if worker.get("online") is True and _worker_can_claim(worker, task)
    ]
    if len(compatible) != 1:
        return False
    worker = compatible[0]
    candidates = repository.queued_candidates() if queued_candidates is None else queued_candidates
    claimable = [candidate for candidate in candidates if _worker_can_claim(worker, candidate)]
    if any(candidate.resource_key != task.resource_key for candidate in claimable):
        return False
    scan_position = next(
        (
            index
            for index, candidate in enumerate(claimable, start=1)
            if candidate.task_id == task.task_id
        ),
        None,
    )
    return scan_position is not None and scan_position == queue_position


def _waiting_training_truth(
    task: TaskRecord,
    repository: TaskRepository,
    reason: str,
) -> dict[str, Any]:
    return {
        "status": "WAITING_RESOURCE",
        "resource_wait_reason": str(reason),
        "resource_queue_position": repository.resource_queue_position(task.task_id),
        "resource_queue_position_exact": False,
        "resource_pool_key": task.resource_key,
        "resource_pool_label": _training_resource_pool_label(task.resource_key),
    }


def training_queue_truth(
    task: TaskRecord,
    repository: TaskRepository,
    *,
    now=None,
    worker_runtime: list[dict[str, Any]] | None = None,
    queued_candidates: tuple[TaskRecord, ...] | None = None,
) -> dict[str, Any]:
    """Project local training queue readiness without mutating durable state.

    Exact rank proof is intentionally conservative. GPU admission and remote
    affinity are outside this read model, so their resource-scoped position is
    never advertised as an exact executable queue rank.
    """
    pool = {
        "resource_pool_key": task.resource_key,
        "resource_pool_label": _training_resource_pool_label(task.resource_key),
    }
    if task.status is not TaskStatus.QUEUED or task.kind is not TaskKind.TRAINING:
        return {
            "status": effective_task_status(task),
            "resource_wait_reason": task.resource_wait_reason,
            "resource_queue_position": None,
            "resource_queue_position_exact": False,
            **pool,
        }

    queue_position = repository.resource_queue_position(task.task_id)
    if task.resource_key.startswith("training:remote:"):
        return _waiting_training_truth(
            task,
            repository,
            "指定远程服务器的 Worker 路由尚未建立",
        )

    runtime = (
        WorkerInstanceService(repository).list_runtime(now=now)
        if worker_runtime is None
        else worker_runtime
    )
    online = [worker for worker in runtime if worker.get("online") is True]
    if not online:
        return _waiting_training_truth(task, repository, "当前没有在线 Worker")

    training_workers = [
        worker
        for worker in online
        if TaskKind.TRAINING.value in {str(value) for value in worker.get("task_kinds") or ()}
    ]
    if not training_workers:
        return _waiting_training_truth(task, repository, "当前没有可执行训练任务的 Worker")

    compatible = [worker for worker in training_workers if _worker_can_claim(worker, task)]
    if not compatible:
        missing = ", ".join(task.required_capabilities) or "所需 capability"
        return _waiting_training_truth(
            task,
            repository,
            f"当前在线 Training Worker 不支持 {missing}",
        )

    if task.stage == "resource_waiting" and str(task.resource_wait_reason or "").strip():
        return _waiting_training_truth(task, repository, str(task.resource_wait_reason))

    exact = False
    if task.resource_key == "training:cpu" and len(compatible) == 1:
        worker = compatible[0]
        candidates = (
            repository.queued_candidates()
            if queued_candidates is None
            else queued_candidates
        )
        claimable = [
            candidate
            for candidate in candidates
            if _worker_can_claim(worker, candidate)
        ]
        cross_resource = any(
            candidate.resource_key != task.resource_key for candidate in claimable
        )
        scan_position = next(
            (index for index, candidate in enumerate(claimable, start=1)
             if candidate.task_id == task.task_id),
            None,
        )
        exact = (
            not cross_resource
            and scan_position is not None
            and scan_position == queue_position
        )

    return {
        "status": "QUEUED",
        "resource_wait_reason": None,
        "resource_queue_position": queue_position,
        "resource_queue_position_exact": exact,
        **pool,
    }
