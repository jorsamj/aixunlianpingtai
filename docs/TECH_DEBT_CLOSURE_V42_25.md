# v42.25 技术债关闭总账

> **状态：ACTIVE / 技术债优先阶段**  
> **工作分支：`refactor/frontend-runtime-stabilization`**  
> **正式版本：`VERSION.txt` 仍为 `42.24.0`；不得提前发布 `v42.25.0`。**  
> **最近完整验证代码点：`495721171832aa06b99785b37d32996e5cd26bf5`，Frontend Runtime run `34592149034`：Node + Real Chrome 全绿。**  
> **当前在验代码点：`e062ea354dc8d21b0e0d47d76d55f0a28b4b8cf3`，用于 canonical config reader 跨历史 scope 修复；未绿前不得标本批 CLOSED。**  
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
- `/train/start` 唯一网络 owner 是 `TrainingSubmitRuntime`；`static/app.js` 中出现 `/train/start` 即视为回归，永久 CI guard 会失败。
- A800 RC 在本文件 P0/P1 技术债关闭前保持 `DEFERRED`。
- 未经用户明确授权，不得 merge `main`、把 `VERSION.txt` 改为 `42.25.0`、打 tag 或发布 release。

状态定义：`CLOSED` / `IN PROGRESS` / `OPEN` / `DEFERRED`。

## 1. 技术债总表

| ID | 技术债 | 最终 owner / 目标 | 状态 | 当前证据 / 下一步 |
|---|---|---|---|---|
| TD-01 | `trainingLabelSelected` | `state.trainingDraft.newLabelCodes` | **CLOSED** | Runtime 强制退休；CI + Chrome 防回归 |
| TD-02 | `trainSplitV3` | `state.trainingDraft` split/material fields | **CLOSED** | Runtime 强制退休；CI + Chrome 防回归 |
| TD-03 | `train429Selected` 作为训练素材 truth source | `state.trainingDraft.materialIds` | **IN PROGRESS** | Label/Submit 已 canonical-first；`app.js` 仍有历史 picker/helper 读写，继续迁移真实 owner |
| TD-04 | `train428AlgorithmId` 作为训练算法 truth source | `state.trainingDraft.algorithmId` | **IN PROGRESS** | Chrome 会主动污染 legacy algorithm 并验证提交不受影响；最终 429 启动与迭代设置仍有历史读写待迁 |
| TD-05 | `train428Config` 作为训练配置 truth source | `state.trainingDraft.config/resource` | **IN PROGRESS** | v3 device/GPU/resource strategy 双写已物理退出并经 run `34592149034` Chrome 验证；428/429/415 配置读取正迁为 canonical-first；历史 settings writer 仍待迁 |
| TD-06 | `/train/start` 多 owner / 旧 payload builder | `TrainingSubmitRuntime` | **CLOSED** | 所有 classic `app.js` 直发 `/train/start` owner 已物理清零：3 个 `submitTrain429` + 9 个更早 `startTrain/startTrain423/submitTrain424/425/428`；run `34591792092` Node + Chrome 全绿；永久 CI guard 禁止 `app.js` 再出现 `/train/start` |
| TD-07 | “开始训练”按钮 readiness 多 owner | `TrainingSubmitRuntime.trainingSubmitReadiness()` | **CLOSED** | `renderSplit()` 与 `refreshProjected417()` legacy DOM writer 已物理删除；Real Chrome 真点击提交通过 |
| TD-08 | `/jobs` poll + manual 双请求 | `TrainingTaskRuntime` | **CLOSED** | 120ms cross-source coalescing；mutation 强制 fresh；Chrome 要求每次手动刷新仅 1 GET |
| TD-09 | `training-metrics.sqlite3` FD 泄漏 | deterministic SQLite close | **CLOSED** | 单测含连接开关 + Linux `/proc/self/fd`；Release Regression 通过；A800 后续实机再观测 |
| TD-10 | 训练任务 polling 生命周期 | `TrainingTaskRuntime + PollRegistry` | **CLOSED** | 单 owner + 页面生命周期 + request coalescing |
| TD-11 | 自动标注 polling 生命周期 | `AutoLabelPollRuntime + PollRegistry` | **IN PROGRESS** | 主 poll owner 已迁移；继续清 rebind timers / legacy timer |
| TD-12 | 视频切帧 legacy polling | VideoTasks / PollRegistry | **OPEN** | 已识别 `__videoFramePollTimer`，需 owner 判定后物理退役 |
| TD-13 | `auto422Timer` / prelabel / 老 `setupPagePolling` | 各页面 Runtime + PollRegistry | **OPEN** | 做死代码证明，不能只 clear/null |
| TD-14 | 历史 `render=` / `window.setPage=` override | 每页面单 owner | **OPEN** | 建 owner 表，逐层删 412/417/423/428/429 失效层 |
| TD-15 | `app.js` 过大 / 历史死代码 | named Runtime + 有界 legacy shell | **IN PROGRESS** | 已物理删除旧 submit/button/network owner；继续按“证明无引用→测试→删除” |
| TD-16 | 临时 shim / migration helper | 无长期 owner | **IN PROGRESS** | 已完成的 submit/network/resource migration helper 均已删除；当前 config-read migration helper 仅在本批验收期间保留，Chrome 全绿后必须删除 |
| TD-17 | 静态资源 cache-busting 不统一 | 单一 cache/build version | **OPEN** | 当前 `styles.css/bootstrap=42.24.0`，`app.js` 已到 `42.25.40`，`main.mjs=42.25.38`，仍不统一 |
| TD-18 | 剩余页面重复请求 / 全量 reload | scoped refresh | **OPEN** | 扫描 `loadAll/loadRelated/loadCore412/render` |
| TD-19 | observer/timer/fetch/render/setPage 生命周期 | 明确 owner + destroy | **OPEN** | 全仓扫描，记录创建者/owner/销毁点/跨页行为 |
| TD-20 | 版本号命名进入业务语义 | `TrainingDialog/DatasetPage/VideoTasks/...` | **OPEN** | owner 收口后逐步语义化，不做盲目全局重命名 |
| TD-21 | 测试历史债 / flaky sleep | deterministic tests | **IN PROGRESS** | `/jobs` 已从产品竞态根治；训练 owner 测试主动污染 legacy mirrors；本轮还暴露了跨 IIFE helper scope 的真实浏览器错误，说明 Chrome 门禁必须保留 |
| TD-22 | 文档与代码漂移 | 本总账 + CURRENT_STATE + legacy audit | **IN PROGRESS** | 三份文档保持持续同步；本总账记录当前在验批次，不以迁移脚本单测替代 Chrome 结果 |
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
- `static/app.js` 现在不得包含 `/train/start`；`.github/workflows/frontend-runtime-stabilization.yml` 有永久 guard。

