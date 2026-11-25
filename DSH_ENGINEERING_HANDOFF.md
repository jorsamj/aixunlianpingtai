# DSH Engineering Handoff — 畅联云算法训练平台

- 交接时间：2026-11-24（Asia/Shanghai）
- 原工程根目录：`C:\Users\jorsam\Documents\ChatGPT\算法相关\p2b2-backend`
- 新工程根目录：`D:\lab\p2b2-backend`
- 唯一开发分支：`feature/external-algorithm-publishing`
- 交接本地 HEAD：`0ca94867c35d439ded1bd9f776cf1b64c02c3ee7`
- 远端：`origin https://github.com/jorsamj/aixunlianpingtai.git`
- VERSION：见 `VERSION.txt`，迁移不得修改
- 本文件为新增交接文档，不属于四份受保护文档。

## 1. 项目与架构

畅联云算法训练平台：FastAPI 模块化单体 + SQLite TaskRepository + Node Agent 分布式执行 +
Vue 3/TypeScript 前端。核心执行链：

`node_agent.py → NodeAgentExecutorLoop → AgentTrainingRunner / AgentConversionRunner → CPU/GPU Worker → NodeExecutorClient → FastAPI → TaskRepository/Assignment/Lease/Fencing/Hold`

禁止新建第二套 Scheduler、Repository、模型注册中心、标注系统；禁止 PostgreSQL 迁移、Kubernetes、Ray、微服务化。

## 2. 已完成并需保留的成果

- 正式 AgentTrainingRunner HTTP 生命周期 E2E（12 条）。
- 正式 NodeAgentExecutorLoop + AgentTrainingRunner A/B/C 双槽 CPU E2E。
- NO_PROCESS_LAUNCHED 与 Stop Proof 合同、proof_type、不可变身份。
- 中央 `recover_execution`、Hold 状态矩阵、finish/Hold Trigger 故障恢复、中央 OS 冷重启恢复。
- schema-6/schema-7 冻结 fixture 与真实迁移；旧 Stop Proof legacy digest 兼容。
- Windows 长路径 LocalStorageProvider 全生命周期；分页仅对返回页计算 SHA256。
- W9 ModelArtifact 自动上传 122 个相关测试通过。
- 双节点真实 `node_agent.py` HTTP loopback、SIGKILL 后中央不错误重排、Fencing。
- 最新 P0-01：Slot generation 保持 Assignment generation；execution attempt 独立；
  Workdir 元数据持久化 assignment generation/GPU；Coordinator 严格双槽身份对账；
  Slot intent 按 assignment generation + execution attempt + GPU 清理。

## 3. 当前状态与阻断

- `FORMAL_RUNNER_E2E_PASS`：功能本地通过；最新 SHA CI 可能仍在运行。
- `CPU_PROTOCOL_BLOCKED`：缺少真实 Node Agent OS SIGKILL → 新 Agent → 中央 HTTP 恢复训练 E2E。
- `MULTI_NODE_CPU_PROTOCOL_BLOCKED`：双槽 Worker/Agent 崩溃隔离、多节点失联恢复未完成。
- W9 Manifest/ONNX/ORT/检测框一致性/发布回滚合同未完成。
- W10 负样本正式入训、反馈到 GT、下一轮训练闭环未完成。
- W11–W16 训练生命周期、数据/存储治理、前端迁移、规模性能、离线升级、单槽生产候选未完成。
- `REAL_GPU_UAT_NOT_VERIFIED`、`REAL_HARDWARE_INFERENCE_NOT_VERIFIED`、
  `PRODUCTION_DUAL_SLOT_DISABLED`、`A800_PREFLIGHT_REQUIRED`、
  `A800_PRODUCTION_UPGRADE_NOT_EXECUTED`。

## 4. P0 安全合同（下一会话优先复核）

1. Slot reservation key = `(task_id, assignment_generation)`；`slot.generation` 是 Assignment generation。
2. Workdir / ProcessIdentity / Hold execution attempt 使用 `execution_attempt`。
3. `mark_started` 必须校验中央 Lease 的 assignment generation 与 GPU UUID 与本地预留一致。
4. 双槽恢复缺失 assignment generation/GPU UUID 必须 BLOCKED，不能用中央当前值补齐。
5. 有 Hold 的中央终态恢复必须核验 task/node/attempt/assignment/GPU/ProcessIdentity/proof_type；
   `proof_sha256` 只读字段已暴露但 Coordinator 后置比较仍需补强。
6. 本地清理顺序仍为“先 ProcessIdentity 再 Slot intent”，故障窗口待整改。
7. 真实 Linux Agent SIGKILL 训练恢复 E2E 尚未实现。

## 5. 后续自主开发授权与顺序

此前 W7-B–W16 连续开发授权继续有效。新会话从以下顺序继续，不需要逐阶段重新授权：

1. 完成 P0-01B/C/D：proof_sha256 后置核验、清理故障窗口、正式 Loop Assignment=5/attempt=2 全链路恢复。
2. 实现真实 Linux `node_agent.py` SIGKILL → 新 Agent → 中央恢复训练 E2E；Windows 只做身份逻辑测试。
3. W10 负样本正式入训（隔离数据）：人工确认 → 算法关联 → 正式 GT → 训练选择 → 冻结快照。
4. W9 ONNX 拓扑/Checker/ORT、张量一致性、检测框一致性、Manifest、发布/回滚合同。
5. W11 训练生命周期（TRAINING_FREEZE_PUBLICATION_INCOMPLETE、参数、取消、checkpoint、报告）。
6. W15/W16 单槽生产候选独立验收、离线升级/回滚预检；不得等待实验性双槽全部完成。
7. W8 双槽/多节点完整故障隔离。
8. W12 数据存储治理、W13 渐进前后端迁移、W14 规模性能。

每阶段：最小正确实现 → 定向测试 → git diff 审核 → 指定文件 git add → commit → 正常 fast-forward push → 继续。

## 6. Git / 生产 / 产品边界

- 唯一分支 `feature/external-algorithm-publishing`；禁止 reset、clean、stash、rebase、force push、merge main、git add -A。
- 禁止修改 `VERSION.txt` 和四份受保护未跟踪文档：
  - `DSH_C2B_HANDOFF_20261121.md` SHA256 `F1B88032EA60265FD6B724CB3741C3F204486FA253AD4B11223AA550B56B72C8`
  - `docs/architecture/P2B_4A_2A_TASK_RUNTIME_ARCHITECTURE_AUDIT_20261118.md` SHA256 `FD611A41B13EDA29A1086DCD1361CA39A20306E0619665CD7AAB07982AA35B12`
  - `docs/architecture/P2B_4A_2B_LOCAL_CLAIM_PIPELINE_20261118.md` SHA256 `179C2A63049365F675BF544FEF8BCA3C19A2BEDACD85D216416401C6B562BEC0`
  - `docs/architecture/P2B_4A_2B_PAYLOAD_PUBLICATION_DESIGN_20261118.md` SHA256 `67A3DFC5926C6769F0714F904AFDED149E3DB24CEEE6521CEE30D18B666FEA9D`
- 禁止访问/操作 A800、4070、生产 SQLite、生产素材/GT/模型、生产服务、真实发布/部署、生产双槽。
- 不修改 Vue 菜单、算法库卡片页、素材库入口、原业务布局。
- 不引入新 Scheduler、微服务、PostgreSQL、Kubernetes、Ray。

## 7. 新会话第一项任务

在新根目录 `D:\lab\p2b2-backend` 打开 DeepSeek Harness，先只读核验：
`git rev-parse --show-toplevel`、HEAD、branch、status、remote、四份保护文档 SHA256、`VERSION.txt`。

然后执行 P0-01B/C/D：Coordinator 使用 `proof_sha256` 做恢复后置核验；修复本地清理顺序；
用正式 `NodeAgentExecutorLoop` 验证 Assignment generation=5、execution attempt=2 的预留、
start、mark_started、Worker、恢复、Slot intent 精确清理、新任务准入。

## 8. 迁移说明

- 采用“复制 → 验证 → 切换”，C 盘原目录保留为临时备份，未获授权不得删除。
- D 盘目录验证通过后成为唯一开发工作区；禁止两个目录同时开发。
- 本文件随工程复制，位于新根目录 `DSH_ENGINEERING_HANDOFF.md`。

## 9. 本轮（2026-11-24 续接会话）进度

### 9.1 身份核验（通过）

- 工作区 `D:\lab\p2b2-backend`，分支 `feature/external-algorithm-publishing`。
- 起始 HEAD `0ca94867` = 远端 HEAD；VERSION.txt `42.24.592`；无已跟踪改动；四份保护文档与
  `DSH_C2B_HANDOFF_20261121.md` SHA256 全部匹配；`DSH_ENGINEERING_HANDOFF.md` 迁移 SHA 匹配。
- 网络：GitHub 连接时断时续，push 曾失败一次，后恢复并成功。

### 9.2 M0｜CI 回归修复（已完成，已推送）

- 提交 `3e01cf29 fix: distinguish legacy and corrupt workdir recovery metadata`。
- 根因：`list_process_identities()` 新增 `assignment_generation`/`gpu_uuid` 恢复元数据，
  原测试仍用旧完整字典相等断言。
