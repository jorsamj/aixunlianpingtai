from __future__ import annotations

import collections
import hashlib
import json
import os
import sqlite3
import stat
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tools import production_upgrade as upgrade_tool
from tools.production_upgrade import (
    UpgradeRefused,
    create_data_backup,
    load_backup_manifest,
    require_idle_tasks,
    restore_data_backup,
    restore_tracked_code_modes,
    verify_data_backup,
)

PREVIOUS_SHA = "1" * 40
TARGET_SHA = "2" * 40
FIXED_NOW = datetime(2026, 11, 24, 4, 5, 6, tzinfo=timezone.utc)
DiskUsage = collections.namedtuple("DiskUsage", "total used free")


# ---------------------------------------------------------------------------
# Fixtures/helpers
# ---------------------------------------------------------------------------

@contextmanager
def _connect(path: Path):
    """Commit on success and always close; Windows blocks os.replace on open handles."""
    connection = sqlite3.connect(path)
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_digest(manifest: dict) -> str:
    body = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    canonical = json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _write_manifest(backup_dir: Path, manifest: dict) -> None:
    manifest["manifest_sha256"] = _manifest_digest(manifest)
    (backup_dir / "backup.json").write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _write_task_db(data_dir: Path, statuses=("SUCCEEDED",)) -> Path:
    path = data_dir / "task_runtime" / "tasks.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    with _connect(path) as database:
        database.execute("CREATE TABLE tasks (task_id TEXT, status TEXT)")
        for index, status in enumerate(statuses):
            database.execute("INSERT INTO tasks VALUES (?,?)", (f"task-{index}", status))
    return path


def _write_project_db(
    data_dir: Path, project_id: str = "p1", name: str = "materials.sqlite3",
) -> Path:
    path = data_dir / "projects" / project_id / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with _connect(path) as database:
        database.execute("CREATE TABLE materials (material_id TEXT, label TEXT)")
        database.execute("INSERT INTO materials VALUES (?,?)", ("m-1", "fire"))
    return path


def _make_data_dir(tmp_path: Path) -> Path:
    """Two included control DBs plus excluded deep artifact content."""
    data_dir = tmp_path / "data"
    _write_task_db(data_dir)
    _write_project_db(data_dir)
    deep_artifact = data_dir / "projects" / "p1" / "task_artifacts" / "deep" / "big.bin"
    deep_artifact.parent.mkdir(parents=True)
    deep_artifact.write_bytes(b"x" * 4096)
    nested_artifact_db = data_dir / "task_runtime" / "artifacts" / "task-0" / "selection.sqlite3"
    nested_artifact_db.parent.mkdir(parents=True)
    with _connect(nested_artifact_db) as database:
        database.execute("CREATE TABLE selection (item TEXT)")
        database.execute("INSERT INTO selection VALUES ('frozen')")
    return data_dir


def _control_hashes(data_dir: Path) -> dict[str, str]:
    return {
        "task_runtime/tasks.sqlite3": _sha256(data_dir / "task_runtime" / "tasks.sqlite3"),
        "projects/p1/materials.sqlite3": _sha256(data_dir / "projects" / "p1" / "materials.sqlite3"),
    }


def _service_recorder(calls: list[tuple[str, ...]]):
    def fake_systemctl(*args: str) -> str:
        calls.append(tuple(args))
        return "active" if args[:1] == ("is-active",) else ""
    return fake_systemctl


