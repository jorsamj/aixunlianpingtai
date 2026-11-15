"""Stage-2B original central grant -> durable one-shot journal CAS -> CPU OS.

The fake systemd validates the state machine without starting host services;
the separate Ubuntu integration tests the same path with real systemd.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import time

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pytest import raises

from platform_core.os_supervisor_authorization import PURPOSE, GrantRejected, _claims_payload
from platform_core.os_supervisor_cpu_systemd import FixedCpuSystemd
from platform_core.os_supervisor_journal import ExecutionJournal
from platform_core.os_supervisor_protocol import SupervisedProcessHandle, validate_request
from platform_core.os_supervisor_service import SupervisorService

BOOT = "65ad39e5-7bfa-4b46-9b1e-7f1f0d0d6c8a"
TASK = "conv_stage2_test11"
NODE = "agentnode1"
LEASE_DIGEST = hashlib.sha256(b"real-task-execution-token").hexdigest()


class FakeRunner:
    def __init__(self, *, launch_fails=False):
        self.spawn_count = 0
        self.launch_fails = launch_fails
        self.active = True
        self.invocation = "e" * 32
        self.finished = False
        self.exit_type = "cgroup"
        self.exec_main_pid = "54321"
        self.control_group_override = None

    def __call__(self, command, **kwargs):
        from types import SimpleNamespace
        if command[0].endswith("systemd-run"):
            self.spawn_count += 1
            return SimpleNamespace(
                returncode=1 if self.launch_fails else 0,
                stdout="", stderr="systemd unavailable" if self.launch_fails else "")
        if command[0].endswith("journalctl"):
            name = command[command.index("--unit") + 1]
            record = {
                "__CURSOR": "s=demo;i=1",
                "_SYSTEMD_INVOCATION_ID": self.invocation,
                "_SYSTEMD_UNIT": name,
                "MESSAGE": "fixed-cpu-log",
            }
            if any(arg.startswith("--after-cursor=") for arg in command):
                return SimpleNamespace(returncode=0, stdout="")
            return SimpleNamespace(
                returncode=0, stdout=json.dumps(record) + "\n")
        if command[3] == "stop":
            self.active = False
            return SimpleNamespace(returncode=0, stdout="")
        name = command[-1]
        fields = {
            "Id": name,
            "LoadState": ("loaded" if self.spawn_count else "not-found"),
            "Transient": "yes",
            "ActiveState": "active" if self.active else "inactive",
            "SubState": ("exited" if self.finished else
                         ("running" if self.active else "dead")),
            "InvocationID": self.invocation,
            "ControlGroup": (self.control_group_override
                             if self.control_group_override is not None else
                             ("/system.slice/" + name if self.active else "")),
            "MainPID": "0" if self.finished else ("54321" if self.active else "0"),
            "ExecMainPID": self.exec_main_pid,
            "ExitType": self.exit_type, "RemainAfterExit": "yes",
            "Restart": "no", "NRestarts": "0",
            "PrivateDevices": "yes", "DevicePolicy": "closed",
            "KillMode": "control-group", "DynamicUser": "yes",
            "NoNewPrivileges": "yes", "ExecMainCode": "1",
            "ExecMainStatus": "0", "Result": "success",
        }
        return SimpleNamespace(returncode=0, stdout="\n".join(
            f"{k}={v}" for k, v in fields.items()))


def request(action, payload=None):
    return {"version": 1, "request_id": "stage2request1234", "action": action,
            "payload": {} if payload is None else payload}


def make_registered(tmp_path, *, launch_fails=False):
    key = Ed25519PrivateKey.generate()
    journal = ExecutionJournal(
        tmp_path / "journal.sqlite3", test_only_unprivileged=True,
        boot_id_for_tests=BOOT)
    scope = {
        "task_id": TASK, "task_attempt": 7,
        "node_id": NODE, "worker_id": "agent:" + NODE,
        "execution_lease_sha256": LEASE_DIGEST,
        "gpu_uuid": "CPU_ONLY", "boot_id": BOOT,
        "runner_profile": "fixed-cpu-v1",
    }
    nonce = journal.issue_challenge(scope)
    now = int(time.time())
    claims = {**scope, "challenge": nonce, "purpose": PURPOSE,
              "issued_at": now, "expires_at": now + 15}
    signed = {"claims": claims,
              "signature": key.sign(_claims_payload(claims)).hex()}
    first = journal.register_intent(signed, trusted_public_key=key.public_key())
    fake = FakeRunner(launch_fails=launch_fails)
    backend = FixedCpuSystemd(test_only_runner=fake)
    supervisor = SupervisorService(
        tmp_path / "control.sock", allowed_uid=10101, allowed_gid=10101,
        authorization_journal=journal, trusted_public_key=key.public_key(),
        cpu_trial_backend=backend)
    begin = request("start", {"handle_id": first["handle_id"],
                             "execution_generation": 7, "envelope": signed})
    scope_request = {"handle_id": first["handle_id"], "execution_generation": 7}
    return journal, backend, fake, supervisor, begin, scope_request, key


def test_once_cas_and_restart_preserve_one_systemd_invocation(tmp_path):
    journal, backend, fake, service, begin, scope, key = make_registered(tmp_path)
    first = service.dispatch(begin, peer_uid=10101)
    assert first["ok"] is True
    assert first["result"]["state"] == "RUNNING"
    assert fake.spawn_count == 1
    replay = service.dispatch(begin, peer_uid=10101)
    assert replay["ok"] is False and replay["code"].endswith("HOLD")
    assert fake.spawn_count == 1
    j2 = ExecutionJournal(journal.path, test_only_unprivileged=True,
                          boot_id_for_tests=BOOT)
    recovered = SupervisorService(
        Path("/tmp/other.sock"), allowed_uid=10101, allowed_gid=10101,
        authorization_journal=j2, trusted_public_key=key.public_key(),
        cpu_trial_backend=backend)
    observed = recovered.dispatch(request("inspect", scope), peer_uid=10101)
    assert observed["ok"] and observed["result"]["state"] == "RUNNING"
    read_log = recovered.dispatch(request("read_log", scope), peer_uid=10101)
    assert read_log["ok"] is True
    assert read_log["result"]["offset_contract_available"] is True
    assert read_log["result"]["cursor"] == "s=demo;i=1"
    next_log = recovered.dispatch(
        request("read_log", {**scope, "cursor": "s=demo;i=1"}),
        peer_uid=10101)
    assert next_log["ok"] is True
    assert next_log["result"]["cursor"] == "s=demo;i=1"
    assert next_log["result"]["data_base64"] == ""
    stopped = recovered.dispatch(request("stop", scope), peer_uid=10101)
    assert stopped["ok"] is False and stopped["code"].endswith("HOLD")
    assert stopped["result"]["state"] == "UNKNOWN"
    assert fake.spawn_count == 1
    with sqlite3.connect(journal.path) as db:
        assert db.execute(
            "SELECT state,event_seq FROM execution_intents").fetchone() == (
                "UNKNOWN", 4)


def test_launch_failure_and_response_loss_never_trigger_second_spawn(tmp_path):
    journal, backend, fake, service, begin, scope, key = make_registered(
        tmp_path, launch_fails=True)
    response = service.dispatch(begin, peer_uid=10101)
    assert response["ok"] is False
    assert response["result"]["state"] == "UNKNOWN"
    assert fake.spawn_count == 1
    assert service.dispatch(begin, peer_uid=10101)["ok"] is False
    assert fake.spawn_count == 1
    with sqlite3.connect(journal.path) as db:
        assert db.execute("SELECT state FROM execution_intents").fetchone()[0] == "UNKNOWN"


def test_wrong_grant_never_claims_cpu_systemd_launch(tmp_path):
    journal, backend, fake, service, begin, scope, key = make_registered(tmp_path)
    forged = {**begin, "payload": {
        **begin["payload"],
        "envelope": {
            **begin["payload"]["envelope"],
            "signature": "f" * 128,
        },
    }}
    reply = service.dispatch(forged, peer_uid=10101)
    assert reply["ok"] is False and fake.spawn_count == 0
    assert service.dispatch(begin, peer_uid=10102)["code"] == "PEER_UID_DENIED"
    assert fake.spawn_count == 0
    assert service.dispatch(request("start"), peer_uid=10101)["ok"] is False
    assert fake.spawn_count == 0
    ok = service.dispatch(begin, peer_uid=10101)
    assert ok["ok"] is True


def test_start_contract_rejects_agent_executable_or_shell():
    payload = {"handle_id": "a" * 32, "execution_generation": 1,
               "envelope": {"claims": {}, "signature": "f" * 128},
               "command": "/bin/sh"}
    with raises(Exception):
        validate_request(request("start", payload))


def test_cpu_natural_exit_is_durable_and_never_relaunches(tmp_path):
    journal, backend, fake, service, begin, scope, key = make_registered(tmp_path)
    assert service.dispatch(begin, peer_uid=10101)["ok"] is True
    fake.finished = True
    observed = service.dispatch(request("inspect", scope), peer_uid=10101)
    assert observed["ok"] is True
    assert observed["result"]["state"] == "EXITED"
    assert observed["result"]["exit_code"] == 0
    assert observed["result"]["trusted_stop_receipt_available"] is False
    assert journal.inspect(scope["handle_id"], 7)["state"] == "EXITED"
    with sqlite3.connect(journal.path) as db:
        assert db.execute("SELECT state,event_seq FROM execution_intents").fetchone() == (
            "EXITED", 4)
        assert db.execute("SELECT exit_code,unit_result FROM cpu_terminal_evidence").fetchone() == (
            0, "success")
    restarted = SupervisorService(
        Path("/tmp/cpu-terminal.sock"), allowed_uid=10101, allowed_gid=10101,
        authorization_journal=ExecutionJournal(
            journal.path, test_only_unprivileged=True, boot_id_for_tests=BOOT),
        trusted_public_key=key.public_key(), cpu_trial_backend=backend)
    assert restarted.dispatch(request("inspect", scope), peer_uid=10101)["result"]["state"] == "EXITED"
    assert restarted.dispatch(begin, peer_uid=10101)["ok"] is False
    assert restarted.dispatch(request("stop", scope), peer_uid=10101)["ok"] is False
    assert fake.spawn_count == 1


def test_cpu_exit_incomplete_or_replaced_evidence_keeps_hold(tmp_path):
    for change in ("mainpid", "exit_type", "result", "still_running"):
        working = tmp_path / change
        working.mkdir()
        journal, backend, fake, service, begin, scope, key = make_registered(working)
        assert service.dispatch(begin, peer_uid=10101)["ok"] is True
        fake.finished = True
        if change == "mainpid":
            fake.exec_main_pid = "23456"
        elif change == "exit_type":
            fake.exit_type = "main"
        elif change == "result":
            fake.invocation = "d" * 32
        elif change == "still_running":
            fake.finished = False
        reply = service.dispatch(request("inspect", scope), peer_uid=10101)
        if change == "still_running":
            assert reply["result"]["state"] == "RUNNING"
        else:
            assert reply["ok"] is False and reply["result"]["state"] == "UNKNOWN"
        with sqlite3.connect(journal.path) as db:
            assert db.execute("SELECT count(*) FROM cpu_terminal_evidence").fetchone()[0] == 0


def test_cpu_exit_cannot_promote_unknown_or_mismatched_boot(tmp_path):
    journal, backend, fake, service, begin, scope, key = make_registered(tmp_path)
    assert service.dispatch(begin, peer_uid=10101)["ok"] is True
    journal.mark_cpu_unknown(scope["handle_id"], 7)
    with raises(GrantRejected, match="UNVERIFIED_STATE_HOLD"):
        journal.record_cpu_exit(
            scope["handle_id"], 7, invocation_id=fake.invocation,
            main_pid=54321, exit_code=0, unit_result="success",
            cgroup_exit_type_verified=True)
    assert journal.inspect(scope["handle_id"], 7)["state"] == "UNKNOWN"
    journal_on_new_boot = ExecutionJournal(
        journal.path, test_only_unprivileged=True, boot_id_for_tests="new-boot")
    assert journal_on_new_boot.inspect(scope["handle_id"], 7)["state"] == "UNKNOWN"


def test_cpu_starting_crash_after_real_spawn_reattaches_once(tmp_path):
    """No second OS launch after lost identity commit and Supervisor restart."""
    journal, backend, fake, service, begin, scope, key = make_registered(tmp_path)
    claim = journal.claim_cpu_launch(
        scope["handle_id"], 7, begin["payload"]["envelope"],
        trusted_public_key=key.public_key())
    os_identity = backend.launch(claim["unit_name"])
    assert fake.spawn_count == 1
    assert os_identity["main_pid"] == 54321
    with sqlite3.connect(journal.path) as db:
        assert db.execute("SELECT state FROM execution_intents").fetchone()[0] == "STARTING"
        assert db.execute("SELECT count(*) FROM cpu_unit_identities").fetchone()[0] == 0

    journal_again = ExecutionJournal(
        journal.path, test_only_unprivileged=True, boot_id_for_tests=BOOT)
    restarted = SupervisorService(
        Path("/tmp/startup-recovery.sock"), allowed_uid=10101, allowed_gid=10101,
        authorization_journal=journal_again, trusted_public_key=key.public_key(),
        cpu_trial_backend=backend)
    result = restarted.dispatch(request("inspect", scope), peer_uid=10101)
    assert result["ok"] and result["result"]["state"] == "RUNNING"
    saved = journal.cpu_identity(scope["handle_id"], 7)
    assert saved["invocation_id"] == os_identity["invocation_id"]
    assert saved["main_pid"] == os_identity["main_pid"]
    # Two concurrent observers can record only the same identity, once.
    journal.record_cpu_identity(
        scope["handle_id"], 7, invocation_id=os_identity["invocation_id"],
        control_group=os_identity["control_group"], main_pid=os_identity["main_pid"])
    with raises(GrantRejected, match="CONCURRENT_MISMATCH"):
        journal.record_cpu_identity(
            scope["handle_id"], 7, invocation_id="d" * 32,
            control_group=os_identity["control_group"], main_pid=os_identity["main_pid"])
    assert restarted.dispatch(request("inspect", scope), peer_uid=10101)["ok"]
    assert restarted.dispatch(begin, peer_uid=10101)["ok"] is False
    assert fake.spawn_count == 1
    with sqlite3.connect(journal.path) as db:
        assert db.execute(
            "SELECT state,event_seq FROM execution_intents").fetchone() == ("RUNNING", 3)


def test_starting_reattach_requires_real_os_unit_original_boot_and_identity(tmp_path):
    for mode in ("missing", "wrong_boot", "wrong_pid", "wrong_group",
                 "wrong_protection", "unknown"):
        folder = tmp_path / mode
        folder.mkdir()
        journal, backend, fake, service, begin, scope, key = make_registered(folder)
        journal.claim_cpu_launch(
            scope["handle_id"], 7, begin["payload"]["envelope"],
            trusted_public_key=key.public_key())
        if mode != "missing":
            backend.launch("changlian-os-" + scope["handle_id"] + ".service")
        if mode == "wrong_boot":
            journal = ExecutionJournal(
                journal.path, test_only_unprivileged=True,
                boot_id_for_tests="different-linux-boot")
        elif mode == "wrong_pid":
            fake.exec_main_pid = "45678"
        elif mode == "wrong_group":
            fake.control_group_override = "/system.slice/not-the-original.service"
        elif mode == "wrong_protection":
            fake.exit_type = "main"
        elif mode == "unknown":
            journal.mark_cpu_unknown(scope["handle_id"], 7)
        retry = SupervisorService(
            Path("/tmp/startup-denied.sock"), allowed_uid=10101, allowed_gid=10101,
            authorization_journal=journal, trusted_public_key=key.public_key(),
            cpu_trial_backend=backend)
        reply = retry.dispatch(request("inspect", scope), peer_uid=10101)
        assert reply["ok"] is False and reply["result"]["state"] == "UNKNOWN", mode
        assert retry.dispatch(begin, peer_uid=10101)["ok"] is False, mode
        with sqlite3.connect(journal.path) as db:
            assert db.execute(
                "SELECT count(*) FROM cpu_unit_identities").fetchone()[0] == 0, mode
