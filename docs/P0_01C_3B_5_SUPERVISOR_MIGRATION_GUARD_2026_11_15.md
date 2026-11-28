# P0-01C-3B-5｜Supervisor 渐进式接入：正式 Agent 准入保护与 GPU 节点只读盘点

**日期**：2026-11-15  
**唯一开发分支**：`feature/external-algorithm-publishing`  
**当前状态**：首次正式业务代码改动已提交，但 **真实 Supervisor 尚未接入**；生产仍 HOLD / 自动派单 OFF / NO-GO。当前不授权改动 A800、双 4070。

## 一、为什么从反复 PoC 转为实际开发

此前已完成：Linux 三层进程/cgroup 停机、同代/boot/InvocationID、中央 SQLite 一次性挑战模拟、分权限 root Supervisor、Unix Socket SO_PEERCRED、unit 外 CPU 进程反例、模拟文件 DAC。它们已足够指出核心问题：**当前正式训练和转换 Runner 会直接继承 Node Agent 的权限通过 `subprocess.Popen` 启动计算进程**。继续做相似 CPU 测试已经不是当前主瓶颈。

真正困难之处在于：正式训练和转换 Runner 的 `LaunchedProcess` 返回 `subprocess.Popen`，依赖其 `poll()`、`returncode`，而取消操作、日志、子进程身份和上传结果发布又依赖 `ProcessController` 与进程状态。不能不加审计地把 `launch_process` 改为 HTTP/Unix Socket 调用，或让 Agent 获得 root 代替受保护 Supervisor。

因此本轮采取**增量安全迁移，默认兼容旧行为**的最小实施：

## 二、已写入正式代码的保护

### 2.1 唯一配置

`CHANGLIAN_AGENT_EXECUTION_BOUNDARY`：

| 值 | 实际效果 |
|---|---|
| 未设置或 `legacy`（默认） | 按现有行为申领远程任务，并保留原 `launch_process`；**没有**新增可信停机证明 |
| `supervisor-required` | **不再上报 `training`、`conversion`、`conversion.rknn`、`deployment-test`、`deployment-test.rknn` 能力**，不申领这些任务；即使已有 Runner 对象被直接调用，真正 `begin_process_launch` / `launch_process` 前也会 fail-closed，绝不静默退回普通 Popen |
| 任何其他字符串 | 配置无效，必须拒绝启动；不猜测为 `legacy` |

**严禁现在对生产节点设置 `supervisor-required`**：真实 supervisor launcher/handle adapter 尚未安装，开启后远程训练和转换会被停止接单，这是预期的**安全阻断**而不是业务功能已上线。生产默认不变。

### 2.2 具体代码和影响面

- `platform_core/node_agent_supervisor_gate.py`：新增独立轻量策略模块，统一解析执行边界模式和可广告的远程计算能力，提供 `assert_direct_remote_launch_permitted()`。不 import 中央数据库、GPU 或服务协议。
- `node_agent.py`：获取可执行 capabilities 后先由统一策略过滤，`supervisor-required` 下训练/转换不进入 `reported_capabilities`；相应 `NodeAgentExecutorLoop` 不创建 TRAINING 和 MODEL_CONVERSION Runner，也不会根据已过滤的能力分配 DEPLOYMENT_TEST。其他非上述计算启动链路的 cleaning、material-import、model-upload 等能力仍按既有规则判定。doctor 的 executor 诊断增加 `execution_boundary_mode`。
- `platform_core/node_agent_training_runtime.py` / `node_agent_conversion_runtime.py` / `node_agent_deployment_runtime.py`：在远程训练/转换各自 `begin_process_launch(lease)` **之前**，以及部署复核的 `launch_process()` **之前**追加严格入口保护；启用强制 Supervisor 模式而尚未实现真正保护进程句柄时，抛出 `RemoteExecutionFenced`，不能直接 Popen，也不会把可能存在的进程臆断为已停止。异常配置同样拒绝。
- `tests/unit/test_node_agent_supervisor_gate.py`：少量必要回归，包括 legacy 默认不变、required 隐藏训练/转换/部署复核计算能力、非法值 fail-closed、三个真实 Runner 保护点位次序、原入口能力过滤与 doctor 可观察性。
- `.github/workflows/node-agent-executor.yml`：复用已有 Node Agent 全套回归 CI，增加新配置和入口保护检查。**只复用已有 CI，不再增设独立的数十轮 CPU PoC**。

**当前提交 SHA 按 GitHub 分支实际提交记录校验；准确代码/工作流初次验收 run**：
- [Node Agent Executor run 43679203190](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43679203190)，代码/工作流 SHA `c95caed83033042b97603b410dd45970abd75f8a`，初次记录仍 pending。需分别核对 Ubuntu、Windows 和 API Jobs；如失败须根据原始日志精确修复，不得把 pending 写成已通过。

