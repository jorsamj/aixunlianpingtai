"""Real API and temporary repositories; no production material is used."""
import uuid

import pytest
import app as host
from platform_core.annotation_candidates import CandidateStore
from platform_core.task_runtime import ArtifactStore, TaskRepository, TaskRecord, TaskKind, TaskStatus


@pytest.fixture
def review_task(seeded_project, tmp_path, monkeypatch):
    project, image = seeded_project
    repo = TaskRepository(tmp_path / 'tasks.sqlite3')
    artifacts = ArtifactStore(tmp_path / 'artifacts')
    monkeypatch.setattr(host, '_SHARED_TASK_REPOSITORY', repo)
    monkeypatch.setattr(host, '_SHARED_TASK_ARTIFACTS', artifacts)
    identity = uuid.uuid4().hex
    artifacts.atomic_write_json(identity, 'request.json', {'image_ids': [image['id']], 'labels': ['fire']})
    repo.create(TaskRecord.new(identity, project, TaskKind.AI_ANNOTATION, 'request.json', identity))
    lease = repo.claim_next('test', {TaskKind.AI_ANNOTATION}, set())
    store = CandidateStore(artifacts, task_id=identity)
    store.initialize(labels=['fire'], total_images=1)
    store.append_items([{'image_id': image['id'], 'status': 'empty', 'boxes': [], 'width':128, 'height':128}])
    repo.finish(identity, lease.lease_token, TaskStatus.AWAITING_CONFIRMATION, 'candidates/manifest.json')
    return project, image, identity, store, repo


def test_saved_draft_survives_reload_and_stale_revision_conflicts(client, review_task):
    project, image, task, store, _ = review_task
    base = f'/api/v60/projects/{project}/annotation-tasks/{task}'
    original = host.read_annotation(project, image['id'])
    boxes = [{'label':'fire','x1':10,'y1':12,'x2':64,'y2':96}]
    result = client.put(base+f"/candidates/{image['id']}/draft", json={
        'boxes':boxes, 'revision':0, 'request_id':'draft-test-00001'})
    assert result.status_code == 200, result.text
    assert result.json()['revision'] == 1
    repeat=client.put(base+f"/candidates/{image['id']}/draft",json={'boxes':boxes,'revision':0,'request_id':'draft-test-00001'})
    assert repeat.status_code==200,repeat.text
    assert repeat.json()['revision']==1
    page = client.get(base+'/candidates').json()
    assert page['items'][0]['boxes'][0]['x1'] == 10
    assert host.read_annotation(project, image['id']) == original
    stale = client.put(base+f"/candidates/{image['id']}/draft", json={
        'boxes':[], 'revision':0, 'request_id':'draft-test-00002'})
    assert stale.status_code == 409


def test_no_candidate_artifact_still_has_readable_details(client, review_task):
    project, image, task, store, repo = review_task
    other = uuid.uuid4().hex
    store.artifacts.atomic_write_json(other, 'request.json', {'image_ids':[image['id']], 'labels':['fire']})
    repo.create(TaskRecord.new(other, project, TaskKind.AI_ANNOTATION, 'request.json', other))
    repo.request_cancel(other)
    response = client.get(f'/api/v60/projects/{project}/annotation-tasks/{other}/candidates')
    assert response.status_code == 200, response.text
    assert response.json()['items'] == []
    assert response.json()['task_error'] is not None


def test_transfer_excludes_boxes_and_undo_restores_review_without_gt(client, review_task):
    from platform_core.negative_pool import NegativePool
    project, image, task, store, _ = review_task
    pool = NegativePool(host.material_store(project))
    category = pool.category(name='review-'+uuid.uuid4().hex)
    item = store.get(image['id']);item['status']='success';item['boxes']=[{'label':'fire','x1':1,'y1':1,'x2':30,'y2':30}]
    store.append_items([item])
    base = f'/api/v60/projects/{project}/annotation-tasks/{task}'
    body = {'request_id':'transfer-test-001','image_ids':[image['id']], 'category_ids':[category['id']], 'confirm_absent':False,
            'review_revision':store.review_revision()}
    preview = client.post(base+'/negative-transfer-preview',json=body)
    assert preview.status_code == 200,preview.text
    assert preview.json()['discarded_boxes']==1
    response = client.post(base+'/negative-transfer',json=body)
    assert response.status_code==200,response.text
    assert response.json()['succeeded']==1
    assert store.get(image['id'])['review_state']=='transferred'
    assert store.review_counts()['remaining_reviewable']==0
    repeat=client.post(base+'/negative-transfer',json=body)
    assert repeat.json()['succeeded']==1
    assert not host.read_annotation(project,image['id'])['boxes']
    store.decide_unmentioned(True)
    assert list(store.iter_accepted_items())==[]
    undo=client.post(base+'/negative-transfer/transfer-test-001/undo')
    assert undo.status_code==200,undo.text
    assert store.get(image['id'])['review_state']=='active'
    assert image['id'] not in pool.candidate_ids()


def test_transfer_failure_remains_excluded_and_original_request_recovers(client, review_task, monkeypatch):
    from platform_core.negative_pool import NegativePool
    project,image,task,store,_=review_task
    pool=NegativePool(host.material_store(project));category=pool.category(name='recover-'+uuid.uuid4().hex)
    base=f'/api/v60/projects/{project}/annotation-tasks/{task}'
    body={'request_id':'transfer-test-002','image_ids':[image['id']],'category_ids':[category['id']]}
    original=NegativePool.members
    def fail(*args,**kwargs): raise ValueError('isolated transient failure')
    monkeypatch.setattr(NegativePool,'members',fail)
    failed=client.post(base+'/negative-transfer',json=body)
    assert failed.status_code==200,failed.text
    assert failed.json()['failed']==1
    assert store.get(image['id'])['review_state']=='blocked'
    store.decide_unmentioned(True)
    assert list(store.iter_accepted_items())==[]
    monkeypatch.setattr(NegativePool,'members',original)
    recovered=client.post(base+'/negative-transfer',json=body)
    assert recovered.json()['succeeded']==1,recovered.text
    assert store.get(image['id'])['review_state']=='transferred'


def test_transfer_gt_conflict_and_stale_final_count_fail_closed(client, review_task):
    from platform_core.negative_pool import NegativePool
    project,image,task,store,_=review_task
    category=NegativePool(host.material_store(project)).category(name='conflict-'+uuid.uuid4().hex)
    host._v50_annotation_repository(project).upsert(image['id'],boxes=[{'label':'fire','class_id':0,'x1':1,'y1':1,'x2':40,'y2':40}],annotation_state='annotated')
    base=f'/api/v60/projects/{project}/annotation-tasks/{task}'
    response=client.post(base+'/negative-transfer',json={'request_id':'transfer-test-003','image_ids':[image['id']],'category_ids':[category['id']]})
    assert response.status_code==200,response.text
    assert response.json()['conflicts']==1
    assert host.read_annotation(project,image['id'])['boxes']
    stale=client.post(base+'/decisions',json={'decisions':[],'accept_unmentioned':True,'reject_unmentioned':False,'expected_remaining':99})
    assert stale.status_code==409,stale.text


def test_40_boxed_and_60_empty_transfers_leave_exact_remaining_scope(client, review_task):
    from platform_core.negative_pool import NegativePool
    project,image,task,store,_=review_task
    materials=host.material_store(project)
    original=materials.get(image['id'])
    ids=[f'batch-{i:03}' for i in range(111)]
    materials.upsert_many([{**original,'id':value,'filename':value+'.jpg'} for value in ids])
    store.initialize(labels=['fire'],total_images=111)
    store.append_items([{'image_id':value,'status':'success' if i<40 or i>=100 else 'empty',
                         'boxes':[{'label':'fire','x1':1,'y1':1,'x2':20,'y2':20}] if i<40 or i>=100 else []}
                        for i,value in enumerate(ids)])
    category=NegativePool(materials).category(name='batch-'+uuid.uuid4().hex)
    base=f'/api/v60/projects/{project}/annotation-tasks/{task}'
    first=client.post(base+'/negative-transfer',json={'request_id':'transfer-batch-0040','image_ids':ids[:40],'category_ids':[category['id']]})
    assert first.status_code==200,first.text
    assert first.json()['succeeded']==40
    selection=client.post(base+'/review-selection',json={'filter':'empty','review_revision':store.review_revision()}).json()
    assert selection['total']==60
    second=client.post(base+'/negative-transfer',json={'request_id':'transfer-batch-0060','selection_id':selection['selection_id'],'category_ids':[category['id']],'review_revision':selection['review_revision']})
    assert second.status_code==200,second.text
    assert second.json()['succeeded']==60
    assert store.review_counts()['remaining_reviewable']==11
    final=client.post(base+'/decisions',json={'decisions':[],'accept_unmentioned':True,'reject_unmentioned':False,'commit':False,'expected_remaining':11,'review_revision':store.review_revision()})
    assert final.status_code==200,final.text
    assert {row['image_id'] for row in store.iter_accepted_items()}==set(ids[100:])
    assert store.review_counts()['transferred']==100
    assert len(materials.get_many(ids))==111
    assert all(not row['boxes'] for row in host.read_annotations_many(project,ids).values())


def test_cross_page_selection_with_180_images_and_exclusions(client, review_task):
    from platform_core.negative_pool import NegativePool
    project,image,task,store,_=review_task
    materials=host.material_store(project);original=materials.get(image['id'])
    ids=[f'cross-{i:03}' for i in range(240)]
    materials.upsert_many([{**original,'id':value,'filename':value+'.jpg'} for value in ids])
    store.initialize(labels=['fire'],total_images=240)
    store.append_items({'image_id':value,'status':'empty','boxes':[]} for value in ids)
    pool=NegativePool(materials);category=pool.category(name='cross-'+uuid.uuid4().hex)
    base=f'/api/v60/projects/{project}/annotation-tasks/{task}'
    selection=client.post(base+'/review-selection',json={'filter':'empty'}).json()
    body={'request_id':'transfer-cross-page-180','selection_id':selection['selection_id'],'excluded_image_ids':ids[180:],'category_ids':[category['id']]}
    transferred=client.post(base+'/negative-transfer',json=body)
    assert transferred.status_code==200,transferred.text
    assert transferred.json()['succeeded']==180
    first=client.get(base+'/candidates?filter=transferred&limit=100').json()
    assert first['total']==180 and len(first['items'])==100
    second=client.get(base+'/candidates?filter=transferred&limit=100&cursor='+first['next_cursor']).json()
    assert len(second['items'])==80 and second['next_cursor'] is None
    assert store.review_counts()['remaining_reviewable']==60
    assert client.post(base+'/negative-transfer',json=body).json()['succeeded']==180


def test_explicit_absence_confirmation_records_formal_scope_only_after_opt_in(client, review_task):
    from platform_core.negative_pool import NegativePool
    project,image,task,store,_=review_task
    algorithm=host.create_algorithm_asset(host.project_dir(project)/'algorithms.json',{'name':'isolated-absence'},host.now_iso())
    category=NegativePool(host.material_store(project)).category(name='confirm-'+uuid.uuid4().hex)
    base=f'/api/v60/projects/{project}/annotation-tasks/{task}'
    response=client.post(base+'/negative-transfer',json={'request_id':'transfer-human-confirm','image_ids':[image['id']],'category_ids':[category['id']],'algorithm_id':algorithm['id'],'confirm_absent':True})
    assert response.status_code==200,response.text
    assert response.json()['succeeded']==1,response.text
    formal=host.read_annotation(project,image['id'])
    assert formal['annotation_state']=='confirmed_empty'
    assert 'fire' in formal['annotation_scope']
    assert not formal['boxes']


def test_transfer_attempts_later_pages_before_retrying_failed_first_batch(client, review_task, monkeypatch):
    from platform_core.negative_pool import NegativePool
    project,image,task,store,_=review_task
    materials=host.material_store(project);original=materials.get(image['id'])
    ids=[f'failed-batch-{i:03}' for i in range(240)]
    materials.upsert_many([{**original,'id':value,'filename':value+'.jpg'} for value in ids])
    store.initialize(labels=['fire'],total_images=240)
    store.append_items({'image_id':value,'status':'empty','boxes':[]} for value in ids)
    pool=NegativePool(materials);category=pool.category(name='failed-page-'+uuid.uuid4().hex)
    base=f'/api/v60/projects/{project}/annotation-tasks/{task}'
    selection=client.post(base+'/review-selection',json={'filter':'empty'}).json()
    calls=[];real=NegativePool.members
    def fail(self,image_ids,**kwargs):
        calls.extend(image_ids);raise ValueError('isolated unavailable pool')
    monkeypatch.setattr(NegativePool,'members',fail)
    body={'request_id':'transfer-progress-240','selection_id':selection['selection_id'],'category_ids':[category['id']]}
    first=client.post(base+'/negative-transfer',json=body).json()
    assert first['status']=='pending' and first['failed']==200
    second=client.post(base+'/negative-transfer',json=body).json()
    assert second['status']=='partial' and second['failed']==240
    assert len(calls)==240 and len(set(calls))==240
    monkeypatch.setattr(NegativePool,'members',real)
    resumed=client.post(base+'/negative-transfer',json=body).json()
    assert resumed['succeeded']==200
    completed=client.post(base+'/negative-transfer',json=body).json()
    assert completed['status']=='completed' and completed['succeeded']==240


def test_completed_transfer_replay_does_not_rebase_undo_revision(client, review_task):
    from platform_core.negative_pool import NegativePool
    project,image,task,store,_=review_task
    pool=NegativePool(host.material_store(project));category=pool.category(name='before-'+uuid.uuid4().hex)
    base=f'/api/v60/projects/{project}/annotation-tasks/{task}'
    body={'request_id':'completed-receipt-rebase','image_ids':[image['id']],'category_ids':[category['id']]}
    assert client.post(base+'/negative-transfer',json=body).json()['status']=='completed'
    later=pool.category(name='after-'+uuid.uuid4().hex)
    pool.members([image['id']],category_ids=[later['id']])
    assert client.post(base+'/negative-transfer',json=body).json()['status']=='completed'
    undo=client.post(base+'/negative-transfer/completed-receipt-rebase/undo')
    assert undo.status_code==409,undo.text
    assert later['id'] in pool.member_snapshot(image['id'])['categories']


def test_transfer_manifest_writes_are_bounded_and_mid_batch_pool_changes_survive(client, review_task, monkeypatch):
    from platform_core.negative_pool import NegativePool
    project,image,task,store,_=review_task
    materials=host.material_store(project);original=materials.get(image['id'])
    ids=[f'bounded-{i:03}' for i in range(240)]
    materials.upsert_many([{**original,'id':value,'filename':value+'.jpg'} for value in ids])
    store.initialize(labels=['fire'],total_images=240)
    store.append_items({'image_id':value,'status':'empty','boxes':[]} for value in ids)
    pool=NegativePool(materials);category=pool.category(name='bounded-'+uuid.uuid4().hex)
    base=f'/api/v60/projects/{project}/annotation-tasks/{task}'
    selection=client.post(base+'/review-selection',json={'filter':'empty'}).json()
    writes=[];original_write=ArtifactStore.atomic_write_json
    def observe(self,task_id,ref,payload):
        if str(ref).startswith('review/transfers/') and isinstance(payload,dict) and 'image_ids' in payload:writes.append(len(payload.get('items') or {}))
        return original_write(self,task_id,ref,payload)
    monkeypatch.setattr(ArtifactStore,'atomic_write_json',observe)
    body={'request_id':'transfer-bounded-240','selection_id':selection['selection_id'],'category_ids':[category['id']]}
    assert client.post(base+'/negative-transfer',json=body).json()['status']=='pending'
    assert len(writes)<=4,'the whole task manifest must not be rewritten per image'
    later=pool.category(name='intervening-'+uuid.uuid4().hex)
    pool.members([ids[0]],category_ids=[later['id']])
    assert client.post(base+'/negative-transfer',json=body).json()['status']=='completed'
    undo=client.post(base+'/negative-transfer/transfer-bounded-240/undo')
    assert undo.status_code==409,undo.text
    assert later['id'] in pool.member_snapshot(ids[0])['categories']


