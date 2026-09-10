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


def _label_schema():
    return [
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
    ]


def _durable_training_version(
    tmp_path: Path,
    *,
    task_id: str = "task-manifest",
    version_id: str = "v1",
    snapshot_id: str = "snap-1",
    artifact_snapshot_id: str = "snap-1",
):
    task_root = tmp_path / "task_runtime" / "artifacts" / task_id
    outputs = task_root / "outputs"
    outputs.mkdir(parents=True)
    model = outputs / "best.pt"
    model.write_bytes(f"verified-training-weights-{version_id}".encode())
    labels = _label_schema()
    snapshot = {
        "snapshot_id": artifact_snapshot_id,
        "label_schema": labels,
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
                "model": "yolo11n.pt",
                "training_label_schema_snapshot": {
                    "schema_version": 1,
                    "labels": labels,
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    version = {
        "id": version_id,
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
    assert manifest["source_model"] == {
        "version_id": None,
        "sha256": None,
        "reference": "yolo11n.pt",
    }

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


def test_manifest_self_hash_tamper_is_blocked(tmp_path: Path):
    store = tmp_path / "algorithms.json"
    create_algorithm(store, {"name": "fire-smoke"}, "2026-09-10T11:00:00Z", "algo")
    _, version = _durable_training_version(tmp_path)
    attach_version(store, "algo", version)
    data = json.loads(store.read_text(encoding="utf-8"))
    data[0]["versions"][0]["artifact_manifest"]["names"][0] = "forged-fire"
    store.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    algorithm = list_algorithms(store)[0]

    with pytest.raises(PlatformError) as error:
        choose_iteration_base(
            algorithm["versions"],
            "mother.pt",
            strict_latest=True,
            current_version_id="v1",
        )

    assert error.value.code == "CURRENT_VERSION_UNAVAILABLE"
    assert "自身 SHA256" in error.value.detail


def test_snapshot_id_mismatch_blocks_version_publish(tmp_path: Path):
    store = tmp_path / "algorithms.json"
    create_algorithm(store, {"name": "fire-smoke"}, "2026-09-10T11:00:00Z", "algo")
    _, version = _durable_training_version(tmp_path, snapshot_id="wrong-snapshot")

    with pytest.raises(PlatformError) as error:
        attach_version(store, "algo", version)

    assert error.value.code == "TRAINING_ARTIFACT_MANIFEST_INVALID"
    assert "快照" in error.value.message
    assert list_algorithms(store)[0]["versions"] == []


def test_payload_and_snapshot_label_mapping_mismatch_blocks_publish(tmp_path: Path):
    store = tmp_path / "algorithms.json"
    create_algorithm(store, {"name": "fire-smoke"}, "2026-09-10T11:00:00Z", "algo")
    model, version = _durable_training_version(tmp_path)
    payload_path = model.parent.parent / "payload.json"
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    payload["training_label_schema_snapshot"]["labels"][0]["label_id"] = "wrong-label-id"
    payload_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(PlatformError) as error:
        attach_version(store, "algo", version)

    assert error.value.code == "TRAINING_ARTIFACT_MANIFEST_INVALID"
    assert "标签快照" in error.value.message


def test_iteration_version_pins_parent_model_hash_lineage(tmp_path: Path):
    store = tmp_path / "algorithms.json"
    create_algorithm(store, {"name": "fire-smoke"}, "2026-09-10T11:00:00Z", "algo")
    _, v1 = _durable_training_version(
        tmp_path,
        task_id="task-v1",
        version_id="v1",
        snapshot_id="snap-v1",
        artifact_snapshot_id="snap-v1",
    )
    first = attach_version(store, "algo", v1)
    _, v2 = _durable_training_version(
        tmp_path,
        task_id="task-v2",
        version_id="v2",
        snapshot_id="snap-v2",
        artifact_snapshot_id="snap-v2",
    )
    second = attach_version(store, "algo", v2)

    assert second["parent_version_id"] == "v1"
    assert second["artifact_manifest"]["source_model"]["version_id"] == "v1"
    assert second["artifact_manifest"]["source_model"]["sha256"] == first["artifact_manifest"]["model"]["sha256"]

    algorithm = list_algorithms(store)[0]
    selected = choose_iteration_base(
        algorithm["versions"],
        "mother.pt",
        strict_latest=True,
        current_version_id="v2",
    )
    assert selected["base_version_id"] == "v2"


def test_lineage_fails_closed_if_pinned_parent_manifest_disappears(tmp_path: Path):
    store = tmp_path / "algorithms.json"
    create_algorithm(store, {"name": "fire-smoke"}, "2026-09-10T11:00:00Z", "algo")
    _, v1 = _durable_training_version(
        tmp_path,
        task_id="task-v1",
        version_id="v1",
        snapshot_id="snap-v1",
        artifact_snapshot_id="snap-v1",
    )
    attach_version(store, "algo", v1)
    _, v2 = _durable_training_version(
        tmp_path,
        task_id="task-v2",
        version_id="v2",
        snapshot_id="snap-v2",
        artifact_snapshot_id="snap-v2",
    )
    attach_version(store, "algo", v2)
    data = json.loads(store.read_text(encoding="utf-8"))
    parent = next(row for row in data[0]["versions"] if row["id"] == "v1")
    parent.pop("artifact_manifest")
    store.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    algorithm = list_algorithms(store)[0]

    with pytest.raises(PlatformError) as error:
        choose_iteration_base(
            algorithm["versions"],
            "mother.pt",
            strict_latest=True,
            current_version_id="v2",
        )

    assert error.value.code == "CURRENT_VERSION_UNAVAILABLE"
    assert "父版本没有可验证" in error.value.detail


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


def test_idempotent_replay_does_not_mask_corrupted_model(tmp_path: Path):
    store = tmp_path / "algorithms.json"
    create_algorithm(store, {"name": "fire-smoke"}, "2026-09-10T11:00:00Z", "algo")
    model, version = _durable_training_version(tmp_path)
    attach_version(store, "algo", version)
    model.write_bytes(b"corrupted-before-post-processing-replay")

    with pytest.raises(PlatformError) as error:
        attach_version(store, "algo", {**version, "id": "replay"})

    assert error.value.code == "TRAINING_ARTIFACT_MANIFEST_INVALID"
