# P1E–P1G 模型版本与转换历史只读交付

基线：本地/远端 `5fd293cb541642697544de7ae4fe8549fd1572cb`，唯一分支 feature/external-algorithm-publishing，工作区干净，仅当前工作树。VERSION.txt 与缓存标识分离。本轮连续授权A–E；设计/计划技能用于落实已确认需求，不重复请求阶段批准。

## 合同与最小设计

| 场景 | 原Owner/API | 本轮处理 |
|---|---|---|
| 算法摘要 | AlgorithmSqlStore / GET v12 algorithms?summary_only=true | 原摘要仍含所有版本及外部分析；新增asset_view=true的有界分页与筛选，复用同一SQL仓储，版本deferred显式标记 |
| 版本列表/详情 | AlgorithmSqlStore / GET v12 algorithms/{id} | 原详情展开全部版本、report/evaluation/lineage。asset_view分支分页列出版本，version_id按需提取单版本安全元数据，不扫描模型或GT |
| ModelArtifact | ModelArtifactRepository | 只读选中项目/算法/版本的已登记记录，不调用v64 OSS配置/扫描/审计；转换产物仍是Artifact，不变成训练版本 |
| 转换历史 | ConversionHistoryProjection + 原durable overlay / GET v42 ...versions/{id}/deployments | asset_view安全投影，保留原版本作用域/分页/筛选/缓存，不创建全项目扫描或任务状态机；原API默认行为保持 |
| 原页面 | AlgorithmListRuntime / openVersionConvert428 | opt-in按钮，原登录/API/导航/内存路由/请求生命周期保留，旧写入与执行界面不迁移 |

选择扩展已有HTTP端点的显式只读投影，而非使用v64冒充通用资产清单、复制完整版本到前端伪分页，或另建资产库/任务中心。仅显示已保存证据，当前指针缺失不推断；文件后缀不表示兼容性，登记/上传/可下载/验证/发布分离。

## 实施计划

- [x] A：限定仓储SQL/端点/历史投影核查；安全字段白名单，不回传绝对路径、密钥、冻结GT或日志正文。补分页/身份/缺失值/非全量读取定向测试，先见失败。
- [x] B：模型资产/算法版本Vue页：项目算法摘要分页、选择后版本分页、单版本详情、来源/文件/元数据/分源指标/lineage与已登记Artifact。只读GET，转换历史按用户选择进入。
- [x] C：版本转换历史Vue页：原服务端分页和筛选值、详情诊断、任务/产物/数值/硬件/发布五类证据独立，保留返回筛选及页码。不新增轮询/任务操作。
- [x] D：复用PageHeader与实际共同的只读详情/状态展示，四模块中性视觉、桌面/平板与异步布局；原CRUD业务不重写。限定Chrome及真实入口临时库冒烟、只读/迟到响应/退出/项目隔离。
- [ ] E：类型/Vite、必要Node/Python、原缓存合同、资源打包包含性；更新交接；fetch后普通提交推送，准确SHA既有CI和artifact下载核验。不得以本地/CI冒充现场部署。

## 实际完成与入口

原登录后使用 `/?vue_model_assets=1` → 算法列表 → **Vue 模型资产**。旧版本行同时提供 Vue 转换记录入口。模型资产中选择算法才读取版本，选择详情才读取该版本元数据及最多20条登记资产；转换记录按选中版本读取，每页20条，支持原后端状态/目标/芯片/精度/CSC/日期筛选。筛选候选来自后端记录投影，安全过滤掉含敏感文本的值，保留其余原始值供精确查询，不复制 SDK/芯片兼容枚举。

上下文始终是 project→algorithm→version。Vue Router memory不改旧hash；按项目保留筛选/版本选择，按算法+版本身份保留历史页码，切新版本重置历史查询。仅保存页面选择，不缓存业务真值，重新进入重新GET核验。项目变化/退出abort，迟到响应再次核对项目/页面/代数。桥接不给新页post方法，限制精确项目和版本URL，不新增轮询，不取消后台任务。

版本文件只显示文件名/已保存大小与SHA，不返回内部路径，不推断下载可用性。缺失mAP50显示未提供，0保留；版本/Val/Test分组独立。原登记资产的PENDING/UPLOADED不等于已发布，converted记录不进入训练版本列表。任务执行、产物文件存在、完整性、数值一致性、硬件和发布证据分别展示；缺字段明确未提供证据。当前版本只依赖持久化current_version_id，不推断最优/最新版本。

页面“返回完整管理”回算法列表；“原版本转换 / 验证”先返回原列表，再通过原openVersionConvert428打开同算法/版本弹窗，写操作仍归原页面。关闭开关刷新即可回退。原服务节点、字典CRUD和导航菜单保持原业务所有权。

四模块统一PageHeader层级、间距、主题色和Element Plus反馈。两个新页共享确有共同合同的ReadOnlyFacts；版本详情独立组件。桌面双栏、平板单栏，表格限制纵向高度并内部滚动，不让20条算法把版本区挤到数屏之后；详情只有一层抽屉。未建立第二套设计系统。

## 有界API与安全

新增的是原端点的显式 `asset_view=true` **只读响应投影**，不是新的URL或Owner：

- v12 algorithms：仍要求summary_only=true；page≥1、page_size≤50，名称query、原记录type/industry/source/status及updated/created/name/name_desc排序。服务端SQL COUNT/LIMIT/OFFSET，不加载版本payload/report。
- v12 algorithms/{aid}：asset_view无version_id时版本分页；指定version_id时仅提取该版本的静态白名单JSON字段，关联ModelArtifactRepository已登记记录。不存在或身份错配返回404；原鉴权和get_project保留。不能使用旧完整详情满足安全范围，因为它会展开全部版本及评测/报告/冻结证据。
- v42 ...versions/{vid}/deployments：复用原ConversionHistoryProjection缓存、分页、筛选和durable overlay，先从原SQL确认版本归属。安全投影仅返回有界字段和最多20个输出；仅在授权deploy根内检查文件是否存在，不扫描模型/GT、不校验SHA、不新增下载链接。不改变原默认响应及任务状态机。

