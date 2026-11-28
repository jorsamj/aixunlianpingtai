# 算法库与版本生命周期模块化（2026-11-25）

开发 FUNCTIONAL_COMPLETE / 验收 CI_PENDING。运行期、完整 OpenAPI 展开与生产未验收。

## 工程身份与本轮范围

起始 21fb70de23c3be40006cb27579a031ca487abf60：用户已独立核验 22/22 PR workflow SUCCESS，既有 P0-01C 与资源准入不重新开发。
A 实现 dd8ee530924e79b87ed876d309b4dc0017d650bc，重启恢复合同见[资源等待记录](RESOURCE_ADMISSION_SAFE_REQUEUE_20261125.md)。
B 实现 da45ae7a46458cad0c8ce469f6083ae6c4613c21。最终含文档 SHA 和一次性 CI 快照见交付消息。

本轮完成算法库目录与版本生命周期这一完整子域，未声称迁完算法训练、评测、转换或发布域。

## 业务与模块边界

|模块|职责与唯一 Owner|
|---|---|
|algorithm_catalog_api.py|原 v12 HTTP 路由、签名、参数与原返回；调用目录 Service。|
|algorithm_catalog_contracts.py|原 AlgorithmReq、AlgorithmVersionReq、VersionPatchReq、AlgorithmVersionRollbackReq，字段/默认值/Literal 不变。|
|algorithm_catalog_service.py|目录与版本业务唯一实现：查询投影、历史/计数、引用保护、版本清理、回退、dry-run 及下载编排。|
|原 algorithms / AlgorithmRepository provider|继续拥有算法/版本持久读写、CAS 与事务；不新增 Repository，不增加 SQL，不启用 U1/PostgreSQL 切换或 fallback。|
|原 Task/Artifact/反馈/存储/发布服务|继续拥有对应记录、资源和外部操作；新 Service 只调用原访问器与既有锁。|
|app.py|Router 装配、动态依赖访问器和仍被其他域/测试调用的兼容入口；不保留两份业务实现。原 bootstrap 快照与锁仍由原应用生命周期 Owner 持有。|

14 个原接口原位注册，URL/Method 不变：

- 算法列表、创建、详情、编辑、删除（5）。
- 项目待归属模型查询；原手工版本归属拒绝入口（2）。
- 版本备注、版本删除、回退（3）。
- 激活 dry-run、回退 dry-run（2）。
- 清理失败重试、授权版本下载（2）。

原手工归属继续 409，外部 CHANG_LIAN 版本退役禁令、expected_current_version_id、活动引用阻断、删除回执、远端清理幂等及 dry-run 零写入断言保持。授权下载仍走原受控业务文件入口。原 App 兼容函数仅调用同一个 Service 实现，不重复注册路由；内部无引用的旧辅助转发已移除。

## 共享状态与一致性

依赖为显式、晚绑定访问器，不反向 import app，不复制 DATA_DIR、bootstrap 字典、锁、任务缓存或 Repository 实例。旧测试/业务替换存储 provider、目录读取器或数据根目录时仍经过相同入口。

bootstrap 列表只读复用与发布仍检查原项目、SQL revision、原锁及提交前 revision，回写由 app 的单一状态 Owner 完成。其余 28 个业务/辅助函数经依赖名还原的 AST 逐项比较，语句结构保持不变；未修改 Repository 事务或外部操作顺序。

## 必要验证与数量

- app.py 29,124 → 28,264 行（减少 860 行）。
- 直接 HTTP 声明 330 → 316，新 Router 原位补回 14。其他 Router 注册未改；展开新 Router 后，静态有序 Method/URL/签名/默认值/响应注解/说明与原注册序列逐项一致。这是静态证据，未冒充本机实际应用路由枚举。
- 原 4 个请求模型 AST 保持一致；新增 Router 的 FastAPI 导入、依赖字段/装配参数对应、未定义全局名称和新模块循环引用检查通过。
- 复用原 CRUD、模型视图、版本回退/清理/API 测试；现有 test_algorithm_flow 增加按旧声明冻结的 14 接口 OpenAPI operationId、query 默认值、请求模型和 dry-run 说明检查，交 CI 执行。
- 原外部退役安全守卫转向真正的 Service/Contracts/API Owner，保留全部断言；原 Algorithm SQL Store HTTP Job 增加运行现有版本回退测试。无新 workflow。
- 本机仅修改文件语法、AST/符号等定向静态检查及 git diff --check 通过。未导入运行 app，未执行 pytest、测试函数、浏览器、服务、Docker/WSL、GPU 或构建。运行期断言全部待现有 GitHub CI。

