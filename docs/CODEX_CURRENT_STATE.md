# Codex Current State

> First-entry handoff for `jorsamj/aixunlianpingtai`. Always verify the live branch/HEAD/diff before changing code. This file describes the intended current state, not a substitute for inspecting the repository.

## 1. Branch and release state

```text
stable main baseline:                 6683edeb5d8391acbd96909ff22f72022105026b
current cleanup branch:               refactor/frontend-runtime-stabilization
latest validated functional milestone: d3a5f61cc0262f6add97e6d18f3042476ad372c6
formal VERSION.txt:                   42.24.0 until v42.25 acceptance
frontend badge:                       v42.25.0-dev
frontend module entry cache:          main.mjs?v=42.25.30
```

Later documentation/CI-only commits may exist after the recorded functional milestone. Verify the branch HEAD before editing.

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
       ├── TrainingDraftControlsRuntime
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

`static/modules/poll-registry.js` owns creation/lifecycle for the important current high-frequency paths:

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

Current build:

```text
material-pagination-runtime-422205
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

The old install-time 250ms material bootstrap is now conditional: once the dataset shell + current filter signature have committed, the delayed bootstrap must not reset the cursor. This fixes the real race where a user could click Next and then be pushed back to page 1 by a late bootstrap request.

Real Chrome regression verifies natural next-page navigation, the delayed-bootstrap window, search and top refresh while preserving the same `.data426-shell`. Top refresh does not request bootstrap, algorithms, datasets or legacy `/images`.

## 7. Canonical training creation state — P0-B canonical-first milestone

Canonical frontend draft:

```text
state.trainingDraft
```

Owned by:

```text
static/modules/training-draft.js
static/modules/training-draft-runtime.js
static/modules/training-draft-controls.js
static/modules/training-submit.js
```

Current runtime builds:

```text
training-draft-runtime-422504
training-draft-controls-422500
```

The canonical draft owns exact material ids, independent test ids, split mode, experiment/validation percentages, inherited/new/effective labels, resource strategy/device/GPU/batch/workers/cache, config and queue priority.

The principal final train-v3 interactions are now canonical-first:

```text
open/switch training algorithm
confirm training/independent-test materials
switch split mode
label selection
experiment percentage
validation percentage
queue priority
resource strategy
training device
GPU policy
training settings apply/save
```

These write `TrainingDraftRuntime.update(...)` before or directly from the active control path. Historical state is mirrored for legacy rendering instead of being authoritative.

Training settings direct-write includes advanced values and protects explicit resource semantics. Real Chrome currently covers:

```text
epochs=30
batch=16
workers=4
cache=false
optimizer=AdamW
resource_strategy=manual
device=cpu in browser fixture
gpu_policy=exclusive
```

The browser test verifies canonical draft, compatibility mirror, stale-manual-POST canonicalization and the final user-facing submit all carry the same values.

Final `/train/start` frontend owner is `TrainingSubmitRuntime`. Duplicate submit is locked. Explicit false/zero values are preserved.

Legacy fields still exist only as compatibility mirrors:

```text
state.train428AlgorithmId
state.train428Config
state.train429Selected
state.trainSplitV3
state.trainingLabelSelected
```

Do not delete them wholesale yet. The next P0-B step is reducing generic legacy event sampling/sync and removing individual mirrors only after unit + real Chrome parity proves no current renderer still depends on them.

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

Labels come only from the exact selected materials plus inherited prior-version schema. Label changes already write canonical `newLabelCodes` through `TrainingDraftRuntime.update()`.

The module does not own `/train/start`.

## 9. Current frontend gates

Workflow:

```text
.github/workflows/frontend-runtime-stabilization.yml
```

At functional milestone `d3a5f61c...`, Node/syntax and real Chrome were green. A following CI-only commit adds explicit `node --check` for `training-draft-controls.js`; verify the latest branch HEAD checks before claiming green.

Current browser set includes:

```text
navigation-stability.spec.mjs
training-label-selector.spec.mjs
auto-label-polling.spec.mjs
algorithm-list-performance.spec.mjs
training-task-performance.spec.mjs
material-pagination-performance.spec.mjs
```

## 10. Next work order

1. Reduce generic `TrainingDraftRuntime.sync()` event sampling for train-v3 controls already owned by `TrainingDraftControlsRuntime`; keep sync only as a migration/final guard where legacy async initialization still requires it.
2. Remove individual training compatibility mirrors only after renderer/browser parity proves they are no longer read by the active UI.
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
