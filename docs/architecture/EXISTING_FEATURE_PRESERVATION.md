# 既有功能保护与 Vue 试点边界

## 2026-11-18 Payload 最终审计整改

对照 `6f9260163442a16d163c316f7b56f793d3fa0604`；详见[本轮根因、定向命令及边界](P2B_4A_2B_FINAL_AUDIT_FIXES_20261118.md)。仅修正旧测试夹具 / 新 Payload 验证式读取和两个任务概览的删除查询异常回退。

| 项目 | 结论 | 证据 |
|---|---|---|
| 菜单 / 页面 / 布局 / 按钮 | 保持一致 | static / Vue / 导航无 Diff，浏览器仅更正新任务证据读取 |
| 训练创建、排除审计、修订拒绝、Test 泄漏和标注 | 保持一致 | 原断言保留，真实 Chrome 指定单项通过；未改冻结 / 执行身份合同 |
| Durable 状态覆盖旧概览索引 | 保持一致 | 原 RUNNING 覆盖 queued 与 progress=37 断言通过；墓碑查询批量、无新增 N+1 / 全历史扫描 |
| 删除身份无法核验时的旧索引回退 | 发现差异（本轮明确授权修正） | 原先可能展示已删任务，现明确 HTTP 503；正常 / 回退列表均批量过滤墓碑；原索引不写入 |
| 训练准备、取消 / 删除保留、只读维护和统计 | 保持一致 | 直接相关 62 项回归通过；不重做 P2A–P4、不改 lease / attempt Owner |
| 生产 / Linux 最终 CI | 尚未核实 | 无 A800 / 4070 / 生产操作；准确新 SHA CI 与本地验证分开报告 |

## 2026-11-18 P2B-4A-2B Payload 连续开发补充

本条补充下方历史台账，范围为用户批准的不可变 Payload 发布、训练 / 部署迁移、执行锚点、有界 Claim、安全删除。对照 `aabffa49479a9b40f3c35d6fcd2414bad09519ea`，不改 VERSION。阶段提交、真实测试 / 性能与未验证范围见 [连续交付记录](P2B_4A_2B_CONTINUOUS_DELIVERY_20261118.md)。原三份未提交设计不覆盖、不混入提交。

| 对象 | 本轮结论 | 源码 / 定向证据 |
|---|---|---|
| 菜单 / 分组 / 页面布局 | 保持一致 | static / Vue / 导航无 Diff；不重新运行无关页面测试 |
| 创建 / 取消 / 恢复 / 查看按钮及前端提交字段 | 保持一致 | 原入口保留，没有新增前端 Owner；训练请求、部署创建恢复 API 回归 |
| 训练 / 部署操作链路 | 发现差异（已授权内部安全协议） | 原 Task / Handler / GT / 模型校验 Owner 不变，Payload 改不可变 ref + 收据 + Repository CAS；训练先 freeze 再 READY，两个实际正式 Test 调用方传锚点 |
| Task kind / status / 优先方向 / queue_rank / 执行代数 | 保持一致 | Repository / Scheduler / Fencing / GPU 与 Assignment 定向测试；有界扫描改为优先窗口 + 轮转，不声称全局严格优先级 |
| Assignment / Execution Lease / 远程资源保护 | 保持一致 | 沿用中央分配和原执行权，远程 Agent 无中央 SQLite 访问；73 项 Assignment 回归，历史晚期门禁复用现有端点和监控循环 |
| 删除后当前列表 / 详情 / 操作 | 保持一致 | 当前 Task 消失，终态 / 活进程保护保留；已有批删及新回归通过 |
| 删除后的物理文件与身份重用 | 发现差异（已授权安全保留） | 新协议和历史证据保留、墓碑防复活 / 重用；附加 audit_retained_ids，不自动 GC。空间释放策略待独立确认 |
| 模型 / 历史报告 / 正式 Test 证据 | 保持一致（原证据含义） | 新执行固定 attempt 锚点，重试 / 删除后不改读当前 Payload；legacy 保留可靠原路径，无法证明历史时仍拒绝 |
| checkpoint / result / log / 普通缓存写入 | 保持一致 | 没有机械版本化所有产物；只限制 Payload / 证据保留命名空间 |
| A800 / 4070 / 掉电 / 真 GPU 与网络分区现场 | 尚未核实 | 没有生产操作；Windows 临时库验证不冒充现场或 Linux CI |

