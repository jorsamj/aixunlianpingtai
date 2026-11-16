"""Pure contract tests for the explicit CI-only trusted PT pilot."""
from pathlib import Path

import pytest

from platform_core.os_supervisor_authorization import GrantRejected
from platform_core.os_supervisor_pt_export_cpu_systemd_pilot import (
    IsolatedPtExportCpuPilot, StagedPtCpuFixture, build_fixed_pt_cpu_argv,
    parse_pt_export_log,
)


def test_fixed_cpu_service_has_no_agent_executable_or_network():
    argv = build_fixed_pt_cpu_argv("a" * 32)
    assert argv[:3] == (
        "/usr/bin/systemd-run", "--system", "--no-ask-password")
    text = "\n".join(argv)
    for required in (
        "DynamicUser=yes", "DevicePolicy=closed", "PrivateNetwork=yes",
        "ProtectSystem=strict", "NoNewPrivileges=yes", "CPUQuota=200%",
        "RuntimeMaxSec=180s", "RestrictAddressFamilies=AF_UNIX",
        "RuntimeDirectory=changlian-pt-output-" + "a" * 32,
    ):
        assert required in text
    assert "/var/lib/changlian-pt-export-cpu-pilot/venv/bin/python3" in text
    assert "/bin/sh" not in text
    assert "CUDA_VISIBLE_DEVICES" not in text  # private OS device boundary


@pytest.mark.parametrize("bad", [
    "../evil", "/etc/shadow", "", "0" * 31, "X" * 32, 5,
])
def test_no_untrusted_handles(bad):
    with pytest.raises(GrantRejected, match="HOLD"):
        build_fixed_pt_cpu_argv(bad)


def test_pilot_is_opt_in_only():
    with pytest.raises(GrantRejected, match="DISABLED_HOLD"):
        IsolatedPtExportCpuPilot()
    with pytest.raises(GrantRejected, match="DISABLED_HOLD"):
        IsolatedPtExportCpuPilot(isolated_ci_only=1)


def test_trusted_stage_does_not_convey_production_rights():
    frozen = StagedPtCpuFixture("a" * 32, Path("/run/x"), "f" * 64, 200)
    assert frozen.trusted_ci_generated
    assert frozen.production_launch_allowed is False
    assert frozen.result_publish_allowed is False
    assert frozen.trusted_stop_receipt_available is False


def test_result_log_parser_fails_closed():
    sha = "a" * 64
    good = {
        "source_sha256": sha, "onnx_sha256": "b" * 64,
        "onnx_size_bytes": 2048, "input_shape": [1, 3, 32, 32],
        "output_shape": [1, 84, 21], "input_sha256": "c" * 64,
        "cpu_provider": "CPUExecutionProvider", "max_abs_error": 0.00001,
        "runtime": "8.4.127", "opset": 12,
    }
    import json
    line = b"changlian-pt-export-proof:" + json.dumps(good).encode("ascii")
    assert parse_pt_export_log(line, sha) == good
    invalids = [
        line + b"\n" + line,
        line.replace(b"CPUExecutionProvider", b"CUDAExecutionProvider"),
        line.replace(b"8.4.127", b"0.0.0"),
        line.replace(b'"opset": 12', b'"opset": 13'),
        line.replace(b'"max_abs_error": 1e-05',
                     b'"max_abs_error": 0.01'),
        b"no result",
        b"changlian-pt-export-proof:{}",
    ]
    for invalid in invalids:
        with pytest.raises(GrantRejected, match="HOLD"):
            parse_pt_export_log(invalid, sha)


def test_proof_log_identity_rejects_forged_unit_before_any_os_call():
    instance = object.__new__(IsolatedPtExportCpuPilot)
    for invalid in (
        {}, {"unit_name": "../../etc/passwd", "invocation_id": "a" * 32},
        {"unit_name": "changlian-os-" + "a" * 32 + ".service",
         "invocation_id": "not-an-invocation"},
    ):
        with pytest.raises(GrantRejected, match="HOLD"):
            instance.read_export_proof_log(invalid)
