import argparse
import io
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--images', type=int, default=1000)
    parser.add_argument('--json-out', default='')
    return parser.parse_args()


def tiny_jpeg() -> bytes:
    buffer = io.BytesIO()
    Image.new('RGB', (32, 32), 'white').save(buffer, format='JPEG', quality=75)
    return buffer.getvalue()


def main():
    args = parse_args()
    root = Path(tempfile.mkdtemp(prefix='zip-processing-p2a-')).resolve()
    os.environ['MC_TRAIN_DATA_DIR'] = str(root / 'platform-data')
    os.environ['MC_PLATFORM_VERSION'] = 'test'

    import app
    from platform_core.annotation_repository import AnnotationRepository

    project = app.create_project(app.ProjectCreate(name='zip-processing-p2a', labels=[]))
    project_id = project['id']
    app.ensure_default_datasets(project_id)

    dataset = root / 'source'
    images_dir = dataset / 'images' / 'train'
    labels_dir = dataset / 'labels' / 'train'
    images_dir.mkdir(parents=True, exist_ok=True)
    labels_dir.mkdir(parents=True, exist_ok=True)
    payload = tiny_jpeg()
    for index in range(args.images):
        stem = f'image_{index:05d}'
        (images_dir / f'{stem}.jpg').write_bytes(payload)
        (labels_dir / f'{stem}.txt').write_text('0 0.5 0.5 0.5 0.5\n', encoding='utf-8')
    (dataset / 'data.yaml').write_text(
        'train: images/train\nnames: [object]\n', encoding='utf-8'
    )

    counters = {
        'annotation_init': 0,
        'annotation_connect': 0,
        'annotation_upsert': 0,
        'annotation_upsert_many': 0,
        'annotation_get': 0,
    }
    original_init = AnnotationRepository.__init__
    original_connect = AnnotationRepository._connect
    original_upsert = AnnotationRepository.upsert
    original_upsert_many = AnnotationRepository.upsert_many
    original_get = AnnotationRepository.get

    def counted_init(self, *args, **kwargs):
        counters['annotation_init'] += 1
        return original_init(self, *args, **kwargs)

    def counted_connect(self, *args, **kwargs):
        counters['annotation_connect'] += 1
        return original_connect(self, *args, **kwargs)

    def counted_upsert(self, *args, **kwargs):
        counters['annotation_upsert'] += 1
        return original_upsert(self, *args, **kwargs)

    def counted_upsert_many(self, *args, **kwargs):
        counters['annotation_upsert_many'] += 1
        return original_upsert_many(self, *args, **kwargs)

    def counted_get(self, *args, **kwargs):
        counters['annotation_get'] += 1
        return original_get(self, *args, **kwargs)

    AnnotationRepository.__init__ = counted_init
    AnnotationRepository._connect = counted_connect
    AnnotationRepository.upsert = counted_upsert
    AnnotationRepository.upsert_many = counted_upsert_many
    AnnotationRepository.get = counted_get

    report = app.v19_build_report_base({'id': 'bench', 'file_name': 'bench.zip'})
    started = time.perf_counter()
    app._v50_begin_image_batch(project_id)
    try:
        imported = app._v18_import_yolo(project_id, dataset, 'default', report)
        import_seconds = time.perf_counter() - started
        commit_started = time.perf_counter()
        app._v50_end_image_batch(save=True)
        commit_seconds = time.perf_counter() - commit_started
    except BaseException:
        app._v50_end_image_batch(save=False)
        raise
    finally:
        AnnotationRepository.__init__ = original_init
        AnnotationRepository._connect = original_connect
        AnnotationRepository.upsert = original_upsert
        AnnotationRepository.upsert_many = original_upsert_many
        AnnotationRepository.get = original_get

    material_summary = app.material_store(project_id).summary()
    annotation_summary = AnnotationRepository(app.project_dir(project_id)).summary()
    result = {
        'images_requested': args.images,
        'imported': bool(imported),
        'report_imported_images': int(report.get('imported_images') or 0),
        'report_boxes': int(report.get('boxes') or 0),
        'material_total': int(material_summary.get('total') or 0),
        'material_boxes': int(material_summary.get('boxes') or 0),
        'annotation_total': int(annotation_summary.get('total') or 0),
        'annotation_annotated': int(annotation_summary.get('annotated') or 0),
        'import_seconds': round(import_seconds, 4),
        'commit_seconds': round(commit_seconds, 4),
        'wall_seconds': round(import_seconds + commit_seconds, 4),
        **counters,
    }
    assert result['report_imported_images'] == args.images, result
    assert result['report_boxes'] == args.images, result
    assert result['material_total'] == args.images, result
    assert result['material_boxes'] == args.images, result
    assert result['annotation_total'] == args.images, result
    assert result['annotation_annotated'] == args.images, result
    assert result['annotation_upsert'] == args.images * 2, result
    assert result['annotation_upsert_many'] == args.images * 2, result

    line = json.dumps(result, ensure_ascii=False, sort_keys=True)
    print('P2A_METRICS=' + line)
    if args.json_out:
        Path(args.json_out).write_text(line, encoding='utf-8')
    shutil.rmtree(root, ignore_errors=True)


if __name__ == '__main__':
    main()
