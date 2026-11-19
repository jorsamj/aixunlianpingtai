# 功能/API迁移矩阵（M0基线2026-11-18，当前M3-A）

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
|素材库分页/详情/标注/GT|MaterialPaginationRuntime；openAnnotation|/api/v61/projects/{p}/materials；/api/projects/{p}/annotations/{i}|MaterialRepository；AnnotationRepository|源SHA/正式GT version CAS/隐藏框保全|MaterialLibrary + MaterialPreview；人工标注回原Owner|完整编辑继续原Owner|LEGACY_BRIDGE|NOT_STARTED|未实施/未提交|frontend/src/views/MaterialLibrary.vue；本行Owner/API源码|
|图片上传/ZIP/清洗治理|原Uppy/ZIP/TaskCenter|v19 ZIP；v61 storage-imports/{t}/confirm|原导入Handler；MaterialRepository；TaskRepository|AWAITING_CONFIRMATION非终态/取消fencing/单调进度|MaterialImportGovernance|ZIP/治理真实执行未验|LEGACY_BRIDGE|NOT_STARTED|未实施/未提交|frontend/src/views/MaterialImportGovernance.vue；本行Owner/API源码|
|算法负池/标签管理|static/modules/labels.js；frontend/src/views/NegativePool.vue|/api/v61/projects/{p}/negative-pool；GET /api/v12/projects/{p}/labels；POST /api/projects/{p}/labels；PUT/DELETE /api/v12/projects/{p}/labels/{class_id}；GET /api/v54/projects/{p}/label-schema|platform_core/negative_pool_api.py；platform_core/annotation_repository.py；app.py标签路由|revision/operation_id/CAS/未知回执先读回|NegativePool；标签完整页仍旧|标签完整CRUD不因负池组件存在视为完成|LEGACY_BRIDGE|NOT_STARTED|未实施/未提交|frontend/src/views/NegativePool.vue；本行Owner/API源码|
|AI创建/选择/Provider/确认|原AI Submit/Picker|/api/v60/projects/{p}/annotation-tasks；by-request|AnnotationTaskService；TaskRepository|request_id UNKNOWN只GET恢复/冻结选择|AiAnnotationCreate|三步展示复用原子树|LEGACY_BRIDGE|NOT_STARTED|未实施/未提交|frontend/src/views/AiAnnotationCreate.vue；本行Owner/API源码|
|AI任务/失败诊断/取消恢复|原Task/Candidate Owner|v60 annotation-tasks/{t}及原诊断/恢复子路由|AnnotationTaskService；CandidateStore|取消后不得推理/候选写入；失败不算unreviewed|AiAnnotationTasks|完整诊断导出/重试继续旧页|LEGACY_BRIDGE|NOT_STARTED|未实施/未提交|frontend/src/views/AiAnnotationTasks.vue；本行Owner/API源码|
|AI候选/人工消歧/采用拒绝/正式提交|reviewAiLabel427/Annotorious|原v60审核路由|CandidateStore；AnnotationRepository|草稿revision≠GT version；歧义禁止提交；明确确认后入库|AiReviewWorkbench + AnnotationEditor|编辑核/GT提交不可复制|LEGACY_BRIDGE|NOT_STARTED|未实施/未提交|frontend/src/views/AiReviewWorkbench.vue；本行Owner/API源码|
|训练创建/标签/选材/冻结|原生src/app/TrainingCreate.vue + TrainingMaterials.vue；复用纯Draft/Submit函数|原v12 train/start；v62 training-materials分页/summary/reference/revision/compatibility；Task reader_view|原训练服务/GT/Artifact/TaskRepository/Worker|五修订核验/大范围引用/Test隔离/已审核GT/未知只GET|原views外壳保留旧试点；新App完全原生|任务执行和报告不在M3-A；有来源评测决策仍原Owner|原生普通创建；其余LEGACY_BRIDGE|FUNCTIONAL_COMPLETE（M3-A普通创建范围）|CI_PENDING|代码07b98d23；文末测试与边界|
|训练准备/执行/队列/取消/恢复|TrainingRecoveryRuntime/TaskCenter|/api/v62/projects/{p}/tasks[/{t}]；cancel/promote|task_runtime/query_api.py；TaskRepository；原Worker|资源队列/租约/取消fencing/terminal停止轮询|TrainingTasks|执行与恢复完整旧页|LEGACY_BRIDGE|NOT_STARTED|未实施/未提交|frontend/src/views/TrainingTasks.vue；本行Owner/API源码|
|报告/评估/质量中心|原reports/quality/evaluation|/api/v44/projects/{p}/jobs/{j}/report|原报告Owner/正式版本与评估数据|finalized优先/Val Test独立/身份校验/有界历史|TrainingReport + ReportCharts|复杂评估与质量中心旧页|PRESENTATION_ONLY|NOT_STARTED|未实施/未提交|frontend/src/views/TrainingReport.vue；本行Owner/API源码|
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
