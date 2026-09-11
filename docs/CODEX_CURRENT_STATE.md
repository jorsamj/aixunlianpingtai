# Codex Current State

> First-entry handoff for `jorsamj/aixunlianpingtai`. Always verify live branch/HEAD/diff before editing. Repository code is final authority; `docs/TECH_DEBT_CLOSURE_V42_25.md` is the authoritative v42.25 debt status ledger.

## 1. Branch / release state

```text
current cleanup branch:   refactor/frontend-runtime-stabilization
latest full frontend acceptance point: f3bae76de68b14b0a2799119de62a9b8ac13acaa
Frontend Runtime run:     34595909062
formal VERSION.txt:       42.24.0
frontend badge:           v42.25.0-dev
app.js cache:             42.25.43
main.mjs cache:           42.25.40
training-draft import:    422506
TrainingDraftRuntime import/build: 422511 / training-draft-runtime-422511
TrainingLabelRuntime import: 422508
TrainingSubmitRuntime:    training-submit-422504
```

Run `34595909062` passed syntax, permanent owner/mirror guards, all frontend unit tests and Real Chrome runtime regressions. This is the current full frontend acceptance point.

Do not merge this branch into `main`, bump `VERSION.txt`, tag, or release without explicit user authorization.

## 2. Current priority

**Do not move to A800 yet.** Current order is:

```text
close remaining frontend/runtime technical debt
→ zero-point debt scan
→ resume A800 RC
```

Read before editing, in this order:

```text
docs/TECH_DEBT_CLOSURE_V42_25.md
docs/CODEX_CURRENT_STATE.md
docs/frontend-legacy-audit.md
```

If documents disagree, `TECH_DEBT_CLOSURE_V42_25.md` wins.

## 3. Backend contracts that must not regress

- Snapshot schema v3 and SHA duplicate/leakage protection.
- `confirmed_empty` is the formal negative-sample contract; unannotated zero-box data is not automatically a valid negative.
- task-runtime lease/generation/process fencing and fenced artifact publication.
- explicit training resources cannot be silently increased; preserve requested `batch`, `workers`, and `cache=false`.
- first training uses task-scoped labels only and must not inherit mother-model classes.
- iteration training inherits only the latest successful, artifact-verified, trainable version/schema.
- `training-metrics.sqlite3` uses short deterministic-close SQLite connections; FD regression tests must remain green.

Release gate remains `.github/workflows/v42.25-release-regression.yml`.

## 4. Frontend runtime shape

The frontend is still classic `static/app.js` plus named stabilization modules. It is not Vue. Do not add another numbered override generation.

```text
static/app.js historical shell
  → static/main.mjs
       ├── NavigationStability
       ├── PageRequestScope
       ├── PollRegistry
       ├── AlgorithmListRuntime
       ├── TrainingTaskRuntime
       ├── MaterialPaginationRuntime61
       ├── TrainingDraftRuntime
       ├── TrainingDraftControlsRuntime
       ├── TrainingSubmitRuntime
       ├── TrainingLabelRuntime
       └── AutoLabelPollRuntime
```

New stabilization work should prefer named modules and explicit ownership.

## 5. Canonical training state and submit ownership

The sole training state truth source is:

```text
state.trainingDraft
```

Owner chain:

```text
train-v3 UI
  ↓
state.trainingDraft
  ↓
TrainingDraftRuntime
  ↓
TrainingSubmitRuntime
  ↓
POST /api/v12/projects/{project_id}/train/start
```

Contracts:

- `TrainingDraftRuntime.networkOwner=false`; it never intercepts `/train/start`.
- `TrainingSubmitRuntime.networkOwner=true`; it is the sole training-start network owner.
- all classic `static/app.js` direct `/train/start` paths are physically removed.
- submit readiness belongs to `TrainingSubmitRuntime.trainingSubmitReadiness()`.
- permanent CI fails if `/train/start` returns to `static/app.js`.

Do not restore old payload builders, global fetch wrappers, or DOM readiness writers.

## 6. Five retired training mirrors: CLOSED

The following are **fully retired from active `static/app.js` and from the three core training modules**:

```text
state.trainingLabelSelected
state.trainSplitV3
state.train429Selected
state.train428AlgorithmId
state.train428Config
```

Core modules guarded against reintroduction:

```text
static/modules/training-draft.js
static/modules/training-draft-runtime.js
static/modules/training-labels.js
```

Permanent Frontend CI checks all five names in `static/app.js` and the three modules above.

### Important rule for future AI/Codex

Tests may deliberately create objects with these old field names as **pollution fixtures**. That does not mean compatibility ownership still exists. The required behavior is:

```text
retired field exists in test fixture
→ runtime does not read it
→ runtime does not write it
→ runtime does not delete it
→ state.trainingDraft remains authoritative and unchanged by that stale field
```

Do not reintroduce a fallback because a test mentions one of these names.

## 7. `trainingDraftFromLegacyState` is physically retired

`trainingDraftFromLegacyState` has been removed from `training-draft.js`, `main.mjs`, runtime dependencies and tests.

