# Codex Read First

This is the shortest entry point for continuing `jorsamj/aixunlianpingtai` on branch `refactor/frontend-runtime-stabilization`.

## Mandatory read order

Before editing, read and reconcile these files against live GitHub HEAD:

1. `docs/CODEX_READ_FIRST.md`
2. `docs/CODEX_HANDOFF_2026-09-15_TRAINING_WORKER_ISOLATION.md`
3. `docs/CODEX_CURRENT_STATE.md`
4. `docs/TECH_DEBT_CLOSURE_V42_25.md`
5. `docs/frontend-legacy-audit.md`
6. `docs/FRONTEND_OWNER_MAP_V42_25.md`

`docs/CODEX_CURRENT_STATE.md` contains valuable historical closure detail, but its top branch/push snapshot may lag the live branch. Never trust an old SHA or `push pending` sentence over the actual remote branch.

## Non-negotiable repository constraints

- Do not merge `main`.
- Keep `VERSION.txt` exactly `42.24.0`.
- No tag, release or force push.
- Windows development + NVIDIA Linux production compatibility is mandatory.
- Do not delete/relax tests or lower thresholds to make CI pass.
- Do not restore retired legacy owners.
- Reuse existing TaskRepository, Scheduler, Worker Runtime, Worker heartbeat and GPU admission/reservation truth; do not build parallel replacements.

## Current completed implementation batch

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

## Next P0 after Worker-isolation acceptance

### Training Task Visibility Stability / Single Rendering Owner

Real user evidence already exists:

```text
TaskRepository = RUNNING
/jobs = task present
training process = advancing
UI = task temporarily disappears
later polling = task reappears
```

Treat this as a frontend state/render ownership race, not backend task loss.

The next focused batch should audit and fix:

```text
static/modules/training-task-runtime.js
static/app.js renderTraining423/424/425 legacy paths
loadRelated()/state.jobs writes
PollRegistry / navigation request fencing
```

Goal: the newest `/jobs` truth has exactly one runtime owner and stale/legacy rendering can never remove a non-terminal task that the latest response contains.

Do not fix this by increasing polling frequency, fabricating tasks in browser memory, adding a second polling owner, or using delayed DOM reinsertion.

## Still later / explicitly not started

GPU Runtime Truth Phase 1B remains separate:

- node-scoped `gpu_reservations`
- cross-node worker-slot identity/uniqueness migration
- full GPU assignment identity
- worker/server remote routing
- automatic cross-node GPU scheduling

Do not silently combine Phase 1B with the frontend visibility P0.

## Acceptance wording

Do not mark Training Worker Isolation `CLOSED` until real A800 concurrency and seconds-level dispatch are manually verified.

Until then use:

```text
Training Worker Isolation & Fast Dispatch
IMPLEMENTED
AUTOMATED CI: verify live latest HEAD
REAL A800 CONCURRENCY / 1-3s DISPATCH ACCEPTANCE: PENDING
```
