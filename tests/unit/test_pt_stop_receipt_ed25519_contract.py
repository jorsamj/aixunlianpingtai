"""2C-03B: real Ed25519 crypto, but ONLY central SQLite :memory: simulation."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import sys

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "poc"))
import central_stop_recovery_contract as central
from pt_stop_receipt_ed25519_contract import (
    IsolatedWitnessRejected, isolated_test_witness_verifier,
    sign_test_only_stop_witness, synthetic_payload,
)

_NOW = datetime(2026, 11, 16, 5, 0, tzinfo=timezone.utc)
_BOUND = {
    "boot_id": "01234567-89ab-cdef-0123-456789abcdef",
    "invocation_id": "b" * 32,
    "unit": "clpoc-" + "a" * 24 + ".service",
    "cgroup": "/user.slice/app.slice/clpoc-" + "a" * 24 + ".service",
}
_TOKEN = "isolated-old-original-lease-" + "x" * 24


@pytest.fixture
def scratch():
    db = sqlite3.connect(":memory:", isolation_level=None)
    central.init_scratch_schema(db)
    db.execute(
        """INSERT INTO tasks(task_id,attempt,status,stage,worker_id,
           lease_token,lease_expires_at,resource_wait_reason,process_pid)
           VALUES(?,?,?,?,?,?,?,?,?)""",
        ("conv_pt_isolated_001", 9, "RUNNING", central.HOLD,
         "agent:ci-gpu-node", _TOKEN,
         (_NOW - timedelta(seconds=4)).isoformat(),
         "REMOTE_AGENT_STOP_UNVERIFIED", 12345),
    )
    db.execute(
        "INSERT INTO gpu_reservations(task_id,worker_id,lease_token,policy) VALUES(?,?,?,?)",
        ("conv_pt_isolated_001", "agent:ci-gpu-node", _TOKEN, "exclusive"),
    )
    key = Ed25519PrivateKey.generate()
    yield db, key
    db.close()


def _challenge(db):
    return central.issue_challenge(
        db, task_id="conv_pt_isolated_001", node_id="ci-gpu-node",
        now=_NOW, **_BOUND,
    )


def _sign(key, scope):
    return sign_test_only_stop_witness(
        synthetic_payload(scope), key, isolated_test_only=True,
    )


def _commit(db, key, envelope, *, now=None):
    return central.commit_test_recovery(
        db, attestation=envelope,
        now=now or _NOW + timedelta(seconds=1),
        independent_witness_verifier=isolated_test_witness_verifier(
            key.public_key(), isolated_test_only=True,
        ),
    )


def _unchanged(db):
    status, stage, worker_id, lease, attempt = db.execute(
        "SELECT status,stage,worker_id,lease_token,attempt FROM tasks"
    ).fetchone()
    return (status, stage, worker_id, lease, attempt) == (
        "RUNNING", central.HOLD, "agent:ci-gpu-node", _TOKEN, 9,
    ) and db.execute("SELECT COUNT(*) FROM gpu_reservations").fetchone()[0] == 1


def test_ed25519_one_shot_original_task_lease_and_gpu_cas(scratch):
    db, key = scratch
    challenge = _challenge(db)
    receipt = _sign(key, challenge)
    assert receipt["payload"]["execution_generation"] == 9
    assert isolated_test_witness_verifier(
        key.public_key(), isolated_test_only=True,
    )(receipt) is True
    finished = _commit(db, key, receipt)
    assert finished == {
        "task_id": "conv_pt_isolated_001",
        "status": "QUEUED",
        "previous_execution_generation": 9,
        "challenge_consumed": True,
        "scratch_only": True,
    }
    task = db.execute(
        "SELECT status,stage,attempt,worker_id,lease_token,process_pid FROM tasks"
    ).fetchone()
    assert task == ("QUEUED", "recovered", 9, None, None, None)
    assert db.execute("SELECT COUNT(*) FROM gpu_reservations").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM recovery_audit").fetchone()[0] == 1
    with pytest.raises(central.RecoveryRejected, match="CONSUMED"):
        _commit(db, key, receipt)
    assert db.execute("SELECT COUNT(*) FROM recovery_audit").fetchone()[0] == 1


def test_cancellation_request_is_preserved_as_cancelled(scratch):
    db, key = scratch
    db.execute("UPDATE tasks SET status='CANCEL_REQUESTED'")
    receipt = _sign(key, _challenge(db))
    result = _commit(db, key, receipt)
    assert result["status"] == "CANCELLED"
    assert db.execute("SELECT finished_at FROM tasks").fetchone()[0] is not None
    assert db.execute("SELECT COUNT(*) FROM gpu_reservations").fetchone()[0] == 0


@pytest.mark.parametrize("field,value", [
    ("task_id", "conv_other_001"),
    ("execution_generation", 10),
    ("worker_id", "agent:other-node"),
    ("boot_id", "ffffffff-ffff-ffff-ffff-ffffffffffff"),
    ("invocation_id", "c" * 32),
    ("unit", "clpoc-" + "c" * 24 + ".service"),
    ("cgroup", "/user.slice/app.slice/clpoc-" + "c" * 24 + ".service"),
    ("nonce", "changed-valid-nonce"),
    ("challenge_id", "c" * 32),
])
def test_validly_signed_different_execution_identity_cannot_consume(
    scratch, field, value,
):
    db, key = scratch
    challenge = _challenge(db)
    changed = synthetic_payload(challenge)
    changed[field] = value
    envelope = sign_test_only_stop_witness(
        changed, key, isolated_test_only=True,
    )
    with pytest.raises(central.RecoveryRejected, match="CHALLENGE"):
        _commit(db, key, envelope)
    assert _unchanged(db)


@pytest.mark.parametrize("field,value", [
    ("os_cgroup_empty", False),
    ("known_processes_stopped", "true"),
    ("stop_command_succeeded", 1),
    ("empty_observed_ns", 2),
    ("stop_requested_ns", 0),
    ("execution_generation", True),
    ("invocation_id", "0" * 32),
    ("unit", "ssh.service"),
    ("cgroup", "/system.slice/ssh.service"),
    ("purpose", "changlian-production-stop-v1"),
])
def test_invalid_stop_evidence_cannot_be_signed(scratch, field, value):
    db, key = scratch
    body = synthetic_payload(_challenge(db))
    body[field] = value
    with pytest.raises(IsolatedWitnessRejected):
        sign_test_only_stop_witness(body, key, isolated_test_only=True)
    assert _unchanged(db)


def test_signature_key_is_independent_and_pinned(scratch):
    db, key = scratch
    envelope = _sign(key, _challenge(db))
    forged_verifier = isolated_test_witness_verifier(
        Ed25519PrivateKey.generate().public_key(),
        isolated_test_only=True,
    )
    assert not forged_verifier(envelope)
    with pytest.raises(central.RecoveryRejected, match="INDEPENDENT"):
        central.commit_test_recovery(
            db, attestation=envelope, now=_NOW + timedelta(seconds=1),
            independent_witness_verifier=forged_verifier,
        )
    assert _unchanged(db)


def test_signed_payload_mutation_and_signature_malleation_rejected(scratch):
    db, key = scratch
    original = _sign(key, _challenge(db))
    verifier = isolated_test_witness_verifier(
        key.public_key(), isolated_test_only=True,
    )
    for modified in (
        {**original, "payload": {**original["payload"], "empty_observed_ns": 300}},
        {**original, "payload": {**original["payload"], "unexpected": 1}},
        {**original, "signature": "0" * 128},
        {**original, "signature": original["signature"].upper()},
        {**original, "other": "agent-supplied"},
    ):
        assert verifier(modified) is False
        with pytest.raises(central.RecoveryRejected, match="INDEPENDENT"):
            central.commit_test_recovery(
                db, attestation=modified, now=_NOW + timedelta(seconds=1),
                independent_witness_verifier=verifier,
            )
        assert _unchanged(db)


def test_disabled_production_signer_and_verifier(scratch):
    db, key = scratch
    body = synthetic_payload(_challenge(db))
    with pytest.raises(IsolatedWitnessRejected, match="TEST_ONLY"):
        sign_test_only_stop_witness(body, key)
    with pytest.raises(IsolatedWitnessRejected, match="PRODUCTION"):
        isolated_test_witness_verifier(key.public_key())
    assert _unchanged(db)


def test_central_rejects_lease_rotation_with_correct_cryptographic_signature(scratch):
    db, key = scratch
    receipt = _sign(key, _challenge(db))
    db.execute("UPDATE tasks SET lease_token=?", ("new-lease-token-" + "z" * 32,))
    with pytest.raises(central.RecoveryRejected, match="LEASE"):
        _commit(db, key, receipt)
    assert db.execute("SELECT status FROM tasks").fetchone()[0] == "RUNNING"
    assert db.execute("SELECT COUNT(*) FROM recovery_audit").fetchone()[0] == 0


def test_central_rejects_future_lease_with_correct_signature(scratch):
    db, key = scratch
    receipt = _sign(key, _challenge(db))
    db.execute("UPDATE tasks SET lease_expires_at=?",
               ((_NOW + timedelta(seconds=600)).isoformat(),))
    with pytest.raises(central.RecoveryRejected, match="LEASE"):
        _commit(db, key, receipt)
    assert db.execute("SELECT status FROM tasks").fetchone()[0] == "RUNNING"


def test_central_rejects_expired_challenge_with_correct_signature(scratch):
    db, key = scratch
    receipt = _sign(key, _challenge(db))
    with pytest.raises(central.RecoveryRejected, match="EXPIRED"):
        _commit(db, key, receipt, now=_NOW + timedelta(seconds=46))
    assert _unchanged(db)


def test_no_verifier_and_agent_claim_cannot_recover(scratch):
    db, key = scratch
    receipt = _sign(key, _challenge(db))
    with pytest.raises(central.RecoveryRejected, match="INDEPENDENT"):
        central.commit_test_recovery(
            db, attestation=receipt, now=_NOW + timedelta(seconds=1),
            independent_witness_verifier=None,
        )
    assert _unchanged(db)


def test_scratch_poc_cannot_open_production_database(tmp_path):
    db = sqlite3.connect(tmp_path / "real.sqlite3", isolation_level=None)
    try:
        with pytest.raises(central.RecoveryRejected, match="MEMORY"):
            central.init_scratch_schema(db)
    finally:
        db.close()
