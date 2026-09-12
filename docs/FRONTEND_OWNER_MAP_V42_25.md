# Frontend Final-Owner Map — v42.25

> Branch: `refactor/frontend-runtime-stabilization`  
> Status: ACTIVE AUDIT  
> Latest fully accepted code point: `2d9bc0b30a72761d784cc57472eb50b158b8851f` / run `34663389819`  
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
| R7 | shadowed `renderBase424` 算法列表 / 数据集 / 训练任务 branches | `2d9bc0b3...` / `34663389819` |

Every accepted batch passed frontend unit + Real Chrome. R6 and R7 both ran 14 browser tests and passed 14/14. Temporary migration helpers/workflows were removed after success.

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

Historical localStorage `自动标注` values are canonicalized at restore time and immediately written back as `自动标注及清洗`. Render no longer mutates route alias state. The older v42.2/v42.4 route branches keyed to `自动标注` are physically absent.

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
| Data/material route | `oldRender412 → renderDatasets424()` | stable outer data route; no fallback to renderBase424 | unit + browser performance |
| Algorithm list route | `oldRender412 → renderAlgorithms423()` | sole outer algorithm route | browser performance + permanent guard |
| Training task page route | `renderBase428 → renderTraining423()` | training-only route | browser performance + permanent guard |
| Quality center route | `renderBase424 → renderQualityCenter424()` | live legacy route retained | permanent guard |
| Video slicing route | `renderBase424 → renderVideo424()` | live legacy route retained | permanent guard |
| Storage configuration page route | `finalRender` | route to `renderStorageSources61` | dedicated Real Chrome contract |

## 6. Render topology — confirmed live / retired

### Confirmed live

```text
oldRender412
  算法列表 / 数据集 stable routing

renderBase428
  训练任务 routing only

renderTraining423
  current training-page renderer
  directly activates PollRegistry training-jobs

renderBase427
  canonical 自动标注及清洗 route owner
  delegates to renderOps427()

renderBase424
  质量中心 / 视频切帧 route owner only

finalRender
  素材存储配置 final route owner
```

### Physically retired because fully shadowed / unreachable

```text
oldRender429
previousRender61
render423Base
renderBase428 算法列表 branch
v42.2 render422 legacy 自动标注 route branch
v42.4 renderBase424 legacy 自动标注 route branch
renderBase424 算法列表 branch
renderBase424 数据集 branch
renderBase424 训练任务 branch
```

R7 capture proof:

```text
算法列表: final chain reaches oldRender412 first → stop
数据集:   final chain reaches oldRender412 first → stop
训练任务: oldRender412 delegates → renderBase428 stops → renderBase424 unreachable
质量中心: no later owner intercepts → renderBase424 remains live
视频切帧: no later owner intercepts → renderBase424 remains live
```

The historical `renderAutoLabel424()` function still contains an old-name self-refresh predicate. It is not a route owner and remains for a separate dead-code/lifecycle proof.

## 7. Remaining render audit targets

Independent liveness proof is still required for:

```text
baseRenderV37
  requestAnimationFrame page enhancement

oldRenderV39
  deploy conversion/artifact/resource/plugin routes

render426base
  post-render file input beautification

render414Base
  标签管理 route + version badge behavior

baseRender417
  version badge/footer correction

post-render cleanup wrapper + MutationObserver
older base/global render generations still reachable through delegates
renderAutoLabel424 old-page self-refresh condition
```

Current bounded owners `renderBase424`, `renderBase427`, `renderBase428`, `oldRender412`, `finalRender` are not deletion candidates as whole wrappers without a new semantic migration proof.

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
- `renderBase428` stays training-only;
- `oldRender412` stays authoritative for algorithm/data routes;
- `renderBase424` cannot regain algorithm/data/training branches and must retain quality/video branches.

Browser:

```text
tests/browser/navigation-stability.spec.mjs
tests/browser/navigation-readiness.spec.mjs
tests/browser/algorithm-list-performance.spec.mjs
tests/browser/training-task-performance.spec.mjs
tests/browser/material-pagination-performance.spec.mjs
```

Current accepted Real Chrome suite: 14/14 passed in run `34663389819`.

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