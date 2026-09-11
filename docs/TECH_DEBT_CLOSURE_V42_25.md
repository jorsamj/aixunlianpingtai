# v42.25 技术债关闭总账

> **状态：ACTIVE / 技术债优先阶段**  
> **分支：`refactor/frontend-runtime-stabilization`**  
> **正式版本：`VERSION.txt` 仍为 `42.24.0`，不得提前发布 `v42.25.0`。**  
> **最近完整代码验收点：`4cabbe84d7af37cc7cdf11aa2e8dc00db9be3386`**  
> **Frontend Runtime Stabilization：run `34617573070`，frontend + Real Chrome 全绿。**  
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
__pollRegistryVideoWrapped
installSourceCreationBridge
__pollRegistrySourceWrapped
installPollingCreationBridge
__pollRegistryCreationWrapped
originalSetupPagePolling / wrappedSetupPagePolling
registry.adopt('training-jobs', ...)
adoptLegacy / rebindCreation
```

## 2. 技术债状态

| ID | 技术债 | 最终 owner / 目标 | 状态 |
|---|---|---|---|
| TD-01~05 | training 历史 mirror | `state.trainingDraft` | **CLOSED** |
| TD-06~07 | `/train/start` / readiness 多 owner | `TrainingSubmitRuntime` | **CLOSED** |
| TD-08 | `/jobs` 重复请求 race | `TrainingTaskRuntime` | **CLOSED** |
| TD-09 | metrics SQLite FD | deterministic close | **CLOSED** |
| TD-10 | training task polling | `TrainingTaskRuntime + PollRegistry` | **CLOSED** |
| TD-11 | AutoLabel polling | `AutoLabelPollRuntime + PollRegistry` | **CLOSED** |
| TD-12 | video polling | direct `PollRegistry(video-frames)` | **CLOSED** |
| TD-13 | legacy auto/video/prelabel timer compatibility | named runtimes | **CLOSED** |
| TD-14A | source polling wrapper/state timer | direct `PollRegistry(sources)` | **CLOSED** |
| TD-14B | training polling wrapper/state timer | direct `PollRegistry(training-jobs)` | **CLOSED** |
| TD-14C1 | `setupPagePolling` historical shells | direct `replaceTrainingJobTimer()` call sites | **CLOSED** |
| TD-14C2 | historical render/setPage overrides | final owner table + physical deletion | **IN PROGRESS** |
| TD-15 | `app.js` dead code | bounded shell + named runtimes | **IN PROGRESS** |
| TD-17 | cache-busting | single strategy | **OPEN** |
| TD-18 | global reload / duplicate request | scoped refresh | **OPEN** |
| TD-19 | observer/timer/fetch/render lifecycle | explicit owner + destroy | **OPEN** |
| TD-20 | version-number business naming | semantic names | **OPEN** |
| TD-21 | flaky/historical tests | deterministic tests | **IN PROGRESS** |
| TD-22 | docs drift | 4 handoff docs | **IN PROGRESS** |
| TD-23 | A800 RC | acceptance runbook | **DEFERRED** |
| TD-24 | TrainingDraft/TrainingLabel wrappers | direct canonical lifecycle | **CLOSED** |

## 3. Current canonical owners

### Training submit

```text
train-v3 UI
→ state.trainingDraft
→ TrainingDraftRuntime
→ TrainingSubmitRuntime
→ POST /api/v12/projects/{project_id}/train/start
```

### Training task polling

Training polling is wrapper-free, state-timer-free and shell-free：

```text
classic render call site
→ PollRegistryRuntime.replaceTrainingJobTimer()
→ PollRegistry(training-jobs, 2000ms active / 5000ms idle)
→ TrainingTaskRuntime.refresh({render:true, source:'poll'})
→ focused /jobs update
```

Physically removed：

```text
state.jobPollTimer
classic setupPagePolling setInterval/clearInterval owner
setupPagePolling function/assignment shells
PollRegistry registry.adopt('training-jobs', ...)
installPollingCreationBridge
originalSetupPagePolling / wrappedSetupPagePolling
__pollRegistryCreationWrapped
adoptLegacy / rebindCreation
NavigationStability jobPollTimer fallback
```

永久 CI 现在要求 `setupPagePolling` 和 `jobPollTimer` 在 active product runtime 中均为 0。

### AutoLabel

```text
renderOps427
→ AutoLabelPollRuntime.activate()/deactivate()
→ PollRegistry(auto-label-v60)
→ managed one-shot refresh
```

### Video

```text
renderVideo424
→ PollRegistryRuntime.replaceVideo424Timer()
→ PollRegistry(video-frames, 2000ms one-shot)
→ refreshVideo424Delta
→ row patch
→ replaceVideo424Timer()
```

### Sources

```text
renderSources422
→ renderSourceRows422()
→ PollRegistryRuntime.replaceSourceTimer()
→ PollRegistry(sources, 2500ms managed interval)
→ refreshSources422()
```

## 4. Current version/cache facts

```text
app.js cache                     42.25.49
main.mjs cache                   42.25.53
navigation-stability.js          422506
poll-registry.js                 422511
training-draft-runtime.js        422516
training-labels.js               422513
auto-label-poll-runtime.js       422501
TrainingSubmitRuntime            training-submit-422504
TrainingTaskRuntime              training-task-runtime-422503
```

Cache-busting is still heterogeneous and remains debt.

## 5. Permanent frontend guards now active

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
```

