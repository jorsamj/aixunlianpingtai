# v42.25 技术债关闭总账

> **状态：ACTIVE / 技术债优先阶段**  
> **分支：`refactor/frontend-runtime-stabilization`**  
> **正式版本：`VERSION.txt` 仍为 `42.24.0`；不得提前发布 `v42.25.0`。**  
> **最近完整代码验收点：`1470bb9f0dd19e1be5d0695cd7f4de21173dd944`**  
> **Frontend Runtime Stabilization：run `34652823778`，frontend + Real Chrome 全绿。**  
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
| `baseSetPage417` mobile-sidebar wrapper | migrate to final navigation runtime | **IN PROGRESS** |
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
initial bootstrap setPage binding
→ baseSetPage417         mobile sidebar close
→ NavigationStability    outer runtime coordinator
   ├─ normalizeNavigationPage()
   ├─ PageRequestScope / navigation epoch
   ├─ PollRegistry before/after navigation
   ├─ waitForNavigationReady() → __v53InitPromise
   └─ persistUiState() → ui-state.js
```

已迁移到命名 runtime 的真实语义：

```text
自动标注 → 自动标注及清洗
startup snapshot / uiReady readiness gate
navigation persistence
```

readiness 时序合同：导航意图会先进入 PageRequestScope / PollRegistry beforeNavigate；若启动 snapshot 尚未完成，实际 `state.page`/render 必须等待 `__v53InitPromise`，完成后才调用 classic predecessor，并在实际导航完成后 align / afterNavigate / persist。

注意：v42.7 的 render-level `if(state.page==='自动标注')...` 仍属于后续 render-owner 技术债，不再承担 setPage ownership。

## 4. Current cache/build facts

```text
app.js cache                     42.25.55
main.mjs cache                   42.25.56
navigation-stability.js          422509
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
  # 历史文件名；当前同时禁止 v42.7 alias 与 setPageReady414 回归
tests/frontend/navigation-stability.test.mjs
tests/frontend/navigation-persistence.test.mjs
tests/frontend/ui-state.test.mjs
```

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

## 6. Latest acceptance — readiness retirement

```text
baseline old owner:
  commit 0adc46fe1fc9a75a6c69cff7615cdc7795419c89
  run    34652201043
  startup Real Chrome readiness contract PASS

double-owner equivalence:
  commit a618696e712dad29ea667896572e7952a25c530f
  run    34652478444
  frontend PASS / Real Chrome 12/12 PASS

final retirement:
  commit 1470bb9f0dd19e1be5d0695cd7f4de21173dd944
  run    34652823778
  syntax + permanent guards PASS
  all frontend unit tests PASS
  Real Chrome 12/12 PASS
```

该批证明：

1. `setPageReady414` 已从 `static/app.js` 物理删除；
2. readiness 由 `NavigationStability` 的 named `waitForNavigationReady` hook 接管；
3. `static/main.mjs` 明确将 `!state.uiReady && window.__v53InitPromise` 作为启动 gate；
4. request/poll intent 仍在 readiness wait 之前发生，实际 page mutation/render 在 gate resolve 后发生；
5. `baseSetPage417` 完整保留；
6. 临时 readiness migration helper/workflow 已物理删除；
7. 训练、轮询、算法列表、素材分页等全套浏览器回归无退化。

## 7. 下一批：`baseSetPage417` sidebar owner

当前 classic 语义只有：

```js
const baseSetPage417=window.setPage;
window.setPage=function(page){
  window.toggleMobileSidebarV37?.(false);
  return baseSetPage417?.(page);
};
```

`toggleMobileSidebarV37(false)` 的真实副作用：移除 `#sidebar.mobile-open` 与 `#sideBackdrop.show`。现有 Real Chrome 已锁定“导航后 sidebar/backdrop 关闭”。

下一批必须继续使用同一模式：

```text
A. 补/加强 unit 合同，锁定 sidebar close 在 actual predecessor invocation 前发生
B. 将 close 行为迁入 NavigationStability 的命名 before-navigation hook
C. 双 owner 等价期 unit + Real Chrome 全绿
D. 再物理删除 baseSetPage417
E. 永久 guard 禁止 numbered sidebar owner 回归
F. initial bootstrap setPage binding 暂不动，后续单独做 capture/liveness 审计
```

## 8. 后续顺序

```text
A. baseSetPage417 sidebar migration
B. initial bootstrap setPage binding liveness audit
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
