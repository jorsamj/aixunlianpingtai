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


def test_catalog_crud_api_uses_one_record_operations_and_authoritative_query(tmp_path,monkeypatch):
    monkeypatch.setattr(api,"DATA_DIR",tmp_path)
    monkeypatch.setattr(api,"v39_list_deploy_resources",lambda:{"items":[]})
    body={"entity":"vendors","action":"create","operation_id":"api-create","expected_revision":0,"record":{"name":"vendor","template_id":"rknn"}}
    result=api.v39_catalog_operation(body)
    replay=api.v39_catalog_operation(body)
    assert result["id"]==replay["id"] and replay["replayed"]
    page=api.v39_catalog_records(entity="vendors",query="vendor",template_id="rknn",enabled="true",page=1,page_size=10,sort="name",vendor_id="")
    assert page["total"]==1 and page["items"][0]["chip_count"]==0
    detail=api.v39_catalog_record("vendors",result["id"])
    assert detail["references"]["can_delete"]
    assert api.v39_catalog_operation_result("api-create")["after"]["id"]==result["id"]


def test_original_conversion_admission_holds_catalog_fence_until_durable_acceptance(tmp_path,monkeypatch):
    from contextlib import nullcontext
    from filelock import FileLock,Timeout
    monkeypatch.setattr(api,"DATA_DIR",tmp_path)
    monkeypatch.setattr(api,"_resolve_deploy_source",lambda *a:{})
    monkeypatch.setattr(api,"_algorithm_version_reference_fence",lambda *a:nullcontext())
    def admitted(*args):
        with pytest.raises(Timeout):
            FileLock(str(tmp_path/"model_artifacts"/".conversion-catalog.lock")).acquire(timeout=0)
        return {"accepted":True}
    monkeypatch.setattr(api,"_v39_create_deploy_job_under_version_fence",admitted)
    assert api.v39_create_deploy_job("p",api.DeployJobReq(source_id="s",target="sophon",resource_id="r"))["accepted"]


def test_chip_detection_reuses_resource_owner_once_and_keeps_each_sdk_fact(tmp_path,monkeypatch):
    from platform_core.model_artifacts import ModelArtifactRepository
    from platform_core.errors import PlatformError
    monkeypatch.setattr(api,"DATA_DIR",tmp_path)
    ModelArtifactRepository(tmp_path).save_conversion_catalog(catalog(),expected_revision=0)
    good={**live(),"id":"good","name":"remote good","mode":"remote"}
    bad={**live(),"id":"bad","name":"local invalid","mode":"local","status":"missing","message":"API Key 鉴权失败","targets":[],"supported_chips":[],"sophon_probe":{"available":False,"version":"1.29.0","error":"authentication failed"}}
    resources=[good,bad];seen=[]
    monkeypatch.setattr(api,"v39_list_deploy_resources",lambda:{"items":resources})
    def detect(identity):
        seen.append(identity);return next(r for r in resources if r["id"]==identity)
    monkeypatch.setattr(api,"v39_detect_deploy_resource",detect)
    result=api.v39_catalog_detect_chip("chip-84",{})
    assert seen==["good","bad"] and result["capability"]["sdk_ready"]
    facts={f["resource_id"]:f for f in result["capability"]["resources"]}
    assert facts["good"]["ready"] and not facts["bad"]["ready"]
    assert facts["good"]["mode"]=="remote" and facts["bad"]["mode"]=="local"
    assert facts["bad"]["message"]==bad["message"]
    assert facts["good"]["sdk_version"]!=facts["bad"]["sdk_version"]
    seen.clear();api.v39_catalog_detect_chip("chip-84",{"resource_ids":["good","good"]});assert seen==["good"]
    with pytest.raises(PlatformError) as error: api.v39_catalog_detect_chip("chip-84",{"resource_ids":["missing"]})
    assert error.value.code=="CATALOG_RESOURCE_MISMATCH"
    resources.clear()
    with pytest.raises(PlatformError) as error: api.v39_catalog_detect_chip("chip-84",{})
    assert error.value.code=="CATALOG_RESOURCE_UNAVAILABLE"


