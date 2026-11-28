"""2D-2D2B2B-2A: root journal PT reservation + central recheck + one CAS.

All tests are CPU-only; no unpickling, systemd service, result publication
or production Node Agent router is imported or enabled.
"""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import json
import sqlite3
import time

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from platform_core.os_supervisor_authorization import (
    PURPOSE, GrantRejected, _claims_payload,
)
from platform_core.os_supervisor_cpu_pt_export_admission import (
    FrozenPtExportAdmission, VerifiedPtBytes,
)
from platform_core.os_supervisor_journal import ExecutionJournal
from platform_core.os_supervisor_pt_export_grant import (
    CentralPtExportAdmissionIssuer, PT_PROFILE, PT_TEST_RESOURCE,
)
from platform_core.os_supervisor_pt_export_launch import (
    PtExportJournal, issue_pt_export_launch_grant,
    verify_pt_export_launch_grant,
)
from platform_core.service_nodes import ServiceNodeRepository
from platform_core.task_runtime import (
    ArtifactStore, TaskKind, TaskRecord, TaskRepository,
)

TASK = "conv_pt_launch_987"
NODE = "pt-launch-node"
BOOT = "65ad39e5-7bfa-4b46-9b1e-7f1f0d0d6c8a"
LEASE = "original-pt-conversion-execution-lease-not-a-node-assignment"
BYTES = b"never-unpickle-this-pt-data"
SHA = hashlib.sha256(BYTES).hexdigest()
OPTIONS = {
    "input_size": 640, "batch": 1, "opset": 12,
    "dynamic": False, "simplify": False,
}


def central_payload(**changes):
    conversion = {
        "schema_version": 1, "target": "onnx",
        "source": {
            "type": "object", "storage_source_id": "test-models",
            "object_key": "algo/ver/source.pt", "file_name": "source.pt",
            "sha256": SHA, "size_bytes": len(BYTES),
        },
        "source_trace": {
            "algorithm_id": "algo1", "version_id": "ver1", "sha256": SHA,
        },
        "params": dict(OPTIONS),
        "output": {"file_name": "model.onnx"},
    }
    conversion.update(changes)
    return {"remote_execution": {
        "version": 1, "task_kind": "MODEL_CONVERSION",
        "transport": "object-storage-v1", "conversion": conversion,
    }}


@pytest.fixture
def stage(tmp_path):
    task_repo = TaskRepository(tmp_path / "db" / "tasks.sqlite3")
    artifacts = ArtifactStore(tmp_path / "db" / "artifacts")
    artifacts.atomic_write_json(TASK, "request.json", central_payload())
    task_repo.create(TaskRecord.new(
        task_id=TASK, project_id="demo",
        kind=TaskKind.MODEL_CONVERSION, payload_ref="request.json",
        resource_key=PT_TEST_RESOURCE, required_capabilities=("conversion",),
    ), artifacts=artifacts)
    nodes = ServiceNodeRepository(task_repo)
    _, token = nodes.create({
        "node_id": NODE, "display_name": "PT CPU offline",
        "connection_mode": "agent", "allowed_capabilities": ["conversion"],
    })
    nodes.heartbeat(NODE, token, {"reported_capabilities": ["conversion"]})
    with closing(task_repo._connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            """UPDATE tasks SET status='RUNNING',stage='running',
                     attempt=3,worker_id=?,lease_token=?,lease_expires_at=?
               WHERE task_id=?""",
            ("agent:" + NODE, LEASE,
             (datetime.now(timezone.utc) + timedelta(seconds=120)).isoformat(),
             TASK),
        )
        db.commit()
    key = Ed25519PrivateKey.generate()
    issuer = CentralPtExportAdmissionIssuer(
        task_repo, artifacts, key, pt_trial_enabled=True)
    root = ExecutionJournal(
        tmp_path / "os" / "executions.sqlite3",
        test_only_unprivileged=True, boot_id_for_tests=BOOT,
    )
    pt = PtExportJournal(root)
    frozen = FrozenPtExportAdmission(
        task_id=TASK, task_attempt=3, node_id=NODE,
        worker_id="agent:" + NODE,
        execution_lease_sha256=hashlib.sha256(LEASE.encode()).hexdigest(),
        source_sha256=SHA, source_size_bytes=len(BYTES),
        source_name="source.pt", output_name="model.onnx", **OPTIONS,
    )
    manifest_sha = hashlib.sha256(frozen.freeze_nonexecutable_manifest(
        VerifiedPtBytes(SHA, len(BYTES)))).hexdigest()
    scope = {
        "task_id": TASK, "task_attempt": 3,
        "worker_id": "agent:" + NODE, "node_id": NODE,
        "execution_lease_sha256": hashlib.sha256(LEASE.encode()).hexdigest(),
        "boot_id": BOOT, "runner_profile": PT_PROFILE, "gpu_uuid": "CPU_ONLY",
        "source_sha256": SHA, "source_size_bytes": len(BYTES),
        "source_name": "source.pt", "output_name": "model.onnx",
        "params": dict(OPTIONS), "manifest_sha256": manifest_sha,
    }
    return task_repo, artifacts, key, token, issuer, root, pt, scope


