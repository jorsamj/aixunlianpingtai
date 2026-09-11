# v42.25 技术债关闭总账

> **状态：ACTIVE / 技术债优先阶段**  
> **分支：`refactor/frontend-runtime-stabilization`**  
> **正式版本：`VERSION.txt` 仍为 `42.24.0`；不得提前发布 `v42.25.0`。**  
> **最近完整代码验收点：`05abf71d067d4b1e08a2bdeeb9d7787e9fc06dd4`**  
> **Frontend Runtime Stabilization：run `34655960701`，frontend + Real Chrome 全绿。**  
> **更新日期：2026-09-12**

## 0. 接手入口

按顺序阅读：
1. `docs/TECH_DEBT_CLOSURE_V42_25.md`
2. `docs/CODEX_CURRENT_STATE.md`
3. `docs/frontend-legacy-audit.md`
4. `docs/FRONTEND_OWNER_MAP_V42_25.md`

当前优先级仍是技术债关闭；A800 RC 暂缓。未经用户明确允许，不得 merge `main`、改正式 `VERSION.txt`、tag 或 release。

## 1. 永久退休 surface

不得恢复为 truth source、bootstrap fallback、timer owner、polling shell、direct navigation owner 或 compatibility wrapper：

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
baseSetPage (V37 duplicate mobile-sidebar wrapper)
oldSetV39
oldSet42
set422Base
v34 window.setPage(...saveUiState...)
v35 window.setPage(state.page/render)
v42.4 window.setPage(state.page/render)
v42.7 direct window.setPage auto-label alias owner
setPageReady414
baseSetPage417
initial bootstrap function setPage(p){state.page=p;render()} / window.setPage=setPage
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

`static/app.js` 当前不得再定义任何 `window.setPage=` owner。最终导航链：

```text
window.setPage = NavigationStability.stableSetPage
  → normalizeNavigationPage()
  → PageRequestScope.navigate / navigation epoch
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

关键合同：named `performNavigation` 配置后不得再调用 classic predecessor；一次导航只允许一次 page mutation / render。runtime 即使没有 classic predecessor，也必须自行安装 `window.setPage`。

## 4. Current cache/build facts

```text
app.js cache                     42.25.57
main.mjs cache                   42.25.59
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
```

主 CI `Retired navigation setPage guard` 当前要求：
- `static/app.js` 不得出现任何 `window.setPage=` classic owner；
- `setPageReady414` / `baseSetPage417` / bootstrap binding 不得回归；
- `normalizeNavigationPage`、`waitForNavigationReady`、`beforeInvokeNavigation`、`performNavigation` 必须存在；
- `main.mjs` 必须继续明确接入 readiness、sidebar cleanup、`state.page = page; render()` named apply。

Browser：

```text
tests/browser/navigation-stability.spec.mjs
tests/browser/navigation-readiness.spec.mjs
```

Real Chrome 锁定：stale request fencing、managed polling 离页停止、sidebar/backdrop close、页面持久化/reload、legacy alias canonicalization、startup readiness，以及 inline 菜单 / programmatic `window.setPage` 的真实导航路径。

## 6. Latest acceptance — initial bootstrap setPage retirement

```text
named actual-owner equivalence:
  commit 04b6982eb50d7afd95ca62517240ed0f7e49f135
  run    34655575856
  frontend PASS / Real Chrome PASS

physical retirement:
  bot commit 1f3e53c5f91f9478b2bad74a07d545af51f99f9b
  focused exact deletion + navigation tests PASS

final cleaned acceptance:
  commit 05abf71d067d4b1e08a2bdeeb9d7787e9fc06dd4
  run    34655960701
  syntax + permanent navigation guards PASS
  all frontend unit tests PASS
  Real Chrome PASS
```

该批证明：
1. 最后一条 classic bootstrap `setPage` 已从 `static/app.js` 物理删除；
2. `performNavigation` 是唯一 actual page mutation/render owner；
3. runtime 无 predecessor 仍会安装全局 `window.setPage`；
4. inline 菜单和 programmatic `window.setPage` 在真实 Chrome 中继续工作；
5. readiness、sidebar、PollRegistry、request fencing、persistence 无退化；
6. 两组 bootstrap 一次性 migration helper/workflow 已全部物理删除；
7. classic `setPage` owner family 当前可以视为 **zero-point CLOSED**。

## 7. 下一批：render override owner audit

下一目标不是盲删 `render()`，而是建立最终 renderer capture/liveness 表。优先审计：

```text
render = ... / const xxx=render 捕获链
v42.7 render-level 自动标注 → 自动标注及清洗 fallback
renderXXX412 / 417 / 423 / 424 / 425 / 427 / 428 / 429
NavigationStability PAGE_RENDERERS guards
```

执行顺序：
1. 枚举所有 `render` 赋值/捕获和最终调用链；
2. 区分全局 shell render、page renderer、已被后层完全覆盖的 dead generation；
3. 先给真实语义补 unit/Chrome 合同；
4. 迁入 bounded semantic owner 后再做物理删除；
5. 每刀保持 `render()` 启动路径、导航、局部刷新、表单/滚动/选择状态不退化。

特别注意：v42.7 render-level alias fallback 仍是已知 render-chain debt。setPage alias 已 canonicalize，因此可优先证明该 fallback 是否已冗余，但不得无测试直接删。

## 8. 后续顺序

```text
A. render override owner audit / obsolete layer deletion
B. app.js dead code + global reload/request debt
C. cache-busting unification
D. MutationObserver/timer/fetch/render/setPage zero-point scan
E. semantic naming + deterministic test cleanup
F. technical-debt zero-point scan
G. A800 RC
```

## 9. 发布禁令

正式 `v42.25.0` 前必须：技术债无未解决 P0/P1、Frontend Runtime 与 Release Regression 全绿、A800 preflight/首训/迭代/worker fencing 实机全绿，并取得用户明确 merge/version/tag/release 授权。
