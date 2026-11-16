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
    from platform_core.training_reader_views import bounded_json,task_display
    from platform_core.task_runtime.artifacts import ArtifactStore
    store=ArtifactStore(tmp_path/'artifacts')
    store.atomic_write_json('t','payload.json',{'asset_algorithm_id':'a','version_id':'v','epochs':50,'token':'PRIVATE','dataset_selected_ids':['GT_SENTINEL']})
    task=TaskRecord.new('t','p',TaskKind.TRAINING,'payload.json','training:auto')
    result=task_display(task,store,detail=True)
    assert result['status']=='QUEUED' and result['algorithm_id']=='a' and result['configuration']['epochs']==50
    assert 'PRIVATE' not in json.dumps(result) and 'GT_SENTINEL' not in json.dumps(result)
    path=tmp_path/'large.json';path.write_text('x'*30)
    assert bounded_json(path,limit=10)[1]=='DEFERRED'
