"""Real SQLite/ASGI measurement, synthetic heavy reports, no model or GPU calls."""
from collections import Counter
import hashlib
import json
import statistics
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from platform_core.algorithm_sql_store import AlgorithmSqlStore
from platform_core.material_repository import MaterialRepository
from platform_core.negative_pool import NegativePool
from platform_core.negative_pool_api import create_negative_pool_router
from platform_core import performance_diagnostics as diagnostics


def test_pool_existence_and_empty_algorithm_do_not_hydrate_unrelated_reports(tmp_path, monkeypatch):
    materials = MaterialRepository(tmp_path / 'synthetic-project')
    materials.upsert_many([{'id':'one','filename':'one.png','object_key':'uploads/one.png',
        'created_at':'2026-11-07T00:00:00+00:00','updated_at':'2026-11-07T00:00:00+00:00'}])
    store = AlgorithmSqlStore(materials.project_path / 'algorithms.json')
    target = {'id':'target','name':'target','versions':[]}
    graph = [target, *[{'id':f'other-{i}','name':f'other-{i}', 'versions':[
        {'id':f'v-{i}-{j}','evaluation':{'synthetic_report':'e'*(2*1024*1024)},
         'label_contract':{'synthetic_report':'l'*(1024*1024)}} for j in range(2)]} for i in range(8)]]
    store.replace_all(graph)
    pool = NegativePool(materials)
    pool.members(['one'], algorithm_id='target')
    # Stable synthetic input permits exact before/after response comparison.
    with materials._connect() as db:
        db.execute("UPDATE negative_pool_members SET joined_at='2026-11-07T00:00:00+00:00'")
        db.execute("UPDATE negative_pool_algorithm_members SET joined_at='2026-11-07T00:00:00+00:00'")
        db.commit()
    api = FastAPI()
    api.include_router(create_negative_pool_router(lambda _id: materials,
        lambda _id: {'id':'synthetic-project','labels':[]}, lambda _id,row: row))
    original = AlgorithmSqlStore._json_object
    parsed = {'bytes':0,'ms':0,'calls':0}
    def observed_json(value):
        began=time.perf_counter()
        try:
            return original(value)
        finally:
            parsed['bytes'] += len(str(value or '{}').encode('utf-8'))
            parsed['ms'] += (time.perf_counter()-began)*1000
            parsed['calls'] += 1
    monkeypatch.setattr(AlgorithmSqlStore, '_json_object', staticmethod(observed_json))
    measurements=[]
    with TestClient(api) as client:
        assert client.get('/api/v61/projects/synthetic-project/negative-pool?algorithm_id=target').status_code==200
        for _ in range(7):
            parsed.update(bytes=0,ms=0,calls=0)
            trace={'counts':Counter(),'stages_ms':Counter(),'sql_cumulative_ms':None}
            token=diagnostics._current.set(trace)
            began=time.perf_counter()
            try:
                response=client.get('/api/v61/projects/synthetic-project/negative-pool?algorithm_id=target')
            finally:
                diagnostics._current.reset(token)
            assert response.status_code==200, response.text
            assert response.json()['total']==1
            assert response.json()['scope_kind']=='requested_labels'
            assert response.json()['effective_label_codes']==[]
            measurements.append({'request_ms':(time.perf_counter()-began)*1000,
                'json_bytes':parsed['bytes'],'json_parse_ms':parsed['ms'],'json_calls':parsed['calls'],
                'sql_calls':trace['counts']['sql.execute.calls'],'sql_ms':trace['sql_cumulative_ms'],
                'response_sha256':hashlib.sha256(json.dumps(response.json(),sort_keys=True).encode()).hexdigest()})
    elapsed=sorted(row['request_ms'] for row in measurements)
    report={'kind':'ISOLATED_SYNTHETIC_NOT_PRODUCTION','samples':7,'version_payload_mib':48,
        'p50_ms':statistics.median(elapsed),'p95_ms':elapsed[-1], 'measurements':measurements}
    print('ARCH_ALGORITHM_BENCHMARK='+json.dumps(report,sort_keys=True))
    assert len({row['response_sha256'] for row in measurements})==1
    assert max(row['json_bytes'] for row in measurements)<1024, 'scope/list must not parse unrelated version reports'