def test_transfer_receipt_pages_and_undo_crash_recover_from_original_pool_receipt(client, review_task, monkeypatch):
    from platform_core.negative_pool import NegativePool
    project,image,task,store,_=review_task
    pool=NegativePool(host.material_store(project));category=pool.category(name='crash-'+uuid.uuid4().hex)
    base=f'/api/v60/projects/{project}/annotation-tasks/{task}'
    body={'request_id':'undo-crash-safe-001','image_ids':[image['id']],'category_ids':[category['id']]}
    original = CandidateStore.set_review_exclusion

    def crash_after_pool(self, image_id, state, **kwargs):
        if state == 'transferred':
            raise RuntimeError('interrupted after membership write')
        return original(self, image_id, state, **kwargs)

    revision = int(pool.revision())
    with monkeypatch.context() as patch:
        patch.setattr(CandidateStore, 'set_review_exclusion', crash_after_pool)
        with pytest.raises(RuntimeError, match='after membership write'):
            client.post(base+'/negative-transfer', json=body)
    assert pool.member_snapshot(image['id'])['member']
    assert int(pool.revision()) == revision + 1
    assert client.post(base+'/negative-transfer',json=body).json()['status']=='completed'
    assert int(pool.revision()) == revision + 1
    page=client.get(base+'/negative-transfer/undo-crash-safe-001').json()
    assert len(page['items'])==1 and page['processed']==1 and 'image_ids' not in page
    original=CandidateStore.set_review_exclusion
    def crash(self,image_id,state,**kwargs):
        if state=='active':raise ValueError('isolated crash after pool restore')
        return original(self,image_id,state,**kwargs)
    monkeypatch.setattr(CandidateStore,'set_review_exclusion',crash)
    assert client.post(base+'/negative-transfer/undo-crash-safe-001/undo').status_code==409
    assert not pool.member_snapshot(image['id'])['member']
    assert int(pool.revision()) == revision + 2
    monkeypatch.setattr(CandidateStore,'set_review_exclusion',original)
    resumed=client.post(base+'/negative-transfer/undo-crash-safe-001/undo')
    assert resumed.status_code==200,resumed.text
    assert resumed.json()['status']=='undone' and store.get(image['id'])['review_state']=='active'
    assert int(pool.revision()) == revision + 2


def test_legacy_json_transfer_receipt_is_archived_and_migrated_without_gt_changes(client, review_task):
    from platform_core.negative_pool import NegativePool
    project,image,task,store,_=review_task
    category=NegativePool(host.material_store(project)).category(name='legacy-'+uuid.uuid4().hex)
    base=f'/api/v60/projects/{project}/annotation-tasks/{task}'
    body={'request_id':'legacy-transfer-safe','image_ids':[image['id']],'category_ids':[category['id']]}
    assert client.post(base+'/negative-transfer',json=body).json()['status']=='completed'
    ref=host._annotation_review_operation_path(body['request_id']).replace('review/operations/','review/transfers/')
    receipt=store.artifacts.read_json(task,ref);receipt['items']=store.read_transfer_receipts(body['request_id'])
    receipt.pop('receipt_storage',None);receipt.pop('pool_revision_base',None)
    store.artifacts.atomic_write_json(task,ref,receipt)
    import sqlite3
    with sqlite3.connect(store.path) as db:db.execute('DELETE FROM review_transfer_receipts WHERE operation_id=?',(body['request_id'],))
    replay=client.post(base+'/negative-transfer',json=body)
    assert replay.status_code==200 and replay.json()['idempotent']
    migrated=store.artifacts.read_json(task,ref)
    assert migrated['receipt_storage']=='candidate_sqlite_v1' and 'items' not in migrated
    assert store.artifacts.read_json(task,migrated['legacy_audit_ref'])['items']
    assert not host.read_annotation(project,image['id'])['boxes']


def test_frozen_review_selection_pages_all_filtered_ids_and_rejects_stale_revision(client, review_task):
    project, image, task, store, _ = review_task
    material_store = host.material_store(project)
    source = material_store.get(image['id'])
    ids = [f'review-paged-{index:03}' for index in range(205)]
    material_store.upsert_many([{**source, 'id':item_id, 'filename':item_id+'.jpg'} for item_id in ids])
    store.initialize(labels=['fire'], total_images=len(ids))
    store.append_items({'image_id':item_id, 'status':'success',
                        'boxes':[{'label':'fire','x1':1,'y1':2,'x2':20,'y2':25}]}
                       for item_id in ids)
    base = f'/api/v60/projects/{project}/annotation-tasks/{task}'
    frozen_response = client.post(base+'/review-selection', json={
        'filter':'clean_boxes', 'review_revision':store.review_revision()})
    assert frozen_response.status_code == 200, frozen_response.text
    frozen = frozen_response.json()
    assert frozen['total'] == 205
    url = base+'/review-selection/'+frozen['selection_id']+'/candidates'
    first = client.get(url+'?cursor=0&limit=200')
    assert first.status_code == 200, first.text
    assert [row['image_id'] for row in first.json()['items']] == ids[:200]
    assert first.json()['next_cursor'] == '200'
    second = client.get(url+'?cursor=200&limit=200')
    assert second.status_code == 200, second.text
    assert [row['image_id'] for row in second.json()['items']] == ids[200:]
    assert second.json()['next_cursor'] is None
    assert client.get(url+'?limit=201').status_code == 422
    store.save_draft(ids[0], [], expected_revision=0,
                     actor='isolated-review', request_id='revision-bump-review')
    assert client.get(url).status_code == 409


def test_batch_candidate_drafts_use_original_cas_replay_and_leave_gt_untouched(client, review_task):
    project, image, task, store, _ = review_task
    materials = host.material_store(project)
    source = materials.get(image['id'])
    second_id = 'review-batch-second'
    materials.upsert_many([{**source, 'id':second_id, 'filename':'second.jpg'}])
    ids = [image['id'], second_id]
    store.initialize(labels=['fire'], total_images=2)
    store.append_items({'image_id':item_id, 'status':'success',
                        'boxes':[{'label':'fire','x1':1,'y1':1,'x2':30,'y2':30}]}
                       for item_id in ids)
    baseline = {item_id:host.read_annotation(project,item_id) for item_id in ids}
    url = f'/api/v60/projects/{project}/annotation-tasks/{task}/candidates/drafts-batch'
    boxes = [{'label':'fire','x1':2,'y1':3,'x2':45,'y2':50}]
    payload = {'items':[{'image_id':item_id, 'boxes':boxes, 'revision':0,
                         'request_id':'draft-batch-'+str(index)} for index,item_id in enumerate(ids)]}
    response = client.post(url,json=payload)
    assert response.status_code == 200, response.text
    assert response.json()['saved'] == 2
    assert all(row['ok'] and row['revision'] == 1 for row in response.json()['items'])
    replay = client.post(url,json=payload)
    assert replay.status_code == 200, replay.text
    assert [row['revision'] for row in replay.json()['items']] == [1,1]
    assert all(store.get(item_id)['draft_revision'] == 1 for item_id in ids)
    assert {item_id:host.read_annotation(project,item_id) for item_id in ids} == baseline
    stale = client.post(url,json={'items':[{'image_id':ids[0], 'boxes':[],
                                           'revision':0, 'request_id':'draft-batch-new'}]})
    assert stale.status_code == 200, stale.text
    assert stale.json()['saved'] == 0
    assert stale.json()['items'][0]['status_code'] == 409
    assert client.post(url,json={'items':[payload['items'][0],payload['items'][0]]}).status_code == 422


def test_review_accept_selected_only_does_not_accept_other_clean_or_ambiguous_candidates(client, review_task):
    project, image, task, store, repo = review_task
    materials = host.material_store(project)
    source = materials.get(image['id'])
    ids = ['selected-clean-0','selected-clean-1','selected-clean-2','unselected-empty-3']
    materials.upsert_many([{**source,'id':item_id,'filename':item_id+'.jpg'} for item_id in ids])
    store.initialize(labels=['fire'], total_images=4)
    store.append_items({'image_id':item_id,
                        'status':'success' if index<3 else 'empty',
                        'boxes':[{'label':'fire','x1':1,'y1':2,'x2':30,'y2':40}] if index<3 else []}
                       for index,item_id in enumerate(ids))
    baseline = {item_id:host.read_annotation(project,item_id) for item_id in ids}
    base = f'/api/v60/projects/{project}/annotation-tasks/{task}'
    frozen = client.post(base+'/review-selection',json={
        'filter':'clean_boxes','review_revision':store.review_revision()})
    assert frozen.status_code == 200, frozen.text
    assert frozen.json()['total'] == 3
    accepted_ids = ids[:2]
    approved = client.post(base+'/decisions',json={
        'decisions':[{'image_id':item_id,'accepted':True} for item_id in accepted_ids],
        'accept_unmentioned':False,'reject_unmentioned':False,'commit':False,
        'request_id':'review-selected-only-001','review_revision':store.review_revision()})
    assert approved.status_code == 200, approved.text
    assert {item['image_id'] for item in store.iter_accepted_items()} == set(accepted_ids)
    assert store.get(ids[2])['accepted'] is None
    assert store.get(ids[3])['accepted'] is None
    assert repo.get(task).status is TaskStatus.AWAITING_CONFIRMATION
    assert {item_id:host.read_annotation(project,item_id) for item_id in ids} == baseline

def test_selected_twice_confirmed_writes_formal_gt_immediately_without_finishing_other_candidates(client, review_task, monkeypatch):
    """Explicit user-selected batches commit formal GT, not a mere accepted draft."""
    project, image, task, store, repo = review_task
    from io import BytesIO
    from PIL import Image

    def upload_test_image(name, color):
        buffer = BytesIO()
        Image.new('RGB', (128, 128), color).save(buffer, format='JPEG')
        response = client.post(f'/api/projects/{project}/images',
            files=[('files', (name, buffer.getvalue(), 'image/jpeg'))],
            data={'dataset_id':'default'})
        assert response.status_code in (200, 201), response.text
        return response.json()['uploaded'][0]['id']

    ids = [image['id'], upload_test_image('direct-ambiguous.jpg', 'red'),
           upload_test_image('direct-unselected.jpg', 'blue')]
    materials = host.material_store(project)
    source_hashes = [materials.get(image_id)['content_sha256'] for image_id in ids]
    store.initialize(labels=['fire','smoke'], total_images=3)
    fire = {'label':'fire','x1':12,'y1':12,'x2':60,'y2':60}
    smoke = {'label':'smoke','x1':12,'y1':12,'x2':60,'y2':60}
    store.append_items([
        {'image_id':ids[0], 'status':'success', 'boxes':[fire], 'source_content_sha256':source_hashes[0]},
        {'image_id':ids[1], 'status':'success', 'boxes':[fire,smoke],
         'manual_review_required':True, 'source_content_sha256':source_hashes[1]},
        {'image_id':ids[2], 'status':'empty', 'boxes':[], 'source_content_sha256':source_hashes[2]},
    ])
    base = f'/api/v60/projects/{project}/annotation-tasks/{task}'
    rejected = client.post(base+'/decisions',json={
        'decisions':[{'image_id':ids[0],'accepted':True}],
        'reject_unmentioned':True,'accept_unmentioned':False,
        'commit':True,'commit_selected':True,'request_id':'direct-gt-invalid-0001',
        'review_revision':store.review_revision(),
    })
    assert rejected.status_code == 422, rejected.text
    body = {
        'decisions':[{'image_id':ids[0],'accepted':True}],
        'reject_unmentioned':False,'accept_unmentioned':False,
        'commit':True,'commit_selected':True,'request_id':'direct-gt-selected-0001',
        'review_revision':store.review_revision(),
    }
    def crash_before_journal(*args, **kwargs):
        raise OSError('interrupted after formal GT commit')

    before_write = {**body, 'request_id': 'direct-gt-interrupted-0001'}
    with monkeypatch.context() as patch:
        patch.setattr(host, '_decide_annotation_candidates', crash_before_journal)
        with pytest.raises(OSError):
            client.post(base+'/decisions', json=before_write)
    unwritten = client.get(base+'/decisions/by-request/'+before_write['request_id']).json()
    assert unwritten['status'] == 'rejected' and unwritten['detail']['code'] == 'REVIEW_NOT_COMMITTED'
    assert client.post(base+'/decisions', json=before_write).status_code == 409

    with monkeypatch.context() as patch:
        patch.setattr(CandidateStore, 'record_commit_summaries', crash_before_journal)
        with pytest.raises(OSError, match='after formal GT'):
            client.post(base+'/decisions', json=body)
    saved = host.read_annotation(project, ids[0])
    assert saved['version'] > 0 and store.get_commit_summaries(ids) == {}
    assert client.post(base+'/decisions', json={**body, 'review_revision': 999}).status_code == 409
    first = client.get(base+'/decisions/by-request/'+body['request_id'])
    assert first.status_code == 200, first.text
    result = first.json()['result']
    assert result['committed_selected'] is True
    assert result['applied_images'] == result['boxes_added'] == 1
    assert host.read_annotation(project, ids[0])['boxes'][0]['label'] == 'fire'
    assert host.read_annotation(project, ids[1])['boxes'] == []
    assert host.read_annotation(project, ids[2])['boxes'] == []
    assert set(store.get_commit_summaries(ids)) == {ids[0]}
    assert store.get(ids[1])['accepted'] is None
    assert store.get(ids[2])['accepted'] is None
    assert repo.get(task).status is TaskStatus.AWAITING_CONFIRMATION

    replay = client.post(base+'/decisions',json=body)
    assert replay.status_code == 200, replay.text
    assert replay.json() == {**result, 'idempotent': True}
    assert host.read_annotation(project, ids[0]) == saved

    second = client.post(base+'/decisions',json={
        'decisions':[{'image_id':ids[1],'accepted':True,'boxes':[fire]}],
        'reject_unmentioned':False,'accept_unmentioned':False,
        'commit':True,'commit_selected':True,'request_id':'direct-gt-selected-0002',
        'review_revision':store.review_revision(),
    })
    assert second.status_code == 200, second.text
    assert second.json()['committed_selected'] is True
    assert len(host.read_annotation(project,ids[1])['boxes']) == 1
    assert host.read_annotation(project,ids[1])['boxes'][0]['label'] == 'fire'
    assert host.read_annotation(project,ids[2])['boxes'] == []
    assert store.get(ids[2])['accepted'] is None
    assert set(store.get_commit_summaries(ids)) == set(ids[:2])
    assert repo.get(task).status is TaskStatus.AWAITING_CONFIRMATION

    # Legacy actorless receipts may repair a journal, but cannot be claimed.
    legacy = _formal_selection_body(store, [ids[2]], "legacy-actorless-formal-001")
    path = host._annotation_review_operation_path(legacy["request_id"])
    with monkeypatch.context() as patch:
        patch.setattr(CandidateStore, "record_commit_summaries", crash_before_journal)
        with pytest.raises(OSError, match="after formal GT"):
            client.post(base + "/decisions", json=legacy)
    legacy_gt = host.read_annotation(project, ids[2])
    assert legacy_gt["annotation_state"] == "confirmed_empty"
    pending = store.artifacts.read_json(task, path)
    pending.pop("actor")
    store.artifacts.atomic_write_json(task, path, pending)
    assert client.get(base + "/decisions/by-request/" + legacy["request_id"]).status_code == 404
    assert client.post(base + "/decisions", json=legacy).status_code == 404
    repaired = store.artifacts.read_json(task, path)
    assert repaired["status"] == "completed" and "actor" not in repaired
    assert ids[2] in store.get_commit_summaries(ids)
    assert host.read_annotation(project, ids[2]) == legacy_gt


