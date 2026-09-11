# Frontend Legacy Runtime Audit

> Branch: `refactor/frontend-runtime-stabilization`
>
> Purpose: keep one authoritative cleanup map while the existing browser UI is stabilized before any Vue/TypeScript migration.

## 1. Current runtime shape

The remaining frontend is still a legacy global runtime, but the most dangerous duplicate ownership has started to be removed.

```text
static/app.js
  -> historical IIFE/versioned overrides
  -> final train-v3 UI
  -> static/main.mjs
       ├── Navigation Ownership
       ├── Page RequestScope / AbortController
       ├── PollRegistry
       ├── TrainingDraftRuntime
       └── module training-labels
```

The following classic training-label compatibility layers have been retired and removed:

```text
static/training-label-bootstrap.js     REMOVED
static/training-label-v3-anchor.js     REMOVED
```

`static/modules/training-labels.js` now understands the final `.train-v3-summary` directly. It no longer owns `/train/start` submission. Training submission has one frontend owner: `TrainingDraftRuntime`.

## 2. Runtime contracts already enforced

### 2.1 Navigation ownership

A page that is no longer active must not repaint `#view` after an awaited request completes.

Implemented by:

```text
static/modules/navigation-stability.js
```

A real Chrome regression deliberately delays an old page request, navigates away, then releases the old request. The current page must remain unchanged.

### 2.2 Page RequestScope

Same-origin `/api/*` GET/HEAD requests belong to the active page scope.

On navigation:

- the previous page AbortController is aborted;
- stale read continuations are quarantined during the legacy migration phase;
- POST/PUT/DELETE are not automatically cancelled.

Implemented by:

```text
static/modules/page-request-scope.js
```

### 2.3 PollRegistry

Known page-owned polling timers are centrally destroyed when their page is left.

Current adopted legacy slots include:

```text
state.jobPollTimer
state.source422Timer
state.auto422Timer
window.__videoFramePollTimer
window.__prelabelPollTimer
```

Implemented by:

```text
static/modules/poll-registry.js
```

Current limitation: some legacy code still creates timers directly. The registry guarantees cleanup, but timer creation itself still needs to migrate into the registry.

### 2.4 Canonical TrainingDraft

The canonical training draft is:

```text
state.trainingDraft
```

Model:

```js
{
  algorithmId,
  baseVersionId,
  materialIds,
  testMaterialIds,
  splitMode,
  experimentPercent,
  validationPercent,
  inheritedLabelCodes,
  newLabelCodes,
  effectiveLabelCodes,
  inheritancePending,
  resource: {
    strategy,
    device,
    gpuPolicy,
    batch,
    workers,
    cache
  },
  config,
  priority
}
```

Implemented by:

```text
static/modules/training-draft.js
static/modules/training-draft-runtime.js
```

The runtime currently:

- reads final train-v3 DOM values for experiment/validation percentages, priority and resource controls;
- canonicalizes exact selected material ids and labels;
- mirrors the canonical result back into historical state only for compatibility;
- rejects iteration fallback when versions exist but none is successful/trainable;
- canonicalizes the final `/api/v12/projects/{project}/train/start` payload.

Real Chrome regression verifies that stale ids/labels/percentages in a manually constructed payload are replaced by the values visible in the current training UI.

### 2.5 Training labels have one UI owner

Current label UI owner:

```text
static/modules/training-labels.js
```

Responsibilities:

- derive selectable labels only from exact selected training materials;
- show previous successful/trainable version labels as inherited and immutable;
- never inherit mother-model classes on first training;
- write selected new labels into TrainingDraft;
- render directly next to the final train-v3 summary.

It does **not** wrap `/train/start` anymore. Backend label contract remains authoritative after the frontend canonical draft is submitted.

## 3. Historical training state: compatibility mirrors only

The following variables still exist because final train-v3 in `static/app.js` reads/writes them:

```text
state.train428Config
state.train429Selected
state.trainSplitV3
state.trainingLabelSelected
state.train428AlgorithmId
```

They are no longer allowed to become independent sources of truth.

Current direction:

```text
UI action
  -> TrainingDraftRuntime.update()
  -> state.trainingDraft
  -> compatibility mirror to old fields
```

Do not introduce another `train430`, `train431`, etc. New training behavior must move toward named modules rather than another numbered override generation.

## 4. Next cleanup order

### P0-A — finish runtime lifecycle migration

```text
DONE  stale renderer ownership guard
DONE  Page RequestScope
DONE  legacy timer leave-page cleanup
DONE  real Chrome stale-navigation regression
NEXT  move timer creation itself into PollRegistry
```

### P0-B — finish training state consolidation

```text
DONE  canonical TrainingDraft model
DONE  live train-v3 DOM -> TrainingDraft
DONE  exact material ids / labels -> TrainingDraft
DONE  one frontend /train/start owner
DONE  remove classic training-label shims
NEXT  make train-v3 controls call TrainingDraftRuntime.update() directly
NEXT  stop constructing training payload from legacy state in app.js
NEXT  delete train428/train429/trainSplitV3 compatibility fields after browser parity
```

Target named modules:

```text
TrainingDialog
TrainingMaterialPicker
TrainingLabelSelector
TrainingConfig
TrainingSubmit
```

### P0-C — incremental rendering

Priority:

1. Training Tasks
2. Algorithms
3. Datasets / Materials

Polling/background refresh must patch only changed records/status fields. It must not periodically replace the whole page DOM.

### P1 — standard frontend project

Only after P0 behavior is stable:

```text
frontend/
  Vue 3
  TypeScript
  Vite
  Pinia
  Vue Router
```

A migrated page must replace its classic implementation. Permanent dual-run is not acceptable.

## 5. Non-negotiable rules

1. No new numbered compatibility generation for new work.
2. No global `window.render()` repair loop.
3. No page polling that repaints unrelated pages.
4. No training request built from project-wide label catalog.
5. No mother-model class inheritance on first training.
6. No independent mutation of old training state without synchronizing the canonical draft.
7. Do not delete historical code until replacement behavior has unit tests and real-browser coverage.

## 6. Current regression gates

Frontend CI workflow:

```text
.github/workflows/frontend-runtime-stabilization.yml
```

It runs:

```text
node --check
node --test tests/frontend/*.test.mjs
Playwright Chrome:
  tests/browser/navigation-stability.spec.mjs
  tests/browser/training-label-selector.spec.mjs
```

Before merging this branch, also run the broader repository regression and the A800 real training acceptance path. Frontend browser green does not replace real CUDA/Ultralytics validation.
