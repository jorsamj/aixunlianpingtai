# 功能/API迁移矩阵（M0基线2026-11-18）

## 14 个正式菜单及后台闭环（2026-11-26，当前）

批量安全与训练环境候选（2026-11-26）。训练任务墙的批量删除按所选集合校验回执并分列“记录删除/按原证据保留/跳过执行中/未找到/失败”，未知结果保留待核验记录并用新增只读 `deletion-status` 端点核对（≤200，不删除不重试）；新增训练环境与母模型原生页（显式探测、资产校验与 `.pt` 上传、节点发现清单与安装任务只读）；评测共享身份与最新创建排序口径对齐。菜单、名称、顺序、默认入口与原 API/Owner 未变。运行期与视觉为 `CI_PENDING / VISUAL_PENDING`。未完成：标签预设与负样本分类（无 HTTP API）、批量暂停/恢复/停止（无批量 API）、存储扫描导入创建、算法卡片投影、总览历史趋势。

评测语义与工作台候选（2026-11-26）。严格排名证据统一到 `training_evaluation` 共享函数（基准摘要 + 输入绑定 + verified_independent 历史独立性 + 协议 + 类别身份），v49 报告不再自持规则；最新创建版本身份由版本分页 Owner 有界返回，翻页不再读取完整报告；训练任务墙原生接入 v48 批量删除（≤200、跳过执行中、保留版本与产物）；AI 创建与清洗工作台补充范围与状态事实；转换创建/详情改用工作区令牌并明示证据分层。菜单、名称、顺序、默认入口与原 API/Owner 未变。运行期与视觉为 `CI_PENDING / VISUAL_PENDING`。未完成：算法卡片投影、标签快捷预设（后端无 API）、节点环境原生入口、有界历史趋势。

版本身份与评测可比性候选（2026-11-26）。v49 轻量报告新增同口径可比性投影（复用 `compare_evaluations` 合同），算法报告按基准与协议分组展示组内最佳并标注窗口边界；算法库版本面板改用服务端全算法 `latest_created_version`，不再以分页第一条冒充最新创建。当前版本、最新创建、最佳评测三项身份独立，不跨基准排名。菜单、名称、顺序、默认入口与原 API/Owner 未变。运行期与视觉为 `CI_PENDING / VISUAL_PENDING`。算法卡片列表的同类投影与 AiCreate/NativeCleaning 页面级优化待下一轮。

资源与交付页产品化候选（2026-11-26）。算力与节点、模型转换环境、存储管理、平台对接、畅联云数据、AI 辅助配置新增页面级信息架构与状态表达；标签管理、视频切帧、AI 标注任务补充概览与状态语义；AI 审核以 `role=status` 暴露审核状态。菜单、名称、顺序、默认入口与原 API/Owner 未变。自动标注及清洗、转换创建/详情、算法报告深层归因仍未做页面级专项优化。运行期与视觉为 `CI_PENDING / VISUAL_PENDING`。

核心链路工作台候选（2026-11-26）。算法库卡片明确当前版本指标口径并区分主次操作；素材库动作按常用/次级分组；训练任务补齐算法版本、运行设备、耗时与失败原因并使用共享状态标签；总览新增有界失败任务面板；质量中心标注本页检查范围。菜单、名称、顺序、默认入口及原 API/Owner 未变，运行期与视觉为 `CI_PENDING / VISUAL_PENDING`。资源与交付六个菜单本轮未做页面级专项优化。

定向候选 `cc59bc0c272cf94fa547dc9349ae3f5e8598e0b0` 校正审核入库弹窗阶段操作与范围回归用例。业务状态不变，运行期仍待 CI。

视觉候选 `8ba383fa8691dac3243d830b7dfdaa0531796fe7`。原生页面经独立应用主题统一控件、表格和弹窗。AI 审核、素材库、算法库、人工标注及训练表单/报告另做页面级调整。运行期及视觉为 `CI_PENDING / VISUAL_PENDING`。下方沿用上一轮已实现的业务范围及状态，配套 [前端设计规范](../FRONTEND_DESIGN_SYSTEM.md)。

代码候选 `75e41e0d3fea764ca16ba55ab370ddf1746dda6c`。功能状态描述源码覆盖，运行期、视觉和现场分列为 `CI_PENDING / UAT_PENDING / PRODUCTION_NOT_VERIFIED`。

|菜单|状态|原入口、Vue 及原 API/Owner|尚未迁移或验证|
|---|---|---|---|
|总览|NATIVE_PARTIAL|原总览 → Overview，v53 核心快照和有界近期任务|历史趋势、资源诊断|
|质量中心|NATIVE_PARTIAL|原质量中心 → QualityCentre，v53/v61 有界检查、v44 本页质量、v62 报告与原 ECharts|Smart Audit 全库分析界面、场景实测及高级评测|
|算法库|NATIVE_PARTIAL|原算法卡片与交付 → Algorithms/ConversionDetail，算法版本历史、转换记录、v39 硬件回执和未领取恢复|整算法删除 409，转换终态和已领取板端恢复缺安全准入。深层血缘报告及真实硬件待验|
|训练任务|NATIVE_PARTIAL|原任务、报告 → TrainingIteration/NativeEvaluation/TrainingCreate，v64 困难样本游标、原 TaskRepository 历史、固定 Test 与继续训练来源|原训练批量管理、报告深层归因|
|素材库|NATIVE_PARTIAL|原数据集 → Materials/MaterialDatasets/MaterialBatchGovernance，v62 后台归属和用途。正式人工标注沿用原 Annotorious 和 GT。算法级 v1 及公共 v2 负池支持跨页操作|算法级负池高级分类与审核仍有原入口，每次成员写入保留 200 张合同。2 万级治理与 20 万浏览待实测|
|视频切帧|NATIVE_COMPLETE|原切帧 → VideoTasks，v33 回执和暂存恢复，局域网 HTTP 原视频摘要核验|历史无摘要请求仅可读取回执，现场离线和真实切帧待验|
|自动标注及清洗|NATIVE_PARTIAL|原审核三栏 → AiReview/NativeReviewAmbiguity，v60 后台预检、草稿 CAS、原 C2-B 正式入库，保留正式 GT 及清洗 Owner|参考图实际推理。自动策略须原人工复核，真实规模和视觉待验|
|标签管理|NATIVE_PARTIAL|原标签 → Labels/LabelAudit，原标签目录、合并及 GT 修复任务|预设操作、重复冲突及 Smart Audit 专业复核|
|算力与节点|NATIVE_PARTIAL|原算力 → ServiceNodes，原只读资源和调度证据|连接、凭据、环境、母模型、诊断的完整原生入口|
|模型转换环境|NATIVE_PARTIAL|原部署资源 → ConversionEnvironment，v39 配置、单项检测、本机批量检测、厂商芯片字典|资源删除缺旧引用与凭据生命周期保护，原入口保留|
|AI 辅助配置|NATIVE_PARTIAL|原配置 → AiConfiguration，v35 模型、Prompt、诊断、样本验证、原 SecretStore|凭据换密/清理持有者证明与产品安全策略|
|存储管理|NATIVE_PARTIAL|原存储 → StorageManagement/StorageRescan，v61 存储配置、引用和扫描|扫描确认、导入、归档、空间缓存、迁移与物理地址删除|
|平台对接|NATIVE_PARTIAL|原对接 → PlatformIntegration/ExternalPublish，v63 连接、诊断、同步与 v64 版本发布回执|映射写入、发布回退和未知远端结果对账|
|畅联云数据|NATIVE_COMPLETE|原查看 → ChangLianData，v63 产品/版本/权重读取，标签分页、列表对账、int64 字符串与证据复制|原查看链接保留，真实远端、三档视觉仍待验。同步和发布归平台对接|

共 2 项原生完整、12 项部分原生。五个试用入口与原正式默认入口保留。任务、回执与保护核对见 [开发接续入口](AI_DEVELOPMENT_HANDOFF.md)。

## 14 个正式菜单及业务闭环（2026-11-26，上一批）

代码候选 `1cd6323069a5070efeb85ea91f462fc8346f09d5`。状态为代码覆盖，验收 `CI_PENDING / UAT_PENDING`。

