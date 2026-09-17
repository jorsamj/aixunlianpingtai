# Codex Handoff — Resource Discovery Ownership + Training Orphan Process Cleanup

Date: 2026-09-15
Branch: `refactor/frontend-runtime-stabilization`

> GitHub current branch HEAD is authoritative. Do not use a stale SHA in this document to reset or rewind the branch.

## Scope

This batch closes two production defects found during real A800 operation without changing Scheduler architecture, GPU admission thresholds, GPU Runtime Truth Phase 1B, or `VERSION.txt`.

1. `RESOURCE_DISCOVERY` tasks remained `QUEUED` because the isolated background Worker omitted the `discovery` role.
2. A failed training could leave torch/DataLoader descendants alive after Linux OOM killed the main training PID. Those children became `PPID=1`, retained CUDA/shared-memory resources, and correctly caused the next training to remain resource-waiting.

## Production evidence

### Resource discovery

The compatibility `--roles all` mode had already been split into:

- training Worker: `training`
- background Worker: `storage, materials, video, annotation, conversion, deployment-test`

`platform_core.worker_registry` already supported the valid `discovery` role, but `platform_core.worker_supervisor.BACKGROUND_ROLES` omitted it. Therefore a `RESOURCE_DISCOVERY` task could be created but no supervised Worker advertised a matching handler.

### Training orphan process tree

Historical task:

- task: `99a99b479ecf`
- project: `f1fb1e6fa373`
- final durable status: `FAILED`
- main PID: `310980`
- 300/300 epochs completed
- `best.pt` and `last.pt` existed
- final `best.pt` validation reached 5/7
- Linux global host-memory OOM killed PID 310980 at 2026-09-15 13:14:10 local time
- surviving child PIDs included `311166 311167 311168 311169`
- those children became `PPID=1`
- about 9.9 GiB GPU memory remained occupied
- the next training was correctly blocked by GPU admission with `GPU_MEMORY_INSUFFICIENT`
- there was no active GPU reservation leak; the blocker was real orphan process memory

This proves the admission controller behaved correctly. The defect was process-tree cleanup after abrupt leader death.

## Root causes

### 1. Background role omission

Before this batch:

```python
BACKGROUND_ROLES = (
    "storage",
    "materials",
    "video",
    "annotation",
    "conversion",
    "deployment-test",
)
```

`discovery` was missing.

### 2. PID-tree cleanup could not recover after leader death

`launch_process()` already started POSIX children with `start_new_session=True`, which creates a private process group/session for each task.

However `ProcessController.terminate_tree()` previously did this when the bound main PID no longer existed:

```text
inspect(bound PID)
  -> ProcessLookupError
  -> return
```

Once Linux OOM killed the training leader, torch/DataLoader descendants were re-parented to PID 1. They could no longer be found through `root.children(recursive=True)`, so returning on missing leader left them alive.

## Implementation

### Background Worker owns discovery

`platform_core/worker_supervisor.py` now defines the background group as:

```text
discovery
storage
materials
video
annotation
conversion
deployment-test
```

The training Worker remains `training` only.

No second Scheduler or Worker Runtime was introduced.

### POSIX process-group cleanup

`platform_core/task_runtime/process_control.py` continues to launch task processes in their own POSIX session/process group.

`ProcessController.terminate_tree()` now has two cleanup paths:

1. if the bound leader is still alive, use exact PID/create-time/command-hash identity plus psutil descendant cleanup, then verify the dedicated process group has no remaining members;
2. if the exact bound leader has already disappeared, terminate the private POSIX process group whose group id is the original launch PID.

The group cleanup uses `SIGCONT -> SIGTERM -> bounded wait -> SIGKILL -> bounded verification`.

This is deliberately scoped to the process group created by `launch_process()`; it does **not** scan for or kill arbitrary `python`, `train_worker.py`, or CUDA processes.

PID reuse fencing remains intact: if the PID exists but create time / command hash does not match, `ProcessIdentityMismatchError` still prevents signaling an unrelated replacement process.

