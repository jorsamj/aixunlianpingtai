# 畅联云算法训练平台｜P0-01C 独立 Supervisor 进度、问题、下一步与新会话交接

**交接日期**：2026-11-15  
**仓库**：https://github.com/jorsamj/aixunlianpingtai  
**唯一允许开发、提交和推送的分支**：`feature/external-algorithm-publishing`  
**历史交接基线**：`2584367c55cba24da8507b5fb2518d09eed6003f`（阶段 1A 初稿，不能作为最新 HEAD）。  
**当前优先状态（2026-11-15）**：**2C-2 已完成（代码 `f121d9bd` 全仓 23/23 SUCCESS）；2C-3 也已完成核心 CPU-only 验收（代码 `8d3140d1c91e26f18d26c0668c2f3e1ae7c2f5da`，同 SHA GitHub Actions 全仓 23/23 SUCCESS，含真实 Ubuntu systemd E2E 4/4）**。以下旧章节保留历史证据，实际接续以最新第 17 节和 2C-3 专项文档为准。**生产 A800/双4070 未接入，StopReceipt 与自动恢复仍 NO-GO。**

## 1. 业务背景及真正要解决的问题

平台已有中央调度、Node Agent、训练/模型转换/边缘模型复核 Runner、GPU reservation、租约和执行代数。当前执行层的风险是：Agent 在启动 GPU/SDK 计算之后若崩溃、网络分区或租约过期，计算进程及其 DataLoader/SDK 子孙进程可能仍存活。中央不能仅依据 Agent 心跳丢失或原主 PID 退出就认定旧 GPU 计算已停止，也不能自动释放原 reservation 并重新派发同一任务。

**既有 fail-closed 基线不得破坏**：远程执行未获得可信 OS 停机证明时维持 `REMOTE_AGENT_STOP_UNVERIFIED` HOLD，原 worker/lease/`tasks.attempt` 和 GPU reservation 保留，远程自动派单/恢复保持 OFF。Supervisor 是本机 OS 进程生命周期与可信见证，不是第二套中央调度器。

生产：A800、双 RTX4070；**本专项从未对这些真实生产节点执行、部署或重启操作**。4070 的业务数据与程序目录有专门离线部署合同，不可把 A800 与 4070 的路径/账户混用，也不可根据 GitHub 托管 CPU VM 假设真实 GPU 设备权限已经达标。

## 2. 已完成与未完成：逐阶段状态

| 专项 | 已取得的证据或代码 | 结论 |
|---|---|---|
| P0-01C-2B | GitHub 托管 Linux 的 systemd/cgroup 真实停机实验、隔离 launcher/child/grandchild；cgroup.events 绑定原 unit 的观察 | **隔离实验成功**；非生产可信 StopReceipt |
| P0-01C-3A | 一次性挑战、原 `tasks.attempt` + lease/boot/InvocationID/unit/cgroup 绑定、内存 SQLite CAS/假 GPU reservation 释放 | **模拟事务合同**；未接正式中央恢复 |
| P0-01C-3B-1/2 | Linux kernel→模拟中央桥；独立 UID/root-owned systemd unit 与 root-only 测试签名 | **受限 VM 实验成功**；未实现长期受保护信任根 |
| P0-01C-3B-3 | Unix Socket `SO_PEERCRED`、一次性准入和原 systemd unit 外独立 CPU 进程存活反例 | **确认原 cgroup 空组不等于整节点计算已停止** |
| P0-01C-3B-4 | GitHub AST 源码审计；非真实 GPU 的普通文件 DAC 模拟 | 确认原 Runner 直接 `Popen`；**真实 CUDA/GPU 权限仍未核实** |
| P0-01C-3B-5 | 正式模块 `node_agent_supervisor_gate.py`，Node Agent 能力过滤和三个 Runner 直启保护，`tools/audit_gpu_node_access.py` | **代码已提交**；默认 `legacy`，`supervisor-required` 只能阻断计算接单/直启，**不是可用 Supervisor** |
| 阶段 0 | [渐进实施方案](P0_01C_SUPERVISOR_INCREMENTAL_IMPLEMENTATION_PLAN_2026_11_15.md) 冻结五阶段及回退规则 | 已形成文档 |
| **阶段 1A（当前）** | `os_supervisor_protocol.py`、`os_supervisor_service.py`、`test_os_supervisor_phase1.py` 与 Node Agent 既有 CI 接入 | **独立通信代码已提交、存在需核对的问题、远端 CI 未通过** |
| 阶段 1B | 中央信任的执行授权 + 启动前持久 journal / 幂等 handle | **未开发** |
| 阶段 2 | 独立 Supervisor 真正执行固定 CPU worker；status/exit/log/stop/cgroup/restart 闭环 | **未开发** |
| 阶段 3 | 先模型转换，后训练，最后边缘复核，逐类适配 | **未开发** |
| 阶段 4/5 | 真实 GPU 权限、可信 StopReceipt、公钥信任链、中央原子恢复、生产 UAT | **未验收，生产 NO-GO** |

### 2.1 阶段 1A 现有代码（务必先读）

- `platform_core/os_supervisor_protocol.py`：协议 v1、16 KiB 长度帧、严格消息格式、请求 ID、客户端核验 Supervisor 内核 `SO_PEERCRED` UID；`SupervisedProcessHandle` 与 `subprocess.Popen` 完全分开。状态 UNKNOWN/失联不得当作 EXITED。
- `platform_core/os_supervisor_service.py`：独立 Linux AF_UNIX 服务端、受限 Agent UID 鉴权、默认 root-owned 固定 socket 地址、拒绝抢占既有 socket；当前 `health` 可以响应，但 `start/stop/read_log` 无真实执行后端，`inspect` 未知一律 HOLD。
- `tests/unit/test_os_supervisor_phase1.py`：协议、拒绝危险动作和本机 Linux Socket 回归。
- `.github/workflows/node-agent-executor.yml`：已纳入上述三个文件的语法与单元测试，没有另加一套 CI。
- 前一阶段正式保护 `CHANGLIAN_AGENT_EXECUTION_BOUNDARY`：**未设置或 `legacy` 为默认**；`supervisor-required` 则过滤 `training`、`conversion`、`conversion.rknn`、`deployment-test`、`deployment-test.rknn`，并在三个正式 Runner 中保护直接 spawn。**不可现在给生产节点设置 supervisor-required**，因为真正受保护启动后端不存在。

**验收补充**：阶段 1A 精确代码 SHA 的 [Ubuntu CI 43684001227](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43684001227) 后续已成功完成主合同 **503 passed、2 skipped**，POSIX Agent SIGKILL 集成 **2 passed**，Linux cgroup 专项 **31 passed**。这证明 Linux 方向现有协议测试通过，但 Windows/API 与整个 Workflow 尚未全绿。

## 3. 本次新核实的 CI 状态及明确缺陷（新会话先处理）

### 3.1 三个实际 GitHub CI 运行

| Run | 所对应提交 | 本次核查 | 处理 |
|---|---|---|---|
| [43679203190](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43679203190) | `c95caed83033042b97603b410dd45970abd75f8a` | **completed / failure**。Ubuntu contract 成功；Windows contract 和 Linux API guard 失败 | **已有原始日志，原因如下** |
| [43679484571](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43679484571) | `c66ef5678c9dd86cd681c67a1623baacc5217e3d` | **completed / failure**：Ubuntu contract 成功；Windows contract、API guard 失败 | 已读取原始 Job 日志；与 43679203190 相同两类已定位问题 |
| [43684001227](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43684001227) | `2ab61ce6fe6d6c8a09e5fc8d9723672d92c5f5f8` | **completed / failure**：Ubuntu contract success（503 passed / 2 skipped，另有 2+31 passed）；Windows 主合同 502 passed / 3 skipped、Linux PoC 30 passed / 1 failed（缺少 `os.getsid`）；API 24 passed 后旧 grep guard 失败 | 两项原因已核实，做最小修复并验证新 SHA 的完整 CI |

请注意：上述是**2026-11-15 本次只读核查时间点**的状态，新会话必须再次查看最新 HEAD、最近 CI 和确切 SHA。

### 3.2 已定位的两个旧 CI 失败根因

1. **Windows 旧 PoC 用例不兼容**：`tests/unit/test_linux_cgroup_poc_contract.py:226` 直接 `monkeypatch.setattr(poc.os, "getsid", ...)`；Windows 的 `os` 没有 `getsid`，导致 `AttributeError`。run 43679203190 的 Windows 主合同实际是 **472 passed、2 skipped**，后来 Linux 专项 PoC 合同 **30 passed、1 failed**。应仅将确实需要 POSIX 的用例作有据可查的跨平台跳过，或把它移至 Linux 专用工作流；**不能删除真实内核的安全验证**。
2. **Node Agent API guard 为过时代码文本检查**：`.github/workflows/node-agent-executor.yml` 仍用 `grep -Fq 'reported_capabilities = executable_agent_capabilities(requested_capabilities)' node_agent.py`；`node_agent.py` 现已使用 `reported_capabilities = allowed_remote_capabilities(...)`，因此 API 的 `Permanent Agent executor guards` 步骤退出 1。应更新为对**新安全过滤行为**的严格合同检查，而非删除守卫或回退生产实现。

