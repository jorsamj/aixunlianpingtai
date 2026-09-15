import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading
import time

import pytest

import platform_core.algorithms as algorithms_module
from platform_core.algorithms import attach_version, choose_iteration_base
from platform_core.errors import PlatformError


def test_latest_missing_artifact_falls_back_to_previous_usable(tmp_path: Path):
    usable = tmp_path / "best.pt"
    usable.write_bytes(b"real-checkpoint-placeholder-for-selection-test")
    versions = [
        {
            "id": "v3",
            "version_name": "20260828120000",
            "finished_at": "2026-08-28T12:00:00",
            "best_path": str(tmp_path / "missing.pt"),
        },
        {
            "id": "v2",
            "version_name": "20260827120000",
            "finished_at": "2026-08-27T12:00:00",
            "best_path": str(usable),
        },
    ]

    result = choose_iteration_base(versions, "yolo11n.pt")

    assert result["base_version_id"] == "v2"
    assert result["base_model_path"] == str(usable.resolve())
    assert result["base_selection_reason"] == "latest_usable_version"


def test_no_usable_history_uses_mother_model():
    result = choose_iteration_base([], "yolo11n.pt")

    assert result["base_version_id"] is None
    assert result["base_model_path"] == "yolo11n.pt"
    assert result["base_selection_reason"] == "mother_model"


def test_deployment_artifacts_are_never_used_for_iteration(tmp_path: Path):
    converted = tmp_path / "model.onnx"
    converted.write_bytes(b"converted")

    result = choose_iteration_base(
        [{"id": "v1", "version_name": "20260828120000", "stored_path": str(converted)}],
        "yolo11n.pt",
    )

    assert result["base_version_id"] is None
    assert result["base_model_kind"] == "mother_model"


def test_strict_iteration_base_rejects_unusable_immediate_latest(tmp_path: Path):
    usable_previous = tmp_path / "previous.pt"
    usable_previous.write_bytes(b"previous")
    versions = [
        {
            "id": "v3",
            "version_name": "20260828120000",
            "finished_at": "2026-08-28T12:00:00",
            "stored_path": str(tmp_path / "missing.pt"),
            "artifact_verified": False,
        },
        {
            "id": "v2",
            "version_name": "20260827120000",
            "finished_at": "2026-08-27T12:00:00",
            "stored_path": str(usable_previous),
            "artifact_verified": True,
        },
    ]

    with pytest.raises(PlatformError) as error:
        choose_iteration_base(versions, "yolo11n.pt", strict_latest=True)

    assert error.value.code == "ITERATION_BASE_UNAVAILABLE"
    assert "20260828120000" in error.value.detail


def test_strict_iteration_base_uses_latest_only_and_validator(tmp_path: Path):
    latest = tmp_path / "latest.pt"
    latest.write_bytes(b"latest")
    previous = tmp_path / "previous.pt"
    previous.write_bytes(b"previous")
    versions = [
        {
            "id": "v3",
            "version_name": "20260828120000",
            "finished_at": "2026-08-28T12:00:00",
            "stored_path": str(latest),
            "artifact_verified": True,
            "training_status": "SUCCEEDED",
            "trainable": True,
            "framework": "ultralytics",
        },
        {
            "id": "v2",
            "version_name": "20260827120000",
            "finished_at": "2026-08-27T12:00:00",
            "stored_path": str(previous),
            "artifact_verified": True,
            "training_status": "SUCCEEDED",
            "trainable": True,
            "framework": "ultralytics",
        },
    ]

    result = choose_iteration_base(
        versions,
        "yolo11n.pt",
        strict_latest=True,
        artifact_validator=lambda path: path == latest.resolve(),
    )

    assert result["base_version_id"] == "v3"
    assert result["base_selection_reason"] == "latest_verified_version"


def test_latest_trainable_ignores_failed_and_cancelled_attempts(tmp_path: Path):
    good = tmp_path / "good.pt"
    good.write_bytes(b"weights")
    versions = [
        {
            "id": "failed-newer",
            "training_status": "FAILED",
            "created_at": "2026-08-31T12:00:00Z",
            "stored_path": "",
        },
        {
            "id": "cancelled",
            "training_status": "CANCELLED",
            "created_at": "2026-08-31T11:00:00Z",
            "stored_path": "",
        },
        {
            "id": "good",
            "training_status": "SUCCEEDED",
            "artifact_verified": True,
            "trainable": True,
            "framework": "ultralytics",
            "created_at": "2026-08-31T10:00:00Z",
            "stored_path": str(good),
        },
    ]

    selected = choose_iteration_base(
        versions,
        "mother.pt",
        strict_latest=True,
        artifact_validator=lambda path: True,
    )

    assert selected["base_version_id"] == "good"


def test_attach_version_is_idempotent_for_training_task(tmp_path: Path):
    path = tmp_path / "algorithms.json"
    path.write_text(
        json.dumps([{"id": "algorithm-one", "name": "fire", "versions": []}]),
        encoding="utf-8",
    )
    version = {
        "id": "version-one",
        "task_id": "train-one",
        "job_id": "train-one",
        "training_status": "SUCCEEDED",
        "artifact_verified": True,
        "created_at": "2026-09-15T01:02:03+00:00",
    }

    first = attach_version(path, "algorithm-one", version)
    second = attach_version(path, "algorithm-one", {**version, "id": "duplicate-version"})

    stored = json.loads(path.read_text(encoding="utf-8"))[0]["versions"]
    assert first["id"] == "version-one"
    assert second["id"] == "version-one"
    assert [row["task_id"] for row in stored] == ["train-one"]


def test_concurrent_training_finalizers_do_not_overwrite_versions(tmp_path, monkeypatch):
    path = tmp_path / "algorithms.json"
    path.write_text(
        json.dumps([{"id": "algorithm-one", "name": "fire", "versions": []}]),
        encoding="utf-8",
    )
    original_list = algorithms_module.list_algorithms
    start = threading.Barrier(2)

    def slow_list(target):
        rows = original_list(target)
        time.sleep(0.05)
        return rows

    monkeypatch.setattr(algorithms_module, "list_algorithms", slow_list)

    def archive(task_id):
        start.wait(timeout=2)
        return attach_version(
            path,
            "algorithm-one",
            {
                "id": f"version-{task_id}",
                "task_id": task_id,
                "training_status": "SUCCEEDED",
                "finished_at": f"2026-09-15T00:00:0{task_id[-1]}+00:00",
            },
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(archive, ("task-1", "task-2")))

    versions = original_list(path)[0]["versions"]
    assert {row["task_id"] for row in versions} == {"task-1", "task-2"}
