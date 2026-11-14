# P0-01C-2｜Linux cgroup v2 / systemd 可信执行边界：只读审计与最小 PoC 任务书

> 日期：2026-11-15（Asia/Singapore）
> 仓库：jorsamj/aixunlianpingtai
> 唯一允许开发分支：`feature/external-algorithm-publishing`
> 审计基线（**文档写入前**）：`9a7b16d167c45a178ddfd73cc40790d92f9bd352`（docs HEAD）
> 最近业务代码 SHA：`e515ce78523e76d9acf6afdc42e049993aee24ad`
> **状态：方案与源码审计已完成；cgroup/systemd 原型、真实内核隔离验收均未实施。生产 NO-GO。**

## 1. 本轮准确 GitHub CI 收口（不要混淆 SHA）

通过 GitHub REST Actions `head_sha` 精确查询：
- `e515ce78523e76d9acf6afdc42e049993aee24ad`：**27/27 workflow completed success**（含 Push/PR）。Node Agent Executor Push run `43616115883`：Windows `455 passed, 2 skipped`、Ubuntu `455 passed, 2 skipped`，另 Ubuntu 原生 SIGKILL 子进程窗口隔离测试 `2 passed`；Remote Training Push run `43616115834`、Remote Conversion Push `43616115844`、Remote Cleaning Push `43616115943`、Portable Deployment Push `43616115853`、Task Runtime Truth `43616115896`、双 Node HTTP `43616115714`、Frontend `43616111303` 均 SUCCESS。
- 文档 HEAD `9a7b16d167c45a178ddfd73cc40790d92f9bd352`：**22/22 workflow completed success**。这一 SHA 本身只改文档，不能替代业务代码验收。
- Windows 训练/转换恢复回归用例当前分别在 `tests/unit/test_node_agent_training_runtime.py` 与 `tests/unit/test_node_agent_conversion_runtime.py`；关联 Windows workflow/job 全部 SUCCESS。历史 `os`、`PyYAML` 测试归属问题在 `e461737` / `e515ce7` 修复。本次没有发现需要再修的相同 CI 故障。
- 以上属于 GitHub 隔离环境（Ubuntu 24.04 / Windows latest）合同测试，**没有**完成真实 Linux delegated cgroup、双 GPU/双物理主机/跨网络分区的验收。

## 2. 只读源码核对：现有保护和缺口

| 审计位置 | 当前实际代码证据 | P0-01C-2 判定 |
| --- | --- | --- |
| `platform_core/task_runtime/process_control.py` | `launch_process`：POSIX `start_new_session=True`；Windows `CREATE_NEW_PROCESS_GROUP`；`inspect` 核 PID/create_time/hash/有限值；`terminate_tree` 遍历已知后代及 `killpg` | **不是可信 OS 执行边界**。PGID 可复用，逃出进程组的后代不一定受控；Windows 不等同 Job Object |
| `platform_core/node_agent_executor_runtime.py` | `begin_process_launch` 先持久化危险标志并 POSIX 同步目录链，之后才允许 spawn；`persist_process_identity` 保存精确 PID；`cleanup` 若意图/身份仍存在则拒绝清理 | 防证据消失，不证明后代已经停止；尚无 unit/cgroup 身份记录 |
| `platform_core/node_agent_training_runtime.py` | 重启先检查共享未知启动标志与 PID 身份；Windows 发现历史 PID 则 `ready=False`，保留记录；Linux 尝试 `terminate_tree`；正常启动为 marker→Popen→PID 持久化 | 启动后的成员归属及 Agent SIGKILL 后全后代仍未由内核证明 |
| `platform_core/node_agent_conversion_runtime.py` | 与训练同样的重启保护；转换完成后先尝试严格停止验证再上传结果 | 正确方向，但 POSIX group stop 不能跨故障当作完整可信证明 |
| `platform_core/node_agent_executor_loop.py` / `node_agent.py` | `effective_capabilities` 会过滤 not-ready Runner，训练与转换共享 workdir；Node heartbeat 上报可执行能力 | 应保留现有 readiness 语义，不能让未验 OS 边界节点宣称可执行新计算 |
| `platform_core/task_runtime/repository.py` | `_release_expired_in`：远端过期置 `recovery_blocked_remote_agent_unverified` 与 `REMOTE_AGENT_STOP_UNVERIFIED`，不转 QUEUED/CANCELLED；保留 GPU reservation，分配检查 HOLD | **必须原样保留**，本阶段禁止写自动解除 |
| `platform_core/agent_execution.py` | `remote_recovery_diagnosis` 为只读，返回 `stop_proof_verified=False`、`automatic_reassignment_allowed=False` | 不存在正式 stop-proof 接受端；不要伪造 VERIFIED |
| `tests/integration/test_agent_launch_sigkill.py` | 真实 SIGKILL 造成“已 spawn、未记录 PID”竞态，两类任务保留危险标记并 fail-closed | 只验证合成 CPU 进程/工作目录，不代表真实 cgroup/GPU 可信停止 |

