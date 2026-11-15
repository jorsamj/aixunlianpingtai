# P0-01C-3B-2｜Linux OS Supervisor 账户/密钥/cgroup 权限隔离实测报告

**日期：2026-11-15**  
**仓库：** `jorsamj/aixunlianpingtai`  
**唯一开发分支：** `feature/external-algorithm-publishing`  
**范围：仅 GitHub-hosted Ubuntu 22.04 disposable CPU VM；未触碰 A800、双4070、生产数据库、GPU、OSS、训练及转换任务。**

## 一、结论先行

本次实验已在 GitHub-hosted Linux VM 中**通过真实 OS 权限测试**：root 管理的 systemd **system** unit 执行非特权计算进程，普通 Agent 和计算进程是不同系统 UID。非特权 Agent 无法直接停止 root-owned system unit、给计算主进程发送信号、使用 sudo 或读取 root-only Ed25519 私钥；计算进程自身无法读取该私钥，且从原 systemd unit cgroup 向父 cgroup 的实际迁移写入被拒绝。Supervisor 停机后，监听原 `cgroup.events` 证实 `populated=0`，已知计算父子进程退出，root-only 测试签名验证通过，并在**内存 SQLite** 消耗一次性挑战、完成模拟恢复，重复提交被拒绝。

**当前仅可判定：在测试 VM 中，权限划分方案对这些具体攻击尝试有效。** 无法证明恶意 Agent 在生产机器上不能绕过 Supervisor，尤其是 Agent 若仍拥有 `sudo`、GPU 设备访问、可用的 user systemd manager、可写 cgroup delegation、可创建其他 GPU workload 的能力。**禁止**因此开放真实任务自动恢复。生产 `REMOTE_AGENT_STOP_UNVERIFIED` HOLD、原 owner、`tasks.attempt`、GPU reservation、自动派单 OFF 和生产 NO-GO 全部保持。

## 二、实际源码与权限结构

| GitHub 文件 | 用途 | 是否接入业务 |
|---|---|---|
| `tools/poc/linux_supervisor_privilege_probe.py` | **必须同时指定 `--run --github-ephemeral-only`** 且硬校验 GitHub-hosted Ubuntu 22.04、root via runner sudo；在临时 VM 中创建两个随机短命 UID，root 运行 systemd `system` 服务，完成权限负面试验、Ed25519 签名及内存事务 | 否 |
| `tools/poc/test_linux_supervisor_privilege_probe_contract.py` | 纯合同测试，验证默认入口不执行、非 GitHub VM 拒绝、root-only 0600 私钥/0700 目录、签名防篡改、unit 身份重用拒绝、负面检查不被移除 | 否 |
| `.github/workflows/linux-supervisor-privilege-probe.yml` | 专属 GitHub-hosted `ubuntu-22.04`，仅 `contents:read`，Python 依赖安装在 runner 临时 venv，完成合同后执行 root-only 隔离实验 | 否 |

虚拟机内的角色和权限：

```text
GitHub-hosted disposable Ubuntu 22.04 VM
  ├─ 测试时临时 root Supervisor / systemd SYSTEM manager
  │    ├─ 随机 clpoc-<24hex>.service；User=隔离 workload UID
  │    ├─ KillMode=control-group、Delegate=no、NoNewPrivileges=yes
  │    ├─ ProtectControlGroups=yes、RestrictSUIDSGID=yes
  │    ├─ 私钥 root:root，文件 0600 / 上级目录 0700
  │    ├─ 读取原 cgroup.events 并监听实际 populated=0
  │    └─ 测试 Ed25519 签名 + memory SQLite challenge / CAS
  │
  ├─ 普通 Agent 临时 UID（与 workload UID 不同）
  │    ├─ 无 sudo / 无 root 控制系统服务的权限
  │    ├─ 不允许给其他 UID 的计算进程直接发信号
  │    └─ 不允许读取 root-only signer 私钥
  │
  └─ 计算 workload 临时 UID
       ├─ 由 root-owned SYSTEM unit 启动
       ├─ 另起独立 session 的 CPU 子进程
       ├─ 实际尝试向父层级 cgroup.procs 写 PID 被拒绝
       └─ root-only signer 私钥读取被拒绝
```

这是**系统级 unit** 而非之前普通 Agent 自己可管理的 `systemctl --user` unit，因此专门验证“Agent 无法管理 unit”这一信任边界。

## 三、真实 CI 证据

**准确运行：** [GitHub Actions run 43674027072](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43674027072)  
**代码 HEAD/SHA：** `c7be6e77ca44a241d72724e41947d624feb56f06`  
**状态：** `completed / success`，`hosted-ubuntu22-sandbox` Job 全步骤成功。

