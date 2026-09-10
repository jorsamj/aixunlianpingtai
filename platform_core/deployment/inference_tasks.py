from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from platform_core.task_runtime import (
    ProcessController,
    ProcessIdentity,
    TaskKind,
    TaskStatus,
    launch_process,
)
from platform_core.task_runtime.scheduler import HardwareUnavailableError
from platform_core.resource_discovery import OFFICIAL_DOWNLOADABLE_MODELS


BOARD_ONLY = {
    ".rknn": "当前环境没有 RKNN Runtime/RK 芯片设备，无法执行真实板端测试。",
    ".om": "当前环境没有 Ascend ACL Runtime/Atlas 设备，无法执行真实板端测试。",
    ".bmodel": "当前环境没有 Sophon Runtime/算能设备，无法执行真实板端测试。",
}


def _last_json_line(text: str) -> dict[str, Any]:
    for line in reversed(text.splitlines()):
        value = line.strip()
        if value.startswith("{") and value.endswith("}"):
            return json.loads(value)
    raise RuntimeError("推理执行器没有返回结构化结果")


def _finished_result(context, request: dict[str, Any]) -> str | None:
    """Publish an already verified result after a lease/process crash boundary."""
    result = context.artifacts.read_json(context.task.task_id, "result.json", default=None)
    if not isinstance(result, dict) or str(result.get("task_id") or "") != context.task.task_id:
        return None
    output = Path(str(request.get("output_path") or ""))
    if not output.is_file() or output.stat().st_size <= 0:
        return None
    expected_size = int(result.get("output_size_bytes") or 0)
    if expected_size <= 0 or output.stat().st_size != expected_size:
        return None
    return "result.json"


def run_deployment_test(context) -> tuple[TaskStatus, str]:
    request = context.artifacts.read_json(context.task.task_id, context.task.payload_ref, default={})
    if not isinstance(request, dict):
        raise ValueError("部署测试请求无效")
    finished = _finished_result(context, request)
    if finished:
        return TaskStatus.SUCCEEDED, finished

    model_path = str(request.get("model_path") or "").strip()
    model_reference = str(request.get("model_reference") or "").strip()
    model_reference_type = str(request.get("model_reference_type") or "").strip()
    is_official_reference = model_reference_type == "official_downloadable"
    if is_official_reference:
        if model_reference.casefold() not in OFFICIAL_DOWNLOADABLE_MODELS:
            raise FileNotFoundError("官方模型引用不在平台允许列表中")
        model_argument = model_reference
        suffix = Path(model_reference).suffix.lower()
    else:
        model = Path(model_path)
        if not model.is_file():
            raise FileNotFoundError(f"测试模型不存在：{model}")
        model_argument = str(model)
        suffix = model.suffix.lower()
    image = Path(str(request.get("input_path") or ""))
    output = Path(str(request.get("output_path") or ""))
    if not image.is_file():
        raise FileNotFoundError(f"测试图片不存在：{image}")
    if suffix in BOARD_ONLY:
        raise HardwareUnavailableError(BOARD_ONLY[suffix])
    if suffix not in {".pt", ".pth", ".onnx", ".engine", ".pdparams", ".pdmodel", ".pdiparams"}:
        raise EnvironmentError(f"当前部署测试不支持 {suffix or '未知'} Runtime")
    framework = str(request.get("framework") or "ultralytics")
    runner_name = "predict_paddle_runner.py" if framework == "paddle" else "predict_ultralytics_runner.py"
    runner = Path(str(request.get("runner_path") or ""))
    if not runner.is_file() or runner.name != runner_name:
        raise EnvironmentError(f"部署测试执行器不可用：{runner_name}")
    python_path = str(request.get("python_path") or sys.executable)
    output.parent.mkdir(parents=True, exist_ok=True)
    log_ref = "logs/runtime.log"
    log_path = context.artifacts.artifact_path(context.task.task_id, log_ref)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    command = [python_path, str(runner), "--model", model_argument, "--input", str(image), "--output", str(output), "--conf", str(float(request.get("conf") or 0.25))]
    context.repository.heartbeat(context.task.task_id, context.lease.lease_token, progress=5, stage="LOADING_RUNTIME", current_item=image.name)
    started = time.perf_counter()
    launched = None
    controller = ProcessController()
    try:
        with log_path.open("w", encoding="utf-8", errors="ignore") as log:
            launched = launch_process(
                command,
                cwd=runner.parent,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="ignore",
            )
            context.repository.bind_process(
                context.task.task_id,
                context.lease.lease_token,
                launched.identity,
            )
            context.artifacts.atomic_write_json(
                context.task.task_id,
                "process-identity.json",
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
            while launched.process.poll() is None:
                if context.cancel_requested():
                    controller.terminate_tree(launched.identity)
                    raise InterruptedError("deployment test cancelled")
                context.repository.heartbeat(
                    context.task.task_id,
                    context.lease.lease_token,
                    progress=50,
                    stage="RUNNING_INFERENCE",
                    current_item=image.name,
                )
                time.sleep(0.25)
    except BaseException:
        # Lease loss / SQLite failure is also a stop condition. Do not leave an
        # unowned inference child running after another Worker may take over.
        if launched is not None and launched.process.poll() is None:
            try:
                controller.terminate_tree(launched.identity)
            except (ProcessLookupError, PermissionError):
                pass
        raise

    text = log_path.read_text(encoding="utf-8", errors="ignore")
    if launched is None:
        raise RuntimeError("推理进程未启动")
    if launched.process.returncode != 0:
        message = text[-2000:] or f"推理进程退出码 {launched.process.returncode}"
        if suffix in {".engine"}:
            raise HardwareUnavailableError(message)
        raise RuntimeError(message)
    data = _last_json_line(text)
    if not output.is_file() or output.stat().st_size <= 0:
        raise RuntimeError("推理执行成功但没有生成结果图片")
    result = {
        **data,
        "task_id": context.task.task_id,
        "model_path": model_path,
        "model_reference": model_reference,
        "model_reference_type": model_reference_type,
        "input_path": str(image),
        "output_path": str(output),
        "image_url": request.get("image_url") or "",
        "total_elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        "runtime_log_ref": log_ref,
        "output_size_bytes": output.stat().st_size,
    }
    result_ref = "result.json"
    context.artifacts.atomic_write_json(context.task.task_id, result_ref, result)
    context.repository.heartbeat(context.task.task_id, context.lease.lease_token, progress=100, stage="RUNTIME_VERIFIED", current_item=image.name)
    return TaskStatus.SUCCEEDED, result_ref


class DeploymentTestHandler:
    def run(self, context):
        return run_deployment_test(context)

    def recover(self, context):
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
                raise EnvironmentError(f"DEPLOYMENT_PROCESS_IDENTITY_UNVERIFIED: {error}") from error
            else:
                controller.terminate_tree(identity)
                context.artifacts.atomic_write_json(
                    task.task_id,
                    "recovery.json",
                    {
                        "action": "verified_process_terminated",
                        "pid": task.process_pid,
                        "at": datetime.now(timezone.utc).isoformat(),
                    },
                )
        return run_deployment_test(context)


def worker_registration(_data_dir: Path):
    return {
        "handlers": {TaskKind.DEPLOYMENT_TEST: DeploymentTestHandler()},
        "capabilities": {"deployment.runtime"},
    }
