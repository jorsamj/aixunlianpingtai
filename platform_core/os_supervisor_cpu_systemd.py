"""Stage-2 isolated CPU systemd-system-service backend, NOT a business runner.

A root-owned Supervisor may run ONLY a baked-in, bounded, non-GPU test worker.
Never accepts Agent commands, env, cwd, binary path, unit, or systemd options.
This module does not authorize central task ownership or issue StopReceipts.
"""
from __future__ import annotations

import json
import os
import platform
import re
import subprocess
from typing import Any, Callable, Mapping

from .os_supervisor_authorization import GrantRejected

_UNIT = re.compile(r"changlian-os-[0-9a-f]{32}\.service\Z")
_INVOCATION = re.compile(r"[0-9a-f]{32}\Z")
_CURSOR = re.compile(r"^s=[A-Za-z0-9=;:._+-]{1,510}$")
# No child processes, external I/O, GPU, or uncontrolled work. Hard-coded code
# is *not* provided by an Agent, model converter, or task payload.
_WORKER = (
    "import time\n"
    "print('changlian-fixed-cpu-trial-start', flush=True)\n"
    "time.sleep(25)\n"
    "print('changlian-fixed-cpu-trial-done', flush=True)\n"
)
_PROPERTIES = (
    "Type=exec", "ExitType=cgroup", "RemainAfterExit=yes", "Restart=no",
    "DynamicUser=yes", "NoNewPrivileges=yes",
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
    "InvocationID", "ControlGroup", "MainPID", "ExecMainPID",
    "ExitType", "RemainAfterExit", "Restart", "NRestarts",
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
                or data.get("ExitType") != "cgroup"
                or data.get("RemainAfterExit") != "yes"
                or data.get("Restart") != "no"
                or data.get("NRestarts") != "0"
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
            "exec_main_pid": data.get("ExecMainPID", ""),
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

    def verified_natural_exit(self, unit: str, expected_invocation: str, *,
                              original_control_group: str,
                              original_main_pid: int) -> dict[str, Any]:
        """Verify a fixed CPU unit's natural terminal state, never a StopReceipt.

        ExitType=cgroup ensures systemd does not enter its final state while
        descendants are still in the controlled cgroup. RemainAfterExit keeps
        the exact transient unit and its exit details queryable. This is NOT
        sufficient evidence for an arbitrary GPU process or a central retry.
        """
        name = _unit(unit)
        if (original_control_group != "/system.slice/" + name
                or type(original_main_pid) is not int or original_main_pid <= 1):
            raise GrantRejected("CPU_EXIT_ORIGINAL_BOUNDARY_INVALID_HOLD")
        evidence = self.inspect(name, expected_invocation)
        state = (evidence["active_state"], evidence["sub_state"])
        if state not in (("active", "exited"), ("failed", "failed")):
            raise GrantRejected("CPU_EXIT_NOT_TERMINAL_HOLD")
        if (evidence["control_group"] not in ("", original_control_group)
                or evidence["main_pid"] != 0
                or not evidence["exec_main_pid"].isdigit()
                or int(evidence["exec_main_pid"]) != original_main_pid
                or evidence["exec_main_code"] != "1"
                or not evidence["exec_main_status"].isdigit()):
            raise GrantRejected("CPU_EXIT_IDENTITY_OR_DESCENDANTS_UNVERIFIED_HOLD")
        exit_code = int(evidence["exec_main_status"])
        if (exit_code < 0 or exit_code > 255
                or (exit_code == 0 and
                    (state != ("active", "exited") or evidence["result"] != "success"))
                or (exit_code > 0 and
                    (state != ("failed", "failed") or evidence["result"] != "exit-code"))):
            raise GrantRejected("CPU_EXIT_RESULT_INCONSISTENT_HOLD")
        return {"invocation_id": expected_invocation,
                "main_pid": original_main_pid,
                "exit_code": exit_code,
                "unit_result": evidence["result"],
                "cgroup_exit_type_verified": True,
                "trusted_stop_receipt_available": False}

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

    def read_log_page(self, unit: str, expected_invocation: str,
                      *, cursor: str | None = None) -> dict[str, Any]:
        """Read only the original systemd invocation; return an opaque journal cursor.

        Every decoded journal entry must match both the exact unit AND the
        recorded invocation. A replaced unit cannot leak another worker's log.
        No log data is accepted from the Agent, and the cursor is never a path.
        """
        name = _unit(unit)
        if not isinstance(expected_invocation, str) or not _INVOCATION.fullmatch(
                expected_invocation):
            raise GrantRejected("CPU_LOG_INVOCATION_INVALID_HOLD")
        if cursor is not None and (not isinstance(cursor, str)
                                   or not _CURSOR.fullmatch(cursor)):
            raise GrantRejected("CPU_LOG_CURSOR_INVALID_HOLD")
        self.inspect(name, expected_invocation)
        args = [
            "/usr/bin/journalctl", "--system", "--no-pager",
            "--output=json", "--lines=+64", "--unit", name,
            "_SYSTEMD_INVOCATION_ID=" + expected_invocation,
        ]
        if cursor is not None:
            args.append("--after-cursor=" + cursor)
        raw = self._run(args)
        lines: list[bytes] = []
        result_cursor = cursor
        size = 0
        try:
            for line in raw.splitlines():
                if not line.strip():
                    continue
                item = json.loads(line)
                if (not isinstance(item, dict)
                        or item.get("_SYSTEMD_INVOCATION_ID") != expected_invocation
                        or item.get("_SYSTEMD_UNIT") != name
                        or not isinstance(item.get("MESSAGE"), str)
                        or not isinstance(item.get("__CURSOR"), str)
                        or not _CURSOR.fullmatch(item["__CURSOR"])):
                    raise GrantRejected("CPU_LOG_ENTRY_SCOPE_UNVERIFIED_HOLD")
                content = (item["MESSAGE"] + "\n").encode("utf-8")
                if size + len(content) > 8192:
                    if not lines:
                        raise GrantRejected("CPU_LOG_ENTRY_TOO_LARGE_HOLD")
                    break
                size += len(content)
                lines.append(content)
                result_cursor = item["__CURSOR"]
        except (ValueError, TypeError) as exc:
            raise GrantRejected("CPU_LOG_JSON_UNVERIFIED_HOLD") from exc
        return {"data": b"".join(lines), "cursor": result_cursor,
                "offset_contract_available": True,
                "trusted_stop_receipt_available": False}

    def read_log(self, unit: str, expected_invocation: str) -> bytes:
        """Backward-compatible bounded diagnostic read, same invocation only."""
        return self.read_log_page(unit, expected_invocation)["data"]
