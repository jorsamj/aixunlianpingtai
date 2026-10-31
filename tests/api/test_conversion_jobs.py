import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from platform_core.conversion import validate_target


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("target", "params", "error_code", "forbidden_suffix"),
    [
        ("ascend", {"soc_version": "Ascend310P3", "precision": "fp16"}, "ATC_NOT_FOUND", ".om"),
        ("rockchip", {"chip": "rk3568", "precision": "fp16"}, "RKNN_TOOLKIT_NOT_FOUND", ".rknn"),
        (
            "tensorrt",
            {"precision": "fp16", "target_environment": "test-gpu/cuda/tensorrt"},
            "TENSORRT_NOT_FOUND",
            ".engine",
        ),
    ],
)
def test_missing_vendor_compiler_fails_without_fake_artifact(
    tmp_path, target, params, error_code, forbidden_suffix
):
    job_dir = tmp_path / target
    source_dir = job_dir / "source"
    source_dir.mkdir(parents=True)
    source = source_dir / "source.onnx"
    source.write_bytes(b"not-used-before-compiler-check")
    job = {
        "id": f"job-{target}",
        "source_id": "test-source",
        "source_path": str(source),
        "source_trace": {"source_id": "test-source", "version_id": "v1", "sha256": "test"},
        "target": target,
        "resource": {"id": "missing-sdk", "name": "missing-sdk", "version": ""},
        "params": params,
        "status": "queued",
    }
    (job_dir / "job.json").write_text(json.dumps(job), encoding="utf-8")
    empty_path = tmp_path / "empty-path"
    empty_path.mkdir()
    environment = os.environ.copy()
    environment["PATH"] = str(empty_path)

    completed = subprocess.run(
        [sys.executable, str(ROOT / "deployment_worker.py"), "--job-dir", str(job_dir)],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        timeout=30,
    )
    assert completed.returncode != 0
    result = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    assert result["status"] == "failed"
    assert result["error_code"] == error_code
    assert not list((job_dir / "artifacts").rglob(f"*{forbidden_suffix}"))



def test_product_contract_rejects_rk3578_target_platform():
    with pytest.raises(ValueError, match="rk3568.*rk3576"):
        validate_target("rockchip", {"chip": "rk3578", "precision": "fp16"})



def test_rknn_preflight_blocks_incompatible_onnx_before_model_export(tmp_path, monkeypatch):
    import deployment_worker as worker

    fake_python = tmp_path / "rknn-python"
    fake_python.write_text("placeholder", encoding="utf-8")
    monkeypatch.setattr(worker, "probe_rknn_toolkit", lambda *_args, **_kwargs: {
        "available": False,
        "version": "2.3.2",
        "onnx_version": "1.20.0",
        "error_code": "RKNN_ONNX_DEPENDENCY_INCOMPATIBLE",
        "error": "RKNN-Toolkit2 与 ONNX 1.20.0 不兼容（缺少 onnx.mapping）。",
    })
    with pytest.raises(worker.ConversionError) as captured:
        worker.preflight_vendor_tool("rockchip", {"python_path": str(fake_python)}, {})
    assert captured.value.code == "RKNN_ONNX_DEPENDENCY_INCOMPATIBLE"
    assert "onnx.mapping" in str(captured.value)
    assert "onnx==1.18.0" in captured.value.solution


def test_existing_onnx_conversion_ships_explicit_csc_reference_without_weight_changes(tmp_path):
    import hashlib
    import onnx
    import numpy as np
    from onnx import helper, TensorProto
    job_dir=tmp_path/'csc-onnx';job_dir.mkdir()
    source=job_dir/'source.onnx'
    graph=helper.make_graph([helper.make_node('Identity',['images'],['output'])],'csc-contract',
        [helper.make_tensor_value_info('images',TensorProto.FLOAT,[1,3,32,32])],
        [helper.make_tensor_value_info('output',TensorProto.FLOAT,[1,3,32,32])])
    model=helper.make_model(graph,opset_imports=[helper.make_opsetid('',13)]);model.ir_version=10
    onnx.save(model,source);before=source.read_bytes()
    params={'input_size':32,'batch':1,'opset':13,'dynamic':False,'simplify':False,'precision':'fp32',
        'input_color_order':'rgb','source_color_order':'rgb',
        'csc':{'preset':'bt709_full','input_format':'NV12','deployment_contract_acknowledged':True}}
    job={'id':'csc-onnx','status':'queued','target':'onnx','source_id':'isolated-identity','source_path':str(source),
        'source_trace':{'sha256':hashlib.sha256(before).hexdigest()},'resource':{'python_path':sys.executable},'params':params}
    (job_dir/'job.json').write_text(json.dumps(job),encoding='utf-8')
    result=subprocess.run([sys.executable,str(ROOT/'deployment_worker.py'),'--job-dir',str(job_dir)],cwd=ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=45)
    assert result.returncode==0,(result.stdout+result.stderr)[-6000:]
    final=json.loads((job_dir/'job.json').read_text(encoding='utf-8'))
    manifest=json.loads(Path(final['manifest_path']).read_text(encoding='utf-8'))
    contract=manifest['execution_evidence']['csc']
    assert contract['preset']=='bt709_full' and contract['applied'] is False
    assert contract['execution_location']=='external_preprocessing' and contract['device_observed']=='unknown'
    assert manifest['parameters']['csc']==params['csc']
    assert {'csc_deployment_reference.zip','csc_deployment_contract.json'} <= {r['name'] for r in manifest['outputs']}
    assert source.read_bytes()==before
    assert (job_dir/'artifacts/source.onnx').read_bytes()==before
    raw=tmp_path/'raw.nv12';raw.write_bytes(bytes([100]*4+[90,240]));out=tmp_path/'decoded.npy'
    import zipfile
    reference_dir=tmp_path/'shipped-reference'
    with zipfile.ZipFile(job_dir/'artifacts/csc_deployment_reference.zip') as archive:archive.extractall(reference_dir)
    reference=subprocess.run([sys.executable,str(reference_dir/'csc_reference.py'),str(raw),str(out),'--width','2','--height','2','--preset','bt709_full','--input-format','NV12'],capture_output=True,text=True,timeout=15)
    assert reference.returncode==0,reference.stderr
    assert np.load(out).tolist()==[[[255,55,29]]*2]*2
