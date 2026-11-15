# 畅联云算法训练平台｜P0-01C 远程 Agent 可信停机证明：现状、技术方案与新会话交接

> 更新：2026-11-15（Asia/Singapore）  
> 仓库：[`jorsamj/aixunlianpingtai`](https://github.com/jorsamj/aixunlianpingtai)  
> 唯一允许开发/推送的长期分支：`feature/external-algorithm-publishing`  
> **本页核对的最后业务代码 HEAD**：[`e515ce78523e76d9acf6afdc42e049993aee24ad`](https://github.com/jorsamj/aixunlianpingtai/commit/e515ce78523e76d9acf6afdc42e049993aee24ad)  
> 本次只新增/链接文档，**文档提交不能冒充业务代码完整 CI 通过**。  
> 生产状态：**NO-GO**；未获授权不得部署、重启、改生产数据或开启自动派单。

## 1. 一句话背景与业务边界

平台正在从单服务器训练演进为 **中央唯一调度 + 多 Node Agent 分布执行**：以统一任务库、唯一任务 owner、assignment/execution lease、attempt/generation、Node Token、HTTP 远程通信完成训练、模型转换、素材与其他任务的统一派发，未来支持可配置的 OSS/S3/NAS 存储和 A800/双4070 等不同硬件节点。

关键问题：**中心判定远端 Agent 的租约过期，不等于原机器的 GPU/SDK/数据加载子进程已停止**。盲目 `RUNNING -> QUEUED` 或 `CANCEL_REQUESTED -> CANCELLED` 会让两个节点并发执行同一任务、重复占用 GPU、导致错误结果和资源争抢。即使旧 generation 的中心 API 写入被拒，失联的旧进程依然可能消耗资源。

因此 P0-01B/P0-01C 当前采用 **fail-closed**：原节点执行情况未知时，保留 `recovery_blocked_remote_agent_unverified` / `REMOTE_AGENT_STOP_UNVERIFIED`、旧任务 owner、GPU 预留和磁盘进程证据；不自动解除 HOLD / 不重派。**这是一项止损措施，不是自动恢复功能。**

## 2. 精确代码与 CI 基线（不要把不同 SHA 混用）

- 最后已确认**完整 27/27 成功**的业务代码提交：`9caf13b07912d6e6d8f258292ea6f11bbcdd4cb5`（前端 browser-navigation(3) 首轮失败后，失败 Job 定向 rerun attempt 2 SUCCESS）。这是历史基线，不代表后续 Windows 改动已通过。
- Windows 持久 PID 恢复加固提交：[`a4b8418`](https://github.com/jorsamj/aixunlianpingtai/commit/a4b84180c196469091bb07e89a025425df449820)。首次 CI 暴露**测试代码**问题：训练测试漏 `import os`；共享 Node Executor 测试反向导入训练模块，使部分 Windows 轻量工作流缺 `PyYAML`。失败不应归咎于生产行为，也不能无脑加依赖。
- 测试导入修正：[`e461737`](https://github.com/jorsamj/aixunlianpingtai/commit/e461737773af2548c5daf305e3aa1d16936b8448)。
- 测试职责迁移及最新业务代码 HEAD：[`e515ce7`](https://github.com/jorsamj/aixunlianpingtai/commit/e515ce78523e76d9acf6afdc42e049993aee24ad)。Windows 恢复用例分别移至训练/转换专项测试，不再污染共享 Node Executor 合同；**没有修改运行时安全机制**。
- 2026-11-15 文档撰写时，`e515ce7` 的 27 项 GitHub Actions **19 SUCCESS、0 FAILURE、8 IN_PROGRESS**（仅此时点快照；在新会话里必须重新调用 GitHub 查询准确 HEAD、SHA、全部 workflow/job conclusion）。核心 Push 中 Remote Cleaning、Portable Deployment 全绿，Node Agent Ubuntu/API 已成功；Windows 与 Remote Training/Conversion 的剩余任务需最终核实。
- 固定审计入口：[Issue #26](https://github.com/jorsamj/aixunlianpingtai/issues/26)（远程调度/可信恢复）；[Issue #27](https://github.com/jorsamj/aixunlianpingtai/issues/27)（独立前端浏览器不稳定问题）；原专项文档 [`AGENT_REMOTE_RECOVERY_FAIL_CLOSED_P0_2026_11_14.md`](AGENT_REMOTE_RECOVERY_FAIL_CLOSED_P0_2026_11_14.md)。

**注：** 如果下一轮仅提交本交接文档、而 GitHub 未触发完整业务 CI，应记录“最新文档 HEAD”和“已验证业务代码 SHA”两个值，绝不能将文档 SHA 与业务 CI 验证 SHA 混为一谈。

## 3. 已完成能力与主要提交脉络

| 提交 | 已有可验证保护或测试 | 局限 |
|---|---|---|
| `1baebfd9` | 训练/转换启动子进程前写 `process-launch-intent.json`，崩溃窗口内未知进程不接新任务 | 单有标志不是停止证明 |
| `977e098` | 转换主进程退出后再次核验/回收子进程组，不能先发布结果后确认旧子进程是否结束 | Windows 不具备 Job Object 级整体核验 |
| `18dd4d9` | 训练、转换共享 Workdir 内**任意**未知启动危险标志均阻断两种计算 Runner | 可能导致不同任务种类共享 GPU 的保守阻断 |
| `4173375` | GitHub Linux 真 `SIGKILL` 故障注入：spawn 已发生、PID 身份未持久化，训练/转换 **2/2 通过** | 单机合成 CPU 进程；不代表真实 GPU/多主机 UAT |
| `e049b05` | 非有限 `create_time`（NaN/Infinity）不能用于持久进程身份或 PID 核验 | 仍需防 PID/PGID 复用 |
| `d7d252e` | POSIX 启动危险标志的目录链 `fsync`；同步失败禁止继续 launch | 不替代可信进程容器；Windows 不具等价保证 |
| `9caf13b` | 通用 `cleanup` 禁止删除仅剩 `process-identity.json` 的工作目录 | 历史记录必须先可信清除，可能持续 HOLD |
| `a4b8418` | Windows 训练/转换 Agent 初始化发现历史 PID 身份时，不 ready、不删身份、不接新计算 | 正常退出未用 Job Object 管控；没有自动释放 HOLD |
| `e461737`、`e515ce7` | 对应测试导入/职责分离 | 当前 SHA CI 需要重新精确核对 |

已存在的中心防重复执行保护包括：`TaskRepository/FencedTaskRepository`、`BEGIN IMMEDIATE` 事务、任务 lease/generation fencing、Node Token 与中央唯一分配器；`CHANGLIAN_AGENT_AUTO_ASSIGN_ON_CLAIM` 缺省为 **OFF**，不得为验收便利开启。中央只读诊断 `remote_recovery_diagnosis` 返回 `stop_proof_verified: false`，**没有受认可的自动止停证明提交/原子恢复协议**。

## 4. 关键源码导航（新会话应先读原代码）

| 位置 | 重点审计 |
|---|---|
| `platform_core/task_runtime/process_control.py` | `launch_process`、`ProcessController.inspect / terminate_tree / _terminate_posix_group`：PID 创建时间及命令 hash、POSIX session/group、Windows `CREATE_NEW_PROCESS_GROUP` |
| `platform_core/node_agent_executor_runtime.py` | `AgentExecutionWorkdir.begin_process_launch / _sync_launch_intent_directories / persist_process_identity / list_unverified_process_launch_intents / cleanup` |
| `platform_core/node_agent_training_runtime.py` | `AgentTrainingRunner._recover_persisted_processes`、spawn→identity→monitor→strict terminate 流程 |
| `platform_core/node_agent_conversion_runtime.py` | `AgentConversionRunner._recover_persisted_processes`、转换结果上报前子进程停止核验 |
| `platform_core/node_agent_executor_loop.py`、`node_agent.py` | 真实 Runner readiness / effective capabilities；同一共享 Workdir、claim/start 边界 |
| `platform_core/task_runtime/repository.py` | `_release_expired_in` 远端 STOP_UNVERIFIED HOLD、resource_key/预留保护 |
| `platform_core/agent_execution.py` | `remote_recovery_diagnosis`、Node Token、generation、result/finish 真实性 |
| `platform_core/task_node_assignments.py` | 中央唯一分配、explicit Agent、portable contract、默认自动派单 OFF |
| `tests/integration/test_agent_launch_sigkill.py` | 已有 Linux 真实进程 SIGKILL 竞态测试；不得误称真正的 GPU/多机测试 |
| `tests/unit/test_node_agent_training_runtime.py`、`tests/unit/test_node_agent_conversion_runtime.py` | Windows 重启 fail-closed 与 Linux 正向恢复分平台断言 |
| `.github/workflows/node-agent-executor.yml` 等 | Ubuntu+Windows 专项合同、完整 CI workflow/job 终态 |

特别说明：**Windows** `terminate_tree` 在主进程已不存在时调用的 `_terminate_posix_group` 实际会直接返回。这不等于所有 SDK/DataLoader 后代停止；当前 Windows 重启路径已保守拒绝清理，但还未实现运行期 Job Object。

## 5. 下一阶段决策：先做可信 OS 执行边界，再做中心恢复接口

**优先级 P0-01C-1：收口已提交代码的 CI，停止额外功能叠加**

1. 先重新读取长期分支 HEAD。若 HEAD 是文档提交，找到最后业务代码 SHA `e515ce7` 的全部 27 项工作流；查实 Node Agent、Remote Training/Conversion、Windows、Linux、Frontend 的最终 conclusion，任何 failure 只定位失败 Job，不修改无关代码。
2. 若测试未全绿：保留失败日志、准确测试名称和是否可重复；修复后只推送长期分支，重新按新 SHA 验收，严禁以历史成功代替本次结果。#27 前端项目清空后草稿不清、1920×1080 训练弹窗滚轮失败仍单独跟踪，不把它们当 Agent 安全失败。
3. 此时仍不能部署，不能新增 `stop-proof VERIFIED` 虚假状态。

**优先级 P0-01C-2：Linux cgroup v2 / systemd 执行隔离专项，先做只读可行性与隔离故障测试**

- 在**非生产、独立测试环境**审计运行账户、cgroup v2 统一层级、systemd scope/service 权限、是否可委派子 cgroup、cgroup.procs / cgroup.events / cgroup.kill 的实际能力。4070 将来应在 `changlian4070` 非 root 运行，不能偷用 root 绕过权限。
- 针对每个 `task_id + generation + node_id` 设计独立、不可串用的 OS 任务边界。必须在真实计算开始**之前**完成边界创建和进程归属，证明 SDK/DataLoader 后代受管；Agent 在分配进边界之前硬死时不可留可计算的逃逸进程。
- 在信任链充分时才能用对应 cgroup 的 `populated=0` 作为一个停止证据；**先证明是本任务的 cgroup，才能读取空值**。cgroup 路径不存在、权限不足、改属、宿主重启、记录损坏、无法验证是否逃逸均为 UNKNOWN/HOLD，不能默认成功。
- 首轮只做独立最小 PoC/合同：正常退出、Agent SIGKILL、中途拒绝归属、孤儿子进程、PID/PGID 重用、断网、状态篡改；真实 cgroup 不可用的 CI 环境必须明确 skip/blocked，不能靠 mock 冒充真实内核证据。
- 通过之后才将 Linux Agent 计算进程接入该边界。避免大规模重构、另建 Scheduler 或修改现有统一 DB owner。

**优先级 P0-01C-3：Windows Job Object，独立专项**

- 使用微软原生 Job Object 进行全子孙生命周期约束，评估 `CreateJobObject`、`AssignProcessToJobObject`、`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`、可逃逸/嵌套 Job 的实际行为；应考虑子进程在加入 Job **之前**启动的竞态，因此需要暂停启动/先绑定后放行或等效可靠方式。
- 测试 PID leader 消失但后代存在、Agent crash、Job 句柄被关闭/复用、系统重启、无权限、GPU SDK 派生子进程。没有通过之前继续保持 Windows 历史 PID fail-closed，不自动清除证据。
- Linux 和 Windows 的可证明能力要**分别标记准入**，不可用 Linux 测试代替 Windows 证明。

**优先级 P0-01C-4：中央一次性 stop-proof challenge + SQLite 原子放行（严格后置）**

- 由中央向**原 Node** 签发短期、一次性挑战，证明严格绑定 task_id、project_id、kind、attempt/generation、worker_id/node_id、boot/session、OS 容器身份、证据摘要和有效期；Node Token 单独不能证明进程停止。
- 只有执行边界完整、原节点可验证、证据与中心旧任务完全匹配，并经过并发测试，才在 `BEGIN IMMEDIATE` 中一次性消费挑战并清理旧 owner/旧 GPU reservation；根据 RUNNING/CANCEL_REQUESTED 决定安全重排或终止。重复证明、跨节点、跨代、伪造/过期证明必须拒绝。
- **如果系统没有证明原节点所有计算进程停止的能力，中央 HOLD 不得自动解除**。必要的手工程序必须通过授权的基础设施级停机证明、审计与双人确认，而不是前端“强制重试/清空 PID”按钮。

**优先级 P0-01C-5：真实多节点 UAT 后才考虑生产**

- 两台独立物理机的真实训练/转换 GPU/SDK 负载：断网、Agent SIGKILL、Linux OOM、子进程逃逸、重启、租约过期、重连、旧 token 上传及竞争新任务；验证无双执行、无资源重复放行、无不可信产物发布。
- 同时单列 OSS/NAS 配置式存储、训练输入和结果回传、真实资源调度容量/多 GPU、10k 队列和 SQLite 争用 P95 压测验收；不能拿 GitHub 模拟测试冒充真实 A800/4070 性能。
- 生产部署只可在单独获得明确授权、备份/回退/灰度准备完善、无活跃任务受损风险时进行。

### 5.1 官方参考（设计依据，不等于代码验收）

- [Linux Kernel: Control Group v2](https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html)：`cgroup.events populated` 的含义、`cgroup.kill`、控制器/权限与委派。**空 cgroup 只说明该层级内当前无存活进程，不证明没有逃出该层级的进程**。
- [Microsoft: Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)：作业统一生命周期、`KILL_ON_JOB_CLOSE`、breakaway 与嵌套行为。
- [Microsoft: AssignProcessToJobObject](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-assignprocesstojobobject)：绑定行为、权限和运行前后限制。

## 6. 明确不在本专项混做的事项

- #27 前端训练草稿清空状态、滚轮异常：保留独立专项，不把 UI Flaky 用作 Agent 安全验收依据。不要通过延长超时/移除断言粉饰根因。
- `app.py`、`static/app.js` 巨型单文件治理、Vue 重写、MySQL/Redis 迁移：与 P0-01C 可信停止证据无直接关系，除非证明必须，否则不做。
- 20 万素材分页/批量选择、AI 标注审核、OSS/S3 存储策略、多 GPU 自动配置、P0-03 容量准入：维持已有合同，后续另立里程碑，不顺手重构。
- A800 生产取消异常与 PID create_time mismatch、8GB 残留素材副本：属于独立生产事故/部署专项，**不因为开发分支修复就宣称生产已解决**；涉及生产处理须先授权且保留现场证据。

## 7. GitHub 与生产操作硬约束

- **唯一可写分支：`feature/external-algorithm-publishing`**，每次更改前先读取最新远端 HEAD，禁止强推、合并 main、创建 Release 或重写历史。
- 先审计/复现/补 RED 负面用例，再实施**最小范围**修复，跨 Linux/Windows CI、API/HTTP/前端相关回归；按精确 SHA 记录 commit、工作流成功/失败/取消/排队状态。
- 不在 Agent 本地直接连中央 SQLite，不加第二个 Scheduler/TaskQueue owner，不删除无法证实安全的 PID/训练副本；不将租约过期、`active_tasks=[]`、Node ONLINE、原 PID 不存在、旧 `PGID` 为空、cgroup 路径消失当作独立可信停机证明。
- 未明确授权时绝不连接/修改生产 A800、4070，不能停服、重新启动任务、改 GPU 推理路由、清理训练副本、变更数据库/OSS、开启自动派单；**自动派单缺省 OFF**。
- 业务用词为“算法训练平台/服务、物联中台”，不要擅自改成监狱专用平台或新架构。

## 8. 新会话的第一个实际任务与验收输出

**第一次回复必须先做只读核实而非直接写 cgroup/Job Object 代码**：
1. 重新确认 HEAD 和最后业务代码 SHA，逐项提取准确 CI workflow/job 终态；如已有失败，读真实日志给根因。
2. 对照本页第 4 节实际读取 Node Agent、训练/转换 Runner、process_control、Repository 与现有测试，确认 `a4b8418` Windows 恢复门槛仍有效且旧版行为无回归。
3. 给出 Linux cgroup v2/systemd 与 Windows Job Object **两套最小设计的前提、权限和风险**，优先 Linux 可测试的隔离验证；不要让服务以 root 运行。
4. 先把只读核查结果与最小实施计划写入 #26 或专项文档；只有明确的安全修复、可复现故障和 CI 合同后再开发；默认不做中心自动解锁。
5. 输出准确 SHA、测试数、异常/阻塞、后续依赖用户的事项（如物理机、真实 GPU、网络断连 UAT）与 **GO/NO-GO**。文档提交与代码验收状态必须分开记录。

---

**交接结论**：当前最重要的不是“再加更多调度按钮”，而是补齐**每代任务的 OS 可信执行边界与退出证明**。在此之前保持远端不明任务 HOLD、远程自动派单 OFF、生产 NO-GO；已获 GitHub Actions GREEN 的仅是对应 SHA 的代码保护与隔离测试，不能推导为真实生产安全上线。

## 9. 2026-11-15 续审索引：P0-01C-2A/2B 实际 PoC 与仍未完成的验收

> **本节晚于第 2 节历史交接快照；若数字冲突，以准确 SHA 的 GitHub Actions API 最新查询为准。**
>
> 本轮所有改动严格在 `feature/external-algorithm-publishing` 的 `tools/poc`、`tests/unit`、`.github/workflows/node-agent-executor.yml`、docs；**未改业务训练/转换 Runner、中央 owner/租约/SQLite、任何生产服务或配置**。

- 上一阶段业务代码 `e515ce7`：**27/27 workflow completed SUCCESS**；历史 docs-only `e22662e`：**22/22 SUCCESS**。这两个数字都**不是本次新增 PoC 代码 CI**。
- 本轮完成：Linux cgroup v2/systemd 非 root **只读能力预检工具** `tools/poc/linux_cgroup_probe.py`；需显式 `--run --isolated-test-host` 才会进入的 **隔离 CPU/systemd transient user service PoC** `tools/poc/linux_cgroup_poc.py`；新增 **12 个便携合同**（`tests/unit/test_linux_cgroup_poc_contract.py`）；已接 Node Agent Ubuntu/Windows CI 的纯合同 step。
- 本地隔离容器：`python -m py_compile` 成功；**12 passed**；probe 确认 cgroup v2 可读但当前为 root、缺 user bus/user manager，所以真实 transient service 内核 PoC **BLOCKED_ENVIRONMENT**。这不代表真实 Linux OS 停机证明通过。
- PoC 入口检查非 root、随机 unit 命名、测试 manifest/boot ID 和 payload 当前 cgroup；停机前须匹配 `Id + ControlGroup + InvocationID`；只有 cgroup `populated=0` 且已知测试父/子 PID+启动 tick 都已不在执行才允许**本地 PoC**返回 `LOCAL_CGROUP_POC_PASS_NOT_CENTRAL_STOP_PROOF`。权限/身份不符、PID 复用、unit/cgroup 被 systemd 回收均 UNKNOWN/HOLD；尚无法证明未知后代永不逃逸。
- 新增 PoC 合同准确代码提交：`675b4e538134d9553209db72a4c68bf9f25e42fa`；核查时其 23 个 GitHub Actions **全部 queued**，无实际 Job 日志、不能宣称 GREEN；随后 docs 另有提交，仅用于进度记录。排队根因尚未证实，不盲重跑。
- **下一步**：先取精确 SHA 的最终 CI，随后才在经确认的**非生产、非 root、有 user manager 的 Ubuntu 22.04 隔离机**做真实 CPU cgroup PoC，记录 unit GC/进程逃逸失败场景，再决定是否进入 Linux Runner adapter。Windows Job Object、中央新鲜挑战 + SQLite 原子恢复和真实两物理机 GPU UAT 继续独立待办。
- **完整审计与手册**：[`P0_01C_2_LINUX_SYSTEMD_EXECUTION_BOUNDARY_POC_2026_11_15.md`](P0_01C_2_LINUX_SYSTEMD_EXECUTION_BOUNDARY_POC_2026_11_15.md)。Issue #26 继续追踪可信恢复；Issue #27 仍独立追踪前端回归。
- **生产 NO-GO**；`CHANGLIAN_AGENT_AUTO_ASSIGN_ON_CLAIM` 继续 OFF；不得删除 PID/启动证据、跳过 HOLD、把 `stop_proof_verified` 改成 true、触及 A800/4070 生产服务或数据。

## 10. 2026-11-15 08:50+08 续审：前端滚动 CI 精准修复、完整 22/22 验证

> 本节为 **P0-01C Agent 可信停机专项的并行前端回归记录**，不是新的 Agent stop-proof 能力。早期章节中的“前端有红灯/CI 排队”是历史快照；**本节记录准确代码 SHA 的最新完整终态**。

### 10.1 历史失败与只读审计

- 历史仅文档 HEAD `6c97817db45855548b8cb8ddf16d3c9d7f7b7178` 的 GitHub Actions 共 **21 success / 1 failure**；唯一失败为 [Frontend Runtime Stabilization run 43654112610](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43654112610) 的 `browser-navigation (3)`；该 run 的 `frontend`、`browser-navigation (1)`、`browser-navigation (2)` 均 success。
- 真正失败栈：`tests/browser/training-create-scroll.spec.mjs:43`，1920×1080，向 `.train-create-layout` 发送 `wheel(0,400)`，5 秒内 `scrollTop` 仍为 0，断言 `toBeGreaterThan(0)` 失败；**不是 Agent/任务调度/SQLite 的失败**。
- 只读核对 [`static/training-create-modal.css`](../static/training-create-modal.css)：训练创建弹窗对 `.train-create-layout` 已使用 `overflow-y:auto`、有界 modal 高度、`min-height:0` 等单一滚动所有者约束；但原始测试在 7 个参数分组**折叠**的高桌面分辨率下，**没有事先检查实际 `scrollHeight > clientHeight`**。如果内容完全放入可视高度，`scrollTop=0` 是浏览器正常行为。此根因由测试前置条件和失败证据支持；无法仅凭旧失败日志反推 CSS 本身存在故障。

### 10.2 唯一代码修改（不动业务 CSS/JS）

- 提交 [`98f91585f2c976f9321507d6ab812796a94bbea0`](https://github.com/jorsamj/aixunlianpingtai/commit/98f91585f2c976f9321507d6ab812796a94bbea0)；GitHub commit changed files 真实核实仅 **`tests/browser/training-create-scroll.spec.mjs` 1 个文件**。
- 测试首先采集 `clientHeight / scrollHeight / scrollTop / overflowY`。若高桌面布局暂未溢出，**实际点击可见的训练参数 `details > summary`**，逐步展开当前步骤的参数，直到确认真实可滚动；如果全部展开仍无溢出，测试继续失败而非跳过。
- 保留原先的两项强断言：向下真实鼠标滚轮后 `scrollTop>0`、向上真实滚轮后 `scrollTop=0`；并要求 `overflowY=auto`。
- 轮滚前记录鼠标坐标和 `document.elementFromPoint` 命中节点及其祖先的 `overflowY`，通过 Playwright `testInfo.attach` 保存 `training-scroll-<viewport>.json` 证据；回归完成后恢复本次临时展开的参数分组，再执行原有训练参数输入/状态保存断言。
- **不涉及** `static/app.js`、`static/styles.css`、`static/training-create-modal.css`、后端进程、生产部署、Node Agent、数据库或 GPU 作业。

### 10.3 精确 CI 终态：完成

**针对代码 SHA `98f91585f2c976f9321507d6ab812796a94bbea0` 查询 GitHub Actions，最终结果为 `22 success / 0 failure / 0 cancelled`（22/22 GREEN）。**

本轮最相关 [Frontend Runtime Stabilization Push run 43660420636](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43660420636)：

| Job | 结论 |
| --- | --- |
| `frontend` | SUCCESS |
| `browser-navigation (1)` | SUCCESS |
| `browser-navigation (2)` | SUCCESS |
| `browser-navigation (3)` | **SUCCESS**，覆盖原失败的 1920×1080 训练弹窗滚动场景 |

确认范围：**代码 SHA 的整套 CI 已全绿**；并不等价于在真实 A800/4070 环境运行过 Chrome、也不等价于所有前端 UX 需求都已经完成。Issue [#27](https://github.com/jorsamj/aixunlianpingtai/issues/27) 历史记录的另一问题（项目真实清空后训练草稿未同步清空）**不在本次改动范围**，需单独按原事件时序核验，不能因本轮 CI 绿色就声称其根因已修复。

### 10.4 后续专项与安全约束

- **前端滚动测试本轮收口**：无失败证据不得额外修改生产 CSS；若后续 CI 再次复现，先读 `training-scroll-<viewport>.json` 和 Playwright trace，区别真实滚动故障、未溢出和滚轮命中内层元素。
- **P0-01C 未收口**：Linux cgroup v2 / systemd user manager 的真实内核 CPU PoC 仍因当前隔离容器非 root 条件/user manager 缺失而 **BLOCKED_ENVIRONMENT**；下一步需**非生产 Ubuntu 22.04** 且可用非 root systemd user manager 测试机，先做真实进程 SIGKILL、跨进程组后代、unit 身份和停机审计，再决定是否接入 Runner。
- **中央 fail-closed 继续**：`REMOTE_AGENT_STOP_UNVERIFIED` HOLD 不释放，旧 owner/GPU reservation 不乱动，`CHANGLIAN_AGENT_AUTO_ASSIGN_ON_CLAIM` 默认 OFF，Windows Job Object、中央 challenge/SQLite 原子恢复、双物理节点 GPU UAT 继续待办。**生产 NO-GO。**
- Issue #26 追踪 Agent stop-proof；Issue #27 追踪前端历史 CI 问题。后续文档追加会形成新的 docs SHA，其 Actions 状态必须另查；**不得把本节 22/22 自动套用于新的 docs HEAD**。

## 11. 2026-11-15｜无需额外实验服务器：GitHub-hosted Ubuntu 22.04 真实内核验证结果

> **这是最新的 P0-01C-2B 实验状态**，比第 9～10 节中“仅本地合同通过 / 无独立测试机”更晚。GitHub-hosted `ubuntu-22.04` 是独立临时 VM（**不是** self-hosted 生产服务器），合成 CPU-only workload；用户没有独立非生产主机也能完成首轮 OS 行为试验。

- 独立 CI：[`agent-kernel-stop-poc.yml`](../.github/workflows/agent-kernel-stop-poc.yml)，只允许 GitHub 托管 Ubuntu 22.04、`contents: read`、非 root systemd user unit、随机名/短时合成 CPU 任务、自动证据附件。**生产 A800/双4070、真实 GPU/数据库/OSS/任务一概未操作**。
- **真实第一轮**：[run 43661539327](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43661539327)：Ubuntu 22.04 / systemd 249 / cgroup v2；`membership_verified=true`、模拟 Agent launcher `SIGKILL=true`、后代进程在 launcher 消失后仍存活、`systemd_stop_returncode=0`、`known_processes_stopped=true`；但无法在 stop 后重新读取原 cgroup `populated=0`，`cgroup_empty_verified=false`，**HOLD / job failure**。
- **真实第二轮**：[run 43661732962](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43661732962)：在 stop 前预先打开并绑定原 `cgroup.events` 句柄；**14/14 合同测试通过**；相同的真实 OS 启动器崩溃、计算后代存活、systemd 停止、已知 PID 退出结果再次得到；但 stop 后 `cgroup_path_after_stop=null`、`cgroup_handle_after_stop=null`，无 `populated=0` 正向证据，故仍 **HOLD / job failure**。
- **重要结论**：不需要另买服务器，真实 Linux 内核已开展测试；当前可证明的是“本实验中已知 CPU 进程停止”，**不能证明**所有可能的未知计算后代都停止、更不能签发可供中央解除 `REMOTE_AGENT_STOP_UNVERIFIED` 的可信证明。systemd unit/cgroup 停止后回收窗口需要事件级取证；`null`/路径消失不得转成 `True`。
- **下一步**：优先继续用 GitHub VM 隔离复现 `cgroup.events` 停机之前的状态变化、unit D-Bus `InvocationID` 与异步 GC 时序，再增加更多反例；通过后才评估 Linux Runner adapter。Windows Job Object、中央 challenge/SQLite 原子恢复、真实双 GPU 节点 UAT 仍待验；继续自动派单 OFF、保持 HOLD 和生产 **NO-GO**。
- 详细代码、实际输出和风险见 [`P0_01C_2_LINUX_SYSTEMD_EXECUTION_BOUNDARY_POC_2026_11_15.md`](P0_01C_2_LINUX_SYSTEMD_EXECUTION_BOUNDARY_POC_2026_11_15.md) 第 10 节。

## 12. 2026-11-15 追加重要里程碑：GitHub VM 首次真实捕获 `cgroup.events populated=0`

**本节为最新 01C-2B 内核 PoC 进展。用户不需要额外购买独立测试服务器。**

- 第一、二轮真实 Ubuntu 22.04 [43661539327](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43661539327)、[43661732962](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43661732962) 已证明 Agent launcher SIGKILL 后，systemd 可停掉 PoC 中已知 CPU 子进程，但停机完成之后读取原 cgroup `populated=0` 因路径/FD 不可读而失败，按设计 HOLD。
- **第三轮真正成功**：GitHub-hosted CPU-only [run 43662224850](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43662224850)；准确 SHA `e39d644b0acbdb36bf18faf3aa87e681367ef51a`，14/14 合同成功、`linux-cgroup-22` SUCCESS。新增 `CgroupEventObserver` **在 systemctl stop 之前**订阅原 cgroup.events FD 的 `poll(POLLPRI|POLLERR)`，记录先 `populated=1`，随后 mask 10 通知 `populated=0`；已知父子进程不再执行，`LOCAL_CGROUP_POC_PASS_NOT_CENTRAL_STOP_PROOF`。停机后原 cgroup 目录和 FD 可继续不可读，**事件在回收前已被可靠采样**。
- 因存在“停机请求发出之前 cgroup 就已为空”的误判风险，后续又收紧 `arm_stop()`：要求发出 stop 前明确 `populated=1`，否则不放行，扩展至 19 项负面合同。中间试验有单条测试错误（关闭文件后再调用 `fileno()`，属于测试代码），在最新测试提交 `218d6c4736f387d20529e48421af22cb4c3eabca` 精准修复；其目标 [run 43662765705](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43662765705) 在本节写入时尚未拿到终态，**不能声称最新版本已 GREEN**。
- **影响范围**：`tools/poc/linux_cgroup_poc.py`、`tests/unit/test_linux_cgroup_poc_contract.py`、独立 GitHub-hosted CPU 工作流，以及 docs。未改正式训练/转换/中央调度/SQLite、生产 A800/双4070 或 GPU、OSS。
- **剩余门槛**：严格代码版 19 合同 + 内核复验；多层子孙、cgroup 外迁/进程权限、unit 重用、启动 generation/boot 证据、Windows Job Object、中央新鲜 challenge/SQLite 原子恢复，以及物理 GPU/多节点 UAT。**现阶段不可接入生产 Runner，不可解除 `REMOTE_AGENT_STOP_UNVERIFIED`，自动派单 OFF，生产 NO-GO。**
- 详细证据、版本和下一轮最小任务见 [P0-01C-2 专项文档第 11 节](P0_01C_2_LINUX_SYSTEMD_EXECUTION_BOUNDARY_POC_2026_11_15.md)。GitHub run/link 的精确 SHA 比文档 HEAD 更重要；文档提交自身须独立核验 CI。

## 13. 2026-11-15 10:09+08｜多层子进程真实停机 PoC 两次成功

> 本节为最新工作交接信息；不改变本项目**唯一长期分支**、中央 fail-closed HOLD 和生产 NO-GO。

- 新反例不是单层 sleep：`service main → child → grandchild`，child、grandchild 分别 `start_new_session=True`；使用 `/proc/<pid>/stat` 的实际父 PID、PID 启动 ticks、`os.getsid`、原 cgroup 路径逐一校验。随后单独 SIGKILL stand-in Agent launcher，要求 child 与 grandchild **均仍在运行**，才由 systemd user unit `KillMode=control-group` 停止；所有已知进程必须退出并监听 `cgroup.events populated=0`。没有改生产 Agent。
- **实测 Ubuntu 22.04 成功两次**：[run 43666636076](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43666636076) 对应代码 `29ea40de32e2540e1433509007254445149a0c06` 和 [run 43666680688](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43666680688) 对应代码 `2ff6242543e69dededbcb2eaf4ea6112256d9380`：均 **19/19 便携合同 SUCCESS**、真实内核 Job SUCCESS、`three_process_sessions_bound=true`、`both_descendants_survived_launcher=true`、`known_processes_stopped=true`、`cgroup_empty_verified=true`。均明确 `stop_proof_verified=false`，不允许中央恢复。
- **额外严格负面合同**：防止空组后又 `populated=1` 仍判成功；校验生成的 Python 子进程脚本可编译、虚假父子关系、PID reuse、失去原 cgroup、session 不独立以及缺失孙进程身份。对应最新代码 SHA `4216be9ce011cf617e3af5ca741537386fef621e`，合同由 19 扩展至 **24 项**；其 GitHub-hosted [run 43666716976](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43666716976) 在本节提交时仍 queued，**不可提前宣称最新 SHA 的 24/24 和 kernel 终态通过**。
- 独立前端回归：`218d6c4` 的浏览器失败是 `tests/browser/annotorious-poc.spec.mjs:48`、`createAnnotation` 事件 5s 仍未观测到，已单独留痕 Issue #27；**不是 Node Agent 失败**。
- 本轮仅改 `tools/poc/linux_cgroup_poc.py`、`tests/unit/test_linux_cgroup_poc_contract.py` 和 docs，所有系统运行命令均仅在 GitHub-hosted **临时 VM**。未操作 A800、双4070、GPU、OSS、真实训练/转换任务、生产数据库、Web/Worker。
- **下一步**：精确读最新 24 合同与真实内核 run 的最终状态；失败只根据 Job 日志修复。通过后才进入 execution generation + boot_id + unit InvocationID 绑定以及迁移/重用反例，最后才评估 Linux Runner adapter、Windows Job Object、中央一次性 challenge 和 SQLite 原子恢复。继续 `REMOTE_AGENT_STOP_UNVERIFIED` HOLD、`CHANGLIAN_AGENT_AUTO_ASSIGN_ON_CLAIM` OFF、生产 NO-GO。
- 全量证据与细节：[P0-01C-2 Linux systemd PoC 专项文档第 12 节](P0_01C_2_LINUX_SYSTEMD_EXECUTION_BOUNDARY_POC_2026_11_15.md)；Issue #26 为中央可信停机进度。

## 14. 2026-11-15 10:09+08｜防错代复用：task/generation/boot/nonce/systemd InvocationID PoC

> 最新接续：独立 CPU PoC 已可以验证真实三层跨 session 后代停机，24/24 安全合同及 Ubuntu 22.04 内核 PoC 已在 [run 43666716976](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43666716976) SUCCESS。本节是其后的**执行实例身份绑定**专项，状态独立。

- **背景风险**：仅凭 `populated=0` 和同名 systemd unit，无法阻止把旧任务 generation 或旧 Linux boot 的停机事件挪用给新任务。
- **只改 `tools/poc/linux_cgroup_poc.py`**：先生成随机 synthetic task ID、测试代数 `execution_generation=1`、boot ID、随机 nonce、随机 unit；systemd 服务 payload 从官方 `INVOCATION_ID` 读取每次运行独立的 128-bit hex 身份，写进 `ready.json`。只有 `intent + ready + unit_info + 实时 boot_id` 全部匹配，才会模拟 Agent 异常并执行原 unit 的 stop。发 stop 前再次核验原始和当前快照，任何跨代/重启/替换保持 HOLD。
- **新增 7 项负面合同**，总数 **31**；覆盖旧 execution generation、bool 代数绕过、boot ID 不符、systemd InvocationID 替换/缺失、task/nonce/unit 错配、前后证据发生变更和字段损坏。代码 `7a6cbf5e85a010a0930a0a4f650c579bb5342b87` + 合同 `cad6a3365bb715794f1a30bc1429f1855293d57e`。
- **CI 未宣告成功**：上述新代码准确 SHA 对应 [GitHub-hosted ubuntu-22.04 run 43667494312](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43667494312)，更新本节时还处于 GitHub 队列，尚未取得 31/31 和真实内核身份绑定通过。不得引用旧 24/24 成绩冒充本次结果。
- **真实验收门槛**：31/31、`identity_binding_verified=true`、三层 CPU 后代原 cgroup 和 PID/start_ticks、启动器 SIGKILL 后继续运行、systemd stop 成功、原 FD 读到 `populated=0`、已知三进程结束。仍要求 `stop_proof_verified=false`、`central_recovery_allowed=false`、`LOCAL_CGROUP_POC_PASS_NOT_CENTRAL_STOP_PROOF`。
- **不是中央协议**：PoC 代数恒为 1，尚无中央真实单调 generation、挑战凭证、加签或 SQLite 原子事务；不能凭本地 PoC 的 JSON 释放真实 owner/GPU reservation。下轮先对现有中央租约与 generation 数据合同做只读审计，再设计比对与原子恢复。
- **严格边界不变**：无生产 Agent、Remote Training/Conversion Runner、A800、双4070、GPU/OSS、用户服务/真实数据库变更；`REMOTE_AGENT_STOP_UNVERIFIED` HOLD、自动派单 OFF、生产 **NO-GO**。
- **完整技术文档**：[P0-01C-2 Linux systemd 执行边界 PoC 第 13 节](P0_01C_2_LINUX_SYSTEMD_EXECUTION_BOUNDARY_POC_2026_11_15.md)。

### 14.1 本会话追加：中央现有 generation/lease 真相已只读核实

前述“下轮审计中央代数”已完成一轮只读代码核查（无生产数据库读取/写入）：
- **真执行代数** = `tasks.attempt`，由 `platform_core/agent_execution.py` 在中央 `BEGIN IMMEDIATE` 执行 `QUEUED -> RUNNING` 时 `attempt=attempt+1`；`FencedTaskRepository` 会按 `attempt` 和执行 lease token 拒绝旧代写入。
- **节点分配代数** = `task_node_assignments.generation`，另由 `MAX(generation)+1` 分配，保护 assignment lease；与执行代数**不是同一个值、不可互换**。
- Agent 正式 `RemoteExecutionLease` 里的 `generation` 来自中央 `execution.generation`，代表前述任务 `attempt`；远程失联仍有 `REMOTE_AGENT_STOP_UNVERIFIED` 的 fail-closed hold 和 GPU reservation 保护。
- 后续可信 OS Stop Proof 应只复用**中央 `task_id + tasks.attempt + 原 worker/node 身份 + execution lease + boot_id + InvocationID`**，并在中央同一事务中处理一次性 challenge。PoC 的 `execution_generation=1` 是独立模拟，不可当真实代数。**不需要新增第二套中央调度代数或业务数据库表。**
- 正式恢复协议需注意对代数严格类型判断，不能把 `True` 通过 Python `int()` 转换误当代数 1。当前只是未来协议风险提示，未改业务代码。

具体证据与对照见 [专项文档第 13.6 节](P0_01C_2_LINUX_SYSTEMD_EXECUTION_BOUNDARY_POC_2026_11_15.md)。**新身份绑定 31 合同 + GitHub 托管 VM 的 kernel run 43667494312 在本段落撰写时仍排队**，不宣告该 SHA 已通过。生产 NO-GO 和中央 HOLD 不变。

## 15. 2026-11-15 P0-01C-3A 已完成：中央可信恢复事务**隔离协议合同**（非生产接口）

在此前 **31/31** 合同与真实 Ubuntu systemd/cgroup 多子孙 CPU 停机、boot/InvocationID 绑定 PoC 成功的基础上，本轮将中央恢复协议先落为**纯隔离验证**，仍不对任何线上或本地真实平台数据库执行变更。

### 15.1 真实代码和验收

- `tools/poc/central_stop_recovery_contract.py`：新增测试专用中央挑战 + 消费 + 事务合同；`_memory_only()` 强制主数据库必须为 SQLite `:memory:`，任何文件型数据库均抛 `ISOLATED_MEMORY_DATABASE_REQUIRED`，故**不能对生产 SQLite 发起恢复**。
- `tests/unit/test_central_stop_recovery_contract_poc.py`：正向仅模拟 `RUNNING -> QUEUED` 或 `CANCEL_REQUESTED -> CANCELLED`；旧 `attempt` 不在恢复时递增，真实新执行开始才允许增加代数。
- 校验：真实字段名 `tasks.attempt`、旧 worker/token、远端 lease 已过期、HOLD stage、GPU reservation owner、一次性挑战过期/消费、boot ID、InvocationID、unit/cgroup、模拟 OS 见证签名与空组/已知 PID 停止严格标记；`BEGIN IMMEDIATE` 原子恢复并在同事务消费 challenge、清理 GPU reservation、插入审计。重放、伪造、错代、租约/节点变更、审计冲突导致的事务回滚均有负面回归。
- 提交：模块 `a2ef6048c42aafee8b1abc6f36648e86042ff63f`、合同 `37af8c9ceac8d473c0044f365feafa65227ab2cc`、专用跨平台 GitHub CI `1714ba852abb29f3f767357197976c6e91a9385c`。
- [GitHub-hosted run 43670649572](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43670649572)：**Ubuntu 22.04 41/41 passed、Windows-latest 41/41 passed，两项 Job 都 SUCCESS**。此结果仅授权说明“隔离合同通过”，不授权生产使用。
- 全量设计、测试用例、失效路径、下一步参考：[P0-01C-3A 中央停机挑战与恢复事务隔离合同](P0_01C_3A_CENTRAL_STOP_RECOVERY_CONTRACT_2026_11_15.md)。

### 15.2 未解决且绝不可越过的安全边界

**真正的可信 OS 见证尚未实现**。本轮 HMAC 使用测试模拟独立见证，不能由普通 Agent 持有密钥并通过自报 JSON 来宣称停机。未来必须具备独立可信边界/密钥保护、服务节点身份认证、预登记 boot/InvocationID/cgroup/执行代数、跨节点故障反例，才能把可信 StopReceipt 提交中央。

本轮 challenge/audit 是隔离测试数据，不是生产数据库 schema，也**不是第二套任务调度所有权**。未来正式接口还需单独审计现有单一 `TaskRepository` 的 WAL/锁、GPU reservation、持久审计、并发取消/上传竞赛；不得直接把 PoC 的 `commit_test_recovery()` 复制进生产服务。

### 15.3 下一专项建议

- **P0-01C-3B：可信 OS StopReceipt 合同**。只读梳理真实 Node Agent 现有 `process-launch-intent.json` / `process-identity.json` 和 `launch_process` 路径。定义正确的 `task_id + tasks.attempt + lease/node + boot_id + InvocationID + cgroup` 预登记、见证权限、事件持久化和挑战响应。先独立验证、不要改生产 Runner。
- **P0-01C-3C：中央真实 API（继续默认 OFF）**。只有具备可信 OS 见证及负面验收后，才能在保留现有 `FencedTaskRepository` 逻辑下新增附属 challenge/audit 持久表和中央原子恢复接口。
- **最终上线准入**仍需 A800/双4070 真实 GPU、多节点网络分区、取消竞态和 Windows Job Object 测试；任何生产变更另请用户明确授权。

继续 `REMOTE_AGENT_STOP_UNVERIFIED` HOLD、保留原 owner/GPU reservation、`CHANGLIAN_AGENT_AUTO_ASSIGN_ON_CLAIM` OFF、生产 **NO-GO**。

## 16. 2026-11-15 P0-01C-3B-1 已完成：真实 Linux 内核停机 + 中央挑战隔离联调

**本节为最新交接**。已把 P0-01C-2B 的真实 Ubuntu 22.04 systemd/cgroup `populated=0` 实验，与 P0-01C-3A 的纯内存 SQLite 一次性挑战、CAS 恢复连接起来。未连接任何生产服务；**OS witness 的信任根仍未解决，自动恢复仍禁止**。

### 16.1 范围和结果

- 修改 `tools/poc/linux_cgroup_poc.py`：只给 CPU-only 实验增加可选测试 `before_stop` hook、合成 task/generation；在已知三层进程真实绑定、模拟 Agent launcher SIGKILL 之后、执行 `systemctl stop` **之前**签发中央挑战；记录 stop 请求和原 cgroup 内核空组事件单调时间戳，**先空后 stop 或时序倒置必须拒绝**。正常 CLI 不接受正式真实任务 ID，也不能操作生产机器。
- 新增 `tools/poc/linux_stop_receipt_bridge.py`：硬限制 GitHub-hosted 非 root VM 和显式 `--run --isolated-test-host`；先在独立 SQLite `:memory:` 创建 HOLD 的 synthetic task（`attempt=3`）和假 GPU reservation；对真实原 unit 挑战→内核停机→事件归属和时间顺序核验→**模拟 HMAC 见证**→内存 `BEGIN IMMEDIATE` 消费挑战、清空模拟 GPU reservation、任务进入 QUEUED→同一挑战重放拒绝。
- 新增 `tests/unit/test_linux_stop_receipt_bridge_contract.py`：拒绝错代、错误 boot/InvocationID、被替换的 cgroup/unit、停机前已经为空、缺少原始 `populated=1`、无正式 runner 授权、伪造 OS 证据及默认 CLI 越权执行。
- 工作流仍是 [`agent-kernel-stop-poc.yml`](../.github/workflows/agent-kernel-stop-poc.yml)，只运行 **GitHub-hosted ubuntu-22.04 CPU 临时 VM**，原本的真实 kernel PoC 和本轮 bridge 各执行一次。不会触及 A800/4070/OSS/生产 GPU、worker、数据库。
- **真实 GitHub CI 最终通过**：[run 43672300351](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43672300351)，精确代码 SHA `341b2f73998bbd0db68cdeca72e6f1700ea26406`：**71/71 合同 SUCCESS**、真实三层进程 systemd stop SUCCESS、桥接真实 kernel → 内存 CAS SUCCESS、`challenge_replay_rejected=true`、`simulated_central_recovery_committed=true`、GitHub Job SUCCESS。原始 2B/3B JSON 工件名 `p001c2b-ubuntu22-cpu-evidence`，保留 14 天。
- 首轮新桥接 [run 43672197474](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43672197474) 有 **70 passed / 1 failed**：拒绝非 Github Runner 的代码少返回 `production_recovery_allowed=false`，因此真内核阶段跳过；已在 `341b2f7` 只修补明确的拒绝字段，不放松停机/身份断言。不能把首轮前置测试失败算作内核实验失败。
- 正式桥接输出仍准确为 `REAL_KERNEL_TO_MEMORY_CAS_SIMULATION_PASS_NOT_TRUSTED_STOP_PROOF`，`trusted_os_witness_implemented=false`、`production_recovery_allowed=false`；**这个 PASS 只证明隔离时序及模拟协议一致性，绝不等于可用于正式任务释放 HOLD**。

### 16.2 尚未完成的 P0 关键安全门槛

- 独立于普通 Agent 的 OS Execution Supervisor、**启动前**注册受保护的 systemd unit/cgroup、可信地收集完整内核事件、限制 cgroup 迁出、OS 进程逃逸和单位重用；
- 受保护的签名密钥/不同进程权限域/中央公钥信任链、一次性挑战、boot/InvocationID/真 `tasks.attempt`/原 lease 的防重放验证。**同用户进程内 HMAC 不是独立可信 witness**，就算测试成功也不能复制到正式 API；
- 正式 Node Agent 与训练/转换 Runner 的 ExecutionBoundary 适配、Windows Job Object、GPU DataLoader 多进程、真实双节点网络分区和生产变更批准；再到 P0-01C-3C 中央持久挑战/审计事务和受控默认 OFF 的恢复 API。

详细只读链路审计、Linux cgroup/systemd 官方依据、代码文件和 Run 证据见 [`P0_01C_3B_LINUX_STOP_RECEIPT_TRUST_BOUNDARY_2026_11_15.md`](P0_01C_3B_LINUX_STOP_RECEIPT_TRUST_BOUNDARY_2026_11_15.md)。

**最终安全状态不变**：`REMOTE_AGENT_STOP_UNVERIFIED` HOLD，原 worker/lease/`tasks.attempt`/GPU reservation 保留，`CHANGLIAN_AGENT_AUTO_ASSIGN_ON_CLAIM` OFF，生产 **NO-GO**。**本轮没有对 A800、4070、真实训练/转换任务、真实数据库或 GPU 服务执行命令。**

## 17. 2026-11-15 P0-01C-3B-2 完成：Linux Supervisor 独立系统账户/签名权限隔离实验

> 本节承接 3B-1 的真实 cgroup→模拟中央挑战流程。**本轮已实际通过额外的 OS 权限边界反例，但仅 GitHub 托管 VM 成功，不等于生产 StopReceipt 可用。**

### 17.1 实际提交与验证

- 新增 `tools/poc/linux_supervisor_privilege_probe.py`：**仅允许** `--run --github-ephemeral-only` 且 root + `SUDO_USER=runner` + `GITHUB_ACTIONS=true` + `RUNNER_ENVIRONMENT=github-hosted` + Ubuntu 22.04 + cgroup v2 才可执行。临时创建两个独立 UID（普通 Agent、受托管 CPU workload），root 持有新建 Ed25519 私钥，`0600` 文件、`0700` 目录。root 通过 systemd **SYSTEM** unit 启动 workload，属性 `User=<workload_uid>`、`KillMode=control-group`、`Delegate=no`、`ProtectControlGroups=yes`、`NoNewPrivileges=yes`、`RestrictSUIDSGID=yes`、`RuntimeMaxSec=25s`。
- 实测非特权 Agent 不能读取 root 私钥、直接向另一 UID 的计算进程发送信号、`sudo -n` 提权或 `systemctl --system stop` 停掉 root 所属 unit。workload 真实尝试向父 cgroup 的 `cgroup.procs` 写入自己的 PID 被拒绝，私钥也不能读取。
- root Supervisor 监听原 `cgroup.events populated=1→0`、校验 systemd unit ID、ControlGroup、InvocationID 和已知进程；真实 systemd stop 成功后使用**临时 root-only Ed25519** 对包含挑战和事件摘要的测试 payload 签名，在纯内存 SQLite 中模拟 `BEGIN IMMEDIATE` 恢复并拒绝挑战重放。所有数据仍是假任务、假 GPU reservation、测试临时私钥，**无真实 Node Agent 接口**。
- 新增 `tools/poc/test_linux_supervisor_privilege_probe_contract.py`，提供默认入口不执行、非托管机拒绝、不同密钥验签失败、签名篡改失败、unit identity 重用拒绝等 **12 项**可执行合同。
- 专属 `.github/workflows/linux-supervisor-privilege-probe.yml`：`ubuntu-22.04` GitHub-hosted disposable CPU VM，不使用 self-hosted，不连接生产 GPU/服务/数据库。
- **真实 CI**：[run 43674027072](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43674027072)，准确代码 SHA `c7be6e77ca44a241d72724e41947d624feb56f06`，`hosted-ubuntu22-sandbox` **SUCCESS**，`12 passed in 0.06s`，实际 `agent_denials.key_denied/signal_denied/sudo_denied/unit_stop_denied` 全 true，`workload_escape_denied=true`，`workload_key_read_denied=true`、`systemd_boundary_verified=true`、`privilege_boundary_verified=true`、`systemd_stop_returncode=0`、`cgroup_empty_verified=true`、`known_processes_stopped=true`，`test_supervisor_signature_verified=true`，`challenge_replay_denied=true`。
- 明确 `outcome=SEPARATE_UID_SUPERVISOR_ISOLATED_PASS_NOT_PRODUCTION_ATTESTATION`、`trusted_production_stop_receipt=false`、`production_recovery_allowed=false`。
- **首次 workflow 文件 SHA `652f58a` 在 run 43673969567 GitHub 解析失败（`runner.environment` 被放在 job-level env）**，无实际 Job；后在 `c7be6e7` 挪到 step env，真实运行全绿。该失败不能误称为 OS 负面验证不通过。

### 17.2 必须保留的疑点与最小下一专项

- GitHub runner 管理账户拥有 sudo，实验创建的 Agent UID 是特意限制的无 sudo 账户。**不能由这一组隔离成功断言 A800/4070 的真实 Agent 拥有相同权限边界**；生产服务账户、user-systemd、sudoers、polkit、cgroup delegation 和 `/dev/nvidia*` 权限尚未核实。
- 当前签发者是**同一隔离脚本内以 root 执行的短命测试 signer**，没有生产独立 Supervisor 守护进程、`SO_PEERCRED` IPC 鉴权、密钥生命周期、公钥预登记/撤销、持久执行代数边界或灾难恢复协议。root-only 测试 key 和真实长期可信 StopReceipt 严格不同。
- `cgroup.events populated=0` 只证明原 unit cgroup 空，**不证明普通 Agent 无法在 unit 之外发起另一个 GPU 程序**；未来需核对 coordinator 与 workload 的 GPU 设备访问隔离、阻止 unbound GPU spawn 的机制、实际 NVIDIA/昇腾/瑞芯微设备权限和驱动差异。
- 只读代码审计：仓库 `node_agent.py` 仍直接启动 `NodeAgentExecutorLoop`；训练/转换仍调用现有 `launch_process`；未集成 Supervisor。仓库 `tools/install_rockchip_agent.sh` 是板端安装器，不能代表 A800/双4070 当前 service 配置。**没有生产节点系统权限的读取证据**。
- **下一步 P0-01C-3B-3**：先只读审计真实 GPU Agent 运行账户、systemd unit、sudo/polkit/GPU device 权限（若必须访问生产服务器需用户明确授权）；同时继续 GitHub VM 隔离实验验证普通 Agent 在原 unit 外独立启动 CPU 进程的反例、最小受保护 Unix socket/peer credentials 和可信签发者边界。完成后才评估正式 Agent/Runner 适配和 P0-01C-3C 中央 API。
- **安全基线不变：**`REMOTE_AGENT_STOP_UNVERIFIED` HOLD、旧 owner/`tasks.attempt`/GPU reservation、自动派单 OFF、生产 **NO-GO**；没有对任何生产节点执行命令。

完整实验和源码路径：[P0-01C-3B-2 Linux Supervisor 权限实测专项](P0_01C_3B_2_LINUX_SUPERVISOR_PRIVILEGE_PROBE_2026_11_15.md)。

## 18. 2026-11-15 P0-01C-3B-3 完成：Unix Socket / SO_PEERCRED 与 unit 外独立 CPU 存活反例

> **阶段结论：隔离安全验证已成功，发现原 unit 空组并不代表节点无其他计算。生产仍 NO-GO。**

### 18.1 本轮新代码和 CI 验证

- 新增 `tools/poc/linux_supervisor_ipc_probe.py`：仅显式 `--run --github-ephemeral-only`、GitHub-hosted 非 self-hosted Ubuntu 22.04/root 临时机才可执行；临时创建不同的 Agent/workload UID，随机 root-owned systemd SYSTEM unit、root-only 私有目录、`AF_UNIX` socket（`root:<agent_gid>`，权限 0660），通过 Linux 内核 `SO_PEERCRED` 验证 socket 请求者 UID。服务端**只有 `request_stop_admission` 测试准入方法**，不提供直接 stop/kill/shell/签发证明的 API。
- 测试仅接受登记过的 synthetic `task_id+generation+unit+boot_id+InvocationID+challenge_id+nonce`；拒绝错误 UID、跨代/类型欺骗、错 unit/任务/nonce、过期/重放/多余字段、非白名单方法。根私有文件只能 root 读取；禁止普通 Agent/workload 读取。
- **关键负面反证**：普通 Agent UID 可以在原受控 unit **外**启动另一份 CPU 程序，`/proc/<pid>` UID/start_ticks 和独立 cgroup 已验证。root 关闭**原受控** systemd unit、确认原 cgroup `populated=0` 且该 unit 的原已知主进程退出后，**另一份 unit 外 CPU 程序仍在执行**。这并不是“原已登记训练子进程已成功逃出受控 unit”的证明，而是**未受管控的新计算可与受控 unit 停机并存**，提醒未来 GPU 设备访问必须有额外安全约束。
- 新增 `tools/poc/test_linux_supervisor_ipc_probe_contract.py`，并扩展 `.github/workflows/linux-supervisor-privilege-probe.yml`；原 3B-2 Supervisor 权限分离真实实验依然执行。
- **GitHub-hosted 真实 CI 最终 PASS**：[run 43674960801](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43674960801)，精确代码 SHA `2ef3bf0b6408347f043afb006a5c63fc27c1d8df`，**54/54 合同通过**，3B-2 实际 Supervisor 阶段 SUCCESS，3B-3 真实 Socket / unbound CPU 阶段 SUCCESS。
- 原始 3B-3 日志：`workload_socket_permission_denied=true`、`unauthorized_peer_credential_rejected=true`（短暂 chmod 0666 仍由内核 `SO_PEERCRED` 判错 UID）、`wrong_scope_denied=true`、`authorized_request_admitted_once=true`、`replay_rejected=true`、`agent_secret_read_denied=true`、`workload_secret_read_denied=true`、`controlled_unit_stopped=true`、**`unbound_cpu_spawn_possible=true`、`unbound_cpu_survived_controlled_stop=true`**。
- 结果 `EXPECTED_ESCAPE_COUNTEREXAMPLE_AND_IPC_CONTRACT_PASS_NOT_STOP_PROOF`；依然 **`real_stop_proof_implemented=false`、`production_recovery_allowed=false`**，没有生成正式可信 OS StopReceipt，也没有改真实数据库或 GPU 预留。
- 中间两轮 CI 历史：`c303a9c` 在 [run 43674713650](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43674713650) 因测试参数名 `request` 是 pytest 保留名字而 collection ERROR（未运行 OS 阶段）；`6683b66` 在 [run 43674891679](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43674891679) 为 **53/54**，真实 Socket 测试错误使用历史固定 `monotonic_ns` 导致正确拒绝过期挑战（未运行 OS 阶段）。最终代码仅精确修正测试参数和时钟，没有削弱 fail-closed 验证。

### 18.2 仍欠缺的生产安全能力（不允许解锁）

- **真正受保护的 OS Execution Supervisor** 还不是生产长期守护进程：缺启动前执行身份登记、系统 UID/Unix socket 信任模型落地、私钥轮换/撤销、公钥注册、独立证据持续性、boot/InvocationID/启动代数持久链、离线重启、中央挑战绑定与签发防重放。
- GitHub VM CPU 没有证明**真实 NVIDIA/Ascend/GPU 驱动设备访问控制**；即使 unit 的 cgroup 有 `populated=0`，普通 Agent 可能继续单独执行程序，是否能占 GPU 未验收。真实设备策略要按 A800、双4070 的运行账户和 `/dev/nvidia*` 权限先只读审计、再进行受控硬件 UAT，必须事先获用户授权。
- 当前 Agent 训练与转换的 `launch_process` 没有适配 Supervisor，Node Agent 的现有所有权约束继续 `REMOTE_AGENT_STOP_UNVERIFIED` HOLD；不能据此接 P0-01C-3C 真实中央可恢复 API。
- 继续**默认自动派单 OFF、原 task/lease/`tasks.attempt`/GPU reservation 保留、生产 NO-GO**。本轮没有访问 A800、4070 或生产数据库、没有合并 main、发布 Release、部署/重启任何生产服务。

**专项完整报告与下步建议：** [P0-01C-3B-3 独立进程与 Socket 安全验证](P0_01C_3B_3_UNBOUND_COMPUTE_AND_IPC_2026_11_15.md)。

## 19. 2026-11-15 P0-01C-3B-4｜GPU 访问与 Supervisor 适配的代码审计 + 模拟权限验收

**本轮仍只在唯一长期开发分支提交测试专用代码/文档。生产 A800、双4070、真实 GPU、OSS、数据库、训练/转换任务完全未触及；正式 Agent、训练/转换 Runner 没有修改；中央 HOLD/自动派单 OFF/NO-GO 不变。**

### 19.1 代码只读审计的已确认事实

- 实际 `platform_core/node_agent_training_runtime.py` 和 `platform_core/node_agent_conversion_runtime.py` 在持久化 launch intent 后都**直接调用 `launch_process()`**，并继承普通 Agent 的 `os.environ`；前者虽然核对 selected device、GPU UUID/worker 资源，但没有调用受保护的 OS Supervisor。转换任务要按目标 SDK 分辨是否使用 GPU，不能笼统声称全部转换占用 CUDA。
- `platform_core/task_runtime/process_control.py` 的 POSIX session/Windows process group 与 PID/create time/hash 不是可信 systemd unit/Windows Job Object 的替代；`gpu_reservations_v2.py` 是中央逻辑 GPU 预留，**不是设备 ACL**。
- `platform_core/node_agent_runtime.py` 直接执行 `nvidia-smi` 采集卡、进程、显存和负载；`training_devices.py` 会尝试 `torch.cuda` 探针。若下一专项禁掉普通 Agent GPU device 权限，**必须迁移相关硬件只读遥测/探测到受保护执行边界**，不能直接破坏现有多节点调度和自动资源选择。
- 当前没有足以确认 A800/双4070 上真实 GPU Node Agent 的 service UID、sudo/polkit、`/dev/nvidia*` ACL、驱动设备访问策略、容器设备映射等的在线证据；仓库 `install_rockchip_agent.sh` 只能说明板端示例，不能推断两套 GPU 生产环境权限。

### 19.2 本轮实际交付和现有验收

- 新增 `tools/poc/gpu_supervisor_gate_audit.py`、`tests/unit/test_gpu_supervisor_gate_audit.py`、`.github/workflows/gpu-supervisor-source-audit.yml`。脚本只解析 GitHub 源码 AST，不 import 平台/访问数据库/启动 GPU；模拟边界合同对 task_id、真实执行代数概念、worker/node、lease token digest、GPU UUID、boot/InvocationID/unit/cgroup/challenge/nonce、7 类 OS 控制信号进行 fail-closed 匹配。**即使全部模拟输入匹配，仍 `production_gpu_launch_allowed=false`。**
- 源码审计 GitHub-run：[43677681674](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43677681674)（准确 SHA `6279609597b77a8f395dc6e71a468c706eba0d29`）：Ubuntu 已 **65/65 passed、静态审计 `DIRECT_GPU_CAPABLE_LAUNCH_BYPASSES_SUPERVISOR_HOLD`**；Windows Job 在本节写入时仍 queued，**不可提前报跨平台全绿**。
- 新增 `tools/poc/gpu_device_acl_shadow_probe.py`、`tools/poc/test_gpu_device_acl_shadow_probe.py`，复用严格 GitHub-hosted Ubuntu 22.04 测试环境。**仅测试临时普通文件**：root:workload-only group、0660 时 Agent UID 不可读，workload UID 可读；模式 0666 时 Agent 可读，恢复 0660 后再次不可读。这**不是 NVIDIA/昇腾 GPU 真实设备测试**。
- [真实 GitHub-hosted Ubuntu run 43677832627](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43677832627)，准确 SHA `a82d6df04fb41add9930ccc2bac106deba86041b`：**59/59 合同通过**，旧 Supervisor/SO_PEERCRED OS 实验和新增普通文件 DAC 实验全部 SUCCESS；`fake_device_acl_separation_verified=true`、`fake_world_access_bypass_observed=true`、`restored_agent_denial_verified=true`。仍 `actual_cuda_or_gpu_device_tested=false`、`production_gpu_isolation_verified=false`、`production_recovery_allowed=false`。
- 完整核对清单、最低限度 Supervisor adapter、GPU telemetry 兼容要求与后续只读实机验证步骤：[P0-01C-3B-4 GPU 设备访问与 Supervisor 前置审计](P0_01C_3B_4_GPU_SUPERVISOR_ACCESS_AUDIT_2026_11_15.md)。

### 19.3 下一步和未完成的生产准入

- **先取得用户对指定 A800 / 4070 的明确许可**，才可对真实运行用户、systemd unit、sudoers/polkit、GPU 设备节点与驱动/cgroup 权限做只读采样；本轮没有 SSH 或远程命令。
- 得到真实硬件权限模型后再设计正式非 root Agent + 受保护 workload UID/systemd unit + GPU device 访问限额和只读遥测接口；绝不能仅设置 `CUDA_VISIBLE_DEVICES` 就声称隔离。
- 随后在经批准的维护窗口或独立 GPU 测试机验收真实 CUDA/其他 SDK 越权启动拒绝、合法任务正常运行、所有 DataLoader/转换子进程停止、重启/网络分区/重复挑战的 StopReceipt 完整性；再决定是否进入正式中央默认 OFF 恢复 API。
- **任何生产功能解锁都尚未授权。** `REMOTE_AGENT_STOP_UNVERIFIED` HOLD、旧 `tasks.attempt`/owner/lease/GPU reservation、自动派单 OFF 继续。

## 20. 2026-11-15｜从重复 PoC 转向正式 Agent 渐进式开发：Supervisor 强制准入保护

本轮用户明确要求减少重复测试、直接推进开发。已从纯 `tools/poc` 转向**最小正式业务代码改动**，仍不动任何生产机器/任务/数据库，不解除 HOLD。

- 新增 `platform_core/node_agent_supervisor_gate.py`（生产可导入的轻量策略模块）。`CHANGLIAN_AGENT_EXECUTION_BOUNDARY` **默认 `legacy`**，旧流程不变；仅在显式配置 `supervisor-required` 时，因真正受保护 launcher/进程句柄适配尚不存在，强制拒绝训练、转换和部署复核的直接进程启动，绝不静默退回旧 `subprocess.Popen`。配置非法亦拒绝启动。
- 已修改 `node_agent.py`：在上报能力、构建 `NodeAgentExecutorLoop` 和申领任务之前过滤 `training`、`conversion`、`conversion.rknn`、`deployment-test`、`deployment-test.rknn`。模型安装、素材处理、清洗等其他能力按原规则继续，不随意扩大范围；doctor 增加执行边界模式可观察性。
- 已修改三个正式 Runner：`node_agent_training_runtime.py`、`node_agent_conversion_runtime.py`、`node_agent_deployment_runtime.py`，在各自唯一的真正 `launch_process` 入口之前二次保护。保护拒绝会走 `RemoteExecutionFenced` 路径而不是宣称已停止旧 GPU 进程。注意部署复核也有 GPU/SDK 计算能力，不能将其漏掉。
- 新增 `tests/unit/test_node_agent_supervisor_gate.py`，直接复用已有 `.github/workflows/node-agent-executor.yml` 回归。运行 [Node Agent Executor 43679484571](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43679484571) 针对代码 SHA `c66ef5678c9dd86cd681c67a1623baacc5217e3d` 的 Ubuntu、Windows、API Jobs **首次记录仍在队列中，禁止称作通过**。每一笔中间代码提交可能触发几十项 GitHub workflow，后续要**合并变更和缩减重复运行**，不用为了测试而重复测试。
- 新增 `tools/audit_gpu_node_access.py`：经明确许可后可在指定 Linux 节点使用的**只读权限盘点**。默认 `INERT_OPT_IN_REQUIRED`，仅 `--read-only [--unit existing.service]` 读取 systemd **允许列表内的非秘密属性**、当前 UID/GID 和设备节点 `stat` 元数据；不调用 CUDA/nvidia-smi，不打开设备节点，不读 token/ExecStart/环境变量，不修改生产。**本轮没有在 A800/4070 实际运行，也无法推断真实 GPU 授权**。
- 当前受控配置 `supervisor-required` **不代表 Supervisor 真正可启动计算**，如果现在对生产设置它，会主动阻断远程计算任务接单；未授权、未部署、不可直接启用。默认 `legacy` 保持线上原有行为和 fail-closed 的远程租约过期 HOLD。
- 下一阶段不再重复类似 CPU PoC，而是一个可工作的受保护 Supervisor 纵向切片：跨 UID Unix Socket 鉴权、启动前登记、实际 systemd launch、稳定异步 `poll/returncode`、日志/取消与一体化 StopReceipt，并在真实 GPU 权限/驱动 UAT 审批后替换旧启动路径。绝不能重构或另建第二套调度系统，中央 `tasks.attempt` 继续唯一执行代数。

**完整记录**：[P0-01C-3B-5 渐进式接入和只读权限盘点](P0_01C_3B_5_SUPERVISOR_MIGRATION_GUARD_2026_11_15.md)。安全状态不变：`REMOTE_AGENT_STOP_UNVERIFIED` HOLD、原 owner/lease/GPU reservation、自动派单 OFF、生产 **NO-GO**。无任何 A800/双4070/SSH/训练/部署任务动作。

## 21. 2026-11-15｜冻结 OS Supervisor 渐进式实施路线（只读审计/方案，不提前改业务）

用户要求“先确定怎么做，然后渐进实施”。本轮已只读核对 GitHub 最新长期分支 `3e411fa12df02cd7acac1889b9299ef8f3eff97d` 下的真实 `process_control.py`、远程 Training/Conversion/Deployment Runner、Node Agent Executor 与上轮 CI；正式业务逻辑**未改动**。

**核心决策与不可破坏的合同：**

- 旧 `LaunchedProcess` 中 `process: subprocess.Popen`，三个 Runner 都依赖 `poll/returncode`、现有日志及结束/取消清理；不能将 Supervisor 的 Socket JSON 直接冒充 Popen。必须设计独立 `SupervisedProcessHandle`，状态、退出码、日志、stop 和恢复语义清晰。
- **先独立 Linux OS Supervisor 服务，再做进程句柄 CPU 纵向闭环，随后“模型转换 → 训练 → 边缘模型复核”逐个迁移**；模型转换已有启动前 intent/进程身份持久化，适合首个灰度。边缘复核进程恢复机制与前两类不同，要另行适配。
- Linux 服务采用不同 UID/系统管理的受保护 unit/cgroup，Unix Socket 的 `SO_PEERCRED` 只能认证本机身份，中央原任务授权必须额外核验；固定命令和路径白名单，绝不接收任意 shell/PID/unit。重复 start/超时/重启必须 fail-closed 且不可形成第二个真实执行实例。
- 中央 `tasks.attempt`、旧 owner/lease 和 GPU reservation 是执行归属唯一真相；Supervisor 本地持久数据只记录 OS 边界，不创建第二套调度系统；正式 StopReceipt 尚未实现，不能启用中央自动恢复。
- 原 `CHANGLIAN_AGENT_EXECUTION_BOUNDARY=legacy` 默认保持线上业务行为；`supervisor-required` 目前仍是拒绝训练/转换/复核旧直启的保护开关，**不可在生产启用**。迁移需使用独立隔离 Node Agent，一个能力通过后才开放下一个。
- 真正 GPU 设备 ACL 和专用运行账户、systemd、polkit/sudoers 必须在用户明确许可下对 A800/4070 只读审计，再经维护窗口或独立 GPU 环境验收。不能把 CPU PoC / 文件 DAC 结果当 CUDA/Ascend 真相。
- 测试原则：每一阶段只做必要单元合同、一次真实隔离 E2E、复用既有 CI；不再为相似证明增加多个 GitHub Actions 工作流。

**当前 CI 未关闭风险**：[Node Agent Executor run 43679484571](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43679484571) 对 `c66ef5678c9dd86cd681c67a1623baacc5217e3d` 的 Ubuntu/Windows/API 三项 Job 在本轮核查时**仍排队**，不得写成全绿。正式下一步先锁定这一基线结果，再做阶段 1 的独立 Supervisor 服务/句柄合同。

详细阶段 0–5、每一步修改范围、单类 Runner 验收、回滚约束、常见失败模式见：[P0-01C Supervisor 渐进式实施方案](P0_01C_SUPERVISOR_INCREMENTAL_IMPLEMENTATION_PLAN_2026_11_15.md)。

**本轮只写入 GitHub 方案/交接文档**，不连接 A800/4070，不操作生产数据库/训练任务，不切换默认模式，不合并 main、不 Release。生产继续 HOLD、自动派单 OFF、NO-GO。

## 22. 2026-11-15｜真正进入阶段 1A：独立 OS Supervisor Socket 服务与句柄合同已提交

本轮按第 21 节冻结的渐进式方案**实际新增正式模块**，不是另做纯模拟 PoC，也不变更现有训练/转换/复核 Runner。重点先建立服务通信与进程句柄**严格不可误用的边界**，不冒进启动真实进程。

### 新交付

- `platform_core/os_supervisor_protocol.py`：版本 1 的 16 KiB 长度帧/严格 JSON schema、动作白名单 `health/inspect/start/stop/read_log`、随机 request_id 和响应 ID 验证；Linux `SO_PEERCRED` 检查**服务端 UID**（生产默认必须 root）；`SupervisedProcessHandle` 独立于 `subprocess.Popen`，`poll()` 只能在完整 EXITED + 合法 int exit code 时返回退出码，UNKNOWN/不可信/网络断开全部 HOLD。
- `platform_core/os_supervisor_service.py`：真实独立 AF_UNIX Socket 服务，内核 `SO_PEERCRED` 检查**调用方非 root Agent UID**；root 运行模式固定 `/run/changlian-os-supervisor/control.sock`，拒绝现存 Socket、符号链接父目录和未知所有者；受限 socket 目录权限、请求大小/超时和结束清理。没有暴露 shell、kill 或任意可执行文件接口。
- **刻意禁用所有执行副作用**：`start` 明确 `PROTECTED_LAUNCH_NOT_IMPLEMENTED_HOLD`、`stop` 明确 `PROTECTED_STOP_NOT_IMPLEMENTED_HOLD`、`inspect` 为 `UNKNOWN` + HOLD、日志读取不可用。health 虽响应成功，但 `launch_available=false`、`stop_available=false`、`trusted_stop_receipt_available=false`、`central_recovery_allowed=false`。
- `tests/unit/test_os_supervisor_phase1.py` 已新增必要回归，复用**现有** `.github/workflows/node-agent-executor.yml` 的 Ubuntu/Windows/API 工作流，不新建独立重复 CI；开发时本地 Linux 非 root 实测同类 Socket 协议 **31 passed**。
- 确切 GitHub 代码/CI SHA `2ab61ce6fe6d6c8a09e5fc8d9723672d92c5f5f8`；[Node Agent Executor run 43684001227](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43684001227) 在此节写入时 Ubuntu/Windows/API **仍 queued**，不宣称已完成远端验收。

### 还不能做什么

- 这仍不是生产可用的完整 Supervisor：**没有真实 central grant 校验、启动前持久 OS boundary journal、systemd/cgroup 启动/停止、日志与退出码真实来源、root-only 长期签名密钥或 StopReceipt**；不能把已建立 Socket 误当作可运行/可恢复的任务。
- 正式 Agent/Training/Conversion/Deployment 没有 import/使用此模块；`supervisor-required` 依旧是**拒绝普通计算直启的安全阻断**，不要现在在生产启用。
- 下一步阶段 1B 先开发**可信任务执行授权和持久 handle 登记**，随后阶段 2 才让独立服务通过固定执行器实际启动一个隔离 CPU worker，再逐步适配模型转换→训练→复核。严禁一次重构全部 Runner。
- 生产 A800/双4070、GPU/OSS/SQLite/真实任务未操作。继续中央 `REMOTE_AGENT_STOP_UNVERIFIED` HOLD、原 owner/lease/`tasks.attempt`/GPU reservation、自动派单 OFF、生产 NO-GO。

详细代码清单、阶段差异、明示的禁区见：[P0-01C Supervisor 阶段 1A 通信服务](P0_01C_SUPERVISOR_PHASE1_TRANSPORT_2026_11_15.md)。
