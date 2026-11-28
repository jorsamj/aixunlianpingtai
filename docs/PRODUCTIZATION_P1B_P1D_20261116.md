# P1B–P1D 连续开发与验收

## 已授权范围及设计

起点远端/本地均为 `7f874632ab96eb44e41bf9ade67e225f5f893c1a`；工作区干净，`git worktree list` 仅当前检出。唯一分支 feature/external-algorithm-publishing；VERSION.txt 实际42.24.592。用户完整附件已明确授权四阶段连续实施，无须重复审批方案。使用 brainstorming / writing-plans 梳理后直接执行已授权工作。

选择扩展已有 Vue 工程与桥接，复用原 API、NavigationStability 和 Element Plus。未选择替换默认页面（尚无授权），亦不将旧 DOM 表单包入 Vue（会形成双 Owner）。旧只读预览继续可用；新增 opt-in 管理与服务节点只读 Owner，不创建侧边栏、登录客户端或后台轮询。

正式字典：分页列表与抽屉详情，独立短表单/删除确认，不嵌套弹窗。后端 templates 唯一来源；稳定ID后端生成。普通名称/启停编辑与身份改挂分开，只有 can_delete=true 才允许危险身份编辑/删除；后端再次检查引用。一次 mutation 冻结原 operation 请求，未知结果查原 receipts，404只允许同一请求重放，冲突重新读取而不自动覆盖。离页/切项目取消请求，待确认请求保留原身份用于恢复。

服务节点：只读原 GET /api/v63/service-nodes，明确区分授权/上报/可调度能力，在线不代表训练准入。字段缺失显示未上报，不推断NPU/GPU支持；显式字段展示，排除Token与凭据。用户手动刷新，单飞请求与离页取消。

## 实施计划及状态

- [x] A：扩展 frontend/src/types/catalog.ts、api/catalog.ts、stores/catalog.ts 与 CatalogPreview.vue；增加短表单组件；原桥接增加明确写入白名单和原 catalogOperationId 委托。先以针对未知结果、revision、危险操作及CRUD的定向测试观察失败，再实现闭环；保留 read-only 测试。
- [x] B：新增 ServiceNodesOverview.vue 与真实响应类型，复用同一 mount/桥接；旧 service-node-runtime.js 仅加 opt-in 入口。验证真实字段、空/错误/无权限、无写入/轮询及返回。
- [x] C：统一 PageHeader、状态/错误和中性样式，仅提取实际复用部分；1366/768宽度检查，查看真实截图；验证退出/切项目、重复刷新及迟到响应。
- [ ] D：Node22 类型+Vite构建、直接相关 Node/浏览器/API合同；核实入口缓存一致、无CDN、缺资源回退；明确源码+构建资源与可安装离线包差异。更新Owner/交接与后端拆分建议；提交推送前再次fetch，核验准确SHA既有CI和实际artifact。

## 验证命令与证据

在根目录运行 `npx -y -p node@22 node --test tests/frontend/catalog-preview-runtime.test.mjs tests/frontend/conversion-catalog-editor.test.mjs`；按缓存变化补原八文件定向测试。前端目录运行 `npx -y -p node@22 -p npm@11 -c "npm run build && npm run test:browser"`。所有CRUD在临时数据目录，SDK检测以测试替身证明显式调用，不执行真实SDK。不得扩跑全仓/GPU/训练/标注/压测。准确SHA CI尚未产生，不借用历史结果。

## 架构及未验证边界

API审计：app.py原HTTP入口 → ModelArtifactRepository（唯一字典事务/回执Owner）及compute_platform_catalog（唯一能力语义）/conversion_catalog_references（唯一引用核验）。服务节点已由platform_core/service_nodes.py提供Router与Repository。只为文件行数拆分没有收益，本轮不全面拆app.py。

后续可先抽原catalog HTTP Router并注入原Repository/资源观察函数；风险为错误码、引用快照、observe_only、revision与operation_id重放合同，需沿原定向测试逐项等价验证。Service层只承接资源/能力编排，不新建持久化或调度Owner。本轮先落实两个页面，不强制后端重构。

控制端可部署、Agent可安装通信、设备能力实际验证、训练/推理/转换现场验收是四个不同证据层。保留linux/amd64、linux/arm64、CUDA、Ascend NPU及其他真实设备合同的扩展空间；未新增硬件适配/调度、PG/Redis/MQ或独立服务。生产部署、真实SDK、A800/4070/NPU与真实离线目标机均未验证。

## 实际功能、Owner 与入口（2026-11-17 本地收尾）