- 整改：保留 `process-identity.json` 精确字段与令牌不泄漏断言；`read_process_identities`
  合同不变；恢复元数据只来自本 workdir 的 `execution.json`（launch 前持久化的 start 响应），
  历史缺失 = `0/""`；携带但不可用的 Assignment 证据 = 损坏，fail-closed，不降级为历史形态。
- 定向测试：`test_node_agent_executor_runtime.py` + 三个 node agent 套件 73 passed/13 skipped。

### 9.3 M1｜P0 恢复合同收口（已完成，已推送）

- 提交 `df61811f fix: bind dual-slot recovery to the original assignment contract`。
- 4.1 `mark_started` 原子绑定：全部身份核验（task/execution generation/assignment
  generation/GPU/Assignment 证据存在）通过后才写入 `slot.lease`/`slot.execution_attempt`；
  拒绝时不留污染；`_run_dual_once` 增加 start 响应与预留身份的显式对账。
- 4.2 原始槽位合同：中央 `start_execution` 计算一次 `execution_slots`，写入 released
  assignment `resolved_execution_config.$.execution_slots` 与 start 响应
  `execution.execution_slots`；Agent 持久化到 `execution.json`。`_dual_hold_verified()`
  改为按该持久合同判定（合同 2 缺 Hold 一律拒绝，合同 1 视为合法单槽，仅 pre-marker 历史
  记录回退到能力启发式）；历史单槽无 Hold 的恢复不再被错误阻断，双槽缺 Hold 不因节点降级放行。
- 4.3 Stop Proof：Coordinator 前后置核验——Task 合法终态、Hold RELEASED、proof_type、
  `proof_sha256` 用原始身份+assignment+GPU 本地复算（当前 schema + schema-6/7 legacy 双兼容）、
  恢复返回 digest 必须等于重新查询值、已 RELEASED 幂等分支、NO_PROCESS_LAUNCHED 与持久
  ProcessIdentity 矛盾拒绝。
- 4.4 可恢复清理：先清 Slot intent 再删 ProcessIdentity（唯一原始执行证据留存），两步幂等
  可收敛；同任务但不匹配的 intent 显式报错、不静默忽略、不删其他任务/新 attempt。
- 定向测试：194 passed / 16 skipped（含 4.1 Formal Assignment=5/attempt=2 绑定、
  4.2 中央降级不释放、4.3 digest 正反例、4.4 故障窗口收敛与 intent 不误删）。
- 边界：真实 Linux POSIX SIGKILL 全链路仍在 M2；Windows 恢复继续 fail-closed。

### 9.4 CI（df61811f，单次查询结果，2026-11-24 11:47）

- 31 个工作流已触发；16 completed 全部 success；其余 queued/in_progress
  （Node Agent Executor / Remote Training Runtime / Remote Conversion Runtime /
  Task Runtime Truth / Training Input Integrity / Online Feedback 等）。
- 上一轮 4 个红工作流中 Portable Deployment、Remote Cleaning Runtime 已 success。

### 9.5 本轮后续提交（时间顺序）

| SHA | 内容 | 定向测试 |
|---|---|---|
| `420e0755` | 恢复协调器 Fake 客户端按真实 `/recover` 合同返回 `proof_sha256`；两个原 POSIX-only 逻辑测试改为跨平台 `_use_posix_recovery`（本地可跑，防漏检） | recovery 21 passed/5 skipped |
| `f7298f9d` | 双槽 reap 单飞锁 + `SlotNotReleased` 幂等容忍（修复 CI 偶发 `slot is not the current registered execution`）；W15/W16 默认单槽不变量测试 | 137 passed/8 skipped |
| `e041ff53` | W10：算法级负样本池接入训练选择（`NegativePool.algorithm_scope_sql` 唯一 Owner）、首次纯负样本/新类别纯负样本 typed admission code（`TRAINING_FIRST_TRAINING_REQUIRES_POSITIVE`/`TRAINING_NEGATIVE_ONLY_NEW_LABEL_FORBIDDEN`）→ prepare error code / 同步 409、11 条真实 SQLite 端到端测试 | 新增 11 passed；picker/negative/training/prepare 套件 103+90+27 passed |
| `011c0441` | W16：`tools/production_upgrade.py` 受控备份（控制面 SQLite 在线一致快照 + manifest digest + quick_check + 有界/空间/空闲预检）、回滚（verify→dry-run→POSIX+root→ack→pre-rollback 安全快照→停服→原子替换→健康校验）、CLI 向后兼容 | 27 passed/1 skipped |
| `7356131e` | **生产缺陷修复**：`execution_status` SQL NULL 被 `str()` 成 "None" 导致 HELD 执行被恢复协调器误判为已有 Stop Proof、真实 SIGKILL 恢复必然 fail-closed；`proof_type/proof_sha256/assignment_lease_expires_at` 保留 None + 回归测试 | 30 passed |
| `5cbe36c1` | 默认单槽不变量测试在缺 PyYAML/Pillow/psutil 的 CI job 显式 skip（不降级断言） | — |
| `97f3fd91` | M2：真实 `node_agent.py` staged runtime + 真实中央 HTTP + 真实 Worker 子进程；POSIX SIGKILL 全链路（Agent SIGKILL → 新 Agent → 本地证据 → 中央 `/recover` → 原 Worker 停止 → PROCESS_STOP_VERIFIED + Hold RELEASED → intent/identity 清理 → 新任务准入）；Windows 跨平台 fail-closed 变体；CI 增加 Linux-only step 与 paths | 本地 1 passed/1 skipped（POSIX 仅 Linux CI）+ fail-closed 1 passed |

### 9.6 已知 CI 说明

- e041ff53 的一批红 job 根因是主代理新增的默认单槽测试在未安装训练依赖的 job 中触发
  `ModuleNotFoundError: yaml`；已在 5cbe36c1 用 `pytest.importorskip` 显式 skip 修复。
- 双槽 reap 并发竞态（同一 SHA 的 PR 运行绿、push 运行红）已由 f7298f9d 的单飞锁修复。
- M2 的 POSIX 全链路只在 Linux CI 验证；该场景已于 `39a1d0f1` 获得正式 Linux CI
  证据（见 §9.9 与 `AGENT_SIGKILL_RESTART_E2E_PASS`）。

### 9.7 进行中工作流（子代理并行）

- W9 模型质量：真实 PT/ONNX 比较（坐标还原/匹配 IoU/动态输入/runtime 版本）、不可变
  Source Manifest + digest、状态投影；本机 torch/ultralytics/onnx/onnxruntime 可真实执行。
- W8/M7：Worker 外部 SIGKILL 隔离、双槽 fencing、能力撤销后恢复安全、
  `execution_status.execution_slots` 诊断字段。
- W11/W12 调研已完成（见下）；实现待 W9 释放共享 app.py 后启动。

### 9.8 收盘结果（本轮最终，候选 SHA `39a1d0f1`）

追加提交：

| SHA | 内容 | 定向验证 |
|---|---|---|
| `c696ea8d` | CI 修复：ONNX 输入合同在加载 PT 模型之前判定（动态未冻结尺寸不再需要 torch）；恢复测试改用无可选依赖的 `deployment-test` 能力 | 本地 + 屏蔽 torch 仿真下动态合同测试通过 |
| `39a1d0f1` | W11/W12 收口：冻结发布守卫窄化 + `training.freeze` 只读诊断投影、创建时 `reference_version_id` 固化进 payload 并在 freeze 断言血缘、`read_training_input_freeze()` 统一 payload evidence 优先/legacy 回退、报告 requested/actual 参数一致性告警 | prepare 30 / api 90 / unit 75 / W10+picker 67 / usage 78 全绿 |

同轮已完成（前序提交）：W9 真实 PT/ONNX 比较与不可变 Source Manifest（`b7aa8560`）、
W8/M7 双槽故障隔离（`56b22658`）、W15/W16 单槽候选证据（`ec1199f8`）。

最终状态标签（保持）：

- `REAL_GPU_UAT_NOT_VERIFIED`
- `REAL_HARDWARE_INFERENCE_NOT_VERIFIED`
- `PRODUCTION_DUAL_SLOT_DISABLED`
- `A800_PREFLIGHT_REQUIRED`
- `A800_PRODUCTION_UPGRADE_NOT_EXECUTED`
- `OFFLINE_INSTALL_NOT_VERIFIED`
- `AGENT_SIGKILL_RESTART_E2E_PASS`（**已由准确 Linux CI 证据确认**）：
  SHA `39a1d0f1`，workflow run `45331930879`（Node Agent Executor，pull_request，
  conclusion=success），Linux job `138234917704`，其中 step
  `POSIX Agent crash-window SIGKILL isolation (no GPU)` 与
  `Real Node Agent OS SIGKILL recovery E2E (Linux, no GPU)` 均 SUCCESS。
  该标签**仅覆盖**“真实 node_agent.py OS 进程 SIGKILL → 新 Agent → 中央 HTTP 对账 →
  Stop Proof → Hold RELEASED → 清理 → 新任务准入”这一场景；
  响应丢失五类、双槽两槽同时崩溃分别恢复、同 GPU 重新准入、同 node_id 双实例、
  真实 GPU 验收**仍未覆盖**，继续单独记录。
- `REAL_OS_SIGKILL_RECOVERY_NOT_VERIFIED`：不再用于上述核心场景；仅用于尚未覆盖的
  POSIX 恢复子合同（见 M15 队列）。

### 9.9 CI 事实核对（M9，2026-11-24）

