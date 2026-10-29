import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import platform_core.training_metrics as training_metrics
import platform_core.training_devices as training_devices
import platform_core.training_resource_policy as resource_policy


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

    def get_device_properties(self, _index):
        return SimpleNamespace(uuid="GPU-test", name="Test GPU")


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
        training_metrics,
        "host_resource_snapshot",
        lambda: {
            "cpu_cores": 16,
            "host_available_bytes": 31 * GIB,
            "host_total_bytes": 64 * GIB,
            "cgroup_limit_bytes": None,
            "cgroup_current_bytes": None,
            "cgroup_headroom_bytes": None,
            "effective_available_bytes": 31 * GIB,
            "memory_source": "host",
            "sampled_at": "2026-10-15T00:00:00+00:00",
        },
    )
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



def test_auto_precision_is_frozen_before_trainer_start(monkeypatch):
    _patch_host(monkeypatch)
    fp16 = training_metrics.resolve_resources(
        _request(precision="auto", amp=True),
        _context(gpu_uuid="GPU-test", gpu_name="Scheduler GPU"),
        _Model(),
        _Torch(_Cuda()),
    )
    fp32 = training_metrics.resolve_resources(
        _request(precision="auto", amp=False),
        _context(gpu_uuid="GPU-test"),
        _Model(),
        _Torch(_Cuda()),
    )

    assert fp16["requested_precision"] == "auto"
    assert fp16["resolved_precision"] == "fp16"
    assert fp16["assigned_device"] == "cuda:0"
    assert fp16["gpu_uuid"] == "GPU-test"
    assert fp32["resolved_precision"] == "fp32"
    assert fp32["activation_precision_factor"] == pytest.approx(2.0)


def test_resource_resolution_rejects_changed_gpu_identity(monkeypatch):
    _patch_host(monkeypatch)

    class ChangedCuda(_Cuda):
        def get_device_properties(self, _index):
            return SimpleNamespace(uuid="GPU-other", name="Other GPU")

    with pytest.raises(RuntimeError, match="GPU_IDENTITY_MISMATCH"):
        training_metrics.resolve_resources(
            _request(),
            _context(gpu_uuid="GPU-assigned"),
            _Model(),
            _Torch(ChangedCuda()),
        )

