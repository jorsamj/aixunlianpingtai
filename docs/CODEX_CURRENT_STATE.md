# Codex Current State

> First-entry handoff for `jorsamj/aixunlianpingtai`. Always verify the live branch/HEAD/diff before changing code. This file describes the intended current state, not a substitute for inspecting the repository.

## 1. Branch and release state

```text
stable main baseline:              6683edeb5d8391acbd96909ff22f72022105026b
current cleanup branch:            refactor/frontend-runtime-stabilization
current recorded cleanup HEAD:     e38b72a4d93e1f56db633f540d68a160b83aa9d3
formal VERSION.txt:                42.24.0 until v42.25 acceptance
frontend badge:                    v42.25.0-dev
frontend module entry cache:       main.mjs?v=42.25.26
```

Do not merge the cleanup branch into `main` unless explicitly authorized.

## 2. Backend/runtime contracts already in main

Do not regress these contracts while cleaning the UI:

- SHA duplicate/leakage protection and Snapshot schema v3;
- `confirmed_empty` formal negatives; unannotated zero-box material is not a valid negative;
- task runtime lease/generation/process fencing and fenced artifacts;
- explicit training resources cannot be silently increased (`batch`, `workers`, `cache=false` semantics);
- task-scoped model label schema, first training never inherits mother-model classes;
- iteration inherits only the latest successful artifact-verified trainable version schema.

## 3. Current frontend migration shape

The browser is still a classic `static/app.js` application with a module stabilization layer. Do not pretend it is already a clean Vue application.

```text
static/app.js historical runtime
  -> static/main.mjs
       ├── NavigationStability
       ├── PageRequestScope
       ├── PollRegistry
       ├── AlgorithmListRuntime
       ├── TrainingTaskRuntime
       ├── MaterialPaginationRuntime61
       ├── TrainingDraftRuntime
       ├── TrainingSubmitRuntime
       ├── training-labels
       └── AutoLabelPollRuntime
```

New work must go into named modules. Do not create another `train430`, `train431`, etc.

## 4. Navigation / async ownership

`static/modules/navigation-stability.js` no longer uses a MutationObserver to call global `window.render()` as a repair mechanism.

Final owners currently guarded include final implementations such as:

```text
算法列表:          renderAlgorithms423 / renderAlg412
数据集:            renderDatasets424
训练任务:          renderTraining423 / renderTraining428 family
自动标注及清洗:    renderOps427
视频切帧:          renderVideo424 / refreshVideo424Delta
素材接入:          renderSources422 / refreshSources422
```

`PageRequestScope` scopes legacy same-origin `/api/*` GET/HEAD calls to the current page. POST/PUT/DELETE are not automatically cancelled.

Real Chrome regression proves a delayed old-page GET cannot repaint after navigating away.

## 5. Polling ownership

`static/modules/poll-registry.js` now owns creation/lifecycle for the important current high-frequency paths, not only cleanup:

```text
training-jobs     managed interval, 2s active / 5s idle
video-frames      v42.4 managed one-shot, 2s while active
sources           managed interval, 2.5s
auto-label-v60    managed one-shot, 1.8s while active
```

The final v42.4 video implementation is the accepted path. Old v33 video timers are compatibility cleanup only.

The old `auto422Timer` path belongs to a legacy page and should disappear with that page rather than receive new architecture work.

## 6. Incremental high-frequency pages — P0-C complete

### Algorithm list

Owner:

```text
static/modules/algorithm-list-runtime.js
```

Contracts:

```text
expand/collapse -> local state only -> 0 algorithm/bootstrap requests
page refresh    -> GET algorithms + GET jobs -> patch cards
training create -> focused algorithms/jobs refresh
```

The algorithm page shell is preserved.

### Training tasks

Owner:

```text
static/modules/training-task-runtime.js
```

Contracts:

```text
top/page refresh -> GET jobs only -> patch final train428 counts + tbody
promote/pause/resume/stop/delete -> mutation endpoint -> GET jobs -> patch
```

No normal training-task action uses `loadRelated()` + whole-page render.

Material-pool hydration may still happen in the background for training creation, but `MaterialPaginationRuntime61` is explicitly forbidden from globally repainting `.train428-page` after that hydration finishes.

### Datasets / materials

Owner:

```text
static/modules/material-pagination-runtime.js
window.MaterialPaginationRuntime61
```

The v61 server-paged data model remains authoritative.

Contracts:

```text
first dataset entry or structural toolbar change
-> build .data426-shell

page / search / label filter / source filter / top refresh
-> fetch /api/v61/.../materials
-> update current state/images/totals
-> patch #data412Grid + counts + pager + filter/source decorations
-> preserve .data426-shell
```

Structural changes such as switching processed/unprocessed tabs or entering/leaving delete mode may rebuild the shell because the toolbar itself changes.

Real Chrome regression verifies natural next-page navigation, search and top refresh all preserve the same `.data426-shell`, while top refresh does not request bootstrap, algorithms, datasets or legacy `/images`.

## 7. Canonical training creation state

Canonical frontend draft:

```text
state.trainingDraft
```

Owned by:

```text
static/modules/training-draft.js
static/modules/training-draft-runtime.js
static/modules/training-submit.js
```

The canonical draft owns exact material ids, independent test ids, split mode, experiment/validation percentages, inherited/new/effective labels, resource strategy/device/GPU/batch/workers/cache, config and queue priority.

Final `/train/start` frontend owner is `TrainingSubmitRuntime`. Duplicate submit is locked. Explicit false/zero values are preserved.

Legacy fields are compatibility mirrors only:

```text
state.train428AlgorithmId
state.train428Config
state.train429Selected
state.trainSplitV3
state.trainingLabelSelected
```

Current remaining P0-B work is to make final train-v3 controls write through `TrainingDraftRuntime.update()` directly, then remove compatibility mirrors only after browser parity.

## 8. Training labels

Active owner:

```text
static/modules/training-labels.js
```

Removed classic shims:

```text
static/training-label-bootstrap.js
static/training-label-v3-anchor.js
```

Labels come only from the exact selected materials plus inherited prior-version schema. The module does not own `/train/start`.

## 9. Current frontend gates

Workflow:

```text
.github/workflows/frontend-runtime-stabilization.yml
```

At recorded HEAD `e38b72a4...`, Node/syntax and real Chrome were green.

Current browser set includes:

```text
navigation-stability.spec.mjs
training-label-selector.spec.mjs
auto-label-polling.spec.mjs
algorithm-list-performance.spec.mjs
training-task-performance.spec.mjs
material-pagination-performance.spec.mjs
```

Always verify the latest HEAD checks again before claiming green.

## 10. Next work order

1. Finish direct train-v3 -> `TrainingDraftRuntime.update()` writes; reduce dependence on `train428/train429/trainSplitV3` compatibility state.
2. Remove old training mirror variables only after unit + real Chrome parity proves the named owner is complete.
3. Continue deleting global render ownership only after named replacement modules have browser parity.
4. Broad repository regression.
5. Real A800 short training acceptance (`device=0`, `batch=16`, `workers=4`, `cache=false`, fire+smoke -> `nc=2`).
6. Security hardening after functional acceptance.

## 11. Do not do yet

- do not rewrite the whole frontend to Vue before current P0 migration is stable;
- do not split Git repositories;
- do not add another numbered override layer;
- do not remove legacy code before replacement browser coverage exists;
- do not claim CUDA/production acceptance from frontend CI.

Read `docs/frontend-legacy-audit.md` for the remaining debt map and `docs/superpowers/specs/` for backend/data/runtime contracts.
