# Frontend Legacy Runtime Audit

> Branch: `refactor/frontend-runtime-stabilization`  
> Authority: `docs/TECH_DEBT_CLOSURE_V42_25.md`  
> Goal: reduce classic `static/app.js` to bounded shell + named runtime owners before any future framework replacement.

## 1. Latest accepted code point

```text
commit: 70b6f755cd8633de3e8591ac2fee044efc770b97
run:    34663768606
frontend:     PASS
Real Chrome:  PASS (14/14)
```

Current caches/builds:

```text
app.js                    42.25.65
main.mjs                  42.25.68
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

No classic timer or creation-wrapper ownership may return. R8 removed the last old-page AutoLabel424 self-refresh timeout; `static/app.js` now contains zero `state.page==='自动标注'` predicates.

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

## 3. Render/lifecycle retirement already completed

### auto-label route alias + legacy timer

Current responsibility split:

```text
navigation alias request  → NavigationStability.normalizeNavigationPage
historical persisted page → v34 restore-boundary canonicalization + writeback
canonical render route    → renderBase427 → renderOps427()
managed polling           → AutoLabelPollRuntime + PollRegistry
render                    → never mutates route alias state
```

Physically retired:

```text
v42.7 render route-state alias mutation
v42.2 render422 legacy 自动标注 route branch
v42.4 renderBase424 legacy 自动标注 route branch
renderAutoLabel424 legacy 1.8s self-refresh timeout keyed to 自动标注
```

The old `renderAutoLabel424()` function itself remains because historical submit/stop/retry action functions still call it directly. R8 was intentionally timer-only.

### Fully shadowed classic render generations / branches

Physically retired and permanently guarded:

```text
oldRender429
previousRender61
render423Base
renderBase428 的 算法列表 branch
renderBase424 的 算法列表 / 数据集 / 训练任务 branches
```

R7 proof remains:

```text
renderBase424 算法列表 → later oldRender412 intercepts first
renderBase424 数据集   → later oldRender412 intercepts first
renderBase424 训练任务 → later renderBase428 intercepts first
renderBase424 wrapper  → still live for 质量中心 / 视频切帧
```

Acceptance evidence:

```text
oldRender429             0455eeef... / 34659041402 PASS
storage baseline         00721975... / 34659361434 PASS
previousRender61         69732d9e... / 34659543452 PASS
render423Base            58ece59e... / 34659775870 PASS
renderBase428 alg branch 6be679b6... / 34660269685 PASS
legacy auto-label routes 66339fc0... / 34663089996 PASS (Chrome 14/14)
renderBase424 branches   2d9bc0b3... / 34663389819 PASS (Chrome 14/14)
AutoLabel424 timer       70b6f755... / 34663768606 PASS (Chrome 14/14)
```

One-shot migration helpers/workflows were deleted after acceptance.

## 4. Current live render topology — partial map

These are confirmed live and must not be removed as whole layers without a new proof:

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
  delegates to renderOps427()

renderBase424
  质量中心 / 视频切帧 route owner only

oldRenderV39
  deployment conversion/artifact/resource/plugin/component routes

render414Base
  标签管理 route + version badge semantics

finalRender
  素材存储配置 final route owner
```

Still under audit:

```text
baseRenderV37       post-render page enhancement
render426base       post-render file-input beautification
baseRender417       version badge/footer correction
post-render cleanup wrapper + MutationObserver
older base/global render generations reached through the chain
```

`oldRenderV39` and `render414Base` were re-checked after R7/R8 and are live; they are not deletion candidates merely because they are historical wrappers.

## 5. Permanent contracts added for render cleanup

Frontend:

```text
tests/frontend/render-alias-restore.test.mjs
tests/frontend/render-owner-retirement.test.mjs
tests/frontend/auto-label-poll-runtime.test.mjs
```

They prevent return of:

```text
render-level auto-label alias mutation
legacy v42.2/v42.4 自动标注 route branches
legacy state.page==='自动标注' predicate
legacy AutoLabel424 1.8s timeout
oldRender429
previousRender61
render423Base
renderBase428 shadowed 算法列表 branch
renderBase424 shadowed 算法列表 / 数据集 / 训练任务 branches
```

and require live replacements, including:

```text
renderBase427 → renderOps427() for 自动标注及清洗
AutoLabelPollRuntime + PollRegistry for AutoLabel polling
oldRender412 → 算法列表 / 数据集
renderBase428 → 训练任务
renderBase424 → 质量中心 / 视频切帧 only
```

Current accepted Real Chrome suite is 14/14 in run `34663768606`, including `auto-label-polling.spec.mjs`.

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
→ identify final live owner vs fully shadowed generation/branch
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
4. `state.page==='自动标注'` must remain zero in `app.js`.
5. Render must not resume route-state alias mutation.
6. Legacy v42.2/v42.4 `自动标注` route branches and AutoLabel424 legacy timer must stay absent.
7. `renderBase428` must remain training-only unless its training semantics are explicitly migrated first.
8. `renderBase424` must remain quality/video-only unless those semantics are explicitly migrated first.
9. AutoLabel remains PollRegistry-only.
10. No mother-model class inheritance on first training.
11. Explicit false/zero training settings survive end-to-end.
12. Trial/test inference must never receive GT labels.
13. Do not weaken duplicate-request/race/performance/Real Chrome tests.
14. TrainingDraftRuntime / TrainingLabelRuntime remain wrapper-free.
15. Video/source/training polling direct ownership must not regress.
16. Frontend CI is not A800/CUDA acceptance.

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