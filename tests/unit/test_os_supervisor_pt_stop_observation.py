"""2C-03A negative stop contracts. No production services or model execution."""
from __future__ import annotations

from pathlib import Path
import itertools
from types import SimpleNamespace

import pytest

from platform_core.os_supervisor_authorization import GrantRejected
from platform_core.os_supervisor_pt_stop_observation import (
    IsolatedPtStopObserver, _populated,
)


HANDLE = "a" * 32
UNIT = "changlian-os-" + HANDLE + ".service"
INVOCATION = "b" * 32
BOOT = "01234567-89ab-cdef-0123-456789abcdef"
GROUP = "/system.slice/" + UNIT


class Journal:
    def __init__(self):
        self.journal = SimpleNamespace(boot_id=BOOT)
        self.identity = {
            "handle_id": HANDLE, "boot_id": BOOT,
            "unit_name": UNIT, "invocation_id": INVOCATION,
            "control_group": GROUP, "main_pid": 12345,
        }

    def verified_pt_identity(self, handle_id, task_attempt):
        assert handle_id == HANDLE and task_attempt == 7
        return dict(self.identity)


class Backend:
    def __init__(self, path: Path):
        self.path = path
        self.calls = []
        self.snapshot = {
            "unit_name": UNIT, "invocation_id": INVOCATION,
            "control_group": GROUP, "main_pid": 12345,
            "active_state": "active", "sub_state": "running",
        }
        self.empty_on_stop = True

    def inspect(self, unit, invocation):
        self.calls.append("inspect")
        assert (unit, invocation) == (UNIT, INVOCATION)
        return dict(self.snapshot)

    def request_stop(self, unit, invocation):
        self.calls.append("stop")
        assert (unit, invocation) == (UNIT, INVOCATION)
        if self.empty_on_stop:
            self.path.write_text("populated 0\nfrozen 0\n", encoding="ascii")
        return {"state": "UNKNOWN", "stop_requested": True,
                "trusted_stop_receipt_available": False}


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("RUNNER_ENVIRONMENT", "github-hosted")
    path = tmp_path / "system.slice" / UNIT / "cgroup.events"
    path.parent.mkdir(parents=True)
    path.write_text("populated 1\nfrozen 0\n", encoding="ascii")
    journal = Journal()
    backend = Backend(path)
    observer = IsolatedPtStopObserver(journal=journal, backend=backend,
                                       cgroup_root=tmp_path,
                                       isolated_ci_only=True)
    return observer, journal, backend, path


def test_positive_local_empty_is_never_a_stop_receipt(ctx):
    observer, journal, backend, path = ctx
    result = observer.request_and_observe(HANDLE, 7)
    assert result["state"] == "LOCAL_EMPTY_OBSERVED_NO_RECEIPT"
    assert type(result["empty_observed_monotonic_ns"]) is int
    assert (result["empty_observed_monotonic_ns"]
            >= result["stop_requested_monotonic_ns"])
    assert result["trusted_stop_receipt_available"] is False
    assert result["central_recovery_allowed"] is False
    assert result["result_publish_allowed"] is False
    assert backend.calls == ["inspect", "inspect", "stop"]


@pytest.mark.parametrize("field,value", [
    ("handle_id", "c" * 32),
    ("boot_id", "d" * 32),
    ("unit_name", "ssh.service"),
    ("invocation_id", "not-an-id"),
    ("control_group", "/user.slice/" + UNIT),
    ("main_pid", 0),
])
def test_forged_or_stale_scope_cannot_stop(ctx, field, value):
    observer, journal, backend, path = ctx
    journal.identity[field] = value
    with pytest.raises(GrantRejected, match="PT_STOP_"):
        observer.request_and_observe(HANDLE, 7)
    assert "stop" not in backend.calls


@pytest.mark.parametrize("field,value", [
    ("unit_name", "ssh.service"),
    ("invocation_id", "c" * 32),
    ("control_group", "/system.slice/ssh.service"),
    ("main_pid", 99999),
    ("active_state", "inactive"),
    ("sub_state", "exited"),
])
def test_replaced_or_exited_systemd_identity_cannot_stop(ctx, field, value):
    observer, journal, backend, path = ctx
    backend.snapshot[field] = value
    with pytest.raises(GrantRejected, match="ORIGINAL_IDENTITY_UNVERIFIED"):
        observer.request_and_observe(HANDLE, 7)
    assert "stop" not in backend.calls


def test_empty_before_stop_is_never_authorized(ctx):
    observer, journal, backend, path = ctx
    path.write_text("populated 0\n", encoding="ascii")
    with pytest.raises(GrantRejected, match="CGROUP_NOT_LIVE"):
        observer.request_and_observe(HANDLE, 7)
    assert "stop" not in backend.calls


def test_unreadable_or_ambiguous_cgroup_is_never_authorized(ctx):
    observer, journal, backend, path = ctx
    path.write_text("populated 1\npopulated 0\n", encoding="ascii")
    with pytest.raises(GrantRejected, match="CGROUP_NOT_LIVE"):
        observer.request_and_observe(HANDLE, 7)
    assert "stop" not in backend.calls


def test_missing_cgroup_path_cannot_be_treated_as_empty(ctx):
    observer, journal, backend, path = ctx
    path.unlink()
    with pytest.raises(GrantRejected, match="CGROUP_FD_UNAVAILABLE"):
        observer.request_and_observe(HANDLE, 7)
    assert "stop" not in backend.calls


def test_unobserved_stop_is_unknown_and_never_recovery(ctx, monkeypatch):
    import platform_core.os_supervisor_pt_stop_observation as target
    observer, journal, backend, path = ctx
    backend.empty_on_stop = False
    clock = itertools.count(1, 2)
    monkeypatch.setattr(target.time, "monotonic", lambda: next(clock))
    result = observer.request_and_observe(HANDLE, 7)
    assert result["state"] == "UNKNOWN"
    assert result["original_cgroup_became_empty"] is False
    assert result["empty_observed_monotonic_ns"] is None
    assert result["central_recovery_allowed"] is False


def test_ci_gate_is_closed_without_explicit_opt_in(ctx, monkeypatch):
    observer, journal, backend, path = ctx
    with pytest.raises(GrantRejected, match="PRODUCTION_DISABLED"):
        IsolatedPtStopObserver(journal=journal, backend=backend)
    monkeypatch.delenv("GITHUB_ACTIONS")
    with pytest.raises(GrantRejected, match="PRODUCTION_DISABLED"):
        IsolatedPtStopObserver(journal=journal, backend=backend,
                               isolated_ci_only=True)


@pytest.mark.parametrize("payload,expected", [
    ("populated 1\nfrozen 0\n", 1),
    ("populated 0\n", 0),
    ("populated 2\n", None),
    ("frozen 0\n", None),
    ("populated 1\npopulated 0\n", None),
])
def test_kernel_event_parser_is_strict(tmp_path, payload, expected):
    path = tmp_path / "events"
    path.write_text(payload, encoding="ascii")
    with path.open(encoding="ascii") as stream:
        assert _populated(stream) == expected
