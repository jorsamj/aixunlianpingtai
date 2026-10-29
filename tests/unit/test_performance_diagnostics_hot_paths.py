import asyncio
import json

from platform_core.performance_diagnostics import PerformanceDiagnosticsMiddleware, _endpoint, count


def test_hot_path_categories_never_include_project_or_material_identity():
    assert _endpoint('/api/v53/bootstrap/snapshot') == 'bootstrap'
    assert _endpoint('/api/v61/projects/secret-project/materials/secret-image/content/thumbnail') == 'material.thumbnail'
    assert _endpoint('/api/v42/projects/p/algorithms/a/versions/v/deployments') == 'conversion.history'
    assert _endpoint('/api/v41/deploy/plugins') == 'conversion.plugins'
    assert _endpoint('/api/v19/projects/p/import/jobs/old-id') == 'upload.jobs'
    assert _endpoint('/api/not-profiled/private') is None


def test_opt_in_middleware_adds_request_id_timing_and_body_bytes(monkeypatch, caplog):
    monkeypatch.setenv('MC_PERFORMANCE_DIAGNOSTICS', '1')
    sent = []

    async def app(_scope, _receive, send):
        count('fixture_calls')
        await send({'type':'http.response.start','status':200,'headers':[]})
        await send({'type':'http.response.body','body':b'{"ok":true}','more_body':False})

    scope = {'type':'http','method':'GET','path':'/api/training_options',
             'headers':[(b'x-client-operation-id',b'client_12345678'),(b'authorization',b'Bearer SECRET')]}
    async def collect(message):
        sent.append(message)

    async def run():
        await PerformanceDiagnosticsMiddleware(app)(scope,lambda:None,collect)

    with caplog.at_level('INFO',logger='platform.performance'):
        asyncio.run(run())
    headers = dict(sent[0]['headers'])
    assert len(headers[b'x-request-id'])==32
    assert b'total;dur=' in headers[b'server-timing']
    fact = json.loads(caplog.records[-1].message)
    assert fact['response_bytes']==11
    assert fact['counts']['fixture_calls']==1
    assert fact['client_operation_id']=='client_12345678'
    assert 'SECRET' not in caplog.records[-1].message
    assert '/api/' not in caplog.records[-1].message
