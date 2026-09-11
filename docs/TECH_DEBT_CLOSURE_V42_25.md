# v42.25 技术债关闭总账

> **状态：ACTIVE / 技术债优先阶段**  
> **工作分支：`refactor/frontend-runtime-stabilization`**  
> **正式版本：`VERSION.txt` 仍为 `42.24.0`；不得提前发布 `v42.25.0`。**  
> **最近完整前端验收代码点：`5ad08f03406e10dfd8c66a1455f068d503a77a4f`。**  
> **Frontend Runtime Stabilization run `34608378866`：syntax + 永久 guards + 全量 frontend unit + Real Chrome 全绿。**  
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

永久禁止：

- TrainingDraftRuntime 重新接管 classic function wrapper；
- TrainingLabelRuntime 重新接管 start/refresh classic wrapper；
- 用 `setTimeout` fan-out / rebind timer 修训练标签 UI；
- DraftRuntime 从 `.training-label-contract` 控件事件做 generic sync。

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
| TD-11 | auto-label polling lifecycle | `AutoLabelPollRuntime + PollRegistry` | **IN PROGRESS** | 旧 422 interval + v60 timer + renderer wrapper/rebind 待清 |
| TD-12 | video legacy polling | VideoTasks / PollRegistry | **OPEN** | `__videoFramePollTimer` 待退役 |
| TD-13 | `auto422Timer` / prelabel / `setupPagePolling` | named runtimes | **IN PROGRESS** | AutoLabel 先收口；其余后续 |
| TD-14 | historical render/setPage overrides | 每页面单 owner | **OPEN** | owner 表待建 |
| TD-15 | `app.js` 历史死代码 | named runtimes + bounded shell | **IN PROGRESS** | 训练 owner/mirror/wrapper 已收口 |
| TD-16 | 一次性 migration helper | 无长期 owner | **CLOSED** | 用完即删 |
| TD-17 | cache-busting 不统一 | 单一策略 | **OPEN** | app `42.25.43`; main `42.25.48` |
| TD-18 | 全局 reload/重复请求 | scoped refresh | **OPEN** | 扫 `loadAll/loadRelated/loadCore412` |
| TD-19 | observer/timer/fetch/render 生命周期 | 明确 owner + destroy | **OPEN** | zero-point 扫描待做 |
| TD-20 | 版本号业务命名 | semantic names | **OPEN** | owner 收口后迁移 |
| TD-21 | 测试历史债 | deterministic tests | **IN PROGRESS** | canonical/wrapper-free/DOM-stable tests 已补 |
| TD-22 | 文档漂移 | 三份权威文档 | **IN PROGRESS** | 每 runtime 批次同步 |
| TD-23 | A800 RC | A800 acceptance runbook | **DEFERRED** | 技术债阶段后恢复 |
| TD-24 | TrainingDraft/TrainingLabel classic wrappers | direct canonical UI lifecycle | **CLOSED** | Draft + Label 均 wrapper-free；Label timer-free；Chrome 通过 |

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
main.mjs cache                   42.25.48
training-draft.js                422506
training-draft-runtime.js        422516
TrainingDraftRuntime build       training-draft-runtime-422516
training-labels.js               422513
TrainingLabelRuntime build       module-422513
TrainingSubmitRuntime            training-submit-422504
TrainingTaskRuntime              training-task-runtime-422503
```

## 3. TD-24：CLOSED

### TrainingDraftRuntime：wrapper-free

所有 classic wrapper 已物理删除：

```text
confirmTrainMaterialPickerV3
setTrainSplitModeV3
saveTrainSettings428
startAlgorithmTraining429
```

并删除全部 wrapper infrastructure：

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

Runtime diagnostics：

```text
networkOwner=false
classicWrapperOwner=false
```

永久 CI guard 禁止恢复 classic wrapper。

### TrainingLabelRuntime：wrapper-free / timer-free / canonical-only

已物理退役全部 bind/wrapper：

```text
openTrain428
refreshTrain428
startAlgorithmTraining423
openTrain425
trainCounts425
startAlgorithmTraining429
refreshTrain429
```

已移除：

```text
post-action timer fan-out
rebind timers
legacy train425Selected fallback
legacy tr425AssetAlg / train423Asset lookup
legacy .train428-data / .train425-data host fallback
```

当前生命周期：

```text
TrainingDraftRuntime.subscribe()
→ TrainingLabelRuntime
→ canonical materialIds / newLabelCodes
→ MutationObserver 仅补 DOM 被外层重绘后的面板
```

标签 checkbox 事件由 TrainingLabelRuntime 独占；DraftRuntime 显式排除 `.training-label-contract`，避免 click/change 触发 generic sync 后把正在操作的 checkbox DOM 重建。

Chrome 回归覆盖：

- 素材选择后标签立即出现；
- 勾选/取消标签不 detach 当前 checkbox；
- 同一算法第二次打开训练时，上一 session 的 label interaction 不污染新 session；
- 最终 POST 仍只由 TrainingSubmitRuntime 发送 canonical payload。

## 4. 最近完整验收

```text
acceptance commit: 5ad08f03406e10dfd8c66a1455f068d503a77a4f
Frontend Runtime Stabilization: 34608378866
syntax: PASS
retired-mirror guard: PASS
canonical network-owner guard: PASS
TrainingDraft wrapper-free + owner-boundary guard: PASS
TrainingLabel canonical lifecycle guard: PASS
frontend unit: PASS
Real Chrome runtime regressions: PASS
```

## 5. 当前清理顺序

```text
A. AutoLabel polling 单 owner：清 auto422Timer / ai60ListTimer / renderOps427 wrapper / 100,400,1000ms rebind timers
B. __videoFramePollTimer / prelabel / setupPagePolling
C. renderer/setPage owner table + old override physical deletion
D. app.js dead code + global reload/request debt
E. cache-busting 统一
F. observer/timer/fetch/render/setPage zero-point
G. semantic naming + deterministic tests + docs
H. 技术债 zero-point scan
I. A800 RC
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
