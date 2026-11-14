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