def registered(stage):
    repo, artifacts, key, token, issuer, root, pt, scope = stage
    nonce = pt.issue_admission_challenge(scope)
    first_grant = issuer.issue(
        task_id=TASK, task_attempt=3, node_id=NODE, node_token=token,
        execution_lease_token=LEASE, boot_id=BOOT, challenge=nonce,
    )
    first = pt.register_admission(
        first_grant, trusted_public_key=key.public_key())
    return first, first_grant


def launch_grant(stage, handle_id, first_grant, **changes):
    _repo, _artifacts, _key, token, issuer, _root, pt, _scope = stage
    nonce = pt.issue_launch_challenge(handle_id, 3)
    request = {
        "task_id": TASK, "task_attempt": 3, "node_id": NODE,
        "node_token": token, "execution_lease_token": LEASE,
        "boot_id": BOOT, "challenge": nonce,
        "handle_id": handle_id, "registered_grant_digest":
            hashlib.sha256(
                b"changlian-pt-export-cpu-admission-v1\x00" +
                json.dumps(first_grant["claims"], sort_keys=True,
                           separators=(",", ":"), allow_nan=False).encode("utf-8")
            ).hexdigest(),
    }
    request.update(changes)
    return issue_pt_export_launch_grant(issuer, **request)


def test_one_registered_original_attempt_one_claim_even_after_restart(stage):
    repo, artifacts, key, token, issuer, root, pt, scope = stage
    first, signed = registered(stage)
    assert first["state"] == "UNKNOWN" and not first["launch_authorized"]
    assert pt.register_admission(
        signed, trusted_public_key=key.public_key())["replayed"] is True
    receipt = launch_grant(stage, first["handle_id"], signed)
    claimed = pt.claim_rechecked_launch(
        first["handle_id"], 3, receipt, trusted_public_key=key.public_key())
    assert claimed["state"] == "UNKNOWN"
    assert claimed["os_executor_connected"] is False
    assert claimed["launch_authorized"] is False
    assert not hasattr(pt, "launch")
    with pytest.raises(GrantRejected, match="CPU_PT_HANDLE_PROFILE_MISMATCH_HOLD"):
        root.starting_cpu_unit(first["handle_id"], 3)
    with closing(root._connect()) as db:
        assert tuple(db.execute(
            "SELECT state,event_seq FROM execution_intents WHERE task_id=?",
            (TASK,)).fetchone()) == ("STARTING", 2)
        assert db.execute(
            "SELECT count(*) FROM execution_intents WHERE task_id=?",
            (TASK,)).fetchone()[0] == 1
        audit = db.execute(
            "SELECT launch_grant_digest,claimed_at FROM pt_export_claims"
        ).fetchone()
        assert audit["launch_grant_digest"] == claimed["launch_grant_digest"]
        assert type(audit["claimed_at"]) is int
    reopened = PtExportJournal(ExecutionJournal(
        root.path, test_only_unprivileged=True, boot_id_for_tests=BOOT))
    with pytest.raises(GrantRejected, match="HOLD"):
        reopened.claim_rechecked_launch(
            first["handle_id"], 3, receipt,
            trusted_public_key=key.public_key())
    with pytest.raises(GrantRejected, match="HOLD"):
        reopened.issue_launch_challenge(first["handle_id"], 3)


