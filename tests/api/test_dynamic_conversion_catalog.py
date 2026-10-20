import pytest
import app as api
from fastapi import HTTPException
from tests.unit.test_dynamic_conversion_catalog import catalog, live


def test_resolve_uses_local_dictionary_sdk_identity_and_backend_defaults(tmp_path,monkeypatch):
    from platform_core.model_artifacts import ModelArtifactRepository
    monkeypatch.setattr(api,"DATA_DIR",tmp_path)
    ModelArtifactRepository(tmp_path).save_conversion_catalog(catalog(),expected_revision=0)
    monkeypatch.setattr(api,"_resolve_deploy_source",lambda *a:{"kind":"imported","path":str(tmp_path/"best.pt")})
    monkeypatch.setattr(api,"_deploy_resource_by_id",lambda *a:live())
    monkeypatch.setattr(api,"_detect_local_deploy_resource",lambda r:r)
    body=api.DeployJobReq(source_id="s",target="sophon",resource_id="s",params={"local_vendor_id":"local-s","local_chip_id":"chip-84"})
    result=api.v39_resolve_conversion("p",body)
    assert result["ready"] and result["params"]["chip"]=="bm1684" and result["params"]["precision"]=="fp32"
    assert result["params"]["local_chip_id"]!="bm1684"
    assert result["allowed_precisions"]==["fp32"]
    body.params["precision"]="fp16"
    assert api.v39_resolve_conversion("p",body)["ready"] is False


def test_job_cannot_bypass_dictionary_with_disabled_chip(tmp_path,monkeypatch):
    from platform_core.model_artifacts import ModelArtifactRepository
    monkeypatch.setattr(api,"DATA_DIR",tmp_path)
    data=catalog();data["chips"][0]["enabled"]=False
    ModelArtifactRepository(tmp_path).save_conversion_catalog(data,expected_revision=0)
    source=tmp_path/"best.pt";source.write_bytes(b"source")
    monkeypatch.setattr(api,"_resolve_deploy_source",lambda *a:{"kind":"imported","path":str(source)})
    monkeypatch.setattr(api,"_deploy_resource_by_id",lambda *a:live())
    monkeypatch.setattr(api,"_detect_local_deploy_resource",lambda r:r)
    monkeypatch.setattr(api,"_deploy_job_dir",lambda *a:pytest.fail("invalid job must fail before staging"))
    with pytest.raises(HTTPException) as e:
        api._v39_create_deploy_job_under_version_fence("p",api.DeployJobReq(source_id="s",target="sophon",resource_id="s",
            params={"chip":"bm1684","precision":"fp32","constraint_id":"tpu-mlir-1.30.2","local_vendor_id":"local-s","local_chip_id":"chip-84"}))
    assert e.value.status_code==400

def test_auto_conversion_can_resolve_unique_local_bm1684_without_fp16_override(tmp_path,monkeypatch):
    from tests.unit.test_dynamic_conversion_catalog import catalog, live
    from platform_core.model_artifacts import ModelArtifactRepository
    monkeypatch.setattr(api,"DATA_DIR",tmp_path)
    data=catalog();data["chips"]=data["chips"][:1]
    ModelArtifactRepository(tmp_path).save_conversion_catalog(data,expected_revision=0)
    resource={**live(),"mode":"remote"}
    monkeypatch.setattr(api,"_builtin_deploy_resources",lambda:[])
    monkeypatch.setattr(api,"_load_saved_deploy_resources",lambda:[resource])
    monkeypatch.setattr(api,"_deploy_resource_runtime",lambda r:r)
    monkeypatch.setattr(api,"_detect_remote_deploy_resource",lambda r:r)
    monkeypatch.setattr(api,"_v48_quality_reached",lambda j:True)
    submissions=[]
    monkeypatch.setattr(api,"v39_create_deploy_job",lambda p,b:submissions.append(b) or {"job":{"id":"auto"}})
    result=api._v48_auto_convert_version("p","a",{"id":"v","stored_path":"best.pt"},{"auto_convert_targets":["sophon"]})
    assert not result["errors"] and len(submissions)==1
    assert submissions[0].params["chip"]=="bm1684" and submissions[0].params["precision"]=="fp32"
    assert submissions[0].params["local_chip_id"]=="chip-84"

def test_resolver_and_history_share_actual_training_job_dimensions(tmp_path,monkeypatch):
    from platform_core.model_artifacts import ModelArtifactRepository
    monkeypatch.setattr(api,"DATA_DIR",tmp_path)
    ModelArtifactRepository(tmp_path).save_conversion_catalog(catalog(),expected_revision=0)
    monkeypatch.setattr(api,"project_dir",lambda *a:tmp_path)
    job=tmp_path/"jobs"/"train1";job.mkdir(parents=True)
    (job/"job.json").write_text('{"actual_train_params":{"imgsz":[384,800]},"runtime_precision":"fp32"}')
    version={"id":"v","job_id":"train1","stored_path":str(tmp_path/"best.pt")}
    monkeypatch.setattr(api,"list_algorithms_internal",lambda *a:[{"id":"a","versions":[version]}])
    monkeypatch.setattr(api,"_resolve_deploy_source",lambda *a:{"algorithm_id":"a","version_id":"v","path":version["stored_path"]})
    monkeypatch.setattr(api,"_deploy_resource_by_id",lambda *a:live())
    monkeypatch.setattr(api,"_detect_local_deploy_resource",lambda r:r)
    result=api.v39_resolve_conversion("p",api.DeployJobReq(source_id="src",target="sophon",resource_id="s",params={"local_vendor_id":"local-s","local_chip_id":"chip-84"}))
    defaults=api._version_deploy_conversion_defaults("p",version)
    assert (result["params"]["input_height"],result["params"]["input_width"])==(defaults["input_height"],defaults["input_width"])==(384,800)
    assert result["params"]["source_training_precision"]=="fp32"