def test_auto_workers_use_actual_reservations_not_installed_gpu_count(monkeypatch):
    _patch_host(monkeypatch)

    one_gpu_job = training_metrics.resolve_resources(
        _request(workers=0, resource_profile="performance"),
        _context(concurrent_reservations=1),
        _Model(),
        _Torch(_Cuda(devices=1)),
    )
    two_gpu_single_job = training_metrics.resolve_resources(
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

    assert one_gpu_job["resolved_workers"] == two_gpu_single_job["resolved_workers"]
    assert 0 <= second_parallel_job["resolved_workers"] < two_gpu_single_job["resolved_workers"]
    assert two_gpu_single_job["estimated_host_memory_bytes"] <= two_gpu_single_job["host_memory_budget_bytes"]
    assert second_parallel_job["estimated_host_memory_bytes"] <= second_parallel_job["host_memory_budget_bytes"]
    if training_metrics.os.name == "nt":
        assert two_gpu_single_job["resolved_workers"] <= 4
    else:
        assert two_gpu_single_job["resolved_workers"] <= 12


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


def test_auto_requested_batch_128_resolves_to_safe_batch_32(monkeypatch):
    _patch_host(monkeypatch)
    constrained_gpu = _Cuda(
        free=int(14.2 * GIB),
        total=24 * GIB,
    )
    result = training_metrics.resolve_resources(
        _request(batch=128, resource_profile="balanced"),
        _context(),
        _Model(),
        _Torch(constrained_gpu),
    )

    assert result["requested_batch"] == 128
    assert result["resolved_batch"] == 32
    assert constrained_gpu.selected == 0


def test_manual_batch_128_over_same_gpu_budget_fails(monkeypatch):
    _patch_host(monkeypatch)
    constrained_gpu = _Cuda(
        free=int(14.2 * GIB),
        total=24 * GIB,
    )
    with pytest.raises(
        ValueError,
        match=r"RESOURCE_MANUAL_INVALID: requested batch=128 exceeds current GPU budget",
    ):
        training_metrics.resolve_resources(
            _request(
                resource_strategy="manual",
                batch=128,
                workers=4,
                cache=False,
                resource_profile="balanced",
            ),
            _context(),
            _Model(),
            _Torch(constrained_gpu),
        )


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


def test_auto_preserves_loader_parallelism_under_a800_host_ram_ceiling():
    request = {"imgsz":800, "precision":"fp32", "prefetch_factor":2}
    context = {"train_image_count":10000, "dataset_bytes":0}
    snapshot = {"effective_available_bytes":25 * GIB}
    kwargs = dict(profile="balanced", batch=128, workers=8, cache=False,
                  snapshot=snapshot)
    legacy = training_metrics.plan_host_training_resources(request, context, **kwargs)
    adaptive = training_metrics.plan_host_training_resources(request, context,
        **kwargs, prefer_loader_parallelism=True)
    assert legacy["workers"] == 0
    assert adaptive["workers"] >= 2
    assert 1 <= adaptive["batch"] < legacy["batch"]
    assert adaptive["estimated_bytes"] <= adaptive["budget_bytes"]
    assert adaptive["requested_estimated_bytes"] > adaptive["budget_bytes"]


def test_auto_tiny_dataset_caps_batch_and_workers_to_executable_loader_truth(monkeypatch):
    _patch_host(monkeypatch)
    result = training_metrics.resolve_resources(
        _request(batch=4, workers=0, cache=False, resource_profile="balanced"),
        _context(train_image_count=11, decoded_dataset_bytes=2 * GIB),
        _Model(),
        _Torch(_Cuda()),
    )

    assert result["resource_candidate_batch"] == 3
    assert result["resolved_batch"] == 3
    assert result["loader_batches"] == 4
    assert result["resolved_workers"] == 4
    assert any("small training set" in item and "->3" in item for item in result["adjustments"])
    assert any("train_images=11" in item and "loader_batches=4" in item for item in result["reasons"])


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



def test_deferred_auto_admission_only_estimates_batch_one_floor():
    evidence = resource_policy.auto_admission_evidence(
        _request(device="auto", batch=128, resource_profile="balanced"),
        _Model(),
    )

    memory = evidence["memory_model"]
    assert evidence["mode"] == "deferred_auto_assignment"
    assert evidence["gpu_memory_floor_bytes"] == (
        memory["fixed_bytes"] + memory["per_image_bytes"]
    )
    assert evidence["target_gpu_memory_fraction"] == pytest.approx(0.70)
    assert "resolved_batch" not in evidence
    assert memory["resolved_precision"] == "fp16"


def test_deferred_auto_reservation_scales_with_candidate_gpu_headroom():
    payload = {
        "resource_resolution_deferred": True,
        "resource_strategy": "auto",
        "resource_profile": "balanced",
        "gpu_memory_floor_bytes": 2 * GIB,
    }
    small = resource_policy.deferred_auto_reservation_bytes(
        payload,
        total_bytes=24 * GIB,
        free_bytes=22 * GIB,
        already_reserved_bytes=0,
        active_count=0,
    )
    large = resource_policy.deferred_auto_reservation_bytes(
        payload,
        total_bytes=48 * GIB,
        free_bytes=44 * GIB,
        already_reserved_bytes=0,
        active_count=0,
    )

    assert small and large
    assert large > small > payload["gpu_memory_floor_bytes"]
    shared = resource_policy.deferred_auto_reservation_bytes(
        payload,
        total_bytes=48 * GIB,
        free_bytes=44 * GIB,
        already_reserved_bytes=4 * GIB,
        active_count=1,
    )
    assert shared == payload["gpu_memory_floor_bytes"]


def test_auto_small_dataset_keeps_multiple_optimizer_updates(monkeypatch):
    _patch_host(monkeypatch)
    result = training_metrics.resolve_resources(
        _request(batch=-1, workers=0, resource_profile="performance"),
        _context(train_image_count=80),
        _Model(),
        _Torch(_Cuda()),
    )
    assert result["resolved_batch"] <= 20
    assert result["loader_batches"] >= 4
    assert result["resolved_workers"] <= 12
    assert any("small training set" in note for note in result["adjustments"])


def test_auto_workers_are_bounded_by_actual_host_ram(monkeypatch):
    _patch_host(monkeypatch)
    monkeypatch.setattr(
        training_metrics,
        "host_resource_snapshot",
        lambda: {
            "cpu_cores": 16,
            "host_available_bytes": 8 * GIB,
            "host_total_bytes": 64 * GIB,
            "cgroup_limit_bytes": None,
            "cgroup_current_bytes": None,
            "cgroup_headroom_bytes": None,
            "effective_available_bytes": 8 * GIB,
            "memory_source": "host",
            "sampled_at": "2026-10-15T00:00:00+00:00",
        },
    )
    resolved = training_metrics.resolve_resources(
        _request(batch=-1, workers=0, resource_profile="performance"),
        _context(),
        _Model(),
        _Torch(_Cuda()),
    )
    assert resolved["resolved_workers"] <= 2


def test_real_a800_incident_shape_is_jointly_bounded_by_host_memory(monkeypatch):
    """31 GiB must not repeat batch=75/workers=11 host-OOM conditions."""
    _patch_host(monkeypatch)
    resolved = training_metrics.resolve_resources(
        _request(
            batch=75,
            workers=11,
            imgsz=800,
            resource_profile="performance",
            precision="fp16",
        ),
        _context(train_image_count=8171, decoded_dataset_bytes=18 * GIB),
        _Model(),
        _Torch(_Cuda(free=int(30 * GIB), total=80 * GIB)),
    )

    assert not (
        resolved["resolved_batch"] >= 75
        and resolved["resolved_workers"] >= 11
    )
    assert resolved["estimated_host_memory_bytes"] <= resolved["host_memory_budget_bytes"]
    assert resolved["host_memory_prefetch_factor"] >= 2
    assert any("host memory" in reason.lower() for reason in resolved["reasons"])


def test_auto_host_budget_scales_with_real_ram_instead_of_fixed_workers(monkeypatch):
    workers = []
    for ram_gib in (31, 64, 128, 256):
        resolved = training_metrics.plan_host_training_resources(
            _request(batch=75, workers=11, imgsz=800, resource_profile="performance"),
            _context(train_image_count=8171, decoded_dataset_bytes=18 * GIB),
            profile="performance",
            batch=75,
            workers=12,
            cache=False,
            snapshot={"effective_available_bytes": ram_gib * GIB},
        )
        workers.append(resolved["workers"])
        assert resolved["estimated_bytes"] <= resolved["budget_bytes"]

    assert workers == sorted(workers)
    assert workers[0] < workers[-1]
    assert len(set(workers)) >= 2


def test_cgroup_headroom_is_stricter_than_host_available_memory(monkeypatch):
    _patch_host(monkeypatch)
    monkeypatch.setattr(
        training_metrics,
        "host_resource_snapshot",
        lambda: {
            "cpu_cores": 32,
            "host_available_bytes": 128 * GIB,
            "host_total_bytes": 128 * GIB,
            "cgroup_limit_bytes": 32 * GIB,
            "cgroup_current_bytes": 12 * GIB,
            "cgroup_headroom_bytes": 20 * GIB,
            "effective_available_bytes": 20 * GIB,
            "memory_source": "cgroup_v2",
            "sampled_at": "2026-10-15T00:00:00+00:00",
        },
    )
    resolved = training_metrics.resolve_resources(
        _request(batch=75, workers=11, imgsz=800, resource_profile="performance"),
        _context(train_image_count=8171, decoded_dataset_bytes=18 * GIB),
        _Model(),
        _Torch(_Cuda(free=int(30 * GIB), total=80 * GIB)),
    )

    assert resolved["host_memory_source"] == "cgroup_v2"
    assert resolved["available_ram_bytes"] == 20 * GIB
    assert resolved["cgroup_memory_limit_bytes"] == 32 * GIB
    assert resolved["estimated_host_memory_bytes"] <= resolved["host_memory_budget_bytes"]


def test_prestart_validation_rejects_resource_drift_without_mutating_frozen_plan(monkeypatch):
    frozen = {
        "resolved_batch": 64,
        "resolved_workers": 6,
        "estimated_host_memory_bytes": 18 * GIB,
        "host_memory_budget_bytes": 22 * GIB,
        "host_memory_remaining_required_bytes": 14 * GIB,
        "sampled_at": "2026-10-15T00:00:00+00:00",
    }
    monkeypatch.setattr(
        training_metrics,
        "host_resource_snapshot",
        lambda: {
            "cpu_cores": 16,
            "host_available_bytes": 8 * GIB,
            "host_total_bytes": 31 * GIB,
            "cgroup_limit_bytes": None,
            "cgroup_current_bytes": None,
            "cgroup_headroom_bytes": None,
            "effective_available_bytes": 8 * GIB,
            "memory_source": "host",
            "sampled_at": "2026-10-15T00:00:10+00:00",
        },
    )

    with pytest.raises(RuntimeError, match="RESOURCE_HOST_MEMORY_CHANGED"):
        training_metrics.validate_frozen_resource_budget(frozen)
    assert frozen["resolved_batch"] == 64
    assert frozen["resolved_workers"] == 6


def test_prestart_gpu_validation_rejects_changed_free_memory_without_downshifting():
    frozen = {
        "assigned_device": "cuda:0",
        "estimated_gpu_memory_bytes": 12 * GIB,
        "resolved_batch": 64,
        "resolved_workers": 4,
    }
    torch = _Torch(_Cuda(free=10 * GIB, total=80 * GIB))

    with pytest.raises(RuntimeError, match="RESOURCE_GPU_MEMORY_CHANGED"):
        training_metrics.validate_frozen_gpu_budget(frozen, torch)
    assert frozen["resolved_batch"] == 64
    assert frozen["resolved_workers"] == 4


def test_host_budget_uses_resolved_fp32_truth_when_precision_is_auto(monkeypatch):
    _patch_host(monkeypatch)
    context = _context(train_image_count=128, decoded_dataset_bytes=2 * GIB)
    automatic = training_metrics.resolve_resources(
        _request(device="cpu", precision="auto", batch=8, workers=0),
        context,
        _Model(),
        _Torch(_Cuda()),
    )
    explicit = training_metrics.resolve_resources(
        _request(device="cpu", precision="fp32", batch=8, workers=0),
        context,
        _Model(),
        _Torch(_Cuda()),
    )

    assert automatic["resolved_precision"] == "fp32"
    assert automatic["estimated_host_memory_bytes"] == explicit["estimated_host_memory_bytes"]


@pytest.mark.skipif(os.name == "nt", reason="Linux cgroup v2 runtime files required")
def test_linux_cgroup_v2_snapshot_matches_runtime_memory_files():
    relative = None
    for line in Path("/proc/self/cgroup").read_text(encoding="utf-8").splitlines():
        parts = line.split(":", 2)
        if len(parts) == 3 and parts[0] == "0":
            relative = parts[2].lstrip("/")
            break
    assert relative is not None, "Ubuntu training CI must expose the unified cgroup v2 hierarchy"
    scope = Path("/sys/fs/cgroup") / relative
    limit_file = scope / "memory.max"
    current_file = scope / "memory.current"
    assert limit_file.is_file()
    assert current_file.is_file()

    raw_limit = limit_file.read_text(encoding="utf-8").strip()
    expected_limit = None if raw_limit == "max" else int(raw_limit)
    current_before = int(current_file.read_text(encoding="utf-8").strip())
    snapshot = training_metrics.host_resource_snapshot()
    current_after = int(current_file.read_text(encoding="utf-8").strip())

    assert snapshot["cgroup_limit_bytes"] == expected_limit
    observed_current = snapshot["cgroup_current_bytes"]
    assert observed_current is not None and observed_current > 0
    current_delta = min(abs(observed_current - current_before), abs(observed_current - current_after))
    current_tolerance = max(64 * 1024 ** 2, observed_current // 4)
    assert current_delta <= current_tolerance
    if expected_limit is None:
        assert snapshot["cgroup_headroom_bytes"] is None
        assert snapshot["memory_source"] == "host"
    else:
        assert snapshot["cgroup_headroom_bytes"] == max(
            0, expected_limit - snapshot["cgroup_current_bytes"]
        )
        expected_available = min(
            snapshot["host_available_bytes"], snapshot["cgroup_headroom_bytes"]
        )
        assert snapshot["effective_available_bytes"] == expected_available
        expected_source = (
            "cgroup_v2"
            if snapshot["cgroup_headroom_bytes"] < snapshot["host_available_bytes"]
            else "host"
        )
        assert snapshot["memory_source"] == expected_source
