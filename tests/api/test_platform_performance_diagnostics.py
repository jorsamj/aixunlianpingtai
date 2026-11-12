import json
import logging
import re


def test_training_creation_and_freeze_diagnostics_use_existing_opt_in_route_owner():
    from platform_core.performance_diagnostics import _endpoint

    assert _endpoint('/api/system/recommendation') == 'training.recommendation'
    assert _endpoint('/api/training_options') == 'training.options'
    assert _endpoint('/api/projects/p1/jobs') == 'training.jobs'
    for name in ('bulk-selection', 'selection-reference', 'selection-membership'):
        assert _endpoint(f'/api/v62/projects/p1/training-materials/{name}') == 'training.materials'
    assert _endpoint('/api/v62/projects/p1/training-materials/unknown') is None


def test_training_create_diagnostics_is_opt_in_and_never_logs_request_body(monkeypatch, caplog):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from platform_core.performance_diagnostics import (
        _endpoint, measure, PerformanceDiagnosticsMiddleware,
    )

    assert _endpoint('/api/v12/projects/synthetic/train/start') == 'training.create'
    assert _endpoint('/api/v12/projects/synthetic/train/start/extra') is None
    monkeypatch.setenv('MC_PERFORMANCE_DIAGNOSTICS', '1')
    app = FastAPI()
    app.add_middleware(PerformanceDiagnosticsMiddleware)

    @app.post('/api/v12/projects/{project_id}/train/start')
    def create(project_id: str, payload: dict):
        with measure('training.create.source_admission'):
            assert payload['task_id'] == 'train_' + 'c' * 24
        return {'ok': True}

    with caplog.at_level(logging.INFO, logger='platform.performance'):
        with TestClient(app) as client:
            response = client.post('/api/v12/projects/synthetic/train/start', json={
                'task_id': 'train_' + 'c' * 24, 'api_key': 'secret-not-for-logs',
            })
    assert response.status_code == 200
    assert 'training.create.source_admission;dur=' in response.headers['Server-Timing']
    record = next(json.loads(row.message) for row in caplog.records
                  if row.name == 'platform.performance')
    assert record['endpoint'] == 'training.create'
    assert 'secret-not-for-logs' not in json.dumps(record)


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


