# AI 预标注、清洗范围与提示词创建体验实施计划

> 2026-10-30 P0 AI 标注体验续批：基线 `5dcd7186`／`42.24.432`，本批开发版本 `42.24.433`。以下「续批证据」仅陈述本批实改和验证边界；不会把已有的模型/审核/GT 功能重复计为新建，也不把隔离浏览器夹具称为生产实测。

> 本计划以用户 2026-10-16 的专项修复指令为已确认设计；只在现有 v60 AI 标注、v47 CLEAN MaterialBatch 与 MaterialSelectionSpec Owner 内增量实现。

## 目标与边界

- AI 创建弹窗在用户点击后同步打开，不等待全量素材读取；异步数据采用弹窗内 loading/error/retry，并以打开代次隔离迟到响应。
- 清洗主范围支持全部图片、选定图片、选定标签；标签按 OR 命中，标注状态等次级条件与主范围取交集。
- AI 创建任务允许选择视觉模型、提示词模板、任务级提示词覆盖、恢复模板原文、后端预览，以及显式选择当前有效标签。
- 后端冻结模型配置、模板版本、任务级有效提示词和标签 schema；恢复及 Worker 执行只使用冻结输入。
- 不改变清洗的只读扫描/人工确认合同，不直接删除素材或修改正式标注。

## 实施步骤

1. 先补前端所有权、清洗 selection、提示词冻结与真实 Chrome 响应时延的失败测试，保存修复前证据。
2. 扩展 `annotation_runtime.prepare_request()`：校验任务级提示词长度与模板变量，生成并持久化有效提示词模板、来源、模板版本和预览；Worker 仅使用冻结的有效模板。
3. 扩展 v47 清洗请求：将主范围、次级过滤和标签 OR 规范化为现有 `MaterialSelectionSpec`，preflight/estimate/prepare/retry 共用同一规范化结果。
4. 重做现有两个创建弹窗的内部内容，不改变 modal/任务 Owner：同步首屏、异步 hydration、固定底部操作区、局部错误重试、搜索与分页/选择反馈。
5. 更新静态资源缓存键（不改 `VERSION.txt`），运行 Node、Python、Playwright 定向与全量回归。
6. 在 1366×768 和移动端真实 Chrome 验证并截图；核对 Network、重复监听、迟到响应、冻结 request.json。
7. 检查 diff、工作区、VERSION 后创建一个本地独立提交；不推送。

## 验收证据

- 点击到弹窗可见小于 300ms，且打开动作不请求全量 `/materials/ids`。
- 清洗标签 OR、状态交集、空范围拒绝、revision 冻结及远程 preflight 结果均有自动化测试。
- 修改模板/模型后，已创建任务的 request.json 与 Worker 仍使用原冻结值；浏览器响应中不暴露 secret。
- 关闭后重开时，第一次迟到 hydration 不覆盖第二次弹窗。
- 现有恢复、远程清洗、素材选择、模型配置和提示词 API 回归通过。

## 2026-10-30｜P0 AI 自动标注创建、跨页选择和审核 UI 续批证据

### 已确认的问题

1. 创建任务的模型、提示词模板、标签 3 路配置并行读取后，旧代码才调用 `loadAiCreateMaterials429`，所以配置接口的尾部延迟会直接阻塞第一页素材；旧代码还可能在空显式选择时从 `state.images` 继承暂存素材，并自动选中当前页。这与用户明确选择集合不符。
2. AI 创建页只有「选择本页」，没有跨多页解析 *当前筛选条件* 的操作。已有 `/materials/ids` 会调用 `list_page` 水合素材 JSON，再只抽取 ID，批量请求代价不必要。
3. v60 候选审核有现成 Annotorious 与真实 GT 提交流程，但编辑候选时再 `modal()` 一次，形成审核窗套编辑窗；切图容易误丢尚未保存草稿。
4. 任务列表旧版只读第一页 50 项、缺少可见分页与当前页搜索。历史任务远多于 50 时不能浏览。

### 变更及安全边界

