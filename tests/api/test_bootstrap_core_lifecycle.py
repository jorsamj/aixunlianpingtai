import json
import threading
import app as api


def test_core_snapshot_excludes_history_and_report_enrichment(client,seeded_project,monkeypatch):
    project,_=seeded_project
    running=api.project_dir(project)/'jobs'/'running-sentinel'/'job.json'
    running.parent.mkdir(parents=True,exist_ok=True)
    running.write_text(json.dumps({'id':'running-sentinel','status':'running','epoch':17}),encoding='utf-8')
    before=running.read_bytes()
    def forbidden(*args,**kwargs):raise AssertionError('noncritical history/report must not block core')
    for name in ['_training_history_context','_successful_training_counts','_v53_live_jobs','_v53_algorithms_with_revision','_v35_model_items']:
        monkeypatch.setattr(api,name,forbidden)
    result=api._v53_build_snapshot(project,core_only=True)
    assert result['project']['id']==project
    assert result['jobs']==[] and result['jobs_deferred'] is True
    assert result['algorithms_deferred'] is True
    assert len(json.dumps(result))<100000
    assert running.read_bytes()==before


def test_core_cache_miss_never_builds_inline(client,seeded_project,monkeypatch):
    project,_=seeded_project
    monkeypatch.setattr(api,'_V53_BOOTSTRAP_SNAPSHOT',{})
    monkeypatch.setattr(api,'_V53_BOOTSTRAP_STATUS',{'status':'running'})
    monkeypatch.setattr(api,'_v53_start_bootstrap',lambda *a,**kw:None)
    monkeypatch.setattr(api,'_v53_build_snapshot',lambda *a,**kw:(_ for _ in ()).throw(AssertionError('inline build')))
    response=client.get('/api/v53/bootstrap/snapshot',params={'core':True,'preferred_project_id':project})
    assert response.status_code==503
    assert response.json()['code']=='BOOTSTRAP_PENDING'


def test_forced_start_cannot_duplicate_a_live_worker(monkeypatch):
    class Live:
        def is_alive(self):return True
    monkeypatch.setattr(api,'_V53_BOOTSTRAP_THREAD',Live())
    monkeypatch.setattr(api.threading,'Thread',lambda **kw:(_ for _ in ()).throw(AssertionError('duplicate')))
    api._v53_start_bootstrap(force=True)

def test_core_fresh_cache_never_reads_history_and_invalid_revision_is_not_returned(client,seeded_project,monkeypatch):
    project,_=seeded_project
    cached=api._v53_build_snapshot(project,core_only=True)
    monkeypatch.setattr(api,'_V53_BOOTSTRAP_SNAPSHOT',cached)
    monkeypatch.setattr(api,'_V53_BOOTSTRAP_STATUS',{'status':'ready'})
    monkeypatch.setattr(api,'_v53_snapshot_with_live_jobs',lambda *a:(_ for _ in ()).throw(AssertionError('history overlay')))
    response=client.get('/api/v53/bootstrap/snapshot')
    assert response.status_code==200
    assert response.headers['X-Bootstrap-Cache']=='fresh'
    assert int(response.headers['X-Response-Bytes'])==len(response.content)
    monkeypatch.setattr(api,'_v53_core_revisions',lambda _:{'changed':True})
    monkeypatch.setattr(api,'_v53_start_bootstrap',lambda *a,**kw:None)
    assert client.get('/api/v53/bootstrap/snapshot').status_code==503


def test_many_cold_requests_share_one_background_build(client,seeded_project,monkeypatch):
    import concurrent.futures,time
    project,_=seeded_project
    entered,release=threading.Event(),threading.Event()
    builds=[]
    cached=api._v53_build_snapshot(project,core_only=True)
    def build(*args,**kwargs):
        builds.append(1);entered.set();assert release.wait(5);return cached
    monkeypatch.setattr(api,'_V53_BOOTSTRAP_SNAPSHOT',{})
    monkeypatch.setattr(api,'_V53_BOOTSTRAP_STATUS',{'status':'idle'})
    monkeypatch.setattr(api,'_V53_BOOTSTRAP_THREAD',None)
    monkeypatch.setattr(api,'_v53_build_snapshot',build)
    monkeypatch.setattr(api,'list_projects',lambda:[cached['project']])
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            results=list(pool.map(lambda _:api.v53_bootstrap_snapshot(project),range(6)))
        assert entered.wait(1)
        assert all(r.status_code==503 for r in results)
        assert len(builds)==1
    finally:
        release.set()
        if api._V53_BOOTSTRAP_THREAD:api._V53_BOOTSTRAP_THREAD.join(5)
    assert api.v53_bootstrap_snapshot(project).status_code==200


def test_database_probe_failure_is_classified_and_retryable(client,seeded_project,monkeypatch):
    import sqlite3
    project,_=seeded_project
    cached=api._v53_build_snapshot(project,core_only=True)
    monkeypatch.setattr(api,'_V53_BOOTSTRAP_SNAPSHOT',cached)
    monkeypatch.setattr(api,'_v53_core_revisions',lambda _:(_ for _ in ()).throw(sqlite3.OperationalError('database is locked')))
    response=client.get('/api/v53/bootstrap/snapshot')
    assert response.status_code==503 and response.json()['code']=='BOOTSTRAP_DATABASE_BUSY'
    assert 'database is locked' not in response.text

def test_noncritical_recovery_failure_does_not_retire_ready_core(client,seeded_project,monkeypatch):
    project,_=seeded_project
    monkeypatch.setattr(api,'_V53_BOOTSTRAP_THREAD',None)
    monkeypatch.setattr(api,'_V53_BOOTSTRAP_STATUS',{'status':'ready','progress':100})
    monkeypatch.setattr(api,'list_projects',lambda:[{'id':project}])
    monkeypatch.setattr(api,'_v50_recover_dataset_deletions',lambda _:(_ for _ in ()).throw(RuntimeError('isolated recovery failure')))
    api._v53_post_bootstrap_recovery()
    assert api._V53_BOOTSTRAP_STATUS['status']=='ready'
    assert api._V53_BOOTSTRAP_STATUS['maintenance_status']=='failed'


def test_failed_core_build_can_be_retried_without_publishing_partial_snapshot(client,seeded_project,monkeypatch):
    project,_=seeded_project
    good=api._v53_build_snapshot(project,core_only=True)
    monkeypatch.setattr(api,'_V53_BOOTSTRAP_STATUS',{})
    monkeypatch.setattr(api,'_V53_BOOTSTRAP_SNAPSHOT',{})
    monkeypatch.setattr(api,'list_projects',lambda:[good['project']])
    monkeypatch.setattr(api,'_v53_build_snapshot',lambda *a,**kw:(_ for _ in ()).throw(RuntimeError('isolated build failure')))
    api._v53_bootstrap_worker(project)
    assert api._V53_BOOTSTRAP_STATUS['status']=='failed'
    assert not api._V53_BOOTSTRAP_SNAPSHOT
    monkeypatch.setattr(api,'_v53_build_snapshot',lambda *a,**kw:good)
    api._v53_bootstrap_worker(project)
    assert api._V53_BOOTSTRAP_STATUS['status']=='ready'
    assert api._V53_BOOTSTRAP_SNAPSHOT['core_only']
