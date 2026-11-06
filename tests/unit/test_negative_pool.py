import sqlite3
import pytest
from platform_core.material_repository import MaterialRepository
from platform_core.negative_pool import NegativePool


def setup(tmp_path):
    repo=MaterialRepository(tmp_path)
    repo.upsert_many([{'id':str(i),'filename':f'photo{i}.jpg','object_key':f'uploads/{i}.jpg','labels':['person'] if i % 2 else [],'created_at':'2026-10-28T00:00:00+00:00'} for i in range(4)])
    return repo,NegativePool(repo)


def test_read_does_not_initialize_optional_tables(tmp_path):
    repo,pool=setup(tmp_path)
    assert pool.query()['items']==[]
    assert pool.categories()==[]
    with sqlite3.connect(repo.path) as db:
        assert db.execute("SELECT COUNT(*) FROM sqlite_master WHERE name LIKE 'negative_pool_%'").fetchone()[0]==0


def test_membership_idempotence_multiple_categories_and_no_material_changes(tmp_path):
    repo,pool=setup(tmp_path)
    original=repo.get_many(['0','1'])
    a=pool.category(name='拿手机')['id']; b=pool.category(name='反光')['id']
    pool.members(['0','1'],category_ids=[a,b]); joined=pool.query()['items'][0]['negative_pool']['joined_at']
    pool.members(['0','1'],category_ids=[a,b])
    rows=pool.query()['items']
    assert len(rows)==2 and all(len(r['negative_pool']['categories'])==2 for r in rows)
    assert rows[0]['negative_pool']['joined_at']==joined
    pool.category(a,delete=True)
    assert pool.query()['total']==2
    pool.members(['0'],action='remove')
    assert pool.query()['total']==1
    assert repo.get_many(['0','1'])==original


def test_positive_upload_intent_does_not_create_training_gt_or_erase_labels(tmp_path):
    repo,pool=setup(tmp_path)
    before=repo.get('1')
    pool_revision=pool.revision()
    result=pool.set_positive_upload_intent(['1'],['fire','smoke'])
    after=repo.get('1')
    assert result['affected']==1
    assert after['upload_intended_label_codes']==['fire','smoke']
    assert after['labels']==before['labels']==['person']
    assert after.get('annotation_state')==before.get('annotation_state')
    assert after.get('annotation_scope')==before.get('annotation_scope')
    assert pool.query()['total']==0
    assert pool.revision()==pool_revision,'positive upload must not invalidate pool-only training selections'
    with pytest.raises(ValueError):
        pool.set_positive_upload_intent(['1','missing'],['fire'])
    assert repo.get('1')['upload_intended_label_codes']==['fire','smoke']


def test_upload_intent_endpoint_validates_active_project_labels_and_categories(tmp_path):
    from fastapi import FastAPI, HTTPException
    from platform_core.negative_pool_api import create_negative_pool_router
    repo, pool = setup(tmp_path)
    project = {'labels': ['fire', 'smoke', 'retired'], 'label_meta': [{}, {}, {'status': 'disabled'}]}
    def get_project(project_id):
        if project_id != 'allowed':
            raise HTTPException(403, 'forbidden')
        return project
    router = create_negative_pool_router(lambda _: repo, get_project, lambda _, row: row)
    app = FastAPI()
    app.include_router(router)
    endpoint = next(route.endpoint for route in router.routes if route.path.endswith('/upload-intent'))
    assert endpoint('allowed', {'sample_type': 'positive', 'image_ids': ['1'], 'label_codes': ['fire', 'smoke']})['affected'] == 1
    assert repo.get('1')['upload_intended_label_codes'] == ['fire', 'smoke']
    with pytest.raises(HTTPException) as disabled:
        endpoint('allowed', {'sample_type': 'positive', 'image_ids': ['1'], 'label_codes': ['retired']})
    assert disabled.value.status_code == 422
    category = pool.category(name='反光')
    assert endpoint('allowed', {'sample_type': 'negative', 'image_ids': ['1'], 'category_ids': [category['id']]})['affected'] == 1
    assert pool.query(category_ids=[category['id']])['total'] == 1
    assert repo.get('1')['upload_intended_label_codes'] == ['fire', 'smoke']
    assert repo.get('1')['labels'] == ['person'], 'negative classification never mutates formal labels'
    with pytest.raises(HTTPException) as forbidden:
        endpoint('forbidden', {'sample_type': 'negative', 'image_ids': ['1'], 'category_ids': [category['id']]})
    assert forbidden.value.status_code == 403


