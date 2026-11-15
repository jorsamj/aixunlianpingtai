# 畅联云算法训练平台｜P0-01C-3B Linux StopReceipt 信任边界与真实内核→中央挑战隔离验证

**编写日期**：2026-11-15  
**工作分支**：`feature/external-algorithm-publishing`  
**安全状态**：HOLD、自动派单 OFF、生产 NO-GO。**任何阶段的 PoC 成功都不允许自动释放真实 owner/GPU reservation。**

## 1. 当前为什么还不能接生产

真实 Linux GitHub-hosted Ubuntu 22.04 临时虚拟机已经证明：`KillMode=control-group` 下，即使 Agent 启动器被 SIGKILL，仍可停止本试验的三层、跨 session CPU 计算进程，并在原 `cgroup.events` 文件回收前得到 `populated=1→0` 事件；`boot_id`、systemd `InvocationID` 和测试用 generation 已绑定。该证据来自**同一 PoC 控制进程/用户**，不是独立签发并保护私钥的 OS 证明服务。

另外，P0-01C-3A 的 **41 项 Ubuntu + 41 项 Windows 内存 SQLite 合同**已经通过，验证挑战过期、一次消费、防重放、旧任务代数、GPU reservation、事务回滚，但“独立 OS witness”是测试内 HMAC 模拟器，不能证明真实进程死亡。

**两个环节都通过，不等于两环节连起来就安全**：原 Agent 有可能撒谎、篡改日志或在 stop 前迁出计算进程。因此先验证真实内核观测、一次性挑战和中央事务的端到端时序，再独立建立真实 witness 的权限、密钥和信任根。

## 2. 对现有正式 Runner 只读核查

已核实以下现有代码，未修改业务运行路径：

| 实际位置 | 已有能力 | 尚缺 |
|---|---|---|
| `platform_core/node_agent_executor_runtime.py` | `begin_process_launch` 在训练/转换启动前持久 `process-launch-intent.json`、目录 fsync；`persist_process_identity` 保存 PID/create_time/command_hash；损坏身份不允许清理 | 没有独立、受保护的 systemd unit/cgroup 和停机证明签发服务 |
| `platform_core/node_agent_training_runtime.py` | Trainer 真正 `launch_process` 前先写 intent，之后写 exact identity；持久失败会阻止继续 | 原 PID/进程树控制不是受保护的所有子孙整组停机 proof |
| `platform_core/node_agent_conversion_runtime.py` | 转换 worker 也采用启动前 intent、启动后进程身份落盘 | 与训练共享 GPU/节点时，须证明所有潜在计算后代都停下 |
| `platform_core/task_runtime/fenced_repository.py` | 远程租约到期仍 `recovery_blocked_remote_agent_unverified`，保留原 owner 和 GPU reservation | 暂无经过授权的原子解除 HOLD 协议 |
| `platform_core/agent_execution.py` | 中央 `tasks.attempt`、execution lease token 和 `BEGIN IMMEDIATE` 执行归属真相 | 缺停机前挑战、可信独立见证和持久恢复审核 |

**设计原则**：使用现有 **`tasks.attempt`** 而不是 `task_node_assignments.generation` 作为真实执行代数；不另造任务队列或 Agent owner。

## 3. 本轮已提交的测试专用桥接

本轮仅新增/调整 `tools/poc` 和独立 CI，不接 Web/API/训练/转换 Worker：

