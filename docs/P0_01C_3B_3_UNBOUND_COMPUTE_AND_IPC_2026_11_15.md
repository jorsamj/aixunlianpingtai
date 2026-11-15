# P0-01C-3B-3｜非受控 CPU 进程反例与 Supervisor Unix Socket 鉴权

**2026-11-15**｜唯一开发分支：`feature/external-algorithm-publishing`｜**生产 NO-GO**

> 本专项只有 GitHub-hosted Ubuntu 22.04 虚拟机 CPU 实验。**从头到尾未调用生产中央恢复接口，不读取/修改 A800、双4070 的任何程序、服务或数据，也没有真实 GPU 控制权。** GitHub VM 的测试账户和模拟 challenge 均不是生产节点认证/签名配置。

## 一、背景：为什么前一轮 OS Supervisor 实验还不能放行

P0-01C-3B-2 的实际成功证据：根用户管理的 systemd SYSTEM unit、独立的普通 Agent UID、独立的 workload UID、root-only Ed25519 私钥。受测 Agent 不能在实验权限模型中停止该 system unit、读取密钥、直接操作异 UID 进程，workload 不能向父级 cgroup 迁移。但 **`cgroup.events populated=0` 只证明原 cgroup 子树空了**；Agent 是否可以从 unit 外直接新建另一份 GPU 计算任务，前轮没测。

本轮必须明确区分两个不同安全性质：

- **原执行边界内的全部进程已停止**：systemd stop 和完整 `cgroup.events`/进程身份可以局部验证；
- **节点上不能存在原执行的未授权后代或额外计算**：需设备权限、创建新进程的管控和原任务授权映射；即使前者成立，后者也不能自动成立。

## 二、测试一：unbound CPU 负面反例（越界进程存活是预期结果）

在 GitHub-hosted Ubuntu VM 中，root 为随机 ID 创建临时的 systemd SYSTEM `clpoc-<24hex>.service`，用非特权 workload UID 运行一个受管理 CPU 进程。**另一无 sudo 的 Agent UID** 在这个 unit **外**直接调用 Python，运行一个独立的 CPU sleep（不需要越权迁移现有进程）。验证其真实 `/proc/<pid>` UID、PID 启动 ticks、cgroup 身份以及仍活着的状态。

root 通过 `systemctl --system stop` 停止受管理 unit，并从预打开的原 `cgroup.events` 句柄读取 `populated=0`，核实已知受管理进程结束。此时若另一份未绑定 CPU 计算仍存在，程序输出 **`unbound_cpu_spawn_possible=true`、`unbound_cpu_survived_controlled_stop=true`**，结论应为**成功发现安全反例**，而不是解除 HOLD。结束时只清理本次随机创建的单元、测试进程和临时系统账户。

**这个 CPU 反例不能替代 GPU 检查**。GitHub VM 通常没有可按生产方式验证的 NVIDIA/昇腾 GPU 设备，故**本轮无法证明 GPU 设备 ACL、cgroup devices BPF 或驱动访问授权有效**。后续仍需独立 GPU 测试或经批准的只读/实验窗口。

## 三、测试二：root Supervisor Unix Socket / SO_PEERCRED

- 在 root 管理的随机临时目录建立 `AF_UNIX/SOCK_STREAM`；通过 `SO_PEERCRED` 由内核返回对端 PID/UID/GID，**不采信 JSON 中自报的 uid**。
- socket 文件 `root:<agent_gid>`、模式 `0660`，拒绝另一个 workload UID 连接。额外**暂时将 socket chmod 0666**，验证即便文件访问控制放宽，受限服务仍能通过 **`SO_PEERCRED` 拒绝错 UID**，随后恢复 `0660`。
- 测试服务只暴露 `request_stop_admission`，它是**模拟准入检查**：仅接受预登记的 `task_id + execution_generation + unit + boot_id + InvocationID + challenge_id + nonce`，强制严格正整数 generation、限时和一次性消费；拒绝跨任务、跨代、改 unit、替换 nonce、重复提交、任意方法/执行命令和额外字段。
- **不暴露 `systemctl stop`、`kill`、shell 命令或签名 API，不产生 StopReceipt，不接正式 Node Agent。** 即使 Agent 获得 `ok=true`，也仅表示“本次准入模拟检查成功”，不是 OS 停机证明。
- root-only 临时文件位于 `0700` 私有目录、模式 `0600`，Agent 和 workload 均不能读取；密钥不上传 CI artifacts。

