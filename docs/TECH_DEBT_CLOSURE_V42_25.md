# v42.25 技术债关闭总账

> **状态：ACTIVE / 技术债优先阶段**  
> **工作分支：`refactor/frontend-runtime-stabilization`**  
> **正式版本：`VERSION.txt` 仍为 `42.24.0`；不得提前发布 `v42.25.0`。**  
> **更新日期：2026-09-11**

## 0. 给后续 AI / Codex 的强制入口

本文件是 v42.25 技术债关闭工作的**权威状态总账**。继续开发前必须先阅读：

1. `docs/TECH_DEBT_CLOSURE_V42_25.md`（本文件）
2. `docs/CODEX_CURRENT_STATE.md`
3. `docs/frontend-legacy-audit.md`

执行规则：

- 不得仅因为 legacy 代码“暂时没被调用”就标记 CLOSED；需要有明确最终 owner、物理退场或有界兼容边界，以及自动化证据。
- 不得为了让 CI 变绿而放宽重复请求、竞态、sleep、timer 或 owner 冲突的断言。
- 不得重新引入 `trainingLabelSelected` / `trainSplitV3`。
- 不得让 `train428AlgorithmId` / `train428Config` / `train429Selected` 重新成为训练提交 truth source。
- 训练 canonical state 是 `state.trainingDraft`。
- `/train/start` 的最终网络 owner 是 `TrainingSubmitRuntime`；`TrainingDraftRuntime` 不得拦截或改写该请求。
- A800 RC 在本文件 P0/P1 技术债关闭前保持 **DEFERRED**。
- 不得合并 `main`、改 `VERSION.txt` 为 42.25.0、打 tag/release，除非技术债关闭 + A800 RC 均通过且用户明确授权。

状态定义：

- `CLOSED`：owner 已收口、相关旧路径已物理退场或被严格隔离、自动化证据通过。
- `IN PROGRESS`：最终 owner 已明确，但仍存在真实运行或物理 legacy 残留。
- `OPEN`：尚未开始或尚未建立可信关闭证据。
- `DEFERRED`：有意延后，且有明确前置条件。

## 1. 技术债总表

