# Codex Current State

> First-entry handoff for `jorsamj/aixunlianpingtai`. Verify live branch/HEAD before editing. `docs/TECH_DEBT_CLOSURE_V42_25.md` is the authoritative debt ledger.

## 1. Branch / release state

```text
branch:                      refactor/frontend-runtime-stabilization
latest full code acceptance: 60d87751e4e259a3a8ef11e6c1a5d5a9ea42ab29
Frontend Runtime run:        34666673017
formal VERSION.txt:          42.24.0
visible frontend version:    v42.24.0
internal UI build metadata:  42.25.0-dev
app.js cache:                42.25.69
main.mjs cache:              42.25.73
NavigationStability:         422511
UI state runtime:            422500
PollRegistry:                422511
TrainingDraftRuntime:        422516
TrainingLabelRuntime:        422513
TrainingSubmitRuntime:       training-submit-422504
TrainingTaskRuntime:         training-task-runtime-422503
AutoLabelPollRuntime:        422501
```

Run `34666673017` passed syntax, all permanent owner guards, all frontend unit tests and Real Chrome runtime regressions. Browser navigation now runs **18 tests and passed 18/18**. Do not merge `main`, bump `VERSION.txt`, tag or release without explicit user approval.

## 2. Current priority

```text
baseRenderV37 / baseModalV37 / cleanup+observer owner audit
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

Permanent CI forbids classic `window.setPage=` owners in `static/app.js`.

## 4. Render / lifecycle debt already closed

Physically retired and permanently guarded:

```text
v42.7 render route-state alias mutation
oldRender429
previousRender61
render423Base
renderBase428 算法列表 branch
v42.2/v42.4 legacy 自动标注 route branches
renderBase424 算法列表 / 数据集 / 训练任务 branches
renderAutoLabel424 legacy 自动标注 1.8s self-refresh timeout/predicate
baseRender417 visible-version correction wrapper/timers
12 historical app.js versionBadge startup timers
main.mjs applyBuildVersion visible-version writer/timers
render426base page-render file-input beautification wrapper
modal426 modal file-input beautification wrapper
enhancePageV37 post-render normalization helper
```

### R9 — version marker ownership consolidation

A Real Chrome baseline exposed delayed `v42.25.0-dev` overwrite. R9 separated internal build metadata from visible formal version display.

```text
product:    1e9ae1118a77313d8dd3d4c0cf12d5ce5f9edff7
validation: 36fd25c48a2251d1b4a85583921c00dd98bf33fb
run:        34664755130
Chrome:     15/15 PASS
```

### R10 — render426base page wrapper retirement

`render426base` was live: `测试发布 #predFile` depended on post-render `beautifyFileInputs426()`. Behavior was locked first, then page ownership moved to `cleanup(root)`.

```text
behavior baseline: 6b67497ae43a32edf343fc7dec49f7b3824c1088
product:           b9d25955c185aaabb4108f3d37cfecd9f876390a
validation:        0dacf581da4acb52312f75eb7e85e6b334e060db
run:               34665470320
Real Chrome:       16/16 PASS
```

### R11 — modal426 retirement

A generic modal behavior contract proved the old wrapper's file-input semantics before migration. After R10, the existing `#modalBody` MutationObserver already routes inserted modal nodes through `cleanup(root)`, and `cleanup(root)` owns `beautifyFileInputs426`.

Final topology:

```text
modal body mutation
→ modalBody MutationObserver
→ cleanup(addedNode)
→ beautifyFileInputs426(root)
```

Retired:

```text
const modal426=modal
requestAnimationFrame(()=>beautifyFileInputs426(layer||document))
```

R11 acceptance:

```text
behavior baseline: d2aa614870a52864e991502c2218134943afb14f
product:           8ff8e7fd9dc055b6e413c273cc030e7f20a2f0c1
validation:        9bad939a70bc85c75b0897ee7b4d5a21fb2ab9d1
run:               34665890699
frontend:          PASS
Real Chrome:       17/17 PASS
```

Permanent proof remains in:

```text
tests/frontend/file-input-beautification-owner.test.mjs
tests/browser/navigation-stability.spec.mjs
```

All R10/R11 one-shot baseline/migration helpers and workflows were deleted after acceptance.

### R12 — enhancePageV37 normalization helper retirement

Audit proved `enhancePageV37()` still owned table wrapping and “使用建议” cleanup, while `baseModalV37` also used it before autofocus. R12 locked modal table wrapping + autofocus in Real Chrome, then moved normalization into the later `cleanup(root)` owner.

```text
before:
  baseRenderV37/baseModalV37
  → requestAnimationFrame(enhancePageV37)
  → table wrapping / 使用建议 cleanup

after:
  cleanup(root)
  → table.table → .table-wrap
  → panel/history cleanup

baseRenderV37 → state.versionInfo write only
baseModalV37  → first editable field autofocus only
```

R12 acceptance:

```text
behavior baseline: 6ae19dc79abbf690371a71162c97a2df6322518b
product:           202a5a82b0cb4629423ee0c6812f649031234daa
validation:        60d87751e4e259a3a8ef11e6c1a5d5a9ea42ab29
run:               34666673017
frontend:          PASS
Real Chrome:       18/18 PASS
```

Permanent proof: `tests/frontend/post-render-normalization-owner.test.mjs` plus the browser contract `modal table wrapping and first-field focus survive normalization ownership`.

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
  page/modal post-render normalization
  table wrapping + file-input beautification

baseRenderV37
  state.versionInfo formal-version compatibility write only

baseModalV37
  first editable modal field autofocus only
```

Still requiring independent liveness analysis:

```text
baseRenderV37 versionInfo compatibility ownership
baseModalV37 autofocus ownership
post-render cleanup wrapper + view/modalBody MutationObserver lifecycle
body-wide ZIP-review MutationObserver
older base/global render generations still reachable through delegates
```

`baseRender417`, `render426base`, and `modal426` are permanently retired.

## 6. Permanent frontend/browser contracts

Frontend includes:

```text
render-alias-restore.test.mjs
render-owner-retirement.test.mjs
version-marker-owner.test.mjs
file-input-beautification-owner.test.mjs
post-render-normalization-owner.test.mjs
navigation-stability.test.mjs
navigation-persistence.test.mjs
retired-sidebar-setpage-guard.test.mjs
retired-pre-v424-setpage-guard.test.mjs
auto-label-poll-runtime.test.mjs
```

`file-input-beautification-owner.test.mjs` now permanently requires:
- `render426base` absent;
- `modal426` absent;
- old page/modal RAF beautification callbacks absent;
- `cleanup(root)` calls `beautifyFileInputs426`;
- `view` and `modalBody` observer wiring remains until lifecycle ownership is explicitly migrated.

Real Chrome verifies navigation, readiness, stale-request fencing, managed polling, sidebar cleanup, current/historical auto-label canonicalization, persistence/reload, storage route, algorithm/training/material performance, formal-version stability, and page/modal file-input beautification. Current accepted suite: **18/18**.

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
1. baseRenderV37 / baseModalV37 / cleanup+observer owner audit
2. proven dead app.js + global reload/request debt
3. cache-busting unification
4. zero-point MutationObserver/timer/fetch/render/setPage scan
5. semantic naming + deterministic tests + dead-code cleanup
6. technical-debt zero-point scan
7. resume A800 RC
```

## 10. A800 status

**DEFERRED** until current P0/P1 technical debt is closed. Frontend CI is not CUDA/A800 acceptance.