## 三、可执行但尚未在生产执行的只读 GPU 节点盘点工具

文件：`tools/audit_gpu_node_access.py`（Python 标准库；Linux only）。**默认不执行**，只有明确 `--read-only` 才会统计：

1. 如果指定现有系统服务名，使用 `systemctl --system show <name> --property=...` 仅读允许列表内的属性，例如 User/Group、PrivateDevices、DevicePolicy、DeviceAllow、ProtectControlGroups、Delegate、NoNewPrivileges。
2. 只使用 `stat` 读取 `/dev/nvidia*`、`/dev/dri/renderD*`、`/dev/kfd`、部分 Ascend/Rockchip 设备节点的文件类型、UID、GID、权限位；**不打开设备节点、不执行 CUDA、torch、nvidia-smi**。
3. 读取执行本脚本用户的有效 UID/GID/组以及系统 cgroup v2 是否存在；不读取 Node Agent token、Environment、ExecStart、私钥、训练素材、模型或业务数据库；不修改 systemd、GPU 驱动或机器状态。
4. 结果仅是**权限清单**：不能单凭 DAC metadata 推断真实 CUDA/SDK 是否能访问；也不会声称 supervisor 已可信。

**未来仅在明确授权的目标 Linux 节点本地运行时的命令示例**：

```bash
python3 tools/audit_gpu_node_access.py --read-only
# 已确定正确服务名后再添加
python3 tools/audit_gpu_node_access.py --read-only --unit <actual-node-agent.service>
```

目前并没有在 A800 或双4070 执行以上命令。用户可以以后批准只读采样，但**暂不需要用户现在腾出时间**。

## 四、未完成的真实开发，下一小阶段怎么做

**下一阶段不应再继续一轮轮 CPU 模拟**，而是实现一个真正受保护的本机 Supervisor 最小纵向切片：

1. Linux 非特权 Node Agent 只通过本机 Unix Socket 请求**受限白名单的执行器**；Supervisor 从 kernel `SO_PEERCRED` 判断请求者 UID，而不是相信客户端自报身份。
2. Supervisor 自行从中央已签发的原 `task_id + tasks.attempt + worker/node + lease` 校验身份，在系统级 cgroup/unit 启动固定训练/转换可执行文件，负责进程生命周期、退出码、可靠日志流/offset、取消和完整停机证据。
3. 先做 **CPU-only 真实执行器 E2E**，确保与 `Popen.poll()/returncode` 及已有 `ProcessController` 兼容，**不允许损坏训练结果上报或清理语义**。
4. 仅当 GPU 节点权限模型已获批准、明确 Agent 不能直接打开 GPU、workload 可以授权使用时，接入正式 GPU 训练/转换，并进行真实多子孙、断网、OOM、GPU 占用和热切换测试。
5. 再做 StopReceipt 独立公钥信任/挑战防重放和中央默认 OFF 恢复 API；不重新实现现有 `tasks.attempt` 或调度队列。

**重要安全限制**：现在的 `supervisor-required` 只保护不安全的直接启动路径，**尚不能运行受保护的训练任务，也不能签发生产可信 StopReceipt**。保留 `REMOTE_AGENT_STOP_UNVERIFIED` HOLD、GPU reservation 以及自动派单 OFF；任何上线、systemd 配置变更、真实任务迁移、生产权限审计/设备操作均先获得明确授权。

### 2.3 2026-11-15 精准审计补充：DEPLOYMENT_TEST 也可启动计算

在训练/转换防护后，额外只读核查 `platform_core/node_agent_deployment_runtime.py`，发现 **Ultralytics/Paddle/RKNN 模型复核同样使用 `launch_process(command, env={**os.environ,...})`**，部分模型可能使用 CUDA/板端推理 SDK。若只禁止训练/转换而不管部署复核，将留下未经 Supervisor 约束的另一条计算启动链路。因此已将 `deployment-test`、`deployment-test.rknn` 加入同一能力过滤，并在其唯一直接启动点加上相同 fail-closed 阻断；**legacy 默认完全不变**。

此举意味着未来真正部署 `supervisor-required` 前，不只是训练和转换需要新的受控 launcher，还必须覆盖模型复核。不能把功能无声下线后宣称“Supervisor 已上线”。新增保护仅在该配置被显式设置时生效。

**精确 CI 说明**：本轮修改 `node_agent.py` 及三类 Runner 后 GitHub 会触发广泛的仓库工作流，但只将 [Node Agent Executor](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43679484571) 的 Ubuntu / Windows / API 回归作为本功能主要证据，该准确源码 SHA 为 `c66ef5678c9dd86cd681c67a1623baacc5217e3d`；更新本节时仍排队，不能宣称已验收通过。由于仓库 push 会触发大量 unrelated 工作流，后续应**合并小改动再提交、控制重复 CI、只对失败项定向处理**，避免无效反复压测。
