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
