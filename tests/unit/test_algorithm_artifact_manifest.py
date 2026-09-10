from __future__ import annotations

import json
from pathlib import Path

import pytest

from platform_core.algorithms import (
    attach_version,
    choose_iteration_base,
    create_algorithm,
    list_algorithms,
    update_algorithm,
)
from platform_core.errors import PlatformError


def _durable_training_version(tmp_path: Path, *, snapshot_id: str = "snap-1"):
    task_id = "task-manifest"
    task_root = tmp_path / "task_runtime" / "artifacts" / task_id
    outputs = task_root / "outputs"
    outputs.mkdir(parents=True)
    model = outputs / "best.pt"
    model.write_bytes(b"verified-training-weights")
    snapshot = {
        "snapshot_id": "snap-1",
        "label_schema": [
            {
                "label_id": "label-fire",
                "code": "fire",
                "display_name": "明火",
                "platform_class_id": 7,
                "yolo_class_id": 0,
            },
            {
                "label_id": "label-smoke",
                "code": "smoke",
                "display_name": "烟雾",
                "platform_class_id": 11,
                "yolo_class_id": 1,
            },
        ],
    }
    (task_root / "snapshot.json").write_text(
        json.dumps(snapshot, ensure_ascii=False), encoding="utf-8"
    )
    (task_root / "payload.json").write_text(
        json.dumps(
            {
                "framework": "ultralytics",
                "task_type": "detect",
                "imgsz": 960,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    version = {
        "id": "v1",
        "task_id": task_id,
        "stored_path": str(model),
        "snapshot_id": snapshot_id,
        "training_status": "SUCCEEDED",
        "artifact_verified": True,
        "trainable": True,
        "framework": "ultralytics",
        "created_at": "2026-09-10T12:00:00Z",
    }
    return model, version


def test_attach_training_version_freezes_model_and_label_manifest(tmp_path: Path):
    store = tmp_path / "algorithms.json"
    create_algorithm(store, {"name": "fire-smoke"}, "2026-09-10T11:00:00Z", "algo")
    model, version = _durable_training_version(tmp_path)

    attached = attach_version(store, "algo", version, expected_revision=1)
    manifest = attached["artifact_manifest"]

    assert manifest["task_id"] == "task-manifest"
    assert manifest["framework"] == "ultralytics"
    assert manifest["task_type"] == "detect"
    assert manifest["input_size"] == 960
    assert manifest["snapshot_id"] == "snap-1"
    assert manifest["num_classes"] == 2
    assert manifest["names"] == ["fire", "smoke"]
    assert [row["label_id"] for row in manifest["labels"]] == ["label-fire", "label-smoke"]
    assert [row["yolo_class_id"] for row in manifest["labels"]] == [0, 1]
    assert manifest["model"]["name"] == "best.pt"
    assert manifest["model"]["size_bytes"] == model.stat().st_size
    assert len(manifest["model"]["sha256"]) == 64
    assert len(manifest["manifest_sha256"]) == 64

    persisted = list_algorithms(store)[0]["versions"][0]
    assert persisted["artifact_manifest"] == manifest


def test_model_tamper_is_blocked_before_iteration_training(tmp_path: Path):
    store = tmp_path / "algorithms.json"
    create_algorithm(store, {"name": "fire-smoke"}, "2026-09-10T11:00:00Z", "algo")
    model, version = _durable_training_version(tmp_path)
    attach_version(store, "algo", version)
    algorithm = list_algorithms(store)[0]

    model.write_bytes(b"tampered-after-version-publish")

    with pytest.raises(PlatformError) as error:
        choose_iteration_base(
            algorithm["versions"],
            "mother.pt",
            strict_latest=True,
            current_version_id="v1",
            artifact_validator=lambda path: path.is_file(),
        )

    assert error.value.code == "CURRENT_VERSION_UNAVAILABLE"
    assert "artifact manifest" in error.value.detail


def test_snapshot_id_mismatch_blocks_version_publish(tmp_path: Path):
    store = tmp_path / "algorithms.json"
    create_algorithm(store, {"name": "fire-smoke"}, "2026-09-10T11:00:00Z", "algo")
    _, version = _durable_training_version(tmp_path, snapshot_id="wrong-snapshot")

    with pytest.raises(PlatformError) as error:
        attach_version(store, "algo", version)

    assert error.value.code == "TRAINING_ARTIFACT_MANIFEST_INVALID"
    assert "快照" in error.value.message
    assert list_algorithms(store)[0]["versions"] == []


def test_idempotent_task_replay_keeps_original_manifest_and_revision(tmp_path: Path):
    store = tmp_path / "algorithms.json"
    create_algorithm(store, {"name": "fire-smoke"}, "2026-09-10T11:00:00Z", "algo")
    _, version = _durable_training_version(tmp_path)
    first = attach_version(store, "algo", version, expected_revision=1)
    update_algorithm(
        store,
        "algo",
        {"name": "fire-smoke-renamed"},
        "2026-09-10T12:10:00Z",
        expected_revision=2,
    )
    before = list_algorithms(store)[0]

    replay = attach_version(
        store,
        "algo",
        {**version, "id": "must-not-create-a-second-version"},
        expected_revision=1,
    )
    after = list_algorithms(store)[0]

    assert replay["id"] == first["id"] == "v1"
    assert replay["artifact_manifest"] == first["artifact_manifest"]
    assert len(after["versions"]) == 1
    assert after["revision"] == before["revision"]