- 代码候选 `39a1d0f1`：50 个 workflow run 全部 completed；其中 48 success。
  非 success 两项均已定性：
  1. `Remote Material Import`（PR run `45331930750`）`cancelled`：由后续运行/并发取消，
     同 SHA 的 push run `45331923075` success、最终 SHA `fe0e964c` 的 PR run
     `45332708407` success ⇒ 等价通过，不计失败根因。
  2. `Node Agent Executor`（push run `45331923029`）Windows `contract` 失败：
     `test_real_agent_restart_is_fail_closed_without_stop_proof` 中的真实 Agent 以
     退出码 2 结束，argparse 报 `argument --token: expected one argument`。
     根因：节点 token 由 `secrets.token_urlsafe` 生成，可能以 `-` 开头，作为独立 argv
     传给 `--token` 时被 argparse 当成选项（同 SHA 的 PR run 通过 = token 恰好未以 `-`
     开头的时序随机）。已修复：
     - `node_agent.py::_normalized_argv` 将 `--token -<value>` 规范化为 `--token=<value>`
       （生产 CLI 健壮性缺陷，不只是测试问题）；
     - M2 harness 显式使用 `--token=<value>`；
     - 新增回归测试 `test_cli_accepts_tokens_that_start_with_a_dash`。
- 最终文档 SHA `fe0e964c`：22 runs，21 completed（0 failure）+1 in_progress（当次查询）。
- CI 查询规则：单次查询记录状态，不轮询；pending 不宣称验收通过。


下一轮优先：

1. 复核候选 SHA `39a1d0f1` 的准确 CI（Node Agent Executor 的 Linux SIGKILL step、
   Remote Conversion Runtime、Portable Deployment、Remote Training Runtime 等）。
2. M8/W13-W14（Vue 渐进迁移剩余、API 合同、20 万素材/千级模型/SQLite 锁竞争真实测量）。
3. W8 剩余：真实双槽 GPU UAT（需现场授权）、同 node_id 双实例/运维诊断面。
4. W11 剩余：取消上限/卡死回收、缓存空闲维护调度、ETA 陈旧标记。
5. 现场 W15/W16：按 `docs/architecture/W15_W16_SINGLE_SLOT_PRODUCTION_CANDIDATE_20261124.md`
   顺序执行预检/备份/升级/回滚，需单独授权。



### 9.10 第二轮（M9–M17）交付摘要（2026-11-24 下午）

代码候选（本轮最终代码 SHA，推送后以远端为准）：`3d17cc74`（后续仅文档提交）。

| 提交 | 内容 | 关键验证 |
|---|---|---|
| `d803afea` | M9：真实 Agent 以退出码 2 结束的根因（`secrets.token_urlsafe` 可能以 `-` 开头 → argparse 误判）；`node_agent.py::_normalized_argv` + harness `--token=` 形式 + 回归测试；交接记录 `AGENT_SIGKILL_RESTART_E2E_PASS`（run 45331930879 / Linux job 138234917704，POSIX+真实 SIGKILL 两个 step SUCCESS） | 回归测试通过；fail-closed E2E 连跑 3 次稳定 |
| `3cacaef3` | W11/W12：空闲门控的训练 bundle 缓存维护（dry-run 预览、活跃/取消未收口/共享引用保护、1h 节流、后台 Worker 调度、按项目故障隔离） | `test_training_bundle_cache.py` 21 passed/1 skipped（Windows 长路径需短 basetemp；CI Linux 无此限制） |
| `2e32827b` | W11/W12：训练磁盘只读诊断（每任务 workspace/artifact/checkpoint、可回收/受保护/未知分类、缓存 dry-run、`GET /training-tasks/storage-diagnostics`），不执行任何删除/自动 GC | 2 passed；recovery API 20 passed |
| `9ee9f33d` | W11/W12：训练 ETA 陈旧治理——投影新增 `eta_stale/eta_display/telemetry_age_seconds`（阈值 env 可配），前端陈旧 ETA 显示"估算滞后"且停止本地倒数；入口缓存标识推进 | projection/progress/terminal 22 passed；Node 36 passed |
| `3e4ed593` | W11/W12：断点续训合同——要求冻结类名 schema、last.pt 必须含 optimizer（best.pt 不等于完整 checkpoint）、epoch 与冻结 schema 交叉核验（admission + worker 双层） | 18 passed |
| `3cacaef3`→`97fc6f34` | M10-A/B：应用+数据库**协调回滚**（备份绑定 app SHA/VERSION/build/schema；schema 不兼容 fail-closed；`--rollback-application-to` 仅祖先 SHA、非破坏性 checkout；部分恢复结构化诊断+幂等收敛；备份非灾备声明；Hold/活跃任务/近期心跳/worker 标记准入） | 27 passed/1 skipped + 15 new passed |
| `a541b36b` | M10-C：数值验证**先证据后发布**（完整证据含 project/algo/version/job/PT/ONNX/产物 SHA/manifest digest/样本集/参数/摘要→原子落盘→锁内身份复核→发布摘要；STALE/冲突/并发/崩溃恢复收敛；artifact 按自身转换 job 投影） | 176 passed；真实 PT→ONNX 4 passed |
| `16280076` | M11/W13 首批原生迁移：`/app` 新增 AI 任务列表（消除孤儿审核路由）、转换记录只读页、服务节点只读页；复用现有 API/视图；旧入口与菜单保留；类型检查/构建/Playwright 全绿 | vue-tsc 0 error；vite app build ok；Node 1824 passed；新增 Playwright 6/6 + 回归 17/17 |
| `3d17cc74` | M13-A：首次纯负样本 typed 码在**真实** prepare/同步创建路径可达（不再仅 monkeypatch 证明）；负样本算法归属一致性（算法池成员或算法上下文回执，否则 `TRAINING_NEGATIVE_ALGORITHM_ATTRIBUTION_MISSING`，选择器/冻结/Worker 输入一致）；M14-A：取消未证明停止时记录有界退避与 `cancelling_unverified` 诊断，不释放 GPU/lease | W10 22 passed；picker/negative 66；request/GT 90；prepare 30；cancel/scheduler 16 |

状态标签保持：`REAL_GPU_UAT_NOT_VERIFIED`、`REAL_HARDWARE_INFERENCE_NOT_VERIFIED`、
`PRODUCTION_DUAL_SLOT_DISABLED`、`A800_PREFLIGHT_REQUIRED`、
`A800_PRODUCTION_UPGRADE_NOT_EXECUTED`、`OFFLINE_INSTALL_NOT_VERIFIED`。
`AGENT_SIGKILL_RESTART_E2E_PASS` 已由 Linux CI 证据确认；响应丢失五类、双槽同时崩溃、
同 GPU 重新准入、同 node_id 双实例、真实 GPU 仍未覆盖。

本轮仍未完成（下一轮队列）：
1. M11 剩余优先项：ZIP 导入双 Owner/双轮询收口、AI 审核任务创建/取消/重试原生化、
   训练暂停/删除/提权原生化、转换创建/日志/质量中心、外部发布/平台配置原生页、
   统一请求出口（日志/训练创建）。
2. M12/W14 大规模真实性能（20 万素材/千级模型/2 万跨页选择/SQLite 并发）——本轮未开始。
3. M15 剩余：同 GPU 重新准入、响应丢失五类正式 Agent 链路、双槽同崩溃分别恢复、
   同 node_id 双实例中央合同、运维诊断面。
4. M16 剩余：FP16/动态/opset 扩展矩阵、来源血缘贯通、发布准入实际消费质量状态、
   发布幂等/回滚 Dry-Run。
5. M17：离线安装（当前 OFFLINE_INSTALL_NOT_VERIFIED）、单槽真实业务候选现场 UAT、
   候选证据文档更新为最终不可歧义 SHA。

### 9.11 第三轮（N0–N7）交付摘要（2026-11-24 傍晚）

代码候选 SHA：`bee265a488983d4dc206d0f901d6f169af9e9f15`（已推送；候选文档 §1 已回填）。
该 SHA 的 CI 单次查询时为 `CI_PENDING`（24 workflows 已触发、0 completed），未完成前保持
`CANDIDATE_CI_PENDING`，不得称验收通过。

