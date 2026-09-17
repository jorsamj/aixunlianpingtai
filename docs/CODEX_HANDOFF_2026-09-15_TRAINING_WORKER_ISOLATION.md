# Codex Handoff — Training Worker Isolation & Fast Dispatch

> Branch: `refactor/frontend-runtime-stabilization`
>
> Read this file together with `docs/CODEX_CURRENT_STATE.md`, `docs/TECH_DEBT_CLOSURE_V42_25.md`, `docs/frontend-legacy-audit.md`, and `docs/FRONTEND_OWNER_MAP_V42_25.md`. Live GitHub HEAD always outranks stale documentation.

## 1. Release constraints remain unchanged

- Do **not** merge `main`.
- Do **not** change formal `VERSION.txt`; it must remain `42.24.0`.
- Do **not** tag or release.
- Do **not** force-push.
- Do not delete/relax tests, lower thresholds, or restore retired legacy behavior to make CI pass.
- Windows development and NVIDIA Linux production must remain supported.
- Do not hard-code Windows drive paths or Windows-only production process behavior.

## 2. Starting point

GPU Runtime Truth Phase 1A was already pushed before this batch:

```text
9c3bcd9593e17ff43daba6ae848d492e1a8eba65
GPU Runtime Truth Phase 1A
IMPLEMENTED + BASIC TESTS
REAL NVIDIA / A800 / MULTI-NODE / MIG ACCEPTANCE PENDING
```

Training Finalization & Queue Handoff behavior was deliberately not changed in this batch.

GPU Runtime Truth Phase 1B is still **NOT STARTED**. In particular, this batch does not node-scope `gpu_reservations`, change global `worker_slot` uniqueness, add remote routing, or add automatic cross-node GPU scheduling.

## 3. Problem fixed by this batch

User requirement:

> Training Worker must be independent. Resource scanning, material work, annotation, video processing, conversion and other non-training work must not block a runnable training task. Resource discovery must not default to whole-machine traversal. When a compatible Training Worker and GPU are available, a queued training task should be claimed on a seconds-level timescale.

The code audit found two concrete causes/risk paths.

### 3.1 Default `all` Worker serialized training behind unrelated work

`launcher.py` intentionally starts `task_worker.py --roles all`. Previously `task_worker.py` registered every handler into one Scheduler. Because one Worker executes one claimed task at a time, a long material/resource-discovery/annotation/video task could occupy that Worker while an otherwise runnable GPU training task waited.

The Scheduler itself was **not** the root cause. `Scheduler.run_once()` already claims only kinds present in the current Worker's handler registry, and its default idle poll interval is `0.25` seconds.

### 3.2 `auto` resource discovery could fall back to whole-machine traversal

`ResourceDiscoveryHandler._environment()` previously did this when fast discovery found no usable environment:

```text
scope=auto
+ no AVAILABLE environment
→ scan_python_candidates(None)
→ scanner chooses visible local filesystem roots
```

Model discovery with `scope=full` likewise called `scan_model_files(None)`.

That behavior is no longer acceptable for platform-default discovery.

## 4. Implemented architecture

### 4.1 `--roles all` is now an isolation supervisor

New module:

```text
platform_core/worker_supervisor.py
```

Compatibility CLI remains valid:

```bash
python task_worker.py --data-dir <DATA_DIR> --roles all
```

But it no longer owns one Scheduler containing both training and non-training handlers.

It now supervises two real child Worker processes:

```text
training child
  roles: training

background child
  roles:
    storage
    materials
    video
    annotation
    conversion
    deployment-test
```

The parent supervisor owns no TaskRepository lease, Scheduler, task status, task queue, GPU reservation, or Worker heartbeat. Each child continues to use the existing Worker Runtime, WorkerInstanceService, Scheduler and TaskRepository.

Therefore this change does **not** add a second scheduler architecture or a second execution truth.

A long background task can no longer occupy the process that claims `TRAINING`.

### 4.2 Explicit role semantics remain available

Existing explicit commands continue to work, for example:

```bash
python task_worker.py --data-dir <DATA_DIR> --roles training
python task_worker.py --data-dir <DATA_DIR> --roles annotation
python task_worker.py --data-dir <DATA_DIR> --roles video
```

For production, explicit dedicated Worker processes are still the clearest deployment model. `--roles all` is a compatibility supervisor for existing launchers/deployments that expect one top-level Worker process.

Do not reinterpret `--roles all` as one Worker runtime instance in future changes.

### 4.3 Training claim path remains the existing Scheduler

No Scheduler queue ordering change was made.

Current default:

```text
Scheduler.poll_seconds = 0.25
```

A training-only registration contains only:

```text
TaskKind.TRAINING
capability: training.ultralytics
```

The existing Scheduler still owns:

```text
reap/release expired leases
GPU telemetry/admission
claim_next
priority/FIFO semantics
execution fencing
training process lifecycle
terminal handoff
```

Do not create `training_queue_v2`, `training_dispatcher_v2`, another heartbeat, or another task database to optimize dispatch.

If A800 shows dispatch slower than the seconds-level target, profile the existing training Worker claim path first.

## 5. Bounded resource discovery policy

Modified:

```text
platform_core/resource_discovery/tasks.py
```

### Environment discovery

`scope=auto` without explicit roots now performs only the existing bounded fast discovery sources. It does **not** escalate to recursive local-filesystem scanning when no environment is found.

Deep scan is allowed only with explicit roots.

```text
scope=full + roots=[]
→ explicit validation error
```

`scope=auto` with explicit roots may deep-scan those roots if fast discovery still finds no available environment.

### Model discovery

Both `directory` and `full` model discovery now require at least one explicit root.

