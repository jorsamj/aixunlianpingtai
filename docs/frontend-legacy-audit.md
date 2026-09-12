# Frontend Legacy Runtime Audit

> Branch: `refactor/frontend-runtime-stabilization`  
> Authority: `docs/TECH_DEBT_CLOSURE_V42_25.md`  
> Goal: reduce classic `static/app.js` to bounded shell + named runtime owners before any future framework replacement.

## 1. Latest accepted code point

```text
commit: 66339fc0b8459328a68bf775230eae179a4d969d
run:    34663089996
frontend:     PASS
Real Chrome:  PASS (14/14)
```

Current caches/builds:

```text
app.js                    42.25.63
main.mjs                  42.25.66
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

A Real Chrome cold-start test first exposed the old persistence bug; the restore-boundary fix then passed fully.

After that boundary became canonical, two remaining old-name route branches were proven unreachable and physically removed:

```text
v42.2 render422:     if state.page === 自动标注 → renderAutoLabel422
v42.4 renderBase424: if state.page === 自动标注 → renderAutoLabel424
```

There is no direct `state.page='自动标注'` writer in active `app.js`. The old `renderAutoLabel424()` body still contains a legacy self-refresh condition keyed to that old page name; it is not a route owner and remains for a later dead-code/lifecycle audit rather than being broadened into this deletion.

### Fully shadowed classic render generations / branches

Physically retired and permanently guarded:

```text
oldRender429
previousRender61
render423Base
renderBase428 的 算法列表 branch
v42.2 render422 的 legacy 自动标注 route branch
v42.4 renderBase424 的 legacy 自动标注 route branch
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

renderBase428 算法列表 branch:
  later oldRender412 intercepts 算法列表 first;
  the wrapper itself remains live for 训练任务.

legacy 自动标注 route branches:
  both navigation requests and persisted historical page state are canonicalized to 自动标注及清洗;
  later renderBase427 owns that canonical route;
  neither old-name branch has a reachable page-state source.
```

Acceptance evidence:

```text
oldRender429             0455eeef... / 34659041402 PASS
storage baseline         00721975... / 34659361434 PASS
previousRender61         69732d9e... / 34659543452 PASS
render423Base            58ece59e... / 34659775870 PASS
renderBase428 alg branch 6be679b6... / 34660269685 PASS
legacy auto-label routes 66339fc0... / 34663089996 PASS (Chrome 14/14)
```

One-shot migration helpers/workflows were deleted after acceptance.

## 4. Current live render topology — partial map

These are confirmed live and must not be removed as whole layers without a new proof:

```text
oldRender412
  routes 算法列表 and 数据集
  now the sole outer 算法列表 route owner

renderBase428
  routes only 训练任务 after the shadowed algorithm branch was removed

renderTraining423
  current training renderer
  directly owns PollRegistry.replaceTrainingJobTimer()

renderBase427
  routes canonical 自动标注及清洗 to renderOps427()

finalRender
  routes 素材存储配置
```

Still under audit:

```text
baseRenderV37       post-render page enhancement
oldRenderV39        deployment routes
renderBase424       quality/video live routes + shadowing candidates
render426base       post-render file-input beautification
render414Base       标签管理 + version badge behavior
baseRender417       version badge/footer correction
post-render cleanup wrapper + MutationObserver
older base/global render generations reached through the chain
```

The next high-value bounded candidate is inside `renderBase424`, not the whole wrapper:

```text
算法列表 → later oldRender412 intercepts first
数据集   → later oldRender412 intercepts first
训练任务 → later renderBase428 intercepts first
```

`renderBase424` itself remains live because `质量中心` and `视频切帧` still route through it. A branch inside a live wrapper may be dead while the wrapper remains live. Delete branches/layers only after exact source-order and coverage proof.

## 5. Permanent contracts added for render cleanup

Frontend:

```text
tests/frontend/render-alias-restore.test.mjs
tests/frontend/render-owner-retirement.test.mjs
```

They currently prevent return of:

```text
render-level auto-label alias mutation
legacy v42.2/v42.4 自动标注 route branches
oldRender429
previousRender61
render423Base
renderBase428 shadowed 算法列表 branch
```

and require the live replacements, including `renderBase427 → renderOps427()` for canonical `自动标注及清洗`, `oldRender412` as sole outer algorithm route and `renderBase428` as training-only route wrapper.

Browser:

`tests/browser/navigation-stability.spec.mjs` includes real current/historical auto-label alias contracts and a real `素材存储配置` route contract. Existing browser performance suites continue to cover algorithm list, training task and material page behavior. Current accepted browser suite is 14/14.

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
7. No mother-model class inheritance on first training.
8. Explicit false/zero training settings survive end-to-end.
9. Trial/test inference must never receive GT labels.
10. Do not weaken duplicate-request/race/performance/Real Chrome tests.
11. TrainingDraftRuntime / TrainingLabelRuntime remain wrapper-free.
12. AutoLabel remains PollRegistry-only.
13. Video/source/training polling direct ownership must not regress.
14. Frontend CI is not A800/CUDA acceptance.

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