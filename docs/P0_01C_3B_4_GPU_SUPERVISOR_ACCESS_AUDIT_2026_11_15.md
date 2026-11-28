# P0-01C-3B-4｜GPU 设备访问控制与可信 Supervisor 正式适配前置审计

**日期**：2026-11-15  
**仓库/唯一允许开发分支**：`jorsamj/aixunlianpingtai` / `feature/external-algorithm-publishing`  
**安全结论**：生产继续 `REMOTE_AGENT_STOP_UNVERIFIED` HOLD、原 worker/lease/`tasks.attempt`/GPU reservation 不释放；自动派单 OFF；A800/双4070 生产 NO-GO。

> 本阶段只审计 GitHub 源码、设计最小合同和在 GitHub-hosted CPU 虚拟机中演示**普通文件**权限。未访问生产宿主机、未操作任何真实 GPU、CUDA/Ascend 驱动、真实数据库或任务。静态审计成功不等于生产安全，文件 DAC 模拟成功也不等于 GPU 权限隔离成功。

## 一、代码只读审计：为什么直接上线 Supervisor 有风险

| 已核对源码 | 现有真实行为 | 与可信 OS 停机的差距 |
|---|---|---|
| `platform_core/node_agent_training_runtime.py` | `begin_process_launch(lease)` 后直接通过 `launch_process(command, cwd=self.runtime_root, env={...os.environ...})` 启动训练；记录 process identity，并检查 selected CUDA device、GPU UUID 和资源快照 | 进程由普通 Agent 的宿主机权限直接创建，**未强制经过受保护 Supervisor**；任务 lease 与 GPU UUID 是调度/资源一致性，不是 OS GPU 权限授予 |
| `platform_core/node_agent_conversion_runtime.py` | 转换任务相同：持久启动意图后直接 `launch_process`，传递 Agent 的环境与预期任务参数 | 包含 GPU/SDK 依赖时，存在与训练同类的未受监管进程启动边界；并非所有转换都必然用 GPU，需按目标 SDK 区分 |
| `platform_core/task_runtime/process_control.py` | POSIX `start_new_session=True`，Windows `CREATE_NEW_PROCESS_GROUP`，依靠 PID/create time/hash 和进程组/树清理 | 这些都不等同于由**不同权限域**持有的 systemd unit/cgroup 或 Windows Job Object，更不能单凭它们签发中央可信 StopReceipt |
| `platform_core/gpu_reservations_v2.py` | 用 `gpu_reservations` 和 worker/node/GPU UUID 保存调度预留；任务状态变更时由事务/trigger 协调 | 逻辑 reservation 不能拒绝同一节点的另一个本地进程直接打开 `/dev/nvidia*`、`/dev/dri/*` 等设备 |
| `platform_core/node_agent_runtime.py` 和 `platform_core/training_devices.py` | Agent 直接通过 `nvidia-smi` 查询 GPU/进程，部分路径用 torch 子进程检查已指派 GPU 的 CUDA 可用性 | 将来若用 OS DAC/设备策略严格限制 Agent 本身的 GPU 权限，**现有健康探测和资源准入可能被影响**；必须提供受保护 Supervisor/遥测代理的只读替代，不能简单收紧权限导致任务全部排队 |
| `node_agent.py` | Agent 持续启动 `NodeAgentExecutorLoop` 并获取调度/心跳 | 仍无真实 Supervisor 适配器；本阶段不得在生产入口加入 PoC 的 root/SO_PEERCRED 代码 |
| `tools/install_rockchip_agent.sh` | 瑞芯微板端的 systemd 安装脚本允许显式 `User=...`，不是 NVIDIA A800/4070 的通用生产部署实况 | 不能依据这个脚本假定 A800/4070 生产 Agent 已正确限制 sudo、polkit 或 GPU 设备 ACL |

**审计核心判断**：系统有很好的中央任务代数、逻辑 GPU reservation、持久化进程身份，但**尚未形成“普通 Agent 无法绕过受保护 Supervisor 直接使用目标 GPU”的操作系统级强制边界**。这是欠缺的能力，不等于已证明存在生产越权攻击。

## 二、本轮实际交付的自动化合同

本轮新增：