安全诊断遮蔽URL、绝对路径、UNC和明文/带引号凭据；白名单不含冻结GT、完整报告、训练数据或日志正文。独立审查发现并修复了原始筛选候选绕过脱敏、带引号JSON凭据/UNC未覆盖两处漏洞，均有定向回归。安全候选被移除而非替换成不可查询的伪值。

## 验证证据与复现

- Python：`pytest -q --confcutdir=tests/unit tests/unit/test_model_asset_views.py tests/unit/test_conversion_history.py tests/api/test_model_asset_views.py tests/unit/test_algorithm_sql_store.py` **36/36**。覆盖SQL有界摘要、禁止full reader、跨算法/版本、缺失/0/Test、原1000条历史增量缓存/分页/overlay、登记资产作用域、脱敏。先观察新增合同失败再实现；无全仓Python测试。
- Node24：入口缓存/桥接/只读API/缺失值/错误脱敏等10个文件 **48/48**；原算法列表/lineage/数量三个文件 **25/25**。本机默认Node20不支持直接导入TS，新用例须用Node24（与Frontend CI一致）；不跳过测试。
- `npm run build --prefix frontend`（vue-tsc + Vite）通过；四模块共用按需JS **778.67 kB / gzip214.09**，CSS **112.56 kB / gzip16.38**。相对前批JS gzip约增加8.38 kB；未opt-in的旧首屏不下载Vue制品。无CDN运行依赖。
- `npm run test:browser --prefix frontend`：四模块Chrome **11/11**。新增两例覆盖摘要懒读/详情/105条历史真实分页请求、页码返回、GET-only、迟到响应/退出/项目切换和403区分。HTTP夹具截图位于test-results/vue-catalog，与真实入口证据区分。冷启动夹具原legacy异步mount与测试导航竞争已通过明确等待fixtureReady解决，不改变业务时序。
- 真实入口：根目录 `python tools/test_vue_productization_server.py`，另终端frontend目录 `node tests/real-model-browse.acceptance.mjs`。固定127.0.0.1:8028、全新临时DATA_DIR、原index/app/main/登录/API/SQL仓储；lifespan关闭，所有SDK探测明确禁止。22个合成版本、25个保存的合成终态转换记录；**没有创建或执行正式任务**。原登录、懒读、历史分页/返回、脱敏、原版本弹窗和JS/CSS200、pageerror=[]通过；新只读路径写请求只有原登录POST。
- 同一临时真实入口执行原 `frontend/tests/real-entry.acceptance.mjs` 通过：原字典CRUD/回执恢复、两个旧管理页面可达、节点GET和登出。节点为合成心跳，不代表硬件通过；本轮未调用真实SDK。
- 已查看桌面1600与平板768截图：真实模型/转换/版本/诊断位于 `test-results/p1eg-real-entry/`（receipt.json）；字典/节点位于 `test-results/p1bd-real-entry/`。Chrome隔离夹具布局另有1366/768截图。截图/回执是本地生成证据，不声称CI执行了本地真实入口脚本。

## 离线资源、提交与CI

入口styles/app/main三资源统一缓存 **42.25.609**；仅改变的algorithm-list-runtime与桥接另更新自身缓存，未改其他业务模块缓存。VERSION.txt保持 **42.24.592**。CI沿用Frontend Runtime现有构建/Chrome/upload流程，新增投影测试加入已有Algorithm SQL Store job，不新建工作流，不手工触发无关工作流。

联网构建机 `npm ci --prefix frontend; npm run build --prefix frontend` 后，必须整体包含 `static/vue-catalog/`。源码git archive不会包含忽略的制品目录，使用前批文档的追加ZIP命令，或将准确SHA CI artifact中的该目录还原至同SHA源码根。CI artifact为 `vue-catalog-preview-<SHA>`，推送后核对实际上传条目并下载验证JS/CSS字节与本地一致；再验证源码+Vue ZIP包含两文件并通过CRC检查。最终准确SHA与CI/ZIP回执保存在test-results，最终回复报告，避免为自引用SHA制造未验收提交。

上述是**源码和离线前端资源包含验证**；不包含Python wheels/系统库/容器/SDK的完整离线安装验收。目标机断网安装、生产数据、真实模型格式质量、数值一致性、芯片实机推理和发布均**未验证**。历史数值验证独立API返回大量报告/明细，本轮不自动扫描；只显示历史记录中已有安全字段，缺失则明确“未提供数值验证证据”，允许回原验证页面查看。没有可靠全项目统一资产查询，范围明确为算法/版本及登记关联。

## 后续建议（未实施）

若后续授权，先评估原数值验证Owner的单任务有界证据摘要，再考虑增强只读中心；由原ModelArtifact Repository补充明确的下载可用性投影需另行确认授权合同。可考虑按实际性能证据拆分Vue业务chunk；当前增量约8kB gzip未引入另一个运行时。训练、标注、转换创建、发布、后端全面拆分及数据库迁移均未开始。本轮完成P1E–P1G后停止。

## 边界

无生产/真实SDK/训练/转换执行/发布/GT操作；无新数据库、调度、Worker/Agent/Supervisor改动。控制端可部署、Agent通信、设备确认、现场训练/转换验收是不同证据层。保留linux/amd64、linux/arm64、CUDA、Ascend和其他可信设备扩展，不实施硬件适配。完成后停止，不启动后续专项。