def test_original_fixed_cpu_and_pt_intents_share_attempt_uniqueness(stage):
    repo, artifacts, key, token, issuer, root, pt, scope = stage
    first, signed = registered(stage)
    with pytest.raises(GrantRejected, match="CPU_PT_HANDLE_PROFILE_MISMATCH_HOLD"):
        root.issue_cpu_launch_challenge(first["handle_id"], 3)
    old_scope = {
        "task_id": TASK, "task_attempt": 3,
        "node_id": NODE, "worker_id": "agent:" + NODE,
        "execution_lease_sha256": scope["execution_lease_sha256"],
        "gpu_uuid": "CPU_ONLY", "boot_id": BOOT,
        "runner_profile": "fixed-cpu-v1",
    }
    nonce = root.issue_challenge(old_scope)
    now = int(time.time())
    old_claims = {
        **old_scope, "challenge": nonce, "purpose": PURPOSE,
        "issued_at": now, "expires_at": now + 12,
    }
    old_grant = {"claims": old_claims,
                 "signature": key.sign(_claims_payload(old_claims)).hex()}
    with pytest.raises(GrantRejected, match="HOLD"):
        root.register_intent(old_grant, trusted_public_key=key.public_key())
    with closing(root._connect()) as db:
        assert db.execute(
            "SELECT count(*) FROM execution_intents WHERE task_id=?",
            (TASK,)).fetchone()[0] == 1


def test_pt_intent_rejects_original_fixed_cpu_even_if_signed(stage):
    repo, artifacts, key, token, issuer, root, pt, scope = stage
    old_scope = {
        "task_id": TASK, "task_attempt": 3,
        "node_id": NODE, "worker_id": "agent:" + NODE,
        "execution_lease_sha256": scope["execution_lease_sha256"],
        "gpu_uuid": "CPU_ONLY", "boot_id": BOOT,
        "runner_profile": "fixed-cpu-v1",
    }
    nonce = root.issue_challenge(old_scope)
    now = int(time.time())
    old_claims = {
        **old_scope, "challenge": nonce, "purpose": PURPOSE,
        "issued_at": now, "expires_at": now + 12,
    }
    old_grant = {"claims": old_claims,
                 "signature": key.sign(_claims_payload(old_claims)).hex()}
    old = root.register_intent(old_grant, trusted_public_key=key.public_key())
    assert old["handle_id"]
    pt_nonce = pt.issue_admission_challenge(scope)
    admission = issuer.issue(
        task_id=TASK, task_attempt=3, node_id=NODE, node_token=token,
        execution_lease_token=LEASE, boot_id=BOOT, challenge=pt_nonce)
    with pytest.raises(GrantRejected, match="HOLD"):
        pt.register_admission(admission, trusted_public_key=key.public_key())


@pytest.mark.parametrize("change", [
    "source_sha256", "manifest_sha256", "params",
    "task_attempt", "boot_id", "worker_id", "challenge",
])
def test_forged_launch_scope_never_claims(stage, change):
    repo, artifacts, key, token, issuer, root, pt, scope = stage
    first, signed = registered(stage)
    grant = launch_grant(stage, first["handle_id"], signed)
    claims = dict(grant["claims"])
    if change == "params":
        claims["params"] = {**claims["params"], "input_size": 320}
    elif change == "task_attempt":
        claims[change] = 4
    elif change == "boot_id":
        claims[change] = "0" * 8 + "-0000-0000-0000-000000000000"
    elif change == "worker_id":
        claims[change] = "agent:bad-node"
    elif change == "challenge":
        claims[change] = "b" * 32
    else:
        claims[change] = "0" * 64
    forged = {"claims": claims, "signature": grant["signature"]}
    with pytest.raises(GrantRejected, match="HOLD"):
        pt.claim_rechecked_launch(
            first["handle_id"], 3, forged,
            trusted_public_key=key.public_key())
    with closing(root._connect()) as db:
        assert db.execute(
            "SELECT state FROM execution_intents WHERE task_id=?",
            (TASK,)).fetchone()[0] == "PREPARED"


