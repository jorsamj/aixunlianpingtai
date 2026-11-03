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
    assert evidence['unknown_parent_version_ids']==['a:v']


def test_verified_parent_with_missing_old_snapshot_allows_assumed_unseen(tmp_path, monkeypatch):
    import hashlib
    from types import SimpleNamespace
    from platform_core.task_runtime.repository import TaskRepository
    from platform_core.material_repository import MaterialRepository
    from platform_core.training_material_usage import admit_history_selection, assert_formal_test_independence
    from platform_core.training_splits import SplitRequest, SplitMode
    import platform_core.training_label_tasks as labels

    repository = TaskRepository(tmp_path / 'task_runtime' / 'tasks.sqlite3')
    project = tmp_path / 'projects' / 'p'
    project.mkdir(parents=True)
    weight = project / 'parent.pt'
    weight.write_bytes(b'content verified old checkpoint without historical snapshot')
    digest = hashlib.sha256(weight.read_bytes()).hexdigest()
    version = {'id': 'v', 'training_job_id': 'missing-task', 'artifact_verified': True,
               'verified_models': [{'sha256': digest, 'verified': True}]}
    monkeypatch.setattr(labels, '_iteration_base',
                        lambda *args: (version, {'base_model_path': str(weight)}))
    MaterialRepository(project).upsert_many([
        {'id': f'i-{i}', 'filename': f'{i}.jpg', 'content_sha256': f'{i+1:064x}'}
        for i in range(3)
    ])
    context = SimpleNamespace(repository=repository, run_owned=lambda fn: fn())
    split = SplitRequest(SplitMode.RANDOM_TEST_FROM_TRAINING_POOL,
                         ('i-0', 'i-1', 'i-2'), experiment_percent=20, validation_percent=20)
    admitted, history = admit_history_selection(context, SimpleNamespace(project_id='p', task_id='new'),
                                                project, {'id': 'a', 'versions': [version]},
                                                {'history_policy': 'new_for_algorithm'}, split)
    assert admitted.train_image_ids == split.train_image_ids
    assert history['index_health'] == 'healthy'
    assert history['historical_independence'] == 'assumed_unseen'
    assert history['unknown_parent_version_ids'] == ['a:v']
    index = TrainingMaterialUsage(repository)
    frozen = {'snapshot_id': 's', 'images': [
        {'image_id': 'i-0', 'role': 'test', 'content_sha256': f'{1:064x}'}]}
    verified = assert_formal_test_independence(index, frozen, 'p', 'a', admission=history)
    assert verified['historical_independence'] == 'assumed_unseen'
    index.record_selected('p', 'a', 'older', {'snapshot_id': 'old', 'images': [
        {'image_id': 'old-id', 'role': 'train', 'content_sha256': f'{1:064x}'}]})
    index.record_execution('older', first_batch=True)
    with pytest.raises(ValueError, match='TRAINING_TEST_HISTORY_EXPOSURE'):
        assert_formal_test_independence(index, frozen, 'p', 'a', admission=history)


def test_admission_health_rejects_partial_index_schema_not_as_unknown(tmp_path):
    path = tmp_path / 'tasks.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE training_material_usage (task_id TEXT)')
    index = TrainingMaterialUsage(path)
    with pytest.raises(ValueError, match='TRAINING_HISTORY_INDEX_UNAVAILABLE'):
        index.ensure_admission_index('p', 'a')


