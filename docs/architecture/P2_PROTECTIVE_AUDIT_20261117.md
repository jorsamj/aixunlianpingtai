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


## 919cd393 CI 后续诊断核验（2026-11-17）

- Run 44065564960 已完成，准确 head_sha 为 919cd39355add275c6d8ffaaaf795db437a74c0f。browser-navigation (2) Job 133978239864 为 success，日志明确列出原 manual annotation 用例并汇总 130 passed (4.7m)。条件诊断步骤 skipped，未产生 OVERLAY 日志；不能据此宣布原回归修复。
- shard-2 制品 14320013078 已上传（ai-annotation-ui-919cd39355add275c6d8ffaaaf795db437a74c0f-shard-2）。本次没有诊断执行产物，不能把成功上传步骤描述为已保留函数级失败证据。历史 da23f503 失败 Trace 继续有效。
- frontend Job 独立失败（用户已定位 tests/service-nodes.spec.ts）；本轮只记录，不修改服务节点页面，不扩大日志分析或测试。
- 发现并补齐诊断工具缺陷：旧 replace 静默失配；旧输出目录可能在二次 Playwright 执行时清除原失败 Trace。现 15 处合同/注入匹配均要求恰好一次，失配或重复立即 OVERLAY_INJECTION_FAILED；响应路由未命中也由 afterEach 报错。只变换隔离浏览器响应，不写业务 JS。
- 新增签名输入、签名比较（计算值/旧值）、节点 ID/替换前后、materialMedia raw 参数、分页调用/捕获原函数/抑制状态、素材请求与响应、列表应用前后、数据集重绘、change 冒泡和测试结束日志。checkbox 选择器 .material-box-toggle input 与原 label/input/onchange 合同逐项匹配。
- 诊断改用 test-results/material-overlay-diagnostic 独立输出、强制保留本次诊断 Trace、overlay.jsonl 和 integrity.json；既有工作流上传该目录，原失败 Trace 不再被同目录重跑清除。临时测试 finally 删除，并校验原测试/app.js/分页 JS SHA256；任何字节变化报错。当前临时文件不存在。
- 本地仅执行 --verify-only（15 处匹配、两份注入 JS 语法检查）、4 项零匹配/重复匹配拒绝检查和 git diff --check；未重复运行已通过原浏览器用例。原测试和两份业务 JS 对 919cd393 零差异。
- **根因仍未证实，未修改业务链路，未完成恢复验收。** 本次成功运行没有最后成功函数/首个异常函数证据。需要保留原失败证据，在同一原始用例下一次真实失败时采集函数级链路；不靠增加随机重复次数定位，也不因成功运行关闭问题。开/关/再开及分页重绘完整闭环仍未验收。未改 GT/API/数据库/Worker/分页业务规则，未部署或合并 PR。


## 已证实素材摘要覆盖缺陷最小修复（2026-11-17）

用户已授权修复 apply(s) 的素材赋值。修复前 `state.images=s.images||[]` 会将同项目 core_only 且不含 images 的摘要解释为清空素材；定向 B 实验已证明素材先应用、摘要后应用时原人工标注断言失败。现复用 sameProject，以 Object.hasOwn 区分缺字段与显式空数组：同项目缺字段保留原列表，显式 images=[] 仍清空；跨项目缺字段和初次加载缺字段为空，不保留旧项目素材。只改这一赋值及局部注释，不改 GT/保存/分页 API/Repository/Worker/数据库/版本号/入口。

验证：新增 bootstrap-material-ownership.test.mjs 直接执行原 apply 函数，修复前4/5、修复后5/5（缺字段保留、显式空、跨项目、初次加载、显式列表更新）。历史点击屏障 B 修复前原 toHaveCount(1) 失败，修复后 A/B 各一次1/1通过；两组 natural503=true、complete=true，交付顺序分别 bootstrap→materials、materials→bootstrap。B同次验证on/off/on及原renderer局部重绘，框数量与状态一致；两次读取正式合成GT响应完全相同。另直接运行未经注入的原 material-workflows 用例1/1通过。原测试文件及分页JS SHA256保持不变；诊断运行期间 app.js 哈希前后相同，临时文件已删除。

命令：`node --test tests/frontend/bootstrap-material-ownership.test.mjs`；`node tools/diagnose_material_overlay.mjs --scenario=A/B`（独立执行各一次，输出根目录另设以保护旧证据，B启用OVERLAY_VALIDATE_TOGGLES=1）；`npx playwright test tests/browser/material-workflows.spec.mjs -g "manual annotation saves, survives reload, and updates the thumbnail"`。两个诊断工具的现有未提交修改仍保留，不混入此修复提交；CI原工作流及原用例不改。不做全仓测试/新工作流/生产操作。离线前端/Vue无变更，不重复构建。

证据：本机 delivery-evidence/20261117/material-response-barrier-af659bd 保留修复前A/B日志和Trace；material-overlay-minimal-fix 保留修复后A/B overlay.jsonl、integrity.json、Trace、原用例日志和诊断工具未提交diff。响应时间差受隔离浏览器交付开销影响，两组合成项目ID不同；不将此对照描述为历史时序逐字节重放。已修复这一具体覆盖缺陷，但历史CI末尾仍留旧卡片等表现不等同于B清空卡片，不能宣称历史所有症状已解释。准确提交CI推送后只查一次，待异步结果；未生产验收或部署。
