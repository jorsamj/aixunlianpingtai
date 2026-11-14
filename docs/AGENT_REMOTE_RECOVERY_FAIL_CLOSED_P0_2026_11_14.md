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

## 2026-11-14 P0-01C 小步二：子进程启动前危险标志（候选，准确 SHA CI 待验证）

- 基线 `de483d2` 的 **26 项 GitHub Actions 全部 SUCCESS**；此前 Annotorious 首轮 130/131、重跑 131/131，此基线的相同分片再次 131/131。此事实只关闭当次 CI 红灯，不代表自动事件防抖问题永不复现。
- 训练与模型转换执行器现于实际 `launch_process()` **之前**写 `process-launch-intent.json`（使用原来的原子写文件/fsync），只记录 task_id、generation 和 kind，不包含 Token、存储 URL 或密钥。此标志表示“可能启动了子进程，尚未证明终止”，**不是**生存证明或 stop-proof。
- 若 SIGKILL、异常或重启令 intent 存在但找不到精确 PID/create_time/command_hash，Runner **不 ready / 不接新任务 / 不允许未知状态下正常提交 FAILED/重派**；任务工作目录不得删除。已持久化精确身份的任务仍走原进程树验证/清理，确认后连同 intent 清除。损坏的身份/intent 或路径 fail closed。
- 已明确安全与可用性取舍：甚至 **spawn 之前**硬崩溃也可能留下无法自行清除的标志，必须人工或后续可信作业边界核验；现有 fsync 文件不等于完成断电级目录 fsync、OS 进程组可信证明或多主机实测。
- 这是 **P0-01C 的前置危险证据保护**，非可信解锁协议。原节点 challenge、防重放、generation 绑定、进程组/cgroup/Windows Job Object 可信停止证明、中央 `BEGIN IMMEDIATE` 原子释放和审计、真实断网及 OSS/GPU UAT 仍未实现/验收。
- 新增 workdir 与训练/转换 Runner 的隔离合同测试，**必须等本精确 SHA CI 完成才能宣称通过**。A800、双4070、生产数据库、OSS、自动派单默认 OFF 全部不动；生产 **NO-GO**。

## 2026-11-14 P0-01C 继续审计：模型转换成功退出后的残留子进程围栏（候选 CI 待验）

- 只读确认 `AgentConversionRunner.run()` 在转换主进程正常退出时，于 `finally` 直接清除 `process-identity.json` 并擦除内存身份；与训练 Runner 在成功退出后再次调用 `_terminate_active(strict=True)`、核验并清理整个进程组的安全策略不同。若转换器另起子进程并遗留，结果确认/终态可能在仍占用硬件时发生。
- 修复仅把转换成功退出路径改为**先按现有 `ProcessController.terminate_tree` 检查/清理，验证失败就保留进程身份证据和启动危险标志，拒绝上传或发布最终结果**。复用原控制器、原执行租约和原结果确认，不加新后台任务或控制端分支。
- 新负面测试将“转换主进程退出但进程组死亡无法证明”注入 `PermissionError`，要求 fail closed、不执行 prepare/confirm/finish、保留 task+generation 身份和 intent。原正向真实子进程测试继续作为成功回归。
- Windows `ProcessController` 的现有进程组语义不等于 Job Object 级子孙生命周期证明；Linux 真实孤儿子进程和多机断网仍需要独立实测。此补丁不提供 stop proof 或解除中央 HOLD，生产继续 **NO-GO**。

## 2026-11-14 P0-01C 跨执行器共享状态安全门槛（本提交 CI 待验）

- 只读核查 `node_agent.py::_build_executor`：训练与转换 Runner 使用同一个 `AgentExecutionWorkdir(state_dir / "executor")`，但早先各自传入 `TRAINING`/`MODEL_CONVERSION` 筛选未知启动危险标志。若训练在 spawn→PID 持久化窗口中异常退出且只留下 intent，转换 Runner 不会因该 intent 阻断 ready，反之亦然。同节点共享 GPU 的背景下可能继续分派新任务。
- 最小修复：保留原 `list_unverified_process_launch_intents(kind)` 的按类型诊断能力，新增 `kind=None` 查看**所有**训练/转换未配对危险标志；训练和转换的恢复准入调用无类型过滤。任一未知子进程可能占用共享 GPU，两种新任务均必须 HOLD；未加数据库/新调度 owner，也不清理或假定旧进程停止。
- 增加三类负面回归：共享 Workdir 可查询其他种类危险标志；未证实停止的历史转换阻止新训练；未证实停止的历史训练阻止新转换；保持原 task_id/generation、无结果发布/finish。
- 该安全门槛的已知代价是不同任务类型之间也会相互阻断，这是故障防双执行的保守处理。仍缺可信 stop-proof、持久进程组身份/代数绑定、挑战防重放、中央原子解除、真实多机断网与 Windows Job Object 验收；CI 未完成前不宣称 GREEN，生产 NO-GO。

