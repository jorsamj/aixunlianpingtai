# 畅联云算法训练平台｜P0-01C Supervisor 新会话接续执行提示词（2026-11-15）

> 复制下方“提示词正文”到一个新 ChatGPT 会话。新会话必须实际核查 GitHub 最新状态，不能机械沿用此文档的历史 SHA 或 CI 结论。

---

## 提示词正文

你现在接续开发我的**畅联云算法训练平台**，担任资深 Python/FastAPI、Linux systemd/cgroup、OS 进程管理、分布式调度、GPU 资源管理和安全审计工程师。

**GitHub 仓库**：https://github.com/jorsamj/aixunlianpingtai  
**唯一允许开发/提交/推送的长期分支**：`feature/external-algorithm-publishing`。不能合并 main、创建 Release、强推或写入其它分支。

**首先必须打开并通读**：
1. `docs/P0_01C_SUPERVISOR_STAGE1A_HANDOFF_AND_NEXT_STEPS_2026_11_15.md`（最权威的当前接续文档，含真实 CI 问题、进度、风险和实施步骤）。
2. `docs/P0_01C_SUPERVISOR_INCREMENTAL_IMPLEMENTATION_PLAN_2026_11_15.md`（已确定的渐进方案，不得随意大重构）。
3. `docs/P0_01C_SUPERVISOR_PHASE1_TRANSPORT_2026_11_15.md`（阶段 1A Socket 和进程句柄实现）。
4. `docs/P0_01C_REMOTE_AGENT_TRUSTED_STOP_HANDOFF_2026_11_15.md`（长期背景与历史验收，尤其末尾 20–23 节）。
5. [GitHub Issue #26](https://github.com/jorsamj/aixunlianpingtai/issues/26)。

**最新一次已核查的分支基线**：在编写这份提示词前，已核对 HEAD `bbc5c6f4c3c5888c1efa39011d8cd451d2ab11e7`（交接文件自身的提交）；**你开始前必须重新读取远端分支 HEAD**，不要假设它仍是当前 HEAD。

### 当前项目技术状态

目标是在不改变中央任务所有权的前提下，逐步引入受保护的**独立 Linux OS Supervisor**，管理 Node Agent 的训练、模型转换、边缘模型复核进程；防止 Agent 宕机/网络中断后旧 GPU 子孙进程未停而中央错误重新派单。中央继续以 `tasks.attempt` 为真实 execution generation，保留原 worker/lease/GPU reservation。Supervisor 只管理 OS 进程边界，不再新建第二套调度系统。

**之前已做的**：Linux systemd/cgroup 停机实验、独立 UID 和 Unix Socket `SO_PEERCRED` 安全隔离实验、一次性挑战 + in-memory SQLite CAS 模拟、未受控进程反例、模拟 DAC；真实业务代码已有 `CHANGLIAN_AGENT_EXECUTION_BOUNDARY` 迁移开关。默认 `legacy` 不变；`supervisor-required` 目前只能阻断 TRAINING/MODEL_CONVERSION/DEPLOYMENT_TEST 的旧直启路径，**不能正常运行受保护的真实计算**。

**阶段 1A 已提交**：`platform_core/os_supervisor_protocol.py`、`platform_core/os_supervisor_service.py`、`tests/unit/test_os_supervisor_phase1.py`，复用 `.github/workflows/node-agent-executor.yml`。其功能是版本化、本机身份双向核验的独立 Socket 服务及 `SupervisedProcessHandle` 合同；**没有实际 systemd 启动/停机、root-only 长期密钥、可信 grant、持久 OS journal、StopReceipt、中央真实恢复 API**。

### 你必须按以下顺序实际执行

**第一步：真实 GitHub 基线与 CI 审计（先做）**

- 重新读取唯一长期分支 HEAD、上面所有关键源文件和工作流；获取精确 run SHA、状态、Job 和失败日志。
- 特别核查 [Node Agent 43684001227](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43684001227)（阶段 1A、代码 SHA `2ab61ce6fe6d6c8a09e5fc8d9723672d92c5f5f8`），本次最后核对仍 queued；以及 [43679484571](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43679484571)，本次已 **completed/failure**：Ubuntu 成功、Windows 因 POSIX-only `os.getsid` 失败、API 因过时 grep guard 失败（主体 Windows 473 passed/2 skipped，API 24 passed）。**不能宣称已经通过**。
- [43679203190](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43679203190) 实际已 `completed/failure`：Windows 的 Linux 专项单测 `tests/unit/test_linux_cgroup_poc_contract.py:226` 调用 `os.getsid` 导致 AttributeError；API Job 中旧 `grep 'reported_capabilities = executable_agent_capabilities(requested_capabilities)'` 已与 `node_agent.py` 的 `allowed_remote_capabilities(...)` 新写法冲突。
- 新核实的阶段 1A 协议/测试矛盾：`os_supervisor_protocol.py` 对 start 空 payload 抛 `START_NOT_IMPLEMENTED`，但 `os_supervisor_service.py` 想返回 `PROTECTED_LAUNCH_NOT_IMPLEMENTED_HOLD`，`test_os_supervisor_phase1.py` 也要求后者。请复现、统一拒绝语义、保持所有实际启动动作关闭。**不可通过放开任意命令或启动后端来修测试。**
- 只做最小修复：POSIX-only 用例明确按平台分流或跳过、API guard 更新为验证新能力过滤代码、修 start 协议与服务端拒绝码不一致。保留原有安全防线和测试，不要删掉失败用例。
- 复用现有 CI，在准确提交 SHA 上确认 Ubuntu/Windows/API 状态；只记录**实际完成**的验收，排队/未运行必须继续标记 pending。

**第二步：阶段 1B（必须在阶段 1A 通过后）**

- 在不碰三个正式 Runner 的前提下，定义受保护 Supervisor 的可信中央授权合同，绑定 `task_id+tasks.attempt+worker/node+原 lease digest+boot_id+GPU UUID+challenge/nonce+有效期`。仅凭 Agent 自报字段或者 `SO_PEERCRED` 不能批准启动；不能将长期签名密钥放在普通 Agent 可读路径。
- 增加本机**持久化 OS 执行 journal/handle** 最小实现：启动前写入、原 execution generation 与 OS unit 身份固定、重复 start 幂等、回复丢失不可另起同代计算、服务重启身份不明必须 UNKNOWN/HOLD；不创建第二套中央任务队列。
- 尽量使用主流 systemd/Linux 正规机制，维持小模块和少量必要回归。阶段 1B 不开放真实 GPU 启动，也不接生产中央自动恢复。

**第三步：阶段 2 以后（按文档渐进，不要跨阶段）**

- 在隔离 Linux 托管环境实现固定 CPU worker 的真正可用 start/status/exit code/log offset/stop/restart 接口；一次性完整端到端验收。
- 随后**模型转换 → 训练 → 边缘模型复核**分别迁移，每次只动一个 Runner；绝对不能把 Socket JSON 冒充 `subprocess.Popen`，也不能让普通 Agent 的 `ProcessController` 去杀受不同 UID 管理的 Supervisor 进程。
- 真正 GPU device ACL、CUDA/Ascend/RKNN、可信 StopReceipt 与中央 CAS 恢复只有取得实机授权和完成硬件 UAT 后才考虑。不要因为 CPU/文件权限模拟实验成功就认为 A800/4070 具备可运行的生产安全边界。

### 严格安全与工作方式

- **不授权**访问/部署/重启真实 A800、双4070；不动真实 GPU、训练任务、生产数据/数据库、GPU reservation，不改生产 Node Agent 配置；涉及现场只读核查也要先取得我明确许可。
- `REMOTE_AGENT_STOP_UNVERIFIED` HOLD、旧 owner/lease/`tasks.attempt`、GPU reservation、自动派单 OFF、生产 NO-GO **始终保留**。严禁任何模拟 StopReceipt 直接解除 HOLD 或重排。
- **不要大重构**：不把功能堆在 `app.py`，不重写中央调度，尽量遵循原有模块化规范；旧 `legacy` 默认兼容。阶段 1B 不必改前端。
- **减少重复测试**：只做必要定向单测/合同 + 已有工作流验证。GitHub push 可能触发多项 unrelated 工作流，不要为“测试数量”不断重复提交。
- 每阶段执行前先确认真实根因、改动范围及回退，实施后**写清提交 SHA、准确 CI run/Job、已完成/未完成、风险和下一步**；同步 `docs/P0_01C_SUPERVISOR_STAGE1A_HANDOFF_AND_NEXT_STEPS_2026_11_15.md`、长期交接文档与 Issue #26。
- 不要让我重复已经交代过的信息，能独立完成的 GitHub 代码和文档工作直接完成；若无法获得足够证据，保持 HOLD 并明确缺失证据，**不要假称已完成**。

**你现在先执行“第一步：阶段 1A CI 基线收尾”，发现问题直接精准修复、记录并推送到唯一长期分支；确认验收后再决定是否进入阶段 1B。请先告诉我本次真实核查结论，然后继续工作。**