## 现状与剩余真实边界

|域|当前状态与后续边界|
|---|---|
|外部平台/发布、在线反馈|已有 Router/Service/Repository，继续复用，未重复开发。|
|算法库目录与版本生命周期|本轮 Router、契约和业务已迁出，持久化沿原 provider；训练结束自动归档等训练域调用留原 Owner。|
|训练创建/报告、素材 Picker/负池、智能审计|已有独立 API/Service 或专业模块；不能据此宣称全部训练/素材 HTTP 与业务已迁完。|
|素材、标签、人工 GT、AI 创建/审核|仍有 app 路由和编排；复用已有 MaterialRepository、AnnotationRepository、CandidateStore/annotation_task_service。后续需按标签/GT 锁、审核修订、冻结选择与批量提交边界迁移，不拆出第二写入 Owner。|
|训练管理与转换/质量/部署|仍有 app 任务控制、历史与联动编排；转换/旧 v42 组共享 _v42_*、产物及执行边界，应按完整业务单元迁，不能只搬两三个接口或改调度。|
|认证、bootstrap、存储/系统配置及生命周期|应用根仍持有 Session、快照、密钥/存储工厂和启动装配；新 Service 注入这些 Owner。尚未进行本轮范围外的生命周期重构。|

前端未修改，算法卡片、素材人工标注入口、AI 三栏、菜单和业务流程保持。保护文档/VERSION/AGENTS 未改，未访问 A800/4070/生产或启用双槽、自动清理、supervisor-required、PostgreSQL 正式切换。

本轮完成后停止，交 GPT 独立审计；CI_PENDING 不等于验收通过。

## 后续批次：素材目录与只读标签投影（2026-11-25）

起点 c183ab3d；A 832e168d 修复实际 CI 失效守卫，保留全部业务语义；B 327023ff399263e93b261c68cf08f5c534622bfc。开发 FUNCTIONAL_COMPLETE / 验收 CI_PENDING，不沿用旧 CI 验收新代码。

完整迁移单元为“素材浏览、数据集目录管理及只读标签/质量投影”，不是全部素材/标签业务：
- v61 素材分页、筛选、ID/跨页解析、状态统计、授权原内容、授权缩略图，共 5 接口。
- 数据集目录读取/创建/编辑共 3 接口。
- 兼容图片列表、标签目录、数据集质量、数据集统计共 4 接口。
- dataset_quality_report 的业务投影同时迁出；原 DatasetReq 字段/默认值保留。

material_catalog_api 只承担 HTTP，material_catalog_service 持有上述业务唯一实现，contracts 保留原 DatasetReq。无反向 app 导入，无新 Repository/SQL、共享全局复制或第二缓存。使用多组 Router 原位装配以保留原有穿插的存储生命周期接口顺序，不通过集中提前注册改变匹配次序。

原 MaterialRepository 的 list_page/list_ids/iter_filtered_ids/revision/processing_status_counts，原 AnnotationRepository 对外读取访问器、StorageManager 的内容/thumbnail 验证锁、后台标注索引调度 Owner 保留。数据集元数据沿原 ensure_default_datasets/datasets_file/write_json 访问器；未改变原锁或事务。分页入口不新增整库读取，兼容旧图片全量读取行为保持，未借迁移声称修复其历史性能问题。

已定向定位迁出路由/函数/模型/URL 与测试/Workflow 引用。现有兼容调用保留；未发现 B 需要迁移的额外旧源码守卫。A 将 intranet-mode-contract 的本地创建检查改查真实 Router 委派/Service 和原 LOCAL 来源，Label Normalization 的算法详情声明使用 AST 检查真实 GET，避免引号耦合，其余守卫不删。

静态证据：app.py 28,264→28,001 行，直接 HTTP 316→304+新 Router 12；展开后有序 HTTP 声明/签名/说明及其他 Router 注册相同。13 个业务/辅助函数依赖名称还原后 AST 一致；未定义名称检查通过。原 material_reader_views 补旧 12 接口 OpenAPI/operationId/DatasetReq 检查；原 Algorithm SQL Store HTTP Job 复用分页、统计、过滤、内容测试，无新 workflow。本机仅 py_compile、node --check（守卫语法）、定向 AST/符号检查和 git diff --check，未执行任何运行期测试。

