import json
from pathlib import Path

import pytest

import deployment_worker as worker
from platform_core.conversion import validate_target, derive_version_conversion_defaults


@pytest.mark.parametrize("params", [{}, {"chip":"bm1690"}, {"chip":"bm1684x","precision":"fp32"},
    {"chip":"bm1688","batch":2}, {"chip":"bm1688","dynamic":True}, {"chip":"bm1688","num_core":2}])
def test_sophon_rejects_unsupported_or_implicit_target(params):
    with pytest.raises(ValueError):
        validate_target("sophon", params)


@pytest.mark.parametrize("chip", ["bm1684x", "BM1688"])
def test_sophon_normalizes_explicit_fp16_static_batch_one(chip):
    values = validate_target("sophon", {"chip":chip})
    assert values["chip"] == chip.lower()
    assert values["precision"] == "fp16" and values["batch"] == 1
    assert values["preprocessing"]["owner"] == "caller"


def test_training_rectangle_remains_default_rectangle():
    values=derive_version_conversion_defaults({"training_lineage":{"parameters":{"actual":{"imgsz":[384,640]}}}})
    assert (values["input_height"], values["input_width"]) == (384,640)


def test_pt_export_uses_explicit_rectangle_without_interpolating_source(tmp_path, monkeypatch):
    source=tmp_path/"best'quoted.pt"; source.write_bytes(b"isolated-source")
    out=tmp_path/"out";out.mkdir()
    commands=[]
    def run(argv,*args,**kwargs):
        commands.append(argv)
        source.with_suffix(".onnx").write_bytes(b"isolated-export")
        return ""
    monkeypatch.setattr(worker,"run_cmd",run)
    worker.export_pt_to_onnx(source,out,{}, {"input_height":384,"input_width":640,"input_size":800},tmp_path/"log")
    script=commands[0][2]
    assert "imgsz=[384, 640]" in script
    assert str(source) not in script
    assert str(source) in commands[0][3:]


def _onnx_identity(path, shape):
    import onnx
    from onnx import helper, TensorProto
    model=helper.make_model(helper.make_graph([helper.make_node("Identity",["images"],["output"])],"shape-test",
        [helper.make_tensor_value_info("images",TensorProto.FLOAT,shape)],
        [helper.make_tensor_value_info("output",TensorProto.FLOAT,shape)]),opset_imports=[helper.make_opsetid("",12)])
    model.ir_version=9
    onnx.save(model,str(path))


def test_sophon_rejects_onnx_shape_that_differs_from_compilation(tmp_path):
    path=tmp_path/"model.onnx";_onnx_identity(path,[1,3,640,640])
    with pytest.raises(worker.ConversionError,match="shape|尺寸"):
        worker.validate_onnx_runtime(path,{"kind":"sophon","chip":"bm1688","input_height":384,"input_width":640},tmp_path/"log")


def test_sophon_records_actual_onnx_rectangle(tmp_path):
    path=tmp_path/"model.onnx";_onnx_identity(path,[1,3,384,640])
    facts=worker.validate_onnx_runtime(path,{"kind":"sophon","chip":"bm1684x","input_height":384,"input_width":640},tmp_path/"log")
    assert facts["input_shapes"] == [[1,3,384,640]]



def test_sophon_preflight_missing_tools_is_classified_before_export(monkeypatch):
    monkeypatch.setattr(worker,"find_tpu_tools",lambda resource:(None,None,None))
    with pytest.raises(worker.ConversionError) as error:
        worker.preflight_vendor_tool("sophon", {"python_path":"/nonexistent/python"}, {"chip":"bm1684x"})
    assert error.value.code in {"TPU_MLIR_NOT_FOUND","TPU_MLIR_UNAVAILABLE"}


@pytest.mark.parametrize("chip", ["bm1684x", "bm1688"])
def test_sophon_build_checks_nonempty_artifact_and_does_not_fuse_preprocessing(tmp_path,monkeypatch,chip):
    source=tmp_path/"input.onnx";source.write_bytes(b"isolated-onnx")
    monkeypatch.setattr(worker,"find_tpu_tools",lambda resource:("transform.py","deploy.py",None))
    monkeypatch.setattr(worker,"require_sophon_toolchain",lambda *args,**kwargs:{"tools":{"model_transform":"transform.py","model_deploy":"deploy.py","model_tool":"model_tool"},"python_path":"python","version":"fixture"})
    commands=[]
    def run(argv,*args,**kwargs):
        commands.append(argv)
        if "--mlir" in argv and "--model_def" in argv:
            Path(argv[argv.index("--mlir")+1]).write_bytes(b"isolated-mlir")
        if "--model" in argv:
            Path(argv[argv.index("--model")+1]).write_bytes(b"")
        return ""
    monkeypatch.setattr(worker,"run_cmd",run)
    with pytest.raises((worker.ConversionError,ValueError), match="为空|empty"):
        worker.build_sophon(source,tmp_path,{}, {"chip":chip,"precision":"fp16","input_height":384,"input_width":640},None,tmp_path/"log")
    assert not any("--fuse_preprocess" in cmd for cmd in commands)
    assert not any("--mean" in cmd for cmd in commands)



