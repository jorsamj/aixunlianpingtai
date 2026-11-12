"""Default picker history SQL must match the original full-pool evidence projection."""
from __future__ import annotations

from pathlib import Path

from platform_core.annotation_repository import AnnotationRepository
from platform_core.material_repository import MaterialRepository
from platform_core.training_material_picker_api import (
    _bulk_filtered_ids, _cached_usage_pool, _gt_material_filter_page, _role_material_page,
    _picker_filter_sql, _picker_relation_tokens, _usage_filters,
)
from platform_core.training_material_usage import TrainingMaterialUsage


def test_default_history_sql_matches_full_pool_and_batch_scope(tmp_path: Path):
    repo = MaterialRepository(tmp_path / 'data' / 'projects' / 'p1')
    rows = [
        {'id':f'm{i:04d}', 'filename':f'image-{i:04d}.jpg',
         'object_key':f'images/{i}.jpg', 'storage_source_id':'remote' if i % 2 else 'local',
         'created_at':f'2026-10-01T00:00:{i:02d}+00:00',
         'content_sha256':f'{i+1:064x}', 'processing_status':'processed'}
        for i in range(48)
    ]
    rows[1]['source_root_id'] = 'm0000'
    rows[2]['content_sha256'] = rows[0]['content_sha256']
    rows[3]['near_duplicate_group_id'] = 'group-a'
    rows[4]['near_duplicate_group_id'] = 'group-a'
    rows[5]['stored_name'] = 'CAMERA\\FRAME.JPG'
    rows[6]['stored_name'] = 'camera/frame.jpg'
    rows[7]['camera_id'] = 'camera-1'
    rows[7]['session_id'] = 'session-1'
    rows[8]['camera_session_id'] = 'camera-1\x1fsession-1'
    repo.upsert_many(rows)
    annotations = AnnotationRepository(repo.project_path)
    for image_id in ('m0009', 'm0010'):
        annotations.upsert_many([{'image_id':image_id, 'annotation_state':'annotated',
                                  'boxes':[{'label':'person', 'x1':1, 'y1':1, 'x2':3, 'y2':3}]}])
    task_db = repo.project_path.parent.parent / 'task_runtime' / 'tasks.sqlite3'
    task_db.parent.mkdir(parents=True,exist_ok=True)
    import sqlite3
    sqlite3.connect(task_db).close()
    usage = TrainingMaterialUsage(task_db)
    for image_id, algorithm, task, role, exposed in (
        ('m0000','a','t0','train',True),
        ('m0003','a','t3','train',True),
        ('m0005','a','t5','train',True),
        ('m0007','a','t7','train',True),
        ('m0009','b','t9','train',True),
        ('m0010','a','t10','train',False),
        ('m0011','a','t11','validation',True),
    ):
        # Production freezes normalized MaterialRepository rows, not raw upload input.
        source = repo.get(image_id)
        usage.record_selected('p1',algorithm,task,{'snapshot_id':task,'images':[
            {'image_id':image_id,'role':role,'content_sha256':source['content_sha256']}]},
            source_images=[source])
        if exposed:
            usage.record_execution(task,completed_epoch=True,validation_observed=role=='validation')

    for role in ('train','test'):
        _cached_usage_pool.cache_clear()
        original = _cached_usage_pool(str(repo.project_path),str(task_db),repo.current_revision(),
                                      'a',usage.read_revision(),role,True)
        filters, meta = _usage_filters(repo,{'algorithm_asset_id':'a','role':role})
        assert '__usage_sql_exclusion' in filters
        assert 'usage_excluded_image_ids' not in filters
        # EXPLAIN, without writing schema: the Task token lookup must be an
        # indexed seek, never a nested full scan for each material token.
        import sqlite3
        clauses,params=_picker_filter_sql(filters)
        with sqlite3.connect(repo.path,uri=True) as db:
            db.execute('ATTACH DATABASE ? AS usage_index',(task_db.resolve().as_uri()+'?mode=ro',))
            db.create_function('picker_relation_tokens',3,_picker_relation_tokens)
            plan=[row[3] for row in db.execute('EXPLAIN QUERY PLAN SELECT m.id FROM materials m WHERE '
                                             +' AND '.join(clauses),params)]
        assert any('SEARCH t USING COVERING INDEX' in line and 'project_id=?' in line
                   for line in plan),plan
        first = _gt_material_filter_page(repo,annotations,filters=filters,limit=15,page=1)
        first_hydrated = _gt_material_filter_page(repo,annotations,filters=filters,
                                                  limit=15,page=1,include_payload=True)
        second = _gt_material_filter_page(repo,annotations,filters=filters,limit=15,page=2)
        all_rows = _gt_material_filter_page(repo,annotations,filters=filters,limit=60,page=1)
        expected = {row['id'] for row in rows} - set(original['excluded_image_ids'])
        assert set(all_rows['items']) == expected
        assert first['total']==second['total']==all_rows['total']==len(expected)
        assert set(first['items']).isdisjoint(second['items'])
        assert [row['id'] for row in first_hydrated['items']] == first['items']
        assert 'm0009' in expected  # Another algorithm's training does not exclude.
        assert 'm0010' in expected  # Selected but never executed is not exposed.
        assert ('m0011' in expected) == (role=='train')
        assert not {'m0000','m0001','m0002','m0003','m0004','m0005','m0006','m0007','m0008'} & expected

    # Explicit state filters still use the old authoritative history projection.
    selected, _ = _usage_filters(repo,{'algorithm_asset_id':'a',
                                      'history_policy':'include_history','usage_state':'selected'})
    assert '__usage_sql_exclusion' not in selected
    assert 'm0010' in selected['usage_image_ids']

    # The role-filtered path must attach the same Task evidence and preserve GT.
    filters, _ = _usage_filters(repo,{'algorithm_asset_id':'a'})
    page = _role_material_page(repo,annotations,{'effective_label_codes':['person']},
                               filters=filters,sample_role='positive',limit=60,
                               include_payload=True)
    assert 'm0009' in [row['id'] for row in page['items']]
    assert 'm0010' in [row['id'] for row in page['items']]


