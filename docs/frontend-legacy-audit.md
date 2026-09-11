# Frontend Legacy Runtime Audit

> Branch: `refactor/frontend-runtime-stabilization`  
> Purpose: cleanup map for the classic frontend before any later framework replacement.  
> Current work order is **technical-debt closure first**, not A800 acceptance.  
> For status precedence, read `docs/TECH_DEBT_CLOSURE_V42_25.md` first.

## 1. Runtime shape

The frontend is still `static/app.js` plus named stabilization modules:

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

No new numbered override generation (`train430`, etc.) is allowed.

One-shot migration helpers/workflows must be removed after the guarded migration and regression pass. The canonical training migration helper/workflow has already been deleted.

## 2. Established owners

### Navigation
`NavigationStability` owns navigation stabilization. Do not restore MutationObserver + global `window.render()` repair loops.

### Page requests
`PageRequestScope` scopes same-origin `/api/*` GET/HEAD work to the active page. Named runtimes should still prefer explicit lifecycle/generation ownership.

### Algorithms
Owner: `static/modules/algorithm-list-runtime.js`.

### Training tasks
Owner: `static/modules/training-task-runtime.js`, build `training-task-runtime-422503`.

Contract:

```text
concurrent refresh                → one inflight request
poll → manual within 120ms        → reuse fresh result
manual → poll within 120ms        → reuse fresh result
mutation → refresh                → force fresh GET
manual refresh completion         → re-arm managed poll timer
```

Real Chrome requires exactly one `/jobs` GET per manual refresh.

### Datasets/materials
Owner: `static/modules/material-pagination-runtime.js`. Routine operations patch only the relevant material UI rather than rebuilding unrelated page state.

## 3. Canonical training ownership

Canonical state:

```text
state.trainingDraft
```

Principal modules:

```text
static/modules/training-draft.js
static/modules/training-draft-runtime.js
static/modules/training-draft-controls.js
static/modules/training-submit.js
static/modules/training-labels.js
```

Current identifiers:

```text
app.js cache                      42.25.43
main.mjs cache                    42.25.40
training-draft import             422506
TrainingDraftRuntime import       422511
TrainingDraftRuntime build        training-draft-runtime-422511
TrainingLabelRuntime import       422508
TrainingSubmitRuntime             training-submit-422504
TrainingTaskRuntime               training-task-runtime-422503
```

Final submit chain:

```text
train-v3 UI
→ state.trainingDraft
→ TrainingDraftRuntime
→ TrainingSubmitRuntime
→ POST /api/v12/projects/{project_id}/train/start
```

`TrainingSubmitRuntime` is the sole `/train/start` network owner. Permanent CI rejects direct `/train/start` ownership in `static/app.js`.

## 4. Five training mirrors are retired

Fully retired from active `static/app.js` **and** the core training modules:

```text
state.trainingLabelSelected
state.trainSplitV3
state.train429Selected
state.train428AlgorithmId
state.train428Config
```

Permanent CI rejects reintroduction in:

```text
static/app.js
static/modules/training-draft.js
static/modules/training-draft-runtime.js
static/modules/training-labels.js
```

Tests may deliberately use old field names as stale/pollution fixtures. Product runtimes must ignore these fields and must not use, update, delete, or bootstrap from them.

### `train429Selected` replacement

```text
TrainingDraftRuntime.materialIds()
TrainingDraftRuntime.setMaterialIds(ids)
TrainingDraftRuntime.toggleMaterialId(id)
→ state.trainingDraft.materialIds
```

This owns picker selected state, toggle, select-all/invert, summary count, label aggregation, quality checks and projected split counts.

### `train428AlgorithmId` / `train428Config` replacement

```text
algorithm → state.trainingDraft.algorithmId
config    → state.trainingDraft.config
resource  → state.trainingDraft.resource
```

They no longer have an active fallback role in TrainingDraft/TrainingLabel modules.

## 5. Legacy training bootstrap is retired

`trainingDraftFromLegacyState` has been physically removed.

Missing canonical state now follows:

```text
no state.trainingDraft
→ createTrainingDraft()
→ empty canonical draft
→ live/current controls may update it
```

It does **not** follow:

```text
no state.trainingDraft
→ recover train428AlgorithmId / train429Selected / train428Config
```

Do not restore `trainingDraftFromLegacyState`, `bootstrapFromLegacy`, or equivalent compatibility recovery.

## 6. TrainingDraft wrapper debt still exists

Mirror retirement does not mean `TrainingDraftRuntime` is wrapper-free.

Current wrapper owner: `wrapLegacyMutation()` in `training-draft-runtime.js`.

Wrapped classic functions:

```text
startAlgorithmTraining429
confirmTrainMaterialPickerV3
setTrainSplitModeV3
saveTrainSettings428
```

Behavior today:

```text
classic action invoked
→ wrapper derives canonical patch
→ TrainingDraftRuntime.update()
→ original classic callback runs
→ TrainingDraftRuntime.sync()
```

