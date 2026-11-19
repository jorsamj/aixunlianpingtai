# AI 开发接续入口

项目：畅联云算法训练平台；仓库 `jorsamj/aixunlianpingtai`；唯一分支 `feature/external-algorithm-publishing`。

## 当前阶段与准确提交

当前为 M3-C 原生训练报告与独立评测。M3-B 基线 `f8377d2c92a911717a9a140024b27e87b2d570e7` 的只读列表和详情已通过独立代码审计，40 项 CI 中 39 成功，Windows Node Agent Executor 失败，见文末。独立复核本轮交付前，以 `git rev-parse HEAD` 和远端分支核对最终提交，按同一 SHA 查看 Actions。交付消息记录本轮准确 SHA 和 CI 快照。

- M2 起点（已核对远端）：`4c7a6d1f31c275311156fb0ab1a7a5cd9d47d7f8`，保留 M1 的数字缓存键修复与未知写入刷新保护。
- M2-A：`280ed4cfb21f80e0980c03ace18aa70877a41706`，原 AlgorithmSqlStore 新增 opt-in 全局算法库只读投影及正式版本备注写入的轻量回执。
- M2-B/C 实现：`c83c114230873f57ae9d0f9a348ffc17f9cc4307`，完整 Vue 列表/版本 UI、备注编辑、受控操作入口及定向回归；最后仅补本入口、矩阵、功能保护与当前 AGENTS 阶段说明。
- M1 原 `65ae81372555786b78284a1bc62608703c1c40d6` 的 GPT 审计结果是50工作流48成功、2失败（Frontend Runtime Stabilization 44344576655、Material Upload Chunking 44344576624），不是验收通过；已在4c7a6d1f修复。该修复 SHA 的最终 CI 本轮未查询，不借旧结果验收新代码。

## 架构与唯一 Owner

业务目标是素材/GT、算法训练评测、转换交付、外部平台与算力管理。当前 FastAPI 模块化单体 + SQLite，各既有 Repository 拥有领域数据；ArtifactStore保存不可变证据；Scheduler/Worker、中央Assignment、Agent Execution Lease、Supervisor负责执行。新Vue只读写原同源Session/API，不取得执行权。

最终目标为完整独立 Vue 3 / TS / Vite / Router / Pinia / Element Plus，逐步退役旧前端；当前同一frontend工程保留库构建并新增独立 `/app/#/projects/{projectId}/algorithms`，原 `/` 仍可用。新应用不加载app.js、不调用window.setPage、不移入旧DOM表单。其他工作台暂以整页交给唯一原Owner，不能宣称原生迁移完成。

## M2 已完成及接口

- 算法卡片：名称/ID、来源、行业类型、说明、当前版本、版本数、训练状态/可训练性、成功训练次数、当前mAP50、更新时间、外部产品/品目/状态；点击展开/收起不重读列表，选中项不在筛选页时仍保留独立版本详情区。
- 搜索名称/ID；来源、行业、类型、训练状态、仅可训练、多级官方品目叶子选择；组合、标签移除、重置、分页；URL为当前条件，sessionStorage按项目保存重入条件，不跨项目混用。
- 综合/最近更新/训练次数/mAP50全局排序：新 `library_view=true&asset_view=true&summary_only=true` 的v12 GET在SQL过滤排序后LIMIT/OFFSET，新App显式请求10、服务端最大50；HTTP未带page_size仍保留v12原20默认。旧asset_view的status及原默认响应行为不改，新训练语义使用training_state，浏览器不拉全算法或全历史。
- 统计从 `_training_history_context` 一次读取既有历史上下文，`_successful_training_counts`保持成功/证据/去重口径，Durable状态覆盖旧job状态；综合用旧activeJob集合，训练筛选沿原provider集合。它们存在不同的原状态集合，未擅自合并。没有新统计存储/任务权威。
- 当前指标按精确current_version_id关联，不把最新创建版本当当前；保留原指标字段优先序、比例/百分数转换，缺失/布尔/非数值不伪造0，真实0保留。
- 普通详情复用原basic_only，外部主数据只读；补充产品/品目/分析ID、同步时间/摘要等只读字段；写后GET核验、局部更新。
- 历史版本分页、当前指针、训练任务关联、配置/指标/血缘与登记产物详情；版本只可编辑原API允许的remark，版本号不变。PUT新增asset_view=true只返回确认，原默认响应不改，再用身份验证的GET核对；备注返回业务原文，不把脱敏显示值写回。
- 新建/编辑/版本备注共用原按项目sessionStorage待核格式，版本操作增versionId与remark；写前记录，确认拒绝或GET一致才清除。未知结果跨刷新/重入阻止重复写；没有创建回执ID则人工核对ID后GET，不按名字猜测。仅覆盖本标签页会话，不提供跨设备/跨会话后端幂等。
- 原Owner整页动作：训练、算法/版本报告、已有独立评测、溯源、转换、授权下载、交付、算法/版本删除、回退。先GET核验项目/算法/版本，再进入原确认；回退仍由原Owner提交expected_current_version_id并执行引用保护。外部算法删除/主数据编辑禁用；版本退役限制准确保留EXTERNAL + CHANG_LIAN，未扩大到其他提供方。交付待清理状态拦截，下载标记仅代表原stored_path记录，真实文件由下载API核验。
- 外部同步去原“平台对接”页，不自动触发同步。旧页保留“返回新版算法库”，刷新不重放交接动作。旧canonical项目限制不变，不伪造项目切换。