| 提交 | 内容 | 状态/证据 |
|---|---|---|
| N0 `66ec7d70` | 定时缓存清理默认关闭；实际删除需 `TRAINING_BUNDLE_CACHE_MAINTENANCE_DELETE` 显式 opt-in；扫描中按项目重读保护（新任务/Hold 出现即中止删除）；dry-run 默认；未释放 Hold 保护 | 定向测试通过；默认不扫描不删除 |
| N1 `f119e628` / `fcbe3af3` | Windows CI 真实根因与稳定化：真实 Agent 以退出码 2 结束的 token 前置 `-` 问题（前轮已修）；新增有界 worker 存活失败现场证据；修复双槽 fencing 测试在中央 start-identity 注册完成前过期 lease 的真实竞态 | 本地 10 次无法复现原 flake；fencing 前置条件修复；CI 待准确 SHA 结果 |
| N2 `bee265a4` | W14 真实 200k 规模基线（200,000 素材/110 算法/1,100 版本/1,160 任务/20k 选中/20k AI 候选）+ 原始 JSON；唯一生产优化：过滤冻结分页 1,000→5,000（含历史冻结 −53.9%、排除历史 −44.1%，SQL 241→81/281→89）；性能测试保持 `RUN_SCALE_PERF=1` opt-in | 报告 `docs/performance/2026-11-24-scale-200k-baseline.md`；P95 与瓶颈证据在 JSON |
| N3 | W13 第二批：ZIP 导入单一网络/状态 Owner（去双轮询、卸载销毁、保留 Uppy 续传）；AI 任务取消/合法重试/审核恢复/失败素材定位（复用 v60 既有 API）；训练暂停/继续/插队/删除资格与日志统一走 `app/http.ts`；旧入口与产品菜单/布局不变 | vue-tsc 0、app build 成功、Node 契约 1845 通过、Playwright 26 通过（含新增 8） |
| N4 | W10 反馈闭环：反馈证据保留原预测不可变 + `correction_kind`（漏检/类别/定位/部分修正）非破坏性增量迁移；`needs_correction` 永不直接写 GT；confirm 复用登录身份 + GT CAS + `request_id` 幂等回执；GT 写入后响应丢失安全恢复；部分修正保留其他框；反馈→候选→审核→GT→候选集→训练冻结 `supplement_provenance` 真实 E2E | 新增 `test_online_feedback_training_chain.py`；review/negative/prepare 回归通过 |
| N5 | W9 收口：真实 FP32/FP16/opset11/opset12/simplify/动态冻结矩阵（FP16 真实导出+ORT，历史 Cast→Conv 拓扑故障真实复现并证明 sorter 正确）；`assert_delivery_quality_eligibility` 只信真实证据不信 `numeric_status`；job.json 写入统一锁；交付预检区分归档/附件交付/正式激活/硬件验收；发布/回滚 Dry-Run 只读 | 真实矩阵 8 passed；核心单测 190/121 通过；硬件一律 NOT_VERIFIED |
| N6 | W15/W16：备份绑定前端构建身份与 Python 依赖指纹；systemd 配置差异只读记录；停服后活动二次复核（Hold/心跳/worker marker，不自动 force）；detached HEAD 升级拒绝并给出分支恢复命令；部分恢复/回滚后再次升级语义；`write_silence=unverified` 保持；离线交付事实清单与阻断（无 wheelhouse/主 unit 安装脚本，`OFFLINE_INSTALL_NOT_VERIFIED`） | 42 passed/1 skipped + N6.1 10 passed；候选文档重写并回填 SHA |
| N7 | 已证明：GPU-A 仅在 Stop Proof/Hold RELEASED 后可被下一任务复用（未释放前不可准入）；同 node_id 两独立 Agent 实例合计不得超过授权槽；stale generation 不能改写新执行身份 | 新增 3 项 central 合同测试 |

本轮仍未完成：
1. N1/全部工作包的准确 SHA GitHub CI 验收（当前 CI_PENDING）。
2. N7 剩余：五类 HTTP 响应丢失的正式 Agent 全链路、双槽同时崩溃分别恢复、运维只读诊断面。
3. N2 后续瓶颈（转换历史冷扫描 ~5s、AI 候选兼容接口全量 ~7.7MB、空交集筛选 ~0.6s、并发素材查询 P95 ~0.57s、冷统计/大摘要）。
4. N5 的 HTTP 只读 dry-run/预检端点接线（本轮只完成后端只读函数）。
5. N3 剩余：外部发布/平台配置只读原生页、转换创建/日志/质量中心原生详情（转换创建与真实发布仍禁止执行）。
6. M12/W14 其他规模化整改与 M8/W13-14 剩余迁移。

### 9.12 第三轮续推进（N5/N7/N2 后续，2026-11-24 17:00 前后）

**最终代码 SHA：`6032874814f6bcb821d0a0add23f7a3dc08095f7`**（已推送；
候选文档 §1 已回填该 SHA，CI 状态 `CANDIDATE_CI_PENDING`）。

| 提交 | 内容 | 关键验证 |
|---|---|---|
| N7 `88817c60` | 五类 HTTP 响应丢失补全（start_execution/finish/recover 新增，start-identity/stop-proof 既有）；双槽同时崩溃分别恢复（POSIX 真 SIGKILL + Windows fail-closed 合同）；只读执行诊断 `execution_status`/`remote_recovery_diagnosis` 增补 node_capabilities/recovery_state/evidence_sha256，无写操作、无 token | 定向 21 passed/2 skipped（POSIX-only 由 Linux CI） |
| N5 HTTP `0d228047` + `5745e71a` | 只读交付质量/激活与回滚 Dry-Run 端点（零写入快照断言，`DRY_RUN_STATE_CHANGED` fail-closed）；列表/详情投影 `quality_preflight/formal_activation_eligible/delivery_presentation/hardware_acceptance`；未验证产物仍可附件交付但不伪装正式激活；`_write_job_json` 统一 `<job.json>.lock` + 原子写，并修复 Windows 共享读导致的瞬时 PermissionError（有界重试、不丢证据投影） | 定向 9 passed；并发写不撕裂、无投影丢失 |
| N2 后续 `60328748` | 转换历史冷扫描 1,000 文件：串行 scandir+stat 后 8 线程池解析（3,998→584ms，−85%）；`ix_materials_source_status` 覆盖索引 + 非关联标签存在性前置谓词（空交集 cold 576→32–47ms；并发素材查询 P95 491→52–61ms）；AI 兼容全量接口定位后不动（真实调用方已有界分页）；LIKE/冷统计记录为下轮候选 | 定向 53 passed；200k 语义等价 9 组组合 ID/计数一致；旧库补索引 user_version 不变 |
| 中间快照 `05c9da6d` | `_real_agent_crash_recovery_support.py` 的 N7 中间态（后续 `88817c60` 已包含最终内容）；同时修正 N1 失败证据路径与中央 task.error 投影 | 仅测试基础设施 |

当前 CI：`60328748` 推送后按规则查询一次并如实记录；`CANDIDATE_CI_PENDING` 未完成前
不得称生产候选验收通过。仍待办：
1. 准确 SHA 的 GitHub CI 结果（失败时只分析失败 Job 并最小整改）。
2. N3 剩余：外部发布/平台配置只读原生页、转换创建/日志/质量中心原生详情（真实发布/设备激活仍禁止执行）。
3. N2 剩余候选：LIKE 搜索计划优化、冷统计覆盖索引（需评估写放大）。
4. N5 剩余：`train_worker.py`/`remote_train_server.py` 的 job.json 写入统一锁（当前不在本批允许范围）。
5. M12/W14 其余规模化整改与 M8/W13-14 剩余迁移。

### 9.13 N1 收尾状态（第三轮末，2026-11-24 17:20 +08）

- 候选代码 SHA `6032874814f6bcb821d0a0add23f7a3dc08095f7` 的 Actions：25 completed / 1 failure
  （Node Agent Executor；Ubuntu + Windows contract 均失败，api success）。失败用例：
  `test_real_agent_restart_is_fail_closed_without_stop_proof` 与 Windows 双槽同崩 fail-closed。
- 现场证据：worker 进程已消失；中央 task 仍 `RUNNING / stage=REMOTE_TRAINING_STARTING_WORKER`、
  `process_pid` 已登记；本地 `process-identity.json`/`process-launch-intent.json` 缺失；
  中央 Hold 仍 HELD；Agent 存活且 executor 无 active_tasks。指向“launch 后注册身份成功、
  但 worker 立刻退出或被 runner 清理，测试在 runner finalize 之前的窗口断言”的竞态。
- 已推送 `50d15711`（仅测试基础设施）：失败诊断增加 execution `runtime.log` 尾部及
  `execution.json`/`workspace-cleanup.json` 选字段，下一次 CI 将给出 worker 真实退出原因；
  该提交到达后需再按准确 SHA 查询一次并根因修复。未删除/放宽任何存活与 fail-closed 断言。
- 状态标签保持：`REAL_GPU_UAT_NOT_VERIFIED` / `REAL_HARDWARE_INFERENCE_NOT_VERIFIED` /
  `PRODUCTION_DUAL_SLOT_DISABLED` / `A800_PREFLIGHT_REQUIRED` /
  `A800_PRODUCTION_UPGRADE_NOT_EXECUTED` / `OFFLINE_INSTALL_NOT_VERIFIED` /
  `CANDIDATE_CI_PENDING`。

### 9.14 第四轮（T0–T8）交付摘要（2026-11-24 晚）

起始 HEAD `32a260add5762c238ddfa25ef6a72e8c9f6605e4`（=远端 HEAD），VERSION `42.24.592`，
四份受保护文档 SHA256 全部匹配。**代码候选 SHA：`7ee407d476a50582333a15bc3b66f204343d908d`**
（本文件与候选文档的提交仅改文档，不改变代码候选身份）。

环境说明（新会话遇到，已解决）：本机 DNS 把 `github.com` 解析到不可达地址，`git` 直连
https 失败，而 api.github.com 正常。已用 `.dsh-local/gh_connect_proxy.py`＋
`.dsh-local/git-gh.ps1`（本机 CONNECT 代理钉住可达边缘 IP，TLS 仍端到端校验；`git` 需
`-c credential.interactive=never`）完成 fetch/push。`.dsh-local/` 已加入
`.git/info/exclude`，不入库。后台进程在本环境**没有外网**，push 必须前台执行。

