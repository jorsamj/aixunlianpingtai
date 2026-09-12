# v42.25 技术债关闭总账

> **状态：ACTIVE / 技术债优先阶段**  
> **分支：`refactor/frontend-runtime-stabilization`**  
> **正式版本：`VERSION.txt` 仍为 `42.24.0`；不得提前发布 `v42.25.0`。**  
> **最近完整代码验收点：`6be679b6b23f566d14434e2032b8af8015341ae4`**  
> **Frontend Runtime Stabilization：run `34660269685`，frontend + Real Chrome 全绿。**  
> **更新日期：2026-09-12**

## 0. 接手入口

按顺序阅读：
1. `docs/TECH_DEBT_CLOSURE_V42_25.md`
2. `docs/CODEX_CURRENT_STATE.md`
3. `docs/frontend-legacy-audit.md`
4. `docs/FRONTEND_OWNER_MAP_V42_25.md`

当前优先级仍是技术债关闭；A800 RC 暂缓。未经用户明确允许，不得 merge `main`、改正式 `VERSION.txt`、tag 或 release。

## 1. 永久退休 surface

以下对象不得恢复为 truth source、bootstrap fallback、timer owner、polling shell、direct navigation owner 或 historical render owner：

```text
trainingLabelSelected
trainSplitV3
train429Selected
train428AlgorithmId
train428Config
trainingDraftFromLegacyState
auto422Timer
ai60ListTimer
__videoFramePollTimer
__prelabelPollTimer
_oldSetupPollV33
source422Timer
jobPollTimer
setupPagePolling
installVideo424CreationBridge
installSourceCreationBridge
installPollingCreationBridge
__pollRegistryVideoWrapped
__pollRegistrySourceWrapped
__pollRegistryCreationWrapped
originalSetupPagePolling / wrappedSetupPagePolling
registry.adopt('training-jobs', ...)
adoptLegacy / rebindCreation
set423Base
setBase424
baseSetPage
oldSetV39
oldSet42
set422Base
v34/v35/v42.4 direct window.setPage owners
v42.7 direct window.setPage auto-label alias owner
setPageReady414
baseSetPage417
initial bootstrap function setPage(p){state.page=p;render()} / window.setPage=setPage
v42.7 render-level state.page 自动标注 → 自动标注及清洗 mutation
oldRender429
previousRender61
render423Base
renderBase428 的 shadowed 算法列表 branch
```

## 2. 技术债状态

| 技术债 | 最终 owner / 目标 | 状态 |
|---|---|---|
| training 历史 mirror | `state.trainingDraft` | **CLOSED** |
| `/train/start` 多 owner / readiness | `TrainingSubmitRuntime` | **CLOSED** |
| `/jobs` 重复请求 race | `TrainingTaskRuntime` | **CLOSED** |
| metrics SQLite FD | deterministic close | **CLOSED** |
| training / AutoLabel / video / source polling | named runtime + `PollRegistry` | **CLOSED** |
| `setupPagePolling` / classic polling compatibility | direct managed owners | **CLOSED** |
| classic `setPage` owner family | `NavigationStability` | **CLOSED** |
| navigation alias/readiness/sidebar/apply/persistence | `NavigationStability` + `ui-state.js` | **CLOSED** |
| historical persisted `自动标注` alias | restore-boundary canonicalization | **CLOSED** |
| fully shadowed render generations (`oldRender429`, `previousRender61`, `render423Base`) | later bounded render owners | **CLOSED** |
| shadowed `renderBase428` 算法列表 branch | `oldRender412` sole algorithm-list route owner | **CLOSED** |
| remaining historical render overrides | bounded semantic owners | **IN PROGRESS** |
| `app.js` dead code | bounded shell + named runtimes | **IN PROGRESS** |
| global reload / duplicate request | scoped refresh | **OPEN** |
| cache-busting | single strategy | **OPEN** |
| observer/timer/fetch/render lifecycle | explicit owner + destroy | **OPEN** |
| version-number business naming | semantic names | **OPEN** |
| A800 RC | acceptance runbook | **DEFERRED** |

## 3. Canonical owners

### Training

```text
train-v3 UI
→ state.trainingDraft
→ TrainingDraftRuntime
→ TrainingSubmitRuntime
→ POST /api/v12/projects/{project_id}/train/start
```

### Polling

```text
training-jobs → PollRegistry + TrainingTaskRuntime
AutoLabel      → AutoLabelPollRuntime + PollRegistry
video          → PollRegistry(video-frames)
sources        → PollRegistry(sources)
```

### Navigation

`static/app.js` 当前不得再定义任何 `window.setPage=` owner：

```text
window.setPage = NavigationStability.stableSetPage
  → normalizeNavigationPage()
  → PageRequestScope / navigation epoch
  → PollRegistry.beforeNavigate
  → waitForNavigationReady() / __v53InitPromise
  → beforeInvokeNavigation() / toggleMobileSidebarV37(false)
  → performNavigation(page)
       state.page = page
       render()
  → PageRequestScope.alignPage
  → PollRegistry.afterNavigate
  → persistUiState()
```

历史 localStorage 中的 `自动标注` 在 v34 restore boundary 先 canonicalize 为 `自动标注及清洗`，随后写回 storage；render 本身不再修改 route state。

### Render — 当前已确认的 live owner

当前不能误删：

