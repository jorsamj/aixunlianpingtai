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
