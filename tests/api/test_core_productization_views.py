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


@pytest.mark.parametrize('case', [
    'empty', 'terminal', 'training', 'TRAINING_PREPARE', 'AI_ANNOTATION',
    'MODEL_CONVERSION', 'DEPLOYMENT_TEST', 'mixed', 'cross_project',
])
def test_task_list_reads_queue_evidence_only_when_needed(tmp_path, monkeypatch, case):
    from dataclasses import replace
    from platform_core.task_runtime import TaskRepository, TaskRecord, TaskKind, TaskStatus, task_to_public
    from platform_core.task_runtime.query_api import WorkerInstanceService

    repo = TaskRepository(tmp_path / 'tasks.sqlite3')
    def add(task_id, kind, status=TaskStatus.QUEUED, project='p', resource='cpu:test'):
        task = TaskRecord.new(task_id, project, kind, 'payload.json', resource,
                              required_capabilities=('test',))
        repo.create(replace(task, status=status))
    if case == 'terminal':
        for status in (TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED):
            add(status.value, TaskKind.TRAINING_PREPARE, status)
    elif case == 'training':
        add('train', TaskKind.TRAINING)
    elif case in ('mixed', 'cross_project'):
        add('train', TaskKind.TRAINING, resource='training:auto')
        add('prepare', TaskKind.TRAINING_PREPARE)
        if case == 'cross_project':
            add('foreign', TaskKind.TRAINING_PREPARE, project='other', resource='cpu:other')
    elif case != 'empty':
        add('queued', TaskKind(case))
    workers = [{'online': True, 'task_kinds': [k.value for k in TaskKind if k is not TaskKind.TRAINING],
                'capabilities': ['test']}]
    candidates = repo.queued_candidates()
    page = repo.list(project_id='p', limit=50)
    expected = {'items': [task_to_public(t, repo, worker_runtime=workers, queued_candidates=candidates)
                          for t in page.items], 'next_cursor': page.next_cursor}
    calls = {'worker': 0, 'queue': 0}
    original_candidates = repo.queued_candidates
    def runtime(service, *args, **kwargs):
        assert service.repository is repo
        calls['worker'] += 1
        return workers
    def queue():
        calls['queue'] += 1
        return original_candidates()
    monkeypatch.setattr(WorkerInstanceService, 'list_runtime', runtime)
    monkeypatch.setattr(repo, 'queued_candidates', queue)
    monkeypatch.setattr(api, 'get_project', lambda p: {'id': p})
    monkeypatch.setattr(api, 'shared_task_repository', lambda: repo)
    endpoint = next(r.endpoint for r in api._task_query_router.routes if r.name == 'list_unified_runtime_tasks')
    result = endpoint('p', kind=None, limit=50, cursor=None)
    needs = case not in ('empty', 'terminal', 'training')
    assert calls == {'worker': int(needs), 'queue': int(needs)}
    assert result == expected
    for item in result['items']:
        if item['persisted_status'] == 'QUEUED':
            assert item['resource_queue_position'] == repo.resource_queue_position(item['task_id'])
            assert item['resource_queue_position_exact'] is (
                item['kind'] != 'TRAINING' and case != 'cross_project')
    assert repo.list(project_id='p', limit=50) == page


def test_task_list_batch_positions_avoid_scalar_reads(tmp_path, monkeypatch):
    from platform_core.task_runtime import TaskRepository, TaskRecord, TaskKind
    repo = TaskRepository(tmp_path / 'tasks.sqlite3')
    for i in range(10):
        repo.create(TaskRecord.new(str(i), 'p', TaskKind.TRAINING, 'payload.json', 'training:auto'))
    monkeypatch.setattr(api, 'get_project', lambda p: {'id': p})
    monkeypatch.setattr(api, 'shared_task_repository', lambda: repo)
    monkeypatch.setattr(repo, 'resource_queue_position', lambda *a: pytest.fail('per-task queue read'))
    endpoint = next(r.endpoint for r in api._task_query_router.routes if r.name == 'list_unified_runtime_tasks')
    body = endpoint('p', kind=None, limit=10, cursor=None)
    assert sorted(row['resource_queue_position'] for row in body['items']) == list(range(1, 11))
    assert all(row['resource_queue_position_exact'] is False for row in body['items'])
