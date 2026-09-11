# v42.25 技术债关闭总账

> **状态：ACTIVE / 技术债优先阶段**  
> **分支：`refactor/frontend-runtime-stabilization`**  
> **正式版本：`VERSION.txt` 仍为 `42.24.0`；不得提前发布 `v42.25.0`。**  
> **最近完整代码验收点：`f3eb6b360123dd688eea4dd0f29c05a9db5b4c05`**  
> **Frontend Runtime Stabilization：run `34619698115`，frontend + Real Chrome 全绿。**  
> **更新日期：2026-09-11**

## 0. 接手入口

按顺序阅读：

1. `docs/TECH_DEBT_CLOSURE_V42_25.md`
2. `docs/CODEX_CURRENT_STATE.md`
3. `docs/frontend-legacy-audit.md`
4. `docs/FRONTEND_OWNER_MAP_V42_25.md`

规则：先清技术债，再恢复 A800 RC；未经用户明确允许，不得 merge `main`、改正式 `VERSION.txt`、tag 或 release。

## 1. 永久退休 surface

不得恢复为 truth source、bootstrap fallback、timer owner、polling shell 或 compatibility wrapper：

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
```

## 2. 技术债状态

| 技术债 | 最终 owner / 目标 | 状态 |
|---|---|---|
| training 历史 mirror | `state.trainingDraft` | **CLOSED** |
| `/train/start` 多 owner / readiness | `TrainingSubmitRuntime` | **CLOSED** |
| `/jobs` 重复请求 race | `TrainingTaskRuntime` | **CLOSED** |
| metrics SQLite FD | deterministic close | **CLOSED** |
| training task polling | `TrainingTaskRuntime + PollRegistry` | **CLOSED** |
| AutoLabel polling | `AutoLabelPollRuntime + PollRegistry` | **CLOSED** |
| video polling | direct `PollRegistry(video-frames)` | **CLOSED** |
| source polling | direct `PollRegistry(sources)` | **CLOSED** |
| training polling wrapper/state timer | direct `PollRegistry(training-jobs)` | **CLOSED** |
| `setupPagePolling` shells | direct `replaceTrainingJobTimer()` call sites | **CLOSED** |
| v42.3 pass-through `setPage` + unused v42.4 capture | later direct router | **CLOSED** |
| duplicate V37 mobile-sidebar `setPage` wrapper | V417 `baseSetPage417` owner | **CLOSED** |
| historical render/setPage overrides | semantic final router + bounded render owners | **IN PROGRESS** |
| `app.js` dead code | bounded shell + named runtimes | **IN PROGRESS** |
| cache-busting | single strategy | **OPEN** |
| global reload / duplicate request | scoped refresh | **OPEN** |
| observer/timer/fetch/render lifecycle | explicit owner + destroy | **OPEN** |
| version-number business naming | semantic names | **OPEN** |
| A800 RC | acceptance runbook | **DEFERRED** |

## 3. Current owner contracts

### Training submit

```text
train-v3 UI
→ state.trainingDraft
→ TrainingDraftRuntime
→ TrainingSubmitRuntime
→ POST /api/v12/projects/{project_id}/train/start
```

### Training task polling

```text
classic render call site
→ PollRegistryRuntime.replaceTrainingJobTimer()
→ PollRegistry(training-jobs, 2000ms active / 5000ms idle)
→ TrainingTaskRuntime.refresh({render:true, source:'poll'})
→ focused /jobs update
```

`jobPollTimer`、`setupPagePolling`、PollRegistry creation wrapper/adopt/rebind compatibility 均已物理删除。

### Mobile navigation

当前 classic sidebar-close owner：

```text
baseSetPage417 = window.setPage
→ window.setPage(page)
   → toggleMobileSidebarV37(false)
   → baseSetPage417(page)
