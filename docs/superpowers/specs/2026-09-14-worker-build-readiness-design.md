# Worker Build Readiness Design

## Goal

Keep API and Worker deployments usable and truthful when they are upgraded independently. A task created by one API Build must never be claimed by a different Worker Build, and the product must refuse a new training task when no compatible Worker is currently online.

## Confirmed problem

The current durable `worker_instances` table records only process lease identity and timestamps. It does not record Worker Build ID, handled task kinds, capabilities, or startup rejection details. The API therefore cannot determine whether a compatible Worker is online. Durable tasks also require only functional capabilities such as `training.ultralytics`, so an older online Worker can claim a task created by a newer API Build.

The existing `upgrade_guard` correctly refuses a new Worker Build when `RUNNING` or `CANCEL_REQUESTED` tasks belong to the previous Build. This protection remains unchanged; the missing work is durable observability, claim fencing, admission control, and user-facing explanation.

## Architecture

### Durable Worker truth

Extend the existing task-runtime SQLite ownership model instead of adding a parallel registry.

- An active `worker_instances` row records `build_id`, handled task kinds, capabilities, heartbeat time, and expiry.
- A separate startup-failure table records recent rejected Worker starts. It must not overwrite or impersonate a live Worker lease.
- Readiness treats heartbeat expiry as authoritative. It does not inspect a remote PID because API and Worker may run on different hosts.
- Successful acquisition clears the matching stale startup-failure record.

### Build claim fence

Represent the required Build as a normal durable capability: `runtime.build:<build_id>`.

- The API's shared task repository appends its Build capability to every newly created durable task.
- Each Worker appends its own Build capability to the capabilities passed to the scheduler.
- Existing capability-subset claim logic then prevents old or different-Build Workers from claiming new tasks without creating a second claim implementation.
- Legacy tasks without a Build capability keep their existing recovery behavior. The existing active-task upgrade guard still protects `RUNNING` and `CANCEL_REQUESTED` takeover.

### Readiness service and API

Add a focused readiness query over durable Worker rows. Inputs are task kind, required functional capabilities, and the API Build ID. Output includes:

- `ready`;
- expected Build ID;
- stable reason code;
- readable Chinese message and suggested action;
- sanitized online Worker summaries;
- recent startup-rejection summaries.

Reason precedence is:

1. compatible online Worker exists: `READY`;
2. recent cross-Build startup rejection exists: `WORKER_START_REJECTED`;
3. online Workers for the task kind exist but their Build differs: `WORKER_BUILD_MISMATCH`;
4. online Workers exist but lack the required capability: `WORKER_CAPABILITY_MISMATCH`;
5. no relevant online Worker exists: `NO_ONLINE_WORKER`.

Expose this through a read-only system endpoint. Do not expose lease owner tokens, local data paths, or other secrets.

### Training admission and UI

The explicit v3 training route checks readiness after request validation but before writing payload, job, or task artifacts. When readiness is not ready it returns `503` with code `COMPATIBLE_WORKER_UNAVAILABLE`, the durable reason, and a concrete recovery suggestion. No task row or job is created.

The training modal continues to open immediately. It starts with a non-blocking “正在检查 Worker” state, fetches readiness asynchronously for the selected training framework, and shows the returned reason. `TrainingSubmitRuntime` remains the sole submit-button readiness owner and disables submit only while the explicit Worker readiness state is checking or unavailable. Changing the training target refreshes readiness.

The server-side admission check remains authoritative even if the browser state is stale or bypassed.

## Error handling

- SQLite schema upgrades are additive and preserve existing rows.
- Missing Build metadata on an older live Worker is treated as incompatible/unknown, never assumed compatible.
- A rejected Worker start records diagnostics best-effort; failure to write diagnostics must not weaken the existing startup refusal.
- If the readiness query itself fails, task creation fails closed with an actionable `503` rather than creating an unexecutable task.
- Heartbeat expiry makes a Worker unavailable without requiring API/Worker clock-local PID inspection.

## Testing

Use focused RED → GREEN contracts only:

1. Worker instance schema and readiness classification: same Build ready, different Build mismatch, expired Worker offline, recent rejected start visible.
2. Build capability claim fencing: a different-Build Worker cannot claim a new task; the matching Build can.
3. Training API admission: no compatible Worker returns `503` and creates no durable task/artifact; a compatible Worker returns `202`.
4. Worker CLI wiring: active registration publishes Build/task kinds/capabilities and rejected startup records the guard reason.
5. Frontend readiness: modal probe is asynchronous, reason is rendered, and the sole submit owner disables/re-enables correctly.

Run only affected Python compile/import checks, JavaScript syntax checks, and the focused tests above. Linux/A800, real distributed shared storage, CUDA/PyTorch, OSS/MinIO, Atlas, RKNN, and Sophon remain `NOT VERIFIED` without their real environments.

## Scope boundaries

- Do not weaken `ensure_worker_build_compatible` or `MC_ALLOW_ACTIVE_TASK_UPGRADE`.
- Do not change `main`, `VERSION.txt`, tags, or releases.
- Do not restore temporary training helper/workflow files.
- Do not add fake progress or a browser-owned queue.
- Do not change exact-material training selection, label semantics, independent-test blindness, or requested/assigned device separation.
- This batch gates the current explicit v3 training creation path. The generic readiness service and Build capability fence cover all newly created durable tasks; product-specific admission UX for other creation surfaces can adopt the same service in later bounded batches.
