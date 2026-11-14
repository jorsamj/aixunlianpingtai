# 畅联云算法训练平台｜P0-01B / P0-01C 远程 Agent 失联后可信恢复与上线准入

更新：2026-11-14 · 范围：开发分支 `feature/external-algorithm-publishing`
状态：**P0-01B 安全修复已提交、最新 CI 未验收；P0-01C 可信停止确认协议待开发；生产 NO-GO。**

## 1. 背景、风险与已采取的止损措施

中央服务节点派发任务使用唯一的 Durable TaskRepository / FencedTaskRepository、中央任务分配、assignment lease、execution lease、attempt/generation、HTTP Node Agent 与服务端验证结果上传。

问题：`worker_id=agent:<node-id>` 的远端执行租约过期，**只能证明旧执行代不能继续对中央平台合法写入，不能证明旧服务器上的计算进程停止**。例如：双向网络分区、操作系统冻结、GPU 作业继续执行但中心收不到心跳。若直接 `RUNNING -> QUEUED`，可能在另一节点启动同一训练，引发 GPU 资源争用、成本上升、重复计算。即使旧 token/generation 被拒绝，它仍可能消耗 GPU。

P0-01B 当前止损（开发分支 HEAD 首次引入于 `a007f4c`、`6694c7c`、`8065c53`，完整开发基线记录于 issue #26）：
- 对原 owner 为 `agent:%` 的已过期 `RUNNING/CANCEL_REQUESTED`：不因 TTL 自动转成 `QUEUED/CANCELLED`；标记 `recovery_blocked_remote_agent_unverified` 和 `REMOTE_AGENT_STOP_UNVERIFIED`，保留 owner、attempt、执行令牌。
- 保留 GPU reservation / 同资源键保护；中央自动分配和普通 Worker 抢占路径都不得绕过；本地 Worker 维持已有 ProcessController PID / create_time / command_hash 查验与恢复逻辑。
- 旧 generation 的 heartbeat / finish / result publication 仍由既有租约+代数拒绝，不新增第二调度 owner。
- 代价：远端失联任务可能长期处在受阻态。这是有意识的 fail-closed 行为，不是“任务自动恢复已完成”。

**测试状态**：此前双 `node_agent.py` OS 进程、真实 loopback HTTP、SIGKILL、HTTP 503、模拟 OSS 正向结果回传，在历史开发提交各自 GREEN；本次改变恢复语义的 HEAD `d2b69ddc44bbb82ceb14a3d841593946393bf4a3` 截至本页撰写时对应 23 个 Actions 仍全部 queued，**不得引用历史 GREEN 冒充本次验收**。

## 2. 现有证据能力只读审计

| 位置 | 已存在能力 | 局限 |
| --- | --- | --- |
| `platform_core/node_agent_executor_runtime.py` | 任务+generation 作用域的持久 `process-identity.json`，PID/create_time/command_hash，安全路径校验 | 文件不存在不能证明过去未启动子进程 |
| `platform_core/node_agent_training_runtime.py` | 训练启动记录进程身份；Agent 启动时尝试精确终止遗留训练子进程；失败则 `recovery_error` 阻止就绪 | 启动→身份落盘有时间窗；不能从中央 SQLite 直接核实远端 PID |
| `platform_core/node_agent_conversion_runtime.py` | 模型转换同样采用本地持久进程身份和恢复清理 | 上述时间窗和跨机器证明问题仍存在 |
| `platform_core/node_agent_deployment_runtime.py` | 运行期间以内存身份结束本地子进程树；网络心跳失败时 fail-closed | 不能将进程内状态或重新上报心跳当作跨重启可信死亡证据 |
| `platform_core/node_agent_executor_loop.py` | 单 Agent 执行循环一次一个任务；拒绝能力不匹配；正常停机调用 runner shutdown | 不证明硬重启、进程冻结、失联时所有执行子进程都结束 |
| `platform_core/agent_execution.py` | Node Token、assignment lease / execution lease / generation fencing、结果确认 | 鉴权令牌证明节点身份；不等价于进程不存在的证明 |

特别禁止把 **`reported_active_tasks=[]`、节点 `ONLINE`、执行租约到期、进程身份记录缺失、Agent 构建号变化** 当成独立充分的停止证据。

## 3. P0-01C 最小可信恢复协议（提案；未实现）

不增加新 Scheduler、新任务类型、Agent 直接连接中心 SQLite、新数据库集群或全量页面重构。

