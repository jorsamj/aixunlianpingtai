import json
import uuid

import app as app_module


def test_v19_terminal_report_externalizes_imported_image_ids_without_breaking_review(client):
    project = client.post(
        '/api/projects',
        json={'name': f'report-externalization-{uuid.uuid4().hex[:8]}', 'description': '', 'labels': []},
    )
    project.raise_for_status()
    project_id = project.json()['id']
    job_id = uuid.uuid4().hex[:10]
    image_ids = [f'image-{index:05d}' for index in range(10_000)]
    report = {
        'ok': True,
        'batch_id': job_id,
        'file_name': 'ten-thousand-yolo.zip',
        'detected_format': 'YOLO',
        'imported_images': 10_000,
        'annotated_images': 10_000,
        'boxes': 10_000,
        'missing_images': 0,
        'skipped_images': 0,
        'invalid_boxes': 0,
        'skipped_labels': 0,
        'unmatched_labels': 0,
        'labels': [],
        'warnings': [],
        'imported_image_ids': image_ids,
        'label_box_counts': {'object': 10_000},
    }
    app_module.v19_write_job(
        project_id,
        {
            'id': job_id,
            'project_id': project_id,
            'dataset_id': 'default',
            'file_name': 'ten-thousand-yolo.zip',
            'status': 'done',
            'stage': '导入完成',
            'progress': 100,
            'report': report,
        },
    )

    job_path = app_module.v19_job_file(project_id, job_id)
    persisted = json.loads(job_path.read_text(encoding='utf-8'))
    assert job_path.stat().st_size < 64 * 1024
    assert persisted['report_ref'] == 'report.json'
    assert 'imported_image_ids' not in persisted['report']
    report_path = app_module.v19_report_file(project_id, job_id)
    assert report_path.is_file()
    durable_report = json.loads(report_path.read_text(encoding='utf-8'))
    assert durable_report['imported_image_ids'] == image_ids

    review_response = client.get(f'/api/v52/projects/{project_id}/import/jobs/{job_id}/review')
    review_response.raise_for_status()
    review = review_response.json()
    assert review['image_ids'] == image_ids
    assert review['report']['imported_image_ids'] == image_ids
    assert review['job']['status'] == 'done'
