# v42.25 技术债关闭总账

> **状态：ACTIVE / 技术债优先阶段**  
> **分支：`refactor/frontend-runtime-stabilization`**  
> **正式版本：`VERSION.txt` 仍为 `42.24.0`；不得提前发布 `v42.25.0`。**  
> **最近完整代码验收点：`f6e71c05d35b1a39b0b79e1b652cf901044c68bd`**  
> **Frontend Runtime Stabilization：run `34653776200`，frontend + Real Chrome 12/12 全绿。**  
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
setPageReady414 classic startup-readiness wrapper
baseSetPage417 classic mobile-sidebar wrapper
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
| old pass-through / duplicate setPage layers | later/final navigation owner | **CLOSED** |
| pre-v42.7 direct setPage family | semantic navigation runtime | **CLOSED** |
| v42.7 direct alias owner | `normalizeNavigationPage()` | **CLOSED** |
| navigation UI state persistence | `NavigationStability` + `ui-state.js` | **CLOSED** |
| `setPageReady414` startup readiness | `NavigationStability.waitForNavigationReady` | **CLOSED** |
| `baseSetPage417` mobile-sidebar wrapper | `NavigationStability.beforeInvokeNavigation` | **CLOSED** |
| initial bootstrap `setPage` | migrate actual page mutation/render into named navigation owner | **IN PROGRESS** |
| remaining historical render overrides | bounded semantic owners | **IN PROGRESS** |
| `app.js` dead code | bounded shell + named runtimes | **IN PROGRESS** |
| cache-busting | single strategy | **OPEN** |
| global reload / duplicate request | scoped refresh | **OPEN** |
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

当前 live chain 已缩减为：

```text
initial bootstrap function setPage(p){ state.page=p; render(); }
→ NavigationStability final coordinator
   ├─ normalizeNavigationPage()
   ├─ PageRequestScope / navigation epoch
   ├─ PollRegistry before/after navigation
   ├─ waitForNavigationReady() → __v53InitPromise
   ├─ beforeInvokeNavigation() → toggleMobileSidebarV37(false)
   ├─ predecessor actual page mutation/render
   └─ persistUiState() → ui-state.js
```

已迁移到 named runtime 的真实语义：

```text
自动标注 → 自动标注及清洗
startup snapshot / uiReady readiness gate
mobile sidebar/backdrop close
navigation persistence
```

关键时序合同：

```text
request:navigate
→ poll:before
→ readiness wait
→ beforeInvokeNavigation (close sidebar/backdrop)
→ actual page mutation/render
→ request:align
→ poll:after
→ persistence
```

启动 `window.__clInit` 直接通过 `render()` 完成初始化，不依赖 `setPage()`；初始 bootstrap binding 当前仍然活跃，是 `NavigationStability` 捕获的实际 page mutation/render predecessor，同时提供全局 `setPage` 入口。下一批必须先迁移这两项职责，再允许删除 bootstrap binding。

注意：v42.7 的 render-level `if(state.page==='自动标注')...` 仍属于后续 render-owner 技术债，不再承担 setPage ownership。

## 4. Current cache/build facts

```text
app.js cache                     42.25.56
main.mjs cache                   42.25.57
navigation-stability.js          422510
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

永久 guard 当前明确要求：
- `setPageReady414` 不得回归；
- `baseSetPage417` 不得回归；
- named `waitForNavigationReady` 必须存在；
- named `beforeInvokeNavigation` 必须存在；
- `main.mjs` 必须继续将 sidebar close 接入 named hook；
- 初始 bootstrap `setPage` 当前必须保留，直到其独立迁移批次完成。

Browser：

```text
tests/browser/navigation-stability.spec.mjs
tests/browser/navigation-readiness.spec.mjs
```

Real Chrome 当前锁定：

```text
stale request 不得跳回旧页面
managed polling 离页停止
最终导航关闭 mobile sidebar/backdrop
页面选择持久化并在 reload 后恢复
legacy 自动标注 route canonicalize 为 自动标注及清洗
startup snapshot pending 时页面不得提前切换
startup ready 后导航只完成一次并持久化请求页
```

不得为了继续删 classic 代码而放宽这些合同。

## 6. Latest acceptance — V417 sidebar retirement

```text
readiness final baseline:
  commit 1470bb9f0dd19e1be5d0695cd7f4de21173dd944
  run    34652823778
  frontend PASS / Real Chrome 12/12 PASS

sidebar double-owner equivalence:
  commit d6b9e459ef132a77e95410d628f60ce5c5e16177
  run    34653340984
  frontend PASS / Real Chrome 12/12 PASS

sidebar final retirement:
  commit f6e71c05d35b1a39b0b79e1b652cf901044c68bd
  run    34653776200
  syntax + permanent navigation guards PASS
  all frontend unit tests PASS
  Real Chrome 12/12 PASS
```

该批证明：

1. `baseSetPage417` 已从 `static/app.js` 物理删除；
2. sidebar/backdrop 关闭由 `NavigationStability.beforeInvokeNavigation` 接管；
3. named cleanup 保持旧语义时序：readiness resolve 后、actual predecessor invocation 前执行；
4. 初始 bootstrap `setPage` 在本批保持不变；
5. 两份历史 navigation guard 均已升级到“V417 必须为 0 + named hook 必须存在”；
6. 主 CI 永久导航 guard 已同步；
7. 临时 V417 migration helper/workflow 已物理删除；
8. 全套浏览器回归无退化。

## 7. 下一批：initial bootstrap `setPage` capture/liveness

当前唯一 classic `setPage` 定义：

```js
function setPage(p){
  state.page=p;
  render();
}
window.setPage=setPage;
```

已确认 liveness：

```text
A. NavigationStability 安装时当前仍 capture window.setPage 作为 predecessor
B. predecessor 的实际产品语义只有：state.page mutation + final classic render()
C. 全局/inline setPage 入口由最终 NavigationStability 覆盖，因此按钮最终走 named coordinator
D. startup __clInit 直接 render()，不依赖 setPage()
```

删除前必须完成：

```text
1. 为 NavigationStability 增加明确的 performNavigation/applyPage hook，承接 state.page mutation + render。
2. named runtime 在没有 classic predecessor 的情况下也必须安装 window.setPage。
3. unit 锁定 lifecycle → readiness → UI cleanup → apply page/render → finalize 时序。
4. 双 owner 期：classic predecessor 与 named apply hook 只能有一个真正 page mutation/render owner，禁止重复 render。
5. Real Chrome 锁定菜单点击、programmatic window.setPage、启动 readiness、sidebar、persistence 全部正常。
6. 等价全绿后物理删除 bootstrap function/binding，并升级永久 guard 为 bootstrap 必须为 0。
```

不能用 `state.page=...; render()` 散落回 classic app.js 作为替代 owner。

## 8. 后续顺序

```text
A. initial bootstrap setPage migration
B. remaining render override owner audit / obsolete layer deletion
C. app.js dead code + global reload/request debt
D. cache-busting unification
E. MutationObserver/timer/fetch/render/setPage zero-point scan
F. semantic naming + deterministic test cleanup
G. technical-debt zero-point scan
H. A800 RC
```

## 9. 发布禁令

正式 `v42.25.0` 前必须：技术债无未解决 P0/P1、Frontend Runtime 与 Release Regression 全绿、A800 preflight/首训/迭代/worker fencing 实机全绿，并取得用户明确 merge/version/tag/release 授权。