def test_filters_full_selection_and_atomic_rejection(tmp_path):
    repo,pool=setup(tmp_path)
    category=pool.category(name='干扰')['id']
    pool.members(['0','1','2','3'],category_ids=[category])
    assert pool.query(page_size=1)['total']==4
    assert len(pool.query(ids_only=True)['items'])==4
    assert pool.query(labels=['person'],category_ids=[category])['total']==2
    assert pool.query(query='photo3')['items'][0]['id']=='3'
    assert pool.query(review_status='unannotated')['total']==4
    assert len(pool.query(review_status='unannotated',ids_only=True)['items'])==4
    assert pool.query(joined_days=7)['total']==4
    assert pool.query(joined_to='2000-01-01')['total']==0
    day=pool.query()['items'][0]['negative_pool']['joined_at'][:10]
    assert pool.query(joined_from=day,joined_to=day)['total']==4
    assert len(pool.query(joined_from=day,joined_to=day,ids_only=True)['items'])==4
    with pytest.raises(ValueError):
        pool.members(['0','missing'],action='remove')
    assert pool.query()['total']==4
    row=repo.get('0'); row['_dataset_delete_claim']={'token':'active'}; repo.upsert_many([row])
    assert pool.query()['total']==3
    repo.patch({'1':{'annotation_needs_review':True}})
    assert pool.query(review_status='stale')['items'][0]['id']=='1'
    assert pool.query(review_status='stale',ids_only=True)['items']==['1']
    assert pool.query(review_status='unannotated')['total']==2
    with pytest.raises(ValueError):
        pool.members(['0'])


def test_router_filters_and_authorizes_all_operations(tmp_path):
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient
    from platform_core.negative_pool_api import create_negative_pool_router
    repo,pool=setup(tmp_path)
    def authorize(project):
        if project != 'allowed':
            raise HTTPException(403,'forbidden')
    app=FastAPI()
    app.include_router(create_negative_pool_router(lambda _:repo,authorize,lambda _,row:row))
    with TestClient(app) as client:
        base='/api/v61/projects/allowed/negative-pool'
        category=client.post(base+'/categories',json={'name':'反光'}).json()['id']
        assert client.post(base+'/members',json={'image_ids':['0','1'],'category_ids':[category]}).status_code==200
        assert client.get(base,params={'category_id':category,'label':'person'}).json()['total']==1
        assert client.get(base+'/ids',params={'category_id':category,'label':'person'}).json()['items']==['1']
        assert client.get('/api/v61/projects/forbidden/negative-pool').status_code==403
        assert client.post('/api/v61/projects/forbidden/negative-pool/members',json={'image_ids':['2']}).status_code==403

def test_algorithm_membership_isolated_and_legacy_not_inherited(tmp_path):
    repo, pool = setup(tmp_path)
    pool.members(['0'])
    pool.members(['1'], algorithm_id='fire')
    pool.members(['1','2'], algorithm_id='person')
    assert pool.candidate_ids(algorithm_id='fire') == ['1']
    assert pool.candidate_ids(algorithm_id='person') == ['1','2']
    assert pool.query(algorithm_id='fire')['total'] == 1
    assert pool.query(algorithm_id='fire')['items'][0]['negative_pool']['algorithm_id'] == 'fire'
    pool.members(['1'], action='remove', algorithm_id='fire')
    assert pool.candidate_ids(algorithm_id='fire') == []
    assert pool.candidate_ids(algorithm_id='person') == ['1','2']
    assert repo.get('1') is not None


def test_algorithm_pool_read_does_not_initialize_or_certify_gt(tmp_path):
    repo, pool = setup(tmp_path)
    assert pool.query(algorithm_id='fire')['items'] == []
    assert pool.candidate_ids(algorithm_id='fire') == []
    original = repo.get('0')
    pool.members(['0'], algorithm_id='fire')
    row = pool.query(algorithm_id='fire')['items'][0]
    assert row['negative_pool']['qualification'] == 'pending_confirmation'
    assert repo.get('0') == original

