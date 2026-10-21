from __future__ import annotations

import json
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from fastapi import HTTPException


def _setup(monkeypatch, tmp_path: Path):
    import app as platform
    project_id = "evaluation-project"
    algorithm_id = "algo"
    version_id = "v1"
    digest = "a" * 64
    root = tmp_path / "projects" / project_id
    (root / "snapshots").mkdir(parents=True)
    image = root / "readonly-test.jpg"
    Image.new('RGB', (120, 80), 'navy').save(image)
    content_hash = hashlib.sha256(image.read_bytes()).hexdigest()
    (root / "snapshots" / f"{digest}.json").write_text(json.dumps({
        "snapshot_id": digest,
        "test_image_ids": ["test-image", "train-image"],
        "images": [
            {"image_id": "test-image", "content_sha256": content_hash},
            {"image_id": "train-image", "content_sha256": "c" * 64},
        ],
    }), encoding="utf-8")
    version = {"id": version_id, "evaluation": {
        "status": "succeeded", "snapshot_id": digest,
        "error_samples": [{"image": "readonly-test.jpg", "fp_count": 1, "fn_count": 1}]
    }}
    monkeypatch.setattr(platform, "get_project", lambda _: {"id": project_id})
    monkeypatch.setattr(platform, "list_algorithms_internal", lambda _: [{
        "id": algorithm_id, "versions": [version]
    }])
    monkeypatch.setattr(platform, "project_dir", lambda _: root)
    rows = [
        {"id": "test-image", "stored_name": "readonly-test.jpg", "content_sha256": content_hash},
        {"id": "train-image", "stored_name": "train.jpg", "content_sha256": "c" * 64},
    ]
    class Repository:
        def __init__(self, root): self.root = root
        def current_revision(self): return 1
        def get_many(self, ids): return [row for row in rows if row["id"] in ids]
        def get_by_content_sha256(self, digest):
            return next((row for row in rows if row['content_sha256'] == digest), None)
    monkeypatch.setattr(platform, "MaterialRepository", Repository)
    class Manager:
        def material(self, image_id):
            assert image_id == "test-image"
            return {"id": image_id}
        def materialize(self, value, *, read_only=False):
            return SimpleNamespace(path=image)
    monkeypatch.setattr(platform, "storage_manager", lambda _: Manager())
    return platform, version, rows, root, image


def test_evaluation_image_is_read_only_and_exactly_bound_to_frozen_material(monkeypatch, tmp_path):
    platform, version, rows, root, image = _setup(monkeypatch, tmp_path)
    result = platform.evaluation_diagnostic_image_v1("evaluation-project", "algo", "v1", "readonly-test.jpg")
    assert Path(result.path) == image
    assert result.headers["cache-control"] == "private, no-store"
    assert result.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize(("suffix", "pil_format", "media_type"), [
    (".jpg", "JPEG", "image/jpeg"),
    (".png", "PNG", "image/png"),
    (".webp", "WEBP", "image/webp"),
    (".bmp", "BMP", "image/bmp"),
])
def test_verified_preview_reports_real_raster_format_and_dimensions(
    monkeypatch, tmp_path, suffix, pil_format, media_type,
):
    platform, version, rows, root, original = _setup(monkeypatch, tmp_path)
    image = root / f"verified{suffix}"
    Image.new("RGB", (123, 77), "navy").save(image, format=pil_format)
    digest = hashlib.sha256(image.read_bytes()).hexdigest()
    version["evaluation"]["error_samples"][0]["image"] = image.name
    rows[0].update(stored_name=image.name, content_sha256=digest)
    snapshot_path = root / "snapshots" / ("a" * 64 + ".json")
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    snapshot["images"][0].update(stored_name=image.name, content_sha256=digest)
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

    class Manager:
        def material(self, image_id): return {"id": image_id}
        def materialize(self, _value, *, read_only=False): return SimpleNamespace(path=image)
    monkeypatch.setattr(platform, "storage_manager", lambda _: Manager())

    response = platform.evaluation_diagnostic_image_v1(
        "evaluation-project", "algo", "v1", image.name,
    )

    assert response.media_type == media_type
    assert response.headers["x-evaluation-image-format"] == pil_format
    assert response.headers["x-evaluation-image-width"] == "123"
    assert response.headers["x-evaluation-image-height"] == "77"
    assert response.headers["x-evaluation-evidence-source"] == "material"


