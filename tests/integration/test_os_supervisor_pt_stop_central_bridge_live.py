"""2C-03C: real CPU-systemd STOP after ORIGINAL PT central signed grant.

The unit executes only the existing FIXED 25-second CPU worker, not pickle.
All identities still belong to the original PT TaskRepository/OS journal.
No production stop API, StopReceipt, result upload or task release exists.
"""
from __future__ import annotations

from contextlib import closing
import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_os_supervisor_pt_export_rechecked_bridge_live import (
    _environment, _fresh_launch, _cleanup, _TASK, _NODE,
)

from platform_core.os_supervisor_authorization import GrantRejected
from platform_core.os_supervisor_pt_stop_grant import CentralPtStopTrialIssuer
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
        with closing(ctx["repo"]._connect()) as db:
            db.execute("UPDATE tasks SET status='CANCEL_REQUESTED' WHERE task_id=?",
                       (_TASK,))
        nonce = ctx["journal"].issue_pt_stop_challenge(handle, 3)
        assert nonce == ctx["journal"].issue_pt_stop_challenge(handle, 3)
        central = CentralPtStopTrialIssuer(
            ctx["repo"], ctx["key"], isolated_test_only=True,
        )
        envelope = central.issue(
            task_id=_TASK, task_attempt=3, node_id=_NODE,
            boot_id=ctx["root"].boot_id, handle_id=handle,
            invocation_id=original["invocation_id"],
            main_pid=original["main_pid"], challenge=nonce,
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
        receipt = signer.stop_and_sign(
            handle, 3, challenge_id="f" * 32,
            nonce="preissued-isolated-central-nonce-" + "a" * 24,
        )
        proof = receipt["payload"]
        expected = {name: proof[name] for name in _BIND}
        assert verify_ci_root_stop_witness(
            receipt, public_key=signer.public_key,
            expected_original=expected, now=proof["issued_at"],
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
