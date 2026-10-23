import pytest
import app as api
from fastapi import HTTPException
from platform_core.task_runtime import TaskKind
from types import SimpleNamespace
from contextlib import nullcontext

@pytest.mark.parametrize('params', [{}, {'chip': 'bm1684x', 'precision':'fp16'}])
def test_sophon_creation_requires_live_chip_support(tmp_path, monkeypatch, params):
    source=tmp_path/'model.onnx';source.write_bytes(b'onnx')
    monkeypatch.setattr(api,'_resolve_deploy_source', lambda *a: {'kind':'imported','path':str(source)})
    monkeypatch.setattr(api,'_deploy_resource_by_id',lambda *a: {'id':'sophon-remote','kind':'sophon','mode':'remote','status':'ready','targets':['sophon'],'supported_chips':['bm1684x']})
    calls=[]
    monkeypatch.setattr(api,'_detect_remote_deploy_resource',lambda r: calls.append(r) or {**r,'status':'ready','supported_chips':['bm1688']})
    with pytest.raises(HTTPException) as error:
        api._v39_create_deploy_job_under_version_fence('p',api.DeployJobReq(source_id='src',resource_id='sophon-remote',target='sophon',params=params))
    assert error.value.status_code == 400
    assert len(calls)==1


def test_remote_sophon_admission_uses_existing_durable_owner(tmp_path,monkeypatch):
    from tests.unit.test_sophon_conversion import _onnx_identity
    from tests.unit.test_dynamic_conversion_catalog import catalog, live
    from platform_core.model_artifacts import ModelArtifactRepository
    monkeypatch.setattr(api,'DATA_DIR',tmp_path)
    ModelArtifactRepository(tmp_path).save_conversion_catalog(catalog(),expected_revision=0)
    source=tmp_path/'model.onnx';_onnx_identity(source,[1,3,640,640])
    monkeypatch.setattr(api,'_resolve_deploy_source',lambda *a:{'kind':'imported','path':str(source)})
    resource={'id':'sophon-remote','kind':'sophon','mode':'remote','status':'ready','targets':['sophon'],
              'supported_chips':['bm1688'],'supported_precisions':['fp16'],'secret_ref':'test-secret','base_url':'http://isolated.invalid'}
    resource.update(version='v1.30.2-20260831',sophon_probe=live()['sophon_probe'])
    monkeypatch.setattr(api,'_deploy_resource_by_id',lambda *a:resource)
    monkeypatch.setattr(api,'_detect_remote_deploy_resource',lambda r:dict(r))
    monkeypatch.setattr(api,'_deploy_resource_public',lambda r:{k:v for k,v in r.items() if k!='secret_ref'})
    monkeypatch.setattr(api,'get_active_ultralytics_env',lambda:{})
    monkeypatch.setattr(api,'get_active_paddle_env',lambda:{})
    monkeypatch.setattr(api,'project_dir',lambda *a:tmp_path)
    monkeypatch.setattr(api,'_deploy_job_dir',lambda p,j:tmp_path/'jobs'/j)
    monkeypatch.setattr(api,'_storage_source_fence',lambda:nullcontext())
    jobs=[];tasks=[];payloads=[]
    monkeypatch.setattr(api,'_write_deploy_job',lambda p,j:jobs.append(j))
    monkeypatch.setattr(api,'shared_task_repository',lambda:SimpleNamespace(create=lambda t:tasks.append(t)))
    monkeypatch.setattr(api,'shared_task_artifacts',lambda:SimpleNamespace(atomic_write_json=lambda t,r,p:payloads.append(p)))
    monkeypatch.setattr(api.threading,'Thread',lambda *a,**k:pytest.fail('Sophon must not start a detached sync thread'))
    result=api._v39_create_deploy_job_under_version_fence('p',api.DeployJobReq(source_id='src',resource_id='sophon-remote',target='sophon',params={'chip':'bm1688'}))
    assert len(tasks)==1 and tasks[0].kind is TaskKind.MODEL_CONVERSION
    assert result['job']['task_id']==tasks[0].task_id
    assert payloads[0]['execution_mode']=='remote'
    assert payloads[0]['remote_connection']['secret_ref']=='test-secret'
    assert 'secret_ref' not in result['job']['resource']
    assert result['job']['params']['precision']=='fp16'
    assert result['job']['requested_params']=={'chip':'bm1688'}
    assert jobs[0]['requested_params']==result['job']['requested_params']


