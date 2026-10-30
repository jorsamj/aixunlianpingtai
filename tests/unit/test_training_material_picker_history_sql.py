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
        second = _gt_material_filter_page(repo,annotations,filters=filters,limit=15,page=2)
        all_rows = _gt_material_filter_page(repo,annotations,filters=filters,limit=60,page=1)
        expected = {row['id'] for row in rows} - set(original['excluded_image_ids'])
        assert set(all_rows['items']) == expected
        assert first['total']==second['total']==all_rows['total']==len(expected)
        assert set(first['items']).isdisjoint(second['items'])
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
                               filters=filters,sample_role='positive',limit=60)
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
