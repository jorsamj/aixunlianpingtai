# v42.25 技术债关闭总账

> **状态：ACTIVE / 技术债优先阶段**  
> **工作分支：`refactor/frontend-runtime-stabilization`**  
> **正式版本：`VERSION.txt` 仍为 `42.24.0`；不得提前发布 `v42.25.0`。**  
> **最近完整前端验收代码点：`f3bae76de68b14b0a2799119de62a9b8ac13acaa`。**  
> **Frontend Runtime Stabilization run `34595909062`：syntax + 永久 owner/mirror guards + 全量 frontend unit + Real Chrome 全绿。**  
> **更新日期：2026-09-11**

## 0. 给后续 AI / Codex 的强制入口

本文件是 v42.25 技术债关闭工作的**权威状态总账**。继续开发前必须按顺序阅读：

1. `docs/TECH_DEBT_CLOSURE_V42_25.md`（本文件）
2. `docs/CODEX_CURRENT_STATE.md`
3. `docs/frontend-legacy-audit.md`

执行规则：

- 当前优先级：**先关闭技术债，再恢复 A800 RC**。
- 未标记 `CLOSED` 的项目不得自行宣称完成。
- legacy 代码必须经过 owner 证明、自动化回归、必要的物理退场后才能关闭。
- 不得为了 CI 变绿而放宽竞态、重复请求、timer、owner 或浏览器断言。
- 训练 canonical state 只有 `state.trainingDraft`。
- `/train/start` 唯一网络 owner 是 `TrainingSubmitRuntime`。
- 未经用户明确授权，不得 merge `main`、修改正式 `VERSION.txt`、打 tag 或发布 release。
- A800 RC 在本文件 P0/P1 技术债关闭前保持 `DEFERRED`。

### 已永久退休、不得恢复为 fallback/truth source 的五个字段

```text
trainingLabelSelected
trainSplitV3
train429Selected
train428AlgorithmId
train428Config
```

永久 Frontend CI 会在以下产品代码中阻止它们重新出现：

```text
static/app.js
static/modules/training-draft.js
static/modules/training-draft-runtime.js
static/modules/training-labels.js
```

**测试文件可以故意构造这些旧字段作为污染 fixture，用来证明 Runtime 不读取、不写入、不删除这些字段；测试中的历史字段名不代表兼容 owner 仍然存在。**

`trainingDraftFromLegacyState` 也已物理删除。不得恢复它、`bootstrapFromLegacy` 或等价的 428/429 状态恢复逻辑。

状态定义：`CLOSED` / `IN PROGRESS` / `OPEN` / `DEFERRED`。

## 1. 技术债总表