剩余明确边界：素材删除与引用/恢复事务、GT 提交回执、标签写入/合并、AI 审核、治理执行，以及已模块化的 material_batches、训练 Picker/公共负池继续原 Owner。后续需沿这些共享锁和生命周期边界迁移，不伪称已经迁完，不改 UI。生产/硬件、运行时展开及准确新 SHA CI 尚待验证。

## 后续批次：素材治理、标签写入与人工 GT（2026-11-25）

基线 6111b541d617def129ac8ed51b1841782417ee8f，用户已独立核验 22/22 PR workflows SUCCESS。A 实现 e3764889；B 与最终 SHA 见本轮提交及交付消息。开发 FUNCTIONAL_COMPLETE / 验收 CI_PENDING；不沿用基线 CI 验收新代码。

- material_governance_api/service/contracts：8 个原接口，覆盖单图/数据集/批量旧删除入口的统一预检准入、素材成员移动、选中/筛选/数据集批量用途分配、自动分配、标记就绪和处理状态。旧删除入口仍要求原预检协议，不重新开放直接删除；实际删除、引用保护、恢复日志和文件回收继续由既有 material_batches、StorageManager 及原生命周期协议负责。
- annotation_governance_api/service/contracts：10 个原接口与 5 个关联辅助函数，覆盖标签创建/编辑/软删除与引用保护、人工标注详情/保存、导入标签重映射、正式标签引用统计/合并预检/单源及多源统一。正式 GT 写入仍调用原 write_annotation / AnnotationRepository；标签合并任务仍调用 material_batches 的冻结、幂等、持久回执和退役协议。
- 不复制共享状态，不新增 Repository/SQL/缓存；显式依赖装配复用原数据集锁、label_governance_fence、项目元数据访问器、TaskRuntime/ArtifactStore。兼容函数保留既有内部调用和测试替身入口，业务实现只有 Service 一份。HTTP 分组原位注册，保留中间穿插的其他 Router 顺序和应用原鉴权。

静态证据：app.py 28,001→27,303 行，直接 HTTP（含 async）304→286，新 Router 补回 18；有序 Method/URL、函数名、签名/默认值、说明、返回注解及其他 Router 注册一致。23 个业务/辅助函数经依赖名还原后 AST 一致，12 个请求模型 AST 一致，依赖字段与装配参数匹配，无新增未定义全局名称或反向 app 导入。保留 GT 版本 CAS、素材代际、审核 actor 私有字段、空标注/负样本范围、标签锁及历史训练映射。

旧源码守卫已转向真实 Owner：批量分组性能检查、Label Normalization 的标签引用/编码/空标注合同、Online Feedback 的审核状态合同。未删断言；新增两个现有 API 文件内的 18 接口 OpenAPI/唯一注册/请求模型回归，运行期全部交现有 CI。既有 material-annotation-atomicity、label-normalization、online-feedback 与 Algorithm SQL Store workflow 跟随新模块路径，无新 workflow。本机仅语法、符号、AST/接口合同和 git diff --check，未执行测试、应用或浏览器。

剩余边界：AI 创建/清洗/审核的原 HTTP 编排仍在 app，与候选草稿 CAS、冻结选择、正式 GT 屏障、负池和 C2-B 续批/取消对账共享上下文；本轮未拆出这些流程的一部分。原删除恢复日志及 write_annotation 底层事务访问器继续为其他导入/审核入口共享，未借迁移重构生命周期。旧 /images 全量读取和自动分配的既有读取行为保留，不声称完成其性能治理。前端、VERSION、AGENTS、四份保护文档及生产均未改；完成后停止，交独立审计。

## 后续批次：路由合同、AI 审核与训练管理（2026-11-25）

起点 47b7900b；用户核验 21/22 成功，唯一失败是 FastAPI 新版嵌套路由的测试枚举假设。A f68fa3669609304cad0b2a48174d372bac814ef7 改用官方 iter_route_contexts 的有效路径/original_route，保留旧版扁平路由回退和全部安全断言；未改生产注册或依赖版本。