@pytest.mark.parametrize("sql,values", [
    ("UPDATE tasks SET status='CANCEL_REQUESTED' WHERE task_id=?", (TASK,)),
    ("UPDATE tasks SET attempt=4 WHERE task_id=?", (TASK,)),
    ("UPDATE tasks SET lease_token='rotated' WHERE task_id=?", (TASK,)),
    ("UPDATE tasks SET stage='stopping' WHERE task_id=?", (TASK,)),
    ("UPDATE service_nodes SET enabled=0 WHERE node_id=?", (NODE,)),
])
def test_recheck_after_central_revocation_prevents_claim(stage, sql, values):
    repo, artifacts, key, token, issuer, root, pt, scope = stage
    first, admission = registered(stage)
    with closing(repo._connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute(sql, values)
        db.commit()
    with pytest.raises(GrantRejected, match="HOLD"):
        launch_grant(stage, first["handle_id"], admission)
    with closing(root._connect()) as db:
        assert db.execute("SELECT state FROM execution_intents").fetchone()[0] == "PREPARED"


def test_central_source_changes_between_register_and_start_stays_prepared(stage):
    repo, artifacts, key, token, issuer, root, pt, scope = stage
    first, admission = registered(stage)
    altered = central_payload()
    altered["remote_execution"]["conversion"]["source"]["sha256"] = "0" * 64
    altered["remote_execution"]["conversion"]["source_trace"]["sha256"] = "0" * 64
    artifacts.atomic_write_json(TASK, "request.json", altered)
    grant = launch_grant(stage, first["handle_id"], admission)
    with pytest.raises(GrantRejected, match="HOLD"):
        pt.claim_rechecked_launch(
            first["handle_id"], 3, grant,
            trusted_public_key=key.public_key())
    with closing(root._connect()) as db:
        assert db.execute("SELECT state FROM execution_intents").fetchone()[0] == "PREPARED"


def test_expired_nonce_no_renewal_and_replay_after_crash_holds(stage):
    repo, artifacts, key, token, issuer, root, pt, scope = stage
    first, admission = registered(stage)
    nonce = pt.issue_launch_challenge(first["handle_id"], 3, now=100)
    assert nonce
    with pytest.raises(GrantRejected, match="HOLD"):
        pt.issue_launch_challenge(first["handle_id"], 3, now=116)
    with pytest.raises(GrantRejected, match="HOLD"):
        pt.claim_rechecked_launch(
            first["handle_id"], 3, admission,
            trusted_public_key=key.public_key(), now=116)
    with closing(root._connect()) as db:
        assert db.execute("SELECT state FROM execution_intents").fetchone()[0] == "PREPARED"


def test_wrong_pubkey_and_original_admission_are_not_launch_authorization(stage):
    repo, artifacts, key, token, issuer, root, pt, scope = stage
    first, admission = registered(stage)
    grant = launch_grant(stage, first["handle_id"], admission)
    with pytest.raises(GrantRejected, match="HOLD"):
        pt.claim_rechecked_launch(
            first["handle_id"], 3, admission,
            trusted_public_key=key.public_key())
    with pytest.raises(GrantRejected, match="HOLD"):
        pt.claim_rechecked_launch(
            first["handle_id"], 3, grant,
            trusted_public_key=Ed25519PrivateKey.generate().public_key())
    with closing(root._connect()) as db:
        assert db.execute("SELECT state FROM execution_intents").fetchone()[0] == "PREPARED"


def test_same_challenge_only_one_registration_and_binding_quota(stage):
    repo, artifacts, key, token, issuer, root, pt, scope = stage
    a=pt.issue_admission_challenge(scope)
    b=pt.issue_admission_challenge(scope)
    c=pt.issue_admission_challenge(scope)
    d=pt.issue_admission_challenge(scope)
    assert len({a,b,c,d}) == 4
    with pytest.raises(GrantRejected, match="HOLD"):
        pt.issue_admission_challenge(scope)
