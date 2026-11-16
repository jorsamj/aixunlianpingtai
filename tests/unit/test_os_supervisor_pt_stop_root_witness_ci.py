"""2C-03D: CI root's OS stop witness cannot be signed by Agent JSON.

Root/test-only process boundary uses fake cgroup.files here. The real kernel
and systemd path are covered by the separate Ubuntu24.04 integration workflow.
"""
from __future__ import annotations

from contextlib import closing
import os
from pathlib import Path
import sys
import time

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_os_supervisor_pt_export_launch import BOOT, TASK, stage
from test_os_supervisor_pt_stop_grant import original_running, stop_scope

from platform_core.os_supervisor_authorization import GrantRejected
from platform_core.os_supervisor_pt_stop_observation import IsolatedPtStopObserver
from platform_core.os_supervisor_pt_stop_rechecked_bridge import CiOnlyPtStopRecheckedBridge
from platform_core.os_supervisor_pt_stop_root_witness_ci import (
    CiOnlyRootPtStopWitnessSigner, _BIND, _canonical,
    verify_ci_root_stop_witness,
)


class _FakeKernel:
    def __init__(self, original, path):
        self.original = dict(original)
        self.path = path
        self.calls = []
        self.empty_on_stop = True

    def inspect(self, unit, invocation):
        self.calls.append("inspect")
        assert unit == self.original["unit_name"]
        assert invocation == self.original["invocation_id"]
        return {
            "unit_name": self.original["unit_name"],
            "invocation_id": self.original["invocation_id"],
            "control_group": self.original["control_group"],
            "main_pid": self.original["main_pid"],
            "active_state": "active", "sub_state": "running",
        }

    def request_stop(self, unit, invocation):
        self.calls.append("stop")
        assert unit == self.original["unit_name"]
        assert invocation == self.original["invocation_id"]
        if self.empty_on_stop:
            self.path.write_text("populated 0\nfrozen 0\n", encoding="ascii")
        return {"stop_requested": True, "state": "UNKNOWN",
                "trusted_stop_receipt_available": False}


@pytest.fixture
def root_ci(original_running, tmp_path, monkeypatch):
    if os.name != "posix":
        pytest.skip("CI-only root signer requires Linux; pure verifier runs on Windows")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("RUNNER_ENVIRONMENT", "github-hosted")
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    stage_data, handle = original_running
    repo, artifacts, key, token, issuer, root, pt, scope = stage_data
    origin = pt.verified_pt_identity(handle, 3)
    group = tmp_path / origin["control_group"].lstrip("/")
    group.mkdir(parents=True)
    path = group / "cgroup.events"
    path.write_text("populated 1\nfrozen 0\n", encoding="ascii")
    backend = _FakeKernel(origin, path)
    observer = IsolatedPtStopObserver(
        journal=pt, backend=backend, cgroup_root=tmp_path,
        isolated_ci_only=True,
    )
    bridge = CiOnlyPtStopRecheckedBridge(
        pt, observer, isolated_ci_only=True,
    )
    signer = CiOnlyRootPtStopWitnessSigner(
        pt, bridge, isolated_ci_only=True,
    )
    return stage_data, handle, pt, backend, signer


def _claim_root_stop(root_ci):
    stage_data, handle, pt, backend, signer = root_ci
    envelope, _ = stop_scope((stage_data, handle))
    pt.claim_pt_stop_rechecked(
        handle, 3, envelope, trusted_public_key=stage_data[2].public_key(),
    )


def _sign(signer, handle):
    return signer.stop_and_sign(
        handle, 3, challenge_id="f" * 32,
        nonce="an-isolated-central-challenge-" + "z" * 24,
    )


def test_root_signs_only_after_original_claim_and_kernel_empty(root_ci):
    stage_data, handle, pt, backend, signer = root_ci
    _claim_root_stop(root_ci)
    envelope = _sign(signer, handle)
    body = envelope["payload"]
    assert body["test_only_no_production_recovery"] is True
    assert body["os_cgroup_empty"] is True
    assert body["known_processes_stopped"] is True
    assert body["stop_command_succeeded"] is True
    assert body["stop_requested_ns"] > 0
    assert body["empty_observed_ns"] >= body["stop_requested_ns"]
    assert body["unit"] == "changlian-os-" + handle + ".service"
    assert body["boot_id"] == BOOT
    assert body["task_id"] == TASK
    assert body["task_attempt"] == 3
    assert backend.calls.count("stop") == 1
    expected = {key: body[key] for key in _BIND}
    assert verify_ci_root_stop_witness(
        envelope, public_key=signer.public_key,
        expected_original=expected, now=body["issued_at"],
    )
    with closing(stage_data[0]._connect()) as db:
        assert db.execute(
            "SELECT status FROM tasks WHERE task_id=?", (TASK,),
        ).fetchone()[0] == "CANCEL_REQUESTED"
    with closing(stage_data[5]._connect()) as db:
        assert db.execute(
            "SELECT state FROM execution_intents WHERE handle_id=?",
            (handle,),
        ).fetchone()[0] == "RUNNING"
        assert db.execute(
            "SELECT COUNT(*) FROM pt_export_stop_observation_claims",
        ).fetchone()[0] == 1


def test_unclaimed_central_stop_cannot_reach_systemd_or_sign(root_ci):
    stage_data, handle, pt, backend, signer = root_ci
    with pytest.raises(GrantRejected, match="OS_STOP_OBSERVATION_NOT_AUTHORIZED"):
        _sign(signer, handle)
    assert "stop" not in backend.calls


