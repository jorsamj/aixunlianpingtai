# 畅联云算法训练平台｜独立 OS Supervisor 渐进式实施方案（基线审计版）

**编写日期：2026-11-15**  
**仓库：** `jorsamj/aixunlianpingtai`  
**唯一开发分支：** `feature/external-algorithm-publishing`  
**阶段：** **仅方案确定、只读代码审计；未开发新的生产 Supervisor。**  
**生产状态：** A800、双4070 未操作；`REMOTE_AGENT_STOP_UNVERIFIED` HOLD、原 owner/lease/`tasks.attempt`/GPU reservation 保留；自动派单 OFF；可信自动恢复 NO-GO。

## 0. 为什么先停止重复 PoC

前序阶段已经完成 Linux systemd/cgroup 真实停机、一次性挑战、独立 UID/Unix Socket `SO_PEERCRED`、root-only 测试签名、unit 外进程存活反例与模拟文件 DAC。事实足以确定**可行的技术方向与尚缺的生产信任根**，重复 CPU 实验不再是最有价值的工作。

本阶段先解决真实业务如何逐步接入的问题。上轮已提交一个**真实业务保护开关**：

- `CHANGLIAN_AGENT_EXECUTION_BOUNDARY=legacy`（**默认**）沿用现有流程；
- `supervisor-required` 时，由于真正 protected launcher 尚不存在，Node Agent 不声明 `training` / `conversion` / `conversion.rknn` / `deployment-test` / `deployment-test.rknn`，三个 Runner 的直接 Popen 入口也拒绝 fallback；
- 非法配置直接拒绝，而不按 legacy 猜测。
- **严禁当前在生产设置 supervisor-required**：设置后计算类任务将不能按原路径启动，不等于已拥有 Supervisor。

## 1. 已确认的正式代码事实与约束

| 位置 | 当前依赖 | 渐进改造约束 |
|---|---|---|
| `platform_core/task_runtime/process_control.py` | `LaunchedProcess(process: subprocess.Popen, identity: ProcessIdentity)`；`launch_process()` 使用 POSIX `start_new_session=True` 或 Windows process group，`ProcessController.terminate_tree(identity)` 做树/进程组清理 | **不能**把一个 Unix Socket 返回的 JSON 冒充 `subprocess.Popen`；需独立 `SupervisedProcessHandle`、明确 `poll()/exit_code/stop` 语义 |
| `platform_core/node_agent_training_runtime.py` | 启动前 `begin_process_launch`、PID 身份落盘、`launched.process.poll()/returncode`、`ProcessController`、DataLoader 后代清理、进度/显存/结果发布 | **暂不先迁移训练**；每次退出都要确保原受控计算组停止后才能上传结果，不能只看 leader 退出 |
| `platform_core/node_agent_conversion_runtime.py` | 同样有启动前 intent、身份持久化、轮询、日志、取消与最终产物处理 | **首个 Runner 适配对象**，优先非 GPU 的简单转换案例；不打破原转换格式/数值验收 |
| `platform_core/node_agent_deployment_runtime.py` | 模型复核/推理也直接 `launch_process`，依赖 poll、returncode、日志和 `ProcessController`；与训练/转换的持久身份恢复方式不同 | **第三个适配对象**；在接 Supervisor 前先补相同的 durable launch/identity 原则，不能直接搬训练的清理实现 |
| `platform_core/node_agent_executor_loop.py` | 中央 `start_execution` 才形成执行租约，runner 在执行之前按能力过滤；被 fence 不可冒充成功 | 保留原 `tasks.attempt`、token、owner、心跳、任务状态、GPU reservation；Supervisor **不是第二个中央调度器** |
| `node_agent.py` | Node Agent 根据 `reported_capabilities` 构造运行器并上报心跳 | 每阶段只在**专用隔离 Agent**中开启已实现的任务种类；旧 Agent 默认仍走 legacy；不要全局一次性切换 |

真实 Node Agent service UID、sudoers/polkit、user-systemd 权限、`/dev/nvidia*`/UVM ACL、容器/设备 cgroup 限制、CUDA/板端 SDK 权限**未在真实服务器验证**。仓库板端安装示例不代表 A800/双4070 实际服务配置。

## 2. 已确定的最小架构

```text
中央现有 task / tasks.attempt / lease / GPU reservation
                      │
                  Node Agent
           （只下发已受限的请求）
                      │  受保护的本机 Unix Socket / SO_PEERCRED
                      ▼
              Linux OS Supervisor
          （独立服务 UID/系统权限边界）
         ├─ 中央原执行租约身份核验（必要时签名 grant/回查）
         ├─ 注册 task/generation/node/GPU/原始凭证摘要
         ├─ 只允许固定的 Runner 类型与参数结构
         ├─ 启动专属 systemd system service/cgroup
         ├─ 持久 OS execution identity / 运行状态 / 退出码
         ├─ 日志存储、poll、取消、stop + cgroup 证据
         └─ 后续才加入受保护 StopReceipt 签发
                      │
              SupervisedProcessHandle
                      │
         先转换 → 再训练 → 最后边缘复核
```

