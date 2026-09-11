# Frontend Legacy Runtime Audit

> Branch: `refactor/frontend-runtime-stabilization`
>
> Purpose: establish the authoritative cleanup map for the current browser runtime before Vue/TypeScript migration. Update it as each legacy layer is retired.

## 1. Current diagnosis

The frontend is not suffering from one isolated slow API. The main structural issue is cumulative runtime layering:

```text
static/app.js original global runtime
  -> later IIFE overrides
  -> version-suffixed page functions (4xx series)
  -> durable train-v3 override
  -> static/main.mjs module bootstrap
  -> navigation-stability wrappers
  -> training-label classic bootstrap
  -> training-label v3 anchor
```

Consequences observed in production/browser use:

- page changes can be overwritten by late async work from the previous page;
- polling can trigger expensive full-page redraws;
- opening training has multiple historical implementations and state shapes;
- modal DOM is shared globally and multiple layers patch it;
- MutationObserver-based compatibility code can self-trigger;
- the same user action may pass through classic globals plus ES-module wrappers;
- UI state is duplicated across historical version variables.

The target is **one implementation owner per concern**, not another compatibility layer.

## 2. Confirmed legacy structures

### 2.1 Root router/render is global and full-page

At the start of `static/app.js`:

```js
function setPage(p){state.page=p;render()} window.setPage=setPage;
function render(){
  renderNav();
  renderTop();
  renderSummary();
  (...)();
}
```

This means every page navigation starts from an application-wide render path instead of a page lifecycle.

### 2.2 `render` is overridden later

Later compatibility layers capture and replace the root renderer, e.g.:

```js
const finalRender=render;
render=function(){
  if(state.page==='素材存储配置'){
    renderNav();renderTop();renderSummary();renderStorageSources61();return;
  }
  finalRender();
};
```

This proves the final runtime behavior is not represented by the first `render()` definition alone.

### 2.3 Dataset rendering has multiple generations

Current code includes versioned dataset renderers such as:

```text
renderDatasets
renderDatasets424
renderData429Cards
```

and later wrappers replace `window.renderDatasets424` again for storage-source behavior.

Risk:

- a dataset refresh can execute an older renderer;
- local filters and selected state can be replaced during a later wrapper render;
- full `#view.innerHTML` replacement destroys DOM-local state.

### 2.4 Training UI has multiple generations

Current runtime still contains historical training naming/state, including:

```text
train425...
train428...
train429...
train-v3
```

The durable v3 layer explicitly wraps the prior training entry:

```js
const previousStart=window.startAlgorithmTraining429;
```

Current state also spans multiple generations:

```text
state.train428AlgorithmId
state.train428Config
state.train429Selected
state.trainSplitV3
state.trainMaterialPickerV3
state.trainingLabelSelected
```

This is a primary source of regressions because display state and submit state can come from different generations.

### 2.5 `main.mjs` is a second runtime layer

`static/main.mjs` installs modules on top of classic `app.js`, including:

```text
negative-samples
training-labels
material pagination
material batch runtime
resource discovery
navigation stability
page request scope
poll registry
```

The migration target is to move authority from global classic functions to explicit modules, but during migration **a feature must not have two active owners**.

### 2.6 Previous navigation repair was itself a performance risk

The first v42.25 `navigation-stability.js` observed the entire `#view`. If stale async work existed, any DOM mutation could trigger a global `window.render()` repair.

That behavior has been removed on this branch. Current behavior:

- navigation epoch is still tracked;
- known page renderers are guarded by page ownership;
- stale page DOM is no longer repaired by a global `window.render()`;
- known page polling is removed from the old page lifecycle;
- current page navigation coordinates RequestScope and PollRegistry.

### 2.7 Page RequestScope is now active

`static/modules/page-request-scope.js` is installed by `static/main.mjs` and wraps the existing final `window.fetch` chain.

Current migration contract:

- same-origin `/api/*` GET/HEAD requests are attached to the active page AbortController;
- navigation aborts the previous page controller;
- a GET invalidated by navigation is quarantined so legacy `safe()`/catch blocks do not display a false request-failure toast and the stale continuation cannot mutate DOM/state;
- POST/PUT/DELETE are not automatically cancelled by page navigation;
- explicit caller-provided `signal` remains authoritative.

