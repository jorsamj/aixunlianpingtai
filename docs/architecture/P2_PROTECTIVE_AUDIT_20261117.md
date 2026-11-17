# P2 保护性审计与素材标注回归（2026-11-17）

## 基线与范围

已核对本地/远端均为 da23f50349801c9bcd414ae00a829abe07b831b5，开始时工作区干净。未部署、未合并 PR #18、未改生产或 VERSION。

实际 git diff 文件数为 49（以命令输出为准，不预设48）。以下为逐文件分类；新增工具/试点不等同新增正式业务替换。

| 文件 | 分类与影响 |
|---|---|
| `.github/workflows/remote-conversion-runtime.yml` | 前端构建/入口缓存；无页面布局改造 |
| `AGENTS.md` | 纯文档 |
| `app.py` | 后端 API 组合；七端点等价迁出/原 Repository 注入，无新 URL |
| `docs/CODEX_CURRENT_STATE.md` | 纯文档 |
| `docs/CODEX_READ_FIRST.md` | 纯文档 |
| `docs/FRONTEND_OWNER_MAP_V42_25.md` | 纯文档 |
| `docs/PROJECT_HANDOFF_CURRENT.md` | 纯文档 |
| `docs/TECH_FOUNDATION_P2_20261117.md` | 纯文档 |
| `docs/architecture/EXISTING_FEATURE_PRESERVATION.md` | 纯文档 |
| `docs/architecture/P2_DATA_OWNERS_AND_POSTGRESQL_PREPARATION_20261117.md` | 纯文档 |
| `docs/architecture/P2_HETEROGENEOUS_RUNTIME_BASELINE_20261117.md` | 纯文档 |
| `docs/architecture/P2_STORAGE_SOURCE_INVENTORY_20261117.json` | 纯文档 |
| `frontend/package.json` | 前端构建/入口缓存；无页面布局改造 |
| `frontend/src/main.ts` | 前端运行时；动态页面/生命周期，移除单路由壳 |
| `frontend/tests/lazy-pages.spec.ts` | 测试；名称/缓存预期或定向合同，原素材失败文件未改 |
| `frontend/tests/real-product-workbench.acceptance.mjs` | 测试；名称/缓存预期或定向合同，原素材失败文件未改 |
| `frontend/vite.config.ts` | 前端构建/入口缓存；无页面布局改造 |
| `platform_core/deployment/catalog_api.py` | 后端 API 组合；七端点等价迁出/原 Repository 注入，无新 URL |
| `static/app.js` | 原前端 Owner；授权名称、已注册 Owner 恢复、标注详情合并 |
| `static/index.html` | 前端构建/入口缓存；无页面布局改造 |
| `static/main.mjs` | 前端路由/菜单；取消 P1Z 替代，独立试点与原入口恢复 |
| `static/modules/algorithm-list-runtime.js` | 前端展示；仅算法库可见名称，卡片/操作保留 |
| `static/modules/catalog-preview-runtime.js` | 前端路由/菜单；取消 P1Z 替代，独立试点与原入口恢复 |
| `static/modules/product-workbench-runtime.js` | 前端路由/菜单；取消 P1Z 替代，独立试点与原入口恢复 |
| `tests/api/test_dynamic_conversion_catalog.py` | 测试；名称/缓存预期或定向合同，原素材失败文件未改 |
| `tests/browser/advanced-menu-integration.spec.mjs` | 测试；名称/缓存预期或定向合同，原素材失败文件未改 |
| `tests/browser/algorithm-list-performance.spec.mjs` | 测试；名称/缓存预期或定向合同，原素材失败文件未改 |
| `tests/browser/core-actions.spec.mjs` | 测试；名称/缓存预期或定向合同，原素材失败文件未改 |
| `tests/browser/external-algorithm-platform.spec.mjs` | 测试；名称/缓存预期或定向合同，原素材失败文件未改 |
| `tests/browser/external-algorithm-publish.spec.mjs` | 测试；名称/缓存预期或定向合同，原素材失败文件未改 |
| `tests/browser/model-and-conversion.spec.mjs` | 测试；名称/缓存预期或定向合同，原素材失败文件未改 |
| `tests/browser/navigation-stability.spec.mjs` | 测试；名称/缓存预期或定向合同，原素材失败文件未改 |
| `tests/browser/page-loading-performance.spec.mjs` | 测试；名称/缓存预期或定向合同，原素材失败文件未改 |
| `tests/browser/training-label-selector.spec.mjs` | 测试；名称/缓存预期或定向合同，原素材失败文件未改 |
| `tests/browser/training-material-picker-performance.spec.mjs` | 测试；名称/缓存预期或定向合同，原素材失败文件未改 |
| `tests/browser/training-quality-reports.spec.mjs` | 测试；名称/缓存预期或定向合同，原素材失败文件未改 |
| `tests/frontend/annotation-workbench.test.mjs` | 测试；名称/缓存预期或定向合同，原素材失败文件未改 |
| `tests/frontend/catalog-preview-runtime.test.mjs` | 测试；名称/缓存预期或定向合同，原素材失败文件未改 |
| `tests/frontend/lazy-advanced-evaluation-owner.test.mjs` | 测试；名称/缓存预期或定向合同，原素材失败文件未改 |
| `tests/frontend/lazy-changlian-data-browser-owner.test.mjs` | 测试；名称/缓存预期或定向合同，原素材失败文件未改 |
| `tests/frontend/lazy-legacy-material-owner.test.mjs` | 测试；名称/缓存预期或定向合同，原素材失败文件未改 |
| `tests/frontend/lazy-quality-detection-workbench-owner.test.mjs` | 测试；名称/缓存预期或定向合同，原素材失败文件未改 |
| `tests/frontend/modal-style-scope-13b.test.mjs` | 测试；名称/缓存预期或定向合同，原素材失败文件未改 |
| `tests/frontend/navigation-presentation-owner.test.mjs` | 测试；名称/缓存预期或定向合同，原素材失败文件未改 |
| `tests/frontend/product-workbench-runtime.test.mjs` | 测试；名称/缓存预期或定向合同，原素材失败文件未改 |
| `tests/frontend/training-resource-cards-extraction.test.mjs` | 测试；名称/缓存预期或定向合同，原素材失败文件未改 |
| `tests/frontend/vue-offline-chunks.test.mjs` | 测试；名称/缓存预期或定向合同，原素材失败文件未改 |
| `tools/package_vue_offline.py` | 新增离线交付工具；不新增业务功能 |
| `tools/verify_vue_offline.mjs` | 新增离线交付工具；不新增业务功能 |

