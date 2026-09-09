"""Bounded, checkpoint-independent probes for local Python environments.

The probe intentionally validates only the Python/Ultralytics/PyTorch runtime.
Checkpoint discovery and resolution belong to the model-discovery layer and
must never affect whether an otherwise healthy environment is usable.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Mapping, Sequence
from typing import Any


PROBE_TIMEOUT_SECONDS = 30.0
_MAX_ERROR_LENGTH = 2_048
_MAX_GPU_NAME_LENGTH = 512
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b([A-Z0-9_]*(?:SECRET|PASSWORD|PASSWD|TOKEN|CREDENTIAL|API[_-]?KEY|"
    r"ACCESS[_-]?KEY|PRIVATE[_-]?KEY)[A-Z0-9_]*)\s*[:=]\s*([^\s,;]+)"
)
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")


# Kept as a self-contained script so the candidate interpreter does not need
# this project on sys.path. Imports are deliberately independent: a failure in
# one component must not hide the diagnostics for the others.
_PROBE_SCRIPT = r'''
import contextlib
import io
import json
import platform
import sys


def failure(error):
    return {
        "type": type(error).__name__,
        "message": str(error),
    }


result = {
    "python_executable": sys.executable,
    "python_version": platform.python_version(),
    "ultralytics": {"ok": False, "version": "", "error": None},
    "torch": {"ok": False, "version": "", "error": None},
    "torchvision": {
        "ok": False,
        "version": "",
        "ops_ok": False,
        "error": None,
        "ops_error": None,
    },
    "cuda_available": False,
    "gpu_count": 0,
    "gpu_names": [],
    "weights_dir": None,
}

# Some packages print banners or warnings while importing. Suppress those so
# stdout contains exactly one machine-readable JSON document.
with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
    try:
        import ultralytics

        result["ultralytics"]["ok"] = True
        result["ultralytics"]["version"] = str(getattr(ultralytics, "__version__", ""))
        try:
            settings = getattr(ultralytics, "settings", None)
            if settings is not None:
                value = settings.get("weights_dir") if hasattr(settings, "get") else None
                if value is not None:
                    result["weights_dir"] = str(value)
        except Exception:
            # Settings are advisory discovery data, not an availability gate.
            pass
    except BaseException as error:
        result["ultralytics"]["error"] = failure(error)

    torch_module = None
    try:
        import torch

        torch_module = torch
        result["torch"]["ok"] = True
        result["torch"]["version"] = str(getattr(torch, "__version__", ""))
        try:
            result["cuda_available"] = bool(torch.cuda.is_available())
            if result["cuda_available"]:
                result["gpu_count"] = max(0, int(torch.cuda.device_count()))
                result["gpu_names"] = [
                    str(torch.cuda.get_device_name(index))
                    for index in range(result["gpu_count"])
                ]
        except BaseException:
            # A broken CUDA driver must not invalidate a working CPU runtime.
            result["cuda_available"] = False
            result["gpu_count"] = 0
            result["gpu_names"] = []
    except BaseException as error:
        result["torch"]["error"] = failure(error)

    torchvision_module = None
    try:
        import torchvision

        torchvision_module = torchvision
        result["torchvision"]["ok"] = True
        result["torchvision"]["version"] = str(getattr(torchvision, "__version__", ""))
    except BaseException as error:
        result["torchvision"]["error"] = failure(error)

    if torch_module is not None and torchvision_module is not None:
        try:
            boxes = torch_module.tensor([[0.0, 0.0, 10.0, 10.0]], device="cpu")
            scores = torch_module.tensor([0.9], device="cpu")
            torchvision_module.ops.nms(boxes, scores, 0.5)
            result["torchvision"]["ops_ok"] = True
        except BaseException as error:
            result["torchvision"]["ops_error"] = failure(error)

print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
'''


def _safe_text(value: object, *, limit: int = _MAX_ERROR_LENGTH) -> str:
    """Bound text and redact common credential forms from probe diagnostics."""
    text = str(value or "").replace("\x00", "")[:limit]
    text = _SECRET_ASSIGNMENT.sub(
        lambda match: f"{match.group(1)}=[REDACTED]", text
    )
    return _BEARER.sub("Bearer [REDACTED]", text)


def _safe_error(value: object) -> dict[str, str] | None:
    if not isinstance(value, Mapping):
        return None
    error_type = _safe_text(value.get("type", "Error"), limit=128) or "Error"
    message = _safe_text(value.get("message", ""))
    return {"type": error_type, "message": message}


def _module_result(value: object, *, include_ops: bool = False) -> dict[str, Any]:
    source = value if isinstance(value, Mapping) else {}
    result: dict[str, Any] = {
        "ok": bool(source.get("ok", False)),
        "version": _safe_text(source.get("version", ""), limit=256),
        "error": _safe_error(source.get("error")),
    }
    if include_ops:
        result["ops_ok"] = bool(source.get("ops_ok", False))
        result["ops_error"] = _safe_error(source.get("ops_error"))
    return result


def _unavailable(
    python_path: str,
    *,
    code: str,
    message: str,
) -> dict[str, Any]:
    components = {
        "ultralytics": {"ok": False, "version": "", "error": None},
        "torch": {"ok": False, "version": "", "error": None},
        "torchvision": {
            "ok": False,
            "version": "",
            "error": None,
            "ops_ok": False,
            "ops_error": None,
        },
    }
    return {
        "python_path": python_path,
        "python_executable": python_path,
        "python_version": "",
        **components,
        "torchvision_ops_ok": False,
        "cuda_available": False,
        "gpu_count": 0,
        "gpu_names": [],
        "weights_dir": None,
        "compatibility": {
            "compatible": False,
            "checks": {
                "ultralytics_import": False,
                "torch_import": False,
                "torchvision_import": False,
                "torchvision_ops": False,
            },
        },
        "status": "UNAVAILABLE",
        "model_status": "NOT_CHECKED",
        "error": {"code": code, "message": _safe_text(message)},
    }


def probe_python_environment(
    python_path: str | os.PathLike[str],
    *,
    timeout_seconds: float = PROBE_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Validate one candidate Python without inspecting model checkpoints.

    The subprocess inherits the candidate interpreter's normal runtime context,
    but this function never serializes, forwards explicitly, or returns process
    environment variables. Raw stdout/stderr are likewise never returned.
    """
    candidate = os.fspath(python_path).strip()
    if not candidate or "\x00" in candidate:
        return _unavailable(
            _safe_text(candidate, limit=4_096),
            code="INVALID_PYTHON_PATH",
            message="Python executable path is empty or invalid.",
        )
    try:
        timeout = float(timeout_seconds)
    except (TypeError, ValueError, OverflowError):
        timeout = PROBE_TIMEOUT_SECONDS
    if timeout <= 0:
        timeout = PROBE_TIMEOUT_SECONDS

    try:
        completed = subprocess.run(
            [candidate, "-c", _PROBE_SCRIPT],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        return _unavailable(
            candidate,
            code="PROBE_TIMEOUT",
            message=f"Python environment probe exceeded {timeout:g} seconds.",
        )
    except OSError as error:
        return _unavailable(
            candidate,
            code="PROBE_START_FAILED",
            message=f"Unable to start the Python interpreter ({type(error).__name__}).",
        )

    if completed.returncode != 0:
        return _unavailable(
            candidate,
            code="PROBE_PROCESS_FAILED",
            message=f"Python environment probe exited with code {completed.returncode}.",
        )

    try:
        payload = json.loads(completed.stdout.strip())
    except (TypeError, ValueError, json.JSONDecodeError):
        return _unavailable(
            candidate,
            code="INVALID_PROBE_OUTPUT",
            message="Python environment probe did not return valid JSON.",
        )
    if not isinstance(payload, Mapping):
        return _unavailable(
            candidate,
            code="INVALID_PROBE_OUTPUT",
            message="Python environment probe returned an invalid result shape.",
        )

    ultralytics = _module_result(payload.get("ultralytics"))
    torch = _module_result(payload.get("torch"))
    torchvision = _module_result(payload.get("torchvision"), include_ops=True)
    checks = {
        "ultralytics_import": ultralytics["ok"],
        "torch_import": torch["ok"],
        "torchvision_import": torchvision["ok"],
        "torchvision_ops": torchvision["ops_ok"],
    }
    compatible = all(checks.values())
    gpu_names_value = payload.get("gpu_names")
    gpu_names = (
        [
            _safe_text(name, limit=_MAX_GPU_NAME_LENGTH)
            for name in gpu_names_value[:64]
        ]
        if isinstance(gpu_names_value, Sequence)
        and not isinstance(gpu_names_value, (str, bytes, bytearray))
        else []
    )
    try:
        gpu_count = max(0, min(int(payload.get("gpu_count", 0)), len(gpu_names)))
    except (TypeError, ValueError, OverflowError):
        gpu_count = 0
    cuda_available = bool(payload.get("cuda_available", False)) and torch["ok"]
    if not cuda_available:
        gpu_count = 0
        gpu_names = []

    weights_dir_value = payload.get("weights_dir")
    weights_dir = (
        _safe_text(weights_dir_value, limit=4_096)
        if isinstance(weights_dir_value, (str, os.PathLike)) and weights_dir_value
        else None
    )
    python_executable = _safe_text(
        payload.get("python_executable", candidate), limit=4_096
    )
    return {
        "python_path": candidate,
        "python_executable": python_executable or candidate,
        "python_version": _safe_text(payload.get("python_version", ""), limit=256),
        "ultralytics": ultralytics,
        "torch": torch,
        "torchvision": torchvision,
        "torchvision_ops_ok": bool(torchvision["ops_ok"]),
        "cuda_available": cuda_available,
        "gpu_count": gpu_count,
        "gpu_names": gpu_names,
        "weights_dir": weights_dir,
        "compatibility": {"compatible": compatible, "checks": checks},
        "status": "AVAILABLE" if compatible else "UNAVAILABLE",
        "model_status": "NOT_CHECKED",
        "error": None,
    }


def rank_environments(
    environments: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Return every environment in deterministic recommendation order."""

    def module_ok(environment: Mapping[str, Any], name: str) -> bool:
        value = environment.get(name)
        return bool(value.get("ok", False)) if isinstance(value, Mapping) else False

    def ranking_key(environment: Mapping[str, Any]) -> tuple[Any, ...]:
        compatibility = environment.get("compatibility")
        compatible = (
            bool(compatibility.get("compatible", False))
            if isinstance(compatibility, Mapping)
            else False
        )
        available = (
            str(environment.get("status", "")).strip().upper() == "AVAILABLE"
            or compatible
        )
        torchvision = environment.get("torchvision")
        nested_ops = (
            bool(torchvision.get("ops_ok", False))
            if isinstance(torchvision, Mapping)
            else False
        )
        ops_ok = bool(environment.get("torchvision_ops_ok", nested_ops))
        import_score = sum(
            (
                module_ok(environment, "torch"),
                module_ok(environment, "torchvision"),
                module_ok(environment, "ultralytics"),
            )
        )
        path = str(
            environment.get("python_path")
            or environment.get("python_executable")
            or ""
        )
        return (
            -int(available),
            -int(bool(environment.get("cuda_available", False))),
            -int(ops_ok),
            -import_score,
            path.casefold(),
            path,
        )

    return [dict(item) for item in sorted(environments, key=ranking_key)]


__all__ = [
    "PROBE_TIMEOUT_SECONDS",
    "probe_python_environment",
    "rank_environments",
]
