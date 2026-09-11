# Codex Current State

> First-entry handoff for `jorsamj/aixunlianpingtai`. Always verify live branch/HEAD/diff before editing. This file records intended current state; repository code remains the final authority.

## 1. Branch and release state

```text
current cleanup branch:                  refactor/frontend-runtime-stabilization
validated code HEAD before doc-only sync: d81f19552839210046cad53d6d201fd104c85987
formal VERSION.txt:                      42.24.0 until v42.25 acceptance
frontend badge:                          v42.25.0-dev
frontend module entry cache:             main.mjs?v=42.25.34
```

The handoff/documentation commits after the validated code HEAD are documentation-only; always inspect the live branch HEAD before editing.

Do not merge this branch into `main` unless explicitly authorized.

## 2. Non-regression backend contracts

Do not regress these while cleaning or preparing RC acceptance:

- SHA duplicate/leakage protection and Snapshot schema v3;
- `confirmed_empty` is the formal negative-sample contract; unannotated zero-box material is not a valid negative;
- task-runtime lease/generation/process fencing and fenced artifacts;
- explicit training resources cannot be silently increased (`batch`, `workers`, `cache=false` semantics);
- task-scoped label schema; first training never inherits mother-model classes;
- iteration inherits only the latest successful, artifact-verified, trainable version schema.

A dedicated release gate exists:

```text
.github/workflows/v42.25-release-regression.yml
```

Latest validated backend contract state:

```text
runtime-contracts         ✅
training-data-contracts   ✅
```

The runtime group covers repository/scheduler/process/fencing/GPU recovery/artifact fencing/conversion/training-resource contracts plus `task_worker.py --check`.
The training-data group covers label/negative/scope/split/component/Snapshot/portable-dataset/resource/launcher/worker-integration contracts.

## 3. Current frontend architecture

The browser is still a classic `static/app.js` application with a named module stabilization layer. Do not describe it as already migrated to Vue.

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

New work must go into named modules. Do not create `train430`, `train431`, or another numbered override layer.

## 4. Navigation / async ownership

`static/modules/navigation-stability.js` no longer uses a MutationObserver to trigger global `window.render()` as a repair mechanism.

`PageRequestScope` scopes same-origin `/api/*` GET/HEAD requests to the current page. POST/PUT/DELETE are not automatically cancelled.

Real Chrome regression proves delayed old-page GET responses cannot repaint after navigation.

## 5. Polling / incremental page ownership

Important current managed paths:

```text
training-jobs     2s active / 5s idle
video-frames      2s one-shot while active
sources           2.5s interval
auto-label-v60    1.8s one-shot while active
```

Named page owners already in place:

```text
Algorithms        static/modules/algorithm-list-runtime.js
Training tasks    static/modules/training-task-runtime.js
Datasets          static/modules/material-pagination-runtime.js
```

Routine refreshes patch local page regions and preserve page shells; they must not fall back to unrelated `loadRelated()` + whole-page repaint behavior.

### Training-task refresh race fix

`TrainingTaskRuntime` build is now:

```text
training-task-runtime-422503
```

Training-task polling/manual refresh behavior now has explicit request ownership:

- concurrent refreshes still share one in-flight request;
- a manual refresh immediately adjacent to a completed poll, or vice versa, is coalesced within a 120 ms cross-source dedupe window;
- mutation flows (`pause/resume/stop/delete/promote`) force a fresh `/jobs` GET after the mutation and never reuse the dedupe result;
- after manual refresh, the managed `PollRegistry` training timer is re-armed so the next periodic poll is not immediately stacked onto the click;
- the real Chrome performance gate still requires exactly one `/api/projects/{id}/jobs` GET per manual refresh; the test was not relaxed to permit duplicates.

`PollRegistry` training polling now calls the named `TrainingTaskRuntime.refresh({source: 'poll'})` path when available.

## 6. Canonical training creation state

Single canonical frontend source of truth:

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

Current builds/entries:

```text
training-draft-runtime-422507
training-draft-controls-422501
training-labels module-422506
training-task-runtime-422503
poll-registry import cache 422507
main.mjs?v=42.25.34
```

The canonical draft owns:

```text
algorithmId
baseVersionId
materialIds
testMaterialIds
splitMode
experimentPercent
validationPercent
inheritedLabelCodes
newLabelCodes
effectiveLabelCodes
resource
config
priority
```

Principal train-v3 interactions are canonical-first: algorithm start/switch, material confirmation, independent test material confirmation, split mode, label selection, experiment/validation percentage, priority, resource strategy/device/GPU policy, and training settings save/apply.

Final `/train/start` frontend owner is `TrainingSubmitRuntime`; stale request values are canonicalized before POST. Explicit `false`/`0` values must survive UI -> draft -> request unchanged.

## 7. Compatibility mirror retirement status

### Removed #1: `state.trainingLabelSelected`

