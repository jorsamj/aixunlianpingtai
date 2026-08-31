import hashlib
import json
from pathlib import Path

from PIL import Image

from platform_core.task_runtime import ArtifactStore, Scheduler, TaskKind, TaskRecord, TaskRepository, TaskStatus
from platform_core.training_tasks import TrainingHandler


def test_training_handler_prepares_snapshot_runs_and_commits_verified_result(tmp_path: Path):
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
        (project / "annotations" / f"{image_id}.json").write_text(
            json.dumps({"image_id": image_id, "boxes": boxes}), encoding="utf-8"
        )
    (project / "images.json").write_text(json.dumps(images), encoding="utf-8")
    (project / "algorithms.json").write_text(
        json.dumps([{"id": "algorithm-one", "name": "fire", "versions": []}]), encoding="utf-8"
    )

    runtime = data_dir / "task_runtime"
    repository = TaskRepository(runtime / "tasks.sqlite3")
    artifacts = ArtifactStore(runtime / "artifacts")
    payload = {
        "schema_version": 2,
        "framework": "ultralytics",
        "target": "local",
        "algorithm_asset_id": "algorithm-one",
        "model": "mother.pt",
        "split_mode": "random_test_from_training_pool",
        "train_dataset_ids": ["pool"],
        "test_dataset_ids": [],
        "experiment_percent": 25,
        "validation_percent": 20,
        "seed": 7,
        "epochs": 1,
        "imgsz": 64,
        "batch": 2,
        "device": "cpu",
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

    def fake_runner(context, argv, job_file):
        model = context.artifacts.artifact_path(context.task.task_id, "fake-trained.pt")
        model.parent.mkdir(parents=True, exist_ok=True)
        model.write_bytes(b"verified-model")
        job = json.loads(job_file.read_text(encoding="utf-8"))
        job.update(
            {
                "status": "done",
                "artifact_verified": True,
                "verified_models": [str(model)],
                "best_path": str(model),
                "training_report": {"metrics": {"metrics/mAP50(B)": 0.75}},
            }
        )
        job_file.write_text(json.dumps(job), encoding="utf-8")
        return job

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
    assert task is not None and task.status is TaskStatus.SUCCEEDED
    result = artifacts.read_json("task-one", task.result_ref)
    assert result["counts"] == {"train": 5, "validation": 1, "test": 2, "total": 8}
    assert result["base_selection_reason"] == "mother_model"
    assert result["verified_models"][0]["size_bytes"] > 0
    assert (artifacts.artifact_path("task-one", "work/bundle/manifest.json")).is_file()
    versions = json.loads((project / "algorithms.json").read_text(encoding="utf-8"))[0]["versions"]
    assert len(versions) == 1
    assert versions[0]["training_status"] == "SUCCEEDED"
    assert versions[0]["snapshot_id"] == result["snapshot_id"]