# ---------------------------------------------------------------------------
# Existing upgrade-guard behavior (unchanged)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    os.name != "posix",
    reason="Git mode restoration is only meaningful with POSIX file-mode semantics",
)
def test_restore_only_git_tracked_file_modes_and_ancestor_directories(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    def git(*args):
        return subprocess.run(["git", *args], cwd=repo, capture_output=True, check=True)
    git("init", "-q")
    git("config", "user.name", "Upgrade Guard Test")
    git("config", "user.email", "test@example.invalid")
    folder = repo / "platform_core"
    folder.mkdir()
    code = folder / "service_nodes.py"
    code.write_text("pass\n")
    program = repo / "start.sh"
    program.write_text("#!/bin/sh\nexit 0\n")
    program.chmod(0o755)
    untracked = repo / "private.env"
    untracked.write_text("SECRET=value")
    untracked.chmod(0o600)
    git("add", "platform_core/service_nodes.py", "start.sh")
    git("commit", "-qm", "initial tracked files")

    code.chmod(0o600)
    program.chmod(0o600)
    folder.chmod(0o700)
    fixed = restore_tracked_code_modes(repo)
    assert fixed == 2
    assert stat.S_IMODE(code.stat().st_mode) == 0o644
    assert stat.S_IMODE(program.stat().st_mode) == 0o755
    assert stat.S_IMODE(folder.stat().st_mode) == 0o755
    assert stat.S_IMODE(untracked.stat().st_mode) == 0o600


def test_upgrade_refuses_queued_running_and_pending_confirmation_tasks(tmp_path):
    database = tmp_path / "task_runtime" / "tasks.sqlite3"
    database.parent.mkdir()
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE tasks (task_id TEXT, status TEXT)")
        for task_id, status in enumerate((
            "SUCCEEDED", "PARTIAL_SUCCESS", "FAILED", "CANCELLED",
            "BLOCKED_BY_ENVIRONMENT", "BLOCKED_BY_HARDWARE",
        )):
            db.execute("INSERT INTO tasks VALUES (?,?)", (f"terminal-{task_id}", status))
    # Six terminal states must all bind successfully and allow an idle upgrade.
    require_idle_tasks(tmp_path)
    for status in ("QUEUED", "RUNNING", "AWAITING_CONFIRMATION", "CANCEL_REQUESTED", "UNKNOWN", None):
        with sqlite3.connect(database) as db:
            db.execute("INSERT INTO tasks VALUES (?,?)", ("active-1", status))
        with pytest.raises(UpgradeRefused, match="ACTIVE_TASKS_BLOCK_UPGRADE"):
            require_idle_tasks(tmp_path)
        with sqlite3.connect(database) as db:
            db.execute("DELETE FROM tasks WHERE task_id='active-1'")


def test_missing_task_db_is_not_treated_as_idle(tmp_path):
    with pytest.raises(UpgradeRefused, match="TASK_DB_MISSING"):
        require_idle_tasks(tmp_path)


# ---------------------------------------------------------------------------
# A. Backup: consistency, manifest, verification
# ---------------------------------------------------------------------------

def test_create_data_backup_snapshots_control_databases_and_manifest(tmp_path):
    data_dir = _make_data_dir(tmp_path)
    backup_dir = tmp_path / "backup"
    result = create_data_backup(
        data_dir, backup_dir,
        previous_sha=PREVIOUS_SHA, target_sha=TARGET_SHA, now=FIXED_NOW,
    )

    manifest = load_backup_manifest(backup_dir)
    for key, value in manifest.items():
        assert result[key] == value
    assert result["backup_dir"] == str(backup_dir.resolve())
    assert result["verified"] is True
    assert result["entries_verified"] == 2

    assert manifest["schema_version"] == 1
    assert manifest["created_at"] == "2026-11-24T04:05:06Z"
    assert manifest["previous_sha"] == PREVIOUS_SHA
    assert manifest["target_sha"] == TARGET_SHA
    assert Path(manifest["data_dir"]) == data_dir.resolve()
    assert manifest["platform"] == sys.platform
    assert manifest["manifest_sha256"] == _manifest_digest(manifest)

    relative_paths = [entry["relative_path"] for entry in manifest["entries"]]
    assert relative_paths == [
        "projects/p1/materials.sqlite3",
        "task_runtime/tasks.sqlite3",
    ]
    assert manifest["total_bytes"] == sum(
        entry["size_bytes"] for entry in manifest["entries"]
    )
    for entry in manifest["entries"]:
        assert entry["size_bytes"] == (backup_dir / entry["relative_path"]).stat().st_size
        assert entry["sha256"] == _sha256(backup_dir / entry["relative_path"])
        assert entry["sqlite_quick_check"] == "ok"

    exclusions = json.dumps(manifest["exclusions"], ensure_ascii=False)
    assert "task_runtime/artifacts" in exclusions
    assert "material" in exclusions
    assert not (
        backup_dir / "projects" / "p1" / "task_artifacts" / "deep" / "big.bin"
    ).exists()
    assert not (
        backup_dir / "task_runtime" / "artifacts" / "task-0" / "selection.sqlite3"
    ).exists()
    assert not list(backup_dir.rglob("*-wal"))
    assert not list(backup_dir.rglob("*-shm"))

    verification = verify_data_backup(backup_dir)
    assert verification["ok"] is True
    assert verification["entries_verified"] == 2
    assert verification["total_bytes"] == manifest["total_bytes"]
    assert verification["manifest_sha256"] == manifest["manifest_sha256"]

    with _connect(backup_dir / "task_runtime" / "tasks.sqlite3") as database:
        assert database.execute("SELECT task_id FROM tasks").fetchall() == [("task-0",)]
    with _connect(backup_dir / "projects" / "p1" / "materials.sqlite3") as database:
        assert database.execute(
            "SELECT material_id, label FROM materials"
        ).fetchall() == [("m-1", "fire")]


def test_create_data_backup_captures_committed_wal_content(tmp_path):
    data_dir = tmp_path / "data"
    path = _write_task_db(data_dir)
    writer = sqlite3.connect(path)
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("INSERT INTO tasks VALUES ('wal-task','SUCCEEDED')")
        writer.commit()
        assert Path(str(path) + "-wal").is_file()

        backup_dir = tmp_path / "backup"
        create_data_backup(data_dir, backup_dir, previous_sha=PREVIOUS_SHA)
        with _connect(backup_dir / "task_runtime" / "tasks.sqlite3") as database:
            task_ids = {
                row[0] for row in database.execute("SELECT task_id FROM tasks").fetchall()
            }
        assert "wal-task" in task_ids
        assert "task-0" in task_ids
        # The snapshot must be a standalone database with no live WAL sidecars.
        assert not list(backup_dir.rglob("*-wal"))
    finally:
        writer.close()


# ---------------------------------------------------------------------------
# A. Backup: tamper/missing/corruption verification
# ---------------------------------------------------------------------------

def test_verify_data_backup_rejects_tampered_database_bytes(tmp_path):
    data_dir = _make_data_dir(tmp_path)
    backup_dir = tmp_path / "backup"
    create_data_backup(data_dir, backup_dir, previous_sha=PREVIOUS_SHA)
    target = backup_dir / "projects" / "p1" / "materials.sqlite3"
    original = target.read_bytes()
    tampered = bytearray(original)
    tampered[len(tampered) // 2] ^= 0xFF
    target.write_bytes(bytes(tampered))
    with pytest.raises(UpgradeRefused, match="BACKUP_FILE_SHA256_MISMATCH"):
        verify_data_backup(backup_dir)
    target.write_bytes(original)
    assert verify_data_backup(backup_dir)["ok"] is True


def test_verify_data_backup_rejects_missing_entry(tmp_path):
    data_dir = _make_data_dir(tmp_path)
    backup_dir = tmp_path / "backup"
    create_data_backup(data_dir, backup_dir, previous_sha=PREVIOUS_SHA)
    target = backup_dir / "projects" / "p1" / "materials.sqlite3"
    target.rename(tmp_path / "materials.moved")
    with pytest.raises(UpgradeRefused, match="BACKUP_FILE_MISSING"):
        verify_data_backup(backup_dir)


def test_verify_data_backup_rejects_corrupt_manifest_or_database(tmp_path):
    data_dir = _make_data_dir(tmp_path)
    backup_dir = tmp_path / "backup"
    create_data_backup(data_dir, backup_dir, previous_sha=PREVIOUS_SHA)
    manifest_path = backup_dir / "backup.json"
    original_manifest_text = manifest_path.read_text(encoding="utf-8")

    # Invalid JSON.
    manifest_path.write_text("{not json", encoding="utf-8")
    with pytest.raises(UpgradeRefused, match="BACKUP_MANIFEST_CORRUPT"):
        verify_data_backup(backup_dir)

    # Valid JSON with a stale digest.
    manifest = json.loads(original_manifest_text)
    manifest["previous_sha"] = "3" * 40
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(UpgradeRefused, match="BACKUP_MANIFEST_DIGEST_MISMATCH"):
        verify_data_backup(backup_dir)

    # A corrupted database whose size/SHA were re-recorded must still fail the
    # SQLite quick_check.
    manifest = json.loads(original_manifest_text)
    target = backup_dir / "projects" / "p1" / "materials.sqlite3"
    corrupted = bytearray(b"not a sqlite database")
    corrupted.extend(b"\0" * (len(target.read_bytes()) - len(corrupted)))
    target.write_bytes(bytes(corrupted))
    for entry in manifest["entries"]:
        if entry["relative_path"] == "projects/p1/materials.sqlite3":
            entry["size_bytes"] = target.stat().st_size
            entry["sha256"] = _sha256(target)
    manifest["total_bytes"] = sum(entry["size_bytes"] for entry in manifest["entries"])
    _write_manifest(backup_dir, manifest)
    with pytest.raises(UpgradeRefused, match="BACKUP_SQLITE_QUICK_CHECK_FAILED"):
        verify_data_backup(backup_dir)


# ---------------------------------------------------------------------------
# A. Backup: bounded preflight refusals
# ---------------------------------------------------------------------------

def test_create_data_backup_refuses_active_tasks(tmp_path):
    data_dir = tmp_path / "data"
    _write_task_db(data_dir, statuses=("RUNNING",))
    backup_dir = tmp_path / "backup"
    with pytest.raises(UpgradeRefused, match="ACTIVE_TASKS_BLOCK_UPGRADE"):
        create_data_backup(data_dir, backup_dir, previous_sha=PREVIOUS_SHA)
    assert not backup_dir.exists()


def test_create_data_backup_refuses_existing_or_nested_backup_dir(tmp_path):
    data_dir = _make_data_dir(tmp_path)
    non_empty = tmp_path / "non-empty"
    non_empty.mkdir()
    (non_empty / "keep.txt").write_text("operator data")
    with pytest.raises(UpgradeRefused, match="BACKUP_DIR_NOT_EMPTY"):
        create_data_backup(data_dir, non_empty, previous_sha=PREVIOUS_SHA)
    existing_empty = tmp_path / "existing-empty"
    existing_empty.mkdir()
    with pytest.raises(UpgradeRefused, match="BACKUP_DIR_EXISTS"):
        create_data_backup(data_dir, existing_empty, previous_sha=PREVIOUS_SHA)
    with pytest.raises(UpgradeRefused, match="BACKUP_DIR_INSIDE_DATA_DIR"):
        create_data_backup(
            data_dir, data_dir / "nested-backup", previous_sha=PREVIOUS_SHA,
        )
    with pytest.raises(UpgradeRefused, match="PREVIOUS_SHA_REQUIRED"):
        create_data_backup(data_dir, tmp_path / "bad-sha", previous_sha="not-a-sha")


def test_create_data_backup_refuses_too_large_or_empty_sources(tmp_path):
    data_dir = _make_data_dir(tmp_path)
    with pytest.raises(UpgradeRefused, match="BACKUP_TOO_LARGE"):
        create_data_backup(
            data_dir, tmp_path / "too-large",
            previous_sha=PREVIOUS_SHA, max_backup_bytes=1,
        )
    assert not (tmp_path / "too-large").exists()
    empty_data_dir = tmp_path / "empty-data"
    empty_data_dir.mkdir()
    with pytest.raises(UpgradeRefused, match="NO_CONTROL_DATABASE_FOUND"):
        create_data_backup(empty_data_dir, tmp_path / "no-db", previous_sha=PREVIOUS_SHA)


def test_create_data_backup_refuses_insufficient_disk_space(tmp_path, monkeypatch):
    data_dir = _make_data_dir(tmp_path)
    monkeypatch.setattr(
        upgrade_tool.shutil, "disk_usage", lambda path: DiskUsage(1, 1, 1024),
    )
    backup_dir = tmp_path / "backup"
    with pytest.raises(UpgradeRefused, match="INSUFFICIENT_BACKUP_SPACE"):
        create_data_backup(data_dir, backup_dir, previous_sha=PREVIOUS_SHA)
    assert not backup_dir.exists()


# ---------------------------------------------------------------------------
# B. Rollback: dry run
# ---------------------------------------------------------------------------

def test_restore_data_backup_dry_run_changes_nothing(tmp_path, monkeypatch):
    data_dir = _make_data_dir(tmp_path)
    backup_dir = tmp_path / "backup"
    created = create_data_backup(
        data_dir, backup_dir, previous_sha=PREVIOUS_SHA, target_sha=TARGET_SHA,
    )
    with _connect(data_dir / "task_runtime" / "tasks.sqlite3") as database:
        database.execute("INSERT INTO tasks VALUES ('after-backup','SUCCEEDED')")
    before = _control_hashes(data_dir)

    service_calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(upgrade_tool, "_systemctl", _service_recorder(service_calls))
    monkeypatch.setattr(upgrade_tool, "_require_apply_privileges", lambda: None)
    result = restore_data_backup(
        backup_dir, data_dir, apply=False, acknowledge_data_restore=False,
    )

    assert result["mode"] == "DRY RUN"
    assert result["applied"] is False
    assert result["forced"] is False
    assert result["manifest_sha256"] == created["manifest_sha256"]
    assert result["target_sha"] == TARGET_SHA
    assert result["entries"] == [
        "projects/p1/materials.sqlite3", "task_runtime/tasks.sqlite3",
    ]
    assert service_calls == []
    assert _control_hashes(data_dir) == before
    with _connect(data_dir / "task_runtime" / "tasks.sqlite3") as database:
        task_ids = {row[0] for row in database.execute("SELECT task_id FROM tasks")}
    assert "after-backup" in task_ids


def test_restore_data_backup_refuses_when_verification_fails(tmp_path):
    data_dir = _make_data_dir(tmp_path)
    backup_dir = tmp_path / "backup"
    create_data_backup(data_dir, backup_dir, previous_sha=PREVIOUS_SHA)
    target = backup_dir / "task_runtime" / "tasks.sqlite3"
    target.write_bytes(target.read_bytes() + b"tampered")
    with pytest.raises(UpgradeRefused, match="BACKUP_FILE_SIZE_MISMATCH"):
        restore_data_backup(
            backup_dir, data_dir, apply=False, acknowledge_data_restore=False,
        )


# ---------------------------------------------------------------------------
# B. Rollback: applied restore with mocked services
# ---------------------------------------------------------------------------

def test_restore_data_backup_applies_snapshot_with_safety_backup(tmp_path, monkeypatch):
    data_dir = _make_data_dir(tmp_path)
    backup_dir = tmp_path / "backup"
    created = create_data_backup(
        data_dir, backup_dir, previous_sha=PREVIOUS_SHA, target_sha=TARGET_SHA,
    )
    # Idle, post-backup changes that a successful rollback must overwrite.
    with _connect(data_dir / "task_runtime" / "tasks.sqlite3") as database:
        database.execute("INSERT INTO tasks VALUES ('after-backup','SUCCEEDED')")
    with _connect(data_dir / "projects" / "p1" / "materials.sqlite3") as database:
        database.execute("INSERT INTO materials VALUES ('m-2','smoke')")

    service_calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(upgrade_tool, "_systemctl", _service_recorder(service_calls))
    monkeypatch.setattr(upgrade_tool, "_require_apply_privileges", lambda: None)
    monkeypatch.setattr(
        upgrade_tool, "wait_web_health",
        lambda timeout=45.0: {"ok": True, "version": "test-version"},
    )

    result = restore_data_backup(
        backup_dir, data_dir, apply=True, acknowledge_data_restore=True,
    )

    assert result["mode"] == "APPLIED"
    assert result["applied"] is True
    assert result["forced"] is False
    assert result["entries_restored"] == 2
    assert result["restored_sha256_verified"] is True
    assert result["restored_quick_check"] == "ok"
    assert result["post_start_quick_check"] == "ok"
    assert result["post_start_sha256_unchanged"] is True
    assert result["manifest_sha256"] == created["manifest_sha256"]
    assert result["previous_sha"] == PREVIOUS_SHA
    assert result["target_sha"] == TARGET_SHA
    assert result["total_bytes"] == created["total_bytes"]

    with _connect(data_dir / "task_runtime" / "tasks.sqlite3") as database:
        assert database.execute("SELECT task_id FROM tasks").fetchall() == [("task-0",)]
    with _connect(data_dir / "projects" / "p1" / "materials.sqlite3") as database:
        assert database.execute("SELECT material_id FROM materials").fetchall() == [("m-1",)]
    assert not list(data_dir.rglob("*-wal"))
    assert not list(data_dir.rglob("*-shm"))

    # stop worker -> stop web -> start web -> start worker -> verify worker.
    assert service_calls[:4] == [
        ("stop", upgrade_tool.WORKER_UNIT),
        ("stop", upgrade_tool.WEB_UNIT),
        ("start", upgrade_tool.WEB_UNIT),
        ("start", upgrade_tool.WORKER_UNIT),
    ]
    assert service_calls[4] == ("is-active", upgrade_tool.WORKER_UNIT)

    # Pre-rollback safety snapshot: verifiable, records purpose, keeps the
    # state that existed before the restore.
    safety_dir = Path(result["safety_backup_dir"])
    assert safety_dir.is_dir()
    assert safety_dir.is_relative_to(backup_dir / "pre-rollback")
    assert result["safety_backup_manifest_sha256"] is not None
    safety_verification = verify_data_backup(safety_dir)
    assert safety_verification["ok"] is True
    safety_manifest = load_backup_manifest(safety_dir)
    assert safety_manifest["purpose"] == "pre-rollback"
    with _connect(safety_dir / "task_runtime" / "tasks.sqlite3") as database:
        task_ids = {row[0] for row in database.execute("SELECT task_id FROM tasks")}
    assert "after-backup" in task_ids


def test_restore_apply_requires_privilege_gate_before_touching_data(
    tmp_path, monkeypatch,
):
    data_dir = _make_data_dir(tmp_path)
    backup_dir = tmp_path / "backup"
    create_data_backup(data_dir, backup_dir, previous_sha=PREVIOUS_SHA)
    before = _control_hashes(data_dir)

    def denied() -> None:
        raise UpgradeRefused("ROOT_REQUIRED: simulated non-root operator")

    monkeypatch.setattr(upgrade_tool, "_require_apply_privileges", denied)
    with pytest.raises(UpgradeRefused, match="ROOT_REQUIRED"):
        restore_data_backup(
            backup_dir, data_dir, apply=True, acknowledge_data_restore=True,
        )
    assert _control_hashes(data_dir) == before
    assert not (backup_dir / "pre-rollback").exists()


def test_restore_data_backup_requires_acknowledgement_and_idle_tasks(tmp_path, monkeypatch):
    data_dir = _make_data_dir(tmp_path)
    backup_dir = tmp_path / "backup"
    create_data_backup(data_dir, backup_dir, previous_sha=PREVIOUS_SHA)
    service_calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(upgrade_tool, "_systemctl", _service_recorder(service_calls))
    monkeypatch.setattr(upgrade_tool, "_require_apply_privileges", lambda: None)

    with pytest.raises(UpgradeRefused, match="DATA_RESTORE_NOT_ACKNOWLEDGED"):
        restore_data_backup(
            backup_dir, data_dir, apply=True, acknowledge_data_restore=False,
        )
    assert service_calls == []
    assert not (backup_dir / "pre-rollback").exists()

    with _connect(data_dir / "task_runtime" / "tasks.sqlite3") as database:
        database.execute("INSERT INTO tasks VALUES ('active-rollback','RUNNING')")
    before = _control_hashes(data_dir)
    with pytest.raises(UpgradeRefused, match="ACTIVE_TASKS_BLOCK_ROLLBACK"):
        restore_data_backup(
            backup_dir, data_dir, apply=True, acknowledge_data_restore=True,
        )
    assert service_calls == []
    assert not (backup_dir / "pre-rollback").exists()
    assert _control_hashes(data_dir) == before


def test_restore_data_backup_force_skips_idle_gate_but_needs_acknowledgement(
    tmp_path, monkeypatch,
):
    data_dir = _make_data_dir(tmp_path)
    backup_dir = tmp_path / "backup"
    create_data_backup(data_dir, backup_dir, previous_sha=PREVIOUS_SHA)
    with _connect(data_dir / "task_runtime" / "tasks.sqlite3") as database:
        database.execute("INSERT INTO tasks VALUES ('active-force','RUNNING')")

    service_calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(upgrade_tool, "_systemctl", _service_recorder(service_calls))
    monkeypatch.setattr(upgrade_tool, "_require_apply_privileges", lambda: None)
    monkeypatch.setattr(
        upgrade_tool, "wait_web_health",
        lambda timeout=45.0: {"ok": True, "version": "test-version"},
    )

    with pytest.raises(UpgradeRefused, match="DATA_RESTORE_NOT_ACKNOWLEDGED"):
        restore_data_backup(
            backup_dir, data_dir, apply=True,
            acknowledge_data_restore=False, force=True,
        )
    assert service_calls == []

    result = restore_data_backup(
        backup_dir, data_dir, apply=True,
        acknowledge_data_restore=True, force=True,
    )
    assert result["forced"] is True
    assert result["applied"] is True
    with _connect(data_dir / "task_runtime" / "tasks.sqlite3") as database:
        assert database.execute("SELECT task_id FROM tasks").fetchall() == [("task-0",)]


def test_restore_failure_keeps_services_stopped_and_points_at_safety_backup(
    tmp_path, monkeypatch, capsys,
):
    data_dir = _make_data_dir(tmp_path)
    backup_dir = tmp_path / "backup"
    create_data_backup(data_dir, backup_dir, previous_sha=PREVIOUS_SHA)
    service_calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(upgrade_tool, "_systemctl", _service_recorder(service_calls))
    monkeypatch.setattr(upgrade_tool, "_require_apply_privileges", lambda: None)

    def failing_health(timeout=45.0):
        raise UpgradeRefused("WEB_HEALTH_TIMEOUT: simulated")

    monkeypatch.setattr(upgrade_tool, "wait_web_health", failing_health)
    with pytest.raises(UpgradeRefused, match="WEB_HEALTH_TIMEOUT"):
        restore_data_backup(
            backup_dir, data_dir, apply=True, acknowledge_data_restore=True,
        )

    assert service_calls[:4] == [
        ("stop", upgrade_tool.WORKER_UNIT),
        ("stop", upgrade_tool.WEB_UNIT),
        ("start", upgrade_tool.WEB_UNIT),
        ("stop", upgrade_tool.WORKER_UNIT),
    ]
    assert service_calls[4] == ("stop", upgrade_tool.WEB_UNIT)
    error_output = capsys.readouterr().err
    assert "STOPPED" in error_output
    assert "pre-rollback" in error_output
    assert not any(call[0] == "start" and call[1] == upgrade_tool.WORKER_UNIT
                   for call in service_calls)


# ---------------------------------------------------------------------------
# C. CLI compatibility
# ---------------------------------------------------------------------------

def test_cli_apply_without_backup_or_acknowledgement_is_refused(
    tmp_path, monkeypatch, capsys,
):
    data_dir = tmp_path / "data"
    _write_task_db(data_dir)
    repo = tmp_path / "repo"
    commands: list[tuple[str, ...]] = []

    def fake_command(*args, cwd=None):
        commands.append(tuple(args))
        if args[:2] == ("git", "branch"):
            return upgrade_tool.BRANCH
        if args[:2] == ("git", "status"):
            return ""
        if args[:2] == ("git", "rev-parse"):
            return PREVIOUS_SHA
        if args[:2] == ("systemctl", "is-active"):
            return "active"
        return ""

    monkeypatch.setattr(
        sys, "argv",
        [
            "production_upgrade.py", "--repo", str(repo), "--data-dir", str(data_dir),
            "--target", TARGET_SHA, "--apply",
        ],
    )
    monkeypatch.setattr(upgrade_tool, "_require_upgrade_privileges", lambda apply: None)
    monkeypatch.setattr(upgrade_tool, "command", fake_command)

    assert upgrade_tool.main() == 1
    error_output = capsys.readouterr().err
    assert "DATA_BACKUP_REQUIRED" in error_output
    assert not any(command[:2] == ("systemctl", "stop") for command in commands)


def test_cli_backup_only_never_touches_services(tmp_path, monkeypatch, capsys):
    data_dir = _make_data_dir(tmp_path)
    backup_dir = tmp_path / "backup"
    repo = tmp_path / "repo"
    repo.mkdir()
    commands: list[tuple[str, ...]] = []

    def fake_command(*args, cwd=None):
        commands.append(tuple(args))
        if args[:1] == ("systemctl",):
            raise AssertionError("--backup-only must not call systemctl")
        if args[:2] == ("git", "rev-parse"):
            return PREVIOUS_SHA
        return ""

    monkeypatch.setattr(
        sys, "argv",
        [
            "production_upgrade.py", "--repo", str(repo), "--data-dir", str(data_dir),
            "--backup-dir", str(backup_dir), "--backup-only",
            "--target", TARGET_SHA,
        ],
    )
    monkeypatch.setattr(upgrade_tool, "command", fake_command)

    assert upgrade_tool.main() == 0
    assert commands == [("git", "rev-parse", "HEAD")]
    manifest = load_backup_manifest(backup_dir)
    assert manifest["previous_sha"] == PREVIOUS_SHA
    assert manifest["target_sha"] == TARGET_SHA
    assert verify_data_backup(backup_dir)["ok"] is True
    assert "BACKUP_ONLY" in capsys.readouterr().out


def test_cli_rollback_dry_run_verifies_without_services(tmp_path, monkeypatch, capsys):
    data_dir = _make_data_dir(tmp_path)
    backup_dir = tmp_path / "backup"
    create_data_backup(data_dir, backup_dir, previous_sha=PREVIOUS_SHA)

    def forbidden_systemctl(*args: str) -> str:
        raise AssertionError("a rollback dry run must not call systemctl")

    monkeypatch.setattr(upgrade_tool, "_systemctl", forbidden_systemctl)
    monkeypatch.setattr(
        sys, "argv",
        [
            "production_upgrade.py", "--data-dir", str(data_dir),
            "--backup-dir", str(backup_dir), "--rollback",
        ],
    )
    assert upgrade_tool.main() == 0
    output = capsys.readouterr().out
    assert "DRY RUN" in output
    assert '"applied": false' in output
