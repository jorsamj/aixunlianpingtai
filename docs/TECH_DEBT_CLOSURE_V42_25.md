# v42.25 技术债关闭总账

> **状态：ACTIVE / 技术债优先阶段**  
> **分支：`refactor/frontend-runtime-stabilization`**  
> **正式版本：`VERSION.txt` 仍为 `42.24.0`；不得提前发布 `v42.25.0`。**  
> **最近完整代码验收点：`871b1c91d919760728fd74dc0e7abf7ac25b516f`**  
> **Frontend Runtime Stabilization：run `34618276191`，frontend + Real Chrome 全绿。**  
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

### AutoLabel / Video / Sources

```text
renderOps427 → AutoLabelPollRuntime → PollRegistry(auto-label-v60)
renderVideo424 / refreshVideo424Delta → replaceVideo424Timer() → PollRegistry(video-frames)
renderSources422 → replaceSourceTimer() → PollRegistry(sources)
```

均禁止恢复 classic timer/wrapper owner。

## 4. Current cache/build facts

```text
app.js cache                     42.25.50
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

当前主 CI 包含：

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
```

`Retired pass-through setPage guard` 要求：

- `set423Base` 为 0；
- `setBase424` 为 0；
- v42.4 直接 `window.setPage=function(p){state.page=p;render()}` owner 仍存在。

## 6. Latest acceptance

```text
commit: 871b1c91d919760728fd74dc0e7abf7ac25b516f
run:    34618276191

syntax                                      PASS
all permanent owner guards                  PASS
Retired pass-through setPage guard          PASS
frontend unit                               PASS
Real Chrome                                 PASS
```

Real Chrome 同时覆盖 navigation、training submit/task、AutoLabel、algorithm list、materials 等既有回归。

## 7. Current next task

当前 owner map 已证明：剩余 `setPage` wrapper 大多带真实语义，不允许按版本号机械删除。已观察到：

```text
set422Base        → 页面别名：新建算法/自动迭代 → 算法列表
baseSetPageV37    → 移动侧栏关闭
baseSetPage417    → 再次关闭移动侧栏（疑似与 V37 重复）
setPageReady414   → 等待启动 snapshot/uiReady
later wrappers    → cache invalidation / page alias / persistence / NavigationStability
```

下一候选：**证明并消除重复的 mobile-sidebar setPage wrapper**。当前 `baseSetPageV37` 与后来的 `baseSetPage417` 都关闭侧栏；若最终链上后者完全覆盖前者语义，则只删除更早的重复 wrapper，保留后者及所有其他路由行为。

执行规则：

```text
精确引用计数
→ 独立语义证明
→ focused navigation regression
→ bounded physical deletion
→ permanent guard
→ full frontend + Real Chrome
→ 四份文档同步
```

## 8. 后续顺序

```text
A. duplicate sidebar setPage wrapper
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
