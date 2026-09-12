# Frontend Final-Owner Map — v42.25

> Branch: `refactor/frontend-runtime-stabilization`  
> Status: ACTIVE AUDIT  
> Latest fully accepted code point: `66339fc0b8459328a68bf775230eae179a4d969d` / run `34663089996`  
> Real Chrome: 14/14 passed  
> Authority: `docs/TECH_DEBT_CLOSURE_V42_25.md`

## 1. Purpose

This map exists to delete historical frontend overrides without changing current behavior. Preserve live semantics, not version-era wrapper count. `static/app.js` remains a historical append-only chain; later assignments can completely shadow earlier layers or individual branches.

## 2. Runtime ownership

```text
static/app.js bounded classic render/page shell
→ static/main.mjs
   → PageRequestScope
   → PollRegistry
   → NavigationStability
   → named runtimes
```

Navigation ownership is already fully outside the classic `setPage` family. Current cleanup target is the remaining render capture/override chain.

## 3. Closed owner batches

### Navigation / polling

```text
training/job polling compatibility              CLOSED
set423Base + setBase424                         CLOSED
V37 duplicate sidebar setPage                   CLOSED
oldSetV39 + oldSet42 + set422Base               CLOSED
v34/v35/v42.4 direct setPage family             CLOSED
v42.7 direct alias setPage                      CLOSED
setPageReady414                                 CLOSED
baseSetPage417                                  CLOSED
initial bootstrap setPage                       CLOSED
```

`static/app.js` now contains zero classic `window.setPage=` assignments.

### Render

| Batch | Physically retired | Accepted code / run |
|---|---|---|
| R1 | v42.7 render-level auto-label alias mutation | `e35a29b0...` / `34656747269` |
| R2 | `oldRender429` | `0455eeef...` / `34659041402` |
| R3 | `previousRender61` | `69732d9e...` / `34659543452` |
| R4 | `render423Base` | `58ece59e...` / `34659775870` |
| R5 | shadowed `renderBase428` 算法列表 branch | `6be679b6...` / `34660269685` |
| R6 | v42.2 + v42.4 legacy `自动标注` render route branches | `66339fc0...` / `34663089996` |

Each accepted batch passed frontend unit + Real Chrome. R6 Real Chrome executed 14 tests and passed 14/14. Temporary migration helpers/workflows were removed after success.

## 4. Current final navigation owner

```text
window.setPage = NavigationStability.stableSetPage
  → normalizeNavigationPage
  → PageRequestScope / epoch
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

Historical localStorage `自动标注` values are canonicalized at restore time and immediately written back as `自动标注及清洗`. Render no longer mutates route alias state. The older v42.2/v42.4 route branches keyed to `自动标注` are now physically absent.

## 5. Current visible owner map

| Surface | Current live owner | Required semantics | Proof |
|---|---|---|---|
| Navigation coordination | `NavigationStability` | request epoch, readiness, sidebar cleanup, actual apply, persistence | unit + Real Chrome |
| Training submit | `TrainingSubmitRuntime` | sole `/train/start`, canonical draft/readiness | unit + Chrome |
| Training jobs request | `TrainingTaskRuntime` | focused `/jobs`, coalescing, force-fresh mutation | unit + browser performance |
| Training jobs timer | `PollRegistry(training-jobs)` + `renderTraining423` activation | managed cadence + navigation cleanup | unit + Chrome |
| AutoLabel route | `renderBase427 → renderOps427()` | canonical `自动标注及清洗`; no old-name render route owner | unit + Real Chrome alias contracts |
| AutoLabel polling | `AutoLabelPollRuntime + PollRegistry` | explicit activate/deactivate | unit + Chrome |
| Video | `PollRegistry(video-frames)` | one-shot row patch | unit + Chrome |
| Sources | `PollRegistry(sources)` | managed interval | unit + Chrome |
| Data/material | `MaterialPaginationRuntime61` + `oldRender412`/current renderer | pagination/card patch/annotation stability | browser performance |
| Algorithm list | `AlgorithmListRuntime` + `oldRender412`/current renderer | sole outer route, expand/refresh/version rows | browser performance + permanent guard |
| Training task page route | `renderBase428` | training-only route to current `renderTraining423` | browser performance + permanent guard |
| Storage configuration page route | `finalRender` | route to `renderStorageSources61` | dedicated Real Chrome contract |

## 6. Render topology — confirmed live / retired

### Confirmed live

```text
oldRender412
  算法列表 / 数据集 stable routing
  sole outer 算法列表 route owner