def test_default_history_sql_skips_exclusion_when_no_exposed_record(tmp_path: Path):
    repo=MaterialRepository(tmp_path / 'data' / 'projects' / 'empty')
    repo.upsert_many([{'id':'a','filename':'a.jpg','object_key':'a.jpg',
                      'processing_status':'processed'}])
    filters,meta=_usage_filters(repo,{'algorithm_asset_id':'new-algorithm'})
    assert '__usage_sql_exclusion' not in filters
    assert 'usage_excluded_image_ids' not in filters
    assert _gt_material_filter_page(repo,AnnotationRepository(repo.project_path),
                                    filters=filters,limit=60)['total']==1


def test_combined_filters_bulk_all_pages_and_union_preserve_selection(tmp_path: Path):
    repo=MaterialRepository(tmp_path/'data'/'projects'/'bulk')
    repo.upsert_many([{'id':f'i{i:04d}', 'filename':f'camera-{i:04d}.jpg',
                      'object_key':f'{i}.jpg', 'storage_source_id':'nas' if i<378 else 'other',
                      'created_at':'2026-10-15T01:00:00+00:00',
                      'processing_status':'processed'} for i in range(430)])
    gt=AnnotationRepository(repo.project_path)
    gt.upsert_many([{'image_id':f'i{i:04d}','annotation_state':'annotated',
                     'boxes':[{'label':'person' if i<378 else 'smoke',
                               'x1':1,'y1':1,'x2':3,'y2':3}]} for i in range(430)])
    filters={'storage_source_ids':['nas'],'annotation_state':'annotated',
             'created_from':'2026-10-01','created_to':'2026-10-30'}
    first=_gt_material_filter_page(repo,gt,query='camera',labels=('person',),
                                   filters=filters,limit=60,page=1)
    assert first['total']==378 and len(first['items'])==60
    batch,total=_bulk_filtered_ids(repo,gt,query='camera',labels=('person',),filters=filters)
    assert total==378 and len(batch)==len(set(batch))==378
    assert set(first['items'])<=set(batch)
    # A second valid filter's results must be unioned, not replace the first selection.
    smoke,smoke_total=_bulk_filtered_ids(repo,gt,labels=('smoke',),filters={'annotation_state':'annotated'})
    assert smoke_total==52
    selected=set(batch[:100]);selected.update(smoke[:50]);selected.update(batch[80:130])
    assert len(selected)==180
    selected.symmetric_difference_update(smoke[:20])
    assert len(selected)==160 and set(batch[:100])<=selected


