"""Rockchip board/RKNNLite runtime probing for Agent hardware verification."""
from __future__ import annotations

import json
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

SUPPORTED_BOARD_CHIPS = ("rk3568", "rk3576")
DEFAULT_COMPATIBLE_PATH = Path("/proc/device-tree/compatible")


def detect_rockchip_soc(
    compatible_path: str | Path = DEFAULT_COMPATIBLE_PATH,
    *,
    machine: str | None = None,
) -> dict[str, Any]:
    architecture = str(machine or platform.machine() or "").strip().lower()
    result = {
        "supported": False,
        "chip": "",
        "architecture": architecture,
        "compatible": "",
        "error": "",
    }
    if architecture not in {"aarch64", "arm64"}:
        result["error"] = f"Rockchip board verification requires Linux arm64/aarch64, got {architecture or 'unknown'}"
        return result
    path = Path(compatible_path)
    try:
        raw = path.read_bytes()
    except OSError as error:
        result["error"] = f"cannot read {path}: {type(error).__name__}: {error}"
        return result
    compatible = raw.replace(b"\x00", b",").decode("utf-8", errors="ignore").lower()
    result["compatible"] = compatible[:2000]
    if "rk3576" in compatible:
        result.update(supported=True, chip="rk3576", error="")
    elif "rk3568" in compatible or "rk3566" in compatible:
        # RKNN-Toolkit2 uses the RK3566/RK3568 platform family.
        result.update(supported=True, chip="rk3568", error="")
    else:
        result["error"] = "device-tree compatible is not an RK3568/RK3576 board"
    return result


def probe_rknn_board_runtime(
    python_path: str | Path | None = None,
    *,
    compatible_path: str | Path = DEFAULT_COMPATIBLE_PATH,
    machine: str | None = None,
    timeout: float = 20.0,
) -> dict[str, Any]:
    board = detect_rockchip_soc(compatible_path, machine=machine)
    candidate = Path(str(python_path or sys.executable).strip()).expanduser()
    try:
        executable = candidate.resolve()
    except (OSError, RuntimeError):
        executable = candidate
    result = {
        "available": False,
        "chip": str(board.get("chip") or ""),
        "architecture": str(board.get("architecture") or ""),
        "compatible": str(board.get("compatible") or ""),
        "python_executable": str(executable),
        "rknn_lite_version": "",
        "error": str(board.get("error") or ""),
    }
    if not board.get("supported"):
        return result
    if not executable.is_file():
        result["error"] = "RKNNLite Python executable does not exist"
        return result
    script = (
        "from rknnlite.api import RKNNLite; import importlib.metadata as m,json; "
        "v=''; "
        "\nfor n in ('rknn-toolkit-lite2','rknn_toolkit_lite2'):\n"
        "  try:\n    v=m.version(n); break\n  except Exception:\n    pass\n"
        "print(json.dumps({'version':v},ensure_ascii=False))"
    )
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
        result["error"] = (completed.stderr or completed.stdout or "RKNNLite probe failed")[-2000:]
        return result
    try:
        payload = json.loads((completed.stdout or "").strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as error:
        result["error"] = f"invalid RKNNLite probe output: {error}"
        return result
    result.update(
        available=True,
        rknn_lite_version=str(payload.get("version") or "").strip(),
        error="",
    )
    return result


__all__ = [
    "DEFAULT_COMPATIBLE_PATH",
    "SUPPORTED_BOARD_CHIPS",
    "detect_rockchip_soc",
    "probe_rknn_board_runtime",
]
