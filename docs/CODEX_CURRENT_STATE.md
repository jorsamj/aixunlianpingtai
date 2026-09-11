# Codex Current State

> First-entry handoff for `jorsamj/aixunlianpingtai`. Always verify live branch/HEAD/diff before editing. This file records intended current state; repository code remains the final authority.

## 1. Branch and release state

```text
current cleanup branch:                refactor/frontend-runtime-stabilization
current HEAD when this handoff updated: 035edf9399c8567656b48e5283229e599ab85aea
formal VERSION.txt:                    42.24.0 until v42.25 acceptance
frontend badge:                        v42.25.0-dev
frontend module entry cache:           main.mjs?v=42.25.32
```

Do not merge this branch into `main` unless explicitly authorized.

## 2. Non-regression backend contracts

Do not regress these while cleaning the frontend:

- SHA duplicate/leakage protection and Snapshot schema v3;
- `confirmed_empty` is the formal negative-sample contract; unannotated zero-box material is not a valid negative;
- task-runtime lease/generation/process fencing and fenced artifacts;
- explicit training resources cannot be silently increased (`batch`, `workers`, `cache=false` semantics);
- task-scoped label schema; first training never inherits mother-model classes;
- iteration inherits only the latest successful, artifact-verified, trainable version schema.

A dedicated release gate now exists:

```text
.github/workflows/v42.25-release-regression.yml
```

At HEAD `035edf93...` both groups are green:

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
training-draft-runtime-422506
training-draft-controls-422501
training-labels module-422506
main.mjs?v=42.25.32
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

## 7. First compatibility mirror has been removed

`state.trainingLabelSelected` is no longer a compatibility mirror.

Current behavior:

```text
label UI reads state.trainingDraft.newLabelCodes
label change -> TrainingDraftRuntime.update({newLabelCodes})
TrainingDraftRuntime no longer mirrors labels back to state.trainingLabelSelected
trainingDraftFromLegacyState no longer imports task labels from state.trainingLabelSelected
```

Real Chrome `training-label-selector.spec.mjs` explicitly asserts throughout the creation/submission flow:

```text
Object.hasOwn(state, 'trainingLabelSelected') === false
```

It also validates material selection, label deselection, settings, stale-manual-POST canonicalization, and the final user-facing submit.

Remaining training compatibility mirrors:

```text
state.train428AlgorithmId
state.train428Config
state.train429Selected
state.trainSplitV3
```

Do not delete these wholesale. `app.js` still has active/final renderer reads for parts of this state.

## 8. Frontend gates

Workflow:

```text
.github/workflows/frontend-runtime-stabilization.yml
```

At HEAD `035edf93...` both are green:

```text
frontend             ✅
browser-navigation   ✅
```

Current real-Chrome suite includes:

```text
navigation-stability.spec.mjs
training-label-selector.spec.mjs
auto-label-polling.spec.mjs
algorithm-list-performance.spec.mjs
training-task-performance.spec.mjs
material-pagination-performance.spec.mjs
```

## 9. Next work order

1. Continue P0-B mirror retirement one field/read-path at a time. Prefer migrating final train-v3 reads to `state.trainingDraft` before deleting any mirror.
2. Highest-priority candidates are `train429Selected` / `trainSplitV3`, but only after identifying the exact final renderer reads and proving browser parity.
3. Do not spend unlimited time on frontend debt: after another bounded mirror cleanup batch, prepare A800 RC acceptance.
4. A800 short training target: `device=0`, `batch=16`, `workers=4`, `cache=false`, 3–5 epochs, fire+smoke only, expected `nc=2`.
5. Verify Snapshot/data.yaml only contain intended task classes and `confirmed_empty` produces zero-byte YOLO label files.
6. Run one iteration-training acceptance and restart/lifecycle acceptance for Web + Worker.
7. Security hardening follows functional acceptance.

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
- do not rebuild train requests from project-wide labels;
- do not inherit mother-model classes on first training;
- do not remove multiple compatibility mirrors without unit + real Chrome proof;
- do not claim CUDA/A800 acceptance from browser/CI tests.

Read `docs/frontend-legacy-audit.md` for the remaining cleanup map and `docs/superpowers/specs/` for backend/data/runtime contracts.
