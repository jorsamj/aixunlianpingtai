"""2D-2D2B2B-1: central stored PT evidence -> dedicated signed admission.

No trusted pickle loading, OS launch, result upload, or production flag.
"""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import json
import sqlite3

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from platform_core.os_supervisor_authorization import (
    GrantRejected, verify_central_execution_grant,
)
from platform_core.os_supervisor_cpu_pt_export_admission import (
    FrozenPtExportAdmission, VerifiedPtBytes,
)
from platform_core.os_supervisor_pt_export_grant import (
    CentralPtExportAdmissionIssuer, PT_TEST_RESOURCE,
    verify_pt_export_admission_grant,
)
from platform_core.service_nodes import ServiceNodeRepository
from platform_core.task_runtime import (
    ArtifactStore, TaskKind, TaskRecord, TaskRepository,
)

TASK = "conv_pt_admission_123"
NODE = "pt-node-1"
LEASE = "central-real-execution-lease-secret"
BOOT = "65ad39e5-7bfa-4b46-9b1e-7f1f0d0d6c8a"
SOURCE = b"trusted-evidence-only-not-a-real-pickle"
SHA = hashlib.sha256(SOURCE).hexdigest()


def payload(source_sha=SHA, *, params=None, source_name="source.pt"):
    return {
        "remote_execution": {
            "version": 1,
            "task_kind": "MODEL_CONVERSION",
            "transport": "object-storage-v1",
            "conversion": {
                "schema_version": 1, "target": "onnx",
                "source": {
                    "type": "object", "file_name": source_name,
                    "sha256": source_sha, "size_bytes": len(SOURCE),
                    "storage_source_id": "central-source", "object_key": "models/v1/source.pt",
                },
                "source_trace": {
                    "algorithm_id": "algo-1", "version_id": "ver-1",
                    "sha256": source_sha,
                },
                "params": params or {
                    "input_size": 640, "batch": 1, "opset": 12,
                    "dynamic": False, "simplify": False,
                },
                "output": {"file_name": "model.onnx", "object_key": "out/model.onnx"},
            },
        },
    }


@pytest.fixture
def context(tmp_path):
    repo = TaskRepository(tmp_path / "db" / "tasks.sqlite3")
    artifacts = ArtifactStore(tmp_path / "db" / "artifacts")
    artifacts.atomic_write_json(TASK, "request.json", payload())
    repo.create(TaskRecord.new(
        task_id=TASK, project_id="pt-project",
        kind=TaskKind.MODEL_CONVERSION,
        payload_ref="request.json", resource_key=PT_TEST_RESOURCE,
        required_capabilities=("conversion",),
    ), artifacts=artifacts)
    nodes = ServiceNodeRepository(repo)
    _, token = nodes.create({
        "node_id": NODE, "display_name": "isolated PT CPU",
        "connection_mode": "agent", "allowed_capabilities": ["conversion"],
    })
    nodes.heartbeat(NODE, token, {"reported_capabilities": ["conversion"]})
    with closing(repo._connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            """UPDATE tasks SET status='RUNNING', stage='running',
                     attempt=3, worker_id=?, lease_token=?, lease_expires_at=?
               WHERE task_id=?""",
            ("agent:" + NODE, LEASE,
             (datetime.now(timezone.utc) + timedelta(seconds=120)).isoformat(),
             TASK),
        )
        db.commit()
    key = Ed25519PrivateKey.generate()
    issuer = CentralPtExportAdmissionIssuer(
        repo, artifacts, key, pt_trial_enabled=True)
    return repo, artifacts, token, key, issuer


def issue(context, **changes):
    _repo, _artifacts, token, _key, issuer = context
    request = {
        "task_id": TASK, "task_attempt": 3, "node_id": NODE,
        "node_token": token, "execution_lease_token": LEASE,
        "boot_id": BOOT, "challenge": "a" * 32,
    }
    request.update(changes)
    return issuer.issue(**request)


def binding(grant):
    return {
        key: value for key, value in grant["claims"].items()
        if key not in ("purpose", "issued_at", "expires_at")
    }


def test_central_signs_exact_stored_model_and_manifest_without_start(context):
    _repo, _artifacts, _token, key, _issuer = context
    grant = issue(context)
    claims = grant["claims"]
    assert claims["task_attempt"] == 3
    assert claims["source_sha256"] == SHA
    assert claims["source_size_bytes"] == len(SOURCE)
    assert claims["execution_lease_sha256"] == hashlib.sha256(LEASE.encode()).hexdigest()
    assert claims["runner_profile"] == "pt-to-onnx-cpu-v1"
    assert claims["gpu_uuid"] == "CPU_ONLY"
    assert claims["expires_at"] - claims["issued_at"] <= 15
    proof = verify_pt_export_admission_grant(
        grant, trusted_public_key=key.public_key(),
        expected_binding=binding(grant), now=claims["issued_at"])
    assert proof.source_sha256 == SHA
    assert proof.manifest_sha256 == claims["manifest_sha256"]
    assert not proof.launch_authorized and not proof.result_publish_allowed
    frozen = FrozenPtExportAdmission(
        task_id=TASK, task_attempt=3, worker_id="agent:" + NODE,
        node_id=NODE, execution_lease_sha256=claims["execution_lease_sha256"],
        source_sha256=SHA, source_size_bytes=len(SOURCE),
        source_name="source.pt", output_name="model.onnx",
        **claims["params"],
    )
    assert hashlib.sha256(
        frozen.freeze_nonexecutable_manifest(VerifiedPtBytes(SHA, len(SOURCE)))
    ).hexdigest() == claims["manifest_sha256"]
    serialized = json.dumps(grant)
    assert LEASE not in serialized
    assert "private" not in serialized
    assert "object_key" not in serialized
    assert "node_token" not in serialized
    assert "https://" not in serialized
    with pytest.raises(GrantRejected):
        verify_central_execution_grant(
            grant, trusted_public_key=key.public_key(),
            expected_binding={}, now=claims["issued_at"])