- `12 passed in 0.06s`：专用纯合同测试成功；
- 真实 `agent_denials` 为 `key_denied=true`、`signal_denied=true`、`sudo_denied=true`、`unit_stop_denied=true`；
- `workload_escape_denied=true`（实际向父 cgroup.procs 写迁移失败）；
- `workload_key_read_denied=true`；
- `systemd_boundary_verified=true`、`privilege_boundary_verified=true`；
- `systemd_stop_returncode=0`、`cgroup_empty_verified=true`、`known_processes_stopped=true`；
- `test_supervisor_signature_verified=true`：一次性测试 Ed25519 密钥签发的完整 payload 验签成功；
- `challenge_replay_denied=true`，`test_central_recovery_committed=true`：**仅 sqlite3 :memory: 模拟任务**；
- **`trusted_production_stop_receipt=false`、`production_recovery_allowed=false`**；
- 最终 `outcome=SEPARATE_UID_SUPERVISOR_ISOLATED_PASS_NOT_PRODUCTION_ATTESTATION`。

原始 JSON 可在该 Run 的 `p001c3b2-root-supervisor-isolated-evidence` 工件获取（CI 设置保存 14 天）。无密钥上传。

首次工作流 SHA `652f58a309571d8e45035ca1323e731070384769` 的 [run 43673969567](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43673969567) 由于 `runner.environment` 被错误写在 job-level env，GitHub 解析失败、未运行任何 Job；在 `c7be6e7` 将该表达式移至 step-level env 后真实执行成功。不能将首轮 YAML 失败算作 OS 安全反例失败。

## 四、尚未验证的风险与下一轮准入条件

1. **GitHub runner 的 root/sudo 不是生产硬信任根**。本试验的 Agent UID 是新建无 sudo 账户，而 GitHub runner 的管理用户仍有 sudo。若部署时普通 Node Agent 也是 root 或有 sudo/polkit 权限，则**当前隔离全部失效**；必须先审计并整改实际服务账户、sudoers、polkit、user systemd bus 和 unit delegation。
2. **当前 StopReceipt 仍是测试内 root Python 控制进程签署，不是长期独立守护进程**。尚无受保护的 Unix socket/peer credentials、最小权限 Supervisor API、中央预登记、密钥安全存储/轮换、远程公钥信任链、见证吊销或宕机重启后可恢复的持久证据。
3. **`cgroup.events populated=0` 只证明原 cgroup 子树内没有活进程**。未证实普通 Agent 不能在原 unit 之外**另起**计算程序；需要阻止 Agent/coordinator 访问真实 GPU 设备，把 GPU/模型计算能力仅授予 Supervisor 托管的 workload UID，并验证显卡占用、进程迁移、新建 user-systemd unit、多个 PID namespaces 等反例。
4. 当前只在 CPU 临时机测试了向**父 cgroup**迁移和已知父子进程停止，不是对全部 cgroup 迁移方式、GPU/CUDA 子进程、跨节点残留、权限提升和绕过机制的穷举证明。
5. 正式恢复仍要复用中央 **`tasks.attempt`**，而不是 `task_node_assignments.generation`；持久 challenge/audit 不能成为第二套任务所有权。必须经中央原节点鉴权、公钥注册、真实受保护 witness 及 `BEGIN IMMEDIATE` 事务原子验证后才允许解除 HOLD。
6. Windows Job Object 的进程组完整性证明、真实 GPU（A800/双4070）和多节点网络分区 UAT 仍未验收；任何真实生产操作必须先得到用户授权。

## 五、下一最小专项建议：P0-01C-3B-3

优先做**正式系统部署前的安全可行性审计和隔离验证**，不要马上改运行中的 Agent：

- 审计节点实际安装脚本、systemd 服务账户及权限：Agent 是否 root/sudo、是否可管理 user-systemd/cgroup、GPU /dev 节点权限如何分配。基于现有训练/转换进程 launch contract 设计最小 Supervisor API，确保 Agent 本身无法直接启动绕过 Supervisor 的 GPU 工作负载。
- 在 GitHub VM 再验证**非特权 Agent 在原 unit 外启动计算进程**是否可能，作为“cgroup 空组不能代表整个节点已无计算”的反证；为未来 GPU device ACL/cgroup device policy 提供必须落地的边界。
- 先设计 Unix socket + `SO_PEERCRED` 授权、允许的 task/generation/unit/boot/InvocationID 白名单、签名密钥隔离和崩溃恢复合同，仍仅 PoC 运行。只有全部通过后再考虑正式 Runner 适配。
- 最终需求是中央原子恢复 + 物理 GPU UAT；当前**生产 NO-GO**，不得因本报告 SUCCESS 放开。
