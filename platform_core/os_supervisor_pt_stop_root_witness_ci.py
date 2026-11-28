"""2C-03D: disposable-root ONLY Ed25519 witness from ORIGINAL cgroup stop.

This is NOT a trusted production StopReceipt, a SupervisorService API or
permission to release a task. The CI-only root key is generated in process and
is not stable, registered centrally or usable after a restart.
Unlike a co-located Agent-signed JSON, this signer itself calls the protected
one-shot journal -> systemd observer bridge and accepts NO caller OS result.
Central recovery remains separately prohibited and requires independent trust.
"""
from __future__ import annotations

from contextlib import closing
import hashlib
import json
import os
import re
import time
from typing import Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey, Ed25519PublicKey,
)

from .os_supervisor_authorization import GrantRejected
from .os_supervisor_pt_export_launch import PtExportJournal
from .os_supervisor_pt_stop_rechecked_bridge import CiOnlyPtStopRecheckedBridge

_PURPOSE = "changlian-ci-root-pt-stop-witness-v1"
_DOMAIN = b"changlian-ci-root-pt-stop-witness-v1\x00"
_HEX32 = re.compile(r"[0-9a-f]{32}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_NONCE = re.compile(r"[A-Za-z0-9_-]{16,128}\Z")
_FIELDS = frozenset({
    "purpose", "test_only_no_production_recovery",
    "challenge_id", "nonce", "handle_id",
    "task_id", "task_attempt", "worker_id", "execution_lease_sha256",
    "boot_id", "unit", "invocation_id", "cgroup", "main_pid",
    "stop_grant_digest", "stop_reason",
    "os_cgroup_empty", "known_processes_stopped", "stop_command_succeeded",
    "stop_requested_ns", "empty_observed_ns", "issued_at", "expires_at",
})
_BIND = frozenset({
    "challenge_id", "nonce", "handle_id", "task_id", "task_attempt",
    "worker_id", "execution_lease_sha256", "boot_id", "unit",
    "invocation_id", "cgroup", "main_pid", "stop_grant_digest",
    "stop_reason",
})


def _hold(code: str) -> None:
    raise GrantRejected("PT_CI_ROOT_STOP_WITNESS_" + code + "_HOLD")


def _canonical(body: object) -> bytes:
    if not isinstance(body, dict) or set(body) != _FIELDS:
        _hold("SCHEMA")
    unit = body["unit"]
    handle = body["handle_id"]
    if (body["purpose"] != _PURPOSE
            or body["test_only_no_production_recovery"] is not True
            or not isinstance(handle, str) or not _HEX32.fullmatch(handle)
            or not isinstance(body["challenge_id"], str)
            or not _HEX32.fullmatch(body["challenge_id"])
            or not isinstance(body["nonce"], str)
            or not _NONCE.fullmatch(body["nonce"])
            or not isinstance(body["task_id"], str)
            or not 8 <= len(body["task_id"]) <= 128
            or type(body["task_attempt"]) is not int
            or body["task_attempt"] <= 0
            or not isinstance(body["worker_id"], str)
            or not re.fullmatch(r"agent:[A-Za-z0-9][A-Za-z0-9._:-]{0,127}",
                                body["worker_id"])
            or not isinstance(body["execution_lease_sha256"], str)
            or not _HEX64.fullmatch(body["execution_lease_sha256"])
            or not isinstance(body["boot_id"], str)
            or not re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}",
                                body["boot_id"])
            or unit != "changlian-os-" + handle + ".service"
            or body["cgroup"] != "/system.slice/" + unit
            or not isinstance(body["invocation_id"], str)
            or not _HEX32.fullmatch(body["invocation_id"])
            or body["invocation_id"] == "0" * 32
            or type(body["main_pid"]) is not int
            or body["main_pid"] <= 1
            or not isinstance(body["stop_grant_digest"], str)
            or not _HEX64.fullmatch(body["stop_grant_digest"])
            or body["stop_reason"] not in ("CANCEL_REQUESTED",
                                          "LEASE_EXPIRED_HELD")
            or body["os_cgroup_empty"] is not True
            or body["known_processes_stopped"] is not True
            or body["stop_command_succeeded"] is not True
            or type(body["stop_requested_ns"]) is not int
            or type(body["empty_observed_ns"]) is not int
            or not 0 < body["stop_requested_ns"] <= body["empty_observed_ns"]
            or type(body["issued_at"]) is not int
            or type(body["expires_at"]) is not int
            or not 0 < body["expires_at"] - body["issued_at"] <= 12):
        _hold("BOUNDARY")
    try:
        payload = _DOMAIN + json.dumps(
            body, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (ValueError, TypeError, OverflowError) as exc:
        raise GrantRejected("PT_CI_ROOT_STOP_WITNESS_JSON_UNSAFE_HOLD") from exc
    if len(payload) > 4096:
        _hold("OVERSIZED")
    return payload


def verify_ci_root_stop_witness(
    envelope: object, *, public_key: Ed25519PublicKey,
    expected_original: Mapping[str, object], now: int,
) -> bool:
    """CI-only verifier. The caller MUST supply independent trusted scope.

    A valid signature is not enough: the entire original task+lease+OS tuple
    and the one central challenge/nonce must match independent central data.
    """
    if (not isinstance(public_key, Ed25519PublicKey)
            or not isinstance(expected_original, Mapping)
            or set(expected_original) != _BIND
            or type(now) is not int
            or not isinstance(envelope, dict)
            or set(envelope) != {"payload", "signature"}):
        return False
    signature = envelope.get("signature")
    if (not isinstance(signature, str)
            or not re.fullmatch(r"[0-9a-f]{128}", signature)):
        return False
    body = envelope.get("payload")
    try:
        signed = _canonical(body)
        if (any(type(body.get(field)) is not type(expected_original.get(field))
                or body[field] != expected_original[field] for field in _BIND)
                or not body["issued_at"] - 5 <= now < body["expires_at"]):
            return False
        public_key.verify(bytes.fromhex(signature), signed)
    except (GrantRejected, InvalidSignature, ValueError, TypeError, KeyError):
        return False
    return True


class CiOnlyRootPtStopWitnessSigner:
    """Root-only CI: stop original unit, observe kernel, THEN sign the tuple."""

    def __init__(
        self, journal: PtExportJournal, bridge: CiOnlyPtStopRecheckedBridge, *,
        isolated_ci_only: bool = False,
    ):
        if (isolated_ci_only is not True
                or type(journal) is not PtExportJournal
                or type(bridge) is not CiOnlyPtStopRecheckedBridge
                or bridge.journal is not journal
                or os.name != "posix" or os.geteuid() != 0
                or os.environ.get("GITHUB_ACTIONS") != "true"
                or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted"
                or journal.journal.test_only_unprivileged is not True):
            _hold("PRODUCTION_DISABLED")
        self.journal = journal
        self.bridge = bridge
        # No externally supplied private key, Agent signing API, disk key or
        # production verifier configuration exists in this test-only module.
        self._key = Ed25519PrivateKey.generate()
        self.public_key = self._key.public_key()

    def stop_and_sign(
        self, handle_id: str, task_attempt: int, *,
        challenge_id: str, nonce: str,
    ) -> dict:
        if (not isinstance(handle_id, str) or not _HEX32.fullmatch(handle_id)
                or type(task_attempt) is not int or task_attempt <= 0
                or not isinstance(challenge_id, str)
                or not _HEX32.fullmatch(challenge_id)
                or not isinstance(nonce, str) or not _NONCE.fullmatch(nonce)):
            _hold("CHALLENGE_ARGUMENTS_UNTRUSTED")
        # This is the ONLY OS-stop path for this test signer. The root journal
        # CAS runs before systemd, and a crash cannot mint a second OS claim.
        result = self.bridge.stop_original_after_central_cas(
            handle_id, task_attempt,
        )
        start_ns = result.get("stop_requested_monotonic_ns")
        zero_ns = result.get("empty_observed_monotonic_ns")
        if (result.get("state") != "LOCAL_EMPTY_OBSERVED_NO_RECEIPT"
                or result.get("original_cgroup_became_empty") is not True
                or result.get("trusted_stop_receipt_available") is not False
                or result.get("central_recovery_allowed") is not False
                or type(start_ns) is not int or type(zero_ns) is not int
                or not 0 < start_ns <= zero_ns):
            _hold("KERNEL_STOP_NOT_CONFIRMED")
        # Read only the SAME root journal with the single already-claimed OS
        # invocation; never trust identity fields submitted as a JSON result.
        with closing(self.journal.journal._connect()) as db:
            row = db.execute(
                """SELECT i.task_id,i.task_attempt,i.worker_id,
                          i.lease_sha256,i.boot_id,i.unit_name,i.state,
                          o.invocation_id,o.control_group,o.main_pid,
                          c.stop_grant_digest,c.reason,
                          q.stop_grant_digest AS probed_grant_digest,
                          q.invocation_id AS probed_invocation,
                          q.main_pid AS probed_pid
                   FROM execution_intents i
                   JOIN pt_export_unit_identities o ON o.handle_id=i.handle_id
                   JOIN pt_export_stop_claims c ON c.handle_id=i.handle_id
                   JOIN pt_export_stop_observation_claims q
                     ON q.handle_id=i.handle_id
                   WHERE i.handle_id=? AND i.task_attempt=?""",
                (handle_id, task_attempt),
            ).fetchone()
        if (row is None or row["state"] != "RUNNING"
                or row["boot_id"] != self.journal.journal.boot_id
                or row["unit_name"] != result["original_unit"]
                or row["invocation_id"] != result["original_invocation_id"]
                or row["main_pid"] != result["original_main_pid"]
                or row["stop_grant_digest"] != result["stop_grant_digest"]
                or row["stop_grant_digest"] != row["probed_grant_digest"]
                or row["invocation_id"] != row["probed_invocation"]
                or row["main_pid"] != row["probed_pid"]
                or row["control_group"] != "/system.slice/" + row["unit_name"]):
            _hold("ORIGINAL_ROOT_JOURNAL_MISMATCH")
        walltime = int(time.time())
        payload = {
            "purpose": _PURPOSE,
            "test_only_no_production_recovery": True,
            "challenge_id": challenge_id, "nonce": nonce,
            "handle_id": handle_id, "task_id": row["task_id"],
            "task_attempt": row["task_attempt"],
            "worker_id": row["worker_id"],
            "execution_lease_sha256": row["lease_sha256"],
            "boot_id": row["boot_id"], "unit": row["unit_name"],
            "invocation_id": row["invocation_id"],
            "cgroup": row["control_group"],
            "main_pid": row["main_pid"],
            "stop_grant_digest": row["stop_grant_digest"],
            "stop_reason": row["reason"],
            "os_cgroup_empty": True,
            "known_processes_stopped": True,
            "stop_command_succeeded": True,
            "stop_requested_ns": start_ns, "empty_observed_ns": zero_ns,
            "issued_at": walltime, "expires_at": walltime + 12,
        }
        return {"payload": payload,
                "signature": self._key.sign(_canonical(payload)).hex()}