The worker no longer calls:

```text
scan_model_files(None)
```

from the product task path.

### What is still allowed

This change does not delete resource discovery. A user/admin may explicitly select/configure a large directory, storage mount or model root and scan it. The invariant is that omission of roots can never silently become `/`, `C:\`, `/data`, `/home`, or all mounted filesystems.

Fast discovery remains bounded. It checks known/current Python environments, PATH entries, Conda environment metadata, configured roots and shallow well-known locations; it does not recursively walk an entire disk.

## 6. Permanent guards added

`tests/unit/test_launcher_workers.py` now proves:

1. the existing launcher still starts its top-level worker using the shared DATA_DIR;
2. compatibility `all` resolves to an isolated `training` group and a non-training background group;
3. `task_worker.py --roles all` delegates runtime execution to the isolation supervisor;
4. a `training` registration contains only `TaskKind.TRAINING`;
5. Scheduler default idle poll is sub-second (`0.25s`);
6. `auto` environment discovery without roots cannot deep-scan;
7. `full` environment discovery requires explicit roots;
8. model discovery requires explicit roots.

Do not weaken these guards to restore single-process all-role execution or implicit whole-machine scans.

## 7. Files changed in this batch

Product/runtime:

```text
platform_core/worker_supervisor.py
task_worker.py
platform_core/resource_discovery/tasks.py
```

Permanent regression guard:

```text
tests/unit/test_launcher_workers.py
```

Handoff:

```text
docs/CODEX_HANDOFF_2026-09-15_TRAINING_WORKER_ISOLATION.md
```

`launcher.py` is intentionally unchanged. It can continue launching `--roles all`; that command is now an isolation supervisor rather than one all-handler Scheduler.

## 8. Validation boundary

Automated CI must be read from the latest GitHub HEAD, not inferred from this document.

Required focused checks for this batch are:

```text
python -m pytest -q tests/unit/test_launcher_workers.py
python -m pytest -q tests/unit/task_runtime/test_worker_registry.py
python -m pytest -q tests/integration/test_task_worker_without_web.py
python -m py_compile task_worker.py platform_core/worker_supervisor.py platform_core/resource_discovery/tasks.py
```

The existing `v42.25 Release Regression` workflow already executes `tests/unit/test_launcher_workers.py` and `tests/integration/test_task_worker_without_web.py`; changing `task_worker.py` triggers that workflow.

Do not claim real concurrency/dispatch acceptance from unit tests alone.

## 9. A800 manual acceptance still required

Do not deploy this build by replacing code underneath the currently running training Worker. Existing active training should finish first unless the user explicitly accepts interruption/recovery testing.

After deployment, verify Worker Runtime shows separate instances rather than one runtime `all` instance. With compatibility mode the expected pattern is equivalent to:

```text
<base-worker-id>-training
  roles = [training]

<base-worker-id>-background
  roles = [storage, materials, video, annotation, conversion, deployment-test]
```

Manual acceptance scenarios:

### A. Training is not blocked by resource/material work

Start a long material import/resource discovery/background task. While it is running and GPU is idle, queue a TRAINING task.

Expected:

```text
background task remains active
+
training child independently claims TRAINING
```

### B. Training is not blocked by annotation/video work

Run AI annotation or video processing in the background Worker and queue training.

Expected: the training Worker claims independently.

### C. Seconds-level claim

With compatible training Worker online, no prior training reservation and GPU available, record queue/create time and claim/start time.

Target under normal conditions:

```text
QUEUED → claimed/STARTING/RUNNING in roughly 1–3 seconds
```

The Scheduler's default idle poll is 0.25s, so a tens-of-seconds delay requires investigation; do not hide it by adding another dispatcher.

### D. Resource scan boundary

Trigger default/auto environment detection without a directory.

Expected: bounded fast discovery only. No recursive traversal of `/`, `/data`, `/home`, Windows drive roots, or all mounts.

Trigger a deep/full scan without roots.

Expected: explicit validation failure requiring roots.

## 10. Known next P0 — do not lose this

A separate real user-observed bug remains open:

# Training Task Visibility Stability / Single Rendering Owner

Observed evidence:

```text
TaskRepository: RUNNING
/jobs API: RUNNING task present
training process: still advancing
UI: task temporarily disappeared
later polling: same task reappeared
```

This is not a backend task-loss incident. It strongly indicates frontend state/render ownership or stale-response competition.

Known relevant surfaces include:

```text
static/modules/training-task-runtime.js
static/app.js legacy renderTraining423/424/425 paths
loadRelated()/state.jobs refresh paths
PollRegistry/navigation fencing
```

Next batch must establish one final runtime render/refresh owner for the training list and prove that stale responses or legacy render paths cannot remove a task that is present in the latest `/jobs` truth.

Do **not** fix this by increasing poll frequency, fabricating RUNNING rows in browser memory, using setTimeout to reinsert rows, or adding another polling owner.

## 11. GPU Runtime Truth Phase 1B remains after stability P0s

Still out of scope:

```text
gpu_reservations node scope
global worker_slot UNIQUE migration
full GPU assignment identity
remote worker/server routing
automatic cross-node GPU scheduling
```

Do not start these until the user asks, and do not silently combine them with Worker isolation or frontend visibility work.

## 12. Status wording

Until GitHub CI and real A800 acceptance are both known, use:

```text
Training Worker Isolation & Fast Dispatch
IMPLEMENTED
AUTOMATED CI: verify latest HEAD
REAL A800 CONCURRENCY / 1–3s DISPATCH ACCEPTANCE: PENDING
```

Do not mark this P0 `CLOSED` before real A800 acceptance.
