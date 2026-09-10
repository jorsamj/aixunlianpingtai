from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from platform_core.task_runtime import (
    ProcessController,
    ProcessIdentity,
    TaskKind,
    TaskStatus,
    launch_process,
)


VENDOR_TARGETS = {"tensorrt", "ascend", "rockchip", "sophon"}
ENVIRONMENT_ERROR_CODES = {
    "TENSORRT_NOT_FOUND", "ATC_NOT_FOUND", "RKNN_TOOLKIT_NOT_FOUND",
    "ONNX_VALIDATION_FAILED",
}


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _board_validation_status(job: dict) -> str:
    target = str(job.get("target") or "").strip().lower()
    if target not in VENDOR_TARGETS:
        return "not_applicable"
    return "verified" if bool(job.get("hardware_verified")) else "pending"


def conversion_outcome(job: dict) -> TaskStatus:
    """Conversion success and target-board validation are separate lifecycle facts."""
    if str(job.get("status")) == "done":
        return TaskStatus.SUCCEEDED
    if str(job.get("status")) in {"stopped", "cancelled"}:
        return TaskStatus.CANCELLED
    if str(job.get("error_code")) in ENVIRONMENT_ERROR_CODES:
        return TaskStatus.BLOCKED_BY_ENVIRONMENT
    return TaskStatus.FAILED


def _result_payload(job: dict) -> dict:
    return {
        "job_id": job.get("id"),
        "status": job.get("status"),
        "conversion_status": job.get("conversion_status") or (
            "converted" if str(job.get("status")) == "done" else str(job.get("status") or "unknown")
        ),
        "target": job.get("target"),
        "exit_code": job.get("exit_code"),
        "duration_seconds": job.get("duration_seconds"),
        "manifest_path": job.get("manifest_path"),
        "outputs": job.get("outputs") or [],
        "error": job.get("error") or "",
        "error_code": job.get("error_code") or "",
        "hardware_verified": bool(job.get("hardware_verified")),
        "board_validation_status": _board_validation_status(job),
    }


def _publish_result(context, job: dict) -> tuple[TaskStatus, str]:
    status = conversion_outcome(job)
    target = str(job.get("target") or "").strip().lower()
    if status is TaskStatus.SUCCEEDED and target in VENDOR_TARGETS:
        job.update(
            conversion_status="converted",
            board_validation_status=_board_validation_status(job),
        )
        if not bool(job.get("hardware_verified")):
            job.update(
                stage="转换完成，板端待验证",
                message="模型转换产物已成功生成；目标开发板/Runtime 验证尚未完成，不影响本次转换任务成功。",
            )
    _write(Path(str(job["_job_file"])), {key: value for key, value in job.items() if key != "_job_file"})
    result_ref = "conversion/result.json"
    context.artifacts.atomic_write_json(context.task.task_id, result_ref, _result_payload(job))
    return status, result_ref


def run_conversion(context) -> tuple[TaskStatus, str]:
    request = context.artifacts.read_json(context.task.task_id, context.task.payload_ref, default={})
    job_dir = Path(str(request.get("job_dir") or "")).resolve()
    job_file = job_dir / "job.json"
    worker = Path(str(request.get("worker_path") or "")).resolve()
    if not job_file.is_file() or not worker.is_file():
        raise FileNotFoundError("转换任务或转换执行器不存在")

    # Recovery after the converter finished but before TaskRepository.finish()
    # must publish the already-produced result instead of converting again.
    existing = _read(job_file)
    if str(existing.get("status")) == "done":
        existing["_job_file"] = str(job_file)
        return _publish_result(context, existing)

    stdout_path = job_dir / "worker.stdout.log"
    command = [str(request.get("python_path") or sys.executable), str(worker), "--job-dir", str(job_dir)]
    started = time.perf_counter()
    controller = ProcessController()
    with stdout_path.open("ab") as stdout:
        launched = launch_process(
            command,
            cwd=worker.parent,
            stdout=stdout,
            stderr=subprocess.STDOUT,
        )
        context.repository.bind_process(
            context.task.task_id,
            context.lease.lease_token,
            launched.identity,
        )
        context.artifacts.atomic_write_json(
            context.task.task_id,
            "conversion/process-identity.json",
            {
                "pid": launched.identity.pid,
                "process_create_time": launched.identity.create_time,
                "process_group_id": launched.identity.process_group_id,
                "command_hash": launched.identity.command_hash,
                "launch_token": launched.identity.launch_token,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "command": command,
            },
        )
        try:
            while launched.process.poll() is None:
                job = _read(job_file)
                context.repository.heartbeat(
                    context.task.task_id,
                    context.lease.lease_token,
                    progress=float(job.get("progress") or 0),
                    stage=str(job.get("stage") or "CONVERTING"),
                    current_item=str(job.get("source_name") or ""),
                )
                if context.cancel_requested():
                    controller.terminate_tree(launched.identity)
                    job.update({
                        "status": "stopped",
                        "stage": "已停止",
                        "message": "用户取消",
                        "cancel_requested": True,
                    })
                    _write(job_file, job)
                    raise InterruptedError("conversion cancelled")
                time.sleep(0.25)
        except BaseException:
            if launched.process.poll() is None:
                controller.terminate_tree(launched.identity)
            raise

    job = _read(job_file)
    job.update({
        "exit_code": launched.process.returncode,
        "duration_seconds": round(time.perf_counter() - started, 3),
        "worker_command": command,
        "stdout_path": str(stdout_path),
        "_job_file": str(job_file),
    })
    if launched.process.returncode not in {0, None} and str(job.get("status")) == "done":
        job.update(
            status="failed",
            error_code=str(job.get("error_code") or "CONVERSION_PROCESS_FAILED"),
            error=str(job.get("error") or f"conversion worker exited {launched.process.returncode}"),
        )
    return _publish_result(context, job)


class ConversionHandler:
    def run(self, context):
        return run_conversion(context)

    def recover(self, context):
        # Never kill an unrelated process just because a PID was reused.  Only
        # a fully verified durable identity may be terminated before recovery.
        task = context.task
        if task.process_pid and task.process_create_time is not None and task.process_command_hash:
            identity = ProcessIdentity(
                task.process_pid,
                task.process_create_time,
                task.process_command_hash,
                task.process_group_id,
                task.process_launch_token,
            )
            controller = ProcessController()
            try:
                controller.inspect(identity)
            except ProcessLookupError:
                pass
            except PermissionError as error:
                raise EnvironmentError(f"CONVERSION_PROCESS_IDENTITY_UNVERIFIED: {error}") from error
            else:
                controller.terminate_tree(identity)
                context.artifacts.atomic_write_json(
                    task.task_id,
                    "conversion/recovery.json",
                    {
                        "action": "verified_process_terminated",
                        "pid": task.process_pid,
                        "at": datetime.now(timezone.utc).isoformat(),
                    },
                )
        return run_conversion(context)


def worker_registration(_data_dir: Path):
    return {
        "handlers": {TaskKind.MODEL_CONVERSION: ConversionHandler()},
        "capabilities": {"conversion.runtime"},
    }