| ID | 技术债 | 最终 owner / 目标 | 状态 | 当前证据 / 下一步 |
|---|---|---|---|---|
| TD-01 | `trainingLabelSelected` | `state.trainingDraft.newLabelCodes` | **CLOSED** | active app + core modules 零引用；永久 CI；Chrome |
| TD-02 | `trainSplitV3` | `state.trainingDraft` split/material fields | **CLOSED** | active app + core modules 零引用；永久 CI；Chrome |
| TD-03 | `train429Selected` | `TrainingDraftRuntime` → `trainingDraft.materialIds` | **CLOSED** | picker/全选反选/质量/计数/标签汇总已 canonical-only；永久 CI；Chrome |
| TD-04 | `train428AlgorithmId` 训练算法 mirror | `state.trainingDraft.algorithmId` | **CLOSED** | active app + core modules 零引用；无 legacy bootstrap；污染 fixture 不影响 canonical state |
| TD-05 | `train428Config` 训练配置 mirror | `state.trainingDraft.config/resource` | **CLOSED** | active app + core modules 零引用；settings 写 canonical draft；无 fallback bootstrap |
| TD-06 | `/train/start` 多 owner / 旧 payload builder | `TrainingSubmitRuntime` | **CLOSED** | classic `app.js` 直发 owner 物理清零；永久 CI guard |
| TD-07 | “开始训练” readiness 多 owner | `TrainingSubmitRuntime.trainingSubmitReadiness()` | **CLOSED** | legacy DOM writer 退役；Real Chrome 真点击提交通过 |
| TD-08 | `/jobs` poll + manual 双请求 | `TrainingTaskRuntime` | **CLOSED** | 120ms cross-source coalescing；mutation force-fresh；Chrome 单 GET 约束 |
| TD-09 | `training-metrics.sqlite3` FD 泄漏 | deterministic SQLite close | **CLOSED** | 单测 + Linux `/proc/self/fd` 回归；A800 后续再实机观察 |
| TD-10 | 训练任务 polling 生命周期 | `TrainingTaskRuntime + PollRegistry` | **CLOSED** | 单 owner + 页面生命周期 + request coalescing |
| TD-11 | 自动标注 polling 生命周期 | `AutoLabelPollRuntime + PollRegistry` | **IN PROGRESS** | 主 poll owner 已迁移；继续清 rebind/legacy timer |
| TD-12 | 视频切帧 legacy polling | VideoTasks / PollRegistry | **OPEN** | 已识别 `__videoFramePollTimer`，需 owner 证明后物理退役 |
| TD-13 | `auto422Timer` / prelabel / 老 `setupPagePolling` | 各页面 Runtime + PollRegistry | **OPEN** | 做死代码证明，不能只 clear/null |
| TD-14 | 历史 `render=` / `window.setPage=` override | 每页面单 owner | **OPEN** | 建 owner 表，再删失效 override 层 |
| TD-15 | `app.js` 过大 / 历史死代码 | named Runtime + 有界 legacy shell | **IN PROGRESS** | 已清训练 owner/mirror；继续“证明无引用→测试→删除” |
| TD-16 | 临时 shim / migration helper | 无长期 owner | **CLOSED** | canonical migration helper/workflow 已在完成后删除；不得恢复 |
| TD-17 | 静态资源 cache-busting 不统一 | 单一 cache/build version | **OPEN** | `styles/bootstrap=42.24.0`；`app.js=42.25.43`；`main.mjs=42.25.40`；nested imports 仍各自编号 |
| TD-18 | 剩余页面重复请求 / 全量 reload | scoped refresh | **OPEN** | 扫描 `loadAll/loadRelated/loadCore412/render` |
| TD-19 | observer/timer/fetch/render/setPage 生命周期 | 明确 owner + destroy | **OPEN** | 全仓记录 creator/owner/destroy/cross-page behavior |
| TD-20 | 版本号业务命名 | 语义 owner 名称 | **OPEN** | owner 收口后渐进重命名，不做盲目全局替换 |
| TD-21 | 测试历史债 / flaky sleep | deterministic tests | **IN PROGRESS** | canonical 测试已去 adapter；继续清 sleep/build 常量等历史耦合 |
| TD-22 | 文档与代码漂移 | 本总账 + CURRENT_STATE + legacy audit | **IN PROGRESS** | 每个 runtime 批次必须同步三份文档 |
| TD-23 | A800 v42.25 RC | A800 acceptance runbook | **DEFERRED** | P0/P1 技术债结束后再 preflight → 首训 → 迭代 → Worker lifecycle |
| TD-24 | TrainingDraft/TrainingLabel classic wrapper 生命周期 | direct canonical UI owners | **IN PROGRESS** | canonical mirror debt已清；下一批退役 wrapper/rebind timer/MutationObserver |

## 2. 当前训练 canonical owner（不得回退）

```text
train-v3 UI
  ↓
state.trainingDraft
  ↓
TrainingDraftRuntime
  ↓
TrainingSubmitRuntime
  ↓
POST /api/v12/projects/{project_id}/train/start
```

当前实际版本：

```text
app.js cache                         42.25.43
main.mjs cache                       42.25.40
training-draft.js import             422506
training-draft-runtime.js import     422511
TrainingDraftRuntime build           training-draft-runtime-422511
training-labels.js import            422508
TrainingSubmitRuntime build          training-submit-422504
TrainingTaskRuntime build            training-task-runtime-422503
```

### `TrainingDraftRuntime`

- canonical draft 创建/同步/更新 owner。
- `networkOwner=false`，不得拦截 `/train/start`。
- 无 draft 时只创建空 canonical `createTrainingDraft()`，不读取 428/429 legacy mirror。
- 素材 API：`materialIds()` / `setMaterialIds(ids)` / `toggleMaterialId(id)`。
- `trainingDraftFromLegacyState` 已不存在。

### `TrainingSubmitRuntime`

- `/train/start` 唯一网络 owner。
- 拥有 readiness、迭代起点安全校验、设备校验、payload 构建与 POST。
- 保留 `lastStage / lastError` 诊断字段。
- `static/app.js` 出现 `/train/start` 即为回归。

### `TrainingLabelRuntime`

- v3 当前素材只读 `trainingDraft.materialIds`。
- label selection 写 `trainingDraft.newLabelCodes`。
- 不允许 fallback 到 `train429Selected` 或 `train428AlgorithmId`。
- wrapper/rebind timer/MutationObserver 仍属 TD-24。

