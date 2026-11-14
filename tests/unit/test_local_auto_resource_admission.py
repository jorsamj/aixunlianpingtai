from __future__ import annotations

import json
import sys

import pytest
from types import SimpleNamespace

from platform_core.task_runtime import (
    ArtifactStore,
    TaskKind,
    TaskRecord,
    TaskRepository,
    TaskStatus,
    WorkerContext,
)
from platform_core.remote_training_tasks import TrainingPrepareHandler
import platform_core.training_tasks as training_tasks


GIB = 1024 ** 3


class _Param:
    def numel(self):
        return 3_000_000


class _Model:
    class Inner:
        @staticmethod
        def parameters():
            return [_Param()]

    model = Inner()


def test_local_auto_prepare_publishes_admission_evidence_without_freezing_resources(
    tmp_path, monkeypatch,
):
    data_dir = tmp_path / "data"
    project_id = "project-auto"
    project = data_dir / "projects" / project_id
    project.mkdir(parents=True)
    (project / "algorithms.json").write_text(
        json.dumps([
            {
                "id": "algorithm-auto",
                "name": "auto",
                "versions": [],
            }
        ]),
        encoding="utf-8",
    )

    monkeypatch.setitem(
        sys.modules,
        "ultralytics",
        SimpleNamespace(YOLO=lambda _path: _Model()),
    )
    import platform_core.gpu_resources as gpu_resources

    monkeypatch.setattr(
        gpu_resources,
        "sample_gpus",
        lambda _python=None: [
            {
                "gpu_uuid": "GPU-24",
                "logical_cuda_index": 0,
                "physical_index": 0,
                "total_bytes": 24 * GIB,
                "free_bytes": 22 * GIB,
                "utilization": 5.0,
                "telemetry_available": True,
            },
            {
                "gpu_uuid": "GPU-48",
                "logical_cuda_index": 1,
                "physical_index": 1,
                "total_bytes": 48 * GIB,
                "free_bytes": 44 * GIB,
                "utilization": 5.0,
                "telemetry_available": True,
            },
        ],
    )

    artifacts = ArtifactStore(data_dir / "task_runtime" / "artifacts")
    context = SimpleNamespace(artifacts=artifacts)
    target = SimpleNamespace(task_id="train-auto", project_id=project_id)
    payload = {
        "algorithm_asset_id": "algorithm-auto",
        "model": "mother.pt",
        "framework": "ultralytics",
        "requested_device": "auto",
        "device": "auto",
        "resource_strategy": "auto",
        "resource_profile": "balanced",
        "gpu_policy": "auto",
        "precision": "auto",
        "amp": True,
        "imgsz": 640,
        "multi_scale": 0.0,
        "batch": 128,
        "workers": 0,
        "cache": False,
    }

    prepared = TrainingPrepareHandler(data_dir)._resolve_local_resources(
        context,
        target,
        payload,
        tmp_path / "bundle",
        [],
        SimpleNamespace(counts={"train": 100}),
    )

    assert prepared["resource_resolution_deferred"] is True
    assert prepared["gpu_memory_floor_bytes"] > 0
    assert prepared["estimated_gpu_memory_bytes"] is None
    assert "resolved_batch" not in prepared
    assert "resolved_workers" not in prepared
    assert not artifacts.artifact_path(
        target.task_id, "resolved-resources.json"
    ).is_file()

    admission = artifacts.read_json(
        target.task_id, "resource-admission.json", default={},
    )
    assert admission["mode"] == "deferred_auto_assignment"
    assert admission["candidate_gpu_count"] == 2
    assert admission["candidate_gpu_uuids"] == ["GPU-24", "GPU-48"]
    assert admission["gpu_memory_floor_bytes"] == prepared["gpu_memory_floor_bytes"]
    assert "resolved_batch" not in admission


