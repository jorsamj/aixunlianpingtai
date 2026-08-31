from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from platform_core.task_runtime import TaskKind, TaskStatus
from platform_core.task_runtime.scheduler import HardwareUnavailableError


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


def run_deployment_test(context) -> tuple[TaskStatus, str]:
    request = context.artifacts.read_json(context.task.task_id, context.task.payload_ref, default={})
    model = Path(str(request.get("model_path") or ""))
    image = Path(str(request.get("input_path") or ""))
    output = Path(str(request.get("output_path") or ""))
    if not model.is_file():
        raise FileNotFoundError(f"测试模型不存在：{model}")
    if not image.is_file():
        raise FileNotFoundError(f"测试图片不存在：{image}")
    suffix = model.suffix.lower()
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
    command = [python_path, str(runner), "--model", str(model), "--input", str(image), "--output", str(output), "--conf", str(float(request.get("conf") or 0.25))]
    context.repository.heartbeat(context.task.task_id, context.lease.lease_token, progress=5, stage="LOADING_RUNTIME", current_item=image.name)
    started = time.perf_counter()
    with log_path.open("w", encoding="utf-8", errors="ignore") as log:
        process = subprocess.Popen(command, cwd=str(runner.parent), stdout=log, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="ignore")
        while process.poll() is None:
            if context.cancel_requested():
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                raise InterruptedError("deployment test cancelled")
            time.sleep(0.2)
    text = log_path.read_text(encoding="utf-8", errors="ignore")
    if process.returncode != 0:
        message = text[-2000:] or f"推理进程退出码 {process.returncode}"
        if suffix in {".engine"}:
            raise HardwareUnavailableError(message)
        raise RuntimeError(message)
    data = _last_json_line(text)
    if not output.is_file() or output.stat().st_size <= 0:
        raise RuntimeError("推理执行成功但没有生成结果图片")
    result = {
        **data,
        "task_id": context.task.task_id,
        "model_path": str(model),
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
        return run_deployment_test(context)


def worker_registration(_data_dir: Path):
    return {
        "handlers": {TaskKind.DEPLOYMENT_TEST: DeploymentTestHandler()},
        "capabilities": {"deployment.runtime"},
    }
