# Codex Current State

> First-entry handoff for `jorsamj/aixunlianpingtai`. Always verify the live branch/HEAD/diff before changing code. This file describes the intended current state, not a substitute for inspecting the repository.

## 1. Branch and release state

```text
stable main baseline:              6683edeb5d8391acbd96909ff22f72022105026b
current cleanup branch:            refactor/frontend-runtime-stabilization
current recorded cleanup HEAD:     512f5a59a9f35bbeba5339a12eee0ce2f0b5a360
formal VERSION.txt:                42.24.0 until v42.25 acceptance
frontend badge:                    v42.25.0-dev
frontend module entry cache:       main.mjs?v=42.25.25
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

## 6. Algorithm list performance owner

Current owner:

```text
static/modules/algorithm-list-runtime.js
```

Contracts now enforced:

```text
expand/collapse algorithm card
-> local state only
-> 0 algorithm/bootstrap requests

algorithm-page top refresh
-> GET algorithms
-> GET jobs
-> no bootstrap snapshot
-> preserve page shell and patch cards
```

Training task creation from the algorithm page also uses this focused algorithm/jobs refresh instead of `loadRelated()`.

Real Chrome request-count regression exists in:

```text
tests/browser/algorithm-list-performance.spec.mjs
```

## 7. Training task performance owner

Current owner:

```text
static/modules/training-task-runtime.js
```

It replaces legacy refresh ownership for the final `.train428-page`.

Current behavior:

```text
top Refresh / page Refresh / refreshJobsOnly
-> GET jobs only
-> patch final train428 tab counts + tbody
-> do not replace .train428-page
-> do not load datasets/materials/labels/algorithms/bootstrap
```

The following final task mutations are also focused:

```text
promote / pause / resume / stop / delete
-> mutation endpoint only
-> GET jobs
-> patch train428 table
```

No `loadRelated()` + whole-page render is required for these normal task operations.

Real Chrome regression verifies the DOM shell survives refresh and a real Pause action produces only `POST pause + GET jobs`.

## 8. Canonical training creation state

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

## 9. Training labels

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

## 10. Current frontend gates

Workflow:

```text
.github/workflows/frontend-runtime-stabilization.yml
```

At recorded HEAD `512f5a59...`, Node/syntax and real Chrome were green.

Current browser set includes:

```text
navigation-stability.spec.mjs
training-label-selector.spec.mjs
auto-label-polling.spec.mjs
algorithm-list-performance.spec.mjs
training-task-performance.spec.mjs
```

Always verify the latest HEAD checks again before claiming green.

## 11. Next work order

1. Dataset/material page performance: keep server paging but stop top refresh/current-page refresh from rebuilding the whole dataset shell when a card/grid patch is enough.
2. Continue deleting global render ownership only after named replacement modules have browser parity.
3. Finish direct train-v3 -> `TrainingDraftRuntime.update()` writes and eventually remove old training mirror variables.
4. Broad repository regression.
5. Real A800 short training acceptance (`device=0`, `batch=16`, `workers=4`, `cache=false`, fire+smoke -> `nc=2`).
6. Security hardening after functional acceptance.

## 12. Do not do yet

- do not rewrite the whole frontend to Vue before current P0 migration is stable;
- do not split Git repositories;
- do not add another numbered override layer;
- do not remove legacy code before replacement browser coverage exists;
- do not claim CUDA/production acceptance from frontend CI.

Read `docs/frontend-legacy-audit.md` for the remaining debt map and `docs/superpowers/specs/` for backend/data/runtime contracts.
