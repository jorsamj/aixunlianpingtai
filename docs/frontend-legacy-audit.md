# Frontend Legacy Runtime Audit

> Branch: `refactor/frontend-runtime-stabilization`  
> Authority: `docs/TECH_DEBT_CLOSURE_V42_25.md`  
> Goal: reduce classic `static/app.js` to bounded shell + named runtime owners before any future framework replacement.

## 1. Latest accepted code point

```text
commit:       0dacf581da4acb52312f75eb7e85e6b334e060db
run:          34665470320
frontend:     PASS
Real Chrome:  PASS (16/16)
```

Current caches/builds:

```text
app.js                    42.25.67
main.mjs                  42.25.71
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
v42.2 render422 legacy 自动标注 route branch
v42.4 renderBase424 legacy 自动标注 route branch
renderBase424 算法列表 / 数据集 / 训练任务 branches
renderAutoLabel424 legacy 1.8s self-refresh timeout/predicate
baseRender417 visible-version correction wrapper/timers
12 historical app.js delayed versionBadge startup writers
main.mjs applyBuildVersion visible-version writer/timers
render426base page-render file-input beautification wrapper
```

`renderAutoLabel424()` itself remains referenced by historical action functions and is not yet retired as a function.

## 4. R9 — visible version ownership consolidation

A failing Real Chrome baseline exposed a real asynchronous owner conflict:

```text
50d72687f099eb554ec77e9045e42713025c4453 / 34664100285
frontend PASS
Chrome 14 PASS / 1 FAIL
#versionBadge became v42.25.0-dev after delayed startup work
```

Final ownership split:

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

## 5. R10 — render426base page owner retirement

`render426base` was initially suspected to be removable, but exact behavior audit proved it was live. The final `测试发布` renderer still emits an ordinary file input:

```html
<input id="predFile" type="file" accept="image/*" class="file">
```

Before R10, its platform file-picker UI depended on:

```text
render426base
→ render()
→ requestAnimationFrame
→ beautifyFileInputs426(#view)
```

The current `数据集` upload flow was deliberately not used as the baseline because its actual inputs are hidden and marked `data-file426=1`, which explicitly excludes them from `beautifyFileInputs426`.

R10 first locked the real live behavior in Chrome, then moved page ownership into the later post-render cleanup owner:

```text
cleanup(root)
→ window.beautifyFileInputs426?.(root)
→ existing cleanup work
```

The historical `render426base` wrapper is now absent. `modal426` remains present on purpose; modal behavior was not silently folded into R10 and requires its own liveness/equivalence proof.

Acceptance:

```text
behavior baseline: 6b67497ae43a32edf343fc7dec49f7b3824c1088
product:           b9d25955c185aaabb4108f3d37cfecd9f876390a
validation:        0dacf581da4acb52312f75eb7e85e6b334e060db
run:               34665470320
frontend:          PASS
Real Chrome:       16/16 PASS
```

Permanent proof:

```text
tests/frontend/file-input-beautification-owner.test.mjs
navigation-stability.spec.mjs:
  file input beautification survives page render lifecycle ownership
```

All R10 one-shot baseline/migration helpers and workflows were deleted after acceptance.

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
  page file-input beautification after R10

modal426
  modal file-input beautification wrapper; still under audit
```

Still under audit:

```text
modal426
baseRenderV37
post-render cleanup wrapper + MutationObserver lifecycle
body-wide ZIP-review MutationObserver lifecycle
older base/global render generations reached through delegates
```

`baseRender417` and `render426base` are CLOSED and must not return.

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

Key R10 requirements:

```text
render426base absent
old requestAnimationFrame page beautification callback absent
cleanup(root) invokes window.beautifyFileInputs426?.(root)
modal426 remains until separately audited
测试发布 #predFile still receives native-file426 + filepicker426 behavior
```

Current accepted Real Chrome suite: **16/16** in run `34665470320`.

## 8. Remaining technical-debt targets

```text
modal426 / baseRenderV37 / cleanup+observer owner audit
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
10. `baseRender417`, `render426base`, and delayed visible-version writers stay retired.
11. Internal build metadata must never become a visible formal-version owner.
12. `modal426` cannot be removed merely because page beautification moved to cleanup; modal equivalence must be proven first.
13. No mother-model class inheritance on first training.
14. Explicit false/zero training settings survive end-to-end.
15. Trial/test inference never receives GT labels.
16. Do not weaken duplicate-request/race/performance/Real Chrome tests.
17. Frontend CI is not A800/CUDA acceptance.

## 11. Work order

```text
1. modal426 / baseRenderV37 / cleanup+observer audit
2. app.js dead code + global reload/request debt
3. cache-busting unification
4. zero-point observer/timer/fetch/render/setPage scan
5. semantic naming + deterministic tests + docs
6. technical-debt zero-point scan
7. A800 RC
```