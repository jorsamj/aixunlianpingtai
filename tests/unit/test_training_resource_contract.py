from types import SimpleNamespace

import pytest

import platform_core.training_metrics as training_metrics
import platform_core.training_devices as training_devices


GIB = 1024 ** 3


class _Param:
    def __init__(self, count=3_000_000):
        self._count = count

    def numel(self):
        return self._count


class _Model:
    class Inner:
        @staticmethod
        def parameters():
            return [_Param()]

    model = Inner()


class _Cuda:
    def __init__(self, free=40 * GIB, total=40 * GIB, devices=1):
        self._free = free
        self._total = total
        self._devices = devices
        self.selected = None

    def set_device(self, index):
        self.selected = index

    def mem_get_info(self, index):
        return self._free, self._total

    def device_count(self):
        return self._devices


class _Torch:
    def __init__(self, cuda):
        self.cuda = cuda


def _request(**overrides):
    value = {
        "resource_strategy": "auto",
        "gpu_policy": "auto",
        "precision": "auto",
        "amp": True,
        "batch": 16,
        "workers": 4,
        "cache": False,
        "device": "cuda:0",
        "data": "/tmp/runtime-data.yaml",
        "imgsz": 640,
        "multi_scale": 0.0,
    }
    value.update(overrides)
    return value


def _context(**overrides):
    value = {
        "concurrent_reservations": 1,
        "dataset_bytes": 2 * GIB,
        "decoded_dataset_bytes": 8 * GIB,
        "remote_cache_ready": True,
        "train_image_count": 6794,
    }
    value.update(overrides)
    return value


def _patch_host(monkeypatch):
    monkeypatch.setattr(training_metrics, "host_resources", lambda: (16, 31 * GIB))
    monkeypatch.setattr(
        training_metrics.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(total=200 * GIB, used=20 * GIB, free=180 * GIB),
    )


def test_auto_balanced_owns_batch_workers_and_cache(monkeypatch):
    _patch_host(monkeypatch)
    result = training_metrics.resolve_resources(
        _request(batch=8, workers=0, cache=False),
        _context(),
        _Model(),
        _Torch(_Cuda()),
    )

    assert result["resource_profile"] == "balanced"
    assert result["resolved_batch"] > 8
    expected_workers = 4 if training_metrics.os.name == "nt" else 8
    assert result["resolved_workers"] == expected_workers
    assert result["resolved_cache"] == "disk"
    assert any("batch auto-resolved" in item for item in result["adjustments"])
    assert any("workers auto-resolved" in item for item in result["adjustments"])
    assert any("cache auto-resolved" in item for item in result["adjustments"])


def test_auto_profiles_trade_throughput_for_headroom(monkeypatch):
    _patch_host(monkeypatch)
    stability = training_metrics.resolve_resources(
        _request(batch=8, workers=0, cache=False, resource_profile="stability"),
        _context(),
        _Model(),
        _Torch(_Cuda()),
    )
    balanced = training_metrics.resolve_resources(
        _request(batch=8, workers=0, cache=False, resource_profile="balanced"),
        _context(),
        _Model(),
        _Torch(_Cuda()),
    )
    performance = training_metrics.resolve_resources(
        _request(batch=8, workers=0, cache=False, resource_profile="performance"),
        _context(),
        _Model(),
        _Torch(_Cuda()),
    )

    assert stability["resolved_batch"] <= balanced["resolved_batch"] <= performance["resolved_batch"]
    assert stability["resolved_workers"] <= balanced["resolved_workers"] <= performance["resolved_workers"]
    assert stability["target_gpu_memory_fraction"] == pytest.approx(0.58)
    assert balanced["target_gpu_memory_fraction"] == pytest.approx(0.70)
    assert performance["target_gpu_memory_fraction"] == pytest.approx(0.82)


def test_fp32_uses_more_conservative_activation_memory_budget_than_fp16(monkeypatch):
    _patch_host(monkeypatch)
    fp16 = training_metrics.resolve_resources(
        _request(precision="fp16", amp=True),
        _context(),
        _Model(),
        _Torch(_Cuda()),
    )
    fp32 = training_metrics.resolve_resources(
        _request(precision="fp32", amp=False),
        _context(),
        _Model(),
        _Torch(_Cuda()),
    )

    assert fp16["activation_precision_factor"] == pytest.approx(1.0)
    assert fp32["activation_precision_factor"] == pytest.approx(2.0)
    assert fp32["resolved_batch"] < fp16["resolved_batch"]


def test_auto_workers_use_actual_reservations_not_installed_gpu_count(monkeypatch):
    _patch_host(monkeypatch)

    single_job = training_metrics.resolve_resources(
        _request(workers=0, resource_profile="performance"),
        _context(concurrent_reservations=1),
        _Model(),
        _Torch(_Cuda(devices=2)),
    )
    second_parallel_job = training_metrics.resolve_resources(
        _request(workers=0, resource_profile="performance"),
        _context(concurrent_reservations=2),
        _Model(),
        _Torch(_Cuda(devices=2)),
    )

    if training_metrics.os.name == "nt":
        # Windows intentionally caps Ultralytics loader workers at 4 for runtime safety.
        assert single_job["resolved_workers"] == 4
        assert second_parallel_job["resolved_workers"] == 4
    else:
        assert single_job["resolved_workers"] == 12
        assert second_parallel_job["resolved_workers"] == 7
        assert single_job["resolved_workers"] > second_parallel_job["resolved_workers"]


