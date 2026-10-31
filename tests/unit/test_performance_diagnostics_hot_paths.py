import asyncio
import hashlib
import json

from platform_core.performance_diagnostics import PerformanceDiagnosticsMiddleware, _endpoint, count, connect_sqlite, observe_connection, stage
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
    assert _endpoint('/api/v63/external-algorithm-platform/provider/products/private-product') == 'external.provider'
    assert _endpoint('/api/v63/external-algorithm-platform/config') == 'external.config'
    assert _endpoint('/api/not-profiled/private') is None


def test_training_picker_and_material_summary_routes_have_only_fixed_diagnostic_names():
    for suffix in ('', '/page', '/role-page', '/bulk-selection', '/selection-summary',
                   '/revision', '/compatibility', '/negative-preview'):
        assert _endpoint('/api/v62/projects/private-project/training-materials' + suffix) == 'training.materials'
    assert _endpoint('/api/v61/projects/private-project/materials/status-counts') == 'material.status_counts'
    assert _endpoint('/api/v62/projects/private-project/training-materials/private-image/thumbnail') is None


def test_training_picker_stage_emits_only_opt_in_scalar_timing(monkeypatch, caplog):
    sent = []

    @stage('training.selection_summary')
    def fake_picker_summary():
        return {'sensitive_input': 'PRIVATE_MATERIAL_IDENTIFIER'}

    async def app(_scope, _receive, send):
        fake_picker_summary()
        await send({'type': 'http.response.start', 'status': 200, 'headers': []})
        await send({'type': 'http.response.body', 'body': b'{}'})

    async def collect(message):
        sent.append(message)

    scope = {'type': 'http', 'method': 'POST',
             'path': '/api/v62/projects/private-project/training-materials/selection-summary',
             'headers': [(b'authorization', b'Bearer PRIVATE_TOKEN')]}
    middleware = PerformanceDiagnosticsMiddleware(app)

    monkeypatch.delenv('MC_PERFORMANCE_DIAGNOSTICS', raising=False)
    asyncio.run(middleware(scope, lambda: None, collect))
    assert sent[0]['headers'] == []
    assert not caplog.records

    sent.clear()
    monkeypatch.setenv('MC_PERFORMANCE_DIAGNOSTICS', '1')
    with caplog.at_level('INFO', logger='platform.performance'):
        asyncio.run(middleware(scope, lambda: None, collect))
    headers = dict(sent[0]['headers'])
    assert b'training.selection_summary;dur=' in headers[b'server-timing']
    trace = json.loads(caplog.records[-1].message)
    assert trace['endpoint'] == 'training.materials'
    assert trace['counts']['training.selection_summary.calls'] == 1
    assert trace['stages_ms']['training.selection_summary'] >= 0
    for secret in ('PRIVATE_TOKEN', 'PRIVATE_MATERIAL_IDENTIFIER', 'private-project'):
        assert secret not in caplog.records[-1].message


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
    assert fact['client_operation_id_sha256']==hashlib.sha256(b'client_12345678').hexdigest()
    assert 'client_12345678' not in caplog.records[-1].message
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


def test_diagnostics_measure_real_sql_execute_and_fetch_not_inferred_lock_wait(monkeypatch, caplog):
    monkeypatch.setenv('MC_PERFORMANCE_DIAGNOSTICS', '1')
    sent = []

    async def app(_scope, _receive, send):
        with observe_connection(connect_sqlite(':memory:')) as db:
            db.execute('CREATE TABLE example (value INTEGER)')
            db.execute('INSERT INTO example VALUES (1)')
            assert db.execute('SELECT value FROM example').fetchone()[0] == 1
        await send({'type':'http.response.start','status':200,'headers':[]})
        await send({'type':'http.response.body','body':b'{}'})

    scope = {'type':'http','method':'GET','path':'/api/training_options','headers':[]}
    async def collect(message): sent.append(message)
    with caplog.at_level('INFO',logger='platform.performance'):
        asyncio.run(PerformanceDiagnosticsMiddleware(app)(scope, lambda: None, collect))
    fact = json.loads(caplog.records[-1].message)
    assert fact['sql_cumulative_ms'] is not None and fact['sql_cumulative_ms'] > 0
    assert fact['counts']['repository_sql_statements'] >= 3
    assert fact['sqlite_lock_wait_ms'] is None
    assert 'sql.execute' in dict(sent[0]['headers'])[b'server-timing'].decode('ascii')
    assert 'example' not in caplog.records[-1].message