|菜单|状态|当前原生功能及权威|仍走原系统或阻断|
|---|---|---|---|
|总览|NATIVE_PARTIAL|Overview，v53 核心快照、近期训练和标注|历史趋势、资源诊断|
|质量中心|NATIVE_PARTIAL|QualityCentre，v53/v61 有界检查、v44 本页质量、v62 及原 ECharts|全库后台检查、场景实测、高级评测与完整趋势|
|算法库|NATIVE_PARTIAL|Algorithms、原版本历史和清理、ConversionDetail v39 板端验收与数值结果|整算法删除 409，缺算法级共同保护。转换终态缺原任务恢复接口，硬件重试缺版本 fence|
|训练任务|NATIVE_PARTIAL|NativeEvaluation/TrainingIteration/TrainingCreate 接通 v12 评测确认、v64 挖掘、v60 审核、v63/v12 补数、原来源训练提交|深层报告、原任务批量与困难样本多任务历史|
|素材库|NATIVE_PARTIAL|Materials 原分页、上传、GT。MaterialDatasets 经 v12 显式选中归属调整，最多 100 张|批量分类、筛选冻结成员写入、持久批量回执及算法负池|
|视频切帧|NATIVE_COMPLETE|VideoTasks/v33 原请求回执、原身份重放、暂存恢复与 VIDEO_FRAMES|无摘要旧请求及不支持 Web Crypto 时刷新重选缺证据|
|自动标注及清洗|NATIVE_PARTIAL|AiReview 手工策略消歧、精确冻结、C2-B 正式 GT，原审核及清洗 Owner|自动消歧须人工复核，参考图实际推理|
|标签管理|NATIVE_PARTIAL|Labels/LabelAudit，原标签目录、GT 与修复任务|预设、重复冲突和 Smart Audit|
|算力与节点|NATIVE_PARTIAL|ServiceNodes、原只读资源与调度证据|节点配置、环境、母模型及诊断|
|模型转换环境|NATIVE_PARTIAL|ConversionEnvironment，v39 资源读写、显式 SDK 检测及原厂商字典|批量环境检测、资源删除|
|AI 辅助配置|NATIVE_PARTIAL|AiConfiguration，v35 模型、Prompt、样本验证及原 SecretStore|旧凭据替换和删除受 409 引用保护，显式撤销策略待确认|
|存储管理|NATIVE_PARTIAL|StorageManagement/StorageRescan，v61 存储配置、引用及扫描|物理路径修改、删除、标注确认、导入与完整治理|
|平台对接|NATIVE_PARTIAL|PlatformIntegration/ExternalPublish，v63 主动测试、诊断、同步，v64 原版本确认发布及回执|映射写入、原回退及未知远端结果对账|
|畅联云数据|NATIVE_PARTIAL|ChangLianData，v63 只读产品、版本、权重详情及下载|原标签分页兜底、对账及复制细项|

总计 1 项原生完整、13 项部分原生。五个试用入口保持，旧入口及正式默认交接仍在。各提交、范围和 CI 见 [开发接续入口](AI_DEVELOPMENT_HANDOFF.md)。

## 14 个正式菜单与五个原生预览（2026-11-26，上一批）

代码候选 `4b932ccd0913dbf670b9a26f83eb800f55ad4e2a`。状态描述代码覆盖，运行期与视觉 `CI_PENDING / UAT_PENDING`。五个新增页的原正式链接保留，选择原生试用才进入。

|菜单|状态|原入口 → 原生页面及 API Owner|仍走原系统或待验|
|---|---|---|---|
|总览|NATIVE_PARTIAL|总览 → Overview，v53 核心快照、近期训练和标注|历史趋势、资源诊断|
|质量中心|NATIVE_PARTIAL|原质量中心 → QualityCentre，v53 素材摘要、v61 问题列表、v44 本页质量、v62 训练和报告、原 ECharts|全库检查、场景实测、高级评测、完整趋势|
|算法库|NATIVE_PARTIAL|原算法卡片 → Algorithms/AlgorithmCatalogOperations，原 v12、v49 和 AlgorithmRepository|整算法统一 409，待算法级生命周期保护；深层血缘及报告|
|训练任务|NATIVE_PARTIAL|原任务 → TrainingTasks/TrainingCreate/NativeTrainingReport/NativeEvaluation，原 TaskRuntime、评测和反馈 Owner|困难样本、补数、带来源继续训练及诊断细项|
|素材库|NATIVE_PARTIAL|原素材 → Materials/正式标注，原 GT、分页、上传和治理 Owner|批量分类、数据集成员及算法级负池|
|视频切帧|NATIVE_COMPLETE|原切帧 → VideoTasks，v33 与 VIDEO_FRAMES，新增原请求精确回执|旧无 ID 标记只能人工核对；真实执行和视觉待验|
|自动标注及清洗|NATIVE_PARTIAL|原工作台 → AiTasks/AiCreate/AiReview/NativeCleaning，原 v60/v47 及 GT Owner|批量消歧后正式入库、参考图实际推理|
|标签管理|NATIVE_PARTIAL|原标签 → Labels/LabelAudit，AnnotationRepository 与原治理|标签预设、重复冲突和 Smart Audit|
|算力与节点|NATIVE_PARTIAL|原节点 → ServiceNodes，原只读资源和调度证据|配置、环境与诊断|
|模型转换环境|NATIVE_PARTIAL|原部署资源 → ConversionEnvironment，v39 资源读写、显式 SDK 检测及 CatalogPreview 字典|批量工具检测及资源删除；硬件证据仍随转换产物|
|AI 辅助配置|NATIVE_PARTIAL|原模型配置 → AiConfiguration，v35 模型、Prompt、连接、容量及诊断，原 SecretStore|模型删除及凭据清除的安全引用保护|
|存储管理|NATIVE_PARTIAL|原存储配置 → StorageManagement/StorageRescan，v61 存储源、资源、引用及扫描|物理位置修改、删除、标注确认、导入及完整治理|
|平台对接|NATIVE_PARTIAL|原平台对接 → PlatformIntegration/ExternalPublish，原同步及发布 Owner|同步、连接测试、诊断、发布确认及回退|
|畅联云数据|NATIVE_PARTIAL|原数据页 → ChangLianData，只读 v63 产品、版本、权重详情及下载|原标签分页兜底、对账及复制细项，原同步仍归平台对接|

转换任务详情通过原 v39 数值验证记录恢复丢失回执，并维持硬件验证和正式交付分离。五项旧正式入口继续保留，开发分类为 1 完整、13 部分。各提交和核验见 [开发接续入口](AI_DEVELOPMENT_HANDOFF.md)。

## 14 个正式菜单及本批功能差异（2026-11-26，上一批）

开发候选 `77035375bac317eadb39d8c18449a471c375ccd0`。下表为源码接线状态，运行期及视觉 `CI_PENDING / UAT_PENDING`。

|菜单|状态|原流程、Vue 和现有 Owner|剩余操作|
|---|---|---|---|
|总览|NATIVE_PARTIAL|原总览 → Overview，v53 核心快照及近期训练/标注查询|历史趋势、细项诊断保留原入口|
|质量中心|LEGACY_BRIDGE|原质量中心与治理服务|跨域质量面板及原操作仍由旧页承担|
|算法库|NATIVE_PARTIAL|原算法卡片 → Algorithms、AlgorithmCatalogOperations 和 AlgorithmReport，原 v12/v49 与 AlgorithmRepository|整算法安全退役缺跨域生命周期边界，深层报告及血缘仍走原入口|
|训练任务|NATIVE_PARTIAL|原任务与报告 → TrainingTasks、TrainingCreate、NativeTrainingReport、NativeEvaluation，原 TaskRuntime、评测及独立反馈库|困难样本、带来源继续训练、批量及诊断深链仍走原流程|
|素材库|NATIVE_PARTIAL|原素材和人工 GT → Materials、AnnotationEditor，原有分页、正式 GT、上传、数据集及治理|分类、批量成员和算法级负池仍有旧入口|
|视频切帧|NATIVE_COMPLETE|原视频页 → VideoTasks，原 v33、VIDEO_FRAMES 执行器和自动入库|创建丢失响应需核查列表，生产执行和视觉待验|
|自动标注及清洗|NATIVE_PARTIAL|原三栏及清洗 → AiTasks、AiCreate、AiReview、NativeCleaning，CandidateStore、GT、原 v47/v62 清洗冻结（最多 500 个排除项）|批量消歧后正式入库仍走旧页，Provider 尚缺参考图实际入模|
|标签管理|NATIVE_PARTIAL|原标签目录及审计 → Labels/LabelAudit，AnnotationRepository 与原治理服务|预设、重复冲突和 Smart Audit 仍有旧入口|
|算力与节点|NATIVE_PARTIAL|原节点页 → ServiceNodes，原只读资源、调度授权|配置、环境与诊断仍走原入口|
|模型转换环境|LEGACY_BRIDGE|原环境资源与字典管理|ConversionDetail 新增 v39 停止和数值验证，环境配置与硬件验收仍走原入口|
|AI 辅助配置|LEGACY_BRIDGE|原模型和 Prompt 配置、原 SecretStore|完整旧配置入口|
|存储管理|LEGACY_BRIDGE|原存储源、密钥和容量管理|完整旧配置入口|
|平台对接|NATIVE_PARTIAL|原对接 → PlatformIntegration/ExternalPublish，原平台及发布 Owner|同步、连接测试、诊断、发布确认和回退仍有旧入口|
|畅联云数据|LEGACY_BRIDGE|原数据页和原 API|列表、筛选及相关操作仍走旧页|

完整 1、部分 8、旧交接 5。尚未确认旧入口退役。验证范围及提交见 [开发接续入口](AI_DEVELOPMENT_HANDOFF.md)。

## 数据治理、版本、评测与转换（2026-11-26，上一批）

