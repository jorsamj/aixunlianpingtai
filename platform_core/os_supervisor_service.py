"""Independent Linux Supervisor phase-1 Unix Socket server.

REAL kernel SO_PEERCRED authentication and bounded transport. Optional
CPU-only durable intent registration has NO process launch/stop/attestation.
Production rollout is NOT authorized; no business runner imports this module.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import platform
import socket
import sqlite3
import stat
import struct
import threading
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .os_supervisor_authorization import GrantRejected
from .os_supervisor_journal import ExecutionJournal
from .os_supervisor_cpu_systemd import FixedCpuSystemd
from .os_supervisor_trust import load_supervisor_public_key
from .os_supervisor_protocol import (
    PROTOCOL_VERSION, SupervisorProtocolError, encode_frame,
    receive_frame, validate_request,
)


class SupervisorService:
    """OS-owned socket with peer UID check; privileged actions fail closed."""

    def __init__(self, socket_path: Path, *, allowed_uid: int,
                 allowed_gid: int, timeout: float = 2.0,
                 authorization_journal: ExecutionJournal | None = None,
                 trusted_public_key: Ed25519PublicKey | None = None,
                 cpu_trial_backend: FixedCpuSystemd | None = None):
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
        if (authorization_journal is None) != (trusted_public_key is None):
            raise ValueError("Supervisor journal and pinned public key required together")
        if (trusted_public_key is not None
                and not isinstance(trusted_public_key, Ed25519PublicKey)):
            raise ValueError("pinned Ed25519 public key required")
        if cpu_trial_backend is not None and (
                authorization_journal is None or trusted_public_key is None
                or not isinstance(cpu_trial_backend, FixedCpuSystemd)):
            raise ValueError("CPU trial requires journal and fixed systemd backend")
        self.authorization_journal = authorization_journal
        self.trusted_public_key = trusted_public_key
        self.cpu_trial_backend = cpu_trial_backend
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
                "cpu_intent_registration_available": (
                    self.authorization_journal is not None),
                "cpu_trial_launch_available": self.cpu_trial_backend is not None,
            })
        if action in ("challenge", "authorize_intent"):
            if self.authorization_journal is None:
                return self._reply(request_id, "CPU_INTENT_REGISTRATION_DISABLED_HOLD",
                                   ok=False)
            try:
                if action == "challenge":
                    nonce = self.authorization_journal.issue_challenge(
                        request["payload"])
                    return self._reply(request_id, "CPU_CHALLENGE_ISSUED", ok=True,
                                       result={"challenge": nonce,
                                               "boot_id": self.authorization_journal.boot_id})
                intent = self.authorization_journal.register_intent(
                    request["payload"]["envelope"],
                    trusted_public_key=self.trusted_public_key)
                return self._reply(request_id, "CPU_INTENT_RECORDED_NO_LAUNCH",
                                   ok=True, result=intent)
            except GrantRejected as exc:
                return self._reply(request_id, str(exc), ok=False)
            except (OSError, ValueError, sqlite3.Error):
                return self._reply(request_id, "JOURNAL_UNAVAILABLE_HOLD", ok=False)
        if action == "start":
            if self.cpu_trial_backend is None or not request["payload"]:
                return self._reply(request_id, "PROTECTED_LAUNCH_NOT_IMPLEMENTED_HOLD",
                                   ok=False)
            payload = request["payload"]
            claimed = None
            try:
                # Durable one-shot CAS happens BEFORE the first OS spawn.
                claimed = self.authorization_journal.claim_cpu_launch(
                    payload["handle_id"], payload["execution_generation"],
                    payload["envelope"], trusted_public_key=self.trusted_public_key)
                evidence = self.cpu_trial_backend.launch(claimed["unit_name"])
                self.authorization_journal.record_cpu_identity(
                    claimed["handle_id"], claimed["task_attempt"],
                    invocation_id=evidence["invocation_id"],
                    control_group=evidence["control_group"],
                    main_pid=evidence["main_pid"])
                return self._reply(
                    request_id, "FIXED_CPU_TRIAL_RUNNING", ok=True,
                    result={"handle_id": claimed["handle_id"],
                            "task_attempt": claimed["task_attempt"],
                            "state": "RUNNING",
                            "trusted_stop_receipt_available": False})
            except (GrantRejected, OSError, ValueError, sqlite3.Error):
                # systemd-run might have started even if an ACK/evidence write
                # was lost. Never undo STARTING into a launchable PREPARED.
                if claimed is not None:
                    try:
                        self.authorization_journal.mark_cpu_unknown(
                            claimed["handle_id"], claimed["task_attempt"])
                    except (OSError, ValueError, sqlite3.Error):
                        pass
                return self._reply(request_id, "FIXED_CPU_START_UNVERIFIED_HOLD",
                                   ok=False, result={"state": "UNKNOWN"})
        if action == "stop":
            if self.cpu_trial_backend is None:
                return self._reply(request_id, "PROTECTED_STOP_NOT_IMPLEMENTED_HOLD",
                                   ok=False)
            payload = request["payload"]
            try:
                identity = self.authorization_journal.cpu_identity(
                    payload["handle_id"], payload["execution_generation"])
                stopped = self.cpu_trial_backend.request_stop(
                    identity["unit_name"], identity["invocation_id"])
                self.authorization_journal.mark_cpu_unknown(
                    payload["handle_id"], payload["execution_generation"])
                return self._reply(request_id, "CPU_STOP_RECEIPT_UNVERIFIED_HOLD",
                                   ok=False,
                                   result={"state": "UNKNOWN", **stopped})
            except (GrantRejected, OSError, ValueError, sqlite3.Error):
                return self._reply(request_id, "CPU_STOP_UNVERIFIED_HOLD",
                                   ok=False, result={"state": "UNKNOWN"})
        if action == "inspect":
            payload = request["payload"]
            if self.cpu_trial_backend is not None:
                try:
                    try:
                        identity = self.authorization_journal.cpu_identity(
                            payload["handle_id"], payload["execution_generation"])
                    except GrantRejected:
                        # Crash after the one-shot journal CAS and systemd-run,
                        # but before InvocationID was durably saved: inspect the
                        # journal's exact unit. Never re-run systemd-run.
                        starting = self.authorization_journal.starting_cpu_unit(
                            payload["handle_id"], payload["execution_generation"])
                        observed = self.cpu_trial_backend.snapshot(
                            starting["unit_name"], require_running=True)
                        if (str(observed["main_pid"]) != observed["exec_main_pid"]
                                or observed["control_group"] !=
                                "/system.slice/" + starting["unit_name"]):
                            raise GrantRejected("CPU_REATTACH_OS_IDENTITY_UNVERIFIED_HOLD")
                        self.authorization_journal.record_cpu_identity(
                            starting["handle_id"], starting["task_attempt"],
                            invocation_id=observed["invocation_id"],
                            control_group=observed["control_group"],
                            main_pid=observed["main_pid"])
                        identity = self.authorization_journal.cpu_identity(
                            payload["handle_id"], payload["execution_generation"])
                    evidence = self.cpu_trial_backend.inspect(
                        identity["unit_name"], identity["invocation_id"])
                    if (evidence["active_state"] == "active"
                            and evidence["sub_state"] == "running"
                            and evidence["control_group"] == identity["control_group"]
                            and evidence["main_pid"] == identity["main_pid"]):
                        return self._reply(
                            request_id, "CPU_UNIT_RUNNING_VERIFIED", ok=True,
                            result={"state": "RUNNING",
                                    "handle_id": identity["handle_id"],
                                    "task_attempt": identity["task_attempt"]})
                    terminal = self.cpu_trial_backend.verified_natural_exit(
                        identity["unit_name"], identity["invocation_id"],
                        original_control_group=identity["control_group"],
                        original_main_pid=identity["main_pid"])
                    saved = self.authorization_journal.record_cpu_exit(
                        identity["handle_id"], identity["task_attempt"],
                        invocation_id=terminal["invocation_id"],
                        main_pid=terminal["main_pid"],
                        exit_code=terminal["exit_code"],
                        unit_result=terminal["unit_result"],
                        cgroup_exit_type_verified=terminal["cgroup_exit_type_verified"])
                    return self._reply(
                        request_id, "CPU_TRIAL_EXIT_RECORDED_NO_STOP_RECEIPT",
                        ok=True, result=saved)
                except (GrantRejected, OSError, ValueError, sqlite3.Error):
                    pass
            if self.authorization_journal is not None:
                try:
                    registered = self.authorization_journal.inspect(
                        payload["handle_id"], payload["execution_generation"])
                    if (registered["state"] == "EXITED"
                            and self.cpu_trial_backend is not None):
                        return self._reply(
                            request_id, "CPU_TRIAL_EXIT_RECORDED_NO_STOP_RECEIPT",
                            ok=True, result=registered)
                    return self._reply(
                        request_id, "OS_EXECUTION_NOT_VERIFIED_HOLD", ok=False,
                        result=registered)
                except GrantRejected:
                    pass
                except (OSError, ValueError, sqlite3.Error):
                    return self._reply(
                        request_id, "JOURNAL_UNAVAILABLE_HOLD", ok=False,
                        result={"state": "UNKNOWN"})
            return self._reply(request_id, "OS_EXECUTION_NOT_REGISTERED_HOLD",
                               ok=False, result={"state": "UNKNOWN"})
        if action == "read_log" and self.cpu_trial_backend is not None:
            payload = request["payload"]
            try:
                identity = self.authorization_journal.cpu_identity(
                    payload["handle_id"], payload["execution_generation"])
                page = self.cpu_trial_backend.read_log_page(
                    identity["unit_name"], identity["invocation_id"],
                    cursor=payload.get("cursor"))
                return self._reply(
                    request_id, "CPU_LOG_INVOCATION_CURSOR_PAGE", ok=True,
                    result={"encoding": "base64",
                            "data_base64": base64.b64encode(page["data"]).decode("ascii"),
                            "cursor": page["cursor"],
                            "offset_contract_available": True})
            except (GrantRejected, OSError, ValueError, sqlite3.Error):
                return self._reply(request_id, "CPU_LOG_UNVERIFIED_HOLD", ok=False)
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
    parser.add_argument("--enable-cpu-intent", action="store_true")
    parser.add_argument("--enable-cpu-trial-launch", action="store_true")
    args = parser.parse_args()
    if not args.serve:
        print(json.dumps({"outcome": "INERT_OPT_IN_REQUIRED",
                          "launch_available": False}))
        return 2
    if args.socket is None or args.agent_uid is None or args.agent_gid is None:
        print(json.dumps({"outcome": "CONFIG_MISSING_HOLD"}))
        return 2
    if args.enable_cpu_trial_launch and not args.enable_cpu_intent:
        print(json.dumps({"outcome": "CPU_TRIAL_REQUIRES_TRUSTED_INTENT_HOLD"}))
        return 2
    try:
        # Only a root-owned fixed location is permitted in the opted-in
        # deployment. There is no CLI/Agent-provided key/journal path.
        journal = ExecutionJournal() if args.enable_cpu_intent else None
        public_key = (load_supervisor_public_key()
                      if args.enable_cpu_intent else None)
        backend = FixedCpuSystemd() if args.enable_cpu_trial_launch else None
        service = SupervisorService(
            args.socket, allowed_uid=args.agent_uid, allowed_gid=args.agent_gid,
            authorization_journal=journal, trusted_public_key=public_key,
            cpu_trial_backend=backend)
        service.serve()
    except (OSError, ValueError, SupervisorProtocolError) as exc:
        print(json.dumps({"outcome": "SUPERVISOR_NOT_STARTED_HOLD",
                          "error_type": type(exc).__name__}))
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