def test_transfer_snapshot_is_scoped_to_operator_and_purpose(client, review_task, monkeypatch):
    from platform_core.negative_pool import NegativePool

    project, image, task, store, _ = review_task
    pool = NegativePool(host.material_store(project))
    category = pool.category(name='scope-'+uuid.uuid4().hex)
    base = f'/api/v60/projects/{project}/annotation-tasks/{task}'
    actor = 'reviewer-one'
    monkeypatch.setattr(host, '_material_governance_actor', lambda *_: {'actor_id': actor})
    store.append_items([{'image_id': 'failed-candidate', 'status': 'failed', 'boxes': []}])
    frozen = client.post(base+'/review-selection', json={'filter': 'all', 'purpose': 'transfer'}).json()
    assert frozen['purpose'] == 'transfer'
    assert (frozen['filtered_total'], frozen['total'], frozen['reasons']) == (2, 1, {'failed': 1})
    body = {'request_id': 'transfer-actor-0001', 'selection_id': frozen['selection_id'],
            'category_ids': [category['id']], 'review_revision': frozen['review_revision']}
    selection_url = base+'/review-selection/'+frozen['selection_id']+'/candidates'
    revision = pool.revision()
    actor = 'reviewer-two'
    assert client.get(selection_url).status_code == 404
    for route in ('/negative-transfer-preview', '/negative-transfer'):
        assert client.post(base+route, json=body).status_code == 404
    assert pool.revision() == revision
    actor = 'reviewer-one'
    visible = client.get(base+'/candidates', params={'selection_id': frozen['selection_id']}).json()['items']
    assert {row['image_id']: row['selection_member'] for row in visible} == {
        image['id']: True, 'failed-candidate': False,
    }
    assert client.post(base+'/negative-transfer-preview', json=body).json()['eligible'] == 1
    changed = {**body, 'confirm_absent': True}
    assert client.post(base+'/negative-transfer', json=changed).status_code == 409
    assert client.post(base+'/negative-transfer', json=body).json()['succeeded'] == 1
    assert pool.member_snapshot(image['id'])['member']


def test_worker_recovers_its_supplement_receipt_but_rejects_external_gt(client, review_task, monkeypatch):
    from types import SimpleNamespace
    from platform_core.annotation_candidates import CandidateDecision
    from platform_core.annotation_task_service import commit_confirmed_review

    project, image, task, store, repo = review_task
    image_id = image['id']
    source_hash = host.material_store(project).get(image_id)['content_sha256']
    annotations = host._v50_annotation_repository(project)
    initial_version = host.read_annotation(project, image_id)['version']
    store.append_items([{'image_id': image_id, 'status': 'empty', 'boxes': [],
                         'source_content_sha256': source_hash}])
    store.apply_decisions([CandidateDecision(image_id, True, review_scope=['fire'])])
    store.artifacts.atomic_write_json(task, 'request.json', {
        'labels': ['fire'], 'review_scope_policy': 'per_image_required',
        'per_image_annotation_versions': {image_id: initial_version},
        'per_image_missing_review_scopes': {image_id: ['fire']},
        'per_image_source_hashes': {image_id: source_hash},
    })
    store.artifacts.atomic_write_json(task, 'review/confirmation.json',
                                      {'accepted': True, 'review_request_id': 'supplement-crash-01'})
    worker = SimpleNamespace(task=repo.get(task), repository=repo, artifacts=store.artifacts,
                             heartbeat=lambda **_: None, cancel_requested=lambda: False)

    def crash_before_journal(*args, **kwargs):
        raise OSError('interrupted after supplemental GT')

    with monkeypatch.context() as patch:
        patch.setattr(CandidateStore, 'record_commit_summaries', crash_before_journal)
        with pytest.raises(OSError, match='after supplemental GT'):
            commit_confirmed_review(worker)
    proof = host.read_annotation(project, image_id)
    assert proof['version'] > initial_version
    assert store.get_commit_summaries([image_id]) == {}

    assert commit_confirmed_review(worker) == (TaskStatus.SUCCEEDED, 'review/result.json')
    assert host.read_annotation(project, image_id) == proof
    journal = store.get_commit_summaries([image_id])[image_id]
    assert (journal['gt_snapshot_version'], journal['gt_snapshot_digest']) == (proof['version'], proof['content_digest'])

    edited = [{'label': 'fire', 'class_id': 0, 'x1': 1, 'y1': 2, 'x2': 10, 'y2': 20}]
    annotations.upsert(image_id, boxes=edited, annotation_state='annotated')
    # Reproduce the same missing journal window with a later external GT edit.
    with monkeypatch.context() as patch:
        patch.setattr(CandidateStore, 'get_commit_summaries', lambda *_: {})
        with pytest.raises(ValueError, match='AI_SUPPLEMENT_GT_CHANGED'):
            commit_confirmed_review(worker)
    assert host.read_annotation(project, image_id)['boxes'][0]['x1'] == 1


def test_explicit_single_decision_isolated_and_recovers_durable_receipt(client, review_task, monkeypatch):
    project, image, task, store, repo = review_task
    target = image["id"]
    retired = "unselected-retired-label"
    invalid = "selected-retired-label"
    box = {"label": "fire", "class_id": 0, "x1": 1, "y1": 2, "x2": 30, "y2": 40}
    store.append_items([
        {"image_id": target, "status": "success", "boxes": [box]},
        {"image_id": retired, "status": "success", "boxes": [{**box, "label": "retired"}]},
        {"image_id": invalid, "status": "success", "boxes": [{**box, "label": "retired"}]},
    ])
    base = f"/api/v60/projects/{project}/annotation-tasks/{task}"
    def body(image_id, accepted, request_id, **extra):
        return {"single_candidate": True, "decisions": [{"image_id": image_id, "accepted": accepted, **extra}],
                "commit": False, "commit_selected": False, "accept_unmentioned": False,
                "reject_unmentioned": False, "request_id": request_id, "review_revision": store.review_revision()}

    def candidate_rows():
        from contextlib import closing
        with closing(store._connect()) as db:
            return {row["image_id"]: tuple(row) for row in db.execute("SELECT * FROM candidates")}

    initial = candidate_rows()
    gt = host.read_annotations_many(project, [target, retired, invalid])
    apply = body(target, True, "single-apply-00001")
    applied = client.post(base+"/decisions", json=apply)
    assert applied.status_code == 200, applied.text
    assert applied.json()["accepted"] is True
    assert applied.json()["review_revision"] == apply["review_revision"] + 1
    assert store.get(target)["accepted"] is True
    before = candidate_rows()
    assert before[retired] == initial[retired] and before[invalid] == initial[invalid]

    not_written = body(invalid, True, "single-invalid-0001")
    assert client.post(base+"/decisions", json=not_written).status_code == 409
    assert candidate_rows() == before
    assert store.review_revision() == not_written["review_revision"]

    reject = body(target, False, "single-reject-0001")
    path = host._annotation_review_operation_path(reject["request_id"])
    write = store.artifacts.atomic_write_json
    def interrupt_after_commit(task_id, ref, value):
        if ref == path and value.get("status") == "completed":
            raise OSError("interrupted after single decision")
        return write(task_id, ref, value)
    with monkeypatch.context() as patch:
        patch.setattr(store.artifacts, "atomic_write_json", interrupt_after_commit)
        with pytest.raises(OSError, match="after single decision"):
            client.post(base+"/decisions", json=reject)
    assert store.get(target)["accepted"] is False

    # A later operator's result cannot stand in for the original evidence.
    later = client.post(base+"/decisions", json=body(target, True, "single-later-00001"))
    assert later.status_code == 200
    recovered = client.get(base+"/decisions/by-request/"+reject["request_id"])
    assert recovered.status_code == 200
    assert recovered.json()["status"] == "completed"
    assert recovered.json()["result"]["accepted"] is False
    assert recovered.json()["result"]["review_revision"] == reject["review_revision"] + 1
    replay = client.post(base+"/decisions", json=reject)
    assert replay.json() == {**recovered.json()["result"], "idempotent": True}
    changed = {**reject, "decisions": [{"image_id": target, "accepted": True}]}
    assert client.post(base+"/decisions", json=changed).status_code == 409
    stale = {**apply, "request_id": "single-stale-00001"}
    assert client.post(base+"/decisions", json=stale).status_code == 409
    after = candidate_rows()
    assert after[retired] == initial[retired] and after[invalid] == initial[invalid]
    assert store.get(target)["accepted"] is True
    assert store.review_revision() == later.json()["review_revision"]
    assert host.read_annotations_many(project, [target, retired, invalid]) == gt
    assert repo.get(task).status is TaskStatus.AWAITING_CONFIRMATION

    with monkeypatch.context() as patch:
        patch.setattr(host, "_material_governance_actor", lambda *_: {"actor_id": "other-operator"})
        assert client.get(base+"/decisions/by-request/"+reject["request_id"]).status_code == 404
        assert client.post(base+"/decisions", json=reject).status_code == 409

    never_written = body(target, False, "single-pending-001")
    with monkeypatch.context() as patch:
        def interrupt_before_commit(*args):
            raise OSError("interrupted before single decision")
        patch.setattr(host, "_decide_single_annotation_candidate", interrupt_before_commit)
        with pytest.raises(OSError, match="before single decision"):
            client.post(base+"/decisions", json=never_written)
    receipt = client.get(base+"/decisions/by-request/"+never_written["request_id"])
    assert receipt.status_code == 202 and receipt.json()["status"] == "pending"
    assert client.post(base+"/decisions", json=never_written).status_code == 202
    assert candidate_rows() == after
    assert store.review_revision() == later.json()["review_revision"]


def test_explicit_single_supplement_requires_human_scope_and_keeps_ambiguity_gate(client, review_task):
    project, image, task, store, repo = review_task
    target = image["id"]
    box = {"label": "fire", "x1": 1, "y1": 2, "x2": 30, "y2": 40}
    store.append_items([{"image_id": target, "status": "success", "boxes": [box]}])
    material = host.material_store(project).get(target)
    gt = host.read_annotation(project, target)
    store.artifacts.atomic_write_json(task, repo.get(task).payload_ref, {
        "labels": ["fire"], "review_scope_policy": "per_image_required",
        "per_image_missing_review_scopes": {target: ["fire"]},
        "per_image_annotation_versions": {target: int(gt.get("version") or 0)},
        "per_image_source_hashes": {target: material["content_sha256"]},
    })
    endpoint = f"/api/v60/projects/{project}/annotation-tasks/{task}/decisions"
    revision = store.review_revision()
    body = {"single_candidate": True, "commit": False, "reject_unmentioned": False,
            "review_revision": revision, "decisions": [{"image_id": target, "accepted": True}]}
    assert client.post(endpoint, json={**body, "request_id": "missing-scope-0001"}).status_code == 400
    assert store.review_revision() == revision
    body["decisions"][0]["review_scope"] = ["fire"]
    approved = client.post(endpoint, json={**body, "request_id": "explicit-scope-0001"})
    assert approved.status_code == 200, approved.text
    assert store.get(target)["review_scope"] == ["fire"]
    assert host.read_annotation(project, target) == gt

    store.append_items([{"image_id": target, "status": "success", "manual_review_required": True,
                         "boxes": [box]}])
    body["review_revision"] = store.review_revision()
    denied = client.post(endpoint, json={**body, "request_id": "ambiguous-scope-001"})
    assert denied.status_code == 409 and "跨标签" in denied.json()["detail"]
    assert store.review_revision() == body["review_revision"]
    body["decisions"] = [{"image_id": target, "accepted": False}]
    rejected = client.post(endpoint, json={**body, "request_id": "reject-ambiguous-01"})
    assert rejected.status_code == 200, rejected.text
    assert store.get(target)["accepted"] is False
    assert store.get(target).get("review_scope") is None
    assert host.read_annotation(project, target) == gt

def _formal_selection_body(store, ids, request_id):
    return {
        "commit": True, "commit_selected": True, "single_candidate": False,
        "accept_unmentioned": False, "reject_unmentioned": False, "label_mapping": {},
        "review_revision": store.review_revision(), "request_id": request_id,
        "decisions": [{"image_id": image_id, "accepted": True} for image_id in ids],
    }


def test_selected_formal_commit_requires_human_draft_and_actor_owned_receipt(client, review_task, monkeypatch):
    project, image, task, store, _ = review_task
    image_id = image["id"]
    material = host.material_store(project).get(image_id)
    box = {"id": "fire", "label": "fire", "x1": 5, "y1": 5, "x2": 40, "y2": 40}
    store.append_items([{
        "image_id": image_id, "status": "success", "boxes": [box],
        "manual_review_required": True, "source_content_sha256": material["content_sha256"],
    }])
    base = f"/api/v60/projects/{project}/annotation-tasks/{task}"
    draft_url = base + f"/candidates/{image_id}/draft"
    current_actor = {"actor_id": "reviewer-a"}
    monkeypatch.setattr(host, "_material_governance_actor", lambda *_: current_actor)
    gt_before = host.read_annotation(project, image_id)
    auto = client.put(draft_url, json={
        "boxes": [box], "auto_resolution": True, "revision": 0, "request_id": "auto-draft-formal-001",
    })
    assert auto.status_code == 200, auto.text
    auto_row = store.get(image_id)
    auto_body = _formal_selection_body(store, [image_id], "auto-formal-blocked-001")
    freeze = client.post(base + "/review-selection", json={
        "filter": "all", "purpose": "gt", "review_revision": auto_body["review_revision"],
    })
    assert freeze.json()["reasons"] == {"requires_review": 1}
    denied = client.post(base + "/decisions", json=auto_body)
    assert denied.status_code == 409 and "人工消歧" in denied.text
    assert store.review_revision() == auto_body["review_revision"]
    assert store.get(image_id) == auto_row
    assert host.read_annotation(project, image_id) == gt_before
    legacy = client.post(base + "/decisions", json={
        **auto_body, "commit": False, "commit_selected": False, "request_id": "auto-review-blocked-001",
    })
    assert legacy.status_code == 400
    assert store.get(image_id) == auto_row
    human = client.put(draft_url, json={
        "boxes": [box], "revision": 1, "request_id": "human-draft-formal-001",
    })
    assert human.status_code == 200, human.text
    body = _formal_selection_body(store, [image_id], "human-formal-allowed-001")
    done = client.post(base + "/decisions", json=body)
    assert done.status_code == 200, done.text
    gt_saved = host.read_annotation(project, image_id)
    assert gt_saved["version"] == gt_before["version"] + 1
    receipt_url = base + "/decisions/by-request/" + body["request_id"]
    proof_id = host._annotation_review_operation_identity(host.AnnotationDecisionReq.model_validate(body))
    from platform_core.annotation_task_service import candidate_commit_operation_id, read_candidate_commit_receipts
    proof = read_candidate_commit_receipts(
        project, task, candidate_commit_operation_id("partial", body["request_id"], proof_id), [image_id],
    )[image_id]
    assert (proof["version"], proof["content_digest"]) == (gt_saved["version"], gt_saved["content_digest"])
    current_actor["actor_id"] = "reviewer-b"
    assert client.get(receipt_url).status_code == 404
    assert client.post(base + "/decisions", json=body).status_code == 404
    current_actor["actor_id"] = "reviewer-a"
    assert client.get(receipt_url).json()["status"] == "completed"
    assert client.post(base + "/decisions", json=body).json()["idempotent"] is True
    assert host.read_annotation(project, image_id) == gt_saved