**不允许：**
- 不让普通 Agent 提交任意 shell、任意二进制路径、任意 PID/unit、用户指定的签名密钥路径或不受限 `cwd/env`；即使 `SO_PEERCRED` 成功，也不能单靠本机 UID 证明中央已经授权任务。
- 不把 `systemd-run --user` 的 unit 当作独立 root 权限边界；Linux systemd transient **system** service 与所属 workload UID 要通过实际 OS 信任模型实施。
- 不因为 `systemctl stop` 返回 0 或原 cgroup `populated=0` 就签发全节点 GPU 空闲证明；仅能在绑定的执行边界、受保护身份与完整后代核验条件下形成精确 StopReceipt。
- 不新增第二套任务所有权/执行 generation；Supervisor 的持久表只能记录**本机 OS 执行边界**，中央状态仍由 `tasks.attempt` 和现有任务 repository 决定。
- 不在未证明 root/sudo、GPU 设备权限隔离前启用中央自动恢复或真实任务重排。

## 3. 渐进实施阶段和硬验收闸口

### 阶段 0：冻结基线与接口审计（**当前**）

**改动：** 只读整理现有三个 Runner 的 spawn/poll/returncode/log/stop/intent/结果上传链路和本阶段方案；不引入新工作进程，也不改生产配置。重点核对上一轮 Node Agent Executor 的 Ubuntu/Windows/API CI，只有拿到**最终绿色**才以其为已通过基线。

**验收：** 三类 Runner 依赖点、性能影响、回退方式均列清；`legacy` 必须保持完全兼容；任何现有 CI 未完成不得标记“已全绿”。

### 阶段 1：独立 Supervisor 最小服务与**进程句柄合同**（**下一次开发先做**）

**改动：** 仅新增独立 Linux 服务模块（不挂接中央 Web/API、不替换旧 Runner）。固定版本协议、Unix Socket、内核 `SO_PEERCRED`、严格 schema/请求大小/超时、拒绝任意命令与路径、启动前 durable intent、可恢复的 OS boundary journal。

**句柄最小语义：** `start(authorized_execution)` 返回 `execution_handle_id + registered_boundary`；`status(handle)` 只报告 `STARTING/RUNNING/EXITED/UNKNOWN` + 有据可查的退出码；`stop(handle)` 必须核对原执行组并只处理该组；`log_read(handle, offset)` 有界读取；服务重启后能恢复映射或**UNKNOWN→HOLD**。请求失败/超时不代表命令未执行，不能盲目重试启动。

**授权：** `SO_PEERCRED` 只认证本机 Agent 账户。真正任务执行权限须结合中央原 `task_id+tasks.attempt+node+lease` 的**可信 grant 或独立回查**，不可相信普通 Agent 自述；签名和密钥管理不允许由普通 Agent 控制。

**验收：** Linux 非 root Agent 仅能请求登记的执行实例；Supervisor 重启/请求超时/重复 start 均不产生第二个计算实例。先只以隔离 CPU 程序为验证负载。

**禁区：** 此时不让 `node_agent.py` 启用接单，不触碰 A800/4070，不宣称可信停止证明已可供生产使用。

### 阶段 2：实际进程生命周期纵向闭环

**改动：** 让独立服务实际运行一个固定的测试 worker，并提供真实 status、退出码、日志 offset、cancel/stop、原 unit/cgroup 事件和服务重启后的持久重连；使用**隔离的测试节点**而非正式 Runner。

**验收：** 正常退出、取消、多进程后代、Supervisor 崩溃/重启、Agent 重连和重复请求均无重复运行；无法证明停止时保持 UNKNOWN/HOLD，不删除证据。该阶段**是功能交付，不是再重做前面纯逻辑 PoC**。

### 阶段 3：单一 Runner 灰度适配——**先模型转换**

**理由：** 转换已有 durable launch intent 和精确 ProcessIdentity，运行过程相对训练简单；适合验证新的 `SupervisedProcessHandle` 是否能与现有轮询/日志/取消/结果上传兼容。

**改动：** 仅对专用 Linux 测试节点的模型转换引入 `legacy/supervised` 实现选择；旧流程原样保留；转换成功仍执行既有产物格式/校验/结果确认。绝不允许已选择 supervised 却静默 fallback 为 Popen。

**验收：** 一个转换任务的开始、运行、完成、取消、异常、日志、身份落盘、结果回传、断网/HOLD 均与旧流程一致；其他训练与复核 Runner 完全不改；只有该类任务实现完整才允许专用 Agent 上报相应能力。

### 阶段 4：训练和边缘复核分别适配

**训练：** 保留训练轮数、自动配置、训练报告与模型回传流程；重点确保 DataLoader 多后代、GPU 映射、OOM 后残留、停止证明未完成时不得上传成功结果。

**复核：** 先补 durable identity 的一致性，再覆盖 Ultralytics/Paddle/RKNN 等不同执行入口；不能因不同硬件 SDK 而误判已停机。

