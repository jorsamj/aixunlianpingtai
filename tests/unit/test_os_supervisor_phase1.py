"""Phase-1 standalone Supervisor protocol and real Linux Unix Socket check."""
from __future__ import annotations

import os
from pathlib import Path
import platform
import socket
import struct
import sys
import threading
import time

import pytest

from platform_core.os_supervisor_protocol import (
    MAX_MESSAGE, SupervisorClient, SupervisedProcessHandle,
    SupervisorProtocolError, encode_frame, receive_frame, validate_request,
)
from platform_core.os_supervisor_service import SupervisorService, main

REQUEST = {"version": 1, "request_id": "abcd1234567",
           "action": "health", "payload": {}}


def test_protocol_frame_round_trip_and_schema():
    assert validate_request(REQUEST) == REQUEST
    sender, receiver = socket.socketpair()
    try:
        sender.sendall(encode_frame(REQUEST))
        assert receive_frame(receiver) == REQUEST
    finally:
        sender.close()
        receiver.close()


@pytest.mark.parametrize("invalid", [
    {**REQUEST, "version": True}, {**REQUEST, "version": 0},
    {**REQUEST, "action": "exec"}, {**REQUEST, "action": "kill"},
    {**REQUEST, "action": "sign_receipt"},
    {**REQUEST, "payload": {"command": "/bin/sh"}},
    {**REQUEST, "payload": {"claimed_uid": 0}},
    {**REQUEST, "request_id": "?"}, {**REQUEST, "other": True},
    {}, [], None,
])
def test_arbitrary_action_or_data_rejected(invalid):
    with pytest.raises(SupervisorProtocolError):
        validate_request(invalid)


@pytest.mark.parametrize("action", ["inspect", "stop", "read_log"])
def test_queries_require_exact_handle_and_generation(action):
    entry = {**REQUEST, "action": action, "payload": {}}
    with pytest.raises(SupervisorProtocolError, match="HANDLE_SCOPE_INCOMPLETE"):
        validate_request(entry)
    entry["payload"] = {"handle_id": "handle-123456789",
                        "execution_generation": 3}
    assert validate_request(entry)


@pytest.mark.parametrize("value", [0, -1, True, None, "1", 1.5])
def test_forged_generation_rejected(value):
    entry = {**REQUEST, "action": "inspect", "payload": {
        "handle_id": "handle-123456789", "execution_generation": value}}
    with pytest.raises(SupervisorProtocolError, match="INVALID_EXECUTION_GENERATION"):
        validate_request(entry)


def test_oversized_message_rejected_before_read():
    sender, receiver = socket.socketpair()
    try:
        sender.sendall(struct.pack("!I", MAX_MESSAGE + 1))
        with pytest.raises(SupervisorProtocolError, match="MESSAGE_SIZE_LIMIT"):
            receive_frame(receiver)
    finally:
        sender.close()
        receiver.close()


def test_truncated_payload_is_not_a_valid_message():
    sender, receiver = socket.socketpair()
    try:
        sender.sendall(struct.pack("!I", 100) + b"partial")
        sender.shutdown(socket.SHUT_WR)
        with pytest.raises(SupervisorProtocolError, match="PARTIAL"):
            receive_frame(receiver)
    finally:
        sender.close()
        receiver.close()


def test_no_privileged_action_enabled_and_unknown_never_means_stopped():
    service = SupervisorService(
        Path("/tmp/nonexistent-service.sock"),
        allowed_uid=10001, allowed_gid=10001)
    assert service.dispatch(REQUEST, peer_uid=10002)["code"] == "PEER_UID_DENIED"
    health = service.dispatch(REQUEST, peer_uid=10001)
    assert health["ok"] is True
    assert health["result"]["launch_available"] is False
    assert health["result"]["central_recovery_allowed"] is False
    handle = {"handle_id": "handle-123456789", "execution_generation": 3}
    for action in ("start", "stop", "inspect", "read_log"):
        query = {**REQUEST, "action": action,
                 "payload": {} if action == "start" else handle}
        response = service.dispatch(query, peer_uid=10001)
        assert response["ok"] is False
        assert response["code"].endswith("HOLD")
        if action == "inspect":
            assert response["result"]["state"] == "UNKNOWN"


def test_supervised_handle_fails_closed_on_unknown_stop_and_log():
    class FakeClient:
        def call(self, action, payload):
            return {"ok": False, "result": {"state": "UNKNOWN"}}
    handle = SupervisedProcessHandle(FakeClient(), "handle-123456789", 1)
    with pytest.raises(SupervisorProtocolError, match="STATUS_UNVERIFIED_HOLD"):
        handle.poll()
    with pytest.raises(SupervisorProtocolError, match="STOP_UNVERIFIED_HOLD"):
        handle.request_stop()
    with pytest.raises(SupervisorProtocolError, match="LOG_UNAVAILABLE_HOLD"):
        handle.read_log()
    assert not hasattr(handle, "pid")
    assert not hasattr(handle, "kill")


def test_supervised_process_exit_status_must_not_be_boolean():
    class FakeClient:
        state = {"state": "EXITED", "exit_code": True}
        def call(self, action, payload):
            return {"ok": True, "result": self.state}
    fake = FakeClient()
    handle = SupervisedProcessHandle(fake, "handle-123456789", 1)
    with pytest.raises(SupervisorProtocolError, match="STATUS_UNKNOWN_HOLD"):
        handle.poll()
    fake.state = {"state": "RUNNING"}
    assert handle.poll() is None
    fake.state = {"state": "EXITED", "exit_code": 2}
    assert handle.poll() == 2


@pytest.mark.skipif(
    platform.system() != "Linux" or not hasattr(socket, "SO_PEERCRED") or
    not hasattr(os, "geteuid") or os.geteuid() == 0,
    reason="requires a non-root Linux account")
def test_real_nonroot_socket_and_kernel_peer_credentials(tmp_path):
    endpoint = tmp_path / "supervisor.sock"
    service = SupervisorService(endpoint, allowed_uid=os.geteuid(),
                                allowed_gid=os.getegid())
    runner = threading.Thread(
        target=lambda: service.serve(test_only_unprivileged=True),
        daemon=True)
    runner.start()
    for _ in range(200):
        if endpoint.is_socket():
            break
        time.sleep(0.01)
    try:
        assert endpoint.is_socket()
        client = SupervisorClient(
            str(endpoint), expected_supervisor_uid=os.geteuid())
        result = client.call("health")
        assert result["ok"] is True
        assert result["result"]["trusted_stop_receipt_available"] is False
        assert client.call("start")["code"] == "PROTECTED_LAUNCH_NOT_IMPLEMENTED_HOLD"
        with pytest.raises(SupervisorProtocolError):
            SupervisedProcessHandle(client, "handle-123456789", 3).poll()
        untrusted = SupervisorClient(str(endpoint), expected_supervisor_uid=0)
        with pytest.raises(SupervisorProtocolError, match="PEER_NOT_TRUSTED_HOLD"):
            untrusted.call("health")
    finally:
        service.close()
        runner.join(timeout=4)
    assert not endpoint.exists()


def test_service_cli_does_not_run_implicitly(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["os-supervisor"])
    assert main() == 2
    assert "INERT_OPT_IN_REQUIRED" in capsys.readouterr().out


def test_root_cannot_be_an_agent_peer_uid():
    with pytest.raises(ValueError, match="non-root"):
        SupervisorService(Path("/tmp/never-used.sock"), allowed_uid=0, allowed_gid=0)
