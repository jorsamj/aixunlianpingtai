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
    page=api.list_unified_runtime_tasks('p',kind='',limit=1,cursor=None,reader_view=True,query='t')
    assert page['items'][0]['task_id']=='t' and page['items'][0]['status']=='QUEUED'
    assert page['items'][0]['version_id']=='v'
    assert api.get_unified_runtime_task('p','t',reader_view=True)['task']['configuration']['epochs']==2
    report=api.v44_training_report('p','t',algorithm_id='a',version_id='v',reader_view=True)
    assert report['val_metrics']['map50']==0 and report['test_metrics']['map50']==.7
    with pytest.raises(api.HTTPException):api.get_unified_runtime_task('other','t',reader_view=True)
    with pytest.raises(PlatformError):api.v44_training_report('p','t',algorithm_id='a',version_id='wrong',reader_view=True)
