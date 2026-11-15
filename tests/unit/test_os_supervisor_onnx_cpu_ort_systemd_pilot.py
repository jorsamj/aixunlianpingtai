"""2D-2B2 pure cross-platform fixed systemd contract."""
import json
import pytest
from platform_core.os_supervisor_authorization import GrantRejected
from platform_core.os_supervisor_onnx_cpu_ort_systemd_pilot import (
    build_fixed_onnx_ort_cpu_argv, parse_ort_result_log,
    IsolatedOnnxOrtSystemdPilot,
)

def test_fixed_argv():
    h = "a"*32
    argv = build_fixed_onnx_ort_cpu_argv(h)
    assert "--property=ReadOnlyPaths=/run/changlian-os-onnx-pilot-"+h in argv
    for key in ("DynamicUser=yes", "PrivateDevices=yes", "DevicePolicy=closed",
                "PrivateNetwork=yes", "ProtectSystem=strict", "MemoryMax=768M"):
        assert "--property="+key in argv
    assert argv[argv.index("--")+1] == "/run/changlian-onnxruntime-cpu-pilot/venv/bin/python3"
    assert "CPUExecutionProvider" in argv[argv.index("-c")+1]
    for bad in ("../h", h+"0", "", None):
        with pytest.raises(GrantRejected):
            build_fixed_onnx_ort_cpu_argv(bad)

def test_opt_in_required():
    with pytest.raises(GrantRejected, match="CPU_ONNX_SANDBOX_DISABLED_HOLD"):
        IsolatedOnnxOrtSystemdPilot()

def test_log_scope():
    sha="b"*64
    row=dict(model_sha256=sha, input_sha256="a"*64, output_sha256="c"*64,
             input_shape=[1,3,32,32], output_shape=[1,3,32,32],
             provider="CPUExecutionProvider", onnxruntime_version="1.22.1")
    log=b"changlian-onnx-ort-result:"+json.dumps(row).encode()+b"\n"
    assert parse_ort_result_log(log,sha)==row
    for bad in (b"", log+log, log.replace(b"CPUExecutionProvider",b"CUDAExecutionProvider"),
                log.replace(b"1.22.1",b"0.0.0")):
        with pytest.raises(GrantRejected):
            parse_ort_result_log(bad,sha)
    with pytest.raises(GrantRejected):
        parse_ort_result_log(log,"d"*64)
