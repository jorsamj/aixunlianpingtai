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
    assert client.post(base+'/negative-transfer',json=body).json()['status']=='completed'
    page=client.get(base+'/negative-transfer/undo-crash-safe-001').json()
    assert len(page['items'])==1 and page['processed']==1 and 'image_ids' not in page
    original=CandidateStore.set_review_exclusion
    def crash(self,image_id,state,**kwargs):
        if state=='active':raise ValueError('isolated crash after pool restore')
        return original(self,image_id,state,**kwargs)
    monkeypatch.setattr(CandidateStore,'set_review_exclusion',crash)
    assert client.post(base+'/negative-transfer/undo-crash-safe-001/undo').status_code==409
    assert not pool.member_snapshot(image['id'])['member']
    monkeypatch.setattr(CandidateStore,'set_review_exclusion',original)
    resumed=client.post(base+'/negative-transfer/undo-crash-safe-001/undo')
    assert resumed.status_code==200,resumed.text
    assert resumed.json()['status']=='undone' and store.get(image['id'])['review_state']=='active'


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

def test_selected_twice_confirmed_writes_formal_gt_immediately_without_finishing_other_candidates(client, review_task):
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
    first = client.post(base+'/decisions',json=body)
    assert first.status_code == 200, first.text
    assert first.json()['committed_selected'] is True
    assert first.json()['applied_images'] == 1
    assert host.read_annotation(project, ids[0])['boxes'][0]['label'] == 'fire'
    assert host.read_annotation(project, ids[1])['boxes'] == []
    assert host.read_annotation(project, ids[2])['boxes'] == []
    assert set(store.get_commit_summaries(ids)) == {ids[0]}
    assert store.get(ids[1])['accepted'] is None
    assert store.get(ids[2])['accepted'] is None
    assert repo.get(task).status is TaskStatus.AWAITING_CONFIRMATION

    replay = client.post(base+'/decisions',json=body)
    assert replay.status_code == 200, replay.text
    assert replay.json()['idempotent'] is True

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
