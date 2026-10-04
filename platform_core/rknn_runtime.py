"""RKNN-Toolkit2 runtime probing shared by Agent capability and conversion paths."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REMOTE_RKNN_CHIPS = ("rk3568", "rk3576")


def probe_rknn_toolkit(
    python_path: str | Path | None = None,
    *,
    timeout: float = 20.0,
) -> dict[str, Any]:
    candidate = Path(str(python_path or sys.executable).strip()).expanduser()
    try:
        executable = candidate.resolve()
    except (OSError, RuntimeError):
        executable = candidate
    result = {
        "available": False,
        "python_executable": str(executable),
        "version": "",
        "supported_chips": [],
        "error": "",
    }
    if not executable.is_file():
        result["error"] = "RKNN Python executable does not exist"
        return result

    script = """
import importlib.metadata as metadata
import json
from rknn.api import RKNN

chips = []
for chip in ("rk3568", "rk3576"):
    runtime = RKNN(verbose=False)
    try:
        code = runtime.config(target_platform=chip)
        if code in (None, 0):
            chips.append(chip)
    except Exception:
        pass
    finally:
        try:
            runtime.release()
        except Exception:
            pass

print(json.dumps({
    "version": metadata.version("rknn-toolkit2"),
    "supported_chips": chips,
}, ensure_ascii=False))
""".strip()

    try:
        completed = subprocess.run(
            [str(executable), "-c", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(1.0, float(timeout)),
            shell=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        result["error"] = f"{type(error).__name__}: {error}"
        return result
    if completed.returncode != 0:
        result["error"] = (
            completed.stderr
            or completed.stdout
            or "RKNN-Toolkit2 probe failed"
        )[-2000:]
        return result
    try:
        payload = json.loads((completed.stdout or "").strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as error:
        result["error"] = f"invalid RKNN probe output: {error}"
        return result

    version = str(payload.get("version") or "").strip()
    reported = {
        str(value or "").strip().lower()
        for value in (payload.get("supported_chips") or [])
    }
    chips = [chip for chip in REMOTE_RKNN_CHIPS if chip in reported]
    if not chips:
        result["version"] = version
        result["error"] = (
            "RKNN-Toolkit2 imported but neither rk3568 nor rk3576 "
            "passed target_platform config probing"
        )
        return result
    result.update(
        available=True,
        version=version,
        supported_chips=chips,
        error="",
    )
    return result


__all__ = ["REMOTE_RKNN_CHIPS", "probe_rknn_toolkit"]