@pytest.mark.parametrize("name", ["train.jpg", "other.jpg", "../readonly-test.jpg", ".."])
def test_test_preview_never_reads_unlisted_or_unsafe_paths(monkeypatch, tmp_path, name):
    platform, version, rows, root, image = _setup(monkeypatch, tmp_path)
    with pytest.raises(HTTPException) as ex:
        platform.evaluation_diagnostic_image_v1("evaluation-project", "algo", "v1", name)
    assert ex.value.status_code == 404


def test_exif_preview_preserves_frozen_pixel_grid_and_original_evidence(monkeypatch, tmp_path):
    from io import BytesIO
    platform, version, rows, root, image = _setup(monkeypatch, tmp_path)
    exif = Image.Exif()
    exif[274] = 6
    Image.new('RGB', (120, 80), 'navy').save(image, exif=exif)
    original = image.read_bytes()
    digest = hashlib.sha256(original).hexdigest()
    rows[0]['content_sha256'] = digest
    path = root / 'snapshots' / ('a' * 64 + '.json')
    snapshot = json.loads(path.read_text(encoding='utf-8'))
    snapshot['images'][0]['content_sha256'] = digest
    path.write_text(json.dumps(snapshot), encoding='utf-8')

    response = platform.evaluation_diagnostic_image_v1('evaluation-project', 'algo', 'v1', image.name)

    assert response.media_type == 'image/png'
    with Image.open(BytesIO(response.body)) as displayed:
        assert displayed.size == (120, 80)
        assert displayed.getexif().get(274, 1) == 1
    assert response.headers['x-evaluation-original-sha256'] == digest
    assert response.headers['x-evaluation-display-derived'] == 'true'
    assert image.read_bytes() == original


def test_changed_frozen_image_fails_closed_before_file_read(monkeypatch, tmp_path):
    platform, version, rows, root, image = _setup(monkeypatch, tmp_path)
    rows[0]["content_sha256"] = "d" * 64
    with pytest.raises(HTTPException) as ex:
        platform.evaluation_diagnostic_image_v1("evaluation-project", "algo", "v1", image.name)
    assert ex.value.status_code == 409


def test_portable_image_name_resolves_stable_id_after_source_rename(monkeypatch, tmp_path):
    platform, version, rows, root, image = _setup(monkeypatch, tmp_path)
    version['evaluation']['error_samples'][0]['image'] = 'test-image.jpg'
    version['evaluation']['error_samples'][0]['image_id'] = 'test-image'
    rows[0]['stored_name'] = 'migrated-name.jpg'
    response = platform.evaluation_diagnostic_image_v1('evaluation-project', 'algo', 'v1', 'test-image.jpg')
    assert Path(response.path) == image


def test_legacy_filename_stem_never_overrides_unique_frozen_stored_name(monkeypatch, tmp_path):
    """Regression for the reviewed foo-id / bar-stored-name evidence collision."""
    platform, version, rows, root, image = _setup(monkeypatch, tmp_path)
    wrong = root / 'wrong.jpg'
    expected = root / 'expected.jpg'
    Image.new('RGB', (120, 80), 'red').save(wrong)
    Image.new('RGB', (120, 80), 'blue').save(expected)
    wrong_hash = hashlib.sha256(wrong.read_bytes()).hexdigest()
    expected_hash = hashlib.sha256(expected.read_bytes()).hexdigest()
    snapshot_path = root / 'snapshots' / ('a' * 64 + '.json')
    snapshot_path.write_text(json.dumps({
        'snapshot_id': 'a' * 64,
        'test_image_ids': ['foo', 'bar'],
        'images': [
            {'image_id': 'foo', 'stored_name': 'other.jpg', 'content_sha256': wrong_hash},
            {'image_id': 'bar', 'stored_name': 'foo.jpg', 'content_sha256': expected_hash},
        ],
    }), encoding='utf-8')
    version['evaluation']['error_samples'] = [{'image': 'foo.jpg', 'image_width': 120, 'image_height': 80}]
    material_rows = [
        {'id': 'foo', 'stored_name': 'other.jpg', 'content_sha256': wrong_hash},
        {'id': 'bar', 'stored_name': 'foo.jpg', 'content_sha256': expected_hash},
    ]

    class Repository:
        def __init__(self, _root): pass
        def get_many(self, ids): return [row for row in material_rows if row['id'] in ids]
        def get_by_content_sha256(self, digest):
            return next((row for row in material_rows if row['content_sha256'] == digest), None)

    class Manager:
        def material(self, image_id): return next(row for row in material_rows if row['id'] == image_id)
        def materialize(self, material, *, read_only=False):
            return SimpleNamespace(path=wrong if material['id'] == 'foo' else expected)

    monkeypatch.setattr(platform, 'MaterialRepository', Repository)
    monkeypatch.setattr(platform, 'storage_manager', lambda _: Manager())
    response = platform.evaluation_diagnostic_image_v1('evaluation-project', 'algo', 'v1', 'foo.jpg')
    assert Path(response.path).read_bytes() == expected.read_bytes()
    assert Path(response.path).read_bytes() != wrong.read_bytes()


