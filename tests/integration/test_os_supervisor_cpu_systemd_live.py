"""Real Ubuntu systemd system-service lifecycle, isolated ephemeral CI ONLY.

Must be invoked as root on the dedicated GitHub Ubuntu runner. Does not touch
production and does not authorize a Node Agent, actual model, or GPU task.
"""
from __future__ import annotations

import os
from pathlib import Path
import secrets
import subprocess
import time

from platform_core.os_supervisor_cpu_systemd import FixedCpuSystemd


def test_real_fixed_cpu_systemd_service_start_inspect_log_and_stop():
    # This test must fail (not silently skip) if the requested actual systemd
    # infrastructure is missing. Unit is generated uniquely for this CI job.
    assert os.geteuid() == 0, "real CPU systemd test needs isolated CI root"
    assert Path("/run/systemd/system").is_dir(), "system systemd manager absent"
    name = "changlian-os-" + secrets.token_hex(16) + ".service"
    backend = FixedCpuSystemd()
    launched = False
    try:
        initial = backend.launch(name)
        launched = True
        assert initial["active_state"] == "active"
        assert initial["main_pid"] > 1
        assert initial["control_group"] == "/system.slice/" + name
        assert initial["invocation_id"] != ""
        # Recreating backend mimics Supervisor service restart. No second
        # unit is launched; the OS InvocationID is the same.
        resumed = FixedCpuSystemd().inspect(name, initial["invocation_id"])
        assert resumed["invocation_id"] == initial["invocation_id"]
        # Bounded actual journald read; start log can be slightly delayed.
        log = backend.read_log(name, initial["invocation_id"])
        assert isinstance(log, bytes) and len(log) <= 8192

        result = backend.request_stop(name, initial["invocation_id"])
        assert result["stop_requested"] is True
        assert result["state"] == "UNKNOWN"
        assert result["trusted_stop_receipt_available"] is False
        # No clean STOP proof is manufactured from systemctl success.
        active = subprocess.run(
            ["/usr/bin/systemctl", "--system", "is-active", "--quiet", "--", name],
            capture_output=True, timeout=6, check=False,
        )
        assert active.returncode != 0, "test unit unexpectedly still active"
    finally:
        # Cleanup is confined to the one random CI unit. The test never kills
        # arbitrary PIDs, cgroups, namespaces, or any device processes.
        if launched:
            subprocess.run(
                ["/usr/bin/systemctl", "--system", "stop", "--", name],
                capture_output=True, timeout=8, check=False,
            )



def test_real_cpu_supervisor_journal_one_shot_start_and_stop(tmp_path):
    """Real central-format grant -> SQLite CAS -> true systemd, one time only."""
    import hashlib
    import time
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from platform_core.os_supervisor_authorization import PURPOSE, _claims_payload
    from platform_core.os_supervisor_journal import ExecutionJournal
    from platform_core.os_supervisor_service import SupervisorService

    assert os.geteuid() == 0
    assert Path("/run/systemd/system").is_dir()
    key = Ed25519PrivateKey.generate()
    journal = ExecutionJournal(
        tmp_path / "journal.sqlite3", test_only_unprivileged=True)
    scope = {
        "task_id": "conv_real_sysd123", "task_attempt": 5,
        "node_id": "ci-agent1", "worker_id": "agent:ci-agent1",
        "execution_lease_sha256": hashlib.sha256(b"ci-original-lease").hexdigest(),
        "gpu_uuid": "CPU_ONLY", "boot_id": journal.boot_id,
        "runner_profile": "fixed-cpu-v1",
    }
    nonce = journal.issue_challenge(scope)
    now = int(time.time())
    claims = {**scope, "purpose": PURPOSE, "challenge": nonce,
              "issued_at": now, "expires_at": now + 15}
    envelope = {
        "claims": claims,
        "signature": key.sign(_claims_payload(claims)).hex(),
    }
    registered = journal.register_intent(
        envelope, trusted_public_key=key.public_key())
    handle = registered["handle_id"]
    os_unit = "changlian-os-" + handle + ".service"
    service = SupervisorService(
        tmp_path / "control.sock", allowed_uid=10102, allowed_gid=10102,
        authorization_journal=journal, trusted_public_key=key.public_key(),
        cpu_trial_backend=FixedCpuSystemd())
    entry = {"version": 1, "request_id": "systemdrequest123",
             "action": "start",
             "payload": {"handle_id": handle, "execution_generation": 5,
                         "envelope": envelope}}
    try:
        start = service.dispatch(entry, peer_uid=10102)
        assert start["ok"] is True, start
        assert start["result"]["state"] == "RUNNING"
        assert service.dispatch(entry, peer_uid=10102)["ok"] is False
        assert journal.cpu_identity(handle, 5)["invocation_id"]
        query = {"version": 1, "request_id": "statusrequest123",
                 "action": "inspect",
                 "payload": {"handle_id": handle, "execution_generation": 5}}
        assert service.dispatch(query, peer_uid=10102)["result"]["state"] == "RUNNING"
        restarted = SupervisorService(
            tmp_path / "restart.sock", allowed_uid=10102, allowed_gid=10102,
            authorization_journal=ExecutionJournal(
                journal.path, test_only_unprivileged=True),
            trusted_public_key=key.public_key(),
            cpu_trial_backend=FixedCpuSystemd())
        assert restarted.dispatch(query, peer_uid=10102)["result"]["state"] == "RUNNING"
        stop = restarted.dispatch(
            {**query, "action": "stop"}, peer_uid=10102)
        assert stop["ok"] is False
        assert stop["result"]["state"] == "UNKNOWN"
        assert stop["code"].endswith("HOLD")
        assert journal.inspect(handle, 5)["state"] == "UNKNOWN"
        assert service.dispatch(entry, peer_uid=10102)["ok"] is False
        active = subprocess.run(
            ["/usr/bin/systemctl", "--system", "is-active", "--quiet", "--", os_unit],
            capture_output=True, timeout=6, check=False,
        )
        assert active.returncode != 0
    finally:
        subprocess.run(
            ["/usr/bin/systemctl", "--system", "stop", "--", os_unit],
            capture_output=True, timeout=8, check=False)