@pytest.mark.parametrize("bad_candidate", ["source", "label", "delete", "write_failure"])
def test_selected_formal_commit_preflights_entire_batch(client, review_task, monkeypatch, bad_candidate):
    from io import BytesIO
    from PIL import Image

    project, image, task, store, _ = review_task
    buf = BytesIO()
    Image.new("RGB", (128, 128), "green").save(buf, format="JPEG")
    uploaded = client.post(f"/api/projects/{project}/images",
        files={"files": ("preflight.jpg", buf.getvalue(), "image/jpeg")}, data={"dataset_id": "default"})
    uploaded.raise_for_status()
    first, second = image["id"], uploaded.json()["uploaded"][0]["id"]
    materials = host.material_store(project)
    box = {"label": "fire", "class_id": 999, "x1": 5, "y1": 5, "x2": 40, "y2": 40}
    store.append_items([
        {"image_id": first, "status": "empty", "source_content_sha256": materials.get(first)["content_sha256"]},
        {"image_id": second, "status": "success",
         "boxes": [{**box,"label": "retired" if bad_candidate == "label" else "fire"}],
         "source_content_sha256": "0"*64 if bad_candidate == "source" else materials.get(second)["content_sha256"]},
    ])
    if bad_candidate == "delete":
        # Surface a deletion claim through the real admission check.
        original_read = type(materials).get_many
        def get_many(repository, ids):
            rows = original_read(repository, ids)
            return [{**row, "_dataset_delete_claim": {"token": "audit-delete"}}
                    if row["id"] == second else row for row in rows]
        monkeypatch.setattr(type(materials), "get_many", get_many)
    before = store.get_many([first, second])
    gt_before = host.read_annotations_many(project, [first, second])
    body = _formal_selection_body(store, [first, second], "invalid-selected-batch-001")
    base = f"/api/v60/projects/{project}/annotation-tasks/{task}"
    if bad_candidate == "write_failure":
        from platform_core import annotation_task_service

        def fail_formal_write(*args):
            raise OSError("failure after candidate persistence")

        monkeypatch.setattr(annotation_task_service, "write_formal_annotations", fail_formal_write)
        with pytest.raises(OSError, match="after candidate persistence"):
            client.post(base + "/decisions", json=body)
        assert all(item["accepted"] for item in store.get_many([first, second]).values())
        receipt = client.get(base + "/decisions/by-request/" + body["request_id"]).json()
        assert receipt["status"] == "rejected" and receipt["detail"]["code"] == "REVIEW_NOT_COMMITTED"
    else:
        response = client.post(base + "/decisions", json=body)
        expected_error = {"source": "AI_CANDIDATE_SOURCE_CHANGED", "label": "no longer active",
                          "delete": "is being deleted"}[bad_candidate]
        assert response.status_code == 409 and expected_error in response.text, response.text
        assert store.get_many([first, second]) == before
        assert store.review_revision() == body["review_revision"]
    assert host.read_annotations_many(project, [first, second]) == gt_before
    assert store.get_commit_summaries([first, second]) == {}

def _bulk_intent_fixture(client, review_task, count=1):
    project, image, task, store, repo = review_task
    original = host.material_store(project).get(image["id"])
    ids = [image["id"], *(f"intent-fixture-{index:03d}" for index in range(1, count))]
    host.material_store(project).upsert_many([
        {**original, "id": image_id, "filename": f"{image_id}.jpg",
         "annotation_version": 0, "annotation_hash": ""} for image_id in ids[1:]
    ])
    store.initialize(labels=["fire"], total_images=count)
    store.append_items([
        {"image_id": image_id, "status": "empty", "boxes": [],
         "source_content_sha256": original["content_sha256"]} for image_id in ids
    ])
    base = f"/api/v60/projects/{project}/annotation-tasks/{task}"
    response = client.post(base + "/review-selection", json={
        "filter": "all", "purpose": "gt", "review_revision": store.review_revision(),
    })
    response.raise_for_status()
    selection = response.json()
    assert selection["count"] == count
    return project, task, store, repo, ids, base, {
        "request_id": "bulk-intent-fixture-001", "selection_id": selection["selection_id"],
        "review_revision": selection["review_revision"], "excluded_image_ids": [],
    }


def test_bulk_formal_intent_seals_boundaries_without_writing_gt(client, review_task, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    from platform_core.annotation_repository import AnnotationRepository
    from platform_core.material_repository import MaterialRepository

    actor = {"actor_id": "bulk-owner"}
    monkeypatch.setattr(host, "_material_governance_actor", lambda *_: actor)
    project, task, store, repo, ids, base, body = _bulk_intent_fixture(client, review_task, 201)
    exclusion = [ids[190], ids[1]]
    body["excluded_image_ids"] = exclusion
    expected_ids = [image_id for image_id in ids if image_id not in exclusion]
    gt_owner = host._v50_annotation_repository(project)
    gt_before = gt_owner.get_many(ids)
    candidate_before = {**store.get_many(ids[:100]), **store.get_many(ids[100:200]), **store.get_many(ids[200:])}
    gt_revision = gt_owner.current_revision()
    task_before = repo.get(task)
    calls = {}

    def track(owner, method, key):
        original = getattr(owner, method)
        def wrapped(self, image_ids, *args, **kwargs):
            calls.setdefault(key, []).append(len(image_ids))
            return original(self, image_ids, *args, **kwargs)
        monkeypatch.setattr(owner, method, wrapped)

    track(CandidateStore, "get_many", "candidate")
    track(MaterialRepository, "get_many", "material")
    track(AnnotationRepository, "get_many", "gt")
    url = base + "/bulk-formal/intents"
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: client.post(url, json=body), range(2)))
    for response in responses:
        assert response.status_code == 200, response.text
    accepted = responses[0].json()
    assert responses[1].json() == accepted
    assert (accepted["original_count"], accepted["excluded_count"], accepted["count"]) == (201, 2, 199)
    assert calls == {"candidate": [100, 99], "material": [100, 99], "gt": [100, 99]}
    manifest = store.artifacts.payload_reader.read_evidence_json(task, accepted["manifest_ref"])
    assert [row["image_id"] for row in manifest["images"]] == expected_ids
    assert manifest["intent"]["excluded_image_ids"] == sorted(exclusion)
    assert manifest["review_contract"]["labels"] == ["fire"]
    for row in manifest["images"]:
        gt = gt_before[row["image_id"]]
        assert row["gt_version"] == gt["version"]
        assert row["gt_content_digest"] == (gt.get("content_digest") or gt_owner.record_digest(gt))
        assert len(row["candidate_digest"]) == 64
        assert row["source_content_sha256"] == candidate_before[row["image_id"]]["source_content_sha256"]
    assert gt_owner.get_many(ids) == gt_before and gt_owner.current_revision() == gt_revision
    assert {**store.get_many(ids[:100]), **store.get_many(ids[100:200]), **store.get_many(ids[200:])} == candidate_before
    assert store.review_revision() == body["review_revision"]
    assert repo.get(task) == task_before

    image_id = expected_ids[0]
    host.write_annotations_many(project, [{"image_id": image_id, "boxes": [], "annotation_state": "confirmed_empty",
        "annotation_scope": ["smoke"], "expected_version": gt_before[image_id]["version"],
        "source_content_sha256": candidate_before[image_id]["source_content_sha256"]}])
    assert gt_owner.get(image_id)["version"] > gt_before[image_id]["version"]
    ref = "review/selections/" + body["selection_id"] + ".json"
    snapshot = store.artifacts.read_json(task, ref)
    store.artifacts.atomic_write_json(task, ref, {**snapshot, "expires_at": 0})
    assert client.get(url + "/" + body["request_id"]).json() == accepted
    assert client.post(url, json={**body, "excluded_image_ids": exclusion[::-1]}).json() == accepted
    assert client.post(url, json={**body, "excluded_image_ids": []}).status_code == 409
    assert client.post(url, json={**body, "request_id": "expired-new-intent-001"}).status_code == 409
    assert store.artifacts.payload_reader.read_evidence_json(task, accepted["manifest_ref"]) == manifest

    actor["actor_id"] = "bulk-other"
    assert client.get(url + "/" + body["request_id"]).status_code == 404
    assert client.post(url, json=body).status_code == 404
    actor["actor_id"] = "bulk-owner"
    different = uuid.uuid4().hex
    store.artifacts.atomic_write_json(different, "request.json", {"labels": ["fire"]})
    repo.create(TaskRecord.new(different, project, TaskKind.AI_ANNOTATION, "request.json", different))
    other_task_url = url.replace("/" + task + "/", "/" + different + "/")
    assert client.get(other_task_url + "/" + body["request_id"]).status_code == 404
    other_project = client.post("/api/projects", json={"name": "bulk-other-project"}).json()["id"]
    assert client.get(url.replace("/" + project + "/", "/" + other_project + "/") + "/" + body["request_id"]).status_code == 404


def test_bulk_formal_intent_rejects_changes_and_unpublished_evidence(client, review_task, monkeypatch):
    project, task, store, repo, ids, base, body = _bulk_intent_fixture(client, review_task)
    url = base + "/bulk-formal/intents"
    assert client.post(url, json={**body, "excluded_image_ids": ["outside"]}).status_code == 422
    assert client.post(url, json={**body, "excluded_image_ids": ids}).status_code == 422
    assert client.post(url, json={**body, "review_revision": body["review_revision"] + 1}).status_code == 409
    transfer = client.post(base + "/review-selection", json={
        "filter": "all", "purpose": "transfer", "review_revision": store.review_revision(),
    }).json()
    assert client.post(url, json={**body, "selection_id": transfer["selection_id"]}).status_code == 409

    artifact_type = type(store.artifacts)
    publish_pointer = artifact_type.atomic_write_json
    candidate_before = store.get(ids[0])
    gt_before = host.read_annotation(project, ids[0])

    def interrupt(self, task_id, path, value):
        if path.startswith("review/bulk-formal/intents/"):
            raise OSError("interrupted before publishing intent")
        return publish_pointer(self, task_id, path, value)

    with monkeypatch.context() as patch:
        patch.setattr(artifact_type, "atomic_write_json", interrupt)
        assert client.post(url, json=body).status_code == 503
    assert client.get(url + "/" + body["request_id"]).status_code == 404
    assert store.get(ids[0]) == candidate_before and host.read_annotation(project, ids[0]) == gt_before

    write_evidence = artifact_type.write_evidence_json
    def change_gt(self, task_id, value):
        ref = write_evidence(self, task_id, value)
        host.write_annotations_many(project, [{"image_id": ids[0], "boxes": [], "annotation_state": "confirmed_empty",
            "annotation_scope": ["smoke"], "expected_version": gt_before["version"],
            "source_content_sha256": candidate_before["source_content_sha256"]}])
        return ref

    with monkeypatch.context() as patch:
        patch.setattr(artifact_type, "write_evidence_json", change_gt)
        assert client.post(url, json=body).status_code == 409
    assert client.get(url + "/" + body["request_id"]).status_code == 404
    assert store.get(ids[0]) == candidate_before
    assert store.review_revision() == body["review_revision"]
    admitted = client.post(url, json=body)
    assert admitted.status_code == 200, admitted.text
    ref = admitted.json()["manifest_ref"]
    evidence = store.artifacts.payload_reader.read_evidence_json(task, ref)
    assert evidence["images"][0]["gt_version"] > gt_before["version"]
    (store.artifacts.root / task / ref).write_text("{}", encoding="utf-8")
    assert client.get(url + "/" + body["request_id"]).status_code == 503
    assert client.post(url, json=body).status_code == 503

def _seal_for_bulk(client, project, task, store, base, body):
    response = client.post(base + "/bulk-formal/intents", json=body)
    assert response.status_code == 200, response.text
    operation = response.json()
    actor = store.artifacts.payload_reader.read_evidence_json(task, operation["manifest_ref"])["operation"]["identity"]["actor"]
    identity = {"project_id": project, "task_id": task, "actor": actor, "request_id": body["request_id"]}

    def execute(batch_number=0, *, authorize=lambda _: True):
        from platform_core.annotation_bulk_commit import execute_bulk_formal_batch

        return execute_bulk_formal_batch(
            store.artifacts, identity, operation["operation_id"], operation["manifest_ref"],
            batch_number, authorize=authorize,
        )

    return operation, execute


def test_bulk_formal_commit_writes_100_with_original_baselines_and_order(client, review_task):
    from platform_core.annotation_candidates import CandidateDecision

    project, task, store, repo, ids, base, body = _bulk_intent_fixture(client, review_task, 102)
    row = store.get(ids[0])
    store.append_items([{
        **row, "status": "success", "boxes": [{"label":"fire","x1":10,"y1":10,"x2":30,"y2":30}],
    }])
    store.apply_decisions([CandidateDecision(ids[1], True)])
    selection = client.post(base + "/review-selection", json={
        "purpose": "gt", "review_revision": store.review_revision(),
    }).json()
    body.update(selection_id=selection["selection_id"], review_revision=selection["review_revision"],
                excluded_image_ids=[ids[-1]])
    _, execute = _seal_for_bulk(client, project, task, store, base, body)
    annotations = host._v50_annotation_repository(project)
    original = annotations.get_many(ids)
    excluded = store.get(ids[-1])
    with pytest.raises(PermissionError):
        execute(authorize=lambda _: False)
    before = store.get_many(ids[:100])
    checks = 0
    def revoke_before_candidate_commit(_):
        nonlocal checks
        checks += 1
        return checks < 3
    with pytest.raises(PermissionError):
        execute(authorize=revoke_before_candidate_commit)
    assert not store.bulk_formal_events(ids[:100])
    assert store.get_many(ids[:100]) == before and before[ids[1]]["accepted"] is True
    with pytest.raises(ValueError, match="previous.*incomplete"):
        execute(1)
    assert annotations.get_many(ids) == original and store.review_revision() == body["review_revision"]
    first = execute()
    assert first["completed_image_ids"] == ids[:100]
    events = store.bulk_formal_events(ids[:100])
    assert len(events) == 100 and {event["batch_operation_id"] for event in events} == {first["batch_operation_id"]}
    assert {event["revision_before"] for event in events} == {body["review_revision"]}
    assert {event["revision_after"] for event in events} == {first["candidate_revision_after"]}
    saved = annotations.get_many(ids)
    assert saved[ids[0]]["boxes"][0]["label"] == "fire"
    assert saved[ids[1]]["annotation_state"] == "confirmed_empty"
    assert all(saved[image_id]["version"] == original[image_id]["version"] + 1 for image_id in ids[:100])
    assert saved[ids[-2]] == original[ids[-2]]
    assert execute() == first
    assert annotations.get_many(ids) == saved and store.review_revision() == first["journal_revision"]
    second = execute(1)
    assert second["completed_image_ids"] == [ids[-2]]
    assert second["batch_operation_id"] != first["batch_operation_id"]
    assert store.get(ids[-1]) == excluded and annotations.get(ids[-1]) == original[ids[-1]]
    assert repo.get(task).status is TaskStatus.AWAITING_CONFIRMATION