本轮先不改运行时代码：在既有契约已 GREEN 且尚无真实内核可写测试环境的情况下，直接接入 cgroup 容易制造新的“看似安全”分支。

## 3. 设计选择（参考成熟 Linux 机制）

**首选：systemd 用户管理器的 transient `.service`，每个 `node_id + task_id + attempt/generation + 随机唯一标识` 一份 unit。**由 systemd manager **直接创建**计算主进程，先建立执行 unit/cgroup 再允许 `execve` 计算程序；优先 `Type=exec`、`KillMode=control-group`，通过 D-Bus `StartTransientUnit` 或经过隔离验证的 `systemd-run --user` 合同创建。unit 名须受控长度、不可用未经校验的用户参数；argv 数组传输，禁止 shell 拼接。注：具体接口/选项以目标 Ubuntu 22.04 systemd 249 能力实测为准，不能把官网最新版 262 行为默认视为生产事实。

**为何优先 service 而非先用 `Popen` 再迁移到 scope/cgroup：**后者存在进程已运行但尚未完成 cgroup 成员绑定的窗口，与本专项 P0 风险直接冲突。scope 可作为备选，但必须通过真正的预启动阻塞与归属验证合同才可采用。直接写 `cgroup.procs` 需要合规委派、权限和并发迁移约束，当前不作为最小方案；不通过 root 运行 Agent 绕过权限。

**关键前提：**
1. 专门非 root 账户（4070 将来应为 `changlian4070`）；系统支持统一 cgroup v2、systemd 用户 manager / 用户 bus（`XDG_RUNTIME_DIR`、必要的 linger）；须在**独立测试节点**核实。若服务机没有可用的非 root user manager，应做受约束的系统 manager 策略评估，不给 Agent 任意 system unit 创建/修改的 root 权限。
2. `process-launch-intent` 在启动前写入任务代数、节点身份、boot ID、随机 unit 名/nonce 等**预承诺**；记录 fsync 保证。新元数据只能**新增、默认关闭**，不得令旧版本 identity 文件被误当作 VERIFIED。
3. 启动后读取并核对 `Id`、`ControlGroup`、`InvocationID`（若系统支持）、`MainPID` / `/proc/<pid>/cgroup`、boot ID、所属 UID、task/attempt/generation 与预承诺绑定。unit 意外丢失、改属、读取异常、系统重启或无法证明完整归属，一律 UNKNOWN/HOLD。
4. 非恶意、无额外特权的计算进程 fork 后代继承 cgroup；必须验证 SDK/DataLoader 是否启动独立 unit、容器、提权服务或可迁出此 cgroup 的进程。**只读到 `populated=0` 不证明历史上未逃逸**。
5. 停止时对正确 unit 执行 stop/kill 控制（或在允许且已绑定正确 cgroup 后使用 `cgroup.kill`）；验证整个 cgroup 子树确无活进程，并取得不可与别的 unit 复用的连续身份状态。路径缺失、权限不足、不匹配、无法排除并发 fork/迁移时必须 HOLD。不能凭 `systemctl is-active=inactive`、PID/PGID 不存在或 Agent ONLINE 单独授权恢复。
6. 单次内核检查只供**原节点侧局部安全判断**。中央可信挑战、原节点新鲜证明、`BEGIN IMMEDIATE` 原子释放是之后的 P0-01C-4；此阶段绝不发送 `stop_proof_verified=True`。

