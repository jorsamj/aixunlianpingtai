"""M10-A coordinated application/data rollback and M10-B maintenance-boundary tests.

These tests use real temporary SQLite databases and a real temporary Git repository
(``git merge-base --is-ancestor`` / ``git checkout --detach``) with only
``systemctl``/web-health mocked.  They prove the isolated behavior of
``tools/production_upgrade.py``; no production host, systemd unit or real data is
touched.
"""
from __future__ import annotations

import collections
import contextlib
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tools import production_upgrade as upgrade_tool
from tools.production_upgrade import (
    PartialRestoreFailed,
    UpgradeRefused,
    create_data_backup,
    load_backup_manifest,
    restore_data_backup,
    verify_data_backup,
)

BRANCH = upgrade_tool.BRANCH
PREVIOUS_SHA = "1" * 40
TARGET_SHA = "2" * 40
OLD_VERSION = "42.24.501"
NEW_VERSION = "42.24.592"
DiskUsage = collections.namedtuple("DiskUsage", "total used free")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@contextlib.contextmanager
def _connect(path: Path):
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


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=check,
    )


def _rev(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", message)
    return _rev(repo)


def _write_schema_sources(repo: Path, *, tasks_version: int) -> None:
    (repo / "platform_core" / "task_runtime").mkdir(parents=True, exist_ok=True)
    (repo / "platform_core" / "task_runtime" / "repository.py").write_text(
        f"_SCHEMA_VERSION = {tasks_version}\n", encoding="utf-8",
    )
    (repo / "platform_core" / "material_repository.py").write_text(
        "_SCHEMA_VERSION = 7\n", encoding="utf-8",
    )
    (repo / "platform_core" / "annotation_repository.py").write_text(
        "_SCHEMA_VERSION = 3\n", encoding="utf-8",
    )


def _make_git_history(tmp_path: Path) -> tuple[Path, str, str, str]:
    """Return (repo, oldest_sha, previous_sha, upgraded_sha) on the release branch.

    oldest and previous both declare the old tasks schema 8; the upgraded commit
    declares schema 9.  No destructive git operation is used to build it.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Rollback Test")
    _git(repo, "config", "user.email", "rollback@example.invalid")
    _git(repo, "checkout", "-q", "-b", BRANCH)
    _write_schema_sources(repo, tasks_version=8)
    (repo / "VERSION.txt").write_text(OLD_VERSION + "\n", encoding="utf-8")
    oldest = _commit(repo, "oldest supported code")
    (repo / "docs").mkdir()
    (repo / "docs" / "note.txt").write_text("ancestor-only change\n", encoding="utf-8")
    previous = _commit(repo, "previous running code")
    _write_schema_sources(repo, tasks_version=9)
    (repo / "VERSION.txt").write_text(NEW_VERSION + "\n", encoding="utf-8")
    upgraded = _commit(repo, "upgraded code")
    assert len(oldest) == len(previous) == len(upgraded) == 40
    return repo, oldest, previous, upgraded


def _write_task_database(
    data_dir: Path, *,
    user_version: int = 8,
    include_holds: bool = True,
    hold_state: str | None = None,
    include_agents: bool = False,
    agent_heartbeat: str | None = None,
    agent_active_tasks: str = "[]",
    statuses: tuple[str, ...] = ("SUCCEEDED",),
) -> Path:
    path = data_dir / "task_runtime" / "tasks.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    with _connect(path) as database:
        database.execute(
            "CREATE TABLE tasks (task_id TEXT PRIMARY KEY, project_id TEXT, "
            "kind TEXT, status TEXT)"
        )
        for index, status in enumerate(statuses):
            database.execute(
                "INSERT INTO tasks VALUES (?,?,?,?)",
                (f"task-{index}", "p1", "TRAINING", status),
            )
        database.execute(
            "CREATE TABLE worker_instances (instance_key TEXT PRIMARY KEY, "
            "worker_id TEXT, build_id TEXT)"
        )
        if include_holds:
            database.execute(
                "CREATE TABLE execution_resource_holds (task_id TEXT PRIMARY KEY, "
                "node_id TEXT, state TEXT)"
            )
            if hold_state is not None:
                database.execute(
                    "INSERT INTO execution_resource_holds VALUES ('task-hold','n1',?)",
                    (hold_state,),
                )
        if include_agents:
            database.execute(
                "CREATE TABLE service_nodes (node_id TEXT PRIMARY KEY, "
                "enabled INTEGER, last_heartbeat_at TEXT, active_tasks_json TEXT)"
            )
            database.execute(
                "INSERT INTO service_nodes VALUES ('node-1',1,?,?)",
                (agent_heartbeat, agent_active_tasks),
            )
        database.execute(f"PRAGMA user_version={int(user_version)}")
    return path


def _write_materials_database(data_dir: Path, *, user_version: int = 7) -> Path:
    path = data_dir / "projects" / "p1" / "materials.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    with _connect(path) as database:
        database.execute(
            "CREATE TABLE materials (id TEXT PRIMARY KEY, storage_source_id TEXT, "
            "object_key TEXT, payload_json TEXT)"
        )
        database.execute(
            "INSERT INTO materials VALUES ('m-1','default_local','k1','{}')"
        )
        database.execute(f"PRAGMA user_version={int(user_version)}")
    return path


def _make_coordinated_data_dir(tmp_path: Path, *, tasks_user_version: int = 8) -> Path:
    data_dir = tmp_path / "data"
    _write_task_database(data_dir, user_version=tasks_user_version)
    _write_materials_database(data_dir)
    return data_dir


def _make_simple_data_dir(tmp_path: Path) -> Path:
    """Two plain control DBs for database-only restore tests (mocked services)."""
    data_dir = tmp_path / "data"
    path = data_dir / "task_runtime" / "tasks.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    with _connect(path) as database:
        database.execute("CREATE TABLE tasks (task_id TEXT, status TEXT)")
        database.execute("INSERT INTO tasks VALUES ('task-0','SUCCEEDED')")
    _write_materials_database(data_dir)
    (data_dir / "task_runtime" / "artifacts" / "deep").mkdir(parents=True)
    (data_dir / "task_runtime" / "artifacts" / "deep" / "payload.bin").write_bytes(
        b"x" * 128
    )
    return data_dir


def _control_hashes(data_dir: Path) -> dict[str, str]:
    return {
        "task_runtime/tasks.sqlite3": _sha256(
            data_dir / "task_runtime" / "tasks.sqlite3"
        ),
        "projects/p1/materials.sqlite3": _sha256(
            data_dir / "projects" / "p1" / "materials.sqlite3"
        ),
    }


def _service_recorder(calls: list[tuple[str, ...]]):
    def fake_systemctl(*args: str) -> str:
        calls.append(tuple(args))
        return "active" if args[:1] == ("is-active",) else ""
    return fake_systemctl


def _health_ok(timeout: float = 45.0) -> dict:
    return {"ok": True, "version": "rollback-test-version"}


def _install_service_mocks(monkeypatch) -> list[tuple[str, ...]]:
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(upgrade_tool, "_systemctl", _service_recorder(calls))
    monkeypatch.setattr(upgrade_tool, "_require_apply_privileges", lambda: None)
    monkeypatch.setattr(upgrade_tool, "wait_web_health", _health_ok)
    return calls


def _install_git_command_recorder(monkeypatch) -> list[tuple[str, ...]]:
    recorded: list[tuple[str, ...]] = []
    original = upgrade_tool.command

    def recording_command(*args: str, cwd: Path | None = None) -> str:
        recorded.append(tuple(args))
        return original(*args, cwd=cwd)

    monkeypatch.setattr(upgrade_tool, "command", recording_command)
    return recorded


# ---------------------------------------------------------------------------
# M10-A: ancestry gate (real temporary git repository)
# ---------------------------------------------------------------------------

def test_application_rollback_rejects_non_ancestor_sha(tmp_path, monkeypatch):
    repo, oldest, previous, upgraded = _make_git_history(tmp_path)
    assert _rev(repo) == upgraded
    # A sibling commit is not an ancestor of the backup previous_sha.
    _git(repo, "checkout", "-q", "-b", "side", oldest)
    (repo / "side.txt").write_text("side\n", encoding="utf-8")
    side = _commit(repo, "unrelated sibling branch")
    _git(repo, "checkout", "-q", BRANCH)

    _git(repo, "checkout", "-q", previous)
    data_dir = _make_coordinated_data_dir(tmp_path)
    backup_dir = tmp_path / "backup"
    create_data_backup(
        data_dir, backup_dir, previous_sha=previous, target_sha=upgraded, repo=repo,
    )
    _git(repo, "checkout", "-q", BRANCH)
    before_hashes = _control_hashes(data_dir)

    calls = _install_service_mocks(monkeypatch)
    with pytest.raises(
        UpgradeRefused, match="APPLICATION_ROLLBACK_TARGET_NOT_ANCESTOR",
    ):
        restore_data_backup(
            backup_dir, data_dir, apply=True, acknowledge_data_restore=True,
            app_sha=side, repo=repo,
        )
    assert calls == []
    assert _rev(repo) == upgraded
    assert _control_hashes(data_dir) == before_hashes
    assert not (backup_dir / "pre-rollback").exists()


def test_application_rollback_allows_previous_sha_and_ancestor_dry_run(
    tmp_path, monkeypatch,
):
    repo, oldest, previous, upgraded = _make_git_history(tmp_path)
    _git(repo, "checkout", "-q", previous)
    data_dir = _make_coordinated_data_dir(tmp_path)
    backup_dir = tmp_path / "backup"
    create_data_backup(
        data_dir, backup_dir, previous_sha=previous, target_sha=upgraded, repo=repo,
    )
    _git(repo, "checkout", "-q", BRANCH)

    def forbidden_systemctl(*args: str) -> str:
        raise AssertionError("a coordinated rollback dry run must not call systemctl")

    monkeypatch.setattr(upgrade_tool, "_systemctl", forbidden_systemctl)
    before_hashes = _control_hashes(data_dir)

    for target in (previous, oldest):
        result = restore_data_backup(
            backup_dir, data_dir, apply=False, acknowledge_data_restore=False,
            app_sha=target, repo=repo,
        )
        assert result["mode"] == "DRY RUN"
        assert result["applied"] is False
        assert result["application_rollback"] == "planned"
        assert result["application_sha"] == target
        assert result["schema_status"] == "compatible"
        assert result["application_sha_verified"] is None

    assert _rev(repo) == upgraded
    assert _control_hashes(data_dir) == before_hashes


# ---------------------------------------------------------------------------
# M10-A: coordinated rollback execution and identity verification
# ---------------------------------------------------------------------------

def test_coordinated_rollback_checkout_restore_and_identity_verification(
    tmp_path, monkeypatch,
):
    repo, oldest, previous, upgraded = _make_git_history(tmp_path)
    _git(repo, "checkout", "-q", previous)
    data_dir = _make_coordinated_data_dir(tmp_path)
    backup_dir = tmp_path / "backup"
    created = create_data_backup(
        data_dir, backup_dir, previous_sha=previous, target_sha=upgraded, repo=repo,
    )
    _git(repo, "checkout", "-q", BRANCH)
    assert _rev(repo) == upgraded
    # Idle post-backup changes that this rollback must overwrite.
    with _connect(data_dir / "projects" / "p1" / "materials.sqlite3") as database:
        database.execute(
            "INSERT INTO materials VALUES ('m-2','default_local','k2','{}')"
        )
    with _connect(data_dir / "task_runtime" / "tasks.sqlite3") as database:
        database.execute(
            "INSERT INTO tasks VALUES ('task-after','p1','TRAINING','SUCCEEDED')"
        )

    calls = _install_service_mocks(monkeypatch)
    git_commands = _install_git_command_recorder(monkeypatch)
    result = restore_data_backup(
        backup_dir, data_dir, apply=True, acknowledge_data_restore=True,
        app_sha=previous, repo=repo,
    )

    assert result["mode"] == "APPLIED"
    assert result["applied"] is True
    assert result["application_rollback"] == "applied"
    assert result["application_sha"] == previous
    assert result["application_sha_verified"] is True
    assert result["database_sha256_verified"] is True
    assert result["schema_status"] == "compatible"
    assert result["code_switched"] is True
    assert result["detached_head"] is True
    assert result["entries_restored"] == 2
    assert result["manifest_sha256"] == created["manifest_sha256"]
    assert result["health"]["ok"] is True
    assert result["health"]["version"] == "rollback-test-version"

    # The application code really moved to the requested ancestor and the
    # worktree is detached (never a second, automatic rollback).
    assert _rev(repo) == previous
    assert _git(repo, "branch", "--show-current").stdout.strip() == ""
    assert (repo / "VERSION.txt").read_text(encoding="utf-8").strip() == OLD_VERSION
    # The rolled-back commit's tracked content is present again.
    assert (repo / "docs" / "note.txt").read_text(encoding="utf-8") == (
        "ancestor-only change\n"
    )

    # Only a non-destructive detached checkout was used; no reset/clean/stash.
    checkout_calls = [call for call in git_commands if call[:2] == ("git", "checkout")]
    assert ("git", "checkout", "--detach", previous) in checkout_calls
    forbidden = {"reset", "clean", "stash", "push"}
    assert not [
        call for call in git_commands
        if call[:1] == ("git",) and len(call) > 1 and call[1] in forbidden
    ]

    # Database identity equals the verified backup manifest.
    for entry in created["entries"]:
        restored = data_dir / entry["relative_path"]
        assert _sha256(restored) == entry["sha256"]
        assert restored.stat().st_size == entry["size_bytes"]
    with _connect(data_dir / "projects" / "p1" / "materials.sqlite3") as database:
        assert database.execute("SELECT id FROM materials").fetchall() == [("m-1",)]
    assert not list(data_dir.rglob("*-wal"))
    assert not list(data_dir.rglob("*-shm"))

    # stop worker -> stop web -> start web -> start worker -> verify worker.
    assert calls[:5] == [
        ("stop", upgrade_tool.WORKER_UNIT),
        ("stop", upgrade_tool.WEB_UNIT),
        ("start", upgrade_tool.WEB_UNIT),
        ("start", upgrade_tool.WORKER_UNIT),
        ("is-active", upgrade_tool.WORKER_UNIT),
    ]
    safety_dir = Path(result["safety_backup_dir"])
    assert safety_dir.is_dir()
    assert safety_dir.is_relative_to(backup_dir / "pre-rollback")
    assert verify_data_backup(safety_dir)["ok"] is True
    assert load_backup_manifest(safety_dir)["purpose"] == "pre-rollback"


def test_coordinated_rollback_failure_keeps_stopped_and_never_rolls_back_twice(
    tmp_path, monkeypatch, capsys,
):
    repo, oldest, previous, upgraded = _make_git_history(tmp_path)
    _git(repo, "checkout", "-q", previous)
    data_dir = _make_coordinated_data_dir(tmp_path)
    backup_dir = tmp_path / "backup"
    create_data_backup(
        data_dir, backup_dir, previous_sha=previous, target_sha=upgraded, repo=repo,
    )
    _git(repo, "checkout", "-q", BRANCH)

    calls = _install_service_mocks(monkeypatch)
    git_commands = _install_git_command_recorder(monkeypatch)

    def failing_health(timeout: float = 45.0):
        raise UpgradeRefused("WEB_HEALTH_TIMEOUT: simulated coordinated failure")

    monkeypatch.setattr(upgrade_tool, "wait_web_health", failing_health)
    with pytest.raises(UpgradeRefused, match="WEB_HEALTH_TIMEOUT"):
        restore_data_backup(
            backup_dir, data_dir, apply=True, acknowledge_data_restore=True,
            app_sha=previous, repo=repo,
        )

    # Services were stopped again and the worker was never started.
    assert calls[:3] == [
        ("stop", upgrade_tool.WORKER_UNIT),
        ("stop", upgrade_tool.WEB_UNIT),
        ("start", upgrade_tool.WEB_UNIT),
    ]
    assert calls[3:] == [
        ("stop", upgrade_tool.WORKER_UNIT),
        ("stop", upgrade_tool.WEB_UNIT),
    ]
    assert not any(
        call[0] == "start" and call[1] == upgrade_tool.WORKER_UNIT for call in calls
    )
    # Code stays at the target; no second automatic rollback to the new code.
    assert _rev(repo) == previous
    assert _git(repo, "branch", "--show-current").stdout.strip() == ""
    assert len([c for c in git_commands if c[:2] == ("git", "checkout")]) == 1
    error_output = capsys.readouterr().err
    assert "STOPPED" in error_output
    assert "pre-rollback" in error_output
    assert "will not automatically roll the data" in error_output
    assert "Code worktree is left checked out at" in error_output


# ---------------------------------------------------------------------------
# M10-A: fail-closed schema compatibility
# ---------------------------------------------------------------------------

def test_schema_incompatible_backup_is_refused_without_changing_anything(
    tmp_path, monkeypatch,
):
    repo, oldest, previous, upgraded = _make_git_history(tmp_path)
    _git(repo, "checkout", "-q", previous)

    def _assert_refused(data_dir: Path, backup_dir: Path) -> None:
        create_data_backup(
            data_dir, backup_dir,
            previous_sha=previous, target_sha=upgraded, repo=repo,
        )
        _git(repo, "checkout", "-q", BRANCH)
        before_hashes = _control_hashes(data_dir)
        calls = _install_service_mocks(monkeypatch)
        git_commands = _install_git_command_recorder(monkeypatch)
        with pytest.raises(UpgradeRefused, match="BACKUP_SCHEMA_INCOMPATIBLE"):
            restore_data_backup(
                backup_dir, data_dir, apply=True, acknowledge_data_restore=True,
                app_sha=previous, repo=repo,
            )
        assert calls == []
        assert git_commands == []  # No checkout happened before the fail-closed check.
        assert _rev(repo) == upgraded
        assert _control_hashes(data_dir) == before_hashes
        assert not (backup_dir / "pre-rollback").exists()
        _git(repo, "checkout", "-q", previous)

    # Case 1: the backup user_version is one migration behind the target code.
    version_dir = _make_coordinated_data_dir(
        tmp_path, tasks_user_version=7,
    )
    _assert_refused(version_dir, tmp_path / "backup-version")
    _git(repo, "checkout", "-q", BRANCH)

    # Case 2: the version matches but a critical table expected by the code is
    # missing from the backup database.
    missing_dir = tmp_path / "data-missing-table"
    _write_task_database(missing_dir, user_version=8, include_holds=False)
    _write_materials_database(missing_dir)
    _assert_refused(missing_dir, tmp_path / "backup-missing-table")
    _git(repo, "checkout", "-q", BRANCH)

    # Case 3: a critical column is missing from an existing table.
    column_dir = tmp_path / "data-missing-column"
    _write_task_database(column_dir, user_version=8)
    _write_materials_database(column_dir)
    with _connect(column_dir / "projects" / "p1" / "materials.sqlite3") as database:
        database.execute("DROP TABLE materials")
        database.execute("CREATE TABLE materials (id TEXT PRIMARY KEY)")
    _assert_refused(column_dir, tmp_path / "backup-missing-column")
    _git(repo, "checkout", "-q", BRANCH)


def test_restore_refuses_backup_bound_to_another_data_dir(tmp_path, monkeypatch):
    repo, oldest, previous, upgraded = _make_git_history(tmp_path)
    source_dir = _make_coordinated_data_dir(tmp_path)
    backup_dir = tmp_path / "backup"
    create_data_backup(
        source_dir, backup_dir, previous_sha=previous, target_sha=upgraded,
        repo=repo,
    )
    other_dir = tmp_path / "other-data"
    calls = _install_service_mocks(monkeypatch)
    with pytest.raises(UpgradeRefused, match="BACKUP_DATA_DIR_MISMATCH"):
        restore_data_backup(
            backup_dir, other_dir, apply=True, acknowledge_data_restore=True,
        )
    assert calls == []


def test_unknown_database_kind_blocks_coordinated_rollback(tmp_path, monkeypatch):
    repo, oldest, previous, upgraded = _make_git_history(tmp_path)
    _git(repo, "checkout", "-q", previous)
    data_dir = _make_coordinated_data_dir(tmp_path)
    mystery = data_dir / "projects" / "p1" / "mystery.sqlite3"
    with _connect(mystery) as database:
        database.execute("CREATE TABLE whatever (id TEXT)")
    backup_dir = tmp_path / "backup"
    create_data_backup(
        data_dir, backup_dir, previous_sha=previous, target_sha=upgraded, repo=repo,
    )
    _git(repo, "checkout", "-q", BRANCH)

    calls = _install_service_mocks(monkeypatch)
    with pytest.raises(UpgradeRefused, match="APPLICATION_ROLLBACK_BLOCKED"):
        restore_data_backup(
            backup_dir, data_dir, apply=True, acknowledge_data_restore=True,
            app_sha=previous, repo=repo,
        )
    assert calls == []
    assert _rev(repo) == upgraded


# ---------------------------------------------------------------------------
# M10-A: partial database restore diagnostics and idempotent retry
# ---------------------------------------------------------------------------

def test_partial_restore_records_diagnostics_and_manual_retry_converges(
    tmp_path, monkeypatch, capsys,
):
    data_dir = _make_simple_data_dir(tmp_path)
    backup_dir = tmp_path / "backup"
    created = create_data_backup(
        data_dir, backup_dir, previous_sha=PREVIOUS_SHA, target_sha=None,
    )
    with _connect(data_dir / "task_runtime" / "tasks.sqlite3") as database:
        database.execute("INSERT INTO tasks VALUES ('after-backup','SUCCEEDED')")
    with _connect(data_dir / "projects" / "p1" / "materials.sqlite3") as database:
        database.execute(
            "INSERT INTO materials VALUES ('m-after','default_local','k9','{}')"
        )

    calls = _install_service_mocks(monkeypatch)
    original_replace = upgrade_tool._replace_database_file

    def failing_replace(source: Path, target: Path) -> None:
        if target.name == "tasks.sqlite3":
            raise OSError("simulated replacement failure for tasks.sqlite3")
        original_replace(source, target)

    monkeypatch.setattr(upgrade_tool, "_replace_database_file", failing_replace)
    with pytest.raises(PartialRestoreFailed) as failure:
        restore_data_backup(
            backup_dir, data_dir, apply=True, acknowledge_data_restore=True,
        )
    diagnostics = failure.value.diagnostics
    partial = diagnostics["partial_restore"]
    assert partial["restored"] == ["projects/p1/materials.sqlite3"]
    assert [item["relative_path"] for item in partial["failed"]] == [
        "task_runtime/tasks.sqlite3"
    ]
    assert "simulated replacement failure" in partial["failed"][0]["error"]
    assert partial["not_attempted"] == []
    safety_dir = Path(diagnostics["safety_backup_dir"])
    assert safety_dir.is_dir()
    assert verify_data_backup(safety_dir)["ok"] is True
    assert diagnostics["services"] == "stopped"
    assert "PARTIAL_RESTORE" in str(failure.value)
    assert calls[-2:] == [
        ("stop", upgrade_tool.WORKER_UNIT),
        ("stop", upgrade_tool.WEB_UNIT),
    ]
    stderr = capsys.readouterr().err
    assert "STOPPED" in stderr
    assert "partial database restore" in stderr

    # The already-restored database really matches the manifest now.
    manifest = load_backup_manifest(backup_dir)
    entry_by_path = {e["relative_path"]: e for e in manifest["entries"]}
    materials = data_dir / "projects" / "p1" / "materials.sqlite3"
    assert _sha256(materials) == entry_by_path["projects/p1/materials.sqlite3"]["sha256"]

    # A manual retry converges: already-restored files are re-verified/skipped.
    monkeypatch.setattr(upgrade_tool, "_replace_database_file", original_replace)
    retry = restore_data_backup(
        backup_dir, data_dir, apply=True, acknowledge_data_restore=True,
    )
    assert retry["applied"] is True
    assert retry["application_rollback"] == "not_requested"
    assert retry["database_sha256_verified"] is True
    assert retry["entries_restored"] == 2
    assert retry["partial_restore"]["already_restored"] == [
        "projects/p1/materials.sqlite3"
    ]
    assert retry["partial_restore"]["restored"] == ["task_runtime/tasks.sqlite3"]
    assert retry["partial_restore"]["failed"] == []
    for entry in created["entries"]:
        restored = data_dir / entry["relative_path"]
        assert _sha256(restored) == entry["sha256"]
    with _connect(data_dir / "task_runtime" / "tasks.sqlite3") as database:
        assert database.execute("SELECT task_id FROM tasks").fetchall() == [
            ("task-0",)
        ]


# ---------------------------------------------------------------------------
# M10-B: write-silence probes, forced override and consistency boundary
# ---------------------------------------------------------------------------

def test_backup_refuses_unreleased_hold_and_active_agent_without_force(tmp_path):
    base = tmp_path / "hold-data"
    _write_task_database(base, include_holds=True, hold_state="HELD")
    with pytest.raises(UpgradeRefused, match="UNRELEASED_RESOURCE_HOLDS_BLOCK_BACKUP"):
        create_data_backup(base, tmp_path / "hold-backup", previous_sha=PREVIOUS_SHA)
    assert not (tmp_path / "hold-backup").exists()

    forced_backup = tmp_path / "hold-backup-forced"
    result = create_data_backup(
        base, forced_backup, previous_sha=PREVIOUS_SHA, force_idle=True,
    )
    manifest = load_backup_manifest(forced_backup)
    assert result["write_silence"] == "unverified"
    assert manifest["write_silence"] == "unverified"
    assert manifest["write_silence_detail"]["forced"] is True
    assert "UNRELEASED_RESOURCE_HOLDS_BLOCK_BACKUP" in (
        manifest["write_silence_detail"]["forced_reasons"]
    )
    assert manifest["consistency"]["disaster_recovery"] is False
    assert manifest["consistency"]["cross_database_atomic"] is False
    assert "NOT a disaster-recovery backup" in manifest["consistency"]["note"]

    agents = tmp_path / "agent-data"
    heartbeat = datetime.now(timezone.utc).isoformat()
    _write_task_database(
        agents, include_agents=True, agent_heartbeat=heartbeat,
        agent_active_tasks="[]",
    )
    with pytest.raises(UpgradeRefused, match="ACTIVE_AGENTS_BLOCK_BACKUP"):
        create_data_backup(agents, tmp_path / "agent-backup", previous_sha=PREVIOUS_SHA)
    assert not (tmp_path / "agent-backup").exists()

    # An active task is refused by default and can only be overridden explicitly.
    tasks = tmp_path / "task-data"
    _write_task_database(tasks, include_holds=False, statuses=("RUNNING",))
    with pytest.raises(UpgradeRefused, match="ACTIVE_TASKS_BLOCK_UPGRADE"):
        create_data_backup(tasks, tmp_path / "task-backup", previous_sha=PREVIOUS_SHA)
    assert not (tmp_path / "task-backup").exists()
    task_forced_backup = tmp_path / "task-backup-forced"
    forced_task = create_data_backup(
        tasks, task_forced_backup, previous_sha=PREVIOUS_SHA, force_idle=True,
    )
    task_manifest = load_backup_manifest(task_forced_backup)
    assert task_manifest["write_silence_detail"]["forced"] is True
    assert "ACTIVE_TASKS_BLOCK_BACKUP" in (
        task_manifest["write_silence_detail"]["forced_reasons"]
    )
    assert forced_task["write_silence"] == "unverified"
    assert task_manifest["write_silence_detail"]["active_tasks"]["count"] == 1


def test_backup_refuses_worker_build_marker_mismatch_and_records_override(tmp_path):
    repo, oldest, previous, upgraded = _make_git_history(tmp_path)
    data_dir = tmp_path / "data"
    _write_task_database(data_dir, include_holds=False)
    marker = data_dir / "task_runtime" / "worker-build.json"
    marker.write_text(
        json.dumps({"build_id": "f" * 40}), encoding="utf-8",
    )
    with pytest.raises(UpgradeRefused, match="WORKER_BUILD_MISMATCH_BLOCK_BACKUP"):
        create_data_backup(
            data_dir, tmp_path / "mismatch-backup",
            previous_sha=PREVIOUS_SHA, repo=repo,
        )
    assert not (tmp_path / "mismatch-backup").exists()

    backup_dir = tmp_path / "mismatch-backup-forced"
    result = create_data_backup(
        data_dir, backup_dir, previous_sha=PREVIOUS_SHA, repo=repo, force_idle=True,
    )
    manifest = load_backup_manifest(backup_dir)
    assert result["write_silence"] == "unverified"
    detail = manifest["write_silence_detail"]
    assert detail["forced"] is True
    assert "WORKER_BUILD_MISMATCH_BLOCK_BACKUP" in detail["forced_reasons"]
    assert detail["worker_build_marker"]["matches_current_build"] is False
    # Force never claims consistency.
    assert manifest["consistency"]["business_consistency"] == "unverified"
    assert manifest["write_silence"] == "unverified"


def test_require_idle_only_refuses_unavailable_idleness_probes(tmp_path):
    data_dir = tmp_path / "data"
    _write_task_database(data_dir, include_holds=False)
    # Without --require-idle-only, unavailable probes are recorded but do not
    # masquerade as idle evidence for a normal backup.
    result = create_data_backup(
        data_dir, tmp_path / "default-backup", previous_sha=PREVIOUS_SHA,
    )
    detail = result["write_silence_detail"]
    assert detail["unknown"]  # holds/agents probes are unavailable here
    assert detail["forced"] is False
    assert result["write_silence"] == "unverified"

    with pytest.raises(UpgradeRefused, match="IDLE_PROBE_UNKNOWN_BLOCK_BACKUP"):
        create_data_backup(
            data_dir, tmp_path / "strict-backup",
            previous_sha=PREVIOUS_SHA, require_idle_only=True,
        )
    assert not (tmp_path / "strict-backup").exists()


def test_backup_manifest_binds_application_identity_schema_scope_and_exclusions(
    tmp_path,
):
    repo, oldest, previous, upgraded = _make_git_history(tmp_path)
    _git(repo, "checkout", "-q", previous)
    data_dir = _make_coordinated_data_dir(tmp_path)
    backup_dir = tmp_path / "backup"
    result = create_data_backup(
        data_dir, backup_dir, previous_sha=previous, target_sha=upgraded, repo=repo,
    )
    manifest = load_backup_manifest(backup_dir)
    git_head = _rev(repo)

    assert manifest["application_version"] == OLD_VERSION
    assert manifest["build_id"] == git_head
    assert manifest["previous_sha"] == previous
    assert manifest["target_sha"] == upgraded
    assert Path(manifest["data_dir"]) == data_dir.resolve()
    assert manifest["application"] == {
        "version": OLD_VERSION,
        "build_id": git_head,
        "previous_sha": previous,
        "target_sha": upgraded,
        "data_dir": str(data_dir.resolve()),
        "repo": str(repo.resolve()),
    }
    assert manifest["schema_versions"] == {
        "projects/p1/materials.sqlite3": 7,
        "task_runtime/tasks.sqlite3": 8,
    }
    entries = {entry["relative_path"]: entry for entry in manifest["entries"]}
    assert entries["task_runtime/tasks.sqlite3"]["schema"]["user_version"] == 8
    assert "tasks" in entries["task_runtime/tasks.sqlite3"]["schema"]["tables"]
    assert entries["task_runtime/tasks.sqlite3"]["schema"]["kind"] == "tasks"

    assert manifest["backup_scope"]["database_entries"] == [
        "projects/p1/materials.sqlite3", "task_runtime/tasks.sqlite3",
    ]
    included = manifest["backup_scope"]["included_patterns"]
    assert "task_runtime/tasks.sqlite3" in included
    exclusions = json.dumps(manifest["exclusions"], ensure_ascii=False)
    assert "media" in exclusions
    assert "model" in exclusions.lower()
    assert "artifacts" in exclusions
    assert "checkpoint" in exclusions
    assert manifest["consistency"]["disaster_recovery"] is False
    assert manifest["consistency"]["snapshot_kind"] == "per_database_online_backup"
    assert manifest["write_silence"] == "unverified"
    assert manifest["write_silence_detail"]["reason"]
    assert manifest["write_silence_detail"]["forced"] is False
    assert result["application_version"] == OLD_VERSION
    assert result["build_id"] == git_head
    assert verify_data_backup(backup_dir)["ok"] is True


# ---------------------------------------------------------------------------
# CLI: help text and coordinated-rollback wiring
# ---------------------------------------------------------------------------

def test_cli_help_documents_coordinated_rollback_scope_and_exclusions(
    monkeypatch, capsys,
):
    monkeypatch.setattr(sys, "argv", ["production_upgrade.py", "--help"])
    with pytest.raises(SystemExit) as exit_info:
        upgrade_tool.main()
    assert exit_info.value.code == 0
    output = capsys.readouterr().out
    assert "--rollback-application-to" in output
    assert "--force-idle" in output
    assert "--require-idle-only" in output
    assert "NOT a disaster-recovery backup" in output
    assert "raw material/media" in output
    assert "application_rollback=not_requested" in output


def test_cli_rollback_application_requires_rollback_flag(tmp_path, monkeypatch, capsys):
    repo, oldest, previous, upgraded = _make_git_history(tmp_path)
    monkeypatch.setattr(
        sys, "argv",
        [
            "production_upgrade.py", "--repo", str(repo), "--data-dir",
            str(tmp_path / "data"), "--backup-dir", str(tmp_path / "backup"),
            "--rollback-application-to", previous,
        ],
    )
    assert upgrade_tool.main() == 1
    assert "CONFLICTING_MODES" in capsys.readouterr().err


def test_cli_coordinated_rollback_dry_run_reports_planned_rollback(
    tmp_path, monkeypatch, capsys,
):
    repo, oldest, previous, upgraded = _make_git_history(tmp_path)
    _git(repo, "checkout", "-q", previous)
    data_dir = _make_coordinated_data_dir(tmp_path)
    backup_dir = tmp_path / "backup"
    create_data_backup(
        data_dir, backup_dir, previous_sha=previous, target_sha=upgraded, repo=repo,
    )
    _git(repo, "checkout", "-q", BRANCH)

    def forbidden_systemctl(*args: str) -> str:
        raise AssertionError("a coordinated rollback dry run must not call systemctl")

    monkeypatch.setattr(upgrade_tool, "_systemctl", forbidden_systemctl)
    monkeypatch.setattr(sys, "argv", [
        "production_upgrade.py", "--repo", str(repo), "--data-dir", str(data_dir),
        "--backup-dir", str(backup_dir), "--rollback",
        "--rollback-application-to", previous,
    ])
    assert upgrade_tool.main() == 0
    output = capsys.readouterr().out
    assert '"application_rollback": "planned"' in output
    assert '"application_sha_verified": null' in output
    assert '"schema_status": "compatible"' in output
    assert _rev(repo) == upgraded
