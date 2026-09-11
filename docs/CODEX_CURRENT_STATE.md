# Codex Current State

> First-entry handoff for `jorsamj/aixunlianpingtai`. Verify live branch/HEAD before editing. `docs/TECH_DEBT_CLOSURE_V42_25.md` is the authoritative debt ledger.

## 1. Branch / release state

```text
branch:                      refactor/frontend-runtime-stabilization
latest full code acceptance: 05abf71d067d4b1e08a2bdeeb9d7787e9fc06dd4
Frontend Runtime run:        34655960701
formal VERSION.txt:          42.24.0
frontend badge:              v42.25.0-dev
app.js cache:                42.25.57
main.mjs cache:              42.25.59
NavigationStability:         422511
UI state runtime:            422500
PollRegistry:                422511
TrainingDraftRuntime:        422516
TrainingLabelRuntime:        422513
TrainingSubmitRuntime:       training-submit-422504
TrainingTaskRuntime:         training-task-runtime-422503
AutoLabelPollRuntime:        422501
```

Run `34655960701` passed syntax, permanent navigation/owner guards, all frontend unit tests and Real Chrome runtime regressions. Do not merge `main`, bump `VERSION.txt`, tag or release without explicit user approval.

## 2. Current priority

```text
render override owner audit / obsolete generation deletion
→ app.js/global reload/request debt
→ cache-busting unification
→ zero-point lifecycle scan
→ A800 RC
```

Read in order:

```text
docs/TECH_DEBT_CLOSURE_V42_25.md
docs/CODEX_CURRENT_STATE.md
docs/frontend-legacy-audit.md
docs/FRONTEND_OWNER_MAP_V42_25.md
```

## 3. Closed frontend ownership

### Training

```text
state.trainingDraft
→ TrainingDraftRuntime
→ TrainingSubmitRuntime
→ /train/start
```

Retired mirrors: `trainingLabelSelected`, `trainSplitV3`, `train429Selected`, `train428AlgorithmId`, `train428Config`, `trainingDraftFromLegacyState`.

### Polling

```text
training-jobs → PollRegistry + TrainingTaskRuntime
AutoLabel      → AutoLabelPollRuntime + PollRegistry
video          → PollRegistry(video-frames)
sources        → PollRegistry(sources)
```

Legacy timers/shells/wrappers/adoption compatibility are retired.

### Navigation

All classic `setPage` owners are physically retired and permanently guarded, including:

```text
set423Base / setBase424
V37 duplicate baseSetPage
oldSetV39 / oldSet42 / set422Base
v34/v35/v42.4 direct setPage owners
v42.7 direct auto-label alias owner
setPageReady414
baseSetPage417
initial bootstrap function setPage(p){state.page=p;render()} / window.setPage=setPage
```

Final owner:

```text
NavigationStability
  normalizeNavigationPage()
  PageRequestScope / epoch
  PollRegistry before/after
  waitForNavigationReady()
  beforeInvokeNavigation()
  performNavigation(page)
  persistNavigationState()
```

`main.mjs` provides:

```js
performNavigation: page => {
  state.page = page;
  render();
}
```

When `performNavigation` exists, classic predecessor is bypassed. Unit tests prove classic call count 0 / named apply 1 / render 1. Runtime also installs `window.setPage` when no predecessor exists.

Accepted evidence:

```text
sidebar owner retired         f6e71c05... / 34653776200
named actual-owner equivalence 04b6982e... / 34655575856
bootstrap owner retired       05abf71d... / 34655960701
```

## 4. Current navigation contracts

Permanent CI forbids any `window.setPage=` assignment in `static/app.js` and requires named alias/readiness/sidebar/apply owners.

Real Chrome verifies:
- inline menu navigation;
- programmatic `window.setPage`;
- startup readiness;
- stale request fencing;
- PollRegistry stop-on-leave;
- sidebar/backdrop close;
- alias canonicalization;
- page persistence/reload restoration.

Do not weaken these tests.

## 5. Current exact target: render owner family

`render()` is still a classic global shell and has multiple historical capture/override generations. Known debt includes the v42.7 render-level alias fallback:

```js
render=function(){
  if(state.page==='自动标注') state.page='自动标注及清洗';
  ...
}
```

This fallback no longer owns navigation alias semantics because `NavigationStability` canonicalizes before `performNavigation`, but it may still be reached by direct startup/refresh `render()` calls. Therefore do not delete it until liveness and semantic equivalence are proven.

Audit targets:

```text
render = ... / const oldRender = render capture chain
renderXXX412 / 417 / 423 / 424 / 425 / 427 / 428 / 429
NavigationStability PAGE_RENDERERS wrapping
startup __clInit direct render()
refresh handlers that call render() directly
```

Required sequence for each deletion batch:

```text
live HEAD
→ enumerate exact assignment/capture topology
→ identify final live owner and dead generations
→ behavior contract
→ named/bounded semantic owner where needed
→ double-owner proof if semantics move
→ physical deletion
→ permanent guard
→ full frontend + Real Chrome
→ docs sync
```

## 6. Non-regression backend contracts

- snapshot schema v3 and duplicate/leakage protection;
- `confirmed_empty` negative-sample semantics;
- task-runtime lease/generation/process fencing;
- explicit `batch`, `workers`, `cache=false` end-to-end;
- first training uses task-scoped labels only;
- no mother-model class inheritance on first training;
- iteration inherits only latest successful artifact-verified trainable version;
- metrics SQLite connections close deterministically;
- trial/test images sent to model without GT leakage.

## 7. Work order

```text
1. render override owner audit / obsolete generation deletion
2. proven dead app.js + global reload/request debt
3. cache-busting unification
4. zero-point MutationObserver/timer/fetch/render/setPage scan
5. semantic naming + deterministic tests + docs
6. technical-debt zero-point scan
7. resume A800 RC
```

## 8. A800 status

**DEFERRED** until current P0/P1 technical debt is closed. Frontend CI is not CUDA/A800 acceptance.