def test_auto_sophon_does_not_default_to_bm1684x(tmp_path,monkeypatch):
    resource={'id':'remote','kind':'sophon','mode':'remote','status':'ready','targets':['sophon'],'supported_chips':['bm1684x']}
    monkeypatch.setattr(api,'_builtin_deploy_resources',lambda:[])
    monkeypatch.setattr(api,'_load_saved_deploy_resources',lambda:[resource])
    monkeypatch.setattr(api,'_deploy_resource_runtime',lambda r:r)
    monkeypatch.setattr(api,'_v48_quality_reached',lambda j:True)
    calls=[]
    monkeypatch.setattr(api,'_detect_remote_deploy_resource',lambda r:calls.append('probe') or {**r,'supported_chips':['bm1684x','bm1688']})
    monkeypatch.setattr(api,'v39_create_deploy_job',lambda *a,**k:calls.append('create') or {'job':{'id':'bad'}})
    result=api._v48_auto_convert_version('p','a',{'id':'v','stored_path':'model.pt'},{'auto_convert_targets':['sophon']})
    assert result['errors']
    assert calls==['probe']


@pytest.fixture
def sophon_resources(tmp_path, monkeypatch):
    rows = [{"id":"sophon-remote", "name":"独立算能资源", "kind":"sophon", "mode":"remote",
             "base_url":"http://isolated.invalid:8030", "secret_ref":"isolated-ref",
             "status":"missing", "targets":[], "message":"old unavailable"}]
    monkeypatch.setattr(api, "_load_saved_deploy_resources", lambda: [dict(r) for r in rows])
    monkeypatch.setattr(api, "_save_deploy_resources", lambda value: rows.__setitem__(slice(None), [dict(r) for r in value]))
    monkeypatch.setattr(api, "_builtin_deploy_resources", lambda **kw: [])
    secrets = {"isolated-ref":"isolated-key"}
    monkeypatch.setattr(api, "_v35_secret_store", lambda: SimpleNamespace(
        get=lambda ref: secrets.get(ref, ""), set=lambda ref, value: secrets.__setitem__(ref, value),
        masked=lambda ref: "***" if secrets.get(ref) else ""))
    state = {"mode":"ready", "calls":[]}
    def health(url, headers, timeout):
        state["calls"].append((url, dict(headers)))
        authorized = headers.get("X-API-Key") == "isolated-key" and state["mode"] != "auth"
        probe = {"available":state["mode"] != "sdk", "supported_chips":["bm1684x","bm1688"],
                 "supported_precisions":["fp16"], "version":"v1.30.2-20260831",
                 "error":"TPU_MLIR_UNAVAILABLE: model_deploy failed" if state["mode"] == "sdk" else ""}
        return SimpleNamespace(ok=authorized, status_code=200 if authorized else 401, text="Unauthorized",
            json=lambda: {"version":api.APP_VERSION,"targets":["sophon"],"tools":{"sophon":probe}})
    monkeypatch.setattr(api.requests, "get", health)
    monkeypatch.setattr(api, "COMPONENT_SCAN_DIR", tmp_path / "scans")
    monkeypatch.setattr(api, "get_active_ultralytics_env", lambda: {})
    monkeypatch.setattr(api, "get_active_paddle_env", lambda: {})
    monkeypatch.setattr(api, "_deploy_which", lambda *a: "")
    monkeypatch.setattr(api, "_v40_python_module", lambda py, mod, required=True, dist_name="":
        api._v40_component_item(mod, dist_name or mod, "ready", required))
    return rows, state


def _sophon_scan():
    api._v40_scan_write("sophon-state", {"id":"sophon-state","status":"queued"})
    api._v40_run_component_scan("sophon-state")
    scan = api.v40_get_component_scan("sophon-state")
    assert scan["status"] == "done", scan
    return scan


