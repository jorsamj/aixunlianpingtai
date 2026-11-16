"""2C-03E isolated root-signed ORIGINAL OS registration at central.

No production API, persistent central registration, GPU release or recovery.
Uses existing actual TaskRepository + root PtExportJournal test fixtures.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timezone
import os
from pathlib import Path
import sys

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_os_supervisor_pt_export_launch import TASK, NODE, BOOT
from test_os_supervisor_pt_stop_grant import original_running

from platform_core.os_supervisor_authorization import GrantRejected
from platform_core.os_supervisor_pt_central_identity_registry_ci import (
    CiOnlyCentralPtOriginalRegistry, CiOnlyRootPtOriginalIdentityRegistration,
    _bytes,
)


@pytest.fixture
def registration(original_running, monkeypatch):
    if os.name != "posix":
        pytest.skip("CI root signing only on Linux, not Windows")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("RUNNER_ENVIRONMENT", "github-hosted")
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    stage, handle = original_running
    repo, artifacts, key, node_token, issuer, root, pt, scope = stage
    root_signer = CiOnlyRootPtOriginalIdentityRegistration(
        pt, isolated_ci_only=True,
    )
    central = CiOnlyCentralPtOriginalRegistry(
        repo, root_public_key=root_signer.public_key,
        central_key=key, isolated_ci_only=True,
    )
    return stage, handle, root_signer, central


def _cancel_and_challenge(registration):
    stage, handle, signer, central = registration
    repo, artifacts, key, node_token, issuer, root, pt, scope = stage
    with closing(repo._connect()) as db:
        db.execute(
            "UPDATE tasks SET status='CANCEL_REQUESTED' WHERE task_id=?",
            (TASK,),
        )
    return pt.issue_pt_stop_challenge(handle, 3)


def test_exact_original_root_identity_registered_then_central_stop_cas(registration):
    stage, handle, signer, central = registration
    repo, artifacts, key, node_token, issuer, root, pt, scope = stage
    signed = signer.sign_original(handle, 3)
    assert signed["claims"]["boot_id"] == BOOT
    assert signed["claims"]["main_pid"] == 43210
    result = central.register(signed)
    assert result["original_identity_registered_for_ci"] is True
    assert result["production_recovery_allowed"] is False
    nonce = _cancel_and_challenge(registration)
    stopped = central.issue_original_stop(
        task_id=TASK, task_attempt=3, node_id=NODE,
        root_stop_challenge=nonce,
    )
    assert stopped["claims"]["handle_id"] == handle
    assert stopped["claims"]["invocation_id"] == "b" * 32
    assert stopped["claims"]["execution_lease_sha256"] == scope[
        "execution_lease_sha256"
    ]
    assert "trusted_stop_receipt_available" not in stopped
    os_claim = pt.claim_pt_stop_rechecked(
        handle, 3, stopped, trusted_public_key=key.public_key(),
    )
    assert os_claim["state"] == "STOP_INTENT_CLAIMED_OS_UNVERIFIED"
    with pytest.raises(GrantRejected, match="UNREGISTERED_OR_STOP_REPLAY"):
        central.issue_original_stop(
            task_id=TASK, task_attempt=3, node_id=NODE,
            root_stop_challenge=nonce,
        )
    with closing(repo._connect()) as db:
        assert db.execute(
            "SELECT status FROM tasks WHERE task_id=?", (TASK,),
        ).fetchone()[0] == "CANCEL_REQUESTED"
    with closing(root._connect()) as db:
        assert db.execute(
            "SELECT count(*) FROM pt_export_stop_claims",
        ).fetchone()[0] == 1


def test_cannot_issue_stop_for_caller_supplied_os_identity(registration):
    stage, handle, signer, central = registration
    central.register(signer.sign_original(handle, 3))
    nonce = _cancel_and_challenge(registration)
    with pytest.raises(TypeError):
        central.issue_original_stop(
            task_id=TASK, task_attempt=3, node_id=NODE,
            root_stop_challenge=nonce, invocation_id="c" * 32,
        )
    with pytest.raises(TypeError):
        central.issue_original_stop(
            task_id=TASK, task_attempt=3, node_id=NODE,
            root_stop_challenge=nonce, main_pid=1,
        )
    # Still works with registered identity after malicious calls failed.
    signed = central.issue_original_stop(
        task_id=TASK, task_attempt=3, node_id=NODE,
        root_stop_challenge=nonce,
    )
    assert signed["claims"]["invocation_id"] == "b" * 32


def test_no_registration_or_wrong_node_must_hold(registration):
    stage, handle, signer, central = registration
    nonce = _cancel_and_challenge(registration)
    with pytest.raises(GrantRejected, match="UNREGISTERED"):
        central.issue_original_stop(
            task_id=TASK, task_attempt=3, node_id=NODE,
            root_stop_challenge=nonce,
        )
    central.register(signer.sign_original(handle, 3))
    with pytest.raises(GrantRejected, match="REGISTERED_NODE"):
        central.issue_original_stop(
            task_id=TASK, task_attempt=3, node_id="different-node",
            root_stop_challenge=nonce,
        )


def test_live_non_cancelled_task_must_refuse_stop(registration):
    stage, handle, signer, central = registration
    repo, artifacts, key, node_token, issuer, root, pt, scope = stage
    central.register(signer.sign_original(handle, 3))
    nonce = pt.issue_pt_stop_challenge(handle, 3)
    with pytest.raises(GrantRejected, match="STOP_REASON"):
        central.issue_original_stop(
            task_id=TASK, task_attempt=3, node_id=NODE,
            root_stop_challenge=nonce,
        )
    # Denial must not consume the single STOP grant opportunity.
    _cancel_and_challenge(registration)
    signed = central.issue_original_stop(
        task_id=TASK, task_attempt=3, node_id=NODE,
        root_stop_challenge=nonce,
    )
    assert signed["claims"]["reason"] == "CANCEL_REQUESTED"


@pytest.mark.parametrize("mutation", [
    ("lease_token", "swapped-original-lease-" + "x" * 36),
    ("attempt", 4),
    ("worker_id", "agent:replacement-node"),
    ("kind", "TRAINING"),
    ("resource_key", "gpu-default"),
])
def test_any_original_owner_or_lease_change_fences_registered_stop(registration, mutation):
    stage, handle, signer, central = registration
    repo, artifacts, key, node_token, issuer, root, pt, scope = stage
    central.register(signer.sign_original(handle, 3))
    nonce = _cancel_and_challenge(registration)
    field, value = mutation
    assert field in {"lease_token", "attempt", "worker_id", "kind", "resource_key"}
    with closing(repo._connect()) as db:
        db.execute(
            f"UPDATE tasks SET {field}=? WHERE task_id=?", (value, TASK),
        )
    with pytest.raises(GrantRejected, match="ORIGINAL_TASK_OR_LEASE_CHANGED"):
        central.issue_original_stop(
            task_id=TASK, task_attempt=3, node_id=NODE,
            root_stop_challenge=nonce,
        )
    with closing(root._connect()) as db:
        assert db.execute(
            "SELECT COUNT(*) FROM pt_export_stop_claims",
        ).fetchone()[0] == 0


def test_forged_or_wrong_root_key_registration_denied(registration):
    stage, handle, signer, central = registration
    repo, artifacts, key, node_token, issuer, root, pt, scope = stage
    legit = signer.sign_original(handle, 3)
    forged = {
        "claims": {**legit["claims"], "invocation_id": "c" * 32},
        "signature": legit["signature"],
    }
    with pytest.raises(GrantRejected, match="ROOT_SIGNATURE_UNTRUSTED"):
        central.register(forged)
    other = Ed25519PrivateKey.generate()
    wrong_root = CiOnlyCentralPtOriginalRegistry(
        repo, root_public_key=other.public_key(),
        central_key=key, isolated_ci_only=True,
    )
    with pytest.raises(GrantRejected, match="ROOT_SIGNATURE_UNTRUSTED"):
        wrong_root.register(legit)
    assert central.register(legit)["original_identity_registered_for_ci"] is True


def test_registration_is_immutable_and_cannot_replay(registration):
    stage, handle, signer, central = registration
    legit = signer.sign_original(handle, 3)
    central.register(legit)
    with pytest.raises(GrantRejected, match="REPLAY_OR_DUPLICATE"):
        central.register(legit)
    with pytest.raises(GrantRejected, match="REPLAY_OR_DUPLICATE"):
        central.register(signer.sign_original(handle, 3))


def test_failed_or_expired_root_identity_registration_is_not_accepted(registration):
    stage, handle, signer, central = registration
    signed = signer.sign_original(handle, 3)
    with pytest.raises(GrantRejected, match="STALE_OR_FUTURE_IDENTITY"):
        central.register(signed, now=signed["claims"]["expires_at"])
    with pytest.raises(GrantRejected, match="STALE_OR_FUTURE_IDENTITY"):
        central.register(signed, now=signed["claims"]["issued_at"] - 3)
    central.register(signed, now=signed["claims"]["issued_at"])
    with pytest.raises(GrantRejected, match="ROOT_SIGNATURE_UNTRUSTED"):
        central.register({
            **signed, "signature": "0" * 128,
        })


def test_central_stop_issuance_concurrency_is_one_shot(registration):
    stage, handle, signer, central = registration
    central.register(signer.sign_original(handle, 3))
    nonce = _cancel_and_challenge(registration)
    def issue(_):
        try:
            result = central.issue_original_stop(
                task_id=TASK, task_attempt=3, node_id=NODE,
                root_stop_challenge=nonce,
            )
            return result["claims"]["handle_id"]
        except GrantRejected:
            return "denied"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(issue, range(2)))
    assert sorted(results) == sorted([handle, "denied"])


def test_root_cannot_sign_missing_or_non_running_original_journal(registration):
    stage, handle, signer, central = registration
    repo, artifacts, key, node_token, issuer, root, pt, scope = stage
    with closing(root._connect()) as db:
        db.execute(
            "UPDATE execution_intents SET state='UNKNOWN' WHERE handle_id=?",
            (handle,),
        )
    with pytest.raises(GrantRejected, match="HOLD"):
        signer.sign_original(handle, 3)


def test_default_production_gates_reject_ci_registry(registration, monkeypatch):
    stage, handle, signer, central = registration
    repo, artifacts, key, node_token, issuer, root, pt, scope = stage
    with pytest.raises(GrantRejected, match="PRODUCTION_DISABLED"):
        CiOnlyRootPtOriginalIdentityRegistration(pt)
    with pytest.raises(GrantRejected, match="PRODUCTION_DISABLED"):
        CiOnlyCentralPtOriginalRegistry(
            repo, root_public_key=signer.public_key,
            central_key=key,
        )
    monkeypatch.delenv("GITHUB_ACTIONS")
    with pytest.raises(GrantRejected, match="PRODUCTION_DISABLED"):
        CiOnlyRootPtOriginalIdentityRegistration(
            pt, isolated_ci_only=True,
        )
    with pytest.raises(GrantRejected, match="PRODUCTION_DISABLED"):
        CiOnlyCentralPtOriginalRegistry(
            repo, root_public_key=signer.public_key,
            central_key=key, isolated_ci_only=True,
        )


def test_ci_registry_no_production_persistent_identity_store(registration):
    stage, handle, signer, central = registration
    central.register(signer.sign_original(handle, 3))
    dbinfo = central._db.execute("PRAGMA database_list").fetchall()
    assert len(dbinfo) == 1 and dbinfo[0][2] == ""
    assert not hasattr(central, "recover")
    assert not hasattr(central, "release_gpu")
    assert not hasattr(central, "publish")