def test_legacy_filename_rejects_duplicate_frozen_stored_names(monkeypatch, tmp_path):
    platform, version, rows, root, image = _setup(monkeypatch, tmp_path)
    snapshot_path = root / 'snapshots' / ('a' * 64 + '.json')
    snapshot = json.loads(snapshot_path.read_text(encoding='utf-8'))
    snapshot['test_image_ids'] = ['readonly-test', 'other-id']
    snapshot['images'] = [
        {'image_id': 'readonly-test', 'stored_name': image.name, 'content_sha256': rows[0]['content_sha256']},
        {'image_id': 'other-id', 'stored_name': image.name, 'content_sha256': rows[0]['content_sha256']},
    ]
    snapshot_path.write_text(json.dumps(snapshot), encoding='utf-8')
    with pytest.raises(HTTPException) as captured:
        platform.evaluation_diagnostic_image_v1('evaluation-project', 'algo', 'v1', image.name)
    assert captured.value.detail['code'] == 'IMAGE_IDENTITY_AMBIGUOUS'


def test_explicit_image_id_outranks_filename_and_remains_hash_bound(monkeypatch, tmp_path):
    platform, version, rows, root, image = _setup(monkeypatch, tmp_path)
    version['evaluation']['error_samples'][0]['image_id'] = 'test-image'
    snapshot_path = root / 'snapshots' / ('a' * 64 + '.json')
    snapshot = json.loads(snapshot_path.read_text(encoding='utf-8'))
    snapshot['images'][0]['stored_name'] = 'another-name.jpg'
    snapshot_path.write_text(json.dumps(snapshot), encoding='utf-8')
    response = platform.evaluation_diagnostic_image_v1('evaluation-project', 'algo', 'v1', image.name)
    assert Path(response.path) == image


def test_actual_response_bytes_must_match_frozen_hash(monkeypatch, tmp_path):
    platform, version, rows, root, image = _setup(monkeypatch, tmp_path)
    Image.new('RGB', (120, 80), 'red').save(image)
    with pytest.raises(HTTPException) as captured:
        platform.evaluation_diagnostic_image_v1('evaluation-project', 'algo', 'v1', image.name)
    assert captured.value.detail['code'] == 'IMAGE_HASH_MISMATCH'


