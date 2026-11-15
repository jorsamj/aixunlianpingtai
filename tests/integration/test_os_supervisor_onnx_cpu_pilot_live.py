"""True CPU-provider ONNX validation by existing deployment_worker.py.

Runs as an isolated ordinary CI user, not via Supervisor or a central grant.
Never claims remote production conversion or trusted StopReceipt.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from platform_core.os_supervisor_onnx_cpu_pilot import preflight_existing_onnx_cpu_pilot

ROOT = Path(__file__).resolve().parents[2]


def test_real_existing_onnx_cpu_provider_validation(tmp_path):
    import onnx
    import onnxruntime as ort
    from onnx import TensorProto, helper

    inp = tmp_path / "input"
    inp.mkdir()
    src = inp / "model.onnx"
    vi = helper.make_tensor_value_info
    graph = helper.make_graph(
        [helper.make_node("Identity", ["images"], ["pred"])],
        "actual_cpu_identity",
        [vi("images", TensorProto.FLOAT, [1, 3, 32, 32])],
        [vi("pred", TensorProto.FLOAT, [1, 3, 32, 32])],
    )
    model = helper.make_model(
        graph, opset_imports=[helper.make_operatorsetid("", 12)])
    model.ir_version = 8
    onnx.save(model, src)
    sha = hashlib.sha256(src.read_bytes()).hexdigest()
    params = {"input_size": 32, "batch": 1, "opset": 12,
              "dynamic": False, "simplify": False, "precision": "fp32"}
    payload = {
        "schema_version": 1, "task_kind": "MODEL_CONVERSION",
        "transport": "object-storage-v1", "target": "onnx",
        "params": params,
        "source": {"type": "object", "download": {
            "method": "GET", "file_name": src.name,
            "size_bytes": src.stat().st_size, "sha256": sha}},
        "source_trace": {"source_id": "ci-only", "version_id": "frozen",
                         "sha256": sha},
        "output": {"type": "object", "storage_ref": {},
                   "upload_protocol": "prepare-after-local-hash-v1"},
    }
    proof = preflight_existing_onnx_cpu_pilot(
        payload, source_file=src, trusted_workdir=tmp_path)
    assert proof.source_sha256 == sha
    assert proof.production_launch_allowed is False

    folder = tmp_path / "conversion"
    folder.mkdir()
    (folder / "job.json").write_text(json.dumps({
        "id": "cpu-only-pilot", "status": "queued",
        "source_path": str(src), "source_name": src.name,
        "source_trace": payload["source_trace"],
        "target": "onnx", "params": params, "calibration_dir": "",
        "resource": {"id": "agent-onnx", "kind": "onnx", "mode": "local"},
        "outputs": [],
    }), encoding="utf-8")
    env = {**os.environ, "CUDA_VISIBLE_DEVICES": "-1",
           "HIP_VISIBLE_DEVICES": "-1", "ROCR_VISIBLE_DEVICES": "-1",
           "PYTHONPATH": str(ROOT), "PYTHONUTF8": "1"}
    proc = subprocess.run(
        [sys.executable, str(ROOT / "deployment_worker.py"),
         "--job-dir", str(folder)], cwd=str(ROOT), env=env,
        shell=False, capture_output=True, text=True, timeout=45,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-3000:]
    job = json.loads((folder / "job.json").read_text(encoding="utf-8"))
    manifest = json.loads(
        (folder / "artifacts" / "manifest.json").read_text(encoding="utf-8"))
    artifact = folder / "artifacts" / src.name
    assert job["status"] == "done"
    assert job["runtime_verified"] is True
    assert manifest["status"] == "runtime_verified"
    assert manifest["execution_evidence"]["onnx_export"] == "reused_existing_onnx"
    assert manifest["execution_evidence"]["onnx_export_parameters_applied"] is False
    assert hashlib.sha256(artifact.read_bytes()).hexdigest() == sha
    session = ort.InferenceSession(
        str(artifact), providers=["CPUExecutionProvider"])
    assert session.get_providers() == ["CPUExecutionProvider"]
