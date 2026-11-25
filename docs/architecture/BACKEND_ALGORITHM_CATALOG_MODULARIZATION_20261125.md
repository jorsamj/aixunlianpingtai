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
