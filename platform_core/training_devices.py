"""Canonical training devices probed in the selected trainer interpreter."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any


def normalize_training_device(value: Any = "auto") -> str:
    device = str("auto" if value is None else value).strip().lower()
    if device in {"auto", "cpu"}:
        return device
    if re.fullmatch(r"[0-9]+", device):
        return f"cuda:{int(device)}"
    if re.fullmatch(r"cuda:[0-9]+", device):
        return f"cuda:{int(device[5:])}"
    raise ValueError("device must be auto, cpu, or cuda:N (legacy numeric GPU indices are accepted)")


def training_python(data_dir: str | Path) -> str:
    path = Path(data_dir) / "ultralytics_env.json"
    try:
        configured = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return sys.executable
    if not isinstance(configured, dict):
        raise ValueError("ultralytics_env.json must contain an object")
    # Preserve a configured executable even when missing: probing must expose
    # its failure rather than silently changing the training environment.
    return str(configured.get("python_path") or sys.executable)


_PROBE = r'''
import json, platform, sys
report = {"python_executable": sys.executable, "torch_version": None,
          "cuda_version": None, "cuda_available": False, "device_count": 0,
          "gpus": [], "cpu_name": platform.processor() or "CPU", "error": None}
try:
    import torch
    report["torch_version"] = str(torch.__version__)
    report["cuda_version"] = getattr(torch.version, "cuda", None)
    report["cuda_available"] = bool(torch.cuda.is_available())
    report["device_count"] = int(torch.cuda.device_count())
    for index in range(report["device_count"]):
        gpu = {"id": "cuda:" + str(index), "index": index, "name": None, "uuid": None}
        try:
            props = torch.cuda.get_device_properties(index)
            gpu["name"] = str(props.name)
            uuid = getattr(props, "uuid", None)
            gpu["uuid"] = str(uuid) if uuid is not None else None
        except Exception as error:
            gpu["error"] = str(error)
        report["gpus"].append(gpu)
    if len(sys.argv) > 1:
        device = sys.argv[1]
        if device.startswith("cuda:"):
            index = int(device[5:])
            if not report["cuda_available"] or index >= report["device_count"]:
                raise RuntimeError("requested CUDA index is unavailable")
            torch.empty(1, device=device)
            torch.cuda.synchronize(index)
        else:
            torch.empty(1, device="cpu")
        report["validated_device"] = device
except Exception as error:
    report["error"] = type(error).__name__ + ": " + str(error)
print("TRAINING_DEVICES_JSON=" + json.dumps(report, ensure_ascii=True))
'''


def probe_training_devices(python_executable: str, *, validate_device: str | None = None,
                           timeout: float = 30) -> dict[str, Any]:
    argv = [str(python_executable), "-c", _PROBE]
    if validate_device is not None:
        validate_device = normalize_training_device(validate_device)
        if validate_device == "auto":
            raise ValueError("GPU_ASSIGNMENT_REQUIRED: auto must be assigned by the scheduler")
        argv.append(validate_device)
    report: dict[str, Any] = {
        "python_executable": str(python_executable), "torch_version": None,
        "cuda_version": None, "cuda_available": False, "device_count": 0,
        "gpus": [], "cpu_name": "CPU", "error": None,
    }
    try:
        completed = subprocess.run(
            argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
        )
        lines = [line for line in completed.stdout.splitlines() if line.startswith("TRAINING_DEVICES_JSON=")]
        if not lines:
            raise RuntimeError((completed.stderr or completed.stdout or "probe produced no report")[-2000:])
        report.update(json.loads(lines[-1].split("=", 1)[1]))
        if completed.returncode:
            report["error"] = report.get("error") or f"probe exited {completed.returncode}"
    except (OSError, subprocess.SubprocessError, ValueError, RuntimeError) as error:
        report["error"] = str(error)
    report["requested_python_executable"] = str(python_executable)
    return report


def discover_training_devices(python_executable: str) -> dict[str, Any]:
    report = probe_training_devices(python_executable)
    gpus = [
        {**gpu, "available": bool(report["cuda_available"] and not report["error"] and not gpu.get("error")),
         "type": "cuda", "label": f"{gpu['id']} · {gpu.get('name') or 'GPU'}"}
        for gpu in report["gpus"]
    ]
    usable = [gpu for gpu in gpus if gpu["available"]]
    cpu = {"id": "cpu", "type": "cpu", "name": report["cpu_name"], "label": "CPU",
           "available": bool(report["torch_version"] and not report["error"])}
    auto = {"id": "auto", "label": "自动（优先 GPU）", "type": "auto",
            "meaning": "由调度器分配可用 GPU；无可用 CUDA 环境时选择 CPU，设备繁忙时排队等待。"}
    return {"ok": not bool(report["error"]), **report, "devices": [*gpus, cpu],
            "options": [*gpus, cpu, auto], "auto": auto,
            "recommended": "cuda:0" if any(gpu["id"] == "cuda:0" for gpu in usable) else "cpu"}


def validate_training_device(python_executable: str, assigned_device: str) -> dict[str, Any]:
    device = normalize_training_device(assigned_device)
    report = probe_training_devices(python_executable, validate_device=device)
    if report.get("error") or report.get("validated_device") != device:
        index = int(device[5:]) if device.startswith("cuda:") else None
        gpu = next((gpu for gpu in report["gpus"] if gpu["index"] == index), {})
        raise EnvironmentError(
            f"TRAINING_DEVICE_UNAVAILABLE: device={device}; executable={python_executable}; "
            f"Torch={report['torch_version']}; CUDA={report['cuda_version']}; "
            f"cuda_available={report['cuda_available']}; count={report['device_count']}; "
            f"index={index}; name={gpu.get('name') or 'unavailable'}; "
            f"{report.get('error') or 'device validation was not completed'}"
        )
    return report
