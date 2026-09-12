# Frontend Legacy Runtime Audit

> Branch: `refactor/frontend-runtime-stabilization`  
> Authority: `docs/TECH_DEBT_CLOSURE_V42_25.md`  
> Goal: reduce classic `static/app.js` to bounded shell + named runtime owners before any future framework replacement.

## 1. Latest accepted code point

```text
commit: 2d9bc0b30a72761d784cc57472eb50b158b8851f
run:    34663389819
frontend:     PASS
Real Chrome:  PASS (14/14)
```

Current caches/builds:

```text
app.js                    42.25.64
main.mjs                  42.25.67
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

### v42.7 route alias mutation + old-name route branches

The old render chain changed `state.page` from `自动标注` to `自动标注及清洗`. This has been removed.

Current responsibility split:

```text
navigation alias request  → NavigationStability.normalizeNavigationPage
historical persisted page → v34 restore-boundary canonicalization + writeback
canonical render route    → renderBase427 → renderOps427()
render                    → never mutates route alias state
```

The v42.2/v42.4 route branches keyed to legacy `自动标注` are physically removed. `renderAutoLabel424()` still contains a legacy old-name self-refresh predicate; it is not a route owner and remains for separate dead-code/lifecycle proof.

### Fully shadowed classic render generations / branches

Physically retired and permanently guarded:

```text
oldRender429
previousRender61
render423Base
renderBase428 的 算法列表 branch
v42.2 render422 的 legacy 自动标注 route branch
v42.4 renderBase424 的 legacy 自动标注 route branch
renderBase424 的 算法列表 / 数据集 / 训练任务 branches
```

Why the latest R7 branches were dead:

```text
renderBase424 算法列表:
  later oldRender412 intercepts 算法列表 before delegation can reach renderBase424.

renderBase424 数据集:
  later oldRender412 intercepts 数据集 before delegation can reach renderBase424.

renderBase424 训练任务:
  oldRender412 delegates to later renderBase428, which intercepts 训练任务 before renderBase424.

renderBase424 wrapper itself:
  remains live for 质量中心 and 视频切帧, so the wrapper was reduced rather than deleted.
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
  now only 质量中心 / 视频切帧 route owner

finalRender
  素材存储配置 final route owner
```

Still under audit:

```text
baseRenderV37       post-render page enhancement
oldRenderV39        deployment routes
render426base       post-render file-input beautification
render414Base       标签管理 + version badge behavior
baseRender417       version badge/footer correction
post-render cleanup wrapper + MutationObserver
older base/global render generations reached through the chain
renderAutoLabel424  legacy old-page self-refresh condition (dead-code candidate, not route owner)
```

## 5. Permanent contracts added for render cleanup

Frontend:

```text
tests/frontend/render-alias-restore.test.mjs
tests/frontend/render-owner-retirement.test.mjs
```

They now prevent return of:

```text
render-level auto-label alias mutation
legacy v42.2/v42.4 自动标注 route branches
oldRender429
previousRender61
render423Base
renderBase428 shadowed 算法列表 branch
renderBase424 shadowed 算法列表 / 数据集 / 训练任务 branches
```

and require live replacements, including:

```text
renderBase427 → renderOps427() for 自动标注及清洗
oldRender412 → 算法列表 / 数据集
renderBase428 → 训练任务
renderBase424 → 质量中心 / 视频切帧 only
```

Browser performance suites continue to cover algorithm list, training task and material/data behavior. Current accepted browser suite is 14/14.

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
4. Render must not resume route-state alias mutation.
5. Legacy v42.2/v42.4 `自动标注` route branches must stay absent; canonical route remains `renderBase427`.
6. `renderBase428` must remain training-only unless its training semantics are explicitly migrated first.
7. `renderBase424` must remain quality/video-only unless those semantics are explicitly migrated first.
8. No mother-model class inheritance on first training.
9. Explicit false/zero training settings survive end-to-end.
10. Trial/test inference must never receive GT labels.
11. Do not weaken duplicate-request/race/performance/Real Chrome tests.
12. TrainingDraftRuntime / TrainingLabelRuntime remain wrapper-free.
13. AutoLabel remains PollRegistry-only.
14. Video/source/training polling direct ownership must not regress.
15. Frontend CI is not A800/CUDA acceptance.

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