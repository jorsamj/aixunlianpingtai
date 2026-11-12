import pytest
from platform_core.training_selection_reference import freeze_selection,read_selection

def test_large_selection_is_server_only_and_bound_to_identity(tmp_path):
    context={'project_id':'p','algorithm_id':'a','role':'train','history_policy':'include_history','revisions':[1,2,3,4,5],'contract':'x'}
    receipt=freeze_selection(tmp_path,context,(str(i) for i in range(50001)))
    assert receipt['count']==50001 and 'image_ids' not in receipt
    assert len(read_selection(tmp_path,receipt['selection_ref'],context))==50001
    for key,value in [('project_id','other'),('algorithm_id','b'),('role','test'),('revisions',[2,2,3,4,5]),('contract','changed')]:
        with pytest.raises(ValueError):read_selection(tmp_path,receipt['selection_ref'],{**context,key:value})
    with pytest.raises(ValueError):read_selection(tmp_path,'../../other',context)


def test_freeze_retry_reuses_original_intent_and_failure_removes_partial_database(tmp_path):
    import uuid
    context={'project_id':'p'}
    request_id=str(uuid.uuid4())
    first=freeze_selection(tmp_path,context,['a','b'],request_id=request_id,request_scope='same')
    replay=freeze_selection(tmp_path,context,(_ for _ in () if False),request_id=request_id,request_scope='same')
    assert replay==first
    with pytest.raises(ValueError):freeze_selection(tmp_path,context,['c'],request_id=request_id,request_scope='changed')
    def broken():
        yield 'a'
        raise ValueError('isolated failure')
    before=set((tmp_path/'task_runtime'/'artifacts').glob('trainselection_*/selection.sqlite3'))
    with pytest.raises(ValueError):freeze_selection(tmp_path,context,broken())
    assert set((tmp_path/'task_runtime'/'artifacts').glob('trainselection_*/selection.sqlite3'))==before


def test_manifest_row_bound_rejects_and_cleans_only_failed_manifest(tmp_path,monkeypatch):
    import platform_core.training_selection_reference as refs
    monkeypatch.setattr(refs,'MAX_FROZEN_SELECTION_IDS',2)
    with pytest.raises(ValueError):refs.freeze_selection(tmp_path,{'project_id':'p'},['a','b','c'])
    assert not list((tmp_path/'task_runtime'/'artifacts').glob('trainselection_*/selection.sqlite3'))


def test_submitted_ref_releases_draft_quota_and_unused_expiry_is_explicit(tmp_path,monkeypatch):
    import platform_core.training_selection_reference as refs
    monkeypatch.setenv('MC_TRAIN_SELECTION_MAX_REFERENCES','1')
    first=refs.freeze_selection(tmp_path,{'project_id':'p'},['a'])
    refs.mark_selection_submitted(tmp_path,first['selection_ref'],'task1')
    refs.mark_selection_submitted(tmp_path,first['selection_ref'],'failed-task')
    refs.release_unpersisted_selection_claim(tmp_path,first['selection_ref'],'failed-task')
    second=refs.freeze_selection(tmp_path,{'project_id':'p'},['b'])
    now=refs.time.time()
    monkeypatch.setattr(refs.time,'time',lambda:now+90000)
    assert refs.read_selection(tmp_path,first['selection_ref'],{'project_id':'p'})==['a']
    with pytest.raises(ValueError,match='过期'):refs.read_selection(tmp_path,second['selection_ref'],{'project_id':'p'})
    third=refs.freeze_selection(tmp_path,{'project_id':'p'},['c'])
    assert third['selection_ref']!=second['selection_ref']


def test_streaming_frozen_20k_ids_keep_digest_retry_and_worker_identity(tmp_path, monkeypatch):
    """20k frozen IDs remain immutable and Worker-verified after streaming inserts."""
    import hashlib
    import json
    import sqlite3
    import uuid
    from platform_core import training_selection_reference as refs

    context = {'project_id': 'project-scale', 'algorithm_id': 'algorithm-scale',
        'role': 'train', 'history_policy': 'include_history', 'revisions': [1, 2, 3, 4, 5],
        'contract': 'contract-scale'}
    ids = [f'image-{i:06d}' for i in range(20_000)]
    request_id = str(uuid.uuid4())
    # Duplicate IDs cannot inflate the frozen count or change the ordered digest.
    items = (image_id for image_id in [*reversed(ids), *ids[:500]])
    receipt = refs.freeze_selection(tmp_path, context, items, request_id=request_id,
        request_scope='selected-all')
    assert receipt['count'] == 20_000
    assert set(receipt) == {'selection_ref', 'count'}
    manifest = refs._path(tmp_path, receipt['selection_ref'])
    with sqlite3.connect(manifest) as db:
        recorded = json.loads(db.execute(
            "SELECT value FROM meta WHERE key='training_selection'").fetchone()[0])
        assert db.execute('SELECT COUNT(*) FROM selection').fetchone()[0] == len(ids)
        assert db.execute("SELECT value FROM meta WHERE key='frozen'").fetchone()[0] == '1'
    expected_digest = hashlib.sha256(''.join(image_id + '\0' for image_id in ids).encode()).hexdigest()
    assert recorded['sha256'] == expected_digest
    assert recorded['count'] == 20_000
    assert refs.read_selection(tmp_path, receipt['selection_ref'], context) == ids

    # Replaying the same scope must not consume/rewrite the original selection.
    def do_not_consume():
        raise AssertionError('idempotent freeze must not iterate replacement IDs')
        yield 'other'
    retry = refs.freeze_selection(tmp_path, context, do_not_consume(),
        request_id=request_id, request_scope='selected-all')
    assert retry == receipt

    payload = {'train_selection_ref': receipt['selection_ref'], 'train_image_ids': ids}
    monkeypatch.setattr(refs, 'selection_context', lambda *args, **kwargs: context)
    refs.validate_payload_references(tmp_path, 'project-scale', payload)
    with pytest.raises(ValueError, match='不一致'):
        refs.validate_payload_references(tmp_path, 'project-scale',
            {**payload, 'train_image_ids': ids[:-1]})
    with pytest.raises(ValueError, match='不一致'):
        refs.validate_payload_references(tmp_path, 'project-scale',
            {**payload, 'train_image_ids': [*ids[:-1], 'outside']})


def test_streaming_selection_rejects_late_invalid_identity_without_leaking_manifest(tmp_path):
    from platform_core import training_selection_reference as refs
    def invalid_after_many():
        for i in range(2500):
            yield f'image-{i}'
        yield ' '  # A late failure must roll back every inserted identity.
    with pytest.raises(ValueError, match='invalid selection identity'):
        refs.freeze_selection(tmp_path, {'project_id': 'project-scale'}, invalid_after_many())
    assert not list((tmp_path/'task_runtime'/'artifacts').glob(
        'trainselection_*/selection.sqlite3'))