B 7044815c295777ab335da4526c0f16ba271ca423：
- ai_annotation_api/service/contracts：33 个接口、57 个业务/辅助函数，完整覆盖持久创建及按 request_id 查回、分页/进度、取消/重试/结束审核、候选与诊断、单图及批量草稿、冻结/排除/分页、单图及批量决定/回执、正式 GT 入库、转负池/预览/撤销及 C2-B 执行/续批恢复/取消对账。
- cleaning_management_api/service/contracts：7 接口、12 个业务/辅助函数，覆盖清洗列表、预检、创建、取消、结果、标注审计及确认。原 prepare/publish、冻结 SQLite 选择、资源准入、实际 Worker 和文件删除协议仍为唯一 Owner。
- 原两个 AnnotationSelectionReq 同名但不同字段的 DTO 留在原声明位置，分别注入对应 Router factory；API 刻意在 factory 闭包求值类型，避免未来注解将两种选择解析成同一模型。其余 12 个模型迁出，继承的批量草稿模型和 StrictInt 不变。原搜索/统计后台线程、错误容器和锁留应用生命周期，Service 使用原访问器。

C/最终 SHA 见本节所在代码提交及交付消息：
- training_management_api/service/contracts：11 接口、17 个函数，训练列表、事件流、详情/资源及按需指标历史、有界日志、停止/插队/暂停/恢复、批量及单任务终态删除。唯一 TaskRepository、执行进程注册表、历史归档、删除保留策略及原 legacy 控制访问器保持。
- training_evaluation_api/service/contracts：14 接口、26 个函数，冻结评测图片的安全读取、可信证据/样本/报告、版本与深度对比、评测意见、已审核难样本预览/采用、合格样本筛选/创建、补充数据候选/冻结及算法级训练报告。原评测身份、不可变快照、反馈 Repository、已审核范围和训练联动 Owner 保留。
- 已迁移 training_create_api/service、TaskRuntime management/query、training_report_api 不重复开发。评测索引缓存/锁、历史计数缓存/锁通过原访问器引用，不复制状态，不新增 SQL 或 Repository。

静态证据：app.py 27,303→23,708 行、直接 HTTP 286→221，65 接口原位补回；有序 URL/Method/operationId 输入、参数/默认值、说明、返回注解、其他 Router 相对顺序及旧双选择 DTO 字段绑定一致。112 个函数经依赖名还原后 AST 一致，19 个模型 AST 一致，注入字段对应，无新增未定义全局名称或反向 app 导入。多行字面量保留原值。没有新增全量 hydration/N+1/重复 I/O；旧算法报告及历史路径的已有读取行为不借迁移改写。

定向守卫：标签归一化的恢复合同、AI 有效标签过滤、有界日志/指标历史、训练停止/删除/只读不归档及补充数据冻结 URL 改查真实 Owner；原故障注入/测试替身转向实际 Service 方法，原断言保留。两项既有 API 文件新增 40+25 接口的有效路由唯一性、endpoint Owner、OpenAPI/模型、双选择字段和历史默认值合同，沿既有 AI Recovery、Remote Cleaning、Training Visibility、Remote Training 等 workflow 执行，无新 workflow。本机不执行 pytest、应用、测试函数、浏览器、服务或构建；运行期、生产及实机均未验，开发 FUNCTIONAL_COMPLETE / 验收 CI_PENDING。

剩余职责：app 继续持有装配、认证/存储/配置、导入与检测批次审核、旧停用 AI 入口、共享后台索引及原 legacy 生命周期访问器；旧 V45 辅助归因和 V44 补充素材编排仍有 job.json/素材联动，未借本轮另改其写入语义。没有本轮已知安全阻断；上述剩余单元不是已迁移范围的隐藏第二 Owner。前端、VERSION、AGENTS、四份保护文档不变，无生产、GPU、服务器或正式 PostgreSQL 操作；完成后停止交独立审计。

## 后续批次：转换交付、导入与系统配置集中迁移（2026-11-25）

起点 4d98b1f7bc7de3f7ed55f2e566017532db78517b，开工插件一次查询为 22 个 PR workflow：2 SUCCESS / 20 QUEUED，无已完成失败；未将排队视为验收。A 1c5f6de615254137a6326a81c7f37fd02869bb69，B 4492a17d2518a5bf0bf66107902093b4fb546332；C/最终见所在代码提交及交付消息。开发 FUNCTIONAL_COMPLETE / 验收 CI_PENDING。