renderBase428
  仅保留 训练任务 routing
  its former 算法列表 branch has been physically removed

renderTraining423
  current training-page renderer
  directly activates PollRegistry training-jobs

renderBase427
  canonical 自动标注及清洗 route owner
  delegates to renderOps427()

finalRender
  素材存储配置 final route owner
```

### Physically retired because fully shadowed / unreachable

```text
oldRender429
  outer oldRender412 handled both of its special pages first

previousRender61
  outer finalRender handled its only special page first

render423Base
  oldRender412 handled 算法列表;
  renderBase428 handled 训练任务;
  no independent special page remained

renderBase428 算法列表 branch
  oldRender412 handled 算法列表 first;
  only the training branch remains live inside the wrapper

v42.2 render422 legacy 自动标注 route branch
v42.4 renderBase424 legacy 自动标注 route branch
  no reachable writer survives for the old route value;
  NavigationStability + restore boundary canonicalize to 自动标注及清洗;
  later renderBase427 owns the canonical route
```

The historical `renderAutoLabel424()` function still contains an old-name self-refresh predicate. It is not a route owner and was deliberately left untouched for a separate dead-code/lifecycle proof.

## 7. Remaining render audit targets

Independent liveness proof is still required for:

```text
baseRenderV37
  requestAnimationFrame page enhancement

oldRenderV39
  deploy conversion/artifact/resource/plugin routes

renderBase424
  quality/video live routes remain
  算法列表 / 数据集 / 训练任务 branches are next shadowing candidates

render426base
  post-render file input beautification

renderBase427
  canonical 自动标注及清洗 route is live; do not delete whole wrapper

renderBase428
  training-task route remains live; do not delete whole wrapper without semantic migration

render414Base
  标签管理 route + version badge behavior

baseRender417
  version badge/footer correction

post-render cleanup wrapper + MutationObserver
older base/global render generations still reachable through delegates
```

Next bounded proof target:

```text
renderBase424 算法列表 → later oldRender412
renderBase424 数据集   → later oldRender412
renderBase424 训练任务 → later renderBase428
```

Do not delete `renderBase424` as a whole: its `质量中心` and `视频切帧` semantics are still live. Do not delete an entire wrapper because one branch is shadowed. Split dead branches from live behavior only after behavior coverage exists.

## 8. Permanent proof currently active

Frontend:

```text
tests/frontend/retired-sidebar-setpage-guard.test.mjs
tests/frontend/retired-pre-v424-setpage-guard.test.mjs
tests/frontend/render-alias-restore.test.mjs
tests/frontend/render-owner-retirement.test.mjs
tests/frontend/navigation-stability.test.mjs
```

`render-owner-retirement.test.mjs` now explicitly requires:
- legacy v42.2/v42.4 `自动标注` route branches stay absent;
- canonical `自动标注及清洗` keeps `renderBase427 → renderOps427()` ownership;
- the old combined renderBase428 algorithm+training wrapper stays absent;
- the training-only renderBase428 wrapper remains present;
- `oldRender412` remains the sole outer algorithm-list route owner.

Browser:

```text
tests/browser/navigation-stability.spec.mjs
tests/browser/navigation-readiness.spec.mjs
tests/browser/algorithm-list-performance.spec.mjs
tests/browser/training-task-performance.spec.mjs
tests/browser/material-pagination-performance.spec.mjs
```

Current accepted Real Chrome suite: 14/14 passed in run `34663089996`.

## 9. Per-batch checklist

```text
live HEAD
→ exact reference/liveness/source-order proof
→ deterministic regression or browser contract
→ bounded physical deletion
→ permanent guard
→ syntax/focused unit
→ full frontend
→ Real Chrome
→ delete temporary migration artifacts
→ sync all four handoff docs
```

## 10. Release boundary

No `main` merge, `VERSION.txt` bump, tag/release or A800 acceptance claim is authorized by this cleanup. A800 RC remains deferred until current P0/P1 debt and zero-point scan are complete.