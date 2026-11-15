"""P0-01C phase-1B signed grant and durable pre-launch journal contracts."""
import hashlib
import sqlite3
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from platform_core.os_supervisor_authorization import (
    CLAIM_FIELDS, PURPOSE, GrantRejected, _claims_payload,
    verify_central_execution_grant,
)
from platform_core.os_supervisor_journal import ExecutionJournal

BOOT = "65ad39e5-7bfa-4b46-9b1e-7f1f0d0d6c8a"


def binding(task_id="train_example12345", attempt=3):
    return {
        "task_id": task_id, "task_attempt": attempt,
        "worker_id": "agent:node_example123", "node_id": "node_example123",
        "execution_lease_sha256": hashlib.sha256(b"original-execution-lease").hexdigest(),
        "gpu_uuid": "CPU_ONLY", "boot_id": BOOT,
        "runner_profile": "fixed-cpu-v1",
    }


def signed(private_key, scope, now=1000):
    claims = {**scope, "purpose": PURPOSE,
              "issued_at": now, "expires_at": now + 60}
    assert set(claims) == CLAIM_FIELDS
    return {"claims": claims,
            "signature": private_key.sign(_claims_payload(claims)).hex()}


def test_verified_grant_is_bound_to_original_attempt_lease_and_boot():
    key = Ed25519PrivateKey.generate()
    scope = {**binding(), "challenge": "a" * 32}
    verified = verify_central_execution_grant(
        signed(key, scope), trusted_public_key=key.public_key(),
        expected_binding=scope, now=1010)
    assert verified.task_attempt == 3
    assert verified.execution_lease_sha256 == scope["execution_lease_sha256"]
    assert len(verified.grant_digest) == 64


@pytest.mark.parametrize("field,value", [
    ("task_attempt", 4), ("task_attempt", True),
    ("execution_lease_sha256", "0" * 64),
    ("boot_id", "91ad39e5-7bfa-4b46-9b1e-7f1f0d0d6c8a"),
    ("challenge", "b" * 32), ("gpu_uuid", "GPU-OTHER"),
    ("worker_id", "agent:node_other000"), ("runner_profile", "training"),
])
def test_signature_cannot_override_expected_supervisor_scope(field, value):
    key = Ed25519PrivateKey.generate()
    scope = {**binding(), "challenge": "a" * 32}
    altered = {**scope, field: value}
    with pytest.raises(GrantRejected):
        verify_central_execution_grant(
            signed(key, altered), trusted_public_key=key.public_key(),
            expected_binding=scope, now=1010)


def test_expiry_untrusted_key_tamper_and_arbitrary_command_are_denied():
    key = Ed25519PrivateKey.generate()
    scope = {**binding(), "challenge": "a" * 32}
    envelope = signed(key, scope)
    another = Ed25519PrivateKey.generate()
    with pytest.raises(GrantRejected, match="SIGNATURE"):
        verify_central_execution_grant(
            envelope, trusted_public_key=another.public_key(),
            expected_binding=scope, now=1010)
    with pytest.raises(GrantRejected, match="EXPIRED"):
        verify_central_execution_grant(
            envelope, trusted_public_key=key.public_key(),
            expected_binding=scope, now=1061)
    changed = {"claims": {**envelope["claims"], "task_id": "train_changed000"},
               "signature": envelope["signature"]}
    with pytest.raises(GrantRejected):
        verify_central_execution_grant(
            changed, trusted_public_key=key.public_key(),
            expected_binding=scope, now=1010)
    extra = {"claims": {**envelope["claims"], "command": "/bin/sh"},
             "signature": envelope["signature"]}
    with pytest.raises(GrantRejected, match="SCHEMA"):
        verify_central_execution_grant(
            extra, trusted_public_key=key.public_key(),
            expected_binding=scope, now=1010)


def test_journal_response_loss_and_restart_do_not_allocate_second_handle(tmp_path):
    key = Ed25519PrivateKey.generate()
    file = tmp_path / "execution.sqlite3"
    journal = ExecutionJournal(file, test_only_unprivileged=True,
                               boot_id_for_tests=BOOT)
    scope = binding()
    nonce = journal.issue_challenge(scope, now=1000)
    envelope = signed(key, {**scope, "challenge": nonce})
    first = journal.register_intent(
        envelope, trusted_public_key=key.public_key(), now=1010)
    assert first["state"] == "UNKNOWN" and first["replayed"] is False
    restarted = ExecutionJournal(file, test_only_unprivileged=True,
                                 boot_id_for_tests=BOOT)
    second = restarted.register_intent(
        envelope, trusted_public_key=key.public_key(), now=1011)
    assert second["handle_id"] == first["handle_id"] and second["replayed"]
    assert restarted.inspect(first["handle_id"], 3)["state"] == "UNKNOWN"
    with pytest.raises(GrantRejected, match="NOT_REGISTERED"):
        restarted.inspect(first["handle_id"], 4)
    with sqlite3.connect(file) as db:
        assert db.execute("SELECT count(*) FROM execution_intents").fetchone()[0] == 1
        assert db.execute("SELECT state,event_seq FROM execution_intents").fetchone() == (
            "PREPARED", 1)


def test_conflicting_valid_grant_for_same_attempt_is_hold(tmp_path):
    key = Ed25519PrivateKey.generate()
    journal = ExecutionJournal(tmp_path / "execution.sqlite3",
                               test_only_unprivileged=True, boot_id_for_tests=BOOT)
    scope = binding()
    first_nonce = journal.issue_challenge(scope, now=1000)
    journal.register_intent(signed(key, {**scope, "challenge": first_nonce}),
                            trusted_public_key=key.public_key(), now=1010)
    second_nonce = journal.issue_challenge(scope, now=1000)
    with pytest.raises(GrantRejected, match="ALREADY_RESERVED"):
        journal.register_intent(
            signed(key, {**scope, "challenge": second_nonce}),
            trusted_public_key=key.public_key(), now=1011)


def test_bad_boot_unknown_challenge_and_signature_fail_closed(tmp_path):
    key = Ed25519PrivateKey.generate()
    journal = ExecutionJournal(tmp_path / "execution.sqlite3",
                               test_only_unprivileged=True, boot_id_for_tests=BOOT)
    scope = binding()
    with pytest.raises(GrantRejected, match="BOOT_SCOPE"):
        journal.issue_challenge({**scope, "boot_id": str(uuid4())}, now=1000)
    nonce = journal.issue_challenge(scope, now=1000)
    tampered = signed(key, {**scope, "challenge": nonce})
    tampered["signature"] = "0" * 128
    with pytest.raises(GrantRejected, match="SIGNATURE"):
        journal.register_intent(
            tampered, trusted_public_key=key.public_key(), now=1010)
    with pytest.raises(GrantRejected, match="UNKNOWN_OR_EXPIRED"):
        journal.register_intent(
            signed(key, {**scope, "challenge": "f" * 32}),
            trusted_public_key=key.public_key(), now=1010)


def test_root_owned_path_is_required_outside_test_only_mode(tmp_path):
    with pytest.raises(GrantRejected, match="PROTECTED_OS_IDENTITY"):
        ExecutionJournal(tmp_path / "execution.sqlite3",
                         boot_id_for_tests=BOOT)
