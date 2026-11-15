"""P0-01C-3B: isolated *real kernel event -> simulated central challenge* bridge.

The kernel observations are REAL, but the witness signature is simulated in
this single CI user context. No independent protected signer or trust root.
Thus this is NOT a trusted StopReceipt, not a production Agent API and not a
permission to release REMOTE_AGENT_STOP_UNVERIFIED tasks.

Requires GitHub-hosted Ubuntu disposable VM and explicit CLI opt-in. The
database is sqlite3 :memory: only; never connects to platform endpoints.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
import secrets
import sqlite3
import sys
from typing import Any, Mapping

import central_stop_recovery_contract as central
import linux_cgroup_poc as kernel


TEST_NODE = "isolated-poc-node"
TEST_GENERATION = 3


def observation_is_usable(challenge: Mapping[str, Any],
                          result: Mapping[str, Any],
                          original_scope: Mapping[str, Any]) -> bool:
    """Fail closed on identity/sequence/scope changes. NOT a signer."""
    if not all(isinstance(x, Mapping) for x in (challenge, result, original_scope)):
        return False
    if (result.get("outcome") != "LOCAL_CGROUP_POC_PASS_NOT_CENTRAL_STOP_PROOF"
            or result.get("stop_proof_verified") is not False
            or result.get("central_recovery_allowed") is not False):
        return False
    for name in ("membership_verified", "identity_binding_verified",
                 "three_process_sessions_bound", "launcher_sigkill",
                 "both_descendants_survived_launcher", "cgroup_empty_verified",
                 "known_processes_stopped"):
        if result.get(name) is not True:
            return False
    if result.get("systemd_stop_returncode") != 0 or (
            result.get("empty_before_stop_requested") is not False):
        return False
    stop_ns = result.get("stop_requested_ns")
    zero_ns = result.get("empty_observed_ns")
    if (type(stop_ns) is not int or type(zero_ns) is not int
            or stop_ns <= 0 or zero_ns < stop_ns):
        return False
    bound = result.get("synthetic_execution_identity")
    if not isinstance(bound, Mapping):
        return False
    for name in ("task_id", "execution_generation", "boot_id",
                 "invocation_id", "unit"):
        if (bound.get(name) != challenge.get(name) or
                original_scope.get(name) != challenge.get(name)):
            return False
    if original_scope.get("cgroup") != challenge.get("cgroup") or (
            original_scope.get("worker_id") != challenge.get("worker_id")):
        return False
    if type(challenge.get("execution_generation")) is not int:
        return False
    if result.get("unit") != challenge.get("unit"):
        return False
    timeline = result.get("cgroup_observations")
    if not isinstance(timeline, list):
        return False
    observed_live = any(
        isinstance(item, Mapping) and item.get("populated") == 1
        and item.get("after_stop_armed") is True
        and type(item.get("monotonic_ns")) is int
        and item["monotonic_ns"] <= stop_ns
        for item in timeline)
    observed_zero = any(
        isinstance(item, Mapping) and item.get("populated") == 0
        and item.get("after_stop_armed") is True
        and item.get("monotonic_ns") == zero_ns
        for item in timeline)
    return observed_live and observed_zero


def make_simulated_receipt(challenge: dict, result: dict, scope: dict,
                           simulator_key: bytes) -> dict:
    """Check real kernel observations, sign with TEST-ONLY key.

    Does NOT isolate witness key from the Agent user, and the event timeline
    is still collected in the PoC controller process.
    """
    if not observation_is_usable(challenge, result, scope):
        raise central.RecoveryRejected("KERNEL_EVIDENCE_OR_CHALLENGE_UNVERIFIED")
    payload = {
        **challenge,
        "os_cgroup_empty": True,
        "known_processes_stopped": True,
        "stop_command_succeeded": True,
        "stop_requested_ns": result["stop_requested_ns"],
        "empty_observed_ns": result["empty_observed_ns"],
    }
    return central.test_only_sign_witness(payload, simulator_key)


def run_isolated_bridge() -> tuple[dict, int]:
    """Carry one real Linux cgroup stop through a separate in-memory CAS.

    Challenge is created from the live-bound unit BEFORE systemd stop, never
    constructed retroactively from a completed stop response.
    """
    if (os.name != "posix" or os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted"
            or not hasattr(os, "geteuid") or os.geteuid() == 0):
        return {"outcome": "NOT_ISOLATED_GITHUB_RUNNER_HOLD",
                "central_recovery_allowed": False}, 2
    task_id = "poc-task-" + secrets.token_hex(12)
    key = secrets.token_bytes(32)  # fake, co-located signer, never persisted
    now = datetime.now(timezone.utc)
    token = secrets.token_urlsafe(32)
    db = sqlite3.connect(":memory:", isolation_level=None)
    try:
        central.init_scratch_schema(db)
        db.execute("""INSERT INTO tasks
            (task_id,attempt,status,stage,worker_id,lease_token,
             lease_expires_at,updated_at,resource_wait_reason)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (task_id, TEST_GENERATION, "RUNNING", central.HOLD,
             "agent:" + TEST_NODE, token,
             (now - timedelta(seconds=20)).isoformat(),
             now.isoformat(), "REMOTE_AGENT_STOP_UNVERIFIED"))
        db.execute("""INSERT INTO gpu_reservations
            (task_id,worker_id,lease_token,policy) VALUES (?,?,?,?)""",
            (task_id, "agent:" + TEST_NODE, token, "exclusive"))
        scope: dict[str, Any] = {}
        challenge: dict[str, Any] = {}

        def issue_before_stop(observed: dict[str, Any]) -> bool:
            if (observed.get("task_id") != task_id or
                    observed.get("execution_generation") != TEST_GENERATION or
                    observed.get("worker_id") != "agent:" + TEST_NODE):
                return False
            scope.update(observed)
            challenger = central.issue_challenge(
                db, task_id=task_id, node_id=TEST_NODE,
                boot_id=observed["boot_id"],
                invocation_id=observed["invocation_id"],
                unit=observed["unit"], cgroup=observed["cgroup"],
                now=datetime.now(timezone.utc), ttl_seconds=120)
            challenge.update(challenger)
            return True

        result, code = kernel.run_poc(
            synthetic_task_id=task_id,
            synthetic_generation=TEST_GENERATION,
            before_stop=issue_before_stop)
        evidence = {
            "scope": "GITHUB_VM_CPU_BRIDGE_WITH_SIMULATED_WITNESS",
            "challenge_issued_before_stop": bool(challenge),
            "kernel_stop_outcome": result.get("outcome"),
            "kernel_cgroup_empty": result.get("cgroup_empty_verified") is True,
            "kernel_identity_bound": result.get("identity_binding_verified") is True,
            "simulated_central_recovery_committed": False,
            "trusted_os_witness_implemented": False,
            "production_recovery_allowed": False,
        }
        if code != 0:
            evidence["outcome"] = "KERNEL_STOP_HOLD"
            return evidence, 3
        receipt = make_simulated_receipt(challenge, result, scope, key)
        committed = central.commit_test_recovery(
            db, attestation=receipt, now=datetime.now(timezone.utc),
            independent_witness_verifier=central.test_only_witness_verifier(key))
        task = db.execute(
            "SELECT status,attempt,worker_id,lease_token FROM tasks WHERE task_id=?",
            (task_id,)).fetchone()
        reserved = db.execute(
            "SELECT COUNT(*) FROM gpu_reservations WHERE task_id=?", (task_id,)
        ).fetchone()[0]
        audits = db.execute("SELECT COUNT(*) FROM recovery_audit").fetchone()[0]
        consumed = db.execute(
            "SELECT COUNT(*) FROM recovery_challenges WHERE consumed_at IS NOT NULL"
        ).fetchone()[0]
        # Even the simulated witness cannot replay a consumed challenge.
        try:
            central.commit_test_recovery(
                db, attestation=receipt, now=datetime.now(timezone.utc),
                independent_witness_verifier=central.test_only_witness_verifier(key))
        except central.RecoveryRejected:
            evidence["challenge_replay_rejected"] = True
        else:
            evidence["challenge_replay_rejected"] = False
        consistent = (
            committed.get("scratch_only") is True and
            task == ("QUEUED", TEST_GENERATION, None, None) and
            reserved == 0 and audits == 1 and consumed == 1 and
            evidence["challenge_replay_rejected"]
        )
        evidence["simulated_central_recovery_committed"] = consistent
        evidence["outcome"] = (
            "REAL_KERNEL_TO_MEMORY_CAS_SIMULATION_PASS_NOT_TRUSTED_STOP_PROOF"
            if consistent else "CENTRAL_SIMULATION_INVARIANT_FAILED_HOLD")
        return evidence, 0 if consistent else 3
    except (central.RecoveryRejected, ValueError, sqlite3.Error, OSError, KeyError) as exc:
        return {"scope": "GITHUB_VM_CPU_BRIDGE_WITH_SIMULATED_WITNESS",
                "outcome": "UNKNOWN_OR_UNTRUSTED_HOLD",
                "error_type": type(exc).__name__,
                "simulated_central_recovery_committed": False,
                "trusted_os_witness_implemented": False,
                "production_recovery_allowed": False}, 3
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--isolated-test-host", action="store_true")
    args = parser.parse_args()
    if not (args.run and args.isolated_test_host):
        print(json.dumps({"outcome": "NOT_EXECUTED",
                          "reason": "requires --run --isolated-test-host and GitHub-hosted VM",
                          "trusted_os_witness_implemented": False,
                          "production_recovery_allowed": False}))
        return 2
    result, code = run_isolated_bridge()
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
