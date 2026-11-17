> **当前保护约束**：P2A/P2B 代码保留；P1Z 菜单替代已按用户确认局部修复，工作台与业务试点开关独立，原正式菜单/Owner 不替换。[当前功能保留台账与审批规则](architecture/EXISTING_FEATURE_PRESERVATION.md) 优先于历史工作台描述；本轮完成后停止。

# P2 技术底座实施与回退

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
