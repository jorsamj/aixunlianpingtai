# Task Runtime Truth v2 handoff — 2026-09-16

## Scope

Extends the shared durable-task frontend contract from training/annotation/material batches to:

- storage scan/import progress
- server material import
- resource discovery
- video processing tasks
- deployment test tasks

Cleaning remains intentionally outside this batch because its page consumes a legacy compatibility
business object. It must be migrated together with its backend compatibility projection rather than
by changing frontend status casing in isolation.

## Queue truth rule

A numeric `resource_queue_position` is allowed to render as “队列第 N 位” only when
`resource_queue_position_exact === true` from the backend. A candidate rank, priority order, or a
numeric position without exactness proof is not presented as a real Worker/hardware queue position.

`exactTaskQueuePosition()` in `static/modules/task-runtime-truth.js` is the single frontend helper.

## Status / phase / progress rule

For durable task payloads:

- `task_status` wins over stale compatibility `status`
- `phase` wins over `task_stage` / `stage`
- `progress_percent` wins over legacy `progress`
- item counts and domain metrics remain useful detail but are not converted into a fabricated durable percentage

Resource discovery keeps its frozen-root/scope/permission UX and cache refresh behavior. Server
material import keeps backend scan/extract/index counters. This batch changes task truth semantics,
not domain-specific diagnostics.

## Validation boundary

Focused Node tests cover canonical precedence and exact queue presentation. The permanent Task
Runtime Truth workflow runs the expanded frontend suite on Ubuntu and Windows. Existing Frontend
Runtime / Navigation Real Chrome gates must remain green. Production-host concurrency and real
worker queue contention remain separate acceptance work.
