"""Small opt-in evidence run over existing owners; no GPU, image I/O or load test.

MC_PERF_AUDIT_OUTPUT may name an isolated report directory. SQL values/paths are
never recorded. Timings are instrumented Windows/Linux test data, not production.
"""
import json
import os
import sqlite3
import threading
import time
from collections import Counter
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

from platform_core.annotation_repository import AnnotationRepository
from platform_core.material_repository import MaterialRepository
from platform_core.task_runtime.models import TaskKind, TaskRecord, TaskStatus
from platform_core.task_runtime.repository import TaskRepository
from platform_core.training_material_usage import TrainingMaterialUsage


@contextmanager
def measured(monkeypatch):
    facts = Counter()
    thread_id=threading.get_ident()
    original_connect, original_loads = sqlite3.connect, json.loads
    class Connection(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            if threading.get_ident()!=thread_id: return super().execute(sql,*args,**kwargs)
            facts['sql_statements'] += 1
            began = time.perf_counter()
            try:
                return super().execute(sql, *args, **kwargs)
            finally:
                facts['sql_execute_ms'] += (time.perf_counter()-began)*1000
    def connect(*args, **kwargs):
        if threading.get_ident()!=thread_id: return original_connect(*args,**kwargs)
        facts['db_connections'] += 1
        kwargs.setdefault('factory', Connection)
        return original_connect(*args, **kwargs)
    def loads(*args, **kwargs):
        if threading.get_ident()!=thread_id: return original_loads(*args,**kwargs)
        facts['json_parses'] += 1
        began = time.perf_counter()
        try:
            return original_loads(*args, **kwargs)
        finally:
            facts['json_parse_ms'] += (time.perf_counter()-began)*1000
    with monkeypatch.context() as patch:
        patch.setattr(sqlite3, 'connect', connect)
        patch.setattr(json, 'loads', loads)
        began=time.perf_counter()
        yield facts
        facts['total_ms']=(time.perf_counter()-began)*1000


def timed(patch, facts, owner, name, metric):
    original=getattr(owner,name)
    thread_id=threading.get_ident()
    def invoke(*args, **kwargs):
        if threading.get_ident()!=thread_id: return original(*args,**kwargs)
        facts[metric+'_calls'] += 1
        began=time.perf_counter()
        try:
            value=original(*args, **kwargs)
            if name=='list': facts['task_rows_read'] += len(value.items)
            if name=='query_filter': facts['usage_materials'] += len(value['by_image_id'])
            return value
        finally:
            facts[metric+'_ms'] += (time.perf_counter()-began)*1000
    patch.setattr(owner,name,invoke)


def report(name, results):
    value={'environment':'isolated real repositories; instrumented; NOT production',
           'samples':results,'lock_wait_ms':'NOT SEPARATELY MEASURED; SQL timing includes any wait',
           'network_ms':'NOT MEASURED'}
    output=os.environ.get('MC_PERF_AUDIT_OUTPUT')
    if output:
        root=Path(output);root.mkdir(parents=True,exist_ok=True)
        (root/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    print(name,json.dumps(value,ensure_ascii=False))


def test_jobs_read_cost_with_unchanged_terminal_history(tmp_path, monkeypatch):
    import app as api
    from platform_core.training_history_projection import TrainingHistoryProjection
    project=tmp_path/'projects'/'audit'; jobs=project/'jobs';jobs.mkdir(parents=True)
    repository=TaskRepository(tmp_path/'task_runtime'/'tasks.sqlite3')
    for i in range(220):
        identity=f'audit-{i:04d}'
        repository.create(replace(TaskRecord.new(identity,'audit',TaskKind.TRAINING,'payload.json','test-only'),
            status=TaskStatus.FAILED,error='isolated historical fixture',finished_at='2026-10-28T00:00:00+00:00'))
        directory=jobs/identity;directory.mkdir()
        (directory/'job.json').write_text(json.dumps({'id':identity,'task_id':identity,'status':'failed',
            'asset_algorithm_name':'Isolated audit','message':'isolated historical fixture',
            'created_at':'2026-10-28T00:00:00+00:00','finished_at':'2026-10-28T00:00:00+00:00'}))
    monkeypatch.setattr(api,'get_project',lambda p:{'id':p})
    monkeypatch.setattr(api,'project_dir',lambda p:project)
    monkeypatch.setattr(api,'shared_task_repository',lambda:repository)
    monkeypatch.setattr(api,'_TRAINING_HISTORY_PROJECTION',TrainingHistoryProjection())
    monkeypatch.setattr(api,'_TRAINING_JOB_PROJECTIONS',{})
    results=[]
    for label in ('cold','warm-1','warm-2'):
        with measured(monkeypatch) as facts, monkeypatch.context() as patch:
            for name,key in [('_training_history_context','history'),('_v48_dispatch_training_queues','legacy_queue'),
                             ('sync_jobs_index','index'),('enrich_job_runtime','enrich')]:
                timed(patch,facts,api,name,key)
            timed(patch,facts,repository,'list','task_list')
            rows=api.list_jobs('audit')
        assert len(rows)==50 and all(row['status']=='failed' for row in rows)
        assert facts['history_calls']==1 and facts['task_list_calls']==3
        assert facts['task_rows_read']==220 and facts['db_connections']<20
        results.append({'case':label,'returned_tasks':len(rows),'history_tasks':220,**dict(facts)})
    report('jobs',results)
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from platform_core.performance_diagnostics import PerformanceDiagnosticsMiddleware
    http_app=FastAPI();http_app.add_middleware(PerformanceDiagnosticsMiddleware)
    http_app.add_api_route('/api/projects/{project_id}/jobs',api.list_jobs,methods=['GET'])
    monkeypatch.setattr(api,'_TRAINING_HISTORY_PROJECTION',TrainingHistoryProjection())
    monkeypatch.setattr(api,'_TRAINING_JOB_PROJECTIONS',{})
    monkeypatch.setenv('MC_PERFORMANCE_DIAGNOSTICS','1')
    http=[]
    with TestClient(http_app) as client:
        for label in ('process-cache-cold','warm-1','warm-2'):
            began=time.perf_counter();response=client.get('/api/projects/audit/jobs')
            duration=(time.perf_counter()-began)*1000
            assert response.status_code==200 and len(response.json())==50
            http.append({'case':label,'total_ms':duration,'response_bytes':len(response.content),
                'request_id':response.headers['X-Request-ID'],'server_timing':response.headers['Server-Timing']})
    report('jobs_http',http)


def test_picker_cost_cold_hot_filters_and_revisions(tmp_path,monkeypatch):
    from platform_core import training_material_picker_api as picker
    from platform_core import training_label_tasks as labels
    project=tmp_path/'projects'/'audit';repo=MaterialRepository(project);gt=AnnotationRepository(project)
    images=[{'id':f'i{i:04d}','filename':f'image-{i:04d}.jpg','processing_status':'processed',
             'content_sha256':f'{i+1:064x}','width':100,'height':100,
             'created_at':'2026-10-28T00:00:00+00:00','storage_source_id':'default_local','object_key':f'{i}.jpg'} for i in range(1000)]
    repo.upsert_many(images)
    annotations=[{'image_id':r['id'],'annotation_state':'annotated','boxes':[
        {'label':'fire' if i%2==0 else 'person','class_id':i%2,'x1':1,'y1':1,'x2':20,'y2':20}],
        'annotation_scope':['fire','person']} for i,r in enumerate(images)]
    for start in range(0,len(annotations),500): gt.upsert_many(annotations[start:start+500])
    task_path=tmp_path/'task_runtime'/'tasks.sqlite3';TaskRepository(task_path)
    usage=TrainingMaterialUsage(task_path);usage.mark_coverage('audit','a',complete=True)
    picker._cached_role_index.cache_clear();picker._cached_usage_pool.cache_clear()
    results=[]
    for label,algorithm,query in [('cold','a',''),('warm-1','a',''),('warm-2','a',''),('filter','a','image-00'),('algorithm','b',''),('revision','a','')]:
        if label=='revision': repo.upsert_many([{**images[-1],'filename':'updated-name.jpg'}])
        before_role=picker._cached_role_index.cache_info();before_usage=picker._cached_usage_pool.cache_info()
        with measured(monkeypatch) as facts,monkeypatch.context() as patch:
            for name,key in [('_cached_role_index','role_index'),('_cached_usage_pool','usage_pool'),('_role_material_page','role_page')]:
                timed(patch,facts,picker,name,key)
            timed(patch,facts,labels,'training_material_role','role_classification')
            timed(patch,facts,TrainingMaterialUsage,'query_filter','usage_batch')
            body,_=picker._usage_filters(repo,{'algorithm_asset_id':algorithm,'query':query})
            result=picker._role_material_page(repo,gt,{'effective_label_codes':['fire']},query=query,filters=body,limit=60)
            picker._page_usage_facts(repo,body,result['items'])
            serialized=json.dumps(result,ensure_ascii=False)
        after_role=picker._cached_role_index.cache_info();after_usage=picker._cached_usage_pool.cache_info()
        assert len(result['items'])==60 and result['total']==(100 if query else 1000)
        results.append({'case':label,'pool_materials':1000,'page_materials':60,'filtered_total':result['total'],
            'response_bytes':len(serialized.encode()),'role_cache_hit':after_role.hits>before_role.hits,
            'usage_cache_hit':after_usage.hits>before_usage.hits,**dict(facts)})
    report('picker',results)
    # Measure the complete original router + ASGI JSON response separately.
    # No auth/network/production inference is implied by this isolated client.
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from platform_core.performance_diagnostics import PerformanceDiagnosticsMiddleware
    (project/'meta.json').write_text(json.dumps({'labels':['fire','person']}),encoding='utf-8')
    http_app=FastAPI();http_app.add_middleware(PerformanceDiagnosticsMiddleware)
    http_app.include_router(picker.training_material_picker_router(lambda p:{'id':p},tmp_path,
        algorithm_provider=lambda *args:{'id':'a','versions':[]}))
    picker._cached_role_index.cache_clear();picker._cached_usage_pool.cache_clear()
    monkeypatch.setenv('MC_PERFORMANCE_DIAGNOSTICS','1')
    http=[]
    with TestClient(http_app) as client:
        for label in ('cold','warm-1','warm-2'):
            began=time.perf_counter()
            response=client.post('/api/v62/projects/audit/training-materials/role-page',json={
                'algorithm_asset_id':'a','train_labels':['fire'],'model':'yolo11n.pt','page_size':60})
            duration=(time.perf_counter()-began)*1000
            assert response.status_code==200,response.text
            body=response.json()
            assert body['total']==1000 and len(body['items'])==60
            http.append({'case':label,'total_ms':duration,'response_bytes':len(response.content),
                'request_id':response.headers['X-Request-ID'],'server_timing':response.headers['Server-Timing']})
    report('picker_http',http)


def test_legacy_queue_keeps_post_dispatch_reread(tmp_path,monkeypatch):
    import app as api
    from platform_core.training_history_projection import TrainingHistoryProjection
    project=tmp_path/'projects'/'legacy';directory=project/'jobs'/'old';directory.mkdir(parents=True)
    (directory/'job.json').write_text(json.dumps({'id':'old','status':'queued','resource_key':'local:test',
        'asset_algorithm_name':'Isolated legacy','created_at':'2026-10-28T00:00:00+00:00'}))
    repository=TaskRepository(tmp_path/'task_runtime'/'tasks.sqlite3')
    monkeypatch.setattr(api,'get_project',lambda p:{'id':p})
    monkeypatch.setattr(api,'project_dir',lambda p:project)
    monkeypatch.setattr(api,'shared_task_repository',lambda:repository)
    monkeypatch.setattr(api,'_TRAINING_HISTORY_PROJECTION',TrainingHistoryProjection())
    monkeypatch.setattr(api,'_TRAINING_JOB_PROJECTIONS',{})
    attempted=[]
    def fail_launch(project_id,job):
        attempted.append(job['id'])
        raise RuntimeError('isolated legacy launcher failure; no process started')
    monkeypatch.setattr(api,'_v48_launch_saved_job',fail_launch)
    with measured(monkeypatch) as facts,monkeypatch.context() as patch:
        timed(patch,facts,api,'_training_history_context','history')
        rows=api.list_jobs('legacy')
    assert attempted==['old'] and facts['history_calls']==2
    assert rows[0]['status']=='failed' and 'isolated legacy launcher failure' in rows[0]['message']
    assert json.loads((directory/'job.json').read_text(encoding='utf-8'))['never_started'] is True
