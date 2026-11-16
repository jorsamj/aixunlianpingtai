# 产品化 P0/P1：Vue 厂商/芯片只读预览

## 基线、决策和范围

2026-11-16 用户最新总指令授权 P0/P1 开发、测试、在唯一 `feature/external-algorithm-publishing` 提交推送。起点 `1fa299c9cb0a3adafe58a2e377c791b296ff6a87`，干净独立检出，VERSION.txt 实际为 **42.24.592**，本批不改。旧文档“不改 Vue / VERSION 必须 42.24.0”仅为历史阶段限制；新方向为 Vue3/TS/Vite/Router/Pinia、FastAPI 模块化单体及渐进 PostgreSQL。原业务/数据安全合同继续有效。

本批只迁入厂商/芯片**读取视图**，不是替换完整管理页。Element Plus 单一 UI 组件体系，按用到的组件引入；Annotorious/ECharts/Uppy、GT、Task/Worker/Agent/Supervisor 均不迁移。没有生产授权。

## 开启、共存和回退

1. Node **22+**，项目根执行 `npm ci --prefix frontend`、`npm run build --prefix frontend`。
2. 构建输出为 `static/vue-catalog/catalog-preview.js` 和 `.css`，所有依赖打包本地，无 CDN。目录不入 Git，CI 配置上传离线制品，必须核对准确SHA的实际Artifacts条目；发布打包时必须带上它。未构建时错误页允许返回原管理。
3. 正常登录原系统，URL 加 `?vue_catalog_preview=1`，进入「部署资源」的原厂商/芯片区域，点击「只读预览」。默认无预览按钮，不加载 Vue 制品。
4. 「返回完整管理」走原 `window.setPage('部署资源')`；保留原新增/编辑/停用/删除/检测/转换功能。回退只需移除 query 开关并刷新，不涉及数据回退。

NavigationStability 仍是外层唯一导航；Vue Router 仅使用 memory history，不夺取旧 hash。PageRequestScope/PollRegistry 和 session 沿用，预览不增加轮询或会话计时器。桥接层只将原 `api()` 和 `withRequestDeadline` 注入 Vue，不建立 fetch/登录客户端。Pinia 只存筛选/分页、读取结果及视图状态，不持久化业务真值。离开、重复进入、项目变化、未完成 import/请求均受代数和 abort 保护，旧 JS/Vue 不同时操作同一 DOM。

## 本批保全矩阵

| 功能 | 页面 Owner | API / 后端 Owner | 规则与迁移范围 | 保全验证 |
|---|---|---|---|---|
| 原完整字典 | ConversionCatalogRuntime | 原 catalog CRUD/ModelArtifactRepository | 仅增加 opt-in 导航按钮，写入/检测不迁移 | 原 editor Node 回归、浏览器返回及新增按钮仍在 |
| 预览列表 | CatalogPreview.vue / useCatalogView | GET `/api/v39/deploy/catalog/records` | 原 query/vendor/enabled/sort/page/page_size；最多10条/页 | Chrome 分页、查询、空态、状态不伪造 |
| 预览详情 | 同一 Vue 页面及详情抽屉 | GET `.../records/{entity}/{identity}` | 稳定 ID、引用未核验、已有 SDK 证据 | Chrome 详情及未知证据 |
| 已登录身份 | 原 auth-session.js | 原 `/api/auth/session` | 不增加认证/续期/Token 存储 | Chrome 使用原会话脚本/原 api 读取 |
| 退出/重入 | NavigationStability + 原 request scope | 同一原 API | abort、拒绝迟到结果；不重复监听 | Node 桥接及 Chrome 请求取消/重入 |

API 新增兼容可选参数 `observe_only=false`。试点始终传 true：chips 列表及详情只调用 `v39_list_deploy_resources(detect_missing=False)`，避免原 GET 的默认 SDK 缺失检测。旧调用省略参数保持原行为；未改变 URL、鉴权、Repository、响应或写入合同。注意这是“不执行业务写/检测”的读取模式，不承诺仓储初始化绝无文件/schema 行为；本批测试仅在隔离临时目录运行。

