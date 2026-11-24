"""N6.1 remaining safety-boundary tests for ``tools/production_upgrade.py``.

These tests are isolated: temporary SQLite databases plus a real temporary Git
repository, with only ``systemctl``/web-health (and, where stated, the Git
working-tree mutation) mocked.  They prove the tool's behavior; no production
host, systemd unit, database or service is touched.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from tools import production_upgrade as upgrade_tool
from tools.production_upgrade import (
    SYSTEMD_CONFIG_RISK_CODE,
    UpgradeRefused,
    capture_systemd_configuration,
    compare_systemd_configuration,
    create_data_backup,
    load_backup_manifest,
    require_post_stop_idle,
    resolve_frontend_build_identity,
    resolve_python_dependency_fingerprint,
    restore_data_backup,
    verify_data_backup,
)

BRANCH = upgrade_tool.BRANCH
PREVIOUS_SHA = "1" * 40
TARGET_SHA = "2" * 40
OLD_VERSION = "42.24.501"
NEW_VERSION = "42.24.592"
FOOTPRINT = b"catalog-runtime"
APP_FOOTPRINT = b"app-runtime"


# ---------------------------------------------------------------------------
# Temporary Git repository (real commits/checkouts, no production Git writes)
# ---------------------------------------------------------------------------

def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True,
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
    """Return (repo, oldest, previous, upgraded) on the release branch."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "N6.1 Test")
    _git(repo, "config", "user.email", "n61@example.invalid")
    _git(repo, "checkout", "-q", "-b", BRANCH)
    _write_schema_sources(repo, tasks_version=8)
    (repo / "VERSION.txt").write_text(OLD_VERSION + "\n", encoding="utf-8")
    # The deployed frontend build output is gitignored build output; this is
    # exactly why it needs its own identity binding in backup.json.
    (repo / ".gitignore").write_text(
        "/static/vue-catalog/\n/static/vue-app/\n", encoding="utf-8",
    )
    (repo / "requirements.txt").write_text(
        "fastapi>=0.115.0,<1.0.0\nuvicorn>=0.30.0,<1.0.0\n", encoding="utf-8",
    )
    (repo / "static").mkdir()
    (repo / "static" / "main.mjs").write_text(
        "const UI_BUILD_VERSION = '42.25.0-dev';\n", encoding="utf-8",
    )
    oldest = _commit(repo, "oldest supported code")
    (repo / "docs").mkdir()
    (repo / "docs" / "note.txt").write_text("ancestor-only change\n", encoding="utf-8")
    previous = _commit(repo, "previous running code")
    _write_schema_sources(repo, tasks_version=9)
    (repo / "VERSION.txt").write_text(NEW_VERSION + "\n", encoding="utf-8")
    upgraded = _commit(repo, "upgraded code")
    assert len(oldest) == len(previous) == len(upgraded) == 40
    return repo, oldest, previous, upgraded


# ---------------------------------------------------------------------------
# Temporary data directory and deployed frontend build
# ---------------------------------------------------------------------------

def _connect(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path)