## 2026-11-14 P0-01C 进程启动窗口的真实隔离 SIGKILL 负面测试

- 在 Ubuntu GitHub Actions `Node Agent Executor` workflow 的独立 Linux step 中增加 `tests/integration/test_agent_launch_sigkill.py`。测试在全新临时目录中启动一个真正的 Agent 模拟进程，执行 `AgentExecutionWorkdir.prepare`、`begin_process_launch`，然后通过生产 `launch_process` 创建独立 POSIX 进程组的**纯 CPU sleep 子进程**。测试控制器确认孩子已存活后对 Agent 父进程执行真实 `SIGKILL`，因此能确定“子进程已启动、精确 PID 尚未持久化”的竞态窗口。
- 分别验证 TRAINING、MODEL_CONVERSION 两种历史类型：Agent 被杀而模拟子进程仍活；磁盘只有 `process-launch-intent.json`、没有 `process-identity.json`；重启工作目录后**两种** Runner 都不 ready；异常工作目录不可删除，任务代数和种类可追踪；不意外杀死旧的未知子进程。进程清理由测试主管基于仅测试可见的 PID/create_time 定向完成，不生成产品 stop-proof。
- 测试不连接控制平面、OSS、GPU，也不运行模型或实际训练/转换，因此只是 POSIX 单机故障证据，不是物理双机网络分区验收；Windows Job Object 和可靠的原机停止证明仍需专项完成。CI 完成之前不得标注通过；生产仍 NO-GO。

## 2026-11-14 P0-01C 进程创建时间字段的非有限浮点安全校验（候选 CI 待验）

- 只读审计发现持久化 `process-identity.json` 的 `create_time` 经 `float()` 转换后只判断 `<= 0`，`NaN/Infinity` 可绕过；`ProcessController.inspect` 的 `abs(actual - expected) > 0.01` 对 `NaN` 始终为 false，可能在 PID 复用且命令 hash 一致时错误认领进程。此为确定的数值比较边界，不依赖前端浏览器偶发问题。
- 最小防护：Agent Workdir 读写身份与进程控制器核验处都要求 `math.isfinite(create_time)`，非法 PID/时间 fail closed。引入负面单测覆盖 `NaN`、`Infinity`、`-Infinity` 及 JSON 非有限值；既验证未写入异常身份，又验证既存不合法记录仍保留且阻止恢复；真实进程 PID/命令 hash 也不能用非有限时间冒充。未新增调度 owner、没有开放 stop-proof 解除或破坏现有模型结果协议。
- 本提交的 CI 须按准确 SHA 重新核实，不以此前 `4173375` 的 Linux SIGKILL 两项通过替代新提交的验证。Windows/Linux CI 均需通过；生产仍 NO-GO。

## 2026-11-14 P0-01C POSIX 启动标志目录项的持久化加强（候选 CI 待验）

- 现状 `AgentExecutionWorkdir._atomic_write_json` 对临时 JSON 文件 `fsync` 后执行 `os.replace`，但没有同步存放该文件的目录。针对运行前必须存在的 `process-launch-intent.json`，断电时只同步文件而未同步目录项可能丢失文件名，不能用作可靠的“已启动过子进程”危险证据。
- 最小修复只在 `begin_process_launch` 之后、任何 `launch_process` 之前追加 POSIX 目录同步：依次对 generation、task、executions、Agent state root 及其上一级目录做 `fsync`，用于持久化新目录和原子重命名的目录项；同步失败直接抛异常阻止启动，并且不得删除已有危险标志。复用现有目录路径校验，没有改通用 JSON 写入路径或 SQLite。
- 新负面测试：在 Linux 注入目录 `fsync` 异常，必须拒绝执行启动前方法、保留 task_id/generation/kind 标志且阻止无证据清理；正面测试核验所有必需目录同步发生。Windows 不提供对等的目录 `fsync` 保证，不虚称其具备断电级证明；受限文件系统/硬件缓存不遵循标准持久化合同也未在此验证。
- 本次是“减少启动窗口危险证据因断电丢失的风险”，**并非**进程真实已停止的证据；可信 OS 级执行容器、远端挑战、防重放、中央原子解锁仍然缺失。须以新提交的精确 CI 结果验收，生产保持 NO-GO。

