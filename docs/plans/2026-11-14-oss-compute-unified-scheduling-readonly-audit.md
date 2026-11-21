# 畅联云算法训练平台｜OSS／计算服务器可配置与统一调度架构只读审计（2026-11-14）

**审计代码基线：** `6477320a344c039be52cc42fa6cbeaab3a3ff993`  
**分支：** `feature/external-algorithm-publishing`  
**性质：** 静态代码审计＋现有单元／API 合同核查。未接触生产环境、未执行真实 OSS、跨节点并发及 20k/30k 图片端到端测试。仅新增本报告，不改变业务逻辑。

## 一、长期产品约束（以后开发必须保留）

1. **存储／计算解耦**：素材可存放在本地、阿里云 OSS、S3／MinIO（可配置存储源），不得默认所有素材均存在 Web／训练服务器本地磁盘；正式 GT、素材身份、训练快照和来源定位属于中央业务权威，不得复制出无监督的第二套数据库。
2. **服务器统一管理**：应可配置多台计算服务器／Agent，按节点能力承担素材检查、存储扫描／导入、清洗、AI 标注、模型转换、训练、部署测试等；节点可动态上下线，具备授权、心跳、版本、运行时能力、排队与故障诊断。
3. **统一调度**：调度按照任务能力、节点在线／健康、GPU/CPU、RAM、磁盘、队列负载、存储访问策略及网络／数据传输可达性分配；支持自动选服务器和手动指定服务器（指定后不允许无提示迁移）。
4. **训练真实资源决策**：自动模式在队列实际分配服务器**之后**，按该节点真实 GPU、显存、利用率、CPU/RAM/磁盘、并发预留量决定 batch/workers/cache/precision 等；用户自定义值受相容性校验，不把 Web 机器配置当成目标节点配置。
5. **数据完整性与隔离**：跨节点必须使用冻结输入、内容哈希、可移植合同、安全授权流；远程 Agent 不依赖直接共享控制端 SQLite、控制端绝对路径或原始访问密钥。数据源变更、取消与执行租约失效时安全拒绝。
6. **不以大重构替代验收**：先用隔离合同证实能力缺口，再做局部修复；保留已有工作流和 SQLite 权威数据模型。任何 A800／双 4070 生产部署、Worker 重启、数据变更均需用户明确授权。

## 二、代码审计矩阵

