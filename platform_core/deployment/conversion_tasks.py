from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from platform_core.task_runtime import (
    ExecutionFencedError,
    ProcessController,
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
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def conversion_outcome(job: dict) -> TaskStatus:
    if str(job.get("status")) == "done":
        if str(job.get("target")) in VENDOR_TARGETS and not bool(job.get("hardware_verified")):
            return TaskStatus.BLOCKED_BY_HARDWARE
        return TaskStatus.SUCCEEDED
    if str(job.get("status")) in {"stopped", "cancelled"}:
        return TaskStatus.CANCELLED
    if str(job.get("error_code")) in ENVIRONMENT_ERROR_CODES:
        return TaskStatus.BLOCKED_BY_ENVIRONMENT
    return TaskStatus.FAILED


def run_conversion(context) -> tuple[TaskStatus, str]:
    request = context.artifacts.read_json(context.task.task_id, context.task.payload_ref, default={})
    job_dir = Path(str(request.get("job_dir") or "")).resolve()
    job_file = job_dir / "job.json"
    worker = Path(str(request.get("worker_path") or "")).resolve()
    if not job_file.is_file() or not worker.is_file():
        raise FileNotFoundError("转换任务或转换执行器不存在")
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
        try:
            context.bind_process(launched.identity)
            while launched.process.poll() is None:
                job = _read(job_file)
                context.heartbeat(
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
                    context.assert_current_execution()
                    _write(job_file, job)
                    raise InterruptedError("conversion cancelled")
                time.sleep(0.25)
        except ExecutionFencedError:
            controller.terminate_tree(launched.identity)
            raise
        except Exception:
            if context.lease_lost:
                controller.terminate_tree(launched.identity)
            raise

    context.assert_current_execution()
    job = _read(job_file)
    job.update({
        "exit_code": launched.process.returncode,
        "duration_seconds": round(time.perf_counter() - started, 3),
        "worker_command": command,
        "stdout_path": str(stdout_path),
    })
    status = conversion_outcome(job)
    if status is TaskStatus.BLOCKED_BY_HARDWARE:
        job.update({
            "status": "blocked_by_hardware", "conversion_status": "converted",
            "stage": "等待目标硬件验证",
            "message": "转换产物已生成，但当前环境无法用目标 Runtime/芯片真实加载，不能标记为通过。",
            "hardware_verified": False,
        })
    context.assert_current_execution()
    _write(job_file, job)
    result = {
        "job_id": job.get("id"), "status": job.get("status"), "target": job.get("target"),
        "exit_code": job.get("exit_code"), "duration_seconds": job.get("duration_seconds"),
        "manifest_path": job.get("manifest_path"), "outputs": job.get("outputs") or [],
        "error": job.get("error") or "", "error_code": job.get("error_code") or "",
        "hardware_verified": bool(job.get("hardware_verified")),
    }
    result_ref = "conversion/result.json"
    context.artifacts.atomic_write_json(context.task.task_id, result_ref, result)
    return status, result_ref


class ConversionHandler:
    def run(self, context):
        return run_conversion(context)

    def recover(self, context):
        return run_conversion(context)


def worker_registration(_data_dir: Path):
    return {"handlers": {TaskKind.MODEL_CONVERSION: ConversionHandler()}, "capabilities": {"conversion.runtime"}}