def test_exact_verified_cross_algorithm_weight_inherits_transitive_exposure_not_model_family(tmp_path):
    from types import SimpleNamespace
    from platform_core.algorithms import save_algorithms
    from platform_core.task_runtime import ArtifactStore, TaskKind, TaskRecord, TaskRepository
    from platform_core.material_repository import MaterialRepository
    from platform_core.training_material_usage import admit_history_selection
    from platform_core.training_lineage import build_training_lineage
    from platform_core.training_splits import SplitRequest, SplitMode

    project = tmp_path / 'projects' / 'p'
    project.mkdir(parents=True)
    weights = project / 'models'
    weights.mkdir()
    original = weights / 'a_best.pt'
    copied = weights / 'b_mother.pt'
    unrelated = weights / 'official_same_architecture.pt'
    original.write_bytes(b'verified learned weights from A')
    copied.write_bytes(original.read_bytes())
    unrelated.write_bytes(b'different model with identical YOLO architecture')
    import hashlib
    sha = hashlib.sha256(original.read_bytes()).hexdigest()
    repo = TaskRepository(tmp_path / 'task_runtime' / 'tasks.sqlite3')
    artifacts = ArtifactStore(tmp_path / 'task_runtime' / 'artifacts')
    materials = MaterialRepository(project)
    materials.upsert_many([{'id': item, 'filename': f'{item}.jpg', 'content_sha256': symbol * 64}
                           for item, symbol in [('a-exposed', 'a'), ('new-train', 'b'), ('new-test', 'c'),
                                                ('c-train', 'd'), ('a-original-test', 'e')]])
    for task_id in ('train-a', 'train-b'):
        repo.create(TaskRecord.new(task_id=task_id, project_id='p', kind=TaskKind.TRAINING,
                                   resource_key='training', payload_ref='payload.json'))
    snapshot_a = {'snapshot_id': 'snapshot-a', 'images': [
        {'image_id': 'a-exposed', 'role': 'train', 'content_sha256': 'a' * 64},
        {'image_id': 'a-original-test', 'role': 'test', 'content_sha256': 'e' * 64}]}
    artifacts.atomic_write_json('train-a', 'snapshot.json', snapshot_a)
    a_version = {'id': 'version-a', 'artifact_verified': True, 'task_id': 'train-a',
                 'snapshot_id': 'snapshot-a', 'stored_path': str(original),
                 'verified_models': [{'sha256': sha, 'verified': True}],
                 'evaluation': {'status': 'succeeded', 'snapshot_id': 'snapshot-a',
                                'benchmark_scope': {'binding_level': 'bundle_verified'}}}
    algorithm_a = {'id': 'a', 'versions': [a_version]}
    algorithm_b = {'id': 'b', 'versions': []}
    save_algorithms(project / 'algorithms.json', [algorithm_a, algorithm_b])
    index = TrainingMaterialUsage(repo)
    index.mark_coverage('p', 'b', complete=True)
    context = SimpleNamespace(repository=repo, artifacts=artifacts, run_owned=lambda fn: fn())
    task = SimpleNamespace(project_id='p', task_id='new-b')
    split = SplitRequest(SplitMode.INDEPENDENT_TEST_SET, ('new-train',), ('a-exposed',), validation_percent=20)
    with pytest.raises(ValueError, match='TRAINING_TEST_HISTORY_EXPOSURE'):
        admit_history_selection(context, task, project, algorithm_b, {'model': str(copied)}, split)
    clean = SplitRequest(SplitMode.INDEPENDENT_TEST_SET, ('new-train',), ('new-test',), validation_percent=20)
    _, admitted = admit_history_selection(context, task, project, algorithm_b, {'model': str(copied)}, clean)
    assert admitted['parent_task_ids'] == ['train-a']
    assert admitted['model_ancestry'][0]['algorithm_id'] == 'a'
    assert index.query_filter('p', 'a', [materials.get('a-exposed')], role='test')['excluded_image_ids'] == ['a-exposed']
    assert index.query_filter('p', 'b', [materials.get('a-exposed')], role='test')['excluded_image_ids'] == []
    assert index.query_filter('p', 'b', [materials.get('a-original-test')], parent_task_ids=['train-a'],
                              role='train')['excluded_image_ids'] == ['a-original-test']
    mixed = SplitRequest(SplitMode.INDEPENDENT_TEST_SET, ('new-train', 'a-original-test'),
                         ('new-test',), validation_percent=20)
    selected, _ = admit_history_selection(context, task, project, algorithm_b,
                                          {'model': str(copied), 'history_policy': 'include_history'}, mixed)
    assert selected.train_image_ids == ('new-train',)

    # A third algorithm inherits B's recorded ancestry, even when its loaded
    # checkpoint bytes no longer match A's (B has fine-tuned the weights).
    b_model = weights / 'b_best.pt'
    b_model.write_bytes(b'finetuned after inheriting A')
    b_sha = hashlib.sha256(b_model.read_bytes()).hexdigest()
    artifacts.atomic_write_json('train-b', 'snapshot.json', {'snapshot_id': 'snapshot-b', 'images': [
        {'image_id': 'new-train', 'role': 'train', 'content_sha256': 'b' * 64}]})
    b_version = {'id': 'version-b', 'artifact_verified': True, 'task_id': 'train-b',
                 'snapshot_id': 'snapshot-b', 'stored_path': str(b_model),
                 'verified_models': [{'sha256': b_sha, 'verified': True}],
                 'training_lineage': build_training_lineage(task_id='train-b', snapshot_id='snapshot-b',
                                                          model_ancestry=admitted['model_ancestry'])}
    save_algorithms(project / 'algorithms.json', [algorithm_a, {'id': 'b', 'versions': [b_version]}, {'id': 'c', 'versions': []}])
    index.mark_coverage('p', 'c', complete=True)
    c_split = SplitRequest(SplitMode.INDEPENDENT_TEST_SET, ('c-train',), ('a-exposed',), validation_percent=20)
    with pytest.raises(ValueError, match='TRAINING_TEST_HISTORY_EXPOSURE'):
        admit_history_selection(context, SimpleNamespace(project_id='p', task_id='new-c'), project,
                                {'id': 'c', 'versions': []}, {'model': str(b_model), 'history_policy': 'include_history'}, c_split)

    # Identical architecture is not a verified weight inheritance edge.
    unrelated_split = SplitRequest(SplitMode.INDEPENDENT_TEST_SET, ('c-train',), ('new-test',), validation_percent=20)
    _, unrelated_admission = admit_history_selection(context, task, project, algorithm_b,
                                                      {'model': str(unrelated)}, unrelated_split)
    assert unrelated_admission['model_ancestry'] == []


