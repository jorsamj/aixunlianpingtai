# P1｜训练素材选择器 20 万素材性能与模块边界只读审计（2026-11-14）

- 仓库：`jorsamj/aixunlianpingtai`；唯一开发分支：`feature/external-algorithm-publishing`
- 本次审计基线：`5b9b743bfc19817906bea0d5f1e4d9ba9b320c76`
- 操作边界：**仅代码、CI 日志和公开技术文档的只读分析；本提交只新增审计文档**。不修改 JS/Python、GT、DB、Worker、部署或生产数据。P0-06C 真实 20k～30k 训练任务对账仍按用户决定**延期/未验收**。
- 口径：大小来自 GitHub tree 原始 blob 字节数；定位和性能数字均限于本次核实的基线/隔离 Chrome，**不是生产 P95**。

## 1. 当前源码实际规模与职责

| 文件 | GitHub tree 文件量 | 核心职责 | 建议 |
|---|---:|---|---|
| `static/app.js` | 1,386,275 B | 兼容旧页面/全局逻辑 | 先不整体拆；此前已有 13C 渐进懒加载治理 |
| `static/main.mjs` | 40,222 B | 多个模块的静态装配和路由 | 保持稳定单一装配入口；注意 picker 仍是静态 import |
| `static/modules/training-material-picker-runtime.js` | 100,568 B / 1,658 行 | 注入样式、模态框、查询缓存、60 条卡片、缩略图、筛选批选、冻结、复选、审核、历史 | **第一候选：仅拆约 29KB/582 行运行时内联 CSS**，低风险独立缓存，须按需加载并防闪动 |
| `static/modules/training-material-summary-runtime.js` | 95,607 B / 1,344 行 | 摘要、GT 兼容性、审批、任务范围、审核导航、请求控制 | 有拆分价值但跨业务耦合更深，本期不抢先改 |
| `static/modules/training-submit.js` | 66,148 B | 任务表单与创建合同 | 不在 P1 性能专项顺手拆，避免影响用户训练创建 |
| `platform_core/training_material_picker_api.py` | 134,214 B / 2,326 行 | FastAPI 路由、GT 筛选、SQL、历史/负样本池、冻结、批选、缩略图 | **长期可按职责拆内部服务**，但先证明 SQL 慢点，保留原 URL 和外部合同 |
| `platform_core/material_repository.py` | 88,768 B | SQLite 索引游标/分页/数据操作 | 已有分页数据库架构；本期不更换 MySQL/Redis |

精确源码事实：picker 的 `injectStyles()` 位于约第 152–739 行，运行时 CSS 字符串约 29,071 字符、约 582 行，占 JS 字符数约 30%；它是在 `open()` 第 1329 行才调用，因此**不能将 CSS 无条件挂入所有页面的关键渲染路径**。若拆分，应采用可验证的按需样式资源载入/预取，保留注入时序及样式作用域、移动端弹窗滚动测试。

## 2. 已有成熟实践——不要重复造轮子

1. **服务端分页与延迟总数**：picker 每页 `DEFAULT_PAGE_SIZE=60`，普通列表请求显式 `count_mode=deferred`；`_gt_material_filter_page` 不在首屏进行精确 `COUNT(*)`。已有滚动缩略图可视区加载、前 10 张优先解码；在该 60 张 DOM 规模下没有证据引入虚拟列表。
2. **大批量服务器冻结引用**：大于 2,000 张的 train 全选转服务器 `selection-reference`，前端不下载数万 ID；`bulk-selection` 有固定上限/修订校验；输入、勾选、批选、确认均有现有回归。
3. **取消与防过期数据覆盖**：`activeController` + `requestSequence` + `signature()` 拦截关闭/条件变化后的迟到响应；页面缓存通过 revisions 重新核对。与成熟 Query 取消/查询键模式一致，**不能为了减少一次请求删除修订校验**。
4. **SQL 已有优化**：`material_repository._deferred_material_page_sql` 先分页索引 key 再读取 payload；筛选 SQL 与 GT/usage SQLite 索引关联。不能简单断言当前仍是大 JSON 全量读取或需要换数据库。

## 3. 代码级需测量的风险（非已确认生产 Bug）

| 候选 | 当前源码证据 | 检查方式 | 避免的误改 |
|---|---|---|---|
| **深页跳转的 SQL OFFSET** | picker 按 `page=N` 请求，`_gt_material_filter_page` 第 706 行形成 `OFFSET=(N-1)*limit`；API 另支持 cursor | 隔离 200k SQLite 样本，对比第 1/100/1000/3000 页 `EXPLAIN QUERY PLAN`、P50/P95、GT/历史筛选；评估仅改页面前进/后退为游标 | 不在未测量时重构分页或破坏页码跳转 |
| **恢复冻结选择的 2 次 HTTP** | `loadPage()` 先 GET/POST 当前页，若 `picker.reference` 存在，再 POST `selection-membership` 核对本页已选集合 | 记录 HTTP/服务端分别耗时、可接受优化与版本一致性 | 不直接删除 membership，也不携带 20k ID 到浏览器 |
| **角色筛选的深页扫描** | `_role_material_page` 在 `sample_role` + deferred 时按 120 行游标逐段匹配、跳过前页匹配项 | 测有/无角色筛选与深页在 200k 索引数据的扫描量和延迟 | 避免恢复旧全库角色索引导致首屏阻塞 |
| **分页 UI 重建** | `renderPage()` 为 60 条卡片重新设置 `grid.innerHTML`，附带详情与标注框缩略图 | Chrome Performance/LoAF、DOM 总数、绘制、按条件切换、复选前后比较 | 60 条本身无需急于虚拟化；优先证实重复渲染 |
| **缓存有效性/多请求** | 暖启动有缓存时仍做 revision 查询，缓存键关联筛选/任务策略 | 量化多开、筛选、翻页、缓存命中 P95/请求计数 | 不能把历史/GT/负样本池修订验证变成宽松 TTL |
| **运行时 CSS 与大量模块静态 import** | picker `main.mjs` 静态 import，约 29KB 样式文本作为 JS 加载；CSS 仅在 open 注入 | 比较首屏下载/解析、首次打开样式首帧、缓存复开、模态滚动 | CSS 抽离本身不是承诺的生产提速 |