- `tools/poc/linux_cgroup_poc.py`：增加**测试专用** `before_stop` hook 和可传入的 synthetic task/generation；只有真实三层后代已绑定且 Agent 启动器已模拟崩溃、unit 身份仍一致，才允许调用中央挑战模拟器；随后才调用 `systemctl --user stop`。增加停机前原 cgroup 的可读 `populated=1` 事件，以及`stop_requested_ns` / `empty_observed_ns` 的真实单调时间顺序检查，拒绝在 stop 命令前出现的空组事件冒充本次停止。
- `tools/poc/linux_stop_receipt_bridge.py`：仅在 **GitHub-hosted Ubuntu 临时 VM**、非 root、明确 `--run --isolated-test-host` 时执行；先创建 **SQLite `:memory:` 的 HOLD 任务**，保留旧 lease/owner/GPU reservation；在真实 cgroup 仍 `populated=1` 时按同一 boot/InvocationID/cgroup/代数签发一次性 challenge；执行真实 stop；验证观察记录后用**测试专用 HMAC（与控制器同一进程）**模拟见证；中央 `BEGIN IMMEDIATE` 在 **仅内存 SQLite** 中完成 CAS；再证明相同 challenge 的二次提交被拒绝。输出始终包含 `trusted_os_witness_implemented=false` 和 `production_recovery_allowed=false`。
- `tests/unit/test_linux_stop_receipt_bridge_contract.py`：验证缺失 stop 证据、错误的原始绑定、generation/boot/InvocationID/cgroup 不符、布尔伪造、空组发生于 stop 请求之前、无先前存活记录、模拟私钥不同不能验签、非 GitHub 环境及默认 CLI 必须拒绝。
- `.github/workflows/agent-kernel-stop-poc.yml`：新增 GitHub-hosted Ubuntu 22.04 的桥接真实内核测试步骤，同时保留原 2B 单独 systemd stop 步骤和独立证据附件。
- 本轮真实内核桥接 run：[GitHub Actions 43672300351](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43672300351)。**最终 CI 已核实 SUCCESS（71/71 单元合同 + 真实 OS 停机 + 模拟中央事务）**；上一轮 [43672197474](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43672197474) 为 70 passed /1 failed：仅因非 GitHub 拒绝路径缺少 `production_recovery_allowed=false` 字段，真实 kernel 步骤未执行。已精准修复拒绝路径，不放宽 stop/identity 断言，不能把上一轮当作真实内核失败或成功。

### 3.1 这一步能验证 / 不能验证

**能验证**：在隔离的真实 Linux 内核内发生实际三层进程 stop，再用**停机前已经签发的挑战**与真实发生的时间顺序进行整合，最终在测试 SQLite 中检查一次性恢复事务的完整路径。

**不能验证**：同进程 HMAC 私钥不受普通 Agent 控制；恶意 Agent 绝对不能迁出 cgroup；物理 GPU/多节点 OS 隔离；真实中央数据库 Schema/API；trusted StopReceipt 的生产可验来源。即使桥接输出 PASS，仍然是**隔离模拟集成成功、生产 NO-GO**。

## 4. 真实可信 StopReceipt 的建议架构（尚未开发）

```text
中央调度：tasks.attempt / 原 lease / HOLD / GPU reservation
       │
       ├── 中央签发限时一次性 challenge（绑定任务和已登记 OS 边界）
       │
       ▼
节点本地独立 OS Execution Supervisor（不同于普通非特权 Agent）
       ├── 只允许管理已登记的 unit/cgroup（禁止任意 kill PID/unit）
       ├── 在 START 之前持久化身份与启动边界
       ├── 直接从受保护 OS API 观测 unit / boot / InvocationID / cgroup
       ├── 钉住 cgroup.events FD，并在停止前订阅内核事件
       ├── 核对全部已知进程及历史发起/迁移风险
       ├── systemd stop + 收集完整非僵尸子孙空组事件
       └── 通过受保护的节点私钥签署包含 challenge nonce 的 StopReceipt
                        │
                        ▼
中央可信根验证（独立于普通 Agent JSON 和 Node Token）
       ├── 绑定 challenge、task_id、tasks.attempt、node_id、lease_digest
       ├── boot_id / InvocationID / OS boundary ID / 停机原因与时序
       ├── 验签、证书/公钥注册/撤销、设备身份和时间窗校验
       └── BEGIN IMMEDIATE 中再次核对 owner/status/租约/GPU reservation
                        │
                        ▼
                仅核验通过才恢复任务；否则原样 HOLD
```

### 4.1 信任根与部署风险