@pytest.mark.parametrize("entry", ["scan", "plugins", "detect"])
def test_sophon_authenticated_detection_updates_resource_list_and_public_projection(sophon_resources, entry):
    import json
    rows, state = sophon_resources
    if entry == "scan":
        result = _sophon_scan()
        cap = next(c for c in result["capabilities"] if c["name"].startswith("算能"))
        assert cap["status"] == "ready" and cap["remote"] is True
        assert cap["ready"] == 1 and cap["total"] == 1
        assert "本机未配置" in cap["detail"] and "远程算能资源可用" in cap["detail"]
        local = [c for c in result["components"] if c["key"].startswith("tpu_")]
        assert len(local) == 3 and all(c["status"] == "missing" and c["name"].startswith("本机") for c in local)
        assert all(not c["path"] for c in local)
    elif entry == "plugins":
        result = api.v41_deploy_plugins()
        plugin = next(p for p in result["items"] if p["id"] == "sophon")
        assert plugin["status"] == "ready" and len(plugin["resources"]) == 1
        assert plugin["resources"][0]["version"] == "v1.30.2-20260831"
        assert plugin["resources"][0]["has_api_key"] is True
    else:
        result = api.v39_detect_deploy_resource("sophon-remote")
        assert result["status"] == "ready" and result["version"] == "v1.30.2-20260831"
    assert state["calls"] and all(h["X-API-Key"] == "isolated-key" for _, h in state["calls"])
    listed = api.v39_list_deploy_resources()["items"][0]
    assert listed["status"] == "ready" and listed["supported_chips"] == ["bm1684x","bm1688"]
    assert rows[0]["secret_ref"] == "isolated-ref"
    assert "isolated-key" not in json.dumps(result) and "isolated-ref" not in json.dumps(result)
    assert "isolated-key" not in json.dumps(rows)


@pytest.mark.parametrize("failure", ["auth", "sdk"])
def test_sophon_scan_failure_and_recovery_propagates_to_plugins_and_conversion_list(sophon_resources, failure):
    rows, state = sophon_resources
    api.v39_detect_deploy_resource("sophon-remote")
    state["mode"] = failure
    scan = _sophon_scan()
    cap = next(c for c in scan["capabilities"] if c["name"].startswith("算能"))
    assert cap["status"] == "missing"
    listed = api.v39_list_deploy_resources()["items"][0]
    assert listed["status"] == "missing" and listed["targets"] == []
    assert listed["supported_chips"] == [] and listed["supported_precisions"] == []
    assert ("401" if failure == "auth" else "model_deploy failed") in listed["message"]
    assert next(p for p in api.v41_deploy_plugins()["items"] if p["id"] == "sophon")["status"] == "missing"
    state["mode"] = "ready"
    assert next(p for p in api.v41_deploy_plugins()["items"] if p["id"] == "sophon")["status"] == "ready"
    assert api.v39_list_deploy_resources()["items"][0]["status"] == "ready"
    assert next(c for c in _sophon_scan()["capabilities"] if c["name"].startswith("算能"))["status"] == "ready"


def test_sophon_unconfigured_scan_has_no_fake_resource(sophon_resources):
    rows, state = sophon_resources
    rows.clear()
    scan = _sophon_scan()
    cap = next(c for c in scan["capabilities"] if c["name"].startswith("算能"))
    assert cap["status"] == "missing" and cap["ready"] == cap["total"] == 0
    assert "未配置" in cap["detail"]
    assert not state["calls"]
    assert next(p for p in api.v41_deploy_plugins()["items"] if p["id"] == "sophon")["resources"] == []