| 提交 | 内容 | 关键验证 |
|---|---|---|
| `3ada4245` / `f671e2ea` | **T0 真实缺陷**：`ExecutionLeaseMonitor` 把任何心跳失败当失锁 → 杀 Worker、清 ProcessIdentity、回收 workspace，却不上报控制面（任务停在 `RUNNING/STARTING_WORKER` + Hold `HELD`）。整改为“只有控制面**应答**才 fencing；传输层无应答在租约窗口内有界重试；窗口耗尽才 fencing”，并落 `execution-error.json` 有界证据。首版把 5xx 也当可重试，**被真实 loopback 503 分区测试判红**（该合同是既有安全合同），已收窄回“4xx/5xx 立 fencing，仅传输层重试” | 单测三情形通过；`test_two_agent_http_loopback` 分区用例本地通过；`test_execution_status_read_only_recovery_diagnostics` 的“两次 GET 完全相等”断言改为只比持久身份/证据字段（活任务 stage 会前进，只读性仍由中央快照不变断言证明） |
| `c6c3919a` | **T1**：`job.json` 统一 `<job.json>.lock`（原 Worker 用 `.state.lock`，与 app/转换/部署不同锁 → 取消可被进度写入复活、`finished_at` 可丢）；锁内读改写 + 原子替换 + attempt 栅栏 + 取消保护；`remote_train_server.py` 六个写入点全部收敛 | 24 passed（含新增 `test_training_job_record_contract.py` 5 项）+ durable controls 1 passed |
| `52bbe9e6` | **T2-C**：原生转换创建/详情（复用 v39 catalog/resolve/jobs/by-request/log/artifact 与既有 `delivery_quality` 只读投影），数值/运行时/硬件/发布准入分列，`FORMAL_ACTIVATION`/`UNVERIFIED_ATTACHMENT` 如实显示 | `vue-tsc` 0 error；`build:app` 成功；入口契约 2 passed |
| `0c1d5010` | **T4**：`tools/offline_bundle.py`（build/verify：40hex SHA + VERSION + build_id + 前端资源摘要 + 依赖指纹 + 逐文件 sha256 + `sha256sum -c` 清单；白名单拒绝密钥/DB/`__pycache__`/符号链接；空 wheelhouse/缺前端/歧义 SHA/覆盖产物 fail-closed）＋内嵌 `install_offline.sh`（先校验后复制、仅 `--no-index`、拒绝非空非本包前缀、`OFFLINE_*` 码、装后 healthcheck）＋unit/env 模板 | 11 passed / 1 skipped（`sh -n` 由 Linux 执行） |
| `f0cfd313` | **T8**：算法域 Provider 端口（SQLite 直通默认 + PostgreSQL 实现）、`w5_algorithm` 关系型 schema（版本/校验和/禁止降级/启动不迁移）、单域迁移工具（导出/导入/报告/幂等/断点续跑/dry-run/主键集合/外键/revision/JSON/NULL 语义/摘要；保留原 ID；不读 SecretStore）、切换准入与回滚阻断 | 真实 PostgreSQL 16.2：29 passed（provider 契约、迁移/对账/并发单写者/回滚阻断、SQLite↔PG 18 操作一致） |
| `9693e3ea` | **CI 守卫过期**：`training-task-visibility.yml` 仍断言 `?v=4226386-timing`，实际 `static/main.mjs` 为 `-eta-stale` → 153 测试全绿但 job `exit 1` | 令牌同步，意图不变 |
| `0ef0baca` | **T7**：在线反馈与 deploy artifact 查询迁出 `app.py`（`online_feedback_service.py`/`online_feedback_api.py`/`deployment/artifacts_api.py`），`OnlineFeedbackRepository` 仍是唯一持久化 Owner，`app.py` 保留装配/顺序/薄绑定；外部发布确认“已迁移，无需改动” | 有效路由表 535 项与 OpenAPI 473 paths/527 operations **逐项一致**（含 operationId/状态码/请求体 $ref/安全/标签）；`import app` OK；反馈 API 7 + artifact 可见性 5 passed |
| `fca1e1ac` | **T2-A/B**：原生外部发布（按版本只读详情：发布记录/同步状态/失败原因/产物映射/三个独立质量事实）与平台对接（读 v63 配置 + v64 映射，复用既有 v63 保存契约；只显示掩码状态，密钥只写、保存后清空） | `vue-tsc` 0 error；`build:app` 成功；未调用任何真实发布/同步/连接测试 |

本轮仍未完成 / 待判定：
1. **准确 SHA 的 CI 最终证据**（单次查询时仍有工作流未完成）：代码候选 `fca1e1ac` 的
   Actions 结果决定 `CANDIDATE_CI_PENDING` 能否转 ACCEPTED。
2. **双槽 Windows 崩溃恢复**仍偶发（`dual-crash-task-a` Worker 启动后消失）。本轮补上了
   “谁、因为什么停止”的证据链（`execution-error.json`），下一次 CI 将直接给出结论；
   不得在无证据时改断言或加 sleep。
3. **执行节点 RAM 准入**用瞬时可用内存，`RESOURCE_HOST_MEMORY_INSUFFICIENT` 直接 `FAILED`；
   本机可复现（约 1/3），CI 失败签名不同故非当前 CI 根因。是否改 `BLOCKED_BY_ENVIRONMENT`/
   延迟重排需产品判定，本轮未改。
4. **T3 复核结论**：质量证据的“显示 vs 消费”边界无新增缺陷——发布路径按既有合同允许
   未验证产物**附件交付**但不伪装正式激活，`assert_delivery_quality_eligibility` 已在
   artifact 注册/预检侧真实生效；正式激活写入入口本身不存在（只有 dry-run），故无需新增闸门。
5. **T7 剩余批次**：训练创建/管理、报告、素材、AI 任务、GT、项目配置/权限/节点/系统配置；
   转换/质量引擎与旧 v42 iteration/quality 组必须整体一起迁（共享 `_v42_*` Owner）。
   T7 提示：`include_router` 为惰性注册，后续批次须比对**展开后的有效路由表**，不能比
   `app.routes`。
6. **T8 剩余**：`app.py` 的 Provider 接线（本轮故意留给集成提交）、7 个 presentation-only
   投影未移植（cutover 需显式 `--acknowledge-unported`）、存储源/模型产物/外部发布域、
   素材/GT/负样本联合迁移单元（ATTACH/JSON/事务隔离）、TaskRepository/Hold 等安全域。
7. 离线真机：wheelhouse 实物、系统库/驱动、模型权重/字体、真实断网安装与 systemd 未执行；
   `OFFLINE_INSTALL_NOT_VERIFIED`、`REAL_SYSTEMD_HOST_NOT_EXECUTED` 保持。

### 9.15 第五轮（M0–M5）交付摘要（2026-11-24 20:1x +08）

起始 HEAD `63cfa5b4`（=远端），本轮**代码候选 SHA：`7ee407d476a50582333a15bc3b66f204343d908d`**
（`63cfa5b4` 之后仅文档提交）。执行纪律：默认单主 Agent、不建子 Agent、本地仅轻量检查
（`py_compile`/`git diff --check`/`ast`），重型验证全部交 CI。

| 提交 | 内容 | 验证 |
|---|---|---|
| `76e989da` | **M0-A** 双槽 Windows 失败的真实根因是 fixture：测试替身 trainer 把 `runtime_cache`/`actual_cache` 硬编码 `False`，而冻结解算器在主机有余量时确实会解出 `ram`/`disk`，于是平台按合同判 `REMOTE_RUNTIME_RESOURCES_MISMATCH` 并 FENCED 两个执行。替身改为陈述实际解出的 cache（与生产 Worker 一致），**未放宽任何资源合同校验**。**M0-B** 三条永久守卫仍 grep 已迁走的代码，改绑 `online_feedback_api.py`；其余 app.py 守卫逐条核对仍存在。**M1.1** 租约监视器改为单调截止时间（初始取中央实际授予的截止，不叠加 TTL）、请求超时按剩余租约收紧、重试等待可取消并检查 `stop_event`、beat 单飞且迟到响应不得复活已 fenced 执行；503/HTTP 应答 fencing 合同不变。**M1.2** `_terminate_active()` 不再在中央确认前删除持久 ProcessIdentity，改为写 `process-stop-verified.json`（精确 pid/create_time/command_hash + 原因）；仅 `_confirm_stop_cleanup()` 在中央权威终态后释放身份 | 5 项 lease-monitor 单测通过（高风险并发路径，单次定向）；其余交 CI |
| `adec7da2` | **M2** 算法域单写 Owner：PG 写入在**同一事务**内 `FOR UPDATE` 锁定 `cutover_state` 并复核 provider/admission/generation/吊销（关闭 TOCTOU）；PG 写入强制要求 admission（此前为空即可写）；`evidence.phase` 处于切换中时 PG 拒写；SQLite 适配器**每次写**复核权威（旧实例与未声明的 mutating helper 均不可绕过）；切换前先落 `.transition` marker、本地 admission 落盘后才移除，崩溃窗口留下“两侧都不可写”的显式可恢复状态 | 17 项 provider-boundary 单测通过（fake connection，无真实 PG/磁盘压力）；真实 PG 交 CI |
| `f2ce326e` | **M5.1** `_record_cancel_wait_diagnostic` 改为在共享 `<job.json>.lock` 下读改写（原为无锁，可与 Worker 进度互相覆盖） | `py_compile` + 共享锁助手导入校验 |

