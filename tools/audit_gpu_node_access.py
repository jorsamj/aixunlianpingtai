#!/usr/bin/env python3
"""Read-only local GPU Node Agent privilege inventory for *authorized* use.

Opt-in: --read-only [--unit changlian-node-agent.service]

Reads only public systemd unit properties, Linux user/group metadata and
filesystem metadata (stat; never opens real device files). Does not execute
CUDA, nvidia-smi, sudo, login commands, or alter processes, drivers or services.
Does not print environment variables, tokens, passwords, ExecStart or paths
to business datasets/models. The results are a permissions *inventory*, not
proof that a process can/cannot establish a GPU/SDK context.
"""
from __future__ import annotations

import argparse
import glob
import grp
import json
import os
from pathlib import Path
import platform
import pwd
import re
import stat
import subprocess


SYSTEMD_PROPERTIES = (
    "Id", "LoadState", "ActiveState", "User", "Group", "DynamicUser",
    "SupplementaryGroups", "NoNewPrivileges", "PrivateDevices",
    "DevicePolicy", "DeviceAllow", "ProtectControlGroups", "Delegate",
    "RestrictSUIDSGID", "ProtectKernelTunables",
)

DEVICE_PATTERNS = (
    "/dev/nvidia[0-9]*",
    "/dev/nvidiactl",
    "/dev/nvidia-uvm*",
    "/dev/nvidia-caps/*",
    "/dev/dri/renderD*",
    "/dev/kfd",
    "/dev/davinci[0-9]*",
    "/dev/ascend*",
    "/dev/rknpu*",
)

UNIT_NAME = re.compile(r"^[A-Za-z0-9_.@-]{1,128}\.service$")


def systemd_unit_properties(name: str) -> dict:
    if not UNIT_NAME.fullmatch(name):
        return {"status": "INVALID_UNIT_NAME", "properties": {}}
    cmd = ["systemctl", "--system", "show", name,
           "--property=" + ",".join(SYSTEMD_PROPERTIES), "--no-pager"]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=4,
                           check=False)
    except (OSError, subprocess.TimeoutExpired):
        return {"status": "SYSTEMD_UNAVAILABLE", "properties": {}}
    if p.returncode != 0:
        return {"status": "UNIT_LOOKUP_FAILED", "properties": {}}
    allowed = set(SYSTEMD_PROPERTIES)
    properties = {}
    for line in p.stdout.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key in allowed:
            properties[key] = value
    return {"status": "OBSERVED", "properties": properties}


def _account(name: str) -> dict:
    if not name:
        return {"status": "UNSPECIFIED_SYSTEMD_DEFAULT", "uid": None}
    try:
        row = pwd.getpwnam(name) if not name.isdecimal() else pwd.getpwuid(int(name))
        groups = os.getgrouplist(row.pw_name, row.pw_gid)
    except (KeyError, OSError, OverflowError, ValueError):
        return {"status": "ACCOUNT_LOOKUP_UNKNOWN", "uid": None}
    return {
        "status": "OBSERVED",
        "uid": row.pw_uid,
        "gid": row.pw_gid,
        "group_ids": sorted(set(groups)),
        "root_uid": row.pw_uid == 0,
    }


def device_metadata() -> list[dict]:
    found = set()
    for pattern in DEVICE_PATTERNS:
        found.update(glob.glob(pattern))
    results = []
    for path in sorted(found):
        try:
            info = os.stat(path, follow_symlinks=False)
        except OSError:
            results.append({"path": path, "status": "STAT_UNAVAILABLE"})
            continue
        mode = info.st_mode
        results.append({
            "path": path,
            "status": "OBSERVED",
            "type": "character_device" if stat.S_ISCHR(mode) else
                    "block_device" if stat.S_ISBLK(mode) else "other",
            "mode_octal": f"{stat.S_IMODE(mode):04o}",
            "owner_uid": info.st_uid,
            "group_gid": info.st_gid,
            "world_read_bit": bool(mode & stat.S_IROTH),
            "world_write_bit": bool(mode & stat.S_IWOTH),
            "group_read_bit": bool(mode & stat.S_IRGRP),
            "group_write_bit": bool(mode & stat.S_IWGRP),
        })
    return results


def inventory(*, unit: str = "") -> dict:
    if os.name != "posix" or platform.system() != "Linux":
        return {
            "scope": "GPU_NODE_PRIVILEGE_READ_ONLY_INVENTORY",
            "status": "UNSUPPORTED_OS",
            "permission_isolation_verified": False,
            "production_recovery_allowed": False,
        }
    sysd = systemd_unit_properties(unit) if unit else {
        "status": "NOT_REQUESTED", "properties": {},
    }
    user = sysd.get("properties", {}).get("User", "")
    account = _account(user) if unit and sysd["status"] == "OBSERVED" else {
        "status": "NOT_OBSERVED", "uid": None,
    }
    devices = device_metadata()
    properties = sysd.get("properties", {})
    return {
        "scope": "GPU_NODE_PRIVILEGE_READ_ONLY_INVENTORY",
        "status": "OBSERVED_UNVERIFIED",
        "requested_unit": unit or None,
        "service_unit": sysd,
        "service_account": account,
        "process_context": {
            "effective_uid": os.geteuid(),
            "effective_gid": os.getegid(),
            "group_ids": sorted(set(os.getgroups())),
            "inspector_is_service_account": (
                account.get("uid") is not None and
                os.geteuid() == account["uid"]),
        },
        "os_context": {
            "kernel_release": platform.release(),
            "machine": platform.machine(),
            "cgroup_v2_available": Path("/sys/fs/cgroup/cgroup.controllers").is_file(),
        },
        "device_metadata": devices,
        "review_flags": {
            "no_or_root_service_user": (
                user in ("", "root", "0") if sysd["status"] == "OBSERVED" else None),
            "systemd_device_policy_unknown_or_auto": (
                properties.get("DevicePolicy", "") in ("", "auto")
                if sysd["status"] == "OBSERVED" else None),
            "world_writable_device_metadata_seen": any(
                row.get("world_write_bit") is True for row in devices),
        },
        "important_limitations": [
            "Stat metadata cannot prove CUDA/SDK access or denial.",
            "POSIX ACLs, supplementary device access policies, containers, "
            "cgroup device BPF and driver behavior require separate review.",
            "Process context is the inspector's UID, not necessarily the Agent's.",
            "This tool performs no GPU or supervisor stop challenge.",
        ],
        "permission_isolation_verified": False,
        "production_recovery_allowed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--read-only", action="store_true",
                        help="Explicitly authorize passive local metadata reads.")
    parser.add_argument("--unit", default="",
                        help="Optional exact existing systemd .service name.")
    args = parser.parse_args()
    if not args.read_only:
        print(json.dumps({"status": "INERT_OPT_IN_REQUIRED",
                          "production_recovery_allowed": False}))
        return 2
    if args.unit and not UNIT_NAME.fullmatch(args.unit):
        print(json.dumps({"status": "INVALID_UNIT_NAME",
                          "production_recovery_allowed": False}))
        return 2
    print(json.dumps(inventory(unit=args.unit), ensure_ascii=False, indent=2,
                     sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
