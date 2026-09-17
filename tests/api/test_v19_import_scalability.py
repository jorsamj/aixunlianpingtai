import io
import json
import zipfile

import app as app_module


def _project(client):
    response = client.post('/api/projects', json={'name': 'zip-10k', 'description': '', 'labels': []})
    response.raise_for_status()
    return response.json()['id']


def _ten_thousand_member_zip():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_STORED) as archive:
        for index in range(10_000):
            archive.writestr(f'images/train/image_{index:05d}.jpg', b'x')
        archive.writestr('data.yaml', 'train: images/train\nnames: [object]\n')
    return buffer.getvalue()


def test_v19_10k_scan_keeps_candidate_manifest_out_of_hot_job_state(client):
    project_id = _project(client)
    response = client.post(
        f'/api/v19/projects/{project_id}/datasets/default/import/jobs',
        files={'file': ('ten-thousand.zip', _ten_thousand_member_zip(), 'application/zip')},
    )
    response.raise_for_status()
    body = response.json()
    assert body['image_count'] == 10_000
    assert len(body['images']) == 500
    assert body['images_truncated'] is True

    job_id = body['id']
    job_path = app_module.v19_job_file(project_id, job_id)
    persisted = json.loads(job_path.read_text(encoding='utf-8'))
    assert 'images' not in persisted
    assert persisted['scan_images_ref'] == 'scan-images.json'
    assert job_path.stat().st_size < 64 * 1024

    manifest = json.loads(app_module.v19_scan_images_file(project_id, job_id).read_text(encoding='utf-8'))
    assert len(manifest) == 10_000

    detail = client.get(f'/api/v19/projects/{project_id}/import/jobs/{job_id}')
    detail.raise_for_status()
    assert 'images' not in detail.json()

    preview = client.get(
        f'/api/v19/projects/{project_id}/import/jobs/{job_id}',
        params={'include_images': 'true', 'image_limit': 25},
    )
    preview.raise_for_status()
    assert len(preview.json()['images']) == 25
    assert preview.json()['images_truncated'] is True

    listing = client.get(f'/api/v19/projects/{project_id}/import/jobs')
    listing.raise_for_status()
    row = next(item for item in listing.json()['items'] if item['id'] == job_id)
    assert len(row['images']) == 300
    assert row['images_truncated'] is True

    # Hundreds of hot progress writes stay bounded because they no longer rewrite the 10k manifest.
    for index in range(500):
        app_module.v19_update_job(project_id, job_id, status='running', progress=index / 5, processed=index * 20)
    persisted = json.loads(job_path.read_text(encoding='utf-8'))
    assert 'images' not in persisted
    assert job_path.stat().st_size < 64 * 1024
    listing = client.get(f'/api/v19/projects/{project_id}/import/jobs')
    row = next(item for item in listing.json()['items'] if item['id'] == job_id)
    assert 'images' not in row
