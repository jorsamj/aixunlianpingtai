# v42.25 技术债关闭总账

> **状态：ACTIVE / 技术债优先阶段**  
> **分支：`refactor/frontend-runtime-stabilization`**  
> **正式版本：`VERSION.txt` 仍为 `42.24.0`，不得提前发布 `v42.25.0`。**  
> **最近完整代码验收点：`b74124b974ee12c3bf113fc7a4a336cb706e81f6`**  
> **Frontend Runtime Stabilization：run `34614368651`，frontend + Real Chrome 全绿。**  
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
installVideo424CreationBridge
__pollRegistryVideoWrapped
installSourceCreationBridge
__pollRegistrySourceWrapped
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
| TD-14B | `setupPagePolling` / training creation bridge | direct `PollRegistry(training-jobs)` | **NEXT** |
| TD-14C | historical render/setPage overrides | final owner table + physical deletion | **OPEN** |
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

Source polling is now wrapper-free and state-timer-free:

```text
renderSources422
→ renderSourceRows422()
→ PollRegistryRuntime.replaceSourceTimer()
→ PollRegistry(sources, 2500ms managed interval)
→ refreshSources422()
```

Physically removed for sources:

```text
state.source422Timer
classic source setInterval/clearInterval
PollRegistry registry.adopt('sources', ...)
installSourceCreationBridge
originalRenderSources / wrappedRenderSources
source wrapper restoration
NavigationStability source timer fallback
```

`source422Timer` must remain absent from `static/app.js`, `poll-registry.js`, and `navigation-stability.js`.

## 4. Current version/cache facts

```text
app.js cache                     42.25.47
main.mjs cache                   42.25.52
navigation-stability.js          422505
poll-registry.js                 422510
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
```

Source guard requires:

- `source422Timer` zero references in product runtime files;
- exactly one app-level `replaceSourceTimer()` handoff;
- no source renderer wrapper/adoption compatibility in PollRegistry;
- `replaceSourceTimer()` managed owner retained.

## 6. Latest acceptance

```text
commit: b74124b974ee12c3bf113fc7a4a336cb706e81f6
run:    34614368651

syntax                                      PASS
all permanent owner guards                  PASS
frontend unit                               PASS
Real Chrome                                 PASS
```

Real Chrome still proves source polling is managed at 2500ms and is cleared when leaving the page. Video, training, AutoLabel and performance regressions also remain green.

## 7. Next exact task

Only one PollRegistry creation bridge remains:

```text
installPollingCreationBridge()
→ wraps setupPagePolling
→ legacy setupPagePolling creates state.jobPollTimer
→ wrapper clears/replaces it with PollRegistry(training-jobs)
```

Target:

```text
classic page lifecycle
→ explicit PollRegistryRuntime.replaceTrainingJobTimer()
→ PollRegistry owns training-jobs timer directly
```

Then physically remove:

```text
state.jobPollTimer compatibility
installPollingCreationBridge
originalSetupPagePolling / wrappedSetupPagePolling
__pollRegistryCreationWrapped
legacy training timer adoption/restoration
obsolete setupPagePolling interval creation layers
```

Do not remove historical render/setPage layers in the same blind change. First close training polling bridge with focused unit + Real Chrome, then build the final renderer/setPage owner table.

## 8. Work order after training bridge

```text
A. renderer/setPage final-owner table + physical deletion
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