→ NavigationStability outer wrapper
```

V37 更早的重复 wrapper 已物理删除。Real Chrome 已锁定合同：手动打开 `sidebar.mobile-open + sideBackdrop.show` 后调用最终 `window.setPage('数据集')`，两者必须关闭。

### AutoLabel / Video / Sources

```text
renderOps427 → AutoLabelPollRuntime → PollRegistry(auto-label-v60)
renderVideo424 / refreshVideo424Delta → replaceVideo424Timer() → PollRegistry(video-frames)
renderSources422 → replaceSourceTimer() → PollRegistry(sources)
```

均禁止恢复 classic timer/wrapper owner。

## 4. Current cache/build facts

```text
app.js cache                     42.25.51
main.mjs cache                   42.25.53
navigation-stability.js          422506
poll-registry.js                 422511
training-draft-runtime.js        422516
training-labels.js               422513
auto-label-poll-runtime.js       422501
TrainingSubmitRuntime            training-submit-422504
TrainingTaskRuntime              training-task-runtime-422503
```

Cache-busting 仍未统一。

## 5. Permanent guards

主 CI 当前包含：

```text
Retired training mirror guard
Canonical training network owner guard
TrainingDraft classic wrapper guard
TrainingLabel canonical lifecycle guard
AutoLabel PollRegistry owner guard
Retired legacy poll timer compatibility guard
Video PollRegistry direct owner guard
Source PollRegistry direct owner guard
Training PollRegistry direct owner guard
Retired pass-through setPage guard
Frontend unit tests
```

额外永久静态合同：

```text
tests/frontend/retired-sidebar-setpage-guard.test.mjs
```

它要求 V37 `baseSetPage` wrapper 为 0，同时 V417 `baseSetPage417` sidebar-close owner 必须保留。

Real Chrome 合同位于：

```text
tests/browser/navigation-stability.spec.mjs
→ final navigation owner closes the mobile sidebar and backdrop
```

## 6. Latest acceptance

```text
commit: f3eb6b360123dd688eea4dd0f29c05a9db5b4c05
run:    34619698115

syntax                                      PASS
all permanent owner guards                  PASS
frontend unit incl. sidebar static guard    PASS
Real Chrome                                 PASS
mobile-sidebar navigation contract          PASS
```

## 7. Current next task — pre-v42.4 dead setPage family

只读审计发现以下历史 wrappers 都只在自身 IIFE 中“捕获 previous owner → 包一层 → 自己调用 previous owner”，而后续 v42.4 存在**不调用 previous owner 的直接重置**：

```text
oldSetV39
  部署页面时 state.deployLoaded=false

oldSet42
  v42 页面时 state.v42.loaded=false

set422Base
  新建算法 / 自动迭代 → 算法列表
```

随后 v42.4：

```js
window.setPage=function(p){state.page=p;render()};
```

该直接赋值会切断此前 wrapper chain。若没有其他函数保存这些 wrapper 引用，则它们在最终 app load 后属于 dead code，而不是 live semantics owner。

下一批必须先证明：

```text
1. oldSetV39 / oldSet42 / set422Base 各自只存在声明+自身调用
2. v42.4 direct reset 在它们之后同步执行
3. 最终用户可见页面别名、deploy cache、navigation 行为由后续 router/render 或当前 runtime 覆盖
4. 删除后现有 navigation/performance/Real Chrome 全绿
```

**禁止把 `setPageReady414`、`baseSetPage417`、NavigationStability 或任何仍在最终链上的 later wrapper 一起删除。**

## 8. 后续顺序

```text
A. pre-v42.4 dead setPage family
B. remaining render/setPage obsolete layers
C. app.js dead code + global reload/request debt
D. cache-busting unification
E. MutationObserver/timer/fetch/render/setPage zero-point scan
F. semantic naming + deterministic test cleanup
G. technical-debt zero-point scan
H. A800 RC
```

## 9. 发布禁令

正式 `v42.25.0` 前必须：技术债无未解决 P0/P1、Frontend Runtime 与 Release Regression 全绿、A800 preflight/首训/迭代/worker fencing 实机全绿，并取得用户明确 merge/version/tag/release 授权。