1. **任务保持**：当任务处于 `recovery_blocked_remote_agent_unverified` 时，任何现有普通 claim、自动分配、取消终态、通用 retry API 都不得绕开 hold。
2. **证明生成**：原节点通过受控 Agent recovery 动作，对指定 `task_id + attempt/generation`、精确进程身份进行停止检查/必要的本地进程树终止。失败、权限不足、PID 身份不一致、记录不完整或无法覆盖所有潜在子进程时必须 **UNKNOWN/REJECT**；不得根据空列表认定已停止。该动作仍需覆盖“先 spawn 后 identity persist”窗口（优先先持久化启动意图、专属进程组/作业容器身份、启动器守护等成熟方案，代码审计后选最小实现）。
3. **证明绑定**：中心应签发短有效期一次性 challenge；由经过 Node Token 认证的**原节点**提交 task_id、attempt、worker_id、node_id、agent boot/session identity、目标进程身份/进程组或容器、核验结果、核验时间、证明摘要。仅 Node Token + 心跳 + `active_tasks=[]` 不构成足够证据；需要可信执行边界或运维独立确认。
4. **中心原子校验**：`BEGIN IMMEDIATE` 中重新核对：原任务仍 `RUNNING/CANCEL_REQUESTED` 且 hold stage，原 worker_id、attempt、token、节点 identity 与凭证证据完全一致，旧租约已经过期；无并发重连 heartbeat / 取消 / 上传终态胜出；challenge 一次性消费并留审计。
5. **恢复提交**：仅证明有效时原子解除 hold，`RUNNING -> QUEUED` 或 `CANCEL_REQUESTED -> CANCELLED`，清理旧令牌与原 GPU reservation，保留历史 attempt / result evidence / 恢复决策记录；下一次 start 才发新 execution generation。不要重用旧 token。必要时由运维双人确认后释放，而不是提供无审计的“强制重新派发”快捷入口。
6. **不可证明时**：维持 HOLD，提供只读诊断（节点、代数、失联时刻、最近 heartbeat、受阻原因、可用恢复方式），只接受严格受控的管理员/基础设施级确认流程。**UI 不要将此状态显示为普通排队中或永久“取消中”而没有原因**。

## 4. 需要覆盖的 RED → GREEN 场景

- 远端 Agent 网络分区但 GPU 子进程仍在：TTL、心跳过期不能重派，不能释放 GPU 证据，重复释放调用必须幂等。
- 两个节点竞争同一任务/资源键、普通 TaskRepository vs FencedTaskRepository、delegated GPU admission：任何路径都不能突破 hold。
- 旧 generation heartbeat / finish / signed upload：旧 token 不得写入，旧 generation 不能覆盖新结果。
- 原节点重连但恢复证据缺失/伪造、Node Token 轮换、challenge 过期、错误 task_id/generation/node_id：必须拒绝；仅 `active_tasks=[]` 必须拒绝。
- 正常停机、强制 SIGKILL、子进程悬挂、PID 重用、CreateTime 或 command hash 不匹配、启动-落盘竞争、进程检查权限不足：未证明停止不得释放。
- 原任务 `CANCEL_REQUESTED`，与 old heartbeat、新 stop proof、新 result upload 同时到达：只能一个合法终态、不能“取消中”静默丢失。
- 原节点经可信 cleanup 证明停止后：唯一一次 DB 原子解除，generation + 1 才能在下次新 start；重复证明提交不得导致二次恢复。
- 模型训练、转换、推理、素材处理按各 runner 的进程隔离能力分别准入，不允许仅凭训练 runner 有 PID 记录便为其他 runner 自动开通可信恢复。
- Linux/Windows CI 契约、真实 HTTP/双 OS Agent 隔离测试以及独立多主机长任务+断网实测；生产仍需明确授权。

## 5. 开发顺序和完成定义

**Gate A（当前）**：本次 `d2b69dd` 精确 HEAD 的 CI 尤其 `Task Runtime Truth` / `Node Agent Executor` / `Agent Two Node Loopback HTTP Integration` 必须完成且全绿；任何失败先定位，不以新文档 SHA 的历史 CI 冒充验证。GitHub Actions 若持续排队，需排查仓库 Actions 配额、Runner 可用性、排队限制或 GitHub 事件，不能先改生产。

**Gate B**：只为已具备可信停止证据的训练/转换执行器增加恢复证明合同；先验证对跨节点/跨代 token 和进程身份的负面测试，基于原有 HTTP Router、Node Token、SQLite 权威任务库小范围实现。不要在业务入口堆叠新代码。

**Gate C**：结合剩余执行器逐类扩展，补 UI 受阻态只读诊断/必要的明确人工授权工作流，验证 OSS/真实 GPU 和长任务跨物理机断连。

**生产约束**：A800、双 4070 不部署、不重启、不修改生产数据或配置；`CHANGLIAN_AGENT_AUTO_ASSIGN_ON_CLAIM` 继续 OFF。未通过所有硬门槛之前为 **NO-GO**。

## 6. 追踪

- [GitHub issue #26](https://github.com/jorsamj/aixunlianpingtai/issues/26)：相关提交、RED/CI、隔离测试证据与 GO/NO-GO。
- 唯一开发分支：`feature/external-algorithm-publishing`。
- 本文为专项审计与设计准入记录，**不表示 P0-01C 可信证明协议已编码、上线或验收**。
