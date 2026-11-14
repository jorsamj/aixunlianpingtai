# 畅联云｜分布式 Worker、可配置存储与统一调度需求—实现差异复核（2026-11-14）

> 审计性质：**只读需求—源码—现有测试对照**，不改业务代码、运行配置或生产资源；本报告仅审计用户确认需求，不将任何开发或 CI 状态冒充生产验收。  
> 唯一分支：`feature/external-algorithm-publishing`；当前代码基线：`dfdf6f3036f2cb2da3f3f44859c76bb3548b9694`；`VERSION.txt=42.24.592`。  
> **主需求**：`docs/DISTRIBUTED_WORKER_CLUSTER_ARCHITECTURE_2026_10_10.md`（明确标注「用户确认的目标需求」，优先于后续历史“关闭”叙述）；辅以 `docs/plans/2026-09-07-multi-source-material-storage-design.md`、`docs/STORAGE_CACHE_AND_OBJECT_IMMUTABILITY.md`、`docs/NODE_CONTROL_PLANE_V42_25.md`、`docs/FIFTYONE_SMART_MATERIAL_AUDIT_2026_10_26.md`、`docs/performance/2026-11-14-p0-pinned-gpu-auto-deferred-resource-resolution.md`。

## 1. 产品合同（不可因已有 CI“关闭”而降低）

1. 阿里云 Web/API 控制端应**轻量**，负责中央业务数据、调度、授权、正式写入与审计；可移植的耗时 CPU/GPU/图像/ZIP 工作交给独立且可配置的 Worker/Agent。控制端可另行部署本地 Worker，但须受同一容量约束。
2. **存储源与计算节点解耦**：可选本地、NAS 挂载、OSS、S3/MinIO、远程 HTTP。素材业务 ID/正式 GT/哈希和物理对象位置分离；真正计算时按安全合同按需读取和缓存，不要强制把 20k/30k 原图同步到 Web。
3. 统一 Node Agent 可按能力授权**训练、素材导入、清洗、素材检查、AI 标注、视频切帧、标签统一、转换/部署评测**。配置菜单允许能力≠运行环境具备执行能力；不能把本地 Worker 与远程 Agent 的合同混为一谈。
4. 单一中央 durable queue/allocator 必须**持续自动派单**、能力匹配和资源**硬准入**，不能依赖人工 `allocate-next`；节点离线、任务停止、槽位释放后安全重新分配，严格执行手动 pin。
5. GPU 独占身份，单服务器多 GPU 应能**同时执行两项独立训练**、第三项等待；训练+清洗并发要有 CPU/RAM/SSD/I/O/执行槽预算。实际 Agent 执行容量与调度承诺一致。
6. 自动训练配置在**实际选中服务器并分配硬件后**据其 GPU/RAM/CPU/数据量/现有资源预约进行 batch/workers/cache/precision 决议；不得用 Web 端或排队前旧遥测假定参数。
7. 标注、素材、Snapshot、Task、ModelArtifact 继续沿唯一正式 Owner；Agent 不写中央 SQLite，也不能凭远端绝对路径访问 Web 上的文件。

## 2. 逐项差异与优先级

