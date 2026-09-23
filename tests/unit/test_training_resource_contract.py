from types import SimpleNamespace

import pytest

import platform_core.training_metrics as training_metrics


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
    assert result["resolved_workers"] == 8
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
