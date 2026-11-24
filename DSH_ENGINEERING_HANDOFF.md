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
