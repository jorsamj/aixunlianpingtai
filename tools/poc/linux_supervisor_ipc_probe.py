"""P0-01C-3B-3: isolated SO_PEERCRED + unbound CPU escape counterexample.

This disposable-VM test does NOT implement a real stop API or StopReceipt.
Admission over the Unix socket NEVER invokes systemctl, kills a process,
signs a stop proof or releases any task. An unauthorized CPU process OUTSIDE
the original unit surviving its stop is an EXPECTED NEGATIVE finding.

Opt in only on GitHub-hosted Ubuntu 22.04 via explicit root/sudo wrapper.
Never execute against production A800/4070 or a self-hosted runner.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import pwd
import secrets
import signal
import socket
import sqlite3
import struct
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any

import linux_cgroup_poc as cg
import linux_supervisor_privilege_probe as prior


CLIENT = r"""
import json,socket,sys
address=sys.argv[1]
request=json.loads(sys.argv[2])
sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
try:
    sock.settimeout(4)
    sock.connect(address)
    sock.sendall(json.dumps(request).encode())
    sock.shutdown(socket.SHUT_WR)
    response=sock.recv(4096)
    print(json.dumps({'connected':True,'reply':json.loads(response)}))
except (OSError,ValueError) as exc:
    print(json.dumps({'connected':False,'error_type':type(exc).__name__}))
finally:
    sock.close()
