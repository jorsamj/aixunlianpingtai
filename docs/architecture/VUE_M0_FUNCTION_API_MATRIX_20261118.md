# M0 功能/API迁移矩阵（2026-11-18）

本表是有界源码盘点，不是运行验收。用户新授权独立 `/app` Vue SPA；历史 opt-in-only 与完成后停止限制由本次授权覆盖。保持菜单、字段、权限、状态机、API、GT、任务、Repository唯一Owner及离线组件合同；不删能力、不操作生产/GPU、不改VERSION。P2A按需加载和P2B路由拆分成果保留。

## 状态合同

开发状态仅 NOT_STARTED / IN_PROGRESS / FUNCTIONAL_COMPLETE；验收状态 CI_PENDING / ACCEPTED / BLOCKED / AWAITING_USER_APPROVAL；尚未实施或提交时记“未实施/未提交”，只有实际阶段推送后才记CI_PENDING。覆盖性质另列，不等同开发或验收状态。M0记录时独立SPA全部NOT_STARTED、未实施/未提交；已有18个Vue试点单列，文件存在绝不表示完整迁移。M1仅原生壳和算法卡片CRUD/详情/版本；其余受控整页旧系统入口，需逐项证明链接正确及项目身份。

## 精确原导航

`static/app.js:5931` renderNav：总览→总览、质量中心；算法生成→算法列表（显示算法库）、训练任务；数据中心→数据集、视频切帧、自动标注及清洗、标签管理。展开高级后：高级功能→算力与节点、模型转换环境、AI 辅助配置、存储管理；系统与对接→平台对接、畅联云数据；另有始终显示的AI算法底座独立演示入口。不能把试点页列表当正式菜单。

`static/modules/advanced-navigation.js:1` 子入口：服务节点、训练环境、母模型管理、环境诊断；转换资源、厂商与芯片字典；AI模型、提示词模板；存储资源、空间与缓存、旧素材兼容迁移。

## 有界迁移台账

API中的{p}/{a}/{v}/{t}/{j}/{i}为原项目/算法/版本/任务/训练job/图片身份。未列精确子路由的动作不能据此宣称完成。