def test_browsing_history_keeps_excluded_rows_and_current_scope_is_inclusive(tmp_path):
    repo = MaterialRepository(tmp_path / 'data' / 'projects' / 'browse')
    repo.upsert_many([{'id':'shared','filename':'shared.jpg','object_key':'shared.jpg',
                      'processing_status':'processed','content_sha256':'a'*64}])
    usage = TrainingMaterialUsage(repo.project_path.parent.parent / 'task_runtime' / 'tasks.sqlite3')
    usage.path.parent.mkdir(parents=True, exist_ok=True)
    import sqlite3
    sqlite3.connect(usage.path).close()
    source = repo.get('shared')
    for algorithm in ('a','b'):
        usage.record_selected('browse', algorithm, 'task-'+algorithm,
            {'snapshot_id':algorithm,'images':[{'image_id':'shared','role':'train','content_sha256':'a'*64}]},
            source_images=[source])
        usage.record_execution('task-'+algorithm, completed_epoch=True)
    filters, facts = _usage_filters(repo, {'algorithm_asset_id':'a', 'usage_state':'used',
        'history_scope':'current_only', 'browse_only':True})
    assert _gt_material_filter_page(repo,AnnotationRepository(repo.project_path),filters=filters,limit=60)['items'] == ['shared']
    assert usage.query_filter('browse','a',[source])['by_image_id']['shared']['excluded'] is True
    selected, _ = _usage_filters(repo, {'algorithm_asset_id':'a','history_scope':'current_only',
                                       'history_policy':'include_history'})
    assert selected['usage_image_ids'] == ['shared']


def test_public_training_count_is_current_algorithm_only():
    from platform_core.training_material_picker_api import _public_usage_fact
    fact = {'history_details':[
        {'task_id':'a','role':'train','evidence':2,'algorithm_id':'current'},
        {'task_id':'b','role':'train','evidence':2,'algorithm_id':'other'},
        {'task_id':'c','role':'train','evidence':0,'algorithm_id':'current'}]}
    assert _public_usage_fact(fact, 'current')['training_task_count'] == 1


def test_scope_browsing_uses_indexed_sql_without_hydrating_material_pool(tmp_path, monkeypatch):
    from platform_core.task_runtime.repository import TaskRepository
    repo=MaterialRepository(tmp_path/'data'/'projects'/'scope')
    repo.upsert_many([{'id':'x','filename':'x.jpg','processing_status':'processed'}])
    TaskRepository(repo.project_path.parent.parent/'task_runtime'/'tasks.sqlite3')
    usage=TrainingMaterialUsage(repo.project_path.parent.parent/'task_runtime'/'tasks.sqlite3')
    usage.record_selected('scope','a','task',{'snapshot_id':'s','images':[{'image_id':'x','role':'train'}]})
    usage.record_execution('task', completed_epoch=True)
    import platform_core.training_material_picker_api as api
    monkeypatch.setattr(api,'_cached_usage_pool',lambda *args: (_ for _ in ()).throw(AssertionError('whole pool')))
    filters,_=api._usage_filters(repo,{'algorithm_asset_id':'a','history_scope':'current_only','browse_only':True})
    result=api._gt_material_filter_page(repo,AnnotationRepository(repo.project_path),filters=filters,limit=60,count_mode='deferred')
    assert result['items']==['x']


def test_label_all_requires_each_formal_label(tmp_path):
    repo=MaterialRepository(tmp_path/'data'/'projects'/'labels')
    repo.upsert_many([{'id':i,'filename':i+'.jpg','processing_status':'processed'} for i in ('one','two')])
    gt=AnnotationRepository(repo.project_path)
    for identity,labels in [('one',['a']),('two',['a','b'])]:
        gt.upsert_many([{'image_id':identity,'annotation_state':'annotated','boxes':[{'label':code,'x1':1,'y1':1,'x2':2,'y2':2} for code in labels]}])
    page=_gt_material_filter_page(repo,gt,labels=['a','b'],filters={'label_mode':'all'},limit=60)
    assert page['items']==['two']


def test_deferred_role_first_page_does_not_build_full_role_index(tmp_path, monkeypatch):
    repo=MaterialRepository(tmp_path/'data'/'projects'/'roles')
    repo.upsert_many([{'id':str(i),'filename':str(i)+'.jpg','processing_status':'processed'} for i in range(100)])
    gt=AnnotationRepository(repo.project_path)
    import platform_core.training_material_picker_api as api
    monkeypatch.setattr(api,'_cached_role_index',lambda *args: (_ for _ in ()).throw(AssertionError('whole role index')))
    result=api._role_material_page(repo,gt,{'effective_label_codes':['a']},sample_role='pending_review',limit=10,count_mode='deferred')
    assert len(result['items'])==10
    assert result['total'] is None
    assert result['has_next'] is True


