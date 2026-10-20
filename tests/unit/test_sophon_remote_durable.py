import json
import os
from pathlib import Path
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
os.environ['MC_REMOTE_DEPLOY_DATA_DIR'] = str(Path(os.environ['MC_TRAIN_DATA_DIR']) / 'remote-deploy-service')
import remote_deploy_server as server
from platform_core.deployment import conversion_tasks
from platform_core.task_runtime import TaskStatus


def test_remote_server_denies_unconfigured_key(tmp_path, monkeypatch):
    monkeypatch.setattr(server, 'CONFIG_FILE', tmp_path / 'config.json')
    with pytest.raises(HTTPException) as error:
        server.check_key('')
    assert error.value.status_code == 401


def test_remote_config_requires_current_key(tmp_path, monkeypatch):
    path = tmp_path / 'config.json'
    path.write_text(json.dumps({'api_key': 'current'}))
    monkeypatch.setattr(server, 'CONFIG_FILE', path)
    with pytest.raises(HTTPException):
        server.save_config(server.ConfigReq(api_key='replacement'), x_api_key='wrong')
    assert json.loads(path.read_text())['api_key'] == 'current'


def test_sophon_tool_failure_is_environment_blocked():
    assert conversion_tasks.conversion_outcome({'status': 'failed', 'error_code': 'TPU_MLIR_UNAVAILABLE'}) is TaskStatus.BLOCKED_BY_ENVIRONMENT


def test_recover_remote_uses_same_transport_without_launching_local_worker(tmp_path, monkeypatch):
    jd = tmp_path / 'job'; jd.mkdir()
    (jd / 'job.json').write_text(json.dumps({'id':'client-id','target':'sophon','status':'running'}))
    request = {'execution_mode': 'remote', 'target': 'sophon', 'job_dir': str(jd)}
    context = SimpleNamespace(task=SimpleNamespace(task_id='client-id', payload_ref='request.json'), artifacts=SimpleNamespace(read_json=lambda *a, **k: request))
    calls = []
    monkeypatch.setattr(conversion_tasks, 'run_remote_conversion', lambda *a, **kw: calls.append(kw) or ('remote', 'result'), raising=False)
    assert conversion_tasks.ConversionHandler().recover(context) == ('remote', 'result')
    assert calls[0]['recovering'] is True


def test_stop_after_server_restart_uses_persisted_process_identity(tmp_path, monkeypatch):
    monkeypatch.setattr(server,'CONFIG_FILE',tmp_path/'config.json')
    (tmp_path/'config.json').write_text(json.dumps({'api_key':'secret'}))
    monkeypatch.setattr(server,'JOBS_DIR',tmp_path/'jobs')
    monkeypatch.setattr(server,'PROCESS_REGISTRY',{})
    jd=tmp_path/'jobs/recover-id';jd.mkdir(parents=True)
    (jd/'job.json').write_text(json.dumps({'status':'running'}))
    (jd/'process.json').write_text(json.dumps({'pid':123,'create_time':1.5,'command_hash':'hash'}))
    stopped=[]
    monkeypatch.setattr(server,'ProcessController',lambda:SimpleNamespace(terminate_tree=lambda identity:stopped.append(identity)),raising=False)
    server.stop_job('recover-id',x_api_key='secret')
    assert stopped and stopped[0].pid==123


def test_remote_request_identity_is_idempotent_and_rejects_changed_content(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setattr(server,'CONFIG_FILE',tmp_path/'config.json')
    (tmp_path/'config.json').write_text(json.dumps({'api_key':'secret','python_path':'isolated-python'}))
    monkeypatch.setattr(server,'JOBS_DIR',tmp_path/'jobs')
    monkeypatch.setattr(server,'PROCESS_REGISTRY',{})
    monkeypatch.setattr(server,'probe_sophon_toolchain',lambda *a,**k:{'available':True,'supported_chips':['bm1688']})
    launches=[]
    monkeypatch.setattr(server,'launch_process',lambda *a,**k:launches.append(a) or SimpleNamespace(process=SimpleNamespace(poll=lambda:None),identity=server.ProcessIdentity(123,1.5,'hash')))
    with TestClient(server.app) as client:
        def submit(content):
            return client.post('/api/deploy/convert',headers={'X-API-Key':'secret'},files={'source_model':('model.onnx',content)},data={'target':'sophon','params_json':json.dumps({'chip':'bm1688'}),'client_job_id':'same-request'})
        first=submit(b'source');second=submit(b'source');changed=submit(b'changed')
    assert first.status_code==second.status_code==200
    assert first.json()['job_id']==second.json()['job_id']=='same-request'
    assert second.json()['reused'] is True
    assert changed.status_code==409
    assert len(launches)==1
