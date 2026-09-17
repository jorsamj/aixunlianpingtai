# Generic Durable Queue Exactness Closure

Date: 2026-09-16
Branch: `refactor/frontend-runtime-stabilization`
Formal version remains `42.24.0`.

## Scope

This closure completes the backend half of Task Runtime Truth v2 for non-training durable tasks. A numeric resource-scoped queue position is not automatically an executable Worker rank. The backend now emits `resource_queue_position_exact` only when it can prove the resource order and the unique compatible Worker claim order are the same.

## Proof rule

For a queued non-training task, exactness is true only when all of the following hold:

- exactly one online Worker can claim the task kind and all required capabilities;
- every queued task that Worker could claim belongs to the same `resource_key`;
- the task position in that Worker's claimable durable scan equals `resource_queue_position`.

No compatible Worker, multiple compatible Workers, cross-resource competition, and non-queued tasks fail closed to `resource_queue_position_exact=false`. Training keeps its specialized CPU/GPU/remote queue truth and GPU admission semantics. Scheduler claim order itself is unchanged.

## Frontend contract

AI annotation and material-batch views now use the same `exactTaskQueuePosition()` helper as storage import, resource discovery, video, deployment tests, and training UI. They may show “资源队列第 N 位” only when the backend exact flag is true. Wait reasons remain visible when rank is inexact.

## Performance

Unified task, video-task, and annotation-task list endpoints snapshot Worker runtime and queued candidates once per response and reuse those snapshots for every item, avoiding an N+1 Worker/candidate query pattern.

## Boundaries

This batch does not change Scheduler selection, priority, promotion, Worker capabilities, leases, GPU admission, or the already-closed v47 cleaning compatibility projection. Genuine 10k validation and A800 RC remain deferred.
