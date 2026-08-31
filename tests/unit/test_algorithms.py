from pathlib import Path

import pytest

from platform_core.algorithms import choose_iteration_base
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
