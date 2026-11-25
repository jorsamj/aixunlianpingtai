"""Multipart ZIP upload controls must align UI actions and durable server truth."""
from platform_core.material_ingestion_service import MaterialIngestionService

import io
import threading
import time
import zipfile


def _project(client):
    response = client.post('/api/projects', json={
        'name': 'multipart-controls', 'description': '', 'labels': [],
    })
    response.raise_for_status()
    return response.json()['id']


def _create(client, project_id, **overrides):
    payload = {'file_name': 'sample.zip', 'file_size': 8 * 1024 * 1024 + 1,
               'part_size': 8 * 1024 * 1024, 'fingerprint': 'fingerprint-v2'}
    payload.update(overrides)
    return client.post(f'/api/v19/projects/{project_id}/datasets/default/import/uploads', json=payload)


def _selecting_job(client, project_id, name):
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_STORED) as bundle:
        bundle.writestr(f'images/{name}.jpg', b'scan-only-image')
    return client.post(
        f'/api/v19/projects/{project_id}/datasets/default/import/jobs',
        files={'file': (f'{name}.zip', archive.getvalue(), 'application/zip')},
    )


def test_pause_resume_cancel_preserves_only_intended_zip_session(client):
    project_id = _project(client)
    response = _create(client, project_id)
    response.raise_for_status()
    upload_id = response.json()['upload_id']
    prefix = f'/api/v19/projects/{project_id}/import/uploads/{upload_id}'

    uploaded = client.put(prefix + '/parts/0', content=b'x' * (8 * 1024 * 1024))
    assert uploaded.status_code == 200
    pause = client.post(prefix + '/pause')
    assert pause.status_code == 200
    assert pause.json()['status'] == 'paused'
    assert pause.json()['completed_parts'] == [0]
    assert client.put(prefix + '/parts/1', content=b'z').status_code == 422
    assert client.post(prefix + '/complete').status_code == 409

    # Wrong identity cannot silently create a second business task.
    mismatch = _create(client, project_id, fingerprint='other', resume_upload_id=upload_id)
    assert mismatch.status_code == 409
    resumed = _create(client, project_id, resume_upload_id=upload_id)
    assert resumed.status_code == 200
    assert resumed.json()['upload_id'] == upload_id
    assert resumed.json()['completed_parts'] == [0]
    assert resumed.json()['status'] == 'uploading'

    cancel = client.post(prefix + '/cancel')
    assert cancel.status_code == 200
    assert cancel.json()['status'] == 'cancelled'
    assert cancel.json()['completed_parts'] == []
    assert cancel.json()['received_bytes'] == 0
    assert client.post(prefix + '/cancel').status_code == 200
    assert client.post(prefix + '/complete').status_code == 409

    import app as app_module
    assert app_module.v19_read_job(project_id, upload_id)['status'] == 'cancelled'
    parts = app_module.project_dir(project_id) / 'import_uploads' / upload_id / 'parts'
    assert not list(parts.glob('*.part'))


def test_legacy_upload_cancel_preserves_nonterminal_server_truth(client, monkeypatch):
    project_id = _project(client)
    import app as app_module

    monkeypatch.setattr(MaterialIngestionService, '_v19_cancel_import_job', staticmethod(lambda *_args, **_kwargs: {
        'id': 'racing-upload', 'status': 'merging', 'phase': 'MERGE',
        'cancel_requested': True, 'cleanup_status': 'pending',
    }))
    response = client.post(
        f'/api/v19/projects/{project_id}/import/uploads/racing-upload/cancel',
    )
    assert response.status_code == 200
    body = response.json()
    assert body['status'] == 'merging'
    assert body['cancel_requested'] is True
    assert body['cleanup_status'] == 'pending'
    assert 'completed_parts' not in body


def test_unified_cancel_is_idempotent_and_cleans_only_selected_uncommitted_job(client):
    project_id = _project(client)
    first = _selecting_job(client, project_id, 'first')
    second = _selecting_job(client, project_id, 'second')
    first.raise_for_status()
    second.raise_for_status()
    first_id = first.json()['id']
    second_id = second.json()['id']

    import app as app_module
    first_dir = app_module.v19_job_dir(project_id, first_id)
    second_dir = app_module.v19_job_dir(project_id, second_id)
    formal_sentinel = first_dir / 'formal-material.keep'
    formal_sentinel.write_text('not owned by the ZIP scratch cleanup', encoding='utf-8')
    assert (first_dir / 'source.zip').is_file()
    assert (second_dir / 'source.zip').is_file()

    endpoint = f'/api/v19/projects/{project_id}/import/jobs/{first_id}/cancel'
    cancelled = client.post(endpoint)
    assert cancelled.status_code == 200
    assert cancelled.json()['status'] == 'cancelled'
    assert cancelled.json()['cleanup_status'] == 'complete'
    assert (first_dir / 'job.json').is_file()
    assert not (first_dir / 'source.zip').exists()
    assert not (first_dir / 'scan-images.json').exists()
    assert not (first_dir / 'scan-class-samples.json').exists()
    assert formal_sentinel.read_text(encoding='utf-8') == 'not owned by the ZIP scratch cleanup'

    # A sibling task is outside the cancellation ownership boundary.
    assert (second_dir / 'source.zip').is_file()
    assert (second_dir / 'scan-images.json').is_file()

    repeated = client.post(endpoint)
    assert repeated.status_code == 200
    assert repeated.json()['status'] == 'cancelled'
    assert repeated.json()['cleanup_status'] == 'complete'


