# Training Checkpoint Recovery — v42.25 Closure

## Status

```text
TRAINING CHECKPOINT RECOVERY
CLOSED
```

Accepted product/test tree before this documentation commit:

```text
branch: refactor/frontend-runtime-stabilization
accepted HEAD: fb002174248b19dd3f42959d417d1da87b75df1a
formal VERSION.txt: 42.24.0
```

This closure adds a truthful recovery path for a training task whose training loop has completed but whose post-training/final checkpoint validation failed. It does **not** restart the full training loop and it does **not** create a second training task.

## Durable recovery contract

Recovery is backend-owned. The frontend must never infer recovery eligibility from visible progress such as `100/100 Epoch`.

A failed task is actionable only when durable task state and `failure.json` agree that:

- the durable task is `TRAINING` and currently `FAILED`;
- failure evidence belongs to the same `task_id` and `project_id`;
- `training_loop_completed == true`;
- `failure_stage` is `final_validation` or `post_training`;
- the failure evidence declares `recoverable == true`;
- a `best` checkpoint is recorded and exists as a non-empty file;
- the recorded checkpoint has a SHA256 digest;
- `recovery_action == revalidate_checkpoint`.

The single-task recovery detail endpoint performs a real SHA256 verification before presenting the action as available. The recovery POST performs the same verification again immediately before mutating durable task state.

The list projection intentionally uses the cheaper persisted-evidence/file-existence check so the normal two-second training-task polling path does not re-hash multiple large model files on every refresh. The actionable detail and mutation boundaries remain hash-verified.

## Same-task retry, not retraining

Recovery calls the existing `TaskRepository.retry(task_id)` for the same durable task record. The repository changes that terminal task back to `QUEUED`, sets `retry_of` to the same task id, and clears terminal execution ownership fields.

The existing `RecoveryHardenedLabelContractTrainingHandler` remains the execution owner. On an explicit retry it validates the stored snapshot, portable dataset bundle, runtime data YAML, checkpoint path/hash, and current assignment before starting isolated checkpoint validation. A trusted successful validator result is then finalized through the existing training completion/version archival path.

No second Scheduler, TaskRepository, Worker registry, training queue, version owner, or full-training retry mechanism was introduced.

## API

```text
GET  /api/v62/projects/{project_id}/training-tasks/{task_id}/recovery
POST /api/v62/projects/{project_id}/training-tasks/recovery-query
POST /api/v62/projects/{project_id}/training-tasks/{task_id}/recovery
```

Recovery action payload:

```json
{"action":"revalidate_checkpoint"}
```

## Frontend behavior

`TrainingRecoveryRuntime` is a presentation/action runtime only. It does not own a polling timer.

The training task list batch-loads recovery truth only for failed tasks. A recoverable history row shows that a preserved checkpoint is available. Opening the task detail fetches fresh, hash-verified backend truth and displays the failure reason, Epoch evidence, checkpoint status, process signal/return code when present, and the queue → data preparation → training → checkpoint → final validation → archive timeline.

`重新验证 Checkpoint` is rendered only when backend truth satisfies the full recovery contract. Submitting it rechecks detail truth, posts the action, then reuses the existing `TrainingTaskRuntime` refresh path and existing `PollRegistry` training timer. No `setTimeout` or `setInterval` polling owner was added.

The Real Chrome acceptance path is:

```text
历史记录
  → 最终验证失败任务
  → 详情
  → 重新验证 Checkpoint
  → same task_id POST recovery
  → 当前任务
  → same task_id 排队中
```

## Core files

```text
platform_core/training_recovery_api.py
platform_core/training_recovery_tasks.py
platform_core/material_batches.py
platform_core/task_runtime/repository.py
static/modules/training-recovery-runtime.js
static/modules/training-task-runtime.js
static/main.mjs
tests/unit/test_training_recovery_api.py
tests/frontend/training-recovery-runtime.test.mjs
tests/browser/training-recovery.spec.mjs
tests/browser/training-task-performance.spec.mjs
.github/workflows/training-recovery-guard.yml
```

## Permanent guards

Dedicated workflow: `Training Recovery Guard`.

It permanently verifies:

- backend recovery API compilation;
- backend recovery contract tests;
- frontend recovery/runtime syntax and unit contracts;
- same-task `repository.retry(task_id)` ownership;
- full hash verification at actionable boundaries;
- fixed `revalidate_checkpoint` action semantics;
- no recovery-owned polling timer;
- explicit regression that `100/100 Epoch` alone cannot grant recovery;
- Real Chrome recovery flow.

## Acceptance evidence

### Recovery-specific acceptance

GitHub Actions run `34978171413` on `6c546910bc242ea6759274b3f24cc326d83caa48`:

```text
recovery-contracts     SUCCESS
real-chrome-recovery   SUCCESS
```

This run covers the final recovery production code. The later `fb002174...` commit only updates a stale build-marker assertion in the pre-existing training performance browser test; it does not change recovery production code.

### Full frontend acceptance

GitHub Actions run `34978755928` on `fb002174248b19dd3f42959d417d1da87b75df1a`:

```text
frontend               SUCCESS
browser-navigation     SUCCESS
```

The frontend job includes syntax checks, retired-mirror guards, canonical training network-owner guard, TrainingDraft/TrainingLabel ownership guards, PollRegistry owner guards, retired `setPage` guard, and the full frontend unit suite.

The browser job passes the existing full Real Chrome regression suite, including the training-task performance contract. Its performance/network assertions remain unchanged: focused refresh still performs only the expected jobs request and does not rebuild the page or trigger unrelated bootstrap/algorithm/dataset/material loads.

### Navigation action fencing

GitHub Actions run `34978755907` on `fb002174248b19dd3f42959d417d1da87b75df1a`:

```text
action-fencing         SUCCESS
```

This includes the permanent source guard, action-fence unit contracts, and Real Chrome stale-mutation contract.

## Explicit non-claims

This closure does not claim that a missing, truncated, moved, or hash-mismatched checkpoint can be recovered. Such evidence must remain non-actionable.

It does not claim that a failure during the actual training process can skip training and proceed to validation. Only the two explicitly recoverable post-training stages are eligible.

It does not add automatic retry policy, repeated retry loops, a second task record, a second queue, or a second polling owner.

It does not constitute A800/real NVIDIA hardware acceptance. The checkpoint recovery contract, browser path, task ownership and durable state transitions are accepted here; real A800 RC remains separately paused unless explicitly resumed.

Formal `VERSION.txt` remains `42.24.0`; no `main` merge, tag, or release is part of this closure.
