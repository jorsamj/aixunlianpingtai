# v42.25 技术债关闭总账

> **状态：ACTIVE / 技术债优先阶段**  
> **分支：`refactor/frontend-runtime-stabilization`**  
> **正式版本：`VERSION.txt` 仍为 `42.24.0`；不得提前发布 `v42.25.0`。**  
> **最近完整代码验收点：`bdfb7ae692a197486dc61ed9919c5e18ae1bf9f4`**  
> **Frontend Runtime Stabilization：run `34645250462`，frontend + Real Chrome 全绿。**  
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
| `setPageReady414` startup readiness | migrate to named navigation runtime | **IN PROGRESS** |
| `baseSetPage417` mobile-sidebar wrapper | migrate after readiness | **OPEN** |
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

当前 live chain：

```text
initial bootstrap setPage binding
→ setPageReady414        startup snapshot/uiReady gate
→ baseSetPage417         mobile sidebar close
→ NavigationStability    outer runtime coordinator
   ├─ normalizeNavigationPage()
   ├─ PageRequestScope / navigation epoch
   ├─ PollRegistry before/after navigation
   └─ persistUiState() → ui-state.js
```

已迁移到命名 runtime 的 alias：

```text
自动标注 → 自动标注及清洗
```

`NavigationStability` 从导航开始就使用 canonical page，因此 `PageRequestScope`、`PollRegistry`、guard、底层 `setPage`、最终持久化都只看到 `自动标注及清洗`。

注意：v42.7 的 `render=function(){if(state.page==='自动标注')...}` 仍在 classic render 链中；它属于后续 render-owner 清理，不再是 setPage owner。

## 4. Current cache/build facts

```text
app.js cache                     42.25.54
main.mjs cache                   42.25.55
navigation-stability.js          422508
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

```text
tests/frontend/retired-sidebar-setpage-guard.test.mjs
tests/frontend/retired-pre-v424-setpage-guard.test.mjs
  # 文件名为历史名，当前已同时禁止 v42.7 direct alias owner 回归
tests/frontend/navigation-stability.test.mjs
tests/frontend/navigation-persistence.test.mjs
tests/frontend/ui-state.test.mjs
```

`tests/browser/navigation-stability.spec.mjs` 当前锁定：

```text
stale request 不得跳回旧页面
managed polling 离页停止
最终导航关闭 mobile sidebar/backdrop
页面选择持久化并在 reload 后恢复
legacy 自动标注 route 必须 canonicalize 为 自动标注及清洗并持久化 canonical 值
```

不得为了继续删 classic 代码而放宽这些合同。

## 6. Latest acceptance

```text
commit: bdfb7ae692a197486dc61ed9919c5e18ae1bf9f4
run:    34645250462

syntax / permanent owner guards   PASS
all frontend unit tests           PASS
Real Chrome runtime regressions   PASS
```

该验收点证明：

1. v42.7 direct `window.setPage` alias owner 已物理删除；
2. `normalizeNavigationPage()` 成为 alias 语义 owner；
3. `setPageReady414` 和 `baseSetPage417` 仍保留；
4. `自动标注` legacy route 在删除旧 owner 后仍真实进入并持久化为 `自动标注及清洗`；
5. 一次性 alias migration helper/workflow 已物理删除；
6. 训练、轮询、算法列表、素材分页等浏览器回归未退化。

## 7. 下一批：startup readiness

下一批只处理 `setPageReady414`，不同时动 sidebar wrapper。

当前真实语义：

```js
if (!state.uiReady && window.__v53InitPromise) {
  await window.__v53InitPromise;
}
return previousSetPage(page);
```

删除前必须先完成：

```text
A. 补真实浏览器合同：启动 snapshot 尚未 ready 时发起导航，页面不能提前切换
B. init Promise resolve 后必须只导航一次到用户请求页
C. PageRequestScope / PollRegistry / persistence 必须在正确时序收尾
D. 将 readiness 迁入 NavigationStability 或独立 named readiness hook
E. 双 owner 等价期 unit + Real Chrome 全绿
F. 再物理删除 setPageReady414 wrapper
```

现有 `navigation-persistence.test.mjs` 只覆盖模块级异步 predecessor，**尚不能替代真实 startup/browser readiness 合同**。

## 8. 后续顺序

```text
A. setPageReady414 readiness migration
B. baseSetPage417 sidebar migration
C. remaining render override owner audit / obsolete layer deletion
D. app.js dead code + global reload/request debt
E. cache-busting unification
F. MutationObserver/timer/fetch/render/setPage zero-point scan
G. semantic naming + deterministic test cleanup
H. technical-debt zero-point scan
I. A800 RC
```

## 9. 发布禁令

正式 `v42.25.0` 前必须：技术债无未解决 P0/P1、Frontend Runtime 与 Release Regression 全绿、A800 preflight/首训/迭代/worker fencing 实机全绿，并取得用户明确 merge/version/tag/release 授权。
