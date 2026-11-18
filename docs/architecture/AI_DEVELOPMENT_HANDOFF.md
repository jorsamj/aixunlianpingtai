# AI 开发接续入口

畅联云算法训练平台；仓库 `jorsamj/aixunlianpingtai`；唯一分支 `feature/external-algorithm-publishing`。

## HEAD 与阶段

执行基线：`e639bb12585a79556b7a5fd703205368720265c3`。M0 记录：`5aaf29686faddb5cdf335e0a866515d4809f57e9`；M1 实现：`4865bea70941443b5a62e56b5c90eca5e6c92aef`；离线校验元数据修正：`97ae3a517f9e3d98e58e114515cf88647b4a8129`，本地不把脏工作树产物绑定到旧提交。末次功能修正：`dc1f2b19c9066e02419f40dfc54223ca132b945d`，编辑成功后刷新当前算法详情标题并避免重复列表请求。其后本文件所在提交只更新文档。**当前交付 HEAD 是本文件所在的分支提交**，接续先 `git rev-parse HEAD`、fetch 并比较 `origin/feature/external-algorithm-publishing`，不要把实现 SHA 当作后续文档提交 SHA。最终推送准确 SHA 与一次 CI 快照见本批交付消息。原三份未提交 Payload 设计保留，不混入提交。

目标是逐步完整替换旧前端，不长期双写。当前 FastAPI 模块化单体 + SQLite + 各原 Repository + ArtifactStore + Worker/Agent/Supervisor 已有成熟执行安全。新目标为现有 frontend 工程双构建：库模式继续服务旧视图，独立 `/app/` 使用 Vue Root / Hash Router / Pinia / Element Plus；新应用不加载 app.js，不移入旧表单，不创建第二 API/任务 Owner。

## 本批实现与限制

M0 已建立[功能/API矩阵](VUE_M0_FUNCTION_API_MATRIX_20261118.md)，单独列开发与验收状态。M1 第一批已实现独立 Shell + 原生算法卡片、资产字段筛选/分页、详情/版本、本地创建/基本编辑；类型、构建、定向验证完成，验收 **CI_PENDING**。**算法整个业务域仍 IN_PROGRESS**：品目/训练状态筛选、综合/训练次数排序、删除/回退及完整训练、转换、交付仍由原系统承担。没有把基础资产投影等同完整算法库替代。

新 SPA 源码 `frontend/src/app/`，真实入口 `/app/#/projects/{projectId}/algorithms`；原库 `frontend/src/main.ts` 不迁走。后端仅新增 `/app` 静态挂载，静态壳不含授权数据，Session 由原 API 核验、401 回原登录；复用原 session 续期，不新建登录后端或轮询器。旧系统仅通过显式 allowlist 消费交接参数，先核验 canonical 项目与算法/版本；不把 localStorage 当项目权威。生产旧系统仍为原默认单项目，隔离多项目场景交接到非 canonical 项目会明确拒绝，不能顺便改项目策略。

构建：`npm ci --prefix frontend && npm run build --prefix frontend`，同时保留 `static/vue-catalog` 和新增 `static/vue-app`。Node 使用项目要求的 >=22（本地最终 Node 24.21.0）。`tools/verify_vue_app_offline.mjs` 核原生构建依赖闭包/文件 SHA 与 checkout SHA，现有 CI artifact 增带新目录；`tools/package_vue_offline.py` 对新源码强制校验双构建同 SHA，仍兼容历史单目录包。不得混装 Chunk 或把 local-check 清单当官方 CI 制品。

## 当前验证与 CI

必要本地验证：全 frontend 类型检查、两种 Vite 构建及离线闭包（旧30、新6资源）；原 API/静态挂载鉴权3项；相关 Node 合同12项、离线/打包2项；新 Shell Chrome3项。末次只补测真实新增的“关闭待加载编辑→新增”竞态：先复现旧字段污染新表单，再复用 `useReadScope.cancel('basic')` 修正，定向1项通过；详情标题刷新后再次仅运行受影响的首项Chrome用例，1项通过。未重跑无关绿色测试。

真实临时 FastAPI/AlgorithmSqlStore 联调另已通过：原生创建→PUT编辑→权威GET核对→整页进入原训练创建表单→返回新App；无训练提交/GT/权重或生产操作。旧 service-nodes 首项本地单次通过，无法稳定复现旧 CI 的标题缺失，未放宽断言或 timeout，仍待准确新 SHA CI 观察。

本批只复用现有 Frontend Runtime Job；没有新增 Workflow/矩阵。最终 SHA CI 异步验收，未完成时 CI_PENDING，不冒称全平台/生产已验收。SPA 初始共享 JS 约1.08 MB未压缩（gzip约356 KB），不是性能专项，不能宣称已完成首屏性能验收。自动截图仅测试失败制品；本轮没有反复全页面截图回归。

实际协作：gpt-6.1-sol 完成有界 M0 源码台账及只读 M1 审查；主模型独立检查实际Diff、决定架构与状态Owner、修复已确认竞态、运行必要验证并统一提交推送。未让Agent提交、部署或修改核心安全。

## 下一步与禁止事项

M1 本批代码和必要验证已完成；正常推送本批后只查最终 SHA CI 一次，停止跨领域开发，等 GPT 审查独立结构。下一步：先按准确 SHA 定位实际失败 Job（若有），否则核对算法原完整卡片的品目/训练状态/综合排序/当前版本等剩余对照，再安排训练完整模式迁移；修改仍围绕 `frontend/src/app/Algorithms.vue`、原 AlgorithmListRuntime/API合同及矩阵，不重审全仓，不动执行核心。

已知未完成：其他业务域未原生迁移；原登录/项目创建管理仍复用原页；非 canonical 项目的旧系统跳转不变更策略；新旧入口暂并存且未切换 `/` 默认；未做生产/GPU/现场离线安装或完整业务验收。回退：直接访问 `/` 使用原完整界面，新App按钮经整页交接使用原 Owner，原页有“返回新版算法库”；构建资源异常时 HTML 初始提供原系统链接。旧界面/适配器未退役。

保留唯一数据 Owner、既有训练/GT/Task/Lease/Payload/模型/发布安全；普通 UI 不过度封装、防御、测试。不得操作 A800/4070/生产数据、改 VERSION、强推、merge main、Release。业务需求/默认值/权限变更先确认。自动化通过不等于生产或硬件验收。

## 必需文档

- [当前技术架构及历史实施](../TECH_FOUNDATION_P2_20261117.md)
- [功能/API矩阵](VUE_M0_FUNCTION_API_MATRIX_20261118.md)
- [功能保留台账](EXISTING_FEATURE_PRESERVATION.md)
- [旧前端 Owner 地图](../FRONTEND_OWNER_MAP_V42_25.md)
- [第三方组件合同](../FRONTEND_THIRD_PARTY_REUSE_POLICY.md)
- [Payload 连续交付与已知边界](P2B_4A_2B_CONTINUOUS_DELIVERY_20261118.md)
