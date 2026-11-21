"""Real root-owned ONNX bytes read by DynamicUser inside CI-only systemd.

This is a fixed SHA256 OS workload, NOT an actual ORT execution inside systemd,
business Runner integration, central grant, GPU-node ACL or StopReceipt.
"""
import hashlib
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import time

import onnx
from onnx import TensorProto, helper
from platform_core.os_supervisor_onnx_cpu_pilot import CpuOnnxPilotPreflight
from platform_core.os_supervisor_onnx_cpu_systemd_pilot import IsolatedOnnxCpuSystemdPilot


def test_real_root_owned_onnx_fixed_systemd_cpu_unit():
    assert os.geteuid() == 0
    assert Path("/run/systemd/system").is_dir()
    graph = helper.make_graph(
        [helper.make_node("Identity", ["x"], ["y"])], "real_onnx",
        [helper.make_tensor_value_info("x", TensorProto.FLOAT, [1])],
        [helper.make_tensor_value_info("y", TensorProto.FLOAT, [1])])
    model = helper.make_model(graph, opset_imports=[helper.make_operatorsetid("", 12)])
    model.ir_version = 8
    data = model.SerializeToString()
    sha = hashlib.sha256(data).hexdigest()
    proof = CpuOnnxPilotPreflight(source_sha256=sha, size_bytes=len(data),
                                  input_size=32, _verified_bytes=data)
    backend = IsolatedOnnxCpuSystemdPilot(isolated_ci_only=True)
    staged = backend.stage(proof)
    unit = "changlian-os-" + staged.handle + ".service"
    attempted_launch = False
    try:
        assert not staged.production_launch_allowed
        assert (staged.root / "verified.onnx").read_bytes() == data
        assert (staged.root / "verified.onnx").stat().st_uid == 0

        nobody = pwd.getpwnam("nobody")
        def drop():
            os.setgroups([])
            os.setgid(nobody.pw_gid)
            os.setuid(nobody.pw_uid)
        denied = subprocess.run(
            ["/usr/bin/python3", "-c",
             "import sys;open(sys.argv[1],'wb').write(b'evil')",
             str(staged.root / "verified.onnx")],
            preexec_fn=drop, capture_output=True, timeout=5, check=False)
        assert denied.returncode != 0, "non-root wrote root-owned model"
        assert (staged.root / "verified.onnx").read_bytes() == data

        attempted_launch = True
        first = backend.launch(staged)
        assert first["main_pid"] > 1
        assert first["trusted_stop_receipt_available"] is False
        assert first["central_recovery_allowed"] is False
        expected = ("changlian-onnx-sandbox-verified:" + sha).encode()
        for _ in range(60):
            log = backend.backend.read_log_page(unit, first["invocation_id"])
            if expected in log["data"]:
                break
            time.sleep(0.2)
        else:
            raise AssertionError("isolated systemd never hashed the original ONNX")
        restarted = IsolatedOnnxCpuSystemdPilot(isolated_ci_only=True)
        assert restarted.backend.inspect(unit, first["invocation_id"])["invocation_id"] == first["invocation_id"]
        for _ in range(60):
            try:
                end = restarted.backend.verified_natural_exit(
                    unit, first["invocation_id"],
                    original_control_group=first["control_group"],
                    original_main_pid=first["main_pid"])
                break
            except PermissionError:
                time.sleep(0.2)
        else:
            raise AssertionError("fixed root-owned ONNX systemd unit not terminal")
        assert end["exit_code"] == 0
        assert not end["trusted_stop_receipt_available"]
    finally:
        if attempted_launch:
            # CI cleanup only; this systemctl ACK is NOT a StopReceipt.
            subprocess.run(["/usr/bin/systemctl", "--system", "stop", "--", unit],
                           capture_output=True, timeout=8, check=False)
        assert staged.root.parent == Path("/run")
        assert staged.root.name == "changlian-os-onnx-pilot-" + staged.handle
        shutil.rmtree(staged.root)