**验收：** 两类各自单独 CI/隔离验收；每次**只开放一个能力**，通过后才开下一个；前端、中央 Web、SQLite 调度体系保持不改。

### 阶段 5：真实 GPU 权限隔离 + 可信 StopReceipt + 中央恢复（**需单独授权**）

**先只读：** 在明确批准的 A800/4070 目标节点读取准确 systemd `User/Group/DevicePolicy/Delegate`、sudoers/polkit、`/dev/nvidia*`/UVM、容器/cgroup 状态；现有 `tools/audit_gpu_node_access.py --read-only` 可以生成无秘密的权限清单，**尚未运行**。

**再受控测试：** 证明普通 Agent 无权直接打开或使用 GPU，而 supervisor workload 经授权可以；保留或迁移 `nvidia-smi`/torch 资源探测的只读遥测，避免 GPU 容量调度失效。

**最后：** OS 受保护 signer、挑战 freshness/防重放、可靠 StopReceipt、中央 `BEGIN IMMEDIATE`/CAS 恢复机制、双节点网络分区/取消/训练后代/重复投递验收。**只有此阶段通过、明确生产部署批准后才允许讨论解除 `REMOTE_AGENT_STOP_UNVERIFIED` HOLD 或启用真实自动重排。**

## 4. 每次提交/上线的共同约束

- **代码提交范围：** 唯一长期开发分支；不合并 main、不强推、不 Release、不操作生产服务。
- **最小变更：** 先新增独立 `platform_core`/Supervisor 模块和明确适配接口，不把业务逻辑复制到 Supervisor，不堆进 `app.py` 或重新实现调度器。
- **一次一类功能：** 不同时改三个 Runner；先验证单链路，再打开下一个；所有当前任务处于真实执行状态时，不擅自改执行边界。
- **最低测试：** 以针对性单元合同 + 一次隔离 Linux E2E + 已有 Node Agent CI 为主；不再为同一证明增加多个相似 GitHub workflow。
- **失败回滚：** 开发分支不影响现有服务器；新代码部署后默认仍为 legacy。专用测试节点可停止 Supervisor 接单并恢复旧配置（前提是经核实没有 Supervisor 受控进程仍运行）；**运行中任务不得通过切开关、删 unit、强制释放 GPU reservation 实现“回退”**。
- **状态透明：** 各阶段必须记录当前 HEAD、准确 CI run/SHA、哪一项测试通过或仍 pending、StopReceipt 是否真正可信、生产是否 NO-GO；不能将模拟实验标记为正式验收。

## 5. 专门需要避免的四个失败模式

1. **接入方式错误**：将 Socket JSON 塞给 `subprocess.Popen` 或仍由 Agent 自己调用 `ProcessController.terminate_tree` 处理不同 UID 的 Supervisor 子进程，造成无法停止或错误完成。
2. **启动窗口双执行**：Supervisor 已启动，Agent 没收到回复又重试创建第二个 unit。需要先落盘中央 attempt/lease + 同一 handle 幂等；超时只能查询原 handle，不可再次新建。
3. **硬件隔离误判**：以 `CUDA_VISIBLE_DEVICES`、文件 `0660` 模拟实验或 cgroup 空组证明 NVIDIA/其他 SDK 没有越界 GPU 计算。必须由真实权限/驱动/设备测试验证。
4. **结果过早发布**：leader 退出后还有 DataLoader/SDK 子进程，或 StopReceipt 尚不可验证，就清理 launch intent/上传成功/重新释放 GPU。必须在受控原边界确认退出并保留审计证据之后执行原发布事务。

## 6. 当前已核实状态

- 长期分支在方案写入前实际 HEAD：`3e411fa12df02cd7acac1889b9299ef8f3eff97d`。
- 上轮 [Node Agent Executor](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43679484571) 针对 `c66ef5678c9dd86cd681c67a1623baacc5217e3d` 的 Ubuntu/Windows/API 三项 Job 在本次审计时**仍均为 queued**，不能写作通过。阶段 0 CI 基线待验证。
- 本轮文档仅**确定方案并冻结最小实施顺序**；不新增生产 Supervisor daemon、不切换 Agent、不运行 A800/4070 权限盘点、不解除中央 HOLD。

## 7. 参考的原生操作系统机制

- [systemd-run](https://www.freedesktop.org/software/systemd/man/252/systemd-run.html)：可启动 systemd 管理的独立 transient service/scope。未来执行选择需核对服务和 shell/stdio 的边界差异。
- [Linux unix(7) SO_PEERCRED](https://man7.org/linux/man-pages/man7/unix.7.html)：从内核获取 Unix Socket 对端连接时 UID/GID/PID，不能替代中央业务授权。
- [systemd.exec](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec)：`NoNewPrivileges=` / `ProtectControlGroups=` 等安全边界仍必须结合具体服务与设备环境验证。

**审计结论：先阶段 1→2 再适配 Runner；阶段 5 前不得认为已具备生产可信自动恢复。**
