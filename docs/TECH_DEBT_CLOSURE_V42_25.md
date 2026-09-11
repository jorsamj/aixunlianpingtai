# v42.25 技术债关闭总账

> **状态：ACTIVE / 技术债优先阶段**  
> **工作分支：`refactor/frontend-runtime-stabilization`**  
> **正式版本：`VERSION.txt` 仍为 `42.24.0`；不得提前发布 `v42.25.0`。**  
> **最近完整前端验收代码点：`52fe8f7ff822ef9d39a993d8f62edb5269b863a3`。**  
> **Frontend Runtime Stabilization run `34598219623`：syntax + 永久 guards + 全量 frontend unit + Real Chrome 全绿。**  
> **更新日期：2026-09-11**

## 0. 后续 AI / Codex 强制入口

阅读顺序：

1. `docs/TECH_DEBT_CLOSURE_V42_25.md`
2. `docs/CODEX_CURRENT_STATE.md`
3. `docs/frontend-legacy-audit.md`

规则：先清技术债，再恢复 A800 RC；未经用户允许不得 merge `main` / bump `VERSION.txt` / tag / release。

永久退休、不得恢复为 truth source 或 bootstrap fallback：

```text
trainingLabelSelected
trainSplitV3
train429Selected
train428AlgorithmId
train428Config
trainingDraftFromLegacyState
```

TrainingDraftRuntime 也已永久禁止重新接管 classic function wrapper。

## 1. 技术债总表

| ID | 技术债 | 最终 owner / 目标 | 状态 | 当前证据 / 下一步 |
|---|---|---|---|---|
| TD-01 | `trainingLabelSelected` | `trainingDraft.newLabelCodes` | **CLOSED** | active app + core modules 零引用；CI + Chrome |
| TD-02 | `trainSplitV3` | `trainingDraft` split/material fields | **CLOSED** | canonical-only |
| TD-03 | `train429Selected` | `TrainingDraftRuntime.materialIds` | **CLOSED** | picker/质量/计数 canonical-only |
| TD-04 | `train428AlgorithmId` | `trainingDraft.algorithmId` | **CLOSED** | 无 bootstrap fallback |
| TD-05 | `train428Config` | `trainingDraft.config/resource` | **CLOSED** | settings canonical-only |
| TD-06 | `/train/start` 多 owner | `TrainingSubmitRuntime` | **CLOSED** | classic 直发清零；永久 guard |
| TD-07 | submit readiness 多 owner | `TrainingSubmitRuntime` | **CLOSED** | Chrome 真提交通过 |
| TD-08 | `/jobs` poll/manual 双请求 | `TrainingTaskRuntime` | **CLOSED** | 120ms coalescing；mutation force-fresh |
| TD-09 | metrics SQLite FD | deterministic close | **CLOSED** | unit + Linux FD regression |
| TD-10 | training task polling lifecycle | `TrainingTaskRuntime + PollRegistry` | **CLOSED** | 单 owner |
| TD-11 | auto-label polling lifecycle | `AutoLabelPollRuntime + PollRegistry` | **IN PROGRESS** | legacy/rebind timer 待清 |
| TD-12 | video legacy polling | VideoTasks / PollRegistry | **OPEN** | `__videoFramePollTimer` 待退役 |
| TD-13 | `auto422Timer` / prelabel / `setupPagePolling` | named runtimes | **OPEN** | 需物理退役证明 |
| TD-14 | historical render/setPage overrides | 每页面单 owner | **OPEN** | owner 表待建 |
| TD-15 | `app.js` 历史死代码 | named runtimes + bounded shell | **IN PROGRESS** | 训练 owner/mirror 已大幅收口 |
| TD-16 | 一次性 migration helper | 无长期 owner | **CLOSED** | 用完即删 |
| TD-17 | cache-busting 不统一 | 单一策略 | **OPEN** | app `42.25.43`; main `42.25.44` |
| TD-18 | 全局 reload/重复请求 | scoped refresh | **OPEN** | 扫 `loadAll/loadRelated/loadCore412` |
| TD-19 | observer/timer/fetch/render 生命周期 | 明确 owner + destroy | **OPEN** | zero-point 扫描待做 |
| TD-20 | 版本号业务命名 | semantic names | **OPEN** | owner 收口后迁移 |
| TD-21 | 测试历史债 | deterministic tests | **IN PROGRESS** | canonical/wrapper-free tests 已补 |
| TD-22 | 文档漂移 | 三份权威文档 | **IN PROGRESS** | 每 runtime 批次同步 |
| TD-23 | A800 RC | A800 acceptance runbook | **DEFERRED** | 技术债阶段后恢复 |
| TD-24 | TrainingDraft/TrainingLabel classic wrappers | direct canonical UI lifecycle | **IN PROGRESS** | **TrainingDraft 部分 CLOSED：Runtime 完全 wrapper-free；TrainingLabel 仅剩 start429 + refresh429 两个 wrapper** |

