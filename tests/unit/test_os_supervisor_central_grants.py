"""Phase 1B-2: real task repository lease -> signed CPU grant -> durable journal.

These are isolated contract tests, not production launch or central recovery.
"""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import sqlite3

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from platform_core.os_supervisor_authorization import (
    GrantRejected, verify_central_execution_grant,
)
from platform_core.os_supervisor_central_grants import CentralExecutionGrantIssuer
from platform_core.os_supervisor_journal import ExecutionJournal
from platform_core.service_nodes import ServiceNodeRepository
from platform_core.task_runtime.models import TaskKind, TaskRecord
from platform_core.task_runtime.repository import TaskRepository

BOOT = "65ad39e5-7bfa-4b46-9b1e-7f1f0d0d6c8a"
NODE = "node1"
TASK = "conv_test12345"
LEASE = "real-execution-lease-that-must-stay-private"
NOW = datetime.now(timezone.utc).replace(microsecond=0)


@pytest.fixture
def context(tmp_path):
    tasks = TaskRepository(tmp_path / "tasks.sqlite3")
    nodes = ServiceNodeRepository(tasks)
    _, node_token = nodes.create({
        "node_id": NODE, "display_name": "CPU trial",
        "connection_mode": "agent", "allowed_capabilities": ["conversion"],
    })
    nodes.heartbeat(NODE, node_token, {"reported_capabilities": ["conversion"]})
    record = TaskRecord.new(
        task_id=TASK, project_id="poc_project",
        kind=TaskKind.MODEL_CONVERSION, payload_ref="payload.json",
        resource_key="supervisor-cpu-v1",
        required_capabilities=("conversion",),
    )
    tasks.create(record)
    with closing(tasks._connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            """UPDATE tasks SET status='RUNNING',stage='running',
                    attempt=?,worker_id=?,lease_token=?,lease_expires_at=?
               WHERE task_id=?""",
            (3, "agent:" + NODE, LEASE,
             (datetime.now(timezone.utc) + timedelta(seconds=120)).isoformat(), TASK),
        )
        db.commit()
    key = Ed25519PrivateKey.generate()
    journal = ExecutionJournal(tmp_path / "os" / "journal.sqlite3",
                               test_only_unprivileged=True, boot_id_for_tests=BOOT)
    issuer = CentralExecutionGrantIssuer(tasks, key, cpu_trial_enabled=True)
    scope = {
        "task_id": TASK, "task_attempt": 3,
        "node_id": NODE, "worker_id": "agent:" + NODE,
        "execution_lease_sha256": hashlib.sha256(LEASE.encode()).hexdigest(),
        "gpu_uuid": "CPU_ONLY", "boot_id": BOOT,
        "runner_profile": "fixed-cpu-v1",
    }
    return tasks, node_token, key, journal, issuer, scope


def request(context, **changes):
    _, token, _, journal, issuer, scope = context
    nonce = journal.issue_challenge(scope)
    args = {
        "task_id": TASK, "task_attempt": 3, "node_id": NODE,
        "node_token": token, "execution_lease_token": LEASE,
        "boot_id": BOOT, "challenge": nonce,
    }
    args.update(changes)
    return issuer.issue(**args)


def test_authorized_real_task_lease_registers_only_one_durable_handle(context):
    tasks, token, key, journal, issuer, scope = context
    envelope = request(context)
    claims = envelope["claims"]
    assert claims["task_attempt"] == 3
    assert claims["execution_lease_sha256"] == scope["execution_lease_sha256"]
    assert claims["expires_at"] - claims["issued_at"] <= 15
    actual_scope = {**scope, "challenge": claims["challenge"]}
    assert verify_central_execution_grant(
        envelope, trusted_public_key=key.public_key(),
        expected_binding=actual_scope, now=claims["issued_at"]).task_attempt == 3
    first = journal.register_intent(envelope, trusted_public_key=key.public_key())
    again = ExecutionJournal(journal.path, test_only_unprivileged=True,
                             boot_id_for_tests=BOOT).register_intent(
                                 envelope, trusted_public_key=key.public_key())
    assert first["handle_id"] == again["handle_id"]
    assert first["state"] == again["state"] == "UNKNOWN"
    assert again["replayed"] is True
    with sqlite3.connect(journal.path) as db:
        assert db.execute("SELECT COUNT(*) FROM execution_intents").fetchone()[0] == 1


