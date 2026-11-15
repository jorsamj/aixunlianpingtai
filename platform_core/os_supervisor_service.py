"""Independent Linux Supervisor phase-1 Unix Socket server.

REAL kernel SO_PEERCRED authentication and bounded transport, but NO process
launch/stop/attestation. Production rollout is NOT authorized. No Agent,
Trainer, Converter or Deployment runner imports this module today.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import socket
import stat
import struct
import threading
from typing import Any

from .os_supervisor_protocol import (
    PROTOCOL_VERSION, SupervisorProtocolError, encode_frame,
    receive_frame, validate_request,
)


class SupervisorService:
    """OS-owned socket with peer UID check; privileged actions fail closed."""

    def __init__(self, socket_path: Path, *, allowed_uid: int,
                 allowed_gid: int, timeout: float = 2.0):
        if not isinstance(socket_path, Path) or not socket_path.name.endswith(".sock"):
            raise ValueError("socket path must end with .sock")
        if type(allowed_uid) is not int or allowed_uid <= 0:
            raise ValueError("non-root agent UID required")
        if type(allowed_gid) is not int or allowed_gid < 0:
            raise ValueError("agent group GID required")
        if not 0 < timeout <= 10:
            raise ValueError("bounded socket timeout required")
        self.path = socket_path
        self.allowed_uid = allowed_uid
        self.allowed_gid = allowed_gid
        self.timeout = timeout
        self._listener: socket.socket | None = None
        self._bound_identity: tuple[int, int] | None = None
        self._stop = threading.Event()

    def dispatch(self, request: object, *, peer_uid: int) -> dict[str, Any]:
        request_id = request.get("request_id") if isinstance(request, dict) else None
        if type(peer_uid) is not int or peer_uid != self.allowed_uid:
            return self._reply(request_id, "PEER_UID_DENIED", ok=False)
        try:
            request = validate_request(request)
        except SupervisorProtocolError as exc:
            return self._reply(request_id, str(exc), ok=False)
        action = request["action"]
        if action == "health":
            return self._reply(request_id, "PHASE1_PROTOCOL_ONLY", ok=True,
                               result={
                "healthy": True, "launch_available": False,
                "stop_available": False,
                "trusted_stop_receipt_available": False,
                "central_recovery_allowed": False,
            })
        if action == "start":
            return self._reply(request_id, "PROTECTED_LAUNCH_NOT_IMPLEMENTED_HOLD",
                               ok=False)
        if action == "stop":
            return self._reply(request_id, "PROTECTED_STOP_NOT_IMPLEMENTED_HOLD",
                               ok=False)
        if action == "inspect":
            return self._reply(request_id, "OS_EXECUTION_NOT_REGISTERED_HOLD",
                               ok=False, result={"state": "UNKNOWN"})
        return self._reply(request_id, "LOG_STREAM_NOT_IMPLEMENTED_HOLD",
                           ok=False)

    @staticmethod
    def _reply(request_id: object, code: str, *, ok: bool,
               result: dict | None = None) -> dict:
        return {"version": PROTOCOL_VERSION, "request_id": request_id,
                "ok": ok, "code": code,
                "result": {} if result is None else result}

    def bind(self, *, test_only_unprivileged: bool = False) -> None:
        """Default requires root, fixed /run path, no symlink or socket replace.

        The test-only flag is never accepted by the CLI, and cannot enable
        privileged process operations, which are absent in phase 1.
        """
        if (os.name != "posix" or platform.system() != "Linux" or
                not hasattr(socket, "SO_PEERCRED")):
            raise SupervisorProtocolError("LINUX_PEERCRED_REQUIRED")
        if not test_only_unprivileged:
            if os.geteuid() != 0:
                raise SupervisorProtocolError("ROOT_OWNED_SERVICE_REQUIRED")
            if self.path != Path("/run/changlian-os-supervisor/control.sock"):
                raise SupervisorProtocolError("UNAPPROVED_SYSTEM_SOCKET_PATH")
        parent = self.path.parent
        if parent.is_symlink():
            raise SupervisorProtocolError("SYMLINKED_SOCKET_DIRECTORY_DENIED")
        if not parent.exists():
            parent.mkdir(mode=0o700, parents=False)
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid():
            raise SupervisorProtocolError("UNOWNED_SOCKET_DIRECTORY_DENIED")
        if self.path.exists() or self.path.is_symlink():
            raise SupervisorProtocolError("SOCKET_PATH_ALREADY_PRESENT_HOLD")
        if not test_only_unprivileged:
            os.chown(parent, 0, self.allowed_gid)
            os.chmod(parent, 0o710)
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            listener.bind(str(self.path))
            if not test_only_unprivileged:
                os.chown(self.path, 0, self.allowed_gid)
                os.chmod(self.path, 0o660)
            else:
                os.chmod(self.path, 0o600)
            listener.listen(16)
            listener.settimeout(0.3)
            info = self.path.lstat()
            self._bound_identity = (info.st_dev, info.st_ino)
            self._listener = listener
        except BaseException:
            listener.close()
            # Only our newly bound path can be cleaned up after bind.
            if self.path.is_socket():
                self.path.unlink()
            raise

    def serve(self, *, test_only_unprivileged: bool = False) -> None:
        self.bind(test_only_unprivileged=test_only_unprivileged)
        try:
            while not self._stop.is_set():
                try:
                    connection, _ = self._listener.accept()
                except socket.timeout:
                    continue
                except OSError:
                    if self._stop.is_set():
                        break
                    raise
                with connection:
                    connection.settimeout(self.timeout)
                    try:
                        credentials = connection.getsockopt(
                            socket.SOL_SOCKET, socket.SO_PEERCRED,
                            struct.calcsize("3i"))
                        _pid, uid, _gid = struct.unpack("3i", credentials)
                        request = receive_frame(connection)
                        reply = self.dispatch(request, peer_uid=uid)
                        connection.sendall(encode_frame(reply))
                    except (OSError, TimeoutError, SupervisorProtocolError):
                        # A malformed or unauthorized request cannot mutate state.
                        pass
        finally:
            self.close()

    def close(self) -> None:
        self._stop.set()
        if self._listener is not None:
            self._listener.close()
            self._listener = None
        # Do not unlink any replacement socket installed by another service.
        if self._bound_identity is not None:
            try:
                current = self.path.lstat()
                if (stat.S_ISSOCK(current.st_mode) and
                        (current.st_dev, current.st_ino) == self._bound_identity):
                    self.path.unlink()
            except FileNotFoundError:
                pass
            self._bound_identity = None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--socket", type=Path)
    parser.add_argument("--agent-uid", type=int)
    parser.add_argument("--agent-gid", type=int)
    args = parser.parse_args()
    if not args.serve:
        print(json.dumps({"outcome": "INERT_OPT_IN_REQUIRED",
                          "launch_available": False}))
        return 2
    if args.socket is None or args.agent_uid is None or args.agent_gid is None:
        print(json.dumps({"outcome": "CONFIG_MISSING_HOLD"}))
        return 2
    try:
        service = SupervisorService(args.socket, allowed_uid=args.agent_uid,
                                    allowed_gid=args.agent_gid)
        service.serve()
    except (OSError, ValueError, SupervisorProtocolError) as exc:
        print(json.dumps({"outcome": "SUPERVISOR_NOT_STARTED_HOLD",
                          "error_type": type(exc).__name__}))
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
