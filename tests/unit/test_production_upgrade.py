from __future__ import annotations

import os
import sqlite3
import stat
import subprocess
from pathlib import Path

import pytest

from tools.production_upgrade import (
    UpgradeRefused, require_idle_tasks, restore_tracked_code_modes,
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
