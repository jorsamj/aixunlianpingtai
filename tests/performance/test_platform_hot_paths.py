"""Small opt-in evidence run over existing owners; no GPU, image I/O or load test.

MC_PERF_AUDIT_OUTPUT may name an isolated report directory. SQL values/paths are
never recorded. Timings are instrumented Windows/Linux test data, not production.
"""
import json
import math
import os
import sqlite3
import statistics
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


def _isolated_http_latency_summary(samples):
    """Nearest-rank P95 on twenty warm, in-process calls; never production SLOs."""
    ordered = sorted(samples)
    return {'samples': len(ordered), 'p50_ms': round(statistics.median(ordered), 3),
            'p95_ms': round(ordered[math.ceil(len(ordered)*0.95)-1], 3),
            'min_ms': round(ordered[0], 3), 'max_ms': round(ordered[-1], 3)}


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
        assert facts['legacy_queue_calls']==0, 'GET must not execute legacy maintenance'
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


def test_bootstrap_cached_snapshot_history_scaling(tmp_path, monkeypatch):
    """Real cached-snapshot route and history owners; no startup worker or live data.

    The surrounding project/algorithm lookup is isolated so this measures only
    the historically suspicious cached Bootstrap overlay, not full startup.
    """
    import app as api
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from platform_core.performance_diagnostics import PerformanceDiagnosticsMiddleware
    from platform_core.training_history_projection import TrainingHistoryProjection

    project=tmp_path/'projects'/'audit';jobs=project/'jobs';jobs.mkdir(parents=True)
    repository=TaskRepository(tmp_path/'task_runtime'/'tasks.sqlite3')
    monkeypatch.setattr(api,'get_project',lambda p:{'id':p})
    monkeypatch.setattr(api,'project_dir',lambda p:project)
    monkeypatch.setattr(api,'list_projects',lambda:[{'id':'audit'}])
    monkeypatch.setattr(api,'shared_task_repository',lambda:repository)
    monkeypatch.setattr(api,'algorithm_store_revision',lambda _:0)
    monkeypatch.setattr(api,'_V53_BOOTSTRAP_STATUS',{'status':'ready','active_project_id':'audit'})
    monkeypatch.setattr(api,'_V53_BOOTSTRAP_SNAPSHOT',{
        'project':{'id':'audit'},'algorithms':[],'jobs':[],'algorithm_revision':0})
    monkeypatch.setattr(api,'_TRAINING_JOB_PROJECTIONS',{})
    monkeypatch.setenv('MC_PERFORMANCE_DIAGNOSTICS','1')

    http_app=FastAPI();http_app.add_middleware(PerformanceDiagnosticsMiddleware)
    http_app.add_api_route('/api/v53/bootstrap/snapshot',api.v53_bootstrap_snapshot,methods=['GET'])
    samples=[];prepared=0
    with TestClient(http_app) as client:
        for history_tasks in (220,1000):
            for index in range(prepared,history_tasks):
                identity=f'audit-{index:05d}'
                repository.create(replace(TaskRecord.new(identity,'audit',TaskKind.TRAINING,'payload.json','test-only'),
                    status=TaskStatus.FAILED,error='isolated fixture',finished_at='2026-10-28T00:00:00+00:00'))
                directory=jobs/identity;directory.mkdir()
                (directory/'job.json').write_text(json.dumps({'id':identity,'task_id':identity,
                    'status':'failed','asset_algorithm_name':'Isolated audit',
                    'created_at':'2026-10-28T00:00:00+00:00',
                    'finished_at':'2026-10-28T00:00:00+00:00'}),encoding='utf-8')
            prepared=history_tasks
            # Cold means history/projection caches are reset; Task DB and OS
            # filesystem cache remain warm. It is not a process cold start.
            monkeypatch.setattr(api,'_TRAINING_HISTORY_PROJECTION',TrainingHistoryProjection())
            api._TRAINING_JOB_PROJECTIONS.clear()
            durations=[];first_timing='';response_bytes=0
            for index in range(21):
                began=time.perf_counter()
                response=client.get('/api/v53/bootstrap/snapshot')
                durations.append((time.perf_counter()-began)*1000)
                assert response.status_code==200,response.text
                payload=response.json()
                # Bootstrap presents the existing bounded fifty-task index,
                # even though its live history projection reads all tasks.
                assert len(payload['jobs'])==min(history_tasks,50)
                assert all(row['status']=='failed' for row in payload['jobs'])
                assert response.headers.get('X-Request-ID')
                timing=response.headers['Server-Timing']
                assert 'training_history;dur=' in timing and 'training_index;dur=' in timing
                first_timing=first_timing or timing
                response_bytes=len(response.content)
            samples.append({'entry_path':'cached-bootstrap-history',
                'history_tasks':history_tasks,'scope':'in-process ASGI; synthetic failed training tasks; '
                    'real TaskRepository and TrainingHistoryProjection; other Bootstrap lookups stubbed; '
                    'history projection reset only before first request',
                'first_call_ms':round(durations[0],3),
                'warm':_isolated_http_latency_summary(durations[1:]),
                'response_bytes':response_bytes,'server_timing_first':first_timing})
            assert not (jobs/'index.json').exists(), 'cached GET must not persist a history index'
    report('bootstrap_history_http',samples)