## 20 业务域索引（按最新总指令编号）

“已有实现待验证”不等于生产验收，隐藏入口不是废弃证据。本批仅对 B14 字典视图实施，其余按索引保全，未逐域重验。

| ID / 业务 | 当前状态与真实 Owner | 已有需求索引 |
|---|---|---|
| B01 登录/项目/模式 | 已有实现待验证；SignedSessionManager、本地/外部登录、原项目 JSON；完整 RBAC/租户仅规划 | CODEX_CURRENT_STATE.md；登录单元/浏览器测试 |
| B02 算法/版本 | 已有实现待验证；AlgorithmListRuntime → AlgorithmSqlStore | FRONTEND_OWNER_MAP_V42_25.md；test_algorithm_version_rollback.py |
| B03 上传/导入 | 已有实现待验证；UploadTaskCenter/ZipImportRuntime → Material/Task/ZipMultipart | MATERIAL_WORKBENCH_P0_2026_11_04.md；多来源存储设计 |
| B04 素材治理 | 已有实现待验证；MaterialPagination/Batch/SmartAudit → MaterialRepository/正式GT | TRAINING_MATERIAL_LIFECYCLE_GOVERNANCE_2026_10_21.md |
| B05 标签/REMAP | 已有实现待验证；原标签/映射 Owner → AnnotationRepository/MaterialBatch | test_durable_label_remap.py；标签合同专项 |
| B06 人工GT | 已有实现待验证；AnnotationWorkbench/Annotorious → AnnotationRepository | ANNOTORIOUS_ANNOTATION_INTEGRATION_2026_10_21.md |
| B07 AI候选审核 | 已有实现待验证；原AI工作台/Provider → CandidateStore → 正式GT | AI_REVIEW_IMMERSIVE_UI_2026_11_10.md |
| B08 负样本池 | 已有实现待验证；NegativePoolRuntime → NegativePool（素材同库） | MATERIAL_WORKBENCH_P0_2026_11_04.md；首次纯负样本禁止合同 |
| B09 选材冻结 | 已有实现待验证；Picker/Draft/Summary → selection-reference/Prepare；生产20k链延期 | TRAIN_FROZEN_SELECTION_CONFIRM_P0_2026_11_10.md |
| B10 训练配置迭代 | 已有实现待验证；Submit/Label/Draft → 原训练Handler/标签/划分 | TRAINING_CREATE_FOUR_MODES_UI_2026_10_10.md |
| B11 GPU/调度 | 部分实现；原allocator/GPU reservation；完整硬预算/多执行槽未完成 | DISTRIBUTED_WORKER_CLUSTER_ARCHITECTURE_2026_10_10.md |
| B12 任务执行恢复 | 部分实现；TaskRepository/attempt/lease/fencing/原Runner；远程可信恢复未完 | NODE_CONTROL_PLANE_V42_25.md；P0-01C专项 |
| B13 报告评测 | 已有实现待验证；reports/原评测 → 冻结Snapshot/版本/metrics | ALGORITHM_REPORT_UI_PERFORMANCE_MODAL_SCROLL_2026_11_12.md |
| B14 资产转换 | 部分实现；ModelArtifactRepository/原Conversion Runner；厂商硬件依环境 | CONVERSION_UI_UX_2026_11_12.md；本批只读字典 |
| B15 数值硬件 | 部分实现；numeric_consistency/真实Runtime；缺硬件必须阻断 | SCENARIO_MODEL_EVALUATION_UI_GOVERNANCE_2026_10_22.md |
| B16 部署发布回退 | 部分实现；原部署Task/版本回退；设备回退不能凭版本指针推断 | test_algorithm_version_rollback.py；部署测试专项 |
| B17 外部畅联 | 已有实现待验证；ExternalAlgorithmPublishService/ExternalPublicationRepository | EXTERNAL_PUBLISH_DIALOG_UX_2026_11_05.md |
| B18 存储缓存 | 已有实现待验证；StorageManager/Provider/SourceRepo/原节点缓存 | STORAGE_CACHE_AND_OBJECT_IMMUTABILITY.md |
| B19 Worker/Agent | 部分实现；原ServiceNode/Executor/Worker；部分远程Runner待开发 | NODE_CONTROL_PLANE_V42_25.md；分布式差异复核 |
| B20 Supervisor | 部分实现、生产NO-GO；原root journal/受限profile/CI-only身份登记 | P0_01C_2D2D2C03_STOP_RECOVERY_DEPLOY_GATE_20261116.md |