def test_training_picker_thumbnail_diagnostics_measure_cold_build_and_warm_hit(tmp_path, monkeypatch, caplog):
    """The actual picker thumbnail GET must expose opt-in, sampled phase evidence."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from PIL import Image
    from platform_core.material_repository import MaterialRepository
    from platform_core.training_material_picker_api import training_material_picker_router
    import platform_core.performance_diagnostics as diagnostics

    data_dir = tmp_path / 'data'
    project_dir = data_dir / 'projects' / 'audit'
    source = project_dir / 'uploads' / 'synthetic.png'
    source.parent.mkdir(parents=True)
    Image.new('RGB', (400, 250), '#337799').save(source)
    repo = MaterialRepository(project_dir)
    repo.upsert({
        'id': 'synthetic-image', 'filename': 'synthetic.png',
        'storage_source_id': 'default_local', 'storage_type': 'local',
        'object_key': 'uploads/synthetic.png', 'content_sha256': '',
        'size_bytes': 0, 'processing_status': 'processed',
    })
    revision = repo.current_revision()
    monkeypatch.setenv('MC_PERFORMANCE_DIAGNOSTICS', '1')
    monkeypatch.setattr(diagnostics.random, 'randrange', lambda bound: 0)
    app = FastAPI()
    app.add_middleware(diagnostics.PerformanceDiagnosticsMiddleware)
    app.include_router(training_material_picker_router(
        lambda project_id: {'id': project_id} if project_id == 'audit' else None,
        lambda: data_dir,
    ))
    path = '/api/v62/projects/audit/training-materials/synthetic-image/thumbnail?size=192'
    with caplog.at_level(logging.INFO, logger='platform.performance'):
        with TestClient(app) as client:
            cold = client.get(path)
            warm = client.get(path)
            not_a_get = client.post(path)
            not_a_thumbnail = client.get(path.replace('/thumbnail?', '/thumbnail/extra?'))
            monkeypatch.setattr(diagnostics.random, 'randrange', lambda bound: bound - 1)
            non_sampled = client.get(path)
            monkeypatch.delenv('MC_PERFORMANCE_DIAGNOSTICS')
            diagnostics_off = client.get(path)

    assert cold.status_code == warm.status_code == 200
    assert cold.content == warm.content
    assert re.fullmatch(r'[0-9a-f]{32}', cold.headers.get('X-Request-ID', ''))
    assert re.fullmatch(r'[0-9a-f]{32}', warm.headers.get('X-Request-ID', ''))
    assert 'thumbnail.lock_wait;dur=' in cold.headers['Server-Timing']
    assert 'thumbnail.materialize;dur=' in cold.headers['Server-Timing']
    assert 'thumbnail.render;dur=' in cold.headers['Server-Timing']
    assert 'thumbnail.materialize;dur=' not in warm.headers['Server-Timing']
    assert not_a_get.status_code == 405 and not_a_get.headers.get('X-Request-ID') is None
    assert not_a_thumbnail.status_code == 404 and not_a_thumbnail.headers.get('X-Request-ID') is None
    assert non_sampled.status_code == diagnostics_off.status_code == 200
    assert non_sampled.headers.get('X-Request-ID') is None
    assert diagnostics_off.headers.get('X-Request-ID') is None
    assert repo.current_revision() == revision
    records = [json.loads(row.message) for row in caplog.records if row.name == 'platform.performance']
    assert len(records) == 2
    assert [record['endpoint'] for record in records] == ['training.thumbnail', 'training.thumbnail']
    assert records[0]['counts']['thumbnail.cache_miss'] == 1
    assert records[1]['counts']['thumbnail.cache_hit'] == 1
    assert all('synthetic-image' not in json.dumps(record) and 'audit' not in json.dumps(record) for record in records)


def test_training_picker_thumbnail_lock_wait_is_measured_under_synthetic_contention(tmp_path, monkeypatch):
    """Four actual concurrent HTTP callers share one thumbnail; artificial delay is not production timing."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, Lock
    from time import sleep
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from PIL import Image
    from platform_core.material_repository import MaterialRepository
    from platform_core.training_material_picker_api import training_material_picker_router
    from platform_core.storage.manager import StorageManager
    import platform_core.performance_diagnostics as diagnostics

    root = tmp_path / 'data'
    project = root / 'projects' / 'audit'
    image = project / 'uploads' / 'synthetic.png'
    image.parent.mkdir(parents=True)
    Image.new('RGB', (400, 250), '#8899bb').save(image)
    repo = MaterialRepository(project)
    repo.upsert({
        'id': 'synthetic', 'filename': 'synthetic.png',
        'storage_source_id': 'default_local', 'storage_type': 'local',
        'object_key': 'uploads/synthetic.png', 'content_sha256': '',
        'size_bytes': 0, 'processing_status': 'processed',
    })
    barrier = Barrier(4)
    original_get = MaterialRepository.get
    original_materialize = StorageManager.materialize
    counter_lock = Lock()
    calls = [0]

    def aligned_get(self, image_id):
        row = original_get(self, image_id)
        if image_id == 'synthetic':
            barrier.wait(timeout=5)
        return row

    def delayed_materialize(self, row, *, read_only=False):
        assert read_only is True
        with counter_lock:
            calls[0] += 1
        sleep(0.25)  # Synthetic remote-source latency, never an observed OSS value.
        return original_materialize(self, row, read_only=read_only)

    monkeypatch.setattr(MaterialRepository, 'get', aligned_get)
    monkeypatch.setattr(StorageManager, 'materialize', delayed_materialize)
    monkeypatch.setenv('MC_PERFORMANCE_DIAGNOSTICS', '1')
    monkeypatch.setattr(diagnostics.random, 'randrange', lambda bound: 0)
    app = FastAPI()
    app.add_middleware(diagnostics.PerformanceDiagnosticsMiddleware)
    app.include_router(training_material_picker_router(
        lambda project_id: {'id': project_id} if project_id == 'audit' else None,
        lambda: root,
    ))
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(client.get, '/api/v62/projects/audit/training-materials/synthetic/thumbnail') for _ in range(4)]
        responses = [future.result(timeout=10) for future in futures]
    assert all(response.status_code == 200 for response in responses)
    assert len({response.content for response in responses}) == 1
    assert calls == [1], 'only one request may materialize the shared source'
    waits = [
        float(match.group(1))
        for response in responses
        if (match := re.search(r'thumbnail.lock_wait;dur=([0-9.]+)', response.headers['Server-Timing']))
    ]
    assert len(waits) >= 2, 'contenders must observe time spent waiting for the same real file lock'
    assert max(waits) > 50, 'the deliberately delayed build must be visible as a measured lock wait'


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
