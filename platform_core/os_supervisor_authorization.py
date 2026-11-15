"""Phase 1B verification-only central CPU grant (not a launch authorization API).

The central signer and live tasks.attempt/lease validation are NOT wired yet.
The trusted public key must come from Supervisor-owned configuration, never
from an Agent payload. No process launch, GPU grant or stop receipt is enabled.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Mapping
from uuid import UUID

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

PURPOSE = "changlian-os-supervisor-cpu-grant-v1"
DOMAIN = b"changlian-os-supervisor-grant-v1\x00"
BINDING_FIELDS = frozenset({
    "task_id", "task_attempt", "worker_id", "node_id",
    "execution_lease_sha256", "gpu_uuid", "boot_id", "challenge",
    "runner_profile",
})
CLAIM_FIELDS = BINDING_FIELDS | {"purpose", "issued_at", "expires_at"}
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{7,127}")


class GrantRejected(PermissionError):
    """Unverified execution authorization: HOLD."""


@dataclass(frozen=True)
class VerifiedExecutionGrant:
    task_id: str
    task_attempt: int
    grant_digest: str
    challenge: str
    boot_id: str
    node_id: str
    worker_id: str
    execution_lease_sha256: str
    gpu_uuid: str
    runner_profile: str


def _claims_payload(claims: Mapping[str, object]) -> bytes:
    return DOMAIN + json.dumps(
        claims, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


def verify_central_execution_grant(
    envelope: object, *,
    trusted_public_key: Ed25519PublicKey,
    expected_binding: Mapping[str, object],
    now: int,
) -> VerifiedExecutionGrant:
    """Verify exact trusted journal scope, short expiry and pinned signature."""
    if (not isinstance(trusted_public_key, Ed25519PublicKey)
            or type(now) is not int or not isinstance(expected_binding, Mapping)
            or set(expected_binding) != BINDING_FIELDS):
        raise GrantRejected("CENTRAL_GRANT_TRUST_CONTEXT_MISSING_HOLD")
    if not isinstance(envelope, dict) or set(envelope) != {"claims", "signature"}:
        raise GrantRejected("CENTRAL_GRANT_ENVELOPE_INVALID_HOLD")
    claims = envelope["claims"]
    if not isinstance(claims, dict) or set(claims) != CLAIM_FIELDS:
        raise GrantRejected("CENTRAL_GRANT_SCHEMA_INVALID_HOLD")
    if claims["purpose"] != PURPOSE:
        raise GrantRejected("CENTRAL_GRANT_PURPOSE_INVALID_HOLD")
    for field in ("task_id", "node_id"):
        if not isinstance(claims[field], str) or not _ID.fullmatch(claims[field]):
            raise GrantRejected("CENTRAL_GRANT_ID_INVALID_HOLD")
    if type(claims["task_attempt"]) is not int or claims["task_attempt"] <= 0:
        raise GrantRejected("CENTRAL_GRANT_ATTEMPT_INVALID_HOLD")
    if claims["worker_id"] != "agent:" + claims["node_id"]:
        raise GrantRejected("CENTRAL_GRANT_WORKER_INVALID_HOLD")
    if not isinstance(claims["execution_lease_sha256"], str) or not re.fullmatch(
            r"[0-9a-f]{64}", claims["execution_lease_sha256"]):
        raise GrantRejected("CENTRAL_GRANT_LEASE_DIGEST_INVALID_HOLD")
    if not isinstance(claims["challenge"], str) or not re.fullmatch(
            r"[0-9a-f]{32}", claims["challenge"]):
        raise GrantRejected("CENTRAL_GRANT_CHALLENGE_INVALID_HOLD")
    if not isinstance(claims["boot_id"], str):
        raise GrantRejected("CENTRAL_GRANT_BOOT_INVALID_HOLD")
    try:
        if str(UUID(claims["boot_id"])) != claims["boot_id"]:
            raise ValueError("noncanonical boot ID")
    except ValueError as exc:
        raise GrantRejected("CENTRAL_GRANT_BOOT_INVALID_HOLD") from exc
    # Stage 1B forbids real GPU profiles until hardware ACL and runners pass.
    if claims["gpu_uuid"] != "CPU_ONLY" or claims["runner_profile"] != "fixed-cpu-v1":
        raise GrantRejected("CENTRAL_GRANT_PROFILE_NOT_ENABLED_HOLD")
    if (type(claims["issued_at"]) is not int
            or type(claims["expires_at"]) is not int
            or not 0 < claims["expires_at"] - claims["issued_at"] <= 90):
        raise GrantRejected("CENTRAL_GRANT_TIME_INVALID_HOLD")
    if not claims["issued_at"] - 5 <= now < claims["expires_at"]:
        raise GrantRejected("CENTRAL_GRANT_EXPIRED_OR_FUTURE_HOLD")
    if any(claims[k] != expected_binding[k] for k in BINDING_FIELDS):
        raise GrantRejected("CENTRAL_GRANT_SCOPE_MISMATCH_HOLD")
    signature = envelope["signature"]
    if not isinstance(signature, str) or not re.fullmatch(r"[0-9a-f]{128}", signature):
        raise GrantRejected("CENTRAL_GRANT_SIGNATURE_INVALID_HOLD")
    payload = _claims_payload(claims)
    try:
        trusted_public_key.verify(bytes.fromhex(signature), payload)
    except InvalidSignature as exc:
        raise GrantRejected("CENTRAL_GRANT_SIGNATURE_INVALID_HOLD") from exc
    return VerifiedExecutionGrant(
        task_id=claims["task_id"], task_attempt=claims["task_attempt"],
        grant_digest=hashlib.sha256(payload).hexdigest(),
        challenge=claims["challenge"], boot_id=claims["boot_id"],
        node_id=claims["node_id"], worker_id=claims["worker_id"],
        execution_lease_sha256=claims["execution_lease_sha256"],
        gpu_uuid=claims["gpu_uuid"], runner_profile=claims["runner_profile"],
    )