## 后续模块化与数据库顺序（本批不实施）

FastAPI：先以字典只读/已有资源展示等边界清楚的用例收敛 Router/Schema；复用原 ModelArtifactRepository 和 catalog 规则，再按真实 API 用例移出编排。避免 backend-v2 和无职责转发层。Task、GT最终提交、训练Handler、GPU reservation、Agent确认、Supervisor 均需独立专项，不随展示迁移拆分。

PostgreSQL：先逐域列 writer/reader、修订、约束、引用、JSON迁移及文件确认协议，再一致性副本/只读影子比对/受控单写切换/对账恢复/旧库退役。优先评估低耦合中央配置及审计域；素材/GT/使用记录的 SQLite ATTACH、Task/lease/assignment/GPU 同事务、版本/资产/发布确认必须联合设计。节点 journal、metrics、immutable manifests、缓存不强制迁入PG；大文件仍为NAS/OSS/S3。无Redis/MQ默认依赖，不长期双写。

## 验证边界

本批仅构建、桥接/原字典Node测试、相关字典API测试和两个Chrome关键场景。Chrome使用原session/API/Navigation/RequestScope/PollRegistry/完整字典模块及原CSS，但HTTP为合成夹具；不代表真实用户登录、生产字典、GPU、SDK、完整系统现场或Safari验收。截图位于 `test-results/vue-catalog/catalog-1366.png`、`catalog-768.png`，明确属于隔离夹具。

CI复用原 Frontend Runtime 工作流，增加试点构建/两条Chrome及离线制品，不关闭旧门禁。精确SHA状态以GitHub为准，不借基线23/23冒充本批通过。

本地实测：Node 22，`vue-tsc --noEmit && vite build`通过；JS 675.35 kB / gzip 190.49 kB，CSS 95.02 kB / gzip 13.60 kB，仅主动进入时加载。相关5个Node文件 **35/35**；新增无SDK检测与原CRUD定向 **2/2**；字典API整文件 **33 passed / 1 failed**，唯一旧多进程SDK测试的spawn导入命中本机 `D:/python/Lib/site-packages/tests`，报 `No module named tests.api`，未改断言/跳过或修业务；留待干净CI独立核验。Chrome **2/2**，覆盖原会话、分页/筛选/详情、未知态、错误重试、离页取消、重入无重复、返回原管理、全部API为GET，以及1366/768无横向溢出。初轮库模式保留 `process.env.NODE_ENV` 导致真实Chrome导入失败，已通过显式生产常量修复后重新构建/通过；后续中文locale与占位修正也已复验。现有FastAPI on_event弃用警告仍在，本批不扩展生命周期改造。

官方选型参考：[Element Plus按需使用](https://element-plus.org/en-US/guide/quickstart.html)、[Vite静态构建](https://vite.dev/guide/build.html)。根package/lock未修改，新增工程有独立精确版本lock，不安装或修改生产环境。

下一批建议只审核本试点的真实部署形态、视觉和API证据；通过后选一个字典交互进行Owner交接，不自动扩展训练/GT/数据库迁移。

本批后续精准收尾、状态语义修正、真实入口隔离冒烟和离线包含方法见 [收尾记录](PRODUCTIZATION_P0_P1_CLOSEOUT_20261116.md)。历史首批验证结果保留，新结果以收尾记录为准。