### `TrainingLabelRuntime`

- build `module-422507`。
- canonical draft 已有 algorithm 时，素材必须读取 `trainingDraft.materialIds`。
- legacy `train429Selected / train428AlgorithmId` 即使被污染，也不得改变当前标签集合与最终请求。
- 仍有 legacy entrypoint wrappers、rebind timers、MutationObserver，属于后续清理对象，不得被误判为最终架构。

## 3. 已完成的训练资源 mirror 收口

v3 最终资源控件：

```text
trV3ResourceStrategy
trV3Device
trV3GpuPolicy
```

当前 owner：`TrainingDraftControlsRuntime` → `TrainingDraftRuntime.update()`。

已删除 `app.js` 中对以下 legacy 字段的重复 change writer：

```text
train428Config.resource_strategy
train428Config.device
train428Config.gpu_policy
```

推荐设备也改为直接写 `trainingDraft.resource.device`。该批在 `495721171832aa06b99785b37d32996e5cd26bf5` / run `34592149034` 经 Node + Real Chrome 全绿验证。

## 4. 当前 canonical config read 迁移

目标：配置展示和历史 settings helper 先改为 canonical-first，解除后续删除 `train428Config` writer 的读取依赖。

已建立过渡 reader：

```text
trainingDraft.config/resource
  优先
legacy train428Config
  仅作为尚未迁完历史设置 UI 的 fallback
```

第一次实现把 reader 留在 428 局部 scope，却让后续 429/415 直接调用，Real Chrome 在“点击训练→弹窗出现”处失败；这不是测试抖动，而是多代 IIFE/override 造成的真实 scope bug。当前修复将该 closure reader 显式导出供后续 scope 调用。**此批只有 run `34592853161` Real Chrome 通过后才能标完成。**

## 5. Chrome 关键门禁

`tests/browser/training-label-selector.spec.mjs` 会主动污染：

```text
train428AlgorithmId
train429Selected
train428Config
```

并验证 canonical draft、raw fetch、真实点击提交均不受污染。禁止通过放宽断言、增加 sleep、恢复 fetch wrapper、DOM 抢写轮询来“修复”该测试。

## 6. 已物理退役的训练 legacy owner

已从 `static/app.js` 物理退役：

1. final v3 `renderSplit()` 对开始训练按钮 `.disabled` 的 legacy 写入；
2. `refreshProjected417()` 对同一按钮 `.disabled` 的 legacy 写入；
3. 三套历史 `window.submitTrain429=async function...`；
4. 九套更早 classic 直发 `/train/start` 的实现：`startTrain` ×4、`startTrain423` ×1、`submitTrain424` ×1、`submitTrain425` ×2、`submitTrain428` ×1；
5. final v3 resource strategy/device/GPU policy 对 `train428Config` 的重复 writer。

对应一次性 migration workflow/helper 在各自完整回归通过后均删除；不得恢复。

## 7. 当前工作顺序

```text
A. 完成 canonical config reader Chrome 验证
B. 删除 startAlgorithmTraining429 / trainTarget429 / trainAlg429 对 train428Config 的主动 writer
C. 迁移 train428AlgorithmId / train429Selected 的最终活跃 owner
D. 清 TrainingLabel / TrainingDraft compatibility wrappers 与 rebind timers
E. 清 auto422Timer / __videoFramePollTimer / prelabel / setupPagePolling
F. 建 renderer / setPage 最终 owner 表并物理退役旧 override
G. app.js 可证明死代码削减
H. 重复请求 / 全量 reload 扫描
I. cache-busting 统一
J. observer/timer/fetch wrapper 零点扫描
K. 版本号业务命名迁移
L. 测试去抖动 + 文档持续同步
M. 技术债零点扫描
N. A800 RC
```

每个批次必须：`syntax/Node → Real Chrome（涉及 runtime 时）→ 更新本总账 → 下一批`。

## 8. 发布禁令

以下全部通过前禁止正式发布 `v42.25.0`：

- 本总账无未解决 P0/P1；
- Frontend Runtime Stabilization 全绿；
- Release Regression 全绿；
- A800 preflight PASS；
- A800 首训 + verify-job PASS；
- A800 迭代训练 + iteration verify PASS；
- Worker lifecycle/fencing 实机 PASS；
- 用户明确允许 merge `main` / bump version / tag/release。
