import io
import time
import zipfile
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
    original = MaterialRepository.patch_annotation_projections

    def counted(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        return original(self, *args, **kwargs)

    monkeypatch.setattr(MaterialRepository, 'patch_annotation_projections', counted)
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


def test_v50_batch_annotation_for_existing_material_projects_immediately(monkeypatch, seeded_project):
    project_id, image = seeded_project
    calls = 0
    original = MaterialRepository.patch_annotation_projections

    def counted(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        return original(self, *args, **kwargs)

    monkeypatch.setattr(MaterialRepository, 'patch_annotation_projections', counted)
    app_module._v50_begin_image_batch(project_id)
    try:
        app_module.write_annotation(project_id, image['id'], [_box()])
        assert calls == 1
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
    material_projection_calls = 0
    annotation_upserts = {"calls": 0, "rows": 0}
    original_get_project = app_module.get_project
    original_patch = MaterialRepository.patch_annotation_projections
    original_upsert_many = AnnotationRepository.upsert_many

    def counted_get_project(*args, **kwargs):
        nonlocal get_project_calls
        get_project_calls += 1
        return original_get_project(*args, **kwargs)

    def counted_patch(self, *args, **kwargs):
        nonlocal material_projection_calls
        material_projection_calls += 1
        return original_patch(self, *args, **kwargs)

    def counted_upsert_many(self, *args, **kwargs):
        annotation_upserts["calls"] += 1
        annotation_upserts["rows"] += len(args[0])
        return original_upsert_many(self, *args, **kwargs)

    monkeypatch.setattr(app_module, 'get_project', counted_get_project)
    monkeypatch.setattr(MaterialRepository, 'patch_annotation_projections', counted_patch)
    monkeypatch.setattr(AnnotationRepository, 'upsert_many', counted_upsert_many)

    report = app_module.v19_build_report_base({'id': 'p1', 'file_name': 'p1.zip'})
    app_module._v50_begin_image_batch(project_id)
    try:
        assert app_module._v18_import_yolo(project_id, root, 'default', report) is True
        assert material_projection_calls == 0
        app_module._v50_end_image_batch(save=True)
    except BaseException:
        app_module._v50_end_image_batch(save=False)
        raise

    assert report['imported_images'] == 100
    assert report['boxes'] == 100
    assert get_project_calls <= 3
    assert annotation_upserts == {"calls": 1, "rows": 100}
    assert material_projection_calls == 1
    summary = app_module.material_store(project_id).summary()
    assert summary['total'] == 100
    assert summary['annotated'] == 100
    assert summary['boxes'] == 100



def test_v19_selected_import_extracts_only_selected_images_and_keeps_annotation_files(tmp_path: Path):
    archive = tmp_path / "selected.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("images/train/keep.jpg", b"keep-image")
        zf.writestr("images/train/skip.jpg", b"skip-image")
        zf.writestr("labels/train/keep.txt", "0 0.5 0.5 0.5 0.5\n")
        zf.writestr("labels/train/skip.txt", "0 0.5 0.5 0.5 0.5\n")
        zf.writestr("data.yaml", "names: [object]\n")

    target = tmp_path / "extract"
    target.mkdir()
    events = []
    app_module._v18_safe_extract(
        archive,
        target,
        lambda done, total, message: events.append((done, total, message)),
        selected_image_paths=["images/train/keep.jpg"],
    )

    assert (target / "images/train/keep.jpg").read_bytes() == b"keep-image"
    assert not (target / "images/train/skip.jpg").exists()
    assert (target / "labels/train/keep.txt").is_file()
    assert (target / "labels/train/skip.txt").is_file()
    assert (target / "data.yaml").is_file()
    assert events[-1][:2] == (4, 4)


def test_v19_worker_has_no_second_selected_root_copy_owner():
    source = Path(app_module.__file__).read_text(encoding="utf-8")
    start = source.index("def v19_import_worker(")
    end = source.index("class V19MultipartUploadReq", start)
    worker = source[start:end]

    assert "selected_image_paths=selected_paths if selected_paths else None" in worker
    assert "selected_root" not in worker
    assert "v19_copy_selected_tree" not in source



def test_v19_zip_display_progress_projects_real_phase_counters():
    progress = app_module.v19_zip_display_progress({
        "status": "running",
        "phase": "EXTRACT",
        "phase_completed": 25,
        "phase_total": 100,
        "phase_unit": "files",
        "phase_elapsed_seconds": 6.5,
        "eta_seconds": 19.5,
        "message": "正在解压 25/100 个文件",
        "updated_at": "2026-09-28T05:20:00Z",
    })

    assert progress["phase"] == "EXTRACT"
    assert progress["phase_label"] == "解压导入范围"
    assert progress["phase_progress"] == 25.0
    assert progress["overall_progress"] == 53.0
    assert progress["completed"] == 25
    assert progress["total"] == 100
    assert progress["unit"] == "files"
    assert progress["eta_seconds"] == 19.5


def test_v19_failed_zip_progress_stops_at_failure_point_not_fake_100():
    progress = app_module.v19_zip_display_progress({
        "status": "failed",
        "phase": "FAILED",
        "progress": 63.5,
        "stage": "ZIP 处理失败",
        "message": "boom",
    })

    assert progress["overall_progress"] == 63.5
    assert progress["phase"] == "FAILED"
    assert progress["phase_label"] == "导入失败"


def test_v19_zip_scan_separates_verify_denominator_from_unknown_scan_work(tmp_path: Path):
    archive = tmp_path / "scan-progress.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("images/", b"")
        zf.writestr("images/a.jpg", b"not-a-real-jpeg")
        zf.writestr("labels/a.txt", "0 0.5 0.5 0.5 0.5\n")
        zf.writestr("data.yaml", "names: [object]\n")

    events = []
    result = app_module.v19_scan_zip(
        archive,
        lambda phase, done, total, message: events.append((phase, done, total, message)),
    )

    assert result["file_count"] == 3
    verify = [event for event in events if event[0] == "VERIFY"]
    scan = [event for event in events if event[0] == "SCAN"]
    assert verify
    assert verify[-1][1:3] == (3, 3)
    assert scan
    assert all(event[1] is None and event[2] is None for event in scan)


def test_v19_public_job_contains_canonical_zip_display_progress(client):
    project = client.post('/api/projects', json={'name': 'zip-public-progress', 'labels': []}).json()
    project_id = project['id']
    job = {
        "id": "zip-progress-job",
        "project_id": project_id,
        "status": "running",
        "phase": "ANNOTATION_PARSE",
        "phase_completed": 50,
        "phase_total": 200,
        "phase_unit": "images",
        "progress": 75,
        "message": "正在解析",
    }
    public = app_module.v19_public_job(project_id, job)

    assert public["zip_display_progress"]["phase"] == "ANNOTATION_PARSE"
    assert public["zip_display_progress"]["phase_progress"] == 25.0
    assert public["zip_display_progress"]["overall_progress"] == 75.0



def test_v19_unknown_phase_denominator_does_not_fake_zero_percent_or_zero_eta():
    metrics = app_module._v19_phase_metrics(
        "SCAN",
        None,
        None,
        started_at=time.time() - 1,
    )
    assert metrics["phase_progress"] is None
    assert metrics["eta_seconds"] is None

    display = app_module.v19_zip_display_progress({
        "status": "validating",
        "phase": "SCAN",
        "phase_completed": None,
        "phase_total": None,
        "phase_progress": None,
        "phase_elapsed_seconds": 1.0,
        "eta_seconds": None,
        "progress": 42,
        "message": "正在识别图片与外部标注",
    })
    assert display["phase"] == "SCAN"
    assert display["phase_progress"] is None
    assert display["overall_progress"] == 42.0
    assert display["eta_seconds"] is None


def test_v19_scan_source_contract_never_marks_scan_100_before_annotation_detection_finishes():
    source = Path(app_module.__file__).read_text(encoding="utf-8")
    scan_start = source.index("def v19_scan_zip(")
    scan_end = source.index("def _v19_prepare_scan(", scan_start)
    scan = source[scan_start:scan_end]
    finalize_start = source.index("def _v19_finalize_multipart_upload(")
    finalize_end = source.index("def _v19_schedule_multipart_finalize", finalize_start)
    finalize = source[finalize_start:finalize_end]

    assert 'progress_cb("VERIFY", scan_index, scan_total, name)' in scan
    assert '"SCAN",\n                    None,\n                    None,' in scan
    assert '_v19_phase_metrics("SCAN", None, None' in finalize
    assert 'progress=42' in finalize