| 需求 | 当前判定（代码层） | 实现证据及边界 |
|---|---|---|
| 本地／OSS／S3／MinIO 可配置存储源 | **已有** | `platform_core/storage/models.py` StorageType.LOCAL/OSS/S3/REMOTE；`factory.py` 创建对应 provider；`oss.py` / `s3.py` SDK、上传下载、健康检查与签名 URL；`source_repository.py` 持久配置、密钥引用、默认来源及健康状态；`tests/api/test_storage_sources.py` 有合同。未做真实 OSS 网络验收。 |
| 素材记录关联具体来源、按来源读取 | **已有** | `MaterialRepository` 素材具有 `storage_source_id`、`object_key`、`content_sha256`、`size_bytes`；`StorageManager.materialize` 根据来源走本地路径或验证下载缓存。改默认存储源不等于迁移旧对象。 |
| 多节点注册、心跳、能力授权 | **已有** | `service_nodes.py` 存节点模式(local/agent)、节点能力白名单、令牌、45 秒心跳、资源快照及在线状态；能力必须在 allowed ∩ reported 范围内。 |
| 中央持久化调度、自动／指定节点 | **已有，覆盖有条件** | `task_node_assignments.py` 调度器持久化分配、在线过滤、能力过滤、队列优先级、`scheduling.mode=node` 强亲和、执行租约／fencing。Agent 任务须带 `remote_execution` 可移植合同，不得把本地合同强行迁移。 |
| 多 GPU 节点可多任务分配 | **调度有，Agent 执行容量待对齐** | 调度器可以为一个节点的不同 GPU 分别分配任务（`tests/unit/test_task_node_assignments.py::test_multi_gpu_node_assigns_distinct_gpus_then_queues_next_task`）；但 `node_agent_executor_loop.py` 明确单线程／`run_once` 单任务串行。一个 Agent 进程不能由此推断具备同机多任务并行，更不能等同单任务多 GPU／多节点 DDP。 |
| 排队后依据真实节点资源自动训练配置 | **代码已支持，部署待验** | `task_node_assignments.py` 节点 GPU 选择＋并发预留快照；`node_agent_training_runtime.py::_prepare_project` 使用选中设备、selected_gpu、并发预留和真实硬件运行时调用资源 resolver 解析 batch/workers/cache/precision；`agent_execution.py` 校验解析结果身份。要验证节点变化、队列时间、资源不足及手动/自动模式。 |
| Agent 远程训练、远程获取存储素材 | **已有，仍需 OSS/网络压力验收** | `remote_training_tasks.py` 在 Prepare 阶段冻结元数据并产生可移植任务；`node_agent_training_runtime.py::_materialize_indexed_inputs` 下载图像并在 Agent 本机生成数据集；`remote_training_inputs.py` 在中央控制端用 `StorageManager` 验证数据源并向 Agent 流式提供素材。注意远程训练输出要求配置 OSS/S3 类可移植存储；素材源本身则可与其不同。 |
| 大量图片直接由计算节点访问 OSS，调度具备数据亲和 | **部分／未完整实现** | 目前被检查的远程训练路径走中央控制端的鉴权 HTTP 素材代理，不是所有节点直连 OSS；中央端可能承担重复流量。调度评分依据 GPU/内存/磁盘/CPU/活跃任务，未看到可验证的源 Bucket／Endpoint 可达性、出口流量成本与数据地域亲和校验。不可据此认定未来跨地域对象存储已优化。 |
| 远程导入／存储扫描 | **已有部分能力** | `node_agent_material_runtime.py`、`remote_material_import.py` 有 Agent 导入扫描、分批拉取、结果回传和审核合同；`tests/api/test_storage_sources.py` 含 Agent 存储重扫的隔离合同。实际 OSS 及多节点部署未验证。 |
| 远程清洗 | **已有部分能力** | `material_batches.py` CLEAN 支持 `execution_mode=agent` 和 `scheduling`；`node_agent_cleaning_runtime.py` Agent 分批读取、分析、回传；`remote_cleaning.py` 控制端写入正式事实。需要实际网络、取消与大规模验证。 |
| 智能素材检查 SMART_AUDIT 可指定独立远程检查服务器 | **尚未满足** | `smart_material_audit/service.py` 创建 `TaskKind.MATERIAL_BATCH`、`operation=SMART_AUDIT`、`required_capabilities=(materials.batch,materials.smart_audit)`，在 `material_batches.py::MaterialBatchHandler.run` 由本地材料 Worker 执行；Agent 可执行能力集合不含 SMART_AUDIT 专项 runner。且 `task_node_capability` 对非 CLEAN/AI_ANNOTATE 的 MATERIAL_BATCH 默认映射 `material-import`，与 `materials.smart_audit` 不一致，存在节点选错／排队卡住的待复现风险。 |
| AI 标注／视频任务按远程 Agent 任意调度 | **尚未满足** | `service_nodes.py` 能力枚举包括 annotation/video，`task_node_assignments.py` 可映射；但 `node_agent_executor_loop.py` 的实际 `SUPPORTED_AGENT_TASK_KINDS`、`SUPPORTED_AGENT_EXECUTOR_CAPABILITIES` 不包含 AI_ANNOTATION、VIDEO_FRAMES 或 annotation/video runner。中央本地 Worker 支持对应任务≠独立远程服务器支持。 |
| 资源发现任务可跨远端 Agent 跑 | **未证实／当前偏本地** | `resource_discovery/tasks.py` 是本地 Worker 的 `RESOURCE_DISCOVERY`，而 `task_node_capability` 对其不返回远程能力；节点 Agent 的心跳资源遥测已有，不能把它与控制端本地深度模型扫描混为一谈。 |
| 生产端到端 OSS+多节点+真实 GT+完整训练 | **待验收** | 现有 API/单元合同覆盖接口与隔离任务，不能证明 A800、双 RTX 4070 的实际连接、可用 Worker 角色、并发与生产延迟。 |

