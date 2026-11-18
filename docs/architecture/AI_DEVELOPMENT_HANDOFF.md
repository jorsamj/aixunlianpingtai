# AI 开发接续入口

项目：畅联云算法训练平台；仓库 `jorsamj/aixunlianpingtai`；唯一分支 `feature/external-algorithm-publishing`。

## 当前阶段与准确提交

M2 算法库列表、详情与版本管理已实现，必要本地验证通过；验收 **CI_PENDING**，等待 GPT 独立审计，不自动进入 M3。本文件所属的最后文档提交是本批交付 HEAD；接续执行 `git rev-parse HEAD`，fetch 后比较 `origin/feature/external-algorithm-publishing`。准确最终完整 SHA 和一次 CI 快照在交付消息中，不能把下面实现 SHA 冒充最终文档提交 SHA。

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
