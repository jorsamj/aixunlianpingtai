"""P0-01C-2B: opt-in, isolated, real systemd USER service cgroup experiment.

Not a production execution boundary or a centrally trusted stop proof.
Never contacts the platform, opens a GPU, runs as root, or accepts a target unit
name from the caller. All test service names are fresh and random.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import sys
import tempfile
import time

from linux_cgroup_probe import inspect, unified_path


def command(argv: list[str], timeout: float = 5.0) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)


def unit_info(unit: str) -> dict[str, str]:
    args = ["systemctl", "--user", "--no-pager", "show", "-p", "Id",
            "-p", "ControlGroup", "-p", "InvocationID", "-p", "MainPID", unit]
    output = command(args)
    if output.returncode != 0:
        raise RuntimeError("USER_UNIT_INSPECTION_FAILED")
    return dict(line.split("=", 1) for line in output.stdout.splitlines() if "=" in line)


def proc_start_ticks(pid: int) -> int:
    # /proc/<pid>/stat field 22, after 'comm' which may contain parentheses.
    row = Path(f"/proc/{int(pid)}/stat").read_text(encoding="utf-8")
    suffix = row.rsplit(") ", 1)[1].split()
    return int(suffix[19])


def process_in_cgroup(pid: int, group: str) -> bool:
    """Exact, current /proc binding; does not alone certify no historical escape."""
    if not group.startswith("/") or group == "/":
        return False
    value = unified_path(Path(f"/proc/{pid}/cgroup").read_text(encoding="utf-8"))
    return value == group or bool(value and value.startswith(group.rstrip("/") + "/"))


def cg_populated(mount: str, group: str) -> int | None:
    if not mount or not group.startswith("/") or ".." in group.split("/"):
        return None
    events_path = Path(mount) / group.lstrip("/") / "cgroup.events"
    try:
        rows = events_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for row in rows:
        if row.startswith("populated "):
            try:
                value = int(row.split()[1])
                return value if value in (0, 1) else None
            except (IndexError, ValueError):
                return None
    return None


def wait_for(predicate, timeout: float = 6.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.1)
    return bool(predicate())



def _valid_test_intent(unit: str, root: Path) -> bool:
    """Only an exact fresh synthetic unit/manifest may reach systemd."""
    if os.name != "posix" or not hasattr(os, "geteuid") or os.geteuid() == 0:
        return False
    if not re.fullmatch(r"clpoc-[0-9a-f]{24}\\.service", unit):
        return False
    if not root.is_dir() or not root.name.startswith("p001c2b-"):
        return False
    try:
        intent = json.loads((root / "intent.json").read_text(encoding="utf-8"))
        boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()
    except (OSError, ValueError):
        return False
    return (isinstance(intent, dict) and intent.get("unit") == unit
            and intent.get("boot_id") == boot_id
            and intent.get("purpose") == "P0-01C-2B-CPU-ONLY")


def _payload(root: Path) -> int:
    # A direct public --payload invocation must not start any computation.
    try:
        intent = json.loads((root / "intent.json").read_text(encoding="utf-8"))
        unit = intent.get("unit", "") if isinstance(intent, dict) else ""
        member = unified_path(Path("/proc/self/cgroup").read_text(encoding="utf-8"))
        if not (_valid_test_intent(unit, root) and member
                and member.endswith("/" + unit)):
            return 4
    except (OSError, ValueError):
        return 4
    # Runs only inside a separate transient user service. A descendant with
    # a *new session* must still remain in the same cgroup, unlike killpg.
    child = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(20)"],
                             start_new_session=True)
    data = {"parent_pid": os.getpid(), "parent_ticks": proc_start_ticks(os.getpid()),
            "child_pid": child.pid, "child_ticks": proc_start_ticks(child.pid)}
    state = root / "ready.json"
    temp = root / ".ready.tmp"
    with temp.open("w", encoding="utf-8") as file:
        json.dump(data, file)
        file.flush()
        os.fsync(file.fileno())
    os.replace(temp, state)
    while child.poll() is None:
        time.sleep(0.1)
    return 0


def _start_service(unit: str, root: Path) -> int:
    if not _valid_test_intent(unit, root) or not inspect()["eligible_for_poc"]:
        return 4
    # Called from a disposable launcher so the parent can SIGKILL it after
    # start, reproducing loss of the agent process while compute continues.
    run = command(["systemd-run", "--user", "--no-ask-password", "--unit=" + unit,
                   "--property=Type=exec", "--property=KillMode=control-group",
                   "--property=Restart=no", "--property=RuntimeMaxSec=25s",
                   "--property=TimeoutStopSec=3s",
                   sys.executable, str(Path(__file__).resolve()),
                   "--payload", str(root)], timeout=8)
    if run.returncode:
        (root / "launcher-error.txt").write_text(run.stderr[-1000:], encoding="utf-8")
        return 4
    (root / "launched").write_text("ok\n", encoding="utf-8")
    time.sleep(20)  # controller SIGKILLs this *launcher*, not the workload.
    return 0


def run_poc() -> tuple[dict, int]:
    pre = inspect()
    result = {"scope": "ISOLATED_KERNEL_POC_ONLY", "stop_proof_verified": False,
              "central_recovery_allowed": False, "preflight": pre,
              "membership_verified": False, "cgroup_empty_verified": False}
    if not pre["eligible_for_poc"]:
        result["outcome"] = "BLOCKED_ENVIRONMENT"
        return result, 2
    with tempfile.TemporaryDirectory(prefix="p001c2b-") as directory:
        root = Path(directory)
        unit = "clpoc-" + secrets.token_hex(12) + ".service"
        result["unit"] = unit
        # Precommit before possible start; never accept a unit from input.
        (root / "intent.json").write_text(json.dumps({
            "unit": unit, "boot_id": pre["boot_id"], "nonce": secrets.token_hex(16),
            "purpose": "P0-01C-2B-CPU-ONLY"}), encoding="utf-8")
        launcher = subprocess.Popen([sys.executable, str(Path(__file__).resolve()),
                                     "--start-service", unit, str(root)],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        started = False
        bound = False
        initial = {}
        try:
            started = wait_for(lambda: (root / "launched").exists() and (root / "ready.json").exists(), 8)
            if not started:
                result["outcome"] = "LAUNCH_NOT_VERIFIED_HOLD"
                result["launcher_exit_code"] = launcher.poll()
                return result, 3
            initial = unit_info(unit)
            group = initial.get("ControlGroup", "")
            invocation = initial.get("InvocationID", "")
            parent_pid = int(initial.get("MainPID") or "0")
            ids = json.loads((root / "ready.json").read_text(encoding="utf-8"))
            mount = str(pre["cgroup2_mount"])
            bound = bool(initial.get("Id") == unit and group.startswith("/") and group != "/"
                         and invocation and invocation != "0" * len(invocation)
                         and parent_pid == ids["parent_pid"]
                         and proc_start_ticks(parent_pid) == ids["parent_ticks"]
                         and proc_start_ticks(ids["child_pid"]) == ids["child_ticks"]
                         and process_in_cgroup(parent_pid, group)
                         and process_in_cgroup(ids["child_pid"], group)
                         and cg_populated(mount, group) == 1)
            result["membership_verified"] = bound
            if not bound:
                result["outcome"] = "BOUNDARY_IDENTITY_UNKNOWN_HOLD"
                return result, 3
            # Kill just the launcher (stand-in Agent), not the systemd unit.
            launcher.kill()
            launcher.wait(timeout=3)
            result["launcher_sigkill"] = (launcher.returncode == -signal.SIGKILL)
            try:
                result["compute_survived_launcher"] = (
                    proc_start_ticks(ids["child_pid"]) == ids["child_ticks"]
                    and process_in_cgroup(ids["child_pid"], group))
            except OSError:
                result["compute_survived_launcher"] = False
            if not result["launcher_sigkill"] or not result["compute_survived_launcher"]:
                result["outcome"] = "CRASH_BEHAVIOR_UNEXPECTED_HOLD"
                return result, 3
            # Only stop our exact randomly named unit if invocation still matches.
            if unit_info(unit).get("InvocationID") != invocation:
                result["outcome"] = "UNIT_REPLACED_HOLD"
                return result, 3
            stopped = command(["systemctl", "--user", "--no-ask-password", "stop", unit], 8)
            result["systemd_stop_returncode"] = stopped.returncode
            if stopped.returncode != 0:
                result["outcome"] = "STOP_UNVERIFIED_HOLD"
                return result, 3
            # Missing cgroup is explicitly UNKNOWN; never assume proof from a
            # removed path. systemd may GC the unit immediately after stop.
            result["cgroup_empty_verified"] = wait_for(
                lambda: cg_populated(mount, group) == 0, 2)
            result["outcome"] = ("LOCAL_CGROUP_POC_PASS_NOT_CENTRAL_STOP_PROOF"
                                 if result["cgroup_empty_verified"] else
                                 "CGROUP_GONE_OR_NOT_EMPTY_HOLD")
            return result, 0 if result["cgroup_empty_verified"] else 3
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
            result["outcome"] = "UNKNOWN_HOLD"
            result["error_type"] = type(error).__name__
            return result, 3
        finally:
            if launcher.poll() is None:
                launcher.kill()
            launcher.wait(timeout=3)
            # Defensive cleanup limited strictly to this PoC's random unit
            # when its observed invocation is unchanged. Otherwise fail closed;
            # RuntimeMaxSec bounds the synthetic workload to 25 seconds.
            if started and bound:
                try:
                    if unit_info(unit).get("InvocationID") == initial.get("InvocationID"):
                        command(["systemctl", "--user", "--no-ask-password", "stop", unit], 8)
                except (OSError, RuntimeError, subprocess.TimeoutExpired):
                    pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--isolated-test-host", action="store_true")
    parser.add_argument("--payload", type=Path)
    parser.add_argument("--start-service", nargs=2, metavar=("UNIT", "TEMP_DIR"))
    args = parser.parse_args()
    if args.payload is not None:
        return _payload(args.payload)
    if args.start_service is not None:
        return _start_service(args.start_service[0], Path(args.start_service[1]))
    if not (args.run and args.isolated_test_host):
        print(json.dumps({"outcome": "NOT_EXECUTED", "reason":
                          "requires --run --isolated-test-host; NEVER run on A800/4070 production",
                          "stop_proof_verified": False}))
        return 2
    result, code = run_poc()
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