| ID | 技术债 | 最终 owner / 目标 | 状态 | 自动化证据 / 当前事实 | 遗留风险 / 下一步 |
|---|---|---|---|---|---|
| TD-01 | `trainingLabelSelected` 历史状态 | `state.trainingDraft.newLabelCodes` | **CLOSED** | `TrainingDraftRuntime.commitDraft()` 强制删除；CI 有 retired mirror guard；浏览器训练测试断言属性不存在 | 禁止重新引入 |
| TD-02 | `trainSplitV3` 历史状态 | `state.trainingDraft.splitMode/materialIds/testMaterialIds/...` | **CLOSED** | `TrainingDraftRuntime.commitDraft()` 强制删除；CI retired mirror guard；浏览器测试断言属性不存在 | 禁止重新引入 |
| TD-03 | `train429Selected` 作为训练素材 truth source | `state.trainingDraft.materialIds` | **IN PROGRESS** | `TrainingLabelRuntime` 已改为 canonical draft 存在 algorithm 时无条件读取 `trainingDraft.materialIds`；单测覆盖 legacy selection 被污染仍不得接管 | `app.js` 仍有历史读写，需继续迁移并物理删除真实 owner |
| TD-04 | `train428AlgorithmId` 作为训练算法 truth source | `state.trainingDraft.algorithmId` | **IN PROGRESS** | TrainingDraft/Submit/Label Runtime 已 canonical-first；Chrome 测试会主动污染 legacy algorithm 验证 canonical 不变 | `app.js` 仍有大量历史引用；需证明哪些已失去 owner 后删除 |
| TD-05 | `train428Config` 作为训练配置 truth source | `state.trainingDraft.config/resource` | **IN PROGRESS** | Draft runtime 不再反向镜像；Chrome 测试主动污染 config 并验证 canonical config 不变 | 配置 UI 的历史 handler 仍存在，需要继续迁移/物理退场 |
| TD-06 | `/train/start` 多 owner / payload 被 wrapper 改写 | `TrainingSubmitRuntime` | **IN PROGRESS** | DraftRuntime `networkOwner=false`；SubmitRuntime `networkOwner=true`；raw fetch 浏览器测试要求不被 Draft 改写；SubmitRuntime build `training-submit-422504` | 等当前 Real Chrome 真点击提交链全绿后再升级为 CLOSED；旧 `submitTrain429` 实现仍需物理清理 |
| TD-07 | “开始训练”按钮 readiness 多 owner | `TrainingSubmitRuntime.trainingSubmitReadiness()` | **IN PROGRESS** | 已物理退掉 final `renderSplit()` writer 和 `refreshProjected417()` writer；按钮写入 `data-training-submit-owner=TrainingSubmitRuntime` | 当前 Real Chrome 回归正在验证；未绿前不得 CLOSED |
| TD-08 | `/jobs` poll + manual refresh 重复竞态 | `TrainingTaskRuntime` | **CLOSED** | 120ms cross-source coalescing；mutation 强制 fresh；manual re-arm PollRegistry；浏览器测试要求一次手动刷新仅 1 GET | 禁止用“允许 1~2 次”放宽测试 |
| TD-09 | `training-metrics.sqlite3` FD 泄漏 | `TrainingMetrics` 短连接 + deterministic close | **CLOSED** | `tests/unit/test_training_metrics_fd.py` 覆盖连接开关与 Linux `/proc/self/fd`；Release Regression 已通过 | A800 新任务仍需实机观察 FD 不线性上涨 |
| TD-10 | 训练任务 polling 生命周期 | `TrainingTaskRuntime + PollRegistry` | **CLOSED** | 单 owner + coalescing + 页面生命周期回归 | 继续防止 app.js 老 polling 重新接管 |
| TD-11 | 自动标注 polling 生命周期 | `AutoLabelPollRuntime + PollRegistry` | **IN PROGRESS** | 主 polling owner 已迁移 | Runtime 仍有 `[100,400,1000]` rebind timers；legacy timer/renderer 需物理关闭 |
| TD-12 | 视频切帧 legacy polling | `VideoTasks` / PollRegistry 目标 owner | **OPEN** | 已识别 `__videoFramePollTimer` 残留 | 做 owner 判定、测试、物理删除 |
| TD-13 | `auto422Timer` / prelabel / 老 `setupPagePolling` | 各页面 Runtime + PollRegistry | **OPEN** | 已扫描到历史残留 | 分页做死代码证明并删除，不允许只 clear/null |
| TD-14 | 历史 `render=` / `window.setPage=` override 链 | 每页面单一最终 renderer/navigation owner | **OPEN** | `app.js` 仍有多代 override | 建 owner 表，逐块删除 412/417/423/428/429 失效层 |
| TD-15 | `app.js` 过大、历史死代码 | 模块化 Runtime / 有界 legacy shell | **IN PROGRESS** | 当前约 873KB；已开始用 exact guarded migration 物理退役 writer | 必须按“可证明无引用 → 测试 → 删除”缩减；禁止盲删 |
| TD-16 | 临时 shim / migration helper | 无长期 owner | **IN PROGRESS** | 已删除一批旧 bootstrap；本轮临时 `retire_training_submit_button_legacy` 仅为 873KB 精确迁移 | 当前 migration 全绿验证后必须删除 script + workflow |
| TD-17 | 静态资源 cache-busting 不统一 | 单一 build/cache version source | **OPEN** | 当前 `styles.css=42.24.0`、bootstrap=42.24.0、`app.js=42.25.x`、`main.mjs=42.25.x` | 设计并统一，不允许浏览器新旧 JS 混跑 |
| TD-18 | 剩余页面重复请求 / 全量 reload | 局部 Runtime refresh / scoped fetch | **OPEN** | 算法列表、训练任务、数据集重点链已优化 | 扫描 `loadAll/loadRelated/loadCore412/render` 的局部操作成本 |
| TD-19 | `MutationObserver/setInterval/setTimeout/window.fetch=/render=/setPage=` 生命周期 | 明确 owner + destroy | **OPEN** | 全仓扫描已开始 | 每一个需记录创建者、owner、销毁点、跨页行为 |
| TD-20 | 版本号命名进入业务语义（428/429/412/424） | `TrainingDialog/DatasetPage/VideoTasks/...` 语义命名 | **OPEN** | 迁移阶段仍大量存在 | 先收 owner，再逐步重命名，避免大规模无收益 churn |
| TD-21 | 测试历史债 / flaky sleep | deterministic contract tests | **IN PROGRESS** | `/jobs` 已改成真实竞态契约；training browser test 会主动污染 mirrors 验证 canonical owner | 继续清等待型测试；不能用放宽次数掩盖竞态 |
| TD-22 | 文档与代码漂移 | 本总账 + CURRENT_STATE + legacy audit 同步 | **IN PROGRESS** | 已创建本权威总账 | 当前 `CODEX_CURRENT_STATE.md` / `frontend-legacy-audit.md` 仍需更新到本轮状态 |
| TD-23 | A800 v42.25 RC | A800 acceptance runbook | **DEFERRED** | `a800_rc_acceptance.py` / runbook 已存在 | 技术债 P0/P1 关闭后恢复 preflight → 首训 → 迭代 → Worker lifecycle |

