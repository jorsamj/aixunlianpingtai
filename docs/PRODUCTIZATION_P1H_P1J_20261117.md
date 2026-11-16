# P1H–P1J 核心业务产品化

基线：本地/远端 b39d5a1ae82743d78b25e9f8e14bc5a0263f6abd，唯一分支feature/external-algorithm-publishing，工作区干净、仅一个工作树。用户连续授权H→I→J→UI→验收，不重复阶段批准。

## API / Owner 与设计

| 能力 | Owner / 原API | 增量方案 |
|---|---|---|
| 算法管理 | AlgorithmListRuntime / v12 POST algorithms、PUT algorithms/{aid} / AlgorithmSqlStore | 在P1E原ModelAssets页开启管理模式，不另建列表中心；按需读取安全基本信息，再用原写接口提交四字段，成功后GET权威记录；未知结果停止重复提交 |
| 训练任务 | TaskRepository / v62 tasks、tasks/{id} / task_to_public | 复用原游标分页，加状态/任务ID或阶段查询和reader_view；限TRAINING/TRAINING_PREPARE。复用原public状态，不读取全局queue candidates，不扫描任务目录，不加轮询 |
| 报告 | 原v44 / Task ArtifactStore finalized result + 版本SQL + reports.build_version_report | reader_view只读有界摘要，durable finalized优先；不进入完整报告的GT快照/素材/模型读取。复杂PR/混淆矩阵/错误样本委托原报告/独立评测Owner |
| 导航 | 原NavigationStability / PageRequestScope / API与登录 | 沿用现有Vue桥接和memory router。只开放明确页面和项目URL；任务/报告无写方法；原高风险操作通过原导航与公开函数交回Owner |

选择扩展原显式投影，避免新建页面状态真值/Repository，以及调用完整接口后在Vue过滤敏感或大字段。报告复杂工作台暂保留，核心摘要展示已有真实指标与来源。不存在/尚未生成/损坏/超出读取边界分别反馈，不生成分数或ETA。

## 实施计划

- [x] H：先补算法基本信息安全投影、原新增/编辑与外部只读合同测试；在ModelAssets复用列表/版本/筛选，新增单编辑抽屉和后端确认读取，保留旧管理入口。
- [x] I：TaskRepository原list增加有界任务查询；v62 reader_view复用游标/状态，按需详情；Vue任务表与详情、配置/执行/错误/报告关联，退出取消、项目隔离，无执行写入。
- [x] J：原v44 reader_view安全报告摘要，版本/任务双入口及身份验证，Val/Test分离、可信预警、已保存训练过程；复杂曲线/样本回原Owner，错误重试与上下文返回。
- [x] UI：延续现有黑白灰+主题色、Page→Surface→Content，不嵌套弹窗；桌面/平板真实截图人工查看，修复实际溢出/请求/布局问题。
- [ ] 验收：仅直接相关Python/Node/Chrome、vue-tsc/Vite、真实入口临时库；入口缓存同号、离线资源构建/ZIP/准确SHA CI artifact下载；更新AGENTS+四份交接，普通提交推送并核对实时远端与准确SHA CI。

## 写入和安全边界

唯一新前端写调用：原v12新增本地算法及基本信息PUT（name/remark/industry/algorithm_type），外部只读保护仍由原后端执行。无新写端点，无版本/任务/报告写入。原接口没有创建幂等回执，不假装可自动重试：未确认时保留待核对提示并阻止重复创建。未来amd64/arm64、CUDA/Ascend扩展保持；不改数据库schema、调度、lease、Worker/Agent/Supervisor、GT或硬件适配。不部署生产。

## 实际功能与调用合同

入口：原登录后 `/?vue_algorithm_manage=1&vue_training_tasks=1&vue_training_report=1` → 算法列表 → **Vue 算法管理** 或 **Vue 训练任务中心**。三个开关独立，原vue_model_assets仅只读语义不变，原菜单/登录/内存router仍唯一。管理模式沿用同一个ModelAssets页面、项目选择及筛选状态，未新建算法数据库/缓存中心。原内部页面ID继续复用P1E名称，实际页面标题区显示“算法管理与模型版本/正式管理”。