def test_training_history_projection_file_scan_growth(tmp_path):
    """Bound warm file-signature checking at 1k/10k; no Task DB or HTTP."""
    from concurrent.futures import ThreadPoolExecutor
    from platform_core.training_history_projection import TrainingHistoryProjection

    jobs=tmp_path/'jobs';jobs.mkdir()
    projection=TrainingHistoryProjection();prepared=0;samples=[]
    for history_files in (1000,10000):
        for index in range(prepared,history_files):
            directory=jobs/f'audit-{index:05d}';directory.mkdir()
            (directory/'job.json').write_text('{"status":"failed"}',encoding='utf-8')
        prepared=history_files
        projection=TrainingHistoryProjection()
        loader=lambda path:json.loads(path.read_text(encoding='utf-8'))
        began=time.perf_counter();cold=projection.read(jobs,loader)
        first_ms=(time.perf_counter()-began)*1000
        durations=[]
        for _ in range(20):
            began=time.perf_counter();rows=projection.read(jobs,loader)
            durations.append((time.perf_counter()-began)*1000)
            assert len(rows)==history_files
        assert len(cold)==history_files
        # Four genuine overlapping callers, not a synthetic lock-wait value.
        # Per-caller wall time includes its queueing behind the existing RLock.
        def concurrent_read(gate):
            gate.wait()
            began=time.perf_counter();rows=projection.read(jobs,loader)
            assert len(rows)==history_files
            return (time.perf_counter()-began)*1000
        contended_calls=[];batch_wall=[]
        with ThreadPoolExecutor(max_workers=4) as pool:
            for _ in range(5):
                gate=threading.Barrier(4)
                began=time.perf_counter()
                futures=[pool.submit(concurrent_read,gate) for _ in range(4)]
                contended_calls.extend(item.result() for item in futures)
                batch_wall.append((time.perf_counter()-began)*1000)
        samples.append({'history_files':history_files,'scope':'synthetic local job.json files; '
            'in-process signature-cache cold then warm; filesystem cache not reset',
            'first_call_ms':round(first_ms,3),
            'warm':_isolated_http_latency_summary(durations),
            'concurrent':{'callers_per_batch':4,'batches':5,
                'wall_ms_per_caller':_isolated_http_latency_summary(contended_calls),
                'batch_wall_ms_min':round(min(batch_wall),3),
                'batch_wall_ms_median':round(statistics.median(batch_wall),3),
                'batch_wall_ms_max':round(max(batch_wall),3)}})
    report('training_history_file_scan',samples)


