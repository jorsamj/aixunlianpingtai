"""True Ubuntu CI systemd ORT graph execution; no production tasks."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import time
import numpy as np
import onnx
from onnx import helper, TensorProto
from platform_core.os_supervisor_onnx_cpu_pilot import CpuOnnxPilotPreflight
from platform_core.os_supervisor_onnx_cpu_ort_systemd_pilot import (
    IsolatedOnnxOrtSystemdPilot, parse_ort_result_log,
)

def stage():
    vi=helper.make_tensor_value_info
    graph=helper.make_graph(
        [helper.make_node("Identity",["images"],["pred"])],"real_ort",
        [vi("images",TensorProto.FLOAT,[1,3,32,32])],
        [vi("pred",TensorProto.FLOAT,[1,3,32,32])])
    model=helper.make_model(graph,opset_imports=[helper.make_operatorsetid("",12)])
    model.ir_version=8
    data=model.SerializeToString()
    sha=hashlib.sha256(data).hexdigest()
    pilot=IsolatedOnnxOrtSystemdPilot(isolated_ci_only=True)
    frozen=pilot.stage(CpuOnnxPilotPreflight(
        source_sha256=sha,size_bytes=len(data),input_size=32,_verified_bytes=data))
    return pilot,frozen

def result(pilot,first,sha):
    for _ in range(90):
        page=pilot.backend.read_log_page(first["unit_name"],first["invocation_id"])
        try:
            return parse_ort_result_log(page["data"],sha)
        except PermissionError:
            time.sleep(.2)
    raise AssertionError("no ORT inference evidence in original InvocationID")

def cleanup(staged):
    unit="changlian-os-"+staged.handle+".service"
    subprocess.run(["/usr/bin/systemctl","--system","stop","--",unit],
                   capture_output=True,timeout=8,check=False)
    assert staged.root.parent==Path("/run")
    assert staged.root.name=="changlian-os-onnx-pilot-"+staged.handle
    shutil.rmtree(staged.root)

def test_real_ort_cpu_natural_exit_and_reattach():
    assert os.geteuid()==0
    pilot,frozen=stage()
    try:
        first=pilot.launch(frozen)
        assert first["main_pid"]>1 and not first["trusted_stop_receipt_available"]
        proof=result(pilot,first,frozen.sha256)
        expected=np.arange(3072,dtype=np.float32).reshape(1,3,32,32)
        expected/=float(expected.size+1)
        digest=hashlib.sha256(expected.tobytes()).hexdigest()
        assert proof["input_sha256"]==proof["output_sha256"]==digest
        assert proof["input_shape"]==proof["output_shape"]==[1,3,32,32]
        reopened=IsolatedOnnxOrtSystemdPilot(isolated_ci_only=True)
        for _ in range(90):
            try:
                end=reopened.backend.verified_natural_exit(
                    first["unit_name"],first["invocation_id"],
                    original_control_group=first["control_group"],
                    original_main_pid=first["main_pid"])
                break
            except PermissionError:
                time.sleep(.2)
        else:
            raise AssertionError("ORT unit did not naturally exit")
        assert end["exit_code"]==0 and not end["trusted_stop_receipt_available"]
    finally:
        cleanup(frozen)

def test_cancel_is_not_trusted_stop():
    assert os.geteuid()==0
    pilot,frozen=stage()
    try:
        first=pilot.launch(frozen)
        result(pilot,first,frozen.sha256)
        out=pilot.backend.request_stop(first["unit_name"],first["invocation_id"])
        assert out["state"]=="UNKNOWN" and out["stop_requested"]
        assert not out["trusted_stop_receipt_available"]
    finally:
        cleanup(frozen)
