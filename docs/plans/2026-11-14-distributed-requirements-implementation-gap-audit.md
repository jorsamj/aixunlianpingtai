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
