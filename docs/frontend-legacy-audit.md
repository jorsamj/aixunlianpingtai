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

```text
refresh/action -> jobs-focused API -> patch counts + tbody
```

The final `.train428-page` node is preserved during routine refresh/actions.

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
training-draft-runtime-422506
training-draft-controls-422501
training-labels module-422506
main.mjs?v=42.25.32
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

### Removed: `state.trainingLabelSelected`

This is the first compatibility mirror fully retired.

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

### Remaining compatibility mirrors

```text
state.train428AlgorithmId
state.train428Config
state.train429Selected
state.trainSplitV3
```

These remain because active/final `app.js` render paths still read them. Do not delete them in one patch.

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

Next cleanup rule:

```text
active final renderer read
-> migrate that read to trainingDraft
-> keep temporary compatibility only where a real renderer still needs it
-> unit proof
-> real Chrome proof
-> remove one mirror
```

Do not create another override module just to hide an old read.

## 7. Regression gates

Frontend workflow:

```text
.github/workflows/frontend-runtime-stabilization.yml
```

Latest validated result after label-mirror removal:

```text
frontend             ✅
browser-navigation   ✅
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

Release/backend regression workflow:

```text
.github/workflows/v42.25-release-regression.yml
```

Latest validated result:

```text
runtime-contracts         ✅
training-data-contracts   ✅
```

The first workflow attempt failed before pytest because the CI image's FastAPI/Starlette TestClient required `httpx2`; the workflow dependency was corrected. The subsequent real contract run is green.

## 8. Remaining high-value debt

### P0-B training mirror retirement

Highest-value next candidates:

```text
train429Selected
trainSplitV3
```

But they are not safe for direct deletion yet. First identify final train-v3 reads in `app.js`, migrate those reads to canonical draft, and add browser assertions proving stale mirror mutation cannot change the current UI/request.

`train428Config` and `train428AlgorithmId` have broader historical dependency surfaces and should be later unless a narrow read path is isolated.

### P0-C global render chain cleanup

`app.js` still contains historical `render=function(){...}` / `window.setPage` override layers. Delete a classic owner only after a named replacement module has unit + real-browser parity.

### P1 standard frontend project

After P0 stabilization, migrate page-by-page toward:

```text
frontend/
  Vue 3
  TypeScript
  Vite
  Pinia
  Vue Router
```

This should be replacement, not a permanent classic+Vue dual runtime.

## 9. A800 acceptance after bounded frontend cleanup

Do not let mirror cleanup become open-ended. After another bounded migration batch, move to real A800 RC acceptance:

```text
device=0
batch=16
workers=4
cache=false
epochs=3-5
labels=fire+smoke
expected nc=2
```

Verify Snapshot/data.yaml label schema, zero-byte YOLO labels for `confirmed_empty`, one successful iteration training, and Web/Worker restart lifecycle.

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
10. Frontend/CI acceptance does not replace A800/CUDA acceptance.
