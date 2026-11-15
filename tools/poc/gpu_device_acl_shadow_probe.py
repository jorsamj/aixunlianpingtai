"""P0-01C-3B-4: disposable fake-device DAC counterexample, NOT a GPU test.

Uses a REGULAR FILE as a device-permission shadow. It cannot test NVIDIA,
Ascend, Rockchip, CUDA context creation, GPU isolation, /dev device cgroup BPF
or any production credentials. It illustrates why Agent membership/permissions
matter and why 'CUDA_VISIBLE_DEVICES' is not a security boundary.

Explicit opt-in, GitHub-hosted ephemeral Ubuntu 22.04, non-root Agent UID and
workload UID, temporary users, owned random files only. No production access.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import pwd
import secrets
import subprocess
import tempfile

import linux_supervisor_privilege_probe as prior


_READ_ATTEMPT = (
    "import os,sys\n"
    "fd=os.open(sys.argv[1],os.O_RDONLY)\n"
    "os.read(fd,1)\n"
    "os.close(fd)\n"
)


def _can_read_as(username: str, target: Path) -> bool:
    attempt = prior._run(["runuser", "-u", username, "--", "/usr/bin/python3",
                          "-c", _READ_ATTEMPT, str(target)], timeout=5)
    return attempt.returncode == 0


def run_shadow_probe() -> tuple[dict, int]:
    result = {
        "scope": "GITHUB_HOSTED_FAKE_REGULAR_FILE_DAC_ONLY",
        "fake_device_acl_separation_verified": False,
        "fake_world_access_bypass_observed": False,
        "actual_cuda_or_gpu_device_tested": False,
        "actual_ascend_or_rockchip_device_tested": False,
        "production_gpu_isolation_verified": False,
        "production_recovery_allowed": False,
    }
    if not prior._only_disposable_host():
        result["outcome"] = "GITHUB_EPHEMERAL_ROOT_PRECONDITION_HOLD"
        return result, 2
    accounts = []
    with tempfile.TemporaryDirectory(prefix="p001c3b4-device-shadow-") as d:
        root = Path(d)
        os.chmod(root, 0o711)
        target = root / "simulated-device-regular-file"
        try:
            prefix = "clp" + secrets.token_hex(3)
            agent, workload = prefix + "a", prefix + "w"
            for account in (agent, workload):
                created = prior._run(
                    ["useradd", "--system", "--no-create-home",
                     "--shell=/usr/sbin/nologin", "--user-group", account],
                    timeout=5)
                if created.returncode:
                    raise RuntimeError("DISPOSABLE_USER_CREATION_FAILED")
                accounts.append(account)
            agent_uid = pwd.getpwnam(agent).pw_uid
            workload_uid = pwd.getpwnam(workload).pw_uid
            workload_gid = pwd.getpwnam(workload).pw_gid
            if agent_uid == workload_uid or min(agent_uid, workload_uid) <= 0:
                raise RuntimeError("DISTINCT_NONROOT_UID_REQUIRED")
            # The file deliberately is NOT a device node: no mknod, GPU or
            # driver access. Root owns it; only workload's unique group can read.
            target.write_bytes(b"SIMULATED-FILE-NOT-GPU\n")
            os.chown(target, 0, workload_gid)
            os.chmod(target, 0o660)
            workload_allowed = _can_read_as(workload, target)
            agent_denied = not _can_read_as(agent, target)
            result["fake_device_acl_separation_verified"] = (
                workload_allowed and agent_denied)
            # Demonstrate a danger: a world-readable/writable mock node can be
            # opened by ANY agent even with separate systemd UIDs.
            os.chmod(target, 0o666)
            world_agent_allowed = _can_read_as(agent, target)
            result["fake_world_access_bypass_observed"] = world_agent_allowed
            os.chmod(target, 0o660)
            restored_agent_denied = not _can_read_as(agent, target)
            result["restored_agent_denial_verified"] = restored_agent_denied
            matched = all((
                result["fake_device_acl_separation_verified"],
                result["fake_world_access_bypass_observed"],
                restored_agent_denied,
            ))
            result["outcome"] = (
                "FAKE_FILE_DAC_COUNTEREXAMPLE_PASS_REAL_GPU_NOT_VERIFIED"
                if matched else "FAKE_FILE_DAC_CONTRACT_FAILED_HOLD")
            return result, 0 if matched else 3
        except (OSError, ValueError, RuntimeError,
                subprocess.TimeoutExpired) as exc:
            result["outcome"] = "FAKE_DAC_PROBE_EXCEPTION_HOLD"
            result["error_type"] = type(exc).__name__
            return result, 3
        finally:
            for account in reversed(accounts):
                try:
                    prior._run(["userdel", account], timeout=5)
                except (OSError, subprocess.TimeoutExpired):
                    pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--github-ephemeral-only", action="store_true")
    args = parser.parse_args()
    if not (args.run and args.github_ephemeral_only):
        print(json.dumps({"outcome": "INERT_OPT_IN_REQUIRED",
                          "production_gpu_isolation_verified": False,
                          "production_recovery_allowed": False}))
        return 2
    result, code = run_shadow_probe()
    print(json.dumps(result, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
