"""No shell, no arbitrary unit/path, never production-enabled."""
import pytest
from platform_core.os_supervisor_authorization import GrantRejected
from platform_core.os_supervisor_onnx_cpu_systemd_pilot import (
    IsolatedOnnxCpuSystemdPilot, build_fixed_onnx_cpu_argv,
)


def test_fixed_root_owned_cpu_systemd_only():
    handle = "a" * 32
    args = build_fixed_onnx_cpu_argv(handle)
    assert args[0] == "/usr/bin/systemd-run"
    assert "--unit=changlian-os-" + handle + ".service" in args
    for p in ("DynamicUser=yes", "PrivateDevices=yes", "DevicePolicy=closed",
              "PrivateNetwork=yes", "ProtectSystem=strict", "ExitType=cgroup",
              "KillMode=control-group"):
        assert "--property=" + p in args
    assert "--property=ReadOnlyPaths=/run/changlian-os-onnx-pilot-" + handle in args
    assert "/usr/bin/python3" in args and "/bin/sh" not in args


@pytest.mark.parametrize("value", [
    None, "", "a", "z"*32, "../etc", "a"*32+";rm", "a"*31+" ",
    1234, b"a"*32,
])
def test_agent_cannot_select_command_unit_or_path(value):
    with pytest.raises(GrantRejected, match="HANDLE_INVALID_HOLD"):
        build_fixed_onnx_cpu_argv(value)


def test_pilot_disabled_without_isolated_ci_only():
    with pytest.raises(GrantRejected, match="SANDBOX_DISABLED_HOLD"):
        IsolatedOnnxCpuSystemdPilot()