def test_sophon_local_auto_detect_preserves_independent_python_and_recovers(sophon_resources, monkeypatch):
    import platform_core.sophon_runtime as runtime
    rows, state = sophon_resources
    rows[:] = [{"id":"sophon-local","name":"独立本机TPU", "kind":"sophon","mode":"local",
                "python_path":"/opt/sophon-mlir/env/bin/python","tool_root":"/opt/sophon-mlir/env/bin"}]
    seen=[]
    def probe(resource):
        seen.append(dict(resource))
        return {"available":state["mode"] == "ready", "version":"v1.30.2-20260831", "tools":{},
                "supported_chips":["bm1688"] if state["mode"] == "ready" else [],
                "supported_precisions":["fp16"] if state["mode"] == "ready" else [], "error":"SDK missing"}
    monkeypatch.setattr(runtime, "probe_sophon_toolchain", probe)
    monkeypatch.setattr(api, "_v41_rknn_info", lambda py: {"ok":False})
    for mode in ("sdk", "ready"):
        state["mode"] = mode
        api.v39_detect_local_deploy_resources()
        assert rows[0]["id"] == "sophon-local"
        assert rows[0]["python_path"] == "/opt/sophon-mlir/env/bin/python"
        assert rows[0]["tool_root"] == "/opt/sophon-mlir/env/bin"
        assert rows[0]["status"] == ("ready" if mode == "ready" else "missing")
    assert all(r["python_path"] == "/opt/sophon-mlir/env/bin/python" for r in seen)


def test_sophon_registration_detect_and_plugin_share_one_saved_resource(sophon_resources):
    import json
    rows, state = sophon_resources
    rows.clear()
    registered = api.v39_create_deploy_resource(api.DeployResourceReq(name="独立算能资源", kind="sophon",
        mode="remote", base_url="http://isolated.invalid:8030", api_key="isolated-key"))
    rid = registered["id"]
    assert registered["status"] == "unchecked" and registered["has_api_key"] is True
    assert "isolated-key" not in json.dumps(registered)
    assert api.v39_detect_deploy_resource(rid)["status"] == "ready"
    plugin = next(p for p in api.v41_deploy_plugins()["items"] if p["id"] == "sophon")
    assert [r["id"] for r in plugin["resources"]] == [rid]
    assert plugin["resources"][0]["has_api_key"] is True
    assert len(rows) == 1 and rows[0]["id"] == rid
    assert api.v39_list_deploy_resources()["items"][0]["status"] == "ready"


@pytest.mark.parametrize("missing", ["targets", "supported_chips", "supported_precisions"])
def test_sophon_remote_health_requires_explicit_target_chip_and_fp16(sophon_resources, monkeypatch, missing):
    rows, state = sophon_resources
    def health(*args, **kwargs):
        probe = {"available":True,"supported_chips":["bm1688"],"supported_precisions":["fp16"],"version":"v1.30.2-20260831"}
        if missing != "targets": probe[missing] = []
        return SimpleNamespace(ok=True, json=lambda:{"targets":[] if missing=="targets" else ["sophon"], "tools":{"sophon":probe}})
    monkeypatch.setattr(api.requests, "get", health)
    result = api.v39_detect_deploy_resource("sophon-remote")
    assert result["status"] == "missing" and result["targets"] == []
    assert result["supported_chips"] == result["supported_precisions"] == []


def test_sophon_local_sdk_failure_does_not_hide_ready_remote(sophon_resources, monkeypatch):
    import platform_core.sophon_runtime as runtime
    rows, state = sophon_resources
    rows.append({"id":"local-sophon", "name":"本机独立环境", "kind":"sophon", "mode":"local",
                 "python_path":"/opt/sophon-mlir/env/bin/python", "tool_root":"/opt/sophon-mlir/env/bin"})
    monkeypatch.setattr(runtime, "probe_sophon_toolchain", lambda resource: {
        "available":False,"tools":{},"supported_chips":[],"supported_precisions":[],"error":"SDK import failed"})
    scan = _sophon_scan()
    cap = next(c for c in scan["capabilities"] if c["name"].startswith("算能"))
    assert cap["status"] == "ready" and cap["remote"] is True
    assert cap["ready"] == 1 and cap["total"] == 2
    assert "本机工具未就绪" in cap["detail"] and "远程算能资源可用" in cap["detail"]
    saved_local = next(r for r in rows if r["id"] == "local-sophon")
    assert saved_local["status"] == "missing" and saved_local["python_path"] == "/opt/sophon-mlir/env/bin/python"
