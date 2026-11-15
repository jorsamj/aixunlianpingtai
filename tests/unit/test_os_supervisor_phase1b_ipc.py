"""P0-01C 1B-2B: actual central HTTP -> Linux AF_UNIX -> durable intent.

No worker is started or stopped. Test-only signer injection and unprivileged
socket/journal paths are never wired by production CLI.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import os
from pathlib import Path
import platform
import socket
import sqlite3
import threading
import time

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from platform_core.agent_execution import agent_executor_router
from platform_core.os_supervisor_authorization import GrantRejected
from platform_core.os_supervisor_journal import ExecutionJournal
from platform_core.os_supervisor_protocol import (
    SupervisorClient, SupervisorProtocolError, validate_request,
)
from platform_core.os_supervisor_service import SupervisorService
from platform_core.service_nodes import ServiceNodeRepository
from platform_core.task_runtime import ArtifactStore, TaskKind, TaskRecord, TaskRepository
import platform_core.os_supervisor_central_api as central_api

NODE = "node1"
TASK = "conv_ipc_test123"
LEASE = "original-execution-lease-not-an-assignment-token"
BOOT = "65ad39e5-7bfa-4b46-9b1e-7f1f0d0d6c8a"


@pytest.fixture
def trial(tmp_path):
    repository = TaskRepository(tmp_path / "task_runtime" / "tasks.sqlite3")
    nodes = ServiceNodeRepository(repository)
    _, token = nodes.create({
        "node_id": NODE, "display_name": "CPU trial node",
        "connection_mode": "agent", "allowed_capabilities": ["conversion"],
    })
    nodes.heartbeat(NODE, token, {"reported_capabilities": ["conversion"]})
    repository.create(TaskRecord.new(
        task_id=TASK, project_id="trial_project",
        kind=TaskKind.MODEL_CONVERSION, payload_ref="request.json",
        resource_key="supervisor-cpu-v1",
        required_capabilities=("conversion",),
    ))
    with closing(repository._connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            """UPDATE tasks SET status='RUNNING',stage='running',attempt=3,
                   worker_id=?,lease_token=?,lease_expires_at=?
               WHERE task_id=?""",
            ("agent:" + NODE, LEASE,
             (datetime.now(timezone.utc) + timedelta(seconds=120)).isoformat(),
             TASK),
        )
        db.commit()
    artifacts = ArtifactStore(tmp_path / "task_runtime" / "artifacts")
    app = FastAPI()
    app.include_router(agent_executor_router(lambda: repository, lambda: artifacts))
    journal = ExecutionJournal(tmp_path / "supervisor" / "execution.sqlite3",
                               test_only_unprivileged=True,
                               boot_id_for_tests=BOOT)
    key = Ed25519PrivateKey.generate()
    service = SupervisorService(
        tmp_path / "control.sock", allowed_uid=10001, allowed_gid=10001,
        authorization_journal=journal, trusted_public_key=key.public_key())
    return TestClient(app), repository, token, journal, key, service


def req(action, payload=None):
    return {"version": 1, "request_id": "request12345678", "action": action,
            "payload": {} if payload is None else payload}


def scope():
    return {
        "task_id": TASK, "task_attempt": 3,
        "node_id": NODE, "worker_id": "agent:" + NODE,
        "execution_lease_sha256": hashlib.sha256(LEASE.encode()).hexdigest(),
        "gpu_uuid": "CPU_ONLY", "boot_id": BOOT,
        "runner_profile": "fixed-cpu-v1",
    }


def test_protocol_only_allows_fixed_cpu_intent_and_no_commands():
    assert validate_request(req("challenge", scope()))
    assert validate_request(req("authorize_intent", {
        "envelope": {"claims": {}, "signature": "a" * 128}}))
    for payload in (
        {**scope(), "command": "/bin/sh"}, {**scope(), "gpu_uuid": "GPU-1"},
        {**scope(), "unit": "anything.service"},
    ):
        with pytest.raises(SupervisorProtocolError):
            validate_request(req("challenge", payload))
    for action, payload in (
        ("start", {"envelope": {"claims": {}, "signature": ""}}),
        ("authorize_intent", {"key_file": "/tmp/agent-key.pem"}),
        ("kill", {}),
    ):
        with pytest.raises(SupervisorProtocolError):
            validate_request(req(action, payload))


def test_disabled_by_default_in_both_existing_endpoints(trial, monkeypatch):
    app_client, _, token, journal, key, service = trial
    challenge = service.dispatch(req("challenge", scope()), peer_uid=10001)
    assert challenge["code"] == "CPU_CHALLENGE_ISSUED"
    # A separate, deliberately nonconfigured service cannot register anything.
    inert = SupervisorService(Path("/tmp/unused.sock"),
                              allowed_uid=10001, allowed_gid=10001)
    assert inert.dispatch(req("challenge", scope()), peer_uid=10001)["code"] == (
        "CPU_INTENT_REGISTRATION_DISABLED_HOLD")
    monkeypatch.delenv("CHANGLIAN_SUPERVISOR_CPU_GRANTS_ENABLED", raising=False)
    response = app_client.post(
        f"/api/v63/node-executor/{NODE}/executions/{TASK}/supervisor-cpu/grant",
        json={"execution_generation": 3, "execution_lease_token": LEASE,
              "boot_id": BOOT, "challenge": challenge["result"]["challenge"]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "CENTRAL_CPU_ISSUER_DISABLED_HOLD"
    assert service.dispatch(req("start"), peer_uid=10001)["code"] == (
        "PROTECTED_LAUNCH_NOT_IMPLEMENTED_HOLD")


def test_http_grant_to_actual_journal_and_duplicate_registration(trial, monkeypatch):
    app_client, _, token, journal, key, service = trial
    monkeypatch.setenv("CHANGLIAN_SUPERVISOR_CPU_GRANTS_ENABLED", "1")
    monkeypatch.setattr(central_api, "load_control_issuer_private_key", lambda: key)
    challenge_reply = service.dispatch(req("challenge", scope()), peer_uid=10001)
    assert challenge_reply["ok"] is True
    payload = {"execution_generation": 3, "execution_lease_token": LEASE,
               "boot_id": BOOT,
               "challenge": challenge_reply["result"]["challenge"]}
    url = f"/api/v63/node-executor/{NODE}/executions/{TASK}/supervisor-cpu/grant"
    response = app_client.post(url, json=payload,
                               headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200, response.text
    grant = response.json()["grant"]
    assert response.json()["launch_authorized"] is False
    assert grant["claims"]["task_attempt"] == 3
    first = service.dispatch(req("authorize_intent", {"envelope": grant}),
                             peer_uid=10001)
    second = service.dispatch(req("authorize_intent", {"envelope": grant}),
                              peer_uid=10001)
    assert first["ok"] and second["ok"]
    assert first["code"] == "CPU_INTENT_RECORDED_NO_LAUNCH"
    assert first["result"]["handle_id"] == second["result"]["handle_id"]
    assert second["result"]["replayed"] is True
    inspect = service.dispatch(req("inspect", {
        "handle_id": first["result"]["handle_id"],
        "execution_generation": 3}), peer_uid=10001)
    assert inspect["ok"] is False and inspect["result"]["state"] == "UNKNOWN"
    assert service.dispatch(req("start"), peer_uid=10001)["ok"] is False
    assert service.dispatch(req("stop", {
        "handle_id": first["result"]["handle_id"],
        "execution_generation": 3}), peer_uid=10001)["ok"] is False
    restarted = ExecutionJournal(
        journal.path, test_only_unprivileged=True, boot_id_for_tests=BOOT)
    assert restarted.inspect(first["result"]["handle_id"], 3)["state"] == "UNKNOWN"
    with sqlite3.connect(journal.path) as db:
        assert db.execute("SELECT count(*) FROM execution_intents").fetchone()[0] == 1


def test_wrong_key_wrong_agent_and_unregistered_nonce_hold(trial, monkeypatch):
    app_client, _, token, journal, key, service = trial
    monkeypatch.setenv("CHANGLIAN_SUPERVISOR_CPU_GRANTS_ENABLED", "1")
    monkeypatch.setattr(central_api, "load_control_issuer_private_key", lambda: key)
    challenge = service.dispatch(req("challenge", scope()), peer_uid=10001)
    url = f"/api/v63/node-executor/{NODE}/executions/{TASK}/supervisor-cpu/grant"
    payload = {"execution_generation": 3, "execution_lease_token": LEASE,
               "boot_id": BOOT, "challenge": challenge["result"]["challenge"]}
    assert app_client.post(url, json=payload).status_code == 401
    assert app_client.post(url, json={**payload, "path": "/bin/sh"},
                           headers={"Authorization": f"Bearer {token}"}).status_code == 422
    assert app_client.post(url, json={**payload, "execution_generation": 4},
                           headers={"Authorization": f"Bearer {token}"}).status_code == 409
    grant = app_client.post(url, json=payload,
                            headers={"Authorization": f"Bearer {token}"}).json()["grant"]
    bad_service = SupervisorService(
        Path("/tmp/unused.sock"), allowed_uid=10001, allowed_gid=10001,
        authorization_journal=journal,
        trusted_public_key=Ed25519PrivateKey.generate().public_key())
    assert bad_service.dispatch(req("authorize_intent", {"envelope": grant}),
                                peer_uid=10001)["ok"] is False
    bad = {**grant, "claims": {**grant["claims"], "challenge": "f" * 32}}
    assert service.dispatch(req("authorize_intent", {"envelope": bad}),
                            peer_uid=10001)["ok"] is False
    assert service.dispatch(req("authorize_intent", {"envelope": grant}),
                            peer_uid=10002)["code"] == "PEER_UID_DENIED"


@pytest.mark.skipif(platform.system() != "Linux" or
                    not hasattr(socket, "SO_PEERCRED") or
                    not hasattr(os, "geteuid") or os.geteuid() == 0,
                    reason="real AF_UNIX SO_PEERCRED requires non-root Linux runner")
def test_real_unix_socket_cpu_intent_registration_does_not_start_worker(
        trial, tmp_path, monkeypatch):
    app_client, _, token, journal, key, _unused = trial
    monkeypatch.setenv("CHANGLIAN_SUPERVISOR_CPU_GRANTS_ENABLED", "1")
    monkeypatch.setattr(central_api, "load_control_issuer_private_key", lambda: key)
    path = tmp_path / "trusted.sock"
    service = SupervisorService(
        path, allowed_uid=os.geteuid(), allowed_gid=os.getegid(),
        authorization_journal=journal, trusted_public_key=key.public_key())
    thread = threading.Thread(
        target=lambda: service.serve(test_only_unprivileged=True), daemon=True)
    thread.start()
    try:
        for _ in range(200):
            if path.is_socket():
                break
            time.sleep(0.01)
        assert path.is_socket()
        client = SupervisorClient(
            str(path), expected_supervisor_uid=os.geteuid())
        nonce = client.call("challenge", scope())["result"]["challenge"]
        response = app_client.post(
            f"/api/v63/node-executor/{NODE}/executions/{TASK}/supervisor-cpu/grant",
            json={"execution_generation": 3, "execution_lease_token": LEASE,
                  "boot_id": BOOT, "challenge": nonce},
            headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200, response.text
        saved = client.call("authorize_intent", {"envelope": response.json()["grant"]})
        assert saved["ok"] is True and saved["result"]["state"] == "UNKNOWN"
        assert client.call("health")["result"]["launch_available"] is False
        assert client.call("start")["ok"] is False
    finally:
        service.close()
        thread.join(timeout=4)
    assert not path.exists()


@pytest.mark.skipif(os.name != "posix" or not hasattr(os, "geteuid"),
                    reason="pinned key file permission check needs POSIX")
def test_trusted_control_signer_file_requires_private_mode_and_no_symlink(
        tmp_path, monkeypatch):
    from cryptography.hazmat.primitives import serialization
    from platform_core.os_supervisor_trust import load_control_issuer_private_key
    import platform_core.os_supervisor_trust as trust

    folder = tmp_path / "control-keys"
    folder.mkdir(mode=0o700)
    folder.chmod(0o700)
    key_file = folder / "issuer.ed25519"
    signing_key = Ed25519PrivateKey.generate()
    raw = signing_key.private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
        serialization.NoEncryption())
    key_file.write_bytes(raw)
    key_file.chmod(0o600)
    monkeypatch.setattr(trust, "CONTROL_KEY_PATH", key_file)
    read_key = load_control_issuer_private_key()
    assert read_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw) == signing_key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)

    key_file.chmod(0o644)
    with pytest.raises(GrantRejected, match="FILE_UNTRUSTED"):
        load_control_issuer_private_key()

    key_file.unlink()
    other = folder / "other"
    other.write_bytes(raw)
    other.chmod(0o600)
    key_file.symlink_to(other)
    with pytest.raises(GrantRejected):
        load_control_issuer_private_key()
