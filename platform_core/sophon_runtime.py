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

from .conversion import ConversionError


SOPHON_ENVIRONMENT_CODES = frozenset({"TPU_MLIR_NOT_FOUND", "TPU_MLIR_UNAVAILABLE"})
SOPHON_SOLUTION = "请在官方TPU-MLIR容器或独立Linux环境配置python_path/tool_root并重新检测；不要混装到训练Python。"


# Official v1.30.2 regression/chip.py; compatibility evidence, not business chips.
SOPHON_1302_FLOAT_RULES = {
    "bm1684": ["fp32"], "bm1684x": ["fp16", "fp32"], "bm1688": ["fp16", "fp32"],
    "cv186x": ["fp16", "fp32"], "bm1690": ["fp16", "fp32"], "bm1690e": ["fp16", "fp32"],
}


def sophon_chip_capabilities(probe):
    declared = set(probe.get("declared_chips") or probe.get("supported_chips") or [])
    precisions = set(probe.get("declared_precisions") or probe.get("supported_precisions") or [])
    version = str(probe.get("version") or "")
    rules = SOPHON_1302_FLOAT_RULES if re.search(r"(?<![0-9.])1\.30\.2(?:[^0-9.]|$)",version) else {
        "bm1684x":["fp16"], "bm1688":["fp16"]}
    return {chip:{"precisions":[p for p in allowed if p in precisions],
                  "chip_option":probe.get("chip_option") or "--chip",
                  "evidence":"tpu-mlir-v1.30.2-regression/chip.py" if rules is SOPHON_1302_FLOAT_RULES else "existing-verified-fp16-contract"}
            for chip,allowed in rules.items() if chip in declared and any(p in precisions for p in allowed)}


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
        for role in ("model_transform", "model_deploy"):
            cp = subprocess.run(tool_argv(python_path, role, tools[role], "--help"),
                                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
            output = (cp.stdout or "") + (cp.stderr or "")
            if cp.returncode != 0 or not output.strip():
                raise RuntimeError(f"{role}自检失败(exit={cp.returncode})：{output[-1000:]}")
            help_texts[role] = output
        # model_tool does not support --help: official builds print Usage and
        # exit nonzero. --version is its supported read-only executable probe.
        cp = subprocess.run(tool_argv(python_path, "model_tool", tools["model_tool"], "--version"),
                            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        output = (cp.stdout or "") + (cp.stderr or "")
        model_tool_version = re.search(
            r"^\s*(?:(?:TPU-MLIR|model_tool)\s+)?(?:version\s*[:=]?\s*)?v?\d+\.\d+\.\d+(?:[-+._][A-Za-z0-9]+)*(?:\s|$)",
            output, re.I | re.M)
        if cp.returncode != 0 or not model_tool_version:
            raise RuntimeError(f"model_tool --version自检失败(exit={cp.returncode})：{output[-1000:]}")
        cp = subprocess.run(tool_argv(python_path, "model_deploy", tools["model_deploy"], "--version"),
                            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        output = (cp.stdout or "") + (cp.stderr or "")
        version = re.search(r"(?<![\w.])v?\d+\.\d+(?:\.\d+)?(?:[.a-zA-Z0-9_-]*)", output)
        if cp.returncode != 0 or not version:
            raise RuntimeError("model_deploy --version未返回有效TPU-MLIR版本")
        # Only actual argparse chip choices may advertise product capabilities.
        choice = re.search(r"--(?:chip|processor)\s+\{([^}]+)\}", help_texts["model_deploy"], re.I)
        reported = {x.strip().lower() for x in choice.group(1).split(",")} if choice else set()
        quant = re.search(r"--quantize\s+\{([^}]+)\}",help_texts["model_deploy"],re.I)
        choices={p.strip().upper() for p in quant.group(1).split(",")} if quant else set()
        declared_precisions=[p for sdk,p in (("F16","fp16"),("F32","fp32"),("INT8","int8")) if sdk in choices]
        result.update(version=version.group(0),declared_chips=sorted(reported),
                      declared_precisions=declared_precisions,
                      chip_option="--processor" if choice and choice.group(0).lower().startswith("--processor") else "--chip")
        capabilities=sophon_chip_capabilities(result)
        chips=sorted(capabilities)
        if not chips:
            raise RuntimeError("工具未报告具有芯片/精度兼容证据的编译目标")
        if tools.get("run_calibration"):
            cp = subprocess.run(tool_argv(python_path, "run_calibration", tools["run_calibration"], "--help"),
                                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
            result["calibration_available"] = cp.returncode == 0
        result.update(available=True, version=version.group(0), supported_chips=chips,
                      supported_precisions=sorted({p for c in capabilities.values() for p in c["precisions"]}),
                      chip_capabilities=capabilities, error_code="", error="", solution="")
    except (OSError, subprocess.SubprocessError, RuntimeError) as error:
        result.update(error_code="TPU_MLIR_UNAVAILABLE", error=str(error)[-1500:])
    return result


def require_sophon_toolchain(resource: Mapping[str, Any], *, chip: str = "", precision: str = "") -> dict[str, Any]:
    result = probe_sophon_toolchain(resource)
    if not result["available"] or (chip and chip not in result["supported_chips"]) or (precision and precision not in result.get("chip_capabilities",{}).get(chip,{}).get("precisions",[])):
        raise ConversionError(result.get("error_code") or "TPU_MLIR_UNAVAILABLE",
                              result.get("error") or f"TPU-MLIR未确认芯片{chip}", solution=SOPHON_SOLUTION)
    return result