def test_normalized_bundle_bytes_are_verified_and_original_is_never_silently_substituted(monkeypatch, tmp_path):
    platform, version, rows, root, image = _setup(monkeypatch, tmp_path)
    bundle = tmp_path / "artifacts" / "work" / "bundle"
    normalized = bundle / "dataset" / "images" / "test" / "test-image.jpg"
    normalized.parent.mkdir(parents=True)
    Image.new("RGB", (120, 80), "green").save(normalized)
    evaluated_hash = hashlib.sha256(normalized.read_bytes()).hexdigest()
    version["evaluation"]["task_id"] = "task-verified"
    version["evaluation"]["error_samples"][0].update(
        image="test-image.jpg", image_id="test-image", image_content_sha256=evaluated_hash)
    manifest = {"snapshot_id":"a"*64,"splits":{"test":[{
        "image_id":"test-image","image_ref":"dataset/images/test/test-image.jpg",
        "source_content_sha256":rows[0]["content_sha256"],"content_sha256":evaluated_hash}]}}
    (bundle / "manifest.json").write_text(json.dumps(manifest),encoding="utf-8")
    monkeypatch.setattr(platform,"shared_task_artifacts",lambda:SimpleNamespace(artifact_path=lambda *_:bundle))
    response=platform.evaluation_diagnostic_image_v1("evaluation-project","algo","v1","test-image.jpg")
    assert Path(response.path) == normalized
    assert Path(response.path).read_bytes() != image.read_bytes()
    # Missing normalized evidence cannot fall back to original pixels.
    normalized.unlink()
    with pytest.raises(HTTPException) as captured:
        platform.evaluation_diagnostic_image_v1("evaluation-project","algo","v1","test-image.jpg")
    assert captured.value.detail["code"] == "ORIGINAL_IMAGE_MISSING"


@pytest.mark.parametrize('has_stored_names', [True, False])
@pytest.mark.parametrize('has_evaluated_hash', [True, False])
def test_historical_sample_without_image_id_recovers_only_from_verified_bundle_manifest(
    monkeypatch, tmp_path, has_stored_names, has_evaluated_hash,
):
    """A portable bundle name is not the original stored_name, but its manifest can prove identity."""
    platform, version, rows, root, image = _setup(monkeypatch, tmp_path)
    snapshot_path = root / "snapshots" / ("a" * 64 + ".json")
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    snapshot["images"][0]["stored_name"] = "customer-original-name.jpg"
    # An unrelated frozen original can have the portable evaluated basename.
    # Verified bundle evidence must outrank that filename coincidence.
    snapshot["images"][1]["stored_name"] = "test-image.png"
    if not has_stored_names:
        for member in snapshot['images']:
            member.pop('stored_name', None)
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

    bundle = tmp_path / "historical-artifacts" / "work" / "bundle"
    evaluated = bundle / "dataset" / "images" / "test" / "test-image.png"
    evaluated.parent.mkdir(parents=True)
    Image.new("RGB", (120, 80), "green").save(evaluated)
    evaluated_hash = hashlib.sha256(evaluated.read_bytes()).hexdigest()
    version["evaluation"]["task_id"] = "historical-task"
    version["evaluation"]["error_samples"][0] = {
        "image": "test-image.png",
        "image_content_sha256": evaluated_hash,
        "image_width": 120,
        "image_height": 80,
        "fp_count": 1,
        "fn_count": 1,
    }
    if not has_evaluated_hash:
        version['evaluation']['error_samples'][0].pop('image_content_sha256')
    (bundle / "manifest.json").write_text(json.dumps({
        "snapshot_id": "a" * 64,
        "splits": {"test": [{
            "image_id": "test-image",
            "image_ref": "dataset/images/test/test-image.png",
            "source_content_sha256": rows[0]["content_sha256"],
            "content_sha256": evaluated_hash,
        }]},
    }), encoding="utf-8")
    monkeypatch.setattr(platform, "shared_task_artifacts", lambda: SimpleNamespace(
        artifact_path=lambda *_: bundle,
    ))

    response = platform.evaluation_diagnostic_image_v1(
        "evaluation-project", "algo", "v1", "test-image.png",
    )

    assert Path(response.path) == evaluated
    assert response.media_type == "image/png"
    evaluated.unlink()
    with pytest.raises(HTTPException) as captured:
        platform.evaluation_diagnostic_image_v1('evaluation-project', 'algo', 'v1', 'test-image.png')
    assert captured.value.detail['code'] == 'ORIGINAL_IMAGE_MISSING'


def test_snapshot_identity_mismatch_returns_specific_safe_error(monkeypatch, tmp_path):
    platform, version, rows, root, image = _setup(monkeypatch, tmp_path)
    path = root / 'snapshots' / ('a' * 64 + '.json')
    snapshot = json.loads(path.read_text(encoding='utf-8'))
    snapshot['snapshot_id'] = 'f' * 64
    path.write_text(json.dumps(snapshot), encoding='utf-8')
    with pytest.raises(HTTPException) as captured:
        platform.evaluation_diagnostic_image_v1('evaluation-project', 'algo', 'v1', image.name)
    assert captured.value.detail['code'] == 'SNAPSHOT_INCOMPLETE'
    assert str(root) not in str(captured.value.detail)