def _seed_equivalent_formal_gt(annotations, store, image_id):
    source = store.get(image_id)["source_content_sha256"]
    if annotations.get(image_id)["version"] == 0:
        annotations.upsert(image_id, [], annotation_state="confirmed_empty", annotation_scope=["smoke"],
                           source_content_sha256=source)
    annotations.upsert(image_id, [], annotation_state="confirmed_empty", annotation_scope=["fire"],
                       source_content_sha256=source)
    assert annotations.get(image_id)["version"] == 2


@pytest.mark.parametrize("corrupt_write", [False, True], ids=["replay", "transaction-rollback"])
def test_bulk_formal_commit_equivalent_gt_advances_with_atomic_receipt(client, review_task, corrupt_write):
    from contextlib import closing

    project, task, store, _, ids, base, body = _bulk_intent_fixture(client, review_task, 3)
    existing, fresh, excluded = ids
    annotations = host._v50_annotation_repository(project)
    _seed_equivalent_formal_gt(annotations, store, existing)
    body["excluded_image_ids"] = [excluded]
    _, execute = _seal_for_bulk(client, project, task, store, base, body)
    before = annotations.get_many(ids)
    excluded_candidate = store.get(excluded)
    assert before[fresh]["version"] == 0

    if corrupt_write:
        # Simulate a write that persisted the wrong version after an earlier
        # row and its receipt succeeded inside the same GT transaction.
        with closing(annotations._connect()) as database:
            database.execute(f"""CREATE TRIGGER test_corrupt_gt_version AFTER INSERT ON annotations
                WHEN NEW.image_id='{fresh}' BEGIN
                    UPDATE annotations SET version=0 WHERE image_id=NEW.image_id;
                END""")
        with pytest.raises(RuntimeError, match="protected formal GT write verification failed"):
            execute()
        assert annotations.get_many(ids) == before
        assert not annotations.candidate_committed_ids(task, ids)
        assert not store.get_commit_summaries(ids)
        assert len(store.bulk_formal_events(ids)) == 2
        assert store.get(excluded) == excluded_candidate
        return

    finished = execute()
    assert finished["completed_image_ids"] == [existing, fresh]
    saved = annotations.get_many(ids)
    assert saved[existing]["version"] == 3 and saved[existing]["content_digest"] == before[existing]["content_digest"]
    assert saved[fresh]["version"] == 1
    assert saved[excluded] == before[excluded] and store.get(excluded) == excluded_candidate
    receipts = annotations.candidate_commit_receipts(task, finished["batch_operation_id"], ids)
    journal = store.get_commit_summaries(ids)
    assert set(receipts) == set(journal) == {existing, fresh}
    for image_id in (existing, fresh):
        assert receipts[image_id]["expected_version"] == before[image_id]["version"]
        assert receipts[image_id]["version"] == journal[image_id]["gt_snapshot_version"] == saved[image_id]["version"]
        assert receipts[image_id]["content_digest"] == journal[image_id]["gt_snapshot_digest"] == saved[image_id]["content_digest"]
    revision = store.review_revision()
    assert execute() == finished
    assert store.review_revision() == revision and annotations.get_many(ids) == saved
    assert annotations.candidate_commit_receipts(task, finished["batch_operation_id"], ids) == receipts

    # Ordinary manual saves retain their content-based version semantics.
    source = store.get(existing)["source_content_sha256"]
    same = annotations.upsert(existing, [], annotation_state="confirmed_empty", annotation_scope=["fire"],
                              source_content_sha256=source)
    changed = annotations.upsert(existing, [], annotation_state="confirmed_empty", annotation_scope=["smoke"],
                                 source_content_sha256=source)
    assert same["version"] == 3 and changed["version"] == 4


@pytest.mark.parametrize("stage", ["candidate_only", "gt_only"])
def test_bulk_formal_commit_recovers_original_operation(client, review_task, monkeypatch, stage):
    from platform_core import annotation_task_service as service

    project, task, store, _, ids, base, body = _bulk_intent_fixture(client, review_task, 2)
    _, execute = _seal_for_bulk(client, project, task, store, base, body)
    annotations = host._v50_annotation_repository(project)
    original = annotations.get_many(ids)
    original_journal = CandidateStore.record_commit_summaries

    def interrupted(*args, **kwargs):
        raise OSError("interrupted batch")

    with monkeypatch.context() as patch:
        if stage == "candidate_only":
            patch.setattr(service, "write_formal_annotations", interrupted)
        else:
            patch.setattr(CandidateStore, "record_commit_summaries", interrupted)
        with pytest.raises(OSError, match="interrupted batch"):
            execute()
    events = store.bulk_formal_events(ids)
    candidate_revision = store.review_revision()
    assert len(events) == 2 and all(store.get(image_id)["accepted"] for image_id in ids)
    assert not store.get_commit_summaries(ids)
    operation_id = events[0]["batch_operation_id"]
    current = annotations.get_many(ids)
    proofs = annotations.candidate_commit_receipts(task, operation_id, ids)
    if stage == "candidate_only":
        assert current == original and not proofs
        assert client.post(base + "/decisions", json=_formal_selection_body(
            store, ids, "blocked-competing-formal-001",
        )).status_code == 409
        finished = execute()
    else:
        from platform_core import annotation_bulk_commit

        assert set(proofs) == set(ids) and current != original
        with monkeypatch.context() as patch:
            patch.setattr(type(annotations), "candidate_commit_receipts", lambda self, *_: {})
            with pytest.raises(ValueError, match="GT belongs to another operation"):
                execute()
            assert not store.get_commit_summaries(ids)
        with monkeypatch.context() as patch:
            patch.setattr(type(annotations), "candidate_commit_receipts",
                          lambda self, *_: {ids[0]: proofs[ids[0]]})
            with pytest.raises(ValueError, match="evidence incomplete"):
                execute()
            assert not store.get_commit_summaries(ids)
        with monkeypatch.context() as patch:
            patch.setattr(type(annotations), "candidate_commit_receipts", lambda self, *_: {
                **proofs, ids[0]: {**proofs[ids[0]], "candidate_digest": "0"*64},
            })
            with pytest.raises(ValueError, match="evidence conflict"):
                execute()
            assert not store.get_commit_summaries(ids)
        authorized = True
        read_proof_state = annotation_bulk_commit._proof_state

        def revoke_after_verified_proof(*args):
            nonlocal authorized
            state = read_proof_state(*args)
            if state[1] and not state[2]:
                authorized = False
            return state

        with monkeypatch.context() as patch:
            patch.setattr(annotation_bulk_commit, "_proof_state", revoke_after_verified_proof)
            patch.setattr(service, "write_formal_annotations", interrupted)
            finished = execute(authorize=lambda _: authorized)
        assert not authorized and annotations.get_many(ids) == current
    assert finished["batch_operation_id"] == operation_id
    assert store.review_revision() == candidate_revision + 1
    assert store.bulk_formal_events(ids) == events
    assert CandidateStore.record_commit_summaries is original_journal
    current = annotations.get_many(ids)
    assert execute() == finished and annotations.get_many(ids) == current
    proofs = annotations.candidate_commit_receipts(task, operation_id, ids)
    with monkeypatch.context() as patch:
        patch.setattr(type(annotations), "candidate_commit_receipts", lambda self, *_: {
            **proofs, ids[0]: {**proofs[ids[0]], "candidate_digest": "0"*64},
        })
        with pytest.raises(ValueError, match="evidence conflict"):
            execute()
    assert annotations.get_many(ids) == current and store.review_revision() == finished["journal_revision"]


@pytest.mark.parametrize("revoke_after", ["candidate", "gt"])
def test_bulk_formal_commit_revocation_boundary(client, review_task, monkeypatch, revoke_after):
    from platform_core import annotation_task_service as service

    project, task, store, _, ids, base, body = _bulk_intent_fixture(client, review_task, 2)
    _, execute = _seal_for_bulk(client, project, task, store, base, body)
    annotations = host._v50_annotation_repository(project)
    original = annotations.get_many(ids)
    authorized = True
    owner, method = (
        (CandidateStore, "prepare_bulk_formal_batch") if revoke_after == "candidate"
        else (service, "write_formal_annotations")
    )
    original_write = getattr(owner, method)

    def persist_then_revoke(*args, **kwargs):
        nonlocal authorized
        saved = original_write(*args, **kwargs)
        authorized = False
        return saved

    monkeypatch.setattr(owner, method, persist_then_revoke)
    if revoke_after == "candidate":
        with pytest.raises(PermissionError, match="no execution authority"):
            execute(authorize=lambda _: authorized)
    else:
        result = execute(authorize=lambda _: authorized)
        assert result["completed_image_ids"] == ids

    assert not authorized
    events = store.bulk_formal_events(ids)
    assert len(events) == len(ids)
    proofs = annotations.candidate_commit_receipts(task, events[0]["batch_operation_id"], ids)
    if revoke_after == "candidate":
        assert not proofs and not store.get_commit_summaries(ids)
        assert annotations.get_many(ids) == original
        assert store.review_revision() == events[0]["revision_after"]
    else:
        journal = store.get_commit_summaries(ids)
        current = annotations.get_many(ids)
        assert set(proofs) == set(journal) == set(ids)
        for image_id in ids:
            assert current[image_id]["version"] == original[image_id]["version"] + 1
            assert journal[image_id]["gt_snapshot_version"] == proofs[image_id]["version"]
            assert journal[image_id]["gt_snapshot_digest"] == proofs[image_id]["content_digest"]

@pytest.mark.parametrize("changed", ["gt", "candidate", "source", "delete", "labels", "legacy_digest"])
def test_bulk_formal_commit_stops_on_changed_authority(client, review_task, monkeypatch, changed):
    from platform_core.annotation_candidates import CandidateDecision
    from platform_core.annotation_task_service import write_formal_annotations

    project, task, store, _, ids, base, body = _bulk_intent_fixture(client, review_task, 2)
    _, execute = _seal_for_bulk(client, project, task, store, base, body)
    annotations = host._v50_annotation_repository(project)
    materials = host.material_store(project)
    image_id = ids[-1] if changed == "legacy_digest" else ids[0]
    original = annotations.get_many(ids)
    if changed == "gt":
        host.write_annotations_many(project, [{
            "image_id":image_id, "boxes":[], "annotation_state":"confirmed_empty", "annotation_scope":["smoke"],
            "source_content_sha256":materials.get(image_id)["content_sha256"],
            "expected_version":original[image_id]["version"],
        }])
    if changed == "candidate":
        store.apply_decisions([CandidateDecision(image_id, False)])
    if changed in ("source", "delete"):
        row = materials.get(image_id)
        patch = ({"content_sha256": "9"*64} if changed == "source"
                 else {"_dataset_delete_claim": {"token": "audit-delete"}})
        materials.upsert({**row, **patch})
    if changed == "labels":
        catalog = host._annotation_label_catalog
        monkeypatch.setattr(host, "_annotation_label_catalog",
                            lambda project: [row for row in catalog(project) if row["code"] != "fire"])
    if changed == "legacy_digest":
        assert original[image_id]["version"] == 0

        def replace_legacy_then_write(project_id, rows):
            folder = annotations.project_path / "annotations"
            folder.mkdir(exist_ok=True)
            (folder / f"{image_id}.json").write_text(
                '{"boxes":[],"annotation_state":"confirmed_empty","annotation_scope":["smoke"]}', encoding="utf-8",
            )
            return write_formal_annotations(project_id, rows)

        monkeypatch.setattr("platform_core.annotation_task_service.write_formal_annotations", replace_legacy_then_write)

    candidates_before, revision = store.get_many(ids), store.review_revision()
    gt_before = annotations.get_many(ids)
    with pytest.raises((ValueError, RuntimeError)):
        execute()
    if changed == "legacy_digest":
        assert len(store.bulk_formal_events(ids)) == 2
        assert annotations.get(image_id)["version"] == 0
        assert annotations.get(ids[0]) == gt_before[ids[0]]  # Whole GT transaction rolled back.
        assert annotations.get(image_id)["annotation_scope"] == ["smoke"]
    else:
        assert not store.bulk_formal_events(ids)
        assert store.get_many(ids) == candidates_before and store.review_revision() == revision
        assert annotations.get_many(ids) == gt_before
    assert not store.get_commit_summaries(ids)

@pytest.mark.parametrize("corrupt", ["duplicate", "digest"])
def test_bulk_formal_commit_refuses_invalid_sealed_manifest(client, review_task, corrupt):
    from fastapi import HTTPException

    project, task, store, _, ids, base, body = _bulk_intent_fixture(client, review_task, 2)
    operation, execute = _seal_for_bulk(client, project, task, store, base, body)
    artifacts = store.artifacts
    manifest = artifacts.payload_reader.read_evidence_json(task, operation["manifest_ref"])
    if corrupt == "duplicate":
        manifest["images"][1]["image_id"] = manifest["images"][0]["image_id"]
    else:
        manifest["images"][1]["gt_content_digest"] = "invalid"
    forged_ref = artifacts.write_evidence_json(task, manifest)
    path = "review/bulk-formal/intents/" + host._annotation_review_operation_path(body["request_id"]).rsplit("/", 1)[-1]
    pointer = artifacts.read_json(task, path)
    artifacts.atomic_write_json(task, path, {**pointer, "manifest_ref": forged_ref})
    with pytest.raises(HTTPException) as error:
        execute()
    assert error.value.status_code == 503
    assert not store.bulk_formal_events(ids)
    assert store.review_revision() == body["review_revision"]

@pytest.fixture
def running_formal_bulk(request, client, review_task, tmp_path):
    from platform_core.annotation_bulk_commit import execute_worker_bulk_formal_batch
    from platform_core.task_runtime.fenced_repository import FencedTaskRepository
    from platform_core.task_runtime.worker import WorkerContext

    case = getattr(request, "param", 1)
    project, task, store, _, ids, base, body = _bulk_intent_fixture(client, review_task, 2 if case == "mixed" else case)
    if case == "mixed":
        _seed_equivalent_formal_gt(host._v50_annotation_repository(project), store, ids[0])
    operation, _ = _seal_for_bulk(client, project, task, store, base, body)
    ref = operation["manifest_ref"]
    identity = store.artifacts.payload_reader.read_evidence_json(task, ref)["operation"]["identity"]
    repo = FencedTaskRepository(tmp_path / "execution.sqlite3")
    queued = TaskRecord.new("formal-worker-task", project, TaskKind.ANNOTATION_FORMAL_BULK, ref, "review")
    repo.create(queued, artifacts=store.artifacts)
    lease = repo.claim_next("worker-a", [queued.kind], set())
    context = WorkerContext(lease.task, lease, repo, store.artifacts)

    def execute():
        return execute_worker_bulk_formal_batch(
            context, store.artifacts, identity, operation["operation_id"], ref, 0,
        )

    return project, store, ids, repo, queued, lease, execute, (identity, operation["operation_id"], ref)


