> **当前入口**：[AI 接续入口](architecture/AI_DEVELOPMENT_HANDOFF.md)。P2A/P2B 成果和所有业务安全合同保留；用户已批准独立 Vue M0–M1，以下旧阶段的 opt-in-only/停止条目是历史范围，不能用来阻止已批准迁移。

# 当前架构与独立 Vue 迁移（2026-11-18）

下方 P2/P1 段落保留为历史实施记录。用户现已批准全面迁移，先做 M0–M1；过往“只允许 opt-in / 完成试点后停止”不再约束本轮。当前状态与后续接续以 [AI 入口](architecture/AI_DEVELOPMENT_HANDOFF.md)、[功能/API矩阵](architecture/VUE_M0_FUNCTION_API_MATRIX_20261118.md) 和[功能保留台账](architecture/EXISTING_FEATURE_PRESERVATION.md)为准。

平台服务算法、素材、GT、训练、评测、转换、发布和节点管理。当前旧正式前端 static/main.mjs + app.js 与18个渐进Vue视图并存；后端 FastAPI 模块化单体，AlgorithmSqlStore/MaterialRepository/AnnotationRepository/TaskRepository 等拥有原领域事实；SQLite 持久化、ArtifactStore 持久证据；Scheduler/Worker 领取执行，中央 Assignment 与 Agent Execution Lease 分离，Supervisor 管进程身份。新 Vue 只能使用原会话/API，不获得执行权。

目标为同一 frontend/ 的独立 /app/ SPA，以 Hash 路由避免服务器 rewrite，Router 管新应用页面、Pinia 只存会话/项目和展示态。保留原库构建与旧系统地址；卡片算法库是第一条原生业务链，其他域整页交给原系统，功能等价后再逐个切换，不能删除未替代的旧操作。后端只增必要静态挂载，不顺便拆 app.py 或创建新 Repository/调度器/数据库。

安全边界不变：正式 GT 源 SHA/version CAS、任务 attempt/token/lease/fencing、进程 PID/create_time/command_hash、GPU reservation、远程停止未确认保护、不可变 Payload/收据/Repository CAS/执行锚点、产物身份、删除保护及外部发布 UNKNOWN 回执。普通 UI 不另建安全状态机。

### M0–M1 实际交付

基线 e639bb12585a79556b7a5fd703205368720265c3；M0 5aaf29686faddb5cdf335e0a866515d4809f57e9；M1 4865bea70941443b5a62e56b5c90eca5e6c92aef；本地/CI元数据区分修正 97ae3a517f9e3d98e58e114515cf88647b4a8129；编辑后选中算法详情刷新修正 dc1f2b19c9066e02419f40dfc54223ca132b945d。后续仅文档提交的准确 HEAD 在分支/Git交付记录核验，不将实现 SHA 当作最终 CI SHA。

- `frontend/index.html` + `vite.app.config.ts` 输出 `/app/`；`src/app/` 为真正 Root、Hash Router、Pinia 会话/项目展示态、原生卡片/版本/CRUD。旧 `src/main.ts` 库模式及18个试点保留，彼此整页切换，不同时装载旧 app.js 或移入表单。
- 复用 `api/model-browse.ts`、`algorithm-management.ts`、`useReadScope`、原 api.js deadline/error 和 session 续期。新卡片保留10条/页，旧试点20条不改；写后以原 basic GET 核验，外部只读由原 API/Owner 决定。没有新 Task/GT/算法 Repo、持久业务缓存或回执系统。
- app.py 只有1行静态挂载；原 `/api`、Session中间件和 startup/shutdown 不改。`vue-app-handoff.js` 是旧系统的显式整页交接消费者，原项目/算法/版本核验后调用原训练/转换/发布入口。新App不调用旧全局函数。原root仍默认，不提前宣称全域等价。
- 原FrontEnd CI build脚本在同工程构建两套产物；现有同SHA artifact 加 `static/vue-app/`，无新增 Job/Workflow。新校验器检查 HTML/manifest/依赖/字节 SHA 与 checkout；打包器按源码版本要求两套 CI receipt，拒绝跨SHA/缺新构建，历史只含旧目录的包仍兼容。正式离线安装和官方最终artifact下载未验。

验证与实际功能证据见[接续入口](architecture/AI_DEVELOPMENT_HANDOFF.md)和[矩阵](architecture/VUE_M0_FUNCTION_API_MATRIX_20261118.md)。本地 Node24类型/双构建、API3、Node14、新App Chrome3及真实临时FastAPI创建编辑/旧流程返回已验；旧节点CI失败本地1次通过未复现，未修改其超时或断言。审查发现编辑GET迟到污染新建表单，已先复现再用已有取消机制修复，关键用例补测通过。所有结果均非生产验收；新SHA CI_PENDING。