def test_existing_onnx_shape_is_the_default_input_contract(tmp_path,monkeypatch):
    from platform_core.model_artifacts import ModelArtifactRepository
    from tests.unit.test_sophon_conversion import _onnx_identity
    monkeypatch.setattr(api,"DATA_DIR",tmp_path)
    ModelArtifactRepository(tmp_path).save_conversion_catalog(catalog(),expected_revision=0)
    path=tmp_path/"model.onnx";_onnx_identity(path,[1,3,384,640])
    monkeypatch.setattr(api,"_resolve_deploy_source",lambda *a:{"path":str(path),"kind":"imported"})
    monkeypatch.setattr(api,"_deploy_resource_by_id",lambda *a:live())
    monkeypatch.setattr(api,"_detect_local_deploy_resource",lambda r:r)
    body=api.DeployJobReq(source_id="s",target="sophon",resource_id="s",params={"local_vendor_id":"local-s","local_chip_id":"chip-84"})
    result=api.v39_resolve_conversion("p",body)
    assert result["ready"] and (result["params"]["input_height"],result["params"]["input_width"])==(384,640)
    assert "ONNX" in result["parameter_sources"]["input_shape"]
    body.params.update(input_height=640,input_width=640)
    mismatch=api.v39_resolve_conversion("p",body)
    assert not mismatch["ready"] and "Shape" in mismatch["errors"][0]


def test_catalog_management_metadata_does_not_change_saved_identities_or_external_config(tmp_path,monkeypatch):
    from platform_core.model_artifacts import ModelArtifactRepository
    monkeypatch.setattr(api,"DATA_DIR",tmp_path)
    monkeypatch.setattr(api,"v39_list_deploy_resources",lambda:{"items":[live()]})
    repo=ModelArtifactRepository(tmp_path);repo.save_conversion_catalog(catalog(),expected_revision=0)
    external=tmp_path/"external_algorithm_publish"/"config.json"
    external.parent.mkdir();external.write_text('{"keep":"mapping"}')
    before=repo.conversion_catalog()
    result=api.v39_conversion_catalog()
    assert result["chip_suggestions"] and result["chip_capabilities"]["chip-84"]["sdk_ready"]
    assert repo.conversion_catalog()==before
    changed={**before,"chips":[{**c,"name":"renamed"} if c["id"]=="chip-84" else c for c in before["chips"]]}
    saved=api.v39_save_conversion_catalog({**changed,"expected_revision":before["revision"]})
    assert saved["chips"][0]["id"]=="chip-84" and saved["chips"][0]["sdk_code"]=="bm1684"
    with pytest.raises(HTTPException) as error:
        api.v39_save_conversion_catalog({**before,"expected_revision":before["revision"]})
    assert error.value.status_code==409 and "刷新" in str(error.value.detail)
    assert external.read_text()=='{"keep":"mapping"}'


@pytest.mark.parametrize("mode",["pending_sdk","missing_resource","unknown_adapter"])
def test_catalog_management_never_admits_jobs_without_verified_sdk_evidence(tmp_path,monkeypatch,mode):
    from platform_core.model_artifacts import ModelArtifactRepository
    monkeypatch.setattr(api,"DATA_DIR",tmp_path)
    data=catalog();resource=live()
    if mode=="pending_sdk": data["chips"][0].update(sdk_code="",constraint_id="")
    if mode=="missing_resource": resource.update(status="missing",targets=[])
    if mode=="unknown_adapter": data["vendors"][0]["template_id"]="cambricon"
    ModelArtifactRepository(tmp_path).save_conversion_catalog(data,expected_revision=0)
    source=tmp_path/"best.pt";source.write_bytes(b"isolated source")
    monkeypatch.setattr(api,"_resolve_deploy_source",lambda *a:{"kind":"imported","path":str(source)})
    monkeypatch.setattr(api,"_deploy_resource_by_id",lambda *a:resource)
    monkeypatch.setattr(api,"_detect_local_deploy_resource",lambda r:r)
    monkeypatch.setattr(api,"_deploy_job_dir",lambda *a:pytest.fail("unverified dictionary must never stage a conversion"))
    with pytest.raises(HTTPException) as error:
        api._v39_create_deploy_job_under_version_fence("p",api.DeployJobReq(source_id="s",target="sophon",resource_id="s",
            params={"local_vendor_id":"local-s","local_chip_id":"chip-84"}))
    assert error.value.status_code==400