### 3.3 代码逻辑复核纠正：start 请求并无协议矛盾

先前初读时误以为 `validate_request()` 会拒绝 `start` 的空 payload。**复核准确代码发现这是误判**：在 `os_supervisor_protocol.py` 中，`if payload: raise SupervisorProtocolError("START_NOT_IMPLEMENTED")` 只有 payload **非空**才抛错；空 payload 继续进入 `os_supervisor_service.py` 的 `PROTECTED_LAUNCH_NOT_IMPLEMENTED_HOLD` 响应，与单测一致。**不需要修改该协议来修 CI，也不得放开真正 start。**

阶段 1A Ubuntu 主合同 [run 43684001227](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43684001227) 实际 **503 passed、2 skipped**，进一步证实现有逻辑在该环境下通过。此处保留本纠正记录，避免新会话重复修复不存在的缺陷。

**新会话真正 P0 优先修复只有两个已复现的 CI 兼容问题**：Windows POSIX-only `os.getsid` 用例、API 工作流过期 grep 断言。若 Windows 新 Run 有其它失败，按确切新日志另外分析。

## 4. 已确定的技术路线：每次只推进一个纵向切片

### 阶段 1A 收尾（下一会话第一个动作）

- 重新读取最新 HEAD、run 43684001227 / 43679484571 / 43679203190 的 status/conclusion/jobs/logs。
- 只修上面的**已明确复现**问题，确保 Windows 不执行 POSIX-only 功能测试；CI grep 保留对新能力过滤的验收；start 拒绝路径协议一致。
- 运行 `tests/unit/test_os_supervisor_phase1.py`、`tests/unit/test_node_agent_supervisor_gate.py`、原 Node Agent API/contract 相关回归；Linux 真实 `SO_PEERCRED` 和 Windows 无支持时的拒绝语义分别核验。
- 远端 GitHub **精确提交 SHA 的 Ubuntu/Windows/API 结果**均结束且相关失败归零，才写“阶段 1A 回归已通过”；未结束写 pending，不因同名旧 run 成功而放行。

### 阶段 1B：可信执行授权与持久执行记录（独立模块，不接 Runner）

- 明确中央**不可伪造**的 grant/独立回查接口，要求 Supervisor 核验 `task_id + tasks.attempt + worker_id + node_id + original lease hash + GPU UUID + boot_id + challenge/nonce + expiry`，拒绝 Agent 自报签名、任意路径或命令；独立权限边界中保存验证密钥/公钥。
- 本机 durable journal 应写入：`execution_handle_id`、原任务代数、已验证 grant 摘要、原执行单元预登记、OS identity/InvocationID、状态及单调递增事件序号。它**只负责 OS 执行实例映射**，不另建中央队列或二次任务所有权。
- `start` 必须防重：重复请求、回复丢失、服务崩溃后，只能查询原记录或返回 UNKNOWN/HOLD，不能产生第二个执行；持久落盘先于真实 spawn。
- 这阶段仍不开放实际 GPU、中央任务重排或运行中生产 Agent 切换。
- 最小验收是单条真实持久 journal 的状态和幂等行为，失败时有确定 HOLD；**不再增加多套重复 CPU PoC 工作流**。

### 阶段 2：固定 CPU worker 的完整功能

- Linux systemd SYSTEM service/cgroup 托管**固定、明确允许的**工作负载；`status/exit_code/log_read/stop` 真正可用。
- Supervisor 可以重启后认领持久执行身份，原 unit 不明/被替换/子孙仍活跃时一律 UNKNOWN/HOLD。
- 只测一次完整的启动、日志、完成、取消、断线重连、重复请求和崩溃恢复 E2E，不伪造 StopReceipt。
- 产出可供 Runner 适配的真实 `SupervisedProcessHandle`；仍不能当作 `subprocess.Popen` 或复用普通 Agent 的 `terminate_tree` 控制另一 UID 的进程。

### 阶段 3：逐类正式 Runner 适配

顺序：**模型转换 → 训练 → 边缘模型复核**。先选简单无 GPU 的转换链路验证结果/日志/取消/失败/回传；训练再考虑 DataLoader/多 GPU、OOM 残留和训练报告；复核最后覆盖 Ultralytics/Paddle/RKNN 等 SDK。中央不重构、不加第二套 generation、前端暂不改。

### 阶段 4/5：需授权的真实硬件验收

A800/双4070 的 systemd Agent UID、sudo/polkit、`/dev/nvidia*`、UVM、驱动和 cgroup device policy **尚无现场证据**；已有 `tools/audit_gpu_node_access.py` 是只读清单工具，**从未在生产执行**。实机只读核查、设备权限变更、训练/转换测试、部署重启和真实任务迁移都必须事先取得用户明确授权。可信 StopReceipt/中央 CAS 恢复/自动派单在这些条件通过前全部禁止。

## 5. 严格执行规则（新会话必须遵守）

