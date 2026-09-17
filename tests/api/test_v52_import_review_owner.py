import uuid

import app as app_module


def test_v52_import_review_reads_materials_from_repository_not_route_response(client):
    project = client.post(
        '/api/projects',
        json={'name': f'v52-review-owner-{uuid.uuid4().hex[:8]}', 'description': '', 'labels': []},
    )
    project.raise_for_status()
    project_id = project.json()['id']
    job_id = uuid.uuid4().hex[:10]
    image_ids = ['historical-image-1', 'historical-image-2']
    app_module.v19_write_job(
        project_id,
        {
            'id': job_id,
            'project_id': project_id,
            'dataset_id': 'default',
            'file_name': 'historical.zip',
            'status': 'done',
            'stage': '导入完成',
            'progress': 100,
            'report': {
                'detected_format': 'YOLO',
                'imported_images': len(image_ids),
                'imported_image_ids': image_ids,
                'label_box_counts': {},
            },
        },
    )

    response = client.get(f'/api/v52/projects/{project_id}/import/jobs/{job_id}/review')
    response.raise_for_status()
    body = response.json()
    assert body['image_ids'] == image_ids
    assert body['images'] == []
    assert body['job']['status'] == 'done'
