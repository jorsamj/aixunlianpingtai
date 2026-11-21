import json
from platform_core.task_runtime import TaskRepository,TaskRecord,TaskKind

def test_training_query_filters_before_cursor_pagination_without_other_projects(tmp_path):
    repo=TaskRepository(tmp_path/'tasks.sqlite3')
    for i in range(6):repo.create(TaskRecord.new(f'train-{i}','p',TaskKind.TRAINING,'payload.json','training:auto'))
    repo.create(TaskRecord.new('other','q',TaskKind.TRAINING,'payload.json','training:auto'))
    first=repo.list(project_id='p',kinds=(TaskKind.TRAINING,),task_query='train',limit=2)
    second=repo.list(project_id='p',kinds=(TaskKind.TRAINING,),task_query='train',limit=2,cursor=first.next_cursor)
    assert len(first.items)==len(second.items)==2 and first.next_cursor
    assert {t.task_id for t in first.items}.isdisjoint(t.task_id for t in second.items)
    assert not repo.list(project_id='p',task_query='other').items

def test_bounded_artifact_and_task_display_preserve_truth_and_hide_secrets(tmp_path):
    from dataclasses import replace
    from platform_core.training_reader_views import bounded_json,task_display
    from platform_core.task_runtime.artifacts import ArtifactStore
    store=ArtifactStore(tmp_path/'artifacts')
    store.atomic_write_json('t','payload.json',{'asset_algorithm_id':'a','version_id':'v','epochs':50,'token':'PRIVATE','dataset_selected_ids':['GT_SENTINEL']})
    task=TaskRecord.new('t','p',TaskKind.TRAINING,'payload.json','training:auto')
    task=replace(task,error='Authorization: Bearer SECRET_SENTINEL')
    result=task_display(task,store,detail=True)
    assert result['status']=='QUEUED' and result['algorithm_id']=='a' and result['configuration']['epochs']==50
    assert 'PRIVATE' not in json.dumps(result) and 'GT_SENTINEL' not in json.dumps(result)
    assert 'SECRET_SENTINEL' not in json.dumps(result)
    path=tmp_path/'large.json';path.write_text('x'*30)
    assert bounded_json(path,limit=10)[1]=='DEFERRED'


def test_training_reader_verifies_immutable_payload_and_keeps_display_budget(tmp_path):
    import hashlib
    from platform_core.task_runtime.payload_publications import _native_name
    from platform_core.training_reader_views import report_display, task_display
    from platform_core.task_runtime.artifacts import ArtifactStore

    store = ArtifactStore(tmp_path / 'artifacts')
    payload = json.dumps({'algorithm_asset_id': 'a', 'epochs': 50, 'workers': 4, 'large': 'x' * (40 * 1024)}).encode()
    ref = f'payload-versions/v1/{"0" * 64}/sha256-{hashlib.sha256(payload).hexdigest()}.json'
    from pathlib import Path
    path = Path(_native_name(store.root / 't' / ref))
    path.parent.mkdir(parents=True)
    path.write_bytes(payload)
    task = TaskRecord.new('t', 'p', TaskKind.TRAINING, ref, 'training:auto')
    assert task_display(task, store)['metadata_state'] == 'DEFERRED'
    detail = task_display(task, store, detail=True)
    assert detail['algorithm_id'] == 'a' and detail['configuration']['epochs'] == 50
    store.atomic_write_json('t','result.json',{
        'training_report':{
            'history':[{'epoch':1,'map50':0},{'epoch':2,'map50_95':.4}],
            'actual_train_params':{'epochs':7,'workers':0},
        },
        'best_epoch':1,'completed_epochs':2,'completion_reason':'early_stopping',
        'actual_train_params':{'epochs':2,'batch':16,'token':'hidden'},
    })
    report=report_display('t',task,store,tmp_path/'absent.json',history_offset=1,history_limit=1)
    assert report['configuration']=={'epochs':50,'workers':4}
    assert report['actual_parameters']=={'epochs':2,'batch':16,'workers':0}
    assert report['result']['status']=='QUEUED' and report['result']['best_epoch']==1 and report['result']['completed_epochs']==2
    assert report['history']==[{'epoch':2,'map50_95':.4}] and report['history_total']==2
    assert report['test_metrics']['map50'] is None
    path.write_bytes(payload.replace(b'50', b'51'))
    assert task_display(task, store, detail=True)['metadata_state'] == 'ERROR'
    report=report_display('t',task,store,tmp_path/'absent.json')
    assert 'epochs' not in report['configuration'] and report['warnings']

    legacy=tmp_path/'legacy.json'
    legacy.write_text(json.dumps({'workers':0,'epochs':8,'requested_train_params':{'batch':12}}))
    historical=report_display('old',None,store,legacy)
    assert historical['configuration']=={'batch':12}
    assert historical['actual_parameters']=={}
    assert historical['historical_parameters']=={'workers':0,'epochs':8}
