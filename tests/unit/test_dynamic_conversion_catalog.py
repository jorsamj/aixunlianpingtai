import json
import pytest
from platform_core.model_artifacts import ModelArtifactRepository
from platform_core.compute_platform_catalog import conversion_templates, resolve_conversion_contract
from platform_core.conversion import validate_target
from platform_core.sophon_runtime import probe_sophon_toolchain
from tests.unit.test_sophon_conversion import _tool_fixture


def catalog():
    return {"vendors":[{"id":"local-s","name":"算能","template_id":"tpu-mlir","enabled":True},
                       {"id":"local-r","name":"瑞芯微","template_id":"rknn","enabled":True}],
            "chips":[{"id":"chip-84","vendor_id":"local-s","name":"BM1684","code":"S84",
                      "sdk_code":"bm1684","enabled":True,"constraint_id":"tpu-mlir-1.30.2"},
                     {"id":"chip-88","vendor_id":"local-s","name":"BM1688","code":"S88",
                      "sdk_code":"bm1688","enabled":True,"constraint_id":"tpu-mlir-1.30.2"}]}


def live():
    return {"id":"s","kind":"sophon","status":"ready","targets":["sophon"],
            "version":"v1.30.2-20260831","supported_chips":["bm1684","bm1688"],
            "sophon_probe":{"available":True,"version":"v1.30.2-20260831",
                            "supported_chips":["bm1684","bm1688"],"supported_precisions":["fp16","fp32"],
                            "chip_capabilities":{"bm1684":{"precisions":["fp32"],"chip_option":"--chip"},
                                                 "bm1688":{"precisions":["fp16"],"chip_option":"--chip"}}}}


def test_dictionary_is_empty_until_explicitly_saved_and_survives_restart(tmp_path):
    repo=ModelArtifactRepository(tmp_path)
    assert repo.conversion_catalog()["vendors"] == []
    assert len(conversion_templates()) == 5
    saved=repo.save_conversion_catalog(catalog(), expected_revision=0)
    assert saved["revision"] == 1
    assert ModelArtifactRepository(tmp_path).conversion_catalog() == saved
    with pytest.raises(ValueError,match="revision|并发"):
        repo.save_conversion_catalog(catalog(),expected_revision=0)
    assert len(saved["vendors"]) == 2


@pytest.mark.parametrize("change", ["duplicate","shell","wrong-vendor","arbitrary-command"])
def test_dictionary_rejects_unsafe_or_ambiguous_identity(tmp_path,change):
    data=catalog()
    if change=="duplicate": data["chips"].append(dict(data["chips"][0]))
    if change=="shell": data["chips"][0]["sdk_code"]="bm1684; touch /tmp/x"
    if change=="wrong-vendor": data["chips"][0]["vendor_id"]="absent"
    if change=="arbitrary-command": data["vendors"][0]["command"]="shell script"
    with pytest.raises(ValueError):
        ModelArtifactRepository(tmp_path).save_conversion_catalog(data,expected_revision=0)


def test_backend_resolves_bm1684_f32_rectangle_without_training_batch_or_precision():
    version={"training_lineage":{"parameters":{"actual":{"imgsz":[384,640],"batch":75,"precision":"fp32"}}},
             "label_codes":["smoke","fire"]}
    result=resolve_conversion_contract(catalog(),vendor_id="local-s",chip_id="chip-84",resource=live(),version=version,params={})
    assert result["ready"] and result["status"]=="convertible"
    p=result["params"]
    assert (p["chip"],p["precision"],p["input_height"],p["input_width"],p["batch"])==("bm1684","fp32",384,640,1)
    assert p["local_vendor_id"]=="local-s" and p["local_chip_id"]=="chip-84"
    assert p["template_id"]=="tpu-mlir" and p["template_version"]
    assert result["parameter_sources"]["precision"]=="SDK/芯片约束"
    assert "epochs" not in p and "workers" not in p
    assert validate_target("sophon",p)["precision"]=="fp32"
    with pytest.raises(ValueError):
        validate_target("sophon",{**p,"precision":"fp16"})


@pytest.mark.parametrize("mode,expected", [("offline","service_unavailable"),("unsupported","not_convertible"),
                                         ("unknown","pending_detection"),("adapter","not_adapted")])
