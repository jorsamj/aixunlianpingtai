"""Multipart ZIP upload controls must align UI actions and durable server truth."""


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