## 2. 当前训练 canonical owner（不得回退）

目标链：

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

职责边界：

### `TrainingDraftRuntime`

- 拥有 canonical draft 的创建、同步、更新。
- `networkOwner=false`。
- 不允许拦截 `/train/start`。
- 不允许把 canonical draft 反向写回 `train428AlgorithmId/train428Config/train429Selected` 作为 truth source。

### `TrainingSubmitRuntime`

- `/train/start` 唯一目标网络 owner。
- 拥有 submit readiness、迭代起点安全校验、设备校验、payload 构建与 POST。
- 永久保留诊断字段：`lastStage` / `lastError`，用于 Chrome/E2E 定位“点击但未 POST”的前置失败。
- 当前 build：`training-submit-422504`。

### `TrainingLabelRuntime`

- 当前训练对话框素材选择必须优先 `state.trainingDraft.materialIds`。
- canonical draft 已有明确 algorithm 后，legacy `train429Selected` 与 `train428AlgorithmId` 即使被污染也不得改变本次标签集合。
- 当前 build：`module-422507`。

## 3. 当前真实 Chrome 回归策略

`tests/browser/training-label-selector.spec.mjs` 是训练 owner 收口的关键真实浏览器门禁。它会：

1. 用真实 API 创建 project / fire+smoke 素材 / algorithm。
2. 在 UI 内选择素材、标签、资源、训练参数。
3. 主动把：
   - `train428AlgorithmId`
   - `train429Selected`
   - `train428Config`
   写成错误值。
4. 验证 `state.trainingDraft` 不受污染。
5. 验证 raw caller 直接 fetch `/train/start` 不被 DraftRuntime 偷改 payload。
6. 验证真实点击“开始训练”由 `TrainingSubmitRuntime` 发出 canonical payload。

该测试不得通过以下方式“修复”：

- 放宽断言；
- 允许 legacy mirror 接管；
- 添加轮询抢写 DOM 来掩盖多个 owner；
- 仅增加 sleep；
- 重新加 `/train/start` fetch wrapper。

## 4. 本轮已经物理退役的训练按钮 writer

已从 `static/app.js` 物理退役：

1. final v3 `renderSplit()` 对 `.train428-footer .btn.primary.disabled` 的 legacy 写入；
2. `refreshProjected417()` 使用 `train429Selected/train428AlgorithmId/iteration414` 对同一按钮 `.disabled` 的 legacy 写入。

最终 owner 必须保持 `TrainingSubmitRuntime.trainingSubmitReadiness()`。

## 5. 当前工作顺序

在没有新的用户优先级变更时，继续按以下顺序：

```text
A. 训练 canonical owner Chrome 全绿
B. 物理删除旧 submit/payload/mirror 真运行链
C. timer/polling owner 清理
D. renderer/setPage override owner 清理
E. app.js 可证明死代码削减
F. 重复请求 / 全量 reload 扫描
G. cache-busting 统一
H. observer/timer/fetch wrapper 零点扫描
I. 版本号命名迁移
J. 测试去抖动 + 文档同步
K. 技术债零点扫描
L. A800 RC
```

每完成一个小批次：

```text
Node/syntax/contract tests
→ Real Chrome（涉及前端 runtime 时）
→ 更新本总账
→ 再进入下一批
```

## 6. 发布禁令

在以下条件全部满足前，**禁止正式发布 v42.25.0**：

- 本总账无未解决 P0/P1；
- Frontend Runtime Stabilization 全绿；
- Release Regression 全绿；
- A800 preflight PASS；
- A800 首次短训练 + verify-job PASS；
- A800 迭代训练 + iteration verify PASS；
- Worker lifecycle/fencing 实机 PASS；
- 用户明确允许合并 `main` / bump version / tag release。