@pytest.mark.parametrize("running_formal_bulk", [100], indirect=True)
def test_formal_bulk_gt_barrier_serializes_independent_worker_and_cancel(running_formal_bulk, monkeypatch):
    import subprocess
    import sys
    import threading
    from concurrent.futures import ThreadPoolExecutor, TimeoutError
    from time import perf_counter

    from platform_core import annotation_task_service as service

    project, store, ids, repo, queued, lease, execute, _ = running_formal_bulk
    annotations = host._v50_annotation_repository(project)
    before = annotations.get_many(ids)
    repo.create(TaskRecord.new("other-task", project, TaskKind.VIDEO_FRAMES, "input.json", "other"),
                artifacts=store.artifacts)
    other = repo.claim_next("worker-other", [TaskKind.VIDEO_FRAMES], set())
    actual_write = service.write_formal_annotations
    canceller_entered = threading.Event()
    actual_lock = repo._formal_bulk_lock

    def observe_lock(task_id, **kwargs):
        if threading.current_thread().name.startswith("cancel-formal"):
            canceller_entered.set()
        return actual_lock(task_id, **kwargs)

    monkeypatch.setattr(repo, "_formal_bulk_lock", observe_lock)
    competitor = """
from datetime import datetime, timedelta, timezone
from platform_core.task_runtime import TaskKind
from platform_core.task_runtime.fenced_repository import FencedTaskRepository
import sys
repository = FencedTaskRepository(sys.argv[1])
input()
assert repository.release_expired(datetime.now(timezone.utc) + timedelta(hours=1)) == 1
# The unrelated task is expired by the simulated clock, the bulk task isn't.
assert repository.claim_next("worker-b", [TaskKind.ANNOTATION_FORMAL_BULK], set()) is None
print("blocked", flush=True)
"""
    with subprocess.Popen([sys.executable, "-c", competitor, str(repo.path)], text=True,
                          stdin=subprocess.PIPE, stdout=subprocess.PIPE) as worker_b, \
            ThreadPoolExecutor(1, thread_name_prefix="cancel-formal") as pool:
        try:
            cancellation = None
            elapsed = {}

            def held_write(project_id, rows):
                nonlocal cancellation
                start = perf_counter()
                gained = repo.heartbeat(other.task.task_id, other.lease_token, execution_generation=other.task.attempt)
                elapsed["other_heartbeat"] = perf_counter() - start
                assert gained.status is TaskStatus.RUNNING

                stdout, _ = worker_b.communicate("reap\n", timeout=10)
                assert worker_b.returncode == 0 and stdout.strip() == "blocked"

                def cancel():
                    start_cancel = perf_counter()
                    try:
                        return repo.request_cancel(queued.task_id)
                    finally:
                        elapsed["cancel"] = perf_counter() - start_cancel

                cancellation = pool.submit(cancel)
                assert canceller_entered.wait(2)
                with pytest.raises(TimeoutError):
                    cancellation.result(timeout=0.15)
                assert repo.get(queued.task_id).status is TaskStatus.RUNNING
                assert annotations.get_many(ids) == before
                gt_start = perf_counter()
                committed = actual_write(project_id, rows)
                elapsed["gt_write"] = perf_counter() - gt_start
                elapsed["barrier_observed"] = perf_counter() - start
                return committed

            monkeypatch.setattr(service, "write_formal_annotations", held_write)
            assert execute()["status"] == "completed"
            assert cancellation.result(timeout=5).status is TaskStatus.CANCEL_REQUESTED
            print("formal bulk isolated seconds", elapsed)
            assert elapsed["other_heartbeat"] < 2
            assert elapsed["cancel"] >= 0.15
        finally:
            if worker_b.poll() is None:
                worker_b.kill()

    from datetime import datetime, timedelta, timezone
    assert repo.release_expired(datetime.now(timezone.utc) + timedelta(hours=1)) == 1
    replacement = repo.claim_next("worker-b", [queued.kind], set())
    assert replacement.task.attempt == lease.task.attempt + 1
    with pytest.raises(PermissionError):
        with repo.formal_bulk_gt_write(lease, lease.task.attempt, {}):
            pytest.fail("expired execution acquired the GT barrier")
    after = annotations.get_many(ids)
    assert all(after[key]["version"] == before[key]["version"] + 1 for key in ids)
    assert set(store.get_commit_summaries(ids)) == set(ids)


@pytest.mark.parametrize("durable,running_formal_bulk", [(False, 1), (True, "mixed")],
                         indirect=["running_formal_bulk"], ids=["candidate-only", "gt-durable-mixed"])
def test_formal_bulk_cancel_reclaim_reconciles_without_gt_write(running_formal_bulk, monkeypatch, durable):
    import json
    import subprocess
    import sys
    from datetime import datetime, timedelta, timezone

    from platform_core import annotation_task_service as service
    from platform_core.task_runtime.scheduler import Scheduler

    project, store, ids, repo, queued, lease, execute, intent = running_formal_bulk
    annotations = host._v50_annotation_repository(project)
    before = annotations.get_many(ids)

    def interrupt(*args, **kwargs):
        raise OSError("interrupted before reconciliation")

    if durable:
        crash = """
import json
import os
import sys
import app as host
from platform_core.annotation_bulk_commit import execute_worker_bulk_formal_batch
from platform_core.annotation_candidates import CandidateStore
from platform_core.task_runtime import ArtifactStore, TaskRepository, TaskStatus
from platform_core.task_runtime.fenced_repository import FencedTaskRepository
from platform_core.task_runtime.models import TaskLease
from platform_core.task_runtime.worker import WorkerContext

parameters = json.load(sys.stdin)
repo = FencedTaskRepository(parameters["db"])
artifacts = ArtifactStore(parameters["artifacts"])
host._SHARED_TASK_REPOSITORY = TaskRepository(parameters["review_db"])
host._SHARED_TASK_ARTIFACTS = artifacts
task = repo.get(parameters["task"])
lease = TaskLease(task, parameters["token"], task.worker_id, task.lease_expires_at)
context = WorkerContext(task, lease, repo, artifacts)

def cancel_and_exit(*args, **kwargs):
    assert repo.request_cancel(task.task_id).status is TaskStatus.CANCEL_REQUESTED
    os._exit(42)

CandidateStore.record_commit_summaries = cancel_and_exit
execute_worker_bulk_formal_batch(context, artifacts, *parameters["intent"], 0)
"""
        review_repo = host._SHARED_TASK_REPOSITORY
        process = subprocess.run(
            [sys.executable, "-c", crash],
            input=json.dumps({"db": str(repo.path), "artifacts": str(store.artifacts.root),
                              "review_db": str(review_repo.path), "task": queued.task_id,
                              "token": lease.lease_token, "intent": intent}),
            text=True, capture_output=True, timeout=20,
        )
        assert process.returncode == 42, process.stderr
    else:
        with monkeypatch.context() as patch:
            patch.setattr(service, "write_formal_annotations", interrupt)
            with pytest.raises(OSError, match="before reconciliation"):
                execute()
        assert repo.request_cancel(queued.task_id).status is TaskStatus.CANCEL_REQUESTED

    assert not store.get_commit_summaries(ids)
    with pytest.raises(PermissionError):
        repo.finish(queued.task_id, lease.lease_token, TaskStatus.CANCELLED, execution_generation=lease.task.attempt)
    assert repo.release_expired(datetime.now(timezone.utc) + timedelta(hours=1)) == 1
    assert repo.get(queued.task_id).status is TaskStatus.QUEUED
    monkeypatch.setattr(service, "write_formal_annotations", interrupt)
    current = annotations.get_many(ids)
    assert all(current[key]["version"] == before[key]["version"] + int(durable) for key in ids)
    if durable:
        with monkeypatch.context() as patch:
            patch.setattr(type(annotations), "candidate_commit_receipts", lambda *_: {})
            scheduler = Scheduler(repo, store.artifacts, "worker-second", {queued.kind: object()}, set())
            assert scheduler.run_once()
            assert repo.get(queued.task_id).status is TaskStatus.RUNNING
            assert not store.get_commit_summaries(ids)
        assert repo.release_expired(datetime.now(timezone.utc) + timedelta(hours=1)) == 1
    scheduler = Scheduler(repo, store.artifacts, "worker-final", {queued.kind: object()}, set())
    assert scheduler.run_once()
    final = repo.get(queued.task_id)
    assert final.status is TaskStatus.CANCELLED and final.attempt == lease.task.attempt + 1 + int(durable)
    assert annotations.get_many(ids) == current
    assert bool(store.get_commit_summaries(ids)) == durable
    assert scheduler.run_once() is False


def _sealed_manifest(store, task, operation):
    return store.artifacts.payload_reader.read_evidence_json(task, operation["manifest_ref"])


def _formal_bulk_scheduler(repo, artifacts, worker="formal-worker", handler=None):
    from platform_core.annotation_bulk_execution import FormalBulkAnnotationHandler
    from platform_core.task_runtime.fenced_repository import FencedTaskRepository
    from platform_core.task_runtime.scheduler import Scheduler

    fenced = FencedTaskRepository(repo.path)
    scheduler = Scheduler(
        fenced, artifacts, worker,
        {TaskKind.ANNOTATION_FORMAL_BULK: handler or FormalBulkAnnotationHandler()},
        {"annotation.formal_bulk"},
    )
    return fenced, scheduler


def _start_bulk_execution(client, base, request_id):
    response = client.post(base + f"/bulk-formal/intents/{request_id}/execute")
    assert response.status_code == 200, response.text
    return response.json()


def test_bulk_formal_execution_runs_201_in_three_batches(client, review_task, monkeypatch):
    actor = {"actor_id": "bulk-owner"}
    monkeypatch.setattr(host, "_material_governance_actor", lambda *_: actor)
    project, task, store, repo, ids, base, body = _bulk_intent_fixture(client, review_task, 203)
    exclusion = [ids[190], ids[1]]
    body["excluded_image_ids"] = exclusion
    expected = [image_id for image_id in ids if image_id not in exclusion]
    assert len(expected) == 201
    annotations = host._v50_annotation_repository(project)
    before = annotations.get_many(ids)
    candidate_before = {**store.get_many(ids[:100]), **store.get_many(ids[100:200]), **store.get_many(ids[200:])}
    sealed = client.post(base + "/bulk-formal/intents", json=body)
    assert sealed.status_code == 200, sealed.text
    operation = sealed.json()
    assert operation["count"] == 201

    view = _start_bulk_execution(client, base, body["request_id"])
    assert view["status"] == "QUEUED"
    assert (view["total_images"], view["total_batches"], view["committed_images"]) == (201, 3, 0)
    assert view["execution_task_id"].startswith("fbulk-")
    execution = repo.get(view["execution_task_id"])
    assert execution.kind is TaskKind.ANNOTATION_FORMAL_BULK
    assert execution.payload_ref != operation["manifest_ref"]

    _, scheduler = _formal_bulk_scheduler(repo, store.artifacts)
    assert scheduler.run_once()

    final = repo.get(execution.task_id)
    assert final.status is TaskStatus.SUCCEEDED, final.error
    assert all(annotations.get(key)["version"] == before[key]["version"] + 1 for key in expected)
    assert all(annotations.get(key) == before[key] for key in exclusion)
    journal = {}
    for offset in range(0, len(expected), 100):
        journal.update(store.get_commit_summaries(expected[offset:offset + 100]))
    assert len(journal) == 201
    assert _sealed_manifest(store, task, operation)["images"][0]["image_id"] == expected[0]
    assert repo.get(task).status is TaskStatus.AWAITING_CONFIRMATION
    assert store.review_revision() == body["review_revision"] + 201 + 3
    assert {**store.get_many(ids[:100]), **store.get_many(ids[100:200]), **store.get_many(ids[200:])} != candidate_before

    progress = client.get(base + f"/bulk-formal/intents/{body['request_id']}/execution").json()
    assert progress["status"] == "SUCCEEDED"
    assert (progress["completed_batches"], progress["total_batches"]) == (3, 3)
    assert (progress["committed_images"], progress["pending_images"]) == (201, 0)
    assert progress["current_batch"] == 2 and progress["cancellation_requested"] is False
    assert progress["candidate_only_uncommitted_images"] == 0
    assert progress["finished_at"]


