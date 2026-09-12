# Frontend Legacy Runtime Audit

> Branch: `refactor/frontend-runtime-stabilization`  
> Authority: `docs/TECH_DEBT_CLOSURE_V42_25.md`  
> Goal: reduce classic `static/app.js` to bounded shell + named runtime owners before any future framework replacement.

## 1. Latest accepted code point

```text
commit:       36fd25c48a2251d1b4a85583921c00dd98bf33fb
run:          34664755130
frontend:     PASS
Real Chrome:  PASS (15/15)
```

Current caches/builds:

```text
app.js                    42.25.66
main.mjs                  42.25.70
visible formal version    42.24.0
internal UI build         42.25.0-dev
navigation-stability      422511
ui-state                  422500
poll-registry             422511
training-draft-runtime    422516
training-labels           422513
auto-label-poll-runtime   422501
```

## 2. Closed owner surfaces

### Training

```text
state.trainingDraft
→ TrainingDraftRuntime
→ TrainingSubmitRuntime
→ /train/start
```

Retired training mirrors/fallbacks stay retired.

### Polling

```text
training-jobs → PollRegistry + TrainingTaskRuntime
AutoLabel      → AutoLabelPollRuntime + PollRegistry
video          → PollRegistry(video-frames)
sources        → PollRegistry(sources)
```

No classic timer or creation-wrapper ownership may return.

### Navigation

`static/app.js` must contain zero classic `window.setPage=` assignments.

```text
NavigationStability.stableSetPage
  → normalizeNavigationPage
  → PageRequestScope / navigation epoch
  → PollRegistry.beforeNavigate
  → waitForNavigationReady
  → beforeInvokeNavigation
  → performNavigation(page)
  → PageRequestScope.alignPage
  → PollRegistry.afterNavigate
  → persistNavigationState
```

## 3. Render/lifecycle retirement completed so far

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
renderAutoLabel424 legacy 1.8s self-refresh timeout/predicate
baseRender417 visible-version correction wrapper
baseRender417 delayed correction timers
12 historical app.js delayed versionBadge startup writers
main.mjs applyBuildVersion visible-version writer/timers
```

`renderAutoLabel424()` itself remains referenced by historical action functions and is not yet retired as a function.

## 4. R9 — visible version ownership consolidation

The migration was driven by a failing Real Chrome baseline, not by static assumption.

Baseline:

```text
commit:   50d72687f099eb554ec77e9045e42713025c4453
run:      34664100285
frontend: PASS
Chrome:   14 PASS / 1 FAIL
failure:  #versionBadge expected v42.24.0 but became v42.25.0-dev
```

Root cause:

```text
main.mjs:
  UI_BUILD_VERSION = 42.25.0-dev
  applyBuildVersion()
  delayed writes at 80 / 500 / 1800 / 3600 / 8000ms

app.js:
  12 historical delayed versionBadge writers
  baseRender417 visible correction wrapper
  baseRender417 delayed correction timers
```

Those owners were fighting each other even though most classic constants currently resolved to `42.24.0`.

Final ownership split:

```text
build metadata:
  UI_BUILD_VERSION = 42.25.0-dev
  → document.documentElement.dataset.uiBuild only

visible formal version:
  static/index.html initial badge = v42.24.0
  top badge                      = top412 / V412
  sidebar footer                 = nav426 / V426
```

Product:

```text
1e9ae1118a77313d8dd3d4c0cf12d5ce5f9edff7
```

Validation:

```text
36fd25c48a2251d1b4a85583921c00dd98bf33fb
run 34664755130
frontend PASS
Real Chrome 15/15 PASS
```

Permanent frontend guard: `tests/frontend/version-marker-owner.test.mjs`. Permanent browser guard: `formal version marker stays stable across final render owners and delayed legacy timers` in `navigation-stability.spec.mjs`.

## 5. Current live render topology

Confirmed live; do not delete as whole layers without new proof:

```text
oldRender412
  算法列表 / 数据集 stable routing

renderBase428
  训练任务 routing only

renderTraining423
  current training renderer
  directly owns PollRegistry.replaceTrainingJobTimer()

renderBase427
  canonical 自动标注及清洗 route owner

renderBase424
  质量中心 / 视频切帧 route owner only

oldRenderV39
  deployment conversion/artifact/resource/plugin/component routes

render414Base
  标签管理 route

finalRender
  素材存储配置 final route owner
```

Still under audit:

```text
baseRenderV37
  post-render page enhancement

render426base
  post-render file-input beautification

post-render cleanup wrapper + MutationObserver
older base/global render generations reached through delegates
```

`baseRender417` is CLOSED and must not return.

## 6. Permanent contracts

Frontend includes:

```text
tests/frontend/render-alias-restore.test.mjs
tests/frontend/render-owner-retirement.test.mjs
tests/frontend/version-marker-owner.test.mjs
tests/frontend/auto-label-poll-runtime.test.mjs
tests/frontend/navigation-stability.test.mjs
tests/frontend/navigation-persistence.test.mjs
```

R9 requires:

```text
baseRender417 absent
historical delayed versionBadge writers absent
main.mjs visible version writes absent
applyBuildVersion absent
initial visible version = v42.24.0
UI_BUILD_VERSION kept only as internal metadata
final visible top/footer owners remain formal 42.24.0
```

Current Real Chrome suite: **15/15** in run `34664755130`.

## 7. Remaining technical-debt targets

```text
remaining render override generations
loadAll / loadRelated / loadCore412 ownership
proven dead app.js code
global reload / duplicate requests
cache-busting heterogeneity
MutationObserver / setInterval / setTimeout / fetch lifecycle
version-number business naming
final zero-point scan
```

## 8. Audit method

For every candidate generation:

```text
live HEAD
→ exact assignment/capture/reference topology
→ identify live owner vs shadowed generation/branch
→ lock real semantic behavior
→ migrate semantic ownership if needed
→ double-owner equivalence where semantics move
→ bounded physical deletion
→ permanent guard
→ frontend + Real Chrome
→ delete temporary migration artifacts
→ docs sync
```

Do not delete by version suffix alone. Do not add a global render-repair loop. Prefer page-scoped/semantic owners and local DOM refreshes over periodic whole-page repaint.

## 9. Non-negotiable rules

1. No new numbered compatibility generation.
2. Retired training mirrors/fallbacks stay retired.
3. Classic `setPage` ownership remains zero in `app.js`.
4. `state.page==='自动标注'` remains zero in `app.js`.
5. Render must not resume route-state alias mutation.
6. Legacy AutoLabel route/timer owners stay absent.
7. `renderBase428` remains training-only unless semantics move first.
8. `renderBase424` remains quality/video-only unless semantics move first.
9. AutoLabel remains PollRegistry-only.
10. `baseRender417` and delayed visible-version writers stay retired.
11. Internal build metadata must never become a visible formal-version owner.
12. No mother-model class inheritance on first training.
13. Explicit false/zero training settings survive end-to-end.
14. Trial/test inference never receives GT labels.
15. Do not weaken duplicate-request/race/performance/Real Chrome tests.
16. Frontend CI is not A800/CUDA acceptance.

## 10. Work order

```text
1. remaining render override owner audit / obsolete generation deletion
2. app.js dead code + global reload/request debt
3. cache-busting unification
4. zero-point observer/timer/fetch/render/setPage scan
5. semantic naming + deterministic tests + docs
6. technical-debt zero-point scan
7. A800 RC
```