@pytest.mark.parametrize("change,code", [
    ({"task_attempt": 2}, "ATTEMPT_OR_WORKER"),
    ({"execution_lease_token": "assignment-lease-not-execution"}, "EXECUTION_LEASE"),
    ({"node_token": "forged-node-token"}, "AGENT_NOT_AUTHORIZED"),
    ({"node_id": "other-node"}, "OWNER_NOT_FOUND"),
])
def test_authority_rejects_wrong_task_generation_or_tokens(context, change, code):
    with pytest.raises(GrantRejected, match=code):
        request(context, **change)


@pytest.mark.parametrize("sql,values,code", [
    ("UPDATE tasks SET status='CANCEL_REQUESTED' WHERE task_id=?", (TASK,), "TASK_NOT_CPU_TRIAL"),
    ("UPDATE tasks SET attempt=4 WHERE task_id=?", (TASK,), "ATTEMPT_OR_WORKER"),
    ("UPDATE tasks SET lease_expires_at=? WHERE task_id=?", ("2000-01-01T00:00:00+00:00", TASK), "LEASE_TOO_CLOSE"),
    ("UPDATE tasks SET resource_key='gpu:0' WHERE task_id=?", (TASK,), "TASK_NOT_CPU_TRIAL"),
    ("UPDATE service_nodes SET enabled=0 WHERE node_id=?", (NODE,), "AGENT_NOT_AUTHORIZED"),
])
def test_central_db_current_state_fences_grants(context, sql, values, code):
    tasks, *_ = context
    with closing(tasks._connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute(sql, values)
        db.commit()
    with pytest.raises(GrantRejected, match=code):
        request(context)


def test_issuer_is_disabled_and_ordinary_resource_is_not_eligible(context):
    tasks, _, key, _, _, _ = context
    disabled = CentralExecutionGrantIssuer(tasks, key)
    assert disabled.enabled is False
    with pytest.raises(GrantRejected, match="ISSUER_DISABLED"):
        disabled.issue(task_id=TASK, task_attempt=3, node_id=NODE,
                       node_token="x", execution_lease_token=LEASE,
                       boot_id=BOOT, challenge="a" * 32)


def test_central_lease_is_not_modified_by_grant_issuance(context):
    tasks, token, key, journal, issuer, scope = context
    with closing(tasks._connect()) as db:
        prior = db.execute(
            "SELECT attempt,status,lease_token,worker_id FROM tasks WHERE task_id=?",
            (TASK,),
        ).fetchone()
    request(context)
    with closing(tasks._connect()) as db:
        after = db.execute(
            "SELECT attempt,status,lease_token,worker_id FROM tasks WHERE task_id=?",
            (TASK,),
        ).fetchone()
    assert tuple(after) == tuple(prior)


def _registered_launch_intent(context):
    _, _, key, journal, _, _ = context
    first = request(context)
    intent = journal.register_intent(first, trusted_public_key=key.public_key())
    return intent, first


def _fresh_launch_grant(context, intent):
    _, token, _, journal, issuer, _ = context
    nonce = journal.issue_cpu_launch_challenge(
        intent["handle_id"], intent["task_attempt"])
    return issuer.issue(
        task_id=TASK, task_attempt=3, node_id=NODE,
        node_token=token, execution_lease_token=LEASE,
        boot_id=BOOT, challenge=nonce)


def test_launch_recheck_new_signed_nonce_and_one_journal_cas(context):
    tasks, _, key, journal, _, _ = context
    intent, first = _registered_launch_intent(context)
    fresh = _fresh_launch_grant(context, intent)
    handle = intent["handle_id"]
    assert fresh["claims"]["challenge"] != first["claims"]["challenge"]
    assert journal.issue_cpu_launch_challenge(handle, 3) == fresh["claims"]["challenge"]
    claimed = journal.claim_cpu_launch_rechecked(
        handle, 3, fresh, trusted_public_key=key.public_key())
    assert claimed == {"handle_id": handle, "task_attempt": 3,
                       "unit_name": "changlian-os-" + handle + ".service"}
    restarted = ExecutionJournal(
        journal.path, test_only_unprivileged=True, boot_id_for_tests=BOOT)
    with pytest.raises(GrantRejected, match="NOT_PREPARED"):
        restarted.claim_cpu_launch_rechecked(
            handle, 3, fresh, trusted_public_key=key.public_key())
    with sqlite3.connect(journal.path) as db:
        assert db.execute(
            "SELECT task_id,task_attempt,state,event_seq FROM execution_intents"
        ).fetchall() == [(TASK, 3, "STARTING", 2)]
        assert db.execute(
            "SELECT COUNT(*) FROM cpu_launch_challenges").fetchone()[0] == 1
    with closing(tasks._connect()) as db:
        record = db.execute(
            "SELECT attempt,status,worker_id,lease_token FROM tasks WHERE task_id=?",
            (TASK,)).fetchone()
    assert tuple(record) == (3, "RUNNING", "agent:" + NODE, LEASE)


@pytest.mark.parametrize("sql,values,code", [
    ("UPDATE tasks SET status='CANCEL_REQUESTED' WHERE task_id=?",
     (TASK,), "TASK_NOT_CPU_TRIAL"),
    ("UPDATE tasks SET attempt=4 WHERE task_id=?",
     (TASK,), "ATTEMPT_OR_WORKER"),
    ("UPDATE tasks SET lease_token='rotated' WHERE task_id=?",
     (TASK,), "EXECUTION_LEASE"),
    ("UPDATE tasks SET lease_expires_at=? WHERE task_id=?",
     ("2000-01-01T00:00:00+00:00", TASK), "LEASE_TOO_CLOSE"),
    ("UPDATE service_nodes SET enabled=0 WHERE node_id=?",
     (NODE,), "AGENT_NOT_AUTHORIZED"),
])
def test_recheck_fences_central_revocation_after_initial_intent(
        context, sql, values, code):
    tasks, _, key, journal, _, _ = context
    intent, first = _registered_launch_intent(context)
    journal.issue_cpu_launch_challenge(intent["handle_id"], 3)
    with closing(tasks._connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute(sql, values)
        db.commit()
    with pytest.raises(GrantRejected, match=code):
        _fresh_launch_grant(context, intent)
    with sqlite3.connect(journal.path) as db:
        assert db.execute(
            "SELECT state FROM execution_intents").fetchone() == ("PREPARED",)


def test_recheck_wrong_old_forged_scope_cannot_claim(context):
    _, _, key, journal, _, _ = context
    intent, first = _registered_launch_intent(context)
    handle = intent["handle_id"]
    fresh = _fresh_launch_grant(context, intent)
    for args in (
        (handle, 3, first),
        ("f" * 32, 3, fresh),
        (handle, 4, fresh),
    ):
        with pytest.raises(GrantRejected):
            journal.claim_cpu_launch_rechecked(
                *args, trusted_public_key=key.public_key())
    forged = {"claims": fresh["claims"], "signature": "f" * 128}
    with pytest.raises(GrantRejected, match="SIGNATURE"):
        journal.claim_cpu_launch_rechecked(
            handle, 3, forged, trusted_public_key=key.public_key())
    with sqlite3.connect(journal.path) as db:
        assert db.execute("SELECT state FROM execution_intents").fetchone() == (
            "PREPARED",)


def test_recheck_expired_grant_and_nonce_stay_prepared(context):
    _, _, key, journal, _, _ = context
    intent, first = _registered_launch_intent(context)
    handle = intent["handle_id"]
    fresh = _fresh_launch_grant(context, intent)
    issued = fresh["claims"]["issued_at"]
    with pytest.raises(GrantRejected, match="FRESHNESS"):
        journal.claim_cpu_launch_rechecked(
            handle, 3, fresh, trusted_public_key=key.public_key(),
            now=issued + 4)
    with pytest.raises(GrantRejected, match="NOT_PREPARED"):
        journal.claim_cpu_launch_rechecked(
            handle, 3, fresh, trusted_public_key=key.public_key(),
            now=issued + 16)
    with pytest.raises(GrantRejected, match="CHALLENGE_EXPIRED"):
        journal.issue_cpu_launch_challenge(handle, 3, now=issued + 16)
    with sqlite3.connect(journal.path) as db:
        assert db.execute("SELECT state FROM execution_intents").fetchone() == (
            "PREPARED",)