## 必要验证与 CI

本地 Node24.21.0 / Python3.12 / Chrome：

- `python -m pytest tests/api/test_model_asset_views.py -q`：初始5项通过；新增备注用例后仅`-k library`3项通过、3项未选。后续只对补充只读字段/原文备注分别补测受影响项，均通过。覆盖25个算法全局分页/排序、当前与较新版本区分、品目/状态组合、一次历史读取、旧asset响应兼容、真实备注PUT/GET与版本身份不变；不调用全算法hydration。
- `node --test tests/frontend/vue-app-handoff.test.mjs`：23/23，覆盖真实函数分发、项目/版本身份、外部限制、回退目标、清理状态、下载及缺Owner失败。未实际删除训练/模型或调用外部发布。
- `node node_modules/@playwright/test/cli.js test tests/app-shell.spec.ts --grep "independent cards|unknown algorithm writes|library filters"`（frontend目录）：M1 CRUD及未知恢复2项通过；M2单项修正ElementPlus选中标签的定位后通过。最终M2单项5.0秒含启动，含无列表重读、精确参数、备注核验、刷新重置与外部禁用。未全量跑Playwright。
- `node frontend/node_modules/vue-tsc/bin/vue-tsc.js --noEmit -p frontend/tsconfig.json`；`npm run build --prefix frontend`（双构建）及后续受影响SPA构建：通过；旧30、新6资源闭包。原Node缓存键失败用例2/2通过；语法、Python编译与`git diff --check`通过。构建大chunk警告仍存在，不冒称首屏性能验收。
- 新最终SHA只查询一次现有Actions；未完成时CI_PENDING，不新增Workflow/Job、不手动重跑、不持续等待。正式官方制品下载、现场离线安装、生产/GPU及真实删除/回退/外部交付端到端本轮未验。

## 未完成、实际风险与下一步

|项目|影响/优先级|下一步与确认边界|
|---|---|---|
|训练/评测/转换/交付等仍LEGACY_BRIDGE|尚非全平台Vue原生，P1|GPT复核M2后建议M3完整训练创建/标签选材/全参数/准备取消/报告；先按矩阵定位，不重审全仓，不缩减模式或默认值|
|精确历史统计仍有历史规模成本|每请求一次既有历史上下文，不逐卡扫描；SQL卡片/版本输出有界，但全历史聚合不是固定成本，P2|若真实数据证明慢，后续专项设计正式Owner上的增量投影，不能用窗口估计或新计数真相替代|
|旧canonical项目限制|非canonical旧项目交接会明确拒绝，P2|保留原政策，改变项目策略先确认|
|初始共享JS约1.08MB未压缩|首次下载成本，尚无生产P95，P2|后续有实测再按需拆包，不本轮扩大性能架构|
|待核保护只在当前标签页会话内|无ID/记录改变时须人工核对|保持明确提示，不自动重发、不过期解除保护；后端幂等另行批准|

算法库列表/版本页面开发FUNCTIONAL_COMPLETE、验收CI_PENDING；其他业务域NOT_STARTED或原试点覆盖，均不冒称ACCEPTED。原 `/` 可回退，新SPA尚不接管默认入口。保留三份原未提交Payload设计、VERSION42.24.592及所有训练/GT/lease/attempt/fencing/CAS/不可变Payload/执行锚点/删除/发布安全；不操作A800/4070/生产，不强推/合并/Release，不自动开始M3。

实际协作：gpt-6.1-sol有界核对旧动作并实现受控交接、只读复核SQL；gpt-6.2-sol实现指定Vue/API类型文件。主模型决定语义/事务边界，独立审查实际Diff，修正外部限制、当前版本/只读详情/备注原文及待核行为，统一验证、Git和交付。

