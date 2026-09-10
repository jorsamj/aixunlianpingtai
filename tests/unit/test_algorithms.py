from pathlib import Path

import pytest

from platform_core.algorithms import (
    attach_version,
    choose_iteration_base,
    create_algorithm,
    list_algorithms,
    rollback_current_version,
    update_algorithm,
)
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


def test_explicit_current_version_wins_over_newer_version(tmp_path: Path):
    v3 = tmp_path / "v3.pt"
    v5 = tmp_path / "v5.pt"
    v3.write_bytes(b"v3")
    v5.write_bytes(b"v5")
    versions = [
        {
            "id": "v5",
            "version_name": "20260910120000",
            "finished_at": "2026-09-10T12:00:00Z",
            "stored_path": str(v5),
            "artifact_verified": True,
            "training_status": "SUCCEEDED",
            "trainable": True,
            "framework": "ultralytics",
        },
        {
            "id": "v3",
            "version_name": "20260909120000",
            "finished_at": "2026-09-09T12:00:00Z",
            "stored_path": str(v3),
            "artifact_verified": True,
            "training_status": "SUCCEEDED",
            "trainable": True,
            "framework": "ultralytics",
        },
    ]

    selected = choose_iteration_base(
        versions,
        "mother.pt",
        strict_latest=True,
        current_version_id="v3",
        artifact_validator=lambda path: path.is_file(),
    )

    assert selected["base_version_id"] == "v3"
    assert selected["base_model_path"] == str(v3.resolve())
    assert selected["base_selection_reason"] == "current_verified_version"


def test_missing_explicit_current_version_fails_closed(tmp_path: Path):
    v5 = tmp_path / "v5.pt"
    v5.write_bytes(b"v5")
    versions = [{
        "id": "v5",
        "stored_path": str(v5),
        "artifact_verified": True,
        "training_status": "SUCCEEDED",
        "trainable": True,
        "framework": "ultralytics",
    }]

    with pytest.raises(PlatformError) as error:
        choose_iteration_base(
            versions,
            "mother.pt",
            strict_latest=True,
            current_version_id="missing",
            artifact_validator=lambda path: True,
        )

    assert error.value.code == "CURRENT_VERSION_UNAVAILABLE"


def test_algorithm_revision_increments_and_rejects_stale_update(tmp_path: Path):
    store = tmp_path / "algorithms.json"
    created = create_algorithm(store, {"name": "fire"}, "2026-09-10T00:00:00Z", "algo")
    assert created["revision"] == 1

    updated = update_algorithm(
        store,
        "algo",
        {"name": "fire-v2"},
        "2026-09-10T00:01:00Z",
        expected_revision=1,
    )
    assert updated["revision"] == 2

    with pytest.raises(PlatformError) as error:
        update_algorithm(
            store,
            "algo",
            {"name": "stale"},
            "2026-09-10T00:02:00Z",
            expected_revision=1,
        )
    assert error.value.code == "ALGORITHM_REVISION_CONFLICT"


def test_attach_version_is_idempotent_by_task_id_and_tracks_revision(tmp_path: Path):
    store = tmp_path / "algorithms.json"
    create_algorithm(store, {"name": "fire"}, "2026-09-10T00:00:00Z", "algo")
    checkpoint = tmp_path / "best.pt"
    checkpoint.write_bytes(b"weights")
    version = {
        "id": "v1",
        "task_id": "task-1",
        "stored_path": str(checkpoint),
        "training_status": "SUCCEEDED",
        "artifact_verified": True,
        "trainable": True,
        "framework": "ultralytics",
        "created_at": "2026-09-10T00:03:00Z",
    }

    first = attach_version(store, "algo", version)
    second = attach_version(store, "algo", {**version, "id": "different-id"})
    algorithm = list_algorithms(store)[0]

    assert first["id"] == "v1"
    assert second["id"] == "v1"
    assert len(algorithm["versions"]) == 1
    assert algorithm["current_version_id"] == "v1"
    assert algorithm["revision"] == 2


def test_rollback_moves_only_pointer_and_bumps_revision(tmp_path: Path):
    store = tmp_path / "algorithms.json"
    create_algorithm(store, {"name": "fire"}, "2026-09-10T00:00:00Z", "algo")
    for version_id in ("v1", "v2"):
        checkpoint = tmp_path / f"{version_id}.pt"
        checkpoint.write_bytes(version_id.encode())
        attach_version(store, "algo", {
            "id": version_id,
            "task_id": f"task-{version_id}",
            "stored_path": str(checkpoint),
            "training_status": "SUCCEEDED",
            "artifact_verified": True,
            "trainable": True,
            "framework": "ultralytics",
            "created_at": f"2026-09-10T00:0{1 if version_id == 'v1' else 2}:00Z",
        })

    before = list_algorithms(store)[0]
    result = rollback_current_version(
        store,
        "algo",
        "v1",
        actor="tester",
        expected_revision=before["revision"],
    )
    after = list_algorithms(store)[0]

    assert result["changed"] is True
    assert after["current_version_id"] == "v1"
    assert len(after["versions"]) == 2
    assert after["revision"] == before["revision"] + 1
