"""2C-03A: CI-only observation of the ORIGINAL PT systemd cgroup stopping.

This is NOT a StopReceipt, a central recovery grant, or a replacement
conversion runner. All production call sites must remain disabled.
Missing/replaced units, cgroup GC, unreadable kernel events, and uncertain
process membership must remain UNKNOWN (never successful cancellation).
"""
from __future__ import annotations

import os
import select
import threading
from pathlib import Path
import re
import time
from typing import Any, Mapping

from .os_supervisor_authorization import GrantRejected


_UNIT = re.compile(r"changlian-os-[0-9a-f]{32}\.service\Z")
_INVOCATION = re.compile(r"[0-9a-f]{32}\Z")
_BOOT = re.compile(r"[0-9a-f-]{32,36}\Z")


def _hold(code: str) -> None:
    raise GrantRejected("PT_STOP_" + code + "_HOLD")


def _populated(handle) -> int | None:
    """Only a *pre-opened* cgroup.events descriptor may supply stop evidence."""
    try:
        handle.seek(0)
        data = handle.read(4096)
        if not isinstance(data, str):
            return None
        items = [s.split() for s in data.splitlines() if s.startswith("populated ")]
        if len(items) != 1 or len(items[0]) != 2 or items[0][1] not in ("0", "1"):
            return None
        return int(items[0][1])
    except (OSError, ValueError, UnicodeError):
        return None


def _scope(identity: Mapping[str, Any], snapshot: Mapping[str, Any],
           *, current_boot: str) -> None:
    """Accept no Agent-supplied target or PID. Scope must already be journal-bound."""
    if not isinstance(identity, Mapping) or not isinstance(snapshot, Mapping):
        _hold("SCOPE_INVALID")
    handle = identity.get("handle_id")
    unit = identity.get("unit_name")
    invocation = identity.get("invocation_id")
    group = identity.get("control_group")
    pid = identity.get("main_pid")
    boot = identity.get("boot_id")
    if (not isinstance(handle, str) or not re.fullmatch(r"[0-9a-f]{32}", handle)
            or unit != "changlian-os-" + handle + ".service"
            or not isinstance(unit, str) or not _UNIT.fullmatch(unit)
            or not isinstance(invocation, str) or not _INVOCATION.fullmatch(invocation)
            or group != "/system.slice/" + unit
            or type(pid) is not int or pid <= 1
            or not isinstance(boot, str) or not _BOOT.fullmatch(boot)
            or boot != current_boot
            or snapshot.get("unit_name") != unit
            or snapshot.get("invocation_id") != invocation
            or snapshot.get("control_group") != group
            or snapshot.get("main_pid") != pid
            or snapshot.get("active_state") != "active"
            or snapshot.get("sub_state") != "running"):
        _hold("ORIGINAL_IDENTITY_UNVERIFIED")


class _PinnedCgroupObserver:
    """Arm poll(POLLPRI) BEFORE systemctl stop or kernel GC can erase evidence."""

    def __init__(self, pinned):
        self.pinned = pinned
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._closed = threading.Event()
        self._thread = threading.Thread(target=self._watch, daemon=True,
                                        name="pt-stop-ci-cgroup-events")
        self._request_ns: int | None = None
        self._saw_zero = False
        self._zero_observed_ns: int | None = None
        self._repopulated = False
        self._observer_error = False

    def _watch(self) -> None:
        try:
            poller = select.poll()
            poller.register(self.pinned.fileno(), select.POLLPRI | select.POLLERR)
            self._ready.set()
            while not self._closed.is_set():
                # Poll subscriptions observe the cgroup.events transition even
                # when systemctl stop returns only after the unit was GC'd.
                poller.poll(10)
                with self._lock:
                    value = _populated(self.pinned)
                    if self._request_ns is not None:
                        if value == 0:
                            observed_at = time.monotonic_ns()
                            if observed_at >= self._request_ns:
                                self._saw_zero = True
                                if self._zero_observed_ns is None:
                                    self._zero_observed_ns = observed_at
                        elif value == 1 and self._saw_zero:
                            self._repopulated = True
        except (OSError, ValueError):
            with self._lock:
                self._observer_error = True
            self._ready.set()

    def start(self) -> None:
        self._thread.start()
        if not self._ready.wait(timeout=1.0):
            _hold("CGROUP_OBSERVER_NOT_READY")

    def arm(self) -> int:
        with self._lock:
            if self._observer_error or _populated(self.pinned) != 1:
                _hold("CGROUP_CHANGED_BEFORE_STOP")
            self._request_ns = time.monotonic_ns()
            return self._request_ns

    def empty_observed(self) -> bool:
        with self._lock:
            return self._saw_zero and not self._repopulated and not self._observer_error

    def empty_observed_ns(self) -> int | None:
        with self._lock:
            if not self._saw_zero or self._repopulated or self._observer_error:
                return None
            return self._zero_observed_ns

    def sample_after_stop(self) -> None:
        # Also read synchronously in case fake regular-file tests have no poll
        # notifications. Real cgroup events can be captured by the watcher.
        with self._lock:
            value = _populated(self.pinned)
            if self._request_ns is not None:
                if value == 0:
                    observed_at = time.monotonic_ns()
                    if observed_at >= self._request_ns:
                        self._saw_zero = True
                        if self._zero_observed_ns is None:
                            self._zero_observed_ns = observed_at
                elif value == 1 and self._saw_zero:
                    self._repopulated = True

    def close(self) -> None:
        self._closed.set()
        if self._thread.is_alive():
            self._thread.join(timeout=1.0)


