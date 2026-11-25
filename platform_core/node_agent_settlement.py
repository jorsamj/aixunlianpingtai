"""Shared central-settlement contract for Node Agent executions.

Training, conversion and node recovery must decide the same question from the
same durable facts: *is this exact execution settled by the control plane?*

A ``finish`` response body, an HTTP 200, an accepted stop proof, a RELEASED
Hold on another attempt or a locally verified process stop are never a
settlement on their own.  Only the central ``execution_status`` projection,
bound to the original task/node/execution attempt/ProcessIdentity and (for a
dual-slot execution) to the released resource Hold, is authoritative.

The module is pure: it performs no I/O and holds no state, so the runners and
the recovery coordinator cannot drift apart again.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
from typing import Any, Mapping


TERMINAL_TASK_STATUSES = frozenset({
    "SUCCEEDED",
    "PARTIAL_SUCCESS",
    "CANCELLED",
    "FAILED",
    "BLOCKED_BY_ENVIRONMENT",
    "BLOCKED_BY_HARDWARE",
})
PROCESS_STOP_VERIFIED = "PROCESS_STOP_VERIFIED"
NO_PROCESS_LAUNCHED = "NO_PROCESS_LAUNCHED"
HOLD_HELD = "HELD"
HOLD_STOP_VERIFIED = "STOP_VERIFIED"
HOLD_RELEASED = "RELEASED"


def canonical_digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(
        dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def strict_int(value: object) -> int | None:
    """Return an int only for a real integer; never coerce ``bool``/``str``."""
    return int(value) if type(value) is int else None


def strict_positive_number(value: object) -> float | None:
    """Return a finite positive float from an int/float; never a bool or ``str``."""
    if type(value) is bool or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or number <= 0.0:
        return None
    return number


def process_identity_sha256(
    pid: object, create_time: object, command_hash: object,
) -> str:
    """Digest of the exact OS process identity, as the control plane computes it."""
    return canonical_digest({
        "pid": int(pid),
        "create_time": float(create_time),
        "command_hash": str(command_hash),
    })


def record_identity_sha256(record: Mapping[str, Any]) -> str:
    identity = record.get("process_identity")
    if isinstance(identity, Mapping):
        return process_identity_sha256(
            identity.get("pid"),
            identity.get("create_time"),
            identity.get("command_hash"),
        )
    return process_identity_sha256(
        record.get("pid"), record.get("create_time"), record.get("command_hash"),
    )


def has_hold(status: Mapping[str, Any]) -> bool:
    return (
        status.get("hold_state") is not None
        or status.get("hold_execution_attempt") is not None
    )


def no_launch_evidence(record: Mapping[str, Any]) -> dict[str, Any]:
    evidence = {
        "launch_boundary_entered": False,
        "persisted_launch_intent": False,
        "persisted_process_identity": False,
        "task_id": str(record["task_id"]),
        "assignment_generation": int(record.get("assignment_generation") or 0),
        "execution_attempt": int(record["generation"]),
        "gpu_uuid": str(record.get("gpu_uuid") or ""),
    }
    return {**evidence, "intent_sha256": canonical_digest(evidence)}


def stop_proof_digests(
    status: Mapping[str, Any], record: Mapping[str, Any],
) -> tuple[str, str]:
    """Recompute the acceptable central stop-proof digests from local evidence.

    The first digest is the current proof schema, the second the frozen
    schema-6/7 legacy digest that predates proof_type/no-launch fields.
    """
    base = {
        "node_id": str(status.get("node_id") or ""),
        "task_id": str(record["task_id"]),
        "assignment_generation": int(record.get("assignment_generation") or 0),
        "execution_attempt": int(record["generation"]),
        "gpu_uuid": str(record.get("gpu_uuid") or ""),
        "process_identity": {} if record.get("no_process_launched") is True else {
            "pid": int(record["pid"]),
            "create_time": float(record["create_time"]),
            "command_hash": str(record["command_hash"]),
        },
        "stop_verified": True,
    }
    no_launch = record.get("no_process_launched") is True
    evidence = no_launch_evidence(record) if no_launch else {}
    current = dict(base)
    current["proof_type"] = NO_PROCESS_LAUNCHED if no_launch else PROCESS_STOP_VERIFIED
    current["no_process_launched"] = no_launch
    current["no_launch_evidence"] = evidence
    if no_launch:
        base["no_process_launched"] = True
        base["no_launch_evidence"] = evidence
    return canonical_digest(current), canonical_digest(base)


def hold_identity_error(
    status: Mapping[str, Any],
    record: Mapping[str, Any],
    local_assignment: int,
    local_gpu: str,
) -> str:
    if strict_int(status.get("hold_execution_attempt")) != int(record["generation"]):
        return "central Hold execution attempt mismatch"
    if strict_int(status.get("hold_assignment_generation")) != int(local_assignment):
        return "central Hold assignment generation mismatch"
    if str(status.get("hold_gpu_uuid") or "") != local_gpu:
        return "central Hold GPU UUID mismatch"
    return ""


def proof_error(status: Mapping[str, Any], record: Mapping[str, Any]) -> str:
    """Post-verify the recorded stop proof against the original identity."""
    hold_state = str(status.get("hold_state") or "")
    proof_type = str(status.get("proof_type") or "")
    proof_sha256 = str(status.get("proof_sha256") or "")
    if hold_state in {HOLD_STOP_VERIFIED, HOLD_RELEASED}:
        expected_type = NO_PROCESS_LAUNCHED if record.get("no_process_launched") is True else PROCESS_STOP_VERIFIED
        if proof_type != expected_type:
            return "central stop proof type mismatch"
        if not proof_sha256:
            return "central stop proof digest is missing"
        current, legacy = stop_proof_digests(status, record)
        if not (hmac.compare_digest(proof_sha256, current)
                or hmac.compare_digest(proof_sha256, legacy)):
            return "central stop proof digest mismatch"
        return ""
    if hold_state == HOLD_HELD:
        if proof_sha256 or proof_type:
            return "central stop proof recorded for a held execution"
        return ""
    return "central Hold state is invalid"


def single_slot_contract_error(
    status: Mapping[str, Any],
    record: Mapping[str, Any],
    local_assignment: int,
) -> str:
    """Validate the original single-slot recovery contract.

    A single-slot execution never created a resource Hold, so its durable
    evidence is the execution attempt, the released Assignment that started it,
    and the registered ProcessIdentity.  It must not be blocked merely because
    no Hold exists, and it must not borrow the dual-slot proof.
    """
    if has_hold(status):
        return "central Hold present for single-slot execution"
    if status.get("proof_type") or status.get("proof_sha256"):
        return "central stop proof present without a Hold"
    central_assignment = strict_int(status.get("assignment_generation"))
    if local_assignment > 0:
        if central_assignment != local_assignment:
            return "central assignment generation mismatch"
    return ""


def execution_slots(record: Mapping[str, Any]) -> int:
    slots = strict_int(record.get("execution_slots"))
    if slots is None or slots not in (1, 2):
        return 0
    return slots


def is_dual_slot(record: Mapping[str, Any], status: Mapping[str, Any]) -> bool:
    slots = execution_slots(record)
    return (slots == 2 or strict_int(status.get("execution_slots")) == 2
            or (slots == 0 and has_hold(status)))


def _identity_digest_error(
    status: Mapping[str, Any],
    record: Mapping[str, Any],
    *,
    required: bool,
) -> str:
    central = status.get("process_identity_sha256")
    if record.get("no_process_launched") is True:
        if record.get("no_launch_evidence") != no_launch_evidence(record):
            return "local no-launch evidence is invalid"
        return "central ProcessIdentity exists for an unlaunched execution" if central is not None else ""
    if central is None:
        # Single-slot executions only register their exact identity when the
        # control plane accepted a start identity or a recovery proof; a
        # legacy/never-registered attempt is not corruption by itself.
        return "central ProcessIdentity digest is missing" if required else ""
    if str(central) != record_identity_sha256(record):
        return "central ProcessIdentity digest mismatch"
    return ""


def status_identity_error(
    status: Mapping[str, Any],
    record: Mapping[str, Any],
    *,
    node_id: str = "",
    require_process_identity: bool = False,
) -> str:
    """Bind a central status projection to the original durable execution."""
    if not isinstance(status, Mapping):
        return "central settlement response is invalid"
    if str(status.get("task_id")) != str(record["task_id"]):
        return "central task identity mismatch"
    if node_id and str(status.get("node_id") or "") != str(node_id):
        return "central node identity mismatch"
    attempt = strict_int(status.get("execution_attempt"))
    if attempt != int(record["generation"]):
        return "central execution attempt mismatch"

    local_slots = execution_slots(record)
    if "execution_slots" in record and strict_int(record["execution_slots"]) not in (0, 1, 2):
        return "local execution slot contract is invalid"
    central_slots = strict_int(status.get("execution_slots"))
    if "execution_slots" in status:
        if central_slots not in (1, 2):
            return "central execution slot contract is invalid"
        if local_slots and central_slots != local_slots:
            return "central execution slot contract mismatch"
    local_assignment = int(record.get("assignment_generation") or 0)
    local_gpu = str(record.get("gpu_uuid") or "")
    if is_dual_slot(record, status):
        # The original contract is a dual slot: either recorded explicitly by
        # the control plane at start, or a pre-marker record that owns a
        # central Hold.  A dual-slot execution must carry complete original
        # Assignment/GPU evidence; missing local fields are corruption, not
        # legacy, and a missing central Hold is never bypassed.
        if not has_hold(status):
            return "central Hold missing for dual-slot execution"
        if local_assignment <= 0:
            return "local Assignment generation missing for dual-slot recovery"
        if not local_gpu:
            return "local GPU UUID missing for dual-slot recovery"
        error = hold_identity_error(status, record, local_assignment, local_gpu)
        if error:
            return error
        error = _identity_digest_error(status, record, required=True)
        if error:
            return error
        return proof_error(status, record)
    error = _identity_digest_error(
        status, record, required=bool(require_process_identity),
    )
    if error:
        return error
    return single_slot_contract_error(status, record, local_assignment)


def assignment_settlement_error(
    status: Mapping[str, Any], record: Mapping[str, Any],
) -> str:
    """The released Assignment is the single-slot resource settlement fact."""
    local_assignment = int(record.get("assignment_generation") or 0)
    central_assignment = status.get("assignment_generation")
    if central_assignment is not None:
        parsed = strict_int(central_assignment)
        if parsed is None:
            return "central assignment generation is invalid"
        if parsed <= 0:
            return "central assignment generation is invalid"
        if local_assignment > 0 and parsed != local_assignment:
            return "central assignment generation mismatch"
    elif local_assignment > 0:
        return "central Assignment evidence is missing"
    state = status.get("assignment_state")
    if (local_assignment > 0 or central_assignment is not None) and state is None:
        return "central Assignment state is missing"
    if state is not None and str(state) != HOLD_RELEASED:
        return "central Assignment was not released"
    return ""


def settlement_error(
    status: Mapping[str, Any],
    record: Mapping[str, Any],
    *,
    node_id: str = "",
    expected_status: str | None = None,
    require_process_identity: bool = False,
) -> str:
    """Return ``""`` only for an authoritative settlement of this execution."""
    error = status_identity_error(
        status, record, node_id=node_id,
        require_process_identity=require_process_identity,
    )
    if error:
        return error
    actual = str(status.get("status") or "")
    if actual not in TERMINAL_TASK_STATUSES:
        return "central execution is not terminal"
    if expected_status is not None:
        expected = str(expected_status or "")
        if expected not in TERMINAL_TASK_STATUSES:
            return "requested terminal status is invalid"
        if actual != expected:
            return "central terminal status mismatch"
    if is_dual_slot(record, status):
        if str(status.get("hold_state") or "") != HOLD_RELEASED:
            return "central Hold was not released"
        return ""
    return assignment_settlement_error(status, record)


def fetch_status(client, task_id: str) -> tuple[dict[str, Any] | None, str]:
    try:
        status = client.execution_status(str(task_id))
    except Exception as error:  # noqa: BLE001 - every failure is a fail-closed reason
        return None, (
            "central recovery status is unavailable: "
            f"{type(error).__name__}: {error}"
        )
    if not isinstance(status, Mapping):
        return None, "central recovery status is invalid"
    return dict(status), ""


def settlement_of(
    client,
    record: Mapping[str, Any],
    *,
    node_id: str = "",
    expected_status: str | None = None,
    require_process_identity: bool = False,
) -> tuple[dict[str, Any] | None, str]:
    """Read the real central status and verify this exact execution settled."""
    status, error = fetch_status(client, str(record["task_id"]))
    if error:
        return None, error
    return status, settlement_error(
        status, record, node_id=node_id, expected_status=expected_status,
        require_process_identity=require_process_identity,
    )


def recover_and_verify(
    client,
    record: Mapping[str, Any],
    *,
    node_id: str = "",
) -> tuple[dict[str, Any] | None, str]:
    """Settle an already-stopped original execution through the existing API.

    Used by the legacy no-coordinator path, which has no retry loop: one
    authenticated, fenced recovery request, then the refreshed status must
    prove the terminal state *and* the exact original identity.
    """
    status, error = settlement_of(client, record, node_id=node_id)
    if not error:
        return status, ""
    try:
        recovered = client.recover_execution(
            str(record["task_id"]),
            assignment_generation=int(record.get("assignment_generation") or 0),
            execution_generation=int(record["generation"]),
            gpu_uuid=str(record.get("gpu_uuid") or ""),
            process_identity={
                "pid": int(record["pid"]),
                "create_time": float(record["create_time"]),
                "command_hash": str(record["command_hash"]),
            },
        )
    except Exception as exc:  # noqa: BLE001 - fail closed
        return None, (
            "central recovery could not settle the original execution: "
            f"{type(exc).__name__}: {exc}"
        )
    refreshed, refresh_error = fetch_status(client, str(record["task_id"]))
    if refresh_error:
        return None, refresh_error
    if not isinstance(recovered, Mapping):
        return None, "central recovery returned no settlement evidence"
    error = settlement_error(
        refreshed, record, node_id=node_id, require_process_identity=True,
    )
    if error:
        return refreshed, error
    return refreshed, ""


__all__ = [
    "HOLD_HELD",
    "HOLD_RELEASED",
    "HOLD_STOP_VERIFIED",
    "NO_PROCESS_LAUNCHED",
    "PROCESS_STOP_VERIFIED",
    "TERMINAL_TASK_STATUSES",
    "assignment_settlement_error",
    "canonical_digest",
    "execution_slots",
    "fetch_status",
    "has_hold",
    "hold_identity_error",
    "is_dual_slot",
    "no_launch_evidence",
    "process_identity_sha256",
    "proof_error",
    "record_identity_sha256",
    "recover_and_verify",
    "settlement_error",
    "settlement_of",
    "single_slot_contract_error",
    "status_identity_error",
    "stop_proof_digests",
    "strict_int",
    "strict_positive_number",
]