## 4. 已核实的隔离 Chrome 性能证据

历史同仓工作流 `Training Material Picker` 真实 Chrome 日志（2026-11-14，Job `132273676504`）的 `picker_browser_render`：

- **隔离条件**：60 张模拟卡片，前 10 张 `192×192` BMP，由 Playwright 拦截 page/image；无生产服务器 WAN/存储/正式 GT。
- 首次冷打开 `click_to_decoded_paint_ms=219.1ms`，检测到一次 `71ms` Long Task。
- 暖打开 **20 次**，`P50=137.75ms`、`P95=151.2ms`，`warm_total_long_tasks=0`。
- 请求统计：分页 API 总计 1 次、revision 总计 20 次、首次 10 张缩略图、后 20 次没有新增缩略图请求。
- **推论**：单页 60 条的温态浏览器渲染并未出现可归因的显著长任务；但冷首帧与 Revision RTT、200k 后端过滤/磁盘 I/O、真实网络状况仍不能用上述数据证明达标。需要先测服务端和深页。

CI 风险独立保留：代码提交 `e625ace894badefe9a37ddc18fc3c8d10df81404` 的 22 个 Actions 中有 21 个 success、1 个 `Frontend Runtime Stabilization` failure，失败 Job `132280004184` 的 `training-create-scroll.spec.mjs:43` 在 1920×1080 的训练创建弹框中鼠标滚轮后期望 `scrollTop>0`，实际 5s 仍为 0；其余 124/125 浏览器测试通过。**不能直接认定为偶发，也不属于本次 picker 拆分已解决的问题**。如涉及 CSS 拆分，先重测滚动行为，不能通过放宽断言掩盖。

## 5. 外部成熟方案核对（公开文档，供对照，不等于本项目已实现）

- MDN JS Modules / JS Performance：通过单一功能模块、非关键代码按需装载减少首次解析；`import()` 只在有明确收益时采用：https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide/Modules 与 https://developer.mozilla.org/en-US/docs/Learn_web_development/Extensions/Performance/JavaScript
- FiftyOne 数据浏览：大量样本依赖按索引的筛选/排序、按需显示字段统计、预生成缩略图、受控浏览缓存，不要求全量加载到浏览器：https://docs.voxel51.com/user_guide/app.html
- CVAT Tasks：大的任务分片/分块，优先载入第一块、剩余背景读取：https://docs.cvat.ai/docs/workspace/tasks-page/
- TanStack Virtual：虚拟 DOM 适合**当前页实际渲染很多条**，不替代服务端筛选和分页；现有 60 卡片应先测量：https://tanstack.com/table/latest/docs/framework/react/guide/virtualization
- TanStack Query：关联查询键、缓存和 AbortSignal；本项目已有同类机制，无须为此加入 React Query：https://tanstack.com/query/latest/docs/framework/react/guides/query-cancellation

## 6. 建议执行次序 / 拆分边界

**第一步：证据先行（只读）**。固定同一隔离基线：打开、筛选、深页、全选当前筛选、冻结返回、确认草稿；采集前端 P50/P95/Long Tasks/HTTP、服务端每阶段 DB 计时和 SQL `EXPLAIN`。输出“最慢路径＋原因＋影响范围”，不额外启动 A800/4070。

**第二步：若需要拆文件，先做 CSS 独立**。只从 `training-material-picker-runtime.js` 提取约 582 行 picker 专用 CSS 为 `static/styles/training-material-picker.css`（实际目标路径需先核项目资源路由）；保留 picker JS 逻辑与 `window.TrainingMaterialPickerRuntime`、`injectStyles` 触发时机；以按需 CSS 加载/非关键预取替代原内联字符串；对照首屏/弹窗首开 P95 和样式一致性，不得让首次打开无样式或失去滚动。

**第三步：有证据才拆 JS/后端**。若渲染有热点，再将无副作用的缩略图/预览渲染 helper 提为独立 ES module，picker 保留唯一状态 Owner；不拆多个副本的 `picker.selected/reference` 状态。若后端深页/筛选慢，先优化已证实 SQL 和索引策略，之后才将 `training_material_picker_api.py` 的分页查询/冻结选择/审核治理提成内部 helper（URL、revision、SQL 事务/GT 合同保持不变）。若所有性能指标合格，无需为了“文件多”继续拆分。

**验收**：与原提交对比 CI Chrome 冷/暖数据、训练任务选择器回归、20k/30k 冻结模拟、选择器跨页/多角色/修订争用、移动端与 PC 滚动；准确 SHA 的 GitHub CI 再核。禁止合并 main、force push、Release、生产 GT/部署操作。