已知下一步：算法第一批范围之外的原品目/训练状态/综合排序/删除回退仍旧页，其他域 NOT_STARTED；GPT复核底座后才扩展。旧页面、默认训练全参数、专业插件、Task/Agent执行权不退役。原生共享入口约1.08MB（未压缩）为实测构建大小，性能优化列后续，不为本批引入缓存/预加载架构。

|实际问题/未完成|业务影响与位置|优先级/是否需确认|下一步最小处理|
|---|---|---|---|
|算法首批之外功能未原生迁移|Algorithms.vue / AlgorithmListRuntime；原品目、训练状态、综合排序及删除/回退等须去旧完整页，不能正式替代整个算法库|P1；等价迁移不改需求，改变规则先确认|按矩阵逐动作补原生能力，真正缺API再做最小适配，不重建Repository|
|其余业务域未迁移|frontend/src/views/原Owner；新Shell目前是受控旧页入口，不是原生训练/素材/AI闭环|P1；下一阶段由GPT安排，业务需求仍不变|批准底座后按完整业务链迁移，禁止拆掉原参数/GT/回执合同|
|旧节点标题CI失败未稳定复现|frontend/tests/service-nodes.spec.ts、fixture.ts、catalog-preview-runtime.js；本地一次通过，不声称已修复|P1（若新SHA再现）；无需新业务决策|只检查失败Job trace/截图/导航时序，不加timeout或无穷重跑|
|SPA共享入口构建约1.08MB|frontend/src/app/main.ts ElementPlus共享包；可能影响首次下载，但未测生产P95|P2；技术优化无需业务变更|后续有实际网络/首屏证据再按需组件或拆共享包，不新增持久缓存体系|
|旧系统canonical项目交接限制|vue-app-handoff.js / 原bootstrap；隔离多项目访问非canonical旧项目会明确拒绝，生产原单项目不改|P2（测试兼容边界）；改项目策略须确认|保留fail-closed，不用localStorage伪造项目；后续若获批多项目需求再统一处理|

## 历史 P2 技术底座实施与回退

起点：远端/本地 5e9ae26548c07bbff91b37d703d2bf4a8be0b446，唯一 feature/external-algorithm-publishing，工作区干净。

## P2A 独立提交

- frontend/src/main.ts：18 个页面改为函数式动态 import，加载前后检查原 context.signal；仅原 Owner 驱动挂载/卸载。移除每次挂载只包含 `/` 的冗余内存 Router，直接挂载页面；不接管旧 hash 或建立第二导航。
- frontend/vite.config.ts：保留稳定主 JS/CSS 和本地 base，动态 Chunk 采用内容哈希，生成 manifest.json。共享 Vue/Element/组件由 Rollup 复用，第三方原插件不复制。
- tools/verify_vue_offline.mjs：检查 manifest 闭包、动态业务页及全部资源；生成逐文件 SHA256/准确 CI SHA 清单。构建脚本和既有 CI 使用同一校验。
- tools/package_vue_offline.py：同 SHA git archive + 已校验官方 artifact 的整个 Vue 目录组合，不限于两个入口文件；原 vendor/LICENSE/NOTICE/map 原样保留。
- 仅补充按需加载/离线闭包的定向测试，既有 CI 执行 Node、类型构建、Chrome 与隔离真实入口；本地只必要快速构建。

## P2B 独立提交

- platform_core/deployment/catalog_api.py：沿用已有 APIRouter 工厂模式，迁出七条 v39 catalog 路由，复用 ModelArtifactRepository 和 compute_platform_catalog；不反向 import app。
- app.py 仅注入可调用 Provider / 原资源函数并 include_router，保持全局 Session middleware、异常映射、原 URL/HTTP status/revision/operation_id/引用保护。
- 既有 API 测试改为调用真实注册端点，保留所有业务断言；增加独立工厂 HTTP 合同及鉴权/observe_only 的必要覆盖，接入原 Remote Conversion CI。

## 状态边界

Pinia 仅保存字典展示/筛选/加载态和本次操作待核回执，原 API Adapter 仍调用 context.get/post 等原 api 通道；表单临时状态留在组件，页面读取缓存受项目身份、revision、取消约束。算法版本、GT、任务执行、冻结选择、发布回执均不成为 Pinia 持久业务真相。后续跨页面真实路由出现后再评估统一 Vue Shell，本轮不强制建立。

## 后续文档与验证

P2C/P2D 独立源码依据文档：只做数据 Owner/迁移门槛和异构能力证据分层；不加数据库依赖、不迁移 Schema、不检测硬件。

本轮不修改 VERSION、默认入口、生产环境、训练/GT/Worker/Agent/Supervisor/租约或发布写入逻辑。准确新 SHA CI 和产物状态以交付记录为准，不借用起点 CI。

