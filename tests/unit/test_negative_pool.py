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
