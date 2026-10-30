# AI 预标注、清洗范围与提示词创建体验实施计划

## 2026-10-31｜42.24.448 独立审核 UI 真浏览器修复与训练标签非破坏性重绘（待准确 SHA CI）

- **447 准确 CI 证据**：长期开发分支 `95dabdba6d39fe83901a09b457b7c0ca320cb3ac`，GitHub 原生 API 对精确 SHA 返回 **42 条 Actions：41 success、1 failure**，不能只看插件返回的前 20 条。失败为 [Frontend Runtime Stabilization](https://github.com/jorsamj/aixunlianpingtai/actions/runs/41110882872)：Chrome 分片 1 的审核回执成功未关主区、AI 候选框拖拽未产生新框、跨页人工修改标签未保持，共 3 项；分片 2 的千标签批量勾选在异步刷新后原 DOM 节点不稳定，共 1 项。其余工作流通过不代表这些浏览器体验已验收。
- **原 Owner 的根因**：`finishAiReview60` 在 `review.submitting` 为 true 时调用原退出函数，但 447 新保护对任何退出都拒绝；提交结果已被确认却无法切回任务列表。仅内部持久回执成功路径通过 `afterCommit` 明示放行，外部返回/导航继续拒绝在途提交。原 `bindAiCandidateEditor60` 的 `active()` 仍要求 `#modal` 包含编辑器，迁出主区后隐藏 legacy modal 仍存在，导致 Annotorious 所有可编辑操作被禁用。现仅真正可见的 modal 能阻断主区操作；候选草稿仍通过原保存后审核提交路径，绝不直接写正式 GT。新增 Node 具体行为测试与内外两种关闭合同。
- **训练标签**：原 `TrainingLabelRuntime.refresh()` 的签名包含完整选材 ID，后台摘要/标签名称 hydration 可能造成整个 `#trainingLabelContractPanel` 子树替换，打断刚选中的焦点、用户勾选或检索。签名改为真正影响展示的标签和来源有效性/素材是否为空；准备完成后只协调头部/继承/警告等区域，原标签列表保持同一 DOM 节点，逐个更新标签文字与勾选态；分页/过滤及原草稿唯一选择源不变。既有真实 Chrome 千标签用例继续作为质量门槛，不修改断言绕过失败。
- **回归与边界**：Node 完整测试 183 个文件在提升子进程权限后 **1426/1426 通过**，同时记录受限沙箱曾发生的 Uppy vendor EPERM 非业务故障；新增定向文件和代码语法再验。`static/index.html` app/main 与 `static/main.mjs` 标签模块缓存键同步、`VERSION.txt=42.24.448`。后端/SQLite/训练 Worker/已存任务/正式 GT 均未修改；无生产 DB v2→v3 迁移、无 OSS/远端模型 P50/P95 或实际生产大库证据。提交后必须查 **完整精确 SHA** 的全部 workflows、三浏览器分片、失败 trace 与三视口截图，不能以本地 Node 推定 Chrome 全绿。

## 2026-10-30｜42.24.447 URL 审核连续操作与 446 红项修复（准确 SHA CI 待核）

- **精确 446 CI**：提交 `7eb9dd3e` 可查询的 20 个 Actions 中 19 success、1 failure；失败的 `Label Normalization Contract` 只在 Permanent source guards 的硬编码 `annotation-task-view.js?v=422002`（实际 `422445`），其后端及前端标签规范化合同均 PASS。447 只改为存在性断言 `annotation-task-view.js?v=`，保留原模块和版本缓存隔离，新增 Node 防未来旧字符串回归。
- **真实主区路由**：保留 446 的同一原生 JS `reviewAiLabel427`/Candidate 编辑/GT Worker Owner；新 `ai-review-route.js` 只管理 `#ai-review/<task_id>` 地址，不读/写业务数据。进入任务产生历史记录，浏览器后退退出，前进重进；刷新后等主应用 ready 再按原项目真实 Candidate API 加载，未把候选框、正式 GT、token 或模型参数存在 URL。任务 ID 格式/长度校验，不允许任意路径片段。
- **导航保护**：`NavigationStability` 增可选 `canNavigate`，在 page request/epoch、poll owner 变化**之前**检查；保存前/提交中离开则阻止页面切换，浏览器历史移动后若用户拒绝离开则恢复当前审核地址。顶部“返回任务列表”使用原关闭函数并清 URL，切其他主菜单先释放候选编辑器及任务草稿再导航，不残留审核状态。Pending POST 的原 Request ID 仍按现存 localStorage/GET 回执恢复，不自动重发 POST。新版未扩展 Task、Candidate、正式 GT 或 SQLite schema。
- **本批回归**：`tests/frontend/ai-review-route.test.mjs`、导航 early guard、防过时缓存版本的 Source Guard 测试，以及 `ai-create-experience.spec.mjs` 对浏览器 back/forward/reload、原工作台/三视口截图的延伸。完整 Node 回归已通过；原 Label Normalization Contract 工作流失败的 `Permanent source guards` 脚本在本地按原 YAML 直接执行通过。真实 Chrome/GitHub CI 以本批最后 SHA 结果为准，不能把静态 UI 测试等同于真机视觉检查。
- **剩余 P0**：URL 入口按当前项目隔离（跨项目直达尚未实现）；OS 级生产 Chrome/OSS/远程模型/大批素材 P50/P95、GT 当前态审计及外部同步计数未现场验证。生产任务 DB 前批的 v2→v3 迁移仍须一致性备份与可恢复回滚演练，未部署、未修改生产数据。

## 2026-10-30｜42.24.446 AI 自动标注独立审核主区工作台（本批精确 SHA CI 待核）

- **边界与开源选型**：项目原 `static/vendor/annotorious`/页面已接通 Annotorious 3.9.5（Vanilla JS、BSD-3-Clause），直接复用，不重复安装或套 Label Studio 第二套服务。LabelU-Kit、Label Studio 的审核导航/信息层次仅作为参考；不引入 React/构建系统迁移。审核仍限 AI_ANNOTATION 任务的 Candidate，人工标注已有入口保持独立；二者最终使用唯一 AnnotationRepository 正式 GT。
- **交互**：原 `reviewAiLabel427` 从全屏审核模态框移到“自动标注及清洗”主内容区，顶部明确任务归属与“返回任务列表”，去掉页面无关的全局 KPI；原审核候选图/困难候选、过滤、分页、标签映射、批量统一、接受/拒绝、快捷键、同页三栏 Annotorious 编辑复用原状态与 API，没有新增任务/候选/GT Owner。审阅标签和正式提交范围不变，提交仍使用原 `request_id` 和原 Worker；未知网络回执仍需查询，不自动重试。
- **生命周期**：打开另一任务先结束旧实例并使旧异步请求失效；相同任务刷新沿用原分页草稿；未保存候选框在返回/切任务前确认，正在提交审核时不允许离开；退出后原任务列表按真实 API 复载。新页面是主区内独立视图，**不是已实现 URL 深链接或浏览器 History 级独立路由**，后者仍列待办。旧审核样式保留为兼容 CSS，但运行时不创建其模态层。
- **回归**：调整原 `annotorious-lifecycle`、`auto-label-polling`、`model-and-conversion`、`ai-create-experience` 浏览器断言，检查主区入口、无内嵌审核弹层、原 Candidate 编辑/正式 GT 所有权、返回任务列表，保留 1920×1080、1440×900、1366×768 真截图产物。版本号/静态 JS、CSS 缓存键同步；前端完整 Node 在正常子进程权限下 **1421/1421 通过**；受限沙箱 181/182 个文件，唯一 Uppy 子进程权限导致失败，与本次审核无关。本地 Chrome 与浏览器测试服务依赖不可用，**未运行真实 Chrome**；最终 SHA Actions 与截图需要另核，不能据源码断言“视觉已验收”。
- **部署风险和剩余 P0**：此批不改 SQLite schema，但前批 445 的 TaskRepository v2→v3 尚未在生产迁移，部署前必须先备份任务数据库/WAL 并演练可恢复回滚。真实 Chrome 三视口**视觉人工复核**、海量素材/OSS/远程模型 P50/P95、独立 URL/后退体验、正式 GT 当前态的跨任务归属审计、外部同步真实计数等仍待完成；不部署生产、不碰真实 GT、不 merge main/tag/release/force-push。

## 2026-10-30｜42.24.445 AI 任务阶段统计持久投影（当前批准确 SHA CI 待核）

- **业务口径**：候选图=`success+empty`（不等于候选框个数）；生成失败=`failed`；已审=`accepted+rejected`；待审=`unreviewed`；`gt_committed` 仅为本任务成功写入正式 AnnotationRepository 后的唯一 Image ID Commit 日志行数，**不是外部同步成功数，也不能保证今日 GT 未被别的任务覆盖**。缺乏历史证据时返回 `stage_statistics:null`，绝不把未知显示为零。
- 统计来源仍只有原 `CandidateStore` SQLite 的 indexed candidates 与正式 GT 写入后的 commits journal。后端在生成阶段每 100 张及完成、人工决策后、Worker 正式入库后同步原 `TaskRepository` 轻量投影。列表页先正常 cursor 查询 Task，再一次 `IN(...)` 批量读当前页统计；不在 HTTP GET 上逐任务全量扫描或同步重算。旧任务仅针对可见页异步有界回填（每批 25、每项目最多暂存 200 个 ID），新数据/人工审核可覆盖旧回填，短期未知保留原位并自动限次刷新。单任务详情从权威 CandidateStore 可修复投影。
- 原任务数据库 `PRAGMA user_version 2→3` **仅加** `annotation_task_statistics` 表，无删除/重建已有 Task、Candidate、GT。旧库保持原搜索元数据兼容；回退至 444 之前必须恢复已验证的任务 DB 备份，否则旧代码可能拒绝打开高版本 schema；不可直接把 `user_version` 改回 2 冒充回滚。**生产尚未执行迁移**。部署前需停写/获得一致性备份（含 SQLite WAL/SHM 或 SQLite backup API）、沙箱模拟升级并验证失败回滚、再按独立授权执行生产升级。
- 定向后端 `97/97`（后加历史回填检查 `4/4`），全前端 Node 在正常子进程权限下 **1421/1421 通过**；沙箱内唯一 Uppy vendor 子进程 EPERM 不属于业务断言失败。没有真实 Chrome 三视口、外部 OSS/远程模型 P95、生产迁移/部署验证。本批**不代表 P0 完成**；下一步需独立审核路由、审阅/GT 当前态审计和外部同步真实来源对接。

## 2026-10-30｜AI 审核连续操作快捷键增量（本批待提交、Chrome 未核）

- 在原 `.ai66-review` 审核工作台中增加候选卡片键盘焦点和高可见度焦点环：左右方向键在本页候选图片间移动，`A` 采用、`R` 拒绝当前焦点图，`Alt+←/→` 在有前后页时翻页。页面明确标注快捷键；失败候选不可做人工采用/拒绝。
- 仅修改原内存 `review.decisions` 草稿，**不会通过快捷键提交审核、入库 GT 或跳过持久操作回执**。输入框、选择器、按钮、候选框编辑、页面加载、提交中和待确认回执时均禁用；仍使用原 `loadReviewPage` 和 `setAiDecision60` Owner。
- 本地 Node 定向通过；安装项目锁定依赖后前端 182 个测试文件中 181 通过，唯一 Uppy 测试因沙箱内子进程 EPERM 失败，提升测试执行权限后该文件 3/3 通过。`node --check static/app.js` 和 `git diff --check` 通过。没有运行真实 Chrome 三视口、生产 OSS/远端模型或生产 DB 迁移。
- 这只是连续审核操作的安全增量，不代表独立路由工作台、真实阶段统计、OSS 性能或完整 P0 已完成。后续仍需正式建立可持续更新的 Task/Candidate/GT 聚合投影，不能以列表 N+1 扫描冒充统计。

## 2026-10-30｜42.24.443 AI 标注任务全历史名称/模型/ID 搜索（本批准确 SHA CI 待核）

- **基线**：442 `2696b6e0` 的 49/49 Actions 与真实 Chrome 已通过。本批只处理 AI 任务列表“前端仅搜索当前 50 条”的真实假空态，不触及创建、审核提交、Worker、GT、OSS 原产物和外部模型执行。
- **原数据源增量索引**：在 `TaskRepository.tasks` 原 SQLite 表加 `annotation_name` / `annotation_model_name` / `annotation_model_id` / `annotation_search_ready`，原 schema version 1→2 加法迁移并保留所有已有行；原 `create` 只对 AI_ANNOTATION 从已冻结的 `request.json` 提取三个非敏感字段，**与插入任务行同事务**写入。任何模型管理的后续修改不改变任务创建时选择的模型名；不创建第二套任务表、搜索服务或自动 GT 写入。
- **历史兼容与降级**：旧任务首个带非空 `q` 的列表请求先查原表中待索引数量，后台线程分批（每次至多 100 条）只读原 `request.json`、同库按项目更新元数据；跨 Web 进程用项目文件锁互斥。API 在全部历史可查前返回 `202 indexing` 与 `indexed/total/remaining`，**不把部分索引的结果渲染成“查无此任务”**；损坏/缺失文件单独标记并返回 `503 index_failed`，须修复来源后由显式“重试索引”恢复，绝不伪造任务名称。普通无 `q` 的列表仍使用原轻量 status+cursor，不执行全历史文件扫描；后台派生索引可能与查询并发，但不改变 Task 状态/正式业务数据。
- **服务端筛选与前端归属**：`GET /api/v60/projects/{project_id}/annotation-tasks` 在原 `status/cursor/limit` 外增加 `q`（最多 120 字符）、可选 `retry_index`；在原 SQLite `WHERE` 条件中同时匹配任务 ID、冻结任务名、冻结模型名称、冻结模型 ID，转义 `%`、`_`、`\\`，再按 `(created_at, task_id)` 游标分页。原生 JS 同一搜索输入 300ms 防抖，条件变化立即中止旧 fetch 并废弃旧代次/游标；索引中显示可核验进度且后台短期重试，导航离开不继续请求、不弹旧错误，故障显示重试按钮。没有新增独立轮询器或前端缓存系统。
- **证据**：增加 TaskRepository 67 条异构任务跨页命中与 literal LIKE、旧任务每批限量回填/损坏及修复、FastAPI 202→完整搜索/搜索长度、Node Owner、Playwright 历史搜索与首次索引进度用例。需在准确新 SHA GitHub CI 中核后端/Chrome；本环境缺 Python/浏览器依赖不能替代 CI。真实大库、OSS/远端模型冷启动及 P50/P95 **尚未现场测量**，三视口视觉审阅与完整业务闭环仍未验收。
- **仍未完成 P0**：任务列表候选/已审核/正式入库/外部同步的阶段性真值聚合；独立路由持续审核工作台与更完善的键盘/尺寸交互；真实 OSS、远端模型、大素材库浏览器 HAR/后端 SQL 分段性能；三视口改前改后截图人工评审。不可据本批宣称全部 P0 完成或可以直接部署生产。

## 2026-10-30｜42.24.442 审核操作 ID 与原 GT 状态的强绑定（精确 SHA CI 待核）

- **精确上一版基线**：441 `d5d3ac10` 已检查 49/49 GitHub Actions 全部成功，三组原 Chrome 分片与 AI Annotation Recovery 均通过；这是代码本身 CI 通过，不等于生产 OSS/视觉 P95 已验。
- 在 441 `d5d3ac10` 上完成更严格的故障恢复审计：旧请求 A 已写 pending 意图，但校验失败；后续新请求 B 正式完成，若只按任务已非待审核且存在 result/confirmation 文件恢复，会把 B 结果**错归为 A**。这不应发生，即使 A 的客户端早已收到 400。
- 仅在原 `review/result.json` 和 `review/confirmation.json` 记录该次可选 `review_request_id`（旧客户端不传时不写），`_annotation_review_recover_completed` 必须同时核对持久任务状态、对应权威文件、**同一原操作 ID**，才能返回 200 completed；否则仍返回 202 pending，不会重复执行，也不会误认其他人的审核结果。正常成功回执和 Task/Candidate/GT 已有路径不动。
- 浏览器查询结果增加 `receipt.request_id` 与本地 pending ID 精确校验；Playwright 503→pending→completed 用实际请求路径 ID，而不是伪造固定编号。新增 FastAPI 同任务 A/B 不得互认、确认文件与 Task QUEUED 的 ACK 丢失恢复，受控测试 39/39 通过。完整 Node、准确 SHA 真实 Chrome 和外部模型/OSS/P95 仍待核，不部署、不修改正式数据。

## 2026-10-30｜42.24.441 AI 人工审核提交断线防重与可核验回执（精确 SHA CI 待核）

- **上一版本 CI 事实**：440 `3aa8301a` AI Annotation Recovery、Frontend Runtime Stabilization/真实 Chrome 均成功，49 项中 48 成功；通用 Release Regression 的两个 Linux 暂停进程状态立刻判定用例先后在首轮及单 Job 重跑失败，因此该版本 CI 非全绿，本批不把它伪装成无关紧要的绿版，也不在 AI 专项里混改进程控制。
- **问题与约束**：原 `completeAiReview60` 仅发一次 POST，但若服务端已经修改 Candidate 并唤醒正式 GT Worker、HTTP 回执在代理丢失，浏览器再点会得到 409 且不能分辨「真的没提交」和「已经入库中」；禁止通过简单重试重复提交，也不能将 Candidate 的审核成功冒充正式 GT 已写入。
- **后端**：原 v60 `AnnotationDecisionReq` 仅增可选 `request_id`，旧无 ID 调用保持原合同。复用每个 Task ArtifactStore 与已有 `review.lock`，在修改任何候选前写入按 ID 哈希命名的 pending 意图，并在成功响应后写 completed 回执、冻结原请求内容 SHA256；同 Task/ID/内容重复 POST 返回原响应 `idempotent=true`，同 ID 改决策/映射则 409。新 `GET .../annotation-tasks/{id}/decisions/by-request/{request_id}` 查询持久结果，使用原锁等待在途 POST，仅在原 Task 已离开 AWAITING_CONFIRMATION 且已有 `review/result.json` 或 `review/confirmation.json` 的权威事实时恢复「已改状态但 ACK 未落盘」的回执；不满足条件返回 pending（202），不盲目重新执行 Candidate/GT 副作用。此 pending 可能需要人工核验，**不得宣称所有进程崩溃场景自动恢复**。
- **前端**：审核页提交同 Task/Project 稳定操作 ID 写入本地 pending，原按钮禁并发、收到了不确定 HTTP 结果先按 ID GET，未完成/断网只保留「查询审核结果」而不能发第二个 POST；只有收到 completed 原结果才关闭当前审核并开始原 Task Poller 的正式 GT 入库等待。旧弹窗/其他任务的 UI 结果按 review 实例和导航 action 隔离。未重写 CandidateStore、Annotorious、任务/GT/轮询 Owner。
- **测试**：后端增加提交/重复/配置冲突/非法 ID/缺少回执/pending 防二次执行/持久 Task 状态转移后的恢复回执；原 Playwright 加入真实 Chrome 模拟 POST 503→第一次 GET pending→显式查询 completed，断言只有一次审核 POST；Node Owner、导航栅栏与旧审核测试已同步。隔离 FastAPI 37/37，完整 Node 1419/1419，真实 Chrome 须待准确 SHA CI。不包含生产 OSS 现场、真实视觉模型与真实 10k+ 素材 P95。
- **剩余 P0**：AI 任务名称/模型跨全部历史的服务端索引查询；候选/人工审核/正式 GT/外部同步各阶段真实计数；独立路由连续审核工作台的产品级视觉与键盘操作；真实外部存储/模型冷启动性能、三视口前后截图人工审阅。不直接部署生产，不删除/修改原素材或 GT。

## 2026-10-30｜42.24.440 原 AI 任务状态服务端筛选续批（准确 SHA CI 待核）

- 439 `3442fd23` 的 49 个精确 SHA Actions **49/49 全部成功**；唯一初红是与本 AI 创建无关的 Windows `test_training_cancellation_kills_worker_and_never_publishes_success` 进程启动 `started.marker` 时序断言，已对失败 Job 单独重跑通过。AI 创建真实 Chrome 含三视口截图和标注 API 都成功，但这不代表生产视觉满意度与 P95 达标。
- 原 AI 任务列表 `/api/v60/.../annotation-tasks` 是 50 条 cursor 分页后才在浏览器筛 `status`，会出现当前页无符合任务但更早页有的**错误空态**。440 在原 GET 增可选合法 `status` 参数，直接传给唯一 TaskRepository `statuses`，再排序分页；没有排队任务的当前页不再额外扫描全局待执行队列。不遍历任务 payload、不新增索引迁移、保持无过滤 API 返回格式。
- 前端仅改原 `renderOps427`/`refreshAnnotationTasks60` Owner：状态变化重置 cursor 首页；请求身份包括 project/page/cursor/status，取消旧的 fetch、旧结果/旧错误隔离；同一在途查询继续 single-flight；中文状态复用 `PlatformCore.annotationTasks.annotationTaskView`，当前状态页可显式刷新且按钮有即时反馈。本页名称/模型搜索保留，不冒充全历史搜索。
- 证据：新 FastAPI 测试构造待审核和多个排队任务，证明状态过滤在 `limit=1` 游标之前执行及非法状态 422；原 Playwright 测试改为验证翻页后状态筛选重置至历史首页，增加快速切换 QUEUED→SUCCEEDED 的迟到响应保护；前端静态 Owner 合同已补。定向 API/Node 通过；需要完整 Node、440 精确 SHA Chrome 与真实素材规模 P95 补验。
- **下一待办**：任务名称/模型的全历史索引查询及正式候选/审核/入库投影；审核 POST 的结果未知时按操作 ID 查询及幂等；独立工作台的连续操作 UX；OSS/远程模型的真实性能与三视口人工视觉核查。不能将状态先筛后分页等同于整个 P0 完工；不部署生产、不改 GT。

## 2026-10-30｜42.24.439 创建任务防重复与原回执恢复（待精确 SHA CI）

- 问题：原创建 UI 只禁止本次打开期间的并行 POST；服务端使用随机 Task ID，若 Worker 已收到任务但 HTTP 回执因代理/网络中断丢失，下一次点击会创建第二个真实 AI 任务。**浏览器按钮门禁并非服务端幂等**。
- 后端：原 `AnnotationTaskCreateReq` 新增可选 `request_id`，旧调用合同完全兼容；服务端按项目 + ID 算确定 `AI_ANNOTATION` Task ID，以本地已有 `FileLock` 对相同 ID 跨进程序列化，并在原 `TaskRepository` 和 `ArtifactStore.request.json` 中记录完整用户请求的 SHA256 绑定。相同配置再次 POST 返回原任务（202、`idempotent=true`），同 ID 改配置 409；`GET .../annotation-tasks/by-request/{request_id}` 只按原 Task 真值查回执，不能把孤立准备产物当成功。没有重建新任务表、缓存或 Worker。
- 创建页：最终配置第一次核对时生成稳定 ID，配置发生变化才更换；提交失败后沿用原 ID，网络错误先查询原回执，成功后展示原任务；既有模型/素材、跨页选择、正式 GT 不变。不重复自动调用模型/创建任务。
- **438 精确 SHA Chrome 结果**：`7254db9c` 的 browser-navigation (1) 有 4 个创建用例失败；三路模型/标签/模板实际响应因新增 `hydrationEpoch` 未初始化，`++undefined` 为 `NaN`、旧响应判断失效，一直显示骨架。参考分页 `referenceRequestEpoch` 与试跑 `previewEpoch` 同源风险。439 在唯一创建草稿一次性初始化全部五类请求 epoch 为 0，增加 Node 静态合同，待 439 Chrome 重验；不得把 438 当作绿版。
- 本地回归：原标注 API 模块加入请求重复、后续模型配置变化仍返回原冻结快照、冲突配置 409、非法 ID 与未知 ID 404，**28/28 通过**；原 Node 增 `request_id` 合同，Chrome E2E 增两次模拟 503 同 ID。完成全量 Node / 精确 SHA CI 后才能宣称本批通过；未运行真实远程模型或生产网络、没有 P95 结论。
- 遗留：人工审核 `/decisions` 的断线提交幂等和状态查询；任务列表历史索引/跨页搜索与聚合列；独立导航工作页；OSS 原图/远程模型的真实浏览器分段耗时和视觉评估。无生产部署和数据变更。

## 2026-10-30｜42.24.438 创建页请求生命周期主动取消续批（待精确 CI）

### 需求与原始缺口

- 用户明确反馈「等不及关闭页面、再打开其他功能时，似乎后台仍在不断请求」，要求过期请求不耗浏览器带宽、不回写新页面、不弹旧错误。437 之前原创建 Owner 已有 epoch/项目栅栏，防止大部分旧结果回写；但 `/materials` 分页、`/materials/ids` 跨页解析、参考素材分页、模型/模板/标签并行 hydration **没有向 `fetch` 传 AbortSignal**，关窗或改筛选不主动中断网络等候。

### 本批改动

0. 437 准确 SHA `be405299` 的真实 Chrome `browser-navigation (1)` 已检查到 105/106：确认页现在可以正确展开，但模拟后端 POST 503 后，创建按钮一直 disabled。根因与上一批相同——提交闭包的 `current()` 又调用了只在创建闭包可见的 `aiCreateIsCurrent429`，catch 自己抛异常，导致按钮永不恢复。438 将它替换为**当前草稿身份 + 原 DOM 节点 isConnected + 项目 ID** 的直接栅栏；Node 源合同明确禁止在提交闭包引用这两个私有函数。437 已成功上传真实 Chrome 失败 trace/截图工件，可复核，不能标记 437 全绿。
1. 仅复用原生 `ai429Create` 草稿和现有 `beforeCloseModal424` 生命周期，在其原模态卸载时调用 `beforeCloseAiCreate429`：取消素材、参考素材、跨页 ID 查询、配置 hydration、单图试跑的已有 fetch 控制器和搜索/提示词计时器，同时使原代次失效，释放本次草稿的选择集合。新打开创建页时也先取消旧草稿遗留请求，不新建请求管理框架。
2. 主素材页同条件在途请求仍去重；不同分页/搜索条件立即取消前一个请求，并用原 `materialRequestEpoch` 栅栏保证取消后的旧响应、旧错误不能覆盖当前页。参考素材新增同一 Owner 的单一 controller/sequence；配置重试按同一 epoch 取消旧的三路并行 HTTP；跨页筛选解析在修改条件/关窗后中断当前游标链，不改变已经确认的选择 Set。
3. 创建最终配置确认中的标签复用原共享 `PlatformCore.materials.labelDisplay` 原样输出，不再重复追加英文 code。版本与 app.js 静态资源键同步；无新路由、数据库、模型、任务、GT、训练 Worker 或外部存储接口变动。

### 验证边界和接续

- `tests/frontend/ai-annotation-owner.test.mjs` 增补模态 close hook、五类 fetch 取消控制器、material/reference/hydration 真实 signal 传递的静态合同；既有 Playwright 关窗重开用例增断言草稿释放。需最终 SHA 真实 Chrome 检查路由延迟、关闭后重试/错误不串窗、批量 5 页筛选不重复。
- **AbortController 只保证客户端不再等待旧 HTTP 结果；不能断言服务器已经接受的请求停止了 SQL/OSS/模型计算。** 要减少服务端已启动查询的工作量，仍须后端接口有界执行和现场追踪验证；不是已达到性能 P95 的证据。创建 POST 和审核正式入库均未主动取消，也不得因为页面关闭就推断持久任务失败。
- 本批尚未触及任务全历史索引搜索、状态聚合列、服务端创建/审核操作幂等、独立路由、OSS/远程模型 P95；这些仍按原 P0 优先级续做。无生产读写或部署。

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