## 3. 五个 mirror 与 legacy bootstrap 关闭证据

当前已完成：

- `static/app.js` 对五个 mirror 零引用；
- `training-draft.js` / `training-draft-runtime.js` / `training-labels.js` 对五个 mirror 零引用；
- `trainingDraftFromLegacyState` 从 module、main、runtime dependency、tests 物理删除；
- missing draft → 空 canonical draft，而不是 legacy recovery；
- direct-write/generic-sync tests 改为验证 stale mirror fixture 被**忽略且保持原样**；
- 一次性 migration helper/workflow 已删除；
- 永久 CI guard 保留。

完整前端验收：

```text
commit: f3bae76de68b14b0a2799119de62a9b8ac13acaa
workflow: Frontend Runtime Stabilization
run: 34595909062
result: syntax PASS + permanent guards PASS + frontend unit PASS + Real Chrome PASS
```

Chrome 测试仍会主动污染旧 mirror，再验证 canonical draft 与最终请求不受污染；这是有意的防回归设计。

## 4. 下一批：TD-24 wrapper / lifecycle 清理

**不要误把“mirror 清零”理解为“TrainingDraftRuntime 已无兼容层”。** 当前仍有 wrapper。

### TrainingDraftRuntime 当前 wrapper

```text
startAlgorithmTraining429
confirmTrainMaterialPickerV3
setTrainSplitModeV3
saveTrainSettings428
```

当前 `wrapLegacyMutation()` 会在 classic callback 前直接写 canonical draft，并在 callback 后 `sync()`。`destroy()` 会恢复原函数。

清理方法：

```text
逐个函数证明 final classic UI 已直接写 TrainingDraftRuntime
→ 增加/保留 unit + Chrome 证据
→ 删除对应 wrapper/directMutationFor 分支
→ 不新增替代 wrapper
```

### TrainingLabelRuntime 当前 lifecycle machinery

```text
wrapped entrypoints:
  startAlgorithmTraining429
  startAlgorithmTraining423
  openTrain428
  openTrain425
  refreshTrain429
  refreshTrain428
  trainCounts425

post-entrypoint refresh timers:
  0 / 40 / 120 / 350 / 700 ms

rebind timers:
  100 / 400 / 1000 / 2500 ms

modal MutationObserver
```

目标是让标签 UI 由明确的训练弹窗生命周期触发，而不是靠重复 rebind + 多次延时 refresh + Observer 补偿。

## 5. Chrome / CI 门禁

`tests/browser/training-label-selector.spec.mjs` 当前要求：

- `TrainingDraftRuntime` build 为 `training-draft-runtime-422511`；
- DraftRuntime 不拥有网络；SubmitRuntime 是唯一网络 owner；
- picker 使用 canonical materialIds；
- label selection 写 canonical labels；
- resource/config/priority/split 写 canonical draft；
- stale legacy mirror 污染不能改变 canonical draft；
- raw caller 的 `/train/start` 不被 DraftRuntime 篡改；
- 真点击“开始训练”由 SubmitRuntime 发 canonical payload。

禁止通过恢复 adapter、放宽断言、增加 sleep 或全局轮询修复测试。

## 6. 当前工作顺序

```text
A. 逐个退役 TrainingDraftRuntime classic wrappers
B. 退役 TrainingLabelRuntime wrappers / refresh timers / rebind timers / MutationObserver
C. 清 auto422Timer / __videoFramePollTimer / prelabel / setupPagePolling
D. 建 renderer / setPage 最终 owner 表并物理退役旧 override
E. app.js 可证明死代码削减
F. 重复请求 / 全量 reload 扫描
G. cache-busting 统一
H. observer/timer/fetch wrapper 零点扫描
I. 版本号业务命名迁移
J. 测试去抖动 + 文档持续同步
K. 技术债零点扫描
L. A800 RC
```

每批必须：`syntax/unit → Real Chrome（行为受影响时）→ 更新本总账 → 下一批`。

## 7. 发布禁令

以下全部通过前禁止正式发布 `v42.25.0`：

- 本总账无未解决 P0/P1；
- Frontend Runtime Stabilization 全绿；
- Release Regression 全绿；
- A800 preflight PASS；
- A800 首训 + verify-job PASS；
- A800 迭代训练 + iteration verify PASS；
- Worker lifecycle/fencing 实机 PASS；
- 用户明确允许 merge `main` / bump version / tag/release。