def test_missing_job_record_http_allows_rename_and_toggle_but_never_identity_or_delete(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from platform_core.model_artifacts import ModelArtifactRepository
    from tests.unit.test_conversion_catalog_crud import seed,missing_job_task
    monkeypatch.setattr(api,"DATA_DIR",tmp_path);monkeypatch.setattr(api,"v39_list_deploy_resources",lambda:{"items":[]})
    repo=ModelArtifactRepository(tmp_path);vendor,chip=seed(repo);missing_job_task(tmp_path)
    client=TestClient(api.app)
    detail=client.get(f"/api/v39/deploy/catalog/records/vendors/{vendor['id']}")
    assert detail.status_code==200 and detail.json()["references"]["can_delete"] is False
    assert detail.json()["references"]["check_status"]=="UNVERIFIED"
    for action,record in [("update",{"name":"Renamed vendor"}),("disable",{}),("enable",{})]:
        body={"entity":"vendors","action":action,"id":vendor["id"],"operation_id":"missing-"+action,"expected_revision":repo.conversion_catalog()["revision"],"record":record}
        saved=client.post('/api/v39/deploy/catalog/operations',json=body)
        assert saved.status_code==200 and saved.json()["item"]["id"]==vendor["id"]
        assert client.post('/api/v39/deploy/catalog/operations',json=body).json()["replayed"] is True
    current=client.get(f"/api/v39/deploy/catalog/records/vendors/{vendor['id']}").json()
    assert current["item"]["name"]=="Renamed vendor" and current["item"]["enabled"] is True
    for action,record in [("delete",{}),("update",{"template_id":"rknn"})]:
        denied=client.post('/api/v39/deploy/catalog/operations',json={"entity":"vendors","action":action,"id":vendor["id"],"operation_id":"danger-"+action,"expected_revision":repo.conversion_catalog()["revision"],"record":record,"confirm_delete":True})
        assert denied.status_code==409 and denied.json()["code"]=="CATALOG_REFERENCE_CHECK_FAILED"
    assert repo.conversion_catalog()["chips"][0]["id"]==chip["id"]


@pytest.mark.parametrize("suffix", [".onnx",".pt"])
def test_onnx_admission_records_requested_options_and_only_marks_actual_reuse(tmp_path,monkeypatch,suffix):
    from contextlib import nullcontext
    from types import SimpleNamespace
    from platform_core.remote_execution_transport import RemoteExecutionTransportService
    monkeypatch.setattr(api,"DATA_DIR",tmp_path)
    source=tmp_path/("model"+suffix);source.write_bytes(b"isolated source")
    monkeypatch.setattr(api,"_resolve_deploy_source",lambda *a:{"kind":"imported","path":str(source)})
    resource={"id":"agent","kind":"ultralytics","mode":"agent","status":"ready","targets":["onnx"]}
    monkeypatch.setattr(api,"_deploy_resource_by_id",lambda *a:resource)
    monkeypatch.setattr(api,"_detect_agent_deploy_resource",lambda r:r)
    monkeypatch.setattr(api,"_deploy_resource_public",lambda r:dict(r))
    monkeypatch.setattr(api,"get_active_ultralytics_env",lambda:{})
    monkeypatch.setattr(api,"get_active_paddle_env",lambda:{})
    monkeypatch.setattr(api,"project_dir",lambda *a:tmp_path)
    monkeypatch.setattr(api,"_deploy_job_dir",lambda p,j:tmp_path/"jobs"/j)
    monkeypatch.setattr(api,"_storage_source_fence",lambda:nullcontext())
    jobs=[];staged=[]
    def stage(**kwargs):
        staged.append(kwargs)
        return {"params":RemoteExecutionTransportService._portable_conversion_params("onnx",kwargs["params"])}
    monkeypatch.setattr(api,"_remote_execution_transport_service",lambda:SimpleNamespace(stage_model_conversion=stage))
    monkeypatch.setattr(api,"_write_deploy_job",lambda p,j:jobs.append(j))
    monkeypatch.setattr(api,"shared_task_repository",lambda:SimpleNamespace(create=lambda t:None))
    monkeypatch.setattr(api,"shared_task_artifacts",lambda:SimpleNamespace(atomic_write_json=lambda *a:None))
    requested={"precision":"fp32","opset":17,"dynamic":True,"simplify":True,"onnx_source_reused":True}
    result=api._v39_create_deploy_job_under_version_fence("p",api.DeployJobReq(source_id="s",target="onnx",resource_id="agent",params=requested))
    assert result["job"]["requested_params"]==requested
    params=result["job"]["params"]
    if suffix==".onnx":
        assert params["onnx_source_reused"] is True
        assert not set(params).intersection({"precision","opset","dynamic","simplify","input_size"})
    else:
        assert "onnx_source_reused" not in params
        assert params["precision"]=="fp32" and params["opset"]==17
    assert staged[0]["params"]==params
