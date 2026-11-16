"""2C-03C root journal one-shot STOP intent, no real stop or production switch."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import time

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from platform_core.os_supervisor_authorization import GrantRejected
from platform_core.os_supervisor_journal import ExecutionJournal
from platform_core.os_supervisor_pt_export_launch import PtExportJournal
from platform_core.os_supervisor_pt_stop_grant import (
    CentralPtStopTrialIssuer, verify_pt_stop_grant,
)

# Reuse the EXISTING original central TaskRepository, Agent node and root
# PT journal fixture. No new scheduler, synthetic second attempt or OS launch.
# The test tree has no __init__.py; force this sibling path to the front rather
# than accidentally importing an unrelated installed "tests" package.
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_os_supervisor_pt_export_launch import (
    BOOT, NODE, TASK, LEASE, stage, registered, launch_grant,
)

INV = "b" * 32
PID = 43210


@pytest.fixture
def original_running(stage):
    repo, artifacts, key, token, issuer, root, pt, scope = stage
    admitted, admission = registered(stage)
    handle = admitted["handle_id"]
    signed_launch = launch_grant(stage, handle, admission)
    pt.claim_rechecked_launch(
        handle, 3, signed_launch, trusted_public_key=key.public_key(),
    )
    pt.record_pt_systemd_identity(
        handle, 3, invocation_id=INV,
        control_group="/system.slice/changlian-os-" + handle + ".service",
        main_pid=PID,
    )
    assert pt.verified_pt_identity(handle, 3)["invocation_id"] == INV
    return stage, handle


def stop_scope(original_running, *, mark_cancel=True):
    stage, handle = original_running
    repo, artifacts, key, token, issuer, root, pt, scope = stage
    if mark_cancel:
        with closing(repo._connect()) as db:
            db.execute(
                "UPDATE tasks SET status='CANCEL_REQUESTED' WHERE task_id=?",
                (TASK,),
            )
    nonce = pt.issue_pt_stop_challenge(handle, 3)
    central = CentralPtStopTrialIssuer(repo, key, isolated_test_only=True)
    grant = central.issue(
        task_id=TASK, task_attempt=3, node_id=NODE, boot_id=BOOT,
        handle_id=handle, invocation_id=INV, main_pid=PID, challenge=nonce,
    )
    return grant, nonce


def test_central_cancel_grant_is_one_shot_root_journal_intent(original_running):
    stage, handle = original_running
    repo, artifacts, key, token, issuer, root, pt, scope = stage
    envelope, nonce = stop_scope(original_running)
    claim = pt.claim_pt_stop_rechecked(
        handle, 3, envelope, trusted_public_key=key.public_key(),
    )
    assert claim["state"] == "STOP_INTENT_CLAIMED_OS_UNVERIFIED"
    assert claim["stop_authorized_for_production"] is False
    assert claim["os_stopped"] is False
    assert claim["trusted_stop_receipt_available"] is False
    assert claim["central_recovery_allowed"] is False
    with closing(root._connect()) as db:
        row = db.execute(
            """SELECT stop_grant_digest,invocation_id,main_pid,reason
               FROM pt_export_stop_claims WHERE handle_id=?""", (handle,),
        ).fetchone()
        assert row["stop_grant_digest"] == claim["stop_grant_digest"]
        assert row["invocation_id"] == INV
        assert row["main_pid"] == PID
        assert row["reason"] == "CANCEL_REQUESTED"
        assert db.execute(
            "SELECT state FROM execution_intents WHERE handle_id=?",
            (handle,),
        ).fetchone()[0] == "RUNNING"
        assert db.execute(
            "SELECT COUNT(*) FROM execution_intents WHERE task_id=?",
            (TASK,),
        ).fetchone()[0] == 1
    with pytest.raises(GrantRejected, match="STOP_CLAIM"):
        pt.claim_pt_stop_rechecked(
            handle, 3, envelope, trusted_public_key=key.public_key(),
        )
    with pytest.raises(GrantRejected, match="STOP_CHALLENGE"):
        pt.issue_pt_stop_challenge(handle, 3)
    reopened = PtExportJournal(ExecutionJournal(
        root.path, test_only_unprivileged=True, boot_id_for_tests=BOOT,
    ))
    with pytest.raises(GrantRejected, match="STOP_CLAIM"):
        reopened.claim_pt_stop_rechecked(
            handle, 3, envelope, trusted_public_key=key.public_key(),
        )


def test_non_cancelled_live_lease_cannot_get_signed_stop(original_running):
    stage, handle = original_running
    repo, artifacts, key, token, issuer, root, pt, scope = stage
    nonce = pt.issue_pt_stop_challenge(handle, 3)
    central = CentralPtStopTrialIssuer(repo, key, isolated_test_only=True)
    with pytest.raises(GrantRejected, match="STOP_REASON"):
        central.issue(
            task_id=TASK, task_attempt=3, node_id=NODE, boot_id=BOOT,
            handle_id=handle, invocation_id=INV, main_pid=PID,
            challenge=nonce,
        )
    with closing(root._connect()) as db:
        assert db.execute("SELECT COUNT(*) FROM pt_export_stop_claims").fetchone()[0] == 0


def test_expired_held_original_lease_allows_stop_not_recovery(original_running):
    stage, handle = original_running
    repo, artifacts, key, token, issuer, root, pt, scope = stage
    with closing(repo._connect()) as db:
        db.execute(
            """UPDATE tasks SET status='RUNNING',
                  stage='recovery_blocked_remote_agent_unverified',
                  lease_expires_at=? WHERE task_id=?""",
            ((datetime.now(timezone.utc) - timedelta(seconds=20)).isoformat(), TASK),
        )
    nonce = pt.issue_pt_stop_challenge(handle, 3)
    envelope = CentralPtStopTrialIssuer(
        repo, key, isolated_test_only=True,
    ).issue(
        task_id=TASK, task_attempt=3, node_id=NODE, boot_id=BOOT,
        handle_id=handle, invocation_id=INV, main_pid=PID,
        challenge=nonce,
    )
    assert envelope["claims"]["reason"] == "LEASE_EXPIRED_HELD"
    claimed = pt.claim_pt_stop_rechecked(
        handle, 3, envelope, trusted_public_key=key.public_key(),
    )
    assert claimed["os_stopped"] is False
    assert claimed["central_recovery_allowed"] is False
    with closing(repo._connect()) as db:
        task = db.execute(
            "SELECT status,attempt,worker_id,lease_token FROM tasks WHERE task_id=?",
            (TASK,),
        ).fetchone()
        assert task["status"] == "RUNNING"
        assert task["attempt"] == 3
        assert task["worker_id"] == "agent:" + NODE
        assert task["lease_token"] == LEASE


@pytest.mark.parametrize("sql", [
    "UPDATE tasks SET status='RUNNING'",
    "UPDATE tasks SET attempt=4",
    "UPDATE tasks SET worker_id='agent:elsewhere'",
    "UPDATE tasks SET kind='TRAINING'",
])
def test_central_original_task_change_fences_stop_grant(original_running, sql):
    stage, handle = original_running
    repo, artifacts, key, token, issuer, root, pt, scope = stage
    with closing(repo._connect()) as db:
        db.execute("UPDATE tasks SET status='CANCEL_REQUESTED' WHERE task_id=?", (TASK,))
        db.execute(sql + " WHERE task_id=?" if " WHERE " not in sql else sql, (TASK,))
    nonce = pt.issue_pt_stop_challenge(handle, 3)
    central = CentralPtStopTrialIssuer(repo, key, isolated_test_only=True)
    with pytest.raises(GrantRejected, match="PT_STOP_GRANT_"):
        central.issue(
            task_id=TASK, task_attempt=3, node_id=NODE, boot_id=BOOT,
            handle_id=handle, invocation_id=INV, main_pid=PID, challenge=nonce,
        )
    with closing(root._connect()) as db:
        assert db.execute("SELECT COUNT(*) FROM pt_export_stop_claims").fetchone()[0] == 0


def test_rotated_original_lease_is_rejected_at_root_not_assumed_at_issuer(
    original_running,
):
    # Central sees ONLY the current original task snapshot. When the current
    # token has changed, a newly signed grant may be well-formed, but the
    # immutable original OS journal carries the OLD lease digest and MUST
    # refuse the stop. No systemd operation or central release follows.
    stage, handle = original_running
    repo, artifacts, key, token, issuer, root, pt, scope = stage
    with closing(repo._connect()) as db:
        db.execute(
            "UPDATE tasks SET status='CANCEL_REQUESTED',lease_token=? WHERE task_id=?",
            ("new-original-task-lease-" + "z" * 32, TASK),
        )
    nonce = pt.issue_pt_stop_challenge(handle, 3)
    grant = CentralPtStopTrialIssuer(
        repo, key, isolated_test_only=True,
    ).issue(
        task_id=TASK, task_attempt=3, node_id=NODE, boot_id=BOOT,
        handle_id=handle, invocation_id=INV, main_pid=PID,
        challenge=nonce,
    )
    assert grant["claims"]["execution_lease_sha256"] != scope[
        "execution_lease_sha256"
    ]
    with pytest.raises(GrantRejected, match="ORIGINAL_SCOPE_OR_NONCE_STALE"):
        pt.claim_pt_stop_rechecked(
            handle, 3, grant, trusted_public_key=key.public_key(),
        )
    with pytest.raises(GrantRejected, match="OS_STOP_OBSERVATION_NOT_AUTHORIZED"):
        pt.claim_pt_os_stop_observation(handle, 3)
    with closing(root._connect()) as db:
        assert db.execute(
            "SELECT COUNT(*) FROM pt_export_stop_claims",
        ).fetchone()[0] == 0
        assert db.execute(
            "SELECT COUNT(*) FROM pt_export_stop_observation_claims",
        ).fetchone()[0] == 0


@pytest.mark.parametrize("field,value", [
    ("invocation_id", "c" * 32),
    ("main_pid", 99999),
    ("boot_id", "ffffffff-ffff-ffff-ffff-ffffffffffff"),
    ("task_attempt", 4),
    ("worker_id", "agent:other-node"),
    ("execution_lease_sha256", "f" * 64),
    ("reason", "LEASE_EXPIRED_HELD"),
    ("challenge", "f" * 32),
])
def test_forged_or_wrong_binding_signature_cannot_claim(original_running, field, value):
    stage, handle = original_running
    repo, artifacts, key, token, issuer, root, pt, scope = stage
    envelope, nonce = stop_scope(original_running)
    forged = {"claims": {**envelope["claims"], field: value},
              "signature": envelope["signature"]}
    with pytest.raises(GrantRejected, match="PT_STOP_GRANT_"):
        pt.claim_pt_stop_rechecked(
            handle, 3, forged, trusted_public_key=key.public_key(),
        )
    with closing(root._connect()) as db:
        assert db.execute("SELECT COUNT(*) FROM pt_export_stop_claims").fetchone()[0] == 0


def test_other_public_key_cannot_claim(original_running):
    stage, handle = original_running
    repo, artifacts, key, token, issuer, root, pt, scope = stage
    grant, nonce = stop_scope(original_running)
    with pytest.raises(GrantRejected, match="SIGNATURE"):
        pt.claim_pt_stop_rechecked(
            handle, 3, grant,
            trusted_public_key=Ed25519PrivateKey.generate().public_key(),
        )


def test_signed_stop_grant_is_not_a_launch_authority(original_running):
    stage, handle = original_running
    repo, artifacts, key, token, issuer, root, pt, scope = stage
    grant, nonce = stop_scope(original_running)
    from platform_core.os_supervisor_pt_export_launch import verify_pt_export_launch_grant
    with pytest.raises(GrantRejected, match="HOLD"):
        verify_pt_export_launch_grant(
            grant, trusted_public_key=key.public_key(), expected_binding={},
            handle_id=handle, registered_grant_digest="0" * 64,
            now=int(time.time()), launch_challenge_issued_at=int(time.time()),
        )
    with closing(root._connect()) as db:
        assert db.execute("SELECT COUNT(*) FROM pt_export_stop_claims").fetchone()[0] == 0


def test_expired_root_stop_challenge_cannot_be_renewed_or_claimed(original_running):
    stage, handle = original_running
    repo, artifacts, key, token, issuer, root, pt, scope = stage
    nonce = pt.issue_pt_stop_challenge(handle, 3, now=100)
    with pytest.raises(GrantRejected, match="EXPIRED"):
        pt.issue_pt_stop_challenge(handle, 3, now=131)
    with closing(root._connect()) as db:
        assert db.execute("SELECT COUNT(*) FROM pt_export_stop_claims").fetchone()[0] == 0


def test_stop_grant_disabled_default_and_original_boot_fenced(original_running):
    stage, handle = original_running
    repo, artifacts, key, token, issuer, root, pt, scope = stage
    nonce = pt.issue_pt_stop_challenge(handle, 3)
    with pytest.raises(GrantRejected, match="ISSUER_DISABLED"):
        CentralPtStopTrialIssuer(repo, key).issue(
            task_id=TASK, task_attempt=3, node_id=NODE, boot_id=BOOT,
            handle_id=handle, invocation_id=INV, main_pid=PID, challenge=nonce,
        )
    wrong_boot = PtExportJournal(ExecutionJournal(
        root.path, test_only_unprivileged=True,
        boot_id_for_tests="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    ))
    with pytest.raises(GrantRejected, match="HOLD"):
        wrong_boot.issue_pt_stop_challenge(handle, 3)


def test_cannot_probe_os_without_signed_central_stop_claim(original_running):
    stage, handle = original_running
    repo, artifacts, key, token, issuer, root, pt, scope = stage
    with pytest.raises(GrantRejected, match="OS_STOP_OBSERVATION_NOT_AUTHORIZED"):
        pt.claim_pt_os_stop_observation(handle, 3)
    with closing(root._connect()) as db:
        assert db.execute(
            "SELECT COUNT(*) FROM pt_export_stop_observation_claims",
        ).fetchone()[0] == 0


def test_one_signed_stop_can_claim_only_one_os_probe_even_after_restart(original_running):
    stage, handle = original_running
    repo, artifacts, key, token, issuer, root, pt, scope = stage
    envelope, nonce = stop_scope(original_running)
    claimed = pt.claim_pt_stop_rechecked(
        handle, 3, envelope, trusted_public_key=key.public_key(),
    )
    probe = pt.claim_pt_os_stop_observation(handle, 3)
    assert probe["stop_grant_digest"] == claimed["stop_grant_digest"]
    assert probe["invocation_id"] == INV
    assert probe["main_pid"] == PID
    assert probe["state"] == "OS_STOP_OBSERVATION_CLAIMED_NO_RECEIPT"
    assert probe["trusted_stop_receipt_available"] is False
    with pytest.raises(GrantRejected, match="OS_STOP_OBSERVATION_NOT_AUTHORIZED"):
        pt.claim_pt_os_stop_observation(handle, 3)
    reopened = PtExportJournal(ExecutionJournal(
        root.path, test_only_unprivileged=True, boot_id_for_tests=BOOT,
    ))
    with pytest.raises(GrantRejected, match="OS_STOP_OBSERVATION_NOT_AUTHORIZED"):
        reopened.claim_pt_os_stop_observation(handle, 3)
    with closing(root._connect()) as db:
        assert db.execute(
            "SELECT COUNT(*) FROM pt_export_stop_observation_claims",
        ).fetchone()[0] == 1
        assert db.execute(
            "SELECT state FROM execution_intents WHERE handle_id=?",
            (handle,),
        ).fetchone()[0] == "RUNNING"


@pytest.mark.parametrize("column,value", [
    ("invocation_id", "c" * 32),
    ("main_pid", 56789),
])
def test_changed_original_os_identity_after_stop_grant_never_probes(
    original_running, column, value,
):
    stage, handle = original_running
    repo, artifacts, key, token, issuer, root, pt, scope = stage
    envelope, nonce = stop_scope(original_running)
    pt.claim_pt_stop_rechecked(
        handle, 3, envelope, trusted_public_key=key.public_key(),
    )
    with closing(root._connect()) as db:
        db.execute(
            f"UPDATE pt_export_unit_identities SET {column}=? WHERE handle_id=?",
            (value, handle),
        )
    with pytest.raises(GrantRejected, match="OS_STOP_OBSERVATION_NOT_AUTHORIZED"):
        pt.claim_pt_os_stop_observation(handle, 3)
    with closing(root._connect()) as db:
        assert db.execute(
            "SELECT COUNT(*) FROM pt_export_stop_observation_claims",
        ).fetchone()[0] == 0


def test_stale_stop_grant_never_allows_delayed_os_probe(original_running):
    stage, handle = original_running
    repo, artifacts, key, token, issuer, root, pt, scope = stage
    envelope, nonce = stop_scope(original_running)
    pt.claim_pt_stop_rechecked(
        handle, 3, envelope, trusted_public_key=key.public_key(),
    )
    with closing(root._connect()) as db:
        claimed_at = db.execute(
            "SELECT claimed_at FROM pt_export_stop_claims WHERE handle_id=?",
            (handle,),
        ).fetchone()[0]
    with pytest.raises(GrantRejected, match="OS_STOP_OBSERVATION_NOT_AUTHORIZED"):
        pt.claim_pt_os_stop_observation(handle, 3, now=claimed_at + 13)


def test_wrong_boot_cannot_claim_original_os_probe(original_running):
    stage, handle = original_running
    repo, artifacts, key, token, issuer, root, pt, scope = stage
    envelope, nonce = stop_scope(original_running)
    pt.claim_pt_stop_rechecked(
        handle, 3, envelope, trusted_public_key=key.public_key(),
    )
    changed_boot = PtExportJournal(ExecutionJournal(
        root.path, test_only_unprivileged=True,
        boot_id_for_tests="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    ))
    with pytest.raises(GrantRejected, match="OS_STOP_OBSERVATION_NOT_AUTHORIZED"):
        changed_boot.claim_pt_os_stop_observation(handle, 3)


def test_stop_bridge_is_inaccessible_by_default():
    from platform_core.os_supervisor_pt_stop_rechecked_bridge import (
        CiOnlyPtStopRecheckedBridge,
    )
    with pytest.raises(GrantRejected, match="PRODUCTION_DISABLED"):
        CiOnlyPtStopRecheckedBridge(None, None)