- 普通 Node Agent 的 bearer token 仅证明其“作为哪个节点请求”，**不能证明 OS 子进程不存在**。单靠同进程 HMAC、agent 自报列表或单个 PID 消失也不能形成独立证据。
- 正式应由**与 Agent 不同权限域**的受保护 Supervisor 管理每次训练/转换的专用 unit/cgroup、停机及签名。Supervisor 的密钥不得出现在普通 Agent 环境变量、工作目录、命令行或用户可读文件；鉴权用短期挑战、原节点身份、公钥注册/轮换/撤销和不可重放审计。仅“服务运行在 root”也不够：需防止普通 Agent 借 `sudo`、systemd 用户总线、cgroup delegation 或共享写权限绕开它。
- systemd 的 `Delegate=` 允许某些单元管理其自身 cgroup 子树；是否允许目标服务迁出/创建新 unit 需要独立安全审计，不能仅观察原 cgroup 空了就推断全宿主机无残留。参照 [systemd cgroup delegation](https://systemd.io/CONTROL_GROUP_INTERFACE/)。
- Linux cgroup v2 `cgroup.events populated=0` 描述原 cgroup **及子层级**没有非僵尸进程，不证明其他 cgroup、其他 host 或 GPU 上绝无仍执行的任务。参照 [Linux kernel cgroup v2](https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html)。
- systemd `INVOCATION_ID` 是每次 unit runtime cycle 的身份，用于防同名 unit 复用，但不是签名或可信密钥。参照 [systemd.exec](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html)。
- 在 GitHub-hosted Runner 中，测试账户通常有本机 sudo 权限，**即使另启动 root signer，也不能宣称抵抗拥有 sudo 的恶意 Agent**。真实隔离强度必须在未来的专用受限运行账户/OS 权限模型上另行验收。

## 5. 下一个最小专项及验收闸口

1. 先拿到 **43672300351** 精确 SHA 的 CI 结果，核对 portable contracts、真实 2B stop、3B bridge、核验二次挑战拒绝；若失败定位日志，禁止把错误改成伪绿。
2. 继续在**独立** VM/容器测试 OS Supervisor 权限域、密钥隔离/签发面，先实现不能用于生产的受限 test witness，并覆盖 agent 更换 unit、跨代挑战、cgroup 迁移、OS reboot 和发证中断等反例。
3. 只有 3B 独立可信证据来源通过后，才可进入 P0-01C-3C 正式中央 API/持久 challenge/audit 附属表（默认 OFF），必须在真实 `FencedTaskRepository` 的短事务内 compare-and-swap，继续保留旧 owner/GPU reservation 的安全保护。
4. 最终准入：真实物理 GPU/Ultralytics DataLoader 多进程、双节点网络分区、Windows Job Object、资源回收及回滚。**未经用户明确批准，不部署或重启 A800、4070，不操作生产数据库或任务。**

## 6. 2026-11-15 GitHub-hosted 真实内核端到端隔离联调最终证据

**准确代码 SHA** `341b2f73998bbd0db68cdeca72e6f1700ea26406`；[GitHub Actions run 43672300351](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43672300351) **completed SUCCESS**，Job `linux-cgroup-22` 成功，没有失败步骤。

| 真实 CI 阶段 | 运行结果 |
|---|---|
| 旧 31 项 + 新接桥负面合同 | **71 passed in 0.17s** |
| 非 root Ubuntu 22.04 / systemd user manager / cgroup v2 | PASS |
| 原有三层跨独立 session 的真实 systemd stop | PASS；`cgroup_empty_verified=true`、`identity_binding_verified=true` |
| 绑定挑战后真实内核 cgroup stop → 中央内存 SQLite | PASS |
| 同一挑战重复提交 | **`challenge_replay_rejected=true`** |
| 模拟原子恢复 | **`simulated_central_recovery_committed=true`**；只有内存库任务发生 QUEUED |
| 真正独立且受保护的操作系统见证 | **`trusted_os_witness_implemented=false`** |
| 允许生产恢复 | **`production_recovery_allowed=false`** |

实际桥接输出：`kernel_stop_outcome=LOCAL_CGROUP_POC_PASS_NOT_CENTRAL_STOP_PROOF`，`outcome=REAL_KERNEL_TO_MEMORY_CAS_SIMULATION_PASS_NOT_TRUSTED_STOP_PROOF`。原始 `p001c3b-kernel-to-central.json`、`p001c2b-kernel-result.json`、预检 JSON 统一保存在该 Run 的 **`p001c2b-ubuntu22-cpu-evidence`** 工件中；GitHub 默认保留 14 天。

**可作出的有限结论**：真实 Linux cgroup 空组事件、指定执行实例身份和停机前挑战**可以**按顺序连接到中央现有任务代数概念与模拟 SQLite 事务。这显著降低了方案可行性的不确定性，但**不是签名见证者可信、恶意 Agent 无法迁移进程、真实 GPU/多机已验收的证明**。

**生产准入仍保持 NO-GO**。下一专项 P0-01C-3B-2 应优先在隔离 VM 中检验**不同权限域的 OS supervisor / 完整启动前身份登记 / 私钥不暴露给普通 Agent**，并核对 Agent 是否可通过 systemd 用户总线或 cgroup delegation 跳出边界；若无法证实不可迁移则继续 HOLD。不要提前做开放恢复的生产 API。
