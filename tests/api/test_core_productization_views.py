import json
import pytest
import app as api
from platform_core.algorithms import save_algorithms
from platform_core.errors import PlatformError

def test_algorithm_basic_projection_and_original_writes_keep_external_protection(tmp_path,monkeypatch):
    path=tmp_path/'p'/'algorithms.json';path.parent.mkdir()
    save_algorithms(path,[{'id':'external','name':'外部','source_type':'EXTERNAL','master_data_readonly':True,'versions':[]}])
    monkeypatch.setattr(api,'get_project',lambda p:{'id':p});monkeypatch.setattr(api,'algorithms_file',lambda p:path)
    remark='原备注'*300+' https://example.test/document'
    local=api.v12_create_algorithm('p',api.AlgorithmReq(name='本地',remark=remark))['algorithm']
    basic=api.v12_get_algorithm('p',local['id'],asset_view=True,basic_only=True)
    assert basic['algorithm']['remark']==remark and basic['algorithm']['editable'] is True
    api.v12_update_algorithm('p',local['id'],api.AlgorithmReq(name='已编辑',remark='保留',industry='安全',algorithm_type='custom_python'))
    assert api.v12_get_algorithm('p',local['id'],asset_view=True,basic_only=True)['algorithm']['name']=='已编辑'
    assert api.v12_update_algorithm('p',local['id'],api.AlgorithmReq(name='确认'),asset_view=True)['algorithm']=={'id':local['id']}
    assert api.v12_get_algorithm('p','external',asset_view=True,basic_only=True)['algorithm']['editable'] is False
    with pytest.raises(PlatformError):api.v12_update_algorithm('p','external',api.AlgorithmReq(name='不允许'))

def test_training_reader_uses_task_owner_without_queue_scan_and_report_is_scoped(tmp_path,monkeypatch):
    from platform_core.task_runtime import TaskRepository,TaskRecord,TaskKind
    from platform_core.task_runtime.artifacts import ArtifactStore
    repo=TaskRepository(tmp_path/'tasks.sqlite3');artifacts=ArtifactStore(tmp_path/'artifacts')
    repo.create(TaskRecord.new('t','p',TaskKind.TRAINING,'payload.json','training:auto'))
    artifacts.atomic_write_json('t','payload.json',{'asset_algorithm_id':'a','epochs':2})
    artifacts.atomic_write_json('t','result.json',{'training_report':{'metrics':{'map50':0}},'evaluation':{'metrics':{'map50':.7}}})
    path=tmp_path/'p'/'algorithms.json';path.parent.mkdir();save_algorithms(path,[{'id':'a','name':'A','versions':[{'id':'v','job_id':'t'}]}])
    monkeypatch.setattr(api,'get_project',lambda p:{'id':p});monkeypatch.setattr(api,'project_dir',lambda p:tmp_path/p);monkeypatch.setattr(api,'algorithms_file',lambda p:path)
    monkeypatch.setattr(api,'shared_task_repository',lambda:repo);monkeypatch.setattr(api,'shared_task_artifacts',lambda:artifacts)
    monkeypatch.setattr(repo,'queued_candidates',lambda:pytest.fail('global queue scan'))
    monkeypatch.setattr(api,'list_algorithms_internal',lambda *a,**k:pytest.fail('full algorithm report load'))
    list_tasks=next(r.endpoint for r in api._task_query_router.routes if getattr(r,'path',None)=='/api/v62/projects/{project_id}/tasks' and 'GET' in r.methods)
    get_task=next(r.endpoint for r in api._task_query_router.routes if getattr(r,'path',None)=='/api/v62/projects/{project_id}/tasks/{task_id}' and 'GET' in r.methods)
    page=list_tasks('p',kind='',limit=1,cursor=None,reader_view=True,query='t')
    assert page['items'][0]['task_id']=='t' and page['items'][0]['status']=='QUEUED'
    assert page['items'][0]['version_id']=='v'
    assert get_task('p','t',reader_view=True)['task']['configuration']['epochs']==2
    report=api.v44_training_report('p','t',algorithm_id='a',version_id='v',reader_view=True)
    assert report['val_metrics']['map50']==0 and report['test_metrics']['map50']==.7
    with pytest.raises(api.HTTPException):get_task('other','t',reader_view=True)
    with pytest.raises(PlatformError):api.v44_training_report('p','t',algorithm_id='a',version_id='wrong',reader_view=True)


def test_task_query_registered_http_contract(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from platform_core.task_runtime import TaskRepository, TaskRecord, TaskKind
    from platform_core.task_runtime.artifacts import ArtifactStore
    repo = TaskRepository(tmp_path / 'tasks.sqlite3')
    repo.create(TaskRecord.new('visible', 'p', TaskKind.TRAINING, 'payload.json', 'training:auto'))
    repo.create(TaskRecord.new('foreign', 'other', TaskKind.TRAINING, 'payload.json', 'training:auto'))
    artifacts = ArtifactStore(tmp_path / 'artifacts')
    path = tmp_path / 'algorithms.json'
    save_algorithms(path, [])
    monkeypatch.setattr(api, 'shared_task_repository', lambda: repo)
    monkeypatch.setattr(api, 'shared_task_artifacts', lambda: artifacts)
    monkeypatch.setattr(api, 'algorithms_file', lambda p: path)
    def project(p):
        if p == 'missing':
            raise api.HTTPException(404, detail='项目不存在')
        return {'id': p}
    monkeypatch.setattr(api, 'get_project', project)
    monkeypatch.setattr(api, '_auth_test_bypass_enabled', lambda: False)
    client = TestClient(api.app)  # No lifespan: no workers or execution services.
    base = '/api/v62/projects/p/tasks'
    assert client.get(base).status_code == 401
    assert client.get(base + '/visible').json()['code'] == 'AUTH_REQUIRED'
    client.cookies.set(api.SESSION_COOKIE_NAME, api._CHANGLIAN_AUTH_SESSIONS.issue('isolated-task-query-user'))
    before = [(t.task_id, t.status, t.updated_at) for t in repo.list(project_id='p').items]
    for reader in ('false', 'true'):
        result = client.get(base, params={'reader_view': reader, 'limit': 1})
        assert result.status_code == 200
        assert [t['task_id'] for t in result.json()['items']] == ['visible']
        assert client.get(base + '/visible', params={'reader_view': reader}).status_code == 200
        for task in ('foreign', 'absent'):
            assert client.get(base + '/' + task, params={'reader_view': reader}).status_code == 404
    repo.create(TaskRecord.new('second', 'p', TaskKind.TRAINING, 'payload.json', 'training:auto'))
    expected = [t.task_id for t in repo.list(project_id='p', limit=100).items]
    for reader in ('false', 'true'):
        first = client.get(base, params={'reader_view': reader, 'limit': 1}).json()
        second = client.get(base, params={'reader_view': reader, 'limit': 1, 'cursor': first['next_cursor']}).json()
        assert [first['items'][0]['task_id'], second['items'][0]['task_id']] == expected
    for params in ({'limit': 0}, {'limit': 101}, {'kind': 'invalid'}, {'reader_view': True, 'status': 'invalid'}, {'cursor': 'invalid'}):
        assert client.get(base, params=params).status_code == 422
    assert client.get('/api/v62/projects/missing/tasks').status_code == 404
    assert before == [(t.task_id, t.status, t.updated_at) for t in repo.list(project_id='p').items if t.task_id == 'visible']
    assert len(api._task_query_router.routes) == 2
    assert all(r.methods == {'GET'} for r in api._task_query_router.routes)