- 算法：摘要SQL分页/名称/type/行业分类/source/status/排序；选算法读取正式版本，单版本详情、原资产/转换历史继续可用。基本信息详情新增算法ID/来源/当前版本，授权文本原样提供（四字段最多各16k，超过则禁止本页编辑、指向原管理，不能把截断值写回）。新增本地算法和基本编辑只发送四个原字段，原服务端外部master_data_readonly保护不变；旧历史无外部只读标志时仍遵循原写入判定，不能凭source标签替代后端拒绝。版本行可直接打开对应训练任务或报告。
- 写响应增加显式asset_view=true时仅返回algorithm.id，防止保存历史算法时把全部版本/冻结字段发给Vue；默认原响应和写入行为不变。Vue再GET `asset_view=true&basic_only=true` 核验身份及四字段精确一致才显示已确认。写入Owner内部原有完整读取未重构，不承诺解决旧写接口整体性能。
- 创建或编辑前保存project-scoped sessionStorage待确认packet。只在明确的原写请求400/401/403/404/409/422拒绝或成功GET核验后清除；网络异常/JSON损坏/写后GET失败保留。退出只abort HTTP，不能承诺撤销已到达服务器的算法保存。不存在原创建幂等回执，因此不按名字猜测已创建、不自动重复POST；可回原管理核对，用户显式确认后解除本次待确认。这个提示是客户端防重复，不是服务端exactly-once保证。
- 训练任务：`GET v62 tasks?reader_view=true&kind=&status=&query=&limit=20&cursor=`，原TaskRepository SQL中先project/kind/status/任务ID或stage搜索，再稳定created_at/task_id游标分页。kind仅TRAINING/TRAINING_PREPARE，status候选来自后端TaskStatus；显示状态来自原task_to_public（例如resource_waiting→WAITING_RESOURCE），筛选为持久状态，不伪造第二套状态机。无全量任务扫描、全局queue_candidates、GPU空闲推算或轮询。分页不宣称总数，明确本页条数与上一/下一页。
- 当前页最多100条任务的算法/版本关联由原SQL训练任务索引一次分组查询补齐；多引用或payload身份冲突不任意挑选。可见页payload仅有界32k读取，详情512k；大字段标记DEFERRED，任务真值仍显示。配置与“请求执行配置/实际执行证据”分组，Worker/resource_key来自Task，节点/开始时间仅取已保存finalized execution；未有证据不推断分配。未知ETA不展示倒计时。TaskReader只限GET，无取消/恢复/分配能力。
- 报告：原v44 `reader_view=true`，从Task或版本按需进入；project/TaskKind/SQL版本任务引用和保存的job/lineage身份有冲突时拒绝，不做全项目历史回退扫描。Task ArtifactStore的finalized training_report优先于旧job.metrics，原reports.build_version_report/diagnose_training_history负责指标来源与趋势。Val/Test独立，mAP缺失为null，已有0保留；metric_credibility仅来自durable finalized，不制造可信度或质量通过结论。
- 每个legacy/result JSON最多2MiB，超出DEFERRED；缺失NOT_FOUND、未生成NOT_GENERATED、仅有记录结果PARTIAL、损坏ERROR分别展示并支持重试。不访问冻结GT/snapshot、素材集合、模型权重或完整遥测数据库。返回字段白名单，历史最多200条、预警最多20条，诊断复用既有脱敏。PR曲线/混淆矩阵/错误样本仍由原复杂报告Owner负责，提供明确原完整报告入口；本轮未重建图表评测工作台。

## UI / 生命周期和性能核验

复用原PageHeader、ReadOnlyFacts、Element Plus，单层算法编辑/版本/任务抽屉互斥，报告为独立阅读页。桌面双栏、平板单栏，任务/版本表内部高度有界，筛选、分页及来源选择保留。新旧入口通过原setPage与公开openVersionReport429/openJobReport429/openVersionConvert428交回Owner，不修改旧DOM内部状态。Vue API仍唯一原api通道。

新增Task/Report页面无写方法，桥接精确限制项目与报告job URL；算法写能力只在管理模式资产页，禁止DELETE、版本路径及斜杠伪算法ID。原PageRequestScope/导航leave联动HTTP abort、unmount和迟到响应项目/页面/代数校验。局部useReadScope请求去重、监听器移除，不建全局轮询/任务缓存。报告返回任务保留游标，返回算法保留筛选和选择。

