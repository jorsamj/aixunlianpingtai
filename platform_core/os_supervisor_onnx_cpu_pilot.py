"""Constrained existing-ONNX CPU pilot preflight; NOT an execution grant.

The central task lease, immutable workdir, OS supervisor launch, StopReceipt,
GPU-reservation release and result publication remain outside this module.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import os
import stat
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
    _verified_bytes: bytes = field(default=b"", repr=False, compare=False)



def _reject_external_data(model_bytes: bytes) -> None:
    """Walk every ONNX protobuf message, including nested graphs and sparse tensors.

    Parse from bytes: never onnx.load(path), which can resolve external files.
    """
    try:
        import onnx
    except ImportError as exc:
        raise GrantRejected("CPU_ONNX_PILOT_ONNX_PARSER_UNAVAILABLE_HOLD") from exc
    try:
        model = onnx.load_model_from_string(model_bytes)
    except Exception as exc:
        raise GrantRejected("CPU_ONNX_PILOT_ONNX_PROTO_INVALID_HOLD") from exc
    if not model.HasField("graph") or not model.graph.node:
        raise GrantRejected("CPU_ONNX_PILOT_ONNX_GRAPH_MISSING_HOLD")
    stack = [(model, 0)]
    count = 0
    while stack:
        current, depth = stack.pop()
        count += 1
        if count > 200_000 or depth > 64:
            raise GrantRejected("CPU_ONNX_PILOT_ONNX_GRAPH_LIMIT_HOLD")
        if isinstance(current, onnx.TensorProto):
            if current.data_location == onnx.TensorProto.EXTERNAL or current.external_data:
                raise GrantRejected("CPU_ONNX_PILOT_ONNX_EXTERNAL_DATA_HOLD")
        for descriptor, value in current.ListFields():
            if descriptor.type != descriptor.TYPE_MESSAGE:
                continue
            if descriptor.is_repeated:
                stack.extend((child, depth + 1) for child in value)
            else:
                stack.append((value, depth + 1))


def _pinned_source_bytes(path: Path, *, expected_size: int, sha256: str) -> bytes:
    """Open exactly once without following final symlink; bound and audit changes."""
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        initial = path.lstat()
        if not stat.S_ISREG(initial.st_mode) or initial.st_nlink != 1:
            raise GrantRejected("CPU_ONNX_PILOT_FILE_BOUNDARY_HOLD")
        fd = os.open(path, flags)
        try:
            start = os.fstat(fd)
            def signature(s):
                if os.name == "nt":
                    # Windows file metadata from lstat() and CRT fstat() can
                    # disagree after a write/replace, even for one open handle.
                    # The bounded bytes read from THIS fd must still match the
                    # central frozen SHA256 and length. This pilot grants NO OS
                    # execution authority on Windows.
                    return (s.st_size,)
                return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
            if not stat.S_ISREG(start.st_mode) or start.st_nlink != 1 or signature(initial) != signature(start):
                raise GrantRejected("CPU_ONNX_PILOT_FILE_IDENTITY_CHANGED_HOLD")
            if start.st_size != expected_size:
                raise GrantRejected("CPU_ONNX_PILOT_FILE_SIZE_MISMATCH_HOLD")
            with os.fdopen(fd, "rb", closefd=False) as stream:
                captured = stream.read(_MAX_BYTES + 1)
            if signature(start) != signature(os.fstat(fd)) or signature(start) != signature(path.lstat()):
                raise GrantRejected("CPU_ONNX_PILOT_FILE_IDENTITY_CHANGED_HOLD")
            if len(captured) != expected_size:
                raise GrantRejected("CPU_ONNX_PILOT_FILE_SIZE_MISMATCH_HOLD")
            if hashlib.sha256(captured).hexdigest() != sha256:
                raise GrantRejected("CPU_ONNX_PILOT_DIGEST_MISMATCH_HOLD")
            return captured
        finally:
            os.close(fd)
    except GrantRejected:
        raise
    except OSError as exc:
        raise GrantRejected("CPU_ONNX_PILOT_FILE_UNAVAILABLE_HOLD") from exc


def materialize_cpu_pilot_snapshot(proof: CpuOnnxPilotPreflight, *,
                                   destination_dir: Path) -> Path:
    """Exclusive local CI copy of the captured bytes, NOT a protected OS grant."""
    if (type(proof) is not CpuOnnxPilotPreflight
            or not isinstance(destination_dir, Path)
            or destination_dir.is_symlink() or not destination_dir.is_dir()
            or not proof._verified_bytes or len(proof._verified_bytes) != proof.size_bytes
            or hashlib.sha256(proof._verified_bytes).hexdigest() != proof.source_sha256):
        raise GrantRejected("CPU_ONNX_PILOT_SNAPSHOT_EVIDENCE_HOLD")
    target = destination_dir / "verified.onnx"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(target, flags, 0o400)
        try:
            with os.fdopen(fd, "wb", closefd=False) as out:
                out.write(proof._verified_bytes)
                out.flush()
                os.fsync(fd)
            if hasattr(os, "fchmod"):
                os.fchmod(fd, 0o400)
        finally:
            os.close(fd)
    except OSError as exc:
        raise GrantRejected("CPU_ONNX_PILOT_SNAPSHOT_WRITE_HOLD") from exc
    return target


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

    except GrantRejected:
        # GrantRejected inherits PermissionError/OSError. Preserve the exact
        # fail-closed reason instead of hiding it as an I/O fault.
        raise
    except (OSError, RuntimeError) as exc:
        raise GrantRejected("CPU_ONNX_PILOT_FILE_UNAVAILABLE_HOLD") from exc
    verified = _pinned_source_bytes(
        source_file, expected_size=download["size_bytes"], sha256=download["sha256"])
    _reject_external_data(verified)
    return CpuOnnxPilotPreflight(hashlib.sha256(verified).hexdigest(),
                                len(verified), params["input_size"],
                                _verified_bytes=verified)
