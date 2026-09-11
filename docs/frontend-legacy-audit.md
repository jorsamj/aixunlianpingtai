# Frontend Legacy Runtime Audit

> Branch: `refactor/frontend-runtime-stabilization`
>
> Purpose: one authoritative cleanup map while the classic frontend is stabilized before any Vue/TypeScript migration.

## 1. Runtime shape

The frontend is still `static/app.js` plus a named module stabilization layer.

```text
static/app.js historical/versioned overrides
  -> static/main.mjs
       ├── NavigationStability
       ├── PageRequestScope
       ├── PollRegistry
       ├── AlgorithmListRuntime
       ├── TrainingTaskRuntime
       ├── TrainingDraftRuntime
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

Current page ownership is guarded by `static/modules/navigation-stability.js`.

The final renderer names, not only historical aliases, are registered. Important examples:

```text
renderAlg412
renderDatasets424
renderOps427
renderVideo424
refreshVideo424Delta
refreshJobsOnly
```

A renderer owned by another page must not repaint the active page.

### Page RequestScope

Legacy same-origin `/api/*` GET/HEAD requests are scoped to the current page and quarantined after navigation. Mutations are not automatically cancelled.

New named runtimes should prefer their own finite lifecycle/generation fencing instead of depending on the legacy never-resolve quarantine.

### PollRegistry

Timer creation is now directly managed for the principal current paths:

```text
training-jobs     interval, 2s active / 5s idle
video-frames      v42.4 one-shot, 2s while active
sources           interval, 2.5s
auto-label-v60    one-shot, 1.8s while active
```

Remaining legacy timer fields are compatibility cleanup, not a reason to add more polling wrappers.

## 3. Algorithm list debt status

Final classic renderer is v42.12 `renderAlg412` / `renderAlgorithms423`.

Historical bug:

```text
expand algorithm
-> GET all algorithms
-> rerender all algorithm cards
```

Replacement owner:

```text
static/modules/algorithm-list-runtime.js
```

Current contract:

```text
expand/collapse -> local only, no algorithm/bootstrap request
refresh -> algorithms + jobs only
refresh -> patch cards, preserve page shell
training-create success -> focused algorithms/jobs refresh
```

Later v42.14 algorithm create/edit/delete was already incremental and does not need another replacement layer.

## 4. Training task debt status

Final visible classic task page is the v42.8 `.train428-page` path.

Historical refresh/action pattern:

```text
loadRelated()
-> datasets/images/labels/algorithms/publish/test data
-> renderTraining423()
-> replace page DOM
```

Replacement owner:

```text
static/modules/training-task-runtime.js
```

Current contract:

```text
refresh -> GET jobs only -> patch tab counts + tbody
promote -> POST promote -> GET jobs -> patch
pause   -> POST pause   -> GET jobs -> patch
resume  -> POST resume  -> GET jobs -> patch
stop    -> POST stop    -> GET jobs -> patch
delete  -> optional stop + DELETE -> GET jobs -> patch
```

The final `.train428-page` node is preserved during normal refresh/action operations.

## 5. Auto-label / video / source polling status

### Auto-label

`static/modules/auto-label-poll-runtime.js` owns current v60 task polling. While active it uses a managed 1.8 second one-shot and patches only the task rows.

### Video

Final owner path is v42.4 `renderVideo424 / refreshVideo424Delta`, not old v33. Polling is a managed 2 second one-shot only while a task is active and delta refresh patches rows.

### Source/import

`source422Timer` creation is replaced by a PollRegistry-managed 2.5 second interval. Refresh remains table-local.

## 6. Canonical training state

Canonical source of truth:

```text
state.trainingDraft
```

Owned by:

```text
training-draft.js
training-draft-runtime.js
training-submit.js
```

Compatibility mirrors still present in `app.js`:

```text
state.train428Config
state.train429Selected
state.trainSplitV3
state.trainingLabelSelected
state.train428AlgorithmId
```

They must not regain authority. Do not add `train430`, `train431`, etc.

Training label owner is `static/modules/training-labels.js`. Training POST owner is `TrainingSubmitRuntime`.

## 7. Remaining high-value debt

### P0-A Dataset/material page

The v61 server-paged material path is already the correct data shape, but `loadMaterialPage61()` still calls `renderPagedDataset61()`, which can rebuild the dataset shell through the historical base renderer.

Next target:

```text
server page fetch
-> update state.images/page totals
-> patch cards + counts + pager + controls
-> preserve dataset shell when it already exists
```

Also intercept top-level Refresh on `数据集` so it does not fall back to `loadCore412() + extras412() + render()`.

### P0-B Training mirror removal

Continue moving final train-v3 control writes directly through `TrainingDraftRuntime.update()`. Remove old state fields only after browser parity.

### P0-C Global render chain

`app.js` still contains many historical `render=function(){...}` and `window.setPage` override layers. Do not delete them wholesale. A classic owner can be removed only after its replacement named module has unit + real-browser parity.

### P1 Standard frontend project

After P0 stabilization:

```text
frontend/
  Vue 3
  TypeScript
  Vite
  Pinia
  Vue Router
```

Migration must be page-by-page replacement, not permanent dual-run.

## 8. Regression gates

Workflow:

```text
.github/workflows/frontend-runtime-stabilization.yml
```

Current gates cover:

```text
node --check named runtime modules
node --test tests/frontend/*.test.mjs
Playwright Chrome:
  navigation-stability.spec.mjs
  training-label-selector.spec.mjs
  auto-label-polling.spec.mjs
  algorithm-list-performance.spec.mjs
  training-task-performance.spec.mjs
```

The current recorded milestone (`512f5a59...`) passed Node and real Chrome. Always confirm latest HEAD checks before claiming green.

## 9. Non-negotiable rules

1. No new numbered compatibility generation.
2. No global `window.render()` repair loop.
3. No page polling that repaints unrelated pages.
4. No routine page action that loads unrelated domains when a focused API exists.
5. No training request built from the project-wide label catalog.
6. No mother-model class inheritance on first training.
7. No independent mutation of legacy training state without canonical draft synchronization.
8. Do not delete historical code until replacement behavior has unit and real-browser coverage.
9. Frontend CI does not replace A800/CUDA acceptance.