## 2026-11-14 P0-01C 遗留 PID 身份的目录清理保护（候选 CI 待验）

- 代码审计确认 `clear_process_identity_record` 为保留故障证据，采用先删除 `process-launch-intent.json`、再删除 `process-identity.json` 的顺序。若两步之间 Agent SIGKILL 或系统崩溃，目录仅剩 PID 身份记录。过去通用 `AgentExecutionWorkdir.cleanup()` 只拒绝尚有启动危险标志的目录，**可能在 PID 身份仍可证明旧进程存在时误删目录，丢掉最后一份恢复证据**。另外老版本可能本来就无 intent 而只有 PID 身份。
- 最小修复只在通用 `cleanup` 中增加 `read_process_identity(lease)` 非空时拒绝，损坏的身份文件本就 fail closed；必须由先证明进程停止的控制路径显式 `clear_process_identity`，然后才允许目录删除。没有修改执行器正常结果上传、中央 hold 释放或模型运行。
- 新负面测试覆盖“仅 PID 身份、无 intent”的真实磁盘目录，验证拒绝删除、身份完整保留；显式清除身份后才能继续清理。预期小范围影响：历史未清理的仅 PID 身份目录会继续 HOLD，需要可信核验才能释放，这是安全优先行为。
- 当前精确 SHA CI 尚待完整验收。未修改生产，仍 NO-GO。

## 2026-11-15 P0-01C Windows Agent 重启持久 PID 恢复 Fail-Closed（CI 待验）

- 只读代码审计：`ProcessController.terminate_tree` 在原 leader PID 消失时调用 `_terminate_posix_group(identity.pid)`；Windows 下该方法立即返回，故原代码可能在未确认 DataLoader/SDK 子孙进程是否存活时，清除 `process-identity.json` 和 `process-launch-intent.json` 并重新上报 ready。普通 `CREATE_NEW_PROCESS_GROUP` 不等于 Windows Job Object。参考 [Microsoft Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)。
- 最小安全门槛只限 **Agent 初始化后的持久进程恢复**：在 Windows，若训练/转换共享 Workdir 仍有任何持久 PID 身份，**两种 Runner 均不 ready、保留 PID 身份/启动标志并保持故障诊断**，不再推断旧计算已停止。Linux 现行恢复、中央调度、运行时任务上传和其他任务种类不改。
- Windows 合同测试覆盖两类 runner 均拒绝恢复并保留 task/generation/PID/命令 hash、通用目录清理也拒绝；既有训练重启正面测试按平台分支检查 Linux 正常恢复、Windows 缺 Job proof 持续阻断。代价是 Windows Agent 重启后遇到历史计算记录将持续 HOLD，必须以后续受控可信恢复方案处理，不能人工删文件放行。
- **范围边界**：这不意味着 Windows 正常任务退出时的子进程管理已经安全；本次没有实现真正 Job Object 的“先绑定再运行”、防逃逸继承、意外断电/断线恢复、停机确认或中央原子解锁。生产准入仍 NO-GO；不操作 A800、双4070 或生产数据。待精确 SHA 全量 Actions 通过后才认定代码层验收。

## 2026-11-15 Windows 测试分层修正（候选 CI 待验）

- `a4b8418` 的 Windows 新测试最初误放在共享的 `tests/unit/test_node_agent_executor_runtime.py`，使部分仅安装轻量控制面依赖的 Remote Cleaning/Portable Deployment Windows 工作流意外 import `AgentTrainingRunner`，触发缺少 `PyYAML` 的测试导入错误；另有一个训练测试漏写 `import os` 导致 Ubuntu 两个 NameError。**均为测试归属/导入问题，不应给不使用训练的工作流添加依赖，也无需改运行时代码。**
- 随后 `e461737` 已补上训练测试的 `os` 导入。本提交进一步将 Windows 持久进程身份证据的两项回归分别迁到 `test_node_agent_training_runtime.py` 和 `test_node_agent_conversion_runtime.py`，共享 `test_node_agent_executor_runtime.py` 恢复纯轻量控制面合同。两类任务在 Windows 检查 ready=False、保留 PID+generation、拒绝无证据目录清理。
- 代码运行时保持 `a4b8418` 的 Windows 恢复 fail-closed 策略不变；全量 Windows/Ubuntu Actions 必须以**本提交精确 SHA**重新核实。生产仍 NO-GO。
