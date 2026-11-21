"""2D-2D2B2B-1: CENTRAL PT->ONNX signed admission, not an OS launch grant.

The original tasks.attempt / execution lease and centrally stored conversion
request are authoritative. Agent input cannot supply the source digest, export
options, command, key, or a manifest to sign. No API, Runner or SupervisorService
imports this module, and the signature is deliberately domain-separated from
the live fixed-cpu-v1 execution authorization.
"""
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import re
import sqlite3
from typing import Mapping
from uuid import UUID

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey, Ed25519PublicKey,
)

from .os_supervisor_authorization import GrantRejected
from .os_supervisor_central_grants import _parse_utc
from .os_supervisor_cpu_pt_export_admission import (
    FrozenPtExportAdmission, VerifiedPtBytes,
)
from .service_nodes import HEARTBEAT_TTL_SECONDS, verify_service_node_token

PT_PURPOSE = "changlian-pt-export-cpu-admission-v1"
PT_DOMAIN = b"changlian-pt-export-cpu-admission-v1\x00"
PT_PROFILE = "pt-to-onnx-cpu-v1"
# An isolated, reserved CPU test resource, NOT a production conversion key.
PT_TEST_RESOURCE = "supervisor-pt-export-cpu-v1"
_MAX_GRANT_SECONDS = 15
_MAX_SOURCE_BYTES = 512 * 1024 * 1024
_TASK = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{7,127}\Z")
_NODE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_PT_FILE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\.pt\Z")
_ONNX_FILE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\.onnx\Z")
_NONCE = re.compile(r"[0-9a-f]{32}\Z")
_PARAMS = frozenset({"input_size", "batch", "opset", "dynamic", "simplify"})
_BINDING = frozenset({
    "task_id", "task_attempt", "node_id", "worker_id",
    "execution_lease_sha256", "boot_id", "challenge",
    "runner_profile", "gpu_uuid", "source_sha256", "source_size_bytes",
    "source_name", "output_name", "params", "manifest_sha256",
})
_CLAIMS = _BINDING | {"purpose", "issued_at", "expires_at"}


def _hold(code: str) -> None:
    raise GrantRejected("PT_GRANT_" + code + "_HOLD")


