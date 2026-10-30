# AI 预标注、清洗范围与提示词创建体验实施计划

## 2026-10-30｜42.24.437 P0 真实浏览器对比证据保留续批（待精确 CI）

- 基线为 `a818e1d8`／42.24.436，该精确 SHA 的 41 个 GitHub Actions 工作流 **40 成功、1 失败**。`AI Annotation Recovery` 通过；失败的 `Frontend Runtime Stabilization / browser-navigation (1)` 为 105/106，其中新增创建配置确认用例检测到真实 `#ai429Confirmation` 仍 hidden。另一个 `v42.25 Release Regression` 曾因 `psutil` 暂停状态立即断言失败，原 SHA 单 Job 重跑后成功；这是已记录的独立时序波动，本批不混入进程控制逻辑修改。
- 创建确认故障根因是新增 `renderAiCreateConfirmation429` 位于提交函数的闭包，却调用了创建工作台另一个闭包中不可见的 `aiCreateLabelName429`，抛出运行时异常后面板未被填充。这与此前候选框渲染跨闭包错误同类。**本批已替换为平台公开且原任务列表一直在用的 `window.PlatformCore.materials.labelDisplay` 唯一展示入口**，增加禁止再次引用私有 helper 的 Node 合同，并单独更新 app.js 缓存键；不复制标签映射逻辑、不改变正式 GT 标签规则。
- 同时为原 Playwright 用例增加「配置完成但尚未确认」和「最终确认已展开」两个时点的 1920×1080、1440×900、1366×768 截图，避免仅保留成功后状态而无法比较同一浏览器流程的前后变化。
- 原 `.github/workflows/frontend-runtime-stabilization.yml` 的浏览器作业会生成 `test-results`，但没有上传截图的 action。现沿用同一 workflow/shard，增加 `if: always()` 的 GitHub artifact 上传：仅留 `ai-create-*`、`ai-inline-review-*`、`ai-review-*` 图片与失败 trace，保留 30 天；不新增 workflow、测试系统或生产运行态数据。
- **这属于验收证据保全，不代表视觉满意度或性能已达标**。需在 437 精确 SHA 的真实 Chrome CI 跑完后核对截图产物、分辨率及位置；若有失败，按具体 trace 修复。与 `42.24.436` 的完整业务回归、AI 任务真实远程服务/OSS 冷加载、P50/P95 均应分别记录，不得借「生成截图」宣称整项 P0 完成。

## 2026-10-30｜42.24.436 创建任务最终确认续批（准确 SHA CI 待验）

### A. 基线与本批边界

- 开始前远端长期分支 HEAD `2470ef2a41ed751c32e7e6f2385c2af82fa49363`、`VERSION.txt=42.24.435`，工作区为新克隆的干净副本；本批只修改原生 JS 创建 Owner、样式、回归测试和版本/接续文档。
- 用户 P0 原始要求是「选素材 → 配模型 → 标签/提示词 → 试跑 → 最终确认 → 创建 → 审核 → 正式 GT」的企业级顺畅闭环；此前创建提交按钮直接 POST，缺少本次**真正生效配置**的最后核对。当前仍使用原有同一层宽屏工作区，**不是**已交付独立路由页面。

### B. 本批代码变化

1. `static/app.js`：在现有 `ai429Create` Owner 内增设原位最终配置确认区域。首次点击「核对并创建」只汇总即将提交的真实 JSON（素材数、模型、标签、阈值、已有标注策略、可选参考图、模板、补充说明、完整提示词）；用户第二次确认才发原 v60 任务创建 POST。没有新 API/Task/GT Owner 或模型配置管理弹窗。
2. 修改标签、素材、模型、模板、提示词、参考素材和阈值后旧确认失效，必须重新核对。任务名称在本次打开时固定，避免两次点击产生不同 payload。提交期间单次请求门禁，POST 成功回执与旧对话框的刷新/切换用 epoch + project 栅栏隔离；后续任务详情读取失败不得覆盖原创建回执；阈值空值或越界有明确错误。
3. `static/styles.css`：在既有宽屏工作区内加入层级鲜明、两列自适应的核对摘要，不新增叠层；`static/index.html` 同步 CSS/JS 独立缓存键，`VERSION.txt` 升到 42.24.436。

### C. 本地回归及证据状态

- `node --check static/app.js`、`git diff --check`、版本资源键测试和 AI Owner 定向 Node 已通过。全量前端 182 个文件在受限沙箱 181 通过，唯一 `uppy-vendor.test.mjs` 因临时目录/符号链接权限失败；该文件获授权单独 **3/3 通过**，随后获授权完整 Node **1415/1415 通过**。最终 SHA CI 仍须另验，不能借本地通过宣称远端套件通过。
- 已补 Playwright 合同：首次确认零 POST、参数变化后确认自动失效、新阈值显示正确、重复点击只发一次、失败保留表单、1920/1440/1366 三种视口截图。启动隔离 FastAPI 测试服务正常；本地缺 Chrome，Playwright 下载返回无效 0 MiB ZIP，故**该浏览器用例尚未真实执行**，须以最终 SHA 的 GitHub Actions/Chrome 验收。
- 没有运行真实远程模型、OSS、生产素材库/GT 写入、A800 任务或生产部署；未采集生产 HAR/P95，不能声称达到 300ms/2s/500ms 性能目标。

