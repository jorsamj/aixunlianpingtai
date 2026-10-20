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
    source=tmp_path/'model.onnx';source.write_bytes(b'onnx')
    monkeypatch.setattr(api,'_resolve_deploy_source',lambda *a:{'kind':'imported','path':str(source)})
    resource={'id':'sophon-remote','kind':'sophon','mode':'remote','status':'ready','targets':['sophon'],
              'supported_chips':['bm1688'],'supported_precisions':['fp16'],'secret_ref':'test-secret','base_url':'http://isolated.invalid'}
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
