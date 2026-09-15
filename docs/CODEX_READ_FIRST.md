# Codex Read First

This is the shortest entry point for continuing `jorsamj/aixunlianpingtai` on branch `refactor/frontend-runtime-stabilization`.

## Mandatory read order

Before editing, read and reconcile these files against live GitHub HEAD:

1. `docs/CODEX_READ_FIRST.md`
2. `docs/CODEX_HANDOFF_2026-09-15_TRAINING_FINAL_VALIDATION_OOM.md`
3. `docs/CODEX_HANDOFF_2026-09-15_TRAINING_TASK_VISIBILITY.md`
4. `docs/CODEX_HANDOFF_2026-09-15_TRAINING_WORKER_ISOLATION.md`
5. `docs/CODEX_CURRENT_STATE.md`
6. `docs/TECH_DEBT_CLOSURE_V42_25.md`
7. `docs/frontend-legacy-audit.md`
8. `docs/FRONTEND_OWNER_MAP_V42_25.md`

`docs/CODEX_CURRENT_STATE.md` contains valuable historical closure detail, but its top branch/push snapshot may lag the live branch. Never trust an old SHA or `push pending` sentence over the actual remote branch.

## Non-negotiable repository constraints

- Do not merge `main`.
- Keep `VERSION.txt` exactly `42.24.0`.
- No tag, release or force push.
- Windows development + NVIDIA Linux production compatibility is mandatory.
- Do not delete/relax tests or lower thresholds to make CI pass.
- Do not restore retired legacy owners.
- Reuse existing TaskRepository, Scheduler, Worker Runtime, Worker heartbeat, PollRegistry and GPU admission/reservation truth; do not build parallel replacements.

## Current implemented stability batches

### GPU Runtime Truth Phase 1A

Implemented and pushed before the Worker-isolation batch. Real NVIDIA/A800/multi-node/MIG acceptance is still pending. Phase 1B has not started.

### Training Worker Isolation & Fast Dispatch

Implemented in the current branch. Read the dedicated handoff for exact code and acceptance boundaries:

`docs/CODEX_HANDOFF_2026-09-15_TRAINING_WORKER_ISOLATION.md`

Key invariant:

```text
non-training work busy
!=
training Worker blocked
```

Compatibility `task_worker.py --roles all` now supervises an isolated `training` child and a separate non-training background child. It must never regress to one serial all-handler Scheduler.

Default/auto resource discovery no longer escalates to whole-machine recursive scanning when roots are omitted. Deep/full discovery requires explicit roots.

The dedicated Scheduler claim loop remains the existing implementation; default idle poll is `0.25s`. No second scheduler or queue was introduced.

### Training Task Visibility Stability / Single Final Rendering Owner

Implemented in the current branch. Read:

`docs/CODEX_HANDOFF_2026-09-15_TRAINING_TASK_VISIBILITY.md`

Real user evidence was:

```text
TaskRepository = RUNNING
/jobs = task present
training process = advancing
UI = task temporarily disappears
later polling = task reappears
```

The concrete race was frontend ownership:

```text
legacy loadRelated()
  /api/projects/{project_id}
  -> state.jobs

TrainingTaskRuntime
  /api/projects/{project_id}/jobs
  -> state.jobs
```

plus legacy `renderTraining423/424/425` rendering the same table.

The current branch now gives canonical training jobs and final training rows to the focused training runtime/visibility owner. Generic project refreshes cannot erase canonical `state.jobs`, and the visibility runtime does not create another timer. PollRegistry remains the sole training polling owner.

Non-terminal transitional states (`starting`, `pausing`, `resuming`, `stopping`, `cancel_requested`) remain visible and continue polling where appropriate.

Do not fix future visibility problems by increasing polling frequency, fabricating tasks in browser memory, adding another polling owner, or delayed DOM reinsertion.

### Training Final Validation OOM Hardening / Failure Truth

Implemented in the current branch. Read first:

`docs/CODEX_HANDOFF_2026-09-15_TRAINING_FINAL_VALIDATION_OOM.md`

Real A800 evidence came from task `99a99b479ecf`:

```text
300/300 training epochs completed
best.pt / last.pt written
Ultralytics automatic final validation reached 5/7
Linux global host-memory OOM killed exact training PID 310980
TaskRepository = FAILED
```

This was host RAM/shared-memory pressure, not evidence of A800 VRAM exhaustion.

The current branch now:

- bounds automatic DataLoader workers with `TRAINING_AUTO_MAX_DATALOADER_WORKERS` (default `2`);
- leaves manual worker settings explicit rather than silently rewriting them;
- keeps the existing Label Contract, Scheduler, Worker Runtime and strict completion handshake;
- preserves real process return code/signal and completion-handshake reason on child failure;
- writes structured `failure.json` evidence;
- can classify an evidenced `300/300 + checkpoint + final validation interrupted` case as a recoverable `final_validation` failure without converting it to success;
- does not infer OOM from `SIGKILL` alone;
- does not publish an official algorithm version from an unverified checkpoint.

Important boundary:

```text
recovery_action = revalidate_checkpoint
recovery_action_available = false
```

A real validation-only recovery task/API/button is not implemented yet. Do not claim it exists.

The historical task `99a99b479ecf` must remain historical `FAILED` truth. Do not manually rewrite it to success.

The same run also logged:

```text
[质量门禁] epoch=300 抽取=0张 map50=0.90642 decision=continue
```

That is a separate evidence-backed follow-up. The current OOM-hardening batch does not claim to fix the `抽取=0张` behavior.

## Current acceptance work

These implementations are not yet fully `CLOSED` until the real production-shaped checks are completed.

### Training Final Validation OOM Hardening

Verify on A800 after deploying the latest HEAD:

```text
resource_strategy=auto
-> resolved DataLoader workers <= configured safety cap (default 2)
-> training completes
-> automatic best.pt final validation completes
-> no new host-memory OOM for training PID
-> trusted completion handshake reaches terminal success / 100%
```

For a controlled external-kill failure, verify failure evidence exposes signal/returncode/stage/completion reason rather than stale progress text.

### Training Worker Isolation

Verify on A800:

```text
background material/annotation/video work active
+
Training Worker idle
+
GPU available
+
TRAINING queued
-> training independently claims in roughly 1–3 seconds
```

### Training Task Visibility

Verify in a real browser while real A800 training advances:

```text
/jobs continuously contains active task
+
manual refresh / polling / navigation / unrelated data refreshes
-> active row never disappears
```

Exercise pause/resume/stop transitions and confirm the task remains visible through transitional states.

## Still later / explicitly not started

GPU Runtime Truth Phase 1B remains separate:

- node-scoped `gpu_reservations`
- cross-node worker-slot identity/uniqueness migration
- full GPU assignment identity
- worker/server remote routing
- automatic cross-node GPU scheduling

Do not silently combine Phase 1B with final-validation hardening, frontend visibility, or Worker-isolation acceptance work.

## Acceptance wording

Until real A800 final-validation acceptance is complete, use:

```text
Training Final Validation OOM Hardening
IMPLEMENTED + AUTOMATED REGRESSION
REAL A800 FINAL-VALIDATION ACCEPTANCE: PENDING
```

Until real A800 Worker-isolation acceptance is complete, use:

```text
Training Worker Isolation & Fast Dispatch
IMPLEMENTED + AUTOMATED REGRESSION
REAL A800 CONCURRENCY / 1-3s DISPATCH ACCEPTANCE: PENDING
```

Until real-browser/A800 visibility acceptance is complete, use:

```text
Training Task Visibility Stability
IMPLEMENTED + AUTOMATED REGRESSION
REAL BROWSER / A800 ACCEPTANCE: PENDING
```

Do not mark these P0 items `CLOSED` before their real acceptance is complete.
