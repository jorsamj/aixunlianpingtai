"""Controlled U3 incremental synchronization runner.

Explicit invocation only.  There is no daemon, timer, queue or automatic
production enablement.  The runner wraps the accepted P3 consumer and keeps the
per-project advisory lock, bounded batches, READY publication and failure
classification in that existing implementation.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .u3_incremental_sync import (
    U3IncrementalSyncError,
    diagnose_project,
    synchronize_project,
)


def resolve_project_dir(data_dir: str | Path, project_id: str) -> Path:
    """Resolve one authorized project directory without path traversal/symlinks."""
    identity = str(project_id or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,96}", identity):
        raise ValueError("invalid project identity")
    root = (Path(data_dir) / "projects").resolve()
    candidate = (root / identity).resolve()
    if candidate.parent != root or not candidate.is_dir():
        raise ValueError("project directory is outside the authorized scope")
    meta = candidate / "meta.json"
    if meta.is_file():
        try:
            value = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise ValueError("project metadata is unreadable") from error
        if isinstance(value, dict) and str(value.get("id") or "") not in {"", identity}:
            raise ValueError("project identity does not match its directory")
    return candidate

_TRANSIENT_CODES = frozenset({
    "U3_INCREMENTAL_OWNER_UNAVAILABLE",
    "U3_INCREMENTAL_OWNER_MISSING",
})
_PERMANENT_CODES = frozenset({
    "U3_INCREMENTAL_SEQUENCE_GAP",
    "U3_INCREMENTAL_EVENT_DIGEST_CONFLICT",
    "U3_INCREMENTAL_ENTITY_MISMATCH",
    "U3_INCREMENTAL_EVENT_UNSUPPORTED",
    "U3_INCREMENTAL_LOG_TAIL_MISSING",
    "U3_INCREMENTAL_CURSOR_AHEAD",
    "U3_INCREMENTAL_BASELINE_MISSING",
    "U3_READY_PROJECTION_MISMATCH",
    "U3_READY_BASELINE_MISSING",
    "U3_READY_STREAM_NOT_ALIGNED",
    "U3_READY_CONFIRMATION_WITHOUT_ANNOTATION",
})


@dataclass(frozen=True)
class SyncRunnerConfig:
    """All controls default to disabled/no project scope."""

    enabled: bool = False
    project_ids: tuple[str, ...] = ()
    batch_limit: int = 200
    max_batches: int = 100
    max_seconds: float = 30.0
    retry_attempts: int = 2
    retry_backoff_seconds: float = 0.5
    allow_rebuild: bool = False

    def validate(self) -> None:
        if not 1 <= int(self.batch_limit) <= 1000:
            raise ValueError("batch_limit must be between 1 and 1000")
        if int(self.max_batches) < 1 or float(self.max_seconds) <= 0:
            raise ValueError("max_batches/max_seconds must be positive")
        if int(self.retry_attempts) < 0 or float(self.retry_backoff_seconds) < 0:
            raise ValueError("retry settings must be non-negative")


@dataclass
class SyncProjectResult:
    project_id: str
    status: str
    applied: int = 0
    batches: int = 0
    publication: dict[str, Any] = field(default_factory=dict)
    code: str = ""
    attempts: int = 0
    seconds: float = 0.0


def run_project_sync(
    connection, *, data_dir: str | Path, project_id: str,
    config: SyncRunnerConfig, stop_event=None,
) -> SyncProjectResult:
    """Run one project with bounded retries.  Never rebuilds automatically."""
    config.validate()
    if not config.enabled:
        return SyncProjectResult(project_id, "DISABLED", code="SYNC_DISABLED")
    try:
        project_dir = resolve_project_dir(data_dir, project_id)
    except ValueError as error:
        return SyncProjectResult(
            project_id, "BLOCKED", code="PROJECT_IDENTITY_INVALID",
            publication={"reason": str(error)[:300]},
        )
    started = time.monotonic()
    deadline = started + float(config.max_seconds)
    attempts = 0
    last_code = ""
    while attempts <= int(config.retry_attempts):
        if stop_event is not None and stop_event.is_set():
            return SyncProjectResult(
                project_id, "STOPPED", code="SYNC_STOPPED",
                attempts=attempts, seconds=round(time.monotonic() - started, 3),
            )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return SyncProjectResult(
                project_id, "INCOMPLETE", code="U3_SYNC_TIME_LIMIT",
                attempts=attempts, seconds=round(time.monotonic() - started, 3),
            )
        attempts += 1
        try:
            result = synchronize_project(
                connection, project_dir=project_dir, project_id=project_id,
                limit=int(config.batch_limit),
                max_batches=int(config.max_batches),
                max_seconds=remaining,
            )
            return SyncProjectResult(
                project_id=project_id,
                status=str(result.get("status") or "INCOMPLETE"),
                applied=int(result.get("applied") or 0),
                batches=int(result.get("batches") or 0),
                publication=dict(result.get("publication") or {}),
                attempts=attempts,
                seconds=round(time.monotonic() - started, 3),
            )
        except U3IncrementalSyncError as error:
            last_code = error.code
            if error.code in _PERMANENT_CODES:
                return SyncProjectResult(
                    project_id, "BLOCKED", code=error.code,
                    attempts=attempts, seconds=round(time.monotonic() - started, 3),
                )
            if error.code not in _TRANSIENT_CODES and error.code not in {
                "U3_INCREMENTAL_EVENT_INVALID",
            }:
                return SyncProjectResult(
                    project_id, "FAILED", code=error.code,
                    attempts=attempts, seconds=round(time.monotonic() - started, 3),
                )
            if attempts > int(config.retry_attempts):
                break
            pause = min(
                float(config.retry_backoff_seconds) * attempts,
                max(0.0, deadline - time.monotonic()),
            )
            if pause:
                time.sleep(pause)
    return SyncProjectResult(
        project_id, "RETRY_EXHAUSTED", code=last_code,
        attempts=attempts, seconds=round(time.monotonic() - started, 3),
    )


def run_once(
    connection, *, data_dir: str | Path, config: SyncRunnerConfig,
    stop_event=None,
) -> dict[str, Any]:
    """One explicit fair pass over the configured project scope."""
    config.validate()
    if not config.enabled:
        return {"status": "DISABLED", "projects": []}
    results = []
    for project_id in config.project_ids:
        if stop_event is not None and stop_event.is_set():
            results.append({
                "project_id": project_id, "status": "STOPPED",
                "code": "SYNC_STOPPED",
            })
            break
        results.append(run_project_sync(
            connection, data_dir=data_dir, project_id=project_id,
            config=config, stop_event=stop_event,
        ).__dict__)
    statuses = {row["status"] for row in results}
    if "BLOCKED" in statuses:
        status = "BLOCKED"
    elif "FAILED" in statuses or "RETRY_EXHAUSTED" in statuses:
        status = "FAILED"
    elif "INCOMPLETE" in statuses:
        status = "INCOMPLETE"
    elif "STOPPED" in statuses:
        status = "STOPPED"
    else:
        status = "COMPLETED"
    return {
        "status": status,
        "projects": results,
        "blocked": [row["project_id"] for row in results if row["status"] == "BLOCKED"],
    }


def run_loop(
    connection, *, data_dir: str | Path, config: SyncRunnerConfig,
    stop_event, interval_seconds: float = 5.0, max_rounds: int | None = None,
) -> list[dict[str, Any]]:
    """Explicit bounded loop for an isolated service/maintenance caller only."""
    if not config.enabled:
        return [{"status": "DISABLED", "projects": []}]
    rounds: list[dict[str, Any]] = []
    while not stop_event.is_set():
        rounds.append(run_once(
            connection, data_dir=data_dir, config=config, stop_event=stop_event
        ))
        if max_rounds is not None and len(rounds) >= int(max_rounds):
            break
        if stop_event.wait(max(0.0, float(interval_seconds))):
            break
    return rounds


def sync_status(
    connection, *, data_dir: str | Path, project_id: str,
) -> dict[str, Any]:
    """Read-only status projection; unavailable owner is never reported as zero."""
    return diagnose_project(
        connection, project_dir=Path(data_dir), project_id=project_id
    )