def test_readiness_separates_dictionary_adapter_sdk_and_resource(mode,expected):
    data=catalog(); r=live()
    if mode=="offline": r["status"]="missing"
    if mode=="unsupported": r["supported_chips"]=["bm1688"]
    if mode=="unknown": r["sophon_probe"]["chip_capabilities"]={}
    if mode=="adapter": data["vendors"][0]["template_id"]="cambricon"
    result=resolve_conversion_contract(data,vendor_id="local-s",chip_id="chip-84",resource=r,version={},params={})
    assert not result["ready"] and result["status"]==expected and result["errors"]


def test_explicit_illegal_precision_not_silently_replaced():
    result=resolve_conversion_contract(catalog(),vendor_id="local-s",chip_id="chip-84",resource=live(),version={},params={"precision":"fp16"})
    assert not result["ready"] and "精度" in " ".join(result["errors"])


def test_probe_keeps_declared_targets_but_not_cartesian_precision(tmp_path):
    resource=_tool_fixture(tmp_path,chips="bm1684,bm1684x,bm1688,bm1690,unproved")
    deploy=tmp_path/"model_deploy.py"
    text=deploy.read_text().replace("1.18.0-fixture","1.30.2-fixture").replace("{F16,INT8}","{F32,F16,INT8}")
    deploy.write_text(text)
    facts=probe_sophon_toolchain(resource)
    assert facts["available"] and "bm1684" in facts["supported_chips"]
    assert "unproved" in facts["declared_chips"]
    assert facts["chip_capabilities"]["bm1684"]["precisions"] == ["fp32"]
    assert "fp16" not in facts["chip_capabilities"]["bm1684"]["precisions"]
    assert "unproved" not in facts["chip_capabilities"]

def test_bm1684_command_uses_real_target_precision_and_file_identity(tmp_path, monkeypatch):
    import deployment_worker as worker
    from pathlib import Path
    source=tmp_path/"input.onnx"; source.write_bytes(b"source")
    commands=[]
    monkeypatch.setattr(worker,"require_sophon_toolchain",lambda *a,**k:{
        "tools":{"model_transform":"transform.py","model_deploy":"deploy.py","model_tool":"model_tool"},
        "python_path":"python","version":"1.30.2","chip_option":"--processor",
        "chip_capabilities":{"bm1684":{"precisions":["fp32"],"chip_option":"--processor"}}})
    def run(argv,*a,**k):
        commands.append(argv)
        if "--mlir" in argv and "--model_def" in argv: Path(argv[argv.index("--mlir")+1]).write_bytes(b"mlir")
        if "--model" in argv: Path(argv[argv.index("--model")+1]).write_bytes(b"real fixture output")
        return "chip: BM1684"
    monkeypatch.setattr(worker,"run_cmd",run)
    p=resolve_conversion_contract(catalog(),vendor_id="local-s",chip_id="chip-84",resource=live(),version={},params={})["params"]
    model=worker.build_sophon(source,tmp_path,{},p,None,tmp_path/"log")
    command=next(c for c in commands if "--model" in c)
    assert command[command.index("--quantize")+1]=="F32"
    assert command[command.index("--processor")+1]=="bm1684"
    assert model.name.endswith("_bm1684_fp32.bmodel")
    assert any("--info" in c and str(model) in c for c in commands)
    facts=json.loads((tmp_path/"sophon_validation.json").read_text(encoding="utf-8"))
    assert facts["chip"]=="bm1684" and facts["precision"]=="fp32"
    assert facts["model_validation_status"]=="incomplete" and facts["hardware_verified"] is False

def test_rknn_config_probe_accepts_only_explicit_catalog_candidates(tmp_path,monkeypatch):
    import sys
    import platform_core.rknn_runtime as r
    commands=[]
    def run(argv,**kwargs):
        commands.append(argv)
        return type("Completed",(),{"returncode":0,"stdout":'{"version":"2.3.2","onnx_version":"1.18.0","onnx_mapping_available":true,"supported_chips":["rk3588","rk9999"]}',"stderr":""})()
    monkeypatch.setattr(r.subprocess,"run",run)
    facts=r.probe_rknn_toolkit(sys.executable,target_chips=["rk3588"])
    assert facts["supported_chips"]==["rk3588"]
    assert "rk3588" in commands[0][2] and "rk9999" not in commands[0][2]
    assert validate_target("rockchip",{"chip":"rk3588","constraint_id":"rknn-verified","precision":"fp16"})["chip"]=="rk3588"
    with pytest.raises(ValueError): r.probe_rknn_toolkit(sys.executable,target_chips=["rk3588;bad"])

