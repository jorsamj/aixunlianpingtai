from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from platform_core.build_identity import resolve_build_id, service_matches_build
from platform_core.training_devices import resolve_direct_training_assignment
from platform_core.upgrade_guard import ensure_worker_build_compatible, write_worker_build_marker

ROOT = Path(__file__).resolve().parents[2]


def _active_task_database(data_dir: Path, status: str = "RUNNING") -> None:
    runtime = data_dir / "task_runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    database = sqlite3.connect(runtime / "tasks.sqlite3")
    database.execute(
        "CREATE TABLE tasks (task_id TEXT, kind TEXT, status TEXT, stage TEXT, updated_at TEXT)"
    )
    database.execute(
        "INSERT INTO tasks VALUES (?,?,?,?,?)",
        ("task-1", "TRAINING", status, "running", "2026-09-14T00:00:00+00:00"),
    )
    database.commit()
    database.close()


def test_same_version_requires_same_build_identity(monkeypatch, tmp_path):
    monkeypatch.setenv("MC_BUILD_REVISION", "build-current")
    assert resolve_build_id(tmp_path) == "build-current"
    assert service_matches_build("42.24.0", "build-current", "42.24.0", {"build_id": "build-current"})
    assert not service_matches_build("42.24.0", "build-current", "42.24.0", {"build_id": "build-old"})
    assert not service_matches_build("42.24.0", "build-current", "42.24.0", {})


def test_cross_build_worker_refuses_to_take_over_active_task(tmp_path):
    _active_task_database(tmp_path)
    write_worker_build_marker(tmp_path, "build-old")
    with pytest.raises(RuntimeError, match="跨 Build"):
        ensure_worker_build_compatible(tmp_path, "build-new")


def test_same_build_keeps_crash_recovery_available(tmp_path):
    _active_task_database(tmp_path)
    write_worker_build_marker(tmp_path, "build-current")
    state = ensure_worker_build_compatible(tmp_path, "build-current")
    assert state["build_changed"] is False
    assert state["active_tasks"][0]["task_id"] == "task-1"


def test_explicit_override_is_required_for_cross_build_active_recovery(tmp_path):
    _active_task_database(tmp_path)
    write_worker_build_marker(tmp_path, "build-old")
    state = ensure_worker_build_compatible(tmp_path, "build-new", allow_active_upgrade=True)
    assert state["build_changed"] is True
    assert len(state["active_tasks"]) == 1


def test_direct_remote_training_assignment_matches_new_worker_contract():
    assert resolve_direct_training_assignment("0", cuda_available=True, cuda_devices=2) == ("cuda:0", "cuda:0")
    assert resolve_direct_training_assignment("auto", cuda_available=True, cuda_devices=1) == ("auto", "cuda:0")
    assert resolve_direct_training_assignment("auto", cuda_available=False, cuda_devices=0) == ("auto", "cpu")
    with pytest.raises(ValueError, match="unavailable"):
        resolve_direct_training_assignment("cuda:2", cuda_available=True, cuda_devices=1)


def test_product_wiring_exposes_build_and_passes_remote_device_contract():
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    launcher = (ROOT / "launcher.py").read_text(encoding="utf-8")
    worker = (ROOT / "task_worker.py").read_text(encoding="utf-8")
    remote = (ROOT / "remote_train_server.py").read_text(encoding="utf-8")
    assert '"build_id": BUILD_ID' in app
    assert "service_matches_build(VERSION, BUILD_ID" in launcher
    assert "ensure_worker_build_compatible" in worker
    assert '"--assigned-device", assigned_device' in remote
    assert '"--requested-device", requested_device' in remote
