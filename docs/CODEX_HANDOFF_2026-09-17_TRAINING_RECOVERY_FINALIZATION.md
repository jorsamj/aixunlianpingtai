# Codex Handoff — Training Recovery / Final Validation / Finalization Replay

Date: 2026-09-17

Repository: `jorsamj/aixunlianpingtai`

Branch: `refactor/frontend-runtime-stabilization`

Formal version: `VERSION.txt = 42.24.0` (unchanged)

## Closure status

**CLOSED for code-level durable recovery contracts and browser-visible recovery truth.**

This closure does **not** claim that a real A800 process-kill / machine-loss fault-injection campaign has been executed. Real NVIDIA/A800 production fault injection remains a separate acceptance item.

## What is now durable

### 1. Interrupted training resumes from the trusted task-local checkpoint

A reclaimed durable training task may enter `training_checkpoint_resume` only when the recovery admission can prove all of the following:

- this is a reclaimed attempt, not the first execution;
- the same task/job identity is preserved;
- training did not already complete;
- the frozen Snapshot identity still matches;
- the portable training bundle still verifies;
- the runtime data YAML still exists;
- the task-local `runs/train_<task_id>/weights/last.pt` exists and is non-empty;
- durable epoch evidence proves `0 < completed < requested`;
- the current Scheduler assignment belongs to the **new** lease (`assignment.lease_token == context.lease.lease_token` and worker id also matches);
- the checkpoint SHA256 is calculated before dispatch and passed to the resume worker.

The resume worker executes Ultralytics resume semantics and derives the effective resumed epoch from the loaded trainer/checkpoint state (`trainer.start_epoch`) rather than blindly restarting from epoch 0.

Result: a Worker crash during epoch execution can recover through the existing durable task reclaim path and continue from trusted `last.pt` state instead of creating a fresh training run.

### 2. Final Validation remains an isolated recovery stage

Existing post-training recovery remains distinct from epoch resume. If the training loop is complete but Final Validation failed or was interrupted, the recovery path does not re-enter epoch training merely because the durable task is reclaimed.

Checkpoint-resume admission explicitly rejects post-training/final-validation failures so they stay on the validation-recovery contract.

### 3. Successful Final Validation can replay persistence only

`finalization_replay` is now a separate admitted recovery mode for the crash window after Final Validation has already succeeded but before final result / algorithm-version persistence fully completes.

Replay is fail-closed. It requires trusted evidence including:

- reclaimed task attempt;
- matching job/task identity;
- matching frozen Snapshot identity;
- a successful `final-validation.json` bound to the same task and Snapshot;
- final-validation checkpoint path constrained to the task project runs tree;
- checkpoint SHA256 still matching;
- validated published-model set matching the job's verified-model set;
- every published model still inside the project model tree and present on disk;
- portable bundle evidence still verifies.

When admitted, the system marks validation as reused (`final_validation_reused=true`) and performs final persistence/commit work without rerunning epochs or Final Validation.

This covers the intended recovery case:

```text
training complete
→ Final Validation success
→ persistence/version commit interrupted
→ reclaimed task
→ finalization_replay
→ persistence only
```

### 4. Recovery execution is fenced to the current assignment

This batch does not introduce a second Worker registry or a parallel lease system. It consumes the existing fenced durable-task execution path.

Checkpoint-resume admission specifically requires the persisted Scheduler assignment lease token and worker id to match the current reclaimed `WorkerContext`. A stale assignment is rejected. The resume worker therefore cannot be admitted merely because an old `last.pt` exists.

The broader existing task-runtime fencing remains authoritative for writes/ownership; this closure does not claim a new independent dual-writer protocol.

## Frontend truth

The training task projection/UI now preserves and displays automatic recovery state instead of flattening it into a generic running task.

Permanent contracts cover checkpoint-resume fields and finalization-replay fields, including:

