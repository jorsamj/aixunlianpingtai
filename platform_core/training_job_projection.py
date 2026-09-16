from __future__ import annotations

from typing import Any, Mapping, MutableMapping


def _clamp_percent(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(100.0, number))


def apply_training_task_truth(
    job: MutableMapping[str, Any],
    public_runtime: Mapping[str, Any],
    *,
    legacy_status: str,
) -> MutableMapping[str, Any]:
    """Project durable task truth onto the legacy training-job response.

    `status` and `task_stage` remain compatibility aliases. New frontend runtime
    code must prefer `task_status`, `phase`, `progress_percent`, and resource_*.
    """
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
