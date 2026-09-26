from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from platform_core import training_devices, training_metrics, training_tasks


GIB = 1024 ** 3


class _FakeCuda:
    def device_count(self):
        return 1

    def set_device(self, _index):
        return None

    def mem_get_info(self, _index):
        return 40 * GIB, 80 * GIB


class _FakeTorch:
    cuda = _FakeCuda()


class _FakeModelBody:
    def parameters(self):
        return []


class _FakeModel:
    model = _FakeModelBody()


def test_manual_workers_are_not_coupled_to_batch(monkeypatch, tmp_path):
    """batch=4/workers=8 is valid when host and dataset capacity allow it."""
    monkeypatch.setattr(training_metrics, "host_resources", lambda: (16, 64 * GIB))
    monkeypatch.setattr(
        training_metrics.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(free=200 * GIB),
    )
    resolved = training_metrics.resolve_resources(
        {
            "resource_strategy": "manual",
            "batch": 4,
            "workers": 8,
            "cache": False,
            "device": "cuda:0",
            "data": str(tmp_path / "data.yaml"),
            "imgsz": 640,
            "multi_scale": 0.0,
        },
        {
            "concurrent_reservations": 1,
            "dataset_bytes": 0,
            "decoded_dataset_bytes": 0,
            "remote_cache_ready": True,
            "train_image_count": 100,
        },
        _FakeModel(),
        _FakeTorch(),
    )
    assert resolved["resolved_batch"] == 4
    assert resolved["resolved_workers"] == 8


def test_cuda_validation_uses_lightweight_nvidia_smi_admission(monkeypatch):
    calls = []

    def fake_run(argv, **_kwargs):
        calls.append(list(argv))
        assert argv[0] == "nvidia-smi"
        return SimpleNamespace(
            returncode=0,
            stdout=(
                "0, GPU-11111111-1111-1111-1111-111111111111, NVIDIA A800-SXM4-40GB\n"
                "1, GPU-22222222-2222-2222-2222-222222222222, NVIDIA A800-SXM4-40GB\n"
            ),
            stderr="",
        )

    monkeypatch.setattr(training_devices.subprocess, "run", fake_run)
    report = training_devices.validate_training_device("/opt/yolo/bin/python", "cuda:1")

    assert len(calls) == 1
    assert report["validated_device"] == "cuda:1"
    assert report["gpus"][1]["uuid"] == "GPU-22222222-2222-2222-2222-222222222222"
    assert report["validation_mode"] == "nvidia_smi_admission_then_trainer_torch_validation"


def test_cuda_validation_falls_back_to_torch_probe(monkeypatch):
    def missing_nvidia_smi(*_args, **_kwargs):
        raise FileNotFoundError("nvidia-smi")

    monkeypatch.setattr(training_devices.subprocess, "run", missing_nvidia_smi)
    fallback = {
        "python_executable": "/opt/yolo/bin/python",
        "requested_python_executable": "/opt/yolo/bin/python",
        "torch_version": "2.5.0+cu124",
        "cuda_version": "12.4",
        "cuda_available": True,
        "device_count": 1,
        "gpus": [{"id": "cuda:0", "index": 0, "name": "A800", "uuid": "GPU-1"}],
        "cpu_name": "CPU",
        "error": None,
        "validated_device": "cuda:0",
        "validation_mode": "torch_subprocess",
    }
    monkeypatch.setattr(training_devices, "probe_training_devices", lambda *_args, **_kwargs: dict(fallback))

    report = training_devices.validate_training_device("/opt/yolo/bin/python", "cuda:0")
    assert report == fallback


def test_bundle_copy_hashes_source_during_copy_without_extra_full_reads(monkeypatch, tmp_path):
    source = tmp_path / "source.jpg"
    destination = tmp_path / "bundle" / "image.jpg"
    destination.parent.mkdir()
    payload = (b"training-image-payload" * 8192) + b"tail"
    source.write_bytes(payload)

    import hashlib
    expected = hashlib.sha256(payload).hexdigest()

    # A fresh destination should not need _sha256(source) before copying or
    # _sha256(temp) afterwards: the copy pass itself computes the digest.
    def unexpected_extra_hash(path: Path):
        pytest.fail(f"unexpected extra full-file SHA256 pass: {path}")

    monkeypatch.setattr(training_tasks, "_sha256", unexpected_extra_hash)
    training_tasks._copy_verified_isolated(source, destination, expected)

    assert destination.read_bytes() == payload
    assert not training_tasks._same_physical_file(source, destination)


def test_bundle_copy_rejects_changed_source_even_with_single_pass(tmp_path):
    source = tmp_path / "source.jpg"
    destination = tmp_path / "bundle" / "image.jpg"
    destination.parent.mkdir()
    source.write_bytes(b"new-content")

    with pytest.raises(ValueError, match="source image SHA256 changed"):
        training_tasks._copy_verified_isolated(source, destination, "0" * 64)
    assert not destination.exists()



