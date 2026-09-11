# Frontend Legacy Runtime Audit

> Branch: `refactor/frontend-runtime-stabilization`  
> Purpose: cleanup map for the classic frontend before later Vue/TypeScript replacement.  
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

Removed compatibility shims already include:

```text
static/training-label-bootstrap.js
static/training-label-v3-anchor.js
```

One-shot migration workflows/helpers used for exact `app.js` retirement must be deleted after migration + regression success.

## 2. Established owners

### Navigation
`NavigationStability` owns navigation stabilization. Do not restore MutationObserver + global `window.render()` repair loops.

### Page request scope
`PageRequestScope` scopes same-origin `/api/*` GET/HEAD requests to the active page. New named runtimes should prefer explicit lifecycle/generation ownership over relying on quarantine behavior.

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
Owner: `static/modules/material-pagination-runtime.js`. Routine operations patch the material grid/counts/pager rather than rebuilding unrelated page state.

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

Current key runtime/cache identifiers:

```text
TrainingDraftRuntime import   422510
TrainingSubmitRuntime         training-submit-422504
TrainingLabelRuntime          module-422507
TrainingTaskRuntime           training-task-runtime-422503
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

## 4. Mirror retirement status

Fully retired from active `static/app.js`:

```text
state.trainingLabelSelected
state.trainSplitV3
state.train429Selected
```

Permanent CI rejects reintroduction.

### `train429Selected` replacement

The active v3 picker is now canonical-only:

```text
TrainingDraftRuntime.materialIds()
TrainingDraftRuntime.setMaterialIds(ids)
TrainingDraftRuntime.toggleMaterialId(id)
→ state.trainingDraft.materialIds
```

This owns picker selected-state, toggle, select-all/invert, summary count, label aggregation, quality checks, projected split counts and wrapper reset behavior. Full acceptance: commit `f45f88f8f64a71a1adaa68e359b6f193297fb6a1`, Frontend Runtime run `34594071998`, Node + Real Chrome green.

Tests may still deliberately mention `train429Selected` as a stale compatibility fixture; such fixtures are not active UI owners.

Still present as migration debt:

```text
state.train428AlgorithmId
state.train428Config
```

Important distinction: these may still support historical 428 settings/helpers, but **they are not allowed to own training submission**. Final 429 start/target/engine writers have already been migrated to canonical state.

Retirement method:

```text
find remaining active read/write
→ classify compatibility fallback vs unreachable historical block
→ migrate active fallback
→ unit proof
→ Real Chrome proof
→ physical deletion of dead owner
```

Do not wholesale-delete all 428 code.

## 5. TrainingDraft compatibility debt

`TrainingDraftRuntime` is canonical-first and no longer mirrors canonical state back into the retired material mirror.

It still has bounded compatibility behavior for final classic entrypoints and bootstrap when `trainingDraft` does not yet exist. These wrappers remain debt. Remove only after each underlying final UI action writes canonical state directly and browser parity is proven.

## 6. TrainingLabel compatibility debt

`TrainingLabelRuntime` is canonical-first:

- current materials come from `trainingDraft.materialIds`;
- label selection writes `trainingDraft.newLabelCodes`;
- polluted legacy values must not alter final label/request state.

Remaining compatibility machinery includes:

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

These are explicit cleanup targets, not final architecture.

## 7. Physically retired training owners

Already removed from `static/app.js`:

1. final `renderSplit()` submit-button legacy disabled writer;
2. `refreshProjected417()` submit-button legacy disabled writer;
3. all historical direct `/train/start` functions (3 × `submitTrain429` plus 9 earlier implementations);
4. final v3 resource controls' `train428Config` double writers;
5. final 429 start/target/engine active mirror writers;
6. all active `train429Selected` readers/writers.

Do not restore them.

## 8. Polling/timer debt

Named `PollRegistry` paths cover principal managed polling, but classic timers still need retirement proof.

High-value targets:

```text
auto422Timer
__videoFramePollTimer
prelabel legacy timer
old setupPagePolling
AutoLabel rebind timers
TrainingLabel rebind/refresh timers
```

A legacy timer is not considered closed merely because another runtime later clears it. Obsolete timer creation must be physically removed.

## 9. Global render/override debt

`static/app.js` still contains multiple historical override layers such as:

```text
render = ...
window.setPage = ...
renderXXX412
renderXXX417
renderXXX423
renderXXX428
renderXXX429
```

Create/maintain a final owner table before deletion. Delete a classic owner only after replacement has unit + real-browser parity. Do not add another override layer to hide an old override.

## 10. Global reload/request debt

Scan remaining paths for unnecessary cross-domain reloads:

```text
loadAll()
loadRelated()
loadCore412()
render()
```

A local mutation should use the narrowest authoritative API/runtime refresh possible. Already-optimized algorithm list, training-task and material behavior must not regress.

## 11. Observer/wrapper lifecycle audit

Perform a zero-point scan for:

```text
MutationObserver
setInterval
setTimeout
window.fetch =
render =
window.setPage =
```

For every surviving instance document creator, final owner, creation condition, cleanup/destroy point, cross-page behavior, and whether it is still required.

## 12. Cache-busting debt

Current resource versions are not unified:

```text
styles.css / material-pagination bootstrap: 42.24.0-style cache versions
app.js: 42.25.42
main.mjs: 42.25.39
TrainingDraftRuntime import: 422510
```

This can still produce mixed browser runtime versions. Design one cache/build version source and migrate all static entry resources to it.

## 13. Regression gates

Frontend workflow:

```text
.github/workflows/frontend-runtime-stabilization.yml
```

Latest full acceptance point:

```text
f45f88f8f64a71a1adaa68e359b6f193297fb6a1
run 34594071998: frontend success + Real Chrome success
```

Coverage includes syntax checks, permanent retired-mirror guard (`trainSplitV3`, `trainingLabelSelected`, `train429Selected`), canonical network-owner guard, frontend unit tests and Real Chrome runtime regressions.

Release/backend gate remains `.github/workflows/v42.25-release-regression.yml`.

## 14. Current cleanup order

```text
1. finish train428AlgorithmId / train428Config compatibility + old 428 settings/UI cleanup
2. retire TrainingDraft/TrainingLabel compatibility wrappers where proven obsolete
3. retire old timer/polling owners
4. establish renderer/setPage owner table and remove obsolete override layers
5. reduce app.js proven dead code
6. eliminate global reload/duplicate-request debt
7. unify cache-busting
8. zero-point observer/timer/fetch/render/setPage scan
9. migrate numbered business names toward semantic names
10. deterministic-test cleanup + docs sync
11. technical-debt zero-point scan
12. resume A800 RC
```

## 15. Non-negotiable rules

1. No new numbered compatibility generation.
2. No global render-repair loop.
3. No page polling that repaints unrelated pages.
4. No local action that needlessly reloads unrelated domains.
5. No training request built from project-wide labels.
6. No mother-model class inheritance on first training.
7. No legacy training mirror may regain submit ownership.
8. No historical code deletion without replacement proof.
9. Explicit `false` / `0` resource values must survive UI → draft → request.
10. Do not weaken performance/ownership tests to hide races.
11. Frontend/CI acceptance does not replace A800/CUDA acceptance.
12. A800 remains deferred until the technical-debt ledger allows it.
