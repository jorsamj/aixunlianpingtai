import hashlib
import json
from pathlib import Path

from PIL import Image

from platform_core.algorithms import list_algorithms
from platform_core.task_runtime import ArtifactStore, Scheduler, TaskKind, TaskRecord, TaskRepository, TaskStatus
from platform_core.storage import StorageSourceRepository
import platform_core.training_tasks as training_tasks_module
from platform_core.training_tasks import TrainingHandler


def test_training_handler_prepares_snapshot_runs_and_commits_verified_result(tmp_path: Path, monkeypatch):
    data_dir = tmp_path / "data"
    project_id = "project-one"
    project = data_dir / "projects" / project_id
    (project / "uploads").mkdir(parents=True)
    (project / "annotations").mkdir()
    (project / "jobs").mkdir()
    (project / "models").mkdir()
    (project / "meta.json").write_text(
        json.dumps({"id": project_id, "labels": ["fire"], "label_meta": [{"code": "fire", "class_id": 0}]}),
        encoding="utf-8",
    )
    images = []
    external_root = tmp_path / "external-materials"
    (external_root / "incoming").mkdir(parents=True)
    for index in range(8):
        image_id = f"image-{index}"
        stored_name = f"{image_id}.jpg"
        image_path = project / "uploads" / stored_name
        Image.new("RGB", (64, 64), (index * 10, 10, 10)).save(image_path, format="JPEG")
        boxes = [{"label": "fire", "class_id": 0, "x1": 5, "y1": 5, "x2": 40, "y2": 40}]
        images.append(
            {
                "id": image_id,
                "dataset_id": "pool",
                "stored_name": stored_name,
                "width": 64,
                "height": 64,
                "content_sha256": hashlib.sha256(image_path.read_bytes()).hexdigest(),
                "group_id": image_id,
                "processing_status": "processed",
                "annotated": True,
            }
        )
        if index in {1, 4}:
            external_path = external_root / "incoming" / stored_name
            image_path.replace(external_path)
            images[-1].update(
                {
                    "storage_source_id": "external_local",
                    "storage_type": "local",
                    "object_key": f"incoming/{stored_name}",
                }
            )
        (project / "annotations" / f"{image_id}.json").write_text(
            json.dumps({"image_id": image_id, "boxes": boxes}), encoding="utf-8"
        )
    (project / "images.json").write_text(json.dumps(images), encoding="utf-8")
    (project / "algorithms.json").write_text(
        json.dumps([{"id": "algorithm-one", "name": "fire", "versions": []}]), encoding="utf-8"
    )
    StorageSourceRepository(data_dir / "storage" / "storage_sources.sqlite3").create(
        {
            "id": "external_local",
            "name": "External local",
            "type": "local",
            "config": {"root": str(external_root)},
        }
    )

    runtime = data_dir / "task_runtime"
    repository = TaskRepository(runtime / "tasks.sqlite3")
    artifacts = ArtifactStore(runtime / "artifacts")
    payload = {
        "schema_version": 3,
        "framework": "ultralytics",
        "target": "local",
        "algorithm_asset_id": "algorithm-one",
        "external_analysis_id": "analysis-durable-1",
        "model": "mother.pt",
        "split_mode": "random_test_from_training_pool",
        "train_image_ids": [f"image-{index}" for index in range(7)],
        "test_image_ids": [],
        "experiment_percent": 25,
        "validation_percent": 20,
        "seed": 7,
        "epochs": 1,
        "imgsz": 64,
        "batch": 2,
        "gpu_policy": "auto",
        "device": "cpu",
        "eval_metric": "map50",
        "continue_threshold": 0.60,
        "stop_threshold": 0.90,
    }
    artifacts.atomic_write_json("task-one", "payload.json", payload)
    repository.create(
        TaskRecord.new(
            "task-one",
            project_id,
            TaskKind.TRAINING,
            "payload.json",
            "training:cpu",
            required_capabilities=("training.ultralytics",),
        )
    )

    observed_argv = {}

    def fake_runner(context, argv, job_file):
        observed_argv["value"] = list(argv)
        model = project / "models" / "fake-trained.pt"
        model.parent.mkdir(parents=True, exist_ok=True)
        model.write_bytes(b"verified-model")
        job = json.loads(job_file.read_text(encoding="utf-8"))
        job.update(
            {
                "status": "done",
                "artifact_verified": True,
                "verified_models": [str(model)],
                "best_path": str(model),
                "training_outcome": "completed",
                "finished_at": "2026-09-15T01:02:03+00:00",
                "training_report": {
                    "metrics": {"metrics/mAP50(B)": 0.75},
                    "test_result": {
                        "status": "succeeded",
                        "metrics": {
                            "metrics/precision(B)": 0.80,
                            "metrics/recall(B)": 0.78,
                            "metrics/mAP50(B)": 0.75,
                            "metrics/mAP50-95(B)": 0.55,
                        },
                        "per_class": [],
                        "weak_labels": [],
                        "error_samples": [],
                    },
                },
            }
        )
        job_file.write_text(json.dumps(job), encoding="utf-8")
        return job

    # This integration owns Durable TrainingHandler snapshot/materialization/finalization
    # truth. Device-runtime probing has its own focused tests and would otherwise
    # require installing the full Torch runtime in this lightweight CI job.
    monkeypatch.setattr(
        training_tasks_module,
        "validate_training_device",
        lambda _python, device: {
            "requested_device": device,
            "assigned_device": device,
            "actual_device": device,
            "torch_version": "test-runtime",
            "cuda_available": False,
            "gpus": [],
        },
    )

    handler = TrainingHandler(data_dir, process_runner=fake_runner)
    scheduler = Scheduler(
        repository,
        artifacts,
        "training-test",
        {TaskKind.TRAINING: handler},
        {"training.ultralytics"},
    )
    assert scheduler.run_once() is True
    task = repository.get("task-one")
    assert task is not None and task.status is TaskStatus.SUCCEEDED, task.error if task else "missing task"
    worker_argv = observed_argv["value"]
    assert worker_argv[worker_argv.index("--gpu-policy") + 1] == "auto"
    resource_context = artifacts.read_json("task-one", "resource-context.json")
    assert resource_context["train_image_count"] == 4
    assert resource_context["decoded_dataset_bytes"] == 7 * (64 ** 2) * 3
    result = artifacts.read_json("task-one", task.result_ref)
    assert result["counts"] == {"train": 4, "validation": 1, "test": 2, "total": 7}
    snapshot = artifacts.read_json("task-one", "snapshot.json")
    assert "image-7" not in set(snapshot["ids"]["train"] + snapshot["ids"]["validation"] + snapshot["ids"]["test"])
    assert result["base_selection_reason"] == "mother_model"
    assert result["verified_models"][0]["size_bytes"] > 0
    assert (artifacts.artifact_path("task-one", "work/bundle/manifest.json")).is_file()
    bundle_manifest = artifacts.read_json("task-one", "work/bundle/manifest.json")
    bundled_ids = {
        item["image_id"]
        for role in ("train", "validation", "test")
        for item in bundle_manifest["splits"][role]
    }
    assert "image-1" in bundled_ids and "image-4" in bundled_ids
    assert not (project / "uploads" / "image-1.jpg").exists()
    versions = list_algorithms(project / "algorithms.json")[0]["versions"]
    assert len(versions) == 1
    assert versions[0]["training_status"] == "SUCCEEDED"
    assert len(str(versions[0]["version_name"])) == 14
    assert str(versions[0]["version_name"]).isdigit()
    assert versions[0]["version_no"] == versions[0]["version_name"]
    assert versions[0]["external_analysis_id"] == "analysis-durable-1"
    assert versions[0]["snapshot_id"] == result["snapshot_id"]
    assert versions[0]["dataset_revision_id"] == result["dataset_revision_id"]
    assert versions[0]["training_lineage"]["task_id"] == "task-one"
    assert versions[0]["training_lineage"]["snapshot_id"] == result["snapshot_id"]
    assert versions[0]["training_lineage"]["dataset_revision_id"] == result["dataset_revision_id"]
    assert versions[0]["evaluation"]["status"] == "succeeded"
    assert versions[0]["evaluation"]["metrics"]["metrics/mAP50(B)"] == 0.75
    assert versions[0]["iteration_decision"]["decision"] == "continue_training"
    assert versions[0]["iteration_decision"]["quality_gate"]["continue_threshold"] == 0.6
    assert versions[0]["iteration_decision"]["quality_gate"]["stop_threshold"] == 0.9
    assert result["training_lineage"] == versions[0]["training_lineage"]
    assert result["evaluation"] == versions[0]["evaluation"]
    assert result["iteration_decision"] == versions[0]["iteration_decision"]