本地定向结果与 CI 分开报告；新 SHA CI 未完成前不标记专项通过，不自动进入下一专项。

长期规则已合入根 AGENTS.md；本文是功能保留台账，不另建规则体系。对照基线 5e9ae265；P2A 3a4d76e、P2B d486d75；本轮修复独立提交。源码和既有合同可证明未改动，不等于现场生产验收。

## 原则与审批

用户未提出的产品行为维持原样；技术治理只改变内部实现。菜单/布局/功能入口/业务流程/默认值/权限/API或执行语义变化必须先提交“当前功能、问题、原因、方案、收益、可能丢失能力、习惯影响、数据/API影响、能否暂缓、优先级”，标记 `AWAITING_USER_APPROVAL`，收到明确确认再实施。已确认且不改变合同的技术缺陷可最小修复。本轮以下恢复行为已获用户明确批准，无其他待实施产品变更建议。

## 入口与功能台账

结论仅使用“保持一致 / 发现差异 / 尚未核实”。证据分别区分菜单、页面、按钮、真实操作；只读打开不代表写入验收。未改动的业务复用原文档和既有 CI，不扩展运行测试。

| 功能 | 原入口 / 页面 Owner | API / Repository 权威 | 本轮改动与授权 | 结论 / 证据 |
|---|---|---|---|---|
| 工作台/导航/登录/项目 | 总览、NavigationStability、原 Session、PageRequestScope/PollRegistry | 原 auth/session、v53；原持久导航 | 已授权取消 P1Z 别名替代；工作台不隐式启用 Vue 业务页，保留原菜单分组顺序，不藏入高级菜单 | 发现差异→局部修复；首批 19 项导航/身份/取消定向 Node 通过，另补独立试点刷新单例（已复现原失败，修复后交 CI）；准确修复 SHA CI 待核 |
| 算法库 | 内部 算法列表；AlgorithmListRuntime | v12 / algorithms.py / AlgorithmSqlStore | 已授权用户可见名称统一算法库；卡片/信息/版本/操作不改，工作台卡片回原入口 | 保持一致（恢复后）；原 card-grid 和创建按钮/事件 Owner 仍在；真实入口 CI 补卡片检查 |
| 素材库 | 数据集；原 renderDatasets424 / MaterialPaginationRuntime | v61 / MaterialRepository / StorageManager | 原分组和完整工作台恢复直达；未改素材列表、批选、上传、ZIP、清洗、负池、训练关联 | 保持一致（恢复后）；原素材卡片/批量操作源码不变；CI 补直接人工标注按钮 |
| 人工标注/正式 GT/标签 | 素材卡片“标注/编辑标注”→openAnnotation；annotation-workbench、annotorious-editor、几何适配 | 原 annotations API / AnnotationRepository；CAS/源 SHA | 仅修原读取合并丢失图片 URL，并核验图片 ID；编辑/保存 Owner 不变；不把 Vue 只读详情当作完整标注台 | 保持一致；原 saveAnn/AnnotationRepository 不变，真实离线 Annotorious 打开在隔离 CI 验证，不写 GT |
| AI 自动标注/审核 | 自动标注及清洗；createAiLabel427/showAiTask60/reviewAiLabel427 | v60 / TaskRepository / CandidateStore / 原正式 GT 提交 | 工作台回原入口；Vue AI 页面需各自开关；Provider/候选/失败/人工审核提交未改 | 保持一致（源码合同）；复用 P1O–R/X 及既有 AI/editor CI；真实推理和生产入库未验 |
| 训练创建/任务/取消恢复 | 算法卡片、训练任务；TrainingDraft/TrainingSubmit/TrainingRecoveryRuntime | 原 train/start、v62 / TaskRepository / Frozen selection | 工作台任务卡片及查看详情交回原 Owner；无训练、调度、取消执行代码修改 | 保持一致（源码合同）；复用原训练 CI，不执行训练 |
| 训练/评测报告 | 原版本报告、任务报告；openVersionReport429/openJobReport429、原 ECharts/Panzoom | v44/原版本 evaluation API；原 finalized/report Owner | 工作台默认走原报告；Vue 报告仅显式开关启用，不替换正式菜单 | 保持一致（源码合同）；既有报告隔离测试和原 P1T 合同；真实质量未验 |
| 模型/版本/资产 | 原算法卡片、版本详情；原版本及 ModelArtifact Owner | v12/v64 / AlgorithmSqlStore、ModelArtifactRepository | Vue ModelAssets 表格只作试点，未改原权重身份、当前/历史版本或转换关联 | 保持一致；版本与资产 Repo 文件不改；完整 Vue 功能等价尚未核实，不准宣称正式替代 |
| 模型转换/硬件准入 | 原版本转换/日志/数值验证；conversion-workbench | 原 v39/v42、conversion_tasks/历史投影 | 无执行/准入改动；本轮不改 P2B 七条 catalog Router/DI 合同 | 保持一致（源码合同）；d486d75 Remote Conversion CI 成功；本轮不跑真实转换/SDK |
| 发布/回传/回退 | 原算法版本交付及发布入口；ExternalAlgorithmPublishRuntime/Service | ExternalPublicationRepository、ModelArtifactRepository、原 UNKNOWN 回执 | 无发布、自动回传开关、追加权重、幂等/失败恢复/回退代码修改 | 保持一致（源码合同）；复用原发布 CI；真实外部/OSS 发布未验 |
| 算力/Worker/Agent/Supervisor | 原服务节点/训练资源/部署资源 | ServiceNodeRepository、GPUResourceManager、Task Runtime/fencing | 原资源入口不映射为 Vue 只读页；执行器/租约/调度文件未改 | 保持一致（源码合同）；现场硬件与安全执行不在本轮验证范围 |
| 模型/Prompt/存储/平台/字典配置 | 原高级功能及系统与对接；AdvancedNavigation、原配置 Owner | v35/v61/v63/v64、SecretStore、原 Repositories | 保留原分组和原配置功能；工作台配置入口到原模型配置；统一 Vue 配置中心独立试点 | 保持一致（源码合同）；不读取生产密钥，不触发连接检测 |
| 质量评测/错误样本/场景实测 | 质量中心及原手工/场景评测入口 | 原 evaluation/quality Owner 与训练/评测快照 | 无页面/业务/图表引擎改动；P2 动态 import 不重写图表 | 保持一致（源码合同）；复用质量中心原 CI；真实评测未执行 |
| 数据/任务历史/冻结与日志 | 原算法/版本/任务/历史页 | 原 Task ArtifactStore、BatchSelection、GT、usage/lineage 等 | 不改历史记录、冻结引用、数据库 Schema 或文件 | 保持一致（源码合同）；保留 P2C 只读设计，不迁移/双写 |