def test_formal_score_gate_rejects_known_exposure_and_incomplete_coverage(tmp_path):
    from platform_core.training_material_usage import assert_formal_test_independence
    index = _active_usage_index(tmp_path, 'old', 'test')
    index.mark_coverage('p', 'b', complete=False)
    clean = {'snapshot_id': 'frozen', 'images': [
        {'image_id': 'clean', 'role': 'test', 'content_sha256': 'b' * 64}]}
    with pytest.raises(ValueError, match='TRAINING_TEST_HISTORY_UNKNOWN'):
        assert_formal_test_independence(index, clean, 'p', 'b')
    index.mark_coverage('p', 'b', complete=True)
    assert assert_formal_test_independence(index, clean, 'p', 'b')['status'] == 'passed'
    index.record_selected('p', 'a', 'old', _usage_snapshot('s', 'original', 'validation'))
    index.record_execution('old', validation_observed=True)
    leaked = {'snapshot_id': 'frozen', 'images': [
        {'image_id': 'renamed', 'role': 'test', 'content_sha256': 'a' * 64}]}
    assert assert_formal_test_independence(index, leaked, 'p', 'b')['status'] == 'passed'
    with pytest.raises(ValueError, match='TRAINING_TEST_HISTORY_EXPOSURE'):
        assert_formal_test_independence(index, leaked, 'p', 'b', parent_task_ids=['old'])


def test_local_blind_scoring_reads_original_frozen_task_evidence_and_rejects_tampering(tmp_path):
    from platform_core.task_runtime import ArtifactStore, TaskKind, TaskRecord, TaskRepository
    from platform_core.training_material_usage import assert_frozen_formal_test
    data = tmp_path / 'data'
    project = data / 'projects' / 'p'
    project.mkdir(parents=True)
    repository = TaskRepository(data / 'task_runtime' / 'tasks.sqlite3')
    artifacts = ArtifactStore(data / 'task_runtime' / 'artifacts')
    repository.create(TaskRecord.new(task_id='task', project_id='p', kind=TaskKind.TRAINING,
                                     resource_key='training', payload_ref='payload.json'))
    index = TrainingMaterialUsage(repository)
    index.mark_coverage('p', 'b', complete=True)
    snapshot = {'snapshot_id': 's', 'ids': {'test': ['t']}, 'images': [
        {'image_id': 't', 'role': 'test', 'content_sha256': 'a' * 64}]}
    artifacts.atomic_write_json('task', 'snapshot.json', snapshot)
    admission = {'revision': '0', 'parent_task_ids': [], 'model_ancestry': []}
    artifacts.atomic_write_json('task', 'payload.json', {'snapshot_id': 's', 'algorithm_asset_id': 'b',
                                                       'history_admission': admission})
    artifacts.atomic_write_json('task', 'input-freeze.json', {'snapshot_id': 's', 'history_admission': admission})
    assert assert_frozen_formal_test(project, 'task', 's')['status'] == 'passed'
    with pytest.raises(ValueError, match='TRAINING_TEST_HISTORY_UNKNOWN'):
        assert_frozen_formal_test(project, 'task', 'different-snapshot')
    snapshot['ids']['test'] = ['not-the-frozen-image']
    artifacts.atomic_write_json('task', 'snapshot.json', snapshot)
    with pytest.raises(ValueError, match='TRAINING_TEST_HISTORY_UNKNOWN'):
        assert_frozen_formal_test(project, 'task', 's')


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

# Picker SQL tests stay in the API suite, which includes the FastAPI dependency.