def test_missing_original_id_can_resolve_hash_identical_migrated_object(monkeypatch, tmp_path):
    platform, version, rows, root, image = _setup(monkeypatch, tmp_path)
    version['evaluation']['error_samples'][0].update(image='test-image.jpg', image_id='test-image')
    migrated = {**rows.pop(0), 'id': 'migrated-id', 'stored_name': 'another.jpg', 'storage_source_id': 'archive-s3'}
    monkeypatch.setattr(platform.MaterialRepository, 'get_by_content_sha256', lambda self, digest: migrated)
    seen = []
    class Manager:
        def material(self, identity):
            seen.append(identity)
            return migrated
        def materialize(self, material, *, read_only=False):
            assert material['storage_source_id'] == 'archive-s3'
            return SimpleNamespace(path=image)
    monkeypatch.setattr(platform, 'storage_manager', lambda _: Manager())
    response = platform.evaluation_diagnostic_image_v1('evaluation-project', 'algo', 'v1', 'test-image.jpg')
    assert Path(response.path) == image
    assert seen == ['migrated-id']


def test_temporary_storage_failure_is_retryable_without_exposing_details(monkeypatch, tmp_path):
    platform, version, rows, root, image = _setup(monkeypatch, tmp_path)
    from platform_core.storage.errors import StorageError
    class Manager:
        def material(self, identity):
            raise StorageError(code='STORAGE_NETWORK_ERROR', message='secret endpoint', detail=str(root))
        def materialize(self, material, *, read_only=False):
            raise AssertionError('unreachable after source access error')
    monkeypatch.setattr(platform, 'storage_manager', lambda _: Manager())
    with pytest.raises(HTTPException) as captured:
        platform.evaluation_diagnostic_image_v1('evaluation-project', 'algo', 'v1', image.name)
    assert captured.value.status_code == 503
    assert captured.value.detail['code'] == 'STORAGE_UNAVAILABLE'
    assert captured.value.detail['retryable'] is True
    assert 'secret' not in str(captured.value.detail)


def test_storage_permission_failure_is_specific_and_not_retryable(monkeypatch, tmp_path):
    platform, version, rows, root, image = _setup(monkeypatch, tmp_path)
    from platform_core.storage.errors import StorageError
    class Manager:
        def material(self, _identity):
            raise StorageError(code='STORAGE_ACCESS_DENIED', message='private credential', detail=str(root))
        def materialize(self, _material, *, read_only=False): raise AssertionError('unreachable')
    monkeypatch.setattr(platform, 'storage_manager', lambda _: Manager())

    with pytest.raises(HTTPException) as captured:
        platform.evaluation_diagnostic_image_v1('evaluation-project', 'algo', 'v1', image.name)

    assert captured.value.status_code == 403
    assert captured.value.detail['code'] == 'ACCESS_DENIED'
    assert captured.value.detail['retryable'] is False
    assert 'credential' not in str(captured.value.detail)


def test_hash_valid_but_corrupt_raster_is_reported_as_decode_failure(monkeypatch, tmp_path):
    platform, version, rows, root, image = _setup(monkeypatch, tmp_path)
    image.write_bytes(b'not-a-real-image')
    digest = hashlib.sha256(image.read_bytes()).hexdigest()
    rows[0]['content_sha256'] = digest
    snapshot_path = root / 'snapshots' / ('a' * 64 + '.json')
    snapshot = json.loads(snapshot_path.read_text(encoding='utf-8'))
    snapshot['images'][0]['content_sha256'] = digest
    snapshot_path.write_text(json.dumps(snapshot), encoding='utf-8')

    with pytest.raises(HTTPException) as captured:
        platform.evaluation_diagnostic_image_v1('evaluation-project', 'algo', 'v1', image.name)

    assert captured.value.detail['code'] == 'IMAGE_DECODE_FAILED'


