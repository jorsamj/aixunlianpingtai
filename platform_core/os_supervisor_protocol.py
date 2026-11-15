"""Versioned bounded local protocol for a future protected Linux OS Supervisor.

Phase 1 deliberately has NO launch/stop backend. Successful IPC is neither a
central execution grant nor a trusted OS StopReceipt. UNKNOWN must mean HOLD.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
import re
import socket
import struct
from typing import Any, Mapping

PROTOCOL_VERSION = 1
MAX_MESSAGE = 16 * 1024
ALLOWED_ACTIONS = frozenset({"health", "inspect", "start", "stop", "read_log"})
_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{7,127}$")


class SupervisorProtocolError(RuntimeError):
    """Unverified Supervisor state: never permit fallback to direct execution."""


def _valid_id(value: object) -> bool:
    return isinstance(value, str) and bool(_ID.fullmatch(value))


def validate_request(value: object) -> dict[str, Any]:
    """Reject unknown fields, commands, arbitrary paths, and invalid generations."""
    if not isinstance(value, dict) or set(value) != {
            "version", "request_id", "action", "payload"}:
        raise SupervisorProtocolError("INVALID_REQUEST_SHAPE")
    if type(value["version"]) is not int or value["version"] != PROTOCOL_VERSION:
        raise SupervisorProtocolError("UNSUPPORTED_PROTOCOL_VERSION")
    if not _valid_id(value["request_id"]):
        raise SupervisorProtocolError("INVALID_REQUEST_ID")
    action = value["action"]
    if not isinstance(action, str) or action not in ALLOWED_ACTIONS:
        raise SupervisorProtocolError("ACTION_NOT_ALLOWLISTED")
    payload = value["payload"]
    if not isinstance(payload, dict):
        raise SupervisorProtocolError("INVALID_PAYLOAD")
    if action == "health":
        if payload:
            raise SupervisorProtocolError("HEALTH_PAYLOAD_NOT_EMPTY")
    elif action == "start":
        if payload:
            raise SupervisorProtocolError("START_NOT_IMPLEMENTED")
    else:
        if set(payload) != {"handle_id", "execution_generation"}:
            raise SupervisorProtocolError("HANDLE_SCOPE_INCOMPLETE")
        if not _valid_id(payload["handle_id"]):
            raise SupervisorProtocolError("INVALID_HANDLE_ID")
        if (type(payload["execution_generation"]) is not int or
                payload["execution_generation"] <= 0):
            raise SupervisorProtocolError("INVALID_EXECUTION_GENERATION")
    return value


def encode_frame(value: Mapping[str, Any]) -> bytes:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")
    if not 0 < len(data) <= MAX_MESSAGE:
        raise SupervisorProtocolError("MESSAGE_SIZE_LIMIT")
    return struct.pack("!I", len(data)) + data


def _read_exact(sock: socket.socket, count: int) -> bytes:
    parts = []
    while count:
        fragment = sock.recv(count)
        if not fragment:
            raise SupervisorProtocolError("SUPERVISOR_CONNECTION_CLOSED_OR_PARTIAL")
        parts.append(fragment)
        count -= len(fragment)
    return b"".join(parts)


def receive_frame(sock: socket.socket) -> dict[str, Any]:
    length = struct.unpack("!I", _read_exact(sock, 4))[0]
    if not 0 < length <= MAX_MESSAGE:
        raise SupervisorProtocolError("MESSAGE_SIZE_LIMIT")
    try:
        value = json.loads(_read_exact(sock, length).decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise SupervisorProtocolError("INVALID_JSON") from exc
    if not isinstance(value, dict):
        raise SupervisorProtocolError("INVALID_MESSAGE_OBJECT")
    return value


class SupervisorClient:
    """Unprivileged local transport; checks kernel identity of peer on connect."""

    def __init__(self, socket_path: str, *, timeout: float = 2.0,
                 expected_supervisor_uid: int = 0):
        if not isinstance(socket_path, str) or not socket_path:
            raise ValueError("socket_path required")
        if type(timeout) not in (float, int) or not 0 < timeout <= 10:
            raise ValueError("bounded timeout required")
        if type(expected_supervisor_uid) is not int or expected_supervisor_uid < 0:
            raise ValueError("expected_supervisor_uid must be nonnegative")
        self.socket_path = socket_path
        self.timeout = float(timeout)
        self.expected_supervisor_uid = expected_supervisor_uid

    def call(self, action: str,
             payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        import secrets
        request = {"version": PROTOCOL_VERSION,
                   "request_id": secrets.token_hex(16),
                   "action": action,
                   "payload": {} if payload is None else dict(payload)}
        validate_request(request)
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(self.timeout)
                sock.connect(self.socket_path)
                if os.name != "posix" or not hasattr(socket, "SO_PEERCRED"):
                    raise SupervisorProtocolError("SUPERVISOR_PEERCRED_UNAVAILABLE_HOLD")
                credentials = sock.getsockopt(
                    socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
                _pid, supervisor_uid, _gid = struct.unpack("3i", credentials)
                if supervisor_uid != self.expected_supervisor_uid:
                    raise SupervisorProtocolError("SUPERVISOR_PEER_NOT_TRUSTED_HOLD")
                sock.sendall(encode_frame(request))
                response = receive_frame(sock)
        except (OSError, TimeoutError) as exc:
            raise SupervisorProtocolError("SUPERVISOR_UNAVAILABLE_HOLD") from exc
        if set(response) != {"version", "request_id", "ok", "code", "result"}:
            raise SupervisorProtocolError("MALFORMED_SUPERVISOR_RESPONSE")
        if (type(response["version"]) is not int or
                response["version"] != PROTOCOL_VERSION or
                response["request_id"] != request["request_id"] or
                type(response["ok"]) is not bool or
                not isinstance(response["code"], str) or
                not isinstance(response["result"], dict)):
            raise SupervisorProtocolError("MISMATCHED_SUPERVISOR_RESPONSE")
        return response


@dataclass(frozen=True)
class SupervisedProcessHandle:
    """Future remote process handle, explicitly NOT a subprocess.Popen.

    UNKNOWN, missing supervisor, invalid exit code and failed stop all HOLD.
    No .pid, .kill() or .terminate() on another security domain's processes.
    """
    client: SupervisorClient
    handle_id: str
    execution_generation: int

    def _scope(self) -> dict[str, Any]:
        if (not _valid_id(self.handle_id) or
                type(self.execution_generation) is not int or
                self.execution_generation <= 0):
            raise SupervisorProtocolError("INVALID_HANDLE_SCOPE")
        return {"handle_id": self.handle_id,
                "execution_generation": self.execution_generation}

    def poll(self) -> int | None:
        response = self.client.call("inspect", self._scope())
        if response["ok"] is not True:
            raise SupervisorProtocolError("SUPERVISOR_STATUS_UNVERIFIED_HOLD")
        state = response["result"].get("state")
        if state in ("STARTING", "RUNNING"):
            return None
        if state == "EXITED":
            code = response["result"].get("exit_code")
            if type(code) is int and -255 <= code <= 255:
                return code
        raise SupervisorProtocolError("SUPERVISOR_STATUS_UNKNOWN_HOLD")

    def request_stop(self) -> None:
        response = self.client.call("stop", self._scope())
        if response["ok"] is not True:
            raise SupervisorProtocolError("SUPERVISOR_STOP_UNVERIFIED_HOLD")
        # ACK alone is NOT a verified StopReceipt.

    def read_log(self) -> bytes:
        response = self.client.call("read_log", self._scope())
        if response["ok"] is not True:
            raise SupervisorProtocolError("SUPERVISOR_LOG_UNAVAILABLE_HOLD")
        raise SupervisorProtocolError("LOG_STREAM_NOT_IMPLEMENTED")