| 级别 | 对照需求 | 已证实的代码/测试 | 需求符合性 |
|---|---|---|---|
| P0 | **中央持续自动派单**，无人工按钮 | `CentralTaskAllocator.assign_next` 有事务型持久分配；`central_scheduler_router` 暴露 `POST /api/v63/scheduler/allocate-next`；已检查 `AgentExecutionService.claim_assignment` 仅 `claim_for_node`、Agent Loop 仅领取。**尚未发现/验证常驻调度驱动或任务释放自动唤醒的完整服务闭环**，需排查完整部署启动链与无人工 UAT，不把“尚未证实”写作绝对没有。 | **未达到可验收条件** |
| P0 | **能力严格对应可执行 Runner** | `service_nodes.py` 声明 `annotation`、`video` 等节点能力；`node_agent_executor_loop.py` 仅支持 TRAINING/MATERIAL_IMPORT/MATERIAL_BATCH/MODEL_CONVERSION/MODEL_INSTALL/DEPLOYMENT_TEST，缺 AI_ANNOTATION/VIDEO_FRAMES Runner；`task_node_assignments.py::task_node_capability` 将 MATERIAL_BATCH 的非 CLEAN/AI_ANNOTATE 默认映射 `material-import`。 | **确定存在合同覆盖缺口** |
| P0 | **SMART_AUDIT、素材完整性检查能由指定服务器执行** | `smart_material_audit/service.py` 使用 `MATERIAL_BATCH` 本地材料 Worker 所需能力 `materials.smart_audit`；`material_batches.py::MaterialBatchHandler` 本地执行；没有专用 Agent SMART_AUDIT runner。其他完整性审计同样属于本地 Batch 分支。错误能力映射可能导致调度误分配／被本地 Worker fencing，需新增负例验证。 | **远程未满足** |
| P0 | **真实 CPU/RAM/磁盘/I/O/执行槽硬准入** | `task_node_assignments.py::_online_nodes` 过滤在线/能力/portable；训练 GPU 有最低空闲 1GiB/10%及利用率<85%等门槛、GPU 占用去重；但 `_score_node` 对 CPU/RAM/SSD 主要打分并对 active 施加惩罚，未形成任务级完整预算硬拒绝，非 GPU 任务更明显。 | **部分满足** |
| P1 | **多 GPU 一机多任务真实并行** | `test_multi_gpu_node_assigns_distinct_gpus_then_queues_next_task` 证实 allocator 分配两张卡；但 `NodeAgentExecutorLoop` 一个线程中 `run_once()` 同步执行单任务，`test_background_loop_keeps_one_active_task` 明确此特征。 | **调度已支持、单 Agent 执行不满足** |
| P1 | **远程 AI 标注、视频切帧、标签统一** | 中央本地 Worker 和相关业务 Owner 已有；Remote Agent 执行器无对应 TaskKind/Runner，不得拿平台注册能力枚举代替实跑。 | **未完整实现** |
| P1 | **OSS/S3/MinIO 独立可配存储** | `storage/{models,factory,source_repository,oss,s3,manager}.py` 已支持本地、OSS、S3(含 MinIO alias)、Remote HTTP、来源身份与密钥引用；NAS 依赖受控本地挂载/Provider，而非自动跨服务器映射；真实 OSS Bucket 与生产多节点尚未验。 | **代码已具备，真实验证缺失** |
| P1 | **对象存储/图片直达计算服务器 + 数据亲和** | `remote_training_inputs.py` 目前由中央受控 `StorageManager` 流式对外代理单图；`node_agent_training_runtime.py` 下载并制作 Agent 本地 bundle。没有确认调度器在候选节点准入中考虑原图 bucket 可达性、对象存储区域/带宽/成本。 | **部分满足** |
| P1 | **轻量控制端不执行重 CPU/图片准备** | 正式数据冻结仍在中央 `TrainingPrepareHandler`，且实际本地 Worker 支持大批处理；新远程训练素材物化已延后到 Agent（`indices_only=True`），但大型 GT 冻结、原图流代理或未远程化任务仍可能占用控制端。需隔离按进程测量，不推断所有任务必然阻塞 Web。 | **部分满足，容量实测缺失** |
| P1 | **排队后按目标 GPU 真实配置 Batch/Workers/Cache/Precision** | `node_agent_training_runtime.py::_prepare_project` 使用分配的 selected GPU / concurrent reservations / dataset evidence 调用资源解析器；`docs/performance/2026-11-14-p0-pinned-gpu-auto-deferred-resource-resolution.md` 记录固定 CUDA 的延期 auto 决议，相关合同存在。真实 A800/双4070 不可由伪资源 CI 替代。 | **代码已支持，实机待验** |
| P1 | **创建节点 POST 成功即展示一次性 Token** | `static/modules/service-node-runtime.js` 当前仍 `POST -> await refresh() -> showToken()`，列表 GET 失败会落入创建错误处理，存在“创建已成功却提示失败/Token 未展示”风险；`tests/browser/service-node-management.spec.mjs` 只覆盖正常 GET。 | **明确 UI 风险、缺负例** |
| P2 | **智能素材检查覆盖大规模任务** | `FIFTYONE_SMART_MATERIAL_AUDIT_2026_10_26.md` 及当前 `smart_material_audit/contract.py` 表明可选智能分析一次最多 2,000 张，非完整 20k/30k 智能扫描。不能把历史 10k/100k 元数据拒绝测试宣称成批量图像分析性能验收。 | **明确范围限制** |
| P2 | **低配控制端 + 部署/故障恢复 UAT** | 需求有 A/B/C/D、双 GPU、CPU+GPU 并行、节点丢心跳、指定节点离线、OSS 断连等验收表；现有 API/单元合同无法代替真实多机/真实数据/长期稳定性实验。 | **待验证** |

## 3. 当前需求文档本身存在的状态歧义

1. **目标需求与技术阶段关闭不是同一层级：** `docs/DISTRIBUTED_WORKER_CLUSTER_ARCHITECTURE_2026_10_10.md` 明确是 `SPEC / NOT IMPLEMENTED BY THIS DOCUMENT`，其 P0/P1 项仍应有独立验收。另一方面，`docs/NODE_CONTROL_PLANE_V42_25.md` 标题为“节点控制面/中央 Assignment 已关闭”，实际主要验注册、数据库事务、API、fencing。其“已关闭”**不覆盖**连续自动派单、多执行槽及真实存储可达性。
2. **README 版本漂移：** `README.md` 首行仍写 `v42.24.561`，真实 `VERSION.txt` 是 `42.24.592`。它是历史说明，不是实时业务状态。
3. **旧交接入口互相矛盾：** `docs/CODEX_READ_FIRST.md` 保留了旧 `refactor/frontend-runtime-stabilization` 和“VERSION.txt 必须为 42.24.0”的历史要求；当前分支与版本不符。不能拿这份历史文件的旧版本号覆盖现行有效版本。
4. **远程 Bundle 文档可能陈旧：** 2026-10-10 需求的“现有 Prepare 生成完整 portable bundle”描述与 2026-11 的 `indices_only=True` 延迟物化实现有时间差。以当前 `remote_training_tasks.py` 与 `node_agent_training_runtime.py` 及准确实测为准。
5. **验收范围须标注：** `docs/FIFTYONE_SMART_MATERIAL_AUDIT_2026_10_26.md` 有“最终代码与隔离 CI”状态，但也明确真实 OSS、多万张图像、许可/离线包、生产未验。不能将该代码关闭视为远程全库素材检查满足需求。
6. 建议不批量删除历史文档或改写旧证据；另建**现行需求追踪矩阵**，将 REQUIREMENT / CODE / CI / BROWSER / DEPLOYMENT / PRODUCTION-UAT 分开记录，并由唯一实时 HEAD 做每轮验收。

## 4. 本轮准确 CI 状态（不能写全绿）

