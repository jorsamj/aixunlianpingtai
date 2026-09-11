# v42.25 技术债关闭总账

> **状态：ACTIVE / 技术债优先阶段**  
> **工作分支：`refactor/frontend-runtime-stabilization`**  
> **正式版本：`VERSION.txt` 仍为 `42.24.0`；不得提前发布 `v42.25.0`。**  
> **最近验证代码点：`2f858dabdeb4766a1283e3601c1ed25d7b6cc512`**  
> **最近 Frontend Runtime Stabilization：run `34590904476`，`success`。**  
> **更新日期：2026-09-11**

## 0. 给后续 AI / Codex 的强制入口

本文件是 v42.25 技术债关闭工作的**权威状态总账**。继续开发前必须按顺序阅读：

1. `docs/TECH_DEBT_CLOSURE_V42_25.md`（本文件）
2. `docs/CODEX_CURRENT_STATE.md`
3. `docs/frontend-legacy-audit.md`

执行规则：

- 当前用户优先级是：**先关闭技术债，再恢复 A800 RC**。
- 未标记 `CLOSED` 的项目不得自行宣称完成。
- 不得仅因为 legacy 代码“当前没被调用”就标记 CLOSED；必须有明确最终 owner、物理退场或严格隔离，以及自动化证据。
- 不得为了让 CI 变绿而放宽重复请求、竞态、sleep、timer 或 owner 冲突断言。
- 不得重新引入 `trainingLabelSelected` / `trainSplitV3`。
- `train428AlgorithmId` / `train428Config` / `train429Selected` 不得重新成为训练提交 truth source。
- 训练 canonical state 是 `state.trainingDraft`。
- `/train/start` 唯一网络 owner 是 `TrainingSubmitRuntime`；`TrainingDraftRuntime` 不得拦截或改写该请求。
- A800 RC 在本文件 P0/P1 技术债关闭前保持 `DEFERRED`。
- 未经用户明确授权，不得 merge `main`、把 `VERSION.txt` 改为 `42.25.0`、打 tag 或发布 release。

状态定义：`CLOSED` / `IN PROGRESS` / `OPEN` / `DEFERRED`。

## 1. 技术债总表

| ID | 技术债 | 最终 owner / 目标 | 状态 | 当前证据 / 下一步 |
|---|---|---|---|---|
| TD-01 | `trainingLabelSelected` | `state.trainingDraft.newLabelCodes` | **CLOSED** | Runtime 强制退休；CI + Chrome 防回归 |
| TD-02 | `trainSplitV3` | `state.trainingDraft` split/material fields | **CLOSED** | Runtime 强制退休；CI + Chrome 防回归 |
| TD-03 | `train429Selected` 作为训练素材 truth source | `state.trainingDraft.materialIds` | **IN PROGRESS** | Label/Submit 已 canonical-first；`app.js` 仍有历史 UI/helper 读写，继续迁移真实 owner |
| TD-04 | `train428AlgorithmId` 作为训练算法 truth source | `state.trainingDraft.algorithmId` | **IN PROGRESS** | Chrome 会主动污染 legacy algorithm 并验证提交不受影响；继续清历史 UI/helper 读写 |
| TD-05 | `train428Config` 作为训练配置 truth source | `state.trainingDraft.config/resource` | **IN PROGRESS** | Draft 不再反向镜像；Chrome 主动污染 config；继续迁移 settings/helper 读写 |
| TD-06 | `/train/start` 多 owner / 旧 payload builder | `TrainingSubmitRuntime` | **CLOSED** | `TrainingDraftRuntime.networkOwner=false`；旧 `submitTrain429` 三套实现已从 `app.js` 物理删除；Node + Real Chrome 全绿 |
| TD-07 | “开始训练”按钮 readiness 多 owner | `TrainingSubmitRuntime.trainingSubmitReadiness()` | **CLOSED** | `renderSplit()` 与 `refreshProjected417()` legacy DOM writer 已物理删除；Real Chrome 真点击提交通过 |
| TD-08 | `/jobs` poll + manual 双请求 | `TrainingTaskRuntime` | **CLOSED** | 120ms cross-source coalescing；mutation 强制 fresh；Chrome 要求每次手动刷新仅 1 GET |
| TD-09 | `training-metrics.sqlite3` FD 泄漏 | deterministic SQLite close | **CLOSED** | 单测含连接开关 + Linux `/proc/self/fd`；Release Regression 通过；A800 后续实机再观测 |
| TD-10 | 训练任务 polling 生命周期 | `TrainingTaskRuntime + PollRegistry` | **CLOSED** | 单 owner + 页面生命周期 + request coalescing |
| TD-11 | 自动标注 polling 生命周期 | `AutoLabelPollRuntime + PollRegistry` | **IN PROGRESS** | 主 poll owner 已迁移；继续清 rebind timers / legacy timer |
| TD-12 | 视频切帧 legacy polling | VideoTasks / PollRegistry | **OPEN** | 已识别 `__videoFramePollTimer`，需 owner 判定后物理退役 |
| TD-13 | `auto422Timer` / prelabel / 老 `setupPagePolling` | 各页面 Runtime + PollRegistry | **OPEN** | 做死代码证明，不能只 clear/null |
| TD-14 | 历史 `render=` / `window.setPage=` override | 每页面单 owner | **OPEN** | 建 owner 表，逐层删 412/417/423/428/429 失效层 |
| TD-15 | `app.js` 过大 / 历史死代码 | named Runtime + 有界 legacy shell | **IN PROGRESS** | 已开始物理删除旧 submit/button writer；继续按“证明无引用→测试→删除” |
| TD-16 | 临时 shim / migration helper | 无长期 owner | **CLOSED** | 本轮两个 guarded migration workflow/helper 均在成功后物理删除 |
| TD-17 | 静态资源 cache-busting 不统一 | 单一 cache/build version | **OPEN** | 目前 `styles.css/bootstrap` 与 `app.js/main.mjs` 版本仍不统一 |
| TD-18 | 剩余页面重复请求 / 全量 reload | scoped refresh | **OPEN** | 扫描 `loadAll/loadRelated/loadCore412/render` |
| TD-19 | observer/timer/fetch/render/setPage 生命周期 | 明确 owner + destroy | **OPEN** | 全仓扫描，记录创建者/owner/销毁点/跨页行为 |
| TD-20 | 版本号命名进入业务语义 | `TrainingDialog/DatasetPage/VideoTasks/...` | **OPEN** | owner 收口后逐步语义化，不做盲目全局重命名 |
| TD-21 | 测试历史债 / flaky sleep | deterministic tests | **IN PROGRESS** | `/jobs` 已从产品竞态根治；训练 owner 测试主动污染 legacy mirrors；继续清 sleep 型测试 |
| TD-22 | 文档与代码漂移 | 本总账 + CURRENT_STATE + legacy audit | **IN PROGRESS** | 本文件已更新；另外两份同步更新后关闭 |
| TD-23 | A800 v42.25 RC | A800 acceptance runbook | **DEFERRED** | P0/P1 技术债关闭后恢复 preflight → 首训 → 迭代 → Worker lifecycle |

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

