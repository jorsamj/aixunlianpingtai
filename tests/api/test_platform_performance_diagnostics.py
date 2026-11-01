import json
import logging
import re


def test_negative_pool_categories_diagnostics_route_is_strictly_scoped(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from platform_core.performance_diagnostics import _endpoint, PerformanceDiagnosticsMiddleware

    assert _endpoint('/api/v61/projects/synthetic/negative-pool/categories') == 'negative_pool.categories'
    assert _endpoint('/api/v61/projects/synthetic/negative-pool/categories/delete') is None
    assert _endpoint('/api/v61/projects/synthetic/negative-pool/members') is None
    monkeypatch.setenv('MC_PERFORMANCE_DIAGNOSTICS','1')
    app=FastAPI()
    app.add_middleware(PerformanceDiagnosticsMiddleware)

    @app.get('/api/v61/projects/{project_id}/negative-pool/categories')
    def read(project_id: str):
        return {'items':[]}

    @app.post('/api/v61/projects/{project_id}/negative-pool/categories')
    def write(project_id: str):
        return {'id':'fixture'}

    with TestClient(app) as client:
        observed=client.get('/api/v61/projects/synthetic/negative-pool/categories')
        unobserved=client.post('/api/v61/projects/synthetic/negative-pool/categories')
    assert observed.status_code==200 and observed.headers.get('X-Request-ID')
    assert 'total;dur=' in observed.headers['Server-Timing']
    assert unobserved.status_code==200 and 'X-Request-ID' not in unobserved.headers


def test_hot_path_diagnostics_are_opt_in_correlated_and_do_not_log_inputs(client, seeded_project, monkeypatch, caplog):
    project_id, _ = seeded_project
    endpoint=f'/api/projects/{project_id}/jobs'
    monkeypatch.delenv('MC_PERFORMANCE_DIAGNOSTICS', raising=False)
    ordinary=client.get(endpoint)
    assert ordinary.status_code==200 and 'X-Request-ID' not in ordinary.headers
    monkeypatch.setenv('MC_PERFORMANCE_DIAGNOSTICS','1')
    with caplog.at_level(logging.INFO,logger='platform.performance'):
        observed=client.get(endpoint+'?token=private-audit-secret',headers={'X-Request-ID':'private-audit-secret'})
    assert observed.status_code==200 and observed.json()==ordinary.json()
    request_id=observed.headers.get('X-Request-ID','')
    assert re.fullmatch('[0-9a-f]{32}',request_id)
    assert 'total;dur=' in observed.headers['Server-Timing']
    records=[json.loads(row.message) for row in caplog.records if row.name=='platform.performance']
    assert len(records)==1
    facts=records[0]
    assert facts['request_id']==request_id and facts['endpoint']=='training.jobs'
    assert facts['counts']['training_history.calls']==1
    assert facts['counts']['repository_sql_statements']>0
    assert facts['sql_cumulative_ms'] is not None and facts['sql_cumulative_ms'] > 0
    assert facts['stages_ms']['sql.execute'] > 0
    assert facts['sql_scope']=='instrumented_repository_connections'
    assert facts['sqlite_lock_wait_ms'] is None
    assert 'private-audit-secret' not in json.dumps(facts)
    assert project_id not in json.dumps(facts)
