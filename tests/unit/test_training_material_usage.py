import sqlite3
from concurrent.futures import ThreadPoolExecutor
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


def _active_usage_index(tmp_path, *task_ids):
    path = tmp_path / 'tasks.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE tasks(task_id TEXT PRIMARY KEY,status TEXT)')
        db.executemany('INSERT INTO tasks VALUES(?,?)', [(task_id, 'QUEUED') for task_id in task_ids])
    return TrainingMaterialUsage(path)


def _usage_snapshot(snapshot_id, image_id, role, sha='a'):
    return {'snapshot_id': snapshot_id, 'images': [
        {'image_id': image_id, 'role': role, 'content_sha256': sha * 64}]}


@pytest.mark.parametrize('development_role', ['train', 'validation'])
def test_exposed_development_role_cannot_become_independent_test_even_after_bundle_cleanup(tmp_path, development_role):
    index = _active_usage_index(tmp_path, 'old', 'new')
    index.record_selected('p', 'a', 'old', _usage_snapshot('s', 'original', development_role),
                          enforce_isolation=True)
    index.record_execution('old', first_batch=True)
    with sqlite3.connect(index.path) as db:
        db.execute("UPDATE tasks SET status='SUCCEEDED' WHERE task_id='old'")
    # The original bundle no longer exists; SHA and source identity still bind.
    uploaded_again = {'id': 'renamed', 'content_sha256': 'a' * 64}
    result = index.query_filter('p', 'a', [uploaded_again], role='test')
    assert result['by_image_id']['renamed']['excluded'] is True
    assert index.query_filter('p', 'a', [uploaded_again], role='test', exclude_used=False)['excluded_image_ids'] == ['renamed']
    with pytest.raises(ValueError, match='TRAINING_TEST_HISTORY_EXPOSURE'):
        index.record_selected('p', 'a', 'new', _usage_snapshot('next', 'renamed', 'test'),
                              enforce_isolation=True)


def test_observed_test_permanently_blocks_train_and_validation_even_with_reuse(tmp_path):
    index = _active_usage_index(tmp_path, 'original', 'train-next', 'val-next')
    index.record_selected('p', 'a', 'original', _usage_snapshot('s', 'benchmark', 'test'),
                          enforce_isolation=True)
    index.record_execution('original', test_observed=True)
    with sqlite3.connect(index.path) as db:
        db.execute("UPDATE tasks SET status='SUCCEEDED' WHERE task_id='original'")
    row = {'id': 'same-bytes-new-id', 'content_sha256': 'a' * 64}
    fact = index.query_filter('p', 'a', [row], exclude_used=False)['by_image_id'][row['id']]
    assert fact['state'] == 'test_reserved'
    assert fact['benchmark_protected'] is True and fact['excluded'] is True
    for role, task_id in (('train', 'train-next'), ('validation', 'val-next')):
        with pytest.raises(ValueError, match='TRAINING_TEST_RESERVED'):
            index.record_selected('p', 'a', task_id, _usage_snapshot(task_id, row['id'], role),
                                  enforce_isolation=True)
    # The same benchmark remains eligible for independent evaluation.
    assert index.query_filter('p', 'a', [row], role='test')['excluded_image_ids'] == []
    # An unrelated algorithm need not inherit a different algorithm's lock.
    assert index.query_filter('p', 'unrelated', [row], exclude_used=False)['excluded_image_ids'] == []


def test_pending_test_reservation_releases_only_after_terminal_without_observation(tmp_path):
    index = _active_usage_index(tmp_path, 'pending', 'new')
    index.record_selected('p', 'a', 'pending', _usage_snapshot('s', 'benchmark', 'test'),
                          enforce_isolation=True)
    assert index.has_exposed_records('p', 'a', role='train', include_train_history=False)
    image = {'id': 'copy', 'content_sha256': 'a' * 64}
    assert index.query_filter('p', 'a', [image], exclude_used=False)['excluded_image_ids'] == ['copy']
    with pytest.raises(ValueError, match='TRAINING_TEST_RESERVED'):
        index.record_selected('p', 'a', 'new', _usage_snapshot('n', 'copy', 'train'),
                              enforce_isolation=True)
    with sqlite3.connect(index.path) as db:
        db.execute("UPDATE tasks SET status='FAILED' WHERE task_id='pending'")
    assert not index.has_exposed_records('p', 'a', role='train', include_train_history=False)
    assert index.query_filter('p', 'a', [image], exclude_used=False)['excluded_image_ids'] == []
    index.record_selected('p', 'a', 'new', _usage_snapshot('n', 'copy', 'train'),
                          enforce_isolation=True)