### `TrainingDraftRuntime`

- canonical draft 创建/同步/更新 owner；build `training-draft-runtime-422509`。
- `networkOwner=false`。
- 不拦截 `/train/start`。
- 不允许把 canonical draft 反向写回 `train428AlgorithmId/train428Config/train429Selected` 作为 truth source。

### `TrainingSubmitRuntime`

- `/train/start` 唯一网络 owner；build `training-submit-422504`。
- 拥有 submit readiness、迭代起点安全校验、设备校验、payload 构建与 POST。
- 保留 `lastStage / lastError` 诊断字段。
- `app.js` 内 3 个旧 `window.submitTrain429=async function...` 已物理删除。

### `TrainingLabelRuntime`

- build `module-422507`。
- canonical draft 已有 algorithm 时，素材必须读取 `trainingDraft.materialIds`。
- legacy `train429Selected / train428AlgorithmId` 即使被污染，也不得改变当前标签集合与最终请求。
- 仍有 legacy entrypoint wrappers、rebind timers、MutationObserver，属于后续清理对象，不得被误判为最终架构。

## 3. Chrome 关键门禁

`tests/browser/training-label-selector.spec.mjs` 会主动污染：

```text
train428AlgorithmId
train429Selected
train428Config
```

并验证：

- `state.trainingDraft` 不受污染；
- raw `/train/start` 不被 DraftRuntime 偷改；
- 真点击“开始训练”仍由 `TrainingSubmitRuntime` 发出 canonical payload；
- readiness 不再由 legacy renderer 写回 disabled 状态。

禁止通过放宽断言、增加 sleep、恢复 fetch wrapper、DOM 抢写轮询来“修复”该测试。

## 4. 已物理退役的训练 legacy owner

已从 `static/app.js` 物理退役：

1. final v3 `renderSplit()` 对开始训练按钮 `.disabled` 的 legacy 写入；
2. `refreshProjected417()` 对同一按钮 `.disabled` 的 legacy 写入；
3. 三套历史 `window.submitTrain429=async function...` 及其旧 payload 直发 `/train/start` 实现。

迁移用的一次性 workflow/helper 已删除，不得恢复。

## 5. 当前工作顺序

```text
A. 继续迁移 train429Selected / train428AlgorithmId / train428Config 的真实 UI/helper owner
B. 清 TrainingLabel / TrainingDraft compatibility wrappers 与 rebind timers
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

每个批次必须：`syntax/Node → Real Chrome（涉及 runtime 时）→ 更新本总账 → 下一批`。

## 6. 发布禁令

以下全部通过前禁止正式发布 `v42.25.0`：

- 本总账无未解决 P0/P1；
- Frontend Runtime Stabilization 全绿；
- Release Regression 全绿；
- A800 preflight PASS；
- A800 首训 + verify-job PASS；
- A800 迭代训练 + iteration verify PASS；
- Worker lifecycle/fencing 实机 PASS；
- 用户明确允许 merge `main` / bump version / tag/release。