class IsolatedPtStopObserver:
    """No production API; root CI only; no StopReceipt or task state update."""

    def __init__(self, *, journal, backend, cgroup_root: Path = Path("/sys/fs/cgroup"),
                 isolated_ci_only: bool = False):
        if (isolated_ci_only is not True
                or os.environ.get("GITHUB_ACTIONS") != "true"
                or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted"):
            _hold("PRODUCTION_DISABLED")
        self.journal = journal
        self.backend = backend
        self.cgroup_root = Path(cgroup_root)

    def request_and_observe(self, handle_id: str, task_attempt: int) -> dict[str, Any]:
        """Observe cgroup=1 before stop, then cgroup=0 on the SAME open FD.

        cgroup path disappearance is never equivalent to proof of empty.
        No trusted StopReceipt is issued, regardless of the observation.
        """
        if (not isinstance(handle_id, str)
                or not re.fullmatch(r"[0-9a-f]{32}", handle_id)
                or type(task_attempt) is not int or task_attempt <= 0):
            _hold("ARGUMENTS_INVALID")
        identity = self.journal.verified_pt_identity(handle_id, task_attempt)
        boot = str(self.journal.journal.boot_id)
        if not isinstance(identity, Mapping):
            _hold("ORIGINAL_IDENTITY_UNVERIFIED")
        # Refuse malformed journal targets BEFORE passing anything to systemd.
        unit = "changlian-os-" + handle_id + ".service"
        invocation = identity.get("invocation_id")
        if (identity.get("handle_id") != handle_id
                or identity.get("unit_name") != unit
                or identity.get("control_group") != "/system.slice/" + unit
                or not isinstance(invocation, str)
                or not _INVOCATION.fullmatch(invocation)
                or type(identity.get("main_pid")) is not int
                or identity["main_pid"] <= 1):
            _hold("ORIGINAL_IDENTITY_UNVERIFIED")
        if identity.get("boot_id") != boot:
            _hold("BOOT_MISMATCH")
        before = self.backend.inspect(unit, invocation)
        _scope(identity, before, current_boot=boot)
        group = identity["control_group"]
        # The cgroup name is derived from the original journal, never from a
        # client-controlled path. Reject symlinks in the terminal component.
        path = self.cgroup_root / group.lstrip("/") / "cgroup.events"
        try:
            flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(path, flags)
            with os.fdopen(fd, "r", encoding="ascii") as pinned:
                if _populated(pinned) != 1:
                    _hold("CGROUP_NOT_LIVE")
                watcher = _PinnedCgroupObserver(pinned)
                watcher.start()
                try:
                    # Recheck before dispatch; no external process can choose
                    # the target unit, and the observer is already subscribed.
                    newest = self.backend.inspect(unit, invocation)
                    _scope(identity, newest, current_boot=boot)
                    requested_ns = watcher.arm()
                    response = self.backend.request_stop(unit, invocation)
                    if (not isinstance(response, Mapping)
                            or response.get("stop_requested") is not True
                            or response.get("trusted_stop_receipt_available") is not False):
                        _hold("STOP_RESPONSE_INVALID")
                    deadline = time.monotonic() + 2.0
                    watcher.sample_after_stop()
                    while time.monotonic() < deadline and not watcher.empty_observed():
                        time.sleep(0.02)
                        watcher.sample_after_stop()
                    seen_zero = watcher.empty_observed()
                    empty_observed_ns = watcher.empty_observed_ns()
                finally:
                    watcher.close()
        except GrantRejected:
            raise
        except (OSError, UnicodeError) as exc:
            raise GrantRejected("PT_STOP_CGROUP_FD_UNAVAILABLE_HOLD") from exc
        return {
            "handle_id": handle_id,
            "task_attempt": task_attempt,
            "original_unit": identity["unit_name"],
            "original_invocation_id": identity["invocation_id"],
            "original_main_pid": identity["main_pid"],
            "stop_requested_monotonic_ns": requested_ns,
            "original_cgroup_became_empty": seen_zero,
            "empty_observed_monotonic_ns": (
                empty_observed_ns if seen_zero else None
            ),
            "state": "LOCAL_EMPTY_OBSERVED_NO_RECEIPT" if seen_zero else "UNKNOWN",
            "trusted_stop_receipt_available": False,
            "central_recovery_allowed": False,
            "result_publish_allowed": False,
            "production_launch_allowed": False,
        }