| 业务 | Vue Owner | 既有权威与实际交付 |
|---|---|---|
| 正式字典 | CatalogPreview.vue / useCatalogView / CatalogEditor | 厂商和芯片分页/查询/排序/启停筛选；厂商SDK模板筛选；新增/编辑/启停/确认删除；所属芯片数量和选择；详情/历史引用/诊断；SDK目标、版本、精度和原资源状态。只用 records GET、operations POST/GET、chips/{id}/detect POST，不用整字典PUT。 |
| 回执恢复 | catalog-operation.ts + 原桥接 | 原catalogOperationId创建身份，首次提交前冻结原packet；解析/网络/超时未知先GET回执；无回执只能用户显式重放原packet，不创建新ID。身份、action/entity/revision和item校验通过才显示成功。 |
| 节点总览 | ServiceNodesOverview.vue / ServiceNodeCard | 原GET service-nodes；名称/状态/能力本地筛选、手动刷新；OS/架构/心跳/Agent版本、CPU/RAM/GPU/磁盘、任务与Worker、允许/上报/effective能力、原错误。缺失值不冒充0；无节点写入、controller扫描、Token展示或新增轮询。 |
| 旧管理 | ConversionCatalogRuntime / ServiceNodeRuntime | 原页面与CRUD/检测/Token等管理能力均保留，仅增加URL开关控制的入口按钮。新旧DOM不会同时挂载。 |

进入正式字典：原登录后 `/?vue_catalog_manage=1` → 部署资源 → 厂商与芯片字典 → **Vue 正式管理**。进入节点总览：`/?vue_service_nodes=1` → 原服务节点 → **Vue 只读总览**。两个开关可同时使用；旧 `vue_catalog_preview=1` 仍保持只读，不获得post方法。默认不开新入口、不加载Vue制品；Vue Router只用memory，不接管旧hash。

两个新页的“返回完整管理”均调用原setPage，分别回部署资源/服务节点。移除query并刷新即可回退。页面退出由原NavigationStability调用leave，abort并unmount；项目变化/迟到import或HTTP响应再次核对页面、项目和代数。SDK检测只在显式点击时POST，随后只读刷新chips；不会因为打开列表、详情、保存或重试读取而自动检测。

## 安全与实际缺陷修复

- 不复制后端状态字典或SDK建议；展示status_label/status，未知显示未核验。真实API验收以已有RK3568→rk3568建议为证据，不扩大型号白名单，不推断已安装或已兼容。
- UNVERIFIED或已有引用时仅允许普通名称/启停，SDK/身份保护及删除拒绝保留；后端提交时仍重新核验。原Repository/SQL事务、回执、引用扫描和转换准入完全未修改。
- 独立代码审查发现字典/修订是全局的，待确认写入不能按项目分隔：已改为全局sessionStorage原packet（同源同标签页），切项目/退出/刷新仍显示待确认并阻止新写入。该记录只用于原操作回执恢复，不是业务真值；成功或明确拒绝后才清除。操作结果未知时可返回列表，但不能编辑冻结请求。
- 真实入口发现隐藏的编辑抽屉保留重复错误节点，改为只在编辑时挂载；主按钮样式只应用实心按钮，避免把链接文字变白。查询布局换行为明确两列/整行，表格双栏独立高度；原侧边栏过渡在截图时快进完成，避免截取动画中间帧。新页面错误/空/禁用/加载反馈统一。
- CSS与JS均加载成功才mount；CSS缺失时显示明确失败和原管理返回路径，避免挂载无样式页面。SDK资源不可用正常展示真实后端拒绝，不假装检测成功。

## 实测与截图

- 原仓储CRUD合同 `tests/unit/test_conversion_catalog_crud.py`：**47/47**；原节点API `tests/api/test_service_node_api.py`：**2/2**。包含原操作幂等/冲突/引用/稳定身份合同，没有改后端断言。
- 首批缓存/原字典/节点/桥接/新回执等13个直接相关Node文件 **72/72**；后续跨项目桥接和回执9项、原字典展示与桥接13项均通过（相互重叠，不累加成总数）。没有本地全仓测试。
- `vue-tsc --noEmit && vite build` 通过；当前两页共用本地按需JS约 **737.95 kB / gzip205.71**、CSS **109.54 kB / gzip15.89**；不影响未opt-in的旧首屏下载。
- 前端八项关键Chrome场景 **8/8**；随后新增CSS缺失回退场景单独 **1/1**。涵盖CRUD、延迟引用拒绝、UNVERIFIED普通编辑/身份锁定、revision重新读取、丢回复查回执、原请求恢复、跨项目和刷新保留packet、只读状态九类、节点错误/403/空态、无写入/第二轮询、返回取消。最终CI需在准确提交重新执行9项。
- 真实入口脚本 `frontend/tests/real-entry.acceptance.mjs` 使用原index/app/main/登录/API及临时SQLite仓储：真实UI新增厂商/芯片、后端建议、改名、启停、父厂商被芯片引用拒绝、先删芯片再删厂商、丢失POST回复后GET原回执，原两管理页返回、真实节点GET字段和登出均通过。JS/CSS200，pageerror=[]。SDK按钮无资源时返回原409，未运行实际SDK。
- 真实入口不是生产验收：`tools/test_vue_productization_server.py`强制创建全新临时DATA_DIR，仅127.0.0.1:8028，lifespan=off，核心bootstrap；所有SDK探测函数禁止执行，节点为合成心跳。过期后API真实显示OFFLINE/effective=[]，不能修改前端冒充在线。
- 真实页面截图及JSON在 `test-results/p1bd-real-entry/`，正式字典和服务节点各1600/768 PNG，`real-productization-entry.json`。CI的 `test-results/vue-catalog/` 截图属于HTTP夹具，和本地真实入口证据区分，不伪称CI已跑本地脚本。