def test_local_auto_prepare_without_gpu_telemetry_waits_for_scheduler_instead_of_falling_back_to_cpu(
    tmp_path, monkeypatch,
):
    data_dir = tmp_path / "data"
    project_id = "project-no-telemetry"
    project = data_dir / "projects" / project_id
    project.mkdir(parents=True)
    (project / "algorithms.json").write_text(
        json.dumps([{"id": "algorithm-auto", "name": "auto", "versions": []}]),
        encoding="utf-8",
    )
    monkeypatch.setitem(sys.modules, "ultralytics", SimpleNamespace(YOLO=lambda _: _Model()))
    import platform_core.gpu_resources as gpu_resources
    monkeypatch.setattr(gpu_resources, "sample_gpus", lambda _python=None: [])
    artifacts = ArtifactStore(data_dir / "task_runtime" / "artifacts")
    target = SimpleNamespace(task_id="train-no-telemetry", project_id=project_id)
    result = TrainingPrepareHandler(data_dir)._resolve_local_resources(
        SimpleNamespace(artifacts=artifacts), target,
        {
            "algorithm_asset_id": "algorithm-auto", "model": "mother.pt",
            "framework": "ultralytics", "device": "auto", "requested_device": "auto",
            "resource_strategy": "auto", "resource_profile": "balanced",
            "gpu_policy": "auto", "imgsz": 640, "precision": "auto", "amp": True,
        },
        tmp_path / "bundle", [], SimpleNamespace(counts={"train": 100}),
    )
    assert result["resource_resolution_deferred"] is True
    assert result["resource_admission_ref"] == "resource-admission.json"
    assert "resolved_device" not in result
    evidence = artifacts.read_json(target.task_id, "resource-admission.json")
    assert evidence["candidate_gpu_count"] == 0
    assert evidence["candidate_gpu_uuids"] == []



def test_assignment_time_resource_freeze_is_execution_fenced(tmp_path, monkeypatch):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    artifacts = ArtifactStore(tmp_path / "artifacts")
    task = TaskRecord.new(
        "train-fenced",
        "project-fenced",
        TaskKind.TRAINING,
        "payload.json",
        "training:auto",
        required_capabilities=("training.ultralytics",),
    )
    repository.create(task)
    artifacts.atomic_write_json("train-fenced", "payload.json", {})
    lease = repository.claim_next(
        "worker-fenced",
        (TaskKind.TRAINING,),
        {"training.ultralytics"},
        30,
    )
    assert lease is not None
    context = WorkerContext(
        lease.task,
        lease,
        repository,
        artifacts,
        lease_seconds=30,
    )
    observed = {}

    def fake_resolver(python_executable, request, resource_context, model_argument):
        observed["python"] = python_executable
        observed["request"] = dict(request)
        observed["context"] = dict(resource_context)
        observed["model"] = model_argument
        return {
            "schema_version": 1,
            "resource_strategy": "auto",
            "resource_profile": "balanced",
            "resolved_batch": 64,
            "resolved_workers": 8,
            "resolved_cache": "disk",
            "resolved_precision": "fp16",
        }

    monkeypatch.setattr(
        training_tasks,
        "_resolve_resource_contract_subprocess",
        fake_resolver,
    )
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    resolved = training_tasks._freeze_deferred_resource_contract(
        context,
        python_executable="/runtime/python",
        payload={
            "resource_strategy": "auto",
            "resource_profile": "balanced",
            "requested_device": "auto",
        },
        resource_context={
            "gpu_uuid": "GPU-fenced",
            "reserved_bytes": 20 * GIB,
            "concurrent_reservations": 1,
        },
        model_argument="/models/base.pt",
        bundle=bundle,
        assigned_device="cuda:1",
    )

    assert resolved["resolved_batch"] == 64
    assert observed["request"]["device"] == "cuda:1"
    assert observed["request"]["assigned_device"] == "cuda:1"
    assert observed["request"]["data"] == str(bundle / "manifest.json")
    assert artifacts.read_json(
        "train-fenced", "resolved-resources.json", default={},
    )["resolved_batch"] == 64

    context.finish(TaskStatus.FAILED, error="test fence")
    monkeypatch.setattr(
        training_tasks,
        "_resolve_resource_contract_subprocess",
        lambda *_args, **_kwargs: {
            **resolved,
            "resolved_batch": 999,
        },
    )
    try:
        training_tasks._freeze_deferred_resource_contract(
            context,
            python_executable="/runtime/python",
            payload={"resource_strategy": "auto", "requested_device": "auto"},
            resource_context={"gpu_uuid": "GPU-new"},
            model_argument="/models/base.pt",
            bundle=bundle,
            assigned_device="cuda:0",
        )
        assert False, "stale execution unexpectedly published resources"
    except Exception as error:
        assert type(error).__name__ == "ExecutionFencedError"

    assert artifacts.read_json(
        "train-fenced", "resolved-resources.json", default={},
    )["resolved_batch"] == 64


