# Training Queue / Waiting Resource Truth Design

## Goal

Close only the local unified training-task distinction between `QUEUED` and
`WAITING_RESOURCE`. The public state must explain whether a queued training task
has a provably compatible online Worker or is waiting for one. The durable task
status, Scheduler claim order, Worker registry schema, GPU admission, and the
existing two-second frontend polling owner remain unchanged.

## Existing authorities

- `tasks.status`, `priority`, `queue_rank`, `resource_key`,
  `required_capabilities`, and `resource_wait_reason` remain owned by the
  existing `TaskRepository` and Scheduler.
- `worker_instances` and its lease expiry remain the only Worker liveness and
  registration truth.
- Scheduler/GPU admission remains the only owner of hardware admission reasons.
- `GET /api/projects/{project_id}/jobs` and `enrich_job_runtime()` remain the
  training-list runtime overlay.
- `TrainingTaskRuntime` and `PollRegistry` remain the only frontend list refresh
  and timer owners.

No second queue, Worker registry, Scheduler, polling loop, or durable status is
introduced.

## Read-time projection

For a non-queued durable task, public status continues to use durable truth.

For a local durable `TRAINING` task whose persisted status is `QUEUED`, the
backend derives a read-only projection from a single current Worker runtime
snapshot:

1. no online Worker at all -> `WAITING_RESOURCE`, reason
   `当前没有在线 Worker`;
2. online Workers exist but none registers `TRAINING` -> `WAITING_RESOURCE`,
   reason `当前没有可执行训练任务的 Worker`;
3. online Training Workers exist but none contains every task-required
   capability -> `WAITING_RESOURCE`, reason
   `当前在线 Training Worker 不支持 <capabilities>`;
4. a provably compatible Worker exists and the Scheduler has persisted a
   current admission `resource_wait_reason` -> `WAITING_RESOURCE`, preserving
   that real reason;
5. a provably compatible Worker exists and there is no admission rejection ->
   `QUEUED`.

This projection never changes `tasks.status`, `tasks.stage`, or any task row.
Worker expiry/renewal changes the next GET response naturally.

## Compatibility boundary

For this batch, a provably compatible local Worker means:

- its durable lease is currently online;
- its registered task kinds include `TRAINING`;
- its registered capabilities are a superset of the task's
  `required_capabilities`.

`training:remote:<server_id>` is explicitly excluded from this inference.
Current Worker Runtime Truth does not contain server ID, resource affinity,
allowed resource keys, or remote-server binding, and the current Training
Handler rejects non-local targets. A remote task therefore reports an explicit
remote-routing-unavailable wait reason; an arbitrary local
`training.ultralytics` Worker is never treated as proof that the remote task can
run.

This batch does not add Build claim compatibility, GPU identity, GPU memory
topology, server affinity, or remote routing truth.

## Queue position honesty

The existing `resource_queue_position` remains explicitly resource-scoped. It
is not renamed or presented as an exact executable queue rank.

Because `claim_next()` scans all candidates a Worker can handle across resource
keys, a position calculated only within `training:cpu`, `training:auto`, or
`training:cuda:0` cannot generally prove the task's exact Scheduler position.
This batch therefore adds a boolean proof field such as
`resource_queue_position_exact`.

- The backend may preserve the resource-scoped numeric value for compatibility.
- The training UI displays `队列第 N 位` only when the proof field is true.
- When exactness cannot be proved, it displays the backend resource-pool label
  and `排队中`, without a number.
- `WAITING_RESOURCE` prioritizes the backend wait reason and does not emphasize
  a queue position.

For current local training, multiple resource keys can compete for the same
Training Worker, so exactness is false unless the backend can prove there are no
cross-resource queued competitors for the compatible Worker set. The proof is
conservative: uncertainty suppresses the number rather than manufacturing
precision.

## Resource-pool metadata

The backend returns:

- `resource_pool_key` — the existing requested `resource_key`;
- `resource_pool_label` — a server-owned display label;
- `resource_queue_position_exact` — whether the numeric rank is safe to show.

Training labels are resolved server-side:

- `training:cpu` -> `CPU`;
- `training:auto` -> `GPU 自动`;
- `training:cuda:N` -> `GPU N`;
- `training:remote:<server_id>` -> `指定远程服务器`.

The frontend does not parse `resource_key` or infer resource availability.

## Frontend behavior

- public `queued` -> `排队中`;
- public `waiting` -> `等待资源`;
- queued + exact position -> pool label plus `队列第 N 位`;
- queued + unproved position -> pool label plus `排队中`;
- waiting -> pool label plus backend `resource_wait_reason`.

The existing page-scoped two-second one-shot refresh observes Worker recovery,
admission changes, and rank changes. No new timer or polling endpoint is added.

## Minimal verification

Focused backend contracts cover:

1. no online Worker;
2. online Worker without `TRAINING`;
3. Training Worker missing the required capability;
4. compatible Worker recovery returning the projection to `QUEUED`;
5. Scheduler/GPU admission reason preservation;
6. a compatible queued task not being mislabeled as waiting;
7. remote training not borrowing compatibility from a local Worker;
8. unproved resource-scoped position marked non-exact.

Focused frontend contracts cover `排队中`, `等待资源`, backend reason display,
and suppression of non-exact numeric ranks. Existing PollRegistry tests remain
the proof of automatic two-second refresh; no second polling test framework is
added.

Only affected Python compilation/import and JavaScript syntax checks plus the
focused contracts are required.

## Explicitly out of scope

- Scheduler claim-order changes;
- Worker registration schema changes;
- GPU Runtime Truth and GPU affinity;
- GPU memory scheduling changes;
- Worker/server binding and remote affinity;
- designated GPU or designated-machine scheduling;
- ETA, pause/resume, training detail, creation modal, SSE, deployment center;
- `main` merge, version bump, tag, or release.