"""

UNBOUND_CPU = r"""
import os,sys,time
from pathlib import Path
path=Path(sys.argv[1])
tmp=path.parent / '.cpu-pid.tmp'
tmp.write_text(str(os.getpid()))
os.replace(tmp,path)
time.sleep(23)
"""


class AdmissionGate:
    """Pure test-only request validator. This grants NO stop authorization."""

    def __init__(self, agent_uid: int, registered: dict, issued_ns: int,
                 ttl_ns: int = 5_000_000_000):
        self.agent_uid = agent_uid
        self.registered = dict(registered)
        self.issued_ns = issued_ns
        self.ttl_ns = ttl_ns
        self.consumed = False

    def check(self, payload: object, peer_uid: int, now_ns: int) -> dict:
        if type(peer_uid) is not int or peer_uid != self.agent_uid:
            return {"ok": False, "reason": "PEER_UID_NOT_AUTHORIZED"}
        if (type(now_ns) is not int or now_ns < self.issued_ns or
                now_ns >= self.issued_ns + self.ttl_ns):
            return {"ok": False, "reason": "CHALLENGE_EXPIRED_OR_CLOCK_INVALID"}
        if not isinstance(payload, dict) or (
                set(payload) != set(self.registered) | {"action"}):
            return {"ok": False, "reason": "REQUEST_SHAPE_INVALID"}
        if payload.get("action") != "request_stop_admission":
            return {"ok": False, "reason": "METHOD_NOT_ALLOWED"}
        if (type(payload.get("execution_generation")) is not int or
                payload["execution_generation"] <= 0):
            return {"ok": False, "reason": "GENERATION_TYPE_INVALID"}
        if any(type(payload.get(k)) is not type(v) or payload[k] != v
               for k, v in self.registered.items()):
            return {"ok": False, "reason": "REGISTERED_BOUNDARY_MISMATCH"}
        if self.consumed:
            return {"ok": False, "reason": "CHALLENGE_ALREADY_CONSUMED"}
        self.consumed = True
        return {"ok": True, "reason": "ADMISSION_CHECK_ONLY_NO_STOP_PROOF"}


class RootAdmissionSocket:
    """Root-owned single-thread test server; uses kernel SO_PEERCRED."""

    def __init__(self, pathname: Path, agent_gid: int, gate: AdmissionGate):
        self.pathname = pathname
        self.agent_gid = agent_gid
        self.gate = gate
        self.closed = threading.Event()
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.error: str | None = None

    def _serve(self):
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
                server.bind(str(self.pathname))
                os.chown(self.pathname, 0, self.agent_gid)
                os.chmod(self.pathname, 0o660)
                server.listen(8)
                server.settimeout(0.25)
                self.ready.set()
                while not self.closed.is_set():
                    try:
                        accepted, _ = server.accept()
                    except socket.timeout:
                        continue
                    with accepted:
                        accepted.settimeout(3)
                        try:
                            credentials = accepted.getsockopt(
                                socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
                            _pid, peer_uid, _gid = struct.unpack("3i", credentials)
                            request_bytes = accepted.recv(4097)
                            if not request_bytes or len(request_bytes) > 4096:
                                reply = {"ok": False, "reason": "OVERSIZED_OR_EMPTY"}
                            else:
                                try:
                                    request = json.loads(request_bytes.decode("utf-8"))
                                except (UnicodeError, ValueError):
                                    request = None
                                reply = self.gate.check(
                                    request, peer_uid, time.monotonic_ns())
                            accepted.sendall(json.dumps(reply).encode("utf-8"))
                        except (OSError, ValueError, TimeoutError):
                            pass
        except (OSError, RuntimeError) as exc:
            self.error = type(exc).__name__
            self.ready.set()

    def start(self) -> bool:
        self.thread.start()
        return self.ready.wait(3) and self.error is None

    def close(self):
        self.closed.set()
        if self.thread.is_alive():
            self.thread.join(timeout=4)
        try:
            self.pathname.unlink(missing_ok=True)
        except OSError:
            pass


def _client(account: str, path: Path, request: dict) -> dict:
    proc = prior._run(
        ["runuser", "-u", account, "--", "/usr/bin/python3", "-c",
         CLIENT, str(path), json.dumps(request, sort_keys=True)], 7)
    if proc.returncode:
        return {"connected": False, "error_type": "CLIENT_EXIT_NONZERO"}
    try:
        return json.loads(proc.stdout)
    except ValueError:
        return {"connected": False, "error_type": "CLIENT_OUTPUT_INVALID"}


def _run_trial() -> tuple[dict, int]:
    result = {
        "scope": "GITHUB_DISPOSABLE_SEPARATE_UID_SOCKET_AND_UNBOUND_CPU",
        "real_stop_proof_implemented": False,
        "production_recovery_allowed": False,
        "supervisor_socket_admission_verified": False,
        "unbound_cpu_spawn_possible": False,
        "original_cgroup_only_is_not_global_stop_proof": True,
    }
    if not prior._only_disposable_host():
        result["outcome"] = "GITHUB_EPHEMERAL_UBUNTU_ONLY_HOLD"
        return result, 2
    unit = "clpoc-" + secrets.token_hex(12) + ".service"
    created: list[str] = []
    active_unit = {}
    unbound_pid = None
    unbound_ticks = None
    unbound_wrapper = None
    observer = None
    fd = None
    server = None
    with tempfile.TemporaryDirectory(prefix="p001c3b3-") as d:
        base = Path(d)
        os.chmod(base, 0o711)
        agentdir = base / "agent"
        agentdir.mkdir(mode=0o700)
        private = base / "supervisor-only"
        private.mkdir(mode=0o700)
        private_file = private / "signer-key-not-exported"
        private_file.write_bytes(secrets.token_bytes(32))
        os.chmod(private_file, 0o600)
        socket_path = base / "supervisor-admission.sock"
        try:
            prefix = "clp" + secrets.token_hex(3)
            agent_name, workload_name = prefix+"a", prefix+"w"
            for name in (agent_name, workload_name):
                p = prior._run(["useradd", "--system", "--no-create-home",
                                "--shell=/usr/sbin/nologin", "--user-group", name], 6)
                if p.returncode:
                    raise RuntimeError("ISOLATED_USER_CREATION_FAILED")
                created.append(name)
            agent_uid = pwd.getpwnam(agent_name).pw_uid
            workload_uid = pwd.getpwnam(workload_name).pw_uid
            agent_gid = pwd.getpwnam(agent_name).pw_gid
            if agent_uid == workload_uid or min(agent_uid, workload_uid) <= 0:
                raise RuntimeError("DISTINCT_NONROOT_UIDS_REQUIRED")
            os.chown(agentdir, agent_uid, agent_gid)
            boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
            # Random unit belongs only to the isolated test; the unbound agent
            # process explicitly must NOT be inside this unit's cgroup.
            started = prior._run([
                "systemd-run", "--system", "--no-ask-password",
                "--unit="+unit, "--property=Type=exec",
                "--property=User="+workload_name,
                "--property=KillMode=control-group",
                "--property=Delegate=no",
                "--property=ProtectControlGroups=yes",
                "--property=NoNewPrivileges=yes",
                "--property=Restart=no",
                "--property=RuntimeMaxSec=25s",
                "--property=TimeoutStopSec=3s",
                "/usr/bin/python3", "-c", "import time;time.sleep(23)"
            ], 9)
            if started.returncode:
                result["outcome"] = "ISOLATED_UNIT_START_FAILED_HOLD"
                return result, 3
            if not cg.wait_for(lambda: int(prior._unit_info(unit).get("MainPID") or 0) > 0, 5):
                result["outcome"] = "ISOLATED_UNIT_MISSING_MAINPID_HOLD"
                return result, 3
            active_unit = prior._unit_info(unit)
            group = str(active_unit.get("ControlGroup") or "")
            incarnation = active_unit.get("InvocationID") or ""
            main_pid = int(active_unit.get("MainPID") or 0)
            if (active_unit.get("Id") != unit or
                    active_unit.get("User") != workload_name or
                    not group.endswith("/"+unit) or
                    len(incarnation) != 32 or
                    incarnation == "0"*32 or
                    not cg.process_in_cgroup(main_pid, group)):
                result["outcome"] = "UNIT_IDENTITY_MISMATCH_HOLD"
                return result, 3
            main_ticks = cg.proc_start_ticks(main_pid)
            # This is a negative finding: unprivileged agent can still spawn
            # CPU work outside the supervised unit. We must NEVER interpret
            # original-unit cgroup emptiness as proof of global node idleness.
            pid_path = agentdir / "unbound-pid"
            unbound_wrapper = subprocess.Popen(
                ["runuser", "-u", agent_name, "--", "/usr/bin/python3",
                 "-c", UNBOUND_CPU, str(pid_path)], start_new_session=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if not cg.wait_for(lambda: pid_path.is_file(), 5):
                result["outcome"] = "UNBOUND_CPU_SPAWN_NOT_OBSERVED_HOLD"
                return result, 3
            unbound_pid = int(pid_path.read_text())
            unbound_ticks = cg.proc_start_ticks(unbound_pid)
            unbound_group = cg.unified_path(
                Path(f"/proc/{unbound_pid}/cgroup").read_text())
            if (cg.process_in_cgroup(unbound_pid, group) or
                    unbound_group == group or unbound_group is None or
                    cg.process_executing_by_identity(unbound_pid, unbound_ticks) is not True):
                result["outcome"] = "UNBOUND_CPU_LINEAGE_NOT_VERIFIED_HOLD"
                return result, 3
            result["unbound_cpu_spawn_possible"] = True
            intended = {
                "task_id": "poc-task-"+secrets.token_hex(12),
                "execution_generation": 3,
                "unit": unit,
                "boot_id": boot,
                "invocation_id": incarnation,
                "challenge_id": secrets.token_hex(16),
                "nonce": secrets.token_hex(24),
            }
            gate = AdmissionGate(agent_uid, intended, time.monotonic_ns(),
                                 ttl_ns=15_000_000_000)
            server = RootAdmissionSocket(socket_path, agent_gid, gate)
            if not server.start():
                result["outcome"] = "SUPERVISOR_SOCKET_NOT_READY_HOLD"
                return result, 3
            request = {"action": "request_stop_admission", **intended}
            # Socket file DAC rejects an unregistered workload user.
            work_denied = _client(workload_name, socket_path, request)
            result["workload_socket_permission_denied"] = (
                work_denied.get("connected") is False and
                work_denied.get("error_type") == "PermissionError")
            # Even when socket DAC is weakened, SO_PEERCRED must deny workload.
            os.chmod(socket_path, 0o666)
            wrong_peer = _client(workload_name, socket_path, request)
            os.chmod(socket_path, 0o660)
            result["unauthorized_peer_credential_rejected"] = (
                wrong_peer.get("connected") is True and
                wrong_peer.get("reply", {}).get("reason") == "PEER_UID_NOT_AUTHORIZED")
            # Agent can REQUEST admission only for the registered unit,
            # generation, task, and nonce. No command execution is exposed.
            wrong_unit = _client(agent_name, socket_path,
                                 {**request, "unit": "clpoc-"+secrets.token_hex(12)+".service"})
            wrong_generation = _client(agent_name, socket_path,
                                      {**request, "execution_generation": 4})
            wrong_nonce = _client(agent_name, socket_path,
                                  {**request, "nonce": "replayed"})
            result["wrong_scope_denied"] = all(
                item.get("connected") is True and
                item.get("reply", {}).get("reason") == "REGISTERED_BOUNDARY_MISMATCH"
                for item in (wrong_unit, wrong_generation, wrong_nonce))
            admitted = _client(agent_name, socket_path, request)
            replay = _client(agent_name, socket_path, request)
            result["authorized_request_admitted_once"] = (
                admitted.get("connected") is True and
                admitted.get("reply") == {
                    "ok": True, "reason": "ADMISSION_CHECK_ONLY_NO_STOP_PROOF"})
            result["replay_rejected"] = (
                replay.get("connected") is True and
                replay.get("reply", {}).get("reason") == "CHALLENGE_ALREADY_CONSUMED")
            result["agent_secret_read_denied"] = (
                prior._run(["runuser", "-u", agent_name, "--", "test",
                            "-r", str(private_file)], 4).returncode != 0)
            result["workload_secret_read_denied"] = (
                prior._run(["runuser", "-u", workload_name, "--", "test",
                            "-r", str(private_file)], 4).returncode != 0)
            if not all(result.get(k) is True for k in (
                    "workload_socket_permission_denied",
                    "unauthorized_peer_credential_rejected",
                    "wrong_scope_denied", "authorized_request_admitted_once",
                    "replay_rejected", "agent_secret_read_denied",
                    "workload_secret_read_denied")):
                result["outcome"] = "IPC_AUTHENTICATION_OR_DAC_HOLD"
                return result, 3
            result["supervisor_socket_admission_verified"] = True
            if not prior._loaded_same_unit(prior._unit_info(unit), active_unit):
                result["outcome"] = "UNIT_REPLACED_BEFORE_STOP_HOLD"
                return result, 3
            fd = (Path("/sys/fs/cgroup") / group.lstrip("/") /
                  "cgroup.events").open("rb", buffering=0)
            observer = cg.CgroupEventObserver(fd.fileno())
            if not observer.start() or not observer.arm_stop():
                result["outcome"] = "UNIT_EVENT_WATCH_NOT_READY_HOLD"
                return result, 3
            observer._sample("live_before_system_stop")
            stop_ns = time.monotonic_ns()
            stopped = prior._run(
                ["systemctl", "--system", "--no-ask-password", "stop", unit], 8)
            timeline = observer.evidence()
            zero_after = any(e.get("after_stop_armed") is True and
                             e.get("populated") == 0 and
                             type(e.get("monotonic_ns")) is int and
                             e["monotonic_ns"] >= stop_ns for e in timeline)
            zero_before = any(e.get("after_stop_armed") is True and
                              e.get("populated") == 0 and
                              type(e.get("monotonic_ns")) is int and
                              e["monotonic_ns"] < stop_ns for e in timeline)
            original_stopped = cg.wait_for(
                lambda: cg.process_executing_by_identity(
                    main_pid, main_ticks) is False, 3)
            unbound_survived = (cg.process_executing_by_identity(
                unbound_pid, unbound_ticks) is True)
            result["controlled_unit_stopped"] = (
                stopped.returncode == 0 and observer.observed_empty and
                zero_after and not zero_before and original_stopped)
            result["unbound_cpu_survived_controlled_stop"] = unbound_survived
            safe_negative_result = (
                result["controlled_unit_stopped"] is True and
                result["unbound_cpu_survived_controlled_stop"] is True and
                result["supervisor_socket_admission_verified"] is True)
            result["outcome"] = (
                "EXPECTED_ESCAPE_COUNTEREXAMPLE_AND_IPC_CONTRACT_PASS_NOT_STOP_PROOF"
                if safe_negative_result else
                "UNBOUND_WORKLOAD_OR_UNIT_STOP_NOT_VERIFIED_HOLD")
            return result, 0 if safe_negative_result else 3
        except (OSError, RuntimeError, ValueError, KeyError,
                subprocess.TimeoutExpired) as exc:
            result["outcome"] = "PROBE_EXCEPTION_HOLD"
            result["error_type"] = type(exc).__name__
            return result, 3
        finally:
            if server is not None:
                server.close()
            if observer is not None:
                observer.close()
            if fd is not None:
                fd.close()
            if unbound_pid is not None and unbound_ticks is not None:
                try:
                    if cg.process_executing_by_identity(
                            unbound_pid, unbound_ticks) is True:
                        os.kill(unbound_pid, signal.SIGTERM)
                except (OSError, ValueError):
                    pass
            if unbound_wrapper is not None:
                try:
                    unbound_wrapper.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    unbound_wrapper.kill()
                    unbound_wrapper.wait(timeout=2)
            try:
                if active_unit and prior._loaded_same_unit(
                        prior._unit_info(unit), active_unit):
                    prior._run(["systemctl", "--system",
                                "--no-ask-password", "stop", unit], 8)
            except (OSError, subprocess.TimeoutExpired):
                pass
            for name in reversed(created):
                try:
                    prior._run(["userdel", name], 5)
                except (OSError, subprocess.TimeoutExpired):
                    pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--github-ephemeral-only", action="store_true")
    opts = parser.parse_args()
    if not (opts.run and opts.github_ephemeral_only):
        print(json.dumps({"outcome": "INERT_OPT_IN_REQUIRED",
                          "production_recovery_allowed": False}))
        return 2
    result, code = _run_trial()
    print(json.dumps(result, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
