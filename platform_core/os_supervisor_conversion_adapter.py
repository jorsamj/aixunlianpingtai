"""2D-2D1 isolated conversion admission and read-only OS observer.

NOT imported by the production Node Agent or conversion Runner. No systemd
launch, arbitrary command, GPU assignment, stop receipt or result publication.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import re
from typing import Iterable, Mapping

from .node_agent_executor_runtime import RemoteExecutionLease
from .os_supervisor_cpu_network_pilot import IsolatedCpuNetworkPilot
from .os_supervisor_protocol import SupervisedProcessHandle, SupervisorProtocolError

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{7,127}\Z")
_NODE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_ONNX_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,235}\.onnx\Z")
_HANDLE = re.compile(r"[0-9a-f]{32}\Z")
_MAX_SOURCE_BYTES = 1024 * 1024 * 1024
_FORBIDDEN_KEYS = frozenset({
    "argv", "command", "shell", "cwd", "env", "unit", "executable",
    "script", "pid", "gpu_uuid", "gpu_ids", "device_ids", "runner_profile",
})


def _hold(code: str) -> None:
    raise SupervisorProtocolError(code + "_HOLD")


@dataclass(frozen=True, slots=True)
class FrozenOnnxInput:
    """Immutable central lease metadata, NOT an OS capability."""

    task_id: str
    task_attempt: int
    worker_id: str
    node_id: str
    lease_sha256: str
    source_sha256: str
    source_size_bytes: int
    source_name: str
    profile: str = "onnx-cpu-readonly-v1"

    @classmethod
    def from_lease(cls, lease: RemoteExecutionLease) -> "FrozenOnnxInput":
        if not isinstance(lease, RemoteExecutionLease):
            _hold("CONVERSION_LEASE_TYPE_INVALID")
        p = lease.payload
        if (lease.kind != "MODEL_CONVERSION"
                or not isinstance(lease.task_id, str)
                or not _ID.fullmatch(lease.task_id)
                or type(lease.generation) is not int or lease.generation <= 0
                or not isinstance(lease.worker_id, str)
                or not lease.worker_id.startswith("agent:")
                or not _NODE.fullmatch(lease.worker_id[6:])
                or not isinstance(lease.lease_token, str) or not lease.lease_token
                or not isinstance(p, Mapping)
                or type(p.get("schema_version")) is not int
                or p["schema_version"] != 1
                or p.get("task_kind") != "MODEL_CONVERSION"
                or p.get("transport") != "object-storage-v1"
                or p.get("target") != "onnx"
                or p.get("calibration") is not None):
            _hold("CONVERSION_READONLY_SCOPE_INVALID")
        source = p.get("source")
        trace = p.get("source_trace")
        output = p.get("output")
        params = p.get("params", {})
        if (not isinstance(source, Mapping)
                or not isinstance(trace, Mapping)
                or not isinstance(output, Mapping)
                or not isinstance(params, Mapping)
                or not isinstance(source.get("download"), Mapping)
                or not isinstance(output.get("storage_ref"), Mapping)):
            _hold("CONVERSION_READONLY_SOURCE_CONTRACT_INVALID")
        download = source["download"]
        if any(_FORBIDDEN_KEYS.intersection(scope) for scope in
               (p, source, download, params, output, output["storage_ref"])):
            _hold("CONVERSION_READONLY_COMMAND_FIELD_DENIED")
        name, sha, size = (download.get("file_name"),
                           download.get("sha256"), download.get("size_bytes"))
        if (source.get("type") != "object"
                or output.get("type") != "object"
                or output.get("upload_protocol") != "prepare-after-local-hash-v1"
                or download.get("method") != "GET"
                or not isinstance(name, str)
                or not _ONNX_NAME.fullmatch(name) or ".." in name
                or not isinstance(sha, str) or not _SHA.fullmatch(sha)
                or trace.get("sha256") != sha
                or type(size) is not int or not 0 < size <= _MAX_SOURCE_BYTES):
            _hold("CONVERSION_READONLY_SOURCE_EVIDENCE_INVALID")
        return cls(
            task_id=lease.task_id, task_attempt=lease.generation,
            worker_id=lease.worker_id, node_id=lease.worker_id[6:],
            lease_sha256=hashlib.sha256(lease.lease_token.encode("utf-8")).hexdigest(),
            source_sha256=sha, source_size_bytes=size, source_name=name,
        )

    def verify_source_stream(self, chunks: Iterable[bytes]) -> "VerifiedOnnxBytes":
        """Verify already-downloaded bytes only; never follow source URLs."""
        if not isinstance(chunks, Iterable) or isinstance(chunks, (bytes, str)):
            _hold("CONVERSION_SOURCE_STREAM_INVALID")
        digest = hashlib.sha256()
        count = 0
        for chunk in chunks:
            if type(chunk) is not bytes:
                _hold("CONVERSION_SOURCE_CHUNK_INVALID")
            count += len(chunk)
            if count > self.source_size_bytes:
                _hold("CONVERSION_SOURCE_SIZE_MISMATCH")
            digest.update(chunk)
        if (count != self.source_size_bytes
                or not hmac.compare_digest(digest.hexdigest(), self.source_sha256)):
            _hold("CONVERSION_SOURCE_DIGEST_MISMATCH")
        return VerifiedOnnxBytes(self.source_sha256, count)


@dataclass(frozen=True, slots=True)
class VerifiedOnnxBytes:
    source_sha256: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class ConversionOsObservation:
    """OS exit_code=0 never establishes business-level conversion success."""

    os_state: str
    os_exit_code: int | None
    business_result_verified: bool = False
    production_launch_allowed: bool = False
    result_publish_allowed: bool = False
    trusted_stop_receipt_available: bool = False


@dataclass(frozen=True, slots=True)
class SupervisedConversionHandle:
    """Bound original attempt read-only observer; deliberately NOT a Popen."""

    frozen_input: FrozenOnnxInput
    os_handle: SupervisedProcessHandle

    @classmethod
    def bind_isolated_cpu_pilot(
            cls, lease: RemoteExecutionLease, pilot: IsolatedCpuNetworkPilot,
            verified: VerifiedOnnxBytes) -> "SupervisedConversionHandle":
        identity = FrozenOnnxInput.from_lease(lease)
        if (not isinstance(pilot, IsolatedCpuNetworkPilot)
                or type(verified) is not VerifiedOnnxBytes
                or not isinstance(verified.source_sha256, str)
                or not hmac.compare_digest(verified.source_sha256, identity.source_sha256)
                or verified.size_bytes != identity.source_size_bytes
                or pilot.task_id != identity.task_id
                or pilot.generation != identity.task_attempt
                or pilot.node_id != identity.node_id
                or not isinstance(pilot.execution_lease_token, str)
                or not hmac.compare_digest(
                    hashlib.sha256(pilot.execution_lease_token.encode("utf-8")).hexdigest(),
                    identity.lease_sha256)
                or pilot._launch_attempted is not True
                or not isinstance(pilot.handle, SupervisedProcessHandle)
                or pilot.handle.client is not pilot.supervisor
                or pilot.handle.execution_generation != identity.task_attempt
                or not isinstance(pilot.handle.handle_id, str)
                or not _HANDLE.fullmatch(pilot.handle.handle_id)):
            _hold("CONVERSION_OS_HANDLE_BINDING_UNVERIFIED")
        return cls(identity, pilot.handle)

    def observe(self) -> ConversionOsObservation:
        code = self.os_handle.poll()  # UNKNOWN/transport failure -> HOLD
        if code is None:
            return ConversionOsObservation("RUNNING_OR_STARTING", None)
        return ConversionOsObservation("EXITED", code)

    def read_log_page(self, cursor: str | None = None) -> dict:
        return self.os_handle.read_log_page(cursor)

    def request_stop(self) -> None:
        _hold("CONVERSION_STOP_RECEIPT_UNAVAILABLE")

    def publish_result(self) -> None:
        _hold("CONVERSION_RESULT_NOT_VERIFIED")
