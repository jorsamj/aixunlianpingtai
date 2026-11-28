"""2C-03C: real CPU-systemd STOP after ORIGINAL PT central signed grant.

The unit executes only the existing FIXED 25-second CPU worker, not pickle.
All identities still belong to the original PT TaskRepository/OS journal.
No production stop API, StopReceipt, result upload or task release exists.
"""
from __future__ import annotations

from contextlib import closing
import hashlib
import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_os_supervisor_pt_export_rechecked_bridge_live import (
    _environment, _fresh_launch, _cleanup, _TASK, _NODE,
)

from platform_core.os_supervisor_authorization import GrantRejected
from platform_core.os_supervisor_pt_central_identity_registry_ci import (
    CiOnlyCentralPtOriginalRegistry,
    CiOnlyRootPtOriginalIdentityRegistration,
)
from platform_core.os_supervisor_pt_stop_observation import IsolatedPtStopObserver
from platform_core.os_supervisor_pt_stop_rechecked_bridge import (
    CiOnlyPtStopRecheckedBridge,
)
from platform_core.os_supervisor_pt_stop_root_witness_ci import (
    CiOnlyRootPtStopWitnessSigner, _BIND, verify_ci_root_stop_witness,
)


def test_actual_fixed_cpu_unit_central_cancel_to_original_cgroup_empty(tmp_path, monkeypatch):
    assert os.geteuid() == 0
    assert os.environ.get("GITHUB_ACTIONS") == "true"
    assert os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted"
    ctx = _environment(tmp_path)
    handle = ctx["handle"]
    unit = "changlian-os-" + handle + ".service"
    try:
        # Only substitute the CI-safe fixed 25s worker. The original central
        # recheck grant, root PT journal CAS and OS execution identity remain.
        monkeypatch.setattr(
            ctx["pilot"], "launch",
            lambda staged: ctx["pilot"].backend.launch(unit),
        )
        started = ctx["bridge"].start(
            handle_id=handle, task_attempt=3,
            central_launch_envelope=_fresh_launch(ctx),
            trusted_fixture=ctx["fixture"],
        )
        assert started["unit_name"] == unit
        assert started["state"] == "RUNNING"
        # Bridge.start deliberately returns a narrow receipt; live unit
        # ActiveState/SubState belong to the systemd backend inspection API.
        observed = ctx["pilot"].backend.inspect(unit, started["invocation_id"])
        assert observed["active_state"] == "active"
        assert observed["sub_state"] == "running"
        assert observed["main_pid"] == started["main_pid"]
        assert observed["control_group"] == started["control_group"]
        original = ctx["journal"].verified_pt_identity(handle, 3)
        # Register ORIGINAL OS identity while the CENTRAL task is RUNNING.
        # Central later signs STOP using ONLY this pre-registered scope, not
        # boot/InvocationID/PID supplied by an unprivileged Node Agent.
        original_signer = CiOnlyRootPtOriginalIdentityRegistration(
            ctx["journal"], isolated_ci_only=True,
        )
        central_registry = CiOnlyCentralPtOriginalRegistry(
            ctx["repo"], root_public_key=original_signer.public_key,
            central_key=ctx["key"], isolated_ci_only=True,
        )
        recorded = central_registry.register(
            original_signer.sign_original(handle, 3),
        )
        assert recorded["original_identity_registered_for_ci"] is True
        assert recorded["production_recovery_allowed"] is False
        with closing(ctx["repo"]._connect()) as db:
            db.execute("UPDATE tasks SET status='CANCEL_REQUESTED' WHERE task_id=?",
                       (_TASK,))
        nonce = ctx["journal"].issue_pt_stop_challenge(handle, 3)
        assert nonce == ctx["journal"].issue_pt_stop_challenge(handle, 3)
        envelope = central_registry.issue_original_stop(
            task_id=_TASK, task_attempt=3, node_id=_NODE,
            root_stop_challenge=nonce,
        )
        assert envelope["claims"]["boot_id"] == original["boot_id"]
        assert envelope["claims"]["invocation_id"] == original["invocation_id"]
        assert envelope["claims"]["main_pid"] == original["main_pid"]
        with pytest.raises(GrantRejected, match="UNREGISTERED_OR_STOP_REPLAY"):
            central_registry.issue_original_stop(
                task_id=_TASK, task_attempt=3, node_id=_NODE,
                root_stop_challenge=nonce,
            )
        claimed = ctx["journal"].claim_pt_stop_rechecked(
            handle, 3, envelope, trusted_public_key=ctx["key"].public_key(),
        )
        assert claimed["state"] == "STOP_INTENT_CLAIMED_OS_UNVERIFIED"
        assert claimed["trusted_stop_receipt_available"] is False
        with pytest.raises(GrantRejected):
            ctx["journal"].claim_pt_stop_rechecked(
                handle, 3, envelope, trusted_public_key=ctx["key"].public_key(),
            )
        observer = IsolatedPtStopObserver(
            journal=ctx["journal"], backend=ctx["pilot"].backend,
            isolated_ci_only=True,
        )
        stopped = CiOnlyPtStopRecheckedBridge(
            ctx["journal"], observer, isolated_ci_only=True,
        )
        signer = CiOnlyRootPtStopWitnessSigner(
            ctx["journal"], stopped, isolated_ci_only=True,
        )
        # In this disposable CI the challenge is a TEST constant. A real
        # central-issued, previously registered challenge is still absent:
        # therefore this test cannot authorize production recovery.
        witness_challenge_id = "f" * 32
        witness_nonce = "preissued-isolated-central-nonce-" + "a" * 24
        with closing(ctx["repo"]._connect()) as db:
            owner = db.execute(
                "SELECT task_id,attempt,worker_id,lease_token FROM tasks WHERE task_id=?",
                (_TASK,),
            ).fetchone()
        with closing(ctx["root"]._connect()) as db:
            original_intent = db.execute(
                """SELECT boot_id,unit_name FROM execution_intents
                   WHERE handle_id=? AND task_attempt=?""",
                (handle, 3),
            ).fetchone()
            original_os = db.execute(
                """SELECT invocation_id,control_group,main_pid
                   FROM pt_export_unit_identities WHERE handle_id=?""",
                (handle,),
            ).fetchone()
            stop_claim = db.execute(
                """SELECT stop_grant_digest,reason FROM pt_export_stop_claims
                   WHERE handle_id=?""",
                (handle,),
            ).fetchone()
        assert all(record is not None for record in (
            owner, original_intent, original_os, stop_claim,
        ))
        # Independent scope never derived from the signed witness body.
        expected = {
            "challenge_id": witness_challenge_id,
            "nonce": witness_nonce,
            "handle_id": handle,
            "task_id": owner["task_id"],
            "task_attempt": owner["attempt"],
            "worker_id": owner["worker_id"],
            "execution_lease_sha256": hashlib.sha256(
                owner["lease_token"].encode("utf-8")
            ).hexdigest(),
            "boot_id": original_intent["boot_id"],
            "unit": original_intent["unit_name"],
            "invocation_id": original_os["invocation_id"],
            "cgroup": original_os["control_group"],
            "main_pid": original_os["main_pid"],
            "stop_grant_digest": stop_claim["stop_grant_digest"],
            "stop_reason": stop_claim["reason"],
        }
        assert set(expected) == _BIND
        receipt = signer.stop_and_sign(
            handle, 3, challenge_id=witness_challenge_id,
            nonce=witness_nonce,
        )
        proof = receipt["payload"]
        assert verify_ci_root_stop_witness(
            receipt, public_key=signer.public_key,
            expected_original=expected, now=proof["issued_at"],
        )
        assert not verify_ci_root_stop_witness(
            receipt, public_key=signer.public_key,
            expected_original={**expected, "worker_id": "agent:wrong-node"},
            now=proof["issued_at"],
        )
        assert proof["purpose"] == "changlian-ci-root-pt-stop-witness-v1"
        assert proof["test_only_no_production_recovery"] is True
        assert proof["stop_grant_digest"] == claimed["stop_grant_digest"]
        assert proof["unit"] == started["unit_name"]
        assert proof["invocation_id"] == started["invocation_id"]
        assert proof["main_pid"] == started["main_pid"]
        assert proof["os_cgroup_empty"] is True
        assert proof["stop_requested_ns"] <= proof["empty_observed_ns"]
        with pytest.raises(GrantRejected, match="OS_STOP_OBSERVATION_NOT_AUTHORIZED"):
            signer.stop_and_sign(
                handle, 3, challenge_id="f" * 32,
                nonce="preissued-isolated-central-nonce-" + "a" * 24,
            )
        with closing(ctx["root"]._connect()) as db:
            assert db.execute(
                "SELECT state FROM execution_intents WHERE handle_id=?",
                (handle,),
            ).fetchone()[0] == "RUNNING"
            assert db.execute(
                "SELECT COUNT(*) FROM pt_export_stop_claims WHERE handle_id=?",
                (handle,),
            ).fetchone()[0] == 1
            assert db.execute(
                "SELECT COUNT(*) FROM pt_export_stop_observation_claims WHERE handle_id=?",
                (handle,),
            ).fetchone()[0] == 1
        with closing(ctx["repo"]._connect()) as db:
            assert db.execute(
                "SELECT status FROM tasks WHERE task_id=?", (_TASK,),
            ).fetchone()[0] == "CANCEL_REQUESTED"
        print("PT_SIGNED_CENTRAL_STOP_TO_ORIGINAL_CGROUP_NO_RECEIPT", {
            "invocation_id": proof["invocation_id"],
            "original_cgroup_became_empty": proof["os_cgroup_empty"],
            "test_only_no_production_recovery": proof["test_only_no_production_recovery"],
        }, flush=True)
    finally:
        _cleanup(ctx["fixture"], handle)