## 按需必读

- [功能/API迁移矩阵与历史阶段](VUE_M0_FUNCTION_API_MATRIX_20261118.md)
- [功能保留与差异](EXISTING_FEATURE_PRESERVATION.md)
- [整体技术架构/历史实施](../TECH_FOUNDATION_P2_20261117.md)
- [原前端Owner地图](../FRONTEND_OWNER_MAP_V42_25.md)
- [专业组件复用合同](../FRONTEND_THIRD_PARTY_REUSE_POLICY.md)
- [Payload协议与边界](P2B_4A_2B_CONTINUOUS_DELIVERY_20261118.md)

## M2 CI收尾 / M3-A开始（2026-11-19）

起点e51c30c9：GPT核查50工作流48成功2失败。A修复4个资源测试文件的历史缓存硬编码，改为实际index版本的数字格式、三资源一致性与顺序检查（定向17通过）；首次预加载修正bootstrap资源/推荐被误判实时缓存的新鲜度，指定hard refresh浏览器1通过（16.5秒含服务启动），hydration合同15通过。后者缓存复用用例先执行真实prewarm再断言后续零请求，未削弱预加载。无timeout/默认参数变更。A提交后立即开始M3-A，不等CI，未宣称CI成功。三份原设计及VERSION保留。

## M3-A 原生训练创建（2026-11-19 当前）

阶段SHA：A `3e8e229185c0cc802f1216e24aab243074dec14a`（缓存合同/首次预加载）与 `d635fd1f7cdbea3e741b6d7df10dc18bb24d65f2`（严格点分数字断言）均已先推送；然后实施B，代码 `07b98d236f8dc3b45856c945938e72f98d64e8d8`。最后仅更新接续文档/矩阵/保护台账与AGENTS阶段说明，最终HEAD为包含这些文档的提交，完整SHA和一次CI快照见交付消息。A/B的CI尚未本轮终验，不能继承其他SHA成功。

入口 `/app/#/projects/{projectId}/training/create?algorithm={id}`；可从原生算法卡片“训练”或“训练任务”桥接页的原生创建入口进入。不加载app.js/main.mjs、不移入旧表单DOM。新增src/app/TrainingCreate.vue、TrainingMaterials.vue、training-api.ts及类型声明；原views/TrainingCreate.vue和TrainingMaterialPicker.vue保留服务旧试点，不冒称它们已原生化。Task列表/执行/恢复/完整报告仍LEGACY_BRIDGE。

- 普通首次/当前版本迭代创建、分页搜索算法；四种训练模式、母模型、设备/资源/profile、优先级、精度、Epochs/imgsz/Batch/Workers、学习率与优化器、增强/早停/评测等全部原参数、自动转换选项和任务级robustness配置。版本与模型归属由正式API决定，迭代仍锁定当前版本/引擎编辑。
- 将旧baseCfg428原样提取为trainingConfigurationDefaults纯函数，旧表单通过原PlatformCore命名空间调用相同工厂；曾用git旧工厂与新返回对象严格比较，完全相同。复用既有createTrainingDraft、trainingInheritedDefaults、trainingModePreset、buildTrainingStartPayload、trainingDraftToRequest，未创造新训练默认值。缓存仅数字版本42.25.628，VERSION42.24.592不改。
- 素材v62服务端40条分页，图片lazy、标签/标注状态过滤，跨页Set选择，按项目+算法session草稿保存IDs/冻结引用/资源配置。显式选择沿API上限2000，冻结Train走selection-reference，22,015张例中只传引用；请求ID同范围重试保留，成员查询每批≤100；Test与训练范围重叠阻断。
- 选择确认与创建前复核五项revision；只取正式selection-summary正样本标签，未知GT/候选框不变成训练标签。Train/Val/Test原默认随机20/20及独立Test规则保持，切换模式复用canonical归一化；历史复用、可信固定Test基准和输入冻结交给原服务。
- 正式素材诊断、服务端RESOLVE_SELECTION+二次人工确认排除，复用removeResolvedTrainingMaterials保留原Train/Test范围、排除IDs和证据修订，不改素材库/GT；泄漏不以快捷排除掩盖。显式负样本预览/人工proof确认；冻结范围不误用仅支持显式IDs的负样本计划，必须明确同意后台核验；显式范围仍先检查硬GT/重复冲突。
- 正式POST `/api/v12/projects/{p}/train/start`，先生成并保存train_随机身份，最终预览后草稿变化使确认失效；正式准入后再写。回执 `training-create-pending:{p}` 存储失败不POST；明确拒绝清除，IN_PROGRESS/5xx/丢包/非法回执保留，刷新后只GET `/api/v62/projects/{p}/tasks/{t}?reader_view=true` 核验项目/任务/算法身份，不自动重发。后端TaskRepository/Worker/调度/freeze/Payload均未改。
- 成功后保留正式task_id并提供原训练任务入口。算法/项目切换会重建页面及取消读请求，提交回执按原项目保留。