def test_template_fields_and_preprocessing_values_follow_one_backend_contract():
    templates={t["id"]:t for t in conversion_templates()}
    assert {f["key"] for f in templates["tpu-mlir"]["advanced_fields"]} >= {"num_core","dynamic"}
    assert {f["key"] for f in templates["rknn"]["advanced_fields"]} >= {"mean","rknn_std"}
    result=resolve_conversion_contract(catalog(),vendor_id="local-s",chip_id="chip-84",resource=live(),version={},params={"num_core":2})
    assert not result["ready"] and "num_core" in result["errors"][0]
    with pytest.raises(ValueError,match="mean"):
        validate_target("rockchip",{"chip":"rk3568","mean":"0,nan,0"})


def test_existing_chip_identity_cannot_be_rebound(tmp_path):
    repo=ModelArtifactRepository(tmp_path)
    repo.save_conversion_catalog(catalog(),expected_revision=0)
    changed=catalog();changed["chips"][0]["sdk_code"]="bm1684x"
    with pytest.raises(ValueError,match="身份"):
        repo.save_conversion_catalog(changed,expected_revision=1)
    assert repo.conversion_catalog()["chips"][0]["sdk_code"]=="bm1684"

def test_portable_rectangle_keeps_exact_dimensions_and_local_identity():
    from platform_core.remote_execution_transport import RemoteExecutionTransportService
    params={"chip":"rk3568","precision":"fp16","input_height":384,"input_width":640,
            "local_vendor_id":"vendor-r","local_chip_id":"local-r68","sdk_chip_code":"rk3568",
            "template_id":"rknn","template_version":1,"constraint_id":"rknn-verified","sdk_version":"2.3.2"}
    result=RemoteExecutionTransportService._portable_conversion_params("rockchip",params)
    assert (result["input_height"],result["input_width"])==(384,640)
    assert result["local_chip_id"]=="local-r68" and result["template_version"]==1
    assert result["input_size"]==[384,640]

def test_generic_rknn_worker_uses_verified_new_sdk_target(tmp_path,monkeypatch):
    import deployment_worker as worker
    from pathlib import Path
    source=tmp_path/"model.onnx";source.write_bytes(b"onnx")
    monkeypatch.setattr(worker,"preflight_vendor_tool",lambda *a:None)
    commands=[]
    def run(argv,*a,**k):
        commands.append(argv);Path(argv[argv.index("--output")+1]).write_bytes(b"compiled-rknn-fixture")
        return ""
    monkeypatch.setattr(worker,"run_cmd",run)
    result=worker.build_rockchip(source,tmp_path,{},{"chip":"rk3588","precision":"fp16","constraint_id":"rknn-verified"},None,tmp_path/"log")
    assert result.is_file() and commands[0][commands[0].index("--chip")+1]=="rk3588"

def test_atlas_remote_health_soc_evidence_is_used_without_external_mapping():
    data={"vendors":[{"id":"atlas","name":"Atlas","template_id":"atlas-atc"}],
          "chips":[{"id":"local-310","vendor_id":"atlas","name":"310P3","code":"310","sdk_code":"Ascend310P3","constraint_id":"atc-detected"}]}
    result=resolve_conversion_contract(data,vendor_id="atlas",chip_id="local-310",version={},params={},
        resource={"id":"r","kind":"ascend","status":"ready","targets":["ascend"],"remote_health":{"tools":{"soc_versions":["Ascend310P3"]}}})
    assert result["ready"] and result["params"]["soc_version"]=="Ascend310P3"

def test_frozen_preprocessing_is_inherited_and_unsupported_semantics_are_rejected():
    version={"model_input_contract":{"preprocessing":{"owner":"caller","pixel_format":"bgr","mean":[0,0,0],"scale":[1,1,1],"letterbox":False},"postprocessing":{"nms":"external","coordinates":"xywh"}}}
    result=resolve_conversion_contract(catalog(),vendor_id="local-s",chip_id="chip-84",resource=live(),version=version,params={})
    assert result["ready"] and result["params"]["preprocessing"]["pixel_format"]=="bgr"
    assert result["params"]["preprocessing"]["letterbox"] is False
    assert result["parameter_sources"]["preprocessing"]=="训练成果继承"
    assert result["params"]["model_output_contract"]==version["model_input_contract"]["postprocessing"]
    bad={**result["params"],"preprocessing":{**result["params"]["preprocessing"],"pad_value":0}}
    with pytest.raises(ValueError,match="pad_value"): validate_target("sophon",bad)

