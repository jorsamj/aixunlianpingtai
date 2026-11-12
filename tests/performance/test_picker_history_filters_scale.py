"""Isolated indexed-history and deferred-role timings; never production evidence."""
import json, time, math, statistics, sqlite3
import pytest
from platform_core.material_repository import MaterialRepository
from platform_core.annotation_repository import AnnotationRepository
from platform_core.task_runtime.repository import TaskRepository
from platform_core.training_material_usage import TrainingMaterialUsage
from platform_core.training_material_picker_api import _usage_filters,_gt_material_filter_page,_role_material_page,_picker_filter_sql,_attach_usage_exclusion

@pytest.mark.parametrize('size',[1000,10000,50000,200000])
def test_history_and_role_filter_scale(tmp_path,size):
    repo=MaterialRepository(tmp_path/'data'/'projects'/'perf')
    for start in range(0,size,1000):
        repo.upsert_many([{'id':f'i{i:07d}','filename':f'{i}.jpg','processing_status':'processed',
            'content_sha256':f'{i+1:064x}','created_at':'2026-11-04'} for i in range(start,min(size,start+1000))])
    gt=AnnotationRepository(repo.project_path)
    path=repo.project_path.parent.parent/'task_runtime'/'tasks.sqlite3'
    TaskRepository(path)
    usage=TrainingMaterialUsage(path)
    rows=repo.get_many([f'i{i:07d}' for i in range(120)])
    usage.record_selected('perf','a','past',{'snapshot_id':'s','images':[
        {'image_id':r['id'],'role':'train','content_sha256':r['content_sha256']} for r in rows]},source_images=rows)
    usage.record_execution('past',completed_epoch=True)
    gt.upsert_many([{'image_id':f'i{i:07d}','annotation_state':'annotated',
        'annotation_scope':['person'],'boxes':[{'label':'person','x1':1,'y1':1,'x2':2,'y2':2}]} for i in range(size-60,size)])
    for operation in ('current_only','used','pending_negative','sparse_last_positive','no_match_positive'):
        samples=[]
        for _ in range(7):
            started=time.perf_counter()
            if operation in {'sparse_last_positive','no_match_positive'}:
                result=_role_material_page(repo,gt,{'effective_label_codes':['absent' if operation=='no_match_positive' else 'person']},
                    sample_role='positive',limit=60,count_mode='deferred')
            elif operation=='pending_negative':
                result=_role_material_page(repo,gt,{'effective_label_codes':['person']},
                    sample_role='pending_negative',limit=60,count_mode='deferred')
            else:
                filters,_=_usage_filters(repo,{'algorithm_asset_id':'a','browse_only':True,
                    **({'history_scope':operation} if operation=='current_only' else {'usage_state':operation})})
                result=_gt_material_filter_page(repo,gt,filters=filters,limit=60,count_mode='deferred')
            samples.append((time.perf_counter()-started)*1000)
            assert len(result['items'])==(0 if operation=='no_match_positive' else 60)
        plan=[]
        if operation in {'current_only','used'}:
            clauses,params=_picker_filter_sql(filters)
            with sqlite3.connect(repo.path,uri=True) as db:
                _attach_usage_exclusion(db,filters)
                plan=[row[3] for row in db.execute('EXPLAIN QUERY PLAN SELECT m.id FROM materials m WHERE '+' AND '.join(clauses),params)]
            assert any('SEARCH t USING COVERING INDEX' in row for row in plan),plan
        print(json.dumps({'fixture_only':True,'rows':size,'operation':operation,'samples':7,
            'plan':plan,'p50_ms':round(statistics.median(samples),3),'p95_ms':round(sorted(samples)[-1],3)}))
