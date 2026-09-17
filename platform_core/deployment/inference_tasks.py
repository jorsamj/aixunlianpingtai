from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from platform_core.task_runtime import (
    ExecutionFencedError,
    ProcessController,
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


def _deployment_result(
    context,
    request: dict,
    data: dict[str, Any],
    output: Path,
    *,
    total_elapsed_ms: float | None,
    recovered_from_completed_work: bool,
) -> dict[str, Any]:
    result = {
        **data,
        "task_id": context.task.task_id,
        "model_path": str(request.get("model_path") or "").strip(),
        "model_reference": str(request.get("model_reference") or "").strip(),
        "model_reference_type": str(request.get("model_reference_type") or "").strip(),
        "input_path": str(Path(str(request.get("input_path") or ""))),
        "output_path": str(output),
        "image_url": request.get("image_url") or "",
        "runtime_log_ref": "logs/runtime.log",
        "output_size_bytes": output.stat().st_size,
        "recovered_from_completed_work": bool(recovered_from_completed_work),
    }
    if total_elapsed_ms is not None:
        result["total_elapsed_ms"] = total_elapsed_ms
    elif isinstance(data.get("total_elapsed_ms"), (int, float)):
        result["total_elapsed_ms"] = data["total_elapsed_ms"]
    elif isinstance(data.get("elapsed_ms"), (int, float)):
        result["total_elapsed_ms"] = data["elapsed_ms"]
    return result


def _recover_completed_deployment_test(context) -> tuple[TaskStatus, str] | None:
    task_id = context.task.task_id
    result_ref = "result.json"
    existing = context.artifacts.read_json(task_id, result_ref, default={})
    if isinstance(existing, dict) and existing.get("task_id") == task_id:
        current_item = Path(str(existing.get("input_path") or "")).name
        context.heartbeat(progress=100, stage="RUNTIME_VERIFIED", current_item=current_item)
        return TaskStatus.SUCCEEDED, result_ref

    request = context.artifacts.read_json(task_id, context.task.payload_ref, default={})
    output_value = str(request.get("output_path") or "").strip()
    if not output_value:
        return None
    output = Path(output_value)
    log_ref = "logs/runtime.log"
    log_path = context.artifacts.artifact_path(task_id, log_ref)
    if not output.is_file() or output.stat().st_size <= 0 or not log_path.is_file():
        return None
    try:
        data = _last_json_line(log_path.read_text(encoding="utf-8", errors="ignore"))
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or not data:
        return None

    result = _deployment_result(
        context,
        request,
        data,
        output,
        total_elapsed_ms=None,
        recovered_from_completed_work=True,
    )
    context.assert_current_execution()
    context.artifacts.atomic_write_json(task_id, result_ref, result)
    current_item = Path(str(request.get("input_path") or "")).name
    context.heartbeat(progress=100, stage="RUNTIME_VERIFIED", current_item=current_item)
    return TaskStatus.SUCCEEDED, result_ref


def run_deployment_test(context) -> tuple[TaskStatus, str]:
    request = context.artifacts.read_json(context.task.task_id, context.task.payload_ref, default={})
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
    context.heartbeat(progress=5, stage="LOADING_RUNTIME", current_item=image.name)
    started = time.perf_counter()
    controller = ProcessController()
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
        try:
            context.bind_process(launched.identity)
            while launched.process.poll() is None:
                if context.cancel_requested():
                    controller.terminate_tree(launched.identity)
                    raise InterruptedError("deployment test cancelled")
                time.sleep(0.2)
        except ExecutionFencedError:
            controller.terminate_tree(launched.identity)
            raise
        except Exception:
            if context.lease_lost:
                controller.terminate_tree(launched.identity)
            raise

    context.assert_current_execution()
    text = log_path.read_text(encoding="utf-8", errors="ignore")
    if launched.process.returncode != 0:
        message = text[-2000:] or f"推理进程退出码 {launched.process.returncode}"
        if suffix in {".engine"}:
            raise HardwareUnavailableError(message)
        raise RuntimeError(message)
    data = _last_json_line(text)
    if not output.is_file() or output.stat().st_size <= 0:
        raise RuntimeError("推理执行成功但没有生成结果图片")
    result = _deployment_result(
        context,
        request,
        data,
        output,
        total_elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
        recovered_from_completed_work=False,
    )
    result_ref = "result.json"
    context.assert_current_execution()
    context.artifacts.atomic_write_json(context.task.task_id, result_ref, result)
    context.heartbeat(progress=100, stage="RUNTIME_VERIFIED", current_item=image.name)
    return TaskStatus.SUCCEEDED, result_ref


class DeploymentTestHandler:
    def run(self, context):
        return run_deployment_test(context)

    def recover(self, context):
        recovered = _recover_completed_deployment_test(context)
        if recovered is not None:
            return recovered
        return run_deployment_test(context)


def worker_registration(_data_dir: Path):
    return {
        "handlers": {TaskKind.DEPLOYMENT_TEST: DeploymentTestHandler()},
        "capabilities": {"deployment.runtime"},
    }