## 四、实际文件与测试

| 路径 | 内容 |
|---|---|
| `tools/poc/linux_supervisor_ipc_probe.py` | 只在显式 `--run --github-ephemeral-only` + GitHub-hosted Ubuntu VM + root 测试权限下执行；用户及 systemd unit 全为随机临时对象 |
| `tools/poc/test_linux_supervisor_ipc_probe_contract.py` | 纯合同：凭证类型、错代/跨节点身份、过期挑战、白名单、真实 SO_PEERCRED 本地读取、默认 CLI 不执行、非 VM 拒绝 |
| `.github/workflows/linux-supervisor-privilege-probe.yml` | 保留前一轮 3B-2 系统权限反例，再追加 3B-3 Socket + unbound CPU 真实实验；仍严格 `runs-on: ubuntu-22.04` GitHub-hosted，`contents:read` |
| `docs/P0_01C_3B_3_UNBOUND_COMPUTE_AND_IPC_2026_11_15.md` | 本文：实际证据、风险及接续闸口 |

**待核实 CI**：[GitHub Actions run 43674713650](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43674713650)，精确触发源码 SHA `c303a9c164d8ca8068a3237dc31350c74bf27577`；本文件初次创建时该运行仍在 GitHub 队列中，**不得提前宣称通过**。

### 验收与失败分级

- Contract test 通过：证明守卫逻辑基本符合预期；不证明跨 UID 实际被隔离。
- 实际 Unix socket/权限测试通过：证明该 GitHub VM 中对应 UID 对 socket 的攻击尝试被 OS/服务拒绝。
- 受控 unit 停止且 unbound CPU 仍在执行：证明**仅凭原 cgroup 空组不足以判定节点无其他计算**；这是重要的发现，而不是安全失败或放行条件。
- 任一 unit PID/InvocationID 身份变化、unbound PID 类型不匹配、stop 无真实 cgroup 空组事件、受控 Agent 的错误权限或 IPC 错代重放未被拒绝：实验 **HOLD**，保留日志，先查根因，不为 CI 绿灯直接取消断言。
- 任一 test PASS 的程序化结果始终标注 `real_stop_proof_implemented=false`、`production_recovery_allowed=false`。

## 五、下一步：真正的最小生产适配路径（仍待审计/授权）

1. **检查当前部署环境的真实权限模型**（尚未核实）：A800/4070 Node Agent 服务用户、sudoers/polkit、user systemd manager、GPU 设备访问和可创建新进程的能力；未经授权不得读取/更改生产服务器。
2. **设计受保护 Supervisor 的启动前注册与受限 IPC**：真实中央下发的 `tasks.attempt`、lease/node、boot/InvocationID/专属 cgroup；同一受保护进程完成启动、停机、原 cgroup 事件采集与不可伪造的 StopReceipt 签发。
3. **防止原 Agent 绕过受控进程**：GPU 访问必须受约束，且任何未登记的进程不能冒用原任务身份。需按实际 NVIDIA/Ascend/ARM/Windows 设备与安全策略分别验收；不能以 CPU-only GitHub VM 代替真实 GPU UAT。
4. 只有可信 OS 见证和权限/重启/网络分区 UAT 满足条件，才考虑 P0-01C-3C 中央真实 API、附属 challenge/audit 元数据及持久事务；默认 OFF，不替换旧 `tasks.attempt`。
5. **生产继续 `REMOTE_AGENT_STOP_UNVERIFIED` HOLD、原 worker/lease/GPU reservation 保留、自动派单 OFF、NO-GO**。
