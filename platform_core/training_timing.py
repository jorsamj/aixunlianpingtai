"""Training timing evidence in the existing job record, never a parallel task store."""
from datetime import datetime, timezone
import json
import math
import sys
import time
from pathlib import Path

from filelock import FileLock
from .annotations import atomic_write_json


# One lock identity for the shared per-job record. The app job writer, the
# conversion/deployment workers and the numeric-evidence projection all use
# ``<job.json>.lock``; a second lock name for the training Worker let progress
# updates and cancellation writes read/modify/write the same file at once.
JOB_RECORD_LOCK_SUFFIX = ".lock"
JOB_RECORD_IO_DEADLINE_SECONDS = 15.0
# A cancellation already persisted by the control plane is durable truth: a
# late progress/startup write must not clear it while the process is stopped.
CANCELLATION_STATUSES = frozenset({"stopped", "cancelled", "canceled", "cancelling"})
TERMINAL_STATUSES = CANCELLATION_STATUSES | frozenset({
    "done", "completed", "finished", "failed", "partial_success",
    "blocked_by_environment", "blocked_by_hardware",
})


def utc(value):
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result.astimezone(timezone.utc) if result.tzinfo is not None else None
    except (ValueError, TypeError):
        return None


def now_utc():
    return datetime.now(timezone.utc).isoformat()


def seconds(start, end):
    left, right = utc(start), utc(end)
    return max(0.0, (right-left).total_seconds()) if left and right and right >= left else None


def begin_attempt(job, generation, worker_id, started_at):
    generation = int(generation or 0)
    if generation < 1 or not utc(started_at):
        return
    entries = job.setdefault("training_attempts", [])
    entry = next((row for row in entries if row.get("generation") == generation), None)
    if entry is None:
        for prior in entries:
            if not prior.get("training_closed") and prior.get("training_started_at"):
                prior["interrupted"] = True  # missing crash-end evidence is not invented
        entries.append({"generation": generation, "worker_id": str(worker_id), "started_at": started_at,
                        "active_seconds": None, "training_closed": False})
    elif str(entry.get("worker_id")) != str(worker_id):
        raise ValueError("training attempt worker identity changed")
    job["training_attempt_generation"] = generation


def record_update(job, updates, observed_at=None):
    observed_at = observed_at or now_utc()
    transition_at = updates.get("paused_at") if str(updates.get("status") or "").lower() == "paused" else updates.get("resumed_at")
    if utc(transition_at):
        observed_at = transition_at
    generation = job.get("training_attempt_generation")
    entry = next((row for row in job.get("training_attempts", []) if row.get("generation") == generation), None)
    if entry is None:
        return
    start = any(key in updates for key in ("first_batch_at", "resume_first_batch_at", "training_segment_started_at"))
    if start and not entry.get("active_interval_started_at"):
        if not utc(job.get("first_started_at")):
            # A recovered historical task may have unknown earlier training.
            # Do not pretend its first observed resumed batch was its first-ever batch.
            if len(job.get("training_attempts", [])) == 1 and generation == 1:
                job["first_started_at"] = observed_at
        entry.setdefault("training_started_at", observed_at)
        entry.update(active_interval_started_at=observed_at, active_base_seconds=float(entry.get("active_seconds") or 0),
                     training_closed=False)
    interval = entry.get("active_interval_started_at")
    elapsed = seconds(interval, observed_at)
    if elapsed is not None:
        entry["active_seconds"] = max(float(entry.get("active_seconds") or 0), float(entry.get("active_base_seconds") or 0) + elapsed)
        entry["last_training_observed_at"] = observed_at
    paused = str(updates.get("status") or "").lower() == "paused"
    finished = (bool(updates.get("training_segment_finished_at"))
                or updates.get("training_loop_completed") is True
                or updates.get("recovery_state") == "training_loop_completed"
                or str(updates.get("status") or "").lower() in {"failed", "done", "cancelled", "stopped"})
    if (paused or finished) and interval:
        entry["active_base_seconds"] = entry.get("active_seconds")
        entry.pop("active_interval_started_at", None)
    if paused:
        entry.setdefault("paused_since", observed_at)
    if "resumed_at" in updates and entry.get("paused_since"):
        entry.pop("paused_since", None)
        if entry.get("training_started_at") and not entry.get("training_closed"):
            entry["active_interval_started_at"] = observed_at
            entry["active_base_seconds"] = float(entry.get("active_seconds") or 0)
    if finished:
        entry["training_closed"] = True
    if str(updates.get("status") or "").lower() in {"failed", "done", "cancelled", "stopped"}:
        entry.setdefault("finished_at", observed_at)


def _read_job_record(path: Path) -> dict:
    """Read the record under the caller's lock, retrying transient Windows sharing errors.

    An unreadable record is never degraded to ``{}`` here: merging into an empty
    document would silently drop the fields another owner already persisted.
    """
    deadline = time.monotonic() + JOB_RECORD_IO_DEADLINE_SECONDS
    while True:
        try:
            raw = path.read_text(encoding="utf-8")
            break
        except FileNotFoundError:
            return {}
        except PermissionError:
            # A reader on Windows may hold the file open for a few ms.
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.01)
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("job record is not a JSON object")
    return value


def _persisted_attempt(job) -> int | None:
    try:
        return int(job.get("training_attempt_generation"))
    except (TypeError, ValueError):
        return None


def _superseded_by_newer_attempt(job, attempt) -> bool:
    """An older execution attempt must not overwrite a newer attempt's record."""
    if attempt is None:
        return False
    try:
        mine = int(attempt)
    except (TypeError, ValueError):
        return False
    persisted = _persisted_attempt(job)
    return persisted is not None and persisted > mine


def _cancellation_persisted(job) -> bool:
    return bool(job.get("cancel_requested")) or str(job.get("status") or "").strip().lower() in CANCELLATION_STATUSES


def _guarded_updates(job, updates) -> dict:
    """Keep a persisted cancellation marker; never resurrect a stopped job as running."""
    guarded = dict(updates)
    if not _cancellation_persisted(job):
        return guarded
    status = str(guarded.get("status") or "").strip().lower()
    if status and status not in TERMINAL_STATUSES:
        guarded.pop("status", None)
        guarded.pop("message", None)
        print(
            f"[job-record] cancellation already persisted; skipped status={status!r}",
            file=sys.stderr,
            flush=True,
        )
    for key in ("cancel_requested", "cancel_requested_at"):
        if job.get(key) and not guarded.get(key):
            guarded[key] = job[key]
    return guarded


def update_job(path, updates, *, writer=atomic_write_json, before_update=None,
               attempt=None):
    """Extend the original job mutation under one read/write lock.

    Contract (shared with the app/deployment/numeric job writers):
    ``<job.json>.lock`` + read-under-lock -> mutate -> whole-file atomic replace.
    ``attempt`` is this writer's persisted execution generation; when the record
    already carries a newer generation the update is skipped (and reported to
    stderr) instead of clobbering the newer attempt's facts.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(path) + JOB_RECORD_LOCK_SUFFIX, timeout=10, thread_local=False):
        job = _read_job_record(path)
        if _superseded_by_newer_attempt(job, attempt):
            print(
                f"[job-record] skipped stale write for attempt {attempt}: "
                f"persisted generation {_persisted_attempt(job)} is newer ({path.name})",
                file=sys.stderr,
                flush=True,
            )
            return job
        if before_update is not None:
            before_update()
        observed_at = now_utc()
        guarded = _guarded_updates(job, updates)
        record_update(job, guarded, observed_at)
        job.update(guarded)
        job["updated_at"] = observed_at
        writer(path, job)
        return job


def timing_view(job, runtime=None, *, now=None):
    runtime = runtime or {}
    now = now or now_utc()
    status = str(runtime.get("status") or job.get("task_status") or job.get("status") or "").upper()
    terminal = status in {"SUCCEEDED", "PARTIAL_SUCCESS", "DONE", "COMPLETED", "FINISHED", "FAILED", "CANCELLED", "CANCELED", "STOPPED", "BLOCKED_BY_ENVIRONMENT", "BLOCKED_BY_HARDWARE"}
    first = job.get("first_started_at") or job.get("first_batch_at")
    first = str(first) if utc(first) else None
    end = runtime.get("finished_at") or job.get("finished_at") if terminal else now
    entries = {}
    for row in job.get("training_attempts", []):
        if not isinstance(row, dict):
            continue
        try:
            generation = int(row.get("generation"))
        except (ValueError, TypeError, OverflowError):
            continue
        if generation > 0:
            entries[generation] = row
    ordered = [entries[key] for key in sorted(entries)]
    latest = ordered[-1] if ordered else {}
    current_attempt = runtime.get("attempt")
    if current_attempt is not None and latest.get("generation") != current_attempt:
        # A newer execution may fail before the Trainer record is initialized.
        # Its Worker/start must not be borrowed from the previous generation.
        latest = {}
    active_values = []
    for row in ordered:
        try:
            value = float(row.get("active_seconds"))
            active_values.append(value if math.isfinite(value) and value >= 0 else None)
        except (ValueError, TypeError, OverflowError):
            active_values.append(None)
    active = sum(float(value) for value in active_values if value is not None) if ordered and any(value is not None for value in active_values) else None
    active_complete = bool(latest) and sorted(entries) == list(range(1, max(entries) + 1)) and all(value is not None for value in active_values) and all(row.get("training_closed") and not row.get("interrupted") for row in ordered)
    attempt_end = (runtime.get("finished_at") or latest.get("finished_at") or job.get("finished_at")) if terminal else now
    return {
        "first_started_at": first, "timing_observed_at": now,
        "wall_finished_at": end if terminal and utc(end) else None,
        "wall_elapsed_seconds": seconds(first, end),
        "active_training_seconds": active,
        "active_training_seconds_complete": active_complete,
        "attempt_started_at": latest.get("started_at"),
        "attempt_elapsed_seconds": seconds(latest.get("started_at"), attempt_end),
        "initial_training_worker_id": ordered[0].get("worker_id") if ordered else None,
        "last_training_worker_id": latest.get("worker_id"),
        "timing_status": "verified" if first and (not terminal or utc(end)) else "unknown",
    }