1. `tools/poc/gpu_supervisor_gate_audit.py`：只使用 `ast.parse` 读取源码，不 import 正式平台、不启动训练/转换、不访问数据库/GPU；核查两类 Runner 的直接 `launch_process`、进程身份持久化、环境继承和调度资源能力，明确输出 `DIRECT_GPU_CAPABLE_LAUNCH_BYPASSES_SUPERVISOR_HOLD`、`production_supervisor_enforced=false`、`gpu_runtime_isolation_verified=false`。源代码路径变化时输出 `CODE_PATH_CHANGED_REQUIRES_REAUDIT_HOLD` 而不是冒充安全通过。
2. `tests/unit/test_gpu_supervisor_gate_audit.py`：在真实仓库 AST 上验证上述已知缺口，并通过**纯模拟、不可放行生产的**合同核对 `task_id + tasks.attempt (execution_generation) + worker/node + lease_token_hash + GPU UUID + boot_id + InvocationID + unit/cgroup + challenge_id + nonce`；对错代数、bool/数字类型混淆、错 worker/node/GPU、缺任何 OS 控制标记等做 fail-closed 测试。即使所有模拟标记为 true，也始终返回 `production_gpu_launch_allowed=false`。
3. `.github/workflows/gpu-supervisor-source-audit.yml`：GitHub-hosted Ubuntu 22.04 + Windows 双环境，仅运行静态核查/合同，无 GPU/生产依赖。**CI 绿色只表明准确识别当前差距，绝不表明 GPU 设备隔离已实现。**
4. `tools/poc/gpu_device_acl_shadow_probe.py` 和 `tools/poc/test_gpu_device_acl_shadow_probe.py`：独立 root 限定的 GitHub-hosted Ubuntu 试验，**只创建普通临时文件，不创建真实设备节点、不启动 CUDA**。两个不同普通 UID 中，root 将普通文件授予 workload 专用 group（模式 0660），Agent 读取应拒绝、workload 应成功；临时改为 0666 后 Agent 可以读取，恢复 0660 后又应被拒绝。该结果只能说明 Linux 普通文件 DAC 的边界，**不能证明 NVIDIA/UVM/Ascend 的设备权限可用或能被隔离**。
5. 以上文件均在 `tools/poc`、`tests/unit`、隔离 CI 和 docs 范围；没有修改正式 `node_agent.py`、Training/Conversion Runner、中央调度或生产数据库。

**CI 对应的精确代码 SHA 和最终结果**：
- 源码/模拟合同（Ubuntu/Windows）：[run 43677681674](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43677681674)，触发 SHA `6279609597b77a8f395dc6e71a468c706eba0d29`。初次记录时 Ubuntu **65/65 PASS**，Windows 尚在 GitHub 队列；必须逐 Job 核实。
- 临时文件 DAC 权限（GitHub Ubuntu root 沙盒）：[run 43677832627](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43677832627)，触发 SHA `a82d6df04fb41add9930ccc2bac106deba86041b`。**CI 实际 completed SUCCESS，全部 59 项测试通过**；真实 Linux 权限模拟结果见第 2.1 节。若失败按日志定位，不能降低拒绝条件。


### 2.1 真实 GitHub-hosted Ubuntu 22.04 模拟 DAC 最终证据

专用 [run 43677832627](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43677832627)，准确代码 SHA `a82d6df04fb41add9930ccc2bac106deba86041b`，**completed SUCCESS**；全部历史 Supervisor/SO_PEERCRED/新文件 DAC 合同 **`59 passed in 0.40s`**，三个隔离 OS 实测阶段均 SUCCESS。

特别是本轮新增输出：
- `fake_device_acl_separation_verified=true`：**普通临时文件** root owner + workload 专用组 + 0660 权限时，非 root Agent UID 被拒绝、独立 workload UID 被允许。
- `fake_world_access_bypass_observed=true`：对同一**模拟普通文件**放宽到 0666 后，普通 Agent UID 可以打开；恢复 0660 后，`restored_agent_denial_verified=true`。
- `actual_cuda_or_gpu_device_tested=false`、`actual_ascend_or_rockchip_device_tested=false`、`production_gpu_isolation_verified=false`、`production_recovery_allowed=false`。
- 最终 `outcome=FAKE_FILE_DAC_COUNTEREXAMPLE_PASS_REAL_GPU_NOT_VERIFIED`；它不是对生产 `/dev/nvidia*` 的授权审计、不能证明 CUDA context 被拒绝，也不表示可释放中央任务的 GPU reservation。

**结论仅限文件 DAC**：该实验说明“UID 分离 + 正确的文件 DAC”这一控制有效，也说明“账户分离但模拟设备节点可被任意用户读取”会失去这个控制。真正 NVIDIA/昇腾设备是否具有相同权限语义及阻断效果，必须在实际硬件上另行实测。

## 三、建议的正式架构：最小化而非重构

**坚持原中央真相**：`tasks.attempt` 是 execution generation，`task_node_assignments.generation` 仅是分配代数；继续使用原有 lease token、worker/node 身份和 GPU reservation。Supervisor 增加的是**OS 执行控制与可信停机证明**，不是第二套调度器。