|旧菜单/页/按钮|前端Owner|API|后端服务/Repository|状态/错误合同|既有Vue试点覆盖|缺口/文件|覆盖性质|独立SPA开发|验收|证据|
|---|---|---|---|---|---|---|---|---|---|---|
|登录/项目/总览|static/app.js；static/main.mjs；frontend/src/app/App.vue|POST /api/auth/login；GET /api/auth/session；POST /api/auth/logout；GET/POST /api/projects；PUT/DELETE /api/projects/{p}；POST /api/v53/bootstrap/start；GET /api/v53/bootstrap/status、/snapshot|app.py auth/projects路由；platform_core/bootstrap.py|401/项目身份/退出取消|ProductWorkbench|旧登录与项目流程；独立SPA尚无|PRESENTATION_ONLY|NOT_STARTED|未实施/未提交|frontend/src/views/ProductWorkbench.vue；本行Owner/API源码|
|算法库卡片/筛选/新增编辑删除/详情版本|AlgorithmListRuntime；ModelAssets|/api/v12/projects/{p}/algorithms[/{a}]|AlgorithmSqlStore|写后GET/只读主数据/引用约束；删除不可按编辑覆盖推断|ModelAssets + AlgorithmEditor + ModelVersionDetails|M1原生目标；删除权限/API需逐项核实|PRESENTATION_ONLY|NOT_STARTED|未实施/未提交|frontend/src/views/ModelAssets.vue；本行Owner/API源码|
|素材库分页/详情/标注/GT|MaterialPaginationRuntime；openAnnotation|/api/v61/projects/{p}/materials；/api/projects/{p}/annotations/{i}|MaterialRepository；AnnotationRepository|源SHA/正式GT version CAS/隐藏框保全|MaterialLibrary + AnnotationEditor|完整编辑继续原Owner|LEGACY_BRIDGE|NOT_STARTED|未实施/未提交|frontend/src/views/MaterialLibrary.vue；本行Owner/API源码|
|图片上传/ZIP/清洗治理|原Uppy/ZIP/TaskCenter|v19 ZIP；v61 storage-imports/{t}/confirm|原导入Handler；MaterialRepository；TaskRepository|AWAITING_CONFIRMATION非终态/取消fencing/单调进度|MaterialImportGovernance|ZIP/治理真实执行未验|LEGACY_BRIDGE|NOT_STARTED|未实施/未提交|frontend/src/views/MaterialImportGovernance.vue；本行Owner/API源码|
|算法负池/标签管理|static/modules/labels.js；frontend/src/views/NegativePool.vue|/api/v61/projects/{p}/negative-pool；GET /api/v12/projects/{p}/labels；POST /api/projects/{p}/labels；PUT/DELETE /api/v12/projects/{p}/labels/{class_id}；GET /api/v54/projects/{p}/label-schema|platform_core/negative_pool_api.py；platform_core/annotation_repository.py；app.py标签路由|revision/operation_id/CAS/未知回执先读回|NegativePool；标签完整页仍旧|标签完整CRUD不因负池组件存在视为完成|LEGACY_BRIDGE|NOT_STARTED|未实施/未提交|frontend/src/views/NegativePool.vue；本行Owner/API源码|
|AI创建/选择/Provider/确认|原AI Submit/Picker|/api/v60/projects/{p}/annotation-tasks；by-request|AnnotationTaskService；TaskRepository|request_id UNKNOWN只GET恢复/冻结选择|AiAnnotationCreate|三步展示复用原子树|LEGACY_BRIDGE|NOT_STARTED|未实施/未提交|frontend/src/views/AiAnnotationCreate.vue；本行Owner/API源码|
|AI任务/失败诊断/取消恢复|原Task/Candidate Owner|v60 annotation-tasks/{t}及原诊断/恢复子路由|AnnotationTaskService；CandidateStore|取消后不得推理/候选写入；失败不算unreviewed|AiAnnotationTasks|完整诊断导出/重试继续旧页|LEGACY_BRIDGE|NOT_STARTED|未实施/未提交|frontend/src/views/AiAnnotationTasks.vue；本行Owner/API源码|
|AI候选/人工消歧/采用拒绝/正式提交|reviewAiLabel427/Annotorious|原v60审核路由|CandidateStore；AnnotationRepository|草稿revision≠GT version；歧义禁止提交；明确确认后入库|AiReviewWorkbench|编辑核/GT提交不可复制|LEGACY_BRIDGE|NOT_STARTED|未实施/未提交|frontend/src/views/AiReviewWorkbench.vue；本行Owner/API源码|
|训练创建/标签/选材/冻结|TrainingDraft/Labels/Picker/Submit|v62 training-materials；selection-reference/summary；原提交API|training_material_picker_api.py；原训练服务|20k引用不展开/Test约束/标签冻结/UNKNOWN|TrainingCreate + TrainingMaterialPicker|仅三步外壳；原提交唯一|LEGACY_BRIDGE|NOT_STARTED|未实施/未提交|frontend/src/views/TrainingCreate.vue；本行Owner/API源码|
|训练准备/执行/队列/取消/恢复|TrainingRecoveryRuntime/TaskCenter|/api/v62/projects/{p}/tasks[/{t}]；cancel/promote|task_runtime/query_api.py；TaskRepository；原Worker|资源队列/租约/取消fencing/terminal停止轮询|TrainingTasks|执行与恢复完整旧页|LEGACY_BRIDGE|NOT_STARTED|未实施/未提交|frontend/src/views/TrainingTasks.vue；本行Owner/API源码|
|报告/评估/质量中心|原reports/quality/evaluation|/api/v44/projects/{p}/jobs/{j}/report|原报告Owner/正式版本与评估数据|finalized优先/Val Test独立/身份校验/有界历史|TrainingReport + ReportCharts|复杂评估与质量中心旧页|PRESENTATION_ONLY|NOT_STARTED|未实施/未提交|frontend/src/views/TrainingReport.vue；本行Owner/API源码|
|版本转换/动态参数/历史/验证取消|原转换Owner|/api/v42/projects/{p}/algorithms/{a}/versions/{v}/deployments|原deployment持久层/TaskRepository|UNKNOWN恢复/SDK与芯片能力/真实产物验证|ConversionCreate + ConversionHistory|真实SDK/转换未验|LEGACY_BRIDGE|NOT_STARTED|未实施/未提交|frontend/src/views/ConversionHistory.vue；本行Owner/API源码|
|模型交付/外部算法/平台对接|static/modules/external-algorithm-platform.js；static/modules/external-algorithm-publish.js；frontend/src/views/ModelDelivery.vue|GET/PUT /api/v63/external-algorithm-platform/config；PUT /api/v63/external-algorithm-platform/mode；POST /api/v63/external-algorithm-platform/test、/diagnostics；交付动作见原发布模块，不以配置API代替|platform_core/external_algorithm_platform.py；platform_core/external_algorithm_publish.py；platform_core/external_publish_request.py|预检/明确确认/UNKNOWN读回/禁止虚报成功|ModelDelivery|原完整平台/交付入口|LEGACY_BRIDGE|NOT_STARTED|未实施/未提交|frontend/src/views/ModelDelivery.vue；本行Owner/API源码|
|节点/Worker/GPU/训练环境母模型/组件诊断|ServiceNodeRuntime/原资源Owner|原service nodes/resource API|service_nodes.py；原Agent/Supervisor|在线≠有效≠可调度/不主动探测硬件|ServiceNodesOverview|写配置/诊断/安装旧页|PRESENTATION_ONLY|NOT_STARTED|未实施/未提交|frontend/src/views/ServiceNodesOverview.vue；本行Owner/API源码|
|转换资源/厂商芯片字典|AdvancedNavigation/catalog Owner|/api/v39/deploy/catalog/records；operations；chips/{id}/detect|deployment/catalog_api.py；ModelArtifactRepository|revision/operation_id/引用保护/observe_only|CatalogPreview + CatalogEditor/References|字典管理与转换环境分别验收|LEGACY_BRIDGE|NOT_STARTED|未实施/未提交|frontend/src/views/CatalogPreview.vue；本行Owner/API源码|
|AI模型/Prompt/存储缓存/兼容迁移|static/modules/advanced-navigation.js；static/modules/storage.js；frontend/src/views/ConfigurationCenter.vue|GET/POST /api/v35/model-configs；PUT/DELETE /api/v35/model-configs/{config_id}；POST /api/v35/model-configs/test；GET/POST /api/v35/prompt-templates；PUT/DELETE /api/v35/prompt-templates/{template_id}；POST /api/v35/prompt-templates/preview；GET/POST /api/v61/storage-sources；POST /api/v61/storage-sources/{source_id}/test、/default；DELETE /api/v61/storage-sources/{source_id}|app.py v35/v61路由；platform_core/prompts.py；platform_core/storage/source_repository.py|敏感字段不投影/写入与探测需真实回执|ConfigurationCenter|9可信入口导航并非9项原生CRUD|PRESENTATION_ONLY|NOT_STARTED|未实施/未提交|frontend/src/views/ConfigurationCenter.vue；本行Owner/API源码|
|视频切帧/畅联云数据/AI算法底座|static/modules/video-tasks.js；static/app.js云数据/演示渲染|GET/POST /api/v33/projects/{p}/video-tasks；GET /api/v33/projects/{p}/video-tasks/{t}；POST /api/v33/projects/{p}/video-tasks/{t}/stop；云数据/演示API本轮未核实，不宣称闭环|platform_core/video_tasks.py；platform_core/task_runtime/repository.py；app.py|取消后禁止继续发布/演示标识保留|无对应18视图|完整旧页受控链接|LEGACY_BRIDGE|NOT_STARTED|未实施/未提交|frontend/src/views/ProductWorkbench.vue；本行Owner/API源码|

