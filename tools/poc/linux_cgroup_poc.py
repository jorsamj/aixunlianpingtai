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
import select
import signal
import subprocess
import sys
import tempfile
import threading
import time
from typing import Callable, Mapping, Any

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


def proc_parent_pid(pid: int) -> int:
    """Read real /proc parent PID, not process-group membership."""
    row = Path(f"/proc/{int(pid)}/stat").read_text(encoding="utf-8")
    fields = row.rsplit(") ", 1)[1].split()
    return int(fields[1])


def descendant_tree_bound(parent_pid: int, ids: dict, group: str) -> bool:
    """Validate a live parent -> child -> grandchild in distinct sessions.

    Reject reused PIDs, any migration outside the exact original cgroup, or
    unrelated child trees. This is a local experiment, not an escape-proof
    security guarantee or a central recovery protocol.
    """
    try:
        child_pid = int(ids["child_pid"])
        leaf_pid = int(ids["grandchild_pid"])
        if len({parent_pid, child_pid, leaf_pid}) != 3:
            return False
        return (int(ids["parent_pid"]) == parent_pid
                and proc_parent_pid(child_pid) == parent_pid
                and proc_parent_pid(leaf_pid) == child_pid
                and os.getsid(child_pid) == child_pid
                and os.getsid(leaf_pid) == leaf_pid
                and all(
                    proc_start_ticks(pid) == int(ids[tick_name])
                    and process_in_cgroup(pid, group)
                    for pid, tick_name in (
                        (parent_pid, "parent_ticks"),
                        (child_pid, "child_ticks"),
                        (leaf_pid, "grandchild_ticks"))
                ))
    except (OSError, ValueError, KeyError, TypeError, OverflowError, IndexError):
        return False


def process_executing_by_identity(pid: int, expected_ticks: int) -> bool | None:
    """True=old computation alive; False=gone or zombie; None=unverifiable.

    PID reuse, malformed procfs and permissions are UNKNOWN, never proof.
    """
    try:
        row = Path(f"/proc/{int(pid)}/stat").read_text(encoding="utf-8")
    except FileNotFoundError:
        return False
    except OSError:
        return None
    try:
        fields = row.rsplit(") ", 1)[1].split()
        if int(fields[19]) != int(expected_ticks):
            return None
        return fields[0] not in {"Z", "X", "x"}
    except (IndexError, ValueError, OverflowError):
        return None


def same_unit_instance(observed: dict[str, str], expected: dict[str, str]) -> bool:
    """Stop only the exact unit instance first observed, never name alone."""
    keys = ("Id", "ControlGroup", "InvocationID")
    return all(expected.get(key) and observed.get(key) == expected[key] for key in keys)