`destroy()` restores originals. This is explicit technical debt. The next cleanup pass should prove each underlying final classic function writes canonical state directly, then remove the wrapper branch instead of adding another compatibility layer.

## 7. TrainingLabel lifecycle debt still exists

`TrainingLabelRuntime` is canonical for data selection:

- current v3 materials come from `trainingDraft.materialIds`;
- label selection writes `trainingDraft.newLabelCodes`;
- it no longer falls back to `train429Selected` / `train428AlgorithmId`.

Remaining lifecycle machinery:

```text
wrapped entrypoints:
  startAlgorithmTraining429
  startAlgorithmTraining423
  openTrain428
  openTrain425
  refreshTrain429
  refreshTrain428
  trainCounts425

post-entrypoint refresh timers:
  0 / 40 / 120 / 350 / 700 ms

rebind timers:
  100 / 400 / 1000 / 2500 ms

modal MutationObserver
```

These are cleanup targets, not final architecture.

## 8. Physically retired training owners

Already removed from active classic code:

1. historical submit-button disabled writers;
2. all classic direct `/train/start` implementations;
3. v3 resource controls' `train428Config` double writers;
4. final 429 start/target/engine writes to `train428AlgorithmId/train428Config`;
5. all active `train429Selected` readers/writers;
6. old 428 unreachable training create block;
7. `trainingDraftFromLegacyState` compatibility adapter.

Do not restore them.

## 9. Polling/timer debt

Named `PollRegistry` paths cover principal managed polling, but classic timers still need physical retirement proof.

Targets:

```text
auto422Timer
__videoFramePollTimer
prelabel legacy timer
old setupPagePolling
AutoLabel rebind timers
TrainingLabel rebind/refresh timers
```

A timer is not closed merely because another runtime later clears it.

## 10. Global render/override debt

`static/app.js` still contains historical override layers such as:

```text
render = ...
window.setPage = ...
renderXXX412
renderXXX417
renderXXX423
renderXXX428
renderXXX429
```

Maintain a final-owner table before deletion. Delete only after replacement has unit + browser parity. Never add a newer override layer to hide an older one.

## 11. Global reload/request debt

Scan remaining paths:

```text
loadAll()
loadRelated()
loadCore412()
render()
```

A local mutation should use the narrowest authoritative refresh possible. Algorithm-list, training-task and material optimizations must not regress.

## 12. Observer/wrapper lifecycle audit

Zero-point scan targets:

```text
MutationObserver
setInterval
setTimeout
window.fetch =
render =
window.setPage =
```

For every surviving instance record creator, final owner, creation condition, destroy point and cross-page behavior.

## 13. Cache-busting debt

Current versions are intentionally documented:

```text
styles.css / material-pagination bootstrap: 42.24.0-style versions
app.js:                                  42.25.43
main.mjs:                                42.25.40
training-draft.js:                       422506
training-draft-runtime.js:               422511
training-labels.js:                      422508
```

These are still not unified and can cause mixed runtime versions if future changes forget outer/nested bumps.

## 14. Regression gates

Frontend workflow:

```text
.github/workflows/frontend-runtime-stabilization.yml
```

Latest full acceptance:

```text
commit f3bae76de68b14b0a2799119de62a9b8ac13acaa
run    34595909062
syntax + permanent guards + full frontend unit + Real Chrome: PASS
```

The Chrome training test verifies canonical UI state, stale mirror isolation, sole network ownership and actual submit payload.

Release/backend gate remains `.github/workflows/v42.25-release-regression.yml`.

## 15. Current cleanup order

```text
1. retire TrainingDraftRuntime classic wrappers one by one after direct-owner proof
2. retire TrainingLabelRuntime wrappers/rebind timers/refresh timers/MutationObserver
3. retire old timer/polling owners
4. establish renderer/setPage final-owner table and remove obsolete overrides
5. reduce app.js proven dead code
6. eliminate global reload/duplicate-request debt
7. unify cache-busting
8. zero-point observer/timer/fetch/render/setPage scan
9. migrate numbered business names toward semantic names
10. deterministic-test cleanup + docs sync
11. technical-debt zero-point scan
12. resume A800 RC
```

## 16. Non-negotiable rules

1. No new numbered compatibility generation.
2. No global render-repair loop.
3. No page polling that repaints unrelated pages.
4. No local action that needlessly reloads unrelated domains.
5. No project-wide label catalog as task label truth source.
6. No mother-model class inheritance on first training.
7. No retired training mirror may regain truth-source or bootstrap ownership.
8. No `trainingDraftFromLegacyState` replacement under a new name.
9. No historical deletion without final-owner proof.
10. Explicit `false` / `0` resource values must survive UI → draft → request.
11. Do not weaken performance/ownership tests to hide races.
12. Frontend/CI acceptance does not replace A800/CUDA acceptance.
13. A800 remains deferred until the technical-debt ledger permits it.
