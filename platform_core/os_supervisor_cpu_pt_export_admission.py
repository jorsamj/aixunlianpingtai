"""2D-2D2B2A: real PT->ONNX conversion INPUT admission only.

This is intentionally NOT a launch path. The central issuer and Supervisor's
journal currently only authorize fixed-cpu-v1. Never turn its signature into
permission for a PT unpickler, arbitrary worker, GPU or result upload.

No production Agent/Runner/SupervisorService imports this module.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
import re
from typing import Iterable, Mapping
from urllib.parse import urlsplit

from .node_agent_executor_runtime import RemoteExecutionLease
from .os_supervisor_authorization import GrantRejected

_TASK = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{7,127}\Z")
_NODE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_FILE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\.pt\Z")
_OUTPUT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\.onnx\Z")
_MAX_BYTES = 512 * 1024 * 1024
_PARAMS = frozenset({"input_size", "batch", "opset", "dynamic", "simplify"})
_DOWNLOAD = frozenset({"method", "url", "headers", "file_name", "size_bytes", "sha256"})
_SOURCE = frozenset({"type", "artifact_id", "download"})
_OUTPUT_FIELDS = frozenset({"type", "storage_ref", "upload_protocol"})
_PROFILE = "pt-to-onnx-cpu-untrusted-admission-v1"
_JSON_LIMIT = 4096


def _hold(code: str) -> None:
    raise GrantRejected(code + "_HOLD")


def _mapping(value: object, keys: frozenset[str], code: str) -> Mapping:
    if not isinstance(value, Mapping) or not set(value).issubset(keys):
        _hold(code)
    return value


@dataclass(frozen=True, slots=True)
class VerifiedPtBytes:
    """Exact compressed PT artifact bytes; NOT safe pickle/model trust."""

    sha256: str
    size_bytes: int
    pickle_safe: bool = False
    model_runtime_verified: bool = False
    executable_grant_available: bool = False


@dataclass(frozen=True, slots=True)
class FrozenPtExportAdmission:
    """Immutable ORIGINAL lease scope without executable commands or URLs."""

    task_id: str
    task_attempt: int
    worker_id: str
    node_id: str
    execution_lease_sha256: str
    source_sha256: str
    source_size_bytes: int
    source_name: str
    input_size: int
    batch: int
    opset: int
    dynamic: bool
    simplify: bool
    output_name: str
    profile: str = _PROFILE
    production_launch_allowed: bool = False
    gpu_allowed: bool = False
    trusted_stop_receipt_available: bool = False
    result_publish_allowed: bool = False

    @classmethod
    def from_central_lease(cls, lease: RemoteExecutionLease) -> "FrozenPtExportAdmission":
        if not isinstance(lease, RemoteExecutionLease):
            _hold("PT_EXPORT_LEASE_TYPE_UNTRUSTED")
        p = lease.payload
        if (lease.kind != "MODEL_CONVERSION"
                or not isinstance(lease.task_id, str) or not _TASK.fullmatch(lease.task_id)
                or type(lease.generation) is not int or lease.generation <= 0
                or not isinstance(lease.worker_id, str)
                or not lease.worker_id.startswith("agent:")
                or not _NODE.fullmatch(lease.worker_id[6:])
                or not isinstance(lease.lease_token, str) or not lease.lease_token
                or not isinstance(p, Mapping)
                or p.get("schema_version") != 1 or type(p.get("schema_version")) is not int
                or p.get("task_kind") != "MODEL_CONVERSION"
                or p.get("target") != "onnx"
                or p.get("transport") != "object-storage-v1"
                or set(p) != {"schema_version", "task_kind", "transport",
                              "target", "params", "source", "source_trace", "output"}):
            _hold("PT_EXPORT_TASK_SCOPE_UNTRUSTED")
        params = _mapping(p.get("params"), _PARAMS, "PT_EXPORT_PARAMS_UNTRUSTED")
        if (set(params) != _PARAMS
                or type(params.get("input_size")) is not int
                or params["input_size"] not in (32, 64, 128, 256, 320, 640, 800, 1024)
                or type(params.get("batch")) is not int or params["batch"] != 1
                or type(params.get("opset")) is not int or params["opset"] != 12
                or params.get("dynamic") is not False
                or params.get("simplify") is not False):
            _hold("PT_EXPORT_FIXED_CPU_OPTIONS_UNSUPPORTED")
        source = _mapping(p.get("source"), _SOURCE, "PT_EXPORT_SOURCE_CONTRACT_UNTRUSTED")
        download = _mapping(source.get("download"), _DOWNLOAD,
                            "PT_EXPORT_DOWNLOAD_CONTRACT_UNTRUSTED")
        trace = p.get("source_trace")
        output = _mapping(p.get("output"), _OUTPUT_FIELDS,
                          "PT_EXPORT_OUTPUT_CONTRACT_UNTRUSTED")
        if (source.get("type") != "object" or output.get("type") != "object"
                or not isinstance(trace, Mapping)
                or not isinstance(output.get("storage_ref"), Mapping)
                or output.get("upload_protocol") != "prepare-after-local-hash-v1"):
            _hold("PT_EXPORT_OBJECT_SCOPE_UNTRUSTED")
        sha, size, name = (download.get("sha256"),
                           download.get("size_bytes"), download.get("file_name"))
        if (not isinstance(sha, str) or not _SHA256.fullmatch(sha)
                or type(size) is not int or not 0 < size <= _MAX_BYTES
                or not isinstance(name, str) or not _FILE.fullmatch(name)
                or ".." in name or trace.get("sha256") != sha
                or download.get("method") != "GET"
                or not isinstance(download.get("headers"), Mapping)
                or not isinstance(download.get("url"), str)):
            _hold("PT_EXPORT_SOURCE_DIGEST_OR_TYPE_UNTRUSTED")
        url = urlsplit(download["url"])
        if (url.scheme != "https" or not url.hostname or url.username is not None
                or url.password is not None or url.fragment):
            _hold("PT_EXPORT_DOWNLOAD_URL_UNTRUSTED")
        for header_name, header_value in download["headers"].items():
            if (not isinstance(header_name, str)
                    or not isinstance(header_value, str)
                    or "\r" in header_name + header_value
                    or "\n" in header_name + header_value
                    or len(header_name) > 128 or len(header_value) > 2048):
                _hold("PT_EXPORT_DOWNLOAD_HEADER_UNTRUSTED")
        out = output["storage_ref"]
        out_name = out.get("file_name")
        if (not isinstance(out_name, str) or not _OUTPUT.fullmatch(out_name)
                or ".." in out_name):
            _hold("PT_EXPORT_OUTPUT_NAME_UNTRUSTED")
        return cls(
            task_id=lease.task_id, task_attempt=lease.generation,
            worker_id=lease.worker_id, node_id=lease.worker_id[6:],
            execution_lease_sha256=hashlib.sha256(
                lease.lease_token.encode("utf-8")).hexdigest(),
            source_sha256=sha, source_size_bytes=size, source_name=name,
            input_size=params["input_size"], batch=1, opset=12,
            dynamic=False, simplify=False, output_name=out_name,
        )

    def verify_downloaded_stream(self, chunks: Iterable[bytes]) -> VerifiedPtBytes:
        """Hash already-downloaded bytes without unpickling/untrusted deserialization."""
        if isinstance(chunks, (bytes, bytearray, str)) or not isinstance(chunks, Iterable):
            _hold("PT_EXPORT_STREAM_UNTRUSTED")
        sha = hashlib.sha256()
        size = 0
        for chunk in chunks:
            if type(chunk) is not bytes:
                _hold("PT_EXPORT_STREAM_CHUNK_UNTRUSTED")
            size += len(chunk)
            if size > self.source_size_bytes:
                _hold("PT_EXPORT_SOURCE_SIZE_MISMATCH")
            sha.update(chunk)
        if (size != self.source_size_bytes
                or not hmac.compare_digest(sha.hexdigest(), self.source_sha256)):
            _hold("PT_EXPORT_SOURCE_DIGEST_MISMATCH")
        return VerifiedPtBytes(self.source_sha256, size)

    def freeze_nonexecutable_manifest(self, verified: VerifiedPtBytes) -> bytes:
        """Canonical evidence only. No commands, URL, credentials or OS grant."""
        if (type(verified) is not VerifiedPtBytes
                or not isinstance(verified.sha256, str)
                or not hmac.compare_digest(verified.sha256, self.source_sha256)
                or type(verified.size_bytes) is not int
                or verified.size_bytes != self.source_size_bytes
                or verified.pickle_safe is not False
                or verified.model_runtime_verified is not False
                or verified.executable_grant_available is not False):
            _hold("PT_EXPORT_BYTES_NOT_FROZEN")
        doc = {
            "schema_version": 1, "profile": self.profile,
            "task_id": self.task_id, "task_attempt": self.task_attempt,
            "node_id": self.node_id, "worker_id": self.worker_id,
            "execution_lease_sha256": self.execution_lease_sha256,
            "source": {"name": self.source_name, "sha256": self.source_sha256,
                       "size_bytes": self.source_size_bytes},
            "target": {"kind": "onnx", "name": self.output_name},
            "params": {"input_size": self.input_size, "batch": self.batch,
                       "opset": self.opset, "dynamic": self.dynamic,
                       "simplify": self.simplify},
            "execution_authorized": False,
            "untrusted_pt_pickle": True,
            "business_result_verified": False,
            "trusted_stop_receipt_available": False,
            "result_publish_allowed": False,
        }
        value = json.dumps(doc, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=True, allow_nan=False).encode("ascii")
        if len(value) > _JSON_LIMIT:
            _hold("PT_EXPORT_MANIFEST_OVERSIZE")
        return value

    def request_systemd_launch(self) -> None:
        """No 2D-2D2B2 central profile issuer, journal/CAS or stop receipt yet."""
        _hold("PT_EXPORT_CENTRAL_SIGNED_PROFILE_NOT_ADMITTED")

    def request_result_publish(self) -> None:
        _hold("PT_EXPORT_RESULT_TRANSACTION_NOT_ADMITTED")
