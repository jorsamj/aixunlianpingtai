from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any, Mapping, MutableMapping


_DISPLAY_REVISION_LOCK = threading.Lock()
_DISPLAY_REVISION = 0
_SUCCESS_STATUSES = {"SUCCEEDED", "PARTIAL_SUCCESS"}
_TERMINAL_STATUSES = _SUCCESS_STATUSES | {
    "CANCELLED",
    "FAILED",
    "BLOCKED_BY_ENVIRONMENT",
    "BLOCKED_BY_HARDWARE",
}


def _clamp_percent(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(100.0, number))


def _optional_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    number = _optional_number(value)
    if number is None:
        return None
    try:
        return max(0, int(number))
    except (TypeError, ValueError, OverflowError):
        return None


def _timestamp_key(value: Any) -> float:
    raw = str(value or "").strip()
    if not raw:
        return float("-inf")
    try:
        normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except (TypeError, ValueError, OverflowError):
        return float("-inf")


def _latest_timestamp(*values: Any) -> str:
    candidates = [str(value).strip() for value in values if str(value or "").strip()]
    if not candidates:
        return ""
    return max(candidates, key=_timestamp_key)


def _next_display_revision() -> int:
    """Return a response-order revision that is safe in JavaScript Number."""
    global _DISPLAY_REVISION
    candidate = time.time_ns() // 1_000
    with _DISPLAY_REVISION_LOCK:
        _DISPLAY_REVISION = max(candidate, _DISPLAY_REVISION + 1)
        return _DISPLAY_REVISION


def _canonical_status(job: Mapping[str, Any], public_runtime: Mapping[str, Any] | None) -> str:
    if public_runtime:
        value = str(public_runtime.get("status") or "").strip().upper()
        if value:
            return value
    raw = str(job.get("task_status") or job.get("status") or "").strip().upper()
    aliases = {
        "WAITING": "WAITING_RESOURCE",
        "PENDING": "QUEUED",
        "DONE": "SUCCEEDED",
        "FINISHED": "SUCCEEDED",
        "COMPLETED": "SUCCEEDED",
        "SUCCESS": "SUCCEEDED",
        "STOPPED": "CANCELLED",
        "CANCELED": "CANCELLED",
    }
    return aliases.get(raw, raw)


def _training_phase_progress(
    current_epoch: int | None,
    total_epochs: int | None,
    current_batch: int | None,
    total_batches: int | None,
) -> float | None:
    if not total_epochs or total_epochs <= 0 or not current_epoch or current_epoch <= 0:
        return None
    if current_batch is not None and total_batches and total_batches > 0:
        completed = max(0.0, float(current_epoch - 1))
        completed += max(0.0, min(1.0, float(current_batch) / float(total_batches)))
    else:
        completed = float(current_epoch)
    return round(max(0.0, min(100.0, completed / float(total_epochs) * 100.0)), 2)