def test_cancel_cleanup_failure_is_reported_and_same_endpoint_retries(client, monkeypatch):
    project_id = _project(client)
    response = _selecting_job(client, project_id, 'cleanup-retry')
    response.raise_for_status()
    job_id = response.json()['id']

    import app as app_module
    original_cleanup = app_module._v19_cleanup_uncommitted_job
    attempts = 0

    def fail_once(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError('simulated cleanup lock')
        return original_cleanup(*args, **kwargs)

    monkeypatch.setattr(app_module, '_v19_cleanup_uncommitted_job', fail_once)
    endpoint = f'/api/v19/projects/{project_id}/import/jobs/{job_id}/cancel'

    failed = client.post(endpoint)
    assert failed.status_code == 200
    assert failed.json()['status'] == 'failed'
    assert failed.json()['cleanup_status'] == 'failed'
    assert 'simulated cleanup lock' in failed.json()['cleanup_error']
    assert (app_module.v19_job_dir(project_id, job_id) / 'source.zip').is_file()

    retried = client.post(endpoint)
    assert retried.status_code == 200
    assert retried.json()['status'] == 'cancelled'
    assert retried.json()['cleanup_status'] == 'complete'
    assert retried.json()['cleanup_error'] == ''
    assert not (app_module.v19_job_dir(project_id, job_id) / 'source.zip').exists()


def test_unified_cancel_rejects_commit_fence_and_completed_imports(client):
    project_id = _project(client)
    response = _selecting_job(client, project_id, 'commit-fence')
    response.raise_for_status()
    job_id = response.json()['id']

    import app as app_module
    job = app_module.v19_read_job(project_id, job_id)
    job.update(status='running', phase='DB_COMMIT')
    app_module.v19_write_job(project_id, job)

    rejected = client.post(f'/api/v19/projects/{project_id}/import/jobs/{job_id}/cancel')
    assert rejected.status_code == 409
    assert not app_module.v19_read_job(project_id, job_id).get('cancel_requested')

    job = app_module.v19_read_job(project_id, job_id)
    job.update(status='done', phase='DONE')
    app_module.v19_write_job(project_id, job)
    completed = client.post(f'/api/v19/projects/{project_id}/import/jobs/{job_id}/cancel')
    assert completed.status_code == 409


def test_start_and_cancel_are_serialized_by_the_same_job_fence(client, monkeypatch):
    project_id = _project(client)
    label = client.post(f'/api/projects/{project_id}/labels', json={'label': 'object'})
    assert label.status_code == 200
    response = _selecting_job(client, project_id, 'start-cancel-fence')
    response.raise_for_status()
    job_id = response.json()['id']

    import app as app_module
    entered_start = threading.Event()
    release_start = threading.Event()
    release_worker = threading.Event()
    original_start = app_module._material_ingestion_service()._v19_start_import_job_locked

    def blocking_start(*args, **kwargs):
        entered_start.set()
        assert release_start.wait(5)
        return original_start(*args, **kwargs)

    def parked_worker(*_args, **_kwargs):
        release_worker.wait(5)

    monkeypatch.setattr(MaterialIngestionService, '_v19_start_import_job_locked', staticmethod(blocking_start))
    monkeypatch.setattr(app_module, 'v19_import_worker', parked_worker)

    start_result = {}
    cancel_result = {}
    start_thread = threading.Thread(target=lambda: start_result.setdefault(
        'response', client.post(
            f'/api/v19/projects/{project_id}/import/jobs/{job_id}/start',
            json={'sample_type': 'positive', 'intended_label_codes': ['object']},
        ),
    ))
    cancel_thread = threading.Thread(target=lambda: cancel_result.setdefault(
        'response', client.post(
            f'/api/v19/projects/{project_id}/import/jobs/{job_id}/cancel',
        ),
    ))
    start_thread.start()
    assert entered_start.wait(5)
    cancel_thread.start()
    time.sleep(0.1)
    assert cancel_thread.is_alive(), 'cancel must wait while start owns the stop fence'

    release_start.set()
    start_thread.join(5)
    cancel_thread.join(5)
    release_worker.set()

    assert start_result['response'].status_code == 200
    assert cancel_result['response'].status_code == 200
    durable = app_module.v19_read_job(project_id, job_id)
    assert durable['status'] == 'running'
    assert durable['phase'] == 'QUEUE'
    assert durable['cancel_requested'] is True


def test_durable_cancel_intent_blocks_a_late_start(client):
    project_id = _project(client)
    response = _selecting_job(client, project_id, 'cancel-before-start')
    response.raise_for_status()
    job_id = response.json()['id']

    import app as app_module
    job = app_module.v19_read_job(project_id, job_id)
    job['cancel_requested'] = True
    app_module.v19_write_job(project_id, job)

    rejected = client.post(
        f'/api/v19/projects/{project_id}/import/jobs/{job_id}/start', json={},
    )
    assert rejected.status_code == 409
    durable = app_module.v19_read_job(project_id, job_id)
    assert durable['status'] == 'selecting'
    assert durable['cancel_requested'] is True


def test_late_multipart_finalizer_cannot_overwrite_cancelled_terminal_state(client):
    project_id = _project(client)
    response = _selecting_job(client, project_id, 'late-finalizer')
    response.raise_for_status()
    job_id = response.json()['id']

    cancelled = client.post(f'/api/v19/projects/{project_id}/import/jobs/{job_id}/cancel')
    assert cancelled.status_code == 200
    assert cancelled.json()['status'] == 'cancelled'

    import app as app_module
    app_module._v19_finalize_multipart_upload(project_id, job_id)
    durable = app_module.v19_read_job(project_id, job_id)
    assert durable['status'] == 'cancelled'
    assert durable['phase'] == 'CANCELLED'
    assert durable['cleanup_status'] == 'complete'


def test_remaining_material_ingestion_effective_http_contract():
    import re
    import app as application
    from types import SimpleNamespace
    try:
        from fastapi.routing import iter_route_contexts
        contexts = list(iter_route_contexts(application.app.routes))
    except ImportError:
        contexts = [SimpleNamespace(path=r.path, original_route=r) for r in application.app.routes if hasattr(r, "path")]
    expected = [
        ('get', '/api/v61/projects/{project_id}/storage-sources/{source_id}/rescans/preflight', 'storage_rescan_preflight', None, 'storage_ingestion'),
        ('post', '/api/v61/projects/{project_id}/storage-sources/{source_id}/rescans', 'create_storage_rescan', None, 'storage_ingestion'),
        ('get', '/api/v61/projects/{project_id}/storage-rescans/{task_id}', 'get_storage_rescan', None, 'storage_ingestion'),
        ('post', '/api/v61/projects/{project_id}/storage-rescans/{task_id}/confirm', 'confirm_storage_rescan', 'StorageRescanConfirmReq', 'storage_ingestion'),
        ('post', '/api/v61/projects/{project_id}/storage-rescans/{task_id}/cancel', 'cancel_storage_rescan', None, 'storage_ingestion'),
        ('post', '/api/v61/projects/{project_id}/storage-imports/scan', 'create_storage_import_scan', 'StorageImportScanReq', 'storage_ingestion'),
        ('get', '/api/v61/projects/{project_id}/storage-imports/{task_id}', 'get_storage_import_scan', None, 'storage_ingestion'),
        ('post', '/api/v61/projects/{project_id}/storage-imports/{task_id}/confirm', 'confirm_storage_import', 'StorageImportConfirmReq', 'storage_ingestion'),
        ('get', '/api/v61/projects/{project_id}/label-review/{task_id}/classes/{class_id}/samples', 'label_review_samples_v61', None, 'storage_ingestion'),
        ('get', '/api/v61/projects/{project_id}/label-review/{task_id}/classes/{class_id}/sample-content', 'label_review_sample_content_v61', None, 'storage_ingestion'),
        ('post', '/api/projects/{project_id}/images', 'upload_images', None, 'material_ingestion'),
        ('get', '/api/v19/projects/{project_id}/import/jobs/{job_id}/unannotated', 'v19_unannotated_import_page', None, 'material_ingestion'),
        ('get', '/api/v19/projects/{project_id}/import/jobs/{job_id}/folders', 'v19_import_folders', None, 'material_ingestion'),
        ('post', '/api/v19/projects/{project_id}/import/jobs/{job_id}/retry-folder-classification', 'v19_retry_folder_classification', None, 'material_ingestion'),
        ('post', '/api/v19/projects/{project_id}/datasets/{dataset_id}/import/uploads', 'v19_create_multipart_upload', 'V19MultipartUploadReq', 'material_ingestion'),
        ('put', '/api/v19/projects/{project_id}/import/uploads/{upload_id}/parts/{part_number}', 'v19_upload_multipart_part', None, 'material_ingestion'),
        ('post', '/api/v19/projects/{project_id}/import/uploads/{upload_id}/pause', 'v19_pause_multipart_upload', None, 'material_ingestion'),
        ('post', '/api/v19/projects/{project_id}/import/uploads/{upload_id}/cancel', 'v19_cancel_multipart_upload', None, 'material_ingestion'),
        ('post', '/api/v19/projects/{project_id}/import/uploads/{upload_id}/complete', 'v19_complete_multipart_upload', None, 'material_ingestion'),
        ('post', '/api/v19/projects/{project_id}/datasets/{dataset_id}/import/jobs', 'v19_create_import_job', None, 'material_ingestion'),
        ('post', '/api/v19/projects/{project_id}/import/jobs/{job_id}/cancel', 'v19_cancel_import_job', None, 'material_ingestion'),
        ('post', '/api/v19/projects/{project_id}/import/jobs/{job_id}/stop', 'v19_stop_import_job', None, 'material_ingestion'),
        ('post', '/api/v19/projects/{project_id}/import/jobs/{job_id}/start', 'v19_start_import_job', 'V19ImportStartReq', 'material_ingestion'),
        ('get', '/api/v19/projects/{project_id}/import/jobs/{job_id}/classes/{class_id}/samples', 'v19_label_samples', None, 'material_ingestion'),
        ('get', '/api/v19/projects/{project_id}/import/jobs/{job_id}/classes/{class_id}/sample-content', 'v19_label_sample_content', None, 'material_ingestion'),
        ('get', '/api/v19/projects/{project_id}/import/jobs', 'v19_list_import_jobs', None, 'material_ingestion'),
        ('get', '/api/v19/projects/{project_id}/import/jobs/{job_id}', 'v19_get_import_job', None, 'material_ingestion'),
        ('delete', '/api/v19/projects/{project_id}/import/jobs', 'v19_clear_terminal_import_jobs', None, 'material_ingestion'),
        ('delete', '/api/v19/projects/{project_id}/import/jobs/{job_id}', 'v19_delete_import_job', None, 'material_ingestion'),
        ('get', '/api/v33/projects/{project_id}/video-tasks', 'v33_list_video_tasks', None, 'video_tasks'),
        ('get', '/api/v33/projects/{project_id}/video-tasks/{task_id}', 'v33_get_video_task', None, 'video_tasks'),
        ('post', '/api/v33/projects/{project_id}/video-tasks/{task_id}/stop', 'v33_stop_video_task', None, 'video_tasks'),
        ('post', '/api/v33/projects/{project_id}/video-tasks', 'v33_create_video_task', None, 'video_tasks'),
        ('post', '/api/v36/projects/{project_id}/datasets/{dataset_id}/source-import/scan', 'v36_scan_source_import', 'V36SourceImportScanReq', 'material_ingestion'),
        ('get', '/api/v36/projects/{project_id}/datasets/{dataset_id}/source-import/jobs', 'v36_list_source_import_jobs', None, 'material_ingestion'),
        ('post', '/api/v36/projects/{project_id}/datasets/{dataset_id}/source-import/jobs', 'v36_start_source_import_job', 'V36SourceImportStartReq', 'material_ingestion'),
        ('get', '/api/v55/projects/{project_id}/upload-batches/{batch_id}', 'v55_get_upload_batch', None, 'material_ingestion'),
        ('post', '/api/v55/projects/{project_id}/upload-batches/{batch_id}/decisions', 'v55_apply_upload_batch_decisions', 'V55UploadDecisionsReq', 'material_ingestion'),
        ('get', '/api/v64/projects/{project_id}/detection-batches', 'list_detection_batches', None, 'detection_batches'),
        ('get', '/api/v64/projects/{project_id}/detection-batches/{batch_id}', 'get_detection_batch', None, 'detection_batches'),
        ('post', '/api/v64/projects/{project_id}/detection-batches/{batch_id}/items/{item_index}/review', 'review_detection_batch_item', 'DetectionBatchReviewReq', 'detection_batches'),
        ('get', '/api/v52/projects/{project_id}/import/jobs/{job_id}/review', 'v52_import_review', None, 'material_ingestion'),
    ]
    schema = application.app.openapi()
    for method, path, name, payload, owner in expected:
        operation = schema["paths"][path][method]
        assert operation["operationId"] == re.sub(r"\W", "_", name + path) + "_" + method
        matches = [c.original_route for c in contexts if c.path == path and method.upper() in getattr(c.original_route, "methods", set())]
        assert len(matches) == 1
        assert matches[0].endpoint.__module__ == "platform_core." + owner + "_api"
        if payload:
            assert operation["requestBody"]["content"]["application/json"]["schema"]["$ref"] == "#/components/schemas/" + payload
