import pytest
import app as api
from fastapi import HTTPException
from tests.unit.test_dynamic_conversion_catalog import catalog, live as _live


def live():
    from datetime import datetime, timezone
    return {**_live(),'last_checked_at':datetime.now(timezone.utc).isoformat()}

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
    monkeypatch.setattr(api,"v39_list_deploy_resources",lambda **_:{"items":[live()]})
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
    client.cookies.set(api.SESSION_COOKIE_NAME,api._CHANGLIAN_AUTH_SESSIONS.issue('isolated-catalog-user'))
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
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from platform_core.remote_execution_transport import RemoteExecutionTransportService
    monkeypatch.setattr(api,"DATA_DIR",tmp_path)
    source=tmp_path/("model"+suffix);source.write_bytes(b"isolated source")
    monkeypatch.setattr(api,"_resolve_deploy_source",lambda *a:{"kind":"imported","path":str(source)})
    resource={"id":"agent","kind":"ultralytics","mode":"agent","status":"ready","targets":["onnx"],
              "last_checked_at":datetime.now(timezone.utc).isoformat()}
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


def test_resolve_reads_observations_without_running_any_detector(tmp_path,monkeypatch):
    from platform_core.model_artifacts import ModelArtifactRepository
    monkeypatch.setattr(api,'DATA_DIR',tmp_path)
    ModelArtifactRepository(tmp_path).save_conversion_catalog(catalog(),expected_revision=0)
    monkeypatch.setattr(api,'_resolve_deploy_source',lambda *a:{'kind':'imported','path':str(tmp_path/'best.pt')})
    resource=live()
    monkeypatch.setattr(api,'_deploy_resource_by_id',lambda *a:resource)
    monkeypatch.setattr(api,'_detect_local_deploy_resource',lambda *a:pytest.fail('preview must not probe SDK'))
    body=api.DeployJobReq(source_id='s',target='sophon',resource_id='s',params={'local_vendor_id':'local-s','local_chip_id':'chip-84'})
    first=api.v39_resolve_conversion('p',body)
    assert first['ready'] and first['resource_detection']['state']=='available'
    assert first['timings_ms']['total']>=0
    resource['last_checked_at']='2000-01-01T00:00:00+00:00'
    stale=api.v39_resolve_conversion('p',body)
    assert not stale['ready'] and stale['resource_detection']['state']=='expired'
    monkeypatch.setattr(api,'_builtin_deploy_resources',lambda:pytest.fail('read-only list cannot start all probes'))
    monkeypatch.setattr(api,'_builtin_deploy_resource_summary',lambda:[])
    monkeypatch.setattr(api,'_load_saved_deploy_resources',lambda:[resource])
    assert any(r['id']==resource['id'] for r in api.v39_list_deploy_resources(detect_missing=False)['items'])


def test_version_resolve_reads_only_selected_sql_algorithm_not_project_history(tmp_path, monkeypatch):
    from platform_core.algorithm_sql_store import AlgorithmSqlStore
    from platform_core.model_artifacts import ModelArtifactRepository
    from platform_core.compute_platform_catalog import conversion_chip_status_label
    monkeypatch.setattr(api, 'DATA_DIR', tmp_path)
    ModelArtifactRepository(tmp_path).save_conversion_catalog(catalog(), expected_revision=0)
    source = tmp_path / 'model.pt'; source.write_bytes(b'isolated model')
    version = {'id':'v2','version_name':'second','stored_path':str(source),
               'model_name':'model.pt','report':{'framework':'ultralytics'}}
    calls = []
    def one(self, algorithm_id):
        calls.append(algorithm_id)
        return {'id':'a1','name':'only selected','current_version_id':'v2',
                'versions':[{'id':'v1','stored_path':str(source)},version]}
    monkeypatch.setattr(AlgorithmSqlStore, 'read_one', one)
    monkeypatch.setattr(api, 'get_project', lambda *_:{'id':'p'})
    monkeypatch.setattr(api, '_deploy_source_models', lambda *_:pytest.fail('version lookup must not browse entire project'))
    monkeypatch.setattr(api, 'list_algorithms_internal', lambda *_:pytest.fail('no second full algorithm list'))
    monkeypatch.setattr(api, 'list_models_internal', lambda *_:pytest.fail('no training job.json scan'))
    monkeypatch.setattr(api, '_deploy_resource_by_id', lambda *_:live())
    result = api.v39_resolve_conversion('p', api.DeployJobReq(source_id='version::a1::v2',
        target='sophon', resource_id='s', params={'local_vendor_id':'local-s','local_chip_id':'chip-84'}))
    assert result['ready'] and result['params']['local_chip_id']=='chip-84'
    assert calls == ['a1']
    assert conversion_chip_status_label('not_adapted') == '暂未适配'
    with pytest.raises(HTTPException) as missing:
        api._resolve_deploy_source('p', 'version::a1::missing')
    assert missing.value.status_code == 404


