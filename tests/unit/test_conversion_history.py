import json
from platform_core.conversion_history import ConversionHistoryProjection


def test_incremental_legacy_history_1000_files_scoped_paging_and_live_overlay(tmp_path):
    jobs=tmp_path/'deploy'/'jobs'
    for i in range(1000):
        directory=jobs/f'j{i:04d}';directory.mkdir(parents=True)
        value={'id':f'j{i:04d}','source_id':f'version::a::{"old" if i<20 else "new"}',
               'created_at':f'2026-10-{1+i//40:02d}T12:00:00Z',
               'status':'queued' if i<10 else 'done','target':'sophon',
               'params':{'chip':'bm1684x','precision':'fp16'}}
        (directory/'job.json').write_text(json.dumps(value))
    reads=[];overlays=[]
    def read(path, default):
        reads.append(path)
        try:return json.loads(path.read_text())
        except (ValueError,OSError):return default
    def overlay(job):
        overlays.append(job['id']);job['status']='running';return job
    cache=ConversionHistoryProjection(max_projects=2)
    cold=cache.query(jobs,read_json=read,overlay=overlay,page=1,page_size=10)
    assert cold['total']==1000 and cold['stats']['json_reads']==1000
    assert cold['stats']['overlays']==10 and cold['complete']
    hot=cache.query(jobs,read_json=read,overlay=overlay,page=2,page_size=10)
    assert hot['stats']['json_reads']==0 and hot['stats']['overlays']==10
    assert hot['stats']['metadata_files']==0
    assert {j['id'] for j in cold['items']}.isdisjoint(j['id'] for j in hot['items'])
    old=cache.query(jobs,read_json=read,overlay=overlay,algorithm_id='a',version_id='old',status='running',target='sophon',chip='BM1684X',precision='fp16',csc='unknown',page=2,page_size=3)
    assert old['total']==10 and len(old['items'])==3
    assert all(j['source_id']=='version::a::old' for j in old['items'])
    assert cache.query(jobs,read_json=read,algorithm_id='other')['total']==0
    assert cache.query(jobs,read_json=read,version_id='old',created_from='2026-10-02')['total']==0
    # A terminal job can be retried by its owner: changed signature must replace
    # its parsed data and the live overlay must now participate in filtering.
    path=jobs/'j0999'/'job.json';changed=json.loads(path.read_text());changed['status']='queued'
    changed['params']['csc_preset']='bt709_limited';path.write_text(json.dumps(changed))
    refreshed=cache.query(jobs,read_json=read,overlay=overlay,csc='bt709_limited',status='running',force=True)
    assert refreshed['total']==1 and refreshed['items'][0]['id']=='j0999'
    assert refreshed['stats']['json_reads']==1 and refreshed['stats']['overlays']==11
    # Corrupt records are explicitly incomplete, never normal empty history.
    (jobs/'j0998'/'job.json').write_text('{')
    broken=cache.query(jobs,read_json=read,force=True)
    assert not broken['complete'] and broken['unreadable_count']==1 and broken['total']==999
    assert broken['diagnostics'][0]['file']=='j0998/job.json'
    print({'cold':cold['stats'],'hot':hot['stats'],'changed':refreshed['stats']})

    # Legacy source_meta identities and inclusive date-only UI bounds remain exact.
    legacy=jobs/'legacy-meta';legacy.mkdir()
    (legacy/'job.json').write_text(json.dumps({'id':'legacy','status':'done','target':'onnx',
        'source_meta':{'algorithm_id':'a','version_id':'old'},'created_at':'2026-10-01T22:30:00Z'}))
    dated=cache.query(jobs,read_json=read,algorithm_id='a',version_id='old',created_from='2026-10-01',created_to='2026-10-01',force=True)
    assert dated['total']==21
    assert 'legacy' in {row['id'] for row in dated['items']}
