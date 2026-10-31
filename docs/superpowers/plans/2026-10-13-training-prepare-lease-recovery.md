# TRAINING_PREPARE Lease Recovery Implementation Plan

**Goal:** Make a reclaimed `TRAINING_PREPARE` task recover safely without letting a stale Worker fail or activate its parent training task.

**Architecture:** Keep the existing Scheduler, `WorkerContext`, `TaskRepository`, and `TrainingPrepareHandler`. Add atomic owner predicates to the two parent-task mutations, validate durable preparation evidence before reuse, propagate execution fencing unchanged, and log lease-renewal failures through the service logger so diagnosis does not depend on SQLite.

**Tech Stack:** Python, SQLite/WAL, pytest, vanilla ES modules, Node test runner.

---

### Task 1: Reproduce recovery and stale-owner failures

**Files:**
- Modify: `tests/integration/test_remote_training_prepare_task.py`
- Modify: `tests/unit/task_runtime/test_fencing.py`

- [x] Add a scheduler regression proving attempt 2 calls `recover()` and validated preparation evidence activates the parent once.
- [x] Add a stale-generation regression proving an old preparation lease cannot fail or activate a queued `TRAINING` parent.
- [x] Add cancellation-vs-recovery coverage proving a cancelled parent is never reactivated.
- [x] Run the focused tests and observe failure from the missing handler recovery/owner fence.

### Task 2: Add atomic preparation ownership predicates

**Files:**
- Modify: `platform_core/task_runtime/repository.py`
- Modify: `platform_core/remote_training_tasks.py`

- [x] Extend `activate_prepared_training()` and `fail_queued_precondition()` with preparation task ID, lease token, and execution generation.
- [x] In the same `BEGIN IMMEDIATE` transaction, require the preparation row to be current, active, unexpired, and generation-matched before changing the parent row.
- [x] Pass the current `WorkerContext` ownership tuple from `TrainingPrepareHandler` for every parent mutation.
- [x] Propagate `ExecutionFencedError` before business-error handling.

### Task 3: Implement evidence-validated recovery

**Files:**
- Modify: `platform_core/remote_training_tasks.py`
- Modify: `tests/integration/test_remote_training_prepare_task.py`

- [x] Add `recover()` that reads the durable target and frozen payload without assuming it remains queued.
- [x] Reuse a prepared result only after matching preparation owner, input-freeze identity, snapshot identity, dataset revision, prepared-input evidence, local archive SHA256/size, and remote object metadata.
- [x] If no READY publication exists, re-enter the existing deterministic preparation path; if a READY publication is incomplete or unverifiable, fail closed instead of reusing it.
- [x] Treat a parent already running/completed under the same verified preparation as already activated; never activate it twice.

### Task 4: Preserve lease-renewal diagnostics

**Files:**
- Modify: `platform_core/task_runtime/worker.py`
- Modify: `platform_core/task_runtime/scheduler.py`
- Modify: `tests/unit/task_runtime/test_scheduler.py`

- [x] Track the last attempted stage/current item in `WorkerContext`.
- [x] Log task ID, kind, Worker ID, generation, stage, UTC time, exception type/reason, and failure classification for renewal failures.
- [x] Keep fencing fail-closed and terminate exact bound processes; do not change the 30-second lease or add retries/threads.
- [x] Prove SQLite busy is logged as database unavailable and is not rewritten as material corruption.

### Task 5: Keep preparation failure presentation truthful

**Files:**
- Verify: `platform_core/training_recovery_api.py`
- Modify: `static/modules/training-recovery-runtime.js`
- Modify: `tests/frontend/training-recovery-runtime.test.mjs`

- [x] Lock the existing backend projection of lease/fencing errors to training-input preparation, not CUDA or trainer failures.
- [x] Show runtime precision as unresolved until a real runtime value exists.
- [x] Show dataset counts as “未生成” until durable counts exist.

### Task 6: Verify and commit

- [x] Run focused prepare, repository, scheduler, recovery-projection, and frontend tests.
- [x] Run affected task-runtime integration suites and `npm test`.
- [x] Run Python/JS syntax checks and `git diff --check`.
- [x] Commit only this plan and the TRAINING_PREPARE reliability changes as the second local commit.
- [x] Do not push, deploy, merge `main`, touch production SQLite, or modify `VERSION.txt`.