### Scheduler ordering remains fail-closed

`platform_core/task_runtime/scheduler.py` already had the correct ordering:

```text
handler error / cancel
  -> cleanup bound process
  -> only if cleanup verified
  -> write terminal task status
```

If cleanup cannot be verified, Scheduler keeps the execution non-terminal and reports `process_cleanup_blocked`; it does not publish a terminal state merely to advance the queue.

This batch fixes the lower-level cleanup primitive so that the existing Scheduler contract can also succeed after an externally killed leader.

## Permanent regressions

### Worker isolation

`tests/unit/test_launcher_workers.py` now requires:

- `discovery` is part of `BACKGROUND_ROLES`;
- the background registration owns `TaskKind.RESOURCE_DISCOVERY`;
- the background registration does not own `TaskKind.TRAINING`;
- the training registration remains training-only.

### Real subprocess orphan cleanup

`tests/unit/task_runtime/test_process_control.py` now creates a real process tree on POSIX, kills only the group leader to reproduce the OOM failure mode, verifies the child is still executing, then calls `terminate_tree()` and requires the orphan execution to be gone.

This is a real process regression, not a mocked dictionary-only test.

### CI

- `Training Worker Isolation` runs when the supervisor or isolation tests change.
- `Training Final Validation Hardening` now also watches `process_control.py`, `scheduler.py`, and `test_process_control.py`, compiles them, runs the focused process-control regression, and contains permanent source guards for POSIX group cleanup.

## What was NOT changed

- no `VERSION.txt` change; it must remain `42.24.0`
- no `main` merge
- no tag/release
- no GPU admission threshold relaxation
- no fake GPU-memory release
- no second queue/Scheduler/heartbeat/runtime DB
- no GPU Runtime Truth Phase 1B
- no historical rewrite of `99a99b479ecf`
- no quality-gate fix for `[质量门禁] ... 抽取=0张`; that remains a separate open issue
- no validation-only recovery API/button yet; the prior final-validation hardening only records recovery metadata

## Production acceptance after deploy

Do not mark these items CLOSED until real A800 acceptance is performed.

### A. Resource discovery

1. deploy the current branch and restart the supervisor/Workers using the normal production command;
2. verify both child Workers are online;
3. verify the background Worker advertises/owns discovery capability/handler;
4. create or leave an existing `RESOURCE_DISCOVERY` task queued;
5. confirm it is claimed by the background Worker without starting a separate manual discovery Worker;
6. confirm training Worker remains training-only.

Expected:

```text
RESOURCE_DISCOVERY: QUEUED -> RUNNING -> terminal result
training tasks remain isolated from discovery work
```

### B. Failed training cleanup

Use a short controlled training acceptance rather than another 300-epoch run.

Verify after success, failure, cancellation, and an intentionally terminated training leader where practical:

1. durable task does not become terminal before cleanup is verified;
2. no task-owned training/DataLoader execution remains;
3. no old task process group remains executing;
4. GPU reservation is released after cleanup;
5. `nvidia-smi` memory returns to the expected idle/baseline range within a reasonable driver cleanup window;
6. a queued next training automatically progresses once admission is satisfied;
7. no manual `pkill python` or server reboot is required.

## Status

### Resource Discovery Worker ownership

```text
IMPLEMENTED
+ AUTOMATED REGRESSION
REAL PRODUCTION ACCEPTANCE = PENDING
```

### Training orphan process cleanup

```text
IMPLEMENTED
+ REAL SUBPROCESS REGRESSION
REAL A800 GPU-MEMORY / NEXT-TASK ACCEPTANCE = PENDING
```

### Training Final Validation OOM Hardening

Still:

```text
IMPLEMENTED
+ AUTOMATED REGRESSION
REAL A800 FINAL-VALIDATION ACCEPTANCE = PENDING
```

### Quality gate sample extraction

Still open:

```text
[质量门禁] epoch=300 抽取=0张 map50=0.90642 decision=continue
```

Do not claim it was fixed by this batch.
