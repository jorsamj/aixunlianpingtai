"""P0-01C-3A contracts: isolated in-memory SQLite, no Node/GPU/service access."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "poc"))
import central_stop_recovery_contract as poc


NOW = datetime(2026, 11, 15, 3, 0, tzinfo=timezone.utc)
SIGNER = b"test-only-independent-os-witness-key-32bytes"
BOUNDARY = {
    "boot_id": "01234567-89ab-cdef-0123-456789abcdef",
    "invocation_id": "c" * 32,
    "unit": "clpoc-" + "a" * 24 + ".service",
    "cgroup": "/user.slice/app.slice/clpoc-" + "a" * 24 + ".service",
}


@pytest.fixture
def db():
    connection = sqlite3.connect(":memory:", isolation_level=None)
    poc.init_scratch_schema(connection)
    yield connection
    connection.close()


def add_held(db, *, task_id="train_001", node_id="gpu-node", generation=3,
             status="RUNNING", stage=poc.HOLD, expired=True,
             reservation=True, token="old-remote-lease-token-" + "x" * 24):
    lease_expiry = NOW + timedelta(seconds=-5 if expired else 600)
    db.execute("""INSERT INTO tasks
        (task_id,attempt,status,stage,worker_id,lease_token,lease_expires_at,
         resource_wait_reason,updated_at,process_pid)
        VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (task_id, generation, status, stage, "agent:" + node_id,
         token, lease_expiry.isoformat(), "REMOTE_AGENT_STOP_UNVERIFIED",
         NOW.isoformat(), 123456))
    if reservation:
        db.execute("""INSERT INTO gpu_reservations(task_id,worker_id,lease_token,policy)
                    VALUES (?,?,?,?)""",
                   (task_id, "agent:" + node_id, token, "exclusive"))
    return token


def issue(db, *, task_id="train_001", node_id="gpu-node", now=NOW, **kwargs):
    return poc.issue_challenge(db, task_id=task_id, node_id=node_id,
                               now=now, **{**BOUNDARY, **kwargs})


def attestation(challenge, **changes):
    body = {**challenge, "os_cgroup_empty": True,
            "known_processes_stopped": True,
            "stop_command_succeeded": True,
            "stop_requested_ns": 100, "empty_observed_ns": 120}
    body.update(changes)
    return poc.test_only_sign_witness(body, SIGNER)


def submit(db, proof, *, now=NOW + timedelta(seconds=1), verifier=None):
    return poc.commit_test_recovery(
        db, attestation=proof, now=now,
        independent_witness_verifier=(
            poc.test_only_witness_verifier(SIGNER) if verifier is None else verifier))


def row(db, table, where="task_id='train_001'"):
    db.row_factory = sqlite3.Row
    result = db.execute(f"SELECT * FROM {table} WHERE {where}").fetchone()
    return dict(result) if result is not None else None


def assert_still_held(db, *, task_id="train_001"):
    held = row(db, "tasks", f"task_id='{task_id}'")
    assert held["status"] in ("RUNNING", "CANCEL_REQUESTED")
    assert held["stage"] == poc.HOLD
    assert held["worker_id"] == "agent:gpu-node"
    assert held["lease_token"] is not None


def test_held_running_can_resume_once_without_incrementing_attempt(db):
    token = add_held(db)
    challenge = issue(db)
    evidence = attestation(challenge)
    result = submit(db, evidence)
    assert result == {"task_id": "train_001", "status": "QUEUED",
                      "previous_execution_generation": 3,
                      "challenge_consumed": True, "scratch_only": True}
    task = row(db, "tasks")
    assert task["attempt"] == 3
    assert task["status"] == "QUEUED"
    assert task["stage"] == "recovered"
    assert task["worker_id"] is None and task["lease_token"] is None
    assert task["process_pid"] is None
    assert row(db, "gpu_reservations") is None
    challenge_row = row(db, "recovery_challenges",
                        f"challenge_id='{challenge['challenge_id']}'")
    assert challenge_row["consumed_at"] and challenge_row["decision"] == "QUEUED"
    assert challenge_row["lease_hash"] == poc._digest(token)
    assert challenge_row["nonce_hash"] == poc._digest(challenge["nonce"])
    assert row(db, "recovery_audit", f"challenge_id='{challenge['challenge_id']}'")
    with pytest.raises(poc.RecoveryRejected):
        submit(db, evidence)
    assert row(db, "tasks")["status"] == "QUEUED"
    assert db.execute("SELECT COUNT(*) FROM recovery_audit").fetchone()[0] == 1