|产品入口|新增原生操作及原 API Owner|仍待接通或验收|
|---|---|---|
|素材库|Materials/MaterialDatasets → 原目录 GET、原 v12 单图数据集调整与锁|批量分类、成员管理、算法负池及完整性治理仍有旧入口。|
|自动标注及清洗|NativeReviewTransfer → v60 操作者历史、原回执和撤销；NativeReviewAmbiguity → 原冻结范围与草稿 CAS；NativeCleaning → v47 结果分页、原 DELETE_INDEX 计划及清洗确认|视觉参考图入模、C2-B 正式消歧入库、CLEAN 冻结排除仍待处理。首批建议剔除 ID 及真实规模性能待核验。|
|标签管理|本轮保留已接通的原生目录、统一、标签审计及修复|预设和 Smart Audit 仍使用旧系统。|
|算法库|Algorithms/AlgorithmLifecycleDialog → v12 版本删除、回退、产物清理和授权下载；保留原模型版本和任务引用检查|整算法删除缺引用保护；深层溯源、算法级报告及其他旧流程仍在。|
|训练任务|NativeEvaluation/EvaluationSamplePreview → v12 独立 Test 冻结源图及真实框级诊断|继续训练、补数、跨版本样本并排及其他已有旧交接逐项推进。|
|模型转换与交付|ConversionDetail → v39 转换冻结源身份及有界数值验证历史|验证执行、转换部分操作及交付验证仍由原 Owner。转换增量不改变「模型转换环境」菜单状态。|

各新增操作以源码确认，验收为 `CI_PENDING / UAT_PENDING`。14 项正式菜单见下表。

## AI 审核、清洗与数据治理增量（2026-11-26）

|正式操作|原入口、当前 Vue 与 API Owner|迁移和验证状态|
|---|---|---|
|AI 创建、跨页继承与高级试跑|素材库/AI 创建 → AiCreate；v35 模型配置、v60 选择与创建回执；annotation-trial.js、Annotorious、v60 compare|NATIVE_PARTIAL。原试跑人工基准编辑、预测对比及 JSON 导出已接入。参考图 ID 贯通请求，Provider 实际多图输入尚缺。非等价素材筛选继续用显式选择。|
|审核单图、跨页及冻结转池|原审核工作台 → AiReview、NativeReviewTransfer；v60 review-selection、negative-transfer-preview、negative-transfer/receipt/undo；CandidateStore、NegativePool、AnnotationRepository|NATIVE_PARTIAL。接通冻结排除、目标、修订、资格、分页回执、部分续批和原撤销检查。原操作身份用于核对丢失响应。无 Web Locks 使用标签页会话；当前 Vue 浏览器入口只保留最近一笔。|
|IoU 与消歧|原审核 → NativeReviewAmbiguity；共有 annotation-ambiguity.js；v60 candidates/drafts-batch|NATIVE_PARTIAL。服务端待消歧冻结、阈值、按标签或置信度预检、25 张有界候选草稿。原消歧直接正式入库仍有旧入口。|
|清洗创建、进度、停止与诊断|自动标注及清洗/素材库 → NativeCleaning；v47 clean-runtime/preflight、clean-tasks；v62 原 MaterialBatch 状态、日志、重试|NATIVE_PARTIAL。显式跨页或条件范围，创建时由原后台冻结。清洗规范范围暂不提供全选后排除，旧 v47 创建没有精确按请求回执。|
|清洗结果与选中剔除|NativeCleaning；v47 result/annotation-audit/confirm；原 v62 DELETE_INDEX 的预检、凭据、任务及回执|NATIVE_PARTIAL。逐项浏览及选中，确认其余素材时只提交原剔除排除项。标注质量服务端分页，图片结果沿用原整批响应。|
|素材用途与处理状态|原批量工具 → Materials、MaterialBatchGovernance；v20 batch_split、v62 MARK_CLEAN_SKIPPED|NATIVE_PARTIAL。已选调整用途，免清洗按已选或兼容筛选预检并在同库版本冻结。分类、数据集成员、算法级负池和统一筛选排除仍保留旧入口。|
|标签完整性审计及修复|原标签审计 → Labels、LabelAudit；v54 integrity audits/repairs，v62 MaterialBatch，原 GT Owner|NATIVE_PARTIAL。审计、问题样例、影响确认、历史重映射、投影修复、状态、日志及原任务重试。快速预设、Smart Audit 和重复冲突仍依赖旧页。|

本批验证为 `CI_PENDING / UAT_PENDING`。隔离用例覆盖原转池身份、丢失响应及撤销，以及清洗预检后同一删除计划和排除项。三条正式菜单整体仍为 `NATIVE_PARTIAL`，以本节为当前进度。

## 连续标注和 AI 创建增量（2026-11-26）

|操作|Vue 入口 / 原 API 及 Owner|状态|
|---|---|---|
| 正式标注连续队列与删除后翻页 | FormalAnnotations、MaterialLibrary；原 v61 过滤和编号页，原 GT CAS 与删除回执 | 依确认后的真实成员重查，越界读取最后有效页，保持原素材过滤与跨页选取。CI_PENDING。 |
| 创建 AI 标注任务 | AI 任务列表、素材库、完成的 ZIP 导入 → AiCreate / AiAnnotationCreate；原 v35 脱敏配置，v60 冻结、预览、创建、回执 | 原生创建主链已接通。原试跑高级比对继续有旧入口，非 v60 可冻结条件保持逐张/本页。CI_PENDING，UAT_PENDING。 |
| AI 审核及正式入库 | AiReview / NativeAiCandidateEditor / CandidateStore / AnnotationRepository | NATIVE_PARTIAL。原生三栏、编辑、确认、冻结与 C2-B 沿用。转池、撤销、IoU 批量等原流程待继续。 |
| 清洗、标签审计、素材治理 | 原清洗及素材治理、标签审计入口 | 清洗及标签审计为 LEGACY_BRIDGE，素材治理含原生删除及已实现功能。批量用途、分类、审计修复仍待接入。 |

下面 14 菜单分类为当前实际覆盖。各子操作的真实验收依最终 SHA 和渲染证据。

## 正式人工标注增量（2026-11-26）

| 操作 | 当前 Owner 与 API | 迁移 / 验收 |
|---|---|---|
| 从素材库进入、筛选队列、切图、返回 | FormalAnnotations，通过 v61 materials 48 条分页 | 原生入口，返回保留原素材条件、页码和选择。原工作台提供明确回退。 |
| 画框、选框、移动调框、分类、删除、显示及类别过滤、缩放和平移、撤销重做、快捷操作 | FormalAnnotationEditor / AnnotationEditor / 原 Annotorious 和 geometry adapter | 原生接入。多个框由同一完整框集维护，编辑动作遵循原单选接口。实际 Chrome 和三档桌面待验。 |
| 正式保存、保存并继续、按范围确认无目标、冲突及未知结果 | 原 annotations GET/POST，v61 content 可选代际匹配，AnnotationRepository CAS | 原生代码已接通。明确区分待标注和确认无目标，旧工作台仍可用，CI_PENDING / UAT_PENDING。 |
| AI 候选编辑 | NativeAiCandidateEditor / 同一工具层 / CandidateStore | 增加错误后写入阻断。三栏与 C2-B 原接线保留，AI 创建、清洗和其余审核能力继续核对。 |

下文 14 菜单分类仍适用。素材库与自动标注及清洗整体 NATIVE_PARTIAL，标签审计和治理的旧交接仍在。

## 第二阶段素材库增量（2026-11-26）

| 操作 | 实现 / 原业务 Owner | 状态及证据 |
|---|---|---|
| 素材改名 | Vue MaterialRename / Materials，PUT v47 projects/{p}/images/{i}，原 MaterialGovernanceService 和 MaterialRepository | NATIVE_COMPLETE。只改展示名称，未知回执只读核对，已有浏览器用例覆盖。CI、视觉待验。 |
| 卡片人工标注 | MaterialLibrary 卡片按钮，通过原 material-annotate 交接打开指定图片 | LEGACY_BRIDGE。新增直接入口，保留原工作台、标注保存及 GT 合同。 |
| 删除后继续浏览 | useMaterialDelete 既有预检和回执，MaterialLibrary 回收选择并处理末页越界 | 原生删除闭环的修正。按服务端已确认 ID 更新，前端无法认定未确认结果。CI 待验。 |

14 菜单的总体状态沿用下文，素材库继续 NATIVE_PARTIAL。本段记载当批范围，人工 GT 和 AI 创建后的实际接线见上文。

## 当前增量：标签维护与统一（2026-11-26）

迁移状态与验收分别记录。下列 `NATIVE_COMPLETE` 仅指已实现本行操作闭环，不表示整个菜单完整、CI 通过或视觉验收通过。代码候选与最终 SHA 见[接续入口](AI_DEVELOPMENT_HANDOFF.md)。未改原菜单名、分组及顺序。

