import json
import sys

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from platform_core.material_repository import MaterialRepository
from platform_core.task_runtime import ArtifactStore,TaskRepository
from platform_core.smart_material_audit.api import smart_material_audit_router


def client_for(tmp_path):
    def authorize(project_id):
        if project_id not in {'p','other'}:
            raise HTTPException(403,detail='project denied by original authorization owner')
    repository=TaskRepository(tmp_path/'tasks.sqlite3');artifacts=ArtifactStore(tmp_path/'artifacts')
    app=FastAPI();app.include_router(smart_material_audit_router(authorize,lambda:tmp_path,lambda:repository,lambda:artifacts,
        actor_provider=lambda request,project_id:{'actor_id':'signed-user'}))
    return TestClient(app),repository,artifacts


def test_off_routes_reuse_authorization_and_do_not_create_business_data(tmp_path):
    client,repository,artifacts=client_for(tmp_path)
    base='/api/v62/projects/p/smart-material-audit'
    assert client.get(base+'/status').json()['enabled'] is False
    assert client.get(base+'/models').json()['items']==[]
    response=client.post(base+'/estimate',json={'selection_spec':{'scope':'FILTERED','filters':{}}})
    assert response.status_code==409 and response.json()['detail']['code']=='SMART_AUDIT_DISABLED'
    assert client.get('/api/v62/projects/denied/smart-material-audit/status').status_code==403
    assert not (tmp_path/'projects').exists()
    assert not repository.list(project_id='p',limit=50).items
    assert 'fiftyone' not in sys.modules


def test_new_task_api_is_project_scoped_idempotent_and_not_ready_is_not_empty_success(tmp_path):
    client,repository,artifacts=client_for(tmp_path)
    MaterialRepository(tmp_path/'projects/p').upsert(dict(id='one',filename='one.png',content_sha256='a'*64))
    binary=tmp_path/'optional/Scripts/python.exe';binary.parent.mkdir(parents=True);binary.write_bytes(b'fixture only')
    (binary.parent.parent/'pyvenv.cfg').write_text('include-system-site-packages = false\n')
    (tmp_path/'smart_material_audit.json').write_text(json.dumps(dict(enabled=True,python=str(binary))))
    base='/api/v62/projects/p/smart-material-audit'
    preview=client.post(base+'/estimate',json={'selection_spec':{'scope':'SELECTED','image_ids':['one']}})
    assert preview.status_code==200
    payload={'selection_spec':preview.json()['selection_spec'],'options':{'request_id':'api-isolated-1'}}
    created=client.post(base,json=payload)
    assert created.status_code==202
    task_id=created.json()['task_id']
    assert client.post(base,json=payload).json()['task_id']==task_id
    assert client.get(base+'/'+task_id+'/findings').status_code==409
    assert client.get('/api/v62/projects/other/smart-material-audit/'+task_id+'/findings').status_code==404
    assert len(repository.list(project_id='p',limit=50).items)==1
    # Reject stale/missing/bool generations before any result/source materialization.
    for generation in [None,True,99]:
        response=client.post(base+'/'+task_id+'/findings/old/review',json={
            'verdict':'no_issue','expected_review_token':'old','expected_generation':generation})
        assert response.status_code==409
        assert response.json()['detail']['code']=='SMART_AUDIT_GENERATION_CHANGED'