```text
oldRender412   → 算法列表 / 数据集稳定路由 owner
renderBase428  → 仅保留训练任务路由 owner
renderTraining423 → 当前训练页 renderer，并直接调用 PollRegistry.replaceTrainingJobTimer()
finalRender    → 素材存储配置最终路由 owner
```

已证明并物理删除：

```text
v42.7 render alias state mutation
oldRender429
previousRender61
render423Base
renderBase428 中被 oldRender412 完全遮蔽的 算法列表 branch
```

## 4. Current cache/build facts

```text
app.js cache                     42.25.62
main.mjs cache                   42.25.65
navigation-stability.js          422511
ui-state.js                      422500
poll-registry.js                 422511
training-draft-runtime.js        422516
training-labels.js               422513
auto-label-poll-runtime.js       422501
TrainingSubmitRuntime            training-submit-422504
TrainingTaskRuntime              training-task-runtime-422503
```

Cache-busting 仍未统一。

## 5. 永久合同

Frontend：

```text
tests/frontend/retired-sidebar-setpage-guard.test.mjs
tests/frontend/retired-pre-v424-setpage-guard.test.mjs
tests/frontend/navigation-stability.test.mjs
tests/frontend/navigation-persistence.test.mjs
tests/frontend/ui-state.test.mjs
tests/frontend/render-alias-restore.test.mjs
tests/frontend/render-owner-retirement.test.mjs
```

永久要求：
- `static/app.js` 不得出现任何 classic `window.setPage=` owner；
- render 不得重新承担 `自动标注` route canonicalization；
- `oldRender429` / `previousRender61` / `render423Base` 不得回归；
- `renderBase428` 不得重新出现其 shadowed 算法列表 branch，只允许保留训练任务 branch；
- `oldRender412` 仍是唯一 outer 算法列表 route owner；
- `renderTraining423()` 必须保持 direct PollRegistry training-job ownership；
- `finalRender` 当前仍是 live storage owner，不得无证明删除。

Browser：

```text
tests/browser/navigation-stability.spec.mjs
tests/browser/navigation-readiness.spec.mjs
```

Real Chrome 当前锁定 stale request fencing、managed polling、sidebar、页面持久化、legacy alias、新旧 localStorage 冷启动 canonicalization、素材存储配置最终 owner，以及算法列表/训练任务/素材分页性能路径。

## 6. Recent render acceptance history

```text
historical auto-label restore bug baseline:
  commit 582b913e6643689b00462b1b3bc0154a43a94995
  run    34656484008
  frontend PASS / Chrome 12 PASS + 1 FAIL
  failure: UI canonical，但 localStorage 仍保留 自动标注

alias restore-boundary fix + render mutation retirement:
  commit e35a29b0ded0bf81a5c0f968b07d535472b07f30
  run    34656747269
  frontend PASS / Real Chrome PASS

oldRender429 retirement:
  final  0455eeef696f19457b0f1a2b79e229a7e381b3db
  run    34659041402
  frontend PASS / Real Chrome PASS

storage final-owner browser baseline:
  commit 00721975e9ca95fba9c65b1bf04bde83ef50a654
  run    34659361434
  frontend PASS / Real Chrome PASS

previousRender61 retirement:
  final  69732d9ed659a62a3a1e92b36d07b912e141b8c9
  run    34659543452
  frontend PASS / Real Chrome PASS

render423Base retirement:
  final  58ece59e95722437069c7e03277363197e564136
  run    34659775870
  frontend PASS / Real Chrome PASS

renderBase428 shadowed algorithm branch retirement:
  product da238c7aa3bdc29cb3cc9cd4657dd6e4945f1afc
  validation 60b14108c4477b44912bfc37e945580f627f50c9
  cleaned HEAD 6be679b6b23f566d14434e2032b8af8015341ae4
  run    34660269685
  frontend PASS / Real Chrome PASS
```

对应一次性 migration helper/workflow 已在验收后物理删除；永久 tests 保留。

## 7. 下一批：remaining render owner audit

本轮到此停止，不继续开启下一刀。后续恢复时仍按 capture/liveness 证明推进，重点审计：

```text
baseRenderV37       页面增强 requestAnimationFrame owner
oldRenderV39        部署相关 route owner
renderBase424       质量/数据/视频/自动标注等 route owner
render426base       文件输入美化 post-render owner
renderBase427       自动标注及清洗 route owner
renderBase428       训练任务 live owner（当前不能整层删除）
oldRender412        算法/数据 live owner
render414Base       标签管理 + version badge owner
baseRender417       版本 badge/footer correction owner
finalRender         素材存储配置 live owner
cleanup MutationObserver / post-render cleanup wrapper
```

执行规则：
1. 先证明 exact source order、capture/reference 和 page coverage；
2. 对 live 语义先补 unit/Chrome；
3. 只删除 fully shadowed generation/branch；
4. 语义迁移必须先 double-owner equivalence；
5. 每刀 full frontend + Real Chrome；
6. 不允许通过放宽测试换取删除成功。

## 8. 后续顺序

```text
A. remaining render override owner audit / obsolete layer deletion
B. app.js dead code + global reload/request debt
C. cache-busting unification
D. MutationObserver/timer/fetch/render/setPage zero-point scan
E. semantic naming + deterministic test cleanup
F. technical-debt zero-point scan
G. A800 RC
```

## 9. 发布禁令

正式 `v42.25.0` 前必须：技术债无未解决 P0/P1、Frontend Runtime 与 Release Regression 全绿、A800 preflight/首训/迭代/worker fencing 实机全绿，并取得用户明确 merge/version/tag/release 授权。