官方依据：
- Linux kernel cgroup v2：https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html （`cgroup.events populated`、`cgroup.kill`、delegation）
- systemd-run：https://www.freedesktop.org/software/systemd/man/latest/systemd-run.html （transient service/scope 和 `Type=exec`）
- systemd.scope：https://www.freedesktop.org/software/systemd/man/latest/systemd.scope.html
- systemd.kill：https://www.freedesktop.org/software/systemd/man/latest/systemd.kill.html （`KillMode=control-group`）
- systemd.resource-control：https://www.freedesktop.org/software/systemd/man/latest/systemd.resource-control.html （`Delegate=`）

## 4. 最小实施范围（按三步推进，不越级）

### 01C-2A｜只读环境可行性合同（独立 Linux 测试机）
- 核 `/sys/fs/cgroup/cgroup.controllers`、`/proc/self/mountinfo`、`/proc/self/cgroup`、`uname -r`、`systemctl --version`、`systemctl --user`、可委派权限、`cgroup.kill` 是否存在及调用账号 UID、unit 生命期；**只读收集**。没有相应 user bus/委派的环境标明 BLOCKED，不改生产配置。
- 明确非 root 安装指引和用户服务启动条件；确认是否可由 systemd manager 启动任务、是否能读 unit identity/cgroup.events、是否持久保留足够的审计证据。
- 在 GitHub Actions 无真实委派/写入权限时显式 `SKIP/BLOCKED: kernel cgroup boundary unavailable`；不能使用 mock 测试包装成内核已验。

### 01C-2B｜完全独立的最小 PoC，不接中央、不接 Runner
- 新建**测试专用** `tests/integration` PoC/helper（或 `tools/poc`），不先改 `launch_process` 的生产路径。普通非 root 测试账户，通过 systemd user manager 创建真正 transient service，启动纯 CPU 测试命令和多级子进程；先形成预承诺、再由 manager 启动。
- 正例：任务与 unit/cgroup/UID/boot ID 精确绑定，正常退出后通过真实 cgroup state 收口；故障：leader 死而子存活、Agent SIGKILL、停止过程中 fork、权限拒绝、unit 名复用/窜改、错误代数/节点、重启、路径消失、拒绝归属、无法读取 events、假数据、DataLoader 等价多进程；全部验证“不确定即 HOLD”。
- 特别验证 `systemd-run` 子进程在正式归属前**绝不执行工作代码**；如果没有实证，必须 RED/BLOCKED，不能宣称消除预绑定竞态。验证非 root 不能迁出所属执行边界（已知授权和能力模型下），不能让非受管 helper 长期运行。
- 保存真实 `/proc`、unit `ControlGroup`、boot ID、事件快照、PID/starttime、日志与测试退出码；禁止碰生产 PID、GPU 或真实任务目录。

### 01C-2C｜仅在 PoC GREEN 后做最小适配
- 评估新增 Linux-only `ExecutionBoundary` adapter（独立模块），复用已有 `AgentExecutionWorkdir`、任务 kind/generation、`ProcessController` 接口，不另建队列、owner、数据库或前端。
- **新开关默认 OFF**。仅准备少量隔离 Linux Agent 的训练与转换接入，保持既有 Windows 行为和远端 HOLD；unsupported/权限不足/失败必须拒绝任务**而不是降级到未受管 Popen 然后自动复派**。
- 独立完成 PoC 后再考虑中央证明；不能在本子阶段动 `TaskRepository._release_expired_in` 的 HOLD 或 GPU reservation 释放。

