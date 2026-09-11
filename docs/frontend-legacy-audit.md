# Frontend Legacy Runtime Audit

> Branch: `refactor/frontend-runtime-stabilization`
>
> Purpose: authoritative cleanup map for the classic frontend before the later Vue/TypeScript migration.

## 1. Runtime shape

The frontend is still `static/app.js` plus a named module stabilization layer:

```text
static/app.js historical/versioned overrides
  -> static/main.mjs
       ├── NavigationStability
       ├── PageRequestScope
       ├── PollRegistry
       ├── AlgorithmListRuntime
       ├── TrainingTaskRuntime
       ├── MaterialPaginationRuntime61
       ├── TrainingDraftRuntime
       ├── TrainingDraftControlsRuntime
       ├── TrainingSubmitRuntime
       ├── training-labels
       └── AutoLabelPollRuntime
```

Removed compatibility shims:

```text
static/training-label-bootstrap.js
static/training-label-v3-anchor.js
```

No new numbered override generation is allowed.

## 2. Runtime lifecycle contracts

### Navigation ownership

`static/modules/navigation-stability.js` no longer relies on MutationObserver + global `window.render()` repair behavior. Delayed old-page renderers must not repaint the active page.

### Page RequestScope

Legacy same-origin `/api/*` GET/HEAD requests are scoped to the current page. New named runtimes should prefer explicit lifecycle/generation fencing instead of depending on legacy quarantine behavior.

### PollRegistry

Current principal managed paths:

```text
training-jobs     2s active / 5s idle
video-frames      2s one-shot while active
sources           2.5s interval
auto-label-v60    1.8s one-shot while active
```

Remaining old timer fields are cleanup debt, not a reason to add more wrappers.

Training jobs now use the named `TrainingTaskRuntime.refresh({source: 'poll'})` path when available. Manual refresh and periodic poll requests are source-aware so adjacent cross-source refreshes can be coalesced without weakening mutation freshness.

## 3. Incremental page owners already established

### Algorithms

Owner: `static/modules/algorithm-list-runtime.js`

```text
expand/collapse -> local only
refresh         -> algorithms + jobs only
training create -> focused algorithms/jobs refresh
```

### Training tasks

Owner: `static/modules/training-task-runtime.js`

Current build:

```text
training-task-runtime-422503
```

```text
refresh/action -> jobs-focused API -> patch counts + tbody
```

The final `.train428-page` node is preserved during routine refresh/actions.

The runtime now handles the historical manual-refresh/poll race explicitly:

```text
concurrent refresh                -> share inflight request
poll -> manual within 120 ms      -> reuse fresh jobs result
manual -> poll within 120 ms      -> reuse fresh jobs result
mutation -> refresh               -> force fresh GET
manual refresh completion         -> re-arm managed poll timer
```

Real Chrome continues to require exactly one `/api/projects/{id}/jobs` GET per manual refresh. This was fixed in runtime behavior rather than by relaxing the test.

### Datasets / materials

Owner: `static/modules/material-pagination-runtime.js`

Current build: `material-pagination-runtime-422205`.

Server-paged v61 material APIs remain authoritative. Routine page/search/filter/source/refresh operations patch only the data grid/counts/pager/decorations and preserve `.data426-shell`. Structural tab/delete-mode changes may rebuild the shell.

Real Chrome covers natural pagination, delayed bootstrap, search, top refresh, and shell preservation.

## 4. Canonical training state

Canonical source of truth:

```text
state.trainingDraft
```

Owned by:

```text
static/modules/training-draft.js
static/modules/training-draft-runtime.js
static/modules/training-draft-controls.js
static/modules/training-submit.js
static/modules/training-labels.js
```

Current builds:

```text
training-draft-runtime-422507
training-draft-controls-422501
training-labels module-422506
training-task-runtime-422503
poll-registry import cache 422507
main.mjs?v=42.25.34
```

Principal train-v3 mutations already write canonical state first/directly:

```text
start/switch algorithm
confirm exact training materials
confirm independent test materials
switch split mode
select/unselect task labels
experiment percentage
validation percentage
queue priority
resource strategy
device
GPU policy
training configuration save/apply
```

`TrainingSubmitRuntime` owns final `/train/start`; stale legacy values are canonicalized before submission.

## 5. Mirror removal progress

### Removed #1: `state.trainingLabelSelected`

Current label contract:

```text
trainingDraft.newLabelCodes -> source of truth
label UI -> TrainingDraftRuntime.update({newLabelCodes})
no mirror write to trainingLabelSelected
no legacy import from trainingLabelSelected
```

Real Chrome explicitly verifies the property is absent during label selection and final submission:

```text
Object.hasOwn(state, 'trainingLabelSelected') === false
```

### Removed #2: `state.trainSplitV3`

Final train-v3 split presentation and mutations now derive from canonical draft fields:

```text
trainingDraft.materialIds
trainingDraft.testMaterialIds
trainingDraft.splitMode
trainingDraft.experimentPercent
trainingDraft.validationPercent
```

Current contract:

```text
no trainSplitV3 read/write in final static/app.js train-v3 path
TrainingDraftRuntime does not recreate the mirror
stale trainSplitV3 property is deleted by TrainingDraftRuntime
CI rejects reintroduction of trainSplitV3 into static/app.js
```

Real Chrome injects a deliberately incorrect stale `trainSplitV3` and verifies it cannot alter current split UI or final training request.

### Remaining compatibility mirrors

```text
state.train428AlgorithmId
state.train428Config
state.train429Selected
```

`train429Selected` still has broad reads across historical v412/v414/v415/v417/v429 helper/render paths. It is not safe to delete wholesale and is no longer a P0 blocker for the next A800 RC acceptance pass.

## 6. Generic TrainingDraft sync debt

`TrainingDraftRuntime` still contains compatibility synchronization for historical UI paths:

```text
generic input/change/click sampling
settling sync after selected legacy entrypoints
mirrorDraftToLegacy()
```

The six direct train-v3 controls already bypass generic sampling through `TrainingDraftControlsRuntime`:

```text
trV3Experiment
trV3Validation
tr429Priority
trV3ResourceStrategy
trV3Device
trV3GpuPolicy
```

Future cleanup rule remains:

```text
active final renderer read
-> migrate that read to trainingDraft
-> keep temporary compatibility only where a real renderer still needs it
-> unit proof
-> real Chrome proof
-> remove one mirror
```

Do not create another override module just to hide an old read.

For now this cleanup is intentionally bounded: do not continue mirror retirement merely because debt exists. Resume only for a concrete defect or as a separately scoped frontend migration phase.

## 7. Regression gates

Frontend workflow:

```text
.github/workflows/frontend-runtime-stabilization.yml
```

Validated code HEAD before documentation-only sync:

```text
d81f19552839210046cad53d6d201fd104c85987
```

Latest validated result:

```text
frontend             ✅
browser-navigation   ✅
```

Permanent frontend coverage now includes:

```text
static/app.js syntax check
trainSplitV3 retired-mirror guard
all tests/frontend/*.test.mjs
real Chrome runtime suite
```

Real Chrome suite includes:

```text
navigation-stability.spec.mjs
training-label-selector.spec.mjs
auto-label-polling.spec.mjs
algorithm-list-performance.spec.mjs
training-task-performance.spec.mjs
material-pagination-performance.spec.mjs
```

The current Chrome gate validates both canonical training split behavior and single-request training-task manual refresh behavior.

Release/backend regression workflow:

```text
.github/workflows/v42.25-release-regression.yml
```

Latest validated result:

```text
runtime-contracts         ✅
training-data-contracts   ✅
```

## 8. Remaining high-value debt

### Deferred training mirrors

Remaining:

```text
train429Selected
train428Config
train428AlgorithmId
```

`train429Selected` is the most visible remaining material mirror, but its dependency surface is broad. Do not remove it as a drive-by cleanup before RC acceptance.

### Global render chain cleanup

`app.js` still contains historical `render=function(){...}` / `window.setPage` override layers. Delete a classic owner only after a named replacement module has unit + real-browser parity.

### Standard frontend project

After v42.25 functional acceptance, migrate page-by-page toward:

```text
frontend/
  Vue 3
  TypeScript
  Vite
  Pinia
  Vue Router
```

This should be replacement, not a permanent classic+Vue dual runtime.

## 9. Next priority: A800 RC acceptance

The bounded frontend runtime/mirror cleanup batch is complete. Move to real A800 acceptance:

```text
device=0
batch=16
workers=4
cache=false
epochs=3-5
labels=fire+smoke
expected nc=2
```

Acceptance must verify:

1. requested/effective/actual resources all preserve `16 / 4 / false`;
2. task Snapshot and generated `data.yaml` contain only intended task classes;
3. `confirmed_empty` generates zero-byte YOLO label files;
4. one iteration training starts from the latest successful trainable version/schema only;
5. Web/Worker restart lifecycle preserves queue/process fencing behavior.

Frontend/CI success does not count as CUDA/A800 acceptance.

## 10. Non-negotiable rules

1. No new numbered compatibility generation.
2. No global `window.render()` repair loop.
3. No page polling that repaints unrelated pages.
4. No routine action that loads unrelated domains when a focused API exists.
5. No training request built from the project-wide label catalog.
6. No mother-model class inheritance on first training.
7. No independent mutation of legacy training state without canonical synchronization.
8. Do not delete historical code until replacement behavior has unit and real-browser coverage.
9. Explicit `false` / `0` resource values must survive UI -> draft -> request unchanged.
10. Do not weaken performance tests to conceal duplicate polling/request behavior.
11. Frontend/CI acceptance does not replace A800/CUDA acceptance.