独立审查发现并修复两点：显示脱敏/截断文本不能作为编辑原值；写后GET403/404不能当作写请求拒绝清除待确认。均有定向合同回归。真实截图人工查看确认桌面1600/平板768无横向溢出；管理动作合并一行、表格限制高度，不增加嵌套弹窗。未做全平台内存/性能审计或长期压测。

## 测试与真实入口证据

- 定向Python **41/41**：新API/任务查询/报告4单测+2API，原模型投影/API与AlgorithmSqlStore回归。无全仓Python、训练或硬件测试。
- Node24 **76/76**：算法管理写后读取/未知结果、原桥接能力/身份、原算法列表、入口缓存等13个直接相关文件。新增业务先观察缺失合同失败再实现；不删除原断言。
- 前端原11+新增3项Chrome **14/14**。新三例：本地算法新增/编辑/外部只读、任务游标/报告来源和返回/403、创建未知结果跨导航防重复。无全仓浏览器本地重复运行。
- TypeScript/Vite构建通过，所有运行依赖本地打包。缓存styles/app/main统一610，仅改变的algorithm-list-runtime和Vue桥接更新自身标识；VERSION.txt保持42.24.592。
- 真实入口脚本：根目录 `python tools/test_vue_productization_server.py`；frontend目录 `node tests/real-core-productization.acceptance.mjs`。强制全新临时DATA_DIR、固定loopback8028、原登录/API/SQL/TaskArtifactStore，lifespan off，禁止SDK探测，不运行Worker。25个保存的合成终态Task及报告；它们不代表实际训练/硬件质量。只在隔离数据中新建/编辑本地算法。
- 真实入口通过算法新增后GET确认/编辑、Task游标分页、任务节点证据、finalized优先、Val/Test独立、报告脱敏、返回保留页码和原完整报告/管理入口。JS/CSS200，pageerror=[]。回原训练页面时原Owner有既有POST recovery-query（代码已核实只读取≤100条恢复证据），不等于新增恢复写入；本轮新页面业务写请求仅原算法POST+PUT，无训练/转换/发布执行。
- 桌面/平板真实截图及receipt.json位于 `test-results/p1hj-real-entry/`；HTTP夹具截图在 `test-results/vue-catalog/`，二者区分。最终SHA CI/上传制品在推送后读取，并保存独立回执，避免自引用SHA产生新的未验提交。

## 离线交付和未验证边界

沿用原Frontend Runtime CI构建+upload，artifact `vue-catalog-preview-<准确SHA>`；新Python投影单测加入已有Algorithm SQL Store轻量job，API合同在同工作流已有完整应用依赖的Chrome job，不新建工作流。推送后只核对自动触发结果，不主动启动无关工作流。

源码git archive不含忽略的static/vue-catalog，正式源码+前端包必须追加该目录两文件，或下载同SHA CI artifact还原static/vue-catalog；须核验两文件存在、CRC和字节一致。构建/资源包含核验不是目标机断网安装验收；不包含完整Python wheels/系统库/驱动/SDK。生产A800/4070、真实训练/推理/评测、真实硬件、现场离线安装均未验证。不以合成分数或CI代替生产验收。

## 后端后续拆分清单（建议，未实施）

1. 算法HTTP Router可按已稳定v12管理/安全投影分组；仍注入原AlgorithmSqlStore、外部只读判定及原reference fence，不复制写规则。
2. 训练只读Router可按v62游标列表/详情与查询DTO抽取；TaskRepository/public/ArtifactStore继续唯一Owner，执行/取消/恢复路由独立保留。
3. 报告只读Router可从v44安全摘要抽取，保留项目与版本身份校验；完整报告需要冻结证据、遥测、模型元数据等多Owner，先明确依赖与权限，不能机械拆app.py。
4. 后续若授权，可由原ArtifactStore/报告Owner提供更细粒度分页曲线/证据摘要，改善>2MiB报告；不要为读取而扫描GT或引入第二份报告库。

本轮没有Router抽取或schema迁移。完成后停止，不自动迁移素材库、训练选择器和AI标注工作台。

## 交付前诊断脱敏补修

77bee3d之后的定向安全回归证明，原共享text对Authorization: Bearer的处理只隐藏Bearer单词而遗留令牌正文。补修原共享脱敏函数，Task/Report/原资产诊断共同受益，不建立第二套规则。新增断言先失败、修复后相关10项通过（与上面41项重叠，不累加）。无前端/写入/执行/缓存版本变更；最终新SHA的CI和制品另核对。
