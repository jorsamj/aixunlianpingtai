# Codex Handoff — Training Final Validation OOM Hardening / Failure Truth

> Branch: `refactor/frontend-runtime-stabilization`
>
> Live GitHub HEAD always outranks stale SHA text in older documents. Read `docs/CODEX_READ_FIRST.md` first.

## 1. Real A800 production-shaped incident

Task:

```text
task_id: 99a99b479ecf
project_id: f1fb1e6fa373
training PID: 310980
GPU: NVIDIA A800-SXM4-40GB
```

The training loop itself reached 300/300 epochs and wrote real checkpoints:

```text
300 epochs completed in 1.619 hours.
last.pt written at about 13:14:00
best.pt written at about 13:14:00
```

Ultralytics then started its automatic post-training validation of `best.pt` and reached `5/7`.

At approximately 13:14:10 the Linux kernel recorded a global host-memory OOM and killed the exact training PID:

```text
Out of memory: Killed process 310980 (python)
anon-rss: about 5.7 GiB
shmem-rss: about 9.3 GiB
```

The durable task correctly ended as `FAILED`; the process was dead and the Worker/GPU lease had been released. `result_ref` was not committed.

This is host RAM/shared-memory pressure, not evidence of A800 VRAM exhaustion.

## 2. Why the previous failure message was misleading

The old child-process failure path preferred the last `job.json` message when the process exited non-zero:

```text
RuntimeError: 训练中 · Epoch 300/300
```

That stale progress text hid the actual process termination and the completion-handshake reason.

A terminal training error must preserve process exit truth and completion truth rather than reusing a progress message.

## 3. Implemented hardening

### 3.1 Bounded automatic DataLoader workers

Added:

```text
train_worker_safe.py
```

Automatic resource strategy now receives an additional host-RAM safety ceiling for DataLoader workers.

Default:

```text
TRAINING_AUTO_MAX_DATALOADER_WORKERS=2
```

Operators may override the environment variable with an integer from 0 through 32.

Important behavior:

- the cap is applied only to `resource_strategy=auto`;
- manual strategy remains explicit and is not silently rewritten;
- the original `platform_core.training_metrics.resolve_resources()` remains the base resource resolver;
- the safety bootstrap is installed before importing/running the existing `train_worker.py` main path;
- CUDA/Ultralytics are not initialized early by the bootstrap.

The existing resolver already limits workers by request, CPU capacity and loader capacity. This hardening adds a conservative host-RAM ceiling because the real A800 host has comparatively small system RAM relative to GPU capacity.

### 3.2 Existing Training/Label contracts are preserved

Added:

```text
platform_core/training_hardened_tasks.py
```

Worker registration now maps the `training` role to this module.

The module subclasses/reuses the existing `LabelContractTrainingHandler` and still uses the same:

```text
TaskRepository
Scheduler
Worker Runtime
GPU reservation/admission
ProcessController
strict training completion handshake
training snapshot/bundle verification
algorithm version finalization
```

No second Scheduler, queue, Worker heartbeat, or GPU-reservation implementation was added.

### 3.3 Truthful process failure evidence

When the training child exits without a trusted completion handshake, the hardened process runner records bounded structured evidence in:

```text
failure.json
```

and mirrors the relevant failure fields into the project `job.json`.

Evidence includes:

```text
process_returncode
process_signal
failure_stage
completion_error
completed_epochs
requested_epochs
training_loop_completed
checkpoint_available
checkpoint paths / size / SHA256
recoverable
recovery_action
log tail
```

On POSIX, a return code of `-9` is truthfully recorded as `SIGKILL`.

The platform deliberately does NOT infer `OOM` merely from `SIGKILL`. Kernel/cgroup/service evidence remains authoritative for deciding whether the external kill was an OOM kill.

The terminal RuntimeError now prioritizes process signal/return code and completion-handshake truth. A stale progress message such as `训练中 · Epoch 300/300` can no longer replace the real failure reason.

### 3.4 Recoverable final-validation semantics without fabricating success

If all of the following are evidenced:

```text
requested training epochs completed
+ log contains the completed-epochs marker
+ best/last checkpoint evidence exists
+ final best.pt validation had started
+ process exits before a trusted completion handshake
```

then failure metadata can record:

```text
failure_stage = final_validation
checkpoint_available = true
recoverable = true
recovery_action = revalidate_checkpoint
```

But the task remains `FAILED`.

