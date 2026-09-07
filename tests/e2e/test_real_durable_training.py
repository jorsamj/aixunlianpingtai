import hashlib
import json
import os
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from platform_core.task_runtime import ArtifactStore, Scheduler, TaskKind, TaskRecord, TaskRepository, TaskStatus
from platform_core.training_tasks import TrainingHandler


@pytest.mark.real_training
@pytest.mark.skipif(os.environ.get("RUN_REAL_TRAINING") != "1", reason="set RUN_REAL_TRAINING=1")
def test_real_durable_worker_produces_reloadable_yolo_model(tmp_path: Path):
    source_root = Path(__file__).resolve().parents[2]
    model = source_root / "yolo11n.pt"
    assert model.is_file() and model.stat().st_size > 0
    data_dir = tmp_path / "data"
    project_id = "real-project"
    project = data_dir / "projects" / project_id
    for name in ("uploads", "annotations", "jobs", "models"):
        (project / name).mkdir(parents=True, exist_ok=True)
    (project / "meta.json").write_text(
        json.dumps({"id": project_id, "labels": ["object"], "label_meta": [{"code": "object", "class_id": 0}]}),
        encoding="utf-8",
    )
    rows = []
    for index in range(8):
        image_id = f"real-{index}"
        stored_name = f"{image_id}.jpg"
        image_path = project / "uploads" / stored_name
        image = Image.new("RGB", (96, 96), "white")
        draw = ImageDraw.Draw(image)
        x1 = 10 + index
        draw.rectangle((x1, 15, x1 + 40, 65), fill=(220, 30, 30))
        image.save(image_path, format="JPEG")
        rows.append(
            {
                "id": image_id,
                "dataset_id": "pool",
                "stored_name": stored_name,
                "width": 96,
                "height": 96,
                "content_sha256": hashlib.sha256(image_path.read_bytes()).hexdigest(),
                "group_id": image_id,
                "processing_status": "processed",
                "annotated": True,
            }
        )
        (project / "annotations" / f"{image_id}.json").write_text(
            json.dumps({"image_id": image_id, "boxes": [{"label": "object", "class_id": 0, "x1": x1, "y1": 15, "x2": x1 + 40, "y2": 65}]}),
            encoding="utf-8",
        )
    (project / "images.json").write_text(json.dumps(rows), encoding="utf-8")
    (project / "algorithms.json").write_text(
        json.dumps([{"id": "real-algorithm", "name": "object detector", "versions": []}]), encoding="utf-8"
    )
    runtime = data_dir / "task_runtime"
    repository = TaskRepository(runtime / "tasks.sqlite3")
    artifacts = ArtifactStore(runtime / "artifacts")
    artifacts.atomic_write_json(
        "real-task",
        "payload.json",
        {
            "schema_version": 3,
            "framework": "ultralytics",
            "target": "local",
            "algorithm_asset_id": "real-algorithm",
            "model": str(model),
            "split_mode": "random_test_from_training_pool",
            "train_image_ids": [f"image-{index}" for index in range(8)],
            "test_image_ids": [],
            "experiment_percent": 25,
            "validation_percent": 20,
            "seed": 9,
            "epochs": 1,
            "imgsz": 64,
            "batch": 2,
            "device": "cpu",
            "workers": 0,
            "amp": False,
            "cache": "False",
        },
    )
    repository.create(
        TaskRecord.new(
            "real-task",
            project_id,
            TaskKind.TRAINING,
            "payload.json",
            "training:cpu",
            required_capabilities=("training.ultralytics",),
        )
    )
    scheduler = Scheduler(
        repository,
        artifacts,
        "real-worker",
        {TaskKind.TRAINING: TrainingHandler(data_dir)},
        {"training.ultralytics"},
        lease_seconds=60,
    )
    assert scheduler.run_once() is True
    task = repository.get("real-task")
    assert task is not None and task.status is TaskStatus.SUCCEEDED, task
    result = artifacts.read_json("real-task", task.result_ref)
    assert result["training_report"]["test_result"]["status"] == "succeeded"
    artifact = artifacts.artifact_path("real-task", result["verified_models"][0]["ref"])
    assert artifact.is_file() and artifact.stat().st_size > 0
    from ultralytics import YOLO

    assert YOLO(str(artifact)).model is not None