```text
中央：task_id / tasks.attempt / GPU reservation / 原 worker+lease
         │
         ▼
普通 Node Agent（非 root；不得有任意 CUDA/转换 GPU 启动权限）
         │ 提交指定操作 request，不得自选任意 shell/PID/unit
         ▼
受保护的 OS Supervisor：固定 allowlist 的受保护 Unix Socket
    SO_PEERCRED + challenge/lease + 真实系统启动前注册
         ├── 受控 launcher（训练/转换固定入口、精确参数/数据目录）
         ├── OS 持有专属 unit/cgroup + 运行用户 / 设备访问授权
         ├── 启动前落盘 task_id/attempt/node/lease/GPU UUID/boot
         ├── 从 systemd 获取 InvocationID、控制组和受控 PID identity
         ├── 在 Worker 进入真实 GPU/SDK 之前完成受控启动身份绑定
         ├── 取消/停止时内核事件 + 已知进程 + cgroup 空组核验
         └── 受保护 signing key 签发一次性 StopReceipt（待实现）
         │
         ▼
中央独立验证（仍是同一 tasks.attempt、原 owner/lease/GPU 状态）
         └── BEGIN IMMEDIATE / CAS；证据不可信则继续 HOLD
```

**强制要求与风险**：

- 普通 Agent 不持有 root/sudo/polkit、可任意调用 systemd 的权限或能直接控制其他 UID 的进程；Supervisor 最小权限运行、严格允许的操作/参数/目录/设备白名单、不可读密钥和 OS 注册记录。
- **仅设置 `CUDA_VISIBLE_DEVICES` 或 `NVIDIA_VISIBLE_DEVICES` 环境变量不是设备访问授权**。GPU UUID/逻辑 `cuda:N` 可能受可见设备映射影响，需在 Supervisor 内比较设备真实 UUID、节点 ID 和逻辑/物理映射。
- NVIDIA GPU 可能涉及 `/dev/nvidiactl`、`/dev/nvidia-uvm*` 和 GPU-specific 节点；实际授权/隔离要根据驱动版本、NVIDIA Container Toolkit、systemd DevicePolicy/cgroup devices eBPF、udev 和容器环境综合实测，**不能照搬本实验对普通文件的 0660 规则**。昇腾和瑞芯微需要各自驱动的设备/SDK 边界，不可一套 ACL 覆盖。
- Agent 当前负责 GPU 查询/资源探测；未来切断普通 Agent 的 GPU device 权限后，需要**只读指标代理**或 Supervisor 返回设备信息，以保持统一调度自动资源配置、训练进度/显存监控、CPU/GPU 负载感知，不可破坏已有自动调度功能。
- 出于执行可信性，后续还需审计操作系统文件权限/共享目录、软链接、cwd 路径逃逸、固定 worker 命令白名单、密钥轮换、Supervisor 崩溃重启、网络分区和离线恢复。单个 root 守护进程或 Ed25519 签名本身都不是完整证明。
- Windows Job Object / Device ACL 要另做，不能将 Linux systemd 机制移植为简单 `CREATE_NEW_PROCESS_GROUP`。

## 四、下一阶段及生产门槛

**P0-01C-3B-5（先只读/离线审批）**：核实实际 A800 和 4070 的 Node Agent 安装方式、是否 root/sudo、systemd unit User/Delegate/ProtectControlGroups、`/dev/nvidia*`/UVM 设备 ACL、NVIDIA driver/container/cgroup 设备策略、既有 GPU telemetry 运行账户。**当前尚未取得服务器上实时证据；如需 SSH/运行命令，即便只读，也先获得用户对具体服务器和命令的明确授权。**

**P0-01C-3B-6（测试机/维护窗口）**：在非生产或获明确授权的维护窗口执行真实 GPU 的 Agent UID 与受控 workload UID 相互访问测试；验证原 unit 外非法 CUDA context 不能建立、合法任务能启动、DataLoader/转换子进程受控且停机后不残留。测试不得危及在线业务或抢占生产 GPU。

**P0-01C-3C（最后才考虑）**：经真实 OS Supervisor、设备访问、可信签名、中央一次性挑战、防重放、GPU 双节点故障注入通过后，才对正式平台增加默认 OFF 的中央可信恢复入口。不得用本轮静态源审计或普通文件 DAC 试验解除 HOLD。

**硬限制始终不变**：未修改真实 Runner/Agent 业务、未访问/部署/重启 A800 或 4070；不合并 main、不开 Release；自动派单 OFF、原 GPU reservation 和所有权继续保留、生产 NO-GO。
