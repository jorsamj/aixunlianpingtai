from pathlib import Path
from types import SimpleNamespace

import pytest

import launcher
import task_worker
from platform_core.resource_discovery.tasks import (
    _environment_deep_scan_allowed,
    _require_model_roots,
)
from platform_core.task_runtime import Scheduler, TaskKind
from platform_core.worker_registry import resolve_worker_registration
from platform_core.worker_supervisor import BACKGROUND_ROLES, TRAINING_ROLES, isolated_role_groups


def test_launcher_starts_api_and_worker_with_same_data_root(monkeypatch, tmp_path):
    calls = []

    class FakeProcess:
        def __init__(self, command):
            self.command = command

    def fake_popen(command, **options):
        calls.append((command, options))
        return FakeProcess(command)

    data_dir = tmp_path / "shared data"
    monkeypatch.setenv("MC_TRAIN_DATA_DIR", str(data_dir))
    monkeypatch.setattr(launcher.subprocess, "Popen", fake_popen)
    worker, api = launcher.start_service_processes(Path("python"), {"PYTHONUTF8": "1"})

    assert len(calls) == 2
    worker_command, worker_options = calls[0]
    api_command, api_options = calls[1]
    assert worker_command[1:3] == ["task_worker.py", "--data-dir"]
    assert Path(worker_command[3]) == data_dir.resolve()
    assert worker_command[4:6] == ["--roles", "all"]
    assert api_command[1:4] == ["-m", "uvicorn", "app:app"]
    assert worker_options["shell"] is False
    assert api_options["shell"] is False
    assert worker.command == worker_command
    assert api.command == api_command


def test_all_role_compatibility_mode_isolates_training_from_background():
    groups = isolated_role_groups({"all"})

    assert groups == (TRAINING_ROLES, BACKGROUND_ROLES)
    assert TRAINING_ROLES == ("training",)
    assert "training" not in BACKGROUND_ROLES
    assert {"storage", "materials", "video", "annotation", "conversion", "deployment-test"}.issubset(
        set(BACKGROUND_ROLES)
    )


def test_task_worker_all_role_runtime_delegates_to_isolated_supervisor(monkeypatch, tmp_path):
    captured = {}

    monkeypatch.setattr(task_worker, "ensure_worker_build_compatible", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        task_worker,
        "resolve_node_identity",
        lambda: SimpleNamespace(node_id="test-node", hostname="test-host", source="test"),
    )

    def fake_supervisor(**kwargs):
        captured.update(kwargs)
        return 17

    monkeypatch.setattr(task_worker, "run_isolated_all_roles", fake_supervisor)

    result = task_worker.main(
        [
            "--data-dir",
            str(tmp_path),
            "--roles",
            "all",
            "--worker-id",
            "launcher-all-default",
        ]
    )

    assert result == 17
    assert captured["data_dir"] == tmp_path.resolve()
    assert captured["worker_id"] == "launcher-all-default"
    assert captured["once"] is False


def test_training_only_registry_cannot_claim_non_training_task_kinds(tmp_path):
    registration = resolve_worker_registration(tmp_path, {"training"})

    assert set(registration.handlers) == {TaskKind.TRAINING}
    assert registration.roles == frozenset({"training"})
    assert "training.ultralytics" in registration.capabilities


def test_scheduler_default_idle_poll_supports_subsecond_claim_cycle():
    scheduler = Scheduler(None, None, "training-worker", {}, set())

    assert scheduler.poll_seconds == pytest.approx(0.25)
    assert scheduler.poll_seconds <= 1.0


def test_auto_environment_discovery_without_explicit_roots_never_deep_scans():
    assert _environment_deep_scan_allowed("auto", [], 0) is False
    assert _environment_deep_scan_allowed("auto", [], 1) is False


def test_full_environment_discovery_requires_explicit_roots(tmp_path):
    with pytest.raises(ValueError, match="explicit root"):
        _environment_deep_scan_allowed("full", [], 0)

    assert _environment_deep_scan_allowed("full", [tmp_path], 0) is True


def test_model_discovery_requires_explicit_roots(tmp_path):
    with pytest.raises(ValueError, match="explicit root"):
        _require_model_roots([])

    _require_model_roots([tmp_path])
