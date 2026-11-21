# 畅联云算法训练平台｜P0-01C Supervisor 阶段 1A：受保护通信基础设施与进程句柄合同

**日期：2026-11-15**  
**分支：** `feature/external-algorithm-publishing`  
**实施依据：** [Supervisor 渐进式实施方案](P0_01C_SUPERVISOR_INCREMENTAL_IMPLEMENTATION_PLAN_2026_11_15.md)  
**上线结论：** **不可上线，不得启用生产 `supervisor-required`，远程自动恢复继续 NO-GO**。

## 一、为何先只完成通信层

现有 Training/Conversion/Deployment 任务直接依赖 `LaunchedProcess(process: subprocess.Popen, identity: ProcessIdentity)`、`poll()`、`returncode`、`ProcessController.terminate_tree()`、日志/任务租约/结果上传等。把一个 Socket JSON 直接伪装成 Popen 将破坏取消和退出状态，并使中央错误地认为计算已经停止。

因此按冻结方案的**第一小步（阶段 1A）**，先完成真实独立通信服务、Linux 双向 peer credential 鉴权、协议、预定义的句柄形状和 fail-closed 边界，**不允许启动、停止或签发任何真实 OS 工作负载**。它是一份正式 Python 模块，而不是又一套与业务隔离的测试 PoC；未来阶段 1B/2 将在此服务上实现受控执行后端。

## 二、本轮实际新建的正式文件

| 文件 | 已实现 | 未实现 |
|---|---|---|
| `platform_core/os_supervisor_protocol.py` | 版本 1、16 KiB 上限、长度帧和完整读取；严格动作白名单 `health/inspect/start/stop/read_log`；每次请求随机 request_id；客户端校验 Linux `SO_PEERCRED` 提供的**服务端 UID**，默认要求 root；每个响应绑定原请求 ID、版本和正确的类型；`SupervisedProcessHandle` 与 Popen **明确不同类型**，`poll` 对 UNKNOWN/无法访问返回 HOLD 错误 | 真实 central signed grant、可重启的执行句柄、日志/停止证明、Windows 后端 |
| `platform_core/os_supervisor_service.py` | 独立 Linux Unix Socket 监听；服务端从 `SO_PEERCRED` 获取客户端 UID，仅允许部署时配置的非 root Agent UID；严格的请求形状/超时/长度/动作检查；root 模式限定固定 `/run/changlian-os-supervisor/control.sock`，不覆盖已存在 socket、不接受符号链接运行目录，绑定时设置 root/agent group 与文件权限，退出时只删除自己所绑定的 inode | **真实启动/停止实现**、systemd transient unit 和 cgroup 边界、可验证的 StopReceipt、中央 lease 验证、durable journal、GPU ACL |
| `tests/unit/test_os_supervisor_phase1.py` | 正反合同、无 shell/kill/sign 能力、错代数、过大/截断帧、UNKNOWN→HOLD、Popen 不兼容约束、**真实非 root Linux Unix Socket** + 双向 SO_PEERCRED 交互 | 不作为真实 GPU 的权限证据 |
| `.github/workflows/node-agent-executor.yml` | **复用现有** Ubuntu/Windows/API 工作流，在既有 Python syntax/unit 检查中纳入以上文件，无新工作流 | 实际 CPU systemd 计算 E2E（阶段 2） |

**目前实现是真正可以启动的独立 Socket 服务，但主动禁止执行计算。** 它的 `health` 仅证明协议服务可用，返回：
`launch_available=false`、`stop_available=false`、`trusted_stop_receipt_available=false`、`central_recovery_allowed=false`。

- `start`：`PROTECTED_LAUNCH_NOT_IMPLEMENTED_HOLD`。
- `inspect`：未登记的 OS boundary 一律返回 `UNKNOWN` + HOLD，不会将未知状态当成退出。
- `stop`：`PROTECTED_STOP_NOT_IMPLEMENTED_HOLD`；避免凭普通 Agent 请求发送任意 SIGKILL/systemctl。
- `read_log`：`LOG_STREAM_NOT_IMPLEMENTED_HOLD`；不允许读取客户端指定的文件路径。
- 请求不能提供任意命令、可执行路径、环境变量、root/PID/unit、签名密钥等操作参数。Socket 内核身份 **不是**中央真实任务授权，后续必须增加已签发的 `tasks.attempt` / lease 身份验证。

## 三、本轮核查及 CI

代码提交基线为 `2ab61ce6fe6d6c8a09e5fc8d9723672d92c5f5f8`（本轮新模块/现有工作流）。

开发时在本地 Python 3.13 隔离运行空间，用真实 Linux **非 root** 系统账户执行同类 Socket/协议回归：**31 passed**。这仅是开发初验，不等于 GitHub 最终通过；最新 GitHub [Node Agent Executor run 43684001227](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43684001227) 的 Ubuntu/Windows/API 回归在本文首次保存时仍排队，不能报告全绿。

上一轮 `c66ef5678c9dd86cd681c67a1623baacc5217e3d` 对应 [run 43679484571](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43679484571) 在阶段开始前仍处于 queued；未确认其全绿前不应把该基线标记为“生产可部署”。

**重要限制**：尽管服务 CLI 支持显式 `--serve --socket ... --agent-uid ... --agent-gid ...`，它尚无正式 systemd install/密钥注册和可信启动/停止能力。**严禁在 A800 或 4070 直接手动运行、添加服务或者给生产 Agent 设置 `supervisor-required`**；生产环境尚未授权。

## 四、下一开发阶段与接口冻结

**阶段 1B：受保护的 OS 执行登记和启动前 journal（仍不接 Runner）**

1. 定义**不可由 Agent 自报伪造**的 central grant 或 Supervisor 独立回查，绑定 `task_id + tasks.attempt + worker/node + original lease digest + GPU UUID + boot_id`，严格区分任务分配代数。
2. 在 root-only 本地持久 journal 中原子登记 `execution_handle_id` 和已确定的 OS boundary；重复 start 在未知情况下只能查询**同一 handle**，不得创建第二个执行。
3. 定义 `STARTING/RUNNING/EXITED/UNKNOWN` 的可证据化状态和过渡、超时/重启/消息丢失时的 HOLD 路径；不把普通 Agent 的 JSON 当作 StopReceipt。
4. 只有完整登记/授权合同通过，阶段 2 才允许 Supervisor 启动单一**固定 CPU 测试 worker** 并实际运行/停止 systemd cgroup、日志、exit code、停止证明。阶段 2 依然不得启用中央自动恢复。

**阶段 3** 先适配模型转换，随后训练，最后模型复核；每类 Runner 单独验证并灰度，不一次替换全部 `subprocess.Popen`。未经真实 GPU 节点权限审计和明确授权，不访问生产 GPU/设备 ACL/驱动。

## 五、固定安全与生产边界

- GitHub 唯一开发分支；不合并 main，不强推，不 Release；
- 本轮未修改既有 Node Agent/Training/Conversion/Deployment Runner 的任何逻辑，没有改前端、中央数据库、生产调度、GPU reservation；
- `CHANGLIAN_AGENT_EXECUTION_BOUNDARY=legacy` 继续是默认，`supervisor-required` 当前仍会拒绝计算直启；
- 继续 `REMOTE_AGENT_STOP_UNVERIFIED` HOLD，原 owner/lease/`tasks.attempt`/GPU reservation 保留，自动派单 OFF、生产 NO-GO；
- **没有 SSH 到 A800/双4070、没有运行生产服务、没有操作 GPU、模型和训练数据**。
