# 13C-04F｜部署转换代码只读依赖审计

> 审计日期：2026-11-13；唯一长期分支：`feature/external-algorithm-publishing`。
> 准确只读基线：`549df056161c515f38a7984be4e59f848f15a154`；该基线 GitHub Actions **23/23 工作流成功**。本文件属于审计结论，不是实施完成或性能达标证明。

## 一、结论（GO / NO-GO）

- **NO-GO：不得整体迁移 `static/app.js` 的 v39 部署转换块**。该块不仅呈现页面，也初始化全局部署数据、缓存、部署资源增删改检测、转换任务状态轮询、取消/删除/日志和 RKNN 板端验证操作，并被其他版本的正式转换弹窗调用。
- **NO-GO：不得把 v41 厂商插件块整体延迟加载后删除首屏全局兼容入口**。已有资源变更会调用其缓存失效函数 `invalidateDeployPluginCacheV41`，SDK 安装后还需要刷新资源能力；即使“部署插件”导航别名已退役，也不等于对应入口完全没依赖。
- **GO（只读候选）：优先调查独立的 `static/modules/conversion-workbench-ui.js` 的加载与监听生命周期**。它在 `static/index.html` 无条件以经典脚本加载（第 75 行），只有转换弹窗/展示页涉及它的 DOM 装饰逻辑；其末尾（约第 272–300 行）在启动时安装全局 `MutationObserver(document.documentElement,{childList:true,subtree:true})`，通过 `queueMicrotask` 合并回调，仍会随非转换页面的 DOM 变动执行全局转换节点查找。**这是潜在不必要开销，不是已测量的卡顿根因。**
- 本轮 **未改动任何业务代码、转换业务流程、API、缓存、数据库、Worker 或生产部署**；后续收益需真实 Chrome 分段数据核实。

## 二、源码边界及直接证据

| 代码区域 | 已确认规模 | 初始化/调用关系 | 风险 |
|---|---:|---|---|
| `static/app.js` v39，约 1990–2259 行 | 约 45,118 UTF-8 B（按标记区域计算） | 启动时设置 `state.deployResources/deploySources/deployJobs/deployArtifacts`，导出部署资源 UI/API、版本动作和旧任务轮询 | **高：不允许整段移走** |
| `static/app.js` v41，约 2263–2313 行 | 约 6,017 UTF-8 B | 注册插件状态、缓存恢复、SDK 安装及缓存失效入口 | 中：独立但收益小且依赖 v39 |
| `static/modules/conversion-workbench-ui.js` | 17,862 B（Git tree） | `index.html` 第 75 行静态加载；启动时注册全局 DOM 观察器；装饰转换历史与创建弹窗 | 中：建议作为下一轮最小专项先测再改 |
| `static/modules/conversion-catalog-runtime.js` | 20,322 B（Git tree） | `main.mjs` 第 206 行安装；`renderDeployResources` 调用其 `mount`，页面导航调用其 `leave` | 中高：已有完整 Owner/lifecycle，不与展示监听器混改 |
| `static/app.js` v428 正式版本转换区域（约 3755–3951 行）及 v416/417/428 兼容区域（约 7701–7764 行） | 不纳入 v39 45 KB | 管理实时资源判定、版本历史分页、请求去重、创建状态不确定性、转换编辑器和公共最终入口 | **极高：不得随 v39 拆动** |

### 有效页面与兼容入口的事实