def test_conversion_opt_in_diagnostics_scope_covers_resolve_but_not_job_creation():
    from platform_core.performance_diagnostics import _endpoint
    assert _endpoint('/api/v39/projects/synthetic/deploy/resolve')=='conversion.resolve'
    assert _endpoint('/api/v39/deploy/catalog')=='conversion.catalog'
    assert _endpoint('/api/v39/projects/synthetic/deploy/jobs') is None
    assert _endpoint('/api/v39/projects/synthetic/deploy/resolve/extra') is None


@pytest.mark.parametrize('state, expected', [
    ('not_checked','pending_detection'),('checking','detection_in_progress'),
    ('expired','detection_expired'),('failed','detection_failed'),
])
def test_catalog_per_chip_status_uses_actual_selected_resource_freshness(state, expected):
    from platform_core.compute_platform_catalog import resolve_chip_capability, conversion_chip_status_label
    resource={**live(),'detection':{'state':state},'last_checked_at':'2026-11-02T12:00:00+00:00'}
    fact=resolve_chip_capability(catalog(),vendor_id='local-s',chip_id='chip-84',resource=resource)
    assert not fact['ready'] and fact['status']==expected
    assert conversion_chip_status_label(expected)!='状态未知'


def test_concurrent_saved_resource_detection_coalesces_and_cannot_overwrite_edit(tmp_path, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from datetime import datetime, timezone
    from filelock import FileLock
    file = tmp_path / 'deploy_resources.json'
    monkeypatch.setattr(api, 'DEPLOY_RESOURCES_FILE', file)
    monkeypatch.setattr(api, '_DEPLOY_RESOURCES_WRITE_LOCK', FileLock(str(file)+'.lock'))
    original={'id':'probe','name':'registered','kind':'sophon','mode':'local',
              'config_revision':'v1','status':'unchecked','targets':[],
              'updated_at':'2026-11-02 01:00:00'}
    api._save_deploy_resources([original])
    begin=threading.Event();release=threading.Event();second_read=threading.Event();calls=[]
    original_lookup=api._deploy_resource_by_id
    reads=[0];reads_lock=threading.Lock()
    def traced_lookup(identity):
        value=original_lookup(identity)
        with reads_lock:
            reads[0]+=1
            if reads[0]>=3:second_read.set()
        return value
    monkeypatch.setattr(api,'_deploy_resource_by_id',traced_lookup)
    def inspect(resource, *, force=False):
        calls.append(resource['config_revision'])
        begin.set();assert release.wait(3)
        return {**resource,'status':'ready','targets':['sophon'],
                'last_checked_at':datetime.now(timezone.utc).isoformat()}
    monkeypatch.setattr(api,'_inspect_conversion_resource', inspect)
    with ThreadPoolExecutor(2) as pool:
        first=pool.submit(api.v39_detect_deploy_resource, 'probe')
        assert begin.wait(3)
        second=pool.submit(api.v39_detect_deploy_resource, 'probe')
        assert second_read.wait(3)
        release.set()
        a=first.result(timeout=6);b=second.result(timeout=6)
    assert len(calls)==1 and a['status']==b['status']=='ready'
    assert len(api._load_saved_deploy_resources())==1

    begin.clear();release.clear()
    with ThreadPoolExecutor(1) as pool:
        running=pool.submit(api.v39_detect_deploy_resource, 'probe')
        assert begin.wait(3)
        api.v39_update_deploy_resource('probe', api.DeployResourceReq(name='edited',kind='sophon',tool_root='/new-sdk'))
        release.set()
        with pytest.raises(HTTPException) as changed:
            running.result(timeout=6)
    assert changed.value.status_code==409
    saved=api._load_saved_deploy_resources()[0]
    assert saved['name']=='edited' and saved['tool_root']=='/new-sdk'
    assert saved['status']=='unchecked' and saved['last_checked_at']==''


def test_failed_sdk_inspection_is_shared_as_failed_evidence(tmp_path, monkeypatch):
    from filelock import FileLock
    file = tmp_path / 'deploy_resources.json'
    monkeypatch.setattr(api, 'DEPLOY_RESOURCES_FILE', file)
    monkeypatch.setattr(api, '_DEPLOY_RESOURCES_WRITE_LOCK', FileLock(str(file)+'.lock'))
    original = {'id':'broken-sdk', 'name':'SDK failure','kind':'rockchip',
                'mode':'local', 'config_revision':'v1', 'status':'ready',
                'targets':['rockchip'], 'last_checked_at':''}
    api._save_deploy_resources([original])

    def unavailable(_resource):
        raise RuntimeError('isolated probe failure')

    monkeypatch.setattr(api, '_detect_local_deploy_resource', unavailable)
    result = api.v39_detect_deploy_resource('broken-sdk')
    saved = api._load_saved_deploy_resources()[0]
    assert result['detection']['state']=='failed'
    assert result['status']==saved['status']=='error'
    assert saved['detection_error']=='isolated probe failure'
    assert saved['last_checked_at']
    # A second Web process gets durable failed evidence, never the old ready.
    from platform_core.conversion_resource_detection import observe
    assert observe(saved)['detection']['state']=='failed'


def test_background_detection_single_flight_cross_request_and_read_only_recovery(tmp_path, monkeypatch):
    import threading
    import time
    from filelock import FileLock
    filename=tmp_path/'deploy_resources.json'
    monkeypatch.setattr(api,'DEPLOY_RESOURCES_FILE',filename)
    monkeypatch.setattr(api,'_DEPLOY_RESOURCES_WRITE_LOCK',FileLock(str(filename)+'.lock'))
    api._save_deploy_resources([{'id':'async-sdk','name':'isolated SDK','kind':'rockchip',
        'mode':'local','config_revision':'v1','status':'unchecked','targets':[]}])
    began=threading.Event();finish=threading.Event();calls=[]
    def probe(row, *, force=False):
        calls.append(row['config_revision']);began.set()
        assert finish.wait(4)
        return {**row,'status':'ready','targets':['rockchip'],
                'supported_chips':['rk3568'],'last_checked_at':api.now_iso()}
    monkeypatch.setattr(api,'_inspect_conversion_resource',probe)
    first=api.v39_start_deploy_resource_detection('async-sdk')
    assert first['detection']['state']=='checking'
    assert began.wait(2)
    second=api.v39_start_deploy_resource_detection('async-sdk')
    assert second['detection']['state']=='checking'
    assert first['detection']['run_id']==second['detection']['run_id']
    # This reads the JSON record, not a process-local Event or the SDK.
    assert api.v39_conversion_resource_detection_status('async-sdk')['detection']['state']=='checking'
    finish.set()
    for _ in range(100):
        result=api.v39_conversion_resource_detection_status('async-sdk')
        if result['detection']['state']!='checking':break
        time.sleep(.02)
    assert result['detection']['state']=='available'
    assert len(calls)==1
    assert not api._load_saved_deploy_resources()[0].get('detection_run')


def _isolated_sdk_worker_process(filename, messages, probe_started, release):
    import os
    import time
    from pathlib import Path
    from filelock import FileLock
    import app as worker
    worker.DEPLOY_RESOURCES_FILE=Path(filename)
    worker._DEPLOY_RESOURCES_WRITE_LOCK=FileLock(str(filename)+'.lock')
    def scan(row, *, force=False):
        messages.put(('probe',os.getpid()))
        probe_started.set()
        if not release.wait(30):raise RuntimeError('isolated worker deadline')
        return {**row,'status':'ready','targets':['rockchip'],
                'supported_chips':['rk3568'],'last_checked_at':worker.now_iso()}
    worker._inspect_conversion_resource=scan
    try:
        result=worker.v39_start_deploy_resource_detection('multi-worker-sdk')
        messages.put(('run',result['detection']['run_id']))
        release.wait(30)
        # The daemon detector must finish before this Web worker exits.
        time.sleep(.3)
    except Exception as error:
        messages.put(('error',repr(error)))


def test_two_web_worker_processes_share_one_durable_sdk_scan(tmp_path,monkeypatch):
    import multiprocessing
    import queue
    import time
    from filelock import FileLock
    filename=tmp_path/'deploy_resources.json'
    monkeypatch.setattr(api,'DEPLOY_RESOURCES_FILE',filename)
    monkeypatch.setattr(api,'_DEPLOY_RESOURCES_WRITE_LOCK',FileLock(str(filename)+'.lock'))
    api._save_deploy_resources([{'id':'multi-worker-sdk','name':'isolated','kind':'rockchip',
        'mode':'local','config_revision':'v1','status':'unchecked','targets':[]}])
    # Spawn is safe when pytest, model imports or Web telemetry already have
    # background threads; fork inherits those locks and can deadlock.
    ctx=multiprocessing.get_context('spawn')
    messages=ctx.Queue();probe_started=ctx.Event();release=ctx.Event()
    workers=[];results=[]
    try:
        for index in range(2):
            worker=ctx.Process(target=_isolated_sdk_worker_process,
                args=(str(filename),messages,probe_started,release))
            worker.start();workers.append(worker)
            if index==0:assert probe_started.wait(15)
        for _ in range(3):
            try:results.append(messages.get(timeout=15))
            except queue.Empty:break
        assert sorted(tag for tag,_ in results)==['probe','run','run']
        assert len({value for tag,value in results if tag=='run'})==1
    finally:
        release.set()
        for worker in workers:
            worker.join(timeout=5)
            if worker.is_alive():worker.terminate();worker.join(timeout=2)
    assert all(worker.exitcode==0 for worker in workers)
    for _ in range(100):
        state=api.v39_conversion_resource_detection_status('multi-worker-sdk')['detection']['state']
        if state!='checking':break
        time.sleep(.02)
    assert state=='available'


@pytest.mark.parametrize('outcome',['failed','edited'])
def test_background_detection_cannot_leave_checking_or_overwrite_new_config(tmp_path,monkeypatch,outcome):
    import threading
    import time
    from filelock import FileLock
    filename=tmp_path/'deploy_resources.json'
    monkeypatch.setattr(api,'DEPLOY_RESOURCES_FILE',filename)
    monkeypatch.setattr(api,'_DEPLOY_RESOURCES_WRITE_LOCK',FileLock(str(filename)+'.lock'))
    api._save_deploy_resources([{'id':'async-fence','name':'fenced','kind':'sophon',
        'mode':'local','config_revision':'v1','status':'unchecked','targets':[]}])
    began=threading.Event();finish=threading.Event()
    def probe(row, *, force=False):
        began.set();assert finish.wait(4)
        if outcome=='failed':raise RuntimeError('isolated SDK subprocess failed')
        return {**row,'status':'ready','targets':['sophon'],'last_checked_at':api.now_iso()}
    monkeypatch.setattr(api,'_inspect_conversion_resource',probe)
    api.v39_start_deploy_resource_detection('async-fence')
    assert began.wait(2)
    if outcome=='edited':
        api.v39_update_deploy_resource('async-fence',api.DeployResourceReq(
            name='changed SDK',kind='sophon',tool_root='/new-location'))
    finish.set()
    expected='failed' if outcome=='failed' else 'not_checked'
    for _ in range(100):
        result=api.v39_conversion_resource_detection_status('async-fence')
        if result['detection']['state']==expected:break
        time.sleep(.02)
    assert result['detection']['state']==expected
    if outcome=='failed':assert 'isolated SDK subprocess failed' in result['detection']['error']
    else:assert result['config_revision']!='v1' and result['status']=='unchecked'


def test_display_only_resource_edit_keeps_sdk_evidence_but_real_path_change_invalidates(tmp_path,monkeypatch):
    from filelock import FileLock
    from platform_core.conversion_resource_detection import resource_configuration_key, observe
    filename=tmp_path/'deploy_resources.json'
    monkeypatch.setattr(api,'DEPLOY_RESOURCES_FILE',filename)
    monkeypatch.setattr(api,'_DEPLOY_RESOURCES_WRITE_LOCK',FileLock(str(filename)+'.lock'))
    base={'id':'sdk-edit','name':'old name','kind':'rockchip',
        'mode':'local','config_revision':'v1','python_path':'/configured/python',
        'last_checked_at':api.now_iso(),'status':'ready','targets':['rockchip'],
        'supported_chips':['rk3568']}
    api._save_deploy_resources([{**base,'detection_config_key':resource_configuration_key(base)}])
    renamed=api.v39_update_deploy_resource('sdk-edit',api.DeployResourceReq(
        name='new name',remark='display only',kind='rockchip',python_path='/configured/python'))
    assert renamed['config_revision']=='v1'
    assert renamed['last_checked_at']
    assert renamed['status']=='ready' and renamed['supported_chips']==['rk3568']
    assert observe(renamed)['detection']['state']=='available'
    changed=api.v39_update_deploy_resource('sdk-edit',api.DeployResourceReq(
        name='new name',remark='display only',kind='rockchip',python_path='/other/python'))
    assert changed['config_revision']!='v1'
    assert changed['status']=='unchecked' and changed['last_checked_at']==''
    assert changed['supported_chips']==[]


def test_formal_remote_admission_uses_authenticated_ping_without_sdk_probe(monkeypatch):
    import requests
    calls=[]
    class Response:
        status_code=200
        def raise_for_status(self):pass
        def json(self):return {'ok':True,'server':'mc-deploy-server',
            'version':'v2','config_revision':'config2'}
    monkeypatch.setattr(requests,'get',lambda url,**kwargs:(calls.append((url,kwargs)) or Response()))
    resource={'mode':'remote','base_url':'http://isolated.example',
        'api_key':'isolated-secret','remote_health':{'version':'v2','config_revision':'config2'}}
    api._remote_conversion_resource_online(resource)
    assert [url for url,_ in calls]==['http://isolated.example/api/deploy/ping']
    assert calls[0][1]['headers']['X-API-Key']=='isolated-secret'
    with pytest.raises(HTTPException,match='配置已变化'):
        api._remote_conversion_resource_online({**resource,
            'remote_health':{'version':'v2','config_revision':'previous'}})


def test_remote_ping_never_scans_sdk_or_returns_credentials(tmp_path,monkeypatch):
    monkeypatch.setenv('MC_REMOTE_DEPLOY_DATA_DIR',str(tmp_path/'remote'))
    import remote_deploy_server as remote
    filename=tmp_path/'server_config.json'
    filename.write_text('{"api_key":"do-not-echo","name":"remote"}',encoding='utf-8')
    monkeypatch.setattr(remote,'CONFIG_FILE',filename)
    monkeypatch.setattr(remote,'check_key',lambda _:None)
    monkeypatch.setattr(remote,'detect_tools',lambda:pytest.fail('ping must not scan SDK'))
    ping=remote.runtime_ping('isolated-key')
    assert ping['ok'] and ping['config_revision']
    assert 'do-not-echo' not in str(ping)


def test_local_bulk_probe_does_not_resurrect_concurrently_edited_resource(tmp_path, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from filelock import FileLock
    file = tmp_path / 'deploy_resources.json'
    monkeypatch.setattr(api, 'DEPLOY_RESOURCES_FILE', file)
    monkeypatch.setattr(api, '_DEPLOY_RESOURCES_WRITE_LOCK', FileLock(str(file)+'.lock'))
    original = {'id':'local-rk','name':'Original', 'kind':'rockchip',
                'mode':'local', 'config_revision':'v1', 'tool_root':'/before',
                'status':'unchecked', 'targets':[]}
    api._save_deploy_resources([original])
    began = threading.Event()
    release = threading.Event()

    def inspect(row):
        if row['kind']=='rockchip':
            began.set()
            assert release.wait(3)
        return {**row, 'status':'ready', 'targets':[row['kind']],
                'last_checked_at':'2026-11-02T12:00:00Z'}

    monkeypatch.setattr(api, '_detect_local_deploy_resource', inspect)
    monkeypatch.setattr(api, '_builtin_deploy_resources', lambda:[])
    with ThreadPoolExecutor(1) as pool:
        pending = pool.submit(api.v39_detect_local_deploy_resources)
        assert began.wait(3)
        api.v39_update_deploy_resource('local-rk', api.DeployResourceReq(
            name='Updated', kind='rockchip', tool_root='/after'))
        release.set()
        response = pending.result(timeout=6)
    saved = api._load_saved_deploy_resources()
    current = next(row for row in saved if row['id']=='local-rk')
    assert current['name']=='Updated' and current['tool_root']=='/after'
    assert current['status']=='unchecked'
    assert all(row['id']!='local-rk' for row in response['found'])
    assert next(row for row in response['items'] if row['id']=='local-rk')['name']=='Updated'


def test_version_history_paginates_its_full_legacy_scope_without_global_truncation(tmp_path,monkeypatch):
    import json
    monkeypatch.setattr(api,'get_project',lambda p:{'id':p})
    calls=[]
    def scoped_algorithm(project_id, *, algorithm_id=None, summary_only=False):
        calls.append((project_id, algorithm_id, summary_only))
        return [{'id':'a','name':'algorithm','versions':[{'id':'old','model_name':'source.onnx',
            'stored_path':'/safe/source.onnx','size_mb':2.5,'model_metadata':{'class_count':2},
            'evaluation':{'bulk':'x'*1024},'label_contract':{'bulk':'y'*1024}}]}]
    monkeypatch.setattr(api,'list_algorithms_internal',scoped_algorithm)
    monkeypatch.setattr(api,'_version_deploy_conversion_defaults',lambda *a:{'input_size':640})
    monkeypatch.setattr(api,'deploy_root',lambda p:tmp_path/'deploy')
    for index in range(7):
        root=tmp_path/'deploy/jobs'/str(index);root.mkdir(parents=True)
        (root/'job.json').write_text(json.dumps({'id':str(index),'status':'done','source_meta':{'algorithm_id':'a','version_id':'old'},
            'target':'onnx','created_at':'2026-10-28T10:00:00Z','params':{'csc':{'preset':'bt709_full'}} if index<5 else {},
            'execution_evidence':{'csc':{'applied':False,'device_observed':'unknown'}},'outputs':[]}))
    result=api.v423_version_deployments('p','a','old',page=2,page_size=2,csc='bt709_full')
    assert result['total']==5 and result['total_pages']==3 and len(result['items'])==2
    assert calls==[('p','a',True)]
    assert result['version']['stored_path']=='/safe/source.onnx'
    assert result['version']['size_mb']==2.5
    assert result['version']['model_metadata']['class_count']==2
    assert result['version']['conversion_defaults']['input_size']==640
    assert 'evaluation' not in result['version'] and 'label_contract' not in result['version']
    assert all(row['params']['csc']['preset']=='bt709_full' for row in result['items'])
    assert result['items'][0]['execution_evidence']['csc']['applied'] is False
    legacy=api.v423_version_deployments('p','a','old',csc='legacy_unknown')
    assert legacy['total']==2
