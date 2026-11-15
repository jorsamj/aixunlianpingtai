# 畅联云算法训练平台｜P0-01C 独立 Supervisor 进度、问题、下一步与新会话交接

**交接日期**：2026-11-15  
**仓库**：https://github.com/jorsamj/aixunlianpingtai  
**唯一允许开发、提交和推送的分支**：`feature/external-algorithm-publishing`  
**本次只读核查的远端 HEAD**：`2584367c55cba24da8507b5fb2518d09eed6003f`（文档提交后需以新分支 HEAD 为准）。  
**总状态**：**Supervisor 阶段 1A 代码已写入、GitHub CI 未验收、生产 NO-GO**。此处“已提交”**不等于**“业务功能可用”，更不等于“可信 StopReceipt 可用于重排”。

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