def test_partially_observed_test_remains_locked_after_cancel(tmp_path):
    index = _active_usage_index(tmp_path, 'partial', 'future')
    index.record_selected('p', 'a', 'partial', _usage_snapshot('s', 'test-image', 'test'),
                          enforce_isolation=True)
    # First actual blind-inference invocation persisted a role observation;
    # no successful final report is needed to preserve the frozen cohort.
    index.record_execution('partial', test_observed=True)
    with sqlite3.connect(index.path) as db:
        db.execute("UPDATE tasks SET status='CANCELLED' WHERE task_id='partial'")
    assert index.query_filter('p', 'a', [{'id': 'same', 'content_sha256': 'a' * 64}],
                              exclude_used=False)['excluded_image_ids'] == ['same']
    with pytest.raises(ValueError, match='TRAINING_TEST_RESERVED'):
        index.record_selected('p', 'a', 'future', _usage_snapshot('f', 'same', 'train'),
                              enforce_isolation=True)


def test_live_train_claim_and_test_claim_cannot_race(tmp_path):
    index = _active_usage_index(tmp_path, 'train', 'test')
    index.record_selected('p', 'a', 'setup', {'snapshot_id': 'empty', 'images': []})
    def claim(task_id, role):
        try:
            index.record_selected('p', 'a', task_id, _usage_snapshot(task_id, task_id, role),
                                  enforce_isolation=True)
            return 'committed'
        except ValueError as error:
            return str(error)
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda item: claim(*item), [('train', 'train'), ('test', 'test')]))
    assert outcomes.count('committed') == 1
    assert any('TRAINING_TEST_' in result for result in outcomes)


def test_active_development_claim_blocks_test_but_terminal_unobserved_does_not(tmp_path):
    index = _active_usage_index(tmp_path, 'old', 'test')
    index.record_selected('p', 'a', 'old', _usage_snapshot('s', 'old', 'validation'),
                          enforce_isolation=True)
    with pytest.raises(ValueError, match='TRAINING_TEST_HISTORY_EXPOSURE'):
        index.record_selected('p', 'a', 'test', _usage_snapshot('t', 'new', 'test'),
                              source_images=[{'id': 'new', 'content_sha256': 'a' * 64}],
                              enforce_isolation=True)
    with sqlite3.connect(index.path) as db:
        db.execute("UPDATE tasks SET status='CANCELLED' WHERE task_id='old'")
    index.record_selected('p', 'a', 'test', _usage_snapshot('t', 'new', 'test'),
                          enforce_isolation=True)


def test_read_only_historical_evaluation_trust_flags_exposure_and_unknown(tmp_path):
    from platform_core.evaluation_analysis import append_historical_test_independence
    index = _active_usage_index(tmp_path, 'old')
    index.record_selected('p', 'a', 'old', _usage_snapshot('s', 'old', 'validation'),
                          enforce_isolation=True)
    index.record_execution('old', validation_observed=True)
    with sqlite3.connect(index.path) as db:
        db.execute("UPDATE tasks SET status='SUCCEEDED' WHERE task_id='old'")
    snapshot = {'ids': {'test': ['renamed']}, 'images': [
        {'image_id': 'renamed', 'role': 'test', 'content_sha256': 'a' * 64}]}
    first = append_historical_test_independence({'checks': []}, snapshot, index, 'p', 'a')
    assert first['checks'][0]['status'] == 'risk'
    assert first['checks'][0]['count'] == 1
    assert first['checks'][0]['details'][0]['image_id'] == 'renamed'
    index.mark_coverage('p', 'a', complete=True)
    clean = {'ids': {'test': ['clean']}, 'images': [
        {'image_id': 'clean', 'role': 'test', 'content_sha256': 'b' * 64}]}
    second = append_historical_test_independence({'checks': []}, clean, index, 'p', 'a')
    assert second['checks'][0]['status'] == 'passed'
    index.mark_coverage('p', 'a', complete=False)
    third = append_historical_test_independence({'checks': []}, clean, index, 'p', 'a')
    assert third['checks'][0]['status'] == 'insufficient_evidence'


def test_picker_fast_sql_excludes_pending_and_permanent_test_even_with_history_reuse(tmp_path):
    import json
    from platform_core.training_material_picker_api import _picker_filter_sql, _attach_usage_exclusion
    index = _active_usage_index(tmp_path, 'test-owner')
    index.record_selected('p', 'a', 'test-owner', _usage_snapshot('s', 'benchmark', 'test'),
                          enforce_isolation=True)
    def eligible_count():
        filters = {'__usage_sql_exclusion': {'path': str(index.path), 'project_id': 'p',
            'algorithm_id': 'a', 'role': 'train', 'revision': index.read_revision(),
            'include_train_history': False}}
        clauses, params = _picker_filter_sql(filters)
        with sqlite3.connect(':memory:', uri=True) as db:
            db.execute('CREATE TABLE materials(id TEXT,content_sha256 TEXT,payload_json TEXT)')
            db.execute('INSERT INTO materials VALUES(?,?,?)', ('new-upload', 'a' * 64, json.dumps({})))
            _attach_usage_exclusion(db, filters)
            return db.execute('SELECT COUNT(*) FROM materials m WHERE ' + ' AND '.join(clauses), params).fetchone()[0]
    assert eligible_count() == 0
    with sqlite3.connect(index.path) as db:
        db.execute("UPDATE tasks SET status='FAILED' WHERE task_id='test-owner'")
    assert eligible_count() == 1
    index.record_execution('test-owner', test_observed=True)
    assert eligible_count() == 0
