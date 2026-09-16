# Task Runtime Truth v1 handoff — 2026-09-16

## Scope

This batch closes the first frontend/backend consistency layer for real queue and live progress.
It does not replace the legacy training jobs endpoints. Instead, durable task truth is projected
onto them explicitly while compatibility aliases remain available.

## Canonical backend fields

Frontend runtime truth is now based on:

- `task_status` (or `status` on native durable-task responses)
- `persisted_status`
- `phase`
- `progress_percent`
- `current_item`
- `resource_queue_position`
- `resource_queue_position_exact`
- `resource_pool_key`
- `resource_pool_label`
- `resource_wait_reason`
- worker / error fields

For `/api/projects/{project_id}/jobs`, `status` and `task_stage` remain compatibility aliases.
`task_status` and `phase` are authoritative when both old and new fields exist.

## Frontend contract

`static/modules/task-runtime-truth.js` is the shared adapter. Training, AI annotation,
material batches, and the shared task poller must not invent independent status semantics.
`progress_percent` wins over legacy `progress`; item counts are display data only and are
never used to fabricate a durable task percentage.

Training keeps its old UI vocabulary (`waiting`, `queued`, `running`, etc.) only through
`trainingDisplayStatus()`, which derives that vocabulary from canonical task status.

## Queue correctness

`resource_queue_position_exact` remains the sole proof that a numeric queue position may be
presented as exact. `queue_rank`, priority, and candidate order are not substitutes.

## Validation boundary

Focused Python and Node tests cover the projection contract and frontend precedence.
Windows + Ubuntu CI is the permanent gate. Production-host behavior (real Windows drive set,
real Linux/A800 workers, and true concurrent load) remains a separate acceptance layer.