def test_held_cancel_requested_recovers_to_cancelled_not_queue(db):
    add_held(db, status="CANCEL_REQUESTED")
    challenge = issue(db)
    outcome = submit(db, attestation(challenge))
    assert outcome["status"] == "CANCELLED"
    task = row(db, "tasks")
    assert task["status"] == "CANCELLED" and task["stage"] == "cancelled"
    assert task["finished_at"] is not None
    assert row(db, "gpu_reservations") is None


def test_no_independent_witness_is_never_a_stop_proof(db):
    add_held(db)
    challenge = issue(db)
    proof = attestation(challenge)
    with pytest.raises(poc.RecoveryRejected, match="INDEPENDENT"):
        poc.commit_test_recovery(
            db, attestation=proof, now=NOW+timedelta(seconds=1),
            independent_witness_verifier=None)
    assert_still_held(db)
    assert row(db, "gpu_reservations") is not None


def test_agent_claim_without_test_witness_signature_fails_closed(db):
    add_held(db)
    challenge = issue(db)
    proof = attestation(challenge)
    proof["signature"] = "0" * 64
    with pytest.raises(poc.RecoveryRejected, match="INDEPENDENT"):
        submit(db, proof)
    assert_still_held(db)


@pytest.mark.parametrize("field,value", [
    ("execution_generation", 4),
    ("execution_generation", True),
    ("worker_id", "agent:other-node"),
    ("task_id", "train_somebody_else"),
    ("boot_id", "ffffffff-ffff-ffff-ffff-ffffffffffff"),
    ("invocation_id", "e" * 32),
    ("unit", "clpoc-" + "b" * 24 + ".service"),
    ("cgroup", "/user.slice/app.slice/other.service"),
    ("nonce", "replayed-token"),
])
def test_signed_witness_cannot_change_challenge_scope(db, field, value):
    add_held(db)
    challenge = issue(db)
    with pytest.raises(poc.RecoveryRejected, match="CHALLENGE"):
        submit(db, attestation(challenge, **{field: value}))
    assert_still_held(db)


@pytest.mark.parametrize("field,value", [
    ("os_cgroup_empty", False),
    ("os_cgroup_empty", "true"),
    ("known_processes_stopped", None),
    ("stop_command_succeeded", 1),
    ("stop_requested_ns", 0),
    ("empty_observed_ns", 90),
    ("empty_observed_ns", True),
])
def test_attestation_must_have_strict_os_stop_evidence(db, field, value):
    add_held(db)
    challenge = issue(db)
    with pytest.raises(poc.RecoveryRejected, match="INDEPENDENT"):
        submit(db, attestation(challenge, **{field: value}))
    assert_still_held(db)


def test_challenge_expiry_always_holds_and_does_not_consume(db):
    add_held(db)
    challenge = issue(db, ttl_seconds=5)
    with pytest.raises(poc.RecoveryRejected, match="EXPIRED"):
        submit(db, attestation(challenge), now=NOW+timedelta(seconds=5))
    assert_still_held(db)
    assert row(db, "recovery_challenges",
               f"challenge_id='{challenge['challenge_id']}'")["consumed_at"] is None


@pytest.mark.parametrize("change", [
    {"attempt": 4}, {"worker_id": "agent:new-node"},
    {"lease_token": "new-lease-token-" + "z" * 32},
    {"stage": "running"}, {"status": "SUCCEEDED"},
    {"lease_expires_at": (NOW+timedelta(seconds=60)).isoformat()},
])
def test_transaction_rechecks_current_task_and_rejects_races(db, change):
    add_held(db)
    challenge = issue(db)
    sql = "UPDATE tasks SET " + ", ".join(f"{key}=?" for key in change) + " WHERE task_id=?"
    db.execute(sql, (*change.values(), "train_001"))
    with pytest.raises(poc.RecoveryRejected):
        submit(db, attestation(challenge))
    current = row(db, "tasks")
    for key, value in change.items():
        assert current[key] == value
    assert row(db, "gpu_reservations") is not None


