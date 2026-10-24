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
from starlette.requests import Request

from .task_runtime import TaskKind, TaskStatus

RECOVERY_ACTION_REVALIDATE = "revalidate_checkpoint"
RECOVERABLE_FAILURE_STAGES = {"final_validation", "post_training"}
_ERROR_CODE_RE = re.compile(r"\b[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+\b")
_WRAPPER_ERROR_CODES = {
    "TRAINING_PREPARATION_FAILED",
    "TRAINING_PROCESS_FAILED",
    "TRAINING_FAILED",
}
_SECRET_VALUE_RE = re.compile(
    r"(?i)\b(token|password|passwd|secret|api[_-]?key|access[_-]?key)\s*([=:])\s*([^\s;,]+)"
)
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[^\s;,]+")
_WINDOWS_PATH_RE = re.compile(r"(?i)(?<![\w])(?:[a-z]:\\(?:[^\s;:,]+\\)*[^\s;:,]*)")
_POSIX_PATH_RE = re.compile(r"(?<![\w:])/(?:[^\s;:,/]+/)+[^\s;:,]*")


def _public_text(value: Any, *, limit: int = 800) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = _BEARER_RE.sub("Bearer [REDACTED]", text)
    text = _SECRET_VALUE_RE.sub(
        lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]",
        text,
    )
    text = _WINDOWS_PATH_RE.sub("[内部路径]", text)
    text = _POSIX_PATH_RE.sub("[内部路径]", text)
    return text[:limit]


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
            return _public_text(value)
    return _public_text(getattr(task, "error", None) or getattr(task, "current_item", None) or "")


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
        text = _public_text(value)
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


def _correlated_system_evidence(failure: Mapping[str, Any], evidence_type: str) -> Mapping[str, Any] | None:
    try:
        process_pid = int(failure.get("process_pid"))
        process_create_time = float(failure.get("process_create_time"))
    except (TypeError, ValueError):
        return None
    for item in failure.get("system_evidence") or ():
        if not isinstance(item, Mapping) or item.get("correlated") is not True:
            continue
        if str(item.get("type") or "") != evidence_type:
            continue
        try:
            item_pid = int(item.get("process_pid"))
            item_create_time = float(item.get("process_create_time"))
            observed_at = float(item.get("observed_at_epoch"))
        except (TypeError, ValueError):
            continue
        if item_pid != process_pid or abs(item_create_time - process_create_time) > 0.01:
            continue
        if observed_at < process_create_time - 2.0:
            continue
        if evidence_type == "linux_kernel_oom_kill":
            if str(item.get("source") or "") != "linux_kernel_journal":
                continue
        elif evidence_type == "cgroup_memory_oom":
            try:
                delta = int(item.get("oom_kill_delta") or 0)
            except (TypeError, ValueError):
                delta = 0
            if (
                str(item.get("source") or "") != "cgroup_memory_events"
                or delta <= 0
                or not str(item.get("scope_identity") or "").strip()
            ):
                continue
        return item
    return None