Training guard requires：

- `jobPollTimer` 在 `static/app.js`、`poll-registry.js`、`navigation-stability.js` 为 0；
- `setupPagePolling` 在 active `static/app.js` 为 0；
- PollRegistry 不得恢复 training creation wrapper/adoption/rebind compatibility；
- `replaceTrainingJobTimer()` direct managed owner 和 app 直接 handoff 必须存在。

## 6. Latest acceptance

```text
commit: 4cabbe84d7af37cc7cdf11aa2e8dc00db9be3386
run:    34617573070

syntax                                      PASS
all permanent owner guards                  PASS
Training PollRegistry direct owner guard    PASS
frontend unit                               PASS
Real Chrome                                 PASS
```

该 Real Chrome run 同时覆盖 training label/submit、training task performance/manual refresh、navigation stability、AutoLabel、algorithm list、materials 等现有回归。

## 7. Current next exact task: setPage/render obsolete override closure

`docs/FRONTEND_OWNER_MAP_V42_25.md` 已建立最终 owner 图。当前静态审计确认：

```text
window.setPage=function...   10 个历史 assignment（Batch A 前统计）
render=function...           22 个历史 assignment
setupPagePolling             0 active 引用
```

第一个已证明的 setPage 删除候选：

```text
const set423Base=window.setPage;
window.setPage=function(p){set423Base(p)};
try{setPage=window.setPage}catch(e){}
```

理由：`set423Base` 仅在该纯透传 wrapper 内出现；紧接着 v42.4 又直接重置 `window.setPage=function(p){state.page=p;render()}`。同时 `setBase424` 当前也仅有声明、没有业务使用，需要在同一批中证明后决定是否一并清除。

下一批仍遵守：

```text
prove final owner
→ focused regression
→ physical deletion
→ syntax/unit
→ Real Chrome
→ 更新四份交接文档
```

禁止一次性盲删全部 `setPage/render`；仍承载页面 alias、缓存失效、侧栏关闭、持久化、NavigationStability 协调的层必须保留或先迁移语义。

## 8. Work order after owner table

```text
A. pure pass-through setPage wrapper physical deletion
B. remaining renderer/setPage obsolete override batches
C. app.js dead code + global reload/request debt
D. cache-busting unification
E. MutationObserver/timer/fetch/render/setPage zero-point scan
F. semantic naming + deterministic test cleanup
G. technical-debt zero-point scan
H. A800 RC
```

## 9. Release prohibition

Formal `v42.25.0` requires all of:

- no unresolved P0/P1 debt;
- Frontend Runtime Stabilization green;
- Release Regression green;
- A800 preflight green;
- first A800 train + verify green;
- A800 iteration + verify green;
- worker lifecycle/fencing real-machine green;
- explicit user approval for merge/version/tag/release.