- `recovery_state`
- checkpoint resume state/epoch evidence
- `finalization_replay`
- `final_validation_reused`
- backend `finalizing_commit` phase

The recovery UI explicitly tells the operator that `finalization_replay` does not retrain and does not rerun Final Validation.

A Real Chrome regression also exposed a UI defect in the recovery badge decorator: its `MutationObserver` could repeatedly assign the same `textContent`, retrigger itself, and leave training refresh stuck in-flight. Commit `802703e37a22aacda18cd99369bfdf8bf3fe4604` made the decoration idempotent, eliminating that self-triggering mutation loop.

## Permanent gate

Workflow:

`.github/workflows/training-recovery-guard.yml`

The permanent workflow covers:

- backend recovery contracts;
- checkpoint-resume backend contracts;
- checkpoint/job public projection truth;
- frontend recovery/runtime contracts;
- permanent source guards;
- Windows checkpoint-resume matrix;
- Ubuntu checkpoint-resume matrix;
- Real Chrome recovery UI.

### Accepted recovery run

`Training Recovery Guard` run `35168133304` — **PASS**

Jobs:

- `recovery-contracts` — PASS
- `checkpoint-resume-contracts (windows-latest)` — PASS
- `checkpoint-resume-contracts (ubuntu-24.04)` — PASS
- `real-chrome-recovery` — PASS

Related Navigation Action Fencing run `35168133302` — **PASS**.

## Full frontend regression follow-up

The first full Frontend Runtime run after the training recovery UI fix exposed an unrelated legacy ZIP import-modal refresh inconsistency. This was not ignored or hidden.

Root cause: legacy `openImportDock()` in `app.js` calls lexical `loadImportJobs()` directly. A wrapper placed only on `window.loadImportJobs` therefore did not consume the intended startup snapshot during modal open; the first explicit user refresh could instead consume stale runtime state.

Final fix:

- `7dcf82a076e59b1634b5bedef728774f646fb357` — `fix(import): keep legacy ZIP modal refresh server-backed`
- `539503a70112e2b06fce3dac1006044bfb3f3fbc` — `test(import): guard server-backed legacy ZIP modal refresh`

The legacy ZIP modal now always reads the backend on open/explicit refresh, while the durable ZIP runtime remains the sole background polling/completion-side-effect owner.

Permanent evidence after the fix:

- `ZIP Import Durable Runtime` run `35169684627` — **PASS**
  - Ubuntu contract — PASS
  - Windows contract — PASS
  - backend persistence — PASS
  - Real Chrome refresh recovery — PASS
- `Frontend Runtime Stabilization` run `35169693395` — **PASS**
  - frontend/unit/owner guards — PASS
  - full Real Chrome runtime regressions — PASS
- `Navigation Action Fencing` run `35169693364` — **PASS**
  - source guard — PASS
  - unit contracts — PASS
  - Real Chrome stale-mutation contract — PASS

A diff audit from the accepted training-recovery product head `802703e37a22aacda18cd99369bfdf8bf3fe4604` through `539503a70112e2b06fce3dac1006044bfb3f3fbc` shows only ZIP bridge/test changes. No training checkpoint, Final Validation, recovery, Worker, or fencing implementation was changed by the ZIP follow-up.

## Important boundaries still open

The following are **not** closed by this handoff:

- real A800/NVIDIA Worker process-kill fault injection during training;
- real host loss / container replacement / network partition acceptance;
- GPU Runtime Truth Phase 1B node-scoped reservation/scheduling work;
- real multi-node GPU scheduling/routing;
- genuine 10,000-image ZIP production wall-clock throughput acceptance;
- resumable browser ZIP upload before the backend returns a durable job id.

A800 RC and genuine 10k ZIP timing acceptance remain paused unless explicitly reopened by the user.

## Release constraints preserved

- no merge to `main`;
- no formal version bump;
- no tag;
- no release;
- `VERSION.txt` remains `42.24.0`.
