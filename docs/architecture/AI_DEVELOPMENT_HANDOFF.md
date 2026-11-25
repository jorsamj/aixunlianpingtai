# AI 开发接续入口

项目：畅联云算法训练平台；仓库 `jorsamj/aixunlianpingtai`；唯一分支 `feature/external-algorithm-publishing`。

## 当前阶段与准确提交

D2B2-C2B-F1 已实现专用正式 GT 写入屏障与取消后只读对账。详细实现、隔离验证和自动续批接入条件见 [审核工作台](../AI_REVIEW_WORKBENCH_2026_11_06.md#d2b2-c2b-f1-正式-gt-写入屏障与取消对账)。F1 以 `54e35ddb32346e368125f96a886e125f7015cd92` 为基线，最终提交及 CI 状态见交付记录。


此前 M4-D1-D2A 已实现原生 AI 跨页选择与服务端冻结，功能与 CI 分开验收。M4-D0 的范围及故障恢复见[审核工作台](../AI_REVIEW_WORKBENCH_2026_11_06.md#m4-d0-审核数据恢复与操作范围)。M4-A1 基线 `a8aedf39f455630115511605f74b00dfa3f4fa94` 的 43 项 Actions 已通过。本轮验收以交付消息中准确 SHA 的 Actions 快照为准。

- M2 起点（已核对远端）：`4c7a6d1f31c275311156fb0ab1a7a5cd9d47d7f8`，保留 M1 的数字缓存键修复与未知写入刷新保护。
- M2-A：`280ed4cfb21f80e0980c03ace18aa70877a41706`，原 AlgorithmSqlStore 新增 opt-in 全局算法库只读投影及正式版本备注写入的轻量回执。
- M2-B/C 实现：`c83c114230873f57ae9d0f9a348ffc17f9cc4307`，完整 Vue 列表/版本 UI、备注编辑、受控操作入口及定向回归；最后仅补本入口、矩阵、功能保护与当前 AGENTS 阶段说明。
- M1 原 `65ae81372555786b78284a1bc62608703c1c40d6` 的 GPT 审计结果是50工作流48成功、2失败（Frontend Runtime Stabilization 44344576655、Material Upload Chunking 44344576624），不是验收通过；已在4c7a6d1f修复。该修复 SHA 的最终 CI 本轮未查询，不借旧结果验收新代码。

## 2026-11-21 状态摘要与正式审计文档入口

- 基线：分支 `feature/external-algorithm-publishing`，HEAD 与远端一致，均为 `1fa5119b84e8721e2dc4810903471a2e37b6e862`。该 SHA 的 **48 项 check-suite 已成功**；但这只代表该提交能通过现有 workflow，**不等于每项功能都有对应覆盖，也不等于已验收**。工作区当时不干净（8 个已修改 + 5 个未跟踪）。
- C2-B（冻结选择后的后台分批正式 GT 入库）为**本地未提交候选实现**：唯一执行任务、不可变绑定、执行/查询/取消 API、CPU Handler、100 张续批、取消对账、终态与进度均已写出，但未提交、未 CI、未验收。已确认缺陷/待定项：D1 取消对账 `completed_batches` 多算并漏报最后一批准入批；D2 `unproven` 无有界重试与阻断态；D3 QUEUED 取消语义待定；D4 重复测试函数；D5 final audit 与 publish 锁域/成功语义待确认（事实已确认，风险等级 `TBD`，未定为 P0）；D6 进度含推算值。异常来源与终态可达性仍需定向核验。详见[架构审计](PLATFORM_ARCHITECTURE_AUDIT_20261121.md)第 8 节。
- 20 万素材已有**隔离**证据（200k 元数据分页、稀疏 GT、20k/30k 冻结链路、任务只读批量队列位置），**生产性能与真实图片/GT/OSS 负载全部 `NOT VERIFIED`**。历史报告中部分 `p95_ms` 实为 7 次最大值，引用时须保留该口径。
- 当前无任何阶段为 `ACCEPTED`；Vue 原生化覆盖 8 条具名业务路由（复用 7 个页面组件），其余菜单仍进入原系统。数据库仍为 SQLite，无迁移授权、无迁移动作。
- 正式文档（本轮落库，待独立审阅）：
  [架构与性能深度审计](PLATFORM_ARCHITECTURE_AUDIT_20261121.md)、
  [20 万级素材性能验收规范](../performance/PLATFORM_SCALE_ACCEPTANCE_20261121.md)、
  [架构演进路线与阶段验收](PLATFORM_EVOLUTION_ROADMAP_20261121.md)。
- 下一步：A（C2-B 安全收口）优先，但**不阻塞 B（旧接口只读性能核验）**；C 以 B 的实测证据为前置，D 按各自业务链条件分别验收，E1（AI 批量 GT 的 Vue 入口）依赖 A，E2–E6 与 F 可按独立风险推进。除"正式 GT 写入依赖 A"这一安全前置外，不设统一串联门槛。

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

### M3-C 独立审计整改

- 审计基线 `d822ec1f4e01a90bbbb841f1b24506069a25f1d5`。Windows PR Run `44457940238` 的合同 Job `135337448930` 报 `NoSuchProcess`。本地强制子进程在身份采样前退出，复现于 `launch_process()` 的 `psutil.Process(pid)`。Windows 现由 Popen 持有的原始进程句柄读取内核创建时间，POSIX 和后续 PID、创建时间、命令摘要三项核验沿用原逻辑。
- Frontend Run `44457931106` 的 Job `135337505431` 制品 `14499331406` 显示 POST 和读取均返回目标配置，失败画面仍在等待列表渲染。用例现在等待目标行出现，再清空内存缓存验证原编辑回退。模型配置业务代码保留。
- v44 报告将请求配置、实际执行参数和来源未标注的历史参数分别呈现，缺失显示未提供，0 保留。旧报告和评测工作台返回新版时恢复同项目算法筛选、分页与已核验的版本详情。交接动作仍由原 Owner 一次性消费。现有冻结图片端点的评测 ID、图片 ID、Snapshot 归属及内容摘要校验保留。
- 本轮完成定向本地验证。发布与验收以交付消息中的最终 SHA 和 Actions 快照为准。M3-C 待复审和 CI 验收，不启动 M4。

## M4-A1 原生素材库

- `/app/#/projects/{projectId}/materials` 接入“素材库”菜单，复用 MaterialLibrary、MaterialPreview、v61 分页和原标注详情。列表每页 48 张，使用缩略图和有界框预览，详情按需读取。使用记录沿用 v62 的只读 history 查询。
- URL 保存筛选、页码、布局及详情。浏览器会话按账号和项目保存显式选中的 ID，过滤或翻页保留选择，可逐项移除或清空。实际批量治理在原工作台确认范围。
- 图片上传、ZIP 数据集导入、人工标注、AI 预标注、清洗、负样本池、标签管理、批量治理和删除审核保留 `LEGACY_BRIDGE`。单素材标注进入前核对项目和素材身份。返回新版时恢复浏览 URL 与项目会话选择。
- 后续采用项目公共负样本池及分类，训练使用仍须核验目标标签、正式 GT、处理状态及人工确认凭证。历史算法关联表继续保留。ZIP 文件夹归集、标注映射、Train/Val/Test 的执行核验与训练负样本选材属于后续阶段。
- 本阶段功能为 `FUNCTIONAL_COMPLETE`，现场和生产验收另行核实。停止在 M4-A1，等待 GPT 独立复审。

### M4-A1 独立审计整改

- 基线 `e41db45e` 的 Actions 为 42 项成功、1 项失败。前端 Job 的 5 项失败来自启动快照新增的项目参数及其 `URLSearchParams` 依赖。原启动请求已恢复，服务端继续决定旧页当前项目。Job 在单元测试失败后跳过构建，制品上传随之失败。
- 旧工作台当前项目与请求项目不一致时，素材交接明确拒绝。当前交接只支持服务端已选中的项目。主动打开操作需要原入口就绪，缺失时提示错误并保留新版返回链接。
- 本地验证覆盖三个启动测试文件、素材交接、原生及试点素材浏览与离线构建。最终 CI 状态以交付消息的准确 SHA 为准。

## M4-B1 项目公共负样本池

- 素材库进入项目公共池，支持分页搜索、分类和审核状态筛选、入池、替换分类和移出。成员写入采用 `negative_pool.members.v2`，复用现有事务修订号和回执表，按项目与操作身份查询未知结果。原算法级 v1 及历史关联保留。
- 新训练选材的公共池过滤使用项目成员表和分类。算法仍用于训练标签、版本、历史策略与准入。一批待移出素材如仍有历史算法关联，事务拒绝整批，保留关联和成员。
- 原生训练草稿分别保存正负样本组。显式选择去重后交给原准入。有范围引用时，现有冻结服务校验来源后生成一个 Train 引用。负样本筛选冻结只纳入当前目标下已确认的负样本。原人工确认端点仍核验身份、证据和确认摘要，正式 GT 由原 Owner 维护。
- 独立 Test 可按公共池筛选，仍执行原准入。报告只对可核验且在读取边界内的冻结快照展示正负样本分布。隔离准备夹具验证角色计数、标签文件及原 GT，实际训练和生产待现场确认。
- 本地定向验证覆盖普通池和历史回执、正式确认后的引用重绑、浏览器失联恢复、训练正负样本的两种选择顺序，以及两个 Vue 构建的离线资源。隔离夹具从冻结快照读得 Train 正 1 / 负 1、Val 正 1 / 负 1、Test 正 1 / 负 0，负样本标签文件为空。CI 以本轮交付中的远端 SHA 为准。
- 独立复审先核对真实任务准备证据及兼容边界。M4-C 的 ZIP 划分继续等待独立安排，保持现有 ZIP 上传、确认与导入 Owner。
- 独立审计整改以 `71e9531b229d5bbb70d97b585bdaa9b1c9b3c348` 为基线。冻结合并按账号、项目和算法保存最近一笔 UUIDv4，完整范围及五类修订一致时通过原服务端冻结接口重试。公共池回执按已验证账号和项目恢复，项目切换重新挂载并取消旧读取。旧项目级缓存键因无账号归属不自动恢复。
- 独立审计整改本地通过 2 项 Python 定向用例及 6 项 Chrome 用例，覆盖同范围重试、改范围冲突、过期证据拒绝、账号隔离和项目切换。Vue 类型检查及新旧构建离线闭包通过。新 SHA 的 CI 以交付快照为准。


## M4-C1 ZIP 文件夹归集与标签确认

- 基线 `7f0a01771abd12d2e37919f13efa33481c71d871`。SPA 素材库沿用旧工作台 v19 ZIP 入口。新版普通上传明确启用文件夹确认，未启用的旧客户端、历史任务及旧算法池入口保留原合同。
- `GET /api/v19/projects/{project_id}/import/jobs/{job_id}/folders` 分页返回真实图片目录、用途建议和标注汇总。识别完整中英文目录名。未知、术语需复核及冲突目录等待用户确认。确认同时复用原外部标签映射。外部类别或来源路径有冲突时需修正或拆包。
- 原 job.json 冻结实际 ZIP SHA256、扫描清单摘要、项目、任务、选择范围、文件夹规则和外部映射。正式素材内 `zip_folder_source` 保存完整来源路径、用途、摘要与归集状态。该证据随 MaterialRepository 保留，新版来源用途不写成旧 `split`。成功解析节点直接提交素材 ID 的来源证据，包含 COCO/VOC 未引用原图分支。
- 目标标签只写待标注意图。已入库外部 GT 保留原映射与正式标注权威。负样本直接进入项目公共池，分类和素材归集状态在同一事务提交。失败回执保留待归集范围，可通过原任务重试，或者在素材治理中处理。运行状态异常或归集分类已失效时应先核验任务或修复分类。正式训练、GPU 和生产仍待现场验证。
- M4-C2 需先为 `platform_core/training_splits.py` 的 `SplitRequest` 和 `build_split_manifest()` 设计明确的固定 Val 及跨角色冲突合同，再衔接 `platform_core/remote_training_tasks.py` 的 `_freeze_request_contract()` 与 `platform_core/training_tasks.py` 的 `resolve_training_input_freeze()`。用途意图仅作为来源证据，正式 GT 和隔离准入仍由现有 Owner 校验。
- 定向验证通过 ZIP API 与分类 Python 用例 23 项、ZIP Node 53 项、Chrome ZIP 路径 41 项，以及 Vue 类型、构建和离线资源核验。以交付消息记录最终提交 SHA 与对应 CI。


## M4-C2 按 ZIP 来源固定训练划分

- 基线 `535ec5497245ecea3ad43e05a1b6120c66e40209`。独立 Vue 训练创建页新增 `fixed_zip_train_val_test`，携带显式 Validation 引用和两个空随机比例。旧随机划分与独立 Test 保留默认行为。
- v62 选材接口分页列出具有持久化 C1 素材来源的 ZIP。预览从 MaterialRepository 和 AnnotationRepository 读取真实用途中已入库的成员，排除未指定，显示资格和泄漏问题。三组引用用同一确认 UUID 派生三个稳定身份，复用原选择清单的角色、修订、配额及摘要核验。草稿、冻结请求和待核验创建记录按登录账号、项目及算法隔离。旧浏览器记录因缺少账号归属不自动恢复。
- `/train/start` 校验来源、完整引用与组合限制。原 TrainingPrepare 在队列后复核引用、正式 GT、源内容身份和历史隔离，任一固定成员失效时拒绝整批。固定 Val/Test 使用正式评测 GT；Train 可使用原任务级确认。固定模式拒绝 Benchmark 复用、补数据、样本上限和会增加成员的颜色增强。
- `SplitRequest.validation_image_ids` 和 `build_split_manifest()` 保留三组固定成员，阻断 ID、内容、来源和派生关系的跨组重叠，同角色内容重复也拒绝。冻结可选字段绑定角色、来源清单摘要及原 GT，历史冻结摘要兼容。中央、Node Agent、远程结果和使用索引维护共用固定输入重放合同。
- 实际打包输出 Train/Val/Test 各自图片目录，Test 标签留在独立评测真值目录，未写进训练 YAML。报告核验冻结摘要和快照后显示实际数量及来源规则，超出摘要读取预算时明确显示证据不可用。
- 隔离验证覆盖实际 v19 导入到 v12 任务请求、中央准备、不可变冻结、精确目录、负样本空标签、Test 隔离、使用记录和只读报告。未执行真实 epochs 或 A800/4070 验收。CI 以交付消息所列准确 SHA 为准，后续等待独立复审。
- 本地通过训练核心、引用、报告、历史和准备定向 Python 用例，以及真实 ZIP 创建请求、Node Agent 冻结重放和远程结果验证。前端 41 项 Node、7 项 Chrome、Vue 类型检查和离线构建通过。

## M4-D0 AI 标注与审核安全加固

- 基线 `a4f9b4e40dd4d2522dd0a90f520119c8f21c8edf`，开发状态 `M4-D0_IMPLEMENTED`。本节所在唯一 M4-D0 提交的完整 SHA 与 Actions 快照见交付消息。
- 部分 GT 恢复、逐图补审、负样本转池和撤销复用各自正式 Owner。旧工作台与 Vue 审核投影共用选择 Owner 和服务端资格。正式 GT、训练及任务运行边界见[审核工作台](../AI_REVIEW_WORKBENCH_2026_11_06.md#m4-d0-审核数据恢复与操作范围)。
- 本地验证包括隔离 GT/转池中断、外部 GT 修改、选择排除和跨操作者拒绝；运行与实际改动相关的 Node 校验、Vue 双构建和 Python 编译。相关现有 GitHub Actions 异步验收。未操作生产或启动真实推理。
- 下一步仅复核本次准确 SHA 的 AI Annotation Recovery 与 Frontend Runtime Stabilization，按证据处理相关失败，独立复审完成后再安排 M4-D1。


## M4-D1-B 原生 AI 审核只读试点

基线 `fb9f66ac202876196d1077ff3a870798b69606b1`，该基线 22 项 Actions 成功。D1-B 试点地址为 `/app/#/projects/:projectId/ai/tasks/:taskId/review`。经现有 Session、项目列表和 v60 任务详情核验后，单一 Pinia Store 读取每页 24 张候选。切换范围或离页取消请求；切图同时取消原图详情和诊断读取。原工作台继续承接编辑、采用、拒绝、冻结、消歧、正式入库、转池、撤销和回执恢复。

新页面使用 v61 正式素材读取和既有候选框预览组件。验证使用隔离 Chrome 夹具，覆盖任务身份、20k 总量下的有界分页、图片和诊断按需读取、三个指定视口、原入口回退及读取取消。Vue 类型检查、独立 SPA 构建及离线资源检查见本阶段交付记录。准确提交 SHA 及 Actions 快照见交付消息；独立架构验收后再安排 D1-C。


## M4-D1-C 原生 AI 单图候选草稿

基线 `e0f1761187e6c8c3b4e0bde3259101dae1fbc161`，22 个基线 Actions 成功。审核试点使用相同显式路径。当前单图编辑复用 `AnnotationEditor.vue`、原 Annotorious 3.9.5 内核及正式项目标签。编辑会话记录未确认请求及其原始请求体，按账号、项目、任务、图片隔离。在 v60 草稿 PUT 中原样重放，已有 CandidateStore 完成 CAS、幂等和持久化。确认保存后重读候选及当前分页；版本冲突保留本地编辑，用户确认后采用服务端草稿。

图像取 v61 正式原图，交互与图像共享原图像素坐标。浏览器按 EXIF 显示；历史服务端尺寸与实际显示方向或尺寸不一致时，本页阻止编辑。完整处理该类素材需另行对齐服务端原图坐标合同。独立验收前仍从原入口执行正式采用、GT 入库、批量审核、转池、消歧、撤销及回执流程。准确 SHA 与 Actions 快照见交付消息。D1-D 需独立审计及后续授权。


### M4-D1-C1 草稿恢复收口

基线 `9c0bdd77b091f7e770cf2345eb154063e595c49e` 的 22 项 Actions 均成功。C1 为已有会话恢复记录校验身份、原请求和框数据，兼容同一作用域存储键中原有的未确认记录。原请求未核验时，即使工作副本与服务端一致也触发离开保护。收到成功回执后仅重读服务端，读取失败时保留已确认标记及重读入口。跨作用域取消请求时继续保留未确认身份。无效记录保留，不能进入编辑器或发送请求。

隔离 Chrome 对真实 v60 接口验证响应丢失、原请求重放、确认后重读失败、无本地差异仍提示离开、身份错配记录拒绝、409 保护和正式 GT 保持原样。C1 独立提交；准确 SHA 的 CI 通过前暂停 D1-D1，继续由原工作台提供采用与拒绝。


### M4-D1-D1A 单图审核决定合同

基线 `a7048c781c3b982d687c9b698c4f70d747359bf7` 的 22 项 Actions 均成功。原 v60 decisions 路由新增显式 `single_candidate=true`。调用必须给一张候选、稳定 `request_id` 和权威 `review_revision`，关闭两种未提及处理和正式入库开关，且不提交框或全局映射。旧请求不含该开关时保持原行为和历史回执摘要。

单图资格、标签和逐图范围核对后，在 CandidateStore 同一 SQLite 写事务中完成候选、修订和 `review_events` 持久证据。回执查询按原项目、任务、操作者、请求摘要和单图结果匹配。缺少可信事件时保持 pending，不从后续 accepted 状态推断。拒绝不声明审核范围；逐图补审采用需要显式冻结范围；未人工解歧不得采用。

实际验证比较了未选候选数据库行、正式 GT 内容和版本，并验证回执写入前后的中断、同号重放、修订冲突及旧批量、正式入库和草稿合同。A 阶段准确提交 `d4d0be1086b0f73a74546c46712cbbbde307ad68` 的 Push 26 成功、1 失败，PR 21 成功。两个 AI Annotation Recovery 批次、Material Annotation Atomicity 和 Frontend Runtime Stabilization 均成功。ZIP Import Durable Runtime 的 `real-chrome-refresh` 在 `zip-import-refresh-recovery.spec.mjs:440` 等待第二个 v19 ZIP 队列项失败，原单项在本地复跑通过。A 的改动触及 v60 与 CandidateStore，目前没有因果证据指向 A。按修正放行规则继续 B，保留 GitHub 失败记录。[ZIP 工作流](https://github.com/jorsamj/aixunlianpingtai/actions/runs/44670825120)

### M4-D1-D1B 原生单图采用和拒绝

沿用 `/app/#/projects/:projectId/ai/tasks/:taskId/review`。Pinia 从候选详情保留权威 `review_revision`，操作前复读同一候选以核对显示快照。POST 只包含单图及明确人工选择的冻结补审范围，关闭正式入库和未提及处理开关。按账号、项目、任务、图片隔离单图决定回执。未知结果仅查原请求，404 和 202 继续保留，409 刷新候选后等待用户作下一次决定。已完成回执遇到读回失败时重读详情和当前页统计，保留筛选和检查图。

现有 Frontend Runtime Stabilization 的真实入口 Job 复用该 SHA 已构建的资源运行单图决定与草稿 Chrome 用例。本地验证、准确 SHA 和 CI 快照见阶段交付。跨页冻结、批量决定、批量消歧、正式 GT 入库、转池和撤销继续由原工作台提供，原菜单入口保留。D1-D1B 分页收口基线 `dbfd4b60134f83be3b99bf532d27492cbf0274a2` 的 22 项 Actions 均成功。

### M4-D1-D2A 跨页选择与冻结

原生工作台支持显式跨页选择和 `gt` 服务端筛选快照。显式状态只保存所选 ID；冻结状态只保存数量、资格排除、快照身份和手动排除 ID。每页至多读取 24 张，使用 `selection_member` 显示成员资格。修订不一致、快照过期或找不到时丢弃冻结并要求重新选择；旧工作台需重新选择。已有真实 Chrome Job 验证跨页、空快照、身份隔离和草稿回归。D2B 的正式 GT 提交协议待独立设计。

## 2026-11-21 接续入口（C2-B 与性能阶段）

- 最新已推送 HEAD 见 `git log -1`；本阶段关键提交：`43aaa14e`（封存恢复必须幂等重放证明）、`6134bfb5`（真实批量 GT 回执/坐标/批次证据与 Worker 日志）、`b74766b9`（标签编辑仅刷新标签）。
- 真实浏览器批量证据：`tests/browser/real-bulk-formal.spec.mjs` + `tests/browser/helpers/bulk_review_worker.py`（隔离 uvicorn + 独立测试 Worker 进程，205→201 三批、跨页排除 4 张、第二笔 4 张）。
- 仍未验证：生产 Worker 监督/重启/租约重领、真实 20 万图片与存储 I/O、生产 P95、FTS5 搜索方案。

## 2026-11-21 性能与恢复分类收口（本阶段）

- C2-B 恢复证明：只有 409 摘要冲突进入 `bulkConflict`；503/超时/网络失败进入未知锁定态，保留原 request_id 与 execution_attempted。
- legacy GT：空 `annotations/` 目录不再逐图 `is_file`；隔离 20 万合成、无持久 GT 下 `/projects` 4.65s→1.75s，`/datasets` 6.5s→3.63s，`/images` 仍约 2.15s/106MB。
- 标签：正式标签页 Owner 为 `renderLabelManagement414` / `saveLabel414` / `refreshLabels414`，已具备局部刷新；`b74766b9` 的 `refreshLabelsOnly` 属历史路径，本阶段仅补项目切换与失败保护。
- 未实施：`/images` 有界化、`/datasets` 聚合重构、FTS5、生产 Worker 生命周期验收。

## 2026-11-25 P0-01C 最终定向收口

实现 SHA：`b8c61ec6d0218ee1958aee82ec9aeafec015b9e7`（起点 `8d2c7fe9486f547c6758491e8997f68959aa9707`）。开发 `FUNCTIONAL_COMPLETE` / 验收 `CI_PENDING`；本机只做语法/静态/Git 核验，运行期和生产未验。中央单槽恢复绑定原节点、Assignment、attempt、worker、GPU/CPU、ProcessIdentity；Runner 未启动证明与身份未知分开，未知不得 finish；中央结算使用单一事务快照。测试合同与边界见 [本轮记录](P0_01C_FINAL_TARGETED_CLOSEOUT_20261125.md)。准确最终 SHA 与一次性 CI 快照见交付消息。无已知源码阻断，下一步交 GPT 独立审计；本轮到此停止。

## 2026-11-25 资源准入与安全 Requeue

P0-01C 已结束：用户独立核验基线 aaeebd06c608ab58b2317767dacff2351556606b 的 22 个 PR workflow 全部 SUCCESS。新实现 13a5cecf79d3ca677929e0f77c356cab19c56e0a 补齐资源规划→Agent 未启动证明→中央原子退回→原 Assignment 幂等回执→按节点等待/其他节点选择。保留原 TaskRuntime attempt、Owner、Hold 和 job.json 栅栏，无新 schema。开发 FUNCTIONAL_COMPLETE / 验收 CI_PENDING；本机仅源码/语法/静态/Git 检查通过，运行期/生产未验。准确最终 SHA 和一次性 CI 快照见交付消息。[合同、测试及网络未知边界](RESOURCE_ADMISSION_SAFE_REQUEUE_20261125.md)。完成后停止，交 GPT 独立审计。

## 2026-11-25 资源等待重启恢复与后端模块化

基线 21fb70de23c3be40006cb27579a031ca487abf60 的 22/22 PR workflow SUCCESS 为用户独立核验结论，P0-01C/准入不重做。A：dd8ee530924e79b87ed876d309b4dc0017d650bc，原 Coordinator 消费资源等待持久请求，先查旧 Assignment 回执，明确 404 才按原 lease/attempt 精确重放，未知保留证据；见[资源记录](RESOURCE_ADMISSION_SAFE_REQUEUE_20261125.md)。

B：da45ae7a46458cad0c8ce469f6083ae6c4613c21，算法库目录与版本生命周期 14 个接口和约 900 行业务/辅助逻辑迁到 Router/Contracts/Service，原 Repository/事务/锁/权限/Owner 保持。app.py 29,124→28,264 行，直接 HTTP 330→316+新 Router 14；静态有序合同逐项一致，运行时/OpenAPI 交 CI。新模块不 import app，不复制全局状态；原 bootstrap Owner、必要兼容入口保留。开发 FUNCTIONAL_COMPLETE / 验收 CI_PENDING，准确最终 SHA 和一次性 CI 快照见交付消息。[模块边界、证据、剩余域与依赖](BACKEND_ALGORITHM_CATALOG_MODULARIZATION_20261125.md)。本轮停止，交 GPT 独立审计，不自动扩展下一域。

## 2026-11-25 算法守卫收口与素材目录模块化

后续接续（2026-11-25）：基线已推进至 6111b541d617def129ac8ed51b1841782417ee8f（用户核验 22/22 SUCCESS）。本轮 A e3764889 完成素材成员/用途/状态及旧删除准入 8 接口迁移；B 完成标签 CRUD/引用/重映射/统一和人工标注读取/保存 10 接口及关联业务迁移。原 MaterialRepository、AnnotationRepository、GT write_annotation、数据集锁、标签锁和 material_batches 回执 Owner 保留。app.py 28,001→27,303 行、直接 HTTP 304→286，原序列与模型 AST 保持。相关源码守卫转向真实 Service/Contracts，未弱化断言。开发 FUNCTIONAL_COMPLETE / 验收 CI_PENDING；只做语法/AST/符号/Git 检查，运行期交既有 CI。B/最终实现 SHA 与一次性准确 CI 快照见交付消息及提交记录；详情见[模块化记录](BACKEND_ALGORITHM_CATALOG_MODULARIZATION_20261125.md)末节。下一边界是 AI 创建/清洗/审核的完整候选 CAS、冻结、GT 屏障和 C2-B 回执编排，本轮不拆散迁移；停止等待独立审计。

基线 c183ab3d49b82346ce2866468a92fd1bb4a2b8d3 开工一次查询：22 个 PR workflow，20 SUCCESS/2 FAILURE，无其他失败；资源恢复不重复整改。A：832e168d，两项实际静态守卫跟随算法 Router/Service，保留本地创建无外部授权、LOCAL 来源、原创建调用和标签合同。

B：327023ff399263e93b261c68cf08f5c534622bfc，完成素材浏览、数据集目录管理及只读标签/质量投影单元，12 接口迁到 material_catalog_api/contracts/service，原 MaterialRepository/AnnotationRepository、StorageManager、索引生命周期及数据集元数据访问器保持。删除/引用保护、标签写入/合并、人工 GT、AI 审核和既有 material_batches/Picker/负池留原 Owner，未声称全素材域完成。app.py 28,264→28,001 行；直接 HTTP 316→304+新 Router 12，有序静态合同与 13 个业务体比对一致。开发 FUNCTIONAL_COMPLETE / 验收 CI_PENDING；本机仅语法/定向静态/Git 检查，运行期交现有 CI。准确最终 SHA/一次性 CI 快照见交付消息，详见[模块化记录](BACKEND_ALGORITHM_CATALOG_MODULARIZATION_20261125.md)。本轮停止，交独立审计。

## 2026-11-25 路由合同、AI 审核与训练业务接续

基线 47b7900b4b1dffc9594b14bff9f7e392269d132b，用户核验 22 个 PR workflow 为 21 SUCCESS / 1 FAILURE。A f68fa3669609304cad0b2a48174d372bac814ef7：两处唯一性测试使用 FastAPI iter_route_contexts，有旧版扁平路由回退；唯一注册、真实 endpoint、OpenAPI、请求模型及私有审核字段断言保留。B 7044815c295777ab335da4526c0f16ba271ca423：AI 创建/查询/草稿/冻结/审核/正式入库/转池/C2-B 33 接口及清洗全生命周期 7 接口迁入两个业务模块。C/最终实现 SHA 见本节所在提交及交付消息：训练管理 11 接口、评测/对比/意见/难样本/补充数据冻结/算法报告 14 接口迁入 training_management 与 training_evaluation。

原 CandidateStore、AnnotationRepository、TaskRuntime、Worker、冻结、GT 屏障、幂等及取消对账 Owner 保留；无新任务体系或数据库。app.py 27,303→23,708 行、直接 HTTP 286→221；112 个业务/辅助函数及 19 个模型 AST、接口有序签名与两个同名选择模型绑定保持。旧守卫和故障注入定位至真实 Owner。开发 FUNCTIONAL_COMPLETE / 验收 CI_PENDING；仅语法/符号/AST/装配/Git 检查，运行期和新增 65 接口有效路由合同交既有 CI。前端、VERSION、AGENTS、四份保护文档和生产未动。剩余与验证边界见[模块记录](BACKEND_ALGORITHM_CATALOG_MODULARIZATION_20261125.md)末节。统一推送后一次准确完整 SHA CI 快照，停止等待独立审计。