def _write_task_database(
    data_dir: Path, *, user_version: int = 8,
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
        database.execute(
            "CREATE TABLE execution_resource_holds (task_id TEXT PRIMARY KEY, "
            "node_id TEXT, state TEXT)"
        )
        database.execute(f"PRAGMA user_version={int(user_version)}")
    return path


def _write_materials_database(data_dir: Path) -> Path:
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
        database.execute("PRAGMA user_version=7")
    return path


def _make_data_dir(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    _write_task_database(data_dir)
    _write_materials_database(data_dir)
    return data_dir


def _write_frontend_build(
    repo: Path, *, code_sha: str,
    catalog_runtime: bytes = FOOTPRINT,
    app_runtime: bytes = APP_FOOTPRINT,
) -> None:
    """Write the deployed frontend build (gitignored) plus CI-style receipts."""

    def write(prefix: str, name: str, payload: bytes) -> None:
        directory = repo / Path(prefix)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / name).write_bytes(payload)
        receipt = {
            "sha": code_sha,
            "build_origin": "github-actions",
            "assets": {
                name: {
                    "bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                },
            },
        }
        (directory / "offline-assets.json").write_text(
            json.dumps(receipt, indent=2) + "\n", encoding="utf-8",
        )

    write("static/vue-catalog", "catalog-preview.js", catalog_runtime)
    write("static/vue-app", "index.js", app_runtime)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _service_recorder(calls: list[tuple[str, ...]]):
    def fake_systemctl(*args: str) -> str:
        calls.append(tuple(args))
        return "active" if args[:1] == ("is-active",) else ""
    return fake_systemctl


def _health_ok(timeout: float = 45.0) -> dict:
    return {"ok": True, "version": "n61-test-version"}


def _install_service_mocks(monkeypatch) -> list[tuple[str, ...]]:
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(upgrade_tool, "_systemctl", _service_recorder(calls))
    monkeypatch.setattr(upgrade_tool, "_require_apply_privileges", lambda: None)
    monkeypatch.setattr(upgrade_tool, "wait_web_health", _health_ok)
    return calls


# ---------------------------------------------------------------------------
# N6.1 item 1: frontend build identity + Python dependency fingerprint
# ---------------------------------------------------------------------------

def test_backup_binds_frontend_build_and_python_dependency_identity(
    tmp_path, monkeypatch,
):
    repo, oldest, previous, upgraded = _make_git_history(tmp_path)
    _git(repo, "checkout", "-q", previous)
    _write_frontend_build(repo, code_sha=previous)
    versions = {"fastapi": "0.115.1", "uvicorn": "0.30.6"}
    monkeypatch.setattr(
        upgrade_tool, "_installed_distribution_version", versions.get,
    )
    data_dir = _make_data_dir(tmp_path)
    backup_dir = tmp_path / "backup"
    result = create_data_backup(
        data_dir, backup_dir, previous_sha=previous, target_sha=upgraded,
        repo=repo,
    )

    manifest = load_backup_manifest(backup_dir)
    frontend = manifest["frontend_build"]
    assert frontend["status"] == "ok"
    assert re.fullmatch(r"[0-9a-f]{64}", frontend["identity"])
    assert frontend["receipt_code_sha"] == previous
    assert frontend["matches_code_sha"] is True
    assert frontend["build_origin"] == "github-actions"
    assert frontend["ui_build_version"] == "42.25.0-dev"
    assert {
        entry["path"] for entry in frontend["receipts"]
    } == set(upgrade_tool.FRONTEND_BUILD_RECEIPTS)
    assert all(
        entry["asset_verification"] == "worktree_hashes"
        for entry in frontend["receipts"]
    )
    assert frontend["verified_asset_bytes"] == len(FOOTPRINT) + len(APP_FOOTPRINT)

    dependencies = manifest["python_dependencies"]
    assert dependencies["status"] == "ok"
    assert dependencies["installed"] == versions
    assert dependencies["installed_count"] == 2
    assert re.fullmatch(r"[0-9a-f]{64}", dependencies["fingerprint"])
    assert re.fullmatch(r"[0-9a-f]{64}", dependencies["requirements_digest"])
    assert [item["path"] for item in dependencies["requirements"]] == [
        "requirements.txt"
    ]
    assert result["frontend_build"]["identity"] == frontend["identity"]
    assert result["python_dependencies"]["fingerprint"] == (
        dependencies["fingerprint"]
    )
    assert verify_data_backup(backup_dir)["ok"] is True

    # A rebuilt / partially copied dropdown without a matching receipt must not
    # read as a clean identity.
    (repo / "static" / "vue-catalog" / "catalog-preview.js").write_bytes(
        b"rebuilt-without-updating-the-receipt"
    )
    broken = resolve_frontend_build_identity(repo, expected_code_sha=previous)
    assert broken["status"] == "invalid"
    assert "ASSET_SIZE_MISMATCH" in broken["reason"] or (
        "ASSET_SHA256_MISMATCH" in broken["reason"]
    )


def test_identity_binding_records_explicit_unavailable_without_guessing(
    tmp_path, monkeypatch,
):
    repo, oldest, previous, upgraded = _make_git_history(tmp_path)
    _git(repo, "checkout", "-q", previous)
    monkeypatch.setattr(
        upgrade_tool, "_installed_distribution_version", lambda name: None,
    )
    data_dir = _make_data_dir(tmp_path)
    backup_dir = tmp_path / "backup"
    result = create_data_backup(
        data_dir, backup_dir, previous_sha=previous, target_sha=upgraded,
        repo=None,
    )
    manifest = load_backup_manifest(backup_dir)
    frontend = manifest["frontend_build"]
    dependencies = manifest["python_dependencies"]
    assert frontend["status"] == "unavailable"
    assert frontend["identity"] is None
    assert frontend["reason"] == "NO_REPOSITORY_REFERENCE"
    assert frontend["matches_code_sha"] == "unknown"
    assert dependencies["status"] == "unavailable"
    assert dependencies["fingerprint"] is None
    assert dependencies["installed"] == {}
    assert result["frontend_build"]["status"] == "unavailable"
    assert verify_data_backup(backup_dir)["ok"] is True


def test_rollback_reports_frontend_and_python_identity_risks(
    tmp_path, monkeypatch,
):
    repo, oldest, previous, upgraded = _make_git_history(tmp_path)
    _git(repo, "checkout", "-q", previous)
    _write_frontend_build(repo, code_sha=previous)
    versions = {"fastapi": "0.115.1"}
    monkeypatch.setattr(
        upgrade_tool, "_installed_distribution_version", versions.get,
    )
    data_dir = _make_data_dir(tmp_path)
    backup_dir = tmp_path / "backup"
    create_data_backup(
        data_dir, backup_dir, previous_sha=previous, target_sha=upgraded,
        repo=repo,
    )

    # The upgrade deployed new code, rebuilt the frontend and upgraded fastapi.
    _git(repo, "checkout", "-q", BRANCH)
    _write_frontend_build(
        repo, code_sha=upgraded,
        catalog_runtime=b"catalog-runtime-v2",
        app_runtime=b"app-runtime-v2",
    )
    versions["fastapi"] = "0.116.0"

    result = restore_data_backup(
        backup_dir, data_dir, apply=False, acknowledge_data_restore=False,
        app_sha=previous, repo=repo,
    )
    binding = result["application_identity_binding"]
    frontend = binding["frontend_build"]
    assert frontend["recorded_status"] == "ok"
    assert frontend["matches_recorded"] is False
    # The frontend build output is gitignored, so a detached checkout of the
    # previous code cannot restore it: this must be an explicit risk, not a
    # silent claim that the full application was rolled back.
    assert frontend["restorable_by_git"] is False
    assert "frontend build receipts are gitignored" in (
        frontend["not_restorable_by_git_reason"]
    )
    assert frontend["receipt_sha_matches_target_code"] is False
    assert "FRONTEND_BUILD_CHANGED_SINCE_BACKUP" in binding["risks"]
    assert "FRONTEND_BUILD_BOUND_TO_DIFFERENT_CODE_SHA" in binding["risks"]

    dependencies = binding["python_dependencies"]
    assert dependencies["installed_matches"] is False
    assert dependencies["changed_packages"] == {
        "fastapi": {"backup": "0.115.1", "current": "0.116.0"},
    }
    assert "PYTHON_DEPENDENCY_VERSION_DRIFT" in binding["risks"]
    assert result["identity_risks"] == binding["risks"]
    assert result["mode"] == "DRY RUN"
    assert result["application_rollback"] == "planned"


# ---------------------------------------------------------------------------
# N6.1 item 2: read-only systemd unit/environment configuration diff
# ---------------------------------------------------------------------------

def test_systemd_configuration_diff_is_read_only_and_explicit_risk(
    tmp_path, monkeypatch,
):
    unit = tmp_path / "changlian-web.service"
    unit.write_text("[Service]\nExecStart=/bin/true\n", encoding="utf-8")
    drop_in = tmp_path / "override.conf"
    drop_in.write_text("Environment=MC_MODE=local\n", encoding="utf-8")
    environment_file = tmp_path / "changlian-web.env"
    environment_file.write_text("MC_MODE=local\n", encoding="utf-8")

    mapping = {
        ("systemctl", "show", upgrade_tool.WEB_UNIT, "--value", "-p",
         "FragmentPath"): str(unit),
        ("systemctl", "show", upgrade_tool.WEB_UNIT, "--value", "-p",
         "DropInPaths"): str(drop_in),
        ("systemctl", "show", upgrade_tool.WEB_UNIT, "--value", "-p",
         "EnvironmentFiles"): f"{environment_file} (ignore_errors=no)",
        ("systemctl", "show", upgrade_tool.WEB_UNIT, "--value", "-p",
         "Environment"): "MC_MODE=local",
    }

    def fake_command(*args: str, cwd=None) -> str:
        return mapping.get(tuple(args), "")

    monkeypatch.setattr(upgrade_tool, "command", fake_command)
    before = capture_systemd_configuration()
    assert before["units"][upgrade_tool.WEB_UNIT]["probe"] == "ok"
    assert before["units"][upgrade_tool.WEB_UNIT]["fragment"]["status"] == "readable"
    # Raw Environment= values may carry secrets; only a digest is recorded.
    assert "MC_MODE=local" not in json.dumps(before)

    environment_file.write_text("MC_MODE=production\n", encoding="utf-8")
    after = capture_systemd_configuration()
    comparison = compare_systemd_configuration(before, after)
    assert comparison["status"] == "changed"
    assert comparison["risk"] == SYSTEMD_CONFIG_RISK_CODE
    assert upgrade_tool.WEB_UNIT in comparison["changed_units"]
    assert "never rewrites" in comparison["note"]

    # The comparison itself never rewrites a unit/drop-in/environment file.
    assert environment_file.read_text(encoding="utf-8") == "MC_MODE=production\n"
    unchanged = compare_systemd_configuration(after, after)
    assert unchanged["status"] == "unchanged"
    assert unchanged["risk"] is None
    assert unchanged["changed_units"] == []


def test_upgrade_apply_reports_systemd_configuration_change_as_risk(
    tmp_path, monkeypatch, capsys,
):
    repo, oldest, previous, upgraded = _make_git_history(tmp_path)
    _git(repo, "checkout", "-q", previous)
    data_dir = _make_data_dir(tmp_path)
    unit = tmp_path / "changlian-web.service"
    unit.write_text("[Service]\nExecStart=/bin/true\n", encoding="utf-8")
    environment_file = tmp_path / "changlian-web.env"
    environment_file.write_text("MC_MODE=local\n", encoding="utf-8")
    state = {"head": previous}
    calls: list[tuple[str, ...]] = []

    def fake_command(*args: str, cwd=None) -> str:
        calls.append(tuple(args))
        if args[:2] == ("git", "branch"):
            return BRANCH
        if args[:2] == ("git", "status"):
            return ""
        if args[:2] == ("git", "rev-parse"):
            return state["head"]
        if args[:2] == ("git", "fetch"):
            return ""
        if args[:2] == ("git", "merge-base"):
            return ""
        if args[:2] == ("git", "merge"):
            state["head"] = args[-1]
            # Simulate an out-of-band edit of the service environment made
            # while the services were down; the tool must only report it.
            environment_file.write_text("MC_MODE=production\n", encoding="utf-8")
            return ""
        if args[:1] == ("systemctl",):
            if args[:2] == ("systemctl", "is-active"):
                return "active"
            if args[:2] == ("systemctl", "show"):
                return {
                    "FragmentPath": str(unit),
                    "DropInPaths": "",
                    "EnvironmentFiles": f"{environment_file} (ignore_errors=no)",
                    "Environment": "MC_MODE=local",
                }.get(args[-1], "")
            return ""
        return ""

    monkeypatch.setattr(upgrade_tool, "command", fake_command)
    monkeypatch.setattr(upgrade_tool, "_require_upgrade_privileges", lambda apply: None)
    monkeypatch.setattr(upgrade_tool, "restore_tracked_code_modes", lambda repo: 0)
    monkeypatch.setattr(
        upgrade_tool, "verify_service_code_access", lambda repo, unit: None,
    )
    monkeypatch.setattr(upgrade_tool, "wait_web_health", _health_ok)

    upgrade_tool.upgrade(repo, data_dir, TARGET_SHA, True, True)

    captured = capsys.readouterr()
    assert "SUCCESS:" in captured.out
    assert "SYSTEMD_CONFIGURATION_RISK" in captured.err
    assert SYSTEMD_CONFIG_RISK_CODE in captured.err
    assert any(call[:2] == ("git", "merge") for call in calls)
    assert any(
        call[:3] == ("systemctl", "start", upgrade_tool.WEB_UNIT)
        for call in calls
    )


# ---------------------------------------------------------------------------
# N6.1 item 3: post-stop activity recheck fails closed
# ---------------------------------------------------------------------------

def test_post_stop_recheck_blocks_rollback_and_never_auto_forces(
    tmp_path, monkeypatch, capsys,
):
    repo, oldest, previous, upgraded = _make_git_history(tmp_path)
    _git(repo, "checkout", "-q", previous)
    data_dir = _make_data_dir(tmp_path)
    backup_dir = tmp_path / "backup"
    created = create_data_backup(
        data_dir, backup_dir, previous_sha=previous, target_sha=upgraded,
        repo=repo,
    )
    _git(repo, "checkout", "-q", BRANCH)
    task_database = data_dir / "task_runtime" / "tasks.sqlite3"
    calls: list[tuple[str, ...]] = []
    injected = {"done": False}

    def fake_systemctl(*args: str) -> str:
        calls.append(tuple(args))
        if (
            args[:2] == ("stop", upgrade_tool.WORKER_UNIT)
            and not injected["done"]
        ):
            injected["done"] = True
            # An unreleased hold appears after the pre-stop probes: the
            # post-stop recheck must observe it and refuse.
            with _connect(task_database) as database:
                database.execute(
                    "INSERT INTO execution_resource_holds VALUES "
                    "('task-late','n1','HELD')"
                )
        return "active" if args[:1] == ("is-active",) else ""

    monkeypatch.setattr(upgrade_tool, "_systemctl", fake_systemctl)
    monkeypatch.setattr(upgrade_tool, "_require_apply_privileges", lambda: None)
    monkeypatch.setattr(upgrade_tool, "wait_web_health", _health_ok)

    with pytest.raises(
        UpgradeRefused, match="POST_STOP_ACTIVITY_BLOCK_ROLLBACK",
    ):
        restore_data_backup(
            backup_dir, data_dir, apply=True, acknowledge_data_restore=True,
            app_sha=previous, repo=repo,
        )
    assert calls[:2] == [
        ("stop", upgrade_tool.WORKER_UNIT),
        ("stop", upgrade_tool.WEB_UNIT),
    ]
    assert not any(call[0] == "start" for call in calls)
    # The restore never ran: the injected hold is still there and the task DB
    # does not match the verified manifest.
    entry = {
        item["relative_path"]: item for item in created["entries"]
    }["task_runtime/tasks.sqlite3"]
    assert _sha256(task_database) != entry["sha256"]
    with _connect(task_database) as database:
        assert database.execute(
            "SELECT state FROM execution_resource_holds"
        ).fetchall() == [("HELD",)]
    # Code checkout never happened, so the operator can still see the failed
    # state; the safety snapshot is real and verifiable.
    assert _rev(repo) == upgraded
    assert _git(repo, "branch", "--show-current").stdout.strip() == BRANCH
    safety_directories = list((backup_dir / "pre-rollback").iterdir())
    assert len(safety_directories) == 1
    assert verify_data_backup(safety_directories[0])["ok"] is True
    assert "STOPPED" in capsys.readouterr().err

    # Only an explicit --force-idle records an override, and even then the
    # result is a forced decision with write_silence=unverified.
    forced = require_post_stop_idle(
        data_dir, repo=repo, block_code="POST_STOP_ACTIVITY_BLOCK_ROLLBACK",
        force_idle=True,
    )
    assert forced["status"] == "forced"
    assert forced["forced"] is True
    assert "UNRELEASED_RESOURCE_HOLDS_BLOCK_BACKUP" in forced["forced_reasons"]
    assert forced["write_silence"] == "unverified"


def test_upgrade_post_stop_recheck_blocks_before_code_switch(
    tmp_path, monkeypatch,
):
    repo, oldest, previous, upgraded = _make_git_history(tmp_path)
    _git(repo, "checkout", "-q", previous)
    data_dir = _make_data_dir(tmp_path)
    task_database = data_dir / "task_runtime" / "tasks.sqlite3"
    commands: list[tuple[str, ...]] = []
    restarts: list[tuple[str, ...]] = []
    injected = {"done": False}

    def fake_command(*args: str, cwd=None) -> str:
        commands.append(tuple(args))
        if args[:2] == ("git", "branch"):
            return BRANCH
        if args[:2] == ("git", "status"):
            return ""
        if args[:2] == ("git", "rev-parse"):
            return previous
        if args[:2] in (("git", "fetch"), ("git", "merge-base")):
            return ""
        if args[:1] == ("systemctl",):
            if args[:2] == ("systemctl", "is-active"):
                return "active"
            if args[:2] == ("systemctl", "stop"):
                if args[2] == upgrade_tool.WORKER_UNIT and not injected["done"]:
                    injected["done"] = True
                    with _connect(task_database) as database:
                        database.execute(
                            "INSERT INTO execution_resource_holds VALUES "
                            "('task-late','n1','HELD')"
                        )
            return ""
        return ""

    def fake_run(args, **kwargs):
        restarts.append(tuple(args))
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(upgrade_tool, "command", fake_command)
    monkeypatch.setattr(upgrade_tool, "_require_upgrade_privileges", lambda apply: None)
    monkeypatch.setattr(upgrade_tool.subprocess, "run", fake_run)

    with pytest.raises(
        UpgradeRefused, match="POST_STOP_ACTIVITY_BLOCK_UPGRADE",
    ):
        upgrade_tool.upgrade(repo, data_dir, TARGET_SHA, True, True)

    assert not any(call[:2] == ("git", "merge") for call in commands)
    # No code was switched, so the previous services are restarted; nothing is
    # force-released and no database is touched.
    assert (
        "systemctl", "start", upgrade_tool.WEB_UNIT,
    ) in restarts
    assert (
        "systemctl", "start", upgrade_tool.WORKER_UNIT,
    ) in restarts


# ---------------------------------------------------------------------------
# N6.1 items 4 + 5: detached HEAD after rollback and re-upgrade semantics
# ---------------------------------------------------------------------------

def test_detached_head_after_rollback_blocks_upgrade_until_branch_restored(
    tmp_path, monkeypatch, capsys,
):
    repo, oldest, previous, upgraded = _make_git_history(tmp_path)
    _git(repo, "checkout", "-q", previous)
    data_dir = _make_data_dir(tmp_path)
    backup_dir = tmp_path / "backup"
    create_data_backup(
        data_dir, backup_dir, previous_sha=previous, target_sha=upgraded,
        repo=repo,
    )
    _git(repo, "checkout", "-q", BRANCH)
    _install_service_mocks(monkeypatch)
    result = restore_data_backup(
        backup_dir, data_dir, apply=True, acknowledge_data_restore=True,
        app_sha=previous, repo=repo,
    )
    assert result["mode"] == "APPLIED"
    assert result["detached_head"] is True
    assert result["branch_restore_required"] is True
    expected_command = f"git -C {repo} switch {BRANCH}"
    assert result["branch_restore_command"] == expected_command
    assert _rev(repo) == previous
    assert _git(repo, "branch", "--show-current").stdout.strip() == ""

    # A later --target upgrade is refused with the explicit restore command;
    # the tool never switches the branch or merges by itself.
    monkeypatch.setattr(upgrade_tool, "_require_upgrade_privileges", lambda apply: None)
    recorded: list[tuple[str, ...]] = []
    original_command = upgrade_tool.command

    def recording_command(*args: str, cwd=None) -> str:
        recorded.append(tuple(args))
        return original_command(*args, cwd=cwd)

    monkeypatch.setattr(upgrade_tool, "command", recording_command)
    with pytest.raises(
        UpgradeRefused, match="DETACHED_HEAD_UPGRADE_BLOCKED",
    ) as refusal:
        upgrade_tool.upgrade(repo, data_dir, upgraded, False, False)
    assert expected_command in str(refusal.value)
    assert not any(call[:2] == ("git", "merge") for call in recorded)
    assert not any(call[:2] == ("git", "checkout") for call in recorded)

    # After the operator restores the release branch explicitly, the normal
    # preflight (dry run) is allowed again and still does not merge anything.
    _git(repo, "switch", "-q", BRANCH)
    assert _rev(repo) == upgraded
    dry_run_calls: list[tuple[str, ...]] = []

    def tolerant_command(*args: str, cwd=None) -> str:
        dry_run_calls.append(tuple(args))
        if args[:2] == ("systemctl", "is-active"):
            return "active"
        if args[:1] == ("systemctl",):
            return ""
        if args[:2] == ("git", "fetch"):
            return ""
        if args[:2] == ("git", "merge-base"):
            return ""
        return original_command(*args, cwd=cwd)

    monkeypatch.setattr(upgrade_tool, "command", tolerant_command)
    upgrade_tool.upgrade(repo, data_dir, upgraded, False, False)
    output = capsys.readouterr().out
    assert "DRY RUN: no services stopped, no code changed." in output
    assert "Verified" in output
    assert not any(call[:2] == ("git", "merge") for call in dry_run_calls)


def test_partial_restore_failure_stays_diagnosable_and_blocks_next_upgrade(
    tmp_path, monkeypatch, capsys,
):
    repo, oldest, previous, upgraded = _make_git_history(tmp_path)
    _git(repo, "checkout", "-q", previous)
    data_dir = _make_data_dir(tmp_path)
    backup_dir = tmp_path / "backup"
    create_data_backup(
        data_dir, backup_dir, previous_sha=previous, target_sha=upgraded,
        repo=repo,
    )
    _git(repo, "checkout", "-q", BRANCH)
    _install_service_mocks(monkeypatch)
    original_replace = upgrade_tool._replace_database_file

    def failing_replace(source: Path, target: Path) -> None:
        if target.name == "tasks.sqlite3":
            raise OSError("simulated replacement failure for tasks.sqlite3")
        original_replace(source, target)

    monkeypatch.setattr(upgrade_tool, "_replace_database_file", failing_replace)
    monkeypatch.setattr(sys, "argv", [
        "production_upgrade.py", "--repo", str(repo), "--data-dir",
        str(data_dir), "--backup-dir", str(backup_dir), "--rollback", "--apply",
        "--acknowledge-data-restore", "--rollback-application-to", previous,
    ])
    assert upgrade_tool.main() == 1
    captured = capsys.readouterr()
    payload = json.loads(captured.out[captured.out.index("{"):])
    assert payload["mode"] == "PARTIAL_RESTORE"
    assert payload["services"] == "stopped"
    assert payload["partial_restore"]["restored"] == [
        "projects/p1/materials.sqlite3"
    ]
    assert [
        item["relative_path"]
        for item in payload["partial_restore"]["failed"]
    ] == ["task_runtime/tasks.sqlite3"]
    assert payload["safety_backup_dir"] is not None
    assert payload["post_stop_activity"]["status"] == "verified"
    assert verify_data_backup(Path(payload["safety_backup_dir"]))["ok"] is True
    assert "STOPPED" in captured.err

    # The coordinated checkout already happened: the worktree is detached and
    # a subsequent upgrade is refused until the branch is restored explicitly.
    assert _rev(repo) == previous
    assert _git(repo, "branch", "--show-current").stdout.strip() == ""
    monkeypatch.setattr(upgrade_tool, "_require_upgrade_privileges", lambda apply: None)
    with pytest.raises(
        UpgradeRefused, match="DETACHED_HEAD_UPGRADE_BLOCKED",
    ):
        upgrade_tool.upgrade(repo, data_dir, upgraded, False, False)


# ---------------------------------------------------------------------------
# N6.3: the candidate placeholder must never pass the 40-hex fail-closed gates
# ---------------------------------------------------------------------------

CANDIDATE_DOCUMENT = (
    Path(__file__).resolve().parents[2]
    / "docs" / "architecture"
    / "W15_W16_SINGLE_SLOT_PRODUCTION_CANDIDATE_20261124.md"
)


def test_candidate_sha_placeholder_is_never_treated_as_a_real_sha(
    tmp_path, monkeypatch,
):
    document = CANDIDATE_DOCUMENT.read_text(encoding="utf-8")
    match = re.search(
        r'CANDIDATE_CODE_SHA_40HEX\s*=\s*"([^"]*)"', document,
    )
    assert match is not None, "candidate SHA line missing from the document"
    candidate = match.group(1)
    data_dir = tmp_path / "data"
    _write_task_database(data_dir)

    if candidate == "PENDING_CODE_SHA":
        # Until the lead fills the post-commit remote SHA the placeholder is not
        # a candidate identity; the tool must fail closed instead of guessing.
        assert "由主代理在本轮全部代码提交完成后替换" in document
        assert re.fullmatch(r"[0-9a-f]{40}", candidate) is None
        with pytest.raises(UpgradeRefused, match="TARGET_SHA_REQUIRED"):
            upgrade_tool.upgrade(tmp_path, data_dir, candidate, False, False)
        with pytest.raises(UpgradeRefused, match="PREVIOUS_SHA_REQUIRED"):
            create_data_backup(
                data_dir, tmp_path / "backup", previous_sha=candidate,
            )
        assert not (tmp_path / "backup").exists()
        return

    # After the lead replaces the placeholder the value must be exactly one
    # 40-character SHA that the tool's target gate accepts (the sentinel proves
    # the gate was reached and passed without changing any code or service).
    assert re.fullmatch(r"[0-9a-f]{40}", candidate) is not None
    monkeypatch.setattr(
        upgrade_tool, "_require_upgrade_privileges",
        lambda apply: (_ for _ in ()).throw(
            UpgradeRefused("SHA_GATE_ACCEPTED_TEST_STOP")
        ),
    )
    with pytest.raises(UpgradeRefused, match="SHA_GATE_ACCEPTED_TEST_STOP"):
        upgrade_tool.upgrade(tmp_path, data_dir, candidate, False, False)