@pytest.mark.parametrize(
    ("visibility", "requested_device", "gpu_indices", "expected_device", "expected_gpu_uuid"),
    [
        (None, "cuda:0", (0,), "cuda:0", "GPU-0"),
        (None, "cuda:1", (0, 1), "cuda:1", "GPU-1"),
        (None, "auto", (0, 1), "cuda:1", "GPU-1"),
        ("1,0", "cuda:0", (0, 1), "cuda:0", "GPU-1"),
        ("1,0", "cuda:1", (0, 1), "cuda:1", "GPU-0"),
        ("1", "auto", (0, 1), "cuda:0", "GPU-1"),
        ("GPU-1,GPU-0", "auto", (0, 1), "cuda:0", "GPU-1"),
        ("1", "cuda:1", (0, 1), None, None),
    ],
)
def test_prepare_non_deferred_resource_resolution_uses_visible_cuda_ordinals(
    tmp_path, monkeypatch, visibility, requested_device, gpu_indices,
    expected_device, expected_gpu_uuid,
):
    """The preparation resolver must agree with scheduler-visible CUDA indices."""
    from platform_core.remote_training_tasks import RemoteTrainingPreparationError
    import platform_core.gpu_resources as gpu_resources
    import platform_core.training_metrics as training_metrics

    if visibility is None:
        monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)
    else:
        monkeypatch.setenv("CUDA_VISIBLE_DEVICES", visibility)

    data_dir = tmp_path / "data"
    project = data_dir / "projects" / "gpu-index-project"
    project.mkdir(parents=True)
    (project / "algorithms.json").write_text(
        json.dumps([{"id": "algorithm-auto", "name": "GPU mapping", "versions": []}]),
        encoding="utf-8",
    )
    rows = [
        {
            "gpu_uuid": f"GPU-{index}",
            "physical_index": index,
            "gpu_index": index,
            "free_bytes": (20 if index == 0 else 9) * GIB,
            "total_bytes": 24 * GIB,
            "utilization": 5.0,
            "telemetry_available": True,
        }
        for index in gpu_indices
    ]
    monkeypatch.setattr(gpu_resources, "sample_gpus", lambda: rows)
    monkeypatch.setitem(sys.modules, "ultralytics", SimpleNamespace(YOLO=lambda _: _Model()))
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace())

    captured = []
    def fake_resolve(request, resource_context, _model, _torch):
        captured.append((request["device"], resource_context["resolution_gpu_uuid"]))
        return {
            "resource_strategy": "manual",
            "resolved_batch": 4,
            "resolved_workers": 0,
            "resolved_cache": False,
            "estimated_gpu_memory_bytes": 2 * GIB,
        }
    monkeypatch.setattr(training_metrics, "resolve_resources", fake_resolve)

    runtime = data_dir / "task_runtime"
    runtime.mkdir(parents=True)
    repository = TaskRepository(runtime / "tasks.sqlite3")
    artifacts = ArtifactStore(runtime / "artifacts")
    context = SimpleNamespace(repository=repository, artifacts=artifacts)
    payload = {
        "algorithm_asset_id": "algorithm-auto",
        "model": "mother.pt",
        "framework": "ultralytics",
        "resource_strategy": "manual",
        "resource_profile": "balanced",
        "gpu_policy": "exclusive",
        "requested_device": requested_device,
        "device": requested_device,
        "batch": 4,
        "workers": 0,
        "cache": False,
        "imgsz": 640,
    }
    resolver = TrainingPrepareHandler(data_dir)
    if expected_device is None:
        with pytest.raises(RemoteTrainingPreparationError, match="指定 GPU 缺少可验证的资源遥测"):
            resolver._resolve_local_resources(
                context, SimpleNamespace(task_id="gpu-map-test", project_id="gpu-index-project"),
                payload, tmp_path / "bundle", [], SimpleNamespace(counts={"train": 5}),
            )
        assert captured == []
        return

    prepared = resolver._resolve_local_resources(
        context, SimpleNamespace(task_id="gpu-map-test", project_id="gpu-index-project"),
        payload, tmp_path / "bundle", [], SimpleNamespace(counts={"train": 5}),
    )
    assert captured == [(expected_device, expected_gpu_uuid)]
    assert prepared["resolved_batch"] == 4
    saved = artifacts.read_json("gpu-map-test", "resource-context.json", default={})
    assert saved["resolution_device"] == expected_device
    assert saved["resolution_gpu_uuid"] == expected_gpu_uuid


