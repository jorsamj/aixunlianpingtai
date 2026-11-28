"""2C-03B: isolated Ed25519 stop-witness protocol for the CENTRAL scratch CAS.

TEST-ONLY signed witness. NOT a production StopReceipt or root-owned signer.
Only the existing :memory: central_stop_recovery_contract may consume this
test witness. Nothing in production Agent, SupervisorService, or web imports it.
The signature proves test-key possession, NOT authentic kernel process exit.
"""
from __future__ import annotations

import json
import re
from typing import Any, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey, Ed25519PublicKey,
)

_DOMAIN = b"changlian-isolated-pt-stop-witness-ed25519-v1\x00"
_PURPOSE = "p0-01c-2c03b-ci-only-stop-witness-v1"
_FIELDS = frozenset({
    "purpose", "challenge_id", "nonce", "task_id", "execution_generation",
    "worker_id", "boot_id", "invocation_id", "unit", "cgroup",
    "os_cgroup_empty", "known_processes_stopped",
    "stop_command_succeeded", "stop_requested_ns", "empty_observed_ns",
})
_HEX32 = re.compile(r"[0-9a-f]{32}\Z")
_UUID = re.compile(
    r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\Z"
)
_UNIT = re.compile(
    r"(?:clpoc-[0-9a-f]{24}|changlian-os-[0-9a-f]{32})\.service\Z"
)


class IsolatedWitnessRejected(RuntimeError):
    pass


def _payload_bytes(payload: object) -> bytes:
    if not isinstance(payload, dict) or set(payload) != _FIELDS:
        raise IsolatedWitnessRejected("TEST_WITNESS_SCHEMA_INVALID")
    unit = payload["unit"]
    group = payload["cgroup"]
    if (payload["purpose"] != _PURPOSE
            or not isinstance(payload["challenge_id"], str)
            or not _HEX32.fullmatch(payload["challenge_id"])
            or not isinstance(payload["nonce"], str)
            or not 12 <= len(payload["nonce"]) <= 128
            or not isinstance(payload["task_id"], str)
            or not 1 <= len(payload["task_id"]) <= 128
            or not isinstance(payload["worker_id"], str)
            or not re.fullmatch(r"agent:[A-Za-z0-9][A-Za-z0-9_-]{0,127}",
                                payload["worker_id"])
            or type(payload["execution_generation"]) is not int
            or payload["execution_generation"] <= 0
            or not isinstance(payload["boot_id"], str)
            or not _UUID.fullmatch(payload["boot_id"])
            or not isinstance(payload["invocation_id"], str)
            or not _HEX32.fullmatch(payload["invocation_id"])
            or payload["invocation_id"] == "0" * 32
            or not isinstance(unit, str) or not _UNIT.fullmatch(unit)
            or not isinstance(group, str)
            or (group != "/system.slice/" + unit
                and not (unit.startswith("clpoc-")
                         and group.startswith("/user.slice/")
                         and group.endswith("/" + unit)))
            or any(payload[field] is not True for field in (
                "os_cgroup_empty", "known_processes_stopped",
                "stop_command_succeeded"))
            or type(payload["stop_requested_ns"]) is not int
            or type(payload["empty_observed_ns"]) is not int
            or payload["stop_requested_ns"] <= 0
            or payload["empty_observed_ns"] < payload["stop_requested_ns"]):
        raise IsolatedWitnessRejected("TEST_WITNESS_BOUNDARY_INVALID")
    try:
        raw = json.dumps(
            payload, sort_keys=True, separators=(",", ":"),
            ensure_ascii=True, allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise IsolatedWitnessRejected("TEST_WITNESS_CANONICAL_INVALID") from exc
    if len(raw) > 4096:
        raise IsolatedWitnessRejected("TEST_WITNESS_OVERSIZED")
    return _DOMAIN + raw


def sign_test_only_stop_witness(
    payload: dict[str, Any], key: Ed25519PrivateKey, *,
    isolated_test_only: bool = False,
) -> dict[str, object]:
    """Intentionally unreachable from production: test key is caller-provided."""
    if isolated_test_only is not True or not isinstance(key, Ed25519PrivateKey):
        raise IsolatedWitnessRejected("TEST_ONLY_SIGNING_DISABLED")
    return {"payload": dict(payload), "signature": key.sign(_payload_bytes(payload)).hex()}


def isolated_test_witness_verifier(
    key: Ed25519PublicKey, *, isolated_test_only: bool = False,
):
    """Return a verifier ONLY for the scratch central recovery transaction."""
    if isolated_test_only is not True or not isinstance(key, Ed25519PublicKey):
        raise IsolatedWitnessRejected("PRODUCTION_VERIFIER_DISABLED")

    def verify(envelope: Mapping[str, Any]) -> bool:
        if not isinstance(envelope, dict) or set(envelope) != {"payload", "signature"}:
            return False
        signature = envelope.get("signature")
        if (not isinstance(signature, str)
                or not re.fullmatch(r"[0-9a-f]{128}", signature)):
            return False
        try:
            data = _payload_bytes(envelope.get("payload"))
            key.verify(bytes.fromhex(signature), data)
        except (InvalidSignature, ValueError, TypeError, IsolatedWitnessRejected):
            return False
        return True

    return verify


def synthetic_payload(challenge: Mapping[str, Any], *,
                      stop_requested_ns: int = 100,
                      empty_observed_ns: int = 120) -> dict[str, Any]:
    """Build test data; this is NEVER evidence obtained from an OS kernel."""
    required = {"challenge_id", "nonce", "task_id", "execution_generation",
                "worker_id", "boot_id", "invocation_id", "unit", "cgroup"}
    if not isinstance(challenge, Mapping) or not required.issubset(challenge):
        raise IsolatedWitnessRejected("SYNTHETIC_SCOPE_INCOMPLETE")
    payload = {
        "purpose": _PURPOSE,
        **{key: challenge[key] for key in sorted(required)},
        "os_cgroup_empty": True,
        "known_processes_stopped": True,
        "stop_command_succeeded": True,
        "stop_requested_ns": stop_requested_ns,
        "empty_observed_ns": empty_observed_ns,
    }
    _payload_bytes(payload)
    return payload
