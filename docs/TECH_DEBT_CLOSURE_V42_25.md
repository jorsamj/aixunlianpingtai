# v42.25 技术债关闭总账

> **状态：ACTIVE / 技术债优先阶段**  
> **工作分支：`refactor/frontend-runtime-stabilization`**  
> **正式版本：`VERSION.txt` 仍为 `42.24.0`；不得提前发布 `v42.25.0`。**  
> **最近完整前端验收代码点：`462c7b736e8387bd23a3d5e5eab0e715cc4f2945`。**  
> **Frontend Runtime Stabilization run `34596834911`：syntax + 永久 guards + 全量 frontend unit + Real Chrome 全绿。**  
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

前五个字段在 `static/app.js` 与 `training-draft.js / training-draft-runtime.js / training-labels.js` 有永久 CI guard。测试里出现这些名字只允许作为污染 fixture，用来证明 canonical state 隔离。

## 1. 技术债总表

| ID | 技术债 | 最终 owner / 目标 | 状态 | 当前证据 / 下一步 |
|---|---|---|---|---|
| TD-01 | `trainingLabelSelected` | `trainingDraft.newLabelCodes` | **CLOSED** | active app + core modules 零引用；CI + Chrome |
| TD-02 | `trainSplitV3` | `trainingDraft` split/material fields | **CLOSED** | active app + core modules 零引用；CI + Chrome |
| TD-03 | `train429Selected` | `TrainingDraftRuntime.materialIds` | **CLOSED** | picker/全选/反选/质量/计数/标签汇总 canonical-only |
| TD-04 | `train428AlgorithmId` | `trainingDraft.algorithmId` | **CLOSED** | active app + core modules 零引用；无 bootstrap fallback |
| TD-05 | `train428Config` | `trainingDraft.config/resource` | **CLOSED** | settings canonical-only；无 bootstrap fallback |
| TD-06 | `/train/start` 多 owner | `TrainingSubmitRuntime` | **CLOSED** | classic 直发路径清零；永久 guard |
| TD-07 | submit readiness 多 owner | `TrainingSubmitRuntime` | **CLOSED** | legacy DOM writer 退役；Chrome 真提交通过 |
| TD-08 | `/jobs` poll/manual 双请求 | `TrainingTaskRuntime` | **CLOSED** | 120ms coalescing；mutation force-fresh |
| TD-09 | metrics SQLite FD | deterministic close | **CLOSED** | unit + Linux FD regression |
| TD-10 | training task polling lifecycle | `TrainingTaskRuntime + PollRegistry` | **CLOSED** | 单 owner |
| TD-11 | auto-label polling lifecycle | `AutoLabelPollRuntime + PollRegistry` | **IN PROGRESS** | 主 owner 已迁；legacy/rebind timer 待清 |
| TD-12 | video legacy polling | VideoTasks / PollRegistry | **OPEN** | `__videoFramePollTimer` 待退役 |
| TD-13 | `auto422Timer` / prelabel / `setupPagePolling` | named runtimes | **OPEN** | 需物理退役证明 |
| TD-14 | historical render/setPage overrides | 每页面单 owner | **OPEN** | owner 表待建 |
| TD-15 | `app.js` 历史死代码 | named runtimes + bounded shell | **IN PROGRESS** | 训练 owner/mirror 已大幅收口 |
| TD-16 | 一次性 migration helper | 无长期 owner | **CLOSED** | migration helper/workflow 用完即删 |
| TD-17 | cache-busting 不统一 | 单一策略 | **OPEN** | app `42.25.43`; main `42.25.42`; nested 仍独立 |
| TD-18 | 全局 reload/重复请求 | scoped refresh | **OPEN** | 扫 `loadAll/loadRelated/loadCore412` |
| TD-19 | observer/timer/fetch/render 生命周期 | 明确 owner + destroy | **OPEN** | zero-point 扫描待做 |
| TD-20 | 版本号业务命名 | semantic names | **OPEN** | owner 收口后迁移 |
| TD-21 | 测试历史债 | deterministic tests | **IN PROGRESS** | canonical tests 已去 legacy adapter；继续清旧耦合 |
| TD-22 | 文档漂移 | 三份权威文档 | **IN PROGRESS** | 每 runtime 批次同步 |
| TD-23 | A800 RC | A800 acceptance runbook | **DEFERRED** | 技术债阶段后恢复 |
| TD-24 | TrainingDraft/TrainingLabel classic wrappers | direct canonical UI lifecycle | **IN PROGRESS** | Draft 仅 start429 wrapper 保留；TrainingLabel 已清 428 stale binds，继续证明 423/425 可达性 |

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
main.mjs cache                   42.25.42
training-draft.js                422506
training-draft-runtime.js        422512
TrainingDraftRuntime build       training-draft-runtime-422512
training-labels.js               422509
TrainingLabelRuntime build       module-422509
TrainingSubmitRuntime            training-submit-422504
TrainingTaskRuntime              training-task-runtime-422503
```

Missing draft 只创建空 canonical `createTrainingDraft()`，绝不从 428/429 字段恢复。

## 3. TD-24 当前精确边界

### 已关闭的 TrainingDraft wrappers

```text
confirmTrainMaterialPickerV3
setTrainSplitModeV3
saveTrainSettings428
```

这些 final `app.js` 函数已直接写 canonical。wrapper-only settings helpers `settingsPatch / checkboxInput / normalizedCache` 也已删除。

### 唯一剩余 TrainingDraft wrapper

```text
startAlgorithmTraining429
```

原因：当前 start 路径仍叠有历史 414/415/417/v3 wrapper。TrainingDraftRuntime 仍在最外层先 reset/write canonical algorithm/material/split，再执行原 start 链并 `sync()`。

**禁止直接删除。先收平/证明 final start owner chain。**

### TrainingLabelRuntime 已清理

以下 stale bind 在当前 `static/app.js` 无定义，现已从 TrainingLabelRuntime 物理删除并通过 Chrome：

```text
openTrain428
refreshTrain428
```

当前真实剩余 bind 表：

```text
startAlgorithmTraining429
startAlgorithmTraining423
openTrain425
refreshTrain429
trainCounts425
```

TrainingLabel 仍有：

```text
post-action refresh: 0 / 40 / 120 / 350 / 700 ms
rebind:              100 / 400 / 1000 / 2500 ms
modal MutationObserver
```

### start-owner 初步审计

当前稳定算法列表 `renderAlg412` 的训练按钮直接调用 `startAlgorithmTraining429`。它不是 `startAlgorithmTraining423`。

历史 `startAlgorithmTraining423` 曾在 423、425、初始 429 层多次赋值；早期 429 只做了当时函数对象的 alias。之后 414/415/417/v3 再覆盖 `startAlgorithmTraining429`，因此不能假设 423 始终跟随最终 429。

当前 `startAlgorithmTraining429` 链：

```text
initial 429 canonical modal
→ 414 iteration-base wrapper
→ 415 experiment wrapper
→ 417 iteration presentation wrapper
→ durable v3 device/resource wrapper
→ TrainingDraftRuntime outer start wrapper
```

下一步先证明旧 423/425 页面是否仍由当前最终 renderer/page owner 可达，再决定物理删除范围。

## 4. 最近完整验收

```text
acceptance commit: 462c7b736e8387bd23a3d5e5eab0e715cc4f2945
Frontend Runtime Stabilization: 34596834911
frontend unit: PASS
permanent guards: PASS
Real Chrome runtime regressions: PASS
```

该验收包含：五个 mirror canonical-only、legacy bootstrap 退役、3 个 Draft 重复 wrapper 退役、TrainingLabel `openTrain428/refreshTrain428` stale bind 退役。

## 5. 当前清理顺序

```text
A. 证明 startAlgorithmTraining423/openTrain425/trainCounts425 当前可达性
B. 收平/证明 startAlgorithmTraining429 历史 wrapper 链，最后退役 Draft start wrapper
C. 继续减少 TrainingLabel wrappers / refresh timers / rebind timers / MutationObserver
D. 清 auto422Timer / __videoFramePollTimer / prelabel / setupPagePolling
E. renderer/setPage owner table + old override physical deletion
F. app.js dead code + global reload/request debt
G. cache-busting 统一
H. observer/timer/fetch/render/setPage zero-point
I. semantic naming + deterministic tests + docs
J. 技术债 zero-point scan
K. A800 RC
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