def test_external_http_metrics_include_auth_chain_without_sensitive_inputs(monkeypatch, caplog):
    from platform_core.external_algorithm_platform import ChangLianClient, ChangLianEndpoints

    monkeypatch.setenv('MC_PERFORMANCE_DIAGNOSTICS', '1')
    sent = []
    class FakeResponse:
        status_code = 200
        headers = {}
        def __init__(self, body): self.body = body
        def json(self): return self.body

    class FakeSession:
        def request(self, method, url, **kwargs):
            if url.endswith('/test-sign'):
                return FakeResponse({'code':200,'data':{'timestamp':'100','nonce':'abc','signature':'SECRET_SIGN'}})
            if url.endswith('/token'):
                return FakeResponse({'code':200,'data':{'accessToken':'SECRET_TOKEN','expiresIn':3600}})
            assert url.endswith('/category/tree')
            assert kwargs['headers']['Authorization'] == 'Bearer SECRET_TOKEN'
            return FakeResponse({'code':200,'data':[]})

    async def app(_scope, _receive, send):
        client = ChangLianClient(base_url='https://private.example', access_key='SECRET_KEY',
                                 access_secret='SECRET_PASSWORD', endpoints=ChangLianEndpoints(), session=FakeSession())
        assert client.category_tree()['data'] == []
        await send({'type':'http.response.start','status':200,'headers':[]})
        await send({'type':'http.response.body','body':b'{}'})

    scope = {'type':'http','method':'GET',
             'path':'/api/v63/external-algorithm-platform/provider/categories/tree','headers':[]}
    async def collect(message): sent.append(message)
    with caplog.at_level('INFO',logger='platform.performance'):
        asyncio.run(PerformanceDiagnosticsMiddleware(app)(scope, lambda: None, collect))
    fact = json.loads(caplog.records[-1].message)
    assert fact['endpoint'] == 'external.provider'
    assert fact['external_http_ms'] is not None and fact['external_http_ms'] > 0
    assert fact['counts']['external.http.auth.calls'] == 2
    assert fact['counts']['external.http.business.calls'] == 1
    assert fact['counts']['external.auth_wait.calls'] == 1
    assert fact['stages_ms']['external.auth_wait'] >= 0
    assert b'external.http.business;dur=' in dict(sent[0]['headers'])[b'server-timing']
    for secret in ('SECRET_KEY', 'SECRET_PASSWORD', 'SECRET_SIGN', 'SECRET_TOKEN', 'private.example'):
        assert secret not in caplog.records[-1].message


def test_file_read_time_is_measured_only_for_actual_cache_hash_io(tmp_path, monkeypatch, caplog):
    from platform_core.storage.cache import file_sha256

    monkeypatch.setenv('MC_PERFORMANCE_DIAGNOSTICS','1')
    material = tmp_path/'private-source-name.jpg'
    material.write_bytes(b'x'*8192)

    async def app(_scope, _receive, send):
        assert len(file_sha256(material)) == 64
        await send({'type':'http.response.start','status':200,'headers':[]})
        await send({'type':'http.response.body','body':b''})

    async def collect(_message): pass
    scope = {'type':'http','method':'GET','path':'/api/v61/projects/private/materials/private/content/thumbnail','headers':[]}
    # Thumb sampling remains 1/32. Deterministically take the sampled branch.
    monkeypatch.setattr('platform_core.performance_diagnostics.random.randrange', lambda _:0)
    with caplog.at_level('INFO',logger='platform.performance'):
        asyncio.run(PerformanceDiagnosticsMiddleware(app)(scope,lambda:None,collect))
    fact=json.loads(caplog.records[-1].message)
    assert fact['file_read_ms'] is not None and fact['file_read_ms'] > 0
    assert fact['counts']['sha256_bytes'] == 8192
    assert fact['counts']['file.read.calls'] >= 1
    assert 'private-source-name' not in caplog.records[-1].message


def test_disabled_diagnostics_keeps_native_sqlite_connection_and_response(monkeypatch):
    import sqlite3
    monkeypatch.delenv('MC_PERFORMANCE_DIAGNOSTICS',raising=False)
    db = connect_sqlite(':memory:')
    try:
        assert type(db) is sqlite3.Connection
    finally:
        db.close()
    sent=[]
    async def app(_scope,_receive,send):
        await send({'type':'http.response.start','status':200,'headers':[]})
        await send({'type':'http.response.body','body':b'unchanged'})
    async def collect(message):sent.append(message)
    asyncio.run(PerformanceDiagnosticsMiddleware(app)(
        {'type':'http','method':'GET','path':'/api/training_options','headers':[]},lambda:None,collect))
    assert sent == [{'type':'http.response.start','status':200,'headers':[]},
                    {'type':'http.response.body','body':b'unchanged'}]