def test_auto_selects_ram_cache_when_dataset_safely_fits(monkeypatch):
    _patch_host(monkeypatch)
    result = training_metrics.resolve_resources(
        _request(batch=-1, workers=0, cache=False),
        _context(decoded_dataset_bytes=2 * GIB),
        _Model(),
        _Torch(_Cuda()),
    )

    assert result["resolved_cache"] == "ram"
    assert result["resolved_batch"] > 0


def test_auto_batch_minus_one_remains_supported(monkeypatch):
    _patch_host(monkeypatch)
    result = training_metrics.resolve_resources(
        _request(batch=-1),
        _context(),
        _Model(),
        _Torch(_Cuda()),
    )

    assert result["requested_batch"] == -1
    assert result["resolved_batch"] > 0
    assert result["resolved_batch"] <= 128


def test_manual_batch_minus_one_is_rejected(monkeypatch):
    _patch_host(monkeypatch)
    with pytest.raises(ValueError, match="RESOURCE_MANUAL_INVALID"):
        training_metrics.resolve_resources(
            _request(resource_strategy="manual", batch=-1),
            _context(),
            _Model(),
            _Torch(_Cuda()),
        )



def test_discovered_training_device_recommends_scheduler_auto(monkeypatch):
    monkeypatch.setattr(
        training_devices,
        "probe_training_devices",
        lambda _python: {
            "python_executable": "/python",
            "torch_version": "2.12.1",
            "cuda_version": "13.0",
            "cuda_available": True,
            "device_count": 2,
            "gpus": [
                {"id": "cuda:0", "index": 0, "name": "GPU0", "uuid": "GPU-0"},
                {"id": "cuda:1", "index": 1, "name": "GPU1", "uuid": "GPU-1"},
            ],
            "cpu_name": "CPU",
            "error": None,
        },
    )
    result = training_devices.discover_training_devices("/python")
    assert result["recommended"] == "auto"
    assert result["options"][-1]["id"] == "auto"


def test_gpu_policy_is_preserved_and_shared_fails_closed(monkeypatch):
    _patch_host(monkeypatch)
    result = training_metrics.resolve_resources(
        _request(gpu_policy="exclusive"),
        _context(),
        _Model(),
        _Torch(_Cuda()),
    )
    assert result["gpu_policy"] == "exclusive"

    with pytest.raises(ValueError, match="GPU_POLICY_UNSUPPORTED"):
        training_metrics.resolve_resources(
            _request(gpu_policy="shared"),
            _context(),
            _Model(),
            _Torch(_Cuda()),
        )


def test_manual_keeps_exact_values(monkeypatch):
    _patch_host(monkeypatch)
    result = training_metrics.resolve_resources(
        _request(resource_strategy="manual", batch=16, workers=4, cache=False),
        _context(),
        _Model(),
        _Torch(_Cuda()),
    )

    assert result["resolved_batch"] == 16
    assert result["resolved_workers"] == 4
    assert result["resolved_cache"] is False


def test_auto_tiny_dataset_caps_batch_and_workers_to_executable_loader_truth(monkeypatch):
    _patch_host(monkeypatch)
    result = training_metrics.resolve_resources(
        _request(batch=4, workers=0, cache=False, resource_profile="balanced"),
        _context(train_image_count=11, decoded_dataset_bytes=2 * GIB),
        _Model(),
        _Torch(_Cuda()),
    )

    assert result["resource_candidate_batch"] > 11
    assert result["resolved_batch"] == 11
    assert result["loader_batches"] == 1
    assert result["resolved_workers"] == 0
    assert any("batch capped" in item and "->11" in item for item in result["adjustments"])
    assert any("workers capped" in item and "->0" in item for item in result["adjustments"])
    assert any("train_images=11" in item and "loader_batches=1" in item for item in result["reasons"])


def test_auto_single_image_dataset_is_one_batch_with_zero_workers(monkeypatch):
    _patch_host(monkeypatch)
    result = training_metrics.resolve_resources(
        _request(batch=4, workers=0, cache=False),
        _context(train_image_count=1, decoded_dataset_bytes=64 * 1024 ** 2),
        _Model(),
        _Torch(_Cuda()),
    )

    assert result["resolved_batch"] == 1
    assert result["loader_batches"] == 1
    assert result["resolved_workers"] == 0


def test_effective_loader_resources_caps_workers_by_real_batch_count():
    resolved = training_metrics.effective_loader_resources(
        train_image_count=100,
        batch=50,
        workers=8,
    )

    assert resolved["effective_batch"] == 50
    assert resolved["loader_batches"] == 2
    assert resolved["worker_batch_cap"] == 2
    assert resolved["effective_workers"] == 2


def test_effective_loader_resources_preserves_large_dataset_parallelism():
    resolved = training_metrics.effective_loader_resources(
        train_image_count=10_000,
        batch=128,
        workers=8,
    )

    assert resolved["effective_batch"] == 128
    assert resolved["loader_batches"] == 79
    assert resolved["effective_workers"] == 8


def test_manual_rejects_values_that_ultralytics_loader_would_change(monkeypatch):
    _patch_host(monkeypatch)
    with pytest.raises(ValueError, match="requested batch=16 exceeds train image count=11"):
        training_metrics.resolve_resources(
            _request(resource_strategy="manual", batch=16, workers=0, cache=False),
            _context(train_image_count=11),
            _Model(),
            _Torch(_Cuda()),
        )

    with pytest.raises(ValueError, match="requested workers=4 exceeds runtime loader cap=2"):
        training_metrics.resolve_resources(
            _request(resource_strategy="manual", batch=50, workers=4, cache=False),
            _context(train_image_count=100),
            _Model(),
            _Torch(_Cuda()),
        )