def execution_identity_matches(intent: dict, ready: dict,
                               observed: dict, current_boot_id: str) -> bool:
    """Bind a synthetic task generation to a single systemd invocation.

    Only a local CPU PoC identity check: never a signed or centrally trusted
    stop proof. Any absent, malformed, reused, or cross-generation field HOLDs.
    """
    if not all(isinstance(x, dict) for x in (intent, ready, observed)):
        return False
    unit = intent.get("unit")
    task = intent.get("task_id")
    generation = intent.get("execution_generation")
    boot = intent.get("boot_id")
    nonce = intent.get("nonce")
    invocation = observed.get("InvocationID")
    if not (isinstance(unit, str) and
            re.fullmatch(r"clpoc-[0-9a-f]{24}\.service", unit) and
            isinstance(task, str) and re.fullmatch(r"poc-task-[0-9a-f]{24}", task) and
            type(generation) is int and 0 < generation <= 2**63 - 1 and
            isinstance(boot, str) and re.fullmatch(
                r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", boot) and
            boot == current_boot_id and
            isinstance(nonce, str) and re.fullmatch(r"[0-9a-f]{32}", nonce) and
            isinstance(invocation, str) and re.fullmatch(r"[0-9a-f]{32}", invocation) and
            invocation != "0" * 32 and
            observed.get("Id") == unit):
        return False
    group = observed.get("ControlGroup")
    if not isinstance(group, str) or not group.startswith("/") or (
            group.rsplit("/", 1)[-1] != unit):
        return False
    fields = ("unit", "task_id", "execution_generation", "boot_id", "nonce")
    if any(ready.get(key) != intent.get(key) for key in fields):
        return False
    return (type(ready.get("execution_generation")) is int
            and ready.get("invocation_id") == invocation)


def same_execution_snapshot(expected_intent: dict, current_intent: dict,
                            expected_ready: dict, current_ready: dict) -> bool:
    """Recheck the immutable trial inputs before stop; changes mean HOLD."""
    if not all(isinstance(x, dict) for x in (
            expected_intent, current_intent, expected_ready, current_ready)):
        return False
    return (json.dumps(expected_intent, sort_keys=True) ==
            json.dumps(current_intent, sort_keys=True) and
            json.dumps(expected_ready, sort_keys=True) ==
            json.dumps(current_ready, sort_keys=True))


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


def cg_populated_from_pinned_handle(handle) -> int | None:
    """Read cgroup.events from an FD opened while the original unit lived.

    The FD is bound to that original cgroup; never use missing paths as proof.
    Failure or inaccessible/dead FD => UNKNOWN, not an empty cgroup.
    """
    try:
        handle.seek(0)
        rows = handle.read().splitlines()
    except (OSError, ValueError):
        return None
    for row in rows:
        if row.startswith("populated "):
            try:
                value = int(row.split()[1])
                return value if value in (0, 1) else None
            except (IndexError, ValueError):
                return None
    return None


def read_cgroup_events_fd(fd: int) -> int | None:
    """Read only the original open cgroup.events FD; ENODEV => UNKNOWN."""
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        raw = os.read(fd, 4096).decode("ascii")
    except (OSError, UnicodeError):
        return None
    for line in raw.splitlines():
        if line.startswith("populated "):
            try:
                value = int(line.split()[1])
            except (ValueError, IndexError):
                return None
            return value if value in (0, 1) else None
    return None


class CgroupEventObserver:
    """Subscribe before stopping the original unit; never infer 0 from GC.

    poll(POLLPRI|POLLERR) is Linux cgroup.events' supported notification.
    The observer captures a value only when the original FD is readable.
    A missing read, even after a notification, remains UNKNOWN/HOLD.
    """

    def __init__(self, fd: int):
        self.fd = fd
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._armed = False
        self._lock = threading.Lock()
        self._zero_after_arm = False
        self._repopulated_after_zero = False
        self._events: list[dict] = []
        self._thread = threading.Thread(target=self._watch, daemon=True,
                                        name="p001c-cgroup-events")

    def _sample(self, event: str, mask: int = 0) -> None:
        observed = read_cgroup_events_fd(self.fd)
        record = {"type": event, "mask": mask, "populated": observed,
                  "monotonic_ns": time.monotonic_ns()}
        with self._lock:
            record["after_stop_armed"] = self._armed
            if self._armed and observed == 0:
                self._zero_after_arm = True
            elif self._armed and observed == 1 and self._zero_after_arm:
                self._repopulated_after_zero = True
            if len(self._events) < 100:
                if not self._events or self._events[-1]["populated"] != observed or (
                        self._events[-1]["after_stop_armed"] != self._armed):
                    self._events.append(record)

    def _watch(self):
        try:
            poller = select.poll()
            poller.register(self.fd, select.POLLPRI | select.POLLERR)
            self._ready.set()
            while not self._stop.is_set():
                changes = poller.poll(10)
                if changes:
                    for _, mask in changes:
                        self._sample("poll", mask)
                    # A detached/inaccessible cgroup FD may remain readable
                    # as an error forever. Avoid spinning and flooding evidence.
                    time.sleep(0.002)
                else:
                    # During the tiny stop/GC window even a missed notification
                    # must be diagnosed as UNKNOWN, never assumed to be empty.
                    self._sample("interval")
        except (OSError, ValueError) as error:
            with self._lock:
                self._events.append({"type": "observer_error",
                                     "error_type": type(error).__name__})
            self._ready.set()

    def start(self) -> bool:
        if read_cgroup_events_fd(self.fd) != 1:
            return False
        self._thread.start()
        return self._ready.wait(timeout=2)

    def arm_stop(self) -> bool:
        # Do not accept a zero observed *before* a stop request as proof
        # of that request. The same bound FD must still report a live group.
        if read_cgroup_events_fd(self.fd) != 1:
            return False
        with self._lock:
            self._armed = True
        return True

    @property
    def observed_empty(self) -> bool:
        with self._lock:
            return self._zero_after_arm and not self._repopulated_after_zero

    def evidence(self) -> list[dict]:
        with self._lock:
            return list(self._events)

    def close(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=2)


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
    if not re.fullmatch(r"clpoc-[0-9a-f]{24}\.service", unit):
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
            and intent.get("purpose") == "P0-01C-2B-CPU-ONLY"
            and isinstance(intent.get("task_id"), str)
            and bool(re.fullmatch(r"poc-task-[0-9a-f]{24}", intent["task_id"]))
            and type(intent.get("execution_generation")) is int
            and 0 < intent["execution_generation"] <= 2**63 - 1
            and isinstance(intent.get("nonce"), str)
            and bool(re.fullmatch(r"[0-9a-f]{32}", intent["nonce"])))