def test_gpu_reservation_does_not_clear_if_owner_changed(db):
    add_held(db)
    challenge = issue(db)
    db.execute("UPDATE gpu_reservations SET worker_id='agent:foreign' WHERE task_id='train_001'")
    with pytest.raises(poc.RecoveryRejected, match="GPU_RESERVATION_OWNER"):
        submit(db, attestation(challenge))
    assert_still_held(db)
    assert row(db, "gpu_reservations")["worker_id"] == "agent:foreign"


@pytest.mark.parametrize("kwargs", [
    {"node_id": "other-node"}, {"boot_id": "bad"},
    {"invocation_id": "0"*32}, {"cgroup": "/../../bad"},
    {"ttl_seconds": True}, {"ttl_seconds": 2},
])
def test_challenge_issue_denies_wrong_node_or_invalid_boundary(db, kwargs):
    add_held(db)
    with pytest.raises(poc.RecoveryRejected):
        issue(db, **kwargs)
    assert_still_held(db)
    assert db.execute("SELECT COUNT(*) FROM recovery_challenges").fetchone()[0] == 0


@pytest.mark.parametrize("status,stage,expired", [
    ("QUEUED", poc.HOLD, True),
    ("RUNNING", "running", True),
    ("RUNNING", poc.HOLD, False),
])
def test_challenge_issue_requires_existing_remote_hold(db, status, stage, expired):
    add_held(db, status=status, stage=stage, expired=expired)
    with pytest.raises(poc.RecoveryRejected):
        issue(db)
    assert db.execute("SELECT COUNT(*) FROM recovery_challenges").fetchone()[0] == 0


def test_duplicate_challenge_same_generation_cannot_be_overwritten(db):
    add_held(db)
    challenge = issue(db)
    with pytest.raises(sqlite3.IntegrityError):
        issue(db)
    stored = row(db, "recovery_challenges")
    assert stored["challenge_id"] == challenge["challenge_id"]
    assert_still_held(db)


def test_commit_rollback_is_all_or_nothing_if_audit_insert_fails(db):
    add_held(db)
    challenge = issue(db)
    # Force an audit collision *after* UPDATE tasks and GPU DELETE.
    db.execute("""INSERT INTO recovery_audit
        (challenge_id, task_id, execution_generation, old_worker, next_status, decided_at)
        VALUES (?,?,?,?,?,?)""",
        (challenge["challenge_id"], "train_001", 3, "agent:gpu-node", "OLD", NOW.isoformat()))
    with pytest.raises(sqlite3.IntegrityError):
        submit(db, attestation(challenge))
    assert_still_held(db)
    assert row(db, "gpu_reservations") is not None
    assert row(db, "recovery_challenges")["consumed_at"] is None
    assert row(db, "recovery_audit")["next_status"] == "OLD"


def test_file_backed_database_cannot_use_this_poc_at_all(tmp_path):
    physical_db = sqlite3.connect(tmp_path / "production-lookalike.sqlite3",
                                  isolation_level=None)
    try:
        with pytest.raises(poc.RecoveryRejected, match="ISOLATED_MEMORY"):
            poc.init_scratch_schema(physical_db)
        with pytest.raises(poc.RecoveryRejected, match="ISOLATED_MEMORY"):
            issue(physical_db)
        with pytest.raises(poc.RecoveryRejected, match="ISOLATED_MEMORY"):
            submit(physical_db, {})
    finally:
        physical_db.close()


def test_new_lease_generation_is_only_issued_by_separate_real_start(db):
    add_held(db, generation=7)
    challenge = issue(db)
    submit(db, attestation(challenge))
    current = row(db, "tasks")
    assert current["status"] == "QUEUED"
    assert current["attempt"] == 7  # no artificial increment at recovery
    assert current["lease_token"] is None
    assert row(db, "gpu_reservations") is None
