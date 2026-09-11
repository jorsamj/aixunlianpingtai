# Frontend Legacy Runtime Audit

> Branch: `refactor/frontend-runtime-stabilization`  
> Authority: `docs/TECH_DEBT_CLOSURE_V42_25.md`  
> Goal: reduce classic `static/app.js` to bounded shell + named runtime owners before any future framework replacement.

## 1. Latest accepted code point

```text
commit: 58ece59e95722437069c7e03277363197e564136
run:    34659775870
frontend:     PASS
Real Chrome:  PASS
```

Current caches/builds:

```text
app.js                    42.25.61
main.mjs                  42.25.64
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

### Navigation — classic owner family zero-point CLOSED

`static/app.js` must contain **zero** classic `window.setPage=` assignments. Permanent CI enforces this.

Final topology:

```text
NavigationStability.stableSetPage
  → normalizeNavigationPage
  → PageRequestScope / navigation epoch
  → PollRegistry.beforeNavigate
  → waitForNavigationReady
  → beforeInvokeNavigation
  → performNavigation(page)
       state.page = page
       render()
  → PageRequestScope.alignPage
  → PollRegistry.afterNavigate
  → persistNavigationState
```

## 3. Render retirement already completed

### v42.7 route alias mutation

The old render chain changed `state.page` from `自动标注` to `自动标注及清洗`. This has been removed.

Current responsibility split:

```text
navigation alias request  → NavigationStability.normalizeNavigationPage
historical persisted page → v34 restore-boundary canonicalization + writeback
render                    → never mutates route alias state
```

A new Real Chrome cold-start test first exposed a real bug: the UI became canonical but localStorage did not. Baseline `582b913e... / 34656484008` failed 1 of 13 browser tests; fix `e35a29b0... / 34656747269` passed fully.

### Fully shadowed classic render generations

Physically retired and permanently guarded:

```text
oldRender429
previousRender61
render423Base
```

Why they were dead:

```text
oldRender429:
  算法列表 + 数据集 were intercepted by later oldRender412;
  all other pages were pass-through.

previousRender61:
  素材存储配置 was intercepted by later finalRender;
  all other pages were pass-through.

render423Base:
  算法列表 was intercepted by oldRender412;
  训练任务 was intercepted by renderBase428;
  all other pages were pass-through.
```

Acceptance evidence:

```text
oldRender429      0455eeef... / 34659041402 PASS
storage baseline  00721975... / 34659361434 PASS
previousRender61  69732d9e... / 34659543452 PASS
render423Base     58ece59e... / 34659775870 PASS
```

One-shot migration helpers/workflows were deleted after acceptance.

## 4. Current live render topology — partial map

These are confirmed live and must not be removed as whole layers without a new proof:

```text
oldRender412
  routes 算法列表 and 数据集

renderBase428
  routes 训练任务
  algorithm branch is shadowed, but training branch is live

renderTraining423
  current training renderer
  directly owns PollRegistry.replaceTrainingJobTimer()

finalRender
  routes 素材存储配置
```

Still under audit:

```text
baseRenderV37       post-render page enhancement
oldRenderV39        deployment routes
renderBase424       quality/data/video/auto-label routes
render426base       post-render file-input beautification
renderBase427       自动标注及清洗 route
render414Base       标签管理 + version badge behavior
baseRender417       version badge/footer correction
post-render cleanup wrapper + MutationObserver
older base/global render generations reached through the chain
```

A branch inside a live wrapper may be dead while the wrapper remains live. Delete branches/layers only after exact source-order and coverage proof.

## 5. Permanent contracts added for render cleanup

Frontend:

```text
tests/frontend/render-alias-restore.test.mjs
tests/frontend/render-owner-retirement.test.mjs
```

They currently prevent return of:

```text
render-level auto-label alias mutation
oldRender429
previousRender61
render423Base
```

and require the currently live owners needed to replace them.

Browser:

`tests/browser/navigation-stability.spec.mjs` now includes a real `素材存储配置` route contract requiring `.storage61-shell` and `#storage61Rows` to render without page errors.

Existing browser performance suites continue to cover algorithm list, training task and material page behavior.

## 6. Remaining technical-debt targets

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

## 7. Audit method

For every candidate generation:

```text
live HEAD
→ exact assignment/capture/reference topology
→ identify final live owner vs fully shadowed generation
→ lock real semantic behavior
→ migrate semantic ownership if needed
→ double-owner equivalence where semantics move
→ bounded physical deletion
→ permanent guard
→ frontend + Real Chrome
→ delete temporary migration artifacts
→ docs sync
```

Do not delete by version suffix alone. Do not add a global render-repair loop. Prefer page-scoped/semantic render owners and local DOM refreshes over periodic whole-page repaint.

## 8. Non-negotiable rules

1. No new numbered compatibility generation.
2. Retired training mirrors/fallbacks stay retired.
3. Classic `setPage` ownership must remain zero in `app.js`.
4. Render must not resume route-state alias mutation.
5. No mother-model class inheritance on first training.
6. Explicit false/zero training settings survive end-to-end.
7. Trial/test inference must never receive GT labels.
8. Do not weaken duplicate-request/race/performance/Real Chrome tests.
9. TrainingDraftRuntime / TrainingLabelRuntime remain wrapper-free.
10. AutoLabel remains PollRegistry-only.
11. Video/source/training polling direct ownership must not regress.
12. Frontend CI is not A800/CUDA acceptance.

## 9. Work order

```text
1. remaining render override owner audit / obsolete generation deletion
2. app.js dead code + global reload/request debt
3. cache-busting unification
4. zero-point observer/timer/fetch/render/setPage scan
5. semantic naming + deterministic tests + docs
6. technical-debt zero-point scan
7. A800 RC
```
