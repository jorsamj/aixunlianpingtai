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

One-shot migration workflows/helpers used for exact `app.js` retirement must be deleted after their migration and regression run succeed.

## 2. Established owners

### Navigation

`NavigationStability` owns navigation stabilization. Do not restore MutationObserver + global `window.render()` repair loops.

### Page request scope

`PageRequestScope` scopes same-origin `/api/*` GET/HEAD requests to the active page. New named runtimes should prefer explicit lifecycle/generation ownership over relying on quarantine behavior.

### Algorithms

Owner: `static/modules/algorithm-list-runtime.js`.

Routine expand/collapse is local; refresh is focused to algorithm/job data rather than global reload.

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

Owner: `static/modules/material-pagination-runtime.js`.
Routine operations patch the material grid/counts/pager rather than rebuilding unrelated page state.

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

Current key builds:

```text
TrainingDraftRuntime    training-draft-runtime-422509
TrainingSubmitRuntime   training-submit-422504
TrainingLabelRuntime    module-422507
TrainingTaskRuntime     training-task-runtime-422503
```

Final submit chain:

```text
train-v3 UI
→ state.trainingDraft
→ TrainingDraftRuntime
→ TrainingSubmitRuntime
→ POST /api/v12/projects/{project_id}/train/start
```

`TrainingSubmitRuntime` is the sole `/train/start` network owner.

### Physical retirement completed

The following historical owners have been physically removed from `static/app.js`:

1. final `renderSplit()` writer of submit-button `.disabled` based on legacy state;
2. `refreshProjected417()` writer of the same button state;
3. all three historical `window.submitTrain429=async function...` implementations and their direct legacy payload POST paths.

Do not restore them.

## 4. Mirror retirement status

Fully retired:

```text
state.trainingLabelSelected
state.trainSplitV3
```

Permanent tests reject reintroduction and Real Chrome intentionally injects stale values to prove canonical behavior remains unchanged.

Still present as migration debt:

```text
state.train429Selected
state.train428AlgorithmId
state.train428Config
```

Important distinction: these may still support historical UI/helpers, but **they are not allowed to own training submission**.

Retirement method:

```text
find remaining active read/write
→ identify named/canonical replacement
→ unit proof
→ Real Chrome proof
→ physical deletion of that legacy owner
```

Do not delete all three wholesale.

## 5. TrainingDraft compatibility debt

`TrainingDraftRuntime` is canonical-first and no longer mirrors the canonical draft back into `train428AlgorithmId/train428Config/train429Selected`.

It still has bounded compatibility behavior for final classic entrypoints:

```text
generic train-modal input/change/click synchronization
legacy bootstrap only when trainingDraft does not yet exist
wrappers around:
  startAlgorithmTraining429
  confirmTrainMaterialPickerV3
  setTrainSplitModeV3
  saveTrainSettings428
```

These wrappers remain debt. Remove only after each underlying final UI action writes canonical state directly and browser parity is proven.

## 6. TrainingLabel compatibility debt

`TrainingLabelRuntime` is canonical-first:

- when `trainingDraft.algorithmId` exists, current materials come from `trainingDraft.materialIds`;
- label selection writes `trainingDraft.newLabelCodes`;
- polluted `train429Selected/train428AlgorithmId` must not alter final label/request state.

Remaining compatibility machinery:

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

## 7. Polling/timer debt

Named `PollRegistry` paths already cover principal managed polling, but classic timers still need retirement proof.

High-value targets:

```text
auto422Timer
__videoFramePollTimer
prelabel legacy timer
old setupPagePolling
AutoLabel rebind timers
TrainingLabel rebind/refresh timers
```

A legacy timer is not considered closed merely because another runtime later clears it. If a named runtime owns the feature, obsolete timer creation should be physically removed.

## 8. Global render/override debt

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

Create and maintain a final owner table before deletion. Delete one classic owner only after its replacement has unit + real-browser parity.

Do not use another override layer to hide an old override.

## 9. Global reload/request debt

Scan remaining paths for unnecessary cross-domain reloads:

```text
loadAll()
loadRelated()
loadCore412()
render()
```

A local mutation should use the narrowest authoritative API/runtime refresh possible. Already-optimized algorithm list, training-task, and material-page behavior must not regress.

## 10. Observer/wrapper lifecycle audit

Perform a zero-point scan for:

```text
MutationObserver
setInterval
setTimeout
window.fetch =
render =
window.setPage =
```

For every surviving instance document:

```text
creator
final owner
creation condition
cleanup/destroy point
cross-page behavior
whether still required
```

If there is no owner or cleanup contract, it is unresolved debt.

## 11. Cache-busting debt

Current resource versions are not unified. At the latest validated runtime point:

```text
styles.css / material-pagination bootstrap: legacy 42.24.0-style cache versions
app.js: 42.25.36
main.mjs: 42.25.38
```

This can produce mixed browser runtime versions. Design one cache/build version source and migrate all static entry resources to it.

## 12. Regression gates

Frontend workflow:

```text
.github/workflows/frontend-runtime-stabilization.yml
```

Latest validated runtime point:

```text
2f858dabdeb4766a1283e3601c1ed25d7b6cc512
run 34590904476: success
```

Coverage includes syntax checks, retired mirror guards, all frontend unit tests, and Real Chrome runtime regressions.

The training Chrome test deliberately corrupts legacy mirrors and requires canonical submit to continue working. Do not weaken it.

Release/backend gate remains:

```text
.github/workflows/v42.25-release-regression.yml
```

## 13. Current cleanup order

```text
1. migrate train429Selected / train428AlgorithmId / train428Config active owners
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

## 14. Non-negotiable rules

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
