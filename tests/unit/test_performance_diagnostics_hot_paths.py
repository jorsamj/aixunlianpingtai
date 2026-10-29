import asyncio
import json

from platform_core.performance_diagnostics import PerformanceDiagnosticsMiddleware, _endpoint, count
from platform_core.conversion_resource_detection import detect


def test_hot_path_categories_never_include_project_or_material_identity():
    assert _endpoint('/api/v53/bootstrap/snapshot') == 'bootstrap'
    assert _endpoint('/api/v61/projects/secret-project/materials/secret-image/content/thumbnail') == 'material.thumbnail'
    assert _endpoint('/api/v42/projects/p/algorithms/a/versions/v/deployments') == 'conversion.history'
    assert _endpoint('/api/v41/deploy/plugins') == 'conversion.plugins'
    assert _endpoint('/api/v39/deploy/resources/private-resource/detect') == 'conversion.resource_detect'
    assert _endpoint('/api/v39/deploy/local/auto-detect') == 'conversion.local_detect'
    assert _endpoint('/api/v39/deploy/catalog/chips/private-chip/detect') == 'conversion.chip_detect'
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


def test_explicit_chip_probe_records_detector_duration_without_resource_secrets(monkeypatch, caplog):
    monkeypatch.setenv('MC_PERFORMANCE_DIAGNOSTICS', '1')
    sent = []
    resource = {'id': 'private-chip-probe', 'kind': 'sophon', 'mode': 'remote',
                'api_key': 'NEVER_LOG_THIS_KEY', 'status': 'unchecked'}

    async def app(_scope, _receive, send):
        detect(resource, lambda row: {**row, 'status': 'ready'}, force=True)
        await send({'type': 'http.response.start', 'status': 200, 'headers': []})
        await send({'type': 'http.response.body', 'body': b'{}', 'more_body': False})

    async def collect(message):
        sent.append(message)

    scope = {'type': 'http', 'method': 'POST',
             'path': '/api/v39/deploy/catalog/chips/private-chip/detect', 'headers': []}
    with caplog.at_level('INFO', logger='platform.performance'):
        asyncio.run(PerformanceDiagnosticsMiddleware(app)(scope, lambda: None, collect))

    timing = dict(sent[0]['headers'])[b'server-timing']
    assert b'conversion.resource_inspection;dur=' in timing
    assert b'conversion.detector_call;dur=' in timing
    result = json.loads(caplog.records[-1].message)
    assert result['endpoint'] == 'conversion.chip_detect'
    assert result['counts']['conversion.detector_call.calls'] == 1
    assert 'NEVER_LOG_THIS_KEY' not in caplog.records[-1].message
    assert 'private-chip' not in caplog.records[-1].message
