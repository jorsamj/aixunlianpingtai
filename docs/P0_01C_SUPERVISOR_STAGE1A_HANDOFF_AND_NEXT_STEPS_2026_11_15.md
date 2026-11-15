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
