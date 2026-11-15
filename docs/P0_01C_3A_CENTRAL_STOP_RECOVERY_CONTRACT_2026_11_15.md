# 畅联云算法训练平台｜P0-01C-3A 中央停机挑战与恢复事务隔离合同（2026-11-15）

> **项目安全状态：生产 NO-GO / 自动派单 OFF / REMOTE_AGENT_STOP_UNVERIFIED HOLD 保留。**
>
> 本文件记录已经提交的可执行**纯模拟协议**和测试结果，不应被描述成已实现生产中的“可信停止证明”或安全自动重排。测试库必须是 SQLite `:memory:`，不得访问或修改 A800、双 4070、真实训练/转换任务、模型、OSS、GPU 预留或生产数据库。

## 一、背景及中央现有所有权

已在既有中央代码中只读核实：

- `tasks.attempt` 是**真正的 execution generation**，`platform_core/agent_execution.py` 在成功的 `QUEUED -> RUNNING` 事务中将其加一；真实 Agent 执行租约收到该 generation 和 lease token。
- `task_node_assignments.generation` 只是**分配代数**，不能替代 `tasks.attempt`，也不能构造第二个任务 owner。
- 远程 Agent 租约过期、旧计算可能仍运行时，`FencedTaskRepository` 将原任务置入 `recovery_blocked_remote_agent_unverified`，保留 `worker_id`、`lease_token`、`attempt` 和 GPU reservation；已有逻辑不允许 TTL 到期后直接自动重排。
- P0-01C-2 Linux CPU-only systemd/cgroup PoC 已在 GitHub-hosted Ubuntu 22.04 验证多层进程停止、原 cgroup `populated=0` 事件、`boot_id / InvocationID / synthetic generation` 绑定。**该局部内核结果不构成中央可信证明。**

因此，此次**不新建另一套调度系统**；仅验证未来中央恢复所需的一次性挑战、校验边界和原子恢复事务。临时 challenge/audit 是**协议元数据**，不是新的执行代数或任务队列。

## 二、本轮已提交的独立代码

| 文件 | 用途 | 生产导入 |
|---|---|---|
| `tools/poc/central_stop_recovery_contract.py` | 在内存 SQLite 中演示一次性挑战、严格身份复核、模拟独立 OS 见证、CAS 恢复、GPU reservation 和审计写入同一事务 | **否** |
| `tests/unit/test_central_stop_recovery_contract_poc.py` | 负面/正面合同：旧代数、防重放、过期、签名篡改、所有权竞态、事务失败回滚 | **否** |
| `.github/workflows/central-stop-recovery-isolated.yml` | 只在 GitHub-hosted Ubuntu 22.04 和 Windows 上运行上述独立合同；权限 `contents: read`，无生产连接 | **否** |

独立源码提交 `a2ef6048c42aafee8b1abc6f36648e86042ff63f`；测试提交 `37af8c9ceac8d473c0044f365feafa65227ab2cc`；CI 工作流提交 `1714ba852abb29f3f767357197976c6e91a9385c`。

## 三、协议应如何工作（模拟合约，不是可调用 API）

```text
中央已有任务（tasks.attempt = g，原 agent:node，租约已过期）
                  |
           继续保持 HOLD
                  |
        原节点经认证申请一次性挑战
                  |
     中央事务核对 task_id + attempt(g)
     + worker_id + lease_token + HOLD
     + lease 已过期 + GPU owner
                  |
     持久 challenge_id + nonce_hash
     + 原执行代数 / OS 边界实例
                  |
       独立 OS 停机见证 [尚未实现]
       确认原 cgroup 空组及已知进程停止
                  |
        中央验证见证与一次性挑战
                  |
       BEGIN IMMEDIATE（同一事务）
          + challenge 未过期/未消费
          + 原 worker/token/attempt 未变
          + task 状态仍 RUNNING/CANCEL_REQUESTED + HOLD
          + 仍为原 GPU reservation owner
                  |
          + 消费 challenge、写审计
          + 清理原 GPU reservation
          + RUNNING -> QUEUED
          或 CANCEL_REQUESTED -> CANCELLED
          + 清理旧 lease/worker/process identity
                  |
                 COMMIT
```

