from __future__ import annotations

import json
from contextlib import nullcontext
from pathlib import Path

import pytest
from fastapi import HTTPException


def _setup(monkeypatch, tmp_path: Path):
    import app as platform

    path = tmp_path / "trusted-best.pt"
    path.write_bytes(b"trusted pretrained weight fixture")
    project = tmp_path / "project"
    (project / "snapshots").mkdir(parents=True)

    rows = [
        {"id": "training-a", "content_sha256": "a" * 64,
         "annotation_state": "unannotated", "box_count": 0},
        {"id": "training-b", "content_sha256": "b" * 64,
         "annotation_state": "unannotated", "box_count": 0},
    ]
    class Material:
        def get_many(self, ids):
            return [dict(row) for row in rows if row["id"] in ids]
    tasks = {}
    class Repository:
        def get(self, task_id):
            return tasks.get(task_id)
        def create(self, record):
            assert record.task_id not in tasks
            tasks[record.task_id] = record
            return record
    payloads = {}
    class Artifacts:
        def atomic_write_json(self, task_id, ref, content):
            payloads[task_id] = dict(content)
    monkeypatch.setattr(platform, "get_project", lambda _: {"id": "project"})
    monkeypatch.setattr(platform, "project_dir", lambda _: project)
    monkeypatch.setattr(platform, "_algorithm_version_for_action",
                        lambda p, a, v: ({"id": a}, {"id": v, "best_path": str(path)}))
    monkeypatch.setattr(platform, "material_store", lambda _: Material())
    monkeypatch.setattr(platform, "_annotation_label_catalog",
                        lambda _: [{"code": "person", "class_id": 0}])
    monkeypatch.setattr(platform, "shared_task_repository", lambda: Repository())
    monkeypatch.setattr(platform, "shared_task_artifacts", lambda: Artifacts())
    monkeypatch.setattr(platform, "_storage_source_fence", lambda: nullcontext())
    monkeypatch.setattr(platform, "public_annotation_task", lambda record: {
        "id": record.task_id, "status": record.status.value,
        "kind": record.kind.value, "required_capabilities": record.required_capabilities,
    })
    return platform, project, rows, tasks, payloads


def test_one_durable_annotation_task_is_created_for_existing_training_material(monkeypatch, tmp_path):
    platform, project, rows, tasks, payloads = _setup(monkeypatch, tmp_path)
    result = platform.create_hard_sample_mining("project", "algorithm", "v2",
        platform.HardSampleMiningCreateReq(image_ids=["training-a"], source="existing"))
    assert result["status"] == "QUEUED"
    assert result["kind"] == "AI_ANNOTATION"
    assert result["required_capabilities"] == ("mining.ultralytics",)
    request = payloads[result["id"]]
    assert request["mode"] == "hard_sample_yolo"
    assert request["source_hashes"] == {"training-a": "a" * 64}
    assert request["labels"] == ["person"]
    assert request["overwrite"] is False
    assert request["mining_model_sha256"]
    assert len(tasks) == 1


def test_frozen_test_or_same_bytes_cannot_be_mined(monkeypatch, tmp_path):
    platform, project, rows, tasks, payloads = _setup(monkeypatch, tmp_path)
    (project / "snapshots" / ("d" * 64 + ".json")).write_text(json.dumps({
        "test_image_ids": ["training-b"],
        "images": [{"image_id": "training-b", "content_sha256": "b" * 64}],
    }), encoding="utf-8")
    with pytest.raises(HTTPException) as ex:
        platform.create_hard_sample_mining("project", "algorithm", "v2",
            platform.HardSampleMiningCreateReq(image_ids=["training-b"]))
    assert ex.value.status_code == 409
    assert not tasks
    rows[0]["content_sha256"] = "b" * 64
    with pytest.raises(HTTPException) as ex:
        platform.create_hard_sample_mining("project", "algorithm", "v2",
            platform.HardSampleMiningCreateReq(image_ids=["training-a"]))
    assert ex.value.status_code == 409
    assert not payloads


def test_upload_retry_reuses_existing_task_identity(monkeypatch, tmp_path):
    platform, project, rows, tasks, payloads = _setup(monkeypatch, tmp_path)
    a = platform._enqueue_hard_sample_mining(
        "project", "algorithm", "v2", ["training-a"],
        source="upload", request_key="upload-123")
    b = platform._enqueue_hard_sample_mining(
        "project", "algorithm", "v2", ["training-a"],
        source="upload", request_key="upload-123")
    assert a == b
    assert len(tasks) == 1


def test_automatic_mining_never_relabels_already_annotated_material(monkeypatch, tmp_path):
    platform, project, rows, tasks, payloads = _setup(monkeypatch, tmp_path)
    rows[0]["annotation_state"] = "annotated"
    with pytest.raises(HTTPException) as ex:
        platform._enqueue_hard_sample_mining(
            "project", "algorithm", "v2", ["training-a"], source="upload")
    assert ex.value.status_code == 409
    assert not tasks