## P1 差异归因与处置

- **发现差异：P1Z** `5e9ae265` product-workbench-runtime 的 aliases/primary 菜单及 main.mjs `vueFeatureEnabled` OR 工作台开关，试点时把原算法卡片、完整素材/训练/AI入口导向功能较窄的 Vue 页面。默认未带开关的旧页仍存在，不能称 P2 删除了这些页面。本轮按明确授权局部取消替代；正式菜单不因任何 Vue 试点被改绑。
- **发现差异：历史 P1** ModelAssets 表格/左右分栏来自 P1E/P1H，MaterialLibrary 为 P1K 只读浏览且标注交回原 Owner；二者没有完整业务等价证据，只能独立显式试点。保留其代码，不重写或冒充全功能迁移。
- **用户确认的名称变更**：基线源码菜单/卡片标题实为“算法列表”；本轮用户明确指定显示为“算法库”，仅改可见名称，内部 ID、卡片信息及事件不变。不把这一授权改名说成对基线文字的逐字恢复。
- **发现差异：历史 P1 刷新**：没有工作台时，单独启用的 Vue 页面不在旧固定恢复白名单，刷新丢失当前页。新增单例确认后，原启动恢复仅额外询问 NavigationStability 已注册 Owner；未启用试点仍不恢复。没有新建恢复注册表或 Owner。
- **发现差异：原标注读取**：在 5e9ae265 基线已存在 `response.image || image` 覆盖已有素材记录的问题。真实 CI 收到 HTTP 200、image/jpeg、8671 字节及正确 JPEG 头，但详情未带 url，覆盖后 annImg.src 变成 undefined，Annotorious 因解码失败无法创建。仅在原 ensureWorkbench.load 合并素材/服务端详情，保留可信 URL，并拒绝不同图片 ID；不改 API、编辑器、GT 保存/CAS/Repository。新增单例先复现缺 URL，修复后验证 URL 保留、服务端字段优先及跨图拒绝；真实离线插件仍由原 CI 验证。首次引入提交受浅历史限制尚未核实，不能归因于 P2。
- **P2A/P2B** 未引入上述菜单/布局差异；18 页动态 import、取消冗余 Memory Router、共享 Chunk、离线闭包校验及 v39 工厂/原 Repo 注入均保留。
- **尚未核实**：所有 Vue 页与旧完整业务页面逐项产品等价、现场硬件、真实发布/训练/GT写入和完整目标机离线部署。本轮不扩大开发来填平这些差距；没有其他已确认缺失的正式 Owner，不以“未发现”冒充全平台逐项现场验收。