| 文件 | 本批变更 |
| --- | --- |
| `static/app.js` | 创建页立刻请求当前素材页，保留并行配置加载；请求去重与代次栅栏；取消隐式勾选；复用唯一 `draft.images` Set，实现跨全部筛选结果 ID 分页解析、50k 上限、原子合并与失败保留；审核候选页同步打开、错误可重试；编辑改为同一工作区内联的左队列/中 Annotorious/右对象面板，Dirty 切换提示；任务列表当前页查找与前后分页；提交返回持久化回执后立即展示任务状态。 |
| `app.py` | 既有 `/api/v61/projects/{id}/materials/ids` 增量支持 `narrow=true`：使用 `MaterialRepository.iter_filtered_ids` 同一 SQL 筛选谓词；`expected_revision` 与请求前后修订校验返回 409；无此参数时保持旧 API 用法。 |
| `static/styles.css` | 内联审核三栏与窄屏布局、创建批量反馈、任务表筛选/分页。 |
| `tests/api/test_material_content.py` | ID-only 过滤结果、正反修订号合同。 |
| `tests/browser/ai-create-experience.spec.mjs` | 受控 5 页筛选全选、A∪B 去重、409 原子保留；内联编辑不产生第二弹层；任务翻页/筛选；三个桌面视口截图，均须在 CI 真实 Chrome 执行。 |

整个批量解析期间不修改已有选择；全部分页返回且总量、修订均一致时才合并。新增条件仍由同一 MaterialRepository 过滤；没有新素材库、标注/GT Owner、模型配置系统或 Worker。候选编辑「保存」只写原 `review.edits` 和 `review.decisions`，正式入库仍必须走原 `/decisions` durable 审核链。

### 质量与性能证据（严格区分）

- 静态语法 `node --check static/app.js`、`python -m py_compile app.py`、`git diff --check` 通过。
- Node 定向 `ai-annotation-owner`、`annotation-task-owner-retirement`、`annotation-task-view`、`annotation-workbench`、`auto-label-poll-runtime`、`annotorious-candidate-owner`、`version-marker-owner` 七个文件通过；完整 Node 182 文件中 178 通过、4 失败，经隔离复核均由当前运行环境缺少 npm `node_modules` 的 `@annotorious/annotorious` 或 `@uppy/core` 等依赖引起，不代表功能断言失败。新增浏览器/Python 合同需 CI 正式运行确认。
- 当前执行环境没有 `pytest`、`fastapi`、本地 Chrome 和 `@playwright/test`；不能声称本机完成 Python 端到端或真实浏览器验收。现有 Chrome UI 证据可见 `docs/evidence/annotorious-2026-10-21/`，本批新增三分辨率 Playwright 截图用例在 CI 中输出；当前还没有本批真实截图结果。
- **耗时**：未获取本批真实请求链、OSS、远程模型或生产 HAR，因此没有可报告的修复前/后毫秒、P95 或实际 Stalled 对照；前推只是代码级已确认消除「先等配置」阻塞，不等于达成 300ms/2s/500ms 目标。

### 尚未完成，不能宣称 P0 全量验收

- 创建任务仍复用一层宽屏 modal，尚非独立路由全页面；缺少产品级视觉预标注试跑预览和最终确认预览面板。
- 任务列表的搜索/状态只作用于当前服务端页（界面已写明），未实现跨全历史的名称索引搜索、任务层完整候选/审核/入库聚合列；现有真实 Durable Task 不提供这些汇总的单页快速投影，不能临时逐任务重算冒充实时统计。
- 审核编辑已去除嵌套弹层，但外层仍是全屏 modal，未改独立导航路由；原有批量审核与入库状态未全面重做为全流程单页。
- OSS 冷/热、外部模型远程推理、训练素材与 AI 材料页面交互合同、实际生产全量素材高压负载、人工截屏视觉验收仍待有权限环境执行；生产数据库与正式 GT 未动。

仅长期开发分支正常快进提交；无 main merge、force push、tag、release 或生产部署。精确 SHA CI 与 Chrome 的最终结论须在远端运行完成后另行核对。
