import sqlite3
import pytest

from platform_core.training_material_usage import TrainingMaterialUsage


def test_unknown_selected_possible_and_failed_are_distinct(tmp_path, monkeypatch):
    path = tmp_path / 'tasks.sqlite3'
    sqlite3.connect(path).close()
    index = TrainingMaterialUsage(path)
    images = [{'id': 'a', 'content_sha256': 'a' * 64}]
    assert index.query_filter('p', 'algo', images)['by_image_id']['a']['state'] == 'unknown'
    snapshot = {'snapshot_id': 's', 'images': [{'image_id': 'a', 'role': 'train', 'content_sha256': 'a' * 64}]}
    index.record_selected('p', 'algo', 'task', snapshot)
    assert index.query_filter('p', 'algo', images)['by_image_id']['a']['state'] == 'selected'
    index.record_execution('task', first_batch=True, generation=1)
    result = index.query_filter('p', 'algo', images)
    assert result['by_image_id']['a']['state'] == 'possible'
    assert result['excluded_image_ids'] == ['a']
    index.record_execution('task', first_batch=False, generation=0)
    assert index.query_filter('p', 'algo', images)['by_image_id']['a']['state'] == 'possible'
    index.record_execution('task', completed_epoch=True, generation=1)
    assert index.query_filter('p', 'algo', images)['by_image_id']['a']['state'] == 'used'
    connections=[]
    connect=index._connect
    def observed_connect(*args, **kwargs):
        connections.append(True)
        return connect(*args, **kwargs)
    monkeypatch.setattr(index, '_connect', observed_connect)
    assert index.query_filter('p', 'algo', images)['by_image_id']['a']['state'] == 'used'
    assert len(connections)==1, 'revision and history query must share their read transaction'


def test_same_content_parent_validation_and_benchmark_protection(tmp_path):
    path = tmp_path / 'tasks.sqlite3'
    sqlite3.connect(path).close()
    index = TrainingMaterialUsage(path)
    index.record_selected('p', 'other', 'parent', {'snapshot_id': 's', 'images': [
        {'image_id': 'old', 'role': 'validation', 'content_sha256': 'a'*64},
        {'image_id': 'bench', 'role': 'test', 'content_sha256': 'b'*64}]})
    index.record_execution('parent', first_batch=True, generation=1)
    images = [{'id': 'new', 'content_sha256': 'a'*64}, {'id': 'b', 'content_sha256': 'b'*64}]
    result = index.query_filter('p', 'new', images, parent_task_ids=['parent'], role='test')
    assert result['excluded_image_ids'] == ['new']
    index.mark_coverage('p', 'new', complete=True)
    assert index.query_filter('p', 'new', [{'id': 'fresh'}])['by_image_id']['fresh']['state'] == 'unused'


def test_frozen_original_source_tokens_survive_component_member_changes(tmp_path):
    path = tmp_path/'tasks.sqlite3'
    sqlite3.connect(path).close()
    index = TrainingMaterialUsage(path)
    index.record_selected('p', 'algo', 'task', {'snapshot_id':'s', 'images':[
        {'image_id':'old', 'role':'train', 'group_id':'component:old', 'content_sha256':'a'*64}]},
        source_images=[{'id':'old','content_sha256':'a'*64,'camera_session_id':'camera-session'}])
    index.record_execution('task', first_batch=True)
    query = index.query_filter('p','algo',[{'id':'new','content_sha256':'b'*64,'camera_session_id':'camera-session'}])
    assert query['excluded_image_ids'] == ['new']


def test_stale_execution_cannot_publish_exposure_and_validation_is_eval_only(tmp_path):
    path = tmp_path/'tasks.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE tasks(task_id TEXT,status TEXT,lease_token TEXT,attempt INTEGER,lease_expires_at TEXT)')
        db.execute("INSERT INTO tasks VALUES('t','RUNNING','lease',1,'2099-01-01T00:00:00+00:00')")
    index = TrainingMaterialUsage(path)
    index.record_selected('p','a','t',{'snapshot_id':'s','images':[
        {'image_id':'val','role':'validation','content_sha256':'v'*64}]},owner=('t','lease',1))
    with sqlite3.connect(path) as db:
        db.execute("UPDATE tasks SET attempt=2,lease_token='new'")
    with pytest.raises(PermissionError,match='fenced'):
        index.record_execution('t',first_batch=True,generation=1,owner=('t','lease',1))
    index.record_execution('t',validation_observed=True,generation=2,owner=('t','new',2))
    facts = index.query_filter('p','a',[{'id':'val','content_sha256':'v'*64}])
    assert facts['by_image_id']['val']['state'] == 'eval_only'
    assert facts['excluded_image_ids'] == []


def test_exposed_original_prevents_derived_child_from_new_test(tmp_path):
    path = tmp_path/'tasks.sqlite3'
    sqlite3.connect(path).close()
    index = TrainingMaterialUsage(path)
    index.record_selected('p','a','parent',{'snapshot_id':'s','images':[
        {'image_id':'A','role':'train','content_sha256':'a'*64}]})
    index.record_execution('parent',first_batch=True)
    facts = index.query_filter('p','a',[{'id':'A1','source_root_id':'A','content_sha256':'b'*64}],
        parent_task_ids=['parent'],role='test')
    assert facts['excluded_image_ids'] == ['A1']


def test_missing_ancestor_blocks_new_test_but_original_verified_benchmark_remains(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from platform_core.task_runtime.repository import TaskRepository
    from platform_core.material_repository import MaterialRepository
    from platform_core.training_material_usage import admit_history_selection
    from platform_core.training_splits import SplitRequest,SplitMode
    import platform_core.training_label_tasks as labels
    repository=TaskRepository(tmp_path/'tasks.sqlite3')
    project=tmp_path/'projects'/'p'
    MaterialRepository(project).upsert_many([{'id':str(i),'filename':str(i)+'.jpg','content_sha256':str(i)*64} for i in range(3)])
    version={'id':'v','training_job_id':'missing','artifact_verified':True}
    monkeypatch.setattr(labels,'_iteration_base',lambda *args:(version,{}))
    context=SimpleNamespace(repository=repository,run_owned=lambda fn:fn())
    task=SimpleNamespace(project_id='p',task_id='new')
    algorithm={'id':'a','versions':[version]}
    split=SplitRequest(SplitMode.RANDOM_TEST_FROM_TRAINING_POOL,('0','1','2'),experiment_percent=20,validation_percent=20)
    with pytest.raises(ValueError,match='TRAINING_TEST_ANCESTRY_UNKNOWN'):
        admit_history_selection(context,task,project,algorithm,{'history_policy':'new_for_algorithm'},split)
    _,evidence=admit_history_selection(context,task,project,algorithm,{'history_policy':'new_for_algorithm'},split,verified_benchmark_reuse=True)
    assert evidence['unknown_parent_version_ids']==['v']
