"""Constrained existing-ONNX CPU pilot preflight; NOT an execution grant.

The central task lease, immutable workdir, OS supervisor launch, StopReceipt,
GPU-reservation release and result publication remain outside this module.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
from typing import Any, Mapping

from .os_supervisor_authorization import GrantRejected

_SHA = re.compile(r"[0-9a-f]{64}\Z")
_FILE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,126}\.onnx\Z")
_MAX_BYTES = 64 * 1024 * 1024
_FIELDS = {"schema_version", "task_kind", "transport", "target",
           "params", "source", "source_trace", "output"}
_PARAMS = {"input_size", "batch", "opset", "dynamic", "simplify", "precision"}


@dataclass(frozen=True)
class CpuOnnxPilotPreflight:
    source_sha256: str
    size_bytes: int
    input_size: int
    runner_profile: str = "onnx-cpu-validate-v1"
    production_launch_allowed: bool = False
    hardware_verified: bool = False
    trusted_stop_receipt_available: bool = False


def preflight_existing_onnx_cpu_pilot(
    payload: Mapping[str, Any], *, source_file: Path, trusted_workdir: Path,
) -> CpuOnnxPilotPreflight:
    """Validate narrow business input; DO NOT start processes or grant trust."""
    if (not isinstance(payload, Mapping)
            or set(payload) != _FIELDS
            or type(payload.get("schema_version")) is not int
            or payload["schema_version"] != 1
            or payload.get("task_kind") != "MODEL_CONVERSION"
            or payload.get("transport") != "object-storage-v1"
            or payload.get("target") != "onnx"):
        raise GrantRejected("CPU_ONNX_PILOT_SCOPE_UNSUPPORTED_HOLD")
    params = payload.get("params")
    if (not isinstance(params, Mapping) or set(params) != _PARAMS
            or type(params.get("input_size")) is not int
            or params["input_size"] not in (32, 64, 128, 256, 320, 640)
            or type(params.get("batch")) is not int or params["batch"] != 1
            or type(params.get("opset")) is not int or params["opset"] != 12
            or params.get("dynamic") is not False
            or params.get("simplify") is not False
            or params.get("precision") != "fp32"):
        raise GrantRejected("CPU_ONNX_PILOT_PARAMS_UNSUPPORTED_HOLD")
    source = payload.get("source")
    trace = payload.get("source_trace")
    output = payload.get("output")
    if (not isinstance(source, Mapping) or source.get("type") != "object"
            or not isinstance(trace, Mapping) or not isinstance(output, Mapping)
            or output.get("type") != "object"
            or output.get("upload_protocol") != "prepare-after-local-hash-v1"
            or not isinstance(output.get("storage_ref"), Mapping)):
        raise GrantRejected("CPU_ONNX_PILOT_STORAGE_CONTRACT_HOLD")
    download = source.get("download")
    if (not isinstance(download, Mapping) or download.get("method") != "GET"
            or not isinstance(download.get("file_name"), str)
            or not _FILE.fullmatch(download["file_name"])
            or not isinstance(download.get("sha256"), str)
            or not _SHA.fullmatch(download["sha256"])
            or trace.get("sha256") != download["sha256"]
            or type(download.get("size_bytes")) is not int
            or not 0 < download["size_bytes"] <= _MAX_BYTES):
        raise GrantRejected("CPU_ONNX_PILOT_SOURCE_EVIDENCE_HOLD")
    if not isinstance(source_file, Path) or not isinstance(trusted_workdir, Path):
        raise GrantRejected("CPU_ONNX_PILOT_PATH_TYPE_HOLD")
    try:
        if (trusted_workdir.is_symlink() or not trusted_workdir.is_dir()
                or (trusted_workdir / "input").is_symlink()
                or source_file.is_symlink() or not source_file.is_file()
                or source_file.name != download["file_name"]
                or source_file.parent != trusted_workdir / "input"
                or source_file.resolve(strict=True).parent !=
                    (trusted_workdir / "input").resolve(strict=True)):
            raise GrantRejected("CPU_ONNX_PILOT_FILE_BOUNDARY_HOLD")
        actual_size = source_file.stat().st_size
        if actual_size != download["size_bytes"]:
            raise GrantRejected("CPU_ONNX_PILOT_FILE_SIZE_MISMATCH_HOLD")
        digest = hashlib.sha256()
        with source_file.open("rb") as fp:
            for part in iter(lambda: fp.read(1024 * 1024), b""):
                digest.update(part)
        if digest.hexdigest() != download["sha256"]:
            raise GrantRejected("CPU_ONNX_PILOT_DIGEST_MISMATCH_HOLD")
    except (OSError, RuntimeError) as exc:
        raise GrantRejected("CPU_ONNX_PILOT_FILE_UNAVAILABLE_HOLD") from exc
    return CpuOnnxPilotPreflight(digest.hexdigest(), actual_size,
                                params["input_size"])
