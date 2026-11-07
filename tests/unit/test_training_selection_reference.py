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
