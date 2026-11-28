"""P0-01C-3B-2: disposable Linux systemd privilege-separation experiment.

This tool does NOT implement the production OS supervisor, Node Agent protocol,
StopReceipt, or GPU stop. It runs ONLY with explicit opt-in as root in a
GitHub-hosted Ubuntu 22.04 ephemeral VM. It creates 2 random disposable Linux
users, one random systemd SYSTEM unit and a root-only ephemeral Ed25519 key.
Unprivileged agent/workload escape and key-read attempts MUST fail.

The GitHub runner account has sudo: this test is NOT a production-grade trust
root or proof against a malicious process with sudo. All central task / GPU
state changes occur ONLY in sqlite3 :memory: with a synthetic task.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import pwd
import secrets
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import central_stop_recovery_contract as central
import linux_cgroup_poc as cg


WORKLOAD_CODE = r"""
import json,os,subprocess,sys,time
from pathlib import Path
home=Path(sys.argv[1])
key=Path(sys.argv[2])
group=(Path('/proc/self/cgroup').read_text().strip().split('::',1)[-1])
ancestor=Path('/sys/fs/cgroup') / group.strip('/').rsplit('/',1)[0] / 'cgroup.procs'
escape_denied=False
try:
    with ancestor.open('w') as fd:
        fd.write(str(os.getpid()))
except (PermissionError,OSError):
    escape_denied=True
key_denied=False
try:
    key.read_bytes()
except (PermissionError,OSError):
    key_denied=True
child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(22)'],
                       start_new_session=True)
data={'pid':os.getpid(),'child_pid':child.pid,
      'escaped_denied':escape_denied,'key_denied':key_denied,
      'cgroup':group,'invocation_id':os.environ.get('INVOCATION_ID','')}
temp=home / '.ready.tmp'
temp.write_text(json.dumps(data))
os.replace(temp,home / 'ready.json')
child.wait()
"""

AGENT_CODE = r"""
import json,os,subprocess,sys
from pathlib import Path
unit,key,pid=sys.argv[1],Path(sys.argv[2]),int(sys.argv[3])
key_denied=False
try: key.read_bytes()
except (PermissionError,OSError): key_denied=True
signal_denied=False
try: os.kill(pid,0)
except PermissionError: signal_denied=True
except ProcessLookupError: pass
stop=subprocess.run(['systemctl','--system','--no-ask-password','stop',unit],
                    text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                    timeout=4)
sudo=subprocess.run(['sudo','-n','true'],text=True,
                    stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=4)
print(json.dumps({'key_denied':key_denied,
                  'signal_denied':signal_denied,
                  'unit_stop_denied':stop.returncode!=0,
                  'sudo_denied':sudo.returncode!=0}))