def nested_child_script() -> str:
    """Synthetic CPU child spawning a grandchild in another session."""
    return (
        "import json,os,subprocess,sys\n"
        "from pathlib import Path\n"
        "leaf=subprocess.Popen([sys.executable,'-c',"
        "'import time;time.sleep(20)'],start_new_session=True)\n"
        "root=Path(sys.argv[1])\n"
        "tmp=root / '.grandchild.tmp'\n"
        "tmp.write_text(json.dumps({'pid':leaf.pid}),encoding='utf-8')\n"
        "os.replace(tmp,root / 'grandchild.json')\n"
        "leaf.wait()\n"
    )



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
    invocation_id = os.environ.get("INVOCATION_ID", "")
    if not re.fullmatch(r"[0-9a-f]{32}", invocation_id) or invocation_id == "0" * 32:
        return 4
    # Two independent process sessions. The child itself spawns a leaf in a
    # third session, which process-group-only cleanup cannot reliably cover.
    # Every process is CPU-only and bounded by the synthetic systemd unit.
    child_code = nested_child_script()
    child = subprocess.Popen([sys.executable, "-c", child_code, str(root)],
                             start_new_session=True)
    if not wait_for(lambda: (root / "grandchild.json").is_file(), 5):
        return 4
    leaf_pid = int(json.loads((root / "grandchild.json").read_text(
        encoding="utf-8"))["pid"])
    if proc_parent_pid(leaf_pid) != child.pid:
        return 4
    data = {**{key: intent[key] for key in (
                "unit", "task_id", "execution_generation", "boot_id", "nonce")},
            "invocation_id": invocation_id,
            "parent_pid": os.getpid(), "parent_ticks": proc_start_ticks(os.getpid()),
            "child_pid": child.pid, "child_ticks": proc_start_ticks(child.pid),
            "grandchild_pid": leaf_pid, "grandchild_ticks": proc_start_ticks(leaf_pid)}
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