def _failure_diagnosis(
    task,
    failure: Mapping[str, Any],
    primary: Mapping[str, Any],
    *,
    recoverable: bool,
) -> dict[str, Any]:
    diagnostics = _failure_diagnostics(task, failure)
    diagnostic_text = "\n".join(diagnostics)
    lowered = diagnostic_text.lower()
    primary_code = str(primary.get("primary_error_code") or "").upper()
    process_signal = str(failure.get("process_signal") or "").upper()
    process_returncode = failure.get("process_returncode")
    checkpoint_message = (
        "存在可信训练断点，可按当前恢复合同重新验证 Checkpoint。"
        if recoverable
        else "当前没有可恢复的训练断点，需要重新创建训练任务。"
    )

    host_oom = _correlated_system_evidence(failure, "linux_kernel_oom_kill")
    cgroup_oom = _correlated_system_evidence(failure, "cgroup_memory_oom")
    concurrent_host_oom = next((
        item for item in failure.get("system_evidence") or ()
        if isinstance(item, Mapping)
        and str(item.get("type") or "") == "linux_kernel_oom_concurrent"
        and item.get("correlated") is False
        and str(item.get("source") or "") == "linux_kernel_journal"
    ), None)
    if host_oom is not None:
        return {
            "code": "HOST_MEMORY_OOM",
            "certainty": "confirmed",
            "title": "训练失败：服务器内存不足",
            "summary": "训练过程中服务器物理内存不足，Linux Kernel 强制终止了当前训练进程。",
            "evidence": [
                "Linux Kernel 检测到与当前训练进程匹配的 OOM Kill。",
                "训练进程收到 SIGKILL。",
                checkpoint_message,
            ],
            "possible_causes": [],
            "suggestions": [
                "适当降低 Batch，并减少 DataLoader Workers。",
                "检查服务器剩余内存和同时运行的其他任务。",
                "确认内存资源充足后重新创建训练任务。",
            ],
            "checkpoint_message": checkpoint_message,
        }
    if cgroup_oom is not None:
        return {
            "code": "CGROUP_MEMORY_OOM",
            "certainty": "confirmed",
            "title": "训练失败：服务内存限制不足",
            "summary": "当前训练进程触发了与任务关联的服务或容器内存限制。",
            "evidence": ["运行时记录到与当前训练进程关联的 cgroup OOM Kill。", checkpoint_message],
            "possible_causes": [],
            "suggestions": ["检查 Worker 服务或容器的内存上限。", "资源调整后重新创建训练任务。"],
            "checkpoint_message": checkpoint_message,
        }
    if (
        primary_code in {"GPU_MEMORY_OOM", "CUDA_OUT_OF_MEMORY", "CUDA_OOM"}
        or "torch.cuda.outofmemoryerror" in lowered
        or "cuda out of memory" in lowered
    ):
        return {
            "code": "GPU_MEMORY_OOM",
            "certainty": "confirmed",
            "title": "训练失败：GPU 显存不足",
            "summary": "训练运行时记录到明确的 CUDA 显存不足错误。",
            "evidence": ["训练错误包含明确的 CUDA OutOfMemoryError。", checkpoint_message],
            "possible_causes": [],
            "suggestions": ["适当降低 Batch。", "检查 GPU 是否有其他任务占用显存。", "按需减小输入图片尺寸。"],
            "checkpoint_message": checkpoint_message,
        }

    friendly = {
        "WORKER_LEASE_LOST": ("Worker 执行租约已丢失", "Worker 无法继续证明当前任务的执行所有权。", ["检查 Worker 心跳、网络和任务代次后重新创建任务。"]),
        "WORKER_PROCESS_TERMINATED": ("Worker 进程已终止", "Worker 进程在任务完成前终止。", ["检查 Worker 服务状态和任务执行日志。"]),
        "WORKER_UNEXPECTED_EXIT": ("Worker 异常退出", "Worker 未按预期完成本次训练。", ["检查 Worker 环境和执行日志后重试。"]),
        "TRAINING_CANCELLED": ("训练已取消", "该训练任务由用户或受信控制流程取消。", ["如仍需训练，请重新创建训练任务。"]),
        "TRAINING_PREPARATION_FAILED": ("训练数据准备失败", "训练在启动模型训练前未能完成输入准备。", ["检查素材、标注和训练输入配置。"]),
        "DUPLICATE_ANNOTATION_CONFLICT": ("训练标注存在冲突", "重复图片存在不一致标注，训练已被安全阻止。", ["统一冲突图片的标注后重新训练。"]),
        "RESOURCE_MANUAL_INVALID": ("训练资源配置不可用", "手动资源配置无法满足当前运行预算。", ["降低 Batch / Workers，或改用系统推荐配置。"]),
        "GPU_MEMORY_INSUFFICIENT": ("GPU 资源不足", "当前 GPU 资源不足以安全启动训练。", ["调整配置或等待 GPU 资源释放。"]),
        "CHECKPOINT_MISSING": ("训练断点不存在", "恢复所需的可信 Checkpoint 不存在。", ["重新创建训练任务。"]),
        "MODEL_VALIDATION_FAILED": ("最终模型验证失败", "训练结果未通过最终模型验证。", ["查看验证错误并修复对应模型或环境问题。"]),
        "DATABASE_LOCKED": ("Worker 运行存储被占用", "Worker 的 SQLite 运行存储当前被其他写入占用。", ["检查 Worker 并发写入和存储可用性。"]),
        "TRAINING_IMAGE_INVALID": ("训练素材不可用", "训练素材未通过完整性或可读性检查。", ["检查失败素材并重新准备训练数据。"]),
        "RESOURCE_PREPARE_FAILED": ("训练资源准备失败", "Worker 未能准备训练所需的运行资源。", ["检查 Worker 环境和资源状态。"]),
        "FALSE_FINAL_VALIDATION_HANDSHAKE": ("最终模型验证未完成", "模型验证没有产生可信的完成握手。", ["检查验证日志和模型产物完整性。"]),
    }
    detected_code = primary_code
    if "lease was lost" in lowered or "execution lease" in lowered:
        detected_code = "WORKER_LEASE_LOST"
    if "database is locked" in lowered:
        detected_code = "DATABASE_LOCKED"
    if detected_code.startswith("TRAINING_MODEL_OFFLINE_") or detected_code == "TRAINING_MODEL_REMOTE_DOWNLOAD_FORBIDDEN":
        friendly[detected_code] = (
            "母模型不可用",
            "训练所需的母模型不存在、不可读或当前环境不允许下载。",
            ["检查母模型文件和 Worker 的离线模型配置。"],
        )
    if detected_code.startswith(("TRAINING_PRECISION_", "CUDA_FP16_", "AMP_REFERENCE_")):
        friendly[detected_code] = (
            "Worker 运行环境不兼容",
            "当前 Worker 环境无法满足本次训练的精度或 AMP 合同。",
            ["检查 CUDA、PyTorch、Ultralytics 与模型运行环境。"],
        )
    if detected_code.startswith(("GPU_ASSIGNMENT_", "GPU_IDENTITY_", "WORKER_CUDA_", "TRAINING_DEVICE_")):
        friendly[detected_code] = (
            "GPU 运行资源不可用",
            "当前 Worker 的 GPU 身份或可用状态不满足任务合同。",
            ["检查 GPU 分配、驱动和 Worker 资源状态。"],
        )
    if detected_code in friendly:
        title, summary, suggestions = friendly[detected_code]
        return {
            "code": detected_code,
            "certainty": "confirmed",
            "title": title,
            "summary": summary,
            "evidence": [_public_text(primary.get("primary_message")) or summary, checkpoint_message],
            "possible_causes": [],
            "suggestions": suggestions,
            "checkpoint_message": checkpoint_message,
        }
    if "memoryerror" in lowered or "cannot allocate memory" in lowered:
        return {
            "code": "HOST_MEMORY_PRESSURE_SUSPECTED",
            "certainty": "suspected",
            "title": "训练失败：疑似服务器内存压力",
            "summary": "训练错误表现符合主机内存不足，但没有与当前进程关联的 Kernel OOM 证据。",
            "evidence": ["训练错误记录到内存分配失败。", checkpoint_message],
            "possible_causes": ["服务器可用内存不足", "服务或容器内存限制", "其他进程抢占内存"],
            "suggestions": ["检查系统 OOM、Worker 和任务执行日志。", "确认内存资源后重新创建训练任务。"],
            "checkpoint_message": checkpoint_message,
        }
    if concurrent_host_oom is not None and (process_signal == "SIGKILL" or process_returncode == -9):
        return {
            "code": "HOST_OOM_CONCURRENT_UNATTRIBUTED",
            "certainty": "suspected",
            "title": "训练被强制终止：同时间窗存在主机 OOM",
            "summary": "Kernel 在本任务运行时间窗内终止了其他进程，但没有证据证明当前训练进程就是 OOM 目标。",
            "evidence": ["同一时间窗检测到其他进程的 Kernel OOM Kill。", "该事件未与当前任务 PID/生命周期匹配。", checkpoint_message],
            "possible_causes": ["其他并发任务耗尽主机内存", "当前训练被其他机制终止", "服务或容器资源限制"],
            "suggestions": ["核对同节点并发任务和 Kernel 日志。", "确认任务 PID/cgroup 证据后再判断是否为本任务 OOM。"],
            "checkpoint_message": checkpoint_message,
        }
    if process_signal == "SIGKILL" or process_returncode == -9:
        return {
            "code": "SIGKILL_CAUSE_UNKNOWN",
            "certainty": "unknown",
            "title": "训练被系统强制终止",
            "summary": "训练进程收到 SIGKILL，但目前没有足够证据确认发送者或原因。",
            "evidence": ["训练进程收到 SIGKILL（returncode=-9）。", "未找到与本任务关联的 Kernel/cgroup OOM 证据。", checkpoint_message],
            "possible_causes": ["系统内存不足", "Worker 执行权限或租约变化", "外部进程终止", "服务或容器资源限制"],
            "suggestions": ["查看系统 OOM、Worker 和任务执行日志。", "确认运行环境后重新创建训练任务。"],
            "checkpoint_message": checkpoint_message,
        }
    if detected_code == "TRAINING_PROCESS_FAILED":
        return {
            "code": detected_code,
            "certainty": "confirmed",
            "title": "训练进程异常退出",
            "summary": "训练进程未能正常完成。",
            "evidence": [_public_text(primary.get("primary_message")), checkpoint_message],
            "possible_causes": [],
            "suggestions": ["查看技术详情和 Worker 日志后重新创建任务。"],
            "checkpoint_message": checkpoint_message,
        }
    return {
        "code": primary_code or "TRAINING_FAILURE_UNCLASSIFIED",
        "certainty": "confirmed" if primary_code else "unknown",
        "title": "训练失败",
        "summary": _public_text(primary.get("primary_message")) or "当前没有足够证据确认具体原因。",
        "evidence": [checkpoint_message],
        "possible_causes": [] if primary_code else ["训练进程或运行环境异常"],
        "suggestions": ["查看技术详情和 Worker 日志后处理。"],
        "checkpoint_message": checkpoint_message,
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
    diagnosis = _failure_diagnosis(task, failure, primary, recoverable=recoverable)
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
        "diagnosis": diagnosis,
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
    agent_training_inputs_provider=None,
    project_path_provider=None,
    workspace_actor_provider=None,
):
    from fastapi import APIRouter, Body, HTTPException, Query

    recovery_router = APIRouter(prefix="/api/v62/projects/{project_id}/training-tasks")

    def require_task(project_id: str, task_id: str):
        get_project(project_id)
        task = task_repository().get(task_id)
        if task is None or task.project_id != project_id or task.kind is not TaskKind.TRAINING:
            raise HTTPException(status_code=404, detail="训练任务不存在")
        return task

    def workspace_service(project_id):
        if project_path_provider is None:
            raise HTTPException(status_code=503, detail="训练临时空间服务不可用")
        from .training_workspace_lifecycle import TrainingWorkspaceLifecycle
        return TrainingWorkspaceLifecycle(
            Path(project_path_provider(project_id)).parent.parent,
            task_repository(), task_artifacts(),
        )

    @recovery_router.get("/workspace-history")
    def workspace_history(project_id: str, after: str = "", limit: int = Query(default=20, ge=1, le=20)):
        get_project(project_id)
        return {"ok": True, **workspace_service(project_id).history_page(project_id, after=after, limit=limit)}

    @recovery_router.get("/{task_id}/workspace")
    def workspace_preview(project_id: str, task_id: str):
        require_task(project_id, task_id)
        return {"ok": True, "workspace": workspace_service(project_id).inspect(project_id, task_id)}

    @recovery_router.post("/{task_id}/workspace/cleanup")
    def workspace_cleanup(project_id: str, task_id: str, request: Request, payload: dict = Body(...)):
        require_task(project_id, task_id)
        if workspace_actor_provider is None:
            raise HTTPException(status_code=503, detail="真实登录身份服务不可用")
        actor = workspace_actor_provider(request, project_id)
        actor_id = str((actor or {}).get("actor_id") or "").strip()
        if not actor_id:
            raise HTTPException(status_code=401, detail="请先登录平台")
        if (payload.get("confirm") != "release_training_workspace"
                or type(payload.get("attempt")) is not int or not payload.get("snapshot_id")):
            raise HTTPException(status_code=422, detail="请核对临时空间预览并明确确认释放")
        try:
            result = workspace_service(project_id).cleanup(
                project_id, task_id, actor=actor_id, expected_attempt=payload["attempt"],
                expected_snapshot_id=str(payload["snapshot_id"]),
            )
        except RuntimeError as error:
            raise HTTPException(status_code=409, detail={"code": "TRAINING_WORKSPACE_PROTECTED",
                "blockers": str(error).split(","), "retryable": False}) from error
        except OSError as error:
            raise HTTPException(status_code=503, detail={"code": "TRAINING_WORKSPACE_RETRYABLE",
                "message": "临时空间释放未完成，可安全重试", "retryable": True}) from error
        return {"ok": True, "workspace": result}

    @recovery_router.get("/{task_id}/input-diagnosis")
    def input_diagnosis(project_id: str, task_id: str,
        page: int = Query(default=1, ge=1), limit: int = Query(default=24, ge=1, le=100),
        query: str = Query(default="", max_length=256), issue_type: str = Query(default="", max_length=80)):
        task = require_task(project_id, task_id)
        if project_path_provider is None:
            raise HTTPException(status_code=503, detail="训练输入诊断服务不可用")
        from .training_compatibility import compatibility_page, diagnose_training_duplicates
        from .training_tasks import _training_input_freeze_digest
        from .material_batches import _historical_material_references, BatchRequestError
        artifacts = task_artifacts()
        payload = artifacts.read_json(task_id, task.payload_ref, default={})
        frozen = artifacts.read_json(task_id, "input-freeze.json", default={})
        valid_freeze = bool(isinstance(frozen, Mapping) and frozen.get("input_freeze_id")
            and frozen.get("input_freeze_id") == _training_input_freeze_digest(frozen))
        historical = {
            "status": ("freeze_checksum_verified_not_source_revalidated" if valid_freeze else
                "insufficient_invalid_input_freeze" if frozen else "insufficient_no_input_freeze"),
            "input_freeze_id": str(frozen.get("input_freeze_id") or "") if valid_freeze else None,
            "source_error": _public_text(getattr(task, "error", "")),
            "message": ("冻结合同摘要已核验；当前素材诊断不代表历史标注。" if valid_freeze else
                "历史冻结证据不足，不能用当前标注推断失败时的完整标注。"),
            "preparation_error_recorded": isinstance(artifacts.read_json(task_id,
                "input-preparation-error.json", default=None), Mapping),
        }
        current = {"evidence_basis": "current_canonical_annotations", "available": False}
        project = Path(project_path_provider(project_id))
        try:
            result = diagnose_training_duplicates(project, payload if isinstance(payload, Mapping) else {}, current_only=True)
            current.update(available=True, **result.summary(), **compatibility_page(result, page=page, limit=limit, query=query, issue_type=issue_type))
            reasons = _historical_material_references(project_id, project, task_repository(), artifacts,
                with_reasons=True, reference_image_ids=[item["image_id"] for item in current["items"]])
            current["items"] = [{**item,
                "reference_reasons": reasons.get(item["image_id"], []),
                "protected": any(reason.get('protected', True) for reason in reasons.get(item["image_id"], [])),
                "thumbnail_url": f"/api/v62/projects/{quote(project_id, safe='')}/training-materials/{quote(item['image_id'], safe='')}/thumbnail",
                "content_url": f"/api/v61/projects/{quote(project_id, safe='')}/materials/{quote(item['image_id'], safe='')}/content",
            } for item in current["items"]]
        except (ValueError, KeyError, BatchRequestError) as error:
            current.update(available=False, message=_public_text(error))
        return {"ok": True, "task_id": task_id, "historical_evidence": historical, "current_diagnosis": current}

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
        training_inputs_provider=agent_training_inputs_provider,
    ))
    return root