### D. 未完成与下一续批顺序

1. **P0 未闭环**：创建/审核仍共用单层模态工作区；是否改为独立路由要先核现有导航 Owner、返回/恢复语义及多个任务切换，不能复制第二套状态管理。页面中模型高级配置、样例素材的业务布局仍须真实用户视角截屏验收。
2. **P0 未闭环**：原任务列表只提供服务器 cursor 分页及**当前页**搜索/状态过滤，尚无跨全历史精准搜索、组合筛选和候选/审核/入库/外部同步的后端聚合投影。按原 TaskRepository 单一数据源设计 SQL 投影/索引，避免逐任务扫描或前端伪统计。
3. **P0 未闭环**：创建 POST 只有前端并发门禁，服务器尚未提供明确的 request-key 幂等合同；网络结果未知时不能保证重复点击不会创建两个任务。必须先设计可持久核验的后端操作 ID 后再放开未知状态重试。审核 `/decisions` 的原提交/超时/恢复合同也须逐项核验。
4. **验收缺口**：独立审核页面连续处理、正式 GT 与外部同步状态隔离、三个分辨率真截图、OSS/模型冷加载、实际 10k+ 素材前后端 P50/P95、取消过期请求/旧错误不跨页面提示仍需真实浏览器和授权测试环境取证。

### E. 下一会话接手口径

先 `git fetch` + 核真实 HEAD/VERSION/dirty worktree，再读本段和原 P0 任务书。按「精确 SHA CI → 确认控件真实 Chrome → 后端任务搜索聚合 → 请求幂等/独立路由」推进；每批更新本文与 `docs/CODEX_CURRENT_STATE.md`。不改生产数据、不部署、不 merge main、不 tag/release、不 force push。代码提交后填入确切 SHA 与 CI 结论，不能把本段的待验写成已通过。

> **2026-10-30 / 42.24.434 真实单图试跑接续**：前一批 `80502b0d`（42.24.433）已对准确提交完成 22/22 GitHub Actions、真实 Chrome 307/307；本批新增单图模型试跑及创建界面原位框预览，CI/真实模型仍须按本批最终 SHA 验收。不部署生产。

## 2026-10-30｜42.24.435 单图试跑 CI 候选框修复（准确 SHA 待核验）

- 42.24.434 准确 SHA `312e4b7a` 的 AI Annotation Recovery 后端合同通过；Chrome browser-navigation (1) 105/106，仅新增单图试跑用例失败，真实 Playwright 提示 `candidateOverlay is not defined`。此为前端作用域错误：创建工作台与审核工作台分别处于独立闭包；HTTP 已响应、图片及候选框数据存在，但展示调用了另一作用域的函数。
- 原位共享唯一的 `candidateOverlay` 绘制函数（暴露为 `window.aiCandidateOverlay60`），创建工作台引用该函数，不新增第二套坐标计算、审核状态或 GT 写入。更新独立 app.js 缓存键及原 marker 测试；新真实 Chrome 用例应覆盖框叠加、修改配置废弃、503 重试、任务未创建三个视口。
- 上轮 `744ec1c2` 同步修复 Frontend Runtime Stabilization 的旧缓存键测试；本次不跳过或删除任何失败测试。由于本地执行容器临时不可用，本批修复在原 GitHub 分支作有租约的单次提交，并以准确 SHA GitHub Actions 作为可执行验证；**生产真实模型、OSS、P95 与浏览器用户侧 Stalled 未验证，未部署**。

## 2026-10-30｜P0 AI 标注真实试跑预览续批（42.24.434）

### 补齐的断点

- 上批创建页「预览最终提示词」仅渲染文字，不能验证模型对真实业务图片的视觉输出；原 `/api/v35/model-configs/{id}/test-annotation` 是固定白底 128×128 连接验证，不适合冒充真实素材预览。
- 新增与原 v60 任务入口同路由组的 `POST /api/v60/projects/{project_id}/annotation-preview`，明确要求恰好一张真实素材，复用 `_annotation_create_payload` 的项目/素材/标签/模型冻结校验、`annotation_runtime.prepare_request(runtime=True)` 的密钥引用与提示词、`annotation_task_service.load_task_images` 的原存储源及 `annotate_one` 的真实 provider/解析/阈值/NMS。图片已知体积及本地物化后都限制 16 MiB。无 TaskRecord、CandidateStore、review decision、正式 GT 的写入代码。
- 创建页沿用现有 `ai429Create` 草稿和唯一 `draft.images`，在提示词区之后增一个「试跑一张素材（可选）」区域；当前页已选素材可挑样，异步请求可取消、30 秒有界、失败原位重试，结果在原界面按图片尺寸叠加候选框并显示模型耗时。修改标签、提示词、模型、阈值或选择集合时主动废弃原结果；关闭/切换创建代次后不回写旧结果。
- 远程模型可能产生实际调用费用，因此仅明确点击试跑才触发；没有预取、后台循环、批量自动推理，也不将「零候选框」解释成人工正式负样本。