The quarantine of legacy stale GET continuations is a migration bridge, not the final API-client design. Once page modules use an explicit ApiClient, aborted calls should return typed cancellation rather than relying on legacy suspension.

### 2.8 PollRegistry has started absorbing legacy page timers

`static/modules/poll-registry.js` now owns lifecycle cleanup for known page polling slots:

```text
state.jobPollTimer
state.source422Timer
state.auto422Timer
window.__videoFramePollTimer
window.__prelabelPollTimer
```

Current phase adopts timers created by legacy code and guarantees they are cleared when their owner page is left. Next phase will move timer creation itself into PollRegistry so page modules stop calling `setInterval` directly.

## 3. Target runtime architecture

During the non-Vue stabilization phase:

```text
BrowserRuntime
├── Router
├── PageScope / AbortController
├── PollRegistry
├── ModalManager
├── RenderOwnership
└── ApiClient
```

Rules:

1. `state.page` may only change through Router.
2. Leaving a page aborts its outstanding read requests.
3. Leaving a page destroys its polling registrations.
4. A page renderer may only write while that page owns the active scope.
5. Polling updates local rows/cards only; no periodic whole-page render.
6. Modal open/close does not re-render the owner page unless data actually changed.
7. New code may not add another numbered override generation.

## 4. Planned consolidation order

### P0-A — Runtime stabilization

Status:

```text
DONE      remove MutationObserver/global-render repair
DONE      page renderer ownership guards
DONE      page GET RequestScope / AbortController migration bridge
DONE      centralized legacy PollRegistry adoption/leave cleanup
NEXT      migrate timer creation into PollRegistry
NEXT      browser stress test with delayed API responses
```

### P0-B — Training consolidation

Replace historical training state with one draft object:

```js
trainingDraft = {
  algorithmId,
  baseVersionId,
  materialIds,
  inheritedLabels,
  newLabelCodes,
  experiment,
  resource,
  config,
  priority
};
```

Target components before Vue migration:

```text
TrainingDialog
TrainingMaterialPicker
TrainingLabelSelector
TrainingConfigDialog
```

After browser parity is verified, retire old training entry points instead of keeping wrappers indefinitely.

### P0-C — High-frequency page incremental rendering

Order:

1. Algorithms
2. Training Tasks
3. Datasets / Materials

For these pages, background updates must patch only changed records/status fields.

### P1 — Standard frontend project

Create `frontend/` with:

```text
Vue 3
TypeScript
Vite
Pinia
Vue Router
```

Migrate page-by-page. A migrated page replaces its classic owner; it must not remain permanently dual-run.

### P1 — Backend boundary

Move toward one public API contract under `/api/v1`. Software release numbers must not become API path versions.

FastAPI should gradually become API-only in production; Nginx serves frontend build output separately.

## 5. Deletion criteria for historical code

A historical implementation may be removed only after:

1. replacement behavior exists;
2. unit/frontend tests pass;
3. real browser test covers the migrated user flow;
4. repository search confirms no live caller depends on the old entry;
5. current-state handoff is updated.

Do not keep inactive 425/428/429 compatibility layers forever. Deprecation without deletion is not considered completion.

## 6. Current branch status

Current stabilization implementation lives in:

```text
static/modules/navigation-stability.js
static/modules/page-request-scope.js
static/modules/poll-registry.js
static/main.mjs
```

Tests:

```text
tests/frontend/navigation-stability.test.mjs
tests/frontend/page-request-scope.test.mjs
tests/frontend/poll-registry.test.mjs
```

CI workflow:

```text
.github/workflows/frontend-runtime-stabilization.yml
```

The full frontend Node suite is intentionally run here, not only the newly-added tests, so stale historical test contracts are exposed during stabilization.

Next implementation target:

```text
move high-frequency polling creation and row updates into PollRegistry/page-local renderers,
then start TrainingDialog state consolidation.
```