| `1e89d10d` | **CI 回归修复（本轮自引入）**：`ONLINE_FEEDBACK_MAX_IMAGE_BYTES` 守卫应指向 `online_feedback_service.py`（此前误指 api 模块，OFR 两 job 必然红）；两条 UI 文案守卫改回文件原文（此前按控制台乱码改写，其中一条改成了不存在的文案）；`_terminate_active(graceful=)` 恢复“有序关闭自行验证并清除身份”的既有 POSIX 合同，fenced/异常路径仍保留身份与停止证据 | 由 CI 验证 |

### 9.16 第六轮（P0 安全收口 + T7）交付摘要（2026-11-24 21:xx +08）

起始 HEAD `23227a50`（=远端）。**代码候选 SHA：`7ee407d476a50582333a15bc3b66f204343d908d`**。
纪律：单主 Agent + 至多 1 个活跃子 Agent（仅 T7 迁移使用），本地仅 `py_compile`/`import app`/
定向用例/守卫 grep，无重型测试。

| 提交 | 内容 | 验证 |
|---|---|---|
| `5aa76f41` | **切换证据**：`cutover_transition()` 不再在 `finally` 无条件删 marker——仅当函数正常返回**且**持久 admission 记录证明目标权威已到位时才删；异常一律保留 marker（“两侧都不可写”状态得以留存）。SQLite 写入改用共享 `<admission>.switch.lock` 覆盖“权威检查→真实写”，mutating store 调用统一走受控代理（关闭 TOCTOU，也覆盖未声明的 helper）。rollback 用同一锁并声明 `expect_provider=sqlite`。<br>**租约**：成功续租优先采用控制面回报的实际到期时间（无则不改变 receipt+TTL 规则）；续租请求超时按剩余租约收紧（可 <1s）；`assert_active()` 直接检查截止时间。503/4xx/5xx 应答 fencing 合同不变。<br>**训练停止证据**：`graceful` 路径不再自行清除持久身份，先提交 Stop Proof，控制面接受后才释放；否则保留身份与 `process-stop-verified.json` | 5 项 lease-monitor + 17 项 provider-boundary 定向通过；受控代理行为实测（切换中拒写、清除 marker 后恢复） |
| `ddf0fd65` | **T7 训练报告域**：v44 训练报告读投影（reader_view 显示路径 + legacy `report_type=version` 组合 + 仅该报告使用的 `results.csv` epoch 历史回退）迁至 `platform_core/training_report_api.py`，router 工厂 + 全部依赖晚绑定注入，端点名保留 `v44_training_report` 以维持 operationId；`app.py` 保留装配、原位置 `include_router` 与两处薄绑定（测试仍调用/打补丁）。未迁 v49 算法报告、v45 错误归因、v44 supplement（属训练任务域共享 Owner） | 路由表/OpenAPI 前后**逐项一致**（routes=527 paths=473 operations=527 schemas=122；装饰器 335→334、include_router 12→13）；129 条 `grep app.py` 守卫逐条复核无丢失；报告 API 16 + 产品化 1 + 算法存储 3 通过；`import app` 353 条顶层路由 |

### 9.17 第七轮（真实 PG CI + 算法访问收口）交付摘要（2026-11-24 22:xx +08）

起始 HEAD `2b79a74a`（=远端）。**代码候选 SHA：`7ee407d476a50582333a15bc3b66f204343d908d`**。
本轮按序推进第 1 项（真实 PG CI）与第 3 项（T8 业务接线）的可独立部分；本地仅
`py_compile` / `import app` / pytest `--collect-only` / 守卫 grep，未执行任何 PG、集成或重型测试。

| 提交 | 内容 | 验证 |
|---|---|---|
| `b6e635ca` | **真实 PostgreSQL CI**：新增 `.github/workflows/algorithm-postgres-runtime.yml`（ubuntu-24.04 + `postgres:16` service container + `pg_isready` 健康检查；仅小 fixture，无生产库）。两个 PG 合同测试模块改为优先读 `MC_TEST_POSTGRES_DSN`（CI 容器），本地仍回退 pgserver；模块结束时自清 `w5_algorithm`/`w5_shadow` schema。`MC_REQUIRE_POSTGRES=1` 把“没有 PG”从 skip 变成硬失败，末尾步骤解析 junit，**任何 skip 或少于 12 条合同即判红**。<br>**T8 接线**：`app.py` 新增唯一 Provider 访问器 `algorithm_repository(project_id)`（默认 SQLite、PG 仅准入后启用、不静默回退、未决切换两侧都拒写）与显式 `algorithm_presentation_store(project_id)`（SQLite 承载展示投影是设计而非回退）；`app.py` 内直接构造 `AlgorithmSqlStore` 的调用**全部清零**（仅剩该 helper 内部一处），核心读走 Provider、库/资产/总览/版本展示投影走命名 helper | `import app` 353 条顶层路由；`py_compile` 通过；PG 合同 collect-only 12 条；3 条 `algorithm-sql-store` 守卫复核仍命中；PG 真实执行交新 CI Job |

### 9.18 第八轮（单一算法事实源 + PG CI 修复）交付摘要（2026-11-24 23:xx +08）

起始 HEAD `13111ebc`（=远端）。**代码候选 SHA：`7ee407d476a50582333a15bc3b66f204343d908d`**。

| 提交 | 内容 |
|---|---|
| `490ed16d` | **PG CI 修复**：新 Job 因根 `tests/conftest.py` 导入 PIL/TestClient/app.py 而失败 → 合同运行拆成两步并各自 `--confcutdir`，不增装重型依赖；“无 skip / 真实 PG16”要求不变（守卫步骤改为汇总两份 junit）；工作流触发路径加入 `app.py` 与 `training_report_api.py`。<br>**NAE 诊断**：`assign_next` 失败时输出 tasks/assignments/holds/node 能力/分配器拒绝原因，未改调度、超时或断言。<br>**算法域单一事实源**：PG 真实实现 `bootstrap_summary`（有界 boot 行 + `versions_deferred`）与 `training_display_refs`（task→version 索引、100 id 上限、同分组计数），能力缺口由 7 项降为 5 项；`algorithm_presentation_store()` **不再构造 AlgorithmSqlStore**，PG 切换后未移植投影 fail-closed 而非读过期 SQLite；`app.py` 直接构造 `AlgorithmSqlStore` 由 1 处降为 **0 处**；默认 SQLite 行为不变；3 条守卫复核通过 |

未完成 / 阻断：
1. **PG 业务投影未完成**：`library_algorithms`、`asset_algorithms`、`asset_algorithm_basic`、`asset_versions`、`asset_version` 仍未移植 → Provider 继续声明不支持，需要它们的正式切换仍 fail-closed。这是本轮第 2 项的主要剩余工作。
2. **`training_report_api.py` 两处仍构造 SQLite store**：其 `training_version_refs` 快路径以 SQLite 专属 `db_path.is_file()` 作守卫，需先定义 Provider 中立的“catalog 是否存在”合同。
3. **维护窗口与安全切换（第 3 项）未实现**：持久 phase + operation identity、排空、冻结、对账、rollback 的 `revoked_at` 判定、并发切换阻断、写入判定不依赖方法名前缀——全部未做。
4. **T7（第 4 项）本轮未开展**。
5. 第 5 项保留队列（停止证据消费、no-op Stop Proof 风险、转换 Runner、资源 requeue、离线/Vue/模型质量）未动。

1. **PG 维护窗口与回滚未实现**：切断新增写入 → 排空 → SOURCE_FROZEN → 对账 → 切换 → 恢复 的持久 phase machine、operation identity、rollback 的 `revoked_at` 完成判定、导入工具与切换的统一事务/锁合同、并发切换阻断、`AlgorithmSqlStore` 原始写路径收口（当前靠 `_GuardedStore` 的**方法名前缀**判定写入，审计已指出不可依赖前缀）。
2. **停止证据消费未实现**：`process-stop-verified.json` 仍未被 Coordinator 消费；`_submit_stop_proof` 在 `_require_stop_proof=False` 时是 no-op，graceful 路径存在把 no-op 当确认的风险（本轮未改，需按真实确认结果判定）。
3. **转换 Runner 提前清身份**未整改。
4. **资源准入 requeue 合同未建立**：中央 claim 侧的 `resource_waiting`/`resource_wait_reason` 可用，但 Agent→中央的“未启动+资源不足”上报与安全 requeue 协议未实现；规划器仍未使用 `host_total_bytes`，暂时/永久不足尚不可区分。
5. **T7 后续域**（训练管理、转换质量）未开展。
6. **PG 正式写入**仍未启用（本轮只做读取接入与访问器收口），符合“未验证不开启”。