## 2. 当前 canonical training owner

```text
train-v3 UI
→ state.trainingDraft
→ TrainingDraftRuntime
→ TrainingSubmitRuntime
→ POST /api/v12/projects/{project_id}/train/start
```

版本事实：

```text
app.js cache                     42.25.43
main.mjs cache                   42.25.44
training-draft.js                422506
training-draft-runtime.js        422513
TrainingDraftRuntime build       training-draft-runtime-422513
training-labels.js               422510
TrainingLabelRuntime build       module-422510
TrainingSubmitRuntime            training-submit-422504
TrainingTaskRuntime              training-task-runtime-422503
```

## 3. TD-24 当前精确边界

### TrainingDraftRuntime：CLOSED / wrapper-free

所有 classic wrapper 均已物理删除：

```text
confirmTrainMaterialPickerV3
setTrainSplitModeV3
saveTrainSettings428
startAlgorithmTraining429
```

注意：最后一项表示 **TrainingDraftRuntime 不再 wrapper start429**；`app.js` 里的业务函数名仍存在并由页面自身持有。

一并删除：

```text
settingsPatch
checkboxInput
normalizedCache
directMutationFor
wrapLegacyMutation
mutationWrappers
directWrites
destroy() wrapper restoration
```

Runtime state 明确：

```text
networkOwner=false
classicWrapperOwner=false
```

永久 CI guard 禁止把 classic wrapper 重新加回 `training-draft-runtime.js`。

### TrainingLabelRuntime：仅剩 2 个 wrapper

已退役：

```text
openTrain428
refreshTrain428
startAlgorithmTraining423
openTrain425
trainCounts425
```

其中 423/425 只有在确认最终 stable algorithm renderer 使用 start429、最终 task renderer 不再暴露 425 create UI 后才删除。

当前只剩：

```text
startAlgorithmTraining429
refreshTrain429
```

同时仍有：

```text
post-action refresh timers: 0 / 40 / 120 / 350 / 700 ms
rebind timers:              100 / 400 / 1000 / 2500 ms
modal MutationObserver
legacy 425 state/DOM fallback reads
```

下一批目标：TrainingLabelRuntime wrapper-free + canonical-only，并把 timer fan-out 收掉。

## 4. 最近完整验收

```text
acceptance commit: 52fe8f7ff822ef9d39a993d8f62edb5269b863a3
Frontend Runtime Stabilization: 34598219623
syntax: PASS
retired-mirror guard: PASS
canonical network-owner guard: PASS
TrainingDraft wrapper-free guard: PASS
frontend unit: PASS
Real Chrome runtime regressions: PASS
```

该验收覆盖 TrainingDraftRuntime 最后一个 start wrapper 及整套 wrapper infrastructure 的退役。

## 5. 当前清理顺序

```text
A. TrainingLabelRuntime wrapper-free + canonical-only；清 425 fallback 和 9 个延迟 timer
B. 评估是否仍需 TrainingLabel MutationObserver；能删则物理删除，不能删则收敛为单一 lifecycle owner
C. 清 auto422Timer / __videoFramePollTimer / prelabel / setupPagePolling
D. renderer/setPage owner table + old override physical deletion
E. app.js dead code + global reload/request debt
F. cache-busting 统一
G. observer/timer/fetch/render/setPage zero-point
H. semantic naming + deterministic tests + docs
I. 技术债 zero-point scan
J. A800 RC
```

每批必须：owner 证明 → regression → 物理删除 → syntax/unit → Real Chrome（行为受影响时）→ 更新总账。

## 6. 发布禁令

正式 `v42.25.0` 前必须全部满足：

- 本总账无未解决 P0/P1；
- Frontend Runtime Stabilization 全绿；
- Release Regression 全绿；
- A800 preflight PASS；
- A800 首训 + verify-job PASS；
- A800 迭代 + verify PASS；
- Worker lifecycle/fencing 实机 PASS；
- 用户明确允许 merge/version/tag/release。
