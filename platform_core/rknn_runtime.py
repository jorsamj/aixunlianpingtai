"""RKNN-Toolkit2 runtime probing shared by Agent capability and conversion paths."""
from __future__ import annotations
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

REMOTE_RKNN_CHIPS = ("rk3568", "rk3576")

def _version_tuple(value: object) -> tuple[int, int, int] | None:
    match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", str(value or ""))
    if not match:
        return None
    return tuple(int(part or 0) for part in match.groups(default="0"))

def probe_rknn_toolkit(python_path: str | Path | None = None, *, timeout: float = 20.0) -> dict[str, Any]:
    candidate = Path(str(python_path or sys.executable).strip()).expanduser()
    try:
        executable = candidate.resolve()
    except (OSError, RuntimeError):
        executable = candidate
    result = {"available": False, "python_executable": str(executable), "version": "", "supported_chips": [], "error": ""}
    if not executable.is_file():
        result["error"] = "RKNN Python executable does not exist"
        return result
    script = (
        "from rknn.api import RKNN; import importlib.metadata as m,json; "
        "print(json.dumps({'version':m.version('rknn-toolkit2')},ensure_ascii=False))"
    )
    try:
        completed = subprocess.run(
            [str(executable), "-c", script],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=max(1.0, float(timeout)), shell=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        result["error"] = f"{type(error).__name__}: {error}"
        return result
    if completed.returncode != 0:
        result["error"] = (completed.stderr or completed.stdout or "RKNN-Toolkit2 probe failed")[-2000:]
        return result
    try:
        payload = json.loads((completed.stdout or "").strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as error:
        result["error"] = f"invalid RKNN probe output: {error}"
        return result
    version = str(payload.get("version") or "").strip()
    chips = ["rk3568"]
    parsed = _version_tuple(version)
    if parsed is not None and parsed >= (2, 0, 0):
        chips.append("rk3576")
    result.update(available=True, version=version, supported_chips=chips, error="")
    return result

__all__ = ["REMOTE_RKNN_CHIPS", "probe_rknn_toolkit"]
