import hashlib
import json
from pathlib import Path

import pytest

from platform_core.algorithms import list_algorithms
from platform_core.snapshots import dataset_revision_document, ensure_dataset_revision
from platform_core.task_runtime import ArtifactStore, TaskKind, TaskRecord, TaskRepository, TaskStatus
from platform_core.task_runtime.worker import WorkerContext
from platform_core.training_tasks import (
    TrainingHandler,
    _training_finalization_existing_version,
)


def _trainable_version(version_id: str, *, task_id: str = ""):
    return {
        "id": version_id,
        "version_name": version_id,
        "task_id": task_id,
        "training_status": "SUCCEEDED",
        "artifact_verified": True,
        "trainable": True,
        "framework": "ultralytics",
    }


def test_local_finalization_rejects_stale_iteration_base():
    algorithm = {
        "id": "alg",
        "current_version_id": "v2",
        "versions": [
            _trainable_version("v1"),
            _trainable_version("v2"),
        ],
    }

    with pytest.raises(RuntimeError, match="TRAINING_BASE_VERSION_STALE"):
        _training_finalization_existing_version(
            algorithm,
            task_id="task-new",
            expected_base_version_id="v1",
            framework="ultralytics",
        )


def test_local_first_run_finalization_rejects_new_current_version():
    algorithm = {
        "id": "alg",
        "current_version_id": "v1",
        "versions": [_trainable_version("v1")],
    }

    with pytest.raises(RuntimeError, match="TRAINING_BASE_VERSION_STALE"):
        _training_finalization_existing_version(
            algorithm,
            task_id="task-first",
            expected_base_version_id=None,
            framework="ultralytics",
        )


def test_local_finalization_reuses_same_task_version_before_stale_check():
    existing = _trainable_version("v2", task_id="task-recover")
    algorithm = {
        "id": "alg",
        "current_version_id": "v2",
        "versions": [
            _trainable_version("v1"),
            existing,
        ],
    }

    resolved = _training_finalization_existing_version(
        algorithm,
        task_id="task-recover",
        expected_base_version_id="v1",
        framework="ultralytics",
    )

    assert resolved is existing


