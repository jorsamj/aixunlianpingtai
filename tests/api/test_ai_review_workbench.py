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