回退按相反顺序 git revert P2B 提交、P2A 提交；离线包必须整包恢复同 SHA 源码与全部 Vue 资源，不混用 Chunk。无数据库迁移，无数据回滚步骤。

## 实际变更与验证边界

P2A 独立提交 3a4d76e；一次本地 vue-tsc/Vite 构建成功，30 个 manifest 闭包文件，18 个业务页动态入口。稳定入口约 0.73 KB、共享 main runtime 650.86 KB，工作台业务 Chunk 13.63 KB；原单 JS 1041.657 KB，CSS 163.751 KB 不变。首屏还需共享依赖，不能只用入口 0.73 KB 宣称整体性能；生产 P95 未测。

P2B 七个函数 AST 在仅替换注入依赖后与原函数完全一致；没有修改算法/素材/GT/候选/模型/发布/Task Repository。既有测试从 app 全局函数转为原注册 Router.endpoint，断言保留。补实际 HTTP 401/200/422 与独立 Router 路径集合检查；TestClient 不启动 lifespan，SDK 通过替身保持隔离。

后续 Router 顺序：第二批 v12 算法管理、v62 训练任务只读、v44 报告只读；第三批素材查询、AI 读取、模型资产及转换历史。优先现有模块工厂，尚未新增 platform_api 或 application/domain 空目录，不创建无意义转发 Service。

离线组合（不构建）命令：

```text
python tools/package_vue_offline.py --sha <准确SHA> --artifact <该SHA制品ZIP> --metadata <官方artifact元数据JSON> --output <新交付ZIP>
```

工具先核 workflow_run.head_sha、制品名称、官方摘要、ZIP CRC、CI 构建来源和每个 Chunk SHA/大小，拒绝其他 SHA、本地构建和缺失文件；git archive 同 SHA 源码包含原 vendor/LICENSE/NOTICE/map，附完整 Vue 目录和元数据。既有 Frontend Runtime CI 继续上传整个 static/vue-catalog（manifest 非隐藏文件）；不新建重复 workflow。新构建必须整个目录同 SHA 交付，并完整刷新页面后使用；不在正在打开的旧页面混装新 Chunk。

准确最终提交的 Frontend Runtime/Remote Conversion CI、官方制品下载与完整包校验推送后填写，不将本地构建等同于 CI/现场离线安装。


## P2B-2：v62 任务只读边界（2026-11-17）

### 候选审计与计划执行

基线 c81460a838551e28cdf7decf480e5cb5102cb0ab，GitHub API 已独立核实准确 SHA 的 Actions 36/36 success；素材摘要覆盖缺陷代码/CI已收口，历史其他间歇表现仍未完全解释，不重复素材测试。远端未新增提交。

| 候选 / app.py 中边界 | 原 Owner / 依赖及副作用 | 风险与测试 |
|---|---|---|
| A v12 算法列表/详情：2 GET，包含 summary_only、asset_view、版本投影；其他评测/下载 GET 不纳入该组 | AlgorithmSqlStore、list_algorithms_internal、successful counts、转换产物 Repository；列表会读写原 Bootstrap snapshot，持有全局锁和 revision 栅栏；SQL Owner 还保留历史兼容初始化 | 缓存与启动全局耦合高，若安全迁移需额外缓存接口；已有 model_asset/core_productization 测试。此次不选 |
| B v62 项目任务列表/详情：2 GET | TaskRepository、ArtifactStore、AlgorithmSqlStore 训练版本引用、WorkerInstanceService、task_to_public、原项目/任务检查；普通列表读取原 worker/queue，reader_view 不扫描全队列 | 依赖可延迟注入，无启动服务绑定，无反向 import/cycle；已有 unified task HTTP 与 core_productization/reader 单测。此次选择 |
| C v44 单任务报告：1 GET（quality-center 另有1 GET，不与该组混拆） | TaskRepository/ArtifactStore/AlgorithmSqlStore、job.json、enrich_job_runtime、历史版本/报告及指标回退；报告函数超过200行 | 历史身份/补全与兼容依赖较重，不能仅凭 GET 认定纯读取；已有报告/API测试。本轮不迁移 |

三组均继续受 app Session middleware 保护，项目校验沿用 get_project；任务详情另经 _runtime_task_for_project 核对归属，不借模块化加强或放宽权限。没有新增项目授权策略。A/C 保持原状，不宣称已完成其全部副作用审计。

已执行计划：锁定准确基线并隔离副本 → 比较候选 → 提取 B 两个端点 → 定向 HTTP/原 Owner 投影与 AST 核验 → 更新当前摘要/功能台账 → 单分支提交推送。原 D 盘工作树及既有目标分支工作树保留；后者还有 annotation 等未提交工作。本次隔离副本起点干净，没有历史两个素材诊断工具的未提交修改，未重建或纳入它们。

### 组合与合同

