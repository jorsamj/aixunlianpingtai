import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading
import time

import pytest

import platform_core.algorithms as algorithms_module
from platform_core.algorithms import (
    attach_version,
    choose_algorithm_iteration_base,
    choose_iteration_base,
    delete_algorithm_version,
    resolve_current_version_id,
    rollback_algorithm_version,
    update_algorithm_version,
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

    stored = algorithms_module.list_algorithms(path)[0]["versions"]
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


def _trainable_version(tmp_path: Path, version_id: str, finished_at: str) -> dict:
    model = tmp_path / f"{version_id}.pt"
    model.write_bytes(version_id.encode("utf-8"))
    return {
        "id": version_id,
        "version_name": version_id.upper(),
        "finished_at": finished_at,
        "stored_path": str(model),
        "artifact_verified": True,
        "training_status": "SUCCEEDED",
        "trainable": True,
        "framework": "ultralytics",
    }


def test_historical_algorithm_projects_latest_trainable_version_without_rewriting(tmp_path: Path):
    older = _trainable_version(tmp_path, "v3", "2026-09-13T00:00:00+00:00")
    newer = _trainable_version(tmp_path, "v5", "2026-09-15T00:00:00+00:00")
    algorithm = {"id": "algorithm-one", "versions": [older, newer]}

    assert resolve_current_version_id(algorithm, framework="ultralytics") == "v5"
    assert "current_version_id" not in algorithm


def test_rollback_always_deletes_current_version_and_records_audit(tmp_path: Path):
    path = tmp_path / "algorithms.json"
    versions = [
        _trainable_version(tmp_path, "v5", "2026-09-15T00:00:00+00:00"),
        _trainable_version(tmp_path, "v3", "2026-09-13T00:00:00+00:00"),
    ]
    path.write_text(json.dumps([{"id": "algorithm-one", "name": "fire", "versions": versions}]), encoding="utf-8")

    result = rollback_algorithm_version(
        path,
        "algorithm-one",
        "v3",
        now="2026-09-15T01:02:03+00:00",
        delete_current_version=False,
        operator="local_user",
        expected_current_version_id="v5",
    )

    stored = algorithms_module.list_algorithms(path)[0]
    assert result["previous_current_version_id"] == "v5"
    assert result["current_version_id"] == "v3"
    assert result["deleted_version_id"] == "v5"
    assert result["action"] == "rollback_and_delete"
    assert stored["current_version_id"] == "v3"
    assert {row["id"] for row in stored["versions"]} == {"v3"}
    operation = stored["version_operations"][-1]
    assert operation["algorithm_id"] == "algorithm-one"
    assert operation["from_version_id"] == "v5"
    assert operation["to_version_id"] == "v3"
    assert operation["deleted_version_id"] == "v5"
    assert operation["action"] == "rollback_and_delete"
    assert operation["operator"] == "local_user"
    assert operation["created_at"] == "2026-09-15T01:02:03+00:00"
    assert operation["cleanup_status"] == "cleanup_pending"


def test_rollback_and_delete_preflight_failure_is_atomic(tmp_path: Path):
    path = tmp_path / "algorithms.json"
    versions = [
        _trainable_version(tmp_path, "v5", "2026-09-15T00:00:00+00:00"),
        _trainable_version(tmp_path, "v3", "2026-09-13T00:00:00+00:00"),
    ]
    original = [{"id": "algorithm-one", "name": "fire", "current_version_id": "v5", "versions": versions}]
    path.write_text(json.dumps(original), encoding="utf-8")

    with pytest.raises(PlatformError) as error:
        rollback_algorithm_version(
            path,
            "algorithm-one",
            "v3",
            now="2026-09-15T01:02:03+00:00",
            delete_current_version=True,
            dependency_check=lambda _algorithm, _version: [
                {"kind": "MODEL_CONVERSION", "id": "convert-active", "reason": "该版本仍有运行中的模型转换任务"}
            ],
        )

    assert error.value.code == "ALGORITHM_VERSION_IN_USE"
    assert json.loads(path.read_text(encoding="utf-8")) == original
    assert algorithms_module.list_algorithms(path)[0]["current_version_id"] == original[0].get("current_version_id")


def test_rollback_and_delete_records_cleanup_failure_after_trusted_pointer_switch(tmp_path: Path):
    path = tmp_path / "algorithms.json"
    versions = [
        _trainable_version(tmp_path, "v5", "2026-09-15T00:00:00+00:00"),
        _trainable_version(tmp_path, "v3", "2026-09-13T00:00:00+00:00"),
    ]
    path.write_text(
        json.dumps([{"id": "algorithm-one", "name": "fire", "current_version_id": "v5", "versions": versions}]),
        encoding="utf-8",
    )

    result = rollback_algorithm_version(
        path,
        "algorithm-one",
        "v3",
        now="2026-09-15T01:02:03+00:00",
        delete_current_version=True,
        dependency_check=lambda _algorithm, _version: [],
        cleanup=lambda _algorithm, _version: {
            "status": "cleanup_failed",
            "targets": ["algorithm_versions/algorithm-one/v5"],
            "errors": ["permission denied"],
        },
    )

    stored = algorithms_module.list_algorithms(path)[0]
    assert result["current_version_id"] == "v3"
    assert result["deleted_version_id"] == "v5"
    assert result["cleanup_status"] == "cleanup_failed"
    assert {row["id"] for row in stored["versions"]} == {"v3"}
    assert stored["version_operations"][-1]["cleanup_status"] == "cleanup_failed"
    assert stored["version_operations"][-1]["cleanup_errors"] == ["permission denied"]


def test_iteration_base_uses_persisted_current_version_after_rollback(tmp_path: Path):
    v5 = _trainable_version(tmp_path, "v5", "2026-09-15T00:00:00+00:00")
    v3 = _trainable_version(tmp_path, "v3", "2026-09-13T00:00:00+00:00")
    algorithm = {"id": "algorithm-one", "current_version_id": "v3", "versions": [v5, v3]}

    selected = choose_algorithm_iteration_base(
        algorithm,
        "yolo11n.pt",
        strict_latest=True,
        artifact_validator=lambda path: path.is_file(),
    )

    assert selected["base_version_id"] == "v3"
    assert selected["base_selection_reason"] == "current_verified_version"


def test_attach_version_makes_new_version_current_and_preserves_base_as_parent_truth(tmp_path: Path):
    path = tmp_path / "algorithms.json"
    current = _trainable_version(tmp_path, "v3", "2026-09-13T00:00:00+00:00")
    path.write_text(
        json.dumps([{"id": "algorithm-one", "name": "fire", "current_version_id": "v3", "versions": [current]}]),
        encoding="utf-8",
    )
    next_version = {
        **_trainable_version(tmp_path, "v6", "2026-09-16T00:00:00+00:00"),
        "base_version_id": "v3",
    }

    attach_version(path, "algorithm-one", next_version)

    stored = algorithms_module.list_algorithms(path)[0]
    saved = next(row for row in stored["versions"] if row["id"] == "v6")
    assert stored["current_version_id"] == "v6"
    assert saved["base_version_id"] == "v3"
    assert "parent_version_id" not in saved


def test_version_patch_keeps_current_pointer_and_other_versions(tmp_path: Path):
    path = tmp_path / "algorithms.json"
    versions = [
        _trainable_version(tmp_path, "v6", "2026-09-16T00:00:00+00:00"),
        _trainable_version(tmp_path, "v3", "2026-09-13T00:00:00+00:00"),
    ]
    path.write_text(
        json.dumps([{"id": "algorithm-one", "current_version_id": "v6", "versions": versions}]),
        encoding="utf-8",
    )

    update_algorithm_version(
        path,
        "algorithm-one",
        "v6",
        {"auto_conversion": {"jobs": [{"id": "conversion-one"}]}},
        now="2026-09-16T01:00:00+00:00",
    )

    stored = algorithms_module.list_algorithms(path)[0]
    assert stored["current_version_id"] == "v6"
    assert {row["id"] for row in stored["versions"]} == {"v3", "v6"}
    current = next(row for row in stored["versions"] if row["id"] == "v6")
    assert current["auto_conversion"]["jobs"] == [{"id": "conversion-one"}]


def test_direct_delete_rejects_current_version_without_mutating_store(tmp_path: Path):
    path = tmp_path / "algorithms.json"
    current = _trainable_version(tmp_path, "v5", "2026-09-15T00:00:00+00:00")
    original = [{"id": "algorithm-one", "current_version_id": "v5", "versions": [current]}]
    path.write_text(json.dumps(original), encoding="utf-8")

    with pytest.raises(PlatformError) as error:
        delete_algorithm_version(path, "algorithm-one", "v5", now="2026-09-15T01:02:03+00:00")

    assert error.value.code == "ALGORITHM_CURRENT_VERSION_DELETE_FORBIDDEN"
    assert json.loads(path.read_text(encoding="utf-8")) == original
    assert algorithms_module.list_algorithms(path)[0]["current_version_id"] == original[0].get("current_version_id")


def test_direct_delete_historical_version_keeps_current_and_records_audit(tmp_path: Path):
    path = tmp_path / "algorithms.json"
    versions = [
        _trainable_version(tmp_path, "v5", "2026-09-15T00:00:00+00:00"),
        _trainable_version(tmp_path, "v3", "2026-09-13T00:00:00+00:00"),
    ]
    path.write_text(
        json.dumps([{"id": "algorithm-one", "current_version_id": "v5", "versions": versions}]),
        encoding="utf-8",
    )

    result = delete_algorithm_version(
        path,
        "algorithm-one",
        "v3",
        now="2026-09-15T01:02:03+00:00",
        cleanup=lambda _algorithm, _version: {"status": "cleanup_completed", "targets": [], "errors": []},
    )

    stored = algorithms_module.list_algorithms(path)[0]
    assert result["action"] == "delete_version"
    assert result["deleted_version_id"] == "v3"
    assert stored["current_version_id"] == "v5"
    assert [row["id"] for row in stored["versions"]] == ["v5"]
    assert stored["version_operations"][-1]["action"] == "delete_version"


def test_rollback_remote_delete_failure_keeps_local_versions_unchanged(tmp_path: Path):
    path = tmp_path / "algorithms.json"
    versions = [
        _trainable_version(tmp_path, "v5", "2026-09-15T00:00:00+00:00"),
        _trainable_version(tmp_path, "v3", "2026-09-13T00:00:00+00:00"),
    ]
    original = [{"id": "algorithm-one", "current_version_id": "v5", "versions": versions}]
    path.write_text(json.dumps(original), encoding="utf-8")

    def fail_remote(_algorithm, _version):
        raise PlatformError(
            "EXTERNAL_VERSION_DELETE_FAILED",
            "远端删除失败",
            "provider rejected deletion",
            "请修复远端状态后重试。",
            502,
        )

    with pytest.raises(PlatformError) as error:
        rollback_algorithm_version(
            path,
            "algorithm-one",
            "v3",
            now="2026-09-15T01:02:03+00:00",
            delete_current_version=True,
            expected_current_version_id="v5",
            dependency_check=lambda _algorithm, _version: [],
            remote_delete=fail_remote,
        )

    assert error.value.code == "EXTERNAL_VERSION_DELETE_FAILED"
    stored = algorithms_module.list_algorithms(path)[0]
    assert stored["current_version_id"] == "v5"
    assert {row["id"] for row in stored["versions"]} == {"v3", "v5"}
    assert not stored.get("version_operations")


def test_historical_version_remote_delete_failure_keeps_local_version(tmp_path: Path):
    path = tmp_path / "algorithms.json"
    versions = [
        _trainable_version(tmp_path, "v5", "2026-09-15T00:00:00+00:00"),
        _trainable_version(tmp_path, "v3", "2026-09-13T00:00:00+00:00"),
    ]
    path.write_text(
        json.dumps([{"id": "algorithm-one", "current_version_id": "v5", "versions": versions}]),
        encoding="utf-8",
    )

    def fail_remote(_algorithm, _version):
        raise RuntimeError("remote remove timeout")

    with pytest.raises(RuntimeError, match="remote remove timeout"):
        delete_algorithm_version(
            path,
            "algorithm-one",
            "v3",
            now="2026-09-15T01:02:03+00:00",
            dependency_check=lambda _algorithm, _version: [],
            remote_delete=fail_remote,
        )

    stored = algorithms_module.list_algorithms(path)[0]
    assert stored["current_version_id"] == "v5"
    assert {row["id"] for row in stored["versions"]} == {"v3", "v5"}
    assert not stored.get("version_operations")


def test_rollback_reports_divergence_when_remote_delete_succeeds_but_local_commit_fails(tmp_path: Path, monkeypatch):
    path = tmp_path / "algorithms.json"
    versions = [
        _trainable_version(tmp_path, "v5", "2026-09-15T00:00:00+00:00"),
        _trainable_version(tmp_path, "v3", "2026-09-13T00:00:00+00:00"),
    ]
    path.write_text(
        json.dumps([{"id": "algorithm-one", "current_version_id": "v5", "versions": versions}]),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        algorithms_module.AlgorithmSqlStore,
        "rollback_version",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("database commit failed")),
    )

    with pytest.raises(PlatformError) as error:
        rollback_algorithm_version(
            path,
            "algorithm-one",
            "v3",
            now="2026-09-15T01:02:03+00:00",
            expected_current_version_id="v5",
            dependency_check=lambda _algorithm, _version: [],
            remote_delete=lambda _algorithm, _version: {
                "required": True,
                "status": "deleted",
                "external_algo_version_id": "remote-v5",
            },
        )

    assert error.value.code == "ALGORITHM_ROLLBACK_LOCAL_COMMIT_FAILED_AFTER_REMOTE_DELETE"
    stored = algorithms_module.list_algorithms(path)[0]
    assert stored["current_version_id"] == "v5"
    assert {row["id"] for row in stored["versions"]} == {"v3", "v5"}