## 已确认的素材回归证据

- 原 material-workflows.spec.mjs 在两基线间无差异，原断言保留。
- 本机只运行失败用例一次：1 passed，11.1 秒；不能据此宣布 CI 偶发或通过。
- 只读取失败 Job 133961019393 的日志及 shard-2 artifact 14317389608，未轮询/重跑 CI。
- Trace 中保存后的材料响应：annotation_version=2、annotated=true、box_count=1、annotation_origin=manual，完整 person 坐标 (28,22.4)-(91,72.8)。刷新后普通/processed 两次查询均返回该权威数据。因此不是已证实的 GT 丢失。
- 点击后 checkbox 的 __playwright_checked_=true，但对应卡片渲染签名仍为 materialShowBoxes=null，框节点0。故故障范围在开关状态传播/卡片重绘；具体事件或异步替换时序尚未确认，不能伪称根因已查明或已修复。
- 本地失败 Trace 保存在仓库外 delivery-evidence/20261117/protective-audit/trace.zip。没有修改业务代码或测试断言来掩盖红项。

## 菜单到实际业务合同

| 领域 | 入口→路由→页面/Owner→API | 结论与限制 |
|---|---|---|
| 算法库 | 算法库→算法列表→AlgorithmListRuntime 原卡片→v12/AlgorithmSqlStore | 卡片、信息、版本与操作源码保留；仅可见名称获授权修改，内部ID不变 |
| 素材库 | 数据集→原完整素材工作台→MaterialPaginationRuntime→v61/MaterialRepository | 筛选/分页/上传/批选/治理入口保留；标注框显示存在已确认CI红项，不能宣称完整回归 |
| 人工标注 | 素材卡片标注按钮→openAnnotation→原 Annotorious/annotation-workbench→原 annotation API/AnnotationRepository | 读取合并改动存在：保留原图URL、详情优先与ID核验；saveAnn/保存API/GT Repository未改。原保存回读与刷新响应已有真实证据，卡片显示未闭环 |
| 训练 | 原算法卡片/训练任务→原 TrainingDraft/Submit/Recovery→原 v62/Task Runtime | 不以 Vue 只读页替换正式菜单；创建/取消/恢复/执行Owner未改，现场执行未验证 |
| AI审核 | 自动标注及清洗→原任务/审核Owner→v60/CandidateStore/正式GT | 原入口保留；只读Vue为独立试点。未执行真实推理或生产GT写入 |
| 转换/发布/报告 | 原算法版本按钮/任务入口→原转换、发布、报告Owner→原v39/v42/v44与Repositories | Router提取保持请求/响应主体与原鉴权；转换/发布执行及状态机未改 |
| 配置/节点/评测 | 原高级菜单/质量中心→原页面Owner→原API/资源Owner | 菜单分组顺序保留，无页面重写；未逐项现场执行，不能将源码未变等同全部功能验收 |

