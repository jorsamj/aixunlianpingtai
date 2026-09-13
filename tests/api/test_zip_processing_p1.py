import io
from pathlib import Path

from PIL import Image

import app as app_module
from platform_core.annotation_repository import AnnotationRepository
from platform_core.material_repository import MaterialRepository


def _box(label='fire', class_id=0):
    return {'id': 'b1', 'class_id': class_id, 'label': label, 'x1': 10.0, 'y1': 10.0, 'x2': 80.0, 'y2': 80.0}


def test_direct_annotation_repository_keeps_default_material_projection(seeded_project):
    project_id, image = seeded_project
    AnnotationRepository(app_module.project_dir(project_id)).upsert(image['id'], [_box()])
    material = app_module.material_store(project_id).get(image['id'])
    assert material['annotation_state'] == 'annotated'
    assert material['annotated'] is True
    assert material['box_count'] == 1
    assert material['labels'] == ['fire']
    assert material['annotation_hash']


def test_app_write_annotation_projects_material_once(monkeypatch, seeded_project):
    project_id, image = seeded_project
    calls = 0
    original = MaterialRepository.patch

    def counted(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        return original(self, *args, **kwargs)

    monkeypatch.setattr(MaterialRepository, 'patch', counted)
    app_module.write_annotation(project_id, image['id'], [_box()])
    assert calls == 1
    material = app_module.material_store(project_id).get(image['id'])
    assert material['annotation_state'] == 'annotated'
    assert material['annotation_status'] == 'annotated'
    assert material['annotation_scope'] == ['fire']
    assert material['annotation_hash']
    assert material['box_count'] == 1
    assert material['labels'] == ['fire']
    assert material['annotation_preview'][0]['label'] == 'fire'


def test_v50_batch_annotation_queues_projection_without_material_patch(monkeypatch, seeded_project):
    project_id, image = seeded_project
    calls = 0
    original = MaterialRepository.patch

    def counted(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        return original(self, *args, **kwargs)

    monkeypatch.setattr(MaterialRepository, 'patch', counted)
    app_module._v50_begin_image_batch(project_id)
    try:
        app_module.write_annotation(project_id, image['id'], [_box()])
        assert calls == 0
    finally:
        app_module._v50_end_image_batch(save=False)


def _jpeg(path: Path):
    buf = io.BytesIO()
    Image.new('RGB', (32, 32), 'white').save(buf, format='JPEG')
    path.write_bytes(buf.getvalue())


def test_yolo_batch_processing_bounds_project_reads_and_material_patches(monkeypatch, client):
    project = client.post('/api/projects', json={'name': 'processing-p1', 'labels': []}).json()
    project_id = project['id']
    app_module.ensure_default_datasets(project_id)
    root = app_module.project_dir(project_id) / 'processing-p1-source'
    images = root / 'images' / 'train'
    labels = root / 'labels' / 'train'
    images.mkdir(parents=True, exist_ok=True)
    labels.mkdir(parents=True, exist_ok=True)
    for index in range(100):
        stem = f'image_{index:04d}'
        _jpeg(images / f'{stem}.jpg')
        (labels / f'{stem}.txt').write_text('0 0.5 0.5 0.5 0.5\n', encoding='utf-8')
    (root / 'data.yaml').write_text('train: images/train\nnames: [object]\n', encoding='utf-8')

    get_project_calls = 0
    material_patch_calls = 0
    annotation_upserts = 0
    original_get_project = app_module.get_project
    original_patch = MaterialRepository.patch
    original_upsert_many = AnnotationRepository.upsert_many

    def counted_get_project(*args, **kwargs):
        nonlocal get_project_calls
        get_project_calls += 1
        return original_get_project(*args, **kwargs)

    def counted_patch(self, *args, **kwargs):
        nonlocal material_patch_calls
        material_patch_calls += 1
        return original_patch(self, *args, **kwargs)

    def counted_upsert_many(self, *args, **kwargs):
        nonlocal annotation_upserts
        annotation_upserts += 1
        return original_upsert_many(self, *args, **kwargs)

    monkeypatch.setattr(app_module, 'get_project', counted_get_project)
    monkeypatch.setattr(MaterialRepository, 'patch', counted_patch)
    monkeypatch.setattr(AnnotationRepository, 'upsert_many', counted_upsert_many)

    report = app_module.v19_build_report_base({'id': 'p1', 'file_name': 'p1.zip'})
    app_module._v50_begin_image_batch(project_id)
    try:
        assert app_module._v18_import_yolo(project_id, root, 'default', report) is True
        assert material_patch_calls == 0
        app_module._v50_end_image_batch(save=True)
    except BaseException:
        app_module._v50_end_image_batch(save=False)
        raise

    assert report['imported_images'] == 100
    assert report['boxes'] == 100
    assert get_project_calls <= 3
    # P2b persists the final YOLO truth before add_image_record returns, in one write.
    assert annotation_upserts == 100
    summary = app_module.material_store(project_id).summary()
    assert summary['total'] == 100
    assert summary['annotated'] == 100
    assert summary['boxes'] == 100