复现真实入口（仅开发机完整Python依赖环境）：根目录 `python tools/test_vue_productization_server.py`；另终端在frontend目录执行 `node tests/real-entry.acceptance.mjs`（Node22+，先npm ci/build，Chrome可用）。测试账号只用于该临时进程，绝不用于生产。脚本只访问固定loopback地址；结束停止该测试进程。

## 离线资源与准确SHA交付

现有部署模式不改；所有Vue运行依赖打包进 `static/vue-catalog/catalog-preview.js` / `.css`，无外部CDN运行依赖。两页由同一原桥接按需加载，制品目录必须整体带上。主入口三资源缓存统一608；仅更新实际改变的桥接、字典与节点模块缓存；VERSION.txt仍42.24.592。

联网构建机：Node22+，根目录 `npm ci --prefix frontend`、`npm run build --prefix frontend`。既有Frontend Runtime CI继续构建、运行定向Chrome、upload-artifact；名称 `vue-catalog-preview-<准确SHA>`，需核对实际Artifacts条目及下载内容，不以步骤success冒充上传。缺制品仍报error。

源码ZIP会漏掉忽略目录，明确按以下方式加入构建资源：

```powershell
git archive --format=zip --output=../changlian-source-with-vue.zip HEAD
python -c "from pathlib import Path; from zipfile import ZipFile; p=Path('static/vue-catalog'); required=[p/'catalog-preview.js',p/'catalog-preview.css']; assert all(x.is_file() and x.stat().st_size for x in required); z=ZipFile('../changlian-source-with-vue.zip','a'); [z.write(x,x.as_posix()) for x in p.rglob('*') if x.is_file()]; z.close(); z=ZipFile('../changlian-source-with-vue.zip'); assert all(x.as_posix() in z.namelist() for x in required); assert z.testzip() is None; z.close()"
```

输出使用本次新文件名。或下载准确SHA的CI artifact，将其中 `static/vue-catalog/` 放回同SHA源码根，勿重复嵌套目录；`test-results/`截图不是运行依赖。以上是**源码+前端资源包**，不是含Python wheels/系统库/SDK/容器的完整可安装离线部署包；目标机断网安装及现场部署仍未验证。生产机不运行npm install。

本地实现与验收完成后按唯一分支普通提交推送；准确SHA既有CI、实际制品与ZIP包含性在提交后读回，回执单独保存在test-results，避免为记录自引用SHA再造未验收提交。D阶段提交/远端核验以最终回复为准。本轮结束停止。

## 下一阶段建议（未实施）

建议优先评估“模型资产只读列表/详情”：与本轮厂商/芯片证据关联紧密，可复用分页、详情、只读生命周期；先确认已有ModelArtifact Owner与产物下载授权，避免立即触及训练、GT或转换执行器。该建议不构成迁移授权。全面后端拆分、训练页面迁移及数据库迁移均未启动。


## 首次准确SHA CI反馈收口

`8dc75226289be767aa918c7a343bbe843eca8a57` 的 frontend 单测1675/1675，构建通过，Chrome 8通过1失败：CRUD已通过，失败点为1366→768 viewport切换后立即读取横向宽度。已下载检查失败截图/trace，断言在resize后约28ms执行；Element Plus表格的ResizeObserver布局尚在更新，截图最终无持续横向溢出。将同一 `scrollWidth <= innerWidth` 断言改为等待异步布局收敛，并对截图禁用过渡动画；不改阈值、不删除用例或放宽最终布局要求。CI截图还缺中文字体出现方框，因此复用原browser job的fonts-noto-cjk安装方式到Vue定向截图所在frontend job。仅复验直接相关CRUD/节点用例，之后核对准确修正SHA既有CI，不借用首提交结果。