def test_completed_training_job_recovers_without_retraining(tmp_path: Path, monkeypatch):
    data_dir = tmp_path / "data"
    project_id = "project-one"
    task_id = "train-recover"
    project = data_dir / "projects" / project_id
    (project / "jobs" / task_id).mkdir(parents=True)
    (project / "models").mkdir(parents=True)
    (project / "algorithms.json").write_text(
        json.dumps([{"id": "algorithm-one", "name": "fire", "versions": []}]),
        encoding="utf-8",
    )

    runtime = data_dir / "task_runtime"
    repository = TaskRepository(runtime / "tasks.sqlite3")
    artifacts = ArtifactStore(runtime / "artifacts")
    artifacts.atomic_write_json(task_id, "payload.json", {
        "schema_version": 3,
        "framework": "ultralytics",
        "target": "local",
        "algorithm_asset_id": "algorithm-one",
        "epochs": 300,
    })
    snapshot = ensure_dataset_revision({
        "schema_version": 3,
        "snapshot_id": "snapshot-one",
        "counts": {"train": 80, "validation": 10, "test": 10, "total": 100},
        "actual_ratios": {"train": 80.0, "validation": 10.0, "test": 10.0},
        "requested": {"test_source": "explicit"},
        "test_seed": 7,
        "validation_seed": 11,
        "label_schema": [],
        "images": [],
    })
    revision = dataset_revision_document(snapshot)
    artifacts.atomic_write_json(task_id, "snapshot.json", snapshot)
    artifacts.atomic_write_json(task_id, "dataset-revision.json", revision)

    bundle = artifacts.artifact_path(task_id, "work/bundle")
    (bundle / "dataset").mkdir(parents=True)
    (bundle / "dataset" / "data.yaml").write_text(
        "path: .\ntrain: images/train\nval: images/validation\nnames: {0: fire}\n",
        encoding="utf-8",
    )
    artifacts.atomic_write_json(task_id, "work/bundle/snapshot.json", snapshot)
    artifacts.atomic_write_json(
        task_id,
        "work/bundle/dataset-revision.json",
        revision,
    )
    bundle_snapshot = artifacts.artifact_path(task_id, "work/bundle/snapshot.json")
    bundle_revision = artifacts.artifact_path(
        task_id,
        "work/bundle/dataset-revision.json",
    )
    artifacts.atomic_write_json(task_id, "work/bundle/manifest.json", {
        "schema_version": 3,
        "snapshot_id": snapshot["snapshot_id"],
        "dataset_revision_schema_version": snapshot[
            "dataset_revision_schema_version"
        ],
        "canonical_annotation_schema_version": snapshot[
            "canonical_annotation_schema_version"
        ],
        "dataset_revision_id": snapshot["dataset_revision_id"],
        "snapshot_ref": "snapshot.json",
        "snapshot_sha256": hashlib.sha256(
            bundle_snapshot.read_bytes()
        ).hexdigest(),
        "dataset_revision_ref": "dataset-revision.json",
        "dataset_revision_sha256": hashlib.sha256(
            bundle_revision.read_bytes()
        ).hexdigest(),
        "data_yaml_ref": "dataset/data.yaml",
        "splits": {"train": [], "validation": [], "test": []},
    })

    trained_model = project / "models" / f"train_{task_id}_best.pt"
    trained_model.write_bytes(b"already-verified-model")
    completed_job = {
        "id": task_id,
        "task_id": task_id,
        "status": "done",
        "message": "训练达到质量目标，模型产物校验通过",
        "artifact_verified": True,
        "verified_models": [str(trained_model)],
        "best_path": str(trained_model),
        "snapshot_id": snapshot["snapshot_id"],
        "dataset_revision_id": snapshot["dataset_revision_id"],
        "asset_algorithm_id": "algorithm-one",
        "base_version_id": None,
        "base_version_name": None,
        "base_selection_reason": "mother_model",
        "requested_device": "cuda:0",
        "assigned_device": "cuda:0",
        "actual_device": "cuda:0",
        "device_validation": {"ok": True},
        "actual_train_params": {"epochs": 300},
        "current_epoch": 180,
        "total_epochs": 300,
        "progress_percent": 100,
        "training_outcome": "target_reached",
        "completion_reason": "quality_target_reached",
        "finished_at": "2026-09-11 20:25:26",
        "training_report": {
            "metrics": {
                "metrics/precision(B)": 0.889,
                "metrics/recall(B)": 0.851,
                "metrics/mAP50(B)": 0.897,
                "metrics/mAP50-95(B)": 0.572,
            },
            "test_result": {"status": "not_requested", "metrics": {}},
        },
    }
    (project / "jobs" / task_id / "job.json").write_text(json.dumps(completed_job), encoding="utf-8")

    repository.create(TaskRecord.new(
        task_id,
        project_id,
        TaskKind.TRAINING,
        "payload.json",
        "training:gpu:0",
        required_capabilities=("training.ultralytics",),
    ))
    first = repository.claim_next("worker-before-crash", [TaskKind.TRAINING], {"training.ultralytics"})
    assert first is not None
    with repository._connect() as database:
        database.execute(
            "UPDATE tasks SET lease_expires_at=? WHERE task_id=?",
            ("2000-01-01T00:00:00+00:00", task_id),
        )
    assert repository.release_expired() == 1
    second = repository.claim_next("worker-after-restart", [TaskKind.TRAINING], {"training.ultralytics"})
    assert second is not None and second.task.attempt >= 2

    def must_not_retrain(*_args, **_kwargs):
        raise AssertionError("completed verified training must be finalized, not trained again")

    publish_requests = []
    monkeypatch.setattr(
        "platform_core.training_tasks._request_external_publish_after_training",
        lambda **kwargs: publish_requests.append(dict(kwargs)) or True,
    )

    handler = TrainingHandler(data_dir, process_runner=must_not_retrain)
    context = WorkerContext(second.task, second, repository, artifacts)
    status, result_ref = handler.recover(context)
    context.finish(status, result_ref)

    task = repository.get(task_id)
    assert task is not None and task.status is TaskStatus.SUCCEEDED
    assert task.progress == 100
    result = artifacts.read_json(task_id, "result.json")
    assert result["completed_epochs"] == 180
    assert result["requested_epochs"] == 300
    assert result["training_outcome"] == "target_reached"
    assert result["completion_reason"] == "quality_target_reached"
    assert result["verified_models"][0]["size_bytes"] > 0
    versions = list_algorithms(project / "algorithms.json")[0]["versions"]
    assert len(versions) == 1
    assert versions[0]["task_id"] == task_id
    assert versions[0]["training_status"] == "SUCCEEDED"
    assert result["external_publish_requested"] is True
    assert len(publish_requests) == 1
    assert publish_requests[0]["algorithm_id"] == "algorithm-one"
    assert publish_requests[0]["version_id"] == versions[0]["id"]