1. **唯一长期开发分支**：`feature/external-algorithm-publishing`。任何写操作前重新读取远端 HEAD、文件 blob SHA；不用旧 SHA 盲目覆盖；不合并 main、不 force push、不创建 Release。
2. **不大重构**：不改 `app.py` 形成巨型调度器、不重写中央 `tasks.attempt`/lease/GPU reservation、不搬业务 Runner 的产物处理和日志逻辑。
3. **不提前部署生产**：不 SSH/访问 A800 或双4070，不重启服务、调整 GPU 权限、释放旧 reservation、执行实际训练；需要时明确提出最小只读/维护窗口审批。
4. **代码与文档同时收口**：每一小步提供实际改动文件、提交 SHA、精确 CI run/Job、是否真实通过、失败原因及修复证据，更新 [Issue #26](https://github.com/jorsamj/aixunlianpingtai/issues/26) 及本交接文档。
5. **优先业务能力，不无休止测试**：只修已复现缺陷、少量必要回归与隔离端到端；不新增几乎相同的模拟证明工作流，不重复跑无关压力测试。
6. **禁止错误放行**：不能因为 `health=200`、Socket OK、原 cgroup 空、旧测试签名有效就宣称生产 StopReceipt 可信；`UNKNOWN`、租约断联、启动回复丢失、权限未知一律 HOLD。
7. **默认保持兼容**：`legacy` 不变；`supervisor-required` 只有实现真正受保护 Runner 执行后才可在隔离测试节点启用，不允许拿生产验证缺失能力。

## 6. 建议的下轮最小交付与停止条件

**本次新会话的首个最小专项不是再次写一批新服务功能，而是阶段 1A CI 收尾**：

- 修复经证实的 start 拒绝语义、Windows POSIX 专项、过时代码 grep；
- 对精确 HEAD 的 Node Agent Ubuntu/Windows/API 跑已有 CI，取得明确 PASS/FAIL；
- 若 CI 还有失败，先精确定位、做最小修复，不急着进入阶段 1B；
- 阶段 1A 真实回归过关后，才选择阶段 1B **“可信授权协议 + journal schema”** 一次最小提交，先不接正式 Runner。

**停止/升级条件**：出现必须改变中央任务所有权、要求在未批准的 A800/4070 执行、无法证明权限隔离或完整停机、或者需要一次性重写三个 Runner 时，停止开发该路径，先给出风险、替代方案和用户审批事项。

## 7. 相关资料索引

- [阶段 0 渐进实施方案](P0_01C_SUPERVISOR_INCREMENTAL_IMPLEMENTATION_PLAN_2026_11_15.md)
- [阶段 1A 正式 Socket 服务/句柄合同](P0_01C_SUPERVISOR_PHASE1_TRANSPORT_2026_11_15.md)
- [P0-01C-3B-5 正式 Agent 默认兼容/强制阻断开关](P0_01C_3B_5_SUPERVISOR_MIGRATION_GUARD_2026_11_15.md)
- [完整长期交接文档](P0_01C_REMOTE_AGENT_TRUSTED_STOP_HANDOFF_2026_11_15.md)
- [GitHub Issue #26](https://github.com/jorsamj/aixunlianpingtai/issues/26)
- [Node Agent CI 阶段 1A](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43684001227)

**本文件是新会话的优先上下文。其他历史报告仅作为原始证据，不能覆盖本文件记录的 CI 和生产 NO-GO 条件。**

### 3.4 交接提交后的 CI 状态更新（同日补充）

在写入初版交接文档后，GitHub [run 43679484571](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43679484571) 从 queued 变为 **completed/failure**。原始日志已再次核对：

- `contract (ubuntu-24.04)`：**success**；
- `contract (windows-latest)`：主体单测 **473 passed、2 skipped**，随后 Linux cgroup PoC 专项 **30 passed、1 failed**，仍是 `tests/unit/test_linux_cgroup_poc_contract.py:226` 的 `os.getsid` 在 Windows 不存在；
- `api`：API 测试 **24 passed**，随后 `Permanent Agent executor guards` 因旧的 `reported_capabilities = executable_agent_capabilities(requested_capabilities)` grep 文本不再存在而退出 1；
- 最新阶段 1A run `43684001227` 已 **completed/failure**：Ubuntu contract success（503 passed/2 skipped + 两组专项 2/31 passed）；Windows 主合同 **502 passed/3 skipped**，Linux-only PoC **30 passed/1 failed**（`os.getsid`）；API **24 passed**，后续旧 grep guard 失败。整轮未通过，根因明确。

**旧 Windows/API 问题已跨两个不同 SHA 重复出现；阶段 1A 的 start 拒绝逻辑经代码复核和 Ubuntu CI 验证是正确的，不是故障项。新会话先修真正的 CI 兼容问题，再推新功能。** 不需重复做 cgroup CPU PoC 研究。


## 8. 2026-11-15｜阶段 1A CI 两项定点修复（待新 SHA 验收）

- 修复前长期分支 HEAD：`bddb84a8a5be729626a0cf718895aeaa14e71e7d`；原 [Node Agent Executor run 43684001227](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43684001227) 为 **completed/failure**。原始 Windows Job 132720496253：POSIX 用例 `test_three_process_tree_requires_lineage_sessions_ticks_and_cgroup` 在 Windows 缺少 `os.getsid`（30 passed / 1 failed）；原始 API Job 132720496100：过时的 `reported_capabilities = executable_agent_capabilities(requested_capabilities)` 静态守卫失败；Ubuntu Job 132720496289 成功。
- 本次仅修改 `tests/unit/test_linux_cgroup_poc_contract.py`：对确实依赖 POSIX `os.getsid` 的单一测试标记 `pytest.mark.skipif(not hasattr(os, "getsid"))`，保证 Linux 原有父子进程/会话/cgroup 安全断言完全保留且继续执行，Windows 其它便携合同照常执行；没有跳过整个测试文件。
- 仅修改 `.github/workflows/node-agent-executor.yml`：把旧赋值文本的静态守卫替换为实际入口 `reported_capabilities = allowed_remote_capabilities(`；已有 `test_node_agent_supervisor_gate.py` 保留默认 `legacy`、受保护能力过滤、拒绝非法配置和三 Runner 直启阻断等行为回归，不删除守卫。
- 未改 `os_supervisor_protocol.py` 的正确 `start` 空 payload 拒绝行为；未改正式 Runner、中央任务代数/租约、GPU reservation、生产服务和配置。
- **验收状态：新提交及其 Node Agent Executor Ubuntu/Windows/API CI 待实际终态复核，不提前宣称 1A GREEN，更不得启用中央自动恢复。** 生产依旧 `legacy`、HOLD、自动派单 OFF、NO-GO。

## 9. 2026-11-15｜阶段 1A 正式验收结论

代码 SHA [`1a1eb411144104ddc0464bfe0b133ce3ae5b77e4`](https://github.com/jorsamj/aixunlianpingtai/commit/1a1eb411144104ddc0464bfe0b133ce3ae5b77e4) 的 [Node Agent Executor run 43687654179](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43687654179) 已取得 `completed/success`：Ubuntu、Windows、API 三个 Job 均 `SUCCESS`。此前 Linux-only `os.getsid` Windows 崩溃及旧 Agent capabilities grep 两项已消除。**阶段 1A 代码/跨平台 CI 正式通过；仅授权继续开发阶段 1B，不代表生产可用。**

## 10. 阶段 1B-1｜受限授权校验与本地执行意图 journal（提交后待 CI）

**本次开发边界**：新增 `platform_core/os_supervisor_authorization.py`、`platform_core/os_supervisor_journal.py`、`tests/unit/test_os_supervisor_phase1b.py`；把新的语法检查和单元合同接入原 `node-agent-executor.yml`，不创建重复 workflow，不动正式 Node Agent/训练/转换/边缘复核 Runner，也不改变旧 Supervisor Socket `start` 的禁止运行语义。

- **授权验证仅供正式 Supervisor 后续集成**：Ed25519 固定签名算法、域隔离、严格 schema、90 秒内有效期；绑定 `task_id`、原中央 `tasks.attempt`（字段 `task_attempt`）、`worker_id` / `node_id`、执行 lease SHA-256、`boot_id`、本地挑战与固定 CPU profile。当前只允许 `gpu_uuid=CPU_ONLY`、`runner_profile=fixed-cpu-v1`；其它 GPU/任意执行内容全部 HOLD。**中央的真实任务租约原子校验及可信签发 API 尚未接入**；测试签名不能冒充中央授权。
- **本机持久执行意图**：独立 SQLite FULL-sync（非中央任务数据库），按 `task_id + task_attempt` 唯一持久登记 `handle_id` / grant digest / challenge / boot / 预留 systemd unit / event_seq；对相同有效 grant 的重复请求及响应丢失返回同一 handle，对不同 grant 的同代请求拒绝。root 模式只允许 `/var/lib/changlian-os-supervisor/executions.sqlite3`、root 私有目录/文件；隔离测试有显式 test-only 路径。查询在 OS identity 未核验前始终为 `UNKNOWN`，不得视为 EXITED。
- **阶段 1B-1 不等于 1B 完成**：尚未接入中央真实签发/原 lease 存活校验、公钥安全分发与吊销、独立 Socket 的授权流、真实 systemd 进程启动及崩溃恢复；这些仍按既定门槛逐项实施。只有中央授信和 journal 协作真实接通并验证后才能进入阶段 2 CPU worker。
- **验收闸口**：本次阶段 1B-1 新 SHA 的 Ubuntu/Windows/API 必须独立核验；CI pending 不宣称 GREEN；未来多实例并发和 journal 文件完整性按真实代码再核查，不用重复旧 CPU PoC。
- **生产约束不变**：`legacy` 默认、`supervisor-required` 不对生产启用；`REMOTE_AGENT_STOP_UNVERIFIED` HOLD、自动派单 OFF、生产 NO-GO。A800/双4070 未访问、未部署、未重启。

### 10.1 阶段 1B-1 精确代码 SHA 的 Node Agent CI 正式验收

**功能提交**：[`5b7ca69a2f109a97b37960973fb56c6d214f177b`](https://github.com/jorsamj/aixunlianpingtai/commit/5b7ca69a2f109a97b37960973fb56c6d214f177b)。主验证 [Node Agent Executor 43688432320](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43688432320) 已 **completed/success**，同 SHA 的三个 Job 均成功：
- Ubuntu contract：**517 passed / 2 skipped**，原 POSIX SIGKILL **2 passed**、Linux cgroup 合同 **31 passed**；
- Windows contract：**516 passed / 3 skipped**，Linux cgroup 便携合同 **30 passed / 1 skipped**；
- API：SUCCESS（包含现行永久安全 grep 守卫）。

该准确 SHA 的阶段 **1B-1 语法、权限拒绝合同、签名验签及本机 durable journal 单元回归 GREEN**；同 SHA 的其它仓库级 Actions 如仍 queued/in_progress，不据此声称全部工作流结束。当前根本门槛仍是中央真实租约原子核验后签发、公钥与 journal 接线、完整服务重启/进程身份恢复。新模块虽已存于 Git，却未被正式 Supervisor socket 或 Runner 引用；**阶段 1B 整体尚未完成、阶段 2/生产继续 NO-GO**。本次文档独立提交属于验收记录，不替代功能 SHA 的 CI。

## 11. 2026-11-15｜阶段 1B-2A 中央授权签发最小链路（提交后待 CI）

目标不是重新实现 TaskQueue / Scheduler，也不是目前开放 Supervisor 真实启动，而是用**现有中央 SQLite 任务真相**验证 CPU-only 执行资格，再生成 Supervisor 能独立验证的短时 Ed25519 grant。

- 新建 `platform_core/os_supervisor_central_grants.py`：默认 **disabled**，只接受受信中央进程注入的 `Ed25519PrivateKey`，没有自动创建密钥、没有新 HTTP API；使用现有 `TaskRepository._connect()` 一次只读事务读取 `tasks` 与 `service_nodes`，核对任务状态 `RUNNING`、真正的 `tasks.attempt`、原 execution lease token（非 assignment lease）、原 worker/node、节点 token/可用能力/在线心跳以及执行租约到期时间。只对明确标记 `resource_key=supervisor-cpu-v1` 且 `kind=MODEL_CONVERSION` 的隔离 CPU 试验任务开放签发；15 秒上限，且绝不晚于中央 lease 到期。**普通生产转换/训练任务不能通过本阶段签发。**
- `platform_core/os_supervisor_authorization.py` 中校正 Node ID 格式限制，与现有 `service_nodes._NODE_ID_PATTERN` 保持兼容；不放松 grant 签名验证及 `task_id` 规则。
- 新增 `tests/unit/test_os_supervisor_central_grants.py`：通过**现有真实 TaskRepository 和 ServiceNodeRepository/SQLite**建立隔离资源记录，覆盖授权链路→原签名校验→本机 durable journal 同代幂等，过期 lease、错 attempt、错 node/token、取消中任务、非隔离 CPU profile、节点禁用等 HOLD。代码只在临时测试 DB 上执行，不触碰 A800/双4070。
- 复用 `node-agent-executor.yml` 运行 Ubuntu/Windows/API。额外发现同一前期 1B-1 SHA 的 [Portable Deployment 43688437090](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43688437090) 的 API 主体完成后，**另一个遗留旧 grep** `reported_capabilities = executable_agent_capabilities(requested_capabilities)` 导致 API Job 失败；本次仅更新 `.github/workflows/portable-deployment.yml` 至当前安全过滤赋值文本，保留所有其它守卫。
- **重要边界**：签发模块未接进中央正式 FastAPI，也未配置生产私钥；Supervisor Socket 仍拒绝 `start`；root 公钥管理/轮换、challenge 来源可信验证、实际部署权限、分布式确认时序、lease 到期后的重查、systemd CPU worker 与真实 OS 恢复仍待下一子阶段。即使中央短时 grant 已签发，也**不代表**可释放任何 HOLD、可自动重新分配 GPU、可生产上线。
- **前端判断**：阶段 1B 的签名/持久登记属于后端安全能力，前端无必需变更；进入 Runner 灰度后可以在现有节点管理与任务详情增加 Supervisor 健康、执行模式、停机证据待验证的只读状态。禁止在可信 StopReceipt 和中央 CAS 完成之前加入手动“强制释放/恢复/重派”按钮。
- **验收状态**：阶段 1B-2A 提交后按新 SHA 核实 Node Agent + Portable Deployment 精确 Job，未完成不标记 PASS。保留 `legacy`、`REMOTE_AGENT_STOP_UNVERIFIED` HOLD、自动派单 OFF、生产 NO-GO。

### 11.1 阶段 1B-2A 精确 CI 终态与下一真实纵向切片

**本轮功能提交**：[9808d7e3dd0a11c9b3d93df53e4a2f1197211134](https://github.com/jorsamj/aixunlianpingtai/commit/9808d7e3dd0a11c9b3d93df53e4a2f1197211134)；GitHub [Node Agent Executor run 43689407419](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43689407419) 为 **completed/success**，三个 Job 均成功：
- Ubuntu：主合同 **529 passed / 2 skipped**；POSIX Agent SIGKILL **2 passed**；Linux cgroup 合同 **31 passed**；
- Windows：主合同 **528 passed / 3 skipped**；cgroup 便携合同 **30 passed / 1 skipped**；
- API：SUCCESS。
- 同一 SHA 的 [Portable Deployment run 43689407425](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43689407425)：Ubuntu transport、Windows transport、API **全部 SUCCESS**，原过时 grep 已消除。

**验收判定**：本次 1B-2A 的真实中央任务数据库只读签发逻辑及跨平台 CI **GREEN**。这不是完整阶段 1B：签发逻辑仍默认关闭、尚未挂载中央实际 API；Supervisor Socket 仍没有受保护 challenge→grant→journal 登记调用入口，亦无生产信任配置、公钥轮换、OS 启动/停止与可靠停机证据。绝不可据上述测试开启计算接单或中央自动恢复。

**下一小项 1B-2B（优先实际代码而非再做 PoC）**：审计当前协议与服务，在既有 root-owned Socket 之内增加固定的 challenge/authorize_intent 严格 schema，读取由可信服务部署配置管理的 pinned issuer 公钥，调用 journal 在启动前预登记唯一 handle；Agent 无法提供公钥路径、shell/unit、root PID、任意执行 profile。中央签发路由仅在独立受限测试配置下开放，并与原 `tasks.attempt` / node token / lease 真值实时核验；服务重启、重复授权、过期/回放均保守 HOLD。**阶段 2 才允许固定 CPU workload 真正 systemd 托管，不改训练/模型转换/边缘复核正式 Runner。**

**前端最小方案已审计**：现有 `static/modules/service-node-runtime.js` 已支持展示节点连接状态、心跳、能力、GPU、Worker 与 durable tasks，因此后续只需在该页面的现有卡片/任务行增加只读 Supervisor 实例状态、`legacy/supervisor-required` 执行模式和拒绝/未知原因。先完成可信状态后端字段再开发 UI；目前不改前端，不增加恢复/释放/强停按钮。

生产 A800/双4070 未接触；`legacy` 默认、`REMOTE_AGENT_STOP_UNVERIFIED` HOLD、远程自动派单 OFF、生产 **NO-GO**。

## 12. 2026-11-15｜阶段 1B-2B：中央 HTTP → 受保护 Socket → durable intent（提交待 CI）

**开发目标**：把阶段 1B-2A 已有的中央短时授权验证和阶段 1A 的独立 Unix Socket / 阶段 1B-1 journal 正式接成一个**可请求、可持久登记，但绝不启动工作负载**的纵向切片。不是再建立新的调度器，也不是开始系统级停机控制。

### 改动范围与工作流程

1. 在现有 `agent_executor_router` 中**仅装配一条隔离** `POST /api/v63/node-executor/{node_id}/executions/{task_id}/supervisor-cpu/grant`；实际实现放在 `platform_core/os_supervisor_central_api.py`，不扩充 `app.py` 的业务职责。默认返回 `CENTRAL_CPU_ISSUER_DISABLED_HOLD`，只有受信控制端部署配置 `CHANGLIAN_SUPERVISOR_CPU_GRANTS_ENABLED=1` 且已有 owner-only 固定私钥文件时才会继续；验证真正 `tasks.attempt` + execution lease + node token/worker/心跳/隔离 CPU 资源，再返回有效期 <=15 秒的签名 grant。即使 API 返回，也仅表示允许 **登记**，不是授权任意进程或 GPU 启动。
2. 原 `os_supervisor_protocol.py` 严格新增 `challenge`、`authorize_intent` 两个动作及限定结构；继续拒绝 `start` 非空 payload 和真实 `start/stop`；拒绝任意 shell/命令、路径、unit/PID、GPU 或密钥路径，最大报文 16 KiB/严格 request_id 仍保留。
3. 独立 `os_supervisor_service.py` 仍用内核 `SO_PEERCRED` 限制原非 root Agent UID；**只有显式** CLI `--enable-cpu-intent` 才初始化 root 私有 journal + 固定公钥、开放 challenge 与授权登记；默认 Socket 启动仍只提供 health 与拒绝。正式服务端公钥固定在 `/etc/changlian-os-supervisor/issuer.ed25519.pub`（raw 32 bytes，root 0700 目录 + 0600 文件）；控制端私钥固定在 `/etc/changlian-control/supervisor-cpu-issuer.ed25519.key`（所属服务账户 0700 + 0600）；`O_NOFOLLOW` / `fstat` 校验 owner/mode，**既不从 Agent 请求读取路径，也不在应用里生成/复制生产密钥**。密钥由获准的系统部署流程安全提供，此轮仅开发检查合同，**没有部署或启用配置**。
4. journal 按原 `task_id + tasks.attempt` 唯一落盘；短期同一签名 grant 的丢响应重试返回原 handle，Supervisor 重启后重新打开同一 journal 仍只能报告 `UNKNOWN`；签名错、boot 不符、挑战未知/过期、租约有变化一律 HOLD，不能创建第二个执行实例。登记接口返回 `CPU_INTENT_RECORDED_NO_LAUNCH`，不对外称运行中或停机已验证。
5. 增加 `tests/unit/test_os_supervisor_phase1b_ipc.py`：真实 FastAPI HTTP、正式中央 TaskRepository / ServiceNodeRepository / SQLite，Linux 非 root AF_UNIX Socket + SO_PEERCRED、签名验证/固定文件权限及 journal 重启/防重；Windows 仅便携合同。复用 `Node Agent Executor` 原有 Ubuntu/Windows/API CI，不新建重复工作流；额外专门修正了**默认 legacy 环境对可选 cryptography 依赖的延迟导入**，保持 Portable Deployment 的原有依赖契约。

### 验收边界与剩余工作

本子阶段完成后仍必须明确区分：本次是一条**真实服务请求与持久意图闭环**，并未真正启动、停止、管理 systemd 单元；`StopReceipt` 仍不存在，`central_recovery_allowed=false`，`supervisor-required` 仍禁止生产计算直启。GPU UUID 当前仅 `CPU_ONLY`；无真实 GPU 权限隔离、无正式 Runner 接入、无受控中央恢复和任务重排。签名授权有效期很短，正式 OS 启动前必须再次验证中央任务 lease、确认 journal 与实际 systemd OS identity，不能仅凭旧签名/握手允许派单。

**下一步**：按本轮精确 SHA 审核 Node Agent Ubuntu/Windows/API 和 Portable Deployment 回归。绿后阶段 2 才实施固定 CPU worker 的真实 systemd system service/cgroup 托管、运行/退出码/日志/取消/进程重启核验；随后依序模型转换→训练→边缘复核。未来本机可信 signer/StopReceipt 和中央 CAS 恢复需要独立安全验收及生产授权。

**前端**：阶段 1B-2B 不改现有页面。正式 Runner 灰度时只在现有 `static/modules/service-node-runtime.js` 节点卡片与任务详情新增只读 `Supervisor 状态/执行模式/证据待验证`；不提前新增强制重派/停止证明绕过/释放 GPU 操作。

**生产边界**：A800 / 双4070 未连接；默认 `legacy`、自动派单 OFF，原 `REMOTE_AGENT_STOP_UNVERIFIED` HOLD 和 GPU reservation 保持；生产 **NO-GO**。

### 12.1 阶段 1B-2B 定点 RED/GREEN 与真实 CI 验收结论（同日）

- 首次功能提交 [`1fe3f71f6a0002db422cc026cc7a4b0e999fdbde`](https://github.com/jorsamj/aixunlianpingtai/commit/1fe3f71f6a0002db422cc026cc7a4b0e999fdbde) 的 [Node Agent 43690842053](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43690842053) Ubuntu 新合同 **534 passed / 2 skipped / 1 failed**：`test_trusted_control_signer_file_requires_private_mode_and_no_symlink` 本来已拒绝权限错误，但由于 `GrantRejected` 继承 `PermissionError` / `OSError`，被通用 `except OSError` 再包装成 `SUPERVISOR_KEY_UNAVAILABLE_HOLD`，丢失专门的 `FILE_UNTRUSTED` 错误码。没有错误放行权限。只在 `platform_core/os_supervisor_trust.py` 增加 `except GrantRejected: raise`，后续 OS 异常仍按通用 HOLD，绝不改安全判定。
- 精确修复 SHA [`fe0c791fb0db447648db309d590014dc1098553b`](https://github.com/jorsamj/aixunlianpingtai/commit/fe0c791fb0db447648db309d590014dc1098553b)；[Node Agent Executor run 43691027462](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43691027462) **completed/success**，三个 Job 全部成功：Ubuntu **535 passed / 2 skipped**（POSIX SIGKILL **2 passed**，Linux cgroup **31 passed**），Windows **532 passed / 5 skipped**（便携 cgroup **30 passed / 1 skipped**），API **SUCCESS**。
- 初次功能提交的 [Portable Deployment run 43690842045](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43690842045) 三 Job **completed/success**，确认中央路由延迟导入加密依赖后旧可移植部署路径不回归。修复 SHA 的 [Portable Deployment 43691032313](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43691032313) 在本节写入时尚未整体 completed，不能把全部仓库工作流标记为成功。
- **阶段 1B-2B 仅“隔离 CPU-only HTTP→Socket→durable intent 基础链路 + 核心 CI”GREEN**。这不代表生产根公钥/私钥部署、密钥轮换、真正 systemd/cgroup 执行、崩溃重接管、可信停止证明或中央自动恢复通过。后续阶段 2 的真实固定 CPU worker 应在 GitHub/其他获准隔离 Linux 环境实施一次功能 E2E；不需要 A800/4070，但绝不把普通权限 PoC 当硬件 GPU 安全证明。
- 最小未解决的安全/运维项：正式 key provisioning / rotation 和 root-owned unit 运行审计；短期 challenge journal 的容量/清理界限；systemd unit 不可被普通 Agent 创建或越权停止；服务重启后原 OS identity 与持久 handle 绑定；确认停止的后代进程及 fail-closed STOP。全部满足并得到用户授权前，中央 `REMOTE_AGENT_STOP_UNVERIFIED` HOLD、自动派单 OFF、默认 `legacy`、生产 NO-GO 不变。无真实 Worker 任务被启动。

### 12.2 修复 SHA 同版 Portable Deployment 最终终态（同日补录）

针对精确功能 SHA `fe0c791fb0db447648db309d590014dc1098553b` 的 [Portable Deployment run 43691032313](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43691032313) 已 **completed/success**：Ubuntu transport、Windows transport、API 三项全部成功。与 [Node Agent Executor 43691027462](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43691027462) 同 SHA 的 Ubuntu/Windows/API 全绿相互印证。阶段 1B-2B **本专项关键工作流同 SHA 验收通过**，不意味着其它仓库工作流或生产部署全部完成，更不能解除 HOLD。

## 13. 阶段 2A｜固定 CPU-only systemd SYSTEM service 真实执行后端（待本 SHA CI）

**先决确认**：此前修复 SHA `fe0c791fb0db447648db309d590014dc1098553b` 关联 GitHub Actions 23/23 success；唯一长期分支本轮前 HEAD `ee966848124d63db08e670704c4b0490b8b1708d`。A800/双4070 不访问、不部署、不重启。这里进入真实 OS 生命周期，**不冒充为已经接入普通任务执行**。

### 13.1 本轮实现

- 新增 `platform_core/os_supervisor_cpu_systemd.py` 的 `FixedCpuSystemd`，仅在 Linux / root / systemd system manager 可用时才可在正常模式初始化；**此时没有任何正式 Agent/Runner 调用它**。没有公开新的 HTTP/Socket 启动接口，没有生产启动开关。单元名称只能由 Supervisor 原既定随机 handle 构成 `changlian-os-<32 hex>.service`，不能由 Agent 提供 shell、命令行、任意进程 PID、任意路径、unit 参数或 env/cwd。
- `systemd-run --system` 创建真正独立 transient `.service`（不是 `--user` 或普通 `Popen`）。被托管进程固定为 `/usr/bin/python3 -I -u -c` 内置不接收外部参数的 CPU-only 打点/短时 sleep 小程序；`Type=exec`、`DynamicUser=yes`、`NoNewPrivileges=yes`、`PrivateDevices=yes`、`DevicePolicy=closed`、`KillMode=control-group`、`ProtectSystem=strict`、`RuntimeMaxSec=40s`、CPU/内存/PID 限额。**这不能充当 A800/4070 真机 GPU ACL 实证。**
- 启动后通过 `systemctl show` 单独验证固定 systemd unit、`Transient`、`InvocationID`、`ControlGroup`、`MainPID`、设备隔离和子进程清理策略；属性缺失、权限错、重建新 InvocationID 均 HOLD。重新创建 backend 对象可用原 InvocationID 对同一 unit 只读重连，不会重复启动。
- `request_stop` 在精确 InvocationID 检查通过后仅用 `systemctl --system stop` 停止该 unit，不允许任意 PID kill；如果 stop 之后 unit 立刻 GC/状态不明，返回 `UNKNOWN` 而非伪造 `EXITED` 或可信 StopReceipt。即使 systemctl 返回 0，也显式 `trusted_stop_receipt_available=false`，中央 HOLD 和自动重派不可解除。
- `read_log` 仅能从已验证 unit 调用 systemd journald 读取最多 64 条/8192 字节的诊断字节；**尚未承诺 offset 流式日志和跨重启持久日志游标**。

### 13.2 隔离真实 Linux 验证

- 新增 `tests/unit/test_os_supervisor_cpu_systemd.py` 验证固定命令、严格 unit 白名单、拒绝 GPU/命令注入、OS InvocationID 不匹配无法停止和 stop 不发证明。
- 新增 `tests/integration/test_os_supervisor_cpu_systemd_live.py`：在 GitHub 自带 **Ubuntu 24.04 隔离 Runner 的 systemd 系统服务**上，以随机 unit 启动真正固定 CPU 程序；检查 `MainPID/ControlGroup/InvocationID`、重新构造 backend 后同一身份重查、journald 诊断、真正 systemctl stop，最后只回报 UNKNOWN + 尝试清理唯一测试 unit。**没有生产任务**。这是唯一新增的真实 OS E2E，不新增 GitHub workflow，复用 `node-agent-executor.yml` 原 Ubuntu 合同 Job 的独立 step（sudo -n、超时 3 分钟）；如 runner 不支持系统级 systemd，测试会失败并阻止声称阶段 2A 已通过，而非静默跳过。Windows 只执行纯便携合同。
- 正式旧 Supervisor Socket 的 `start/stop` **继续拒绝**、`legacy` 默认；根 journal 暂仅 PREPARED，尚未原子持久化 STARTING 与 OS InvocationID，故 backend 此阶段**不接入任何正式启动入口**，避免已启进程却丢回复后重复启动。下一子阶段在取得本轮真实 E2E 结果后接 journal CAS + Socket 的固定 CPU 启停、跨重启恢复和退出证据。

### 13.3 停止条件与前端

如果隔离 Ubuntu 无法启动系统服务或防护属性不满足，必须定位精确失败原因；不可直接删掉 `PrivateDevices/DevicePolicy/DynamicUser` 等保护来“修绿”。如果真实 systemd/cgroup 证据无法满足，只能报告阶段 2A 未验收。生产 GPU、训练/转换/复核 Runner、中央任务 owner/attempt/lease、自动恢复、StopReceipt、前端 UI 都不改。生产保持 **NO-GO**。

### 13.4 阶段 2A 精确 SHA 与隔离真实 systemd E2E 验证（2026-11-15）

- 功能 SHA [`b2045dd7d64460ab48ef9df2d4fd8c8e27aab990`](https://github.com/jorsamj/aixunlianpingtai/commit/b2045dd7d64460ab48ef9df2d4fd8c8e27aab990)；[Node Agent Executor 43692503127](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43692503127) 已 **completed/success**。Ubuntu 主合同 **543 passed / 2 skipped**、原 POSIX SIGKILL **2 passed**、Linux cgroup 合同 **31 passed**，此外在 GitHub Ubuntu 24.04 隔离 runner 上以 `sudo -n` **真正启动和停止系统级 transient systemd service**，E2E **1 passed**（不是 subprocess mock / CPU PoC 静态断言）；Windows 与 API Job 成功。
- 同 SHA 另外 [Node Agent 43692512206](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43692512206) 与 [Portable Deployment 43692512254](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43692512254) 已 **completed/success**。阶段 2A 固定 CPU-only systemd 后端 + 隔离真实 OS E2E 已验收；这仅是 OS executor 部件，尚无中央授权到真实执行的一体化生产链路。
- 真正 unit 的测试限定固定 CPU 程序、随机 `changlian-os-<handle>.service`、动态非 root workload 用户和 `PrivateDevices/DevicePolicy=closed`；断言 systemd `InvocationID`、cgroup、PID、有限日志、实际 stop 返回但 **StopReceipt=false/UNKNOWN**，从未触碰 A800/4070。

## 14. 阶段 2B｜原签名授权 + journal 单次 CAS + systemd 实际执行（本轮提交待 CI）

**本次专注消除最危险的重复启动窗口。** 以现有 `ExecutionJournal` 为唯一 OS 执行身份归属表（**不是新中央任务所有权**），保留 `tasks.attempt` 和原中央 execution lease；无 GPU、无正式业务 Runner。

- `platform_core/os_supervisor_journal.py`：新增与既有 journal 同一 SQLite 文件里的 `cpu_unit_identities` 本机执行身份表，不改变中央调度库；`claim_cpu_launch` 在一笔 `BEGIN IMMEDIATE` 事务中重新验中央签名原绑定、boot、grant 到期、handle/attempt/lease hash，并只允许 `PREPARED→STARTING` CAS。**CAS 落盘后才能调用 systemd-run**；重试和启动丢响应永不回退 PREPARED。`record_cpu_identity` 验证实际 OS `InvocationID`、原 unit cgroup、main pid 后原子 `STARTING→RUNNING`；异常与 stop 只能转为 UNKNOWN，不允许回收执行租约或宣称 EXITED。
- `platform_core/os_supervisor_protocol.py`：旧 `start` 空 payload 仍默认 HOLD；新增唯一允许的 CPU-only body `handle_id/execution_generation/envelope`，禁止 command、cwd、env、GPU、任意 unit/PID。`read_log` 成功只接受有界 base64、无持久 offset 承诺的已核实数据；旧失败 HOLD 行为不变。
- `platform_core/os_supervisor_service.py`：正常模式仍不启用真实启动；只有 CPU intent 验证、固定可信公钥、独立 journal 且 CLI **同时显式** `--enable-cpu-intent --enable-cpu-trial-launch` 才能调用实际 `FixedCpuSystemd`。启动由上面 CAS 先持久化，再调用 systemd `launch`，最后写入 OS identity；启动回执丢失/进程身份不一致→UNKNOWN/HOLD 且不第二次 spawn。重建服务可从 journal 获取原 InvocationID、继续只读 `inspect`；`request_stop` 真正调用针对原 unit 的 systemctl stop，但**永远返回 StopReceipt 未验证/HOLD**，不让中央自动重派。日志只从该原 unit 的已验证身份读取有界诊断。
- 新增 `tests/unit/test_os_supervisor_cpu_journal.py`：验证签名正确、CAS 先落盘、正常启动同代不重复、失联后不重启、服务重建仍认原 InvocationID、停止仅 UNKNOWN/HOLD、伪造 Agent/签名/任意命令无法启动。原已有各工作流和 Windows 便携合同保留。
- 扩展原 `tests/integration/test_os_supervisor_cpu_systemd_live.py`：在**隔离 Github Ubuntu systemd 实机**上真正串联短时签名 grant→独立 SQLite journal 登记→原子 claim→固定 CPU system service→跨 Supervisor service 对象恢复原 OS identity→固定 unit stop→保持 UNKNOWN/HOLD→阻止再次启动。复用已有一个 Linux E2E step，不新增 workflow，不需要非生产 GPU 硬件。
- **严格限制与后续**：本阶段仅固定 CPU-only 内置测试程序，签发与启动间是短 TTL 授权而非无限期中央回查；正式模型转换、训练、边缘复核尚未适配，不允许根据一份过期签名或已经失联的业务执行租约启动真实计算任务。CPU-only 固定测试通过后还必须完成真实 stop descendant/cgroup 证据、结束码/长期日志、可信 StopReceipt 及中央 CAS 恢复准入。不能让 Agent 看到 CPU trial 能力就参与生产调度，生产 `legacy` 默认、`REMOTE_AGENT_STOP_UNVERIFIED` HOLD/自动派单 OFF/NO-GO 不变。
- **前端**：不改。以后仅在既有 `static/modules/service-node-runtime.js` 与任务详情新增真实可靠的只读系统执行状态；不增加强制停止证明绕过、强制释放 GPU 或提前重新分配按钮。

### 14.1 阶段 2B 精确代码 SHA 与真实 Linux 进程纵向 E2E 终态（2026-11-15）

**功能提交**：[da73e07175073a9919207d6cb3093bba198c9b55](https://github.com/jorsamj/aixunlianpingtai/commit/da73e07175073a9919207d6cb3093bba198c9b55)（注意它不是后续独立文档提交）。

**CI 完整核实**：
- [Node Agent Executor 43693050737](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43693050737) 已 **completed/success**，Ubuntu **547 passed / 2 skipped**，POSIX SIGKILL **2 passed**，Linux cgroup 合同 **31 passed**；**隔离 Ubuntu 24.04 真 systemd 测试 2 passed**（第一条为固定 CPU unit 真启停，第二条为原 signed grant → journal PREPARED/STARTING/RUNNING CAS → 真 systemd → 重启重接管原 InvocationID → 单次运行/stop HOLD），不是模拟 backend，也未在 A800/4070 运行。Windows **544 passed / 5 skipped**，便携 cgroup **30 passed / 1 skipped**，API **success**。
- 同 SHA [Node Agent Executor 43693054981](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43693054981) 与 [Portable Deployment 43693055055](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43693055055) 均 **completed/success**；Portable Deployment 的 Ubuntu transport、Windows transport、API 三项都成功，说明 opt-in CPU backend 未破坏 legacy 发布路径。
- 同 SHA 其余仓库级 Actions 在此轮核实为 **23 项中 19 success、4 in_progress、0 failure**，因此只宣称以上本专项核心工作流全绿，**不宣称全仓 23/23 都已终态**。

**交付的实际能力**：
1. 固定 CPU worker 系统级 systemd service 真启动/真 stop/短诊断日志，受限资源 profile 和独立 DynamicUser；Agent 任意 shell/可执行文件/环境/GPU/PID/unit 不可输入；
2. 原中央已签发、未过期 CPU-only grant 由原 journal 重新验签，**同任务同 attempts 先写 durable STARTING 再操作 OS**，响应丢失/服务崩溃后绝不生成第二个 unit；
3. 已验证的 systemd InvocationID/cgroup/main PID 落本地执行身份 journal，服务进程对象重建可基于原记录只读重连，固定 CPU stop 真发送给原 unit，仍显式 `UNKNOWN` / `STOP_UNVERIFIED_HOLD`，不伪造中央可信停机证明。
4. 服务默认 `legacy` 且新 root Supervisor CPU 启动必须**双 CLI 显式开关**加受信公钥和 journal；上述新代码未部署任何现有计算节点。

**下次阶段 2C 的真正缺口，按先后顺序**：a）journal challenge 过期清理与容量/频率上界；b）systemd 故障/自然完成场景中可信绑定的退出码与 cgroup 后代证据（当前退出/stop 仍 UNKNOWN/HOLD）；c）持久日志 offset/cursor 的安全读取；d）OS 已启动而 journal 还在 STARTING 的崩溃窗口只读复核（原 InvocationID/ExecStart/cgroup 证据不足则维持 UNKNOWN）；e）root 公钥/中央私钥交付和轮换；f）再考虑单一非 GPU 模型转换 Runner 隔离适配。**以上缺口不允许以“现在 CPU 可启停”替代可信 StopReceipt/中央 CAS 恢复验收。**

**前端**：没有业务必要修改，也没有本轮前端代码提交。以后只在原节点卡片/任务详情展示可验证的只读 Supervisor 运行状态；不提前提供释放 GPU/自动重派/强制声明已停按钮。

**生产保持**：A800/双4070 完全未连接、未修改；`legacy` 默认、`REMOTE_AGENT_STOP_UNVERIFIED` HOLD、自动派单 OFF、GPU 生产 NO-GO，不合并 main、不创建 Release。

## 15. 阶段 2C-1｜挑战容量治理与 InvocationID 严格日志游标（2026-11-15，待本轮 CI）

阶段 2B 已具备固定 CPU-only systemd 真启停与原 `tasks.attempt`/执行 lease 签名→独立 journal `PREPARED→STARTING→RUNNING` 的一体化隔离运行能力，但**没有**可供生产自动释放资源的可信 StopReceipt、最终退出证明或正式 Runner。阶段 2C 先处理能安全、低风险闭环的日志与请求表容量，再单独处理自然退出与崩溃时身份核验。

### 15.1 已审计问题及本子阶段修改

1. `platform_core/os_supervisor_journal.py` 原 `challenges` 仅追加不清理，Agent 可制造大量未过期记录，SQLite journal 长期膨胀；新实现每次在同一 `BEGIN IMMEDIATE` 事务中清理**仅到期 nonce**，继续保留全部 `execution_intents` 和 `cpu_unit_identities` 永久身份记录。设置未到期挑战全局 512、每节点 64、每一原任务/原 attempt 4 的软配额，达到上限明确 `*_CAPACITY_HOLD`，不回收原执行身份，不创建第二套 scheduler。对损坏 JSON 绑定 fail closed；90 秒短期 TTL 仍不改变。
2. 原 `FixedCpuSystemd.read_log` 只按 `--unit` 查询 journald，可能混入同名 systemd unit 的历史其它 InvocationID。修复为固定 CPU-only `read_log_page`：先核对原 `systemctl show` unit/InvocationID/隔离合同，再通过 `journalctl --output=json --lines=+64 --unit NAME _SYSTEMD_INVOCATION_ID=ORIGINAL` 查询；**每一条** JSON 消息还必须同时核对 `_SYSTEMD_UNIT` 和 `_SYSTEMD_INVOCATION_ID` 与 journal 保留的原值。只接受有限长度、字符集受限且无文件路径语义的 journal cursor；`--after-cursor` 仅由已验证 cursor 组成。一次返回 <= 8192 bytes、最多 64 条，过大单条消息、错误元数据、解析失败及串线日志全部 HOLD。
3. 原 Socket `read_log` 严格支持可选 `cursor` 参数（`inspect/stop` 不接受）；响应包含有界 base64、同一日志游标和 `offset_contract_available=true`，旧 `SupervisedProcessHandle.read_log()` 保留无 cursor 的兼容接口，新 `read_log_page(cursor)` 可以精确继续读取。这里的 offset 是 journald **原生 cursor**，不是业务日志磁盘字节偏移；journald 日志轮转、缺失日志或 systemd unit 被 GC 时，必须 HOLD 或返回空页，不保证任意时长保留。
4. 在原 `tests/unit/test_os_supervisor_phase1b.py`、`tests/unit/test_os_supervisor_cpu_systemd.py`、`tests/unit/test_os_supervisor_cpu_journal.py` 追加定向测试，覆盖容量限制/过期清理、同调用多代不混淆、无效游标/跨 InvocationID 或跨 unit 日志拒绝、重连后一致游标、原 `inspect/stop` 不接纳 cursor。原 `tests/integration/test_os_supervisor_cpu_systemd_live.py` 只扩展现有 Ubuntu 真 systemd E2E，**实际**校验 stdout 日志含固定 CPU 程序启动标记、原 journal cursor 与二次读取不重复，不新建相似 workflow。

### 15.2 不变更/后续必须做

- 没有增加生产 Agent 接单能力、GPU 资源访问、模型转换/训练/边缘复核 Runner 适配，也没有修改中央任务代数/租约/设备 reservation。
- **本子阶段不承诺自然退出码/可信 StopReceipt**：原 systemd transient service 在进程自然退出后可能被立即 GC；若 unit/InvocationID/cgroup/后代核验不完整，只能 UNKNOWN/HOLD。下一子阶段 2C-2 应在隔离 Linux 下验证真实自然退出、子孙进程空组、系统运行身份/ExecMainCode/ExecMainStatus 的同代持久性，再决定能否有条件登记固定 CPU 的 EXITED（不等于生产 GPU 停机证明）。
- `STARTING` 在 journal CAS 已写入、但 systemd 已启动却尚未写入 `InvocationID` 时的故障窗口，仍**不得**自动二次启动；可读回查方案需在独立根身份核验完整后再开放。
- 生产根公钥/中央私钥轮换、业务 Runner、GPU 设备权限和安全停机证明仍待后续阶段/现场审批。
- 前端不修改；将来仅现有节点管理/任务详情显示只读、可信的状态和原因，不增强停/重派按钮。

### 15.3 本轮 CI 审计口径

阶段 2B 准确功能 SHA `da73e07175073a9919207d6cb3093bba198c9b55` 的 Node Agent、Portable Deployment 核心 CI 已双绿，但复核其**全部** 23 项 GitHub Actions 最终状态是 **22 successful、1 failure**：失败的 [Frontend Runtime Stabilization 43693050722](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43693050722) 属于浏览器导航分片（`createAnnotation` 事件等待 5 秒超时），而非 Node Agent 安全合同。保留明确 RED，不把前端失败美化为 23/23，也不为此在本阶段修改前端。
    
本轮阶段 2C-1 功能提交应以**精确新 SHA** 的 Node Agent Ubuntu/Windows/API 与 Portable Deployment 审核为准，特别是 Ubuntu 上新 journalctl 字段/游标真实测试；若未到终态，不得宣称 2C-1 通过。A800 / 双4070 从未接触，默认 `legacy`、`REMOTE_AGENT_STOP_UNVERIFIED` HOLD、远程自动派单 OFF、生产 NO-GO 保持。

### 15.4 本轮阶段 2C-1 真实 CI 首轮 RED：日志 cursor 安全校验修复

首轮功能 SHA [`84875c548a9870e56b1cfd6554d5f77eb96dae75`](https://github.com/jorsamj/aixunlianpingtai/commit/84875c548a9870e56b1cfd6554d5f77eb96dae75) 对应 [Node Agent Executor 43694497312](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43694497312) 的 Ubuntu 合同 **556 passed / 2 skipped / 3 failed**；API Job 成功。三个失败均是新增日志游标安全测试：原校验 `[A-Za-z0-9=;:._+/-]` 仍允许 `../secrets`、`--no-pager` 等不该出现的游标（第三项为 Socket 传入相同问题）。这是拒绝条件遗漏，不是生产发生越权。**禁止简单删除安全测试。**

本轮定点修复 `platform_core/os_supervisor_cpu_systemd.py` 与 `platform_core/os_supervisor_protocol.py` 的同一个 cursor allowlist：仅接纳以 journald 的 `s=` 起始、长度有界、不可含 `/` 或任意 shell/path-like 前缀的 `s=[A-Za-z0-9=;:._+-]{1,510}` 字符串；保留 `--after-cursor=` 作为固定命令单一参数，继续按原 `InvocationID` 验每条日志。**修复提交和新精确 SHA 的 Ubuntu 实际 journald E2E 仍须通过后方可宣称此子阶段 GREEN。**

### 15.5 阶段 2C-1 定点修复后的准确跨平台 CI 结果（2026-11-15）

**最终功能 SHA**：[`40bc388adc05ba3be05a7b986c0c89b1e3d0e423`](https://github.com/jorsamj/aixunlianpingtai/commit/40bc388adc05ba3be05a7b986c0c89b1e3d0e423)。[Node Agent Executor run 43694652044](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43694652044) 已 **completed/success**，Ubuntu、Windows、API **三个 Job 全成功**：

- Ubuntu 主合同 **559 passed / 2 skipped**，POSIX SIGKILL **2 passed**，Linux cgroup **31 passed**，隔离 Ubuntu 真实 systemd + journald E2E **2 passed**；其中 log E2E 确认能读取固定 CPU worker 的原 InvocationID 日志，取得有效 cursor 并从该 cursor 继续读取而不重复旧条目。
- Windows 主合同 **556 passed / 5 skipped**，可移植 cgroup 合同 **30 passed / 1 skipped**。
- API：**success**。此前拒绝 `../secrets`、`--no-pager` 的新增安全测试保留并成功。

**结论**：阶段 2C-1 的挑战表有界治理、按同一 systemd InvocationID 的日志读写隔离、有界 journald cursor 及跨平台核心回归已通过；**不是**全阶段 2C 完成，也不是生产系统停机证据。日志游标属于原生 journald cursor，日志留存仍由目标机 journald 配置决定，无法保证永久存在；过期或无法核验则 HOLD。

同代码 SHA [Portable Deployment 43694657038](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43694657038) 与另一轮 Node Agent [43694657064](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43694657064) 在记录此节时未最终完成，不能宣称所有仓库 23 项 Actions 终态成功。后续必须核对这些 Job，必要时再补终态证据。

**下一子阶段 2C-2**：只在隔离 Linux 上设计固定 CPU 的自然完成（包含 cgroup/后代完整退出、同一 InvocationID、ExecMainCode/ExecMainStatus/Result）与其持久终态记录；任何 OS 证据缺失、transient unit 被 GC、崩溃后仅剩 STARTING 时返回 UNKNOWN/HOLD，不能凭 leader exit 或 systemctl ACK 签发可信 StopReceipt。生产密钥轮换/模型转换 Runner 是再后一阶段，不与本轮安全修复混在一起。

### 15.6 同一 SHA Portable Deployment 正式验收（2026-11-15）

阶段 2C-1 **准确功能 SHA** `40bc388adc05ba3be05a7b986c0c89b1e3d0e423` 对应 [Portable Deployment run 43694657038](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43694657038) 已 **completed/success**，Ubuntu transport、Windows transport、API 三个 Job **全部成功**。与 [Node Agent Executor run 43694652044](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43694652044) 的 Ubuntu/Windows/API 核心全绿一致，**阶段 2C-1 核心代码和兼容路径可验收为 GREEN**；不得据此宣称阶段 2C 完成、StopReceipt 已可信或正式 GPU Runner 可运行。同 SHA 其它非核心工作流如未终态，以其实际结果为准。


## 16. 阶段 2C-2｜固定 CPU-only 自然退出终态与持久记录（代码已提交，CI 待终态）

- 2C-1 基线：`40bc388adc05ba3be05a7b986c0c89b1e3d0e423`；当时的 23 次 CI workflow 执行均 SUCCESS，**不能替代新的 2C-2 同 SHA 验收**。
- 新功能提交：[`6511cba9ca4e9d8a5f4ab5c2fa371ac04d6ce35f`](https://github.com/jorsamj/aixunlianpingtai/commit/6511cba9ca4e9d8a5f4ab5c2fa371ac04d6ce35f)。随后补齐旧 systemd 单元测试假的属性：[`f121d9bdee6f2fc3b5e918dc73bc6a15a3f5bc3b`](https://github.com/jorsamj/aixunlianpingtai/commit/f121d9bdee6f2fc3b5e918dc73bc6a15a3f5bc3b)。
- 实际变更：仅固定 CPU 测试后端采用 systemd `ExitType=cgroup`、`RemainAfterExit=yes`、`Restart=no`，核查同一 InvocationID、原 ExecMainPID、终态及退出码；`ExecutionJournal` 原子记录不可覆写的 CPU-only 终态；`SupervisorService.inspect` 在证据完全满足时才报告 `EXITED`，否则继续 `UNKNOWN/HOLD`。
- **这不是可信 StopReceipt**：CPU-only 终态报告始终 `trusted_stop_receipt_available=false`，不触发中央重新派单、不释放 GPU reservation、不迁移任何正式转换/训练/复核 Runner。
- CPU-only 测试配置使用 systemd `ExitType=cgroup`（依赖 systemd 250+）；GitHub 24.04 的验证不能自动外推到 A800/4070 Ubuntu 22.04 systemd 环境，禁止以此提交部署生产或启用 `supervisor-required`。
- **2C-2 核心验收：GREEN（准确代码 SHA `f121d9bd`）。** Node Agent [run 43706279911](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43706279911)：Ubuntu 主合同 563 passed/2 skipped，Linux SIGKILL 2 passed、cgroup 31 passed、真 systemd 生命周期 3 passed；Windows 主合同 560 passed/5 skipped、可移植 cgroup 30 passed/1 skipped；API 24 passed。Portable Deployment [run 43706279826](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43706279826)：Ubuntu/Windows/API 3 Job 成功。首轮 `6511cba9` 缺少测试模拟属性导致 RED，已由 `f121d9bd` 修正，**不将旧 RED 归因为系统级启动失败**。
- **仓库级验收不能误报全绿**：同 SHA Frontend Runtime Stabilization [run 43706274712](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43706274712) 首轮 browser-navigation (1) 发生历史 Annotorious `createAnnotation` 5 秒超时，分片 130/131 PASS；其它 3 个前端 Job 均成功。已提交该失败 Job 的针对性重跑请求，最终是否通过必须再次核实，不能修改 Supervisor 逻辑替前端修绿。
- 下一步：如 CI 失败，先按原始日志定点修复；全部满足后记录真实 Job 终态，再单独研究 `STARTING` 崩溃窗口和更强 OS 退出/停机证明、密钥分发及一个非 GPU 真实模型转换 Runner 灰度适配。

完整实施细节：[`P0_01C_SUPERVISOR_STAGE2C2_CPU_TERMINAL_2026_11_15.md`](P0_01C_SUPERVISOR_STAGE2C2_CPU_TERMINAL_2026_11_15.md)。


## 17. 阶段 2C-3｜STARTING 崩溃窗口原 OS unit 身份重连（2026-11-15，代码提交与核心验收）

- 先对上一轮 2C-2 **精确代码 SHA `f121d9bdee6f2fc3b5e918dc73bc6a15a3f5bc3b`** 重新核实：GitHub 该 SHA 全部 **23/23 workflow runs SUCCESS**。原 Frontend Runtime Stabilization [43706274712](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43706274712) 的失败 browser-navigation Job 在 **attempt 2** 定向重跑通过，不再把上一轮标记为 pending。
- 本轮开发提交：[`8d3140d1c91e26f18d26c0668c2f3e1ae7c2f5da`](https://github.com/jorsamj/aixunlianpingtai/commit/8d3140d1c91e26f18d26c0668c2f3e1ae7c2f5da)。仅调整原 Supervisor journal 的 STARTING 原 unit 查询、同 OS 身份幂等写入、inspect 中安全回查，并增加模拟/真实 Linux E2E；**没有新增任务 owner/attempt/队列或 Agent 可控 shell**。
- 正确行为：仅原 boot、原 handle+task attempt、原本已执行 `PREPARED→STARTING` CAS 的固定 CPU unit 可被查询；要求真实 systemd `Transient=yes`、`ExitType=cgroup`、`Restart=no`、`NRestarts=0`、现存 RUNNING 服务、匹配原 unit 的 cgroup、`ExecMainPID==MainPID` 等 OS 保护证据；随后复用既有 journal 事务，将同一 `InvocationID` 记录为 RUNNING；绝不再次调用 `systemd-run`。
- 错误行为仍 HOLD：缺 OS 服务、boot 已变、原记录已经 UNKNOWN/EXITED、保护配置不一致、OS PID 不可信、OS 单元被清理、进程自然退出发生在原身份未写入之前；后续阶段才能单独考虑这些难场景。
- 保证并发幂等：若首次 launch 路径和崩溃恢复 inspect 同时保存**相同** OS 身份，原 journal 接受同证据重复请求且不增加 `event_seq`；身份不一致则拒绝，不再引入“明明已经回查成功但正常 start 返回异常又标记 UNKNOWN”的竞争副作用。
- 新准确 SHA 的 [Node Agent Executor push 43708219773](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43708219773)：Ubuntu 主合同 **565 passed / 2 skipped**、POSIX SIGKILL **2 passed**、cgroup **31 passed**、真实 systemd E2E **4 passed**；这些 Job 已成功。**Windows、另一轮 Node Agent、Portable Deployment 和其它全仓 CI 必须以确切完成结果补录，不能提前全绿。**
- A800/4070、正式 GPU训练/转换/边缘复核仍旧 `legacy`，`supervisor-required` 下无正式执行 Runner；不能发布 StopReceipt，不能重派旧任务/解锁 GPU reservation。

完整细节：[`P0_01C_SUPERVISOR_STAGE2C3_STARTING_REATTACH_2026_11_15.md`](P0_01C_SUPERVISOR_STAGE2C3_STARTING_REATTACH_2026_11_15.md)。


### 17.1 阶段 2C-3 准确代码 SHA GitHub CI 最终终态（2026-11-15）

- **代码 SHA**：[`8d3140d1c91e26f18d26c0668c2f3e1ae7c2f5da`](https://github.com/jorsamj/aixunlianpingtai/commit/8d3140d1c91e26f18d26c0668c2f3e1ae7c2f5da)；**23 次 Actions workflow runs 全部 completed/success（23/23）**，无失败、取消或待执行。
- [Node Agent Executor push run 43708219773](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43708219773) 与 [PR run 43708221724](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43708221724) 均 completed/success。push Ubuntu 主合同 **565 passed/2 skipped**，SIGKILL **2 passed**，cgroup **31 passed**，固定 CPU **真实 Linux systemd E2E 4 passed**；Windows / API 成功。
- [Portable Deployment run 43708221554](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43708221554) Ubuntu/Windows/API 成功；[Frontend Runtime Stabilization run 43708219738](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43708219738) 第 1 次运行直接 success（4/4 Job），没有沿用 2C-2 之前的前端 RED 状态。
- **本次仅验收 fixed CPU-only original-STARTING os unit reattachment；不等于真实 GPU StopReceipt、自动跨节点恢复、正式模型转换/训练/推理 Runner 接线。** Windows CI 仅验证可移植合同；真实 systemd 只在隔离 Ubuntu 24.04 运行。生产 A800/双4070 没有变更。

**下次专项建议**：先只读审计 CPU-only 失败/终态路径剩余边界、systemd Ubuntu 22.04 兼容差异和正式 Runner 适配合同，再选一个非 GPU 转换 Runner 的隔离集成切片。不要一次性改中央调度器、GPU reservation 或现有生产部署模式。