@pytest.mark.parametrize(
    ("requested_device", "available_indices", "expected_uuids"),
    [
        ("cuda:0", (0, 1), ["GPU-0"]),
        ("cuda:1", (0, 1), ["GPU-1"]),
        ("cuda:1", (), []),
    ],
)
def test_fixed_gpu_auto_prepare_defers_without_calculating_resources(
    tmp_path, monkeypatch, requested_device, available_indices, expected_uuids,
):
    import platform_core.gpu_resources as gpu_resources
    import platform_core.training_metrics as training_metrics

    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)
    project = tmp_path / "data" / "projects" / "pin-auto"
    project.mkdir(parents=True)
    (project / "algorithms.json").write_text(
        json.dumps([{"id": "algorithm-pin", "name": "pin", "versions": []}]),
        encoding="utf-8",
    )
    monkeypatch.setitem(sys.modules, "ultralytics", SimpleNamespace(YOLO=lambda _: _Model()))
    monkeypatch.setattr(gpu_resources, "sample_gpus", lambda: [
        {
            "gpu_uuid": f"GPU-{index}", "physical_index": index,
            "total_bytes": 24 * GIB,
            "free_bytes": GIB if index == 1 else 22 * GIB,
            "utilization": 90.0 if index == 1 else 5.0,
            "telemetry_available": True,
        }
        for index in available_indices
    ])
    def no_early_resolution(*_args, **_kwargs):
        raise AssertionError("AUTO resources must resolve after training assignment")
    monkeypatch.setattr(training_metrics, "resolve_resources", no_early_resolution)

    artifacts = ArtifactStore(tmp_path / "data" / "task_runtime" / "artifacts")
    prepared = TrainingPrepareHandler(tmp_path / "data")._resolve_local_resources(
        SimpleNamespace(artifacts=artifacts),
        SimpleNamespace(task_id="train-pinned", project_id="pin-auto"),
        {
            "algorithm_asset_id": "algorithm-pin", "model": "mother.pt",
            "framework": "ultralytics", "requested_device": requested_device,
            "device": requested_device, "resource_strategy": "auto",
            "resource_profile": "balanced", "gpu_policy": "exclusive",
            "precision": "auto", "amp": True, "imgsz": 640,
        },
        tmp_path / "bundle", [], SimpleNamespace(counts={"train": 10}),
    )
    assert prepared["resource_resolution_deferred"] is True
    assert prepared["gpu_memory_floor_bytes"] > 0
    assert prepared["estimated_gpu_memory_bytes"] is None
    assert "resolved_batch" not in prepared
    assert not artifacts.artifact_path("train-pinned", "resolved-resources.json").exists()
    admission = artifacts.read_json("train-pinned", "resource-admission.json")
    assert admission["candidate_gpu_count"] == len(expected_uuids)
    assert admission["candidate_gpu_uuids"] == expected_uuids


@pytest.mark.parametrize(
    ("strategy", "device", "expected_error"),
    [
        ("auto", "cuda:0", "GPU_ASSIGNMENT_REQUIRED"),
        ("auto", "cuda:1", "GPU_ASSIGNMENT_REQUIRED"),
        ("auto", "auto", "GPU_ASSIGNMENT_REQUIRED"),
        ("auto", "cpu", "RESOURCE_DEFERRED_STRATEGY_INVALID"),
        ("manual", "cuda:0", "RESOURCE_DEFERRED_STRATEGY_INVALID"),
    ],
)
def test_handler_deferred_gpu_acceptance_does_not_allow_manual_or_cpu(
    tmp_path, strategy, device, expected_error,
):
    from platform_core.training_tasks import TrainingHandler

    artifacts = ArtifactStore(tmp_path / "artifacts")
    artifacts.atomic_write_json("train-validation", "payload.json", {
        "training_input_state": "READY",
        "resource_resolution_deferred": True,
        "resource_strategy": strategy,
        "requested_device": device, "device": device,
    })
    context = SimpleNamespace(
        artifacts=artifacts,
        task=SimpleNamespace(task_id="train-validation", payload_ref="payload.json"),
    )
    with pytest.raises((ValueError, EnvironmentError), match=expected_error):
        TrainingHandler(tmp_path).run(context)