## 三、优先问题及建议最小专项

### P1-A：任务能力映射与实际执行器能力一致性

- 对 SMART_AUDIT、AUDIT_MATERIAL_INTEGRITY、AUDIT_LABEL_INTEGRITY、AI_ANNOTATE、VIDEO_FRAMES、AI_ANNOTATION 等建立任务类型／operation／required_capabilities／node capability／Agent runner 对照表。
- 对不能远程执行的任务显式标为 local-only，保证中央调度器不提前占有错误节点的任务；补充真实 TaskKind/operation 资格回归和错误信息。
- 智能素材检查的独立服务器化是新增可移植执行合同＋Agent runner 的功能开发，不是只在 UI 加一个服务器下拉框；正式素材／GT 的持久写入仍应在中央完成。

### P1-B：调度容量与 Agent 实际并发对齐

- 明确 Agent 单进程串行与多 GPU 多分配任务之间的容量语义。以真实双 GPU 节点测试两任务并行、第三任务排队、单 GPU 被多任务错误重复占用等合同。
- 需要真正多并发时，逐 GPU 独立 Agent 执行槽＋租约／隔离是可评估方向；**不得**简单把执行线程数调大破坏任务租约。单任务多卡 DDP 应独立专项。

### P1-C：存储可达性与数据传输计量

- 增加仅探测式、无密钥暴露的候选节点来源可读性/目标结果桶可写性/配额/磁盘预算；不能把节点健康等同于对该任务素材的存储可达性。
- 记录 20k/30k 图片的控制端代理流量、远端吞吐、缓存命中与数据准备时长，再决定是否实现短期授权的 Agent 直连 OSS。
- 明确「素材来源可选本地/OSS/S3」与「远程训练结果输出需要可移植 OSS/S3」是两个不同配置对象。

### P2：真实部署验收矩阵

至少覆盖：本地来源→本地训练、本地来源→Agent 训练、OSS/S3→Agent 训练、OSS/S3→Agent 清洗／导入、无能力节点等待、指定节点离线严格等待、节点重启／租约失效、真实 GPU 资源变化后自动配置、同节点双 GPU 并发、素材 GT 证据一致性、取消、临时文件空间/回收。均先做非生产或获授权隔离环境。

## 四、结论

**总体结论：部分满足**。存储抽象、节点管理和中心调度框架已有；远程训练／清洗／存储导入具备有限可移植执行能力；但「全部素材检查／AI 标注／视频任务可配置独立服务器并统一调度」、存储数据亲和、Agent 多 GPU 实际执行容量和生产端到端验证尚不完整。

**开发约束：** 不大重构，不直接把全部素材复制到某台训练服务器，不把 OSS 作为 GT 数据库，不混淆训练任务分配与训练超参配置，不擅自改生产部署。先验证任务合同及能力缺口，后做精确改动。

## 核查入口

- `platform_core/storage/{models,source_repository,factory,manager,s3,oss}.py`
- `platform_core/{service_nodes,task_node_assignments,node_agent_executor_loop,node_agent_training_runtime,remote_training_tasks,remote_training_inputs,node_agent_cleaning_runtime,node_agent_material_runtime}.py`
- `platform_core/smart_material_audit/{service,worker}.py`、`platform_core/material_batches.py`
- `tests/unit/test_task_node_assignments.py`
- `tests/api/{test_central_scheduler_api,test_service_node_api,test_storage_sources}.py`