验证命令与结果（本机隔离或HTTP夹具，不是生产训练）：

1. A四个资源合同测试文件：17通过；hydration合同15通过；指定 `tests/browser/training-create-first-open.spec.mjs --grep "hard refresh algorithm list prewarms"` 1通过，提取默认工厂后补测1通过（11.6秒含启动）。没有提高timeout或修改默认参数。
2. `node --test tests/frontend/native-training-create.test.mjs`：7通过，覆盖正式body/身份、刷新未知GET恢复、资源/草稿变化、22,015引用、存储失败、硬GT冲突、权限拒绝/IN_PROGRESS、审计排除及过期证据。
3. 原纯草稿/提交合同85通过；复用的training-material-summary-runtime仅排除/跨页相关5通过。未跑全部Node测试。
4. `python -m pytest tests/api/test_training_material_selection_summary_api.py -q -k "opt_in_selection_validation or summary_only_avoids or accepts_final_training_submit_payload or resolves_current_scope" --disable-warnings`：4通过，10未选；临时FastAPI/SQLite，不是真实GPU任务。
5. 原生Chrome `frontend/tests/native-training.spec.ts`：1通过（4.4秒含启动），跨两页选材、正式标签、完整默认body、最终确认、正式Task回执；断言不加载旧app.js/main.mjs。首次仅因ElementPlus隐藏input定位失败，改点其实际可见label并保留checked断言，未放宽等待。
6. Vue类型、双Vite构建（旧30、新8资源闭包）、JS语法、git diff --check通过。共享大chunk警告仍在，未声称首屏性能专项完成。没有全仓pytest/完整Playwright，也没有真实GPU训练、生产数据、A800或4070操作。

验收边界：普通原生创建/选择/配置/提交开发完成，CI_PENDING。固定基准、负样本和robustness手工子集已接入原合同，但未逐组合进行浏览器端到端穷举；等待CI和GPT复核。已确认评测决策带来源身份的继续训练/反馈补数入口仍在原评测Owner，不能把它们改造成无来源普通创建；全局robustness默认策略编辑仍保留在原完整训练表单，未新建全局配置Owner。本轮未迁移任务列表/执行恢复/完整报告，也未验证真实Worker训练结果。

下一阶段：先按最终SHA处理已知CI失败（若有）；GPT审计通过后M3-B只做训练任务列表、队列/状态/取消/日志与原Task读取合同，不重写执行器。M3-C再处理完整报告和评测决策入口。保留三份原未提交设计、唯一分支、VERSION、全部冻结/GT/lease/attempt/fencing安全，不自动扩展。

实际分工：gpt-6.1-sol做受影响测试、原生UI与素材控件；gpt-6.2-sol做有界API合同定位和适配器；主模型独立检查实际Diff、修正身份/缓存/回执/准入/快照与默认值边界、测试并统一Git。无代理推送/部署。

Task reader_view若因证据缺失/大小限制不能提供算法身份，原生回查保留待核状态，不把普通HTTP成功当作身份确认，也不自动重发；需在原任务工作台核对证据后专项处理。

## M3-A 冻结请求审计修复

基线 37ea27a95bb3319512edb7198824592d0d990ce0。TrainingMaterials 使用 getRandomValues、UUIDv4 版本位及 RFC4122 variant 位，保留同范围失败重试身份。明确清除选择后可开始下一次冻结。隔离 FastAPI 正式冻结与同请求回执复用、selection-summary 验证 1 项通过。Chrome 夹具验证标准 UUID、失败重试、刷新恢复和 22,015 张训练仅提交引用，1 项通过。训练参数、GT、角色隔离及未知任务 GET 合同沿已有实现。CI 异步验收。

## M3-B 原生训练任务

开始基线为 `37ea27a95bb3319512edb7198824592d0d990ce0`。M3-A 冻结整改单独推送 `f71aae79260052fc26cdf399cea49416076934a9`，随后交付 M3-B。最终精确 SHA 和一次 GitHub Actions 快照见交付消息，可用 `git rev-parse HEAD` 核对包含本段的提交。