def test_rebuildable_bundle_copy_can_defer_per_file_fsync(monkeypatch, tmp_path):
    source = tmp_path / "source.jpg"
    destination = tmp_path / "bundle" / "image.jpg"
    destination.parent.mkdir()
    payload = b"rebuildable-bundle" * 4096
    source.write_bytes(payload)

    import hashlib
    expected = hashlib.sha256(payload).hexdigest()
    monkeypatch.setattr(
        training_tasks.os,
        "fsync",
        lambda _fd: pytest.fail("rebuildable bundle copy should not fsync each image"),
    )

    training_tasks._copy_verified_isolated(
        source,
        destination,
        expected,
        durable=False,
    )
    assert destination.read_bytes() == payload


def test_materialization_uses_construction_evidence_instead_of_full_image_rehash(monkeypatch, tmp_path):
    source = tmp_path / "source.jpg"
    payload = b"image-payload" * 2048
    source.write_bytes(payload)

    import hashlib
    expected = hashlib.sha256(payload).hexdigest()
    snapshot = {
        "snapshot_id": "snapshot-startup-performance",
        "label_schema": [{"code": "smoke", "class_id": 0}],
        "images": [{"image_id": "img-1", "content_sha256": expected}],
        "ids": {"train": ["img-1"], "validation": [], "test": []},
    }
    row = {
        "id": "img-1",
        "filename": "source.jpg",
        "width": 100,
        "height": 100,
        "boxes": [{"label": "smoke", "x1": 10, "y1": 10, "x2": 40, "y2": 40}],
    }
    original_sha256 = training_tasks._sha256
    hashed_paths = []

    def tracked_sha256(path):
        resolved = Path(path).resolve()
        hashed_paths.append(resolved)
        return original_sha256(resolved)

    monkeypatch.setattr(training_tasks, "_sha256", tracked_sha256)
    root = training_tasks.materialize_portable_dataset(
        tmp_path / "work",
        snapshot,
        [row],
        lambda _row: source,
        safety_reserve_bytes=0,
    )

    bundle_image = (root / "dataset/images/train/img-1.jpg").resolve()
    assert bundle_image.is_file()
    assert bundle_image not in hashed_paths
    manifest = training_tasks._json(root / "manifest.json", {})
    assert manifest["construction_verification"]["image_integrity"] == "source_sha256_verified_then_training_input_normalized"
    assert manifest["construction_verification"]["training_input_policy"] == "ultralytics_jpeg_repair_v1"


def test_oom_retry_keeps_workers_independent_from_batch():
    from train_worker import next_oom_retry_resources

    assert next_oom_retry_resources(8, 8) == (4, 8)
    assert next_oom_retry_resources(4, 8) == (2, 8)
    assert next_oom_retry_resources(2, 3) == (1, 3)


def test_startup_stage_contract_persists_first_batch_truth(tmp_path):
    from train_worker import publish_startup_stage, read_json

    job_file = tmp_path / "job.json"
    job_file.write_text("{}", encoding="utf-8")
    publish_startup_stage(
        job_file,
        "first_batch",
        "首个 Batch 已开始",
        29,
        training_started=True,
    )
    job = read_json(job_file, {})
    assert job["startup_stage"] == "first_batch"
    assert job["training_started"] is True
    assert job["current_item"] == "首个 Batch 已开始"


@pytest.mark.parametrize("image_count", [1_000, 10_000, 20_000])
def test_selected_project_images_batches_annotation_repository_reads(monkeypatch, tmp_path, image_count):
    image_ids = [f"image-{index:05d}" for index in range(image_count)]

    class FakeMaterials:
        def get_many(self, ids):
            return [
                {"id": image_id, "filename": f"{image_id}.jpg", "content_sha256": "a" * 64}
                for image_id in ids
            ]

    class FakeAnnotations:
        def __init__(self):
            self.calls = []

        def get_many(self, ids):
            batch = list(ids)
            self.calls.append(batch)
            assert len(batch) <= 500
            return {
                image_id: {
                    "image_id": image_id,
                    "annotation_state": "confirmed_empty",
                    "annotation_scope": ["smoke"],
                    "content_digest": f"digest-{image_id}",
                    "boxes": [],
                }
                for image_id in batch
            }

        def get(self, _image_id):
            pytest.fail("_selected_project_images must not issue per-image AnnotationRepository.get() calls")

    annotations = FakeAnnotations()
    monkeypatch.setattr(training_tasks, "AnnotationRepository", lambda _project: annotations)

    rows = training_tasks._selected_project_images(FakeMaterials(), tmp_path, image_ids)

    assert len(annotations.calls) == (image_count + 499) // 500
    assert sum(len(batch) for batch in annotations.calls) == image_count
    assert all(1 <= len(batch) <= 500 for batch in annotations.calls)
    assert [row["id"] for row in rows] == image_ids
    assert all(row["annotated"] is True for row in rows)
