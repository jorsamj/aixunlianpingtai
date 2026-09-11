# v42.25 技术债关闭总账

> **状态：ACTIVE / 技术债优先阶段**  
> **分支：`refactor/frontend-runtime-stabilization`**  
> **正式版本：`VERSION.txt` 仍为 `42.24.0`，不得提前发布 `v42.25.0`。**  
> **最近完整代码验收点：`774df651c3f278c782029e64bfa3315b12622a9f`**  
> **Frontend Runtime Stabilization：run `34616465336`，frontend + Real Chrome 全绿。**  
> **更新日期：2026-09-11**

## 0. 接手入口

按顺序阅读：

1. `docs/TECH_DEBT_CLOSURE_V42_25.md`
2. `docs/CODEX_CURRENT_STATE.md`
3. `docs/frontend-legacy-audit.md`

规则：先清技术债，再恢复 A800 RC；未经用户明确允许，不得 merge `main`、改正式 `VERSION.txt`、tag 或 release。

## 1. 永久退休 surface

不得恢复为 truth source、bootstrap fallback、timer owner 或 compatibility wrapper：

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
| TD-14C | historical render/setPage/setupPagePolling entrypoints | final owner table + physical deletion | **NEXT** |
| TD-15 | `app.js` dead code | bounded shell + named runtimes | **IN PROGRESS** |
| TD-17 | cache-busting | single strategy | **OPEN** |
| TD-18 | global reload / duplicate request | scoped refresh | **OPEN** |
| TD-19 | observer/timer/fetch/render lifecycle | explicit owner + destroy | **OPEN** |
| TD-20 | version-number business naming | semantic names | **OPEN** |
| TD-21 | flaky/historical tests | deterministic tests | **IN PROGRESS** |
| TD-22 | docs drift | 3 authority docs | **IN PROGRESS** |
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

Training polling is now wrapper-free and state-timer-free:

```text
page lifecycle / remaining historical setupPagePolling entrypoint
→ PollRegistryRuntime.replaceTrainingJobTimer()
→ PollRegistry(training-jobs, 2000ms active / 5000ms idle)
→ TrainingTaskRuntime.refresh({render:true, source:'poll'})
→ focused /jobs update
```

Physically removed:

```text
state.jobPollTimer
classic setupPagePolling setInterval/clearInterval owner
PollRegistry registry.adopt('training-jobs', ...)
installPollingCreationBridge
originalSetupPagePolling / wrappedSetupPagePolling
__pollRegistryCreationWrapped
adoptLegacy / rebindCreation
NavigationStability jobPollTimer fallback
```

`setupPagePolling` 这个历史函数名目前仍有两个一行 handoff 入口，但已不再创建 timer；它们归入下一批 renderer/setPage owner-table 清理，不得重新塞回 polling 逻辑。

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
app.js cache                     42.25.48
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
- PollRegistry 不得恢复 training creation wrapper/adoption/rebind compatibility；
- 若历史 `setupPagePolling` 入口仍存在，只允许显式 handoff 到 `replaceTrainingJobTimer()`；
- `replaceTrainingJobTimer()` direct managed owner 必须保留。

## 6. Latest acceptance

```text
commit: 774df651c3f278c782029e64bfa3315b12622a9f
run:    34616465336

syntax                                      PASS
all permanent owner guards                  PASS
Training PollRegistry direct owner guard    PASS
frontend unit                               PASS
Real Chrome                                 PASS
```

该 Real Chrome run 同时覆盖 training label/submit、training task performance/manual refresh、navigation stability、AutoLabel、algorithm list、materials 等现有回归。

## 7. Next exact task: renderer / setPage final-owner table

Polling creation bridges 已全部关闭。下一步不是再造 Runtime，而是先建立最终 owner 表，再逐层物理删除历史覆盖。

当前已确认 `static/app.js` 至少存在：

```text
多个 render = ... 历史覆盖
多个 window.setPage = ... 历史覆盖
两个只做 PollRegistry handoff 的 setupPagePolling 历史入口
renderXXX 412 / 417 / 423 / 424 / 425 / 427 / 428 / 429 等代际函数
```

下一批执行顺序：

```text
1. 列出每个可见页面的最终 renderer / setPage / action owner
2. 标出仅被后续 wrapper 引用的中间层
3. 为待删层补/复用 deterministic regression
4. 一批只删一个 owner family
5. syntax + unit + Real Chrome
6. 更新三份交接文档
```

优先清理：

```text
setupPagePolling 两个空壳 handoff
纯透传 setPage wrapper（例如只调用 previous owner、没有独立业务语义者）
已被最终 renderer 完全覆盖且无调用者的旧 render 层
```

禁止一次性盲删所有 `setPage/render`，必须先证明最终 owner。

## 8. Work order after owner table

```text
A. renderer/setPage obsolete override physical deletion
B. app.js dead code + global reload/request debt
C. cache-busting unification
D. MutationObserver/timer/fetch/render/setPage zero-point scan
E. semantic naming + deterministic test cleanup
F. technical-debt zero-point scan
G. A800 RC
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