## 显式试点与恢复边界

`vue_workbench=1` 只增加“Vue 试点/工作台”，不改原默认页，不将旧菜单藏入高级功能；快捷卡片永远走原算法列表/数据集/训练任务/自动标注及清洗/服务节点/模型配置。上传卡片在原数据集调用原上传 Owner。

其他开关独立：vue_model_assets/vue_algorithm_manage、vue_material_library、vue_training_tasks、vue_training_report、vue_ai_tasks/vue_ai_review/vue_ai_create、vue_training_create/vue_training_picker、vue_conversion_create、vue_model_delivery、vue_material_import/vue_negative_pool、vue_configuration/vue_service_nodes/vue_catalog_preview/vue_catalog_manage。它们只启用既有试点入口/适配，原菜单 Owner 不变；工作台存在时独立试点以不同名称单独列出，避免同名误认为完整替代。

刷新时旧路由仍是旧路由；未单独启用的 Vue 页不能从历史恢复。项目相关上下文只保留安全身份，迟到请求由原 PageRequestScope/context.signal 与 generation/project 校验取消。退出工作台移除工作台开关，回原总览；试点返回原可信入口，不操作旧 DOM 内部状态。

## 本轮验证与回退

- 本地只执行 19 项定向 Node、语法/diff 检查；Vue SFC/构建配置未再变，不重复构建/浏览器/全量测试。
- 复用既有 Frontend Runtime CI 与隔离真实入口 Job：工作台单开关、刷新、原菜单唯一性、原算法卡片、直接素材标注按钮和真实 Annotorious、显式独立 Vue 页往返、退出取消与六视口；保留原零业务写入/项目身份/最多五条/单 Vue App 等断言。测试新预期来自本轮用户明确授权。
- 正式保存链路仅按源码/已有隔离合同核查，不对生产写 GT；准确修复 SHA CI/产物以最终交付回执为准，不借用 d486d75 状态。
- 回退本轮独立修复提交可恢复此前 P1Z 行为，不回滚 P2A/P2B；无 Schema/数据迁移。因会重新引入已确认替代映射，不自动执行回退，也不部署生产。


## 素材覆盖框专项诊断工具核验（2026-11-17）

- 保持一致（源码证据）：原素材页面、卡片/按钮、分页及标注 Owner/API/GT 链路和原 material-workflows 测试均未修改，本轮仅加强隔离诊断工具及既有 CI 制品保留。
- 尚未核实（运行证据边界）：919cd393 的素材分片 130/130 通过且诊断跳过，历史覆盖框回归仍开放，不能据此断言所有开关/分页路径正常。详见保护性审计后续核验记录。


## 素材摘要缺字段覆盖修复（2026-11-17）