|原菜单/操作|旧位置 → 原生位置|原 API / 唯一业务 Owner|迁移状态|旧系统依赖与具体未完成项|功能/视觉验证|
|---|---|---|---|---|---|
|标签管理：目录搜索、新增、编辑、别名、颜色/快捷键、删除及引用拒绝|static/app.js newLabel/editLabel/delLabel → app/Labels.vue、components/LabelEditor.vue；素材库原标签按钮保持位置|GET v12 labels；POST /api/projects/{p}/labels；PUT/DELETE v12 labels/{class_id}；MaterialCatalogService/AnnotationGovernanceService、原项目标签与 AnnotationRepository|NATIVE_COMPLETE|快捷标签预设仍由旧页承担；本行不包含预设、审计/修复、逐图 GT 编辑|vue-tsc 静态通过；新增 label-management.spec.ts 复用现有浏览器 CI，未在本机执行；CI_PENDING、UAT_PENDING|
|标签管理：读取引用统计、选择≤50个来源、显式目标、影响预检、后台统一、取消、刷新恢复及完整日志|static/app.js openLabelBulkUnify414/pollImportRemap414 → components/LabelUnify.vue|GET v54 label-schema；POST labels/unify/preview、labels/unify；GET/POST v62 material-batches/{t}、/{t}/cancel；原 MaterialBatch/TaskRepository/AnnotationRepository|NATIVE_COMPLETE|Full Audit、投影修复与映射修复仍旧 Owner；部分失败/取消不冒充来源已清零；无新逐图结果接口|源码核对原公开任务 source_labels/target_label/retire_sources_on_success；响应未知不自动重发，URL保留请求范围；仅原任务 GET 恢复；CI_PENDING、UAT_PENDING|
|标签管理：快速预设、审计、修复及历史治理|static/app.js 原标签完整页；新页“标签审计与修复”链接|原 labels/integrity API、material_batches、GT Owner|LEGACY_BRIDGE|完整旧页保留，下一步应原生化审计/修复闭环，不删除入口|本轮仅核对入口源码；实际操作尚未核实|

技术决定：标签目录读写只有本页一份展示状态；专业 GT/候选与持久任务不迁到前端。目录首屏不等待引用统计，统一面板才按需读已有 label-schema，不读取素材全集。统一面板保留原两列来源/目标与影响数量；取消/恢复共享一个可取消任务读取 Owner；无普通操作二次确认，危险删除保留确认和服务端引用保护。依赖不新增，沿用既有同源 request、Element Plus 和离线 Vite 资源闭包。宽度由 Grid/Flex 适配三档桌面，不开发三套页面。

### 当前 14 菜单覆盖摘要

这是已有矩阵及当前原生路由/整页入口的接续索引，不是本轮重新验收全部菜单；未列入新增闭环的功能不据文件存在宣称完成。原 AI算法底座独立演示入口继续另列保留。

|菜单|状态|当前原生位置 / 尚缺操作|
|---|---|---|
|总览|LEGACY_BRIDGE|原总览；独立原生总览未完成|
|质量中心|LEGACY_BRIDGE|原质量中心/治理 Owner，未改|
|算法库|NATIVE_PARTIAL|卡片、版本删除、回退、清理与授权下载；整算法删除、算法报告等仍有旧流程|
|训练任务|NATIVE_PARTIAL|TrainingTasks/Create/NativeTrainingReport、独立 Test 框级诊断；继续训练和补数等仍依原流程|
|素材库|NATIVE_PARTIAL|原生浏览、上传、ZIP、正式人工标注、用途、免清洗、数据集目录及单张归属；批量成员、分类及算法池仍有旧入口|
|视频切帧|LEGACY_BRIDGE|原视频任务页，尚未原生化|
|自动标注及清洗|NATIVE_PARTIAL|AiTasks/AiCreate/AiReview、转池、候选消歧与清洗；原消歧直接批量入库等仍有旧入口|
|标签管理|NATIVE_PARTIAL|目录、后台统一、标签完整性审计和修复已接通；预设和 Smart Audit 等仍有旧入口|
|算力与节点|NATIVE_PARTIAL|ServiceNodes 只读总览；配置、环境、诊断仍原入口|
|模型转换环境|LEGACY_BRIDGE|原环境、资源与字典管理；现有 ConversionCreate/Detail/History 属转换业务，不能据此标环境菜单完成|
|AI 辅助配置|LEGACY_BRIDGE|原模型/Prompt配置 Owner|
|存储管理|LEGACY_BRIDGE|原存储源、密钥、空间/缓存管理|
|平台对接|NATIVE_PARTIAL|PlatformIntegration/ExternalPublish；总开关、同步、连接测试与诊断尚需原流程|
|畅联云数据|LEGACY_BRIDGE|原数据页，尚未原生化|


