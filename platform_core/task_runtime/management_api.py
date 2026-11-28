"""Training/unified task management endpoints (promote, cancel).

These two handlers used to live in ``app.py``. They own only the HTTP contract
and the ordering of existing owners:

* the task repository decides promote/cancel state (no second state machine),
* the caller-supplied ``cancel_prepare_child`` stops the deterministic training
  prepare child after its parent was cancelled,
* the caller-supplied ``terminate_tree`` is the existing process controller, so
  a cancel that cannot be proven safe still fails closed with 409.

Nothing here imports the application; every dependency is injected.
"""
from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, HTTPException

from .models import TaskKind, TaskStatus
from .process_control import ProcessIdentity


def create_task_management_router(
    *,
    task_for_project: Callable[[str, str], Any],
    repository: Callable[[], Any],
    cancel_prepare_child: Callable[[Any, Any], None],
    terminate_tree: Callable[[ProcessIdentity], Any],
    public_task: Callable[[Any, Any], dict],
) -> APIRouter:
    router = APIRouter()

    @router.post("/api/v62/projects/{project_id}/tasks/{task_id}/promote")
    def promote_unified_runtime_task(project_id: str, task_id: str):
        task_for_project(project_id, task_id)
        store = repository()
        try:
            task = store.promote(task_id)
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return public_task(task, store)

    @router.post("/api/v62/projects/{project_id}/tasks/{task_id}/cancel")
    def cancel_unified_runtime_task(project_id: str, task_id: str):
        current = task_for_project(project_id, task_id)
        store = repository()
        try:
            task = store.request_cancel(task_id)
            if current.kind is TaskKind.TRAINING:
                cancel_prepare_child(store, current)
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        if (
            current.status is TaskStatus.RUNNING
            and current.process_pid is not None
            and current.process_create_time is not None
            and str(current.process_command_hash or "").strip()
        ):
            identity = ProcessIdentity(
                pid=int(current.process_pid),
                create_time=float(current.process_create_time),
                command_hash=str(current.process_command_hash),
            )
            try:
                terminate_tree(identity)
            except PermissionError as error:
                raise HTTPException(
                    status_code=409,
                    detail=f"取消请求已记录，但任务进程无法安全终止：{error}",
                ) from error
        return public_task(task, store)

    return router


__all__ = ["create_task_management_router"]