- 保持一致：原素材菜单/卡片/标注按钮、Annotorious/GT保存Owner和分页API未改，原人工标注测试文件不变；只修复同项目摘要缺少images时误清空state.images，复用既有sameProject。
- 合同验证：缺字段保留、显式空列表、跨项目清空、初次加载、显式列表更新5项；A/B闸门均有效且通过，B由修复前失败变为通过；原用例1/1，开关/重绘及合成GT前后读取一致。
- 尚未核实：准确新提交CI异步结果、历史CI其他时序表现及现场环境；不据本地通过宣称所有历史问题关闭。两个诊断工具未提交修改保留，不纳入最小业务修复。


## P2B-2 功能保留核验（2026-11-17）

保持一致：菜单、页面布局、按钮、原进入/退出与操作链路源码均未修改，复用 c81460a8 准确36/36 CI及原Owner合同，不重复浏览器。仅 v62 两条GET内部模块归属变更；函数AST与原合同一致，实际Session/项目任务隔离与分页异常定向通过。TaskRepository/ArtifactStore/算法引用唯一Owner保留，取消/提权等写路由未改。尚未核实：新提交CI最终结果、生产/现场离线验收；本次不操作生产。详见上级 P2 技术底座文档 P2B-2 节。


## P2B-3A 功能保留核验（2026-11-18）

保持一致：菜单、页面、按钮和原操作链路未改；仅普通v62列表的Worker/全局队列证据读取改为按页需要执行。仍调用原task_to_public/TaskRepository，TRAINING_PREPARE不被排除，跨项目完整证据和队列精确性定义不变，reader_view/HTTP/权限/分页合同保留。定向12+3项通过；仅本地隔离测试，尚未核实新提交CI最终结果及生产性能，不操作生产。具体证据见P2技术底座P2B-3A节。


## P2B-3B（2026-11-18）

保持一致：菜单、页面、按钮和业务操作链路无改动；仅普通任务列表批量位置读取，原TaskRepository/投影/队列精确性/跨项目全局证据保留。定向54项通过，详情及其他调用方保持scalar；未操作生产。尚未核实：准确新SHA CI最终结果和生产性能。详见[P2B-3B专项](P2B_3B_TASK_READ_PERFORMANCE_20261118.md)。


## P2B-4A-1A（2026-11-18）

保持一致：菜单/页面/按钮/业务入口无改动；仅显式具备claim内恢复能力且Handler非空的Scheduler跳过外层恢复，空Handler与旧Repository保留。reaper、进程身份/Agent/GPU/代数与事务内复核保留；专项67通过，补强测试后Scheduler11通过（不累计）。尚未核实：新SHA最终CI和生产性能。[专项记录](P2B_4A_1A_SCHEDULER_EXPIRY_20261118.md)。


## P2B-4A-1A CI 精准收尾

保持一致：菜单/页面/按钮/正式导入流程及缓存Owner保留；仅隐藏地址读取面板的空任务列表不再触发完成刷新，真实终态和ZIP完成仍保留标签/素材局部刷新。原单次请求与禁止全局刷新断言保持，Node24精准Chrome1/1、Node7/7通过。新SHA CI未完成前不宣布验收；未部署生产。证据见P2B-4A-1A专项CI节。

## P2B-4A-2B-P1 Payload 存储基础能力（2026-11-18）

保持一致：菜单、页面、按钮及操作链路沿用既有入口；本轮不改前端/API/Task创建/训练/部署/Claim。新增不可变Payload与收据存储接口尚未接入正式业务，legacy无保留目录的删除保持原行为。发现差异：显式使用新命名空间的目录会触发删除前保留保护，仅为P1基础合同，业务删除兼容仍待后续设计。尚未核实：新SHA最终CI、生产路径迁移和历史执行锚点；未操作生产。[P1记录](P2B_4A_2B_P1_PAYLOAD_STORAGE_20261118.md)。

## P2B-4A-2B-P2A Repository Payload 发布事务（2026-11-18）

保持一致：菜单、页面、按钮和正式业务操作链路不改；新增训练/部署严格发布API尚未迁移到正式Handler，legacy父ref原激活合同保留。发现差异：已进入不可变ref协议的父任务，旧激活/settlement接口拒绝修改，防止绕过新事务。尚未核实：新SHA最终CI、生产接入及历史锚点/删除空间治理；未部署生产。[P2A记录](P2B_4A_2B_P2A_PAYLOAD_PUBLICATION_20261118.md)。
