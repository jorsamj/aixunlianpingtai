from __future__ import annotations

import json
import sys
from types import SimpleNamespace

from platform_core.task_runtime import ArtifactStore
from platform_core.remote_training_tasks import TrainingPrepareHandler


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