def test_root_signer_never_replays_same_os_unit(root_ci):
    stage_data, handle, pt, backend, signer = root_ci
    _claim_root_stop(root_ci)
    _sign(signer, handle)
    with pytest.raises(GrantRejected, match="OS_STOP_OBSERVATION_NOT_AUTHORIZED"):
        _sign(signer, handle)
    assert backend.calls.count("stop") == 1


def test_kernel_unknown_cannot_become_signed_receipt(root_ci, monkeypatch):
    import platform_core.os_supervisor_pt_stop_observation as module
    stage_data, handle, pt, backend, signer = root_ci
    _claim_root_stop(root_ci)
    backend.empty_on_stop = False
    # Bound a synthetic test observation; no live kernel waiting is needed.
    ticker = iter([1, 4, 7, 10, 13, 16, 19, 22])
    monkeypatch.setattr(module.time, "monotonic", lambda: next(ticker, 25))
    with pytest.raises(GrantRejected, match="KERNEL_STOP_NOT_CONFIRMED"):
        _sign(signer, handle)
    assert backend.calls.count("stop") == 1
    with pytest.raises(GrantRejected, match="OS_STOP_OBSERVATION_NOT_AUTHORIZED"):
        _sign(signer, handle)


def test_invalid_central_challenge_never_touches_os(root_ci):
    stage_data, handle, pt, backend, signer = root_ci
    _claim_root_stop(root_ci)
    with pytest.raises(GrantRejected, match="CHALLENGE_ARGUMENTS"):
        signer.stop_and_sign(handle, 3, challenge_id="bad", nonce="bad")
    assert backend.calls.count("stop") == 0


def test_root_signer_default_is_disabled(root_ci):
    stage_data, handle, pt, backend, signer = root_ci
    with pytest.raises(GrantRejected, match="PRODUCTION_DISABLED"):
        CiOnlyRootPtStopWitnessSigner(pt, signer.bridge)
    with pytest.raises(GrantRejected, match="PRODUCTION_DISABLED"):
        CiOnlyRootPtStopWitnessSigner(None, None, isolated_ci_only=True)


def test_wrong_key_trusted_scope_and_replay_time_cannot_verify(root_ci):
    stage_data, handle, pt, backend, signer = root_ci
    _claim_root_stop(root_ci)
    receipt = _sign(signer, handle)
    body = receipt["payload"]
    expected = {k: body[k] for k in _BIND}
    assert not verify_ci_root_stop_witness(
        receipt, public_key=Ed25519PrivateKey.generate().public_key(),
        expected_original=expected, now=body["issued_at"],
    )
    for field, value in (
        ("task_attempt", 4),
        ("worker_id", "agent:other-node"),
        ("execution_lease_sha256", "c" * 64),
        ("boot_id", "ffffffff-ffff-ffff-ffff-ffffffffffff"),
        ("invocation_id", "c" * 32),
        ("stop_grant_digest", "d" * 64),
        ("nonce", "attacker-challenge-" + "y" * 24),
    ):
        forged_scope = {**expected, field: value}
        assert not verify_ci_root_stop_witness(
            receipt, public_key=signer.public_key,
            expected_original=forged_scope, now=body["issued_at"],
        )
    assert not verify_ci_root_stop_witness(
        receipt, public_key=signer.public_key,
        expected_original=expected, now=body["expires_at"],
    )
    changed = {**body, "empty_observed_ns": body["empty_observed_ns"] + 4}
    assert not verify_ci_root_stop_witness(
        {"payload": changed, "signature": receipt["signature"]},
        public_key=signer.public_key,
        expected_original=expected, now=body["issued_at"],
    )


def test_pure_ed25519_domain_and_exact_schema_on_windows_too():
    """A separate pure-crypto test cannot activate the CI root OS signer."""
    now = int(time.time())
    handle = "a" * 32
    unit = "changlian-os-" + handle + ".service"
    body = {
        "purpose": "changlian-ci-root-pt-stop-witness-v1",
        "test_only_no_production_recovery": True,
        "challenge_id": "b" * 32,
        "nonce": "pinned-original-central-" + "c" * 24,
        "handle_id": handle,
        "task_id": "conv_pt_origin",
        "task_attempt": 3,
        "worker_id": "agent:gpu01",
        "execution_lease_sha256": "d" * 64,
        "boot_id": "01234567-89ab-cdef-0123-456789abcdef",
        "unit": unit,
        "invocation_id": "e" * 32,
        "cgroup": "/system.slice/" + unit,
        "main_pid": 3210,
        "stop_grant_digest": "f" * 64,
        "stop_reason": "CANCEL_REQUESTED",
        "os_cgroup_empty": True,
        "known_processes_stopped": True,
        "stop_command_succeeded": True,
        "stop_requested_ns": 100,
        "empty_observed_ns": 130,
        "issued_at": now,
        "expires_at": now + 12,
    }
    key = Ed25519PrivateKey.generate()
    receipt = {"payload": body, "signature": key.sign(_canonical(body)).hex()}
    expected = {field: body[field] for field in _BIND}
    assert verify_ci_root_stop_witness(
        receipt, public_key=key.public_key(), expected_original=expected,
        now=now,
    )
    for field, value in (
        ("test_only_no_production_recovery", False),
        ("purpose", "production"),
        ("known_processes_stopped", False),
        ("os_cgroup_empty", "true"),
        ("stop_command_succeeded", False),
        ("empty_observed_ns", 90),
        ("task_attempt", True),
        ("unit", "ssh.service"),
    ):
        changed = {**body, field: value}
        with pytest.raises(GrantRejected, match="PT_CI_ROOT_STOP_WITNESS_"):
            _canonical(changed)
    assert not verify_ci_root_stop_witness(
        {"payload": {**body, "extra": "injected"},
         "signature": receipt["signature"]},
        public_key=key.public_key(), expected_original=expected, now=now,
    )