- 任务恢复为 `QUEUED` 时，**`tasks.attempt` 不在恢复事务中增加**；只有真正下一次成功执行 `QUEUED -> RUNNING` 时才按既有逻辑增加。
- 模拟数据库使用真实平台字段名的子集（`tasks.attempt`、`worker_id`、`lease_token` 等），但这是**独立内存测试结构，并非真实数据库迁移、真实生产方法或真实恢复入口**。
- 任一核对不通过时 rollback，原 `HOLD`、旧租约/代数、GPU reservation 均保持原样；挑战不能重放、不能跨代复用。
- 未来的正式实现必须经原节点 Node Token 认证、真实 OS 执行边界记录、独立可信见证校验后才会进入恢复事务；**本 PoC 当前没有实现这些生产准入能力**。

## 四、模拟见证的边界及为什么不能现在上线

测试里有一个单独的 HMAC 签名模拟器，它可以验证“证据内容没有被修改，挑战 ID 和代数与签名内容一致”。但 HMAC 签名**不能独立证明 GPU/CPU 上的计算已经停止**。若见证密钥仅存在于普通 Agent 或被其控制的进程中，即使加签，也不能把 Agent 的自我声明当作 OS 事实。

本阶段的 `test_only_sign_witness` / `test_only_witness_verifier` **只能用于测试**，绝不构成生产可信证明的实现。正式准入仍欠缺：

1. systemd/cgroup（或平台可信特权执行边界）自身持久、受保护、与任务执行代数绑定的启动与停止证据。
2. 中央下发的短时一次性 challenge，绑定已注册且未变的原节点执行实例、原 Node Token 身份和 boot/session ID。
3. 见证信任根、密钥轮换、时钟/重放防护、错代证据拒绝与原节点不可靠/失联时的处理。
4. 在真实中央任务 SQLite 中的迁移、审计、锁争用及原子恢复 API 的专门实现与测试。
5. GPU 与数据加载子进程、节点物理失联/重启、多服务器争用等端到端 UAT。

**不允许**仅把模拟见证替换成 `agent_reported_stop=true`、`active_tasks=[]`、PID 不存在或 `cgroup` 路径消失后直接开放恢复。

## 五、已执行自动化与证据

- 专用 [GitHub Actions run 43670649572](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43670649572)，准确代码 SHA `1714ba852abb29f3f767357197976c6e91a9385c`。
- **Ubuntu 22.04：41/41 通过**（从 `isolated-transaction (ubuntu-22.04)` Job 原始日志核实）。
- **Windows：本文件首次写入时仍排队**；如后续得到终态，必须用同一准确 SHA 的 Job 结果核验，不得先称跨平台全绿。
- 主要负例：伪造/缺失独立见证、挑战过期、重复消费、篡改 nonce、任务/Node/boot/InvocationID/旧代数错配、错误 GPU reservation owner、原任务已换代/换 token/变状态、非法布尔或时序、事务审计插入异常导致的原子 rollback。
- 专门的硬阻断：`_memory_only()` 检查 SQLite `PRAGMA database_list`，**任何文件型 SQLite 数据库均被拒绝**；测试还覆盖了文件型数据库不能进入这套逻辑。
- **不能**把这 41 项隔离测试的通过等同于生产 Agent 安全恢复已验收。

## 六、下一阶段：P0-01C-3B / 3C 的正确顺序

**3B 先解决可信 OS 证据来源**：设计正式 Linux Agent 的 ExecutionBoundary（启动意图落盘、专属 systemd unit / cgroup、generation、boot、InvocationID）以及受保护的 StopReceipt 接口；不得信任普通 Node Agent 自我声明。先独立可审计验证，不动生产路径。

**3C 再接中央恢复事务**：复用 `tasks.attempt` 和现有单一中央 SQLite repository，将 challenge/audit 元数据作为必要附属表（不是任务队列），实现原节点鉴权、proof verify、CAS 原子解除、GPU reservation、审计与旧写入 fencing。先封闭默认 OFF，经多节点、网络分区、重复投递和 Windows/GPU UAT 后再考虑受控启用。

任何真实生产 A800/双4070 服务、数据库、模型、作业、重启及资源变更必须另行取得明确授权。**现阶段仍是 NO-GO。**