## 证据与交接边界

- `frontend/src/main.ts`：18个按需import视图；`frontend/src/api/{algorithm-management,model-browse,materials,negative-pool,ai-tasks,training-reader,catalog,catalog-operation}.ts`提供实际URL、身份检查、分页与读写边界；这些并非独立SPA路由。
- `static/main.mjs:78-83` 开关只初始化既有试点；`static/modules/navigation-presentation.js`明确原路由/生命周期/项目状态留在main.mjs。`static/modules/navigation-stability.js`保护原页动作。
- 通用 `?page=...&project_id=...` 深链接未在上述导航源码核实，不能作为现成合同。`static/app.js:5740` 从 `mc_train_ui_state_v34`恢复允许页面并删除projectId；`static/modules/ui-state.js`同样不持久项目选择，Vue selection/report必须匹配当前project_id。旧页面名≠URL query自动消费。
- `static/modules/ai-review-route.js`有专门hash审核路由；不能推广成所有菜单通用链接。独立SPA legacy交接需实际allowlist消费与鉴权后项目核验，拒绝不匹配身份，不能借localStorage伪造项目。
- 第三方遵守 `docs/FRONTEND_THIRD_PARTY_REUSE_POLICY.md`：Annotorious3.9.5及原几何适配、Uppy6.0.5、Panzoom4.6.2、FloatingUI1.8.0、ECharts6.1.0保留原入口与销毁；不复制编辑内核/草稿库/轮询器/GT，离线vendor/license/map保留。
- 规则来源：AGENTS.md当前功能保护头部；docs/architecture/EXISTING_FEATURE_PRESERVATION.md；docs/FRONTEND_OWNER_MAP_V42_25.md；docs/TECH_FOUNDATION_P2_20261117.md。历史CI和现场证据不作为新SPA验收。优先准确SHA现有CI，推送后仅一次状态查询，不循环等待。

主实施者可在本表补充M1实际文件、定向构建/测试、准确SHA CI和逐动作证据后更新状态；整页旧入口可按其覆盖性质交付，不得标成原生功能完整。


## M1实施交接更新（源码已出现，验收由主实施者填写）

`frontend/src/app/{App.vue,Algorithms.vue,http.ts,navigation.ts,main.ts}` 已出现独立壳与原生卡片CRUD/详情版本第一批源码。算法大域仍记 IN_PROGRESS：高级动作、删除合同、训练与转换交付不能据此视为全域完成；本表基线NOT_STARTED行由主实施者按实际动作证据更新。尚未推送的实现不得记CI_PENDING。

新增 `static/modules/vue-app-handoff.js` 是本轮受控整页交接消费者，不是历史已有通用deep-link合同。格式为 `/?spa_handoff=1&project_id={p}&page={allowlistedPage}`，可附 `algorithm_id`、`version_id`、`action=train|conversion|delivery`。仅在旧系统canonical项目已加载且等于请求project_id时消费；算法/版本经原GET核验，导航后再次校验项目和页面，消费后清除query防刷新重放。不得通过localStorage冒充项目身份；壳链接构造与端到端验收仍由主实施者核实。
