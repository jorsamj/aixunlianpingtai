# 页面提示文案审计

审计基线为 42.24.561 / `fc38666004168104c1d9ed1356d690fb46218561`。范围按任务书 §5 的 28 个页面和入口编号。基线 Frontend Runtime Stabilization run `42320805181` 的三个 Chrome 分片分别通过 118、120、114 项，共 352 项。ZIP Chrome job `128244621877` 另通过 43 项。用例结果仅支持其实际断言和夹具场景。

表中「隔离数据」指本地测试服务有真实记录和接口，「受控数据」指浏览器由测试路由接收固定业务状态或故障。两类均经过原页面渲染。以前的 15 页空库普查仅作为导航和外壳参考。有些页面的当前业务状态只有源码可核，已在表中标明。此次复用现有证据，未重跑整站或按页面补拍截图。

## 逐项清单

| # | 页面与当前 Owner | 证据及实际覆盖的状态 | 问题与处理 | 应保留的信息或覆盖限制 |
|---:|---|---|---|---|
| 1 | 首页 · `overview-tabs.js` | 受控数据。`overview-tabs.spec.mjs` 覆盖总览分栏、有指标来源及遥测不可用 | 保留。各栏对应不同数据范围，未证实重复解释 | 保留遥测不可用说明，未核现场指标组合 |
| 2 | 算法列表 · `algorithm-list-runtime.js` | 受控数据。`algorithm-list-performance.spec.mjs` 覆盖算法卡片、训练筛选和展开 | 保留。概览和展开操作用于不同层次 | 保留可训练状态和筛选作用域 |
| 3 | 算法详情 · `algorithm-list-runtime.js` 版本展开及 `app.js` 版本入口 | 受控数据。同一 spec 覆盖版本训练血缘及按版本操作 | 保留。版本信息与算法摘要各有用途 | 保留当前版本、历史血缘及危险操作确认 |
| 4 | 素材库 · `renderDatasets424` / `material-pagination-runtime.js` | 受控数据。`material-library-flow.spec.mjs` 覆盖网格、框显隐、跨页勾选与分页 | 保留。工具和筛选有清晰分工 | 保留筛选范围、已选计数及批量操作影响 |
| 5 | 图片详情 · `previewData429` / `material-presentation.js` | 受控数据。同一 spec 的三视口详情包含原图、正式框、来源批次及已标注状态 | 保留。画布展示与属性栏说明有各自用途 | 保留标注与来源信息。证据限夹具图片 |
| 6 | 负样本池 · `negative-pool-runtime.js` 的 `poolHTML()` | 本轮隔离数据。1366 截图前后均有算法池成员和已展开详情，另有 `negative-pool-members.spec.mjs` 实际写入及选择回归 | **已精简一处。** 删除详情中的重复「资格：待确认」，保留卡片主资格标签 | 审核状态、未确认无目标说明、训练使用事实仍可查。截图为同场景的独立测试记录 |
| 7 | 素材审计 · `smart-material-audit.js` / 原素材治理入口 | 隔离数据与受控响应。`smart-material-audit.spec.mjs` 覆盖审计页、分页、GT 对比和失败重试 | 保留。提示分别说明证据、结果和可执行操作 | 保留正式 GT 冲突、复核结论及失败原因 |
| 8 | 数据清洗 · `renderOps427` / `cleaning.js` | 隔离数据与受控响应。`remote-cleaning.spec.mjs` 覆盖作用域、执行位置、清洗进度和复核入口 | 保留。主范围和标注状态是不同维度 | 保留执行不可用原因、冻结范围和结果复核 |
| 9 | 人工标注 · `annotation-workbench.js` / 原编辑器 | 隔离数据。`annotation-ui-governance.spec.mjs` 覆盖原图与正式框、标签颜色、图片故障重试 | 保留。图像加载失败和重试属于操作反馈 | 保留正式状态、失败原因和恢复操作 |
| 10 | AI 自动标注 · `renderOps427` / `auto-label-poll-runtime.js` | 受控数据。`auto-label-polling.spec.mjs` 覆盖任务列表及状态刷新 | 保留。任务状态与轮询反馈承担不同作用 | 保留状态、取消与重试信息，未核现场长任务数据 |
| 11 | AI 审核工作台 · `app.js` v60 审核 / `ai-review-route.js` | 受控数据。`ai-review-workbench.spec.mjs` 覆盖三栏、候选及批选。`ai-review-api-roundtrip.spec.mjs` 补充隔离回执 | 保留。采用、勾选与审核状态各有语义 | 保留 GT 冲突、草稿状态、逐图失败和恢复提示 |
| 12 | 标签管理 · `renderLabelManagement414` / `labels.js` | 隔离数据。`annotation-ui-governance.spec.mjs` 经正式标签编辑验证颜色回读。负样本分类另有 `target-negative-workflow.spec.mjs` | 保留。正标签和负样本分类管理的是不同对象 | 保留名称、用途及编辑影响。未核现场大型字典 |
| 13 | 基础模型管理 · `resource-discovery.js` / `advanced-navigation.js` 的母模型管理 | 源码核对。有资产、发现文件和节点安装入口。早期空库视图仅覆盖训练环境外壳 | 证据不足，保留。缺有基础模型资产、验证和节点安装状态的同页记录 | 保留发现、验证、安装与可训练性的区别 |
| 14 | 训练创建 · `training-create-hydration.js` / `openTrainingCreateCanonical429` | 隔离数据与受控响应。`training-create-first-open.spec.mjs` 和 `training-create-scroll.spec.mjs` 覆盖初次打开、表单编辑、继承和多视口 | 保留。分步输入与条件提示未证实重复 | 保留首训、迭代、标签继承及资源可用性 |
| 15 | 训练素材选择 · `training-material-picker-runtime.js` / `training-material-summary-runtime.js` | 隔离数据与受控响应。`training-quality-reports.spec.mjs` 覆盖精确批次。`training-material-picker-performance.spec.mjs` 覆盖分页读取 | 保留。候选数量、选中范围和准入状态含义不同 | 保留正负样本范围、筛选和冲突阻断 |
| 16 | 训练确认弹窗 · `training-submit.js` / 原任务草稿 | 隔离数据与受控响应。`training-on-demand-admission.spec.mjs` 覆盖真实 GT 核查、明确阻断和提交待核验 | 保留。审核提示影响用户是否确认、修改或重试 | 保留配置确认、准入阻断及提交不确定性 |
| 17 | 训练任务列表 · `training-task-visibility-runtime.js` | 受控数据。`training-quality-reports.spec.mjs` 覆盖队列、资源及数字优先级 | 保留。队列顺位与任务状态提供不同信息 | 保留排队、优先级和失败状态 |
| 18 | 训练任务详情 · `training-recovery-runtime.js` | 受控数据。`training-recovery.spec.mjs` 覆盖运行、成功、失败及可恢复检查点 | 保留。成功状态、异常原因和恢复条件各自必要 | 保留冻结资源、后端不确定性及重试入口 |
| 19 | 训练报告 · `reports.js` / `trainingReportCore425` | 隔离数据与受控响应。`training-analysis-material.spec.mjs` 覆盖数据、图表、报告预览。`training-quality-reports.spec.mjs` 覆盖目标和停止原因 | 保留。指标、样本和报告范围独立 | 保留缺失、真实零值、实际轮次及失败证据差异 |
| 20 | 模型转换列表 · 原版本转换历史 / `conversion-workbench-ui.js` | 隔离数据与受控响应。`model-and-conversion.spec.mjs` 覆盖历史分页、筛选与验证状态 | 保留。转换状态和板端核验不是同一结果 | 保留验证待办、失败原因和历史来源 |
| 21 | 模型转换弹窗 · `openNewConvert428` / `conversion-workbench-ui.js` / `conversion-catalog-runtime.js` | 隔离数据与受控响应。同一 spec 覆盖芯片、参数、资源未就绪及失败重试 | 保留。提示与目标、量化、校准和资源选择关联 | 保留参数校验、资源阻断、平台合同和恢复入口 |
| 22 | 场景化算法实测 · `renderQualityCenter424` / `scenario-evaluation.js` | 受控数据。`scenario-evaluation-workspace.spec.mjs` 覆盖可信冻结样本、A/B 对比、加载失败及重试 | 保留。快速检测与可信评测的说明帮助选择工作流 | 保留正式 GT 不可用、证据不匹配及报告范围 |
| 23 | AI 模型配置 · `renderModelConfigPageV35` / 原视觉模型配置弹窗 | 隔离数据与受控响应。`model-and-conversion.spec.mjs` 及 `model-api-protocol.spec.mjs` 覆盖模型供应商、协议和配置验证 | 保留。配置格式、连接测试和试验结果各自有用 | 保留供应商协议差异、凭据提示和验证失败原因 |
| 24 | AI 容量检查 · 原模型配置弹窗 `#mcCapacityStatus` | 隔离数据。`inference-capacity-config.spec.mjs` 保存配置后在单弹窗核对「有效并发 1 · 容量未知」 | 保留。连接、解析成功与并发证据的区别会影响用户判断 | 保留未知时串行及证据条件，未核现场双实例 |
| 25 | 资源管理 · `renderDeployResources` / `resource-discovery.js` | 受控资源状态。`model-and-conversion.spec.mjs` 覆盖资源编辑和编译器就绪。早期空库视图仅补外壳 | 保留。不同资源卡的「检测」对应不同对象 | 保留资源范围和就绪原因。现场混合节点负载未核 |
| 26 | 节点管理 · `service-node-runtime.js` | 受控数据。`service-node-management.spec.mjs` 覆盖节点资源及 Agent 凭据流程 | 保留。连接状态和凭据用途影响接入 | 保留凭据、资源不可用与状态信息 |
| 27 | 存储管理 · `renderStorageSources61` / `storage-cache-runtime.js` | 隔离数据与受控响应。`storage-source.spec.mjs` 覆盖本地源检查、重扫、冲突映射 | 保留。连接、导入和归档是不同操作 | 保留存储目标、执行位置及冲突策略，未核现场配置 |
| 28 | 新畅联交付 · `external-algorithm-publish.js` / 原版本操作 | 隔离项目与受控对端。`external-algorithm-publish.spec.mjs` 覆盖身份、缺字段、人工确认及成功交付 | 保留。当前信息用于交付核对和失败定位 | 保留身份阻断、正式确认与重试。未核真实对端 |

## 本次可核对的页面改动

负样本池展开「来源与审核详情」时，同一资格在卡片主标签和详情区各显示一次。当前变更只移除后者。前后截图都保留主标签、审核说明、原标签、来源时间及训练使用。实际截图和源码只支持这一处重复的消除。

- [修改前 · 1366](evidence/stability-2026-11-07/negative-pool-before-1366.png)
- [修改后 · 1366](evidence/stability-2026-11-07/negative-pool-after-1366.png)
- [原负样本池渲染](../static/modules/negative-pool-runtime.js)
- [本轮负样本池浏览器回归](../tests/browser/negative-pool-members.spec.mjs)

27 项保留。基础模型管理的有数据状态证据不足，其他各项的判断以表中已覆盖的状态为限。