M4-B1 的项目公共负样本池和训练正负样本选择复用 v61 负样本池、v62 训练选材及原冻结服务。历史算法级操作保留 v1，项目级成员操作使用 v2 回执，恢复状态按登录账号和项目隔离。冻结合并复用原引用幂等机制并校验提交时的证据修订。真实训练、现场和生产验收待确认。详见[接续入口](AI_DEVELOPMENT_HANDOFF.md#m4-b1-项目公共负样本池)。

当前以文末M3-A及M2功能对照及[接续入口](AI_DEVELOPMENT_HANDOFF.md)为准；M1段落为历史范围，不代表M2仍缺少已实现功能。

本表是有界源码盘点，不是运行验收。用户新授权独立 `/app` Vue SPA；历史 opt-in-only 与完成后停止限制由本次授权覆盖。保持菜单、字段、权限、状态机、API、GT、任务、Repository唯一Owner及离线组件合同；不删能力、不操作生产/GPU、不改VERSION。P2A按需加载和P2B路由拆分成果保留。

## 状态合同

开发状态仅 NOT_STARTED / IN_PROGRESS / FUNCTIONAL_COMPLETE；验收状态 CI_PENDING / ACCEPTED / BLOCKED / AWAITING_USER_APPROVAL；尚未实施或提交时记“未实施/未提交”，只有实际阶段推送后才记CI_PENDING。覆盖性质另列，不等同开发或验收状态。M0盘点以e639bb12为基线；当前M1首批状态见下表和文末，已有18个Vue试点单列，文件存在绝不表示完整迁移。M1仅原生壳和算法卡片CRUD/详情/版本；其余受控整页旧系统入口，需逐项证明链接正确及项目身份。

## 精确原导航

`static/app.js:5931` renderNav：总览→总览、质量中心；算法生成→算法列表（显示算法库）、训练任务；数据中心→数据集、视频切帧、自动标注及清洗、标签管理。展开高级后：高级功能→算力与节点、模型转换环境、AI 辅助配置、存储管理；系统与对接→平台对接、畅联云数据；另有始终显示的AI算法底座独立演示入口。不能把试点页列表当正式菜单。

`static/modules/advanced-navigation.js:1` 子入口：服务节点、训练环境、母模型管理、环境诊断；转换资源、厂商与芯片字典；AI模型、提示词模板；存储资源、空间与缓存、旧素材兼容迁移。

## 有界迁移台账

API中的{p}/{a}/{v}/{t}/{j}/{i}为原项目/算法/版本/任务/训练job/图片身份。未列精确子路由的动作不能据此宣称完成。

|旧菜单/页/按钮|前端Owner|API|后端服务/Repository|状态/错误合同|既有Vue试点覆盖|缺口/文件|覆盖性质|独立SPA开发|验收|证据|
|---|---|---|---|---|---|---|---|---|---|---|
|登录/项目/总览|static/app.js；static/main.mjs；frontend/src/app/App.vue|POST /api/auth/login；GET /api/auth/session；POST /api/auth/logout；GET/POST /api/projects；PUT/DELETE /api/projects/{p}；POST /api/v53/bootstrap/start；GET /api/v53/bootstrap/status、/snapshot|app.py auth/projects路由；platform_core/bootstrap.py|401/项目身份/退出取消|ProductWorkbench|M1 Shell会话/项目选择已原生；登录/项目创建与总览业务仍旧页|部分原生/LEGACY_BRIDGE|IN_PROGRESS|CI_PENDING（仅M1 Shell）|src/app/App.vue/main.ts；app-shell.spec.ts；API鉴权及真实临时FastAPI联调|
|算法库卡片/筛选/新增编辑删除/详情版本|frontend/src/app/Algorithms.vue；原动作Owner|v12 algorithms的library_view/asset_view/basic_only；原版本API|AlgorithmSqlStore；原训练历史/TaskRepository|全局筛选排序后分页；外部只读；当前版本；写后GET；原退役保护|原ModelAssets试点保留；独立App原生列表/详情/备注|删除回退及其他工作台整页交给原Owner，不是原生执行工作台|原生列表版本 + LEGACY_BRIDGE动作|FUNCTIONAL_COMPLETE（列表/版本页面）|CI_PENDING|M2-A 280ed4cf；M2-B/C c83c1142；文末精确对照与验证|
|素材库分页/详情/使用记录/标注|原素材库与独立 SPA “素材库”|v61 materials；原 annotations reader_view；v62 history|MaterialRepository、AnnotationRepository 与原使用记录|有界读取、同项目身份、正式 GT 版本|Materials + MaterialLibrary + MaterialPreview|上传、导入、标注、清洗、负样本池、标签、治理及删除审核由原 Owner 负责|原生浏览、详情与选择，写操作 LEGACY_BRIDGE|FUNCTIONAL_COMPLETE（M4-A1）|CI_PENDING|定向浏览器、投影 API 和交接测试|
|图片上传/ZIP/清洗治理|原Uppy/ZIP/TaskCenter|v19 ZIP；v61 storage-imports/{t}/confirm|原导入Handler；MaterialRepository；TaskRepository|AWAITING_CONFIRMATION非终态/取消fencing/单调进度|MaterialImportGovernance|ZIP/治理真实执行未验|LEGACY_BRIDGE|NOT_STARTED|未实施/未提交|frontend/src/views/MaterialImportGovernance.vue；本行Owner/API源码|
|算法负池/标签管理|static/modules/labels.js；frontend/src/views/NegativePool.vue|/api/v61/projects/{p}/negative-pool；GET /api/v12/projects/{p}/labels；POST /api/projects/{p}/labels；PUT/DELETE /api/v12/projects/{p}/labels/{class_id}；GET /api/v54/projects/{p}/label-schema|platform_core/negative_pool_api.py；platform_core/annotation_repository.py；app.py标签路由|revision/operation_id/CAS/未知回执先读回|NegativePool；标签完整页仍旧|标签完整CRUD不因负池组件存在视为完成|LEGACY_BRIDGE|NOT_STARTED|未实施/未提交|frontend/src/views/NegativePool.vue；本行Owner/API源码|
|AI创建/选择/Provider/确认|原AI Submit/Picker|/api/v60/projects/{p}/annotation-tasks；by-request|AnnotationTaskService；TaskRepository|request_id UNKNOWN只GET恢复/冻结选择|AiAnnotationCreate|三步展示复用原子树|LEGACY_BRIDGE|NOT_STARTED|未实施/未提交|frontend/src/views/AiAnnotationCreate.vue；本行Owner/API源码|
|AI任务/失败诊断/取消恢复|原Task/Candidate Owner|v60 annotation-tasks/{t}及原诊断/恢复子路由|AnnotationTaskService；CandidateStore|取消后不得推理/候选写入；失败不算unreviewed|AiAnnotationTasks|完整诊断导出/重试继续旧页|LEGACY_BRIDGE|NOT_STARTED|未实施/未提交|frontend/src/views/AiAnnotationTasks.vue；本行Owner/API源码|
|AI候选/人工消歧/采用拒绝/正式提交|reviewAiLabel427/Annotorious|原v60审核路由|CandidateStore；AnnotationRepository|草稿revision≠GT version；歧义禁止提交；明确确认后入库|AiReviewWorkbench + AnnotationEditor|编辑核/GT提交不可复制|LEGACY_BRIDGE|NOT_STARTED|未实施/未提交|frontend/src/views/AiReviewWorkbench.vue；本行Owner/API源码|
|训练创建/标签/选材/冻结|原生src/app/TrainingCreate.vue + TrainingMaterials.vue；复用纯Draft/Submit函数|原v12 train/start；v62 training-materials分页/summary/reference/revision/compatibility；Task reader_view|原训练服务/GT/Artifact/TaskRepository/Worker|五修订核验/大范围引用/Test隔离/已审核GT/未知只GET|原views外壳保留旧试点；新App完全原生|任务执行和报告不在M3-A；有来源评测决策仍原Owner|原生普通创建；其余LEGACY_BRIDGE|FUNCTIONAL_COMPLETE（M3-A普通创建范围）|CI_PENDING|代码07b98d23；文末测试与边界|
|训练准备/执行/队列/取消/恢复|独立 App TrainingTasks.vue / 原 TrainingTaskRuntime 与 TrainingRecoveryRuntime|v62 tasks reader_view；原 jobs log；v48 stop 与 v62 recovery|TaskRepository、原训练服务|正式状态/进度、项目隔离、准备/训练关联、原取消确认与恢复准入|原views只读试点保留|停止、恢复、暂停、继续、提权和历史管理留原工作台|原生列表/详情/日志；操作 LEGACY_BRIDGE|FUNCTIONAL_COMPLETE（M3-B 页面范围）|M3-B 独立代码审计通过；全量 CI 39/40|HTTP、Node、Chrome 定向验证与接续入口|
|报告/独立评测/版本对比|任务与算法版本入口、原 reports/quality/evaluation|v44 jobs report；v12 evaluation report/samples/images/compare|原报告 Owner、版本与冻结评测证据|Val/Test 分离、分页、身份和图像摘要、原可比性|NativeTrainingReport、NativeEvaluation、NativeReportCharts|源身份决策写入、复杂叠加、深度评测及完整质量中心留原工作台|原生读取；复杂功能 LEGACY_BRIDGE|FUNCTIONAL_COMPLETE（M3-C 只读范围）|CI_PENDING|投影、API、Chrome、离线资源定向验证|
|版本转换/动态参数/历史/验证取消|原转换Owner|/api/v42/projects/{p}/algorithms/{a}/versions/{v}/deployments|原deployment持久层/TaskRepository|UNKNOWN恢复/SDK与芯片能力/真实产物验证|ConversionCreate + ConversionHistory|真实SDK/转换未验|LEGACY_BRIDGE|NOT_STARTED|未实施/未提交|frontend/src/views/ConversionHistory.vue；本行Owner/API源码|
|模型交付/外部算法/平台对接|static/modules/external-algorithm-platform.js；static/modules/external-algorithm-publish.js；frontend/src/views/ModelDelivery.vue|GET/PUT /api/v63/external-algorithm-platform/config；PUT /api/v63/external-algorithm-platform/mode；POST /api/v63/external-algorithm-platform/test、/diagnostics；交付动作见原发布模块，不以配置API代替|platform_core/external_algorithm_platform.py；platform_core/external_algorithm_publish.py；platform_core/external_publish_request.py|预检/明确确认/UNKNOWN读回/禁止虚报成功|ModelDelivery|原完整平台/交付入口|LEGACY_BRIDGE|NOT_STARTED|未实施/未提交|frontend/src/views/ModelDelivery.vue；本行Owner/API源码|
|节点/Worker/GPU/训练环境母模型/组件诊断|ServiceNodeRuntime/原资源Owner|GET/POST /api/v63/service-nodes；GET /{node_id}；POST /{node_id}/connectivity-test、/rotate-token；DELETE /{node_id}；/api/resource-discovery、/api/v63/base-models原环境接口|service_nodes.py；原Agent/Supervisor|在线≠有效≠可调度/不主动探测硬件|ServiceNodesOverview|写配置/诊断/安装旧页|PRESENTATION_ONLY|NOT_STARTED|未实施/未提交|frontend/src/views/ServiceNodesOverview.vue；本行Owner/API源码|
|转换资源/厂商芯片字典|AdvancedNavigation/catalog Owner|/api/v39/deploy/catalog/records；operations；chips/{id}/detect|deployment/catalog_api.py；ModelArtifactRepository|revision/operation_id/引用保护/observe_only|CatalogPreview + CatalogEditor/References|字典管理与转换环境分别验收|LEGACY_BRIDGE|NOT_STARTED|未实施/未提交|frontend/src/views/CatalogPreview.vue；本行Owner/API源码|
|AI模型/Prompt/存储缓存/兼容迁移|static/modules/advanced-navigation.js；static/modules/storage.js；frontend/src/views/ConfigurationCenter.vue|GET/POST /api/v35/model-configs；PUT/DELETE /api/v35/model-configs/{config_id}；POST /api/v35/model-configs/test；GET/POST /api/v35/prompt-templates；PUT/DELETE /api/v35/prompt-templates/{template_id}；POST /api/v35/prompt-templates/preview；GET/POST /api/v61/storage-sources；POST /api/v61/storage-sources/{source_id}/test、/default；DELETE /api/v61/storage-sources/{source_id}|app.py v35/v61路由；platform_core/prompts.py；platform_core/storage/source_repository.py|敏感字段不投影/写入与探测需真实回执|ConfigurationCenter|9可信入口导航并非9项原生CRUD|PRESENTATION_ONLY|NOT_STARTED|未实施/未提交|frontend/src/views/ConfigurationCenter.vue；本行Owner/API源码|
|视频切帧/畅联云数据/AI算法底座|static/modules/video-tasks.js；static/modules/changlian-data-browser.js；prison-night-inspection-entry.mjs|GET/POST /api/v33/projects/{p}/video-tasks；GET /api/v33/projects/{p}/video-tasks/{t}；POST /api/v33/projects/{p}/video-tasks/{t}/stop；云数据GET /api/v63/external-algorithm-platform/provider/products[?status=0或1]；独立演示由prison-night-inspection-entry.mjs打开，不推定正式业务闭环|platform_core/video_tasks.py；platform_core/task_runtime/repository.py；app.py|取消后禁止继续发布/演示标识保留|无对应18视图|完整旧页受控链接|LEGACY_BRIDGE|NOT_STARTED|未实施/未提交|frontend/src/views/ProductWorkbench.vue；本行Owner/API源码|

## 证据与交接边界

- `frontend/src/main.ts`：18个按需import视图；`frontend/src/api/{algorithm-management,model-browse,materials,negative-pool,ai-tasks,training-reader,catalog,catalog-operation}.ts`提供实际URL、身份检查、分页与读写边界；这些并非独立SPA路由。
- `static/main.mjs:78-83` 开关只初始化既有试点；`static/modules/navigation-presentation.js`明确原路由/生命周期/项目状态留在main.mjs。`static/modules/navigation-stability.js`保护原页动作。
- 通用 `?page=...&project_id=...` 深链接未在上述导航源码核实，不能作为现成合同。`static/app.js:5740` 从 `mc_train_ui_state_v34`恢复允许页面并删除projectId；`static/modules/ui-state.js`同样不持久项目选择，Vue selection/report必须匹配当前project_id。旧页面名≠URL query自动消费。
- `static/modules/ai-review-route.js`有专门hash审核路由；不能推广成所有菜单通用链接。独立SPA legacy交接需实际allowlist消费与鉴权后项目核验，拒绝不匹配身份，不能借localStorage伪造项目。
- 第三方遵守 `docs/FRONTEND_THIRD_PARTY_REUSE_POLICY.md`：Annotorious3.9.5及原几何适配、Uppy6.0.5、Panzoom4.6.2、FloatingUI1.8.0、ECharts6.1.0保留原入口与销毁；不复制编辑内核/草稿库/轮询器/GT，离线vendor/license/map保留。
- 规则来源：AGENTS.md当前功能保护头部；docs/architecture/EXISTING_FEATURE_PRESERVATION.md；docs/FRONTEND_OWNER_MAP_V42_25.md；docs/TECH_FOUNDATION_P2_20261117.md。历史CI和现场证据不作为新SPA验收。优先准确SHA现有CI，推送后仅一次状态查询，不循环等待。

主实施者可在本表补充M1实际文件、定向构建/测试、准确SHA CI和逐动作证据后更新状态；整页旧入口可按其覆盖性质交付，不得标成原生功能完整。


## M1本批实际状态（实现提交4865bea70941443b5a62e56b5c90eca5e6c92aef）

`frontend/src/app/{App.vue,Algorithms.vue,http.ts,navigation.ts,main.ts}` 为独立壳与原生卡片第一批。完整算法大域仍 IN_PROGRESS，其余域 NOT_STARTED；下述第一批功能实现完成，随本批推送进入CI_PENDING，不是全平台ACCEPTED。

新增 `static/modules/vue-app-handoff.js` 是本轮受控整页交接消费者，不是历史已有通用deep-link合同。格式为 `/?spa_handoff=1&project_id={p}&page={allowlistedPage}`，可附 `algorithm_id`、`version_id`、`action=train|conversion|delivery`。仅在旧系统canonical项目已加载且等于请求project_id时消费；算法/版本经原GET核验，导航后再次校验项目和页面，消费后清除query防刷新重放。不得通过localStorage冒充项目身份；链接构造/拒绝跨项目/缺版本由Node用例验证，canonical项目原生创建编辑→原训练表单→返回由真实隔离FastAPI/Chrome验证；没有执行训练、转换或外部发布。

|M1限定交付|开发状态|验收状态|证据及正式替代边界|
|---|---|---|---|
|独立Root/HashRouter/Pinia会话项目/请求取消|FUNCTIONAL_COMPLETE|CI_PENDING|类型与双构建；Chrome项目切换取消、匿名返回原登录、F5/后退；原/默认入口不切换|
|原生算法卡片、资产字段筛选、10条分页、详情与版本、创建/基本编辑|FUNCTIONAL_COMPLETE（首批）|CI_PENDING|真实v12/AlgorithmSqlStore创建编辑读回；HTTP夹具Chrome含版本/当前指针/分页；编辑GET迟到已先复现再取消修复；非整个算法库等价|
|受控整页旧功能交接与返回|FUNCTIONAL_COMPLETE（导航机制）|CI_PENDING|同项目/算法/版本核验，拒绝非canonical旧项目；旧训练表单真实联调通过；原训练默认完整模式/参数/准入不改|
|双构建/资源闭包/同SHA离线打包|FUNCTIONAL_COMPLETE|CI_PENDING|旧30、新6本地资源；打包用例涵盖双目录、旧包兼容、缺SPA及SHA不一致拒绝；官方最终CI制品/现场安装未验|

### 后续动作的精确原接口索引

- AI根 `/api/v60/projects/{p}/annotation-tasks`：POST创建，GET列表及by-request/{request_id}、/{t}、/{t}/gt-audit、/{t}/candidates[/{i}]；PUT /{t}/candidates/{i}/draft；POST /{t}/candidates/drafts-batch、/review-selection、/negative-transfer[-preview]、/decisions、/cancel、/retry、/review-completed；decisions/by-request/{request_id} GET确认。实际路由在app.py，业务由annotation_task_service.py/CandidateStore/AnnotationRepository拥有，不能把草稿当GT。
- 训练：POST `/api/v12/projects/{p}/train/start`；v62 training-materials选择/selection-reference；GET `/api/v62/projects/{p}/tasks[/{t}]`，POST /{t}/cancel、/promote；原v48 job pause/resume/stop与v44报告保留。准备/执行依原TaskRuntime及不可变Payload/锚点，Vue不接管。
- 交付：`platform_core/external_algorithm_publish.py` 注册 `/api/v64/external-publish/projects/{p}/algorithms/{a}/versions/{v}` GET、`/selection` PUT、`/publish` POST；v64 model-artifacts/config、oss-config、storage-test、/{artifact_id}/retry/download等仍各由ModelArtifactRepository和原发布Owner负责。

### 未完成与下一阶段最小工程

先让GPT按最终SHA审查独立结构/CI；随后补原算法卡片剩余品目/训练状态/综合排序/删除回退等对照及原生化，再计划完整训练创建/选择/准备/取消/报告迁移。以原Owner地图定位，不重复全仓审计。不得切换正式/入口或退役旧页，直至对应功能等价与验收条件满足；不得因迁移改默认训练参数、GT、Lease、Payload或发布规则。


## 2026-11-19 GPT审计后精准收尾

基线`65ae81372555786b78284a1bc62608703c1c40d6`：GPT核对50工作流48成功、2失败（Frontend Runtime Stabilization 44344576655、Material Upload Chunking 44344576624），不是ACCEPTED。失败由index.html缓存键非数字/三资源不一致引起，非素材上传或AI审核业务回归。保留两原测试断言，三资源统一数字缓存键42.25.626，VERSION不变。

实现提交`daa5534606379db83df12e9f076c61bc8cd55821`：算法卡片创建/基本编辑复用既有按项目sessionStorage待核记录；先保存再写，明确拒绝或正式GET身份与四字段核验一致才清除，未知结果跨刷新/同标签页重入继续阻止重复写入。回执ID已知则核对该ID；创建响应完全丢失则用户核对ID后GET验证，不自动重试、不以列表或名字推断提交结果。此信息仅是前端操作保护，不是第二套业务真相；跨浏览器会话幂等仍不提供。

新增且仅运行一项Chrome刷新恢复用例：1/1通过；包含项目隔离、GET失败与内容不符不解除、GET一致后解除，以及400明确拒绝清除。两个原失败Node用例2/2通过；类型检查、SPA构建/6资源离线闭包、原app.js/main.mjs语法及diff检查通过。没有修改素材/AI/训练/执行核心、CI或既有断言，未运行全量测试。本轮最终提交仅再更新本矩阵及AI入口，准确最终HEAD/异步CI见[接续入口](AI_DEVELOPMENT_HANDOFF.md)及交付消息；新SHA验收为CI_PENDING。

开发覆盖未扩大：M1限定首批FUNCTIONAL_COMPLETE，整个算法域仍IN_PROGRESS；剩余筛选/排序/删除回退及其他业务原生化继续列未完成，不切换默认入口，不进入下一阶段。

## M2 完整功能等价对照（2026-11-19）

基线`4c7a6d1f31c275311156fb0ab1a7a5cd9d47d7f8`；只读投影`280ed4cfb21f80e0980c03ace18aa70877a41706`；Vue/操作入口`c83c114230873f57ae9d0f9a348ffc17f9cc4307`。最后文档提交作为最终交付HEAD，准确SHA/CI快照见交付消息；验收CI_PENDING，不借其他SHA结论。

|原算法库能力|独立App对应|Owner/API与合同|开发/验证边界|
|---|---|---|---|
|卡片、展开收起、当前版本、训练次数/状态/指标|原生卡片、独立版本展开区；不因展开重读列表|SQL精确current_version_id；原成功训练历史Owner+Durable状态；指标真实0/未知分离|FUNCTIONAL_COMPLETE；API/Chrome已验|
|搜索、来源、行业、类型、训练状态、仅看可训练|原生紧凑筛选、标签移除/清空|新training_state与旧asset status不同；后端同一SQL范围筛选排序分页|FUNCTIONAL_COMPLETE；25算法跨页及状态API已验|
|外部多级品目|ElementPlus多选叶子Cascader|原ExternalPlatformRepository缓存ID/parentId；无新分类真相|FUNCTIONAL_COMPLETE；API父子过滤和浏览器精确query已验|
|综合/最近更新/训练次数/mAP50|原生全局排序|SQL排序后LIMIT，非当前10条排序；综合保留原active状态集合及稳定基础顺序|FUNCTIONAL_COMPLETE；队尾最高计数/指标进入第一页已验|
|刷新、返回、项目切换、重入|URL+按项目sessionStorage筛选；原请求取消机制|不共享项目状态；原同源Session及项目Guard|原M1合同保留；本轮受影响刷新/恢复通过|
|本地创建/编辑及结果未知|原生四字段表单，原v12 POST/PUT/basic GET|同项目待核记录写前保存；拒绝/GET成功清除；未知不重发|FUNCTIONAL_COMPLETE；原CRUD与未知结果Chrome通过|
|算法详情/外部只读信息|四原字段+身份/来源/时间/产品/品目/分析/摘要|basic_only扩只读列，不拉版本全文；外部主数据编辑禁用|FUNCTIONAL_COMPLETE；只读API及Chrome禁用通过|
|历史分页、当前指针、版本元数据/产物/任务|原生分页及ModelVersionDetails|原asset_versions/asset_version与已登记模型资产；has_model仅原路径记录，不冒称文件已核验|FUNCTIONAL_COMPLETE；API详情与Chrome通过|
|版本编辑|原生版本备注编辑；版本号不可改|原PUT只提交remark；asset_view轻量回执+GET身份/原文核验；待核共用journal|FUNCTIONAL_COMPLETE；真实临时库PUT/GET、浏览器通过|
|算法/版本删除及回退|明确标“原流程”的受控入口|delAlgorithm/delVersion/openVersionRollback；原确认/引用保护/expected_current_version_id；畅联版本退役仍禁用，其他提供方不被额外禁止|入口FUNCTIONAL_COMPLETE，执行工作台LEGACY_BRIDGE；Node分发/保护通过，真实物理删除未验|
|算法/训练报告、溯源、已有独立评测|每版本/算法真实入口|algorithmReport429/openVersionReport429/openVersionLineage429/openVersionEvaluation429|入口FUNCTIONAL_COMPLETE；相应工作台LEGACY_BRIDGE|
|训练、转换、下载、交付、同步|真实身份受控整页入口；平台对接原页同步|原训练/转换/发布Owner；下载原授权API；清理状态不放行交付；不自动同步|入口FUNCTIONAL_COMPLETE；工作台LEGACY_BRIDGE，未跑真实训练/外部发布|

本轮API测试：原文件初始5通过，新增备注后仅library相关3通过；handoff Node23通过；原生浏览器受影响CRUD/未知恢复2项通过，M2新增单项最终通过（5.0秒含启动）。类型/双构建、旧30/新6离线资源、缓存键2项、编译及diff检查通过。没有全仓pytest、完整Playwright或新CI。

剩余实际边界：统计仍复用每请求一次历史上下文，不能宣称全历史固定成本；官方CI制品/现场离线安装、生产/GPU、真实删除回退与外部发布未验。旧canonical项目限制及本标签页待核存储边界不变。GPT复核后建议M3完整训练创建/选材/准备/报告，保留全部模式/默认参数/GT/Payload/执行权；本批不自动开始。

## M3-A 原生创建与选择（2026-11-19 当前）

M2收尾先推送3e8e2291与d635fd1f，再开始M3-A代码07b98d236f8dc3b45856c945938e72f98d64e8d8；最终文档提交SHA及新CI快照见交付，均不冒称已验收。

|原功能|新原生实现/保留方式|验证与缺口|
|---|---|---|
|算法/母版本/母模型/四模式及全部参数|共享旧默认工厂及纯builder；原生分组控件；按项目算法草稿|默认对象与旧git工厂严格一致；85原合同通过；算法/项目变化重建页面|
|大规模选材/标签/TrainValTest|40条服务端分页、lazy、跨页、2000显式上限和冻结引用；summary正式标签；五revision/成员关系校验|22,015引用合同、4临时API、跨页Chrome通过；不展开全库ID|
|准入、负样本、重复冲突/排除审计|原compatibility/negative proof/RESOLVE_SELECTION；明确人工确认，保留范围和修订；后台范围确认不绕过硬GT|原纯排除5项+新adapter7项；未逐组合浏览器穷举或改GT|
|固定Test/历史继承/robustness及自动转换选项|复用原base/preset/benchmark合同；比率/数量/训练内手工子集；版本号与执行冻结后端拥有|当前版本变更拒绝；固定基准/增强真实训练未验|
|最终确认/正式创建/未知恢复|正式train_id持久回执，原POST和Task GET reader；签名变更使预览失效|无存储不POST、IN_PROGRESS/5xx保留、模块重建只GET，已本地验证|
|任务列表/执行/取消恢复/完整报告|继续原系统入口|LEGACY_BRIDGE；M3-B/M3-C，未原生完成|
|有来源评测决策继续训练/反馈补数、原表单全局策略管理|保留原评测/配置Owner，不能伪装成无来源普通训练|不在本批入口切换；后续按来源身份合同迁移|

新route `/app/#/projects/{p}/training/create?algorithm={id}` 不加载旧app.js/main.mjs，不移DOM；旧views外壳仍为旧试点。M2卡片“训练”进入原生创建，“训练任务”页保留旧执行工作台并新增原生创建入口。普通创建范围FUNCTIONAL_COMPLETE，验收CI_PENDING；不把M3-A当作全部训练域迁移。

验证：类型/双构建/资源闭包/语法/Diff通过；native Chrome1（4.4秒）、adapter7、API4、原Draft/Submit85、排除5；M2缓存17、hydrate15和指定首次打开1通过。未跑全仓或全部浏览器。详细命令和限制见[接续入口](AI_DEVELOPMENT_HANDOFF.md#m3-a-原生训练创建2026-11-19-当前)。下一步仅在GPT审计后安排M3-B，不自动开始。

M3-A 冻结整改提交 `f71aae79`，同范围重试使用 UUIDv4 并恢复已冻结引用。M3-B 和 M3-C 的验收边界见[接续入口](AI_DEVELOPMENT_HANDOFF.md#m3-c-原生训练报告与独立评测)。

M3-C 审计整改后，报告将请求配置、实际执行值和来源未标注的历史值分开，旧评测返回恢复原版本详情与筛选上下文。M3-C 只读范围为 `FUNCTIONAL_COMPLETE`，验收为 `CI_PENDING`，待独立复审。


### M4-C1 ZIP 归集

| 原入口 | 实际覆盖 | API 与 Owner | 迁移 / 验收 |
|---|---|---|---|
| 素材库 → ZIP 数据导入 | 上传恢复、按图片目录确认用途和归集、外部标签映射、取消与结果、安全重试负样本分类 | 原 v19 ZIP Runtime、新增 v19 `folders` 和 `retry-folder-classification`、MaterialRepository、AnnotationRepository、项目公共负样本池 | 正式 ZIP 功能 `FUNCTIONAL_COMPLETE`，SPA 仍为 `LEGACY_BRIDGE`。CI 以准确 SHA 快照为准。固定训练 Val 及现场未验证。 |


### M4-C2 固定 ZIP 训练

| 入口 | 功能 | API 与权威 | 状态 |
|---|---|---|---|
| 原生训练创建与报告 | ZIP 来源分页、固定 Train/Val/Test 核验、三组冻结、正式创建与原任务恢复、报告来源与实际统计 | v62 训练选材、v12 训练创建、原 TrainingPrepare、Task ArtifactStore、MaterialRepository、AnnotationRepository、SplitManifest | 功能实现，本地隔离验收。CI 以准确 SHA 为准，真实 GPU 与现场待验。 |

### M4-D0 AI 标注审核

| 功能 | 页面与 API | 正式 Owner | 功能状态 | 验收 |
| --- | --- | --- | --- | --- |
| AI 候选与审核 | 原「自动标注及清洗」和 Vue 审核投影；v60 审核选择与候选分页 | CandidateStore 与原审核操作 Owner | 现有入口可用，三种批量范围分别核验，仍可查看失败和历史记录。独立 SPA 审核迁移 `NOT_STARTED`（M4-D0 阶段记录；D1-B/D1-C/D2A 已在后续阶段实现，见下节与文末更正） | M4-D0 定向验证完成，`CI_PENDING` |
| 部分及逐图正式 GT | 原确认、入库与按原编号查询回执 | AnnotationRepository、原确认 Worker | 写入和凭据同一事务；中断后补 CandidateStore 日志 | 隔离恢复已验证，`CI_PENDING` |
| 候选转池与撤销 | v60 预检、执行与原请求撤销 | NegativePool、CandidateStore | 快照验证操作者和当前修订，按原身份恢复成员写入和撤销 | 隔离恢复已验证，`CI_PENDING` |


### M4-D1-B 原生 AI 审核试点

| 功能 | 入口与 Owner | 功能状态 | 验收 |
| --- | --- | --- | --- |
| AI 审核只读浏览 | 显式 SPA 任务审核 URL；v60 TaskRepository / CandidateStore，v61 素材读取 | `FUNCTIONAL_COMPLETE`（D1-B 只读范围） | 定向 Chrome、类型和离线构建，`CI_PENDING` |
| 原审核写操作 | 原「自动标注及清洗」工作台；既有 CandidateStore、AnnotationRepository、NegativePool、ArtifactStore | 原工作台可达，D1-C 原生迁移 `NOT_STARTED`（M4-D1-B 阶段记录；D1-C 已在下节记录为实现） | 按原 M4-D0 合同验收 |


### M4-D1-C 单图候选编辑

| 功能 | Owner | 迁移状态 |
| --- | --- | --- |
| 单图候选标注框编辑、撤销/重做及草稿恢复 | 原生编辑会话、既有 Annotorious、v60 CandidateStore | `FUNCTIONAL_COMPLETE`（本阶段范围），CI 异步验收 |
| 单图采用与拒绝 | 原生审核检查区；v60 decisions 与 by-request；CandidateStore | `FUNCTIONAL_COMPLETE`（D1-D1B），按阶段准确 SHA 进行 CI 验收 |
| 跨页选择及 GT 用途冻结 | 原生审核候选区；v60 review-selection、candidates；CandidateStore | `FUNCTIONAL_COMPLETE`（D1-D2A 选择范围），按阶段准确 SHA 进行 CI 验收 |
| 批量决定、批量消歧、GT 入库、转池与撤销 | 原审核工作台及既有服务端 Owner | 原生迁移 `NOT_STARTED`（D2A 阶段记录；C2-B 批量入库为本地未提交候选实现，见文末更正），原入口可达 |

## 2026-11-21 状态更正（审计复核）

本节只修正**已确认的状态矛盾**，不改写历史阶段记录。上文的 `NOT_STARTED` 是各阶段当时的记录，不代表当前代码状态。

| 上文位置 | 原表述 | 2026-11-21 实际 |
|---|---|---|
| M4-D0 表「AI 候选与审核」 | 独立 SPA 审核迁移 `NOT_STARTED` | D1-B 只读页、D1-C 单图编辑、D1-D1B 单图决定、D1-D2A 跨页选择已实现（见下文各节） |
| M4-D1-B 表「原审核写操作」 | D1-C 原生迁移 `NOT_STARTED` | D1-C 已在下节记录为 `FUNCTIONAL_COMPLETE`（本阶段范围） |
| M4-D1-C 表「批量…GT 入库」 | 原生迁移 `NOT_STARTED` | 单图正式 GT 已实现；**批量正式 GT（C2-B）为本地未提交候选实现**，含 D1/D2/D4/D5/D6 已确认问题，未提交、未 CI、未验收 |
| 算法负池/标签管理 | `NOT_STARTED` | 算法级负样本池（v1）已有原生试点写入；项目公共池（v2）已原生；标签管理仍未迁移 |
| 字典管理 | `LEGACY_BRIDGE` | P1 `CatalogPreview` 管理态已可原生写；配置/节点仍为只读或旧入口 |

补充口径：

- 本矩阵**没有任何一项为 `ACCEPTED`**；`FUNCTIONAL_COMPLETE` 只表示开发完成。表中早期阶段写的 `CI_PENDING` 是**该阶段交付时的快照**，不是当前 HEAD 状态：当前 HEAD `1fa5119b` 的 48 项 check-suite 已成功，但"HEAD 绿"不等于"该功能被 CI 实际覆盖"，也不等于已验收。
- `/app` 现有 8 条具名业务路由，复用 7 个页面组件（`training-report` 与 `version-report` 共用 `NativeTrainingReport.vue`）。
- 本文件多处早于代码提交（例如正式 GT 提交晚于本文档记录），属于**文档落后于代码**，不是代码夸大文档。
- 后续状态以[接续入口](AI_DEVELOPMENT_HANDOFF.md)、[架构审计](PLATFORM_ARCHITECTURE_AUDIT_20261121.md)与[路线](PLATFORM_EVOLUTION_ROADMAP_20261121.md)为准；本矩阵只维护功能/API 对照。

## 2026-11-25 P0-01C 后端定向修复

本轮无 Vue/菜单/页面迁移，既有训练、转换、取消及恢复 API 路径与唯一 Owner 保持一致；仅修复执行身份、启动前失败与中央结算证据核验。实现/测试合同见 [收口记录](P0_01C_FINAL_TARGETED_CLOSEOUT_20261125.md)，开发 FUNCTIONAL_COMPLETE / 验收 CI_PENDING，本机未运行期验证。

## 2026-11-25 资源等待合同

前端未改。原训练任务 API/详情展示 TaskRuntime 的 QUEUED/resource_waiting 与 resource_wait_reason，等待与 FAILED 分开；TrainingTasks、训练投影及菜单/操作保持。原 Node Executor router 增加按任务和原 Assignment 提交/回查资源等待回执，使用原节点 token，Agent 不访问数据库。实现 13a5cecf79d3ca677929e0f77c356cab19c56e0a，开发 FUNCTIONAL_COMPLETE / 验收 CI_PENDING，详见[本轮记录](RESOURCE_ADMISSION_SAFE_REQUEUE_20261125.md)。

## 2026-11-25 算法目录后端模块化

前端不变。原 v12 算法列表/CRUD、待归属模型、版本备注/删除/回退、dry-run、重试清理、授权下载共 14 个接口改由 algorithm_catalog_api/contract/service 实现；Method/URL/签名/默认值/鉴权/错误/请求模型保持，原 Repository 与外部 Owner 不变。app 只保留装配、单一 bootstrap 生命周期状态及必要兼容调用。静态 HTTP 序列和模型逐项一致，运行期/OpenAPI CI_PENDING；见[域边界及验证](BACKEND_ALGORITHM_CATALOG_MODULARIZATION_20261125.md)。A 的恢复请求只影响原 Agent 恢复链，不新增前端页面或操作。

## 2026-11-25 素材目录后端模块化

后续治理与标签/人工 GT：8 个素材准入/成员/用途/状态接口进入 material_governance_api/service/contracts；10 个标签创建/编辑/删除/引用/重映射/统一、人工标注查询/保存接口进入 annotation_governance_api/service/contracts。原 HTTP 和权限合同、底层 Repository/GT/标签锁/删除恢复及回执 Owner 保持；前端、专业组件及所有菜单/入口不变。起点 6111b541，A e3764889，B/最终 SHA 见交付消息。开发 FUNCTIONAL_COMPLETE / 验收 CI_PENDING，仅静态验证；AI 创建/清洗/审核与 C2-B 编排未迁移。详见[实际业务范围与剩余依赖](BACKEND_ALGORITHM_CATALOG_MODULARIZATION_20261125.md)。

12 个既有素材浏览、数据集目录、只读标签/质量/统计接口迁入 material_catalog_api/service/contracts；静态 URL/Method/签名/顺序保持。原分页/跨页 ID/缩略图锁/权限与 Repository 不变，原前端、删除、GT、标签写入、AI 审核及治理任务 Owner 不动。开发 FUNCTIONAL_COMPLETE / 验收 CI_PENDING，运行期 OpenAPI/原测试交现有 CI；见[迁移边界](BACKEND_ALGORITHM_CATALOG_MODULARIZATION_20261125.md)。

## 2026-11-25 AI 审核与训练管理后端模块化

前端和全部入口不变。AI 33、清洗 7、训练管理 11、评测/难样本/补充数据/算法报告 14 个原接口分别由 ai_annotation、cleaning_management、training_management、training_evaluation 的 API/Service/Contracts 持有；正式 GT、CandidateStore、冻结、TaskRuntime、反馈 Repository、Worker 与 legacy 运行访问器仍唯一。两种同名选择请求保留原字段与各自绑定。A f68fa366 / B 7044815c，C/最终见所在提交及交付消息。开发 FUNCTIONAL_COMPLETE / 验收 CI_PENDING；仅静态核验，运行期/实际体验未验，不代表后端所有业务已迁完。见[本批范围与剩余 Owner](BACKEND_ALGORITHM_CATALOG_MODULARIZATION_20261125.md)。

## 2026-11-25 剩余后端集中迁移

前端、菜单、入口及 HTTP 产品合同保持。转换交付/部署验证 34、统一导入/存储扫描/视频/检测审核 42、项目/存储/AI/运行资源配置 67 个既有接口进入对应领域 API/Service（有实际模型才设 Contracts）；原转换器、上传/ZIP/存储、GT、TaskRuntime、发布、SecretStore/Session 与 Worker 唯一 Owner 不变，无新执行模式。A 1c5f6de6 / B 4492a17d；C/最终见所在提交和交付消息。开发 FUNCTIONAL_COMPLETE / 验收 CI_PENDING，仅静态核验，运行期、生产和实际体验未验；根生命周期及未迁旧业务见[本批边界](BACKEND_ALGORITHM_CATALOG_MODULARIZATION_20261125.md)。

## 2026-11-26 后端集中收尾

前端与全部菜单/入口保持。model_inference 6、dataset_export 6、legacy_automation 17、quality_analysis 5，以及原 material_governance 增量 1，共 35 原接口完成 HTTP/业务迁移；真实 GT、数据集/模型/任务身份、原事务和共享访问器不变。旧 test_models 仍有实际调用，artifact 兼容符号接回唯一正式 Reader，未删除旧 API。根 43 接口按认证/文件 8、生命周期/环境 9、训练/确认共享入口 5、bootstrap 3、拒绝兼容 16、历史控制 2 保留。A dd8254b8 / B b3b419ee，C/最终见所在提交与交付消息；开发 FUNCTIONAL_COMPLETE / 验收 CI_PENDING，仅静态核验，运行期/产品体验未验，不提前进入 Vue/正式 PostgreSQL。见[完整清单与遗留](BACKEND_ALGORITHM_CATALOG_MODULARIZATION_20261125.md)末节。