1. **PG 维护窗口编排**：切断→排空→SOURCE_FROZEN→对账→切换→恢复 的持久 phase machine、rollback 全流程编排、导入工具与切换的同一锁合同**未实现**（本轮只落地同事务权威核验、共享 switch 锁、marker 语义）。真实 PG 验证须走 GitHub Ubuntu + PG service container（本轮未新增 Job）。
2. **`process-stop-verified.json` 尚未被恢复 Coordinator 消费**：仅写入并在诊断中展示。要接入需改 Coordinator 的 Stop Proof 发布路径，属 CI 验证过的 fail-closed 合同，本轮不据猜测放宽。
3. **转换 Runner**（`node_agent_conversion_runtime.py`）仍在中央确认前清身份；转换有独立 supervisor 证明合同，需单独设计，未机械复制。
4. **T8 正式接线**：`app.py`/API/Worker 接入 Provider、收口直接构造 `AlgorithmSqlStore` 的调用链**未开展**（依赖上面第 1 项证据）。
5. **§5 资源准入**：等待机制确实存在（Scheduler 的 admission 回调 + `stage='resource_waiting'` + `resource_wait_reason`），但只从**中央 claim 路径**可达；远程 Agent 侧 prepare 失败没有 requeue 合同。且规划器只用 `effective_available_bytes`（`host_resource_snapshot` 已采样 `host_total_bytes` 却未使用），因此**当前无法**判定“暂时不足 vs 永久不足”。结论：区分所需数据已具备，缺失的是 Agent→中央的 requeue 协议与状态映射，未盲改。
6. **近期稳定候选**：`1e89d10d` 全量 26 条 run = 25 success + 1 cancelled（`Remote Material Import`，被同一代码树的 `23227a50` 同名 run success 取代，等价证据成立）；`ddf0fd65` 的 CI 待查。

1. **准确 SHA 的 CI**：本轮三次 push 后的 Actions 结果尚未取得（`CI_PENDING`）。
2. **M2 剩余（已明确未做，不得当作已收口）**：完整维护窗口编排（阻断新写→排空→最终快照对账→切换→恢复）与持久 phase machine；rollback 路径的 marker 包裹；`algorithm_migration_cli rollback` 序列；直接构造 `AlgorithmSqlStore` 的正式调用链（M3）。
3. **M3**：Provider 接入 `app.py`/正式 API/Worker 依赖 M2 的 CI 证据，本轮未动。
4. **M4**：训练任务/报告/转换质量域模块化本轮未开展（剩余共享 `app.py` 改动需整域一次完成）。
5. **M1 同类项**：`node_agent_conversion_runtime.py` 仍在中央确认前清除持久身份（同类缺陷，转换器有独立 supervisor 证明合同，需单独设计确认路径，本轮未盲改）。
6. **M5.2 RAM 准入语义**：`RESOURCE_HOST_MEMORY_INSUFFICIENT` 仍直接 `FAILED`，未改为等待资源/`BLOCKED_BY_ENVIRONMENT`（属产品语义，需判定；本轮不猜）。


### 9.19 第九轮（PG 投影去遮蔽 + 准入合同）— 2026-11-24 23:xx +08

代码候选：`7ee407d476a50582333a15bc3b66f204343d908d`。真实缺陷两项：`algorithm_postgres_store.py` 中 `bootstrap_summary`/`training_display_refs`
被类尾同名占位方法**覆盖**（能力断言与实际不符），已删除占位；`algorithm_migration_cli.py` 调用
`cutover_transition` 未导入（cutover-admit 必 NameError），已补 import 并复核调用链。CI 合同：
parity 测试改为先按真实生产流程做隔离 admission 再打开 Provider（不取消写入准入、不加绕过开关）；
两个合同步骤 `if: always()` 各自产出证据，最终守卫仍对失败/缺失/skip 判红。

**七个展示方法现状**：`bootstrap_summary`、`training_display_refs` 为真实 PG 查询；
`library_algorithms`、`asset_algorithms`、`asset_algorithm_basic`、`asset_versions`、`asset_version`
仍为 fail-closed 占位。剩余工作具体阻断：三个 `asset_*` 需把 `model_asset_views.version_columns()`
的 SQLite `json_extract/json_type` 投影改写为 JSONB SQL 并保持 `version_record` 行形状；
`library_algorithms` 还需外部资格、品目层级、训练统计与 mAP50 排序规则；`asset_algorithms` 需
分页/筛选/排序/`filter_options` 与 revision 同快照。PG 正式切换保持关闭。
### 9.20 第九轮补记（PG 展示查询 6/7）

代码候选：`7ee407d476a50582333a15bc3b66f204343d908d`。本轮在 9.19 之后补齐四个 `asset_*` 展示查询的真实 PG 实现
（`asset_algorithm_basic`/`asset_versions`/`asset_version`/`asset_algorithms`），复用
`model_asset_views.version_record` 纯投影与 `_version_columns_sql` 的 JSONB 列合同；
联表统一 `(project_id, algorithm_id)`，分页/筛选/排序/`filter_options`/revision 同快照。
能力缺口由 7 项降为 1 项。

**`library_algorithms` 未完成（明确阻断）**：其 SQLite 实现依赖 SQL 内联的 Python UDF
`library_map50`（`algorithm_sql_store.py:306` 注册、`:277` 使用）按“首个有限数值 / >1 视为百分比”
的规则挑选 mAP50，排序键 `map50_percent` 由该 UDF 计算；PG 无法注册该 UDF，若改用 Python 后处理
则**排序顺序会与 SQLite 不一致**。另有 `WITH stats AS (... json_each(?))` 需要改写为
`jsonb_to_recordset`，以及 `ready` CASE 中的 `algorithm_external_analyses` 存在性与 master digest
比较。需要先定义 Provider 中立的“mAP50 归一化 + 排序”合同（或把该规则实现为 PG 函数）后再移植；
PG 正式切换继续关闭。
### 9.21 第十轮（PG 七个展示方法收口 + 训练报告接 Provider）

代码候选：`7ee407d476a50582333a15bc3b66f204343d908d`。七个 `PRESENTATION_OPERATIONS` **全部具备真实 PG 实现**（能力缺口为空，
`capabilities()` = CORE ∪ 七个），并修复审计指出的六项缺陷：`admission_switch_lock` 未导入、
`capabilities()` 与实际不符、`self._json_object` 未定义、`#>>` 破坏数值类型、
`training_display_refs` 把计数转成字符串、多语句读取无一致性快照。
`library_algorithms` 按 SQLite 合同完整移植（`jsonb_to_recordset` 统计、LATERAL + 有序 VALUES
取 mAP50 首个数值候选、`jsonb_typeof` 过滤非法类型、>1 保留否则 ×100、`DESC NULLS LAST` 与
SQLite NULL 顺序一致、品目祖先展开、filter_options/categories/revision 同快照）。
`training_report_api.py` 移除两处直接构造，改为注入 `algorithm_repository` 并使用
Provider 中立的 `is_initialized()`。新增真实行为测试
`test_all_seven_presentations_answer_real_business_queries`（真实 PG16，覆盖七方法、分页、筛选、
排序、项目隔离、mAP50 优先级、失效 admission 拒写）。

仍未完成/保留：维护窗口与 rollback 状态机、其他数据库域、FastAPI 剩余域、停止证明恢复、
资源 requeue、离线交付；PG 正式切换保持关闭。
### 9.22 第十一轮（PG 展示合同缺陷修复；维护窗口未完成）

代码候选：`7ee407d476a50582333a15bc3b66f204343d908d`。本轮完成第 1、2 项：CI 两处断言与能力合同/双算法 fixture 对齐（保留
single-writer、旧 SQLite 拒写、重复切换等安全断言；七个方法改为按 id 定位，避免一条断言失败
掩盖其余六个方法的证据）；`library_algorithms` 的 `ready` CASE 统一为 BOOLEAN 并用
`IS TRUE/IS FALSE` 过滤；mAP50 恢复“数值或合法数值字符串 + 八来源优先级 + 排除 NaN/Infinity +
`pg_input_is_valid` 安全转换 + >1 原值否则 ×100 + 全无效 NULL + `DESC NULLS LAST`”，返回
double precision 与 SQLite float 对齐。

**第 3 项（维护窗口/安全切换/回滚）本轮未实现**——非硬阻断，是工作量未完成。已具备的部件：
`cutover_state` + `FOR UPDATE` 同事务写入准入、`writer_generation`、`admission`、`switch.lock`、
transition marker（按 operation/是否真实权威状态清理）、PG 侧 `evidence.phase` 非 steady 时拒写。
**缺失的函数（需在 `algorithm_cutover.py` 实现）**：
`begin_window()`（advisory lock + FOR UPDATE，写 phase=QUIESCING 与 operation_id/generation/摘要）、
`freeze_source()`（SOURCE_FROZEN）、`switch_owner()`（SWITCHING → admit → POSTGRES_ACTIVE）、
`resume_state()`（受控恢复入口，未知/中间态 fail-closed），以及把这些 phase 写入本地 transition
marker 以让 SQLite 侧共同阻断；还需 rollback 的 `revoked_at` 完成判定与“PG 有新写入禁止回退”对账。
**第 4 项（正式读写调用方收口）同样未完成**：`platform_core/algorithms.py` 仍有多处直接构造
`AlgorithmSqlStore`，`training_report_api` 的 `_list_algorithms_internal` 历史兼容查询仍走 app 层
原实现，需要统一到 Provider。
### 9.23 第十二轮（A：正式调用方收口；B：维护窗口/安全切换/回滚）

代码候选：`7ee407d476a50582333a15bc3b66f204343d908d`。

