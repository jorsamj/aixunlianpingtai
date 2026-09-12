# Codex Current State

> First-entry handoff for `jorsamj/aixunlianpingtai`. Verify live branch/HEAD before editing. `docs/TECH_DEBT_CLOSURE_V42_25.md` is the authoritative debt ledger.

## 1. Branch / release state

```text
branch:                      refactor/frontend-runtime-stabilization
latest full code acceptance: 36fd25c48a2251d1b4a85583921c00dd98bf33fb
Frontend Runtime run:        34664755130
formal VERSION.txt:          42.24.0
visible frontend version:    v42.24.0
internal UI build metadata:  42.25.0-dev
app.js cache:                42.25.66
main.mjs cache:              42.25.70
NavigationStability:         422511
UI state runtime:            422500
PollRegistry:                422511
TrainingDraftRuntime:        422516
TrainingLabelRuntime:        422513
TrainingSubmitRuntime:       training-submit-422504
TrainingTaskRuntime:         training-task-runtime-422503
AutoLabelPollRuntime:        422501
```

Run `34664755130` passed syntax, all permanent owner guards, all frontend unit tests and Real Chrome runtime regressions. Browser navigation now runs **15 tests and passed 15/15**. Do not merge `main`, bump `VERSION.txt`, tag or release without explicit user approval.

## 2. Current priority

```text
remaining render override owner audit / obsolete generation deletion
→ app.js/global reload/request debt
→ cache-busting unification
→ zero-point lifecycle scan
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

Legacy timers/shells/wrappers/adoption compatibility are retired. R8 removed the old `renderAutoLabel424()` 1.8-second self-refresh timeout keyed to the now-impossible legacy page value `自动标注`.

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
main.mjs applyBuildVersion visible-version writer
main.mjs 80/500/1800/3600/8000ms visible-version writers
```

### R9 — version marker ownership consolidation

A new Real Chrome contract first exposed a real pre-existing bug:

```text
baseline commit: 50d72687f099eb554ec77e9045e42713025c4453
baseline run:    34664100285
frontend:        PASS
Chrome:          14 PASS / 1 FAIL
failure:         expected v42.24.0, received v42.25.0-dev after delayed startup writers
```

Root cause was `static/main.mjs` mixing internal build metadata with visible formal version display through `applyBuildVersion()` plus delayed timers. Classic `app.js` also contained 12 historical delayed badge writers and `baseRender417` correction timers.

R9 final split:

```text
internal build metadata:
  UI_BUILD_VERSION = 42.25.0-dev
  → document.documentElement.dataset.uiBuild only

visible formal version:
  initial HTML badge → v42.24.0
  top badge          → top412 / V412 = 42.24.0
  sidebar footer     → nav426 / V426 = 42.24.0
```

Product commit:

```text
1e9ae1118a77313d8dd3d4c0cf12d5ce5f9edff7
```

Final validation:

```text
36fd25c48a2251d1b4a85583921c00dd98bf33fb
run 34664755130
frontend PASS
Real Chrome 15/15 PASS
```

Permanent guard: `tests/frontend/version-marker-owner.test.mjs`; it is included automatically by the main CI command `node --test tests/frontend/*.test.mjs`. The 15th Real Chrome test permanently verifies visible formal version stability after historical delay windows and across final render owners.

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
```

Still requiring independent liveness analysis:

```text
baseRenderV37
render426base
post-render cleanup / MutationObserver layer
older base/global render generations still reachable through delegates
```

`baseRender417` is no longer an audit target; R9 retired it after the visible-version semantics were proven elsewhere and locked by Chrome.

## 6. Permanent frontend/browser contracts

Frontend includes:

```text
render-alias-restore.test.mjs
render-owner-retirement.test.mjs
version-marker-owner.test.mjs
navigation-stability.test.mjs
navigation-persistence.test.mjs
retired-sidebar-setpage-guard.test.mjs
retired-pre-v424-setpage-guard.test.mjs
auto-label-poll-runtime.test.mjs
```

Important R9 permanent requirements:
- `baseRender417` must remain absent;
- delayed classic `versionBadge` startup writers must remain absent;
- `main.mjs` may keep `UI_BUILD_VERSION` as internal metadata but must not write `#versionBadge` or `.nav-footer b`;
- visible initial version must be `v42.24.0`;
- `top412` and `nav426` must keep formal-version display semantics until a later explicitly named owner migration is proven.

Real Chrome verifies navigation, readiness, stale-request fencing, managed polling, sidebar cleanup, current/historical auto-label canonicalization, persistence/reload, storage route, algorithm/training/material performance, and formal-version stability. Current accepted suite: **15/15**.

Do not weaken these tests.

## 7. Required deletion sequence

For every remaining render candidate:

```text
live HEAD
→ exact assignment/capture/source-order proof
→ page coverage/liveness proof
→ browser/unit behavior contract where needed
→ semantic migration if live
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