- `static/modules/navigation-stability.js:31–33`：`部署转换`、`部署产物` 导航请求规范化到 `算法列表`，`部署插件` 规范化到 `模型配置`。
- `static/main.mjs:536–552`：**`部署资源` 仍有正式页面 Owner** `renderDeployResources`；`static/app.js:2140–2144` 负责渲染部署资源并挂载 `conversionCatalogRuntime`。
- `static/app.js:3800–3802` v428 的版本转换任务操作与 `static/app.js:2236–2254` v39 的 `stopDeployJob`、`openRknnHardwareVerify`、`openRknnAcceptanceReport`、`deleteDeployJob`、`openDeployLog` 相连；所以“旧导航退役”不等于“旧操作不可达”。
- `static/app.js:7293` 的唯一 `window.selectDeployTarget` 公共 Owner 调用 v39 提供的 `selectDeployTargetCoreV39`，说明延迟加载前必须建立稳定代理，否则可出现用户打开表单后点击目标按钮失效。
- `static/app.js:5504` 的刷新路径仍通过全局 `loadDeployData` 刷新部署数据；`v39:2038–2122` 负责缓存与 API。不可凭其旧版标记判定可直接删除。
- `static/app.js:3757–3792` 的新版转换资源核验使用权威 API，不得退回相信 localStorage。v428 的 `submitConvert428`（约 3884 起）还包含请求身份与不确定结果保护，必须原封不动保留。
- `static/app.js:2265–2313` v41 包含插件快照缓存 `cl_deploy_plugins_v41_snapshot` 及与部署资源更新的联动失效，不能随意改掉其初始化/读写语义。
- `static/modules/conversion-workbench-ui.js:287–299` 在首次执行时即注册全局 `MutationObserver`；`window.ConversionWorkbenchUI.refresh` 与 `window.openConversionNumeric560` 被它暴露，未来如按需加载，必须保留数值验证按钮的导航合同。

## 三、建议的下一轮最小实施（13C-04F-02，不自动开展）

**先测量，再决定是否减少全局观察器或进行按需加载。** 两种方案都不是此轮的既成成果。

1. 建立隔离 Chrome 前后可比样本：工作台首次进入、素材/训练页连续 DOM 更新、转换记录弹窗打开/翻页、转换创建弹窗选择参数；记录 MutationObserver 回调次数、`decorate()` 触发次数/耗时、长任务、JS 请求数与解码体积。不得把源码体积变化直接当成 P95 改善。
2. 优先评估 **显式挂载**：由已有 `openVersionConvert428` / `openNewConvert428` 的实际 DOM 就绪点触发展示装饰，解除或限制全局 `document.documentElement` 观察范围；保留弹窗内容异步补齐后重新装饰的能力。只有触发点完全覆盖，才能移除全局观察器。
3. 如果动态导入的收益明确，再把这 **17.9 KB 展示脚本** 按首次打开转换窗口延迟加载；需要一个极薄、稳定的兼容入口，尤其保留 `openConversionNumeric560`、`ConversionWorkbenchUI.refresh`，以及快速切换弹窗的导航/ModalContentRuntime 作用域。
4. 先做单独专项，不触及 `app.js` v39/v41 核心 Owner、v428 的真实任务创建、防重/未知结果/删除/硬件验收，更不切换数据库或后端 Worker。

## 四、验收清单及阻断条件

- Node：`tests/frontend/deployment-action-owner-retirement.test.mjs`、`resource-deployment-public-owner.test.mjs`、`deployment-runtime-source.test.mjs`、`conversion-workbench-presentation.test.mjs`；加“非转换页面 DOM 连续变化不会触发转换装饰”及“异步节点插入可重新装饰”测试。
- Chrome：`tests/browser/conversion-workbench-presentation.spec.mjs`、`deployment-progress-performance.spec.mjs`、`deployment-artifact-visibility.spec.mjs`，以及 `model-and-conversion.spec.mjs` 中的转换、删除、刷新与硬件验收。必须测量多次开关弹窗、切换项目/页面、网络失败重试和观察器退出。
- 关键合同：提交真实转换任务的请求只发一次；请求状态不确定时不发第二个独立任务；列表数字以服务端为准；真实资源状态不能仅信缓存；产物下载/板端数值验证路径完整；转换 UI 修改不能影响训练任务。
- CI 必须按**最终代码 SHA**评估全部必需工作流，并区分 GitHub CI 与 A800/4070 生产现场、20k/200k GT、真实芯片、Safari 的验收。
- 禁止条件：必须维护第二套转换 Store/Router/轮询器、必须修改 v428 请求身份语义、观察器失效时不能可靠补齐异步 DOM、没有可重复的性能收益证据；任一成立则停止迁移。

## 五、提交范围

13C-04F-01 本次只读审计只允许增加此报告及更新进度台账；无业务代码提交、无重新打包/发布/合并 main、无 A800 或 4070 操作。