def test_bootstrap_snapshot_miss_builds_real_synthetic_project(tmp_path,monkeypatch):
    """Snapshot miss exercises real project/material/GT/history read owners.

    No FastAPI app startup worker, network transfer, user accounts or GPU are
    involved. A fresh snapshot is not a cold OS filesystem/SQLite process.
    """
    import app as api
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from platform_core.performance_diagnostics import PerformanceDiagnosticsMiddleware
    from platform_core.training_history_projection import TrainingHistoryProjection

    project=tmp_path/'projects'/'audit';jobs=project/'jobs';jobs.mkdir(parents=True)
    meta={'id':'audit','name':'Isolated audit','labels':['fire','person'],'label_meta':[]}
    (project/'meta.json').write_text(json.dumps(meta),encoding='utf-8')
    (tmp_path/'projects.json').write_text(json.dumps([meta]),encoding='utf-8')
    repository=TaskRepository(tmp_path/'task_runtime'/'tasks.sqlite3')
    material=MaterialRepository(project)
    material.upsert_many([{'id':f'bootstrap-{i:04d}','filename':f'fixture-{i:04d}.jpg',
        'processing_status':'processed','content_sha256':f'{i+1:064x}',
        'width':100,'height':100,'created_at':'2026-10-28T00:00:00+00:00',
        'storage_source_id':'default_local','object_key':f'{i}.jpg'} for i in range(200)])
    AnnotationRepository(project)  # Real but empty canonical GT; no fabricated GT.
    monkeypatch.setattr(api,'DATA_DIR',tmp_path)
    monkeypatch.setattr(api,'PROJECTS_FILE',tmp_path/'projects.json')
    monkeypatch.setattr(api,'MODEL_CONFIGS_FILE',tmp_path/'model_configs.json')
    monkeypatch.setattr(api,'ALLOW_MULTIPLE_PROJECTS_FOR_TESTS',True)
    monkeypatch.setattr(api,'shared_task_repository',lambda:repository)
    monkeypatch.setattr(api,'_TRAINING_JOB_PROJECTIONS',{})
    monkeypatch.setenv('MC_PERFORMANCE_DIAGNOSTICS','1')
    http_app=FastAPI();http_app.add_middleware(PerformanceDiagnosticsMiddleware)
    http_app.add_api_route('/api/v53/bootstrap/snapshot',api.v53_bootstrap_snapshot,methods=['GET'])
    results=[];prepared=0
    with TestClient(http_app) as client:
        for history_tasks in (220,1000):
            for index in range(prepared,history_tasks):
                identity=f'bootstrap-job-{index:05d}'
                repository.create(replace(TaskRecord.new(identity,'audit',TaskKind.TRAINING,'payload.json','test-only'),
                    status=TaskStatus.FAILED,error='isolated fixture',finished_at='2026-10-28T00:00:00+00:00'))
                directory=jobs/identity;directory.mkdir()
                (directory/'job.json').write_text(json.dumps({'id':identity,'task_id':identity,
                    'status':'failed','asset_algorithm_name':'Isolated audit',
                    'created_at':'2026-10-28T00:00:00+00:00',
                    'finished_at':'2026-10-28T00:00:00+00:00'}),encoding='utf-8')
            prepared=history_tasks
            monkeypatch.setattr(api,'_TRAINING_HISTORY_PROJECTION',TrainingHistoryProjection())
            api._TRAINING_JOB_PROJECTIONS.clear()
            monkeypatch.setattr(api,'_V53_BOOTSTRAP_SNAPSHOT',{})
            monkeypatch.setattr(api,'_V53_BOOTSTRAP_STATUS',{'status':'ready','active_project_id':'audit'})
            durations=[];first_timing='';response_bytes=0
            for index in range(21):
                started=time.perf_counter()
                response=client.get('/api/v53/bootstrap/snapshot')
                durations.append((time.perf_counter()-started)*1000)
                assert response.status_code==200,response.text
                body=response.json()
                assert body['project']['id']=='audit'
                assert body['material_summary']['total']==200
                assert len(body['jobs'])==50
                assert len(body['labels'])==2
                assert body['datasets']
                assert 'annotation_summary' in body and 'algorithms' in body
                assert response.headers.get('X-Request-ID')
                timing=response.headers['Server-Timing']
                assert 'training_history;dur=' in timing and 'training_index;dur=' in timing
                first_timing=first_timing or timing
                response_bytes=len(response.content)
            results.append({'entry_path':'snapshot-miss-then-cache-hit','history_tasks':history_tasks,
                'synthetic_materials':200,'scope':'in-process ASGI; genuine temporary project/material/'
                    'annotation/task repositories; snapshot and history projection reset before first call; '
                    'no startup worker, network, OS cold cache, GPU or user identity',
                'first_call_ms':round(durations[0],3),
                'warm':_isolated_http_latency_summary(durations[1:]),
                'response_bytes':response_bytes,'server_timing_first':first_timing})
            assert not (jobs/'index.json').exists(), 'read-only GET cannot persist the history index'
    report('bootstrap_full_snapshot_http',results)


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
    # The production endpoint delegates to this same repository method. Keep
    # this smoke harness isolated from the global app's auth/project state.
    http_app.add_api_route('/api/v61/projects/{project_id}/materials/status-counts',
        lambda project_id: repo.processing_status_counts(), methods=['GET'])
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
        # Measure the actual ASGI/router/repository stack on the existing
        # thousand-row synthetic fixture; avoid production network/credentials.
        # The first call is reported separately from twenty warm samples.
        scenarios = (
            ('role-page', 'POST', '/api/v62/projects/audit/training-materials/role-page',
             {'algorithm_asset_id':'a','train_labels':['fire'],'model':'yolo11n.pt','page_size':60}, 'role_page'),
            ('page', 'POST', '/api/v62/projects/audit/training-materials/page',
             {'algorithm_asset_id':'a','page_size':60}, 'training.gt_page'),
            ('revision', 'GET', '/api/v62/projects/audit/training-materials/revision',
             None, 'training.picker_revision'),
            ('selection-summary', 'POST', '/api/v62/projects/audit/training-materials/selection-summary',
             {'image_ids':[f'i{i:04d}' for i in range(60)]}, 'training.selection_summary'),
            ('status-counts', 'GET', '/api/v61/projects/audit/materials/status-counts',
             None, 'material.status_counts'),
        )
        isolated=[]
        for name,method,path,payload,stage_name in scenarios:
            durations=[]
            first_timing=''
            response_bytes=0
            for index in range(21):
                began=time.perf_counter()
                response=client.request(method,path,json=payload)
                durations.append((time.perf_counter()-began)*1000)
                assert response.status_code==200,(name,response.text)
                first_timing=first_timing or response.headers['Server-Timing']
                response_bytes=len(response.content)
                assert stage_name in response.headers['Server-Timing'],name
            isolated.append({'endpoint':name,'scope':'in-process ASGI; 1000 synthetic materials',
                'first_call_ms':round(durations[0],3),'warm':_isolated_http_latency_summary(durations[1:]),
                'response_bytes':response_bytes,'server_timing_first':first_timing})
        # The regular training picker sends defer_role_counts=true until a
        # concrete role is selected. The older benchmark above intentionally
        # exercises the complete-role contract instead; keep both distinct.
        entry_paths=[]
        for name,extra,expects_role_build in (
            ('default-deferred', {'defer_role_counts':True}, False),
            ('role-filtered', {'sample_role':'positive'}, True),
        ):
            picker._cached_role_index.cache_clear()
            durations=[]
            first_timing=''
            for index in range(21):
                began=time.perf_counter()
                response=client.post('/api/v62/projects/audit/training-materials/role-page',json={
                    'algorithm_asset_id':'a','train_labels':['fire'],
                    'model':'yolo11n.pt','page_size':60,**extra})
                durations.append((time.perf_counter()-began)*1000)
                assert response.status_code==200,(name,response.text)
                body=response.json()
                assert len(body['items'])==60
                assert (body['sample_role_counts'] is not None)==expects_role_build
                first_timing=first_timing or response.headers['Server-Timing']
            cache=picker._cached_role_index.cache_info()
            assert cache.misses==(1 if expects_role_build else 0),name
            entry_paths.append({'entry_path':name,'scope':'in-process ASGI; 1000 synthetic materials; '
                'role cache cleared before first call; other process caches warm',
                'first_call_ms':round(durations[0],3),
                'warm':_isolated_http_latency_summary(durations[1:]),
                'response_bytes':len(response.content),
                'role_index_builds':cache.misses,
                'server_timing_first':first_timing})
        # Exercise the real read-only negative-plan route with valid frozen GT;
        # do not confirm negatives or change task/GT evidence.
        durations=[]
        for index in range(21):
            began=time.perf_counter()
            response=client.post('/api/v62/projects/audit/training-materials/negative-preview',json={
                'algorithm_asset_id':'a','train_labels':['fire'],'model':'yolo11n.pt',
                'train_image_ids':[f'i{i:04d}' for i in range(60)]})
            durations.append((time.perf_counter()-began)*1000)
            assert response.status_code==200,response.text
            assert sum(response.json()['counts'].values())==60
            assert 'training.negative_plan' in response.headers['Server-Timing']
        entry_paths.append({'entry_path':'negative-preview-success',
            'scope':'in-process ASGI; 60 selected synthetic materials; no confirmation/write',
            'first_call_ms':round(durations[0],3),
            'response_bytes':len(response.content),
            'warm':_isolated_http_latency_summary(durations[1:])})
    report('picker_http',http)
    report('picker_http_percentiles',isolated)
    report('picker_entry_paths',entry_paths)


def test_legacy_maintenance_dispatches_without_a_get(tmp_path,monkeypatch):
    import app as api
    from platform_core.training_history_projection import TrainingHistoryProjection
    project=tmp_path/'projects'/'legacy';directory=project/'jobs'/'old';directory.mkdir(parents=True)
    (directory/'job.json').write_text(json.dumps({'id':'old','status':'queued','resource_key':'local:test',
        'asset_algorithm_name':'Isolated legacy','created_at':'2026-10-28T00:00:00+00:00'}))
    repository=TaskRepository(tmp_path/'task_runtime'/'tasks.sqlite3')
    monkeypatch.setattr(api,'get_project',lambda p:{'id':p})
    monkeypatch.setattr(api,'project_dir',lambda p:project)
    monkeypatch.setattr(api,'list_projects',lambda:[{'id':'legacy'}])
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
    assert attempted==[] and facts['history_calls']==1
    assert rows[0]['status']=='queued'
    assert api._v48_legacy_maintenance_tick() is True
    assert attempted==['old']
    rows=api.list_jobs('legacy')
    assert rows[0]['status']=='failed' and 'isolated legacy launcher failure' in rows[0]['message']
    assert json.loads((directory/'job.json').read_text(encoding='utf-8'))['never_started'] is True