迁移前：app 路由函数 → 原任务/产物/算法引用与投影 Owner。
迁移后：app include_router(create_task_query_router(...)) → platform_core/task_runtime/query_api.py 的两条 GET → 同一 Owner；app 仅通过5个延迟 Callable 注入原项目/任务检查、Repository、ArtifactStore 和算法路径，保持运行时替换/初始化顺序。原取消/提权/claim/heartbeat/Worker等全部留原位，无第二存储、任务服务或空转发层。

两函数相对基线 AST 完全一致（只将 decorator app 改为 router），包括同步类型、签名、Query 默认值/限制、异常、分页排序、响应缺失/null/0及普通/reader_view 分支。注册位置保持原列表/详情位置；递归核验真实应用两条 GET 各出现一次，unique_id 保持原函数名和路径。Session、错误处理、缓存/条件请求行为不改，没有新增缓存。

GET 仍可能触发原 Repository 构造、SQLite/历史兼容初始化及原产物读取，本轮不声称旧实现零文件系统副作用；原 worker runtime/queued_candidates 是只读投影，未加入状态写入/执行操作。未修改任何 Repository/schema 或历史兼容逻辑。新模块不 import app。

### 定向验证与边界

命令：`python -m pytest -q --confcutdir=tests/api tests/api/test_core_productization_views.py tests/unit/test_training_reader_views.py`，5 passed；只有已有 on_event 弃用警告。原断言完整保留，仅将直接 app 函数定位改为注册 Router.endpoint（与 Catalog 测试方式相同）。新增实际 app HTTP 覆盖401/有效Session、200、404跨项目/缺任务/缺项目、422 limit/kind/status/cursor，两个视图游标分页和原Repository顺序一致、GET不改既有任务状态/updated_at；不启动 lifespan/Worker。

一次 AST 对照和实际路由递归核验成功，git diff --check 通过。首次测试因本机 FastAPI 使用 _IncludedRouter，直接平铺 app.routes 未找到端点；修正测试定位后通过，未改产品或削弱断言。复用既有 Algorithm SQL Store CI 执行该 API 测试，不增加工作流。

未跑全仓、浏览器、真实训练/转换/硬件，不接触生产。当前改动准确 SHA CI 推送后只取一次状态，未完成不能称验收通过；生产/离线现场未验。回退：在唯一长期分支对本次提交执行普通 git revert，再正常推送；无数据迁移或回滚步骤。P2C/P2D 仅设计，未实施。


## P2B-3A：普通任务列表证据按需读取（2026-11-18）

基线/远端核实为82b7a10805ecb1e592769e77736e43a361dddfef，隔离副本干净，其他工作树和诊断工具不动。仅在query_api.py普通列表取页后判断：有QUEUED且非TRAINING任务时，才各读取一次原Worker快照与完整全局队列；否则传None。空页、仅终态页、仅QUEUED TRAINING页跳过两项读取；TRAINING_PREPARE、AI_ANNOTATION、MODEL_CONVERSION、DEPLOYMENT_TEST及混合页保留完整证据。没有项目过滤/LIMIT，没有替换原投影或修改队列精确性定义、队列位置、排序、游标、Session、项目隔离、reader_view或任务状态；原Repository/Worker/public.py/app.py均未改。

定向测试：`python -m pytest -q --confcutdir=tests/api tests/api/test_core_productization_views.py --disable-warnings --tb=short`，12 passed（既有3项+新增9个参数场景）。新增测试先在旧实现复现空页/终态/TRAINING三项不必要读取，再实施优化后全绿；完整响应与原task_to_public显式传入完整证据的结果一致，并核验次数、队列位置及持久记录不变。TRAINING_PREPARE精确性仍可由兼容在线测试Worker证明；跨项目其他资源候选仍使原证明为false。混合场景训练与准备使用各自资源队列，不将同资源但不可领取任务导致的原保守false误判为缺陷。

另运行原tests/api/test_unified_task_runtime.py的3项合同，3 passed。通过仓库外临时pytest插件提供临时SQLite、项目和TestClient夹具，不启动lifespan/真实Worker；原测试代码/断言未改。首次临时夹具数据库路径与原Repository重开路径不一致导致重开用例404，改为原Provider在临时DATA_DIR初始化后3项通过，临时插件自动删除。测试涵盖原队列/提权、持久重开运行态和取消合同，仅隔离测试状态写入。

git diff --check通过；仅query_api.py、既有API测试、本记录和功能保护台账变更。不建新CI、缓存或Owner，不改Schema/版本/前端/生产。准确提交CI推送后只查询一次，不借旧绿；无生产P95或百分比收益声明，真实现场性能未测。回退对本次提交普通git revert后正常推送，无Schema或业务数据迁移。完成后停止，不进入P2B-3B及其他阶段。
