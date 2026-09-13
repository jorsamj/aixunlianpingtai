from pathlib import Path

APP = Path('app.py')
ANNOTATION_REPO = Path('platform_core/annotation_repository.py')
TEST = Path('tests/api/test_zip_processing_p1.py')

# 1) Keep AnnotationRepository's existing projection behavior by default, but allow
# app-level write_annotation to own the single material projection transaction.
text = ANNOTATION_REPO.read_text(encoding='utf-8')
old = '    def upsert_many(self, rows):\n'
new = '    def upsert_many(self, rows, *, project_material: bool = True):\n'
if text.count(old) != 1:
    raise SystemExit(f'upsert_many signature anchor count={text.count(old)}')
text = text.replace(old, new, 1)

old = '''        if projections and (\n            (self.project_path / 'materials.sqlite3').exists()\n            or (self.project_path / 'images.json').exists()\n        ):\n'''
new = '''        if project_material and projections and (\n            (self.project_path / 'materials.sqlite3').exists()\n            or (self.project_path / 'images.json').exists()\n        ):\n'''
if text.count(old) != 1:
    raise SystemExit(f'projection guard anchor count={text.count(old)}')
text = text.replace(old, new, 1)

old = '''    def upsert(self, image_id, boxes, annotation_state=None, annotation_scope=None):\n        self.upsert_many([{\n            'image_id': image_id,\n            'boxes': boxes,\n            'annotation_state': annotation_state,\n            'annotation_scope': annotation_scope,\n        }])\n        return self.get(image_id)\n'''
new = '''    def upsert(\n        self, image_id, boxes, annotation_state=None, annotation_scope=None,\n        *, project_material: bool = True,\n    ):\n        self.upsert_many([{\n            'image_id': image_id,\n            'boxes': boxes,\n            'annotation_state': annotation_state,\n            'annotation_scope': annotation_scope,\n        }], project_material=project_material)\n        return self.get(image_id)\n'''
if text.count(old) != 1:
    raise SystemExit(f'upsert anchor count={text.count(old)}')
text = text.replace(old, new, 1)
ANNOTATION_REPO.write_text(text, encoding='utf-8')

# 2) write_annotation becomes the sole app-level material projection owner.
text = APP.read_text(encoding='utf-8')
old = '''def write_annotation(project_id: str, image_id: str, boxes: List[Dict[str, Any]], annotation_state=None):\n    saved = AnnotationRepository(project_dir(project_id)).upsert(image_id, boxes, annotation_state)\n    updated = saved['updated_at']\n    # v42.11：把标注摘要同步进 images.json。列表页/首次启动无需逐张再次读取 annotation json，\n    # 同时保留前 32 个框用于数据卡片和预览叠加显示。\n    patch = {\n        **annotation_summary(boxes, saved['annotation_state']),\n        "annotation_summary_at": updated,\n    }\n'''
new = '''def write_annotation(project_id: str, image_id: str, boxes: List[Dict[str, Any]], annotation_state=None):\n    # App-level writes own the material projection so annotation truth and searchable\n    # material metadata are projected exactly once. Direct repository callers keep\n    # the legacy/default projection behavior via project_material=True.\n    saved = AnnotationRepository(project_dir(project_id)).upsert(\n        image_id, boxes, annotation_state, project_material=False\n    )\n    updated = saved['updated_at']\n    # v42.11：把标注摘要同步进 material index。列表页/首次启动无需逐张再次读取 annotation SQLite，\n    # 同时保留前 32 个框用于数据卡片和预览叠加显示。\n    patch = {\n        **annotation_summary(boxes, saved['annotation_state']),\n        "annotation_scope": list(saved.get("annotation_scope") or []),\n        "annotation_hash": str(saved.get("content_digest") or ""),\n        "annotation_summary_at": updated,\n    }\n'''
if text.count(old) != 1:
    raise SystemExit(f'write_annotation anchor count={text.count(old)}')
text = text.replace(old, new, 1)

# 3) Import parsers retain the already-mutated project object instead of rereading meta.json.
replacements = [
    (
        '''            cat_to_class[cid] = ensure_label(project, label)\n            project = get_project(project_id)\n''',
        '''            cat_to_class[cid] = ensure_label(project, label)\n''',
        'COCO category project refresh',
    ),
    (
        '''                boxes.append({'id':uuid.uuid4().hex[:10], 'class_id':cls, 'label':get_project(project_id)['labels'][cls], 'x1':round(max(0,x),2), 'y1':round(max(0,y),2), 'x2':round(min(rec['width'],x+w),2), 'y2':round(min(rec['height'],y+h),2)})\n''',
        '''                boxes.append({'id':uuid.uuid4().hex[:10], 'class_id':cls, 'label':project['labels'][cls], 'x1':round(max(0,x),2), 'y1':round(max(0,y),2), 'x2':round(min(rec['width'],x+w),2), 'y2':round(min(rec['height'],y+h),2)})\n''',
        'COCO per-box project refresh',
    ),
    (
        '''            cls = ensure_label(project, label); project = get_project(project_id)\n''',
        '''            cls = ensure_label(project, label)\n''',
        'VOC per-object project refresh',
    ),
    (
        '''        for n in names:\n            ensure_label(project, n)\n        project = get_project(project_id)\n''',
        '''        for n in names:\n            ensure_label(project, n)\n''',
        'YOLO names project refresh',
    ),
    (
        '''    elif not project.get('labels'):\n        ensure_label(project, 'object'); project = get_project(project_id)\n        names = ['object']\n''',
        '''    elif not project.get('labels'):\n        ensure_label(project, 'object')\n        names = ['object']\n''',
        'YOLO default label project refresh',
    ),
    (
        '''                    new_cls = get_label_id(project, label)\n                    project = get_project(project_id)\n''',
        '''                    new_cls = get_label_id(project, label)\n''',
        'YOLO per-box class project refresh',
    ),
    (
        '''                box['class_id'] = new_cls\n                box['label'] = get_project(project_id)['labels'][new_cls]\n''',
        '''                box['class_id'] = new_cls\n                box['label'] = project['labels'][new_cls]\n''',
        'YOLO per-box label project refresh',
    ),
]
for old, new, name in replacements:
    if text.count(old) != 1:
        raise SystemExit(f'{name} anchor count={text.count(old)}')
    text = text.replace(old, new, 1)
APP.write_text(text, encoding='utf-8')

TEST.write_text(r'''import io
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
    # P1 intentionally preserves the initial unannotated write plus final annotation write.
    assert annotation_upserts == 200
    summary = app_module.material_store(project_id).summary()
    assert summary['total'] == 100
    assert summary['annotated'] == 100
    assert summary['boxes'] == 100
''', encoding='utf-8')

print('ZIP processing P1 optimization applied')