- `/app/#/projects/{projectId}/training/tasks` 接管新 SPA 的“训练任务”，创建成功可直接打开相应任务。通过 URL 保存搜索、持久状态、类型、当前游标与详情。以 v62 Task reader_view 每页最多 20 条查询，详情不重读列表。TaskRepository 提供有效状态和进度，100% 不推断终态。准备与正式任务通过原有任务身份关联，项目/类型校验在现有只读路由内执行。
- 详情显示阶段、起止时间、资源键、等待原因、Worker、执行记录和失败信息。读取不可变 Payload 由原 SHA256 校验读取器完成，继续执行列表 32 KiB 与详情 512 KiB 上限。训练日志复用原日志 GET，只显示有界文本。准备任务经关联入口进入正式训练日志。列表、详情及日志手动刷新，复用读取取消机制，无额外轮询器。
- 停止与恢复属于 LEGACY_BRIDGE。整页交接核验项目、Task ID、类型及停机准入，再由原 stopTrain428 或 openTrainingRecoveryDetail 执行原确认、恢复门禁和回执。新页不将取消请求当作安全停止。暂停、继续、提权和历史记录管理保留在原完整任务页。报告仍由原工作台承担。
- 局部验证：冻结 API 1 项及 Chrome 1 项，任务读 API/不可变读取 2 项，交接 Node 24 项，原生任务 Chrome 1 项，Vue 类型与双构建、JS/Python 语法与 diff 检查。浏览器业务请求使用隔离夹具，未运行实际停止、恢复或 GPU 训练。
- 下一阶段 M3-C 在独立审计后迁移训练报告、指标与有来源评测决策入口。训练执行、GT、租约、调度、Payload 发布、数据库 Schema 与 VERSION 合同沿原 Owner。三份未提交设计文档继续保留。

- M3-A 的 GitHub Actions 快照为 22 成功、1 失败。前端失败来自三处旧数字缓存断言、Node 用例早于 Vue 依赖安装，以及旧训练弹窗的 1920×1080 滚轮用例。已补齐前三处断言的版本格式及一致性检查并调整原工作流安装顺序，定向 Node 18 项通过，YAML 解析通过。旧弹窗用例本地 1 项通过，CI 复现差异仍待最终 SHA 验证。

模型分工。GPT-6.1 Terra（Low）实现原生任务页初稿。GPT-6.2 Sol 负责 UUID 修复、读取与旧操作身份边界、整合、审查、定向验证及 Git。当前运行环境未提供 GPT-6 Luna。

## M3-C 原生训练报告与独立评测

- 任务列表、任务详情、历史版本及版本详情可打开报告。任务 ID 或算法与版本 ID 保存在正式路由，返回仅接受同项目的训练列表或算法库路由，保留 URL 筛选、版本页及详情身份。报告内容每次从 API 读取。
- v44 `report?reader_view=true` 保持 100 条历史一页，独立显示 Val、Test、最佳和最终 Epoch、实际参数、完成原因及质量告警。配置使用既有 SHA256 核验和 512 KiB 展示边界。无任务绑定的旧版本仅展示已保存的版本证据。现有离线 ECharts 在首次打开有数据的曲线区域时模块化加载，切页和离开时释放图表及观察器。
- v12 分段评测和对比使用原版本身份与可比性规则，类别、样本和对比每页 20 条。样本预览使用同源历史证据端点，同时核验冻结评测 ID、图片 ID 与 SHA256。缺少身份时明确标记记录限制。原工作台仍处理 GT/预测的交互叠加、深度诊断、继续训练、困难样本挖掘和反馈补数。交接在旧页面加载后复核已知评测 ID，原 Owner 继续维护决策、快照和回执。
- Windows Node Agent CI **UNRESOLVED**。运行 `44450248821` 的 Windows Job `135312124779` 日志为 860 passed、1 failed、7 skipped。失败断言只打印 FAILED，没有 `outcome.error` 或进程诊断。本机定向用例通过。该测试直接构造 deployment lease，走下载和校验，不调用 M3-B 改动的 `read_payload_version(max_bytes=…)`。新增原样断言失败时显示错误原因，待同类 Runner 给出证据。
- 本地验证为报告/评测投影与 API（含 Windows 单项）20 项、旧入口和静态合同 Node 28 项、Chrome 2 项，以及 SPA 类型检查、双构建、离线闭包、Python 编译和 Diff 检查。没有提交实际训练、评测或发布任务。CI 异步验收。
- 下一步先独立审计本批导航、冻结证据及旧操作边界，按新 SHA 判断 Windows 回归。如需迁移评测决策写操作，先核对原 decision、benchmark、candidate set 和回执合同。