@pytest.mark.parametrize("change", [
    {"task_attempt": 2},
    {"execution_lease_token": "old-assignment-token"},
    {"node_token": "forged-node-credential"},
    {"node_id": "different-node"},
    {"challenge": "bad challenge"},
    {"boot_id": "noncanonical-boot"},
])
def test_central_rejects_wrong_original_identity(context, change):
    with pytest.raises(GrantRejected, match="HOLD"):
        issue(context, **change)


@pytest.mark.parametrize("sql,params", [
    ("UPDATE tasks SET attempt=4 WHERE task_id=?", (TASK,)),
    ("UPDATE tasks SET status='CANCEL_REQUESTED' WHERE task_id=?", (TASK,)),
    ("UPDATE tasks SET stage='stopping' WHERE task_id=?", (TASK,)),
    ("UPDATE tasks SET lease_token='rotated' WHERE task_id=?", (TASK,)),
    ("UPDATE tasks SET resource_key='gpu:0' WHERE task_id=?", (TASK,)),
    ("UPDATE tasks SET lease_expires_at='2000-01-01T00:00:00+00:00' WHERE task_id=?", (TASK,)),
    ("UPDATE service_nodes SET enabled=0 WHERE node_id=?", (NODE,)),
])
def test_central_owner_or_lease_revocation_rejects_grant(context, sql, params):
    repo, *_ = context
    with closing(repo._connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute(sql, params)
        db.commit()
    with pytest.raises(GrantRejected, match="HOLD"):
        issue(context)


@pytest.mark.parametrize("changes", [
    {"target": "rockchip"},
    {"calibration": {"images": []}},
    {"command": "/bin/sh"},
    {"params": {"input_size": 640, "batch": 1, "opset": 12,
                "dynamic": False, "simplify": False, "shell": "sh"}},
    {"params": {"input_size": 640, "batch": 1, "opset": 12,
                "dynamic": True, "simplify": False}},
    {"params": {"input_size": 640, "batch": 1, "opset": 13,
                "dynamic": False, "simplify": False}},
    {"source": {"type": "object", "file_name": "../escape.pt",
                "sha256": SHA, "size_bytes": len(SOURCE)}},
    {"source": {"type": "object", "file_name": "source.pt",
                "sha256": "0" * 64, "size_bytes": len(SOURCE)}},
])
def test_central_payload_must_be_restricted_and_sha_pinned(context, changes):
    _, artifacts, *_ = context
    altered = payload()
    altered["remote_execution"]["conversion"].update(changes)
    artifacts.atomic_write_json(TASK, "request.json", altered)
    with pytest.raises(GrantRejected, match="HOLD"):
        issue(context)


def test_tamper_signature_scope_and_expiry_rejected(context):
    _, _, _, key, _ = context
    grant = issue(context)
    now = grant["claims"]["issued_at"]
    expected = binding(grant)
    bad = {"claims": {**grant["claims"], "source_sha256": "0" * 64},
           "signature": grant["signature"]}
    with pytest.raises(GrantRejected, match="HOLD"):
        verify_pt_export_admission_grant(
            bad, trusted_public_key=key.public_key(),
            expected_binding={**expected, "source_sha256": "0" * 64},
            now=now)
    with pytest.raises(GrantRejected, match="HOLD"):
        verify_pt_export_admission_grant(
            grant, trusted_public_key=key.public_key(),
            expected_binding=expected, now=grant["claims"]["expires_at"])
    with pytest.raises(GrantRejected, match="HOLD"):
        verify_pt_export_admission_grant(
            grant, trusted_public_key=Ed25519PrivateKey.generate().public_key(),
            expected_binding=expected, now=now)
    with pytest.raises(GrantRejected, match="HOLD"):
        verify_pt_export_admission_grant(
            grant, trusted_public_key=key.public_key(),
            expected_binding={**expected, "challenge": "b" * 32}, now=now)
    with pytest.raises(GrantRejected, match="HOLD"):
        verify_pt_export_admission_grant(
            grant, trusted_public_key=key.public_key(),
            expected_binding={**expected, "manifest_sha256": "f" * 64}, now=now)


def test_not_exposed_by_default_or_as_an_agent_supplied_hash(context):
    repo, artifacts, token, key, _ = context
    disabled = CentralPtExportAdmissionIssuer(repo, artifacts, key)
    assert not disabled.enabled
    with pytest.raises(GrantRejected, match="ISSUER_DISABLED"):
        disabled.issue(
            task_id=TASK, task_attempt=3, node_id=NODE,
            node_token=token, execution_lease_token=LEASE,
            boot_id=BOOT, challenge="a" * 32)
    with pytest.raises(TypeError):
        issue(context, source_sha256="0" * 64)
    with pytest.raises(TypeError):
        issue(context, manifest_sha256="0" * 64)


def test_revocation_after_issuance_cannot_mint_new_admission(context):
    repo, _, _, key, _ = context
    first = issue(context)
    assert verify_pt_export_admission_grant(
        first, trusted_public_key=key.public_key(),
        expected_binding=binding(first), now=first["claims"]["issued_at"])
    with closing(repo._connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("UPDATE tasks SET status='CANCEL_REQUESTED' WHERE task_id=?",
                   (TASK,))
        db.commit()
    with pytest.raises(GrantRejected, match="HOLD"):
        issue(context, challenge="b" * 32)
    # No start / journal CAS in this stage: a previously minted signature
    # must never be interpreted as permission to launch after revocation.