def test_direct_delete_reports_divergence_when_remote_delete_succeeds_but_local_commit_fails(tmp_path: Path, monkeypatch):
    path = tmp_path / "algorithms.json"
    versions = [
        _trainable_version(tmp_path, "v5", "2026-09-15T00:00:00+00:00"),
        _trainable_version(tmp_path, "v3", "2026-09-13T00:00:00+00:00"),
    ]
    path.write_text(
        json.dumps([{"id": "algorithm-one", "current_version_id": "v5", "versions": versions}]),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        algorithms_module.AlgorithmSqlStore,
        "delete_version_with_operation",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("database commit failed")),
    )

    with pytest.raises(PlatformError) as error:
        delete_algorithm_version(
            path,
            "algorithm-one",
            "v3",
            now="2026-09-15T01:02:03+00:00",
            dependency_check=lambda _algorithm, _version: [],
            remote_delete=lambda _algorithm, _version: {
                "required": True,
                "status": "deleted",
                "external_algo_version_id": "remote-v3",
            },
        )

    assert error.value.code == "ALGORITHM_DELETE_LOCAL_COMMIT_FAILED_AFTER_REMOTE_DELETE"
    stored = algorithms_module.list_algorithms(path)[0]
    assert stored["current_version_id"] == "v5"
    assert {row["id"] for row in stored["versions"]} == {"v3", "v5"}