def test_algorithm_scoped_api_validates_identity_and_keeps_legacy_separate(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from platform_core.negative_pool_api import create_negative_pool_router
    from platform_core.algorithms import create_algorithm
    repo,pool=setup(tmp_path)
    algorithm=create_algorithm(repo.project_path/'algorithms.json', {'name':'Fire'}, '2026-11-04T00:00:00Z')
    app=FastAPI();app.include_router(create_negative_pool_router(lambda _:repo,lambda _: {},lambda _,row:row))
    with TestClient(app) as client:
        base='/api/v61/projects/p/negative-pool'
        assert client.post(base+'/members',json={'image_ids':['0'],'algorithm_id':'missing'}).status_code==400
        assert client.post(base+'/members',json={'image_ids':['0'],'algorithm_id':algorithm['id']}).status_code==200
        assert client.get(base,params={'algorithm_id':algorithm['id']}).json()['total']==1
        assert client.get(base,params={'algorithm_id':'missing'}).status_code==400

def test_qualification_uses_formal_gt_and_scope_not_membership(tmp_path):
    from platform_core.annotation_repository import AnnotationRepository
    from platform_core.negative_pool import negative_pool_qualification
    repo,pool=setup(tmp_path)
    ann=AnnotationRepository(repo.project_path)
    # Unannotated original remains pending; a forged material flag cannot certify it.
    row=repo.get('0');row['annotation_state']='confirmed_empty'
    result=negative_pool_qualification(repo,[row],['fire'])
    assert result['0']['qualification']=='needs_review'  # Missing source SHA is not confirmable
    assert result['0']['effective_label_codes']==['fire']
    assert result['0']['expected_version']==0

def test_existing_algorithm_scope_cannot_be_narrowed_by_pool_caller(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from platform_core.algorithms import create_algorithm,save_algorithms
    from platform_core.negative_pool_api import create_negative_pool_router
    import platform_core.training_label_tasks as tasks
    repo,pool=setup(tmp_path)
    path=repo.project_path/'algorithms.json'
    algorithm=create_algorithm(path,{'name':'Person'},'now')
    algorithm['current_version_id']='v1';algorithm['versions']=[{'id':'v1'}]
    save_algorithms(path,[algorithm])
    seen=[]
    def resolve(data_dir,project,payload,current,**kwargs):
        seen.append(current['id'])
        return {'effective_label_codes':['person']}
    monkeypatch.setattr(tasks,'resolve_training_label_contract',resolve)
    app=FastAPI();app.include_router(create_negative_pool_router(lambda _:repo,lambda _:{'labels':['person','fire']},lambda _,row:row))
    with TestClient(app) as client:
        endpoint='/api/v61/projects/p/negative-pool'
        assert client.get(endpoint,params={'algorithm_id':algorithm['id'],'target_label':'fire'}).status_code==422
        correct=client.get(endpoint,params={'algorithm_id':algorithm['id']})
        assert correct.json()['effective_label_codes']==['person']
        assert correct.json()['scope_kind']=='algorithm_contract'
        assert seen==[algorithm['id'],algorithm['id']]


def test_pool_listing_rejects_material_revision_drift(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from platform_core.negative_pool_api import create_negative_pool_router
    repo,pool=setup(tmp_path)
    pool.members(['0'])
    query=NegativePool.query
    def changed(self, **kwargs):
        result=query(self, **kwargs)
        repo.upsert({**repo.get('0'), 'needs_review':True, 'content_sha256':'f'*64})
        return result
    monkeypatch.setattr(NegativePool,'query',changed)
    app=FastAPI();app.include_router(create_negative_pool_router(lambda _:repo,lambda _:{},lambda _,row:row))
    with TestClient(app) as client:
        response=client.get('/api/v61/projects/p/negative-pool')
        assert response.status_code==409

def test_restore_receipt_survives_retry_and_unrelated_writes(tmp_path):
    repo,pool=setup(tmp_path)
    before=pool.member_snapshot('0')
    pool.members(['0'])
    revision=pool.revision()
    first=pool.restore_members({'0':before},expected_revision=revision,operation_id='undo-task-1')
    assert not pool.member_snapshot('0')['member']
    after=pool.revision()
    pool.members(['1'])
    second=pool.restore_members({'0':before},expected_revision=revision,operation_id='undo-task-1')
    assert second==first
    assert pool.member_snapshot('1')['member']
    assert pool.revision()==str(int(after)+1)
    with pytest.raises(ValueError,match='operation'):
        pool.restore_members({'1':before},expected_revision=revision,operation_id='undo-task-1')

def test_restore_without_matching_receipt_cannot_infer_success_from_revision(tmp_path):
    repo,pool=setup(tmp_path)
    before=pool.member_snapshot('0');pool.members(['0']);revision=pool.revision()
    pool.members(['1'])
    with pytest.raises(ValueError,match='revision'):
        pool.restore_members({'0':before},expected_revision=revision,operation_id='not-executed')
    assert pool.member_snapshot('0')['member']

def test_member_snapshot_uses_material_index_and_reads_legacy_project_pool(tmp_path):
    from contextlib import closing
    repo,pool=setup(tmp_path);pool.members(['0'],algorithm_id='algorithm')
    with closing(repo._connect()) as db:
        plan=' '.join(str(row[3]) for row in db.execute('EXPLAIN QUERY PLAN SELECT algorithm_id,joined_at FROM negative_pool_algorithm_members WHERE material_id=?',('0',)))
        assert 'SEARCH' in plan and 'ix_negative_pool_material_algorithm' in plan
        db.execute('DROP TABLE negative_pool_algorithm_members');db.commit()
    assert pool.member_snapshot('0')['algorithms']==[]
