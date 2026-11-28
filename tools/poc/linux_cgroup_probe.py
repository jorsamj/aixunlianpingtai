"""P0-01C-2A: read-only Linux/systemd-user preflight, not a stop proof.

Stdlib-only. Never creates units, writes to cgroups, contacts a server, or
reads/prints systemd user-manager environment variables.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import shutil
import subprocess


def cgroup2_mount(mountinfo: str) -> str | None:
    """Find a cgroup2 mount point; mountinfo escaping is handled for spaces."""
    for row in mountinfo.splitlines():
        before, sep, after = row.partition(" - ")
        if not sep or not after.startswith("cgroup2 "):
            continue
        columns = before.split()
        if len(columns) < 5:
            continue
        return columns[4].replace("\\040", " ").replace("\\011", "\t")
    return None


def unified_path(cgroup: str) -> str | None:
    for row in cgroup.splitlines():
        if row.startswith("0::"):
            value = row[3:]
            if value.startswith("/") and ".." not in value.split("/"):
                return value
    return None


def inspect() -> dict:
    result = {
        "scope": "LOCAL_READ_ONLY_P0_01C_2A",
        "stop_proof_verified": False,
        "kernel_cgroup_tested": False,
        "eligible_for_poc": False,
        "blockers": [],
        "os": platform.system(),
        "euid": os.geteuid() if hasattr(os, "geteuid") else None,
    }
    blockers: list[str] = result["blockers"]
    if result["os"] != "Linux":
        blockers.append("LINUX_REQUIRED")
        return result
    if result["euid"] == 0:
        blockers.append("NON_ROOT_REQUIRED")
    try:
        mountinfo = Path("/proc/self/mountinfo").read_text(encoding="utf-8")
        cgroup = Path("/proc/self/cgroup").read_text(encoding="utf-8")
        boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()
        mount = cgroup2_mount(mountinfo)
        path = unified_path(cgroup)
        result.update({"kernel": platform.release(), "cgroup2_mount": mount,
                       "self_cgroup": path, "boot_id": boot_id})
        if not mount or not path:
            blockers.append("UNIFIED_CGROUP_V2_REQUIRED")
        else:
            root = Path(mount)
            result["controllers_readable"] = (root / "cgroup.controllers").is_file()
            result["events_readable"] = (root / path.lstrip("/") / "cgroup.events").is_file()
            if not result["controllers_readable"] or not result["events_readable"]:
                blockers.append("CGROUP_INTERFACE_NOT_READABLE")
    except (OSError, UnicodeError) as error:
        blockers.append("PROCFS_UNREADABLE:" + type(error).__name__)
    run = shutil.which("systemd-run")
    ctl = shutil.which("systemctl")
    result["systemd_run_present"] = bool(run)
    result["systemctl_present"] = bool(ctl)
    if not run or not ctl:
        blockers.append("SYSTEMD_TOOLS_REQUIRED")
    user_runtime = Path(f"/run/user/{os.geteuid()}")
    # Do not print XDG_RUNTIME_DIR; only report existence of the standard bus.
    result["standard_user_bus_present"] = (user_runtime / "bus").exists()
    if not result["standard_user_bus_present"]:
        blockers.append("USER_BUS_UNAVAILABLE")
    if ctl:
        try:
            outcome = subprocess.run(
                [ctl, "--user", "--no-pager", "show", "-p", "Version"],
                capture_output=True, text=True, timeout=3, check=False,
            )
            result["user_manager_reachable"] = (outcome.returncode == 0)
            if outcome.returncode == 0:
                version = outcome.stdout.strip().split("\n", 1)[0]
                result["systemd_version"] = version[:80]
            else:
                blockers.append("USER_MANAGER_UNREACHABLE")
        except (OSError, subprocess.TimeoutExpired):
            result["user_manager_reachable"] = False
            blockers.append("USER_MANAGER_UNREACHABLE")
    result["eligible_for_poc"] = not blockers
    return result


def main() -> int:
    result = inspect()
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    # BLOCKED (2) is not a test failure or proof; command remains read-only.
    return 0 if result["eligible_for_poc"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