When `state.trainingDraft` does not yet exist, `TrainingDraftRuntime` now initializes an empty canonical `createTrainingDraft()` and applies only current live controls. It must **not** recover algorithm/material/config from 428/429 mirrors.

Never restore `trainingDraftFromLegacyState`, `bootstrapFromLegacy`, or any equivalent mirror bootstrap.

Current material-selection API is:

```text
TrainingDraftRuntime.materialIds()
TrainingDraftRuntime.setMaterialIds(ids)
TrainingDraftRuntime.toggleMaterialId(id)
→ state.trainingDraft.materialIds
```

## 8. What compatibility debt still remains

Canonical state cleanup is complete, but wrapper/lifecycle debt remains.

### TrainingDraftRuntime wrappers still present

`TrainingDraftRuntime` currently wraps these final classic functions so canonical writes occur before the classic callback:

```text
startAlgorithmTraining429
confirmTrainMaterialPickerV3
setTrainSplitModeV3
saveTrainSettings428
```

`wrapLegacyMutation()` and wrapper restoration in `destroy()` are therefore **still active debt**. Do not claim the runtime is wrapper-free yet. Remove a wrapper only after proving the underlying final UI action writes canonical state directly and Chrome parity remains green.

### TrainingLabelRuntime lifecycle debt still present

It still has legacy entrypoint wrapping/rebinding and modal refresh machinery, including:

```text
startAlgorithmTraining429
startAlgorithmTraining423
openTrain428
openTrain425
refreshTrain429
refreshTrain428
trainCounts425

post-entrypoint timers: 0 / 40 / 120 / 350 / 700 ms
rebind timers:          100 / 400 / 1000 / 2500 ms
modal MutationObserver
```

These are the next high-priority cleanup targets.

## 9. Polling / request ownership

Closed training-task behavior:

- one in-flight `/jobs` refresh;
- 120 ms cross-source poll/manual freshness coalescing;
- mutation refresh forces a fresh request;
- manual refresh re-arms PollRegistry;
- Real Chrome requires exactly one `/jobs` GET per manual refresh.

Do not relax these tests.

Remaining timer/polling debt:

```text
auto422Timer
__videoFramePollTimer
prelabel legacy timer
old setupPagePolling
AutoLabel rebind timers
TrainingLabel rebind/refresh timers
```

A timer is not closed merely because another runtime later clears it. Obsolete creation must be physically removed after ownership proof.

## 10. `app.js` cleanup rule

Continue reducing `static/app.js` only with:

```text
prove final owner
→ retain/add regression test
→ exact physical deletion
→ syntax + unit tests
→ Real Chrome when behavior is affected
```

Do not perform broad blind deletion.

High-value scans:

```text
render = ...
window.setPage = ...
renderXXX412 / 417 / 423 / 428 / 429
loadAll()
loadRelated()
loadCore412()
MutationObserver
setInterval
setTimeout
window.fetch =
```

## 11. Cache/version debt

Current cache identifiers are intentionally recorded so future agents do not use stale values:

```text
styles.css / material-pagination bootstrap: 42.24.0-style versions
app.js:                                  42.25.43
main.mjs:                                42.25.40
training-draft.js import:                422506
training-draft-runtime.js import:        422511
training-labels.js import:               422508
```

Cache-busting is still not unified and remains open debt.

## 12. Current work order

```text
1. prove and retire TrainingDraftRuntime classic entrypoint wrappers where obsolete
2. retire TrainingLabelRuntime wrappers, rebind/refresh timers and MutationObserver where obsolete
3. retire auto422Timer / __videoFramePollTimer / prelabel / setupPagePolling
4. establish renderer/setPage final-owner table and remove obsolete override layers
5. reduce app.js proven dead code
6. eliminate global reload/duplicate-request debt
7. unify cache-busting
8. zero-point MutationObserver/timer/fetch/render/setPage scan
9. migrate version-number business names toward semantic names
10. deterministic-test cleanup + documentation sync
11. TECH_DEBT_CLOSURE_V42_25 zero-point scan
12. resume A800 RC
```

Every runtime batch must end with syntax/unit tests and Real Chrome when browser behavior is affected, then update the debt ledger.

## 13. A800 status

A800 tooling/runbook exists, but acceptance is deliberately **DEFERRED** until the current P0/P1 debt phase is complete.

When resumed:

```text
preflight
→ first A800 short train (fire+smoke, device0, batch16, workers4, cache=false, epochs3–5)
→ verify-job
→ iteration train + verify
→ Worker lifecycle/fencing
→ only then consider v42.25 formal release
```

Frontend/CI success never counts as CUDA/A800 acceptance.

## 14. Do not do

- do not merge `main` without explicit authorization;
- do not add `train430/train431/...` override generations;
- do not restore global render-repair loops;
- do not restore any of the five retired training mirrors as a truth source or fallback;
- do not restore `trainingDraftFromLegacyState` or an equivalent legacy bootstrap;
- do not weaken duplicate-request, owner, race, or browser tests;
- do not rebuild task labels from the project-wide label catalog;
- do not inherit mother-model classes on first training;
- do not claim wrapper/timer debt CLOSED before physical retirement + regression evidence;
- do not claim A800/CUDA acceptance from CI.
