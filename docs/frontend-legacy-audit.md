# Frontend Legacy Runtime Audit

> Branch: `refactor/frontend-runtime-stabilization`  
> Authority: `docs/TECH_DEBT_CLOSURE_V42_25.md`  
> Goal: reduce classic `static/app.js` to bounded shell + named runtime owners before any future framework replacement.

## 1. Latest accepted code point

```text
commit:       9bad939a70bc85c75b0897ee7b4d5a21fb2ab9d1
run:          34665890699
frontend:     PASS
Real Chrome:  PASS (17/17)
```

Current caches/builds:

```text
app.js                    42.25.68
main.mjs                  42.25.72
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

No classic polling timer or creation-wrapper ownership may return.

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
v42.2/v42.4 legacy 自动标注 route branches
renderBase424 算法列表 / 数据集 / 训练任务 branches
renderAutoLabel424 legacy 1.8s self-refresh timeout/predicate
baseRender417 visible-version correction wrapper/timers
12 historical app.js delayed versionBadge startup writers
main.mjs applyBuildVersion visible-version writer/timers
render426base page-render file-input beautification wrapper
modal426 modal file-input beautification wrapper
```

`renderAutoLabel424()` itself remains referenced by historical action functions and is not yet retired as a function.

## 4. R9 — visible version ownership consolidation

A failing Real Chrome baseline exposed a real asynchronous owner conflict. Final split:

```text
UI_BUILD_VERSION = 42.25.0-dev
  → document.documentElement.dataset.uiBuild only

static/index.html visible initial badge → v42.24.0
top412 / V412                         → visible top v42.24.0
nav426 / V426                         → visible footer v42.24.0
```

Accepted at:

```text
product:    1e9ae1118a77313d8dd3d4c0cf12d5ce5f9edff7
validation: 36fd25c48a2251d1b4a85583921c00dd98bf33fb
run:        34664755130
Real Chrome 15/15 PASS
```

## 5. R10/R11 — file-input lifecycle consolidation

### R10 page owner

The final `测试发布` page still emits ordinary `#predFile`, so `render426base` was proven live before migration. Page semantics moved to:

```text
render chain
→ cleanup(#view)
→ beautifyFileInputs426(root)
```

R10 acceptance:

```text
baseline:   6b67497ae43a32edf343fc7dec49f7b3824c1088
product:    b9d25955c185aaabb4108f3d37cfecd9f876390a
validation: 0dacf581da4acb52312f75eb7e85e6b334e060db
run:        34665470320
Chrome:     16/16 PASS
```

### R11 modal owner

A generic modal baseline locked native-file → platform filepicker behavior before retirement. After R10, `#modalBody` was already observed by the post-render cleanup MutationObserver, and `cleanup(root)` already invoked `beautifyFileInputs426`.

Final modal topology:

```text
modal innerHTML mutation
→ modalBody MutationObserver
→ cleanup(addedNode)
→ beautifyFileInputs426(root)
```

Retired:

```text
modal426
requestAnimationFrame(()=>beautifyFileInputs426(layer||document))
```

R11 acceptance:

```text
baseline:   d2aa614870a52864e991502c2218134943afb14f
product:    8ff8e7fd9dc055b6e413c273cc030e7f20a2f0c1
validation: 9bad939a70bc85c75b0897ee7b4d5a21fb2ab9d1
run:        34665890699
frontend:   PASS
Chrome:     17/17 PASS
```

All R10/R11 one-shot baseline/migration helpers/workflows were deleted after acceptance.

## 6. Current live render topology

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

cleanup(root)
  post-render DOM normalization
  page + modal file-input beautification
```

Still under audit:

```text
baseRenderV37
baseModalV37
post-render cleanup wrapper + view/modalBody MutationObserver lifecycle
body-wide ZIP-review MutationObserver lifecycle
older base/global render generations reached through delegates
```

`baseRender417`, `render426base`, and `modal426` are CLOSED and must not return.

## 7. Permanent contracts

Frontend includes:

```text
tests/frontend/render-alias-restore.test.mjs
tests/frontend/render-owner-retirement.test.mjs
tests/frontend/version-marker-owner.test.mjs
tests/frontend/file-input-beautification-owner.test.mjs
tests/frontend/auto-label-poll-runtime.test.mjs
tests/frontend/navigation-stability.test.mjs
tests/frontend/navigation-persistence.test.mjs
```

Current file-input ownership contract requires:

```text
render426base absent
modal426 absent
old page/modal RAF beautification callbacks absent
cleanup(root) invokes window.beautifyFileInputs426?.(root)
view + modalBody observer wiring remains until explicit lifecycle migration
测试发布 #predFile receives native-file426 + filepicker426
ordinary modal file input receives equivalent filepicker behavior
```

Current accepted Real Chrome suite: **17/17** in run `34665890699`.

## 8. Remaining technical-debt targets

```text
baseRenderV37 / baseModalV37 / cleanup+observer owner audit
loadAll / loadRelated / loadCore412 ownership
proven dead app.js code
global reload / duplicate requests
cache-busting heterogeneity
MutationObserver / setInterval / setTimeout / fetch lifecycle
version-number business naming
final zero-point scan
```

## 9. Audit method

For every candidate:

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

Do not delete by version suffix alone. Do not add a global render-repair loop. Prefer semantic/page-scoped owners and explicit lifecycle cleanup.

## 10. Non-negotiable rules

1. No new numbered compatibility generation.
2. Retired training mirrors/fallbacks stay retired.
3. Classic `setPage` ownership remains zero in `app.js`.
4. `state.page==='自动标注'` remains zero in `app.js`.
5. Render must not resume route-state alias mutation.
6. Legacy AutoLabel route/timer owners stay absent.
7. `renderBase428` remains training-only unless semantics move first.
8. `renderBase424` remains quality/video-only unless semantics move first.
9. AutoLabel remains PollRegistry-only.
10. `baseRender417`, `render426base`, `modal426`, and delayed visible-version writers stay retired.
11. Internal build metadata must never become a visible formal-version owner.
12. File-input page/modal behavior must stay covered while cleanup/observer lifecycle is refactored.
13. No mother-model class inheritance on first training.
14. Explicit false/zero training settings survive end-to-end.
15. Trial/test inference never receives GT labels.
16. Do not weaken duplicate-request/race/performance/Real Chrome tests.
17. Frontend CI is not A800/CUDA acceptance.

## 11. Work order

```text
1. baseRenderV37 / baseModalV37 / cleanup+observer audit
2. app.js dead code + global reload/request debt
3. cache-busting unification
4. zero-point observer/timer/fetch/render/setPage scan
5. semantic naming + deterministic tests + docs
6. technical-debt zero-point scan
7. A800 RC
```