def test_bulk_formal_execution_start_is_idempotent_and_concurrent(client, review_task, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    actor = {"actor_id": "bulk-owner"}
    monkeypatch.setattr(host, "_material_governance_actor", lambda *_: actor)
    project, task, store, repo, ids, base, body = _bulk_intent_fixture(client, review_task, 2)
    assert client.post(base + "/bulk-formal/intents", json=body).status_code == 200
    url = base + f"/bulk-formal/intents/{body['request_id']}/execute"
    with ThreadPoolExecutor(max_workers=3) as pool:
        responses = list(pool.map(lambda _: client.post(url), range(3)))
    assert [item.status_code for item in responses] == [200, 200, 200]
    identities = {item.json()["execution_task_id"] for item in responses}
    assert len(identities) == 1
    execution_id = identities.pop()
    with repo._connect() as database:
        assert database.execute(
            "SELECT COUNT(*) FROM tasks WHERE kind='ANNOTATION_FORMAL_BULK'").fetchone()[0] == 1
    assert repo.get(execution_id).payload_ref.startswith("evidence-versions/v1/")
    assert client.post(url).json()["execution_task_id"] == execution_id


def test_bulk_formal_execution_resumes_after_crash_without_rewriting_gt(client, review_task, monkeypatch):
    from datetime import datetime, timedelta, timezone

    from platform_core.annotation_bulk_commit import execute_worker_bulk_formal_batch
    from platform_core.task_runtime.worker import WorkerContext

    actor = {"actor_id": "bulk-owner"}
    monkeypatch.setattr(host, "_material_governance_actor", lambda *_: actor)
    project, task, store, repo, ids, base, body = _bulk_intent_fixture(client, review_task, 102)
    assert client.post(base + "/bulk-formal/intents", json=body).status_code == 200
    _start_bulk_execution(client, base, body["request_id"])
    annotations = host._v50_annotation_repository(project)
    before = annotations.get_many(ids)

    fenced = _formal_bulk_scheduler(repo, store.artifacts)[0]
    lease = fenced.claim_next("worker-a", [TaskKind.ANNOTATION_FORMAL_BULK], {"annotation.formal_bulk"})
    assert lease is not None
    context = WorkerContext(lease.task, lease, fenced, store.artifacts)
    operation = client.get(base + "/bulk-formal/intents/" + body["request_id"]).json()
    identity = {"project_id": project, "task_id": task, "actor": "bulk-owner",
                "request_id": body["request_id"]}
    execute_worker_bulk_formal_batch(
        context, store.artifacts, identity, operation["operation_id"], operation["manifest_ref"], 0,
        binding_ref=lease.task.payload_ref,
    )
    first = annotations.get_many(ids[:100])
    assert all(first[key]["version"] == before[key]["version"] + 1 for key in ids[:100])
    # Process exit without finish/journal publication; the lease later expires.
    assert fenced.release_expired(datetime.now(timezone.utc) + timedelta(hours=1)) == 1
    assert repo.get(lease.task.task_id).status is TaskStatus.QUEUED

    _, scheduler = _formal_bulk_scheduler(repo, store.artifacts, worker="worker-b")
    assert scheduler.run_once()
    final = repo.get(lease.task.task_id)
    assert final.status is TaskStatus.SUCCEEDED, final.error
    after = annotations.get_many(ids)
    assert all(after[key]["version"] == before[key]["version"] + 1 for key in ids)
    assert len(store.get_commit_summaries(ids)) == 102
    assert final.attempt == lease.task.attempt + 1


def test_bulk_formal_execution_cancel_keeps_candidate_only_batch_uncommitted(client, review_task, monkeypatch):
    from datetime import datetime, timedelta, timezone

    from platform_core.annotation_bulk_commit import _batch, execute_worker_bulk_formal_batch
    from platform_core.annotation_bulk_intents import _candidate_digest
    from platform_core.annotation_task_service import _candidate_commit_digest
    from platform_core.task_runtime.worker import WorkerContext

    actor = {"actor_id": "bulk-owner"}
    monkeypatch.setattr(host, "_material_governance_actor", lambda *_: actor)
    project, task, store, repo, ids, base, body = _bulk_intent_fixture(client, review_task, 102)
    assert client.post(base + "/bulk-formal/intents", json=body).status_code == 200
    view = _start_bulk_execution(client, base, body["request_id"])
    operations = client.get(base + "/bulk-formal/intents/" + body["request_id"]).json()
    manifest = store.artifacts.payload_reader.read_evidence_json(task, operations["manifest_ref"])
    annotations = host._v50_annotation_repository(project)
    before = annotations.get_many(ids)

    fenced = _formal_bulk_scheduler(repo, store.artifacts)[0]
    lease = fenced.claim_next("worker-a", [TaskKind.ANNOTATION_FORMAL_BULK], {"annotation.formal_bulk"})
    context = WorkerContext(lease.task, lease, fenced, store.artifacts)
    identity = {"project_id": project, "task_id": task, "actor": "bulk-owner", "request_id": body["request_id"]}
    execute_worker_bulk_formal_batch(
        context, store.artifacts, identity, operations["operation_id"], operations["manifest_ref"], 0,
        binding_ref=lease.task.payload_ref,
    )
    # Batch 1 candidates were adopted durably, then the execution stopped
    # before the F1 GT barrier admitted that batch.
    labels = {row["code"]: row["class_id"] for row in host._annotation_label_catalog(host.get_project(project))}
    second, frozen = _batch(manifest, operations["manifest_ref"], 1)
    projected = {image_id: store.preview_bulk_formal_candidate(store.get(image_id), labels)
                 for image_id in frozen}
    store.prepare_bulk_formal_batch(second, frozen, projected, labels, store.review_revision(),
                                    _candidate_digest, _candidate_commit_digest, lambda: None)
    assert store.bulk_formal_events(list(frozen))
    assert not annotations.candidate_commit_receipts(task, second["batch_operation_id"], list(frozen))
    assert fenced.release_expired(datetime.now(timezone.utc) + timedelta(hours=1)) == 1
    assert client.post(base + f"/bulk-formal/intents/{body['request_id']}/execution/cancel").status_code == 200

    _, scheduler = _formal_bulk_scheduler(repo, store.artifacts, worker="worker-c")
    assert scheduler.run_once()
    final = repo.get(view["execution_task_id"])
    assert final.status is TaskStatus.CANCELLED, final.error
    after = annotations.get_many(ids)
    assert all(after[key]["version"] == before[key]["version"] + 1 for key in ids[:100])
    assert all(after[key] == before[key] for key in ids[100:])
    assert store.bulk_formal_events(list(frozen))
    progress = client.get(base + f"/bulk-formal/intents/{body['request_id']}/execution").json()
    assert progress["status"] == "CANCELLED"
    assert progress["cancellation_requested"] is True
    assert (progress["completed_batches"], progress["committed_images"]) == (1, 100)
    assert progress["candidate_only_uncommitted_images"] == 2
    assert progress["pending_images"] == 2


def test_bulk_formal_execution_blocks_external_gt_change_and_keeps_finished_batches(client, review_task, monkeypatch):
    from datetime import datetime, timedelta, timezone

    from platform_core.annotation_bulk_commit import execute_worker_bulk_formal_batch
    from platform_core.task_runtime.worker import WorkerContext

    actor = {"actor_id": "bulk-owner"}
    monkeypatch.setattr(host, "_material_governance_actor", lambda *_: actor)
    project, task, store, repo, ids, base, body = _bulk_intent_fixture(client, review_task, 102)
    assert client.post(base + "/bulk-formal/intents", json=body).status_code == 200
    view = _start_bulk_execution(client, base, body["request_id"])
    operations = client.get(base + "/bulk-formal/intents/" + body["request_id"]).json()
    annotations = host._v50_annotation_repository(project)
    before = annotations.get_many(ids)
    fenced = _formal_bulk_scheduler(repo, store.artifacts)[0]
    lease = fenced.claim_next("worker-a", [TaskKind.ANNOTATION_FORMAL_BULK], {"annotation.formal_bulk"})
    context = WorkerContext(lease.task, lease, fenced, store.artifacts)
    identity = {"project_id": project, "task_id": task, "actor": "bulk-owner", "request_id": body["request_id"]}
    execute_worker_bulk_formal_batch(
        context, store.artifacts, identity, operations["operation_id"], operations["manifest_ref"], 0,
        binding_ref=lease.task.payload_ref,
    )
    assert fenced.release_expired(datetime.now(timezone.utc) + timedelta(hours=1)) == 1
    host.write_annotations_many(project, [{
        "image_id": ids[100], "boxes": [], "annotation_state": "confirmed_empty",
        "annotation_scope": ["fire"], "expected_version": before[ids[100]]["version"],
        "source_content_sha256": store.get(ids[100])["source_content_sha256"],
    }])

    _, scheduler = _formal_bulk_scheduler(repo, store.artifacts, worker="worker-b")
    assert scheduler.run_once()
    final = repo.get(view["execution_task_id"])
    assert final.status is TaskStatus.PARTIAL_SUCCESS, final.error
    after = annotations.get_many(ids)
    assert all(after[key]["version"] == before[key]["version"] + 1 for key in ids[:100])
    assert after[ids[100]]["version"] == before[ids[100]]["version"] + 1
    progress = client.get(base + f"/bulk-formal/intents/{body['request_id']}/execution").json()
    assert progress["status"] == "PARTIAL_SUCCESS"
    assert progress["completed_batches"] == 1 and progress["committed_images"] == 100
    assert progress["last_error_code"] and progress["last_error_message"]


def test_bulk_formal_execution_api_is_scoped_to_actor_project_and_task(client, review_task, monkeypatch):
    actor = {"actor_id": "bulk-owner"}
    monkeypatch.setattr(host, "_material_governance_actor", lambda *_: actor)
    project, task, store, repo, ids, base, body = _bulk_intent_fixture(client, review_task, 1)
    assert client.post(base + "/bulk-formal/intents", json=body).status_code == 200
    _start_bulk_execution(client, base, body["request_id"])
    read = base + f"/bulk-formal/intents/{body['request_id']}/execution"
    cancel = read + "/cancel"
    assert client.get(read).status_code == 200

    actor["actor_id"] = "bulk-other"
    assert client.get(read).status_code == 404
    assert client.post(base + f"/bulk-formal/intents/{body['request_id']}/execute").status_code == 404
    assert client.post(cancel).status_code == 404
    actor["actor_id"] = "bulk-owner"

    other_project = client.post("/api/projects", json={"name": "bulk-other-project"}).json()["id"]
    assert client.get(read.replace("/" + project + "/", "/" + other_project + "/")).status_code == 404
    other_task = uuid.uuid4().hex
    store.artifacts.atomic_write_json(other_task, "request.json", {"labels": ["fire"]})
    repo.create(TaskRecord.new(other_task, project, TaskKind.AI_ANNOTATION, "request.json", other_task))
    assert client.get(read.replace("/" + task + "/", "/" + other_task + "/")).status_code == 404
    assert client.get(read + "-missing").status_code == 404


def test_formal_bulk_worker_registration_is_cpu_only(tmp_path):
    from platform_core.worker_registry import resolve_worker_registration

    registration = resolve_worker_registration(tmp_path, {"annotation"})
    assert TaskKind.ANNOTATION_FORMAL_BULK in registration.handlers
    assert "annotation.formal_bulk" in registration.capabilities


def _claim_formal_bulk(repo, store, worker="formal-worker"):
    from platform_core.task_runtime.worker import WorkerContext

    fenced = _formal_bulk_scheduler(repo, store.artifacts)[0]
    lease = fenced.claim_next(worker, [TaskKind.ANNOTATION_FORMAL_BULK], {"annotation.formal_bulk"})
    assert lease is not None
    return fenced, lease, WorkerContext(lease.task, lease, fenced, store.artifacts)


def _record_full_progress(fenced, lease, operation, total, batch_count):
    _, anchor = fenced.formal_bulk_cancel_state(lease, lease.task.attempt)
    fenced.publish_formal_bulk_progress(lease, lease.task.attempt, anchor, {
        "state": "running", "binding_ref": lease.task.payload_ref,
        "operation_id": operation["operation_id"], "manifest_ref": operation["manifest_ref"],
        "manifest_digest": operation["manifest_ref"].rsplit("sha256-", 1)[1].removesuffix(".json"),
        "total_images": total, "batch_size": 100, "batch_count": batch_count,
        "completed_batches": batch_count, "committed_images": total,
        "current_batch": batch_count - 1, "candidate_only_batches": [],
        "candidate_only_uncommitted_images": 0,
        "last_error_code": None, "last_error_message": None,
    })


@pytest.mark.parametrize("external_change", [False, True], ids=["untouched", "external-gt-change"])
def test_formal_bulk_success_reproves_every_batch_after_reclaim(client, review_task, monkeypatch, external_change):
    from datetime import datetime, timedelta, timezone

    from platform_core.annotation_bulk_commit import execute_worker_bulk_formal_batch

    actor = {"actor_id": "bulk-owner"}
    monkeypatch.setattr(host, "_material_governance_actor", lambda *_: actor)
    project, task, store, repo, ids, base, body = _bulk_intent_fixture(client, review_task, 201)
    body["excluded_image_ids"] = []
    assert client.post(base + "/bulk-formal/intents", json=body).status_code == 200
    _start_bulk_execution(client, base, body["request_id"])
    operation = client.get(base + "/bulk-formal/intents/" + body["request_id"]).json()
    annotations = host._v50_annotation_repository(project)
    before = annotations.get_many(ids)

    fenced, lease, context = _claim_formal_bulk(repo, store)
    identity = {"project_id": project, "task_id": task, "actor": "bulk-owner", "request_id": body["request_id"]}
    for number in range(3):
        execute_worker_bulk_formal_batch(
            context, store.artifacts, identity, operation["operation_id"], operation["manifest_ref"],
            number, binding_ref=lease.task.payload_ref,
        )
    _record_full_progress(fenced, lease, operation, 201, 3)
    committed = annotations.get_many(ids)
    assert all(committed[key]["version"] == before[key]["version"] + 1 for key in ids)
    assert fenced.release_expired(datetime.now(timezone.utc) + timedelta(hours=1)) == 1

    if external_change:
        row = store.get(ids[0])
        host.write_annotations_many(project, [{
            "image_id": ids[0],
            "boxes": [{"label": "fire", "x1": 10, "y1": 10, "x2": 30, "y2": 30}],
            "annotation_state": "annotated", "annotation_scope": ["fire"],
            "expected_version": committed[ids[0]]["version"],
            "source_content_sha256": row["source_content_sha256"],
        }])
        changed = annotations.get(ids[0])
        assert changed["version"] == committed[ids[0]]["version"] + 1

    _, scheduler = _formal_bulk_scheduler(repo, store.artifacts, worker="worker-reprove")
    assert scheduler.run_once()
    final = repo.get(lease.task.task_id)
    after = annotations.get_many(ids)
    if external_change:
        assert final.status is not TaskStatus.SUCCEEDED
        assert after[ids[0]] == annotations.get(ids[0])
        assert all(after[key] == committed[key] for key in ids[1:])
        assert annotations.get(ids[0])["version"] == committed[ids[0]]["version"] + 1
        progress = client.get(base + f"/bulk-formal/intents/{body['request_id']}/execution").json()
        assert progress["status"] != "SUCCEEDED"
    else:
        assert final.status is TaskStatus.SUCCEEDED, final.error
        assert after == committed


def test_formal_bulk_durable_gt_with_unfinished_journal_stays_recoverable(client, review_task, monkeypatch):
    from datetime import datetime, timedelta, timezone

    from platform_core.annotation_bulk_commit import _batch
    from platform_core.annotation_candidates import CandidateStore

    actor = {"actor_id": "bulk-owner"}
    monkeypatch.setattr(host, "_material_governance_actor", lambda *_: actor)
    project, task, store, repo, ids, base, body = _bulk_intent_fixture(client, review_task, 102)
    assert client.post(base + "/bulk-formal/intents", json=body).status_code == 200
    view = _start_bulk_execution(client, base, body["request_id"])
    operation = client.get(base + "/bulk-formal/intents/" + body["request_id"]).json()
    annotations = host._v50_annotation_repository(project)
    before = annotations.get_many(ids)
    original = CandidateStore.record_commit_summaries

    def refuse_journal(self, summaries, **kwargs):
        raise ValueError("simulated journal failure after durable GT")

    monkeypatch.setattr(CandidateStore, "record_commit_summaries", refuse_journal)
    _, scheduler = _formal_bulk_scheduler(repo, store.artifacts)
    assert scheduler.run_once()
    failed = repo.get(view["execution_task_id"])
    assert failed.status not in {TaskStatus.FAILED, TaskStatus.PARTIAL_SUCCESS, TaskStatus.SUCCEEDED}
    manifest = store.artifacts.payload_reader.read_evidence_json(task, operation["manifest_ref"])
    first_batch, _ = _batch(manifest, operation["manifest_ref"], 0)
    receipts = annotations.candidate_commit_receipts(task, first_batch["batch_operation_id"], ids[:100])
    assert len(receipts) == 100
    assert not store.get_commit_summaries(ids[:100])
    assert all(annotations.get(key)["version"] == before[key]["version"] + 1 for key in ids[:100])

    monkeypatch.setattr(CandidateStore, "record_commit_summaries", original)
    assert repo.get(view["execution_task_id"]).status is TaskStatus.RUNNING
    from platform_core.task_runtime.fenced_repository import FencedTaskRepository
    fenced = FencedTaskRepository(repo.path)
    assert fenced.release_expired(datetime.now(timezone.utc) + timedelta(hours=1)) == 1
    _, scheduler = _formal_bulk_scheduler(repo, store.artifacts, worker="worker-recover")
    assert scheduler.run_once()
    final = repo.get(view["execution_task_id"])
    assert final.status is TaskStatus.SUCCEEDED, final.error
    assert all(annotations.get(key)["version"] == before[key]["version"] + 1 for key in ids)
    assert len(store.get_commit_summaries(ids)) == 102


def test_formal_bulk_cancel_reports_external_gt_change_on_candidate_only_batch(client, review_task, monkeypatch):
    from datetime import datetime, timedelta, timezone

    from platform_core.annotation_bulk_commit import _batch, execute_worker_bulk_formal_batch
    from platform_core.annotation_bulk_intents import _candidate_digest
    from platform_core.annotation_task_service import _candidate_commit_digest

    actor = {"actor_id": "bulk-owner"}
    monkeypatch.setattr(host, "_material_governance_actor", lambda *_: actor)
    project, task, store, repo, ids, base, body = _bulk_intent_fixture(client, review_task, 102)
    assert client.post(base + "/bulk-formal/intents", json=body).status_code == 200
    _start_bulk_execution(client, base, body["request_id"])
    operation = client.get(base + "/bulk-formal/intents/" + body["request_id"]).json()
    annotations = host._v50_annotation_repository(project)
    before = annotations.get_many(ids)
    manifest = store.artifacts.payload_reader.read_evidence_json(task, operation["manifest_ref"])

    fenced, lease, context = _claim_formal_bulk(repo, store)
    identity = {"project_id": project, "task_id": task, "actor": "bulk-owner", "request_id": body["request_id"]}
    execute_worker_bulk_formal_batch(
        context, store.artifacts, identity, operation["operation_id"], operation["manifest_ref"], 0,
        binding_ref=lease.task.payload_ref,
    )
    labels = {row["code"]: row["class_id"] for row in host._annotation_label_catalog(host.get_project(project))}
    second, frozen = _batch(manifest, operation["manifest_ref"], 1)
    projected = {image_id: store.preview_bulk_formal_candidate(store.get(image_id), labels)
                 for image_id in frozen}
    store.prepare_bulk_formal_batch(second, frozen, projected, labels, store.review_revision(),
                                    _candidate_digest, _candidate_commit_digest, lambda: None)
    host.write_annotations_many(project, [{
        "image_id": ids[100],
        "boxes": [{"label": "fire", "x1": 10, "y1": 10, "x2": 30, "y2": 30}],
        "annotation_state": "annotated", "annotation_scope": ["fire"],
        "expected_version": before[ids[100]]["version"],
        "source_content_sha256": store.get(ids[100])["source_content_sha256"],
    }])
    changed = annotations.get(ids[100])
    assert changed["version"] == before[ids[100]]["version"] + 1
    assert fenced.release_expired(datetime.now(timezone.utc) + timedelta(hours=1)) == 1
    assert client.post(base + f"/bulk-formal/intents/{body['request_id']}/execution/cancel").status_code == 200

    _, scheduler = _formal_bulk_scheduler(repo, store.artifacts, worker="worker-cancel")
    assert scheduler.run_once()
    final = repo.get(lease.task.task_id)
    assert final.status is TaskStatus.CANCELLED, final.error
    assert annotations.get(ids[100]) == changed
    assert store.bulk_formal_events(list(frozen))
    progress = client.get(base + f"/bulk-formal/intents/{body['request_id']}/execution").json()
    assert progress["status"] == "CANCELLED"
    assert progress["candidate_only_uncommitted_images"] == 2
    assert progress["candidate_only_gt_changed_images"] == 1


def test_formal_bulk_real_process_exit_after_durable_gt_recovers_journal(client, review_task, monkeypatch):
    import json
    import subprocess
    import sys
    from datetime import datetime, timedelta, timezone

    actor = {"actor_id": "bulk-owner"}
    monkeypatch.setattr(host, "_material_governance_actor", lambda *_: actor)
    project, task, store, repo, ids, base, body = _bulk_intent_fixture(client, review_task, 102)
    assert client.post(base + "/bulk-formal/intents", json=body).status_code == 200
    view = _start_bulk_execution(client, base, body["request_id"])
    annotations = host._v50_annotation_repository(project)
    before = annotations.get_many(ids)

    crash = """
import json
import os
import sys
import app as host
from platform_core.annotation_bulk_execution import run_formal_bulk
from platform_core.annotation_candidates import CandidateStore
from platform_core.task_runtime import ArtifactStore, TaskKind, TaskRepository
from platform_core.task_runtime.fenced_repository import FencedTaskRepository
from platform_core.task_runtime.worker import WorkerContext

parameters = json.load(sys.stdin)
repository = FencedTaskRepository(parameters["db"])
artifacts = ArtifactStore(parameters["artifacts"])
host._SHARED_TASK_REPOSITORY = TaskRepository(parameters["review_db"])
host._SHARED_TASK_ARTIFACTS = artifacts
lease = repository.claim_next("worker-crash", [TaskKind.ANNOTATION_FORMAL_BULK], {"annotation.formal_bulk"})
assert lease is not None
context = WorkerContext(lease.task, lease, repository, artifacts)
CandidateStore.record_commit_summaries = lambda *args, **kwargs: os._exit(42)
run_formal_bulk(context)
os._exit(43)
"""
    process = subprocess.run(
        [sys.executable, "-c", crash],
        input=json.dumps({"db": str(repo.path), "artifacts": str(store.artifacts.root),
                          "review_db": str(repo.path)}),
        text=True, capture_output=True, timeout=60,
    )
    assert process.returncode == 42, process.stderr
    execution = repo.get(view["execution_task_id"])
    assert execution.status is TaskStatus.RUNNING
    assert all(annotations.get(key)["version"] == before[key]["version"] + 1 for key in ids[:100])
    assert all(annotations.get(key)["version"] == before[key]["version"] for key in ids[100:])
    assert not store.get_commit_summaries(ids[:100])
    manifest = store.artifacts.payload_reader.read_evidence_json(
        task, client.get(base + "/bulk-formal/intents/" + body["request_id"]).json()["manifest_ref"])
    from platform_core.annotation_bulk_commit import _batch
    first, _ = _batch(manifest, client.get(
        base + "/bulk-formal/intents/" + body["request_id"]).json()["manifest_ref"], 0)
    assert len(annotations.candidate_commit_receipts(task, first["batch_operation_id"], ids[:100])) == 100

    from platform_core.task_runtime.fenced_repository import FencedTaskRepository
    fenced = FencedTaskRepository(repo.path)
    assert fenced.release_expired(datetime.now(timezone.utc) + timedelta(hours=1)) == 1
    _, scheduler = _formal_bulk_scheduler(repo, store.artifacts, worker="worker-recover")
    assert scheduler.run_once()
    final = repo.get(view["execution_task_id"])
    assert final.status is TaskStatus.SUCCEEDED, final.error
    assert all(annotations.get(key)["version"] == before[key]["version"] + 1 for key in ids)
    assert len(store.get_commit_summaries(ids)) == 102


def test_formal_bulk_cancel_counts_only_verified_batches(client, review_task, monkeypatch):
    """D1: active_batch admitted without GT must not count as completed."""
    from contextlib import contextmanager
    from datetime import datetime, timedelta, timezone

    from platform_core.annotation_bulk_commit import execute_worker_bulk_formal_batch

    actor = {"actor_id": "bulk-owner"}
    monkeypatch.setattr(host, "_material_governance_actor", lambda *_: actor)
    project, task, store, repo, ids, base, body = _bulk_intent_fixture(client, review_task, 102)
    assert client.post(base + "/bulk-formal/intents", json=body).status_code == 200
    view = _start_bulk_execution(client, base, body["request_id"])
    operation = client.get(base + "/bulk-formal/intents/" + body["request_id"]).json()
    annotations = host._v50_annotation_repository(project)
    before = annotations.get_many(ids)

    fenced, lease, context = _claim_formal_bulk(repo, store)
    identity = {"project_id": project, "task_id": task, "actor": "bulk-owner",
                "request_id": body["request_id"]}
    manifest = store.artifacts.payload_reader.read_evidence_json(task, operation["manifest_ref"])
    execute_worker_bulk_formal_batch(
        context, store.artifacts, identity, operation["operation_id"], operation["manifest_ref"],
        0, binding_ref=lease.task.payload_ref, sealed=(manifest, operation["manifest_ref"]),
    )
    real_barrier = fenced.formal_bulk_gt_write

    @contextmanager
    def aborting_barrier(lease_, generation_, anchor_):
        with real_barrier(lease_, generation_, anchor_):
            raise InterruptedError("stop after admission, before GT commit")

    monkeypatch.setattr(fenced, "formal_bulk_gt_write", aborting_barrier)
    try:
        with pytest.raises(InterruptedError):
            execute_worker_bulk_formal_batch(
                context, store.artifacts, identity, operation["operation_id"],
                operation["manifest_ref"], 1,
                binding_ref=lease.task.payload_ref, sealed=(manifest, operation["manifest_ref"]),
            )
    finally:
        monkeypatch.setattr(fenced, "formal_bulk_gt_write", real_barrier)

    response = client.post(base + f"/bulk-formal/intents/{body['request_id']}/execution/cancel")
    assert response.status_code == 200, response.text
    assert response.json()["cancellation_requested"] is True
    assert fenced.release_expired(datetime.now(timezone.utc) + timedelta(hours=1)) == 1
    _, scheduler = _formal_bulk_scheduler(repo, store.artifacts, worker="worker-cancel")
    assert scheduler.run_once()
    assert repo.get(view["execution_task_id"]).status is TaskStatus.CANCELLED

    progress = client.get(base + f"/bulk-formal/intents/{body['request_id']}/execution").json()
    assert progress["completed_batches"] == 1
    assert progress["committed_images"] == 100
    assert progress["committed_images_proven"] is True
    assert progress["candidate_adopted_images"] == 2
    assert progress["candidate_only_uncommitted_images"] == 2
    assert progress["candidate_only_gt_changed_images"] == 0
    assert progress["uncommitted_gt_changed_images"] == 0
    after = annotations.get_many(ids)
    assert all(after[key]["version"] == before[key]["version"] + 1 for key in ids[:100])
    assert all(after[key] == before[key] for key in ids[100:])


def test_formal_bulk_permanent_block_stops_requeue_and_needs_reverified_resume(client, review_task, monkeypatch):
    """D2: a durable block must not be undone by the automatic reaper."""
    import platform_core.annotation_bulk_commit as bulk_commit
    from datetime import datetime, timedelta, timezone

    actor = {"actor_id": "bulk-owner"}
    monkeypatch.setattr(host, "_material_governance_actor", lambda *_: actor)
    project, task, store, repo, ids, base, body = _bulk_intent_fixture(client, review_task, 3)
    assert client.post(base + "/bulk-formal/intents", json=body).status_code == 200
    view = _start_bulk_execution(client, base, body["request_id"])

    original_audit = bulk_commit.audit_formal_bulk_execution

    def contradictory(*args, **kwargs):
        raise ValueError("synthetic contradictory evidence")

    monkeypatch.setattr(bulk_commit, "audit_formal_bulk_execution", contradictory)
    _, scheduler = _formal_bulk_scheduler(repo, store.artifacts, worker="worker-block")
    assert scheduler.run_once()
    blocked = repo.get(view["execution_task_id"])
    assert blocked.status is TaskStatus.RUNNING
    assert blocked.stage == "formal_bulk_blocked"

    fenced = _formal_bulk_scheduler(repo, store.artifacts)[0]
    assert fenced.release_expired(datetime.now(timezone.utc) + timedelta(hours=1)) == 0
    assert repo.get(view["execution_task_id"]).stage == "formal_bulk_blocked"
    assert fenced.claim_next("worker-2", [TaskKind.ANNOTATION_FORMAL_BULK], {"annotation.formal_bulk"}) is None

    monkeypatch.setattr(bulk_commit, "audit_formal_bulk_execution", original_audit)
    recover = client.post(base + f"/bulk-formal/intents/{body['request_id']}/execution/recover")
    assert recover.status_code == 409, recover.text
    assert repo.get(view["execution_task_id"]).status is TaskStatus.RUNNING


def test_formal_bulk_queued_cancel_is_proven_zero_write(client, review_task, monkeypatch):
    """D3: never-claimed execution can be cancelled without a Worker."""
    actor = {"actor_id": "bulk-owner"}
    monkeypatch.setattr(host, "_material_governance_actor", lambda *_: actor)
    project, task, store, repo, ids, base, body = _bulk_intent_fixture(client, review_task, 3)
    assert client.post(base + "/bulk-formal/intents", json=body).status_code == 200
    view = _start_bulk_execution(client, base, body["request_id"])
    annotations = host._v50_annotation_repository(project)
    before = annotations.get_many(ids)

    response = client.post(base + f"/bulk-formal/intents/{body['request_id']}/execution/cancel")
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "CANCELLED"
    assert result["committed_images"] == 0
    assert result["committed_images_proven"] is True
    record = repo.get(view["execution_task_id"])
    assert record.status is TaskStatus.CANCELLED
    assert record.attempt == 0
    assert annotations.get_many(ids) == before
    fenced = _formal_bulk_scheduler(repo, store.artifacts)[0]
    assert fenced.claim_next("worker-3", [TaskKind.ANNOTATION_FORMAL_BULK], {"annotation.formal_bulk"}) is None


def test_formal_bulk_progress_never_infers_committed_images(client, review_task, monkeypatch):
    """D6: missing proof reports unknown, never a guessed GT count."""
    from datetime import datetime, timedelta, timezone

    actor = {"actor_id": "bulk-owner"}
    monkeypatch.setattr(host, "_material_governance_actor", lambda *_: actor)
    project, task, store, repo, ids, base, body = _bulk_intent_fixture(client, review_task, 3)
    assert client.post(base + "/bulk-formal/intents", json=body).status_code == 200
    _start_bulk_execution(client, base, body["request_id"])
    fenced, lease, _ = _claim_formal_bulk(repo, store)
    assert fenced.release_expired(datetime.now(timezone.utc) + timedelta(hours=1)) == 1

    progress = client.get(base + f"/bulk-formal/intents/{body['request_id']}/execution").json()
    assert progress["committed_images"] is None
    assert progress["committed_images_proven"] is False
    assert progress["pending_images"] is None
    assert progress["status"] == "QUEUED"


def test_formal_bulk_success_semantics_survive_lawful_external_edit(client, review_task, monkeypatch):
    """D5: SUCCEEDED proves this operation committed the frozen range; a later
    lawful edit is a separate GT change and must not retroactively erase it."""
    from platform_core.task_runtime.fenced_repository import FencedTaskRepository

    actor = {"actor_id": "bulk-owner"}
    monkeypatch.setattr(host, "_material_governance_actor", lambda *_: actor)
    project, task, store, repo, ids, base, body = _bulk_intent_fixture(client, review_task, 3)
    assert client.post(base + "/bulk-formal/intents", json=body).status_code == 200
    view = _start_bulk_execution(client, base, body["request_id"])
    annotations = host._v50_annotation_repository(project)
    before = annotations.get_many(ids)
    committed: dict = {}

    real_publish = FencedTaskRepository.publish_formal_bulk_progress

    def publish_after_external_edit(self, lease, generation, anchor, evidence, *, status=None):
        if status is TaskStatus.SUCCEEDED and not committed:
            committed.update(annotations.get_many(ids))
            host.write_annotations_many(project, [{
                "image_id": ids[0],
                "boxes": [{"label": "fire", "x1": 5, "y1": 5, "x2": 25, "y2": 25}],
                "annotation_state": "annotated", "annotation_scope": ["fire"],
                "expected_version": committed[ids[0]]["version"],
                "source_content_sha256": store.get(ids[0])["source_content_sha256"],
            }])
        return real_publish(self, lease, generation, anchor, evidence, status=status)

    monkeypatch.setattr(FencedTaskRepository, "publish_formal_bulk_progress", publish_after_external_edit)
    _, scheduler = _formal_bulk_scheduler(repo, store.artifacts, worker="worker-race")
    assert scheduler.run_once()
    final = repo.get(view["execution_task_id"])
    assert final.status is TaskStatus.SUCCEEDED, final.error
    current = annotations.get(ids[0])
    assert committed[ids[0]]["version"] == before[ids[0]]["version"] + 1
    assert current["version"] == committed[ids[0]]["version"] + 1
    progress = client.get(base + f"/bulk-formal/intents/{body['request_id']}/execution").json()
    assert progress["status"] == "SUCCEEDED"
    assert progress["committed_images"] == 3
    assert progress["committed_images_proven"] is True