def build_training_display_progress(
    job: Mapping[str, Any],
    public_runtime: Mapping[str, Any] | None = None,
    *,
    revision: int | None = None,
    telemetry_job: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Combine lifecycle and worker telemetry into one product display truth."""
    runtime = public_runtime or {}
    telemetry = telemetry_job if telemetry_job is not None else job
    training_progress = (
        telemetry.get("training_progress")
        if isinstance(telemetry.get("training_progress"), Mapping)
        else {}
    )
    status = _canonical_status(job, public_runtime)
    phase = str(
        runtime.get("phase")
        or job.get("phase")
        or job.get("task_stage")
        or job.get("startup_stage")
        or ""
    ).strip()

    worker_progress = _optional_number(telemetry.get("progress_percent"))
    durable_progress = _optional_number(runtime.get("progress_percent"))
    candidates = [value for value in (worker_progress, durable_progress) if value is not None]
    overall_progress = max(candidates) if candidates else 0.0
    if status in _SUCCESS_STATUSES:
        overall_progress = 100.0
    elif status not in _TERMINAL_STATUSES:
        overall_progress = min(99.0, overall_progress)
    overall_progress = _clamp_percent(overall_progress)

    current_epoch = _optional_int(
        training_progress.get("epoch")
        if training_progress.get("epoch") is not None
        else telemetry.get("current_epoch")
    )
    total_epochs = _optional_int(
        training_progress.get("total_epochs")
        if training_progress.get("total_epochs") is not None
        else (telemetry.get("total_epochs") if telemetry.get("total_epochs") is not None else telemetry.get("epochs"))
    )
    current_batch = _optional_int(telemetry.get("current_batch"))
    total_batches = _optional_int(telemetry.get("total_batches"))
    elapsed_seconds = _optional_number(
        training_progress.get("elapsed_seconds")
        if training_progress.get("elapsed_seconds") is not None
        else telemetry.get("elapsed_seconds")
    )
    eta_seconds = _optional_number(
        training_progress.get("eta_seconds")
        if training_progress.get("eta_seconds") is not None
        else telemetry.get("eta_seconds")
    )
    if status in _TERMINAL_STATUSES:
        eta_seconds = 0.0
    elif status == "PAUSED":
        eta_seconds = None
    throughput = _optional_number(training_progress.get("images_per_second"))

    worker_item = str(telemetry.get("current_item") or telemetry.get("message") or "").strip()
    runtime_item = str(runtime.get("current_item") or "").strip()
    if phase in {"training", "trainer_startup"} and worker_item:
        message = worker_item
    else:
        message = runtime_item or worker_item

    telemetry_present = any(
        value is not None
        for value in (current_epoch, current_batch, elapsed_seconds, eta_seconds, throughput)
    ) or bool(training_progress)
    updated_at = _latest_timestamp(runtime.get("updated_at"), telemetry.get("updated_at"))
    return {
        "revision": int(revision if revision is not None else _next_display_revision()),
        "updated_at": updated_at or None,
        "status": status,
        "phase": phase,
        "phase_progress": _training_phase_progress(
            current_epoch, total_epochs, current_batch, total_batches
        ),
        "overall_progress": overall_progress,
        "current_epoch": current_epoch,
        "total_epochs": total_epochs,
        "current_batch": current_batch,
        "total_batches": total_batches,
        "elapsed_seconds": elapsed_seconds,
        "eta_seconds": eta_seconds,
        "throughput": throughput,
        "message": message or None,
        "telemetry_source": "worker_training_telemetry" if telemetry_present else "durable_task",
    }


def apply_training_display_progress(
    job: MutableMapping[str, Any],
    public_runtime: Mapping[str, Any] | None = None,
    *,
    telemetry_job: Mapping[str, Any] | None = None,
) -> MutableMapping[str, Any]:
    display = build_training_display_progress(
        job,
        public_runtime,
        telemetry_job=telemetry_job,
    )
    job["training_display_progress"] = display
    job["display_revision"] = display["revision"]
    job["progress_percent"] = display["overall_progress"]
    job["phase_progress"] = display["phase_progress"]
    job["telemetry_source"] = display["telemetry_source"]
    job["elapsed_seconds"] = display["elapsed_seconds"]
    job["eta_seconds"] = display["eta_seconds"]
    if display["current_epoch"] is not None:
        job["current_epoch"] = display["current_epoch"]
    if display["total_epochs"] is not None:
        job["total_epochs"] = display["total_epochs"]
    if display["current_batch"] is not None:
        job["current_batch"] = display["current_batch"]
    if display["total_batches"] is not None:
        job["total_batches"] = display["total_batches"]
    if display["message"]:
        job["current_item"] = display["message"]
    return job


def apply_training_task_truth(
    job: MutableMapping[str, Any],
    public_runtime: Mapping[str, Any],
    *,
    legacy_status: str,
) -> MutableMapping[str, Any]:
    """Project durable task truth onto the legacy training-job response."""
    phase = str(public_runtime.get("phase") or "")
    job.update(
        status=str(legacy_status or ""),
        task_status=str(public_runtime.get("status") or ""),
        persisted_status=str(public_runtime.get("persisted_status") or ""),
        phase=phase,
        task_stage=phase,
        progress_percent=_clamp_percent(public_runtime.get("progress_percent")),
        current_item=public_runtime.get("current_item"),
        resource_queue_position=public_runtime.get("resource_queue_position"),
        resource_queue_position_exact=public_runtime.get("resource_queue_position_exact") is True,
        resource_pool_key=public_runtime.get("resource_pool_key"),
        resource_pool_label=str(public_runtime.get("resource_pool_label") or "训练资源"),
        resource_wait_reason=public_runtime.get("resource_wait_reason"),
        task_worker_id=public_runtime.get("worker_id"),
        task_lease_expires_at=public_runtime.get("lease_expires_at"),
    )
    return job