|单元|实际迁出职责|保留的权威与安全边界|
|---|---|---|
|conversion_management：27 接口、59 函数|转换资源管理/探测编排、来源/参数解析、创建幂等查回、任务管理、数值验证、硬件预检/证据、交付质量、版本转换历史、授权产物打包及旧模型导出编排|ConversionCatalog、原转换器/任务 Runtime、版本 fence、ModelArtifact、SecretStore、进程/远程线程注册表、发布请求 Owner、性能/缓存访问器；不将未硬件验收的产物升级为正式验收。|
|deployment_validation：7 接口、10 函数|部署检测创建/原提交 fence、回执恢复/查询、重试/取消、正式版本成功结果的反馈证据提升|原 TaskRuntime、stage_deployment_test、执行身份、不可变输入/版本、反馈与文件注册 Owner。|
|material_ingestion：25 接口、39 函数|统一图片上传入口、ZIP 导入/多段上传任务管理、用途/标签映射确认、样本和报告、终态隐藏、原来源导入与上传批次决策|原上传幂等仓储、ZIP 安全解析/扫描/解包、FIFO/停止 fence、标签/GT 写入、文件锁及后台 finalize/恢复 Worker；未重新实现导入引擎。|
|storage_ingestion：10 接口、13 函数|存储重扫预检/创建/确认/取消、素材扫描/确认及标签样本授权读取|StorageManager、来源代际 fence、原 TaskRuntime/Agent staging、冻结范围及正式映射回执。|
|video_tasks：4 接口、5 函数；detection_batches：3 接口、5 函数|视频创建/列表/详情/停止及进度；检测批次有界查询、单图人工结果意见|原视频 Worker/任务身份、Candidate/正式 GT 隔离、检测持久证据与审核 revision；无新切帧器。无 DTO 的单元只保留 API/Service，不留空 Contracts 文件。|
|project_management：5；storage_configuration：6|项目创建/读取/更新/删除/统计；存储源 CRUD、默认和测试|原 get_project/元数据访问器、MaterialRepository、来源变更屏障、凭据和存储仓储；鉴权仍为原 Session/中间件。|
|ai_configuration：19；runtime_catalog：37|AI 模型/容量/坐标和 Prompt、原辅助服务配置；节点/环境/母模型资产及安装验证入口、资源发现、原稳健性策略和运行资源只读目录|原 SecretStore/文件访问器、节点与资产仓储、后台探测/安装任务、配置和缓存 Owner；无真实配置、安装或网络探测执行。|

后三个配置分组共 67 个原 HTTP 业务体迁出，未复制全局状态、连接、缓存或锁。select_ultralytics_env 明确保留：它直接修改原全局环境及相关生命周期，不能为搬移而另建状态 Owner。母模型沙箱探测旧异常分支原引用未绑定 logger，本轮仅将其依赖接到已存在 logging，原失败处理、任务和验证器不改。

证据：app.py 23,708→18,503 行，直接 HTTP 221→78；143 个接口按原位置分组注册，URL/Method、签名、默认值、说明、返回注解及其他 Router 相对次序一致，原 operationId 输入未变。198 个函数依赖名还原后 AST 一致，30 个模型 AST 一致，多行字符串/f-string 原值保留；装配字段对应，无局部/自由变量误捕获、反向 app 导入或新未定义名称。未增加 SQL、全量 hydration、N+1 或额外业务 I/O。

旧守卫/故障注入已跟随真实 Service/API/Contracts。显式保留转换不可变成果与引用删除禁令、硬件能力、发布 fence、ZIP 到期清理/停止/创建、资源扫描冻结根等断言；标签 create_labels 的三处拒绝从旧 app 分布到素材服务 1 处和存储服务 2 处，数量和拒绝语义未降低。现有三个 API 文件新增 34+42+67 接口的有效路由上下文唯一性/endpoint Owner/OpenAPI/请求模型合同，沿现有 CI 执行，无新 workflow。前端产品未改，仅两个现有 Node 源码守卫改查实际后端 Owner。

本机只做源码语法、符号、AST/接口/依赖及源码守卫/YAML、Node 守卫语法、git diff --check；未运行 pytest、测试函数、应用、浏览器、GPU、服务或构建。运行期、硬件、真实安装/存储/外部发布均未验。VERSION 42.24.592、AGENTS 与四份保护文档保持，未操作生产、A800/4070、正式数据库或新执行模式。

