"""Stage 2A systemd backend contract: same unit/invocation or HOLD.

The mock covers bounded command construction; the separate Linux integration
runs a *real systemd system service*, with no GPU, on an isolated CI runner.
"""
from __future__ import annotations

from types import SimpleNamespace
import json

import pytest

from platform_core.os_supervisor_authorization import GrantRejected
from platform_core.os_supervisor_cpu_systemd import FixedCpuSystemd

UNIT = "changlian-os-" + "a" * 32 + ".service"
INVOCATION = "b" * 32


class FakeSystemd:
    def __init__(self):
        self.calls = []
        self.state = "active"
        self.invocation = INVOCATION
        self.private_devices = "yes"
        self.log_invocation = INVOCATION
        self.log_unit = UNIT

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        assert kwargs["shell"] is False
        assert kwargs["timeout"] <= 7
        if "systemd-run" in argv[0]:
            self.state = "active"
            return SimpleNamespace(returncode=0, stdout=f"Running as unit: {UNIT}")
        if "journalctl" in argv[0]:
            if "--after-cursor=s=one;i=1" in argv:
                return SimpleNamespace(returncode=0, stdout="")
            record = {
                "__CURSOR": "s=one;i=1",
                "_SYSTEMD_INVOCATION_ID": self.log_invocation,
                "_SYSTEMD_UNIT": self.log_unit,
                "MESSAGE": "cpu-trial-start",
            }
            return SimpleNamespace(returncode=0, stdout=json.dumps(record) + "\n")
        if argv[3] == "stop":
            self.state = "inactive"
            return SimpleNamespace(returncode=0, stdout="")
        assert argv[3] == "show"
        fields = {
            "Id": UNIT, "LoadState": "loaded", "Transient": "yes",
            "ActiveState": self.state,
            "SubState": "running" if self.state == "active" else "dead",
            "InvocationID": self.invocation,
            "ControlGroup": "/system.slice/" + UNIT if self.state == "active" else "",
            "MainPID": "82340" if self.state == "active" else "0",
            "PrivateDevices": self.private_devices,
            "DevicePolicy": "closed", "KillMode": "control-group",
            "DynamicUser": "yes", "NoNewPrivileges": "yes",
            "ExecMainCode": "1", "ExecMainStatus": "0", "Result": "success",
        }
        return SimpleNamespace(
            returncode=0,
            stdout="\n".join(f"{k}={v}" for k, v in fields.items()) + "\n",
        )


def test_fixed_only_systemd_service_start_inspect_stop_log():
    os_fake = FakeSystemd()
    backend = FixedCpuSystemd(test_only_runner=os_fake)
    created = backend.launch(UNIT)
    assert created["unit_name"] == UNIT
    assert created["control_group"] == "/system.slice/" + UNIT
    assert created["invocation_id"] == INVOCATION
    first = os_fake.calls[0][0]
    assert first[0] == "/usr/bin/systemd-run"
    assert "--system" in first
    assert "--property=DynamicUser=yes" in first
    assert "--property=PrivateDevices=yes" in first
    assert "--property=DevicePolicy=closed" in first
    assert "--property=KillMode=control-group" in first
    assert "--property=Type=exec" in first
    assert "/usr/bin/python3" in first
    assert "/bin/sh" not in first
    assert backend.read_log(UNIT, INVOCATION) == b"cpu-trial-start\n"
    result = backend.request_stop(UNIT, INVOCATION)
    assert result["state"] == "UNKNOWN"
    assert result["stop_requested"] is True
    assert result["trusted_stop_receipt_available"] is False
    assert backend.inspect(UNIT, INVOCATION)["active_state"] == "inactive"
    assert not any("kill" in str(call[0]) for call in os_fake.calls)


@pytest.mark.parametrize("bad_unit", [
    "../evil.service", "ssh.service", "changlian-os-1.service",
    "changlian-os-" + "z" * 32 + ".service",
    "changlian-os-" + "a" * 32 + ".service;rm -rf /",
])
def test_systemd_unit_cannot_be_selected_by_agent(bad_unit):
    stub = FakeSystemd()
    service = FixedCpuSystemd(test_only_runner=stub)
    with pytest.raises(GrantRejected, match="UNIT_INVALID"):
        service.launch(bad_unit)
    assert stub.calls == []


def test_systemd_identity_replacement_is_not_a_stop_target():
    os_fake = FakeSystemd()
    systemd = FixedCpuSystemd(test_only_runner=os_fake)
    systemd.launch(UNIT)
    os_fake.invocation = "c" * 32
    with pytest.raises(GrantRejected, match="INVOCATION_REPLACED"):
        systemd.request_stop(UNIT, INVOCATION)
    assert not any(call[0][3] == "stop" for call in os_fake.calls)


def test_systemd_device_isolation_missing_is_hold():
    stub = FakeSystemd()
    backend = FixedCpuSystemd(test_only_runner=stub)
    stub.private_devices = "no"
    with pytest.raises(GrantRejected, match="PROTECTION_OR_IDENTITY"):
        backend.snapshot(UNIT, require_running=True)


def test_invocation_cursor_log_page_is_bounded_and_verified():
    fake = FakeSystemd()
    systemd = FixedCpuSystemd(test_only_runner=fake)
    page = systemd.read_log_page(UNIT, INVOCATION)
    assert page["data"] == b"cpu-trial-start\n"
    assert page["cursor"] == "s=one;i=1"
    assert page["offset_contract_available"] is True
    next_page = systemd.read_log_page(UNIT, INVOCATION, cursor=page["cursor"])
    assert next_page["data"] == b""
    assert next_page["cursor"] == page["cursor"]
    assert fake.calls[-1][0][-1] == "--after-cursor=s=one;i=1"


@pytest.mark.parametrize("cursor", [
    "", "../secrets", "--no-pager", "s=one\\nwrong", "a" * 513,
])
def test_log_cursor_rejects_unsafe_values(cursor):
    fake = FakeSystemd()
    backend = FixedCpuSystemd(test_only_runner=fake)
    with pytest.raises(GrantRejected, match="LOG_CURSOR_INVALID_HOLD"):
        backend.read_log_page(UNIT, INVOCATION, cursor=cursor)
    assert fake.calls == []


@pytest.mark.parametrize("field,value", [
    ("log_invocation", "f" * 32),
    ("log_unit", "another.service"),
])
def test_log_must_belong_to_exact_unit_and_invocation(field, value):
    fake = FakeSystemd()
    setattr(fake, field, value)
    backend = FixedCpuSystemd(test_only_runner=fake)
    with pytest.raises(GrantRejected, match="LOG_ENTRY_SCOPE_UNVERIFIED_HOLD"):
        backend.read_log_page(UNIT, INVOCATION)


def test_protocol_log_cursor_only_on_scoped_read_log():
    from platform_core.os_supervisor_protocol import (
        SupervisorProtocolError, validate_request,
    )
    scope = {"handle_id": "a" * 32, "execution_generation": 3}
    request = {"version": 1, "request_id": "cursorrequest1234",
               "action": "read_log",
               "payload": {**scope, "cursor": "s=one;i=1"}}
    assert validate_request(request) == request
    for action, value in (
        ("read_log", "../secrets"),
        ("read_log", ""),
        ("inspect", "s=one;i=1"),
        ("stop", "s=one;i=1"),
    ):
        with pytest.raises(SupervisorProtocolError):
            validate_request({**request, "action": action,
                              "payload": {**scope, "cursor": value}})
