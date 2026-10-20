"""Read-only TPU-MLIR capability checks shared by existing conversion owners.

A runnable compiler environment is not evidence of successful compilation or board validation.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Mapping

from .conversion import SUPPORTED_SOPHON_CHIPS, ConversionError


SOPHON_ENVIRONMENT_CODES = frozenset({"TPU_MLIR_NOT_FOUND", "TPU_MLIR_UNAVAILABLE"})
SOPHON_SOLUTION = "请在官方TPU-MLIR容器或独立Linux环境配置python_path/tool_root并重新检测；不要混装到训练Python。"


def _find(paths):
    for raw in paths:
        if not raw:
            continue
        path = Path(str(raw)).expanduser()
        if path.is_file():
            return str(path.resolve())
        found = shutil.which(str(raw))
        if found:
            return found
    return ""


def find_sophon_tools(resource: Mapping[str, Any]) -> dict[str, str]:
    root = Path(str(resource.get("tool_root") or "."))
    tools = {}
    for role, name in (("model_transform", "model_transform.py"), ("model_deploy", "model_deploy.py"),
                       ("run_calibration", "run_calibration.py"), ("model_tool", "model_tool")):
        tools[role] = _find([resource.get(role + "_path"), root/name, root/"python"/"tools"/name,
                             root/"bin"/name, root/"tools"/name, name])
    return tools


def tool_argv(python_path: str, role: str, path: str, *args: str) -> list[str]:
    return ([python_path, path] if role != "model_tool" or path.endswith(".py") else [path]) + list(args)


def probe_sophon_toolchain(resource: Mapping[str, Any], *, timeout: float = 10) -> dict[str, Any]:
    tools = find_sophon_tools(resource)
    python_path = _find([resource.get("python_path")])
    result = dict(available=False, python_path=python_path, tools=tools, version="",
                  supported_chips=[], supported_precisions=[], error_code="TPU_MLIR_NOT_FOUND",
                  error="", solution=SOPHON_SOLUTION, execution_environment="configured-python",
                  calibration_available=False)
    missing = [key for key in ("model_transform", "model_deploy", "model_tool") if not tools[key]]
    if not python_path:
        missing.append("python_path（必须显式配置独立解释器）")
    if missing:
        result["error"] = "TPU-MLIR缺失：" + "、".join(missing)
        return result
    try:
        help_texts = {}
        for role in ("model_transform", "model_deploy", "model_tool"):
            cp = subprocess.run(tool_argv(python_path, role, tools[role], "--help"),
                                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
            output = (cp.stdout or "") + (cp.stderr or "")
            if cp.returncode != 0 or not output.strip():
                raise RuntimeError(f"{role}自检失败(exit={cp.returncode})：{output[-1000:]}")
            help_texts[role] = output
        cp = subprocess.run(tool_argv(python_path, "model_deploy", tools["model_deploy"], "--version"),
                            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        output = (cp.stdout or "") + (cp.stderr or "")
        version = re.search(r"\b\d+\.\d+(?:\.\d+)?(?:[.a-zA-Z0-9_-]*)", output)
        if cp.returncode != 0 or not version:
            raise RuntimeError("model_deploy --version未返回有效TPU-MLIR版本")
        # Only actual argparse chip choices may advertise product capabilities.
        choice = re.search(r"--(?:chip|processor)\s+\{([^}]+)\}", help_texts["model_deploy"], re.I)
        reported = {x.strip().lower() for x in choice.group(1).split(",")} if choice else set()
        chips = sorted(SUPPORTED_SOPHON_CHIPS.intersection(reported))
        if not chips or not re.search(r"\bF16\b", help_texts["model_deploy"], re.I):
            raise RuntimeError("工具未报告受支持的BM1684X/BM1688及F16编译选项")
        if tools.get("run_calibration"):
            cp = subprocess.run(tool_argv(python_path, "run_calibration", tools["run_calibration"], "--help"),
                                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
            result["calibration_available"] = cp.returncode == 0
        result.update(available=True, version=version.group(0), supported_chips=chips,
                      supported_precisions=["fp16"], error_code="", error="", solution="")
    except (OSError, subprocess.SubprocessError, RuntimeError) as error:
        result.update(error_code="TPU_MLIR_UNAVAILABLE", error=str(error)[-1500:])
    return result


def require_sophon_toolchain(resource: Mapping[str, Any], *, chip: str = "") -> dict[str, Any]:
    result = probe_sophon_toolchain(resource)
    if not result["available"] or (chip and chip not in result["supported_chips"]):
        raise ConversionError(result.get("error_code") or "TPU_MLIR_UNAVAILABLE",
                              result.get("error") or f"TPU-MLIR未确认芯片{chip}", solution=SOPHON_SOLUTION)
    return result
