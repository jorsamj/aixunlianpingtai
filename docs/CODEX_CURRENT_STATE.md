# Codex Current State

> First-entry handoff for `jorsamj/aixunlianpingtai`. Verify live branch/HEAD before editing. `docs/TECH_DEBT_CLOSURE_V42_25.md` is the authoritative debt ledger.

## 1. Branch / release state

```text
branch:                      refactor/frontend-runtime-stabilization
latest full code acceptance: 0dacf581da4acb52312f75eb7e85e6b334e060db
Frontend Runtime run:        34665470320
formal VERSION.txt:          42.24.0
visible frontend version:    v42.24.0
internal UI build metadata:  42.25.0-dev
app.js cache:                42.25.67
main.mjs cache:              42.25.71
NavigationStability:         422511
UI state runtime:            422500
PollRegistry:                422511
TrainingDraftRuntime:        422516
TrainingLabelRuntime:        422513
TrainingSubmitRuntime:       training-submit-422504
TrainingTaskRuntime:         training-task-runtime-422503
AutoLabelPollRuntime:        422501
```

Run `34665470320` passed syntax, all permanent owner guards, all frontend unit tests and Real Chrome runtime regressions. Browser navigation now runs **16 tests and passed 16/16**. Do not merge `main`, bump `VERSION.txt`, tag or release without explicit user approval.

## 2. Current priority

```text
remaining render/modal/post-render owner audit
→ app.js/global reload/request debt
→ cache-busting unification
→ zero-point lifecycle scan
→ semantic naming/dead-code cleanup
→ A800 RC
```

A800 RC remains deferred.

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

Legacy timers/shells/wrappers/adoption compatibility are retired. R8 removed the old `renderAutoLabel424()` 1.8-second self-refresh timeout keyed to the impossible legacy page value `自动标注`.

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

Permanent CI forbids classic `window.setPage=` owners in `static/app.js`.

## 4. Render / lifecycle debt already closed

Physically retired and permanently guarded:

```text
v42.7 render route-state alias mutation
oldRender429
previousRender61
render423Base
renderBase428 算法列表 branch
v42.2 render422 legacy 自动标注 route branch
v42.4 renderBase424 legacy 自动标注 route branch
renderBase424 算法列表 / 数据集 / 训练任务 branches
renderAutoLabel424 legacy 自动标注 1.8s self-refresh timeout/predicate
baseRender417 visible-version correction wrapper
baseRender417 120/600/1600ms correction timers
12 historical app.js versionBadge startup timers
main.mjs applyBuildVersion visible-version writer/timers
render426base page-render file-input beautification wrapper
```

### R9 — version marker ownership consolidation

A Real Chrome baseline exposed the delayed `v42.25.0-dev` overwrite. R9 separated internal build metadata from visible formal version display.

```text
product:    1e9ae1118a77313d8dd3d4c0cf12d5ce5f9edff7
validation: 36fd25c48a2251d1b4a85583921c00dd98bf33fb
run:        34664755130
Chrome:     15/15 PASS
```

Final split:

```text
UI_BUILD_VERSION = 42.25.0-dev
  → document.documentElement.dataset.uiBuild only

initial visible badge → v42.24.0
top visible badge     → top412 / V412 = 42.24.0
sidebar footer        → nav426 / V426 = 42.24.0
```

### R10 — render426base page wrapper retirement

Audit proved `render426base` was live, not dead: on `测试发布`, the unmarked `#predFile` input depended on the wrapper's post-render `beautifyFileInputs426()` callback. The current `数据集` upload flow uses hidden `data-file426=1` inputs and is intentionally excluded from this beautifier, so it was not used as the behavior baseline.

Migration:

```text
before:
  render426base
  → render()
  → requestAnimationFrame(beautifyFileInputs426(#view))

after:
  post-render cleanup(root)
  → beautifyFileInputs426(root)
  → existing cleanup semantics
```

`modal426` was deliberately **not** removed in R10. Modal file-input beautification remains a separate live-audit target.

R10 acceptance:

```text
behavior baseline: 6b67497ae43a32edf343fc7dec49f7b3824c1088
product:           b9d25955c185aaabb4108f3d37cfecd9f876390a
validation:        0dacf581da4acb52312f75eb7e85e6b334e060db
run:               34665470320
frontend:          PASS
Real Chrome:       16/16 PASS
```

Permanent guards:

```text
tests/frontend/file-input-beautification-owner.test.mjs
navigation-stability.spec.mjs:
  file input beautification survives page render lifecycle ownership
```

The unit guard forbids `render426base` from returning, requires `cleanup(root)` to call `window.beautifyFileInputs426?.(root)`, and explicitly requires `modal426` to remain until its own migration is proven.

## 5. Current live render owners — do not delete without proof

```text
oldRender412
  算法列表 / 数据集 stable routing

renderBase428
  training-only route to renderTraining423

renderTraining423
  current training renderer
  directly activates PollRegistry training-jobs

renderBase427
  canonical 自动标注及清洗 route owner

renderBase424
  质量中心 / 视频切帧 route owner only

oldRenderV39
  deployment conversion/artifact/resource/plugin/component routes

render414Base
  标签管理 route; remains live

finalRender
  素材存储配置 final route owner

cleanup(root)
  page post-render normalization
  page file-input beautification after R10

modal426
  modal post-render file-input beautification; still under audit
```

Still requiring independent liveness analysis:

```text
modal426
baseRenderV37
post-render cleanup wrapper + MutationObserver ownership
body-wide ZIP-review MutationObserver
older base/global render generations still reachable through delegates
```

`baseRender417` and `render426base` are no longer audit targets; they are permanently retired.

## 6. Permanent frontend/browser contracts

Frontend includes:

```text
render-alias-restore.test.mjs
render-owner-retirement.test.mjs
version-marker-owner.test.mjs
file-input-beautification-owner.test.mjs
navigation-stability.test.mjs
navigation-persistence.test.mjs
retired-sidebar-setpage-guard.test.mjs
retired-pre-v424-setpage-guard.test.mjs
auto-label-poll-runtime.test.mjs
```

Real Chrome verifies navigation, readiness, stale-request fencing, managed polling, sidebar cleanup, current/historical auto-label canonicalization, persistence/reload, storage route, algorithm/training/material performance, formal-version stability, and page-render file-input beautification. Current accepted suite: **16/16**.

Do not weaken these tests.

## 7. Required deletion sequence

For every remaining candidate:

```text
live HEAD
→ exact assignment/capture/source-order proof
→ page/modal coverage and liveness proof
→ browser/unit behavior contract where needed
→ semantic migration if live
→ double-owner equivalence if semantics move
→ physical deletion only when shadowed/dead or semantics have moved
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
1. modal426 / baseRenderV37 / cleanup+observer owner audit
2. proven dead app.js + global reload/request debt
3. cache-busting unification
4. zero-point MutationObserver/timer/fetch/render/setPage scan
5. semantic naming + deterministic tests + dead-code cleanup
6. technical-debt zero-point scan
7. resume A800 RC
```

## 10. A800 status

**DEFERRED** until current P0/P1 technical debt is closed. Frontend CI is not CUDA/A800 acceptance.