def run_poc(*, synthetic_task_id: str | None = None,
            synthetic_generation: int = 1,
            before_stop: Callable[[dict[str, Any]], bool] | None = None
            ) -> tuple[dict, int]:
    pre = inspect()
    result = {"scope": "ISOLATED_KERNEL_POC_ONLY", "stop_proof_verified": False,
              "central_recovery_allowed": False, "preflight": pre,
              "membership_verified": False, "identity_binding_verified": False,
              "cgroup_empty_verified": False}
    if not pre["eligible_for_poc"]:
        result["outcome"] = "BLOCKED_ENVIRONMENT"
        return result, 2
    if ((synthetic_task_id is not None and
         (not isinstance(synthetic_task_id, str) or
          not re.fullmatch(r"poc-task-[a-f0-9]{24}", synthetic_task_id)))
        or type(synthetic_generation) is not int
        or not 1 <= synthetic_generation <= 2**63 - 1):
        result["outcome"] = "INVALID_SYNTHETIC_EXECUTION_HOLD"
        return result, 3
    with tempfile.TemporaryDirectory(prefix="p001c2b-") as directory:
        root = Path(directory)
        unit = "clpoc-" + secrets.token_hex(12) + ".service"
        result["unit"] = unit
        # Precommit before possible start; never accept a unit from input.
        intent = {"unit": unit, "task_id": (
                      synthetic_task_id or "poc-task-" + secrets.token_hex(12)),
                  "execution_generation": synthetic_generation,  # synthetic CPU only
                  "boot_id": pre["boot_id"], "nonce": secrets.token_hex(16),
                  "purpose": "P0-01C-2B-CPU-ONLY"}
        (root / "intent.json").write_text(json.dumps(intent), encoding="utf-8")
        launcher = subprocess.Popen([sys.executable, str(Path(__file__).resolve()),
                                     "--start-service", unit, str(root)],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        started = False
        bound = False
        initial = {}
        original_cgroup_events = None
        cgroup_observer = None
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
                         and descendant_tree_bound(parent_pid, ids, group)
                         and cg_populated(mount, group) == 1)
            bound = (bound and execution_identity_matches(
                intent, ids, initial, pre["boot_id"]))
            result["membership_verified"] = bound
            result["three_process_sessions_bound"] = bound
            result["identity_binding_verified"] = bound
            if bound:
                result["synthetic_execution_identity"] = {
                    "task_id": intent["task_id"],
                    "execution_generation": intent["execution_generation"],
                    "boot_id": intent["boot_id"],
                    "unit": unit, "invocation_id": invocation}
            if not bound:
                result["outcome"] = "BOUNDARY_IDENTITY_UNKNOWN_HOLD"
                return result, 3
            if ".." in group.split("/"):
                result["outcome"] = "INVALID_CGROUP_PATH_HOLD"
                return result, 3
            # Pin a handle to the original cgroup BEFORE requesting stop.
            # This test never infers a stopped workload from a removed path.
            original_cgroup_events = (Path(mount) / group.lstrip("/") /
                                      "cgroup.events").open("r", encoding="utf-8")
            if cg_populated_from_pinned_handle(original_cgroup_events) != 1:
                result["outcome"] = "CGROUP_PIN_UNVERIFIED_HOLD"
                return result, 3
            cgroup_observer = CgroupEventObserver(original_cgroup_events.fileno())
            if not cgroup_observer.start():
                result["outcome"] = "CGROUP_EVENT_OBSERVER_NOT_READY_HOLD"
                return result, 3
            # Kill just the launcher (stand-in Agent), not the systemd unit.
            launcher.kill()
            launcher.wait(timeout=3)
            result["launcher_sigkill"] = (launcher.returncode == -signal.SIGKILL)
            try:
                result["compute_survived_launcher"] = all(
                    proc_start_ticks(ids[pid_field]) == ids[tick_field]
                    and process_in_cgroup(ids[pid_field], group)
                    for pid_field, tick_field in (
                        ("child_pid", "child_ticks"),
                        ("grandchild_pid", "grandchild_ticks")))
            except (OSError, ValueError, KeyError):
                result["compute_survived_launcher"] = False
            result["both_descendants_survived_launcher"] = result[
                "compute_survived_launcher"]
            if not result["launcher_sigkill"] or not result["compute_survived_launcher"]:
                result["outcome"] = "CRASH_BEHAVIOR_UNEXPECTED_HOLD"
                return result, 3
            # CI bridge only: central challenge is issued while the REAL
            # workload is still alive, strictly BEFORE the stop request.
            # This hook is never used by the production Node Agent.
            if before_stop is not None:
                allowed = before_stop({
                    "task_id": intent["task_id"],
                    "execution_generation": intent["execution_generation"],
                    "boot_id": pre["boot_id"], "invocation_id": invocation,
                    "unit": unit, "cgroup": group, "worker_id": "agent:isolated-poc-node",
                })
                if allowed is not True:
                    result["outcome"] = "ISOLATED_CHALLENGE_NOT_ISSUED_HOLD"
                    return result, 3
                result["isolated_challenge_issued_before_stop"] = True
            # Recheck unit Id, ControlGroup and invocation before requesting stop.
            if not same_unit_instance(unit_info(unit), initial):
                result["outcome"] = "UNIT_REPLACED_HOLD"
                return result, 3
            live_boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(
                encoding="utf-8").strip()
            current_intent = json.loads((root / "intent.json").read_text(
                encoding="utf-8"))
            current_ready = json.loads((root / "ready.json").read_text(
                encoding="utf-8"))
            if not (same_execution_snapshot(intent, current_intent, ids, current_ready)
                    and execution_identity_matches(
                        current_intent, current_ready, unit_info(unit), live_boot_id)):
                result["identity_binding_verified"] = False
                result["outcome"] = "EXECUTION_GENERATION_IDENTITY_CHANGED_HOLD"
                return result, 3
            if not cgroup_observer.arm_stop():
                result["outcome"] = "CGROUP_NOT_LIVE_BEFORE_STOP_HOLD"
                return result, 3
            # Record a readable original-FD populated=1 *after* arming and
            # before invoking stop: necessary for strict stop-event ordering.
            cgroup_observer._sample("ready_before_stop_request")
            if not any(
                    event.get("after_stop_armed") is True and
                    event.get("populated") == 1 and
                    type(event.get("monotonic_ns")) is int
                    for event in cgroup_observer.evidence()):
                result["outcome"] = "CGROUP_NOT_LIVE_AT_STOP_REQUEST_HOLD"
                return result, 3
            result["stop_requested_ns"] = time.monotonic_ns()
            stopped = command(["systemctl", "--user", "--no-ask-password", "stop", unit], 8)
            result["systemd_stop_returncode"] = stopped.returncode
            if stopped.returncode != 0:
                result["outcome"] = "STOP_UNVERIFIED_HOLD"
                return result, 3
            # The transient unit may disappear immediately after stop. The
            # pre-opened cgroup.events FD is tied to its *original* cgroup.
            # A removed pathname is not interpreted as empty.
            result["cgroup_path_after_stop"] = cg_populated(mount, group)
            result["cgroup_handle_after_stop"] = cg_populated_from_pinned_handle(
                original_cgroup_events)
            result["cgroup_empty_verified"] = wait_for(
                lambda: cgroup_observer.observed_empty, 2)
            result["cgroup_observations"] = cgroup_observer.evidence()
            # Require the original FD's empty event to occur AFTER the actual
            # stop request; an early empty group is never evidence of this stop.
            early_zero = any(
                event.get("after_stop_armed") is True
                and event.get("populated") == 0
                and type(event.get("monotonic_ns")) is int
                and event["monotonic_ns"] < result["stop_requested_ns"]
                for event in result["cgroup_observations"])
            post_stop_zero_events = [
                event["monotonic_ns"]
                for event in result["cgroup_observations"]
                if event.get("after_stop_armed") is True
                and event.get("populated") == 0
                and type(event.get("monotonic_ns")) is int
                and event["monotonic_ns"] >= result["stop_requested_ns"]
            ]
            result["empty_observed_ns"] = (
                min(post_stop_zero_events) if post_stop_zero_events else None)
            result["empty_before_stop_requested"] = early_zero
            # cgroup.events=0 is not sufficient if a previously-bound known
            # child has moved elsewhere and is still computing.
            known = ((ids["parent_pid"], ids["parent_ticks"]),
                     (ids["child_pid"], ids["child_ticks"]),
                     (ids["grandchild_pid"], ids["grandchild_ticks"]))
            result["known_processes_stopped"] = wait_for(
                lambda: all(process_executing_by_identity(pid, ticks) is False
                            for pid, ticks in known), 2)
            local_pass = (result["cgroup_empty_verified"] and
                          result["known_processes_stopped"] and
                          result["empty_observed_ns"] is not None and
                          not result["empty_before_stop_requested"])
            result["outcome"] = ("LOCAL_CGROUP_POC_PASS_NOT_CENTRAL_STOP_PROOF"
                                 if local_pass else "STOP_OR_MEMBERSHIP_UNVERIFIED_HOLD")
            return result, 0 if local_pass else 3
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
            result["outcome"] = "UNKNOWN_HOLD"
            result["error_type"] = type(error).__name__
            return result, 3
        finally:
            if cgroup_observer is not None:
                cgroup_observer.close()
            if original_cgroup_events is not None:
                original_cgroup_events.close()
            if launcher.poll() is None:
                launcher.kill()
            launcher.wait(timeout=3)
            # Defensive cleanup limited strictly to this PoC's random unit
            # when its observed invocation is unchanged. Otherwise fail closed;
            # RuntimeMaxSec bounds the synthetic workload to 25 seconds.
            if started and bound:
                try:
                    if same_unit_instance(unit_info(unit), initial):
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
