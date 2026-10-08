"""Training recovery read/action API backed by durable failure evidence.

This module deliberately does not invent recovery from UI-visible progress.  A
recovery action is exposed only when the persisted training task and its
``failure.json`` agree that a completed training loop has a trusted checkpoint
available for checkpoint-only revalidation.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote

from .task_runtime import TaskKind, TaskStatus

RECOVERY_ACTION_REVALIDATE = "revalidate_checkpoint"
RECOVERABLE_FAILURE_STAGES = {"final_validation", "post_training"}
_ERROR_CODE_RE = re.compile(r"\b[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+\b")
_WRAPPER_ERROR_CODES = {
    "TRAINING_PREPARATION_FAILED",
    "TRAINING_PROCESS_FAILED",
    "TRAINING_FAILED",
}


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
    for key in ("last_job_message", "recovery_error", "completion_error"):
        value = str(failure.get(key) or "").strip()
        if value:
            return value
    return str(getattr(task, "error", None) or getattr(task, "current_item", None) or "").strip()


def _failure_diagnostics(task, failure: Mapping[str, Any]) -> list[str]:
    values = [
        failure.get("last_job_message"),
        getattr(task, "error", None),
        failure.get("recovery_error"),
        failure.get("completion_error"),
        getattr(task, "current_item", None),
    ]
    diagnostics: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in diagnostics:
            diagnostics.append(text)
    return diagnostics


def _failure_stage_for_code(code: str, declared_stage: str) -> tuple[int, str]:
    upper = str(code or "").upper()
    if upper.startswith(("ADMISSION_", "TRAINING_ADMISSION_", "REQUEST_")):
        return 1, "admission"
    if upper.startswith(("DUPLICATE_", "MATERIAL_", "INPUT_", "DATASET_")):
        return 2, "data_integrity"
    if upper.startswith(("LABEL_", "GOVERNANCE_")):
        return 3, "label_contract"
    if upper.startswith(("RESOURCE_", "GPU_", "CUDA_")):
        return 4, "resource_validation"
    if upper.startswith(("PROCESS_", "WORKER_", "REMOTE_")):
        return 5, "worker_process"
    if upper.startswith(("TRAINER_", "ULTRALYTICS_")):
        return 6, "trainer"
    if upper.startswith(("VALIDATION_", "MODEL_VALIDATION_", "CHECKPOINT_")):
        return 7, "final_validation"
    if upper.startswith(("ARCHIVE_", "COMMIT_", "PUBLISH_")):
        return 8, "archive"
    normalized = str(declared_stage or "").strip().lower()
    if normalized in {"training_input_pending", "training_input_preparation_failed", "materializing"}:
        return 2, "training_input"
    if normalized in {"resource_validation", "resources", "resources_ready"}:
        return 4, "resource_validation"
    if normalized in {"training_process", "worker_process"}:
        return 5, "worker_process"
    if normalized in {"training", "trainer"}:
        return 6, "trainer"
    if normalized in {"final_validation", "post_training"}:
        return 7, "final_validation"
    if normalized in {"archive", "finalizing_commit", "committed"}:
        return 8, "archive"
    return 9, normalized or "unknown"


def _primary_failure(task, failure: Mapping[str, Any]) -> dict[str, Any]:
    diagnostics = _failure_diagnostics(task, failure)
    declared_stage = str(failure.get("failure_stage") or getattr(task, "stage", None) or "").strip()
    candidates: list[tuple[int, int, str, str]] = []
    for diagnostic_index, diagnostic in enumerate(diagnostics):
        codes = _ERROR_CODE_RE.findall(diagnostic)
        specific = [code for code in codes if code not in _WRAPPER_ERROR_CODES]
        for code in specific or codes:
            priority, stage = _failure_stage_for_code(code, declared_stage)
            candidates.append((priority, diagnostic_index, code, stage))
    if candidates:
        _, diagnostic_index, code, stage = min(candidates)
        raw = diagnostics[diagnostic_index]
    else:
        _, stage = _failure_stage_for_code("", declared_stage)
        code = None
        raw = diagnostics[0] if diagnostics else "训练任务失败"

    messages = {
        "DUPLICATE_ANNOTATION_CONFLICT": "发现重复图片存在不同标注，训练已在启动 Worker 前阻止。",
        "RESOURCE_MANUAL_INVALID": "手动资源配置无法满足当前运行预算。请降低 Batch / Workers，或改用系统推荐配置。",
        "GPU_MEMORY_INSUFFICIENT": "当前 GPU 资源不足以安全启动训练，请调整配置或等待可用资源。",
    }
    return {
        "primary_error_code": code,
        "primary_stage": stage,
        "primary_message": messages.get(str(code or ""), raw),
        "secondary_diagnostics": diagnostics,
    }


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
    primary = _primary_failure(task, failure)
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
        **primary,
        "completion_handshake": str(
            failure.get("completion_handshake")
            or failure.get("completion_error")
            or ""
        ).strip() or None,
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


def training_recovery_router(
    get_project,
    task_repository,
    task_artifacts,
    agent_execution_payload_resolver=None,
    agent_result_upload_preparer=None,
    agent_result_upload_confirmer=None,
    agent_result_commit_handler=None,
    agent_training_model_upload_preparer=None,
    agent_training_model_upload_confirmer=None,
    agent_material_scan_page_provider=None,
    agent_material_scan_read_provider=None,
    agent_clean_selection_page_provider=None,
    agent_clean_selection_read_provider=None,
):
    from fastapi import APIRouter, Body, HTTPException, Query

    recovery_router = APIRouter(prefix="/api/v62/projects/{project_id}/training-tasks")

    def require_task(project_id: str, task_id: str):
        get_project(project_id)
        task = task_repository().get(task_id)
        if task is None or task.project_id != project_id or task.kind is not TaskKind.TRAINING:
            raise HTTPException(status_code=404, detail="训练任务不存在")
        return task

    @recovery_router.get("/{task_id}/input-issues")
    def input_issues(
        project_id: str,
        task_id: str,
        page: int = Query(default=1, ge=1),
        limit: int = Query(default=50, ge=1, le=100),
    ):
        require_task(project_id, task_id)
        artifacts = task_artifacts()
        manifest = artifacts.read_json(
            task_id,
            "input-compatibility/manifest.json",
            default=None,
        )
        if not isinstance(manifest, Mapping):
            raise HTTPException(status_code=404, detail="训练输入异常证据不存在")
        issue_count = max(0, int(manifest.get("issue_count") or 0))
        stored_page_size = max(1, min(100, int(manifest.get("page_size") or 100)))
        refs = {
            int(item.get("page") or 0): str(item.get("ref") or "")
            for item in (manifest.get("pages") or [])
            if isinstance(item, Mapping)
            and str(item.get("ref") or "").startswith("input-compatibility/pages/")
        }
        start = (page - 1) * limit
        stop = min(issue_count, start + limit)
        items: list[dict[str, Any]] = []
        if start < stop:
            first_stored_page = start // stored_page_size + 1
            last_stored_page = (stop - 1) // stored_page_size + 1
            for stored_page in range(first_stored_page, last_stored_page + 1):
                ref = refs.get(stored_page)
                if not ref:
                    raise HTTPException(status_code=409, detail="训练输入异常证据不完整")
                rows = artifacts.read_json(task_id, ref, default=None)
                if not isinstance(rows, list):
                    raise HTTPException(status_code=409, detail="训练输入异常证据不完整")
                source_start = (stored_page - 1) * stored_page_size
                local_start = max(0, start - source_start)
                local_stop = min(len(rows), stop - source_start)
                items.extend(
                    {
                        **dict(item),
                        "thumbnail_url": (
                            f"/api/v62/projects/{quote(str(project_id), safe='')}"
                            "/training-materials/"
                            f"{quote(str(item.get('image_id') or ''), safe='')}/thumbnail"
                        ),
                        "content_url": (
                            f"/api/v61/projects/{quote(str(project_id), safe='')}/materials/"
                            f"{quote(str(item.get('image_id') or ''), safe='')}/content"
                        ),
                    }
                    for item in rows[local_start:local_stop]
                    if isinstance(item, Mapping)
                )
        return {
            "ok": True,
            "task_id": task_id,
            "issue_count": issue_count,
            "issue_counts": dict(manifest.get("issue_counts") or {}),
            "required_label_codes": list(
                manifest.get("required_label_codes") or []
            ),
            "material_revision": int(manifest.get("material_revision") or 0),
            "annotation_revision": int(manifest.get("annotation_revision") or 0),
            "items": items,
            "page": page,
            "limit": limit,
            "total_pages": (
                (issue_count + limit - 1) // limit if issue_count else 0
            ),
        }

    @recovery_router.get("/{task_id}/recovery")
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

    @recovery_router.post("/recovery-query")
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

    @recovery_router.post("/{task_id}/recovery", status_code=202)
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

    # app.py owns one additive runtime-router mount for recovery / scheduler /
    # agent APIs. Project material paging is mounted separately by app.py so it
    # cannot inherit task-artifact storage paths.
    from .service_nodes import service_node_router
    from .task_node_assignments import central_scheduler_router
    from .agent_execution import agent_executor_router

    root = APIRouter()
    root.include_router(recovery_router)
    root.include_router(service_node_router(task_repository))
    root.include_router(central_scheduler_router(task_repository, task_artifacts))
    root.include_router(agent_executor_router(
        task_repository,
        task_artifacts,
        execution_payload_resolver=agent_execution_payload_resolver,
        result_upload_preparer=agent_result_upload_preparer,
        result_upload_confirmer=agent_result_upload_confirmer,
        result_commit_handler=agent_result_commit_handler,
        training_model_upload_preparer=agent_training_model_upload_preparer,
        training_model_upload_confirmer=agent_training_model_upload_confirmer,
        material_scan_page_provider=agent_material_scan_page_provider,
        material_scan_read_provider=agent_material_scan_read_provider,
        clean_selection_page_provider=agent_clean_selection_page_provider,
        clean_selection_read_provider=agent_clean_selection_read_provider,
    ))
    return root