def _canonical(claims: Mapping[str, object]) -> bytes:
    return PT_DOMAIN + json.dumps(
        claims, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


def _uuid(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(UUID(value)) == value
    except (ValueError, AttributeError):
        return False


def _options(value: object) -> dict:
    if (not isinstance(value, Mapping) or set(value) != _PARAMS
            or type(value.get("input_size")) is not int
            or value["input_size"] not in (32, 64, 128, 256, 320, 640, 800, 1024)
            or type(value.get("batch")) is not int or value["batch"] != 1
            or type(value.get("opset")) is not int or value["opset"] != 12
            or value.get("dynamic") is not False
            or value.get("simplify") is not False):
        _hold("OPTIONS_UNTRUSTED")
    return dict(value)


def _central_source(conversion: object) -> tuple[str, int, str, str, dict]:
    """Validate the ORIGINAL central request; never accept Agent evidence."""
    if (not isinstance(conversion, Mapping)
            or set(conversion) != {
                "schema_version", "target", "source", "source_trace",
                "params", "output",
            }
            or type(conversion.get("schema_version")) is not int
            or conversion["schema_version"] != 1
            or conversion.get("target") != "onnx"):
        _hold("CENTRAL_CONVERSION_NOT_ADMITTED")
    source, trace, output = (
        conversion.get("source"), conversion.get("source_trace"),
        conversion.get("output"),
    )
    if (not isinstance(source, Mapping)
            or not isinstance(trace, Mapping)
            or not isinstance(output, Mapping)
            or source.get("type") != "object"):
        _hold("CENTRAL_SOURCE_INVALID")
    sha, size, name, output_name = (
        source.get("sha256"), source.get("size_bytes"),
        source.get("file_name"), output.get("file_name"),
    )
    if (not isinstance(sha, str) or not _SHA.fullmatch(sha)
            or trace.get("sha256") != sha
            or type(size) is not int or not 0 < size <= _MAX_SOURCE_BYTES
            or not isinstance(name, str) or not _PT_FILE.fullmatch(name)
            or ".." in name
            or not isinstance(output_name, str)
            or not _ONNX_FILE.fullmatch(output_name)
            or ".." in output_name):
        _hold("CENTRAL_SOURCE_DIGEST_OR_NAME_INVALID")
    return sha, size, name, output_name, _options(conversion.get("params"))


def _check_binding(value: Mapping[str, object]) -> None:
    if set(value) != _BINDING:
        _hold("BINDING_SCHEMA_INVALID")
    if (not isinstance(value["task_id"], str)
            or not _TASK.fullmatch(value["task_id"])
            or type(value["task_attempt"]) is not int
            or value["task_attempt"] <= 0
            or not isinstance(value["node_id"], str)
            or not _NODE.fullmatch(value["node_id"])
            or value["worker_id"] != "agent:" + value["node_id"]
            or value["runner_profile"] != PT_PROFILE
            or value["gpu_uuid"] != "CPU_ONLY"
            or not _uuid(value["boot_id"])
            or not isinstance(value["challenge"], str)
            or not _NONCE.fullmatch(value["challenge"])
            or not isinstance(value["execution_lease_sha256"], str)
            or not _SHA.fullmatch(value["execution_lease_sha256"])
            or not isinstance(value["source_sha256"], str)
            or not _SHA.fullmatch(value["source_sha256"])
            or not isinstance(value["manifest_sha256"], str)
            or not _SHA.fullmatch(value["manifest_sha256"])
            or type(value["source_size_bytes"]) is not int
            or not 0 < value["source_size_bytes"] <= _MAX_SOURCE_BYTES
            or not isinstance(value["source_name"], str)
            or not _PT_FILE.fullmatch(value["source_name"])
            or ".." in value["source_name"]
            or not isinstance(value["output_name"], str)
            or not _ONNX_FILE.fullmatch(value["output_name"])
            or ".." in value["output_name"]):
        _hold("BINDING_UNTRUSTED")
    _options(value["params"])


@dataclass(frozen=True, slots=True)
class VerifiedPtAdmissionGrant:
    task_id: str
    task_attempt: int
    node_id: str
    challenge: str
    grant_digest: str
    source_sha256: str
    manifest_sha256: str
    # This deliberately cannot be used to launch a PT unpickler.
    launch_authorized: bool = False
    result_publish_allowed: bool = False


def verify_pt_export_admission_grant(
    envelope: object, *, trusted_public_key: Ed25519PublicKey,
    expected_binding: Mapping[str, object], now: int,
) -> VerifiedPtAdmissionGrant:
    """Check a separately domain-tagged signed admission; no launch CAS."""
    if (not isinstance(trusted_public_key, Ed25519PublicKey)
            or type(now) is not int
            or not isinstance(expected_binding, Mapping)):
        _hold("TRUST_CONTEXT_MISSING")
    _check_binding(expected_binding)
    if not isinstance(envelope, dict) or set(envelope) != {"claims", "signature"}:
        _hold("ENVELOPE_INVALID")
    claims = envelope["claims"]
    if not isinstance(claims, dict) or set(claims) != _CLAIMS:
        _hold("CLAIMS_SCHEMA_INVALID")
    binding = {key: claims[key] for key in _BINDING}
    _check_binding(binding)
    if (claims["purpose"] != PT_PURPOSE
            or type(claims["issued_at"]) is not int
            or type(claims["expires_at"]) is not int
            or not 0 < claims["expires_at"] - claims["issued_at"] <= _MAX_GRANT_SECONDS
            or not claims["issued_at"] - 5 <= now < claims["expires_at"]):
        _hold("PURPOSE_OR_TIME_INVALID")
    if any(binding[key] != expected_binding[key] for key in _BINDING):
        _hold("SCOPE_MISMATCH")
    signature = envelope["signature"]
    if not isinstance(signature, str) or not re.fullmatch(r"[0-9a-f]{128}", signature):
        _hold("SIGNATURE_INVALID")
    payload = _canonical(claims)
    if len(payload) > 4096:
        _hold("PAYLOAD_TOO_LARGE")
    try:
        trusted_public_key.verify(bytes.fromhex(signature), payload)
    except InvalidSignature as exc:
        raise GrantRejected("PT_GRANT_SIGNATURE_INVALID_HOLD") from exc
    return VerifiedPtAdmissionGrant(
        task_id=claims["task_id"], task_attempt=claims["task_attempt"],
        node_id=claims["node_id"], challenge=claims["challenge"],
        grant_digest=hashlib.sha256(payload).hexdigest(),
        source_sha256=claims["source_sha256"],
        manifest_sha256=claims["manifest_sha256"],
    )


class CentralPtExportAdmissionIssuer:
    """Opt-in, read-only signer for the original central task and stored input.

    No path in the production Agent, API, model converter or OS Supervisor
    instantiates this class. The reserved resource key makes ordinary
    production MODEL_CONVERSION tasks ineligible even if enabled in a test.
    """

    def __init__(self, repository, artifacts, private_key: Ed25519PrivateKey, *,
                 pt_trial_enabled: bool = False):
        if not isinstance(private_key, Ed25519PrivateKey):
            _hold("SIGNER_UNTRUSTED")
        self.repository = repository
        self.artifacts = artifacts
        self._private_key = private_key
        self.enabled = pt_trial_enabled is True

    def issue(self, *, task_id: str, task_attempt: int, node_id: str,
              node_token: str, execution_lease_token: str,
              boot_id: str, challenge: str,
              now: datetime | None = None) -> dict:
        if not self.enabled:
            _hold("ISSUER_DISABLED")
        if (not isinstance(task_id, str) or not _TASK.fullmatch(task_id)
                or type(task_attempt) is not int or task_attempt <= 0
                or not isinstance(node_id, str) or not _NODE.fullmatch(node_id)
                or not isinstance(node_token, str) or not node_token
                or not isinstance(execution_lease_token, str)
                or not execution_lease_token
                or not _uuid(boot_id)
                or not isinstance(challenge, str)
                or not _NONCE.fullmatch(challenge)):
            _hold("REQUEST_INVALID")
        current = now if now is not None else datetime.now(timezone.utc)
        if not isinstance(current, datetime) or current.tzinfo is None:
            _hold("CLOCK_INVALID")
        current = current.astimezone(timezone.utc)
        try:
            with closing(self.repository._connect()) as database:
                # Consistent central owner / lease / node snapshot; no new
                # task attempt, grant table, worker assignment or scheduler.
                database.execute("BEGIN")
                task = database.execute(
                    """SELECT task_id,kind,status,stage,attempt,worker_id,
                              lease_token,lease_expires_at,resource_key,payload_ref
                         FROM tasks WHERE task_id=?""", (task_id,),
                ).fetchone()
                node = database.execute(
                    """SELECT node_id,connection_mode,enabled,token_hash,
                              last_heartbeat_at,allowed_capabilities,
                              reported_capabilities
                         FROM service_nodes WHERE node_id=?""", (node_id,),
                ).fetchone()
                if task is None or node is None:
                    _hold("OWNER_NOT_FOUND")
                if (task["kind"] != "MODEL_CONVERSION"
                        or task["resource_key"] != PT_TEST_RESOURCE
                        or task["status"] != "RUNNING"
                        or task["stage"] != "running"):
                    _hold("TASK_NOT_PT_TRIAL")
                if (type(task["attempt"]) is not int
                        or task["attempt"] != task_attempt
                        or task["worker_id"] != "agent:" + node_id):
                    _hold("ATTEMPT_OR_WORKER_MISMATCH")
                if (not isinstance(task["lease_token"], str)
                        or not hmac.compare_digest(
                            task["lease_token"], execution_lease_token)):
                    _hold("LEASE_MISMATCH")
                if (node["connection_mode"] != "agent"
                        or type(node["enabled"]) is not int
                        or node["enabled"] != 1
                        or not verify_service_node_token(
                            node_id, node_token, str(node["token_hash"] or ""))):
                    _hold("AGENT_NOT_AUTHORIZED")
                try:
                    allowed = set(json.loads(node["allowed_capabilities"]))
                    reported = set(json.loads(node["reported_capabilities"]))
                except (ValueError, TypeError) as exc:
                    raise GrantRejected("PT_GRANT_CAPABILITIES_INVALID_HOLD") from exc
                if "conversion" not in allowed & reported:
                    _hold("CAPABILITY_UNAVAILABLE")
                heartbeat = _parse_utc(node["last_heartbeat_at"])
                if not 0 <= (current - heartbeat).total_seconds() < HEARTBEAT_TTL_SECONDS:
                    _hold("NODE_OFFLINE")
                expires = _parse_utc(task["lease_expires_at"])
                issued_at = int(current.timestamp())
                expires_at = min(
                    int((current + timedelta(seconds=_MAX_GRANT_SECONDS)).timestamp()),
                    int(expires.timestamp()),
                )
                if expires_at <= issued_at + 2:
                    _hold("LEASE_TOO_CLOSE")
                # This is a server-owned task artifact, not a manifest or
                # source digest supplied by an Agent in the request.
                payload = self.artifacts.read_json(
                    task_id, task["payload_ref"], default=None,
                )
                if not isinstance(payload, Mapping):
                    _hold("CENTRAL_PAYLOAD_UNAVAILABLE")
                remote = payload.get("remote_execution")
                if (not isinstance(remote, Mapping)
                        or type(remote.get("version")) is not int
                        or remote["version"] != 1
                        or remote.get("task_kind") != "MODEL_CONVERSION"
                        or remote.get("transport") != "object-storage-v1"):
                    _hold("CENTRAL_REMOTE_PAYLOAD_INVALID")
                sha, size, source_name, output_name, params = _central_source(
                    remote.get("conversion"))
                lease_sha = hashlib.sha256(
                    execution_lease_token.encode("utf-8")).hexdigest()
                frozen = FrozenPtExportAdmission(
                    task_id=task_id, task_attempt=task_attempt,
                    node_id=node_id, worker_id="agent:" + node_id,
                    execution_lease_sha256=lease_sha,
                    source_sha256=sha, source_size_bytes=size,
                    source_name=source_name, output_name=output_name,
                    **params,
                )
                manifest = frozen.freeze_nonexecutable_manifest(
                    VerifiedPtBytes(sha, size))
                claims = {
                    "purpose": PT_PURPOSE, "runner_profile": PT_PROFILE,
                    "issued_at": issued_at, "expires_at": expires_at,
                    "task_id": task_id, "task_attempt": task_attempt,
                    "node_id": node_id, "worker_id": "agent:" + node_id,
                    "execution_lease_sha256": lease_sha,
                    "boot_id": boot_id, "challenge": challenge,
                    "gpu_uuid": "CPU_ONLY", "source_sha256": sha,
                    "source_size_bytes": size, "source_name": source_name,
                    "output_name": output_name, "params": params,
                    "manifest_sha256": hashlib.sha256(manifest).hexdigest(),
                }
                _check_binding({key: claims[key] for key in _BINDING})
                signed = _canonical(claims)
                if len(signed) > 4096:
                    _hold("PAYLOAD_TOO_LARGE")
                signature = self._private_key.sign(signed).hex()
                database.commit()
        except (sqlite3.Error, OSError, ValueError, TypeError, KeyError) as exc:
            raise GrantRejected("PT_GRANT_CENTRAL_EVIDENCE_UNVERIFIED_HOLD") from exc
        return {"claims": claims, "signature": signature}