## 5. 测试矩阵与准入

| 场景 | 最小验收要求 |
| --- | --- |
| 正常结束及多级后代 | 验证整树已退出且与原 unit 绑定；不以主 PID 退出代替 |
| 在 OS 归属前 Agent 被 SIGKILL | 不执行计算；无法证明则 HOLD |
| Agent 在已启动后 SIGKILL / 网络断连 | 后代受正确 unit 管理；中央任务仍 HOLD |
| Linux OOM / leader SIGKILL | 不遗漏活子进程；必须经独立 unit stop 和全树检查 |
| fork 与 stop 并发 | 无活计算遗漏；不能仅对单个 PID 发信号 |
| PID/PGID 或 unit 名复用 | 严格拒绝非同一 task+generation+boot+unit 实例 |
| 缺权限、缺 cgroup、失去 user bus、文件损坏 | BLOCKED/HOLD，无自动回退到弱隔离 |
| GPU SDK/DataLoader 外部拉起辅助进程 | 如无法验证全树归属则不批准真实训练接入 |
| Windows | 旧 Job Object 缺失门槛保持；该 Linux PoC **不构成** Windows 准入 |
| GitHub Runner 无 delegated writable cgroup | 明确 SKIP/BLOCKED，Mock 只可用于纯合同测试 |
| 跨机恢复 | 本阶段不测自动解锁；下一阶段须物理机+旧执行并发负面测试 |

阶段验收材料：可复用的最小 PoC、真实 Linux kernel 日志、测试用例/退出码、权限矩阵和允许/禁止执行条件。**任何一个未知即停留 NO-GO。**

## 6. 影响、风险和回退

**预期好处**：以 OS cgroup 边界代替易复用 PID/PGID + 进程快照，在同一任务代数内追踪并停止整个受管子树；帮助隔离崩溃后孤儿进程与竞态，并为后续中央证明提供来源。

**主要风险**：user systemd manager 不可用或受权限限制；start/stop 时序改变；进程 stdout、环境变量、cwd、GPU 可见性与退出码传递变化；cgroup unit GC 后证据消失；GPU SDK 非直接后代或借助特权守护进程逃逸；服务停止与结果上传竞态；错误 unit 名误停其他任务；权限配置范围过大。所有这些在 PoC 先测试，不能在真实训练上试错。

**回退**：本阶段只写 docs/测试，不改运行时；生产完全不受影响。未来接入 adapter 时应保留默认 OFF，关闭新路径后恢复既有执行代码，但**不能清理已存在的 intent、identity、unit 记录，不能自动解除旧 HOLD/GPU reservation**；如曾启用过新边界，回退前先阻止新分配并验证每个受影响 generation 的 OS 状态。

**生产判定：NO-GO**。GitHub 工作流全绿只证明对应源码合同；缺 Linux 真实可写 cgroup/Agent 崩溃运行边界测试、Windows Job Object、一次性 challenge、SQLite 原子恢复、真实两物理节点 GPU/UAT、授权部署。自动派单必须保持 `CHANGLIAN_AGENT_AUTO_ASSIGN_ON_CLAIM=OFF`。

## 7. 后续顺序与独立缺陷

1. **下一开发最小任务：01C-2A**（非生产只读权限清单 + 支持/不支持探测器），随后 **01C-2B**（纯 CPU systemd transient service 真实内核 PoC）。不做核心 Runner 改造，直到 PoC 显示真正消除“启动→归属”窗口。
2. Linux PoC GREEN 才能提议 01C-2C；Windows 以 CreateJobObject/AssignProcessToJobObject、挂起启动后先绑定及 KILL_ON_JOB_CLOSE 另做验收。
3. 双 OS 边界验证后，才研究原节点 challenge / boot-session / generation 签名和 SQLite `BEGIN IMMEDIATE` 事务；本轮绝不开发自动解除 HOLD。
4. Issue #27 的前端重复失败仍为独立事项。即使本次 `e515ce7` 前端工作流通过，也不等于已消除它们的根因。
