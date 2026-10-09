"""Regression contracts for bounded ZIP annotation commit and unsafe retry fencing."""
import io
from pathlib import Path

from PIL import Image
import pytest

from platform_core.annotation_repository import AnnotationRepository


def _project(client):
    response = client.post('/api/projects', json={
        'name': 'bounded-zip-import', 'description': '', 'labels': ['target'],
    })
    response.raise_for_status()
    return response.json()['id']


def _source(tmp_path):
    file_path = tmp_path / 'image.png'
    Image.new('RGB', (24, 24), 'white').save(file_path)
    return file_path


@pytest.mark.parametrize('image_count', [501, 3042])
def test_formal_annotation_import_keeps_canonical_500_admission_limit(client, tmp_path, image_count):
    import app as app_module

    project_id = _project(client)
    app_module.ensure_default_datasets(project_id)
    source = _source(tmp_path)
    app_module._v50_begin_image_batch(project_id)
    ids = []
    try:
        for index in range(image_count):
            record = app_module.add_image_record(
                project_id, source, f'bounded_{index:04d}.png',
                'imported_yolo', 'default',
                annotation_builder=lambda _row: [{
                    'id': 'box-1', 'class_id': 0, 'label': 'target',
                    'x1': 2.0, 'y1': 2.0, 'x2': 18.0, 'y2': 18.0,
                }],
            )
            ids.append(record['id'])
        committed = app_module._v50_end_image_batch(save=True)
    finally:
        if app_module._v50_active_image_batch(project_id):
            app_module._v50_end_image_batch(save=False)

    assert len(committed) == image_count
    repository = AnnotationRepository(app_module.project_dir(project_id))
    for offset in range(0, len(ids), 500):
        annotations = repository.get_many(ids[offset:offset + 500])
        assert len(annotations) == len(ids[offset:offset + 500])
        assert all(row['annotation_state'] == 'annotated' and row['version'] >= 1 for row in annotations.values())
    for offset in range(0, len(ids), 500):
        material_chunk = app_module.material_store(project_id).get_many(ids[offset:offset + 500])
        assert len(material_chunk) == len(ids[offset:offset + 500])


def test_failed_zip_with_indexed_material_cannot_restart_import(client, tmp_path):
    import app as app_module

    project_id = _project(client)
    app_module.ensure_default_datasets(project_id)
    source = _source(tmp_path)
    record = app_module.add_image_record(project_id, source, 'existing.png', 'raw', 'default')
    job_id = 'partial_import_retry_guard'
    app_module.v19_write_job(project_id, {
        'id': job_id, 'project_id': project_id, 'dataset_id': 'default',
        'status': 'failed', 'phase': 'FAILED', 'stage': '导入失败',
        'report': {'imported_image_ids': [record['id']], 'imported_images': 1},
    })
    response = client.post(f'/api/v19/projects/{project_id}/import/jobs/{job_id}/start', json={})
    assert response.status_code == 409
    assert '禁止重复导入' in response.text
    assert app_module.v19_read_job(project_id, job_id)['status'] == 'failed'
    assert app_module.material_store(project_id).get(record['id']) is not None
