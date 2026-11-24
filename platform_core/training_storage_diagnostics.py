"""Read-only training storage diagnostics.

One bounded, side-effect free view over training workspaces, task artifacts,
checkpoints and the project bundle cache. It never deletes or reclaims
anything; reclamation keeps its existing Owner (TrainingWorkspaceLifecycle /
Task moderation endpoints) and the bundle cache keeps its own maintainer.

Media objects, formal model files outside task artifacts and the control-plane
SQLite databases are reported as *outside* this view: they are not covered by
the project bundle cache or workspace reclamation.
"""
from __future__ import annotations

import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .training_bundle_cache import TrainingBundleCache
from .training_workspace_lifecycle import TrainingWorkspaceLifecycle


DIAGNOSTICS_SCHEMA_VERSION = 1
MAX_TASK_FILES = 20000
MAX_CHECKPOINT_FILES = 50
_TERMINAL_STATUSES = frozenset({
    "SUCCEEDED", "PARTIAL_SUCCESS", "FAILED", "CANCELLED",
    "BLOCKED_BY_ENVIRONMENT", "BLOCKED_BY_HARDWARE",
})


def _bounded_tree(path: Path, *, max_files: int = MAX_TASK_FILES) -> dict[str, Any]:
    """Bounded, link-safe size walk; never follows symlinks/junctions."""
    result: dict[str, Any] = {
        "bytes": 0, "files": 0, "truncated": False, "unsafe_entries": 0, "error": "",
    }
    try:
        if not path.exists() and not path.is_symlink():
            return result
    except OSError as error:
        result["error"] = f"{type(error).__name__}: {error}"
        return result
    pending: list[Path] = [path]
    while pending:
        current = pending.pop()
        try:
            info = current.lstat()
        except OSError:
            result["unsafe_entries"] += 1
            continue
        if stat.S_ISLNK(info.st_mode):
            result["unsafe_entries"] += 1
            continue
        if stat.S_ISDIR(info.st_mode):
            try:
                pending.extend(current.iterdir())
            except OSError as error:
                result["error"] = f"{type(error).__name__}: {error}"
            continue
        if stat.S_ISREG(info.st_mode):
            result["files"] += 1
            result["bytes"] += int(info.st_size)
            if result["files"] >= max_files:
                result["truncated"] = True
                break
            continue
        result["unsafe_entries"] += 1
    return result


def _checkpoint_files(artifacts, task_id: str) -> list[dict[str, Any]]:
    root = Path(artifacts.artifact_path(task_id, "checkpoints"))
    items: list[dict[str, Any]] = []
    if not root.is_dir():
        return items
    try:
        entries = sorted(root.iterdir(), key=lambda item: item.name)
    except OSError:
        return items
    for entry in entries:
        if len(items) >= MAX_CHECKPOINT_FILES:
            break
        try:
            if entry.is_symlink() or not entry.is_file():
                continue
            info = entry.stat()
        except OSError:
            continue
        items.append({
            "name": entry.name,
            "size_bytes": int(info.st_size),
            "modified_at": datetime.fromtimestamp(
                info.st_mtime, tz=timezone.utc).isoformat(),
        })
    return items


