"""Real YOLO11n .pt -> ONNX inside non-root systemd, ephemeral Ubuntu CI ONLY.

Not a production execution test or a verified central stop receipt.
The ONLY pickle in this test is built from installed pinned library YAML by
the root-owned generator on the isolated test VM.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import time

import numpy as np
import onnx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from platform_core.os_supervisor_authorization import GrantRejected
from platform_core.os_supervisor_pt_export_cpu_systemd_pilot import (
    IsolatedPtExportCpuPilot, parse_pt_export_log,
)


def _cleanup(staged):
    unit = "changlian-os-" + staged.handle + ".service"
    subprocess.run(
        ["/usr/bin/systemctl", "--system", "stop", "--", unit],
        capture_output=True, timeout=12, check=False)
    assert staged.root.parent == Path("/run")
    assert staged.root.name == "changlian-os-pt-pilot-" + staged.handle
    shutil.rmtree(staged.root)
    output = Path("/run/changlian-pt-output-" + staged.handle)
    if output.is_dir():
        # The isolated unit owns its private test output; cleanup only the
        # exact random RuntimeDirectory after the unit has been stopped.
        shutil.rmtree(output)


def _wait_result(pilot, first, expected_source_sha):
    deadline = time.monotonic() + 150
    while time.monotonic() < deadline:
        page = pilot.backend.read_log_page(
            first["unit_name"], first["invocation_id"])
        try:
            return parse_pt_export_log(page["data"], expected_source_sha)
        except GrantRejected:
            time.sleep(.6)
    raise AssertionError("trusted PT export proof not found in original systemd invocation")


def _wait_exit(pilot, first):
    deadline = time.monotonic() + 150
    while time.monotonic() < deadline:
        try:
            return pilot.backend.verified_natural_exit(
                first["unit_name"], first["invocation_id"],
                original_control_group=first["control_group"],
                original_main_pid=first["main_pid"],
            )
        except GrantRejected:
            time.sleep(.6)
    raise AssertionError("PT export unit did not naturally exit")


def test_real_yolo11n_pt_to_onnx_cpu_export_and_onnxruntime_consistency():
    assert os.geteuid() == 0
    assert Path("/run/systemd/system").is_dir()
    pilot = IsolatedPtExportCpuPilot(isolated_ci_only=True)
    staged = pilot.generate_trusted_fixture()
    assert staged.source_size_bytes > 1_000_000
    assert staged.source_size_bytes < 64 * 1024 * 1024
    assert staged.production_launch_allowed is False
    first = None
    try:
        first = pilot.launch(staged)
        assert first["main_pid"] > 1
        assert first["control_group"] == "/system.slice/" + first["unit_name"]
        assert first["production_launch_allowed"] is False
        assert first["result_publish_allowed"] is False
        with pytest.raises(GrantRejected, match="LAUNCH_ALREADY_CONSUMED_HOLD"):
            pilot.launch(staged)
        evidence = _wait_result(pilot, first, staged.source_sha256)
        output = Path("/run/changlian-pt-output-" + staged.handle) / "source.onnx"
        assert output.is_file()
        onnx_bytes = output.read_bytes()
        assert len(onnx_bytes) == evidence["onnx_size_bytes"]
        assert hashlib.sha256(onnx_bytes).hexdigest() == evidence["onnx_sha256"]
        assert evidence["max_abs_error"] < 0.001
        assert evidence["runtime"] == "8.4.127"
        assert evidence["cpu_provider"] == "CPUExecutionProvider"
        model = onnx.load_from_string(onnx_bytes)
        assert not any(t.external_data for t in model.graph.initializer)
        onnx.checker.check_model(model)
        assert evidence["input_shape"] == [1, 3, 32, 32]
        assert evidence["output_shape"][0] == 1
        end = _wait_exit(pilot, first)
        assert end["exit_code"] == 0
        assert end["cgroup_exit_type_verified"] is True
        assert end["trusted_stop_receipt_available"] is False
        # Reattached after OS exit: exactly the same original InvocationID.
        reopened = IsolatedPtExportCpuPilot(isolated_ci_only=True)
        again = reopened.backend.verified_natural_exit(
            first["unit_name"], first["invocation_id"],
            original_control_group=first["control_group"],
            original_main_pid=first["main_pid"],
        )
        assert again["exit_code"] == 0
        print("TRUSTED_YOLO_PT_ONNX_EVIDENCE", evidence, flush=True)
    finally:
        _cleanup(staged)


def test_pt_tamper_fails_before_any_systemd_run():
    assert os.geteuid() == 0
    pilot = IsolatedPtExportCpuPilot(isolated_ci_only=True)
    staged = pilot.generate_trusted_fixture()
    try:
        source = staged.root / "source.pt"
        os.chmod(source, 0o644)
        source.write_bytes(b"tampered-not-a-trusted-weight")
        os.chmod(source, 0o444)
        with pytest.raises(GrantRejected, match="HOLD"):
            pilot.launch(staged)
        assert not (staged.root / ".launch-consumed").exists()
    finally:
        _cleanup(staged)


def test_pt_symlink_input_fails_before_systemd_run():
    assert os.geteuid() == 0
    pilot = IsolatedPtExportCpuPilot(isolated_ci_only=True)
    staged = pilot.generate_trusted_fixture()
    try:
        original = staged.root / "source.pt"
        original.rename(staged.root / "saved-source.pt")
        original.symlink_to(staged.root / "saved-source.pt")
        with pytest.raises(GrantRejected, match="HOLD"):
            pilot.launch(staged)
    finally:
        _cleanup(staged)
