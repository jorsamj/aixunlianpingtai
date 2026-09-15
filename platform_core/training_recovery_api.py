"""Training recovery read/action API backed by durable failure evidence.

This module deliberately does not invent recovery from UI-visible progress.  A
recovery action is exposed only when the persisted training task and its
``failure.json`` agree that a completed training loop has a trusted checkpoint
available for checkpoint-only revalidation.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping

from .task_runtime import TaskKind, TaskStatus

RECOVERY_ACTION_REVALIDATE = "revalidate_checkpoint"
RECOVERABLE_FAILURE_STAGES = {"final_validation", "post_training"}


def _best_checkpoint(failure: Mapping[str, Any]) -> Mapping[str, Any] | None:
    for item in failure.get("checkpoints") or ():
        if isinstance(item, Mapping) and str(item.get("kind") or "") == "best":
            return item
    return None


def _checkpoint_state(failure: Mapping[str, Any], *, verify_hash: bool = False) -> tuple[bool, dict[str, Any] | None]:
    checkpoint = _best_checkpoint(failure)
    if checkpoint is None:
        return False, None
    raw = str(checkpoint.get("path") or "").strip()
    expected_sha = str(checkpoint.get("sha256") or "").strip().lower()
    if not raw or not expected_sha:
        return False, None
    path = Path(raw)
    try:
        available = path.is_file() and path.stat().st_size > 0
    except OSError:
        available = False
    if available and verify_hash:
        digest = hashlib.sha256()
        try:
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            available = digest.hexdigest().lower() == expected_sha
        except OSError:
            available = False
    public = {
        "kind": str(checkpoint.get("kind") or "best"),
        "filename": path.name if raw else "best.pt",
        "size_bytes": int(checkpoint.get("size_bytes") or 0),
        "hash_recorded": bool(expected_sha),
    }
    return available, public


def _failure_reason(task, failure: Mapping[str, Any]) -> str:
    for key in ("recovery_error", "completion_error", "last_job_message"):
        value = str(failure.get(key) or "").strip()
        if value:
            return value
    return str(getattr(task, "error", None) or getattr(task, "current_item", None) or "").strip()


def training_recovery_truth(task, artifacts, *, verify_checkpoint_hash: bool = False) -> dict[str, Any]:
    """Project one task's durable recovery contract without mutating it."""
    if task.kind is not TaskKind.TRAINING:
        raise ValueError("task is not a training task")

    failure = artifacts.read_json(task.task_id, "failure.json", default={})
    if not isinstance(failure, Mapping):
        failure = {}
    evidence_matches = bool(
        str(failure.get("task_id") or "") == str(task.task_id)
        and str(failure.get("project_id") or "") == str(task.project_id)
    )
    failure = dict(failure) if evidence_matches else {}
    checkpoint_available, checkpoint = _checkpoint_state(
        failure,
        verify_hash=verify_checkpoint_hash,
    )
    failure_stage = str(failure.get("failure_stage") or "").strip() or None
    declared_action = str(failure.get("recovery_action") or "").strip() or None
    terminal_failed = task.status is TaskStatus.FAILED
    recoverable = bool(
        terminal_failed
        and evidence_matches
        and failure.get("recoverable") is True
        and failure.get("training_loop_completed") is True
        and failure_stage in RECOVERABLE_FAILURE_STAGES
        and failure.get("checkpoint_available") is True
        and checkpoint_available
        and declared_action == RECOVERY_ACTION_REVALIDATE
    )
    return {
        "task_id": task.task_id,
        "project_id": task.project_id,
        "task_status": task.status.value,
        "available": recoverable,
        "recoverable": recoverable,
        "checkpoint_available": bool(checkpoint_available),
        "recovery_action": RECOVERY_ACTION_REVALIDATE if recoverable else None,
        "declared_recovery_action": declared_action,
        "failure_stage": failure_stage,
        "failure_reason": _failure_reason(task, failure),
        "process_returncode": failure.get("process_returncode"),
        "process_signal": failure.get("process_signal"),
        "training_loop_completed": failure.get("training_loop_completed") is True,
        "completed_epochs": int(failure.get("completed_epochs") or 0),
        "requested_epochs": int(failure.get("requested_epochs") or 0),
        "checkpoint": checkpoint,
        "attempt": int(getattr(task, "attempt", 0) or 0),
        "retry_of": getattr(task, "retry_of", None),
        "recovery_attempted": failure.get("recovery_attempted") is True,
        "recovery_completed": failure.get("recovery_completed") is True,
        "recovery_error": str(failure.get("recovery_error") or "").strip() or None,
    }


def request_training_recovery(repository, artifacts, project_id: str, task_id: str, action: str):
    """Queue checkpoint-only recovery on the same durable task record."""
    task = repository.get(task_id)
    if task is None or task.project_id != project_id or task.kind is not TaskKind.TRAINING:
        raise KeyError(task_id)
    action = str(action or "").strip()
    if action != RECOVERY_ACTION_REVALIDATE:
        raise ValueError("unsupported training recovery action")
    truth = training_recovery_truth(task, artifacts, verify_checkpoint_hash=True)
    if not truth["available"] or truth["recovery_action"] != action:
        raise RuntimeError("training task has no trusted recoverable checkpoint")
    retried = repository.retry(task_id)
    return retried, truth


def training_recovery_router(get_project, task_repository, task_artifacts):
    from fastapi import APIRouter, Body, HTTPException

    router = APIRouter(prefix="/api/v62/projects/{project_id}/training-tasks")

    def require_task(project_id: str, task_id: str):
        get_project(project_id)
        task = task_repository().get(task_id)
        if task is None or task.project_id != project_id or task.kind is not TaskKind.TRAINING:
            raise HTTPException(status_code=404, detail="训练任务不存在")
        return task

    @router.get("/{task_id}/recovery")
    def recovery(project_id: str, task_id: str):
        task = require_task(project_id, task_id)
        return {
            "ok": True,
            "recovery": training_recovery_truth(
                task,
                task_artifacts(),
                verify_checkpoint_hash=True,
            ),
        }

    @router.post("/recovery-query")
    def recovery_query(project_id: str, payload: dict = Body(...)):
        get_project(project_id)
        ids = list(dict.fromkeys(str(value) for value in (payload.get("task_ids") or []) if str(value)))
        if len(ids) > 100:
            raise HTTPException(status_code=422, detail="一次最多查询100个训练任务")
        items = {}
        repository = task_repository()
        artifacts = task_artifacts()
        for task_id in ids:
            task = repository.get(task_id)
            if task is None or task.project_id != project_id or task.kind is not TaskKind.TRAINING:
                continue
            items[task_id] = training_recovery_truth(task, artifacts)
        return {"ok": True, "items": items}

    @router.post("/{task_id}/recovery", status_code=202)
    def recover(project_id: str, task_id: str, payload: dict = Body(...)):
        require_task(project_id, task_id)
        try:
            task, before = request_training_recovery(
                task_repository(),
                task_artifacts(),
                project_id,
                task_id,
                str(payload.get("action") or ""),
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="训练任务不存在") from error
        except (ValueError, RuntimeError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return {
            "ok": True,
            "task_id": task.task_id,
            "status": task.status.value,
            "stage": task.stage,
            "retry_of": task.retry_of,
            "attempt": task.attempt,
            "recovery_requested": True,
            "recovery_action": before["recovery_action"],
        }

    return router