def training_storage_diagnostics(
    data_dir: str | Path,
    project_id: str,
    repository,
    artifacts,
    *,
    limit: int = 20,
    include_cache_preview: bool = True,
) -> dict[str, Any]:
    """Bounded read-only view; every classification is advisory."""
    data_dir = Path(data_dir).resolve()
    project_id = str(project_id)
    limit = max(1, min(100, int(limit)))
    lifecycle = TrainingWorkspaceLifecycle(data_dir, repository, artifacts)
    with repository._connect() as database:
        rows = database.execute(
            "SELECT task_id,status,attempt,finished_at FROM tasks "
            "WHERE project_id=? AND kind='TRAINING' "
            "ORDER BY COALESCE(finished_at,'') DESC, task_id DESC LIMIT ?",
            (project_id, limit),
        ).fetchall()
    totals = {
        "workspace_bytes": 0,
        "workspace_reclaimable_bytes": 0,
        "workspace_protected_bytes": 0,
        "workspace_unknown_bytes": 0,
        "artifact_bytes": 0,
        "checkpoint_bytes": 0,
        "task_count": 0,
        "reclaimable_task_count": 0,
        "protected_task_count": 0,
    }
    tasks: list[dict[str, Any]] = []
    for row in rows:
        task_id = str(row[0])
        status = str(row[1] or "")
        terminal = status in _TERMINAL_STATUSES
        workspace: dict[str, Any] = {}
        workspace_bytes = 0
        classification = "unknown"
        blockers: list[str] = []
        try:
            workspace = dict(lifecycle.inspect(project_id, task_id))
            workspace_bytes = int(workspace.get("temporary_logical_bytes") or 0)
            blockers = [str(item) for item in (workspace.get("blockers") or [])]
            classification = "reclaimable" if workspace.get("eligible") else "protected"
        except (OSError, ValueError, KeyError, RuntimeError) as error:
            workspace = {"error": f"{type(error).__name__}: {error}"}
            bundle_bytes = _bounded_tree(
                Path(artifacts.artifact_path(task_id, "work/bundle")))
            workspace_bytes = int(bundle_bytes["bytes"])
            classification = "unknown"
            workspace["bundle_scan"] = bundle_bytes
        if not terminal:
            classification = "protected"
            blockers = sorted(set([*blockers, "TASK_NOT_TERMINAL"]))
        artifact_scan = _bounded_tree(Path(artifacts.root) / task_id)
        checkpoints = _checkpoint_files(artifacts, task_id)
        checkpoint_bytes = sum(int(item["size_bytes"]) for item in checkpoints)
        if classification == "reclaimable":
            totals["workspace_reclaimable_bytes"] += workspace_bytes
            totals["reclaimable_task_count"] += 1
        elif classification == "protected":
            totals["workspace_protected_bytes"] += workspace_bytes
            totals["protected_task_count"] += 1
        else:
            totals["workspace_unknown_bytes"] += workspace_bytes
        totals["workspace_bytes"] += workspace_bytes
        totals["artifact_bytes"] += int(artifact_scan["bytes"])
        totals["checkpoint_bytes"] += checkpoint_bytes
        totals["task_count"] += 1
        tasks.append({
            "task_id": task_id,
            "status": status,
            "terminal": terminal,
            "classification": classification,
            "blockers": blockers,
            "workspace_bytes": workspace_bytes,
            "workspace": workspace,
            "artifact_bytes": int(artifact_scan["bytes"]),
            "artifact_files": int(artifact_scan["files"]),
            "artifact_scan_truncated": bool(artifact_scan["truncated"]),
            "artifact_unsafe_entries": int(artifact_scan["unsafe_entries"]),
            "checkpoints": checkpoints,
        })
    cache_preview: dict[str, Any] | None = None
    if include_cache_preview:
        try:
            cache_preview = TrainingBundleCache(
                data_dir, project_id).maintain(dry_run=True)
        except (OSError, ValueError, RuntimeError) as error:
            cache_preview = {"error": f"{type(error).__name__}: {error}"}
    return {
        "schema_version": DIAGNOSTICS_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project_id": project_id,
        "limit": limit,
        "tasks": tasks,
        "totals": totals,
        "cache_preview": cache_preview,
        "guarantees": {
            "read_only": True,
            "deletion_performed": False,
            "automatic_gc_enabled": False,
            "classifications_are_advisory": True,
        },
        "scope_notes": [
            "workspace_bytes are task-owned portable bundle copies; formal "
            "models and media objects outside task artifacts are not included",
            "cache_preview runs the real maintainer in dry-run mode and "
            "deletes nothing",
            "original materials, control-plane SQLite databases and external "
            "publication state are outside this diagnostic view",
        ],
    }