**A. U1 正式调用方收口（CODE_IMPLEMENTED）**
- `platform_core/algorithms.py` 13 个业务函数全部改走 `_algorithm_repository(path)`（默认 SQLite、PG 仅准入后启用、不静默回退）。
- 另收口 7 个正式调用方：`external_algorithm_platform`（外部同步/读）、`external_algorithm_cleanup`、`negative_pool_api`、`training_workspace_lifecycle`、`smart_material_audit/{api,evidence}`、`task_runtime/query_api`。
- **provider/tooling 之外已无任何 `AlgorithmSqlStore(` 直接构造**（可 grep 复核）。
- 写入权限不再靠方法名前缀：adapter 与受控 store 共用显式 `is_write_operation()`（`WRITE_OPERATIONS` 11 项；不在已知只读集合内的一律视为写，fail-closed）。

**B. 维护窗口/安全切换/回滚（CODE_IMPLEMENTED）**
`cutover_state.evidence` 持久阶段：`QUIESCING → SOURCE_FROZEN → VERIFIED → SWITCHING → POSTGRES_ACTIVE`，回滚镜像 `ROLLBACK_QUIESCING → ROLLBACK_APPLIED`，另有 settled `SQLITE_ACTIVE`。
- 唯一 operation_id 绑定 project/source/target/generation/snapshot_digest/verification_digest；每步校验 phase + operation。
- marker 原子发布（temp+fsync+replace，switch.lock 内），拒绝覆盖他人未完成操作；仅在自身 operation 且本地 admission 证明权威状态匹配后清理。
- 阶段持久化（非事务级），崩溃后两侧都拒写；PG 写入仅允许 `steady/switched/POSTGRES_ACTIVE`。
- `rollback` 先 `ROLLBACK_QUIESCING` 阻断 PG，再复核 digest、恢复 SQLite、revoke，要求 `revoked_at` 且权威回到 sqlite 才落 `ROLLBACK_APPLIED`；PG 有新写入时按既有 `TARGET_HAS_NO_NEW_WRITES` 明确拒绝。
- `resume_maintenance()` 为可重复恢复入口（CLI `maintenance-status`），未完成阶段只报告不清理。
- CLI `cutover-admit` 已改为整窗执行；准入被拒时按**持久真实权威**回退阶段（PG 已权威→POSTGRES_ACTIVE，否则 SQLITE_ACTIVE）并释放 marker，避免把未变更项目永久锁死。

**CI**：`Algorithm PostgreSQL Runtime` 新增 3 条真实 PG 合同（窗口双写阻断/并发窗口与旧 generation 拒绝、未完成窗口 resume 不清理、PG 新写入后拒绝回滚）。全部 `CI_PENDING`，未轮询。
**未验证**：真实 PG 下的窗口/回滚执行结果、并发压力、生产切换；`CUTOVER_NOT_VERIFIED` 保持。
### 9.24 第十三轮（A 安全收口；B 训练任务管理域模块化）

- **A 代码 SHA：`d3896f0dff09bc7623dfe4216602462e219c5c03`**（A1–A6 全部 CODE_IMPLEMENTED）
- **B 代码 SHA：`87a42516b5e99d5968106121997aaef1a06350ba`**
- 最终远端 HEAD：`87a42516b5e99d5968106121997aaef1a06350ba`

**A1 锁身份**：`admission_switch_lock()` 统一归一到 admission record（marker 路径自动去 `.transition` 后缀），因此发布阻断 marker 会先排空已准入 SQLite 写事务；`ensure_ready()` 改为“需要初始化/历史迁移时才取写锁，稳态只校验版本”，避免给正常读加独占锁。
**A2 权威移交**：`admit_cutover()` 接受并保留 maintenance 记录（不再用 `EXCLUDED.evidence` 抹掉 SWITCHING），PG 写门禁对 maintenance 准入的**空 phase 拒写**（legacy 准入显式区分），并拒绝 operation 不匹配；`_set_maintenance()` 改为 advisory+row 锁内的 CAS（phase/operation/generation 前置校验）。
**A3 真实对账**：`cutover-admit` 冻结后重读源、源变动即拒绝、以 operation_id 为 run_id 做**最终导入**，再跑真实 source/target 报告，只有 verdict=OK 才把 `summary_digest` 作为 verification_digest。
**A4 可执行恢复**：新增 `recover_maintenance()`（CLI `maintenance-recover --apply`，默认只读）：marker 未落库则采纳、未完成切换按阶段续跑、PG 已切换但本地未发布则回填、回滚中断可续、settled 只清自己的 marker，外来 operation 拒绝；`_admission_provider_is()` 按 provider 区分 `revoked_at` 语义。
**A5 其余接线**：`negative_pool_api.algorithm_scope` 不再以文件存在性判定算法存在；mAP50 以**缩放后**量级设界（≤1 会 ×100），不可表示候选落回下一优先级。
**A6 CI**：新增 3 条真实 PG 恢复合同（marker 未落库采纳、本地 admission 丢失回填、settled marker 仅清自身）；`14 passed`（collect 15）交 CI。

**B**：`v62 promote/cancel` 两个统一任务管理端点迁入 `platform_core/task_runtime/management_api.py`（工厂 + 全依赖注入，operationId 与路径/错误码不变，OpenAPI 仍 473 paths）。
**状态**：A/B 均 CODE_IMPLEMENTED，CI_PENDING；真实 PG 下的窗口/恢复/回滚执行仍 `CUTOVER_NOT_VERIFIED`。

### 9.25 第十四轮（A 真实回归修复 + B mAP50/恢复证据 + C 训练创建域模块化）

- A 代码 SHA：`98fcb290a73515b5dfe35fa91401fda7ac5c0e82`
- B 代码 SHA：`07dbbc75519e85fc4c264651e580814696edd830`
- C 代码 SHA：见本轮最后一次提交（`platform_core/training_create_api.py` + app.py 装配）

**A1 初始化递归/隐含写入**：`SqliteAlgorithmRepository` 只保留一个 `ensure_ready`；`_GuardedStore` 不再把
`ensure_ready` 转发回 Repository（原循环导致任何调用递归）。持久初始化（WAL、Schema bootstrap、历史 JSON 导入、
备份）改为在 Repository 安装的 `initialization_guard`（同一 switch 锁 + 陈旧写入拒绝）内执行，
`read_all/read_one/revision` 等触发的初始化同样受保护；ready 判定改用 `_ready_without_init_lock()`，
不再以文件存在/mtime 为依据；稳态读取不额外取独占锁。同线程重入由 thread-local 深度计数避免 Windows 自死锁。

**A2 外部清理回归**：清理记录 SQL 迁入 `AlgorithmSqlStore`（确认意图 + 算法退役字段 + revision 同一事务），
`CleanupRepository` 只调用声明的 Provider 操作（`cleanup_*`），不再访问 `_connect` 等私有方法。
PostgreSQL Provider 明确声明不支持清理域（`unsupported_operations()` 含 `CLEANUP_OPERATIONS`），
`CleanupRepository` 在非权威 Provider 上直接 fail-closed；U1 准入新增硬条件 `CLEANUP_DOMAIN_MIGRATED`，
项目仍持有清理回执/待删除标记时拒绝切换，不静默写回 SQLite。

**A3 CI 真实失败**：`cutover-admit` 的准入拒绝恢复退出码 3（新增 `AlgorithmCutoverRefused`，CLI 单独映射），
`admit_cutover()` 补上缺失的 `maintenance` 参数（原每次维护切换都会 TypeError→退出码 1）；
legacy `admit_cutover/cutover_transition/revoke_admission` 不再绕过打开的维护窗口；
PG 集成测试在切换后显式选择 PostgreSQL Provider 并传 `pg.get_uri()`。

**B1–B3 维护合同收口**（与 A 同函数，随 A 提交）：所有阶段写入均为 advisory+row 锁内 CAS（phase/operation/generation），
`_set_maintenance()` 要求事务空闲并独立提交，避免 savepoint 假持久；`begin_maintenance_window` 改为对“上一操作”做 CAS
（修复要求历史 operation 等于新 operation）；恢复只允许重放冻结源，导入按 `migration_run` 身份区分
未创建/RUNNING 拒绝接管/失败受控复活/已完成仅核验（`_begin_run` 支持同 run_id 复活，不新增 id 隐藏冲突）；
`_local_record_matches` 逐字段对照 durable 行（project/operation/admission/generation/phase/三类摘要/provider/revoked_at），
marker 清理前必须证明本地记录与权威状态一致；marker 未落库时的采纳增加项目/generation/源目标校验，外来 marker 报 operation 冲突。

**B4 mAP50**：候选在 CASE 内解析（不依赖 WHERE 求值顺序），布尔/对象/数组/非法或非有限字符串、以及缩放后无法表示为
有限 double 的极端值（上界与下界）一律跳过，取首个合法有限值；SQLite 端用 Decimal 对齐同一量级规则，候选顺序、
>1 不缩放、NULLS LAST 不变。

**C 训练创建域模块化**：新增 `platform_core/training_create_api.py`（`TrainReq`、`validate_train_request`、
`start_training` 编排入口、`build_training_create_router` 两条 URL），app.py 只做依赖装配
（`TrainingCreateDependencies`）并保留进程内 `v12_start_train` 绑定；路径/方法/权限/响应/错误码与
“外部母数据预检延后到 TRAINING_PREPARE”合同不变；新模块不反向 import app。
源码守卫测试改为检查新属主，并断言 app.py 不再定义这两个 URL。

**状态**：A/B/C 均 CODE_IMPLEMENTED，CI_PENDING；U1 仍为 CUTOVER_NOT_VERIFIED，PG 清理域正式切换继续阻断。
