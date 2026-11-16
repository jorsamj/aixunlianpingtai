"""Actual disposable root systemd stop, never on A800 or 4070.

Exercises the 2C-03A original OS identity/cgroup stop observer on a fixed CPU
worker. A synthetic journal adaptor is used here ONLY; this test is NOT a
production PT cancellation or a central StopReceipt.
"""
from __future__ import annotations

import os
import subprocess
from types import SimpleNamespace
import uuid

import pytest

from platform_core.os_supervisor_cpu_systemd import FixedCpuSystemd
from platform_core.os_supervisor_pt_stop_observation import IsolatedPtStopObserver


class _SyntheticJournal:
    def __init__(self, handle: str, first: dict):
        self.journal = SimpleNamespace(
            boot_id=open("/proc/sys/kernel/random/boot_id", encoding="ascii").read().strip()
        )
        self.identity = {
            "handle_id": handle, "boot_id": self.journal.boot_id,
            "unit_name": first["unit_name"],
            "invocation_id": first["invocation_id"],
            "control_group": first["control_group"],
            "main_pid": first["main_pid"],
        }

    def verified_pt_identity(self, handle_id, task_attempt):
        assert handle_id == self.identity["handle_id"]
        assert task_attempt == 3
        return dict(self.identity)


def test_real_isolated_systemd_control_group_stop_requires_live_original_fd():
    assert os.environ.get("GITHUB_ACTIONS") == "true"
    assert os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted"
    assert os.geteuid() == 0
    backend = FixedCpuSystemd()
    handle = uuid.uuid4().hex
    unit = "changlian-os-" + handle + ".service"
    first = None
    try:
        first = backend.launch(unit)
        assert first["active_state"] == "active"
        assert first["sub_state"] == "running"
        observer = IsolatedPtStopObserver(
            journal=_SyntheticJournal(handle, first),
            backend=backend, isolated_ci_only=True,
        )
        evidence = observer.request_and_observe(handle, 3)
        assert evidence["original_invocation_id"] == first["invocation_id"]
        assert evidence["state"] == "LOCAL_EMPTY_OBSERVED_NO_RECEIPT", evidence
        assert evidence["original_cgroup_became_empty"] is True
        assert evidence["trusted_stop_receipt_available"] is False
        assert evidence["central_recovery_allowed"] is False
        print("PT_STOP_LOCAL_ORIGINAL_CGROUP_PROOF", evidence, flush=True)
    finally:
        # Fixed, random isolated unit only; do not stop another invocation.
        if first is not None:
            try:
                check = backend.inspect(unit, first["invocation_id"])
                if check["active_state"] in ("active", "activating", "deactivating"):
                    subprocess.run(
                        ["/usr/bin/systemctl", "--system", "--no-pager", "stop", "--", unit],
                        timeout=12, check=False,
                    )
            except Exception:
                pass  # A GC'd transient unit is not stop proof.