审计源代码 HEAD `dfdf6f3036f2cb2da3f3f44859c76bb3548b9694` 关联 GitHub Actions **21 工作流：20 success、1 failure**（2026-11-14 查询快照）。失败工作流 [Frontend Runtime Stabilization #43554005473](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43554005473)，失败 job `browser-navigation (2)`，`tests/browser/material-pagination-performance.spec.mjs:377` 中“v19 background import completion...”期望标签列表 GET 仅一次，实际两次；其他两个 Browser 分片和 frontend job 成功。未查明是否间歇性竞态，**不能直接将测试改为允许重复或宣称误报**。此失败与统一调度需求差异为独立事项，应先定向复现/检查调用链。

## 5. 建议修复顺序（先证据、后最小变更）

**P0-01 中央调度自动闭环核验：** 实际新建可移植任务，观察服务端没有人工 `allocate-next` 是否会自动创建 assignment，并在节点释放时推进下一任务；补无界面、无人工控制器生命周期测试。未证实则在现有 allocator owner 增加常驻受控驱动，确保单 Leader、幂等、重启恢复，禁止第二套队列。

**P0-02 能力映射和错误派发保护：** 按 TaskKind + MATERIAL_BATCH operation + required_capabilities 对每条已存在 Runner 创建可执行矩阵。对 SMART_AUDIT/素材完整性审计/AI_ANNOTATE/VIDEO_FRAMES/REMAP 等不能远程运行的业务先保持正确 local-only，防止错误占用 node assignment；随后逐个交付真正 portable Agent runner，不能只在 UI 勾选新能力。

**P0-03 真实容量准入：** 先写 A/B/C/D 场景、单节点训练+清洗 CPU/RAM/磁盘不足负例，再针对性增加执行槽及预算占用持久记录；不能用“繁忙惩罚评分”代替准入。

**P1-01 多执行槽：** 双 GPU 节点真实两训练并行＋第三等待、同卡独占；CPU 清洗与 GPU 训练可并行但不超配；执行器租约／取消／回收防护优先于提高并发线程数。

**P1-02 存储与低配控制端：** 真实 MinIO/OSS 可达性合同、缓存/磁盘预算、20k/30k 图片网络路径及吞吐；在不泄露持久凭据的前提下评估临时授权 Worker 直读对象存储；NAS 必须是 Worker 本机真实可达的授权挂载。

**独立 CI 问题：** 先定位 Browser v19 标签请求重复的实际来源并定向回归，不混入分布式开发变更集。

## 6. 验收定义

任何需求条目均应带五类证据：真实当前源码 SHA、隔离单元/API、真实 Chrome、非生产多节点/OSS 测试、生产 UAT。只有代码存在不等于完整满足。除非用户授权，不在 A800、4070 或生产存储上读写、重启、安装或运行 GPU 任务；不合并 main、不创建 tag/release、不强推。

## 7. 相关文件及核验入口

- 正式目标：`docs/DISTRIBUTED_WORKER_CLUSTER_ARCHITECTURE_2026_10_10.md`
- 原节点实现台账：`docs/NODE_CONTROL_PLANE_V42_25.md`
- 本次前一轮架构审计：`docs/plans/2026-11-14-oss-compute-unified-scheduling-readonly-audit.md`
- 存储目标：`docs/plans/2026-09-07-multi-source-material-storage-design.md`
- 智能检查范围：`docs/FIFTYONE_SMART_MATERIAL_AUDIT_2026_10_26.md`
- 自动参数专项：`docs/performance/2026-11-14-p0-pinned-gpu-auto-deferred-resource-resolution.md`
- 核心代码：`platform_core/{service_nodes,task_node_assignments,agent_execution,node_agent_executor_loop,node_agent_training_runtime,remote_training_tasks,remote_training_inputs,material_batches}.py`、`platform_core/storage/`、`platform_core/smart_material_audit/`、`static/modules/service-node-runtime.js`。


## 8. 2026-11-14 接续第一阶段源码复核（0832ac09）

> 本节是对前文历史快照的增量核实；**固定审计源码 SHA** \`0832ac0940ff347d599ab2532bfb74868796b0cf\`，\`VERSION.txt=42.24.592\`。只读检查生产入口源码、现有测试和准确 SHA 的 GitHub Actions；未修改业务代码、未在本地执行测试、未接触生产环境。前文 \`dfdf6f3\` 的 20/21 CI 结果保留为历史证据，不以新状态覆盖旧状态。

### 8.1 准确 HEAD/CI 与边界

- GitHub \`refs/heads/feature/external-algorithm-publishing\` = \`0832ac0940ff347d599ab2532bfb74868796b0cf\`；正式分布式需求 \`docs/DISTRIBUTED_WORKER_CLUSTER_ARCHITECTURE_2026_10_10.md\` 仍为需求权威。
- GitHub Actions 查询 \`head_sha=0832ac...\` 共 **21 个 workflow runs，21 completed/success、0 failure**。其中 Central Node Assignment、Node Agent Executor、Remote Training Runtime、Remote Cleaning Runtime、Remote Material Import、Frontend Runtime Stabilization 均 success。此结论只代表该 SHA 的既有 CI，不证明所缺自动派单闭环已覆盖。
- 早前 \`dfdf6f3\` 的 \`Frontend Runtime Stabilization\` 存在 v19 标签 GET 重复问题；当前 HEAD 通过 CI **不等于根因已经定位**。保持独立问题，不混入分布式业务修复。

### 8.2 P0-01：自动分配触发确有源码缺口，尚未补 RED 测试

1. \`platform_core/task_node_assignments.py:805-944\` 的 \`CentralTaskAllocator.assign_next()\` 能够持久插入 Assignment；\`:1063-1074\` 在 \`POST /api/v63/scheduler/allocate-next\` 显式调用它。
2. \`platform_core/agent_execution.py:622-644\` 的 \`AgentExecutionService.claim_assignment()\` **只**调用 \`self.allocator.claim_for_node(node_id)\`，不调用 \`assign_next()\`；\`node_agent_executor_loop.py:184-323\` 仅轮询 Agent claim API。
3. \`task_worker.py:210-231\` 调用的是本地 \`task_runtime.Scheduler.serve_forever()\`，其 \`task_runtime/scheduler.py:247-260\` 使用 \`TaskRepository.claim_next()\`，不是中央 \`CentralTaskAllocator\` 的自动驱动。
4. 全文检查 \`app.py\` 入口发现 \`@app.on_event('startup')\` 的 \`_v42_source_scheduler_loop\`（\`app.py:22812-22827\`），它是历史来源处理线程，并非中央任务分配；\`training_recovery_api.py:774-796\` 仅挂载路由。现有 \`tests/unit/test_agent_execution.py:104-109\` 和 \`tests/api/test_agent_executor_api.py:104\` 先由测试人工 \`allocator.assign_next()\`，随后才模拟 Agent 领取。
5. **结论：已检查的实际服务入口无持续自动创建 Assignment 的驱动，远程 Agent 仅能领取已有分配。** 单元/API 调度功能存在不能代替自动接单验收；有意不把“来源调度”误判为中央任务调度。

**下一阶段 RED 复现：** 创建 \`execution_mode=agent\` 且有 versioned remote contract 的排队任务、健康合格 Agent；不调用 \`allocate-next\`，仅以 Agent 正常轮询/服务启动驱动，应在有界时间内产生 Assignment 并领取。再测节点上线后自动接单、当前任务结束后下一任务、并发轮询幂等、手动节点严格亲和、旧代次 fencing、断连/重启后的安全恢复。现有代码预计第一项失败；**本轮没有执行 RED，因此不得写作已经复现。**

### 8.3 P0-02：TaskKind + operation + capability + Runner 真实映射

| 任务 | \`task_node_capability\` / 中央映射 | Agent 实际实现 | 第一阶段判断 |
| --- | --- | --- | --- |
| \`TRAINING\` | \`training\` | \`AgentTrainingRunner\` | 可移植条件下有代码；真实硬件待验 |
| \`MODEL_CONVERSION\` / \`DEPLOYMENT_TEST\` | \`conversion[.rknn]\` / \`deployment-test[.rknn]\` | 对应 Runtime Runner | 有条件支持，按实际框架/硬件验证 |
| \`MODEL_INSTALL\` | \`model-upload\` | \`AgentModelInstallRunner\` | 有 Runner，传输/安装环境待验 |
| \`MATERIAL_IMPORT\` | \`material-import\` | \`AgentMaterialImportRunner\` | 仅受控 portable/import 阶段；accepted 后本地正式提交 |
| \`MATERIAL_BATCH/CLEAN\` | \`cleaning\` | \`AgentCleaningRunner\` | 仅 CLEAN 的 \`execution_mode=agent\` portable 合同可远程 |
| \`MATERIAL_BATCH/SMART_AUDIT\` | 错误兜底 \`material-import\` | **没有 SMART_AUDIT Runner** | 必须保持本地，不能把能力名当作已实现 |
| \`MATERIAL_BATCH/AUDIT_* / REMAP_* / REPAIR_*\` | 错误兜底 \`material-import\` | **没有对应 Runner** | 本地 \`MaterialBatchHandler\` 处理，未移植 |
| \`MATERIAL_BATCH/AI_ANNOTATE\` | \`annotation\` | **没有对应 Runner** | 本地，不可远程派单 |
| \`AI_ANNOTATION\` / \`VIDEO_FRAMES\` | \`annotation\` / \`video\` | **Agent 白名单/Runner 缺失** | 本地 Worker 已有，远程未实现 |
| \`TRAINING_PREPARE\` / \`RESOURCE_DISCOVERY\` | \`None\` | 非 Agent Runner | 控制面/本地所有权；不能混同远程任务 |

代码：\`task_node_assignments.py:121-175,215-282\`，\`node_agent_executor_loop.py:18-116,184-262\`，\`node_agent.py:148-235\`，\`material_batches.py:376-448,2648-2697,4805-4815\`，\`smart_material_audit/service.py:95-135\`，\`worker_registry.py:9-24\`。

**高风险边界：** \`_online_nodes\` 虽过滤在线、allowed ∩ reported 和 Agent portable，但对非 Agent 的 local 节点可接受未移植任务；\`AssignmentAwareFencedTaskRepository.claim_next()\`（\`task_node_assignments.py:1027-1055\`）会拦截任何 \`ASSIGNED/CLAIMED\` 任务。若发生 local 节点错误分配，可能形成排队无法被本地 Worker 消费的组合。必须先用隔离测试证实具体触发，再改能力合同；不建议立即全局自动启用 \`assign_next()\` 放大该风险。

### 8.4 P0-03：资源硬容量只有部分准入

\`task_node_assignments.py:333-405,531-569,805-944\`：训练 GPU 选卡排除已预留 CUDA id，按最小空闲显存（至少 1 GiB 或 10%）、GPU 利用率阈值过滤；但并未证明所选任务的真实显存需求预算足够。CPU/RAM/磁盘/执行槽/I/O 主要进入 \`_score_node()\` 的**排序分数**而非统一拒绝门槛，非 GPU 的 CLEAN 等任务缺少一致的持久容量保留。\`NodeAgentExecutorLoop\` 仍仅单任务同步执行，故“同机双 GPU 可分配两张卡”不等于两项任务真能并行运行。P0-01 触发驱动上线前应先设计 P0-02 防误派与 P0-03 最低安全门槛的组合回归。

### 8.5 已有自动训练参数及 OSS 实现边界

- \`node_agent_training_runtime.py:793-1046\`：Agent 得到 \`selected_gpu\` / \`selected_device\` / \`concurrent_reservations\` 后，在 Agent 本机 Ultralytics Python 子进程调用规范资源解析器。\`training_metrics.py:301-455\` 读取实际节点 CPU/可用 RAM、本地磁盘和 \`torch.cuda.mem_get_info(index)\`，解析 Batch/Workers/Cache/Precision；UUID 及执行身份校验存在。\`remote_training_tasks.py:831-870\` 已支持 AUTO+auto GPU 和 AUTO+指定 CUDA 的延后资源决议。**代码已实现关键机制，实机 A800/双 4070、调度切换及资源骤变仍 NOT VERIFIED。**
- \`storage/models.py:8-31\`、\`storage/factory.py:22-50\`、\`storage/manager.py:85-182\` 已有 LOCAL/OSS/S3（MinIO 别名）/REMOTE source 与读取抽象。\`remote_training_inputs.py:50-83\` 通过中央鉴权的 \`StorageManager.open_reader\` 代理向 Agent 流式传输冻结图像；可跨源工作，但 **不是 Agent 直接读取 OSS/NAS**。结果端可移植 bucket 配置、访问范围、带宽成本、节点本地缓存及真 OSS/MinIO 端到端均 NOT VERIFIED。中央正式 GT 和冻结 Snapshot 所有权保持不变。

### 8.6 当前验收和后续实施边界

- **本轮完成：** 需求逐项对照、当前 HEAD 与 21/21 CI 复核、生产调用链只读审计、现行 Agent 任务矩阵与 P0 优先级明确。
- **本轮未完成：** RED/GREEN 运行、源码修复、OSS/NAS 非生产联调、GPU/CPU 压测、生产 UAT；禁止把已有 CI 记成这些场景的验收。
- **下一步最小开发顺序：** (1) 新增无人工 allocate 的 RED 合同，并验证实际失败；(2) 在同一测试中对不支持 Agent 的 operation、local Worker 和手动亲和增加 fail-closed 用例；(3) 复用 \`CentralTaskAllocator\` 在控制端或 Agent 领取入口实现有界、幂等、无第二套队列的自动推进；(4) 然后单独推进资源硬预算、Agent 多执行槽、OSS 直连和真实环境 UAT。不可简单启动多个未经租约保护的调度线程，不可将算力评分当作硬准入。


### 8.7 第一阶段补充发现：RKNN 部署 Agent 能力声明与实际分派不一致、离线 Assignment 恢复缺口

1. \`node_agent_executor_loop.py:18-49\` 宣称支持 \`deployment-test.rknn\`，\`effective_capabilities()\` 能将其上报；但是 \`run_once():219-240\` 对 \`DEPLOYMENT_TEST\` 使用的 \`allowed_capabilities\` 只有默认 \`deployment-test\`，特殊兼容集合仅为 \`MODEL_CONVERSION\` 提供。故一旦领取要求 \`deployment-test.rknn\` 的任务，会在调用 \`start_execution()\` 前被拒为 \`UNSUPPORTED_AGENT_TASK_KIND\`。现有 \`tests/unit/test_node_agent_executor_loop.py:379-388\` 只验证能力上报，不覆盖此类真实领取执行。**确定性源码合同缺陷，尚未增加 RED 测试；按 P0-02 单独精确修复。**
2. \`task_node_assignments.py:805-822\` 排除所有已有 \`ASSIGNED/CLAIMED\` 的排队任务；\`:971-1025\` 仅在**同一节点**调用 \`claim_for_node()\` 时将该节点过期 CLAIMED 重新变成 ASSIGNED。若节点失联且分配仍为 ASSIGNED，目前审阅的自动派发/恢复入口没有证明旧分配会在 TTL 后安全释放并重新分配。该项需按 node TTL、generation/fencing、进程清理确认补负例；不能直接按超时盲目双重分配。


## 9. P0-02 最小修复候选：Agent TaskKind / Operation 准入收敛（2026-11-14）

> **基线与开发顺序：** 从 \`de174436c32513a5beb86e94af4b771cf221800a\` 开始；先提交 RED 隔离测试 \`f906af45\`（MaterialBatch 与 local-only 任务）、\`4bc44d43\`（RKNN 部署测试 Agent claim），后提交业务补丁 \`f41ae22a\`（中央能力映射）和 \`10b880d6\`（RKNN Runner claim）。正式 VERSION 仍是 \`42.24.592\`。未修改数据库 schema、任务数据、Worker 启动入口、现有训练参数或自动派单驱动；未部署 A800/4070。由于 Actions 排队期间已有 GREEN 补丁提交，不能仅凭静态预期将 RED 测试记作已执行失败。

### 9.1 已确认的根因

- \`task_node_assignments.py::task_node_capability\` 原先将 \`TaskKind.CLEANING\`、\`AI_ANNOTATION\`、\`VIDEO_FRAMES\` 映射为清洗/标注/视频能力，尽管当前 \`NodeAgentExecutorLoop.SUPPORTED_AGENT_TASK_KINDS\` 没有这些 Agent Runner。它还将 \`MATERIAL_BATCH\` 除 CLEAN 和 AI_ANNOTATE 之外的所有 operation 默认映射成 \`material-import\`，其中包括 \`SMART_AUDIT\`、完整性审计、GT 标签重映射等本地正式处理任务。这样会让中央 Assignment 提前拦截本地 Worker，形成错误节点分配或长时间等待。
- \`node_agent_executor_loop.py::run_once\` 已允许 \`conversion.rknn\`，但对 \`DEPLOYMENT_TEST\` 只允许普通 \`deployment-test\`；\`deployment-test.rknn\` 能上报却会在开始执行前被误拒绝。

### 9.2 范围严格受控的修改

1. 中央 \`task_node_capability\` 不再给 \`CLEANING\`、\`AI_ANNOTATION\`、\`VIDEO_FRAMES\` 分配虚假的可远程执行能力，交由原本地 Worker Owner 保持处理。不得把此举误称已实现相应远程 Runner。
2. \`MATERIAL_BATCH\` 只有 \`operation=CLEAN + execution_mode=agent\` 返回 \`cleaning\`，其余 operation 和本地 CLEAN 均交原本地 \`MaterialBatchHandler\`；Agent CLEAN 仍需原有合法 \`remote_execution\` 可移植合同，缺失合同不向 local 回退。
3. \`DEPLOYMENT_TEST\` Agent 领取允许 \`deployment-test\` 或 \`deployment-test.rknn\`；仍要求当前 Agent 实际 \`effective_capabilities\` 精确包含所需能力和真实 Runner ready，否则拒绝开始执行。没有把任意部署执行器提升为 RKNN 执行器。
4. 在 \`tests/unit/test_task_node_assignments.py\` 新增参数化 local-only 任务与 operation 负例，要求未产生 Assignment，并保留原 \`AssignmentAwareFencedTaskRepository\` 本地 Worker 领取；补 Agent CLEAN 无 portable 合同不回退 local 测试。
5. 在 \`tests/unit/test_node_agent_executor_loop.py\` 新增 RKNN 专用能力真实领取执行和 generic capability 不匹配的否定测试，避免只检查心跳能力名字。

### 9.3 验收边界与风险

- 本批**没有**实现 P0-01 自动派单，也没有上线更激进的 CPU/RAM/disk 资源准入或 Agent 多线程并行。当前 A800 生产环境未更改；若未来部署新版本，现有本地 Worker 应继续负责 AI 标注、视频抽帧、智能审计、标签统一等任务。
- 当前仍存在历史前端 CI 独立问题：基线 \`de174436\` **21 workflow runs = 20 success + 1 failure**；失败分片 \`Frontend Runtime Stabilization\` 的 \`tests/browser/training-create-scroll.spec.mjs:36\`，本专项未修改该文件，也不将失败归咎于本专项。
- 本批 RED/GREEN、新 HEAD 的定向 Python Linux/Windows、Agent 合同、全仓 CI 终态必须以**准确提交 SHA** 再查；如果未终态写 \`PENDING\`，不宣称通过；真实 A800/4070 GPU、多服务器、OSS/NAS 以及生产 UAT 仍全部 \`NOT VERIFIED\`。
- 回滚：仅回滚 \`task_node_assignments.py\` 和 \`node_agent_executor_loop.py\` 两个业务改动到基线（并按实际依赖撤回对应测试），无需 schema 迁移或数据操作；正式上线仍需要单独的 A800 版本兼容性、备份与停机窗口验收。


### 9.4 Agent Runner 实际注册与能力上报（P0-02 补充）

- 经源码复核 \`NodeAgentExecutorLoop.effective_capabilities()\` 曾只针对 \`model-upload\` 缺失 Runner 特判，而对 \`training\`、\`conversion\`、\`material-import\`、\`cleaning\` 缺少实际 Runner 的 Agent 仍可能上报能力。这样中央分配器会以错误心跳作出派单决定。
- 测试提交 \`cdd162b2f807e2f4eca9d8bd8ee4f376112ec755\`，修复提交 \`e80ea129e0564f16609145bca0e0e5ee4b28cf83\`：所有能力统一要求对应 TaskKind 已注册真实可调用 \`run()\` 的 Runner，并要求 \`ready != False\`，否则不包含在有效能力心跳中；不改变任务 Lease/Claim、Runner 调用或本地 Worker。
- 本节记录的是**代码候选修复**，不是完成验收。准确 HEAD 的 Actions 在本次核查时仍排队；RED/GREEN 执行日志、A800 实机、其它 GPU/OSS 的端到端行为均待核。不从本轮未执行的 RED 测试推断为已验证失败。

### 9.5 P0-01 自动派单启动前的强制安全准入（未开发）

1. 自动推进不得直接调用没有限定范围的 \`CentralTaskAllocator.assign_next()\`，因为它当前也会考虑本地 Worker 使用的 \`TRAINING\` 和其他本地任务。否则可能提前写入 ASSIGNED 并阻断 A800 本地 Worker；需要明确只处理可移植 Agent 合同且显式远程执行意图的任务。
2. 新入口必须**默认关闭**，显式开关 + 受控任务范围 + 真实在线合格节点才允许分配；启动或停用不能迁移、抢占或重写已有 RUNNING/QUEUED 的本地任务。
3. 不增加第二套 Scheduler/Queue/DB Owner；沿用中央事务唯一约束、原 TaskRepository 及 Agent Claim，明确同一节点的真实执行槽，不允许单线程 Agent 因双 GPU 遥测被无限预分配。
4. 分配与 claim 的异常、失联、时钟与 generation 栅栏必须具备保守恢复路径；在无法判断旧执行是否仍在运行时**不能自动重派**。
5. P0-02 准确 HEAD 的 Central Node Assignment、Node Agent Executor 与 RKNN 合同 CI 未确认 GREEN 前，不推进 P0-01 的自动运行时入口；任何 A800 部署、Worker 重启或任务迁移仍需独立授权。


## 10. 2026-11-14 P0-02 验收终态与 P0-01A 受控自动派单首轮（候选，CI 待核）

### 10.1 P0-02 已取得真实 RED/GREEN 证据

- P0-02 精确审计 HEAD \`12f938c5ca091b94e3a2c99f698a61a626247903\` 的 21 个 workflow run 已终态：**20 success、1 failure**。三个必须通过的 \`Central Node Assignment\`（run 43559784921，Linux/Windows/真实 API 成功）、\`Node Agent Executor\`（run 43559785146，Linux/Windows/真实 API 成功）、\`Remote RKNN Board Runtime Protocol\`（run 43559784871，Linux/Windows/API/Chrome 成功）全部为 SUCCESS。
- 真实 RED：测试先行 \`4bc44d43\` 的中央能力合同报告 12 个不支持的 local-only 操作错误映射，Agent 合同报告 RKNN 领取被拒绝；补充 RED \`cdd162b2\` 的 Runner 缺失能力心跳合同报告 1 个失败。随后业务修复与准确 HEAD 上述合同 GREEN。**仅认定 P0-02 代码与 CI 层完成；远程 AI/视频/检查 Runner 和生产部署仍不包含在此完成定义。**
- 准确 HEAD 前端独立红项 \`Frontend Runtime Stabilization\`（run 43559772709），\`browser-navigation (1)\` 130 passed/1 failed，\`tests/browser/annotorious-poc.spec.mjs:48\` 官方编辑器绘制后 \`createAnnotation\` 事件仍为 0；不将此故障冒称调度引入，也不宣称全仓 CI 全绿。

### 10.2 P0-01A 第一段实现：认证 Agent 轮询触发有界自动派单

- 代码修改集中于已有 \`CentralTaskAllocator.assign_next(*, agent_only=False)\` 与 \`AgentExecutionService.claim_assignment\`，HTTP 原路由工厂读取唯一显式开关 \`CHANGLIAN_AGENT_AUTO_ASSIGN_ON_CLAIM\`：**仅字符串 \`1\` 开启，默认完全关闭**。现有人工 \`allocate-next\` 和既有本地 Worker 路径不改。
- 当已认证、启用、心跳在线且为 \`agent\` 模式的节点正常调用原领取 API，且当前没有自己的 Assignment 时，才触发**一次**原中央 allocator 的 \`agent_only=True\` 事务分配，再按原 \`claim_for_node\` 领取；既有 Agent 轮询负责后续推进。不是新建数据库、队列、长期线程或第二 scheduler。全局 allocator 仍按真实资源评分和手动 pin 排序，允许将任务分配给比本次请求节点更合适的其他在线 Agent，不强制偏向发起轮询的节点。
- \`agent_only=True\` **同时要求** \`task_node_connection_mode(...) == "agent"\` 与合法版本化 \`remote_execution\` 合同；有可移植元数据但仍是本地模式的 A800 训练不得自动分配。局部 \`_node_active_work_count\` 已有 Assignment 或 RUNNING 计数时不再为当前串行 Agent 预分配第二任务；多 GPU 真并行属于后续多执行槽专项。新 Agent 分配扫描不调用原 \`_resume_ready_preemptions_in\`，以免修改无关本地抢占恢复任务。
- RED 测试提交 \`ec9cc29f\`、\`a40c0447\`、\`dff159c3\` 分别覆盖 local-only 不被拦截、双 GPU 单执行槽、手动 pin、默认关闭、HTTP 按开关开启、节点鉴权；代码提交 \`2d879e05\`、\`5ab51dc2\`；补充单执行槽释放后下一轮自动推进、并发双请求唯一分配的测试 \`f317ddac\`、\`41c8238b\`；无关抢占恢复扫描修正 \`7f70077a\`。所有本节新提交的具体准确 SHA CI 必须独立查询，不把前一轮 P0-02 GREEN 视为 P0-01A 验收通过。

### 10.3 尚未完成且不能提前启用生产的准入条件

1. **P0-01A 新版本定向 CI（Linux/Windows/API）与 RED→GREEN 真正测试日志**仍需完成，任何失败先查具体原因。
2. 多节点长轮询高频扫描可能让 \`assign_next\` 在存在大量本地 QUEUED 任务时频繁进入 \`BEGIN IMMEDIATE\` 事务；尚未取得 1k/10k 任务队列、多个 Agent 并发请求、A800 同库任务创建/领取 P95 的性能和锁争抢证据。**即便准确 CI 全绿也不得直接给 A800 开启开关。**
3. 离线节点遗留 \`ASSIGNED\` / \`CLAIMED\`、旧执行进程仍存活的安全恢复尚未完成；本轮不擅自释放旧 assignment、不允许自动跨节点重复训练，需另外设计保守的 lease/generation/fencing 接管。
4. P0-03 CPU/RAM/磁盘/I/O/执行槽硬预算、多 GPU 两任务真并行、远程素材检查/AI 标注/视频/标签统一 Runner、真实 OSS/NAS 数据亲和及控制端负载均未因本轮自动领取实现而完成。
5. 没有访问、部署、重启或修改 A800/4070 的程序、数据或服务。生产升级、切换执行模式、打开 \`CHANGLIAN_AGENT_AUTO_ASSIGN_ON_CLAIM=1\` 必须经过**单独授权、当前系统只读核验、备份、隔离 UAT 和明确回滚预案**。


### 10.4 P0-01A 追加审计：写锁隔离、本地训练防抢占、大队列可发现性

> 2026-11-14 接续 \`0c18f58c97e923226bd04318c55176cc9215bae2\` 之后的第二轮最小专项，仅涉及 \`platform_core/task_node_assignments.py\` 和 \`tests/unit/test_task_node_assignments.py\`；准确新 SHA CI 未终态时均按 **PENDING / NOT VERIFIED** 记录，不把代码提交称为验收成功。

1. **读取本地队列不持有写锁：** 原 \`assign_next(agent_only=True)\` 在 \`BEGIN IMMEDIATE\` 后 \`SELECT task.*\` 并逐个读取本地素材/训练请求文件；如果大量本地排队任务存在，高频 Agent 轮询会独占 SQLite Writer，风险覆盖 A800 本地 Worker/Task API。新增 RED \`1d9f15a26d6f5b40fdc592cbf433eb96557b3af6\`：在读取本地任务 JSON 时独立 SQLite 连接尝试 \`BEGIN IMMEDIATE\`，要求不被 Agent 扫描阻塞。修复 \`2c71c92c1f0da6d53b70c5c6e92e5a415d93e2df\`：Agent-only 先使用读连接筛选支持 TaskKind、明确 Agent 模式及合法 portable 合同，释放读连接后进入原唯一事务，按候选 ID 重新验证 QUEUED/无活动 Assignment，再计算实际在线节点与 GPU/单执行槽。**人工 \`assign_next()\` 原逻辑未改**。
2. **显式远程训练不得被本地 Worker 先领走：** 正式 \`RemoteTrainingPreparation._activate_target\` 会把远程目标标记为 \`training:remote:scheduler\`。原 \`AssignmentAwareFencedTaskRepository.claim_next\` 只检查已有 Assignment，尚未自动派单时本地训练 Worker 可能先领取；其原 GPU 准入又显式跳过 \`training:remote:\`，存在执行 Owner 错乱风险。新增 RED \`977becf3acb3f6856f47d1fb6d7e8184c635c304\`；修复 \`e0580d1529d1866e2379d7ccc4c287907350b6bd\` 在原本地领取守卫只针对 \`TaskKind.TRAINING\` 且 \`resource_key.startswith("training:remote:")\` 拒领并返回可诊断原因；不拦截普通 A800 本地训练，Agent 仍使用现有原子 QUEUED→RUNNING 租约。
3. **较大队列防饿死功能测试：** \`cae3d4dcc9fd8b18706b285f487a23961890ac77\` 增加 1,500 条隔离生成本地训练队列元数据、末尾低优先级可移植 Agent 任务场景；\`9ea32ddf35275d16b51b2afc10ff4c8933490857\` 用一次 SQLite 事务批量生成测试数据，避免逐条 autocommit 污染结果。验证目标是**远程任务仍可被正确找到**，不是 1,500 条真实图像读写或 P95 压测。
4. **进一步收敛预检与心跳时间：** \`99d622f914948fa424b099c170619062fc57cea2\` 在 Agent-only 预筛查 SQL 排除不支持远程执行器的 TaskKind，获取真正 Writer 事务后刷新在线心跳时钟；避免慢预检的过时在线证据导致错误分配。仍在原事务内重新检查严格 Node Pin、能力、GPU 与执行槽。
5. **严格风险边界：** 这一版没有新增 DB schema、第二队列、任务迁移、自动释放过期远程 Assignment、GPU 并行执行器或 Worker 守护进程。真实多节点 10k+ QUEUED Agent 高频轮询仍可能占用 API CPU/磁盘读取，需真实不同排队比例下测量 P50/P95、SQLite \`busy\` 次数和远程候选扫描成本；未证明 20k/200k 全量队列在生产下达标。Agent 失联与旧进程未知时不得自动跨节点重派；后续 P0-01B / P0-03 独立处理。
6. **CI 与生产：** P0-01A 初始 HEAD \`0c18f58c97e923226bd04318c55176cc9215bae2\` 的 \`Central Node Assignment\`（run 43564229848）首次查询为 SUCCESS，而 \`Node Agent Executor\`（run 43564229918）及其余相关工作流仍未终态；最新这一批完整 Linux/Windows、HTTP、Agent、真多节点、真实 A800/4070/OSS 性能和生产部署均需要独立验收。不开启 \`CHANGLIAN_AGENT_AUTO_ASSIGN_ON_CLAIM\`，不操作生产环境。

### 10.5 Agent 高频轮询鉴权性能专项与阶段 CI

- 旧入口每次 Agent `/assignments/claim` 都调用 `AgentExecutionService._authenticate_node -> ServiceNodeRepository.get_public`。后者除验证当前 node 的心跳/权限外，还读取 `WorkerInstanceService.list_runtime` 和全库运行中的 Worker/Task 投影，即使当前领取无任务也重复做这些全局查询。此入口处于每个 Agent 的高频正常轮询路径。
- 新 RED 测试提交 `8396203414e78eec89e8a3791436a2401bc950c2`：当禁止调用 `_runtime_projection` 时，正常 Agent 领取仍应成功返回空。此测试的实际 RED CI 尚未确认，不能冒称已复现。
- 最小修复提交 `f769c6bd9ec4851f33a4efcbc11871380c5c72fd` 在 `service_nodes.py` 新增 `get_execution_admission`：单节点权威行+原 `_public_row` 的状态/在线/能力投影，不枚举全局运行态；提交 `4d07db5736533732fbdf015a97b1573270d574b6` 使 `_authenticate_node` 使用轻量入口。Node UI 继续走原 `get_public`，完整 workers/durable_tasks 展示不变；鉴权仍在业务调用之前，`ServiceNodeRepository.authenticate` Token 校验不变。
- `0c18f58c97e923226bd04318c55176cc9215bae2` 作为 P0-01A 初始业务实现 SHA，21 项 workflow 已终态：20 success、1 cancelled、0 failure，关键 Central Node Assignment 与 Node Agent Executor 均 SUCCESS；取消的工作流不可当作通过。该结果只验初始版本，**不能覆盖后续扫描事务解锁、远程训练防抢占以及本轮鉴权性能优化**。
- 最新业务修复 `4d07db5736533732fbdf015a97b1573270d574b6` 及之后的最终 HEAD CI 仍需按准确 SHA 查询。真实 1k/10k 队列、多个远端 Agent、SQLite P95、节点失联/过期后防重执行、A800/4070 和 OSS 网络路径均未做生产验收；默认开关 `CHANGLIAN_AGENT_AUTO_ASSIGN_ON_CLAIM` 保持关闭。