剩余 app 根并非只有装配：仍有认证/Session、受控文件、bootstrap、共享缓存/锁/凭据工厂、Worker 与恢复、装饰的性能/缓存/版本锁访问器；还有旧推理、数据集构建/导出、v42 策略/采集/质量编排、旧辅助归因/补充素材、停用的旧导入/预标注接口。已模块化的外部发布、字典、执行/调度、GT 与报告不重复开发。旧 v12_test_models 仍有基线即存在的未定义 v39_list_deploy_artifacts 兼容引用，属于未迁旧查询入口，留待定向核验，未以测试通过或迁移掩盖。根权限和生命周期 Owner 不强行拆分。完成后停止，交 GPT 独立审计。

## 后端集中收尾：CI、artifact 兼容及剩余域（2026-11-26）

起点 92022115750d8354e88a431416abd1c94916f980。用户最终 CI 核验覆盖两轮：4d98b1f7 的 20/2、92022115 的 19/3（成功/失败）。本轮只读取三个失败 Job 的实际日志，没有把曾经 QUEUED 的快照冒称通过。

A dd8254b8ef00c8974a2384cc0146ecabed3f8f3b，30 项失败分类：
|数量|实际原因|最小处理|
|---|---|---|
|3|AI prepare 替身仍挂 app，真实 Service 使用自己的导入，意外进入真实项目/模型查验|改挂 ai_annotation_service 的 prepare_annotation_request，原项目、1200 张 500 分页、GT、冻结排除和模型快照断言保留。|
|1|旧守卫按 app 中已迁走的 v60 路由切片，substring 不存在|读取真实 Service 方法并核对真实 API 委派，保留原模型快照权威及禁止第二 provider 的断言。|
|19|评测图片的 MaterialRepository 替身/观察器仍挂 app，真实 Service 查询另一实例，提前报缺图，掩盖后续预期分支|将构造、原始类捕获、观察器和 hash 方法注入统一到 training_evaluation_service；SHA、真实格式/尺寸、权限/存储错误和 20k/有界读取断言全部保留。|
|1|困难样本正式 GT 的 AnnotationRepository 替身未命中|指向真实模块，并同步后续采用阶段的版本写入替身；原资格、Test 隔离、GT 代际与幂等断言保留。|
|2|public_annotation_task 替身不接受兼容入口必传的 summary 等投影参数|支持投影参数并保留原字段及非空 summary，不修改实际投影实现。|
|4|目录调用 detect_missing=False 经 app 兼容入口转成位置参数，与关键字替身协议不符|app/API 均按 detect_missing=detect_missing 委派，原公开签名/HTTP 默认值与 Service 业务不变。|

上述为源码和日志确认后的定向修改，未声称这些运行期测试已在本机重跑通过。没有放宽图片身份、GT、节点/资源、模型配置、候选资格或目录探测规则。训练 22 项逐组核对了提前缺图、错误码、计数、GT 资格及投影 TypeError，而非仅凭数量认定 fixture。

B b3b419ee347f468fd8f91df8ddc2d966039e0377 是真实兼容缺陷修复：static/app.js 的 loadRelated/页面补读及原回归仍调用 test_models；其非 scenario 分支引用已从根迁走的 v39_list_deploy_artifacts，NameError 被既有异常处理吞掉，导致转换模型静默缺失。现在 deployment/artifacts_api.py 的 list_deploy_artifacts 为唯一查询体，原 Router 名称/URL/operationId、已产出任务过滤、文件存在/类型与逐文件业务授权、返回字段/下载 URL 保持；根兼容函数只委派同一 Reader，没有新缓存、空列表 fallback 或第二 Artifact Owner。原查询主体 AST 一致；在现有产物 API 测试中补非空 legacy 模型回读和授权拒绝合同。旧可选查询异常处理未重写。