def test_chip_constraints_are_version_bound_and_legacy_fp16_does_not_advertise_fp32():
    data=catalog();r=live();r["sophon_probe"]["version"]="v1.31.0"
    changed=resolve_conversion_contract(data,vendor_id="local-s",chip_id="chip-88",resource=r,version={},params={})
    assert not changed["ready"] and changed["status"]=="pending_detection"
    data["chips"][1]["constraint_id"]="sophon-fp16-verified"
    r=live()
    r["sophon_probe"]["supported_precisions"]=["fp16","fp32"]
    r["sophon_probe"]["chip_capabilities"]["bm1688"]["precisions"]=["fp16","fp32"]
    legacy=resolve_conversion_contract(data,vendor_id="local-s",chip_id="chip-88",resource=r,version={},params={})
    assert legacy["ready"] and legacy["allowed_precisions"]==["fp16"]


def test_unknown_chip_can_be_saved_without_inventing_sdk_and_never_passes_admission(tmp_path):
    repo=ModelArtifactRepository(tmp_path)
    data=catalog()
    data["chips"].append({"id":"chip-pending","vendor_id":"local-s","name":"Unconfirmed 9000",
                          "code":"pending-9000","sdk_code":"","constraint_id":"","enabled":True})
    data["chips"].append({**data["chips"][-1],"id":"pending-second","code":"pending-second"})
    saved=repo.save_conversion_catalog(data,expected_revision=0)
    assert saved["chips"][-1]["sdk_code"]==saved["chips"][-1]["constraint_id"]==""
    result=resolve_conversion_contract(saved,vendor_id="local-s",chip_id="chip-pending",resource=live(),version={},params={})
    assert not result["ready"] and result["status"]=="pending_configuration"
    assert "SDK" in result["errors"][0]


def test_catalog_suggestions_and_detection_share_the_real_chip_contract():
    from platform_core.compute_platform_catalog import conversion_catalog_metadata
    data=catalog()
    metadata=conversion_catalog_metadata(data,resources=[live()])
    suggestions={(x["template_id"],x["name"]):x for x in metadata["chip_suggestions"]}
    assert suggestions[("tpu-mlir","BM1684")]["constraint_id"]=="tpu-mlir-1.30.2"
    assert suggestions[("tpu-mlir","BM1684X")]["sdk_code"]=="bm1684x"
    assert suggestions[("rknn","RK3568")]["constraint_id"]=="rknn-verified"
    assert ("tpu-mlir","Unconfirmed 9000") not in suggestions
    capability=metadata["chip_capabilities"]["chip-84"]
    assert capability["sdk_ready"] and capability["allowed_precisions"]==["fp32"]
    missing=conversion_catalog_metadata(data,resources=[])["chip_capabilities"]["chip-84"]
    assert not missing["sdk_ready"] and missing["status"]=="service_unavailable"
    bad=live();bad["sophon_probe"]["version"]="v1.31.0"
    blocked=conversion_catalog_metadata(data,resources=[bad])["chip_capabilities"]["chip-84"]
    assert not blocked["sdk_ready"] and blocked["status"]=="pending_detection" and "SDK" in blocked["errors"][0]
    data["chips"][0]["enabled"]=False
    assert not conversion_catalog_metadata(data,resources=[live()])["chip_capabilities"]["chip-84"]["sdk_ready"]


def test_existing_vendor_template_cannot_reinterpret_historical_chips(tmp_path):
    repo=ModelArtifactRepository(tmp_path)
    repo.save_conversion_catalog(catalog(),expected_revision=0)
    data=catalog();data["vendors"][0]["template_id"]="rknn"
    with pytest.raises(ValueError,match="身份|模板"):
        repo.save_conversion_catalog(data,expected_revision=1)
    assert repo.conversion_catalog()["vendors"][0]["template_id"]=="tpu-mlir"