Current behavior:

```text
label UI reads state.trainingDraft.newLabelCodes
label change -> TrainingDraftRuntime.update({newLabelCodes})
TrainingDraftRuntime does not mirror labels back to state.trainingLabelSelected
trainingDraftFromLegacyState does not import task labels from state.trainingLabelSelected
```

Real Chrome explicitly asserts throughout the creation/submission flow:

```text
Object.hasOwn(state, 'trainingLabelSelected') === false
```

### Removed #2: `state.trainSplitV3`

The final train-v3 split UI now derives its view directly from `state.trainingDraft`:

```text
trainingDraft.materialIds
trainingDraft.testMaterialIds
trainingDraft.splitMode
trainingDraft.experimentPercent
trainingDraft.validationPercent
```

Current behavior:

- final `static/app.js` train-v3 code has no `trainSplitV3` read/write;
- `TrainingDraftRuntime` no longer creates or mirrors `trainSplitV3`;
- the runtime deletes a stale `trainSplitV3` property if an already-loaded/legacy page still has one;
- the permanent frontend CI guard fails if `trainSplitV3` is reintroduced into `static/app.js`;
- real Chrome deliberately injects a stale/wrong `trainSplitV3` and proves the canonical UI and final `/train/start` request remain unchanged.

Remaining training compatibility mirrors:

```text
state.train428AlgorithmId
state.train428Config
state.train429Selected
```

Do not delete these wholesale. `train429Selected` in particular still has broad historical renderer/helper reads in `app.js`; treat it as later migration debt, not the next mandatory task.

## 8. Frontend gates

Workflow:

```text
.github/workflows/frontend-runtime-stabilization.yml
```

Validated at code HEAD `d81f19552839210046cad53d6d201fd104c85987`:

```text
frontend             ✅
browser-navigation   ✅
```

Current permanent frontend checks include:

- syntax check for named modules and `static/app.js`;
- retired-mirror guard preventing `trainSplitV3` from returning to active `app.js`;
- complete Node frontend unit suite;
- real Chrome runtime regressions.

Current real-Chrome suite includes:

```text
navigation-stability.spec.mjs
training-label-selector.spec.mjs
auto-label-polling.spec.mjs
algorithm-list-performance.spec.mjs
training-task-performance.spec.mjs
material-pagination-performance.spec.mjs
```

The latest Chrome gate covers both the second mirror retirement and the training `/jobs` refresh/poll race fix.

## 9. Next work order: move to A800 RC acceptance

The bounded frontend stabilization batch is complete enough to stop open-ended mirror cleanup. The next priority is real A800/CUDA RC acceptance, not another speculative frontend mirror deletion.

1. Deploy this branch to the existing A800 environment without merging `main`.
2. Run a short real training task with:

```text
device=0
batch=16
workers=4
cache=false
epochs=3-5
selected task labels=fire+smoke only
expected nc=2
```

3. Verify three layers agree on resources:

```text
requested batch=16 workers=4 cache=False
effective batch=16 workers=4 cache=False
Ultralytics actual batch=16 workers=4 cache=False
```

4. Inspect the task Snapshot and generated `data.yaml`; only intended task classes may appear.
5. Confirm `confirmed_empty` negatives generate zero-byte YOLO `.txt` files.
6. Run one iteration-training acceptance and prove it inherits only the latest successful trainable version/schema, not the mother model or a failed newer version.
7. Run Web + Worker stop/restart/lifecycle acceptance and verify queued/running task fencing remains correct.
8. Only after these pass, decide whether v42.25 is ready for formal release/security-hardening work.

`state.train429Selected` and the remaining classic render chain are still debt, but are no longer P0 blockers for this RC pass unless A800 acceptance exposes a concrete frontend defect.

## 10. Standard architecture target

Do not immediately split repositories or rewrite everything. Incremental target remains:

```text
Monorepo
  frontend/  -> Vue 3 + TypeScript + Vite + Pinia + Vue Router
  backend/   -> FastAPI API-only
  platform_core/
  workers/
  tests/
  docs/

Nginx
  /       -> frontend dist
  /api/*  -> FastAPI
```

API versions should eventually represent public API compatibility (for example `/api/v1`) rather than historical implementation generation numbers.

## 11. Do not do

- do not merge to `main` without explicit authorization;
- do not add another numbered frontend override generation;
- do not restore global `window.render()` repair loops;
- do not let polling repaint unrelated pages;
- do not weaken duplicate-request tests merely to hide polling races;
- do not rebuild train requests from project-wide labels;
- do not inherit mother-model classes on first training;
- do not remove multiple compatibility mirrors without unit + real Chrome proof;
- do not claim CUDA/A800 acceptance from browser/CI tests.

Read `docs/frontend-legacy-audit.md` for the remaining cleanup map and `docs/superpowers/specs/` for backend/data/runtime contracts.