def test_missing_snapshot_fails_closed_and_does_not_use_current_training_pool(monkeypatch, tmp_path):
    platform, version, rows, root, image = _setup(monkeypatch, tmp_path)
    version["evaluation"]["snapshot_id"] = "0" * 64
    with pytest.raises(HTTPException) as ex:
        platform.evaluation_diagnostic_image_v1("evaluation-project", "algo", "v1", image.name)
    assert ex.value.status_code == 409


def test_duplicate_source_filenames_are_not_ambiguously_served(monkeypatch, tmp_path):
    platform, version, rows, root, image = _setup(monkeypatch, tmp_path)
    rows[1]["stored_name"] = image.name
    rows[1]["content_sha256"] = "c" * 64
    with pytest.raises(HTTPException) as ex:
        platform.evaluation_diagnostic_image_v1("evaluation-project", "algo", "v1", image.name)
    assert ex.value.status_code == 409


def test_20k_named_frozen_test_preview_only_fetches_one_material(monkeypatch, tmp_path):
    platform, version, rows, root, image = _setup(monkeypatch, tmp_path)
    snapshot_path = root / "snapshots" / ("a" * 64 + ".json")
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    snapshot["images"][0]["stored_name"] = image.name
    snapshot["images"][1]["stored_name"] = "train.jpg"
    for index in range(20_000):
        image_id = f"test-other-{index:05d}"
        snapshot["test_image_ids"].append(image_id)
        snapshot["images"].append({
            "image_id": image_id, "stored_name": f"test-other-{index:05d}.jpg",
            "content_sha256": "d" * 64,
        })
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    original = platform.MaterialRepository
    read_ids = []
    class ObservedRepository(original):
        def get_many(self, ids):
            read_ids.append(tuple(ids))
            return super().get_many(ids)
    monkeypatch.setattr(platform, "MaterialRepository", ObservedRepository)

    result = platform.evaluation_diagnostic_image_v1("evaluation-project", "algo", "v1", image.name)
    assert Path(result.path) == image
    assert read_ids == [("test-image",)]


def test_20k_snapshot_identity_index_is_reused_and_invalidated_on_change(monkeypatch, tmp_path):
    platform, version, rows, root, image = _setup(monkeypatch, tmp_path)
    snapshot_path = root / 'snapshots' / ('a' * 64 + '.json')
    snapshot = json.loads(snapshot_path.read_text(encoding='utf-8'))
    snapshot['images'][0]['stored_name'] = image.name
    snapshot['images'][1]['stored_name'] = 'train.jpg'
    for index in range(20_000):
        image_id = f'large-{index:05d}'
        snapshot['test_image_ids'].append(image_id)
        snapshot['images'].append({
            'image_id': image_id,
            'stored_name': f'{image_id}.jpg',
            'content_sha256': 'd' * 64,
        })
    snapshot_path.write_text(json.dumps(snapshot), encoding='utf-8')
    original_read_json = platform.read_json
    reads = 0

    def observed_read_json(path, default):
        nonlocal reads
        if Path(path) == snapshot_path:
            reads += 1
        return original_read_json(path, default)

    monkeypatch.setattr(platform, 'read_json', observed_read_json)
    for _ in range(24):
        response = platform.evaluation_diagnostic_image_v1('evaluation-project', 'algo', 'v1', image.name)
        assert Path(response.path) == image
    assert reads == 1

    snapshot['snapshot_id'] = 'b' * 64
    snapshot_path.write_text(json.dumps(snapshot) + '\n', encoding='utf-8')
    with pytest.raises(HTTPException) as captured:
        platform.evaluation_diagnostic_image_v1('evaluation-project', 'algo', 'v1', image.name)
    assert captured.value.detail['code'] == 'SNAPSHOT_INCOMPLETE'
    assert reads == 2


