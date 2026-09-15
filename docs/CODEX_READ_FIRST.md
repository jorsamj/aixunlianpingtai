# Codex Read First

This is the shortest entry point for continuing `jorsamj/aixunlianpingtai` on branch `refactor/frontend-runtime-stabilization`.

## Mandatory read order

Before editing, read and reconcile these files against live GitHub HEAD:

1. `docs/CODEX_READ_FIRST.md`
2. `docs/CODEX_HANDOFF_2026-09-15_TRAINING_TASK_VISIBILITY.md`
3. `docs/CODEX_HANDOFF_2026-09-15_TRAINING_WORKER_ISOLATION.md`
4. `docs/CODEX_CURRENT_STATE.md`
5. `docs/TECH_DEBT_CLOSURE_V42_25.md`
6. `docs/frontend-legacy-audit.md`
7. `docs/FRONTEND_OWNER_MAP_V42_25.md`

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

## Current acceptance work

These implementations are not yet fully `CLOSED` until the real production-shaped checks are completed.

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

Do not silently combine Phase 1B with the frontend visibility or Worker-isolation acceptance work.

## Acceptance wording

Until real A800 acceptance is complete, use:

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

Do not mark either P0 `CLOSED` before its real acceptance is complete.