def _tool_fixture(root, *, chips="bm1684x,bm1688,cv186x", broken=False):
    import sys
    tools={}
    for name in ("model_transform", "model_deploy", "model_tool", "run_calibration"):
        path=root/(name+".py")
        script="import sys,json; from pathlib import Path\na=sys.argv[1:]\n"
        if name == "model_deploy":
            script += f"if '--help' in a: print('--chip {{{chips}}} --quantize {{F16,INT8}}'); sys.exit({1 if broken else 0})\n"
            script += "if '--version' in a: print('TPU-MLIR 1.18.0-fixture'); sys.exit(0)\n"
            script += "Path(a[a.index('--model')+1]).write_bytes(b'isolated-bmodel-protocol-fixture')\n"
        elif name == "model_transform":
            script += "if '--help' in a: print('--model_def --input_shapes --mlir'); sys.exit(0)\n"
            script += "Path(a[a.index('--mlir')+1]).write_text('isolated-MLIR-protocol-fixture')\n"
        elif name == "model_tool":
            script += "if '--help' in a: print('--info model.bmodel'); sys.exit(0)\n"
            script += "print('chip: '+('BM1688' if 'bm1688' in a[-1] else 'BM1684X'))\n"
        else:
            script += "print('--dataset --input_num')\n"
        path.write_text(script,encoding="utf-8");tools[name+"_path"]=str(path)
    return {"python_path":sys.executable,**tools}


def test_sophon_probe_executes_tools_and_limits_advertised_chips(tmp_path):
    from platform_core.sophon_runtime import probe_sophon_toolchain
    facts=probe_sophon_toolchain(_tool_fixture(tmp_path))
    assert facts["available"] and facts["version"] == "1.18.0-fixture"
    assert facts["supported_chips"] == ["bm1684x","bm1688"]
    assert facts["supported_precisions"] == ["fp16"]
    assert facts["calibration_available"]


def test_sophon_probe_existing_but_broken_tools_are_unavailable(tmp_path):
    from platform_core.sophon_runtime import probe_sophon_toolchain
    facts=probe_sophon_toolchain(_tool_fixture(tmp_path,broken=True))
    assert not facts["available"] and facts["error_code"] == "TPU_MLIR_UNAVAILABLE"
    assert facts["supported_chips"] == []
    assert "model_deploy" in facts["error"]


def test_sophon_probe_requires_configured_python_even_if_tools_exist(tmp_path):
    from platform_core.sophon_runtime import probe_sophon_toolchain
    resource=_tool_fixture(tmp_path);resource.pop("python_path")
    facts=probe_sophon_toolchain(resource)
    assert not facts["available"] and "python_path" in facts["error"]


@pytest.mark.parametrize("chip", ["bm1684x","bm1688"])
def test_sophon_worker_isolated_tool_protocol_records_manifest_and_unverified_state(tmp_path,monkeypatch,chip):
    from platform_core.conversion import sha256_file
    from platform_core.deployment.conversion_tasks import conversion_outcome
    from platform_core.task_runtime import TaskStatus
    # These scripts implement the tool process protocol, not the TPU compiler.
    # The ONNX checker/runtime and subprocess/file identity checks are real.
    resource=_tool_fixture(tmp_path)
    source=tmp_path/"model.onnx";_onnx_identity(source,[1,3,384,640])
    trace={"version_id":"v1","sha256":sha256_file(source),"label_codes":["smoke","fire"]}
    job={"id":"isolated-"+chip,"target":"sophon","source_path":str(source),"source_trace":trace,
         "resource":resource,"params":{"chip":chip,"input_height":384,"input_width":640}}
    (tmp_path/"job.json").write_text(json.dumps(job))
    monkeypatch.setattr("sys.argv",["deployment_worker.py","--job-dir",str(tmp_path)])
    worker.main()
    finished=json.loads((tmp_path/"job.json").read_text(encoding="utf-8"))
    manifest=json.loads((tmp_path/"artifacts/manifest.json").read_text(encoding="utf-8"))
    assert finished["status"] == "done" and finished["validation_status"] == "converted_unverified"
    assert conversion_outcome(finished) is TaskStatus.BLOCKED_BY_HARDWARE
    assert manifest["target"]["chip"] == chip
    assert manifest["source"] == trace
    assert manifest["onnx"]["input_shapes"] == [[1,3,384,640]]
    assert manifest["tool"]["version"] == "1.18.0-fixture"
    assert manifest["sophon_validation"]["structure"] == "passed" and not manifest["hardware_verified"]
    record=next(row for row in manifest["outputs"] if row["name"].endswith(".bmodel"))
    model=tmp_path/"artifacts"/record["name"]
    assert record["sha256"] == sha256_file(model) and record["size_bytes"] == model.stat().st_size > 0
    log=(tmp_path/"convert.log").read_text(encoding="utf-8")
    assert "--chip "+chip in log and "--input_shapes" in log
    assert "--mean" not in log and "--fuse_preprocess" not in log


def test_sophon_worker_failure_never_publishes_stale_bmodel(tmp_path,monkeypatch):
    resource=_tool_fixture(tmp_path)
    source=tmp_path/"model.onnx";_onnx_identity(source,[1,3,384,640])
    tools=tmp_path/"model_deploy.py"
    tools.write_text(tools.read_text(encoding="utf-8")+"\nraise RuntimeError('isolated compile failure')\n")
    job={"id":"failed-fixture","target":"sophon","source_path":str(source),"resource":resource,
         "params":{"chip":"bm1688","input_height":384,"input_width":640}}
    (tmp_path/"job.json").write_text(json.dumps(job))
    monkeypatch.setattr("sys.argv",["deployment_worker.py","--job-dir",str(tmp_path)])
    with pytest.raises(RuntimeError,match="命令执行失败"):
        worker.main()
    finished=json.loads((tmp_path/"job.json").read_text(encoding="utf-8"))
    assert finished["status"] == "failed"
    assert not list((tmp_path/"artifacts").glob("*.bmodel"))
