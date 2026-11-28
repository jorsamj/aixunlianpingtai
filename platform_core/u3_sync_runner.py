"""Controlled U3 incremental synchronization runner.

Explicit invocation only.  There is no daemon, timer, queue or automatic
production enablement.  The runner wraps the accepted P3 consumer and keeps the
per-project advisory lock, bounded batches, READY publication and failure
classification in that existing implementation.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .u3_incremental_sync import (
    U3IncrementalSyncError,
    diagnose_project,
    synchronize_project,
)

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
    config: SyncRunnerConfig,
) -> SyncProjectResult:
    """Run one project with bounded retries.  Never rebuilds automatically."""
    config.validate()
    if not config.enabled:
        return SyncProjectResult(project_id, "DISABLED", code="SYNC_DISABLED")
    started = time.monotonic()
    attempts = 0
    last_code = ""
    while attempts <= int(config.retry_attempts):
        attempts += 1
        try:
            result = synchronize_project(
                connection, project_dir=Path(data_dir), project_id=project_id,
                limit=int(config.batch_limit),
                max_batches=int(config.max_batches),
                max_seconds=float(config.max_seconds),
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
            time.sleep(float(config.retry_backoff_seconds) * attempts)
    return SyncProjectResult(
        project_id, "RETRY_EXHAUSTED", code=last_code,
        attempts=attempts, seconds=round(time.monotonic() - started, 3),
    )


def run_once(
    connection, *, data_dir: str | Path, config: SyncRunnerConfig,
) -> dict[str, Any]:
    """One explicit fair pass over the configured project scope."""
    config.validate()
    if not config.enabled:
        return {"status": "DISABLED", "projects": []}
    results = [
        run_project_sync(
            connection, data_dir=data_dir, project_id=project_id, config=config
        ).__dict__
        for project_id in config.project_ids
    ]
    return {
        "status": "COMPLETED",
        "projects": results,
        "blocked": [row["project_id"] for row in results if row["status"] == "BLOCKED"],
    }


def sync_status(
    connection, *, data_dir: str | Path, project_id: str,
) -> dict[str, Any]:
    """Read-only status projection; unavailable owner is never reported as zero."""
    return diagnose_project(
        connection, project_dir=Path(data_dir), project_id=project_id
    )
