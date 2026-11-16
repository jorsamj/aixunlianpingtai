"""2C-03C: signed CENTRAL PT stop authorization bound to ORIGINAL task/lease.

This is a DISABLED contract and cannot stop a process or issue StopReceipt.
No production Runner, API or SupervisorService imports or instantiates it.
The central read-only signer is test-opt-in and uses existing TaskRepository.
A stop grant never gives launch, result-publish or central-recovery rights.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
import sqlite3
from typing import Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey, Ed25519PublicKey,
)

from .os_supervisor_authorization import GrantRejected
from .os_supervisor_central_grants import _parse_utc
from .os_supervisor_pt_export_grant import (
    PT_TEST_RESOURCE, _TASK, _NODE, _uuid, _NONCE,
)

STOP_PURPOSE = "changlian-pt-export-stop-central-rechecked-v1"
_STOP_DOMAIN = b"changlian-pt-export-stop-central-rechecked-v1\x00"
_STOP_FIELDS = frozenset({
    "purpose", "task_id", "task_attempt", "node_id", "worker_id",
    "execution_lease_sha256", "boot_id", "handle_id", "unit_name",
    "invocation_id", "control_group", "main_pid", "challenge", "reason",
    "issued_at", "expires_at",
})
_HANDLE = re.compile(r"[0-9a-f]{32}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_STOP_REASONS = frozenset({"CANCEL_REQUESTED", "LEASE_EXPIRED_HELD"})
_MAX_SECONDS = 12


def _hold(code: str) -> None:
    raise GrantRejected("PT_STOP_GRANT_" + code + "_HOLD")


def _payload(claims: Mapping[str, object]) -> bytes:
    return _STOP_DOMAIN + json.dumps(
        claims, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


def _check(claims: object) -> None:
    if not isinstance(claims, dict) or set(claims) != _STOP_FIELDS:
        _hold("CLAIMS_SCHEMA_INVALID")
    if (claims["purpose"] != STOP_PURPOSE
            or not isinstance(claims["task_id"], str)
            or not _TASK.fullmatch(claims["task_id"])
            or type(claims["task_attempt"]) is not int
            or claims["task_attempt"] <= 0
            or not isinstance(claims["node_id"], str)
            or not _NODE.fullmatch(claims["node_id"])
            or claims["worker_id"] != "agent:" + claims["node_id"]
            or not isinstance(claims["execution_lease_sha256"], str)
            or not _SHA.fullmatch(claims["execution_lease_sha256"])
            or not _uuid(claims["boot_id"])
            or not isinstance(claims["handle_id"], str)
            or not _HANDLE.fullmatch(claims["handle_id"])
            or claims["unit_name"] != "changlian-os-" + claims["handle_id"] + ".service"
            or not isinstance(claims["invocation_id"], str)
            or not _HANDLE.fullmatch(claims["invocation_id"])
            or claims["invocation_id"] == "0" * 32
            or claims["control_group"] != "/system.slice/" + claims["unit_name"]
            or type(claims["main_pid"]) is not int
            or claims["main_pid"] <= 1
            or not isinstance(claims["challenge"], str)
            or not _NONCE.fullmatch(claims["challenge"])
            or claims["reason"] not in _STOP_REASONS
            or type(claims["issued_at"]) is not int
            or type(claims["expires_at"]) is not int
            or not 0 < claims["expires_at"] - claims["issued_at"] <= _MAX_SECONDS):
        _hold("CLAIMS_BOUNDARY_INVALID")


def verify_pt_stop_grant(
    envelope: object, *, trusted_public_key: Ed25519PublicKey,
    original_identity: Mapping[str, object], challenge: str,
    challenge_issued_at: int, now: int,
) -> str:
    """Verify STOP only against the original root-owned journal identity."""
    if (not isinstance(trusted_public_key, Ed25519PublicKey)
            or not isinstance(original_identity, Mapping)
            or not isinstance(challenge, str)
            or type(challenge_issued_at) is not int or type(now) is not int):
        _hold("VERIFICATION_CONTEXT_MISSING")
    if not isinstance(envelope, dict) or set(envelope) != {"claims", "signature"}:
        _hold("ENVELOPE_INVALID")
    claims = envelope.get("claims")
    _check(claims)
    expected = {
        "task_id": "task_id", "task_attempt": "task_attempt",
        "node_id": "node_id", "worker_id": "worker_id",
        "execution_lease_sha256": "execution_lease_sha256",
        "boot_id": "boot_id", "handle_id": "handle_id",
        "unit_name": "unit_name", "invocation_id": "invocation_id",
        "control_group": "control_group", "main_pid": "main_pid",
    }
    if (any(type(claims[claim]) is not type(original_identity.get(key))
            or claims[claim] != original_identity.get(key)
            for claim, key in expected.items())
            or claims["challenge"] != challenge
            or not claims["issued_at"] - 5 <= now < claims["expires_at"]
            or claims["issued_at"] < challenge_issued_at
            or claims["issued_at"] > now
            or now - claims["issued_at"] > 3):
        _hold("ORIGINAL_SCOPE_OR_NONCE_STALE")
    signed = _payload(claims)
    if len(signed) > 4096:
        _hold("PAYLOAD_OVERSIZED")
    signature = envelope.get("signature")
    if not isinstance(signature, str) or not re.fullmatch(r"[0-9a-f]{128}", signature):
        _hold("SIGNATURE_FORMAT_INVALID")
    try:
        trusted_public_key.verify(bytes.fromhex(signature), signed)
    except InvalidSignature as exc:
        raise GrantRejected("PT_STOP_GRANT_SIGNATURE_UNTRUSTED_HOLD") from exc
    return hashlib.sha256(signed).hexdigest()


class CentralPtStopTrialIssuer:
    """Original-task-only opt-in signer, with NO remote stop or release action."""

    def __init__(self, repository, key: Ed25519PrivateKey, *,
                 isolated_test_only: bool = False):
        if not isinstance(key, Ed25519PrivateKey):
            _hold("SIGNER_INVALID")
        self.repository = repository
        self.key = key
        self.enabled = isolated_test_only is True

    def issue(self, *, task_id: str, task_attempt: int, node_id: str,
              boot_id: str, handle_id: str, invocation_id: str,
              main_pid: int, challenge: str,
              now: datetime | None = None) -> dict:
        if not self.enabled:
            _hold("ISSUER_DISABLED")
        current = datetime.now(timezone.utc) if now is None else now
        if not isinstance(current, datetime) or current.tzinfo is None:
            _hold("CLOCK_INVALID")
        current = current.astimezone(timezone.utc)
        if (not isinstance(handle_id, str) or not _HANDLE.fullmatch(handle_id)
                or not isinstance(invocation_id, str)
                or not _HANDLE.fullmatch(invocation_id)
                or type(main_pid) is not int or main_pid <= 1
                or not isinstance(challenge, str) or not _NONCE.fullmatch(challenge)
                or not isinstance(task_id, str) or not _TASK.fullmatch(task_id)
                or type(task_attempt) is not int or task_attempt <= 0
                or not isinstance(node_id, str) or not _NODE.fullmatch(node_id)
                or not _uuid(boot_id)):
            _hold("ISSUE_ARGUMENTS_INVALID")
        try:
            with closing(self.repository._connect()) as db:
                db.execute("BEGIN")
                task = db.execute(
                    """SELECT task_id,kind,resource_key,attempt,worker_id,
                              lease_token,lease_expires_at,status,stage
                         FROM tasks WHERE task_id=?""",
                    (task_id,),
                ).fetchone()
                if (task is None
                        or task["kind"] != "MODEL_CONVERSION"
                        or task["resource_key"] != PT_TEST_RESOURCE
                        or type(task["attempt"]) is not int
                        or task["attempt"] != task_attempt
                        or task["worker_id"] != "agent:" + node_id
                        or not isinstance(task["lease_token"], str)
                        or len(task["lease_token"]) < 20):
                    _hold("ORIGINAL_OWNER_NOT_STOP_ELIGIBLE")
                expires = _parse_utc(task["lease_expires_at"])
                if task["status"] == "CANCEL_REQUESTED":
                    reason = "CANCEL_REQUESTED"
                elif (task["status"] == "RUNNING"
                      and task["stage"] == "recovery_blocked_remote_agent_unverified"
                      and expires <= current):
                    reason = "LEASE_EXPIRED_HELD"
                else:
                    _hold("CENTRAL_STOP_REASON_NOT_CONFIRMED")
                issued_at = int(current.timestamp())
                claims = {
                    "purpose": STOP_PURPOSE,
                    "task_id": task_id, "task_attempt": task_attempt,
                    "node_id": node_id, "worker_id": "agent:" + node_id,
                    "execution_lease_sha256": hashlib.sha256(
                        task["lease_token"].encode("utf-8")).hexdigest(),
                    "boot_id": boot_id, "handle_id": handle_id,
                    "unit_name": "changlian-os-" + handle_id + ".service",
                    "invocation_id": invocation_id,
                    "control_group": "/system.slice/changlian-os-" + handle_id + ".service",
                    "main_pid": main_pid, "challenge": challenge,
                    "reason": reason,
                    "issued_at": issued_at,
                    "expires_at": issued_at + _MAX_SECONDS,
                }
                _check(claims)
                signed = _payload(claims)
                if len(signed) > 4096:
                    _hold("PAYLOAD_OVERSIZED")
                signature = self.key.sign(signed).hex()
                db.commit()
        except (OSError, sqlite3.Error, TypeError, ValueError, KeyError) as exc:
            raise GrantRejected("PT_STOP_GRANT_CENTRAL_LOOKUP_UNVERIFIED_HOLD") from exc
        return {"claims": claims, "signature": signature}
