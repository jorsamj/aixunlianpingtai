"""Stage-2 isolated CPU systemd-system-service backend, NOT a business runner.

A root-owned Supervisor may run ONLY a baked-in, bounded, non-GPU test worker.
Never accepts Agent commands, env, cwd, binary path, unit, or systemd options.
This module does not authorize central task ownership or issue StopReceipts.
"""
from __future__ import annotations

import os
import platform
import re
import subprocess
from typing import Any, Callable, Mapping

from .os_supervisor_authorization import GrantRejected

_UNIT = re.compile(r"changlian-os-[0-9a-f]{32}\.service\Z")
_INVOCATION = re.compile(r"[0-9a-f]{32}\Z")
# No child processes, external I/O, GPU, or uncontrolled work. Hard-coded code
# is *not* provided by an Agent, model converter, or task payload.
_WORKER = (
    "import time\n"
    "print('changlian-fixed-cpu-trial-start', flush=True)\n"
    "time.sleep(25)\n"
    "print('changlian-fixed-cpu-trial-done', flush=True)\n"
)
_PROPERTIES = (
    "Type=exec", "DynamicUser=yes", "NoNewPrivileges=yes",
    "PrivateDevices=yes", "DevicePolicy=closed",
    "KillMode=control-group", "SendSIGKILL=yes",
    "ProtectSystem=strict", "ProtectHome=yes",
    "ProtectControlGroups=yes", "PrivateTmp=yes",
    "CapabilityBoundingSet=", "AmbientCapabilities=",
    "RuntimeMaxSec=40s", "TimeoutStopSec=4s",
    "MemoryMax=256M", "TasksMax=24", "CPUQuota=50%",
    "UMask=0077",
)
_SHOW = (
    "Id", "LoadState", "Transient", "ActiveState", "SubState",
    "InvocationID", "ControlGroup", "MainPID",
    "PrivateDevices", "DevicePolicy", "KillMode", "DynamicUser",
    "NoNewPrivileges", "ExecMainCode", "ExecMainStatus", "Result",
)
_ALLOWED = {"active", "activating", "deactivating", "inactive", "failed"}


def _unit(value: object) -> str:
    if not isinstance(value, str) or not _UNIT.fullmatch(value):
        raise GrantRejected("CPU_SYSTEMD_UNIT_INVALID_HOLD")
    return value


class FixedCpuSystemd:
    """Invokes systemd-run/systemctl only; no subprocess.Popen or shell."""

    def __init__(self, *, test_only_runner: Callable[..., Any] | None = None):
        if test_only_runner is None:
            if (platform.system() != "Linux" or not hasattr(os, "geteuid")
                    or os.geteuid() != 0
                    or not os.path.isdir("/run/systemd/system")):
                raise GrantRejected("CPU_SYSTEMD_ROOT_MANAGER_REQUIRED_HOLD")
        self._runner = test_only_runner or subprocess.run

    def _run(self, argv: list[str], *, timeout: int = 7) -> str:
        try:
            outcome = self._runner(
                argv, shell=False, capture_output=True,
                text=True, timeout=timeout, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise GrantRejected("CPU_SYSTEMD_OS_UNAVAILABLE_HOLD") from exc
        if outcome.returncode != 0:
            raise GrantRejected("CPU_SYSTEMD_OPERATION_UNVERIFIED_HOLD")
        # All arguments are fixed or locally derived from a journal handle.
        return str(outcome.stdout)[:16384]

    def launch(self, unit: str) -> dict[str, Any]:
        """Start a fixed system service once; journal CAS must happen FIRST."""
        name = _unit(unit)
        self._run([
            "/usr/bin/systemd-run", "--system", "--no-ask-password",
            "--unit=" + name,
            *("--property=" + item for item in _PROPERTIES),
            "--", "/usr/bin/python3", "-I", "-u", "-c", _WORKER,
        ])
        return self.snapshot(name, require_running=True)

    def snapshot(self, unit: str, *, require_running: bool = False) -> dict[str, Any]:
        name = _unit(unit)
        stdout = self._run([
            "/usr/bin/systemctl", "--system", "--no-pager", "show",
            *[part for field in _SHOW for part in ("-p", field)],
            "--", name,
        ])
        data: dict[str, str] = {}
        for line in stdout.splitlines():
            k, sep, v = line.partition("=")
            if sep and k in _SHOW and k not in data:
                data[k] = v
        if (data.get("Id") != name or data.get("LoadState") != "loaded"
                or data.get("Transient") != "yes"
                or data.get("PrivateDevices") != "yes"
                or data.get("DevicePolicy") != "closed"
                or data.get("KillMode") != "control-group"
                or data.get("DynamicUser") != "yes"
                or data.get("NoNewPrivileges") != "yes"
                or data.get("ActiveState") not in _ALLOWED
                or not _INVOCATION.fullmatch(data.get("InvocationID", ""))):
            raise GrantRejected("CPU_SYSTEMD_PROTECTION_OR_IDENTITY_UNVERIFIED_HOLD")
        is_running = data["ActiveState"] == "active" and data.get("SubState") == "running"
        if require_running and not is_running:
            raise GrantRejected("CPU_SYSTEMD_NOT_RUNNING_HOLD")
        if is_running and (
                data.get("ControlGroup") != f"/system.slice/{name}"
                or not data.get("MainPID", "").isdigit()
                or int(data["MainPID"]) <= 1):
            raise GrantRejected("CPU_SYSTEMD_CGROUP_OR_PID_UNVERIFIED_HOLD")
        return {
            "unit_name": name,
            "invocation_id": data["InvocationID"],
            "control_group": data.get("ControlGroup", ""),
            "main_pid": int(data.get("MainPID") or 0),
            "active_state": data["ActiveState"],
            "sub_state": data.get("SubState", ""),
            "exec_main_code": data.get("ExecMainCode", ""),
            "exec_main_status": data.get("ExecMainStatus", ""),
            "result": data.get("Result", ""),
        }

    def inspect(self, unit: str, expected_invocation: str) -> dict[str, Any]:
        snapshot = self.snapshot(unit)
        if snapshot["invocation_id"] != expected_invocation:
            raise GrantRejected("CPU_SYSTEMD_INVOCATION_REPLACED_HOLD")
        return snapshot

    def request_stop(self, unit: str, expected_invocation: str) -> dict[str, Any]:
        """Actually stop the *same* systemd cgroup, never issue StopReceipt."""
        snapshot = self.inspect(unit, expected_invocation)
        if snapshot["active_state"] != "active":
            raise GrantRejected("CPU_SYSTEMD_STOP_STATE_UNVERIFIED_HOLD")
        self._run([
            "/usr/bin/systemctl", "--system", "--no-pager",
            "stop", "--", _unit(unit),
        ])
        # A transient unit may be garbage-collected immediately after stop.
        # No longer being queryable is NOT proof of a trusted clean exit.
        try:
            after = self.inspect(unit, expected_invocation)
            active_state = after["active_state"]
        except GrantRejected:
            active_state = "UNVERIFIED"
        return {
            "state": "UNKNOWN",
            "stop_requested": True,
            "trusted_stop_receipt_available": False,
            "active_state": active_state,
        }

    def read_log(self, unit: str, expected_invocation: str) -> bytes:
        """Bounded diagnostics only; never a stable global log offset contract."""
        self.inspect(unit, expected_invocation)
        value = self._run([
            "/usr/bin/journalctl", "--system", "--no-pager",
            "--output=cat", "--lines=64", "--unit", _unit(unit),
        ])
        return value.encode("utf-8", errors="replace")[:8192]
