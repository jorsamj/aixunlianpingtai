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