def test_legacy_unnamed_frozen_test_preview_reads_bounded_batches(monkeypatch, tmp_path):
    platform, version, rows, root, image = _setup(monkeypatch, tmp_path)
    snapshot_path = root / "snapshots" / ("a" * 64 + ".json")
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    for index in range(1_201):
        image_id = f"legacy-{index:05d}"
        snapshot["test_image_ids"].append(image_id)
        snapshot["images"].append({"image_id": image_id, "content_sha256": "d" * 64})
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    original = platform.MaterialRepository
    calls = []
    class ObservedRepository(original):
        def get_many(self, ids):
            calls.append(tuple(ids))
            assert len(ids) <= 500
            return super().get_many(ids)
    monkeypatch.setattr(platform, "MaterialRepository", ObservedRepository)

    result = platform.evaluation_diagnostic_image_v1("evaluation-project", "algo", "v1", image.name)
    assert Path(result.path) == image
    assert len(calls) == 4
    assert sum(len(ids) for ids in calls[:3]) == len(snapshot["test_image_ids"])
    assert calls[-1] == ('test-image',)
    calls.clear()
    platform.evaluation_diagnostic_image_v1('evaluation-project', 'algo', 'v1', image.name)
    assert calls == [('test-image',)]


def test_read_only_preview_diagnostic_summarizes_verified_sources_without_paths(monkeypatch, tmp_path):
    platform, version, rows, root, image = _setup(monkeypatch, tmp_path)
    from scripts.diagnose_evaluation_previews import diagnose

    report = diagnose('evaluation-project', 'algo', 'v1')

    assert report['problem_image_count'] == 1
    assert report['previewable_count'] == 1
    assert report['error_code_distribution'] == {'OK': 1}
    assert report['verified_source_distribution'] == {'material': 1}
    assert report['images'] == [{
        'image': image.name,
        'image_id': '',
        'previewable': True,
        'retryable': False,
        'code': 'OK',
        'evidence_source': 'material',
    }]
    assert str(root) not in json.dumps(report)


def test_20k_bundle_index_parses_once_for_24_previews_and_invalidates(monkeypatch, tmp_path):
    import time
    platform, version, rows, root, image = _setup(monkeypatch, tmp_path)
    path = root / 'manifest.json'
    document = {'snapshot_id': 'a' * 64, 'splits': {'test': [
        {'image_id': f'frozen-{i}', 'image_ref': f'dataset/images/test/frozen-{i}.jpg',
         'source_content_sha256': 'b' * 64, 'content_sha256': 'c' * 64}
        for i in range(20000)
    ]}}
    path.write_text(json.dumps(document), encoding='utf-8')
    original = platform.read_json
    reads = []
    def observed(path, default):
        reads.append(path)
        return original(path, default)
    monkeypatch.setattr(platform, 'read_json', observed)
    started = time.perf_counter()
    first = platform._evaluation_bundle_identity_index(path, 'a' * 64)
    first_ms = (time.perf_counter() - started) * 1000
    started = time.perf_counter()
    for i in range(24):
        cached = platform._evaluation_bundle_identity_index(path, 'a' * 64)
        assert cached is first
        assert cached['by_name'][f'frozen-{i}.jpg'][0]['image_id'] == f'frozen-{i}'
    cached_ms = (time.perf_counter() - started) * 1000
    assert reads == [path]
    document['snapshot_id'] = 'd' * 64
    path.write_text(json.dumps(document) + '\n', encoding='utf-8')
    assert platform._evaluation_bundle_identity_index(path, 'a' * 64) == {}
    assert len(reads) == 2
    print(f'20k Bundle index: first={first_ms:.2f}ms, 24 cached lookups={cached_ms:.2f}ms, parses=1')


@pytest.mark.parametrize('field,value', [('expected_evaluation_id','e'*64),('expected_image_id','other-image'),('expected_sha256','f'*64)])
def test_report_thumbnail_rejects_changed_evaluation_or_image_identity(monkeypatch,tmp_path,field,value):
    platform,version,rows,root,image=_setup(monkeypatch,tmp_path)
    version['evaluation']['evaluation_id']='b'*64
    sample=version['evaluation']['error_samples'][0]
    sample.update(image_id='test-image',image_content_sha256=hashlib.sha256(image.read_bytes()).hexdigest())
    expected={'expected_evaluation_id':'b'*64,'expected_image_id':'test-image','expected_sha256':sample['image_content_sha256']}
    expected[field]=value
    with pytest.raises(HTTPException) as error:
        platform.evaluation_diagnostic_image_v1('evaluation-project','algo','v1',image.name,**expected)
    assert error.value.status_code==409
    assert error.value.detail['code']=='EVALUATION_IDENTITY_CHANGED'