默认菜单保持原分组顺序；工作台仅独立启用自身，快捷卡片进入原完整页。各Vue业务开关独立，试点不改绑同名正式菜单；原 ModelAssets 表格/MaterialLibrary 只读页是历史P1试点，不是本轮新增正式替代。P2没有修改业务SFC布局。没有发现删除原业务文件/按钮的差异；这不是全平台实际操作无缺失的保证。

## 后端和数据流

仅v39 catalog七条HTTP端点迁至现有platform_core/deployment/catalog_api.py工厂；原ModelArtifactRepository、compute_platform_catalog、资源读取/显式检测、revision/operation_id与错误映射复用。算法/素材/标注/候选/训练/发布Repository与数据库Schema未改。新增离线manifest/hash/打包工具不增加业务API。P2C/P2D仅文档，不迁移PostgreSQL、不安装SDK。

## 未完成与风险

素材卡片显示回归尚未完成根因定位与修复；禁止关闭该问题或降低现有断言。下一步应在原失败路径采集 change 事件归属、materialShowBoxes 状态及卡片重绘调用先后，或以受控响应顺序复现，确认前不改业务实现。既有CI红项保留，不能宣称验收通过。其他未实际执行的业务写入、真实硬件和生产部署均未验证。

本轮不因猜测而修改原业务逻辑。后续仍须完成这一阻断才能关闭保护性验收。


## 专项因果诊断补充（本轮未修改业务实现）

远端与本地已核对为767a7fcc，工作区起始干净。原测试未修改，单独运行1/1通过。对同一原用例附加临时日志，并只在刷新后控制bootstrap为503，诊断仍1/1通过：change捕获→toggle执行→state=true→pagedMaterialCards→base-render→旧签名null变true→节点1变2→框0变1。因此503本身不足以解释CI失败，不能把它当作根因。

CI历史Trace已经证明权威数据正确、checkbox=true、旧签名null，但没有内部调用日志，不能反推toggle是否执行。已在原Frontend Runtime的失败分片中追加精确条件：只有该原用例失败并留下trace时，运行同一用例的临时因果探针，保留原断言；不重跑其他成功用例，不新建工作流、不轮询。探针仅变换测试浏览器收到的JS以记录事件、真实state、渲染函数、节点身份/签名/框数及请求顺序；原生产文件和原测试字节不变，临时文件finally清理。

尚未取得失败路径的函数级证据，故本轮未提交任何猜测性业务修复，问题保持开放；不得宣称已恢复或验收通过。下一次检查准确SHA的失败Job因果输出后才能确定最小修复点。