### 实际修改及回归入口

| 路径 | 作用 |
| --- | --- |
| `app.py` | 单张视觉试跑只读业务输出 API、单张/16 MiB 防护与外部错误脱敏 |
| `static/app.js`、`static/styles.css`、`static/index.html` | 原创建工作台试跑区域、候选框画布、当前选择/参数修改栅栏、静态资源缓存键 |
| `tests/api/test_annotation_preview.py` | 有界单图、未知 ID、图片过大、错误不泄露、没有 Durable Task/候选持久化副作用 |
| `tests/browser/ai-create-experience.spec.mjs` | 模型真实 API 请求合同 mock、图像框预览、参数变更失效、503 原位重试、未创建任务、三个桌面视口截图 |
| `.github/workflows/ai-annotation-recovery.yml` | 将新增 API 测试接入已有 Durable Annotation API 作业，不建立新 CI 工作流 |

本地已执行 `node --check static/app.js`、`python -m py_compile app.py tests/api/test_annotation_preview.py` 与 `git diff --check`；本机无 `pytest` / `@playwright/test` / Chrome 依赖，新增 Python、浏览器测试需最终 SHA 的 CI 补验。**真实 GLM/Qwen/OSS 冷加载、模型费用、推理 P50/P95、网络等待都未现场实测**；不能声称生产已有 2 秒 SLA。

**首次准确 SHA CI 补验**：`312e4b7a` 的 AI Annotation Recovery 已通过 Ubuntu/Windows 和含新单图预览测试的 API 合同；Frontend Runtime Stabilization 的 Node 1413/1414，唯一失败是 `version-marker-owner.test.mjs` 仍固定旧静态资源缓存键 `42.25.438/453`，新入口已改为 `42.25.439/454`。原测试仍严格逐项断言缓存键，本批仅把对应新预期同步为真实入口值，本地该文件 1/1 通过。浏览器分片及最终修订 SHA CI 仍需单独验收，不能借 API 绿色宣称前端全绿。

### 尚未完成

- 创建与审核仍是单层宽屏弹窗，不是独立导航页面；缺完整最终确认配置页。
- 任务列表搜索仍只对当前 cursor 页，状态/候选/审核/正式入库的全局组合筛选与聚合统计未完成；不能用逐任务遍历同步补齐。
- 多图连贯试跑、真实远程供应商时延与 OSS 暂存成本尚未取证；需要有授权测试环境后单独测量。当前本批仅一个显式单图试跑，不把模型连接测试或夹具视为模型准确率验收。

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
3. v60 候选审核有现成 Annotorious 与真实 GT 提交流程，但编辑候选时再 `modal()` 一次，形成审核窗套编辑窗；从任务进度弹窗直接点击审核也会再叠一层审核；切图容易误丢尚未保存草稿。
4. 任务列表旧版只读第一页 50 项、缺少可见分页与当前页搜索。历史任务远多于 50 时不能浏览。

### 变更及安全边界

| 文件 | 本批变更 |
| --- | --- |
| `static/app.js` | 创建页立刻请求当前素材页，保留并行配置加载；请求去重与代次栅栏；取消隐式勾选；复用唯一 `draft.images` Set，实现跨全部筛选结果 ID 分页解析、50k 上限、原子合并与失败保留；审核候选页同步打开、错误可重试；从任务进度跳转审核时先关闭旧弹层；编辑改为同一工作区内联的左队列/中 Annotorious/右对象面板，Dirty 切换提示；任务列表当前页查找与前后分页；提交返回持久化回执后立即展示任务状态。 |
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

### 远端真实 Chrome 回归与补正（续）

- `740326d1` 的 **Frontend Runtime Stabilization / browser-navigation (1)** 实际运行 105 项，其中 102 通过、3 失败。逐项查看 CI 原始错误后，确认失败用例仍假定「候选框编辑是第二层对话框」（2 项），或假定「创建任务自动选择素材第一页」（1 项）；这两项前提恰与本次业务修复相冲突。
- 更新已有 `tests/browser/annotorious-lifecycle.spec.mjs` 和 `tests/browser/auto-label-polling.spec.mjs` 的定位范围为同一个审核工作台内的 `.ai66-edit`，仍保留真实 Annotorious 画框、保存、翻页、映射与正式 `/decisions` 断言；创建失败恢复用例改为显式点击一张素材后提交，仍验证防重复 POST 和表单内容不丢失。没有删除用例、跳过测试或降低实际功能断言。
- 待新提交的准确 SHA 重新执行真实 Chrome 和后端合同；旧 SHA 的 102/105 **不能**冒充新提交已全部通过。
