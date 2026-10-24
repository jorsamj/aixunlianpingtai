#!/usr/bin/env python3
"""Guarded release of the existing Git-worktree systemd production installation.

This operator-invoked tool does not back up, delete, or migrate business data.
It refuses non-idle task state, enforces a pinned fast-forward and normalizes
tracked code permissions before bringing services online.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import stat
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

BRANCH = "feature/external-algorithm-publishing"
TERMINAL_STATES = frozenset({
    "SUCCEEDED", "PARTIAL_SUCCESS", "FAILED", "CANCELLED",
    "BLOCKED_BY_ENVIRONMENT", "BLOCKED_BY_HARDWARE",
})


class UpgradeRefused(RuntimeError):
    pass


def command(*args: str, cwd: Path | None = None) -> str:
    proc = subprocess.run(
        args, cwd=cwd, capture_output=True, text=True, check=False,
    )
    if proc.returncode:
        raise UpgradeRefused(
            f"{' '.join(args)} failed ({proc.returncode}): {proc.stderr.strip()}"
        )
    return proc.stdout.strip()


def require_idle_tasks(data_dir: Path) -> None:
    path = data_dir / "task_runtime" / "tasks.sqlite3"
    if not path.is_file():
        raise UpgradeRefused(f"TASK_DB_MISSING: cannot prove task idleness: {path}")
    uri = path.resolve().as_uri() + "?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True, timeout=3) as db:
            db.execute("PRAGMA busy_timeout=3000")
            # Keep the bound parameters in sync with the declared terminal
            # states. Unknown and NULL statuses must fail closed.
            terminal_states = tuple(sorted(TERMINAL_STATES))
            placeholders = ",".join("?" for _ in terminal_states)
            rows = db.execute(
                "SELECT task_id, status FROM tasks "
                f"WHERE status IS NULL OR status NOT IN ({placeholders}) LIMIT 6",
                terminal_states,
            ).fetchall()
    except sqlite3.Error as exc:
        raise UpgradeRefused(f"TASK_STATUS_UNAVAILABLE: {exc}") from exc
    if rows:
        examples = ", ".join(f"{task_id}:{status}" for task_id, status in rows[:5])
        raise UpgradeRefused(f"ACTIVE_TASKS_BLOCK_UPGRADE: {examples}")


def restore_tracked_code_modes(repo: Path) -> int:
    """Restore Git 100644/100755 file modes; do not chmod untracked data."""
    entries = subprocess.check_output(
        ["git", "ls-files", "--stage", "-z"], cwd=repo,
    ).split(b"\0")
    fixed = 0
    for entry in entries:
        if not entry:
            continue
        metadata, raw_path = entry.split(b"\t", 1)
        mode = metadata.split(b" ", 1)[0]
        if mode not in (b"100644", b"100755"):
            continue
        file = repo / os.fsdecode(raw_path)
        if file.is_symlink() or not file.is_file():
            raise UpgradeRefused(f"CODE_WORKTREE_FILE_MISSING: {file}")
        expected = 0o755 if mode == b"100755" else 0o644
        if stat.S_IMODE(file.stat().st_mode) != expected:
            file.chmod(expected)
            fixed += 1
        parent = file.parent
        while parent == repo or repo in parent.parents:
            current = stat.S_IMODE(parent.stat().st_mode)
            if current & 0o055 != 0o055:
                parent.chmod(current | 0o055)
            if parent == repo:
                break
            parent = parent.parent
    return fixed


def verify_service_code_access(repo: Path, unit: str) -> None:
    service_user = command("systemctl", "show", unit, "--value", "-p", "User")
    if not service_user:
        return  # Unspecified systemd User means root.
    for name in ("app.py", "task_worker.py", "train_worker.py",
                 "platform_core/service_nodes.py", "platform_core/training_precision.py"):
        command("runuser", "-u", service_user, "--", "test", "-r", str(repo / name))


def wait_web_health(timeout: float = 45.0) -> dict:
    url = "http://127.0.0.1:8010/api/health"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                result = json.load(response)
            if isinstance(result, dict) and result.get("ok") is True:
                return result
        except (OSError, ValueError, json.JSONDecodeError):
            pass
        time.sleep(1)
    raise UpgradeRefused("WEB_HEALTH_TIMEOUT: Web did not return ok=true")


def upgrade(repo: Path, data_dir: Path, target: str, apply: bool,
            acknowledge_no_backup: bool) -> None:
    repo = repo.resolve()
    os.umask(0o022)
    if not re.fullmatch(r"[0-9a-f]{40}", target):
        raise UpgradeRefused("TARGET_SHA_REQUIRED: supply a reviewed 40-character commit SHA")
    if os.name != "posix":
        raise UpgradeRefused("Linux systemd host required")
    if apply and os.geteuid() != 0:
        raise UpgradeRefused("ROOT_REQUIRED: run the upgrade from the authorized host")
    current_branch = command("git", "branch", "--show-current", cwd=repo)
    if current_branch != BRANCH:
        raise UpgradeRefused(f"WRONG_BRANCH: {current_branch}")
    if command("git", "status", "--porcelain", cwd=repo):
        raise UpgradeRefused("DIRTY_CODE_WORKTREE: review local changes before upgrading")
    previous = command("git", "rev-parse", "HEAD", cwd=repo)
    require_idle_tasks(data_dir)
    for unit in ("changlian-web.service", "changlian-worker.service"):
        if command("systemctl", "is-active", unit) != "active":
            raise UpgradeRefused(f"SERVICE_NOT_HEALTHY_BEFORE_UPGRADE: {unit}")
    command("git", "fetch", "--no-tags", "origin", BRANCH, cwd=repo)
    command("git", "merge-base", "--is-ancestor", previous, target, cwd=repo)
    command("git", "merge-base", "--is-ancestor", target, "FETCH_HEAD", cwd=repo)
    print(f"Verified {previous[:12]} -> {target[:12]} ({BRANCH}); no active tasks.")
    if not apply:
        print("DRY RUN: no services stopped, no code changed.")
        return
    if not acknowledge_no_backup:
        raise UpgradeRefused(
            "DATA_BACKUP_NOT_ACKNOWLEDGED: pass --acknowledge-no-data-backup "
            "only after accepting that Git cannot restore database changes"
        )
    command("systemctl", "stop", "changlian-worker.service")
    command("systemctl", "stop", "changlian-web.service")
    switched = False
    try:
        require_idle_tasks(data_dir)
        command("git", "merge", "--ff-only", target, cwd=repo)
        switched = True
        changed = restore_tracked_code_modes(repo)
        print(f"Code permissions normalized: {changed} tracked files.")
        verify_service_code_access(repo, "changlian-web.service")
        verify_service_code_access(repo, "changlian-worker.service")
        command("systemctl", "start", "changlian-web.service")
        health = wait_web_health()
        command("systemctl", "start", "changlian-worker.service")
        time.sleep(2)
        if command("systemctl", "is-active", "changlian-worker.service") != "active":
            raise UpgradeRefused("WORKER_NOT_ACTIVE_AFTER_UPGRADE")
        actual = command("git", "rev-parse", "HEAD", cwd=repo)
        if actual != target:
            raise UpgradeRefused("TARGET_MISMATCH_AFTER_UPGRADE")
        print(f"SUCCESS: {target[:12]} Web={health.get('version')} Worker=active")
    except Exception:
        if not switched:
            # No code was switched; restore the previous running services.
            subprocess.run(["systemctl", "start", "changlian-web.service"], check=False)
            subprocess.run(["systemctl", "start", "changlian-worker.service"], check=False)
        else:
            # Never silently revert code against potentially migrated business state.
            subprocess.run(["systemctl", "stop", "changlian-worker.service"], check=False)
            subprocess.run(["systemctl", "stop", "changlian-web.service"], check=False)
            print(f"STOPPED: inspected target={target}; previous={previous}. "
                  "Business data was not restored or modified by this tool.", file=sys.stderr)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path("/data/platform/aixunlianpingtai"))
    parser.add_argument("--data-dir", type=Path, default=Path("/data/platform-data"))
    parser.add_argument("--target", required=True, help="pinned, CI-verified Git commit SHA")
    parser.add_argument("--apply", action="store_true", help="actually switch code and services")
    parser.add_argument("--acknowledge-no-data-backup", action="store_true")
    args = parser.parse_args()
    try:
        upgrade(args.repo, args.data_dir, args.target, args.apply,
                args.acknowledge_no_data_backup)
        return 0
    except (UpgradeRefused, OSError, subprocess.CalledProcessError) as exc:
        print(f"DEPLOYMENT_REFUSED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