def test_used_browse_sql_matches_authoritative_projection_without_full_pool(tmp_path, monkeypatch):
    from platform_core.task_runtime.repository import TaskRepository
    repo=MaterialRepository(tmp_path/'data'/'projects'/'used')
    repo.upsert_many([{'id':str(i),'filename':str(i)+'.jpg','processing_status':'processed','content_sha256':f'{i+1:064x}'} for i in range(8)])
    path=repo.project_path.parent.parent/'task_runtime'/'tasks.sqlite3'
    TaskRepository(path)
    usage=TrainingMaterialUsage(path)
    for i,role,evidence,algorithm in [(0,'train',2,'a'),(1,'train',1,'a'),(2,'test',2,'a'),(2,'train',2,'a'),(3,'train',2,'b'),(4,'validation',2,'a')]:
        task=f't-{i}-{role}'
        row=repo.get(str(i))
        usage.record_selected('used',algorithm,task,{'snapshot_id':task,'images':[{'image_id':str(i),'role':role,'content_sha256':row['content_sha256']}]},source_images=[row])
        usage.record_execution(task,completed_epoch=evidence==2,first_batch=True,test_observed=role=='test',validation_observed=role=='validation')
    import platform_core.training_material_picker_api as api
    monkeypatch.setattr(api,'_cached_usage_pool',lambda *a: (_ for _ in ()).throw(AssertionError('whole pool')))
    for state, expected in [('used',['0']),('possible',['1'])]:
        filters,_=api._usage_filters(repo,{'algorithm_asset_id':'a','usage_state':state,'browse_only':True})
        assert api._gt_material_filter_page(repo,AnnotationRepository(repo.project_path),filters=filters,limit=60)['items']==expected



def test_no_match_positive_role_skips_python_projection(tmp_path, monkeypatch):
    repo=MaterialRepository(tmp_path/'data'/'projects'/'no-positive')
    repo.upsert_many([{'id':str(i),'filename':str(i)+'.jpg','processing_status':'processed'} for i in range(200)])
    gt=AnnotationRepository(repo.project_path)
    import platform_core.training_label_tasks as tasks
    monkeypatch.setattr(tasks,'training_material_role',lambda *a: (_ for _ in ()).throw(AssertionError('no target must not classify entire pool')))
    result=_role_material_page(repo,gt,{'effective_label_codes':['person']},sample_role='positive',limit=10,count_mode='deferred')
    assert result['items']==[] and result['has_next'] is False


def test_deferred_role_deep_page_uses_forward_cursor_not_repeated_offsets(tmp_path, monkeypatch):
    """Page 27 must keep the exact role contract without re-reading earlier offsets."""
    import platform_core.training_material_picker_api as api
    repo = MaterialRepository(tmp_path / 'data' / 'projects' / 'deep-role')
    repo.upsert_many([{
        'id': f'm{i:04d}', 'filename': f'{i:04d}.jpg',
        'processing_status': 'processed', 'created_at': '2026-11-01T00:00:00+00:00',
        'content_sha256': f'{i+1:064x}',
    } for i in range(360)])
    annotations = AnnotationRepository(repo.project_path)
    contract = {'effective_label_codes': ['person']}
    original_page = api._gt_material_filter_page
    for order in ('oldest', 'newest'):
        expected = api._role_material_page(repo, annotations, contract,
            sample_role='pending_negative', page=27, limit=10,
            sort_order=order, include_payload=False, count_mode='exact')
        observed_calls = []
        def track_gt_page(*args, **kwargs):
            observed_calls.append((kwargs.get('page'), kwargs.get('cursor')))
            return original_page(*args, **kwargs)
        with monkeypatch.context() as patch:
            patch.setattr(api, '_gt_material_filter_page', track_gt_page)
            actual = api._role_material_page(repo, annotations, contract,
                sample_role='pending_negative', page=27, limit=10,
                sort_order=order, include_payload=True, count_mode='deferred')
        assert [row['id'] for row in actual['items']] == [row['id'] for row in expected['items']]
        assert len(actual['items']) == 10
        assert actual['has_next'] is True
        assert len(observed_calls) >= 3, observed_calls
        assert observed_calls[0] == (1, None), observed_calls
        assert all(page is None and cursor for page, cursor in observed_calls[1:]), observed_calls
        assert len(set(cursor for _, cursor in observed_calls[1:])) == len(observed_calls) - 1
