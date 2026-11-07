"""Cross-platform Node Agent resource sampling and heartbeat transport."""
from __future__ import annotations

import csv
import io
import os
import platform
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

import psutil
import requests

from .training_devices import probe_training_devices, training_python


AGENT_PROTOCOL_VERSION = "node-agent-v1"


def _number(value: object, *, multiplier: int = 1) -> int | None:
    text = str(value or "").strip()
    if not text or text.upper() in {"N/A", "NA", "[NOT SUPPORTED]"}:
        return None
    try:
        return int(float(text) * multiplier)
    except ValueError:
        return None


def parse_nvidia_smi_gpus(text: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for row in csv.reader(io.StringIO(str(text or ""))):
        if len(row) < 7:
            continue
        index = _number(row[0])
        if index is None:
            continue
        items.append({
            "index": index,
            "id": f"cuda:{index}",
            "uuid": row[1].strip() or None,
            "name": row[2].strip() or None,
            "memory_total_bytes": _number(row[3], multiplier=1024 * 1024),
            "memory_used_bytes": _number(row[4], multiplier=1024 * 1024),
            "memory_free_bytes": _number(row[5], multiplier=1024 * 1024),
            "utilization_percent": _number(row[6]),
            "temperature_c": _number(row[7]) if len(row) > 7 else None,
        })
    return items


def parse_nvidia_smi_processes(text: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for row in csv.reader(io.StringIO(str(text or ""))):
        if len(row) < 4:
            continue
        pid = _number(row[0])
        if pid is None:
            continue
        items.append({
            "pid": pid,
            "gpu_uuid": row[1].strip() or None,
            "used_memory_bytes": _number(row[2], multiplier=1024 * 1024),
            "process_name": row[3].strip(),
        })
    return items


def _run_nvidia_smi(arguments: list[str], *, timeout: float = 5.0) -> str:
    completed = subprocess.run(
        ["nvidia-smi", *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=max(1.0, float(timeout)),
        env=os.environ.copy(),
        shell=False,
    )
    if completed.returncode:
        raise OSError((completed.stderr or completed.stdout or "nvidia-smi failed")[-2000:])
    return completed.stdout


def collect_gpu_snapshot() -> dict[str, Any]:
    result: dict[str, Any] = {"available": False, "gpus": [], "processes": [], "error": None}
    try:
        output = _run_nvidia_smi([
            "--query-gpu=index,uuid,name,memory.total,memory.used,memory.free,utilization.gpu,temperature.gpu",
            "--format=csv,noheader,nounits",
        ])
        result["gpus"] = parse_nvidia_smi_gpus(output)
        result["available"] = bool(result["gpus"])
        try:
            process_output = _run_nvidia_smi([
                "--query-compute-apps=pid,gpu_uuid,used_memory,process_name",
                "--format=csv,noheader,nounits",
            ])
            result["processes"] = parse_nvidia_smi_processes(process_output)
        except (OSError, subprocess.SubprocessError):
            result["processes"] = []
    except (OSError, subprocess.SubprocessError) as error:
        result["error"] = f"{type(error).__name__}: {error}"
    return result


def collect_runtime_probe(data_dir: str | Path | None = None) -> dict[str, Any]:
    try:
        executable = training_python(Path(data_dir)) if data_dir is not None else sys.executable
        report = probe_training_devices(executable, timeout=20)
    except Exception as error:
        return {
            "python_executable": sys.executable,
            "torch_version": None,
            "cuda_version": None,
            "cuda_available": False,
            "device_count": 0,
            "error": f"{type(error).__name__}: {error}",
        }
    return {
        "python_executable": str(report.get("python_executable") or executable),
        "requested_python_executable": str(report.get("requested_python_executable") or executable),
        "torch_version": report.get("torch_version"),
        "cuda_version": report.get("cuda_version"),
        "cuda_available": bool(report.get("cuda_available")),
        "device_count": int(report.get("device_count") or 0),
        "error": report.get("error"),
    }


def _disk_root(value: str | Path | None) -> Path:
    candidate = Path(value).expanduser() if value is not None else Path.cwd()
    try:
        resolved = candidate.resolve()
    except OSError:
        resolved = Path.cwd().resolve()
    if resolved.exists():
        return resolved
    anchor = Path(resolved.anchor) if resolved.anchor else Path.cwd().resolve()
    return anchor if anchor.exists() else Path.cwd().resolve()


def collect_local_snapshot(
    *,
    data_dir: str | Path | None = None,
    runtime_probe: dict[str, Any] | None = None,
) -> dict[str, Any]:
    memory = psutil.virtual_memory()
    disk_path = _disk_root(data_dir)
    disk = psutil.disk_usage(str(disk_path))
    process = psutil.Process(os.getpid())
    process_memory = process.memory_info()
    process_state: dict[str, Any] = {
        "pid": process.pid,
        "rss_bytes": int(process_memory.rss),
        "vms_bytes": int(process_memory.vms),
        "threads": int(process.num_threads()),
    }
    try:
        process_state["open_files"] = len(process.open_files())
    except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
        process_state["open_files"] = None
    if hasattr(process, "num_fds"):
        try:
            process_state["file_descriptors"] = int(process.num_fds())
        except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
            process_state["file_descriptors"] = None
    if hasattr(process, "num_handles"):
        try:
            process_state["handles"] = int(process.num_handles())
        except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
            process_state["handles"] = None
    gpu = collect_gpu_snapshot()
    return {
        "sampled_at": datetime.now(timezone.utc).isoformat(),
        "host": {
            "hostname": socket.gethostname(),
            "os_name": platform.system(),
            "os_version": platform.version(),
            "architecture": platform.machine(),
            "python_version": platform.python_version(),
        },
        "resources": {
            "cpu": {
                "physical_cores": psutil.cpu_count(logical=False),
                "logical_cores": psutil.cpu_count(logical=True),
                "usage_percent": float(psutil.cpu_percent(interval=None)),
            },
            "memory": {
                "total_bytes": int(memory.total),
                "available_bytes": int(memory.available),
                "used_bytes": int(memory.used),
                "usage_percent": float(memory.percent),
            },
            "disk": {
                "path": str(disk_path),
                "total_bytes": int(disk.total),
                "used_bytes": int(disk.used),
                "free_bytes": int(disk.free),
                "usage_percent": float(disk.percent),
            },
            "gpu": gpu,
        },
        "runtime": dict(runtime_probe or collect_runtime_probe(data_dir)),
        "process": process_state,
    }


def normalize_agent_capabilities(values: Iterable[str]) -> list[str]:
    from .service_nodes import SUPPORTED_NODE_CAPABILITIES

    supported = set(SUPPORTED_NODE_CAPABILITIES)
    normalized = sorted({str(value or "").strip().lower() for value in values if str(value or "").strip()})
    unknown = [value for value in normalized if value not in supported]
    if unknown:
        raise ValueError("unsupported node capabilities: " + ", ".join(unknown))
    return normalized


def build_heartbeat_payload(
    snapshot: dict[str, Any],
    *,
    capabilities: Iterable[str],
    build_id: str,
    active_tasks: Iterable[str] = (),
    last_error: str = "",
) -> dict[str, Any]:
    host = dict(snapshot.get("host") or {})
    return {
        "hostname": str(host.get("hostname") or ""),
        "os_name": str(host.get("os_name") or ""),
        "os_version": str(host.get("os_version") or ""),
        "architecture": str(host.get("architecture") or ""),
        "agent_version": AGENT_PROTOCOL_VERSION,
        "build_id": str(build_id or ""),
        "reported_capabilities": normalize_agent_capabilities(capabilities),
        "resources": dict(snapshot.get("resources") or {}),
        "runtime": dict(snapshot.get("runtime") or {}),
        "process": dict(snapshot.get("process") or {}),
        "active_tasks": list(dict.fromkeys(str(task) for task in active_tasks if str(task))),
        "last_error": str(last_error or ""),
    }


def send_heartbeat(
    control_plane_url: str,
    node_id: str,
    token: str,
    payload: dict[str, Any],
    *,
    session: requests.Session | None = None,
    timeout: float = 10.0,
) -> dict[str, Any]:
    base = str(control_plane_url or "").strip().rstrip("/")
    parsed = urlparse(base)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("control plane URL must be an absolute http(s) URL")
    key = str(node_id or "").strip()
    secret = str(token or "").strip()
    if not key or not secret:
        raise ValueError("node_id and token are required")
    client = session or requests.Session()
    response = client.post(
        f"{base}/api/v63/service-nodes/{key}/heartbeat",
        headers={"Authorization": f"Bearer {secret}"},
        json=payload,
        timeout=max(1.0, float(timeout)),
    )
    try:
        body = response.json()
    except ValueError:
        body = {}
    if not response.ok:
        detail = body.get("detail") if isinstance(body, dict) else None
        if isinstance(detail, dict):
            detail = detail.get("message") or detail.get("code")
        raise RuntimeError(str(detail or f"HTTP {response.status_code}"))
    if not isinstance(body, dict):
        raise RuntimeError("control plane returned a non-object heartbeat response")
    return body


__all__ = [
    "AGENT_PROTOCOL_VERSION",
    "build_heartbeat_payload",
    "collect_gpu_snapshot",
    "collect_local_snapshot",
    "collect_runtime_probe",
    "normalize_agent_capabilities",
    "parse_nvidia_smi_gpus",
    "parse_nvidia_smi_processes",
    "send_heartbeat",
]