"""


def _only_disposable_host() -> bool:
    if not (os.name == "posix" and os.geteuid() == 0
            and os.environ.get("GITHUB_ACTIONS") == "true"
            and os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted"
            and os.environ.get("SUDO_USER") == "runner"
            and Path("/run/systemd/system").is_dir()
            and Path("/sys/fs/cgroup/cgroup.controllers").is_file()):
        return False
    try:
        release = Path("/etc/os-release").read_text()
    except OSError:
        return False
    return 'ID=ubuntu' in release and 'VERSION_ID="22.04"' in release


def _run(argv: list[str], timeout: float = 8) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True,
                          check=False, timeout=timeout)


def _unit_info(unit: str) -> dict[str, str]:
    proc = _run(["systemctl", "--system", "--no-ask-password", "show", unit,
                 "--property=Id,MainPID,ControlGroup,InvocationID,User,"
                 "KillMode,Delegate,ProtectControlGroups,NoNewPrivileges"], 5)
    if proc.returncode:
        return {}
    values = {}
    for row in proc.stdout.splitlines():
        if "=" in row:
            key, value = row.split("=", 1)
            values[key] = value
    return values


def _loaded_same_unit(current: dict[str, str], initial: dict[str, str]) -> bool:
    return bool(initial and all(current.get(name) == initial.get(name) for name in
                   ("Id", "ControlGroup", "InvocationID", "User")))


def _write_secret(directory: Path) -> tuple[Ed25519PrivateKey, Path]:
    directory.mkdir(mode=0o700)
    os.chmod(directory, 0o700)
    key = Ed25519PrivateKey.generate()
    path = directory / "signer-private.pem"
    data = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption())
    descriptor = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, data)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return key, path


def _payload_signature(payload: dict, signer: Ed25519PrivateKey) -> dict:
    data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return {"payload": payload, "signature": signer.sign(data).hex()}


def _public_verifier(signer: Ed25519PrivateKey):
    pub = signer.public_key()
    def verify(message: dict) -> bool:
        try:
            payload = message["payload"]
            signature = bytes.fromhex(message["signature"])
            blob = json.dumps(payload, sort_keys=True,
                              separators=(",", ":")).encode()
            pub.verify(signature, blob)
            return True
        except (ValueError, KeyError, TypeError, InvalidSignature):
            return False
    return verify


def _load_ready(work: Path, seconds: float = 8) -> dict | None:
    stop = time.monotonic() + seconds
    while time.monotonic() < stop:
        path = work / "ready.json"
        if path.is_file():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                return None
        time.sleep(0.03)
    return None


def _create_held_challenge(db: sqlite3.Connection, *,
                           task: str, generation: int, node: str,
                           unit: str, boot: str, invocation: str,
                           group: str) -> dict:
    now = datetime.now(timezone.utc)
    token = secrets.token_urlsafe(32)
    db.execute("""INSERT INTO tasks(task_id,attempt,status,stage,worker_id,
        lease_token,lease_expires_at,updated_at,resource_wait_reason)
        VALUES (?,?,?,?,?,?,?,?,?)""",
        (task, generation, "RUNNING", central.HOLD, "agent:" + node,
         token, (now-timedelta(seconds=15)).isoformat(),
         now.isoformat(), "REMOTE_AGENT_STOP_UNVERIFIED"))
    db.execute("""INSERT INTO gpu_reservations(task_id,worker_id,lease_token,policy)
                 VALUES (?,?,?,?)""",
               (task, "agent:" + node, token, "exclusive"))
    return central.issue_challenge(
        db, task_id=task, node_id=node, boot_id=boot,
        invocation_id=invocation, unit=unit, cgroup=group,
        now=now, ttl_seconds=120)


def _run_trial() -> tuple[dict, int]:
    out = {
        "scope": "ISOLATED_GITHUB_ROOT_SUPERVISOR_PROBE_ONLY",
        "trusted_production_stop_receipt": False,
        "production_recovery_allowed": False,
        "privilege_boundary_verified": False,
        "test_supervisor_signature_verified": False,
        "test_central_recovery_committed": False,
    }
    if not _only_disposable_host():
        out["outcome"] = "DISPOSABLE_GITHUB_HOST_REQUIRED_HOLD"
        return out, 2
    accounts = []
    unit = "clpoc-" + secrets.token_hex(12) + ".service"
    initial: dict[str, str] = {}
    db = sqlite3.connect(":memory:", isolation_level=None)
    group_fd = None
    observer = None
    with tempfile.TemporaryDirectory(prefix="p001c3b2-") as directory:
        root = Path(directory)
        os.chmod(root, 0o711)  # traverse only; secure child stays root 0700
        signer, keypath = _write_secret(root / "supervisor-secret")
        work = root / "work"
        work.mkdir(mode=0o700)
        try:
            account_prefix = "clp" + secrets.token_hex(3)
            agent_user, workload_user = account_prefix+"a", account_prefix+"w"
            for name in (agent_user, workload_user):
                created = _run(["useradd", "--system", "--no-create-home",
                                "--shell=/usr/sbin/nologin",
                                "--user-group", name], 5)
                if created.returncode:
                    raise RuntimeError("DISPOSABLE_ACCOUNT_CREATION_FAILED")
                accounts.append(name)
            agent_uid = pwd.getpwnam(agent_user).pw_uid
            workload_uid = pwd.getpwnam(workload_user).pw_uid
            if agent_uid == workload_uid or not agent_uid or not workload_uid:
                raise RuntimeError("DISTINCT_UNPRIVILEGED_UIDS_REQUIRED")
            os.chown(work, workload_uid, workload_uid)
            # Root alone creates/stops this system-level unit; never delegates
            # systemd unit ownership to ordinary agent or workload user.
            cmd = [
                "systemd-run", "--system", "--no-ask-password",
                "--unit="+unit,
                "--property=Type=exec",
                "--property=User="+workload_user,
                "--property=KillMode=control-group",
                "--property=Delegate=no",
                "--property=ProtectControlGroups=yes",
                "--property=NoNewPrivileges=yes",
                "--property=RestrictSUIDSGID=yes",
                "--property=Restart=no",
                "--property=RuntimeMaxSec=25s",
                "--property=TimeoutStopSec=3s",
                "/usr/bin/python3", "-c", WORKLOAD_CODE, str(work), str(keypath)
            ]
            started = _run(cmd, 10)
            if started.returncode:
                out["outcome"] = "SYSTEM_UNIT_LAUNCH_REJECTED_HOLD"
                out["reason_type"] = "START_FAILED"
                return out, 3
            ready = _load_ready(work)
            if not isinstance(ready, dict):
                out["outcome"] = "WORKLOAD_NOT_READY_HOLD"
                return out, 3
            initial = _unit_info(unit)
            parent = int(initial.get("MainPID") or 0)
            child = int(ready.get("child_pid") or 0)
            group = str(initial.get("ControlGroup") or "")
            invocation = str(initial.get("InvocationID") or "")
            boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
            membership = (
                initial.get("Id") == unit and
                initial.get("User") == workload_user and
                initial.get("KillMode") == "control-group" and
                initial.get("Delegate") == "no" and
                initial.get("ProtectControlGroups") in ("yes", "true") and
                initial.get("NoNewPrivileges") in ("yes", "true") and
                parent > 0 and child > 0 and
                int(ready.get("pid") or 0) == parent and
                isinstance(group,str) and group.endswith("/"+unit) and
                ready.get("cgroup") == group and
                ready.get("invocation_id") == invocation and
                invocation != "0"*32 and len(invocation) == 32 and
                cg.process_in_cgroup(parent,group) and
                cg.process_in_cgroup(child,group) and
                cg.proc_parent_pid(child) == parent)
            out["systemd_boundary_verified"] = bool(membership)
            if not membership:
                out["outcome"] = "SYSTEMD_BOUNDARY_NOT_VERIFIED_HOLD"
                return out, 3
            ticks = ((parent,cg.proc_start_ticks(parent)),
                     (child,cg.proc_start_ticks(child)))
            agent = _run(["runuser","-u",agent_user,"--","/usr/bin/python3",
                          "-c",AGENT_CODE,unit,str(keypath),str(parent)],12)
            if agent.returncode:
                out["outcome"] = "UNPRIVILEGED_AGENT_PROBE_FAILED_HOLD"
                return out, 3
            checks = json.loads(agent.stdout)
            out["agent_denials"] = checks
            out["workload_escape_denied"] = ready.get("escaped_denied") is True
            out["workload_key_read_denied"] = ready.get("key_denied") is True
            boundary = (
                all(checks.get(k) is True for k in (
                    "key_denied","signal_denied","unit_stop_denied","sudo_denied"))
                and out["workload_escape_denied"]
                and out["workload_key_read_denied"]
                and cg.process_in_cgroup(parent,group)
                and cg.process_in_cgroup(child,group)
                and _loaded_same_unit(_unit_info(unit),initial))
            out["privilege_boundary_verified"] = bool(boundary)
            if not boundary:
                out["outcome"] = "AGENT_OR_WORKLOAD_PRIVILEGE_ESCAPE_HOLD"
                return out, 3
            event_path = Path("/sys/fs/cgroup") / group.lstrip("/") / "cgroup.events"
            group_fd = event_path.open("rb",buffering=0)
            observer = cg.CgroupEventObserver(group_fd.fileno())
            if not observer.start() or not observer.arm_stop():
                out["outcome"] = "BOUND_CGROUP_EVENT_OBSERVER_NOT_READY_HOLD"
                return out, 3
            observer._sample("live_before_stop_request")
            if not any(x.get("populated")==1 and x.get("after_stop_armed") is True
                       for x in observer.evidence()):
                out["outcome"] = "CGROUP_WAS_NOT_LIVE_HOLD"
                return out, 3
            if not _loaded_same_unit(_unit_info(unit),initial):
                out["outcome"] = "UNIT_GENERATION_CHANGED_HOLD"
                return out, 3
            task_id = "poc-task-"+secrets.token_hex(12)
            node = "isolated-supervisor-node"
            central.init_scratch_schema(db)
            challenge = _create_held_challenge(
                db,task=task_id,generation=3,node=node,unit=unit,
                boot=boot,invocation=invocation,group=group)
            stop_ns = time.monotonic_ns()
            stopped = _run(["systemctl","--system","--no-ask-password",
                            "stop",unit],8)
            out["systemd_stop_returncode"] = stopped.returncode
            out["cgroup_empty_verified"] = cg.wait_for(
                lambda: observer.observed_empty, 3)
            timeline = observer.evidence()
            ztimes = [
                e["monotonic_ns"] for e in timeline
                if e.get("after_stop_armed") is True and
                e.get("populated")==0 and
                type(e.get("monotonic_ns")) is int and
                e["monotonic_ns"]>=stop_ns
            ]
            earlier = any(
                e.get("after_stop_armed") is True and
                e.get("populated")==0 and
                type(e.get("monotonic_ns")) is int and
                e["monotonic_ns"]<stop_ns for e in timeline)
            zero_ns = min(ztimes) if ztimes else None
            all_gone = cg.wait_for(
                lambda: all(cg.process_executing_by_identity(pid,tick) is False
                            for pid,tick in ticks),3)
            out["known_processes_stopped"] = bool(all_gone)
            ordered = (stopped.returncode==0 and
                       out["cgroup_empty_verified"] is True and all_gone
                       and zero_ns is not None and not earlier
                       and _loaded_same_unit(initial,initial))
            if not ordered:
                out["outcome"] = "OS_STOP_OR_SEQUENCE_UNVERIFIED_HOLD"
                return out, 3
            body = {
                **challenge,
                "os_cgroup_empty": True,
                "known_processes_stopped": True,
                "stop_command_succeeded": True,
                "stop_requested_ns": stop_ns,
                "empty_observed_ns": zero_ns,
                "kernel_event_digest": hashlib.sha256(json.dumps(
                    timeline,sort_keys=True).encode()).hexdigest(),
                "witness_role": "DISPOSABLE_ROOT_SUPERVISOR_TEST_ONLY",
            }
            # This private key resides in a root-only directory, never in the
            # ordinary Agent/workload process or test central memory DB.
            receipt = _payload_signature(body,signer)
            verifier = _public_verifier(signer)
            out["test_supervisor_signature_verified"] = verifier(receipt)
            if not out["test_supervisor_signature_verified"]:
                out["outcome"] = "ISOLATED_SUPERVISOR_SIGNATURE_FAILED_HOLD"
                return out, 3
            transaction = central.commit_test_recovery(
                db,attestation=receipt,now=datetime.now(timezone.utc),
                independent_witness_verifier=verifier)
            task = db.execute(
                "SELECT status,attempt,worker_id FROM tasks WHERE task_id=?",
                (task_id,)).fetchone()
            held_gpu = db.execute(
                "SELECT COUNT(*) FROM gpu_reservations WHERE task_id=?",
                (task_id,)).fetchone()[0]
            try:
                central.commit_test_recovery(
                    db,attestation=receipt,now=datetime.now(timezone.utc),
                    independent_witness_verifier=verifier)
                replay_denied = False
            except central.RecoveryRejected:
                replay_denied = True
            out["challenge_replay_denied"] = replay_denied
            simulated = (transaction.get("scratch_only") is True and
                         task==("QUEUED",3,None) and held_gpu==0 and replay_denied)
            out["test_central_recovery_committed"] = simulated
            out["outcome"] = (
                "SEPARATE_UID_SUPERVISOR_ISOLATED_PASS_NOT_PRODUCTION_ATTESTATION"
                if simulated else "ISOLATED_SUPERVISOR_CAS_FAILED_HOLD")
            return out, 0 if simulated else 3
        except (OSError,ValueError,KeyError,RuntimeError,sqlite3.Error,
                subprocess.TimeoutExpired,central.RecoveryRejected) as error:
            out["outcome"]="UNVERIFIED_OR_SETUP_ERROR_HOLD"
            out["error_type"]=type(error).__name__
            return out,3
        finally:
            if observer is not None:
                observer.close()
            if group_fd is not None:
                group_fd.close()
            # Never stop a unit selected by a client; only own random unit.
            try:
                if initial and _loaded_same_unit(_unit_info(unit),initial):
                    _run(["systemctl","--system","--no-ask-password",
                          "stop",unit],8)
            except (OSError,subprocess.TimeoutExpired):
                pass
            for account in reversed(accounts):
                try:
                    _run(["userdel",account],5)
                except (OSError,subprocess.TimeoutExpired):
                    pass
            db.close()


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run",action="store_true")
    parser.add_argument("--github-ephemeral-only",action="store_true")
    args=parser.parse_args()
    if not (args.run and args.github_ephemeral_only):
        print(json.dumps({"outcome":"INERT_OPT_IN_REQUIRED",
                          "production_recovery_allowed":False}))
        return 2
    result,code=_run_trial()
    print(json.dumps(result,indent=2,sort_keys=True))
    return code


if __name__=="__main__":
    raise SystemExit(main())