C/最终 SHA 见所在提交及交付消息：
|领域|本轮实质迁移|唯一 Owner/边界|
|---|---|---|
|model_inference|6 个旧模型列表/下载、两代预测、ONNX 导出和检测模型目录接口|复用原模型解析、运行环境/预测适配器、文件授权与正式 artifact Reader，不重写推理内核。|
|dataset_export|6 接口、13 函数：YOLO/COCO/Paddle 构建、导出、分组与原训练快照 builder|复用正式 GT、标签归一化、原内容解析和授权；原历史行为及原错误保持，不代替正式训练冻结 Owner。|
|legacy_automation|17 活动接口、22 函数：蓝图、素材源 CRUD/测试/采集编排、策略/迭代历史与删除、旧反馈只读、卫生及质量概览|原 v42 JSON 访问器、采集 Worker/调度生命周期和配置/算法 Owner 保留；明确停用的迭代写入不重新启用。|
|quality_analysis|5 接口、7 函数：项目/数据质量、模型测试委派、V45 辅助归因与 V44 补充素材|原 GT、模型配置、job.json 写锁/索引访问器和素材事务保持；AI 仍只做归因，不替代客观评测或正式 GT。|
|material_governance 增量|原模块增加 1 个显示名编辑接口|不新建 Service，原文件名/物理路径与快照身份不改，沿原 MaterialRepository.patch 和标注投影。|

静态证据：本轮 C 共 35 接口、49 业务/辅助函数、8 模型；依赖名还原后的业务 AST、模型、URL/Method/签名/默认值/说明/返回注解与有序注册一致，未引入依赖误捕获、反向 app 导入或未定义全局名。B 之后剩余 app 活动路径的未定义 artifact 符号已消除。app.py 18,503→17,657，直接路由 78→43；累计较原基点 29,124 行/330 路由为 17,657/43（287 个直接接口迁出）。这些仅为辅助指标，根仍有原共享访问器及 Worker。

对原 78 路由做一次有界分类并完成独立单元迁移后，43 个保留根接口无漏项：
|根职责|数量|保留原因及后续条件|
|---|---|---|
|认证/Session、受控业务文件、应用页面/健康|8|共享鉴权中间件、Cookie/会话和文件权限 Owner，保留安全装配顺序。|
|索引/存储生命周期状态、全局环境选择、组件扫描/SDK/部署矩阵|9|后台索引/扫描注册表、进程级环境与安装生命周期仍唯一；环境选择直接修改原全局状态，不为搬行数复制 Owner。|
|训练选项/继承/基准、已确认动作与迭代基线共享入口|5|跨原创建、算法版本资格、冻结来源及 confirmed action 的根访问器，独立正式创建/评测实现不重复。|
|bootstrap|3|原快照状态、缓存发布/失效及启动协调在根。|
|历史拒绝/间接拒绝入口|16|旧标注格式导入/预标注保留原 409；v47 旧 AI 与 v42 停用迭代保留原 410，以及原前置 400/404 等检查；不得本轮删除/恢复。|
|原预标注历史查询/停止|2|仍需历史兼容和取消控制，原任务/文件 Owner 保留；退役须先确认历史客户端用途。|

后端整体清单：算法目录/版本、素材目录/治理、标签/人工 GT、AI/清洗/审核/C2-B、训练创建/管理/报告/评测、转换/部署/交付与外部发布、统一上传/ZIP/扫描/视频/检测、项目/存储/AI/运行配置，以及本轮推理/导出/活动旧编排均已有相应业务模块。原 NegativePool、Picker、TaskRuntime、Agent、资源恢复和专业存储模块继续复用。没有把剩余根复制到大文件，也没有二次拆分大 AI/转换 Service。共享数据访问、缓存/锁、SecretStore、Session、任务/Worker 和 legacy 生命周期尚在根是有意保留；进一步迁移须先建立保持其生命周期/权限/并发边界的合同。本轮没有未处理的已知代码阻断，但不把这些保留职责宣称为“全部脱离 app”。16 个拒绝入口及历史控制可在后续明确授权和用途核验后退役。

旧源码守卫和 compute_quality 等导入替身已定向改到真实 Owner，原断言未删弱。现有 GT 文件追加 35 接口的有效路由上下文唯一性、endpoint Owner、OpenAPI/请求模型合同；Remote Training 的既有 API Job 仅增加该定向合同和原 include_empty 安全守卫，其他原业务回归沿现有 CI，无新 workflow。本机只做修改文件语法/符号、AST/接口/装配、原断言/守卫与 YAML、git diff --check；不运行 pytest、应用、浏览器、真实服务或构建。开发 FUNCTIONAL_COMPLETE / 验收 CI_PENDING，准确最终 SHA 的一次 CI 快照见交付消息，非通过验收。

VERSION 42.24.592、AGENTS、四份保护文档和产品前端保持，未访问 A800/4070、生产数据/模型/数据库或服务，未开启 Vue/正式 PostgreSQL、双槽、清理或 supervisor-required。统一推送后停止，交独立审计。