No official algorithm version/result is published from an unverified checkpoint.

The current batch intentionally records:

```text
recovery_action_available = false
```

because a real validation-only recovery task/API/button has NOT been implemented yet. Do not claim the user can already click "revalidate". That can be a later narrow batch.

A partial checkpoint from an unfinished training loop does NOT become recoverable merely because `best.pt` exists.

## 4. Worker registration

Modified:

```text
platform_core/worker_registry.py
```

The training role now points to:

```text
platform_core.training_hardened_tasks
```

The capability remains:

```text
training.ultralytics
```

Training Worker isolation semantics remain unchanged.

## 5. Permanent regression coverage

Added:

```text
tests/unit/test_training_final_validation_oom_hardening.py
.github/workflows/training-final-validation-hardening.yml
```

The focused regression locks down:

1. automatic DataLoader worker cap defaults to 2;
2. the cap is operator configurable;
3. manual worker configuration is not silently changed;
4. invalid cap configuration fails explicitly;
5. the exact real-incident shape (`99a99b479ecf`, 300 epochs completed, final validation 5/7, best/last checkpoints, return code -9) becomes a recoverable `final_validation` failure with `SIGKILL` truth;
6. failure text contains signal/return code/stage/handshake reason and does not fall back to stale `Epoch 300/300` progress text;
7. `SIGKILL` alone does not fabricate an OOM diagnosis;
8. checkpoint existence during incomplete training does not fabricate recoverability;
9. the Training Worker is wired to the hardened label-contract handler;
10. existing finalization-handshake/resource-contract/Worker-registry regressions run in the same dedicated CI.

Do not weaken these guards to turn an unverified checkpoint into a successful version.

## 6. Files changed in this batch

```text
train_worker_safe.py
platform_core/training_hardened_tasks.py
platform_core/worker_registry.py
tests/unit/test_training_final_validation_oom_hardening.py
.github/workflows/training-final-validation-hardening.yml
docs/CODEX_HANDOFF_2026-09-15_TRAINING_FINAL_VALIDATION_OOM.md
docs/CODEX_READ_FIRST.md
```

## 7. Explicit non-scope

This batch does NOT implement or change:

```text
GPU Runtime Truth Phase 1B
node-scoped gpu_reservations migration
remote Worker/server routing
cross-node automatic GPU scheduling
Scheduler claim ordering
TaskRepository terminal semantics
formal VERSION.txt
```

It also does NOT manually recover historical task `99a99b479ecf` or change its durable `FAILED` status.

## 8. Separate evidence-backed follow-up: quality gate sampled 0 images

The same real run logged:

```text
[质量门禁] epoch=300 抽取=0张 map50=0.90642 decision=continue
```

This batch does NOT claim to fix that behavior.

The `0张` evidence must be audited separately to determine whether the stage-quality gate actually executed the requested independent evaluation sample, or merely fell back to trainer validation metrics. Do not treat a high mAP50 as proof that the configured sample-based gate ran.

## 9. Real A800 acceptance still required

Use the status:

```text
Training Final Validation OOM Hardening
IMPLEMENTED + AUTOMATED REGRESSION
REAL A800 FINAL-VALIDATION ACCEPTANCE: PENDING
```

Do not mark this batch `CLOSED` yet.

Recommended real acceptance after deploying the current HEAD:

1. confirm a Training Worker uses the current build and hardened registration;
2. run a short real A800 training with `resource_strategy=auto`;
3. confirm the resolved DataLoader workers are no more than the configured safety cap (default 2);
4. observe host RAM/shared memory through training and automatic final validation;
5. confirm final `best.pt` validation completes and the task reaches trusted completion/100%;
6. confirm no new kernel/cgroup host-memory OOM occurred for the training PID;
7. if a child is externally killed in a controlled test/staging scenario, confirm `failure.json` and durable task error expose signal/returncode/stage/handshake truth instead of stale progress text;
8. leave historical task `99a99b479ecf` unchanged; its checkpoints may be separately revalidated later but its past task truth must not be rewritten.

## 10. Next work after this acceptance

Keep the sequence narrow:

```text
1. A800 acceptance for this final-validation hardening
2. Audit/fix quality-gate `抽取=0张`
3. Optionally implement a real validation-only recovery task/API for preserved checkpoints
4. Re-run the full training finalization acceptance
5. Only then resume GPU Runtime Truth Phase 1B when explicitly requested
```
