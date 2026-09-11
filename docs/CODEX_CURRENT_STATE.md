# Codex Current State

> First-entry handoff for `jorsamj/aixunlianpingtai`. Verify live branch/HEAD before editing. `docs/TECH_DEBT_CLOSURE_V42_25.md` is the authoritative debt ledger.

## 1. Branch / release state

```text
branch:                      refactor/frontend-runtime-stabilization
latest full code acceptance: 58ece59e95722437069c7e03277363197e564136
Frontend Runtime run:        34659775870
formal VERSION.txt:          42.24.0
frontend badge:              v42.25.0-dev
app.js cache:                42.25.61
main.mjs cache:              42.25.64
NavigationStability:         422511
UI state runtime:            422500
PollRegistry:                422511
TrainingDraftRuntime:        422516
TrainingLabelRuntime:        422513
TrainingSubmitRuntime:       training-submit-422504
TrainingTaskRuntime:         training-task-runtime-422503
AutoLabelPollRuntime:        422501
```

Run `34659775870` passed syntax, permanent owner guards, all frontend unit tests and Real Chrome runtime regressions. Do not merge `main`, bump `VERSION.txt`, tag or release without explicit user approval.

## 2. Current priority

```text
remaining render override owner audit / obsolete generation deletion
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

All classic `setPage` owners are physically retired. Final owner:

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

`main.mjs` provides exactly one actual page mutation/render owner:

```js
performNavigation: page => {
  state.page = page;
  render();
}
```

Permanent CI forbids any `window.setPage=` assignment in `static/app.js`.

## 4. Render debt already closed

### Route alias state mutation

Historical render code used to mutate:

```text
自动标注 → 自动标注及清洗
```

That behavior is now split correctly:
- navigation request alias → `NavigationStability.normalizeNavigationPage()`;
- historical localStorage restore → v34 restore-boundary canonicalization + canonical writeback;
- render itself no longer mutates route state.

A new cold-start Chrome contract exposed the old persistence bug first (`582b913e... / 34656484008`: 12 pass, 1 fail), then the fix passed at `e35a29b0... / 34656747269`.

### Fully shadowed render layers physically retired

```text
oldRender429
  algorithm/data branches fully shadowed by oldRender412

previousRender61
  素材存储配置 branch fully shadowed by finalRender

render423Base
  算法列表 branch fully shadowed by oldRender412
  训练任务 branch fully shadowed by renderBase428
```

Accepted points:

```text
oldRender429      0455eeef696f19457b0f1a2b79e229a7e381b3db / 34659041402 PASS
previousRender61  69732d9ed659a62a3a1e92b36d07b912e141b8c9 / 34659543452 PASS
render423Base     58ece59e95722437069c7e03277363197e564136 / 34659775870 PASS
```

Storage route has a permanent Real Chrome contract; algorithm/training remain covered by existing browser performance suites.

## 5. Current live render owners — do not delete without proof

```text
oldRender412
  algorithm list + data-set stable routing

renderBase428
  training-task routing remains live
  its algorithm branch is shadowed, but the wrapper as a whole is NOT dead

renderTraining423
  current training renderer
  directly calls PollRegistryRuntime.replaceTrainingJobTimer()

finalRender
  final 素材存储配置 route owner
```

Other wrappers still require independent liveness analysis:

```text
baseRenderV37
oldRenderV39
renderBase424
render426base
renderBase427
render414Base
baseRender417
post-render cleanup / MutationObserver layer
```

Do not remove a whole wrapper merely because one branch is shadowed.

## 6. Permanent frontend/browser contracts

Frontend includes:

```text
render-alias-restore.test.mjs
render-owner-retirement.test.mjs
navigation-stability.test.mjs
navigation-persistence.test.mjs
retired-sidebar-setpage-guard.test.mjs
retired-pre-v424-setpage-guard.test.mjs
```

Real Chrome verifies:
- inline/programmatic navigation;
- startup readiness and stale-request fencing;
- PollRegistry stop-on-leave;
- sidebar close;
- current and historical auto-label alias canonicalization;
- page persistence/reload;
- storage configuration final render route;
- algorithm-list/training-task/material performance paths.

Do not weaken these tests.

## 7. Required deletion sequence

For every remaining render candidate:

```text
live HEAD
→ exact assignment/capture/source-order proof
→ page coverage/liveness proof
→ browser/unit behavior contract where needed
→ semantic migration if the layer is live
→ double-owner equivalence if semantics move
→ physical deletion only when shadowed/dead
→ permanent guard
→ full frontend + Real Chrome
→ delete one-shot migration helper/workflow
→ docs sync
```

## 8. Non-regression backend contracts

- snapshot schema v3 and duplicate/leakage protection;
- `confirmed_empty` negative-sample semantics;
- task-runtime lease/generation/process fencing;
- explicit `batch`, `workers`, `cache=false` end-to-end;
- first training uses task-scoped labels only;
- no mother-model class inheritance on first training;
- iteration inherits only latest successful artifact-verified trainable version;
- metrics SQLite connections close deterministically;
- trial/test images sent to model without GT leakage.

## 9. Work order

```text
1. remaining render override owner audit / obsolete generation deletion
2. proven dead app.js + global reload/request debt
3. cache-busting unification
4. zero-point MutationObserver/timer/fetch/render/setPage scan
5. semantic naming + deterministic tests + docs
6. technical-debt zero-point scan
7. resume A800 RC
```

## 10. A800 status

**DEFERRED** until current P0/P1 technical debt is closed. Frontend CI is not CUDA/A800 acceptance.
