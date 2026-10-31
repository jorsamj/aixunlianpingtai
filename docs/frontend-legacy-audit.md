> **2026-10-30 / 42.24.429**：P0 只修原 `training-submit.js` 的迟到成功/核验/列表刷新通知归属，防止旧窗提示污染新算法；创建任务和原 TaskRuntime 不变。413/415/416/425/427 已有加载/选材代码不重复开发，生产 HAR/A800/ZIP/P95 待验。基线 428 Actions 38/38 绿；429 自身 CI 待核，唯一台账 `performance/2026-10-29-p0-followup.md`，未部署。

> **2026-10-29 / 42.24.416**：保留原 Picker/Summary/Hydration/Submit 前端 Owner 与所有请求字段；后端 role-page 只读合同显式跳过重复的 best.pt SHA256，最终训练仍全量校验。角色候选和使用池冷开销待现网诊断，不增前端状态，CI/生产待核，见 `docs/performance/2026-10-29-p0-followup.md`。

> **2026-10-29 / 42.24.415**：414 试行将空摘要 API 全池数置为 `null` 破坏已有合同，CI 红项发现后已回滚；原前端 SummaryRuntime 零选材本地摘要无需 API，保持首屏不被空请求阻塞。无平行状态和新 Owner，新 SHA/生产待核，未部署，见 `docs/performance/2026-10-29-p0-followup.md`。

> **2026-10-29 / 42.24.413 P0 追加**：保留原 TrainingCreateHydration/TrainingDraft/Submit owner，只针对其 `/api/training_options` 后端读取路径移除旧服务器串行健康探测、Paddle 递归 scan、历史模型目录；训练资源卡片复用原 renderer 增加旧服务器显式检测。原 SummaryRuntime 的空选择本地合法预览，无平行状态。完整需求/根因/测试状态见 [P0 单一台账](performance/2026-10-29-p0-followup.md)，准确 CI/生产待验。

## 2026-10-29｜训练回收与异常证据定向修复（LOCAL VERIFIED / CI及生产未验证）

[唯一审计报告](docs/TRAINING_WORKSPACE_EVIDENCE_AUDIT_2026_10_29.md)：远端40327743/VERSION399隔离基线；原Lifecycle补异常outcomes/框证据归档、显式ID与SHA保护、自动阻塞/归档失败回执。定向71通过/1系统symlink权限跳过，真实原API清理前后相同字节验证通过。用户已授权提交到开发分支；本次提交CI待核验，未部署；保留其他工作树WIP。Checkpoint恢复、未知历史所有权继续保护，远端最终回收/生产启动与接口性能NOT VERIFIED，不能称全量最终回收已验收。无前端/DB/版本更改。

## 2026-10-24｜高级功能菜单整合（代码及隔离CI已验收）

本节为本轮唯一设计、进度及验收记录。基线ee96a837013bbe352df622898152286d104d20a8 / VERSION42.24.385，fetch本地远端0/0；两份未跟踪训练模板测试及5944祖先保留。已检查其他工作树及会话，未发现本分支同时编辑；不操作其他工作树。

|现有入口|实际能力/Owner|原API|去向|后端影响|
|---|---|---|---|---|
|服务节点|ServiceNodeRuntime，Agent/Worker/能力/资源/任务/凭据|/api/v63/service-nodes|算力与节点：服务节点|无|
|训练资源|ResourceDiscoveryRuntime + 原renderResources，环境/模型目录/Paddle/服务器|/api/training_options、/api/resource-discovery/tasks、/api/ultralytics_env、/api/local_models、原环境API|算力与节点：训练环境|无|
|组件检测|renderComponentCheckV40，缓存/最新扫描/有界轮询|/api/v40/system/components/latest、scan|算力与节点：环境诊断|无|
|部署资源|renderDeployResources + ConversionCatalogRuntime|/api/v39/deploy、原conversion-catalog API|模型转换环境：资源/字典/工具说明|无|
|模型配置|最终M4与原提示词Owner，上一轮Responses继续复用|/api/v35/model-configs、prompt-templates|AI辅助配置：AI模型/提示词模板|无|
|存储配置|renderStorageSources61 + ModelArtifact/StorageCacheRuntime|/api/v61/storage-sources、/api/v62/projects/.../storage/lifecycle-summary、原产物配置|存储管理：资源/空间与缓存|无|
|旧素材兼容迁移|原legacy-material-compatibility模块与可恢复扫描|原compatibility API|存储管理：旧素材兼容迁移|无|
|平台对接|ExternalAlgorithmPlatformRuntime：连接/同步/发布/诊断|原external-platform API|保留独立入口，统一页面布局|无|
|畅联云数据|ChangLianDataBrowser：只读分页浏览|/api/v63/external-algorithm-platform/provider（只读）|保留独立入口，统一页面布局|无|

真实重复是高级侧栏平铺相近入口；训练环境快捷检测与全局组件诊断范围不同，必须都保留；服务节点不是转换工具实体。旧部署插件已归一到模型配置，历史render函数不是新增有效页面，不恢复废弃业务。服务节点面包屑原归系统与对接确实错误。

设计取舍：直接将state.page改成四个新名字会破坏组件/服务节点轮询、资源Action fence及旧跳转；复制页面业务会形成双Owner。选择原路由身份不变，只在现有导航层做四项菜单映射/标题/Tab，原业务Renderer直接挂载#view。Tab外框独立于#view，不包装或复制业务Owner，不使用DOM观察器维持导航；同页分区仅为展示状态，保存于原UI偏好，不能拥有业务任务状态。旧入口继续有效，新菜单名只归一到既有路由。平台操作页与只读浏览保留独立，避免双重Tab与写操作混合。

实施清单（按用户授权审计后继续，无重复审批）：
- [x] A 基线/有效入口/Owner/API/重复与独立边界核验并向用户报告。
- [x] B 在原navigation-stability和main导航chrome接入菜单元数据/原路由Tab；修正标题、面包屑、active及刷新恢复。
- [x] C 作用域CSS统一资源、模型、存储及对接页；低频工具说明收纳，旧操作/字典/未知空间语义保留，不改后端。
- [x] D 原advanced-navigation Node守卫升级合同；少量真实Chrome覆盖四菜单/旧路由/Tab/检测离开恢复/弹窗/缩放。仅运行受影响现有回归，不手动全仓测试。
- [x] E VERSION/cache及五份交接入口已更新，代码与测试已正常推送，f95e221f准确SHA CI已验收；文档提交自身最终HEAD的Checks在交付前另核。

风险/边界：真实GPU、NAS/OSS、生产连接/同步/发布均不执行；本轮不新增清理/迁移权限或后端能力。旧路由仍是页面身份，Sidebar折叠不改变业务页；同页Tab不重发请求。测试和提交证据在本节持续补齐，不以写文档代替代码交付。

### 实施与必要验收记录

新增advanced-navigation.js仅拥有四菜单元数据和Tab展示，不持有业务数据/任务、不包装任何Renderer。main现有navigation chrome调用一次展示；Tab位于#view外，旧业务进度更新不能替换它。同页Tab不执行render/API，跨页Tab调用原setPage；原UI偏好键记录分区，刷新后恢复。导航状态/异步Owner仍是原state.page，服务节点面包屑已纠正。四个新菜单名只normalize到旧Owner，旧入口全部保留。

最终布局：算力与节点=服务节点/训练环境/环境诊断；模型转换环境=转换资源（含实际SDK/编译器状态及可折叠工具链接入说明）/厂商与芯片字典，不设空的SDK独立页；AI辅助配置=AI模型/提示词模板；存储管理=存储资源/空间与缓存/旧素材兼容迁移。平台对接/畅联云数据保留原两入口及原内部Tab，采用同一作用域列表/标题/按钮规范；不自动连接、同步或发布。

UI改动：统一Tab、panel间距、按钮最小高度、资源网格、表格换行及窄屏布局；存储占用改为四列紧凑指标行，避免八张卡片横排嵌套，未知数据仍显示未获取；原compact-note被全局!important隐藏，工具链说明改专属类并折叠，未增加!important。新增CSS只作用于高级/对接页面。原节点表单/凭据、训练环境与模型目录/上传、组件扫描、资源/SDK检测、字典CRUD、M4协议、提示词CRUD、存储/算法产物配置、缓存状态与迁移原流程全部保留。

本轮未修改任何后端文件、数据库Schema或API合同；没有新依赖、新任务Owner/轮询、物理清理能力或P2评测改动。仅storage-cache-runtime的HTML内联布局改class；conversion-catalog原字典快捷入口选中对应Tab。其他跳转仍调用原路由，并呈现新标题/active/menu。相关既有浏览器测试只更新新标题/菜单定位和必要Tab路径，原请求次数、fencing、安全、CRUD断言保持。

RED→GREEN：新增Node初始缺模块RED；Chrome明确收到原7菜单而期望4菜单RED。菜单/路由纯合同与版本首批12通过；原导航/唯一Owner/模型局部保存守卫33/33通过；存储缓存/未知值/迟到隔离和版本24/24通过。Chrome第一组11/11（22.7s）、第二组9/9（25.1s）、末组4/4（16.0s）；包括新增2场景、节点凭据、导航折叠/恢复、旧路由、扫描轮询离开恢复、字典CRUD、提示词CRUD、存储状态和120条迁移恢复。各组有重复，不相加冒充独立数量。上一轮Responses配置保存/刷新/编辑原Chrome1/1（6.7s）通过；最后布局截图单例1/1（9.2s）通过。JS syntax、diff check及Python build_identity检查VERSION386通过；未改Python业务，不手动跑全仓pytest。

导航取消补充：截图发现page-navigation短暂错误提示。原PageRequestScope只识别AbortError，但controller.abort('page-navigation')可能使原生fetch直接拒绝该reason；新增单例RED（rejected而非原隔离语义pending），在原判断中补error===signal.reason，保留generation/aborted条件，不重写请求系统。6/6 Node GREEN，包含真实当前网络失败仍抛出；新Chrome使用原生fetch/AbortController亦验证取消隔离1/1，最后页面与旧清洗/AI review迟到结果保护3/3（16.7s）。未新增请求/轮询Owner。

视觉证据：[原7项菜单](screenshots/2026-10-24-advanced-menu/before.png)、[转换字典1440](screenshots/2026-10-24-advanced-menu/conversion-1440.png)、[AI配置1920](screenshots/2026-10-24-advanced-menu/ai-models-1920.png)、[存储1920](screenshots/2026-10-24-advanced-menu/storage-cache-1920.png)、[训练环境1920](screenshots/2026-10-24-advanced-menu/training-environment-1920.png)。全为隔离服务真实Chrome截图，无生产或虚构业务数据；1920/1440/1366及125%等效1093宽已检查无横向溢出，截图路径同时保留在测试输出。旧测试自动重写的历史截图已还原其原HEAD内容，不混入本轮提交。

VERSION42.24.386；app/main/styles cache42.25.434，新页面样式/模块20261024，存储布局缓存20261024-layout。原Frontend Runtime仅追加2个本轮Chrome场景，不新建工作流；精简本地测试不改变原CI既有守卫。当时阶段E待提交/CI；最终状态以下方验收回执为准，不以本地绿色替代远端CI。生产Agent/GPU/NAS/OSS/同步发布NOT VERIFIED，不部署、不扫描生产、不改生产数据。

### 提交与CI问题跟踪

代码d281c72120d73a1514125a0412c7d38b2994360f已正常推送。其CI发现Storage Cache Governance仍grep旧缓存422540-lifecycle（该job Python58及Node21通过），Frontend Runtime两个源码守卫仍要求原七菜单列表及label===currentPage。按真实新菜单合同更新原断言/缓存标识，所有安全/唯一Owner/不重建侧栏断言保留；两份受影响Node文件59/59 GREEN。该SHA不能标全绿，守卫修正后须核新SHA，不使用旧结果替代。

守卫修正0ff220419e4da30437ea958119de192762fedec7准确CI为21成功/1失败，55成功/1失败Checks；存储守卫已通过（Python58/Node21），Node1331/1331通过。完整Chrome264通过/3失败：服务节点无闪页用例对象仍期望旧title、版本遍历用例仍期望旧菜单名、提示词缓存用例未选择新Tab。仅同步这三处新UI合同，保留原页面身份/无闪页/版本标记/DOM稳定/GET一次断言；3/3定向Chrome GREEN（11.7s）。业务代码未变，须再核修正新SHA CI，旧失败记录不隐藏。

### 最终代码验收与接续

最终代码/测试提交f95e221f5243b31884737d903a7eac92fe184d8c，VERSION42.24.386；[准确SHA Checks](https://github.com/jorsamj/aixunlianpingtai/commit/f95e221f5243b31884737d903a7eac92fe184d8c/checks)为23/23 Actions、60/60 Checks成功，0失败/取消/跳过/待完成。先前d281/0ff的失败已由上述合同修正关闭，不将其说成绿色。

[最终Frontend Runtime](https://github.com/jorsamj/aixunlianpingtai/actions/runs/40089845478)：Node1331/1331、真实Chrome267/267通过（16.7分钟），包含四菜单/原Owner/Tab/刷新恢复、真实取消隔离、旧业务回归。存储相关Python58/Node21及不可变/节点隔离/签名上传守卫在0ff22041对应Storage Cache Governance通过；本轮没有Python业务改动，未手动重复全仓pytest。所有最终验收区分准确提交，不把不同轮次数字相加。

原始5944e1a558a34f7be008b644a5a3b07b4ed132cd在祖先链中，两份训练模板测试始终未暂存/提交；没有修改其他工作树。仅正常push唯一长期分支，无reset/强推/main合并。代码d281c721、源码守卫0ff22041、浏览器合同f95e221f均已持久化并保留可追溯记录。当前没有已知未完成的本轮代码项。

接续从static/modules/advanced-navigation.js（纯展示映射）、static/main.mjs原navigation chrome、static/app.js最终renderNav/renderTop以及原各业务Owner开始。不要将state.page替换成四个菜单名，不复制业务Renderer、不新建PollRegistry/Modal/任务/存储管理；同页Tab只改展示，异步Owner及API保持原名称。旧素材迁移是原正式已实现工具，迁移/物理删除仍需其原预览确认和授权；菜单整合没有新增这类能力。

文档自身后续提交不改业务代码；最终HEAD由本文件最近修改commit定位，交付前独立核其Checks，避免SHA自引用循环。生产GPU/Agent环境、NAS/OSS、真实平台同步/发布仍NOT VERIFIED；本轮不部署、不修改生产数据库/素材/GT、未进行生产扫描或迁移。必要生产环境验收属于单独授权范围。

## 2026-10-24｜大模型Chat/Responses协议兼容（代码及隔离CI已验收）

唯一需求/设计/进度：[协议专项](LLM_API_PROTOCOL_COMPATIBILITY_2026_10_24.md)。原provider兼容Chat/Responses，准确端点识别、受控结构化降级、安全错误证据；原M4高级配置/Bootstrap投影同步，连接测试与正式v60同工厂及字段校验。VERSION385/cache433；最终代码982069c8准确CI47/47 Actions、128/128 Checks成功，协议44、API55（含配置11/正式E2E4）、Node1328、Chrome265通过。文档自身最终HEAD另核Checks。5944及两份模板测试保留；真实GLM/收费接口NOT VERIFIED，发布前须授权环境实测，不部署。

## 2026-10-24｜ZIP自动标签确认与重复窗口治理（代码及隔离CI已验收）

唯一记录：[Uppy专项顶部](UPPY_ZIP_ADAPTER_POC_2026_10_22.md)。原Runtime统一自动确认/主动关闭抑制/成功立即关所属内容，旧列表不倒退；Uppy/旧入口同Owner，原选择层交接及复用节点保护，多ZIP独立顺序，完成后整理窗口改手动。VERSION384；代码/测试610878cd准确CI23/23 Actions、60/60 Checks成功，Chrome264/264、Node1328/1328；ZIP相同业务代码52939779的独立Chrome41/41。历史失败和最小Python9/Node/Chrome证据见专项，文档自身最终HEAD交付前另核Checks。5944及两份模板测试保留，无后端/GT合同变更或生产操作。

## 2026-10-24｜创建训练弹窗滚动修复（代码及隔离CI已验收）

唯一记录：[训练创建专项顶部](TRAINING_CREATE_FOUR_MODES_UI_2026_10_10.md)。原CSS收敛高度/单一layout滚动、标签自然展开、footer真实占位；无JS或后端/参数/调度变更，important减少15。五视口真实wheel5/5、原标签提交Chrome1/1及Node27/27通过；VERSION383，CSS cache4226355，代码f5ba6192准确CI 36/36 Actions、99/99 Checks通过，文档最终HEAD自身另核Checks。5944及两份模板测试保留，未部署/未启动训练。

## 2026-10-24｜P1跨标签负样本与首次训练（代码及隔离CI已验收）

唯一需求/进度：[训练质量专项P1](TRAINING_QUALITY_REMEDIATION_TRACKER_2026_10_18.md)。任务标签与原始标签分离，正/已确认负/待审核共享后端合同；人工有限批审保留原框、CAS/源SHA与事务审计；新V3纯负保留像素/空YOLO、混合与历史V2保护不变。VERSION382，必要Python/Node与Chrome四个独立场景通过；代码cd8cde89准确CI 23/23 Actions、60/60 Checks成功，最终文档HEAD自身另核Checks，详见专项回执；不自动确认/丢弃/训练，不生产操作。5944及两份未跟踪模板测试保留。

## 2026-10-23｜普通图片Uppy与本次上传处理（代码及隔离CI已验收）

唯一进度：[Uppy专项普通图片节](UPPY_ZIP_ADAPTER_POC_2026_10_22.md)。原multipart64张/128MB顺序Owner、UploadBatchStore及唯一任务中心复用；本地中文Uppy、48条本批确认页、真实失败/待核验、刷新恢复、原清洗/标注已接通，ready不写GT。Python31、必要Node及Chrome五图/部分失败/65分批/ZIP冒烟通过；VERSION381，修正646aeb0a实际22/22 Actions、58/58 Checks、Chrome250/250与Node1322/1322通过；本次文档自身HEAD另核Checks。每批仅一个原清洗任务限制保留；生产未验证/未部署/未写入，5944及两份模板测试保留。

## 2026-10-23｜旧素材全面检查体验修复

[唯一专项](TRAINING_MATERIAL_LIFECYCLE_GOVERNANCE_2026_10_21.md)顶部为接续依据。一次开始顺序50条、真实汇总及25条明细分页、暂停/刷新/失败恢复已实现；原迁移单独确认，检查不改正式数据。VERSION380，Python15/Chrome3/版本9通过，代码6f663e1c实际38/38 Actions、102/102 Checks通过；本次文档新HEAD另核。原图仅逐条检查时点，库外原位改写/无版本GT不冒充全库原子证明；5944及两份模板测试保留，未生产操作。

## 2026-10-23 P2接续入口

[唯一评测专项](SCENARIO_MODEL_EVALUATION_UI_GOVERNANCE_2026_10_22.md)顶部P2为当前进度；原Owner复用，新增AdvancedEvaluation仅负责展示，不拥有GT/任务/存储/候选；代码9280实际21/21 Actions、55/55 Checks通过；文档新SHA另核，生产未验证。

## 2026-10-20 转换Weight恢复增量

原发布Owner/版本SQL payload/ModelArtifact复用；行内交付意向选择、原/目标分类与Weight/OSS/UNKNOWN审核投影，单一后端合同，无第二队列、弹窗或轮询。详细架构/证据/进度以docs/CONVERSION_WEIGHT_PUBLISH_RECOVERY_2026_10_20.md为准；生产替换未开放，VERSION42.24.360，main408/发布模块64011。

## 2026-10-20｜动态厂商字典与真实SDK目标（本地限定验收通过 / 最终SHA CI待推送 / 生产未部署）

- 完整fetch/pull基线7a2492b24de5d6259bf792ed074f1548e66d6eda，原39/109绿色归档不是本轮CI。复用初始干净长期分支工作树，其他工作树/会话未覆盖。
- 唯一专项docs/DYNAMIC_CONVERSION_CATALOG_ACCEPTANCE_2026_10_20.md保存完整用户V2/第十八条、产品合同、架构、RED、已完成与剩余计划。原ModelArtifactRepository/compute_platform_catalog/Adapter/Worker/Durable MODEL_CONVERSION/发布Owner复用，无平行模型库/队列/调度/轮询。
- 动态本地厂商/芯片表初始为空，模板不等于业务记录；SDK/本地/外部ID分开。BM1684按1.30.2官方矩阵+实检开放F32、原X/88 F16保留；未知组合不乐观放行。后端统一resolve和POST，真实目标/参数/命名、结构/hash、资产快照可追溯，硬件验证独立。
- 正式VERSION本轮已一次42.24.358→42.24.359；必要app/main/styles缓存42.25.407、发布模块64010。正式显示继续读后端版本。最终Python262、Node70、Chrome8通过，另7项发布安全定向用例通过；版本七入口一致、语法/diff/原永久守卫通过。最终完整SHA CI待推送，记录于专项指定独立附件。
- 未部署/重启/安装SDK/改生产密钥或数据库/操作OSS/历史Weight；本机Windows未找到TPU-MLIR工具，真实BM1684编译、模型质量与板卡NOT VERIFIED。生产17项元数据/7Weight补齐仍未执行，须独立授权。

## 2026-10-20｜Weight tags及本地元数据（本地通过 / 最终SHA CI待提交 / 生产补齐未执行）

- 基线0cf65c48bf6c6d0ec0df852128c2faccf4072f8e已完整fetch/pull；历史48/131绿色归档，不代表本轮。VERSION42.24.358，app405/styles402保持，仅main406/发布模块64009必要更新。
- 原模型标签/JSON add-edit/UNKNOWN/差异检测已有。RED确认通用资产未持久化模型信息+upsert整体替换、PARTIAL幂等ensure重置重试时钟、edit多候选未消歧、无外部映射本地标签投影遗漏。共享原解析合同、原SQL/ModelArtifact/发布Owner增量修复，无平行队列/数据库/轮询。
- 版本冻结schema/codes或可信Snapshot为唯一来源；Artifact保存验证快照，未知不清空已知、冲突不覆盖。训练/转换先登记本地，与外部/上传配置独立；已有对象身份保持，不复传。原ID唯一edit，缺可选字段不阻断交付；回执和真实远端读回分开。
- 主Python335通过，版本兼容25、训练/转换传输18通过；Node26、Chrome3通过，0失败0跳过。7缺失实际ID+10隔离对照通过，7edit/10零edit，重复不新增。最后完整SHA仍须CI。
- 唯一专项docs/WEIGHT_TAGS_SYNC_ACCEPTANCE_2026_10_20.md顶部含只读预检、显式本地修复及原Owner受控外部补齐步骤/7ID表；scripts/audit_weight_metadata.py默认只读，--apply-local也不上传或调用新畅联。
- 未连接生产执行补齐/部署/重启/改密钥/操作OSS/S3；生产17项尚未实际修复，远端tags持久化需另行授权读回验收。部署启用自动Owner可能恢复历史重试，也须先审核并批准补齐。

## 2026-10-20｜Sophon资源与页面一致性（本地通过 / 最终SHA CI待提交 / 生产未部署）

- 基线a36b9cdec1cd4aa07c9cde2d9c84bc98bb66b479已fetch/pull，历史22/22 Actions、59/59 Checks归档专项。现场两chip真实FP16编译/远程done与probe可用是用户提供证据，不等于板卡验证。
- 扫描/plugins复用原v39 detect Owner解析secret_ref、鉴权、持久化及公共投影；资源列表/转换弹窗读取同一事实。健康失败清空Sophon能力，恢复重新可用，不泄露密钥；无第二探测/调度/轮询。
- 本机工具明细仅展示本机；整体Sophon按有效资源汇总，区分本机未配置/本机失败/远程可用。版本修为完整v1.30.2-20260831，远程资源展示工具版本；独立Python保留原逻辑已有测试保护。
- RED后端8、Node1、Chrome1→限定Python136/136、Node20/20、Chrome10/10（0失败0跳过）；语法/diff/原永久守卫通过。VERSION42.24.358，app缓存405，main404/styles402不变。
- 唯一专项docs/SOPHON_BMODEL_CONVERSION_ACCEPTANCE_2026_10_20.md；最终CI附件见本轮E节。不修改生产服务/密钥/依赖，不部署，不调用真实新畅联写接口；部署后真实网页与板卡结果仍需现场复验。

## 2026-10-20｜Sophon BMODEL（A-D测试通过 / 最终SHA CI待提交 / 生产与硬件未验证）

- 起始62647aeea258a26ba423f0a9db23d8f6f8ba3b1a；上轮23/23 Actions、59/59 Checks已归档原tags专项，不代表本轮绿色。VERSION42.24.358不变。
- 首期BM1684X/BM1688、FP16、Batch1/static；修复显式芯片/矩形导出与ONNX shape、可运行工具探测及真实产物结构/hash合同。Sophon remote并入原ConversionHandler/MODEL_CONVERSION，原Key/Lease/取消/恢复与确定ID幂等；无第二执行器/数据库/轮询。
- 发布继续原ModelArtifact/Owner与Weight add/edit，同Version下PT和两chip BMODEL共存，tags冻结原生数组，未知可选信息不阻断；Sophon必要chip严格校验。UI增量字段与真实资源/任务/待硬件状态，app/main缓存404、styles402、发布模块64008。
- 本地Python313/313、Node40/40、Chrome10/10，0失败0跳过；最后BMODEL edit断言聚焦4通过。硬件2 SKIP/NOT VERIFIED，无真实TPU-MLIR编译或板卡加载证据；独立规格P1两项均补RED关闭。
- 唯一专项docs/SOPHON_BMODEL_CONVERSION_ACCEPTANCE_2026_10_20.md；提交后最终CI依该文档指定独立附件核对，不能提前宣称CI通过。禁止生产部署/API/OSS/GPU/生产转换；下一会话先读本节和专项后接续。

## 2026-10-20｜Weight tags HTTP链路验收（测试补全待最终CI / 生产未验证）

- 唯一业务范围为Weight tags；冻结类别、PT/ONNX/RKNN、原IDedit与UNKNOWN原机制已存在，不改生产业务/上传人/身份/OSS对象标签/VERSION/静态缓存。
- 新增6项真实requests JSON编码链路回归，最终限定Python200/200、Node16/16、Chrome3/3；单/双/四类别、class_id顺序、多版本、RK3568/3576、未知省略、旧ID补齐与零重复写。初次5项失败为夹具问题，非业务RED。
- 持续进度总入口 docs/CODEX_CURRENT_STATE.md，唯一专项 docs/WEIGHT_TAGS_SYNC_ACCEPTANCE_2026_10_20.md；最终SHA CI独立验证，无生产操作。

## 2026-10-20｜权重补充元数据发布（最终合同：可选、非阻断）

- 首次SHA 6f83076f的CI发现精简Job缺TestClient依赖、浏览器文本守卫未适配参数化；仅补httpx2及更新守卫匹配，保留核心身份零POST断言与全部实际测试。后续1faa9693的后端200项与Chrome3项已通过，另将唤醒信号守卫同步到既有真实Event.set发出断言及消费后无重复断言；最终SHA重新验收。
- 基线93c56659，复用ExternalPublicationRepository / ModelArtifact / 原发布与转换通知Owner。六扩展字段可信则传、未知省略，tags未知不发[]；缺失不阻断交付、不改转换成功状态。
- 原ID edit补齐与确认payload回执、UNKNOWN写入只读恢复、矩形尺寸及冻结标签解析、原版本行内联事实/真实错误展示。无第二队列/数据库/轮询/弹窗Owner；不操作生产。
- 聚焦Python三文件194 passed、Node三文件41 passed、Chrome单规格3 passed，末次schema/存量19 passed。原始RED/失败及纠偏记录见 docs/WEIGHT_METADATA_ACCEPTANCE_2026_10_20.md。
- VERSION42.24.358不变；app/styles402不变，仅main403及两个模块缓存更新。最终SHA Actions/Checks需独立验收，附件：C:/Users/jorsam/.codex/visualizations/2026/10/20/01a156ca-1ca0-7b70-8497-bd255da4345e/weight-metadata-acceptance-20261020.md。
## 2026-10-20｜素材完整性接续审查（本地验证，最终 SHA CI 待验收）

- 完整 fetch/pull 长期分支到 d623a2d6327143571898e778050e5d42cc5e4a4d，六个已知修复全部包含；原工作区保留，复用既有长期分支工作树。
- 仅修复三项真实复现：标签映射摘要未贯穿普通治理计划/Worker；execute 迟到成功/失败未完整校验弹窗归属；恢复复验把已成功删除项重新记作失败。沿用原计划/Task/DELETE_INDEX/AnnotationRepository/Modal/PollRegistry，无新 Owner。
- 审计已有 label_schema_digest 贯穿冻结计划、执行清单和逐项删除；标签锁先于 Material 生命周期锁。缺摘要旧计划 fail closed，需要重新审计/预检；已成功项保持历史计数，未完成项仍复验 keeper/GT/hash/Test/引用。
- 本地新回归 RED：Python 4 failed，Node 2 failed；最小修复及边界补充后聚焦 Python 6 passed，Node 全量 1021 passed。安全扩展最终 116 passed。真实 Chrome 两份规格 19 passed；最后补顶层弹窗按钮归属后聚焦 2 passed。独立复核未发现本次差异的 P0/P1；其 Python 首轮 5 setup error 为 C:/Temp 父目录不存在，换已有短目录后 6 passed，Node 35 passed。首轮新 Chrome 夹具误用 window.state 导致 2 failed，已改为仓库既有 lexical state 并保留所有业务断言。
- 正式 VERSION=42.24.358 不变；入口 app/main/styles 静态缓存 42.25.402。最终准确 SHA、全部 Actions/Checks、未触发与未验证边界记录在 C:/Users/jorsam/.codex/visualizations/2026/10/20/01a156ca-1ca0-7b70-8497-bd255da4345e/material-integrity-acceptance-20261020.md；不沿用基线 40/40 绿色。
- 未部署、不重启生产、不连接生产数据库、不执行真实素材删除，不自动发布模型。生产 OSS/S3、历史现场、GPU/A800、大库并发与查询 SLA 仍 NOT VERIFIED。
## 2026-10-19｜P0 批量 GT 冲突辅助治理

- 本轮唯一进度为 `docs/TRAINING_QUALITY_REMEDIATION_TRACKER_2026_10_18.md` 顶部批量GT节；复用 TrainingCompatibility、原审计/MaterialBatch、ImportCandidateStore、正式 AnnotationRepository 和 DELETE_INDEX，两个入口共用 TrainingMaterialSummaryRuntime。来源证据不代表GT正确，必须人工审核；无第二套存储/队列/Owner/轮询。
- 正式VERSION42.24.356不变；不连接生产、不覆盖GT、不动历史/Test，不部署。最终SHA及实际Actions/Jobs/Chrome证据以追踪文档指向的独立最终验收附件为准，生产960组进一步根因数量未验证。

## 2026-10-19｜P0 远程清理同步锁误保护精准修复

- 现场只读证据由用户提供；精确豁免 `remote-material/staging-cleanup.json.lock`，不豁免真实台账或其他锁。实际清理调用的 RED→GREEN、API/Worker 和 CI 证据统一见 `docs/TRAINING_QUALITY_REMEDIATION_TRACKER_2026_10_18.md` 顶部专项。
- 复用原历史引用、MaterialBatch/DELETE_INDEX Owner；Payload/关联任务/执行记录/冻结/Test/Snapshot/模型/未知依赖仍保护，不改任务历史，不操作生产，不改 VERSION=42.24.356。最终 SHA/Actions/Jobs 以独立最终 CI 验收附件为准，不沿用前一 SHA 绿色。

## 2026-10-19｜P0 素材治理与训练冲突删除闭环

- 当前专项唯一进度仍为 `docs/TRAINING_QUALITY_REMEDIATION_TRACKER_2026_10_18.md` 顶部 P0 节；TQ-04 已完成批次不重做。既有素材治理验收文档追加本次证据，最终准确 SHA/Actions/Jobs 以其关联的 CI 附件为准，不继承旧绿色。
- 仅在可证明 FAILED 输入从未形成现存依赖时释放请求引用；Snapshot/Test/恢复/模型/未知依赖继续保护。同组保留全部保护身份和 keeper。两个入口共用原冻结计划、DELETE_INDEX、MaterialBatchRuntime62 与 PollRegistry；不删除共享源文件，不改历史记录，VERSION仍42.24.356，不部署。

## 2026-10-19｜TQ-04 类别指标真相接续

- 当前任务与实际测试/CI唯一进度入口：`docs/TRAINING_QUALITY_REMEDIATION_TRACKER_2026_10_18.md`。仅维护既有 evaluation/iteration decision/report Owner；禁止生产操作、历史数据重写和 VERSION 变更。最新修复的实际 SHA/CI 需按追踪文档关联的验收证据查询，不沿用旧 SHA 结果。

## 2026-10-18｜安全推送验收阶段（用户已授权 / CI 待最终 SHA 验收）

- 首轮 `edee5fb6fcd32812ee62b0197728dc7ab51d8b0f` CI 发现恢复/素材选择 Chrome build 断言与实际资源不一致，以及新接入 Hardening 守卫锁定退役的注册模块。最小修复只同步精确版本和真实 Production→CheckpointResume→Recovery 继承合同，并增强真实注册对象断言；恢复 Chrome 5/5、素材选择 Chrome 2/2、Node 982/982、两个原始 Bash 永久守卫通过。扩展 Windows 测试的 14 项长路径失败在短 basetemp 消失（19 passed/1 Linux-only skipped）；另 1 项 manual workers=8 与既有 Windows 上限4冲突，不改生产资源保护；相同未变源码的 Ubuntu 124项已实际通过。最终 SHA 仍需重新完整 CI。
- 用户已授权本轮普通 Fast-forward 推送及必要 CI 修复；禁止强推、main 合并、Release、生产服务/数据操作和正式 VERSION 修改。此前 LOCAL ONLY 记录是上一阶段，不再作为本阶段推送限制。
- 代码提交基线 `5d3ad65bf7ff287521481a2ac6bfbd1f7caed52e`，远端父提交 `5a28e4539b81c03b4eaa27fa4b6c718138542169`。范围审查确认只涉及图片标注、类别检查、素材治理和训练冲突闭环，复用原 Repository、TrainingCompatibility、Snapshot 与 Task Owner。
- 推送前独立复核补齐固定 Benchmark 与 duplicate_review 合同：API/Worker 只在真实 Benchmark 解析后正规化；保留原 revision，拒绝客户端 Test 角色及保留素材排除，不暴露私有 Test ID。9 个真实 API→Worker 场景通过，相关 Python 109 passed；Node 全量 981 passed。
- 发现 Release Regression 与 Training Final Validation Hardening 仅监听旧分支，已接入唯一长期分支，并补源码/测试触发路径及 Node 守卫；不删除测试或放宽断言。正式 VERSION=42.24.356，静态缓存规则不变。
- 远端验收必须按最终完整 SHA 查询全部 Actions/Jobs，旧 SHA 结果不可继承。最终 SHA、统计及生产只读核验边界将记录于 `C:/Users/jorsam/.codex/visualizations/2026/10/18/training-conflict-p0/CI_FINAL_HANDOFF.md`，该外部验收文件不产生未经 CI 的额外代码提交。
- 生产 2531 张现场、OSS/S3 历史对象、GPU/A800 和大库并发仍 NOT VERIFIED。历史 Snapshot/Test/模型证据保护保持，不自动解除 FAILED/no-freeze 保护，不删除共享原文件。详见本轮验收文档。

## 2026-10-18｜训练重复冲突与标注/治理闭环（LOCAL ONLY / CI NOT RUN）

- 当前隔离分支 `codex/training-failure-diagnostics`；本轮不得 push、部署、修改正式 VERSION 或操作生产素材。验收与现场边界见 `docs/TRAINING_CONFLICT_GOVERNANCE_ACCEPTANCE_2026_10_18.md`，不能沿用旧 SHA CI。
- 原始正式 GT 同 SHA 冲突在任务标签投影前检查；预检、准入、Worker 和冻结复验共用原 digest。显式排除仅改变新训练草稿且双 revision/原始角色必须验证；Train/Test 泄漏不可绕过。冻结前后复验、锁内发布，外部平台 HTTP 在标注锁外。
- 训练差异/失败诊断仍由 TrainingMaterialSummaryRuntime 管理，标注仍由原工作台/AnnotationRepository 保存；未检查类别默认折叠、单一绘制类别、四视口布局。零可删仍能看真实图与保护原因并人工核对 GT，不创建空删除任务；FAILED/no-freeze 不自动解除保护。
- 移除 MaterialBatch 路由内部重复训练恢复挂载，保留 app 配置完整的唯一 Owner。Snapshot/Test/模型/历史记录不改，共享源文件不删；任务轮询和 DELETE_INDEX 归属不变。
- VERSION=42.24.356；入口 app/main/styles 缓存=42.25.389。最终 Python 聚焦131、API/素材安全115、Node24完整980、真实Chrome24全部通过（无失败/跳过）；原始日志和截图见验收报告。素材选择沿用原Owner，解析全选期间禁止确认，迟到结果校验项目/选择器归属。GitHub/Linux、生产2531张案例、OSS/A800实机仍 NOT VERIFIED。

## 2026-10-17｜素材治理推送后的 Chrome 跨平台证据路径修复（FINAL SHA CI OPEN）

- 已授权提交9830f1de快进推送；该 SHA 实际44次Actions运行中43成功、1失败。唯一失败为 Frontend browser-navigation：Ubuntu缺USERPROFILE，两条新增治理用例在截图路径处中止（93 passed / 2 failed），并非可计为通过的环境跳过。
- 本地清除USERPROFILE稳定复现2 failed / 1 passed；现有三条治理Chrome统一使用Playwright testInfo.outputPath，证据按用例隔离，不依赖Windows或仓库内.codex目录。保留全部业务断言，无生产代码、静态缓存或VERSION变更。
- 修复后相同无USERPROFILE条件下相关Chrome21/21、Node24完整978/978通过；本轮另有Python41/41。9830的Ubuntu Release runtime-contracts实际456 passed，包含test_material_integrity.py；最终修复SHA须重新验收，不能借用旧SHA成功。
- VERSION42.24.356不变；不部署、不触碰生产素材/数据库。生产原两次删除Task及真实存储仍待只读现场核验。

## 2026-10-17｜重复与异常素材删除 P0（LOCAL VERIFIED / CI OPEN）

- 既有素材治理计划 Owner 增补 FILTERED / SELECTED_IMAGES / 异常组冻结；全筛选不下发全量 ID，重复 keeper、不同 GT 人工确认、Test/历史引用与扫描未核验保护不变。异常筛选不能绕过去重保护，DELETE_INDEX 不删除共享原始文件。
- 素材治理在同一个弹窗内完成全选、跨页选择、预检与确认，失败保留上下文；MaterialBatchRuntime62 / PollRegistry 仍是唯一任务状态与轮询 Owner。所有索引删除终态刷新分页并失效旧审计；旧分组不再冒充当前素材。图片尺寸/加载失败时藏框，真实宽高比与 Content API 保持一致。
- 独立代码复核的发布前失败重试、refresh 期间切换项目、Chrome Worker 跨用例领取三项 Important 已关闭并补回归。未发布 manifest 只有完整身份、归属和 pending 状态完全相同才复用；篡改 409。测试 Worker 唯一 capability 仅用于隔离目标临时 Task，生产调度未改变。
- VERSION42.24.356 不变；入口 app/main/styles 缓存42.25.388，MaterialBatch build/import422406。最终 Node24 978/978、Python41/41、真实 Chrome21/21；详细结果和现场边界以 docs/MATERIAL_INTEGRITY_P0_ACCEPTANCE_2026_10_17.md 为准。现场原两次 Task ID/日志尚未取得，不声称生产删除数量或根因已核验；未 push、部署或操作生产数据。

# Frontend Legacy Runtime Audit

## 2026-10-16 Row action menu presentation

Final mobile status tabs keep readable single-line labels within the original scroll strip (<=760px); styles42.25.387, no new owner.

Follow-up closes the verified training Grid overflow without altering desktop columns/owners. Original 3be88817 remote40 workflows/112 jobs passed; shared atomic staging contention was independently reproduced and minimally fixed. Local Node24 972/972, Python75/75, Chrome44/44; next SHA requires fresh CI. See the acceptance report.

Existing algorithm/training entity-more markup now delegates to one RowActionMenuRuntime top-layer popover. It invokes original buttons; no CRUD, task, poll or navigation owner is duplicated. Training epoch patches preserve action markup identity; obsolete nav-project/projectBadge rendering/CSS is removed without changing project state. Node24 972/972, Chrome 44/44; formal VERSION unchanged. See ROW_ACTION_MENU_ACCEPTANCE_2026_10_16.md for evidence and limits.

## 2026-10-13 VNext model-quality owner update

- Canonical owners stay singular: classic `openVersionEvaluation429` presents version-owned evaluation truth; `trainingReportCore425` remains the report entry (aliases only delegate); `TrainingRecoveryRuntime` remains the only detail/log presentation owner.
- Evaluation identity resets filters across project/version/evaluation changes. Image requests use one abort controller; paired comparison requires the API's strict benchmark result plus identical image ID/content SHA. No new polling or broad refresh owner was added.
- Current asset keys: `app.js 42.25.373`, `main.mjs 42.25.373`, `styles.css 42.25.373`, reports/training-recovery module imports `4226373`. Formal `VERSION.txt 42.24.355` is unchanged.
- Node 24 frontend 947/947 and selected Real Chrome 51/51 passed locally. Exact pushed-HEAD CI is not applicable because this batch is intentionally local-only.

> Branch: `refactor/frontend-runtime-stabilization`  
> Authority: `docs/TECH_DEBT_CLOSURE_V42_25.md`  
> Goal: reduce classic `static/app.js` to bounded shell + named runtime owners before any future framework replacement.

## 1. Latest accepted code point

```text
commit:       1c3fa7f2b5cb826c0998f249637241a59134f053
run:          34794630837
frontend:     PASS
Real Chrome:  PASS
```

Current caches/builds:

```text
app.js                  42.25.97
main.mjs                  42.25.94
visible formal version    42.24.0
internal UI build         42.25.0-dev
navigation-stability      422512
ui-state                  422500
poll-registry             422517
training-draft-runtime    422516
training-labels           422513
training-task-runtime     training-task-runtime-422503 (cache 422505)
auto-label-poll-runtime   422501
```

## Product closure — Deployment-test durable queue/progress truth CLOSED

The deployment-test business surface now preserves the same durable task truth as the unified v62 task API. Previously the v61 compatibility projection flattened a resource-waiting durable task back to persisted `QUEUED`, dropped queue/resource/worker metadata, and the final `benchPredictOne` loop only considered `QUEUED / RUNNING / CANCEL_REQUESTED` active. That combination could make a real `WAITING_RESOURCE` deployment test appear terminal or fail without showing why it was waiting.

Closed semantics:

```text
v61 business projection: delegates durable task fields to task_to_public()
compatibility aliases: id / progress / stage / result remain for the existing deployment surface
WAITING_RESOURCE: remains active and visible instead of being flattened to QUEUED
queue truth: resource_queue_position + resource_wait_reason are server-derived and visible
worker/progress truth: worker_id / phase / progress_percent come from durable public truth
active polling: after v61 creation, benchPredictOne reads /api/v62/projects/{project_id}/tasks/{task_id} while the task is active
terminal success: v61 is read once after SUCCEEDED to obtain deployment-specific result payload
frontend projection: PlatformCore.deployment.deploymentTaskView reuses taskPoller active/progress semantics
queue order / resource admission / worker claim / progress generation / process fencing: unchanged
```

Permanent guards include `tests/api/test_deployment_test_runtime.py`, `tests/frontend/deployment-runtime-source.test.mjs`, `tests/frontend/deployment-task-view.test.mjs`, `tests/unit/task_runtime/test_public_projection.py`, and `tests/unit/test_deployment_inference_process_fencing.py`. Release Regression now permanently runs the deployment business-projection contract and is triggered by the deployment task view/wiring guards. The frontend does not invent queue order or percentage; it only renders unified durable truth.

Evidence:

```text
valid RED head:             5748a89155e653a49c8a8c743cdd3de7a9fa67cf
valid RED run:              34794353496 (backend v61 QUEUED vs v62 WAITING_RESOURCE; final frontend unified-truth wiring RED)
focused/full GREEN run:     34794490531 PASS (API + frontend + public projection + deployment fencing + full frontend unit)
product commit:             0b800a54ae64507314a5f9199734759250691cb6
formal accepted clean HEAD: 1c3fa7f2b5cb826c0998f249637241a59134f053
Release Regression:         34794630826 PASS
Navigation Action Fencing:  34794630808 PASS (Real Chrome PASS)
Frontend Runtime:           34794630837 PASS (unit + full Real Chrome PASS)
formal VERSION.txt:         42.24.0 unchanged
```

All temporary deployment RED/migration helpers and workflows were physically removed before formal acceptance. No merge to `main`, tag, release, A800 RC, or genuine 10,000-image processing acceptance was performed.

Next product batch: **storage import polling owner / lifecycle-managed polling truth**. Storage import already preserves durable queue/progress display truth, but its action runtime still owns a direct `while + setTimeout(1200)` polling loop; that owner must be audited separately without mixing it into this deployment closure.

## Product closure — Cleaning frontend queue/progress truth CLOSED

The final cleaning tab now subscribes to the durable v47 cleaning projection instead of flattening server truth into a generic local row. The backend already exposed `status_text`, `progress`, `processed_images`, `total_images`, `flagged_images`, `resource_queue_position`, `resource_wait_reason`, and worker identity; this batch makes the final visible clean-tab owner preserve those values through both initial rendering and managed refresh.

Closed semantics:

```text
status text: consume server status_text; WAITING_RESOURCE compatibility projection remains “等待资源” instead of being flattened to “排队中”
queue metadata: show real resource_queue_position + resource_wait_reason when present
progress: use server progress / processed_images / total_images only; no browser-simulated percentage
worker metadata: running rows may show the real worker_id supplied by the server
polling owner: PollRegistry owns clean-tasks-v47 as a page/tab-scoped 2200 ms one-shot
refresh owner: refreshCleanOps427Delta refreshes only the cleaning task list and patches clean rows
terminal truth: awaiting_confirmation is terminal for list polling; the clean timer is not re-armed
navigation/tab change: PollRegistry clears the clean timer; switching back to AI annotation also clears it immediately
legacy recursive setTimeout(renderOps427, 2200): retired
backend queue order / claim / progress generation / worker execution: unchanged
```

`static/modules/cleaning.js` now owns the pure `cleanTaskView()` / `isActiveCleanTask()` projection. `static/main.mjs` exposes those helpers through `PlatformCore.cleaning`. `static/modules/poll-registry.js` owns `clean-tasks-v47`, and the final v427 clean branch in `static/app.js` consumes that view-model. The v47 public compatibility contract permanently requires the queue metadata fields to exist; their values remain dynamic server truth (for example, an immediately queued task may legitimately report position `1`).

Permanent guards:

```text
tests/frontend/clean-task-view.test.mjs
  - waiting-resource status/queue/progress truth
  - running worker/progress truth
  - final app.js wiring consumes cleanTaskView + PollRegistry
  - retired direct recursive clean-list timer cannot return

tests/frontend/poll-registry.test.mjs
  - clean-tasks-v47 one-shot lifecycle
  - re-arm only while active
  - stop at awaiting_confirmation
  - clear on navigation

tests/api/test_clean_unified_execution_truth.py
  - v47 public queue metadata fields are permanent
  - dynamic queue position is accepted as server truth, never forced to a frontend assumption
```

Evidence:

```text
valid RED commit:           cf3f2c4fec639903435379b3419dbaadad82c949
valid RED run:              34793075909 (245 frontend tests: 242 PASS; exactly 3 intended cleaning truth assertions RED)
focused/full GREEN run:     34793282831 PASS (focused cleaning contracts + full frontend unit + wiring guard)
product commit:             9f6f329393018623807cb4fea04707f3b5350676
formal accepted clean HEAD: 736b2acdbf2560be657011035de173cde67517d0
Release Regression:         34793457861 PASS
Navigation Action Fencing:  34793457872 PASS (Real Chrome PASS)
Frontend Runtime:           34793457920 PASS (unit + full Real Chrome PASS)
formal VERSION.txt:         42.24.0 unchanged
```

The temporary frontend migration helper/workflow were physically deleted before formal acceptance. No merge to `main`, tag, release, A800 RC, or genuine 10,000-image processing acceptance was performed.

Deployment-test durable queue/progress truth is now CLOSED. Next product scope: **storage import polling owner / lifecycle-managed polling truth**. Genuine 10,000-image processing acceptance remains explicitly deferred.

## Product closure — Cleaning durable execution truth CLOSED

The active v47 manual-clean and v55 upload-batch clean entry points now publish one durable `MATERIAL_BATCH/CLEAN` task into the shared `TaskRepository`. The Web/API process no longer owns cleaning execution through legacy daemon threads, and Web startup no longer resurrects those retired workers. Real execution is owned by the registered `materials` worker through `FencedTaskRepository` / `Scheduler` truth.

Closed semantics:

```text
manual v47 create -> prepare + publish one MATERIAL_BATCH/CLEAN durable task
v55 upload-batch decision -> the deterministic clean_task_id points to that same durable task truth
real execution -> materials Scheduler / fenced WorkerContext, never Web daemon execution
prepare -> publish crash window -> reuse the already-frozen semantic request without treating its freeze-time repository_revision as a new user intent
FAILED retry -> same task id is re-queued through TaskRepository retry; no duplicate task identity
successful scan awaiting confirmation -> durable task remains SUCCEEDED/succeeded; v47 compatibility alone projects awaiting_confirmation/review
corrupt image with corrupt_check -> successful flagged cleaning finding for review
source content changed after indexing -> remains SOURCE_CONTENT_CHANGED storage-integrity failure, not disguised as image corruption
```

A real-worker defect was also closed: `MaterialBatchHandler` had called a private artifact validation method that does not exist on the real `FencedArtifactStore`, causing Scheduler execution to fail before processing any material. The handler now validates `project_id` as a safe single path component while preserving fenced artifact access. Corrupt findings are excluded from the hash/dedup index unless real `sha256` and `dhash` metrics exist.

Permanent guards include `tests/api/test_clean_unified_execution_truth.py`, `tests/api/test_upload_clean_flow.py`, `tests/unit/test_material_batch_public_truth.py`, and the Release Regression path/test scope. The final guard explicitly proves that reading the v47 compatibility result may show `awaiting_confirmation / review` while the underlying durable record remains `SUCCEEDED / succeeded`.

Evidence:

```text
valid RED commit:           3f41cdae0d4234bf5171f2aa80111513c223407c
valid RED run:              34790397474 (intended durable-clean execution assertions RED)
focused durable migration:  34792422835 PASS (4 durable contracts + 32 upload-clean regressions)
product commit:             f43631e16a51167cf75bb8e2ec545566f226609f
formal accepted clean HEAD: 3931a9a2d529845f9e698b22f62fe950a7a8b42f
Release Regression:         34792673327 PASS
Navigation Action Fencing:  34792673293 PASS (Real Chrome PASS)
Frontend Runtime:           34792673296 PASS (unit + full Real Chrome PASS)
formal VERSION.txt:         42.24.0 unchanged
```

All one-shot cleaning migration/diagnostic helpers and workflows were physically removed before formal acceptance. No merge to `main`, tag, release, A800 RC, or genuine 10,000-image processing acceptance was performed.

Following batch status: **cleaning frontend queue/progress truth is now CLOSED**. Current next product scope is the storage import / deployment-test queue and progress truth audit.

## Product closure — Video resource queue truth CLOSED

The live v424 video task page already reads `/api/v33/projects/{project_id}/video-tasks`, whose public projection is backed by the shared durable `TaskRepository`. `task_to_public()` dynamically exposes resource-scoped `resource_queue_position` / `resource_wait_reason`; a durable queued task in the `resource_waiting` phase is publicly projected as `WAITING_RESOURCE`. The frontend previously dropped that queue metadata and also failed to classify `WAITING_RESOURCE` as an active video task, so a genuinely resource-waiting task could lose timely managed polling and never show its real queue position/reason.

Closed semantics:

```text
QUEUED: remains active under PollRegistry and shows real resource_queue_position when available
WAITING_RESOURCE: remains active, shows “等待资源”, real queue position and resource wait reason
initial render + delta polling: both use the same v424 row projection and preserve runtimeText
progress: continues to come from durable server/worker truth; no frontend progress simulation
queue ordering / claim / queue_rank / resource fencing: unchanged
cancel / stale-worker / publish fencing: unchanged
```

The fix is intentionally narrow. `static/modules/video-tasks.js` now projects the existing durable queue metadata into `runtimeText` and treats public `WAITING_RESOURCE` as active; the final v424 `videoTaskRow424()` renders that view-model text. `PollRegistry` remains the sole video polling lifecycle owner. Permanent behavior guard: `tests/frontend/video-tasks.test.mjs`, which executes the real final row renderer and verifies both queued and waiting-resource behavior.

Evidence:

```text
final permanent RED commit: 32284a8972faec46775144b8c47406e67edee014
valid RED run:              34789541200 (242 total; 239 PASS; only 3 intended video truth assertions RED)
focused/full GREEN run:     34789628840 PASS
product/self-cleanup:       c0fee2b7c8dfbf03481cbc6dfb1019f922293576
formal clean HEAD:          cb81ca39016aea0fc53ed52090f0b0199d39109a
Release Regression:         34789701814 PASS
Navigation Action Fencing:  34789703315 PASS (Real Chrome PASS)
Frontend Runtime:           34789704610 PASS (unit + full Real Chrome PASS)
formal VERSION.txt:         42.24.0 unchanged
```

No merge to `main`, tag, release, A800 RC, or genuine 10k ZIP processing acceptance was performed. One-shot product/gate migration assets were physically deleted before formal gate acceptance.

## Product closure — AI annotation polling queue metadata truth CLOSED

The durable v60 AI annotation backend/public projection already exposes real `resource_queue_position` and `resource_wait_reason`, and `annotationTaskView()` already turns that truth into `runtimeText`. Initial page rendering consumed `runtimeText`, but `AutoLabelPollRuntime` used a separate row renderer during polling refresh and omitted it. Result: a task could initially show `资源队列第 N 位` / resource wait reason and then lose that truthful metadata after the first managed poll refresh even though durable truth had not changed.

Closed semantics:

```text
initial render: durable status + progress + runtimeText
managed polling refresh: the same durable status + progress + runtimeText
QUEUED / WAITING_RESOURCE: resource queue position remains visible after every refresh
resource wait reason: remains visible when projected by annotationTaskView
no frontend queue simulation, no claim/order/resource-fencing changes
```

The fix is intentionally narrow: `static/modules/auto-label-poll-runtime.js` now renders existing `view.runtimeText` beside the status pill. No backend queue ordering, task claim, execution fencing, polling cadence, or progress semantics changed. Permanent behavior guard lives in `tests/frontend/auto-label-poll-runtime.test.mjs`; Release Regression path scope now includes both the polling runtime and its guard.

Evidence:

```text
valid RED commit:          186005b428f361e88553555b3a86013d206f11b3
valid RED run:             34788748122 (239 existing tests PASS; 1 intended queue-metadata assertion RED)
product commit:            ddb1168a8f3457fef3d875ceec79e618b75acee9
accepted clean code point: 2bc6f72fddd878a7e2d4802c5affd3d640f807e7
Release Regression:        34788824842 PASS
Navigation Action Fencing: 34788824910 PASS (Real Chrome PASS)
Frontend Runtime:          34788824849 PASS (unit + full Real Chrome PASS)
formal VERSION.txt:        42.24.0 unchanged
```

No merge to `main`, tag, release, A800 RC, or genuine 10k ZIP acceptance was performed.

## Product closure — Plain image upload whole-task progress truth CLOSED

The final live ordinary-image upload owner is the storage61 `doUploadImages426` path posting to `/api/projects/{project_id}/images`. The endpoint is synchronous HTTP, but after browser request bytes are sent the server still performs temporary-file handling, image validation, selected-storage object write, SHA256 calculation and material record commit. Therefore browser `xhr.upload` byte completion is not whole-task completion.

Closed semantics:

```text
browser byte transfer: 0% -> 85%
byte transfer complete: hold at 85%, show “文件已上传，正在服务器入库”
server-side synchronous commit: no fabricated percentage animation
successful HTTP completion after material commit: 100%, show “服务器入库完成”
network/non-2xx failure: never claims terminal 100%
```

This batch deliberately does **not** invent a durable background task, fake queue, or fake server progress for a synchronous endpoint. Terminal 100% is fenced to the authoritative successful HTTP completion. Permanent behavior guard: `tests/frontend/image-upload-overall-progress.test.mjs`; Release Regression includes that test in its permanent path scope.

Evidence:

```text
valid RED commit:          03be0050644af80709bddb97321f1a4ec0b1528c
valid RED run:             34788264443 (237 existing tests PASS; 2 intended new assertions RED)
focused migration/GREEN:   34788320142 PASS
product commit:            259d76d753993f2dd10e1963ee1a9a13887209ad
accepted clean code point: bae90eae4b3768d365d20344c1f2db9a75795ac8
Release Regression:        34788383779 PASS
Navigation Action Fencing: 34788383742 PASS (Real Chrome PASS)
Frontend Runtime:          34788383772 PASS (unit + full Real Chrome PASS)
formal VERSION.txt:        42.24.0 unchanged
```

The one-shot product migration workflow was removed in the product commit. No merge to `main`, tag, release, A800 RC, or genuine 10k ZIP acceptance was performed.

## Product mainline checkpoint — ZIP 10k import scalability CLOSED

Technical-debt cleanup remains paused by user request. Product productionization is the active line.

- **Deployment Artifact E2E CLOSED** — successful conversion jobs surface only verified, existing deployment artifacts. Product `b75b7d09780f691b01e4207c3107977b0500d8aa`, focused run `34726749756`, cleanup `8f3d3e394ceed73e5f522cba512622286fead7a5`.
- **Unified Task Truth API Phase 1 CLOSED** — `/api/v62/projects/{project_id}/tasks` remains the durable public truth for queue/resource/worker/progress metadata. Product `aa5b82ebd2140d3a9f03dc6ae6754c9b7a55afcc`, focused run `34727100684`, cleanup `6de0758e9f0c0cd45d79c48bf7fb022dde8f9ca6`.
- **Unified Task Progress Phase 2 CLOSED** — model conversion, AI annotation and cleaning/material-batch business surfaces expose durable waiting-resource/queue/worker/progress truth without parallel polling owners. Products `9817f450b3fbd20256279c3c861b0938ffdcef16` and `ff31f879b6d501a501188fed8bc78426d9eb31ea`.
- **SSE/event stream evaluation DEFERRED** — current page-scoped polling remains lifecycle-managed; no EventSource/replay/reconnect base is introduced without demonstrated need.
- **Training Progress v2 CLOSED** — existing `training-metrics.sqlite3` persists truthful latest-epoch duration, rolling ETA, throughput, losses, trainer metrics/mAP when supplied, LR and elapsed time; Worker mirrors the compact snapshot into `job.json` without extra list requests. Product `70110f9668e593215bc77c8614dd9d6dd55b7601`, focused run `34730431744`.
- **ZIP 10k import scalability CLOSED — hot-state/candidate split + live v19 owner**: baseline proved the final v36 visible ZIP action still delegated to synchronous `doImportData()` / `/api/v18/.../import`, and a synthetic 10,000-candidate v19 `job.json` was **1,370,177 bytes**. The product now routes final v36 ZIP upload through existing v19 background jobs and stores the full candidate manifest once in `scan-images.json`; hot `job.json`, running list polling and detail polling no longer carry the 10k candidate array. Create response is bounded to 500 candidates for the picker; selecting-job list preview is bounded to 300; running/terminal task state stays O(1) in candidate count. Selected-path validation reads the cold manifest. Product `b4875ada5ff084fd4e21d7c5f026f5b09128033b`, focused run `34731027723`, cleanup `e819a35c71f6aa20f7739281ddfc75e8502104ce`.
- **ZIP 10k acceptance**: focused CI created a real ZIP with **10,000 image members** and passed the v19 create/scalability contract plus existing server-import/storage regressions. The permanent legacy unit guard was migrated, not weakened (`27654cba1fb3406567a40754904531c2b53aa53f`), and the permanent Chrome material/import contract was migrated to the real v19 sequence (`60305921402204e77b8e7ed4ec8e576d9f857c4b`): create → start → list polling → terminal done → labels/current paged-material scoped refresh, with an explicit assertion that no `/api/v18/` request or broad reload occurs. Final Frontend Runtime `34733035739` passed all frontend unit guards and Real Chrome **33/33 PASS (53.9s)**; Action Fencing `34733035761` PASS.
- **Release boundary unchanged** — formal `VERSION.txt` remains `42.24.0`; visible version remains `v42.24.0`; classic `app.js` cache is `42.25.95`; `main.mjs` cache remains `42.25.92`. No merge/tag/release.

**Video resource queue truth is CLOSED. Current next product scope: continue the horizontal real queue-position/progress audit across storage import polling owner / lifecycle-managed polling surface. Genuine 10,000-image processing acceptance remains DEFERRED by explicit user instruction.**

## 2. Closed owner surfaces

### Training

```text
state.trainingDraft
→ TrainingDraftRuntime
→ TrainingSubmitRuntime
→ /train/start
```

Retired training mirrors/fallbacks stay retired.

### Polling

```text
training-jobs → PollRegistry + TrainingTaskRuntime
AutoLabel      → AutoLabelPollRuntime + PollRegistry
video          → PollRegistry(video-frames)
sources        → PollRegistry(sources)
```

No classic polling timer or creation-wrapper ownership may return.

### Navigation

`static/app.js` must contain zero classic `window.setPage=` assignments.

```text
NavigationStability.stableSetPage
  → normalizeNavigationPage
  → PageRequestScope / navigation epoch
  → PollRegistry.beforeNavigate
  → waitForNavigationReady
  → beforeInvokeNavigation
  → performNavigation(page)
  → PageRequestScope.alignPage
  → PollRegistry.afterNavigate
  → persistNavigationState
```

R1 action fencing adds `NavigationStability.action(ownerPage) → token/isCurrent/commit` for mutation-completion ownership. R2 extends the same commit fence to the true final `saveVisionModelM4`, `testModelConfigV35`, `confirmClean429`, and v60 `completeAiReview60` owners. Clean confirmation now uses authoritative `deleted_ids + processed_ids` local patching instead of broad `loadRelated()`, and v60 AI review keeps the durable `taskApi(review.id)/decisions` + `commit:true` contract. R2 product `9f6df85b994f23b5408759fb64485b9477c75936`, cleanup/permanentization `3a8781dccf6704fe76d35d99c05b80590dc507c3`, full run `34721755310` **32/32**, permanent Action Fencing run `34721755316` PASS. R1 and R2 are closed; global stale-async zero-point is still not closed because upload/ZIP/deployment/timer-callback completion families remain for the final scan.

## 3. Render/lifecycle retirement completed so far

Physically retired and permanently guarded:

```text
v42.7 render route-state alias mutation
oldRender429
previousRender61
render423Base
renderBase428 算法列表 branch
v42.2/v42.4 legacy 自动标注 route branches
renderBase424 算法列表 / 数据集 / 训练任务 branches
renderAutoLabel424 legacy 1.8s self-refresh timeout/predicate
baseRender417 visible-version correction wrapper/timers
12 historical app.js delayed versionBadge startup writers
main.mjs applyBuildVersion visible-version writer/timers
render426base page-render file-input beautification wrapper
modal426 modal file-input beautification wrapper
enhancePageV37 post-render normalization helper
baseRenderV37 duplicate versionInfo wrapper
baseModalV37 autofocus compatibility wrapper
v35/v36/V37 80/100/120ms startup render/version timers
bounded 100ms renderTop/cleanup startup timer
oldZip412 ZIP completion capture + body-wide ZIP-review MutationObserver
transport.mode-only material summary page guard / off-page summary request leakage
legacy baseRender + RAF page normalization wrapper
#view post-render MutationObserver
#modalBody normalization MutationObserver
base algorithm CRUD new/save/edit/saveEdit/view globals
v30 oldRenderAlgorithms wrapper
v39 oldViewAlgoV39 wrapper
v42.2 renderAlgorithms422/openNewAlgorithm422/saveNewAlgorithm422 generation
shadowed v423 openNewAlgorithm423(async)/saveNewAlgorithm423/editAlgorithm423(old modal)/saveEditAlgorithm423 generation
legacy dataset-group select/new/save/edit/delete CRUD generation
oldSelectDataset persistence wrapper
currentDataset helper
two shadowed historical dataset-group render bodies
zero-reference uploadImages / autoSplit / buildYolo / checkDatasetQuality / setImageSplit owners
shadowed v35/v426/v427 Model Config modal/save generations
```

`renderAutoLabel424()` itself remains referenced by historical action functions and is not yet retired as a function.

R20k did **not** retire the live `doImportData` owner. It migrated only its successful completion refresh from broad `reload()` to labels + current paged materials. Acceptance: product `1e929d47cf1a96bcb3fa17ad3eeb1e6c6029addb`, validation `60775456f3d4c8a441ba58ce65106af114aeebb2` / run `34700127243`, cleanup `f51d44c089b6342398c14bd38c8669747adad48b` / run `34700252041`, Real Chrome **32/32**. Permanent contracts: `tests/frontend/v18-import-completion-scope.test.mjs` and `tests/browser/material-pagination-performance.spec.mjs`.

R20m physically retired the shadowed early v423 algorithm create/edit generation after source-order proof and a pre-retirement Real Chrome pass showed final CRUD already resolves to the later stable 414 owners. Baseline `243bcb1b17074848d91c2c9c64d47dbed54e5e9b`, migration run `34724242632`, product `71cdb2ad192ec99b0e21bfe3c1f70bffca0f586e`, cleanup/final acceptance `40a87bf70402dccfc0387950b6856a561ce1ebe1` / run `34724354775`, Real Chrome **33/33**, Action Fencing `34724354790` PASS. `tests/frontend/shadowed-algorithm-crud-r20m.test.mjs` permanently locks owner cardinality/absence; existing `algorithm-list-performance.spec.mjs` locks live CRUD behavior. Global R20 zero-point remains open.

R20l kept the live `refreshSourceImportTasksV36` owner but removed its terminal broad refresh. Real Chrome baseline proved the old terminal `loadRelated()` fan-out; completion now calls only `refreshLabels414(false)` plus `reloadMaterialPage61()` when still on 数据集. Active source-import polling cadence remains unchanged. Product `f260127d2d41281bc1d996a172e7d4290536f24c`, migration run `34723694735`, permanentization `b17bd0c33bfb99e5557fc245a89a6c4444a8257e`, cleanup/final acceptance `f8356bcf5ec1ea128fb38db2820df38146b48cfd` / run `34723808299`, Real Chrome **33/33**, Action Fencing `34723808298` PASS. Permanent contracts: `tests/frontend/source-import-completion-scope.test.mjs` and `tests/browser/source-import-completion-scope.spec.mjs`; one-shot migration artifacts are deleted. Global R20 zero-point remains open.

R20n retired the three shadowed Model Config modal/save generations (`saveModelConfigV35`, `saveModelConfig426`, `saveModelConfig427`) after source-order proof plus the same M4 Real Chrome contract passed before and after deletion. Final M4 `saveVisionModelM4` and `testModelConfigV35` remain authoritative and action-fenced. Product `9acaa534e596464a1ebe129e435916ed7dd9cdf2`, cleanup `fce8034a861e1f9c5c0d37568891717309845794`, final accepted HEAD `b83b2bf360b891265157e602f622d409d1d2332f` / Frontend Runtime `34725907423`, Real Chrome **33/33**, Action Fencing `34725907404` PASS; app cache `42.25.93`. One-shot migration artifacts are deleted. **Further non-blocking legacy cleanup is PAUSED by user request; remaining debt stays OPEN/DEFERRED unless it blocks real use, performance, data integrity or release acceptance.**

Cross-cutting checkpoint after R20k: Resource Discovery SQLite code-level lifecycle was accepted at product `8ba4e10db5958204aca3d87779711d8e95f5d83b`. Baseline run `34700801232` proved the two target failures before migration; permanent cross-platform workflow run `34700900542` passed Ubuntu + Windows; artifact cleanup `c6ac70b670a6297ccba065854779c10b8ca47cf3` passed Frontend Runtime `34700984963` with Real Chrome **32/32**. Production soak and non-SQLite resource classes remain outside this frontend audit and OPEN.

## 4. R9 — visible version ownership consolidation

A failing Real Chrome baseline exposed a real asynchronous owner conflict. Final split:

```text
UI_BUILD_VERSION = 42.25.0-dev
  → document.documentElement.dataset.uiBuild only

static/index.html visible initial badge → v42.24.0
top412 / V412                         → visible top v42.24.0
nav426 / V426                         → visible footer v42.24.0
```

Accepted at:

```text
product:    1e9ae1118a77313d8dd3d4c0cf12d5ce5f9edff7
validation: 36fd25c48a2251d1b4a85583921c00dd98bf33fb
run:        34664755130
Real Chrome 15/15 PASS
```

## 5. R10/R11 — file-input lifecycle consolidation

### R10 page owner

The final `测试发布` page still emits ordinary `#predFile`, so `render426base` was proven live before migration. Page semantics moved to:

```text
render chain
→ cleanup(#view)
→ beautifyFileInputs426(root)
```

R10 acceptance:

```text
baseline:   6b67497ae43a32edf343fc7dec49f7b3824c1088
product:    b9d25955c185aaabb4108f3d37cfecd9f876390a
validation: 0dacf581da4acb52312f75eb7e85e6b334e060db
run:        34665470320
Chrome:     16/16 PASS
```

### R11 modal owner

A generic modal baseline locked native-file → platform filepicker behavior before retirement. After R10, `#modalBody` was already observed by the post-render cleanup MutationObserver, and `cleanup(root)` already invoked `beautifyFileInputs426`.

Final modal topology:

```text
modal innerHTML mutation
→ modalBody MutationObserver
→ cleanup(addedNode)
→ beautifyFileInputs426(root)
```

Retired:

```text
modal426
requestAnimationFrame(()=>beautifyFileInputs426(layer||document))
```

R11 acceptance:

```text
baseline:   d2aa614870a52864e991502c2218134943afb14f
product:    8ff8e7fd9dc055b6e413c273cc030e7f20a2f0c1
validation: 9bad939a70bc85c75b0897ee7b4d5a21fb2ab9d1
run:        34665890699
frontend:   PASS
Chrome:     17/17 PASS
```

All R10/R11 one-shot baseline/migration helpers/workflows were deleted after acceptance.

## 6. R12 — post-render normalization consolidation

`enhancePageV37()` was still live and owned table wrapping plus old “使用建议” panel removal. A permanent Chrome contract first locked modal table wrapping and first-field autofocus. Normalization then moved into the later cleanup owner:

```text
cleanup(root)
→ wrap table.table in .table-wrap when needed
→ remove historical guidance panels
→ existing file-input/placeholder/empty-state cleanup
```

`enhancePageV37` and its RAF callbacks are now absent. `baseRenderV37` remains only for `state.versionInfo` compatibility; `baseModalV37` remains only for modal autofocus.

```text
baseline:   6ae19dc79abbf690371a71162c97a2df6322518b
product:    202a5a82b0cb4629423ee0c6812f649031234daa
validation: 60d87751e4e259a3a8ef11e6c1a5d5a9ea42ab29
run:        34666673017
Chrome:     18/18 PASS
```

### R13 — duplicate V37 render version write

`baseRenderV37` was reduced by R12 to a single `state.versionInfo.version=42.24.0` write. A later V42 render owner writes the same formal version before delegating into the old render chain, so R13 removed the duplicate wrapper without moving any UI behavior.

```text
product:    928d2387d46a0472bd202bd4df84af8d1573b6c2
validation: 43e31c7e683fbda4b9c36a3d35188262b6a9ff1b
run:        34666985800
Chrome:     18/18 PASS
```

At R13, `baseModalV37` autofocus and the V37 120ms startup timer still remained; both were handled in the next two bounded batches.

### R14 — modal autofocus owner consolidation

The autofocus semantic moved into the base `modal()` function and `baseModalV37` was physically removed.

```text
product:    6eafbe21c3c364a3e8099fd7ff3cdaf2a19e4829
validation: 8593516eb796f10fb43cea748bcc42b479e0a02e
run:        34667341153
first pass: 17/18 due to training-task /materials race
rerun:      18/18 PASS
```

A dedicated diagnostic then repeated the focused training performance test 10 times. All 10 passed and each first refresh contained only `GET /jobs`, proving the training refresh owner itself was not issuing `/materials`.

### R15 — startup render timer retirement

Three historical startup compatibility wakeups were removed:

```text
v35  80ms  versionInfo + render
v36 100ms  versionInfo + render
V37 120ms  versionInfo + render
```

Final startup remains owned by `queueMicrotask → final __clInit`. The separate 100ms `renderTop(); cleanup(document)` wakeup was later retired in R18 after final-render normalization ownership was proven.

```text
product:    280a31bf365b1a6646a57213dfa2dff97e10e0b5
focused:    startup readiness PASS; training performance 5/5 PASS
validation: b6edea36296ab9548037457a124b4369776f6f5e
run:        34667776611
frontend:   PASS
Chrome:     18/18 PASS
```

### R16 — event-owned ZIP completion + page-scoped material summary

R16 converted two asynchronous lifecycle guesses into explicit/scoped owners. The former body-wide ZIP review `MutationObserver` could fire after `pollImport411()` exposed `stage=导入完成` but before the final completion `resultHtml` write, so its persisted review action could be overwritten even though the DOM button and auto-open had already appeared. ZIP review is now invoked explicitly after the final successful completion state is written.

The second failure source was `refreshSummary61()`: its 250/1200ms startup timers only checked stale `transport.mode==='paged'`. Because final navigation no longer uses the early material-aware `setPage` wrapper, those timers could issue `/materials` after navigation to 训练任务. `refreshSummary61()` is now strictly gated by the live paged 数据集 page both before and after its requests.

```text
baseline:        540de6aef4ddbf82a6cf36994a31a73937abca73
baseline run:    34668429941 → 17/19
                 ZIP persisted review false
                 training-task unexpected /materials request
product:         12df27e2af9155e3a1b9f745e46605396e321815
focused run:     34668639496
                 ZIP completion PASS
                 training refresh isolation 5/5 PASS
validation:      540c0944f45030ea198af2be153c1505f71e62f0
full run:        34668702371
frontend:        PASS
Real Chrome:     19/19 PASS
```

Permanent proof: `tests/frontend/lifecycle-event-ownership.test.mjs` plus the browser contract `ZIP import completion surfaces review action and auto-opens review`.

### R17 — final page normalization ownership

R17 removed the remaining page-side triple ownership (`baseRender` wrapper + page RAF cleanup + `#view` MutationObserver). Source-order proof showed the storage wrapper is the final `render` assignment in `static/app.js`, so page normalization now runs exactly once after the final render path through the named `PostRenderNormalizationRuntime`. Modal normalization remains independently owned by the `#modalBody` observer and was intentionally not changed in this batch.

```text
product:         4fc5d90a15ef2fc2dc22aa00f39967deba6f53f8
validation:      c3301d065fa820539873a4fa2f739992ef63f3d2
guard alignment: f5b8ff8789de0f51d2a03bcabe126191005ba24c
full run:        34669152742
frontend:        PASS (179/179)
Real Chrome:     19/19 PASS
```

The first full validation correctly exposed one stale structure-bound storage-owner unit assertion; the product behavior was not reverted. The guard was tightened to require one storage route owner plus one final page-normalization call, then the full suite passed.

### R18 — bounded startup cleanup timer retirement

R18 retired the remaining readiness-bypassing `setTimeout(()=>{renderTop();cleanup(document);},100)` wakeup. Final startup already waits for the v53 snapshot/current-page refresh and then calls the final `render()`, while R17 made that final render the sole page-normalization dispatch. The modal observer was deliberately left untouched because post-open base-modal body mutations still depend on normalization.

```text
product:    1572fdf4fad6e0fe8d10b5253a236722e85b3495
validation: 954e9dba9c891ecd5c7f21144cf00d8664c11620
run:        34670319479
frontend:   PASS
Real Chrome: 19/19 PASS
```


### R19 — explicit modal content ownership

R19 retired the last active DOM normalization observer. A permanent Real Chrome baseline first locked a real post-open base-modal refresh path (后台导入任务 → 刷新). Modal content writes now go through `ModalContentRuntime.replace(root, html)`. When `root.id === 'modalBody'`, that owner synchronously invokes `PostRenderNormalizationRuntime.apply(root)`; preview/review rewrites also route through the same content replacement owner. `static/app.js` now contains zero active `MutationObserver` constructions.

```text
baseline:   6f5fac4313d23083c6bbe9e2a3b8a5284cd49583
product:    1bb210fbb10a7bee9f5b875d0dd6016187c1ef72
validation: f60d00096a0929a63d0370494ef1f1d489f54ca3
run:        34670989473
frontend:   PASS
Real Chrome: 20/20 PASS
```


### R20a — algorithm version deletion scoped refresh

R20 started the global `reload() → loadAll() → loadRelated()` request-debt migration with one proven-live mutation path. The algorithm version delete modal behavior was locked first. The final `delVersion` owner now performs the DELETE and delegates refresh to `AlgorithmListRuntime.refresh({render:true})`, which owns only algorithms + jobs. The browser contract permanently forbids the datasets/images/labels/training-environment/bootstrap request fan-out on this path while allowing unrelated background owners such as the import-job poll to run independently.

```text
baseline:   55f21733121d1280be66548ef4bb13c1c3810737
product:    22c552d27928375dd51081eb152dc25b1554ec18
validation: 103d630b24bd1aad77190149291c4c9f25e8ab75
run:        34677761599
frontend:   PASS
Real Chrome: 21/21 PASS
app.js:     42.25.77
main.mjs:   42.25.82
```

This closes only the version-delete refresh path. R20/global reload debt remains **IN PROGRESS** and must continue mutation-domain by mutation-domain.

### R20b — model-version publish local state ownership

The final live 测试发布 `saveAssign` owner previously performed a successful version POST and then invoked global `reload()`. The backend already returns the authoritative created `version`, so the owner now patches `state.algorithms`, removes the matching pending model, clears transient assignment state and renders locally. The permanent browser request contract requires exactly one publish POST and forbids bootstrap/algorithms/pending/jobs/models/training-resource reload fan-out from this action.

```text
initial baseline:   b41340d4ee292f7e8e268f4bd59206efe072d690 / 34678815343 → 21/22
corrected baseline: b7043a5b780c9d0c4ca160c4bc7d7951a83198ff / 34678924407 PASS
product:            4a2eb2a78869db0b91f1920ff4b7ba3b0dd45b89
validation:         d18044d3d98231affc7488974e04623dab6d2b10 / 34679069872
frontend:           PASS
Real Chrome:        22/22 PASS
```

The initial baseline failure was only an incorrect test assertion against modal text; the model name is rendered as a disabled input value. No product fix was hidden by that correction.

### R20c — training-server refresh ownership

`saveServer` is a proven-live final owner from the training-resource server connection flow. Its former `await reload()` reached the final `refreshCurrentPage413` binding, so a server POST caused a bootstrap snapshot plus 训练资源 extras. Because canonical training targets come from `/api/training_options`, R20c narrows the mutation to exactly the required refresh domain: POST `/api/train_servers`, GET `/api/training_options?project_id=...`, replace `state.targets`, local render. No bootstrap snapshot belongs to this mutation.

```text
baseline:           63de3724ff794dd8712b359a806cd86eb5e3476b / 34679508471 PASS
product:            b790c53e1a766d617c6b834ee69f1335b2e17010
focused migration:  34679584971 PASS
validation:         e3f23f59a4e1513b807490465e94c5558f805c14 / 34681236515
frontend:           PASS
Real Chrome:        23/23 PASS
```

### R20d — Paddle resource refresh ownership

The final late resource-runtime overrides of `detectPaddle` and `quickPaddleDetect` were proven live. Both previously ended in `loadAll()`, whose final binding includes a bootstrap snapshot. The new named helper `refreshPaddleTrainingTargets20d()` fetches only `/api/training_options?project_id=...` and replaces `state.targets`; manual and quick Paddle activation both delegate to it after their required POST sequence.

```text
baseline:                53411a7d26bfd2a9e20f4fd9723d87e5b67a5920 / 34681755467 PASS
first migration run:     34681841986 stopped before commit because the generated unit file had invalid JS newline escaping
helper fix:              e90cfeeb927df7331aa5ca52631f6dd618068f9d
product:                 d4cb8851de061436d030c2a677c009b43d208fc6
focused migration:       34681905173 PASS
validation:              a21846c33d79612f9ab4a47e2a69195da29caa3b / 34681966242
frontend:                PASS
Real Chrome:             24/24 PASS
```

No product was committed by the failed first migration run. Permanent proof now locks select/test/detect payload semantics, canonical target refresh, and bootstrap=0.

### R20g — scoped import completion ownership

The final live ZIP completion path and server-storage confirmation path now avoid broad `loadRelated()` / `loadAll()` fan-out. Permanent owner tests require label refresh only when needed and paged material refresh only for the active 数据集 page. One-shot migration artifacts were physically removed after acceptance.

```text
product:          a67778fd9b60384dbfffa2156e99670d244dadc9
validation:       a2f4cb40abb6d70ad4faf89bde60c1ee39e4a179
validation run:   34693503185
Real Chrome:      30/30 PASS
artifact cleanup: 6337f1a0379c7e60fbbc459668090504c0b6095b
cleanup run:      34695825386
cleanup Chrome:   30/30 PASS
```

### R20h — algorithm CRUD / shadowed generation retirement

R20h removed the broad-reload algorithm CRUD generation and three later shadowed algorithm compatibility layers after proving final routing ownership. Current create/edit/delete mutations use stable 414/423 owners and patch authoritative `state.algorithms` locally.

```text
product:        d58e690ffcc1523f213a65cfc0a57380ffdc571e
focused run:    34696508446
validation:     210a9ad1f6271a8a8986db3f223f4813a6cce288
validation run: 34696729028
frontend:       PASS
Real Chrome:    31/31 PASS
```

Permanent proof:

```text
tests/frontend/legacy-algorithm-crud-owner.test.mjs
tests/browser/algorithm-list-performance.spec.mjs
```

Intentional survivors are explicit: base `renderAlgorithms()` is now only a bounded delegate to `renderAlgorithms423` because older global render maps still evaluate the symbol; the later `window.showReport` compatibility owner remains live because `viewAlgorithm423/versionRows423` still references it. One-shot R20h migration artifacts are physically deleted.

## 7. Current live render topology

Confirmed live; do not delete as whole layers without new proof:

```text
oldRender412
  算法列表 / 数据集 stable routing

renderBase428
  训练任务 routing only

renderTraining423
  current training renderer
  directly owns PollRegistry.replaceTrainingJobTimer()

renderBase427
  canonical 自动标注及清洗 route owner

renderBase424
  质量中心 / 视频切帧 route owner only

oldRenderV39
  deployment conversion/artifact/resource/plugin/component routes

render414Base
  标签管理 route

finalRender
  素材存储配置 final route owner + final page normalization dispatch

PostRenderNormalizationRuntime.apply / cleanup(root)
  final-render page normalization
  table wrapping + page/modal file-input beautification

ModalContentRuntime.replace(root, html)
  explicit base-modal and modal-like content replacement
  applies normalization synchronously for #modalBody

base modal()
  modal first-editable-field autofocus

completeZipImportReview412
  explicit successful ZIP completion review owner

refreshSummary61
  material summary owner scoped to paged 数据集
```

Still under audit:

```text
older base/global render generations reached through delegates
global reload / loadAll / loadRelated request ownership
```

`baseRender417`, `render426base`, `modal426`, `enhancePageV37`, `baseRenderV37`, `baseModalV37`, and the v35/v36/V37 startup render timers are CLOSED and must not return.

## 8. Permanent contracts

Frontend includes:

```text
tests/frontend/render-alias-restore.test.mjs
tests/frontend/render-owner-retirement.test.mjs
tests/frontend/version-marker-owner.test.mjs
tests/frontend/file-input-beautification-owner.test.mjs
tests/frontend/post-render-normalization-owner.test.mjs
tests/frontend/startup-render-owner.test.mjs
tests/frontend/lifecycle-event-ownership.test.mjs
tests/frontend/modal-content-owner.test.mjs
tests/frontend/algorithm-version-refresh-owner.test.mjs
tests/frontend/algorithm-version-publish-owner.test.mjs
tests/frontend/training-server-refresh-owner.test.mjs
tests/frontend/paddle-resource-refresh-owner.test.mjs
tests/frontend/model-config-save-refresh-owner.test.mjs
tests/frontend/auto-label-poll-runtime.test.mjs
tests/frontend/navigation-stability.test.mjs
tests/frontend/navigation-persistence.test.mjs
```

Current file-input ownership contract requires:

```text
render426base absent
modal426 absent
old page/modal RAF beautification callbacks absent
cleanup(root) invokes window.beautifyFileInputs426?.(root)
#view observer remains retired; #modalBody normalization observer is retired; ModalContentRuntime owns modal content replacement
测试发布 #predFile receives native-file426 + filepicker426
ordinary modal file input receives equivalent filepicker behavior
```

Current accepted Real Chrome suite: **28/28** in run `34690924552`.

## 9. Remaining technical-debt targets

```text
loadAll / loadRelated / loadCore412 ownership
global reload / duplicate requests
proven dead app.js/runtime shell
cache-busting heterogeneity
MutationObserver / setInterval / setTimeout / fetch lifecycle
version-number business naming
final zero-point scan
```

## 10. Audit method

For every candidate:

```text
live HEAD
→ exact assignment/capture/reference topology
→ identify live owner vs shadowed generation/branch
→ lock real semantic behavior
→ migrate semantic ownership if needed
→ double-owner equivalence where semantics move
→ bounded physical deletion
→ permanent guard
→ frontend + Real Chrome
→ delete temporary migration artifacts
→ docs sync
```

Do not delete by version suffix alone. Do not add a global render-repair loop. Prefer semantic/page-scoped owners and explicit lifecycle cleanup.

## 11. Non-negotiable rules

1. No new numbered compatibility generation.
2. Retired training mirrors/fallbacks stay retired.
3. Classic `setPage` ownership remains zero in `app.js`.
4. `state.page==='自动标注'` remains zero in `app.js`.
5. Render must not resume route-state alias mutation.
6. Legacy AutoLabel route/timer owners stay absent.
7. `renderBase428` remains training-only unless semantics move first.
8. `renderBase424` remains quality/video-only unless semantics move first.
9. AutoLabel remains PollRegistry-only.
10. `baseRender417`, `render426base`, `modal426`, `baseModalV37`, legacy startup render timers, and delayed visible-version writers stay retired.
11. Internal build metadata must never become a visible formal-version owner.
12. File-input page/modal behavior must stay covered while cleanup/observer lifecycle is refactored.
13. No mother-model class inheritance on first training.
14. Explicit false/zero training settings survive end-to-end.
15. Trial/test inference never receives GT labels.
16. Do not weaken duplicate-request/race/performance/Real Chrome tests.
17. Frontend CI is not A800/CUDA acceptance.

## 12. Work order

```text
1. continue R20 global reload/request mutation-domain migration
2. app.js dead code/runtime-shell cleanup
3. cache-busting unification
4. zero-point observer/timer/fetch/render/setPage scan
5. semantic naming + deterministic tests + docs
6. technical-debt zero-point scan
7. A800 RC
```

### R20e — live model-config / prompt mutation refresh retirement

The next source-order audit found three genuinely live mutation owners in the final 模型配置 surface. The old prompt save/delete path was not merely expensive: because model-page extras reload model configs but not prompt templates, its global refresh left prompt UI stale.

```text
baseline:             afa2bfcb474cc9970129723af5589ab74a26eca7 / 34683803977 → 1/3 PASS
first migration run:  34683969019 → unit 3/4, over-escaped wiring assertion only; no product commit
guard fix:            becabf102d10520db52fdac9af1d5238357aa3f3
focused:              34684037005 → unit 4/4 + Chrome 3/3 PASS
product:              febece523b462692cc857431cb901fc5a863d091
validation:           89327ded9da924753f5f900fc3b79e6df353927f / 34684119911
frontend:             PASS
Real Chrome:          27/27 PASS
```

Live mutation topology is now local/authoritative: model-config delete filters `state.modelConfigs`; prompt save upserts the POST/PUT result into `state.promptTemplates`; prompt delete filters that collection. None of these actions may issue bootstrap/model-config/prompt-template follow-up GETs.

The full run also emitted one non-fatal resource-discovery SQLite `database is locked` during cache initialization. Keep that as a separate concurrency audit target.


### R20f — final M4 model-config save ownership

The first R20f source-only audit selected `saveModelConfig427`, but runtime evidence showed that the visible modal is restored to the earlier M4 implementation by a capture/final-activation chain:

```text
M4 openModelConfigModalV35
→ window.__m4OpenModelConfig capture
→ later 427 compatibility overwrite
→ file-tail M4 final activation
→ openModelConfigModalV35 = __m4OpenModelConfig
→ saveVisionModelM4
```

The old live M4 save owner POSTed/PUT the model configuration and then called `loadRelated()`. The accepted owner now upserts the authoritative saved item directly into `state.modelConfigs` and renders locally; no bootstrap/project/dataset/material/label/algorithm/model-config GET fan-out belongs to the mutation.

```text
baseline:            dddcd3f1eecf27c5b7447a16939e53473ff1d745
readiness alignment: da3f3cee7565b75f0a2de926dfdbdb42f7b30ab9
diagnostic run:      34690682894
product:             c9b7ab44192d38c37753643ee790fc2e089c8598
validation:          94dbebb43d83b1d522ea4e3f6522154417f3e985 / 34690924552
frontend:            PASS
Real Chrome:         28/28 PASS
```

Audit rule added by R20f: **textual last assignment is insufficient when a runtime capture/restore or final-activation layer exists**. Inspect capture aliases and end-of-file restorations before classifying a function as final/live. R20 remains **IN PROGRESS** for the remaining global-refresh zero-point audit.

## R20i — legacy dataset-group owner retirement

Source-order audit proved the late final route executes `renderDatasets424()` directly. Two older dataset-group page bodies and their CRUD/persistence helpers were therefore physically unreachable. R20i removed them while retaining one bounded `renderDatasets() → renderDatasets424()` delegate for historical render-map symbol compatibility.

```text
product:          feeb98f441bb1fe5d0f8f409a1509c66606e59ef
validation:       11131ca30c17809e016807aa6c75b0bf203fa6f8
validation run:   34698850495
cleanup:          a7116811adb26ebe5f0f9e621bf23df1dd1f605f
cleanup run:      34698983278
frontend:         PASS
Real Chrome:      31/31 PASS
app.js cache:                42.25.95
```

Permanent proof: `tests/frontend/legacy-dataset-group-owner.test.mjs`. Next audit target is the remaining legacy dataset action block; do not conflate it with live `renderDatasets424` / MaterialPagination behavior.

## R20j — zero-reference legacy dataset actions

The current-source liveness audit found exactly one assignment and no caller for each of `uploadImages`, `autoSplit`, `buildYolo`, `checkDatasetQuality` and `setImageSplit`. They were physically removed and permanently guarded. The audit deliberately excluded `doImportData`: final v36 `importData()` still calls that unique v18 XHR owner.

```text
product:            e6398f7d8ae665079c82d64217c434af4a73073c
focused run:        34699354229
validation:         693a2fa2c3d39378782ac2270a95924eff5ca5ec
validation run:     34699442423
cleanup:            9c7a3497b9acf69364d83e5cf778ec4139bdbc69
cleanup run:        34699599796
frontend:           PASS
Real Chrome:        31/31 PASS
app.js cache:                42.25.95
```

Permanent proof: `tests/frontend/legacy-dataset-action-shell.test.mjs`. Next audit/migration target: live `doImportData` completion request scope; do not delete it as historical shell.



<!-- V42_25_ZIP_P1_ANNOTATION_SQLITE_ATOMICITY_20260913 -->
## 2026-09-13 — ZIP Processing P1 + Annotation SQLite Dataset Delete Atomicity

### ZIP Processing P1 — CLOSED

- 目标：量化并移除 1,000/10,000 图 ZIP 实际处理阶段的逐图放大，不改变导入语义。
- 同一 GitHub Actions runner、1,000 张真实 JPEG + YOLO txt 的前后基准（run `34733781003`, job `103661376150`）：
  - `get_project`: `2002 -> 1`
  - `material_patch`: `2000 -> 0`
  - `MaterialRepository` 初始化：`4002 -> 2002`
  - annotation 初始化 / upsert：保持 `2000`，本批未跨越 annotation 事务边界
  - wall time：`11.2115s -> 10.0417s`，同 runner 约 `1.116x`（约 11.6%）
  - 导入 1000 图、1000 框、最终 material/annotation 计数完全一致。
- 产品提交：`6fb34ebd07f5c6f460c58e3360825dbab49fea44` (`perf(import): remove per-image ZIP processing amplification`)。
- P1 明确只消除了重复 project `meta.json` 读取和 batch 内无效 material projection；没有用放宽断言换性能。

### Annotation SQLite Dataset Delete Atomicity — CLOSED

- 审计确认旧 dataset-delete journal 仍以 `annotations/{image_id}.json` 为删除/恢复对象，但当前标注真值已经是 `annotations.sqlite3`；成功删除数据集此前会留下 orphan SQLite annotation，异常恢复也无法覆盖当前 GT。
- 新架构不恢复 per-image JSON shadow，也不把 10k 完整 boxes 塞进 JSON journal；`AnnotationRepository` 增加 SQLite 内部 durable delete backup：`annotation_delete_backup`。
- 删除协议：`prepare_delete(token, ids)` 持久备份 -> 物理文件 staging -> material finalize -> annotation `finalize_delete(token)`；失败/恢复使用 `restore_delete(token)`，成功清理使用 `complete_delete(token)`。
- `finalize_delete` 只删除 `content_digest` 仍与备份一致的 annotation；并发标注变化时拒绝 stale delete。`restore_delete` 使用不覆盖已有新行的恢复语义。
- v50 buffered image batch 被拒绝时，同时清理真实 SQLite annotation，避免 orphan GT。
- Windows 文件锁回归改为锁真实上传图片文件，仍要求 409 + 数据集/material/annotation 完整保留；不再依赖不存在的 per-image JSON。
- 迁移 run `34734781793`：旧代码新合同 RED；两个历史 JSON-shaped guards RED；迁移后原子性组 `14 passed`，annotation/ZIP 回归 `7 passed`，正式 `VERSION.txt=42.24.0`。
- 产品提交：`e79eaa60ac18cbd5b78ad6df7bdb109643127871` (`fix(annotations): make dataset deletion atomic with SQLite truth`)。
- 永久化/一次性脚手架清理：`da676db7994c69b06b0084e000c5812d1206f87d`；长期 workflow：`Material Annotation Atomicity`。
- cleaned HEAD 长期验收：
  - Material Annotation Atomicity `34734901591`: PASS
  - Navigation Action Fencing `34734901538`: PASS
  - Frontend Runtime Stabilization `34734901543`: frontend PASS；Real Chrome `33/33 passed (1.0m)`
- 正式 `VERSION.txt` 仍为 `42.24.0`；未 merge main、未 tag、未 release。

### 下一主线

- ZIP Processing P2：先量化剩余 annotation 热点。P1 后 1,000 张 YOLO 仍有 `2000` 次 AnnotationRepository 初始化/upsert（初始 `unannotated` + 最终真实 annotation 各一次）。
- P2 必须先建立事务/失败回滚/负样本语义基线，再决定是否做单图双写折叠、连接复用或批量 annotation commit；禁止为了速度破坏标注真值和 dataset-delete 原子性。

<!-- ZIP-P2AB-2026-09-13 -->
## 2026-09-13 — ZIP Processing P2a / P2b verified checkpoint

状态：**P2a CLOSED；P2b（YOLO）CLOSED。COCO/VOC 同类双写仍 OPEN，后续按 P2c 单独建基线，不把 P2b 泛化为全格式完成。**

### P2a — annotation connection amplification

- 成功迁移 run：`34735300276`，job `103665544357`。
- 产品提交：`6e03e5467e4797b6b935f693953d20c16276c89d` — `perf(import): reduce annotation connection amplification`。
- 永久化 checkpoint：`cb0ff301c034813151703b320e593f8e54875cdb`。
- 1000 张 YOLO 同路径：annotation SQLite connections `6000 -> 2001`；follow-up `get()` `2000 -> 0`；`AnnotationRepository` 初始化 `2000 -> 1`；wall `9.4311s -> 7.6136s`，约 `1.239x`。
- annotation upsert 数量仍为 `2000`，因此 P2a 明确没有通过推迟/删除 durable annotation write 来换性能。

### P2b — YOLO final annotation single durable write

- 热点 profiler run：`34737776295`，job `103672131158`。1000 张下 `annotation_upsert_many` 是主要热点；图片解码与 SHA256 不是主因。
- RED + 迁移 + 同 runner 前后 benchmark run：`34737932595`，job `103672530091`。
- 旧代码基线：P2b 新合同 `3 failed, 1 passed`；失败准确覆盖 `annotation_builder` 不存在与 YOLO `40 != 20` 双写。
- 产品提交：`2be7dd8d1dc7d275fe71f8e0c17604febdf6368c` — `perf(import): write final YOLO annotation once`。
- 永久化/一次性脚手架清理：`d2cda6cab9b9c3b3427cb5f63c833c052f3a069e` — `test(import): permanentize ZIP Processing P2b`。
- 1000 张同 runner：`write_annotation 2000 -> 1000`；`annotation_upsert_many 2000 -> 1000`；annotation connections `2001 -> 1001`；wall `8.097123s -> 6.218626s`，`1.302x`，耗时下降约 `23.2%`。
- 结果不变：`report_imported_images=1000`、`report_boxes=1000`、`material_total=1000`、`material_boxes=1000`、`annotation_total=1000`、`annotation_annotated=1000`。
- 语义护栏：结构化 YOLO 在 `add_image_record()` 返回前直接持久化最终 GT；普通上传仍立即持久化 `unannotated`；空最终 GT 仍为 `confirmed_empty`；dataset-delete / v50 batch rollback 原子性合同继续保留。
- focused contracts：`10 passed`；annotation/material/import regressions：`17 passed`。

### Cleaned HEAD permanent gates

- Material Annotation Atomicity：run `34738062791` PASS，P2b 永久合同已纳入。
- Navigation Action Fencing：run `34738062810` PASS。
- Frontend Runtime Stabilization：run `34738062795` PASS；Real Chrome `33/33 passed`（53.5s）。
- 一次性 P2b profiler/migration workflow + helper 已物理删除；永久测试 `tests/api/test_zip_processing_p2b_single_final_annotation.py` 保留。
- 正式 `VERSION.txt` 仍严格为 `42.24.0`；未 merge `main`、未 tag、未 release。

### Next measured candidate

当前源码确认 `_v18_import_coco()` 与 `_v18_import_voc()` 仍存在 `add_image_record()` 后再 `write_annotation()` 的双 durable write 结构。下一批若继续，应作为 **P2c COCO/VOC structured-import single-write** 独立建立 RED、原子性合同与真实 benchmark；不要直接复用 YOLO 结论。

## ZIP Processing P2c — COCO/VOC structured-import single-write CLOSED

P2c is CLOSED with independent COCO and VOC RED → migration → GREEN → permanent-guard evidence; the YOLO P2b conclusion was not assumed to apply automatically.

```text
baseline + migration run: 34742240350
old COCO RED:             6 images -> 12 annotation upserts
old VOC RED:              6 images -> 12 annotation upserts
product:                  02ce1845d36dfa59e69e2a600d03a31b4da05d13
permanentization/cleanup: 233248847797023bc98bf0974490430139be3641

1000 COCO before:
  annotation writes/upserts: 2000
  annotation connections:    2001
  wall:                      13.599580s
  throughput:                73.532 images/s

1000 COCO after:
  annotation writes/upserts: 1000
  annotation connections:    1001
  wall:                      6.922337s
  throughput:                144.460 images/s
  wall speedup:              1.9646x

1000 VOC before:
  annotation writes/upserts: 2000
  annotation connections:    2001
  wall:                      10.693482s
  throughput:                93.515 images/s

1000 VOC after:
  annotation writes/upserts: 1000
  annotation connections:    1001
  wall:                      10.427986s
  throughput:                95.896 images/s
  wall speedup:              1.0255x
```

Both formats preserve `1000 material / 1000 annotation / 1000 boxes` truth. COCO and VOC now create the image record with the final annotation builder, so structured import no longer persists a temporary `unannotated` row and then rewrites the final GT. Plain image upload still retains immediate durable `unannotated` semantics; mixed structured imports retain `annotated` and `confirmed_empty` state/version contracts.

Permanent cleaned-head gates on `233248847797023bc98bf0974490430139be3641`:

```text
Material Annotation Atomicity: 34742373484 PASS
  atomicity/import contracts: 22 passed
  annotation/ZIP regressions:  7 passed

Navigation Action Fencing:     34742373492 PASS

Frontend Runtime Stabilization:34742373480 PASS
  Real Chrome:                 33/33 PASS (1.1m)
```

One-shot P2c migration workflow, migration helper and profiler were physically deleted after permanentization. The permanent P2c contract remains under `tests/api/test_zip_processing_p2c_structured_single_final_annotation.py` and `Material Annotation Atomicity`.

Post-P2c profiler decision: no new P2d is justified at this checkpoint. After single-write, COCO/VOC have one annotation upsert per image, one storage upload per image, one dataset-writable check per image, `get_project=1`, and one buffered material mutate; the remaining dominant timings are necessary per-image storage/annotation work rather than a newly demonstrated duplicate fan-out. Do not create P2d without new measured evidence.

**NEXT:** genuine 10,000-image processing-phase acceptance. Full 10k processing acceptance remains OPEN until wall time, throughput, resource/FD/SQLite behavior, progress cadence, rollback/recovery and final material/annotation/box truth are measured on a real annotated dataset.

Formal `VERSION.txt` remains `42.24.0`. No merge to `main`, no tag, no release. Technical-debt mainline remains PAUSED; A800 RC remains DEFERRED.

### 2026-09-13 cross-layer guard — durable cancel/resume truth CLOSED

Frontend/API control semantics are now fenced by durable server truth: ordinary v48 resume already rejects non-`RUNNING+paused`; the repository additionally rejects `set_stage()` once persisted status is `CANCEL_REQUESTED`, closing the concurrent stop/resume race rather than relying on the browser or an earlier API read. Real API regression is permanently included in `v42.25 Release Regression`; product `7cab9413185d0bfbc8052d978685ee7a2e8b46d0`, permanentization `dfa9623ad75eab9d7e0945cd45051688492e87f8`, Release `34749914123` PASS, Frontend Real Chrome `34749914114` PASS, Navigation Real Chrome `34749914211` PASS.

<!-- deployment-inference-process-fencing-closed-2026-09-13 -->
## Deployment test inference process fencing — CLOSED (2026-09-13)

Deployment-test subprocesses are now part of the durable execution fence instead of being invisible raw `subprocess.Popen` children. The runner is launched through the shared cross-platform process controller, binds exact `PID + create_time + command_hash` to the durable task, terminates the exact process tree on user cancellation or execution/lease fencing, and re-checks the current execution generation before result persistence.

Evidence:
- valid RED: GitHub Actions `34752083670` — real runner PID existed while durable `process_pid` was `None`;
- product: `97efe23ce2d587027150032f71906f03a75fcc51` (`fix(deployment): fence inference runner process`);
- focused GREEN: `34752147610`;
- permanentization: `fbbacad583a8f5ad50b27b1fcb6624b31255658e`;
- cleaned v42.25 Release Regression: `34752225736` PASS (runtime + training-data);
- cleaned Navigation Action Fencing: `34752225727` PASS including Real Chrome stale-mutation;
- cleaned Frontend Runtime Stabilization: `34752225677` PASS including Real Chrome runtime regressions;
- one-shot deployment process-fencing workflow removed during permanentization;
- formal `VERSION.txt` remains `42.24.0`; no merge/tag/release.

Genuine 10k processing acceptance and A800 RC remain deferred and are not closed by this batch.

<!-- RUNTIME-PROD-CLOSURES-2026-09-13-B -->
## 2026-09-13 — runtime productization closures: video publish + AI annotation cancellation

### Video frame publish cancellation / stale-execution fencing — CLOSED

- Valid RED run: `34752569787`. Old worker continued frame publication after durable cancellation and uploaded `3/3` frames after execution fencing/lease loss.
- Product: `8d267ae86a0a3030aa7faff8d4eccb9a1882b1d9` (`fix(video): fence frame publishing cancellation`). Every publish-side effect is guarded by cancellation/current-execution checks; late stale workers cannot continue material/result publication. Commit-phase progress now continues through the prior 90% plateau toward 97%/98%.
- Focused GREEN: `34752658173`.
- Permanentization: `22378473e077749ee5dc9de80ee9993daf28be64`; permanent contracts include `tests/unit/test_video_commit_fencing.py` plus the real video-worker integration path.
- Annotation integration was aligned with the already-authoritative SQLite truth (`annotations.sqlite3` / `AnnotationRepository`): no per-image JSON shadow was restored. Alignment/accepted HEAD: `cf81fd8b756d902cc6f9168f5f14d6357c806055`.
- Cleaned-head gates: Release `34752863299` PASS; Navigation Action Fencing `34752863247` PASS; Frontend Runtime `34752863225` PASS including Real Chrome.

### AI annotation in-flight cancellation side-effect fencing — CLOSED

- Valid RED run: `34753095270`. Cancellation during materialization still allowed one model inference call; cancellation during an in-flight model call still persisted the returned candidate.
- Product: `a1dabee5d867b19c9815c525e01793692db8b0a5` (`fix(annotation): fence cancellation around inference`). The worker re-proves cancellation/current execution immediately before provider inference and again after inference returns but before candidate/manifest writes. `InterruptedError` / lease-loss `PermissionError` remain control flow and are not converted into failed AI candidates.
- Focused GREEN: `34753193608`.
- Permanentization: `0d1c51f4caa25e1d653a32a5a790e792631126ca`.
- Existing candidate guards were migrated to current stronger truth in `3f6a63362a850049ebe6358d12eecf7d984ae79e`: failed provider generations do not inflate human `unreviewed` count, and unsafe task ids are rejected at `CandidateStore` construction by `ArtifactStore` before any candidate DB path is created.
- Cleaned-head gates on `3f6a63362a85...`: Release `34753389416` PASS; Navigation Action Fencing `34753389436` PASS including Real Chrome stale-mutation; Frontend Runtime `34753389399` PASS including full Real Chrome runtime regressions.

Release boundary remains unchanged: formal `VERSION.txt` is `42.24.0`; no merge to `main`, tag, or release. Genuine 10k/A800 acceptance remains deferred by user request.

<!-- STORAGE-SCAN-CANCEL-CLOSURE-2026-09-13 -->
## 2026-09-13 — external storage scan cancellation fencing CLOSED

- Real bug: if Stop was requested while the final remote image read/decode was in flight, old `StorageImportHandler._scan_impl` had no later loop iteration to observe cancellation. It could open the same remote object again for missing SHA256, flush the candidate manifest, publish `scan/result.json`, and finish as `AWAITING_CONFIRMATION`.
- Permanent RED: `tests/unit/storage/test_import_scan_cancel_fencing.py`; valid RED run `34753661080` proved old code returned `AWAITING_CONFIRMATION` instead of `CANCELLED`.
- Product: `2ca557ed0bd72851948ad778163bf47d590b5a54` (`fix(storage): fence scan cancellation after remote reads`). Remote hashing now checks cancellation per chunk; inspection re-checks after image decode before follow-up I/O and after hashing; cancellation propagates rather than becoming INVALID/FAILED; `_scan_impl` refuses to append the in-flight cancelled object and returns `CANCELLED` while preserving only already-completed pending work.
- Migration run `34753741408` PASS: old-product RED, precise migration, syntax, focused GREEN, real storage-import worker/candidate/YOLO regressions, and formal version boundary all passed.
- Permanentization: `da54910048fd88f6cadeef34d130eba94af34303`; one-shot RED/migration workflows and helper were physically deleted. Release Regression permanently covers the cancellation contract, real storage import worker, import candidates, and YOLO import.
- Cleaned-head gates: Release `34753845097` PASS; Navigation Action Fencing `34753845073` PASS including Real Chrome stale-mutation; Frontend Runtime `34753845116` PASS including full Real Chrome runtime regressions.
- Formal `VERSION.txt` remains `42.24.0`; no merge to `main`, tag, or release. Genuine 10k/A800 acceptance remains deferred by user request.

<!-- V42.25_STORAGE_INDEX_CANCEL_CLOSURE_20260913 -->
## 2026-09-13 Storage indexing cancellation fencing — CLOSED

- 真实缺口：素材导入确认后的 indexing 以批次处理；取消在 preflight 查询期间成为 durable truth 时，旧 Worker 仍可能继续 `materials.upsert_many(...)` / annotation / candidate outcome 写入，形成“任务最终 CANCELLED，但业务数据已继续提交”。
- 永久合同：`tests/integration/test_storage_index_cancel_fencing.py` 走真实 `scan -> AWAITING_CONFIRMATION -> confirm -> indexing`，在 material preflight 返回时注入 `CANCEL_REQUESTED`，要求最终 `CANCELLED`、material count 保持 0、candidate 保持未 indexed、不得发布 final result。
- RED/GREEN：`34755117132`；产品修复 `fe951e32aa2d7b840bfd9c975d500d0f0d200c9d`；永久化 `f9b11e691dd2e9daf0d6da2d3ef4f14c0b6d0909`。
- 修复边界：confirmation/ID assignment/preflight 后及 material、annotation、candidate outcome、mark-indexed 等不可逆写入前均重新读取 cancellation durable truth；不改变扫描、SHA 去重、YOLO label mapping 与确认语义。
- cleaned-head 正式门：Release Regression `34755481707` PASS；Navigation Action Fencing + Real Chrome `34755481732` PASS；Frontend Runtime + Real Chrome `34755481693` PASS（33 browser tests PASS）。accepted HEAD：`6cf54ac3b98a97a8be4c60a46d008e2a6bb499a1`。
- Release gate 同步关闭测试路径漂移：conversion / training resource contract 指回真实测试路径，并新增永久 path-integrity guard，workflow 中所有显式 `tests/*.py` 路径必须真实存在后才允许进入 pytest。
- 正式版本边界不变：`VERSION.txt = 42.24.0`；未 merge main、未 tag、未 release；A800 / genuine 10k acceptance 继续 defer。

<!-- STORAGE_IMPORT_PROGRESS_TRUTH_CLOSED_20260913 -->
## Storage import progress truth closure — 2026-09-13

Status: **CLOSED** on `refactor/frontend-runtime-stabilization`.

- Product fix: `855abb7fe6fc2c759a85acf6c578dc5f8b62b10d` (`fix(storage): make import progress monotonic across confirmation`).
- Permanentization head: `030afa30c3e076cb6fac2c9234711b2f7d0c0cc6`.
- RED→GREEN migration run: `34755980730` PASS. Legacy behavior was proven RED before migration.
- Durable progress contract: material-import `AWAITING_CONFIRMATION` is a partial-task milestone with a 50% floor, not terminal 100%; confirmation/resume uses `MAX(existing_progress, 50)` and therefore never regresses a higher durable value.
- Confirmed indexing emits real monotonic `progress_percent` from the durable 50% floor toward 99% according to `indexed_at_least / selected_count`; only terminal success reaches 100%.
- Permanent tests: `tests/unit/task_runtime/test_material_import_progress_phases.py` and `tests/integration/test_storage_import_progress_truth.py` are included in the formal Release Regression gate.
- Cleaned-head Release Regression `34756082473`: PASS (`runtime-contracts` + `training-data-contracts`, including release-path guard).
- Cleaned-head Navigation Action Fencing `34756082427`: PASS.
- Cleaned-head Frontend Runtime Stabilization `34756082419`: PASS; `Real Chrome runtime regressions` executed and passed.
- One-shot migration helper/workflow were removed before the cleaned-head gates.
- Formal version boundary remains `VERSION.txt = 42.24.0`; no merge, tag, release, A800 RC, or genuine 10k ZIP acceptance was performed.

<!-- TRAINING_REALTIME_PROGRESS_CLOSED_20260913 -->
## Normal training realtime progress closure — 2026-09-13

Status: **CLOSED** on `refactor/frontend-runtime-stabilization`.

- Permanent RED contract commit: `474771da05c9652a1aa7103b737918ebe1011ffa`.
- Successful RED→GREEN migration run: `34756786009` PASS; legacy epoch-only behavior was proven RED before migration.
- Product fix: `16a1f76ebdc704bfbbcd7f96ce7a2b234f4017e7` (`fix(training): publish realtime batch progress`).
- Permanentization / cleaned product head: `65736aefd0b5961c3f6a7b3e45907937a9988973`.
- Progress contract: preparation owns 0..20; active normal training advances 20..90 using epoch + real train-batch completion; batch publication is throttled to about 4 Hz with mandatory final-batch flush; durable task progress remains monotonic.
- `job.json` publication is same-directory atomic replace so higher-frequency batch updates cannot expose a partially-written JSON file to the task handler.
- Durable `current_item` now carries `Epoch X/Y · Batch A/B` when batch truth is available; completed-epoch metrics remain authoritative and are not fabricated by batch callbacks.
- The normal model and the OOM-recreated model both attach the realtime batch callback. AI continuation is intentionally excluded from this closure and tracked as a separate follow-up batch.
- Permanent formal contracts include `tests/unit/test_training_realtime_progress.py`, `tests/unit/test_training_progress_v2.py`, and `tests/api/test_training_unified_task_overlay.py`.
- Cleaned-head Release Regression `34756946382`: PASS (`runtime-contracts` + `training-data-contracts`, release-path guard included).
- Cleaned-head Navigation Action Fencing `34756946390`: PASS; Real Chrome stale-mutation contract executed and passed.
- Cleaned-head Frontend Runtime Stabilization `34756946384`: PASS; full `Real Chrome runtime regressions` executed and passed.
- One-shot migration helper/workflow were deleted in the permanentization commit before cleaned-head gates.
- Formal version boundary remains `VERSION.txt = 42.24.0`; no merge, tag, release, A800 RC, or genuine 10k ZIP acceptance was performed.

### 2026-09-13 — AI continuation realtime progress CLOSED

- RED contract commit: `084923474bdb0627756560c40f1b1a23a0543c14`.
- RED→GREEN workflow: `34757329068` — legacy RED proven, focused continuation GREEN, training runtime regressions PASS, formal version boundary PASS.
- Product commit: `57c698ad318110e9e825a7e80e7a1ad9be073369`.
- Permanentized clean HEAD: `c354d60e319b6fa195d70e175185c3b9cabec792`; one-shot migration helper/workflow removed.
- Release Regression `34758049699`: runtime-contracts PASS and training-data-contracts PASS; permanent `tests/unit/test_training_ai_continuation_progress.py` is in the release gate.
- Navigation Action Fencing `34758049728`: PASS including Real Chrome stale-mutation contract.
- Frontend Runtime Stabilization `34758049698`: frontend unit PASS and full Real Chrome runtime regressions PASS.
- Durable/UI truth: normal training remains 20..90; AI continuation advances 90..95 with cumulative Epoch/Batch truth instead of resetting to 1/N; continuation YOLO instances rebind epoch, batch, resource and device callbacks; 95..100 remains reserved for artifact verification/final evaluation.
- `VERSION.txt` remains exactly `42.24.0`; no main merge, tag, release, or A800 RC was performed.

### 2026-09-13 — Deployment queued resource-position truth CLOSED

- RED contract commit: `11b39b96ee28107e222bf9204ffd5f986e72e9fc`.
- RED→GREEN workflow: `34758458780` — legacy RED proven, focused deployment GREEN, syntax/diff checks PASS, formal version boundary PASS.
- Product commit: `46cc645ac6d47e0b02a3440c2a3000062b19ba05`; precise product diff is one `static/app.js` queue-meta condition replacement only.
- One-shot migration assets removed by `f1e6dad93adee5a8ead763294c5d4aa6b27d147f`.
- Permanentized clean HEAD: `caaeae70098fce7a90a5cd2fbfce481b6f84c332`; Release trigger boundary now includes `static/app.js` and the permanent conversion queue-truth frontend contract.
- Release Regression `34758615703`: runtime-contracts PASS and training-data-contracts PASS.
- Navigation Action Fencing `34758615733`: PASS including Real Chrome stale-mutation contract.
- Frontend Runtime Stabilization `34758615696`: frontend unit tests PASS, including `conversion-unified-task-truth.test.mjs`, and full Real Chrome runtime regressions PASS.
- Queue semantics remain server-owned and resource-scoped. Both `queued` and `waiting_resource` deployment conversion rows now display the live durable `resource_queue_position`; `resource_wait_reason` remains shown only for `waiting_resource`. Existing 1.8s full polling and backend ordering/claim semantics were not changed.
- `VERSION.txt` remains exactly `42.24.0`; migration helper/workflow are physically absent; no main merge, tag, release, or A800 RC was performed.

### 2026-09-14 — ZIP whole-task progress monotonicity CLOSED

- Permanent RED contract commit: `ee0e944ff654869c99c115d38b537e55acafd23f` (`tests/frontend/zip-import-overall-progress.test.mjs`).
- First migration run `34764744365`: legacy RED was proven; GREEN intentionally remained open because the first mapper had a floating-point edge (`95 -> 95.9`) and the source contract was too syntactically narrow for the existing equivalent upload expression.
- Successful RED→GREEN run: `34785810840` — legacy RED PASS, precise migration PASS, focused GREEN PASS, full frontend unit regression PASS, formal version boundary PASS.
- Product commit: `4140a8fa17eb949c26f3c2ec9e5b2b1d3e615f50`; product diff is limited to `static/app.js` (+2/-1): add the processing-to-whole-task mapper and consume it from active v19 ZIP polling.
- One-shot migration helper/workflow were physically removed before permanentization.
- Permanentized clean HEAD: `c6c28b9ed6bf2bfbe3a6cefbde9cdf2609dc2c46`; Release trigger boundary includes the permanent ZIP whole-task progress frontend contract.
- Release Regression `34786028127`: runtime-contracts PASS and training-data-contracts PASS.
- Navigation Action Fencing `34786028132`: PASS including Real Chrome stale-mutation contract.
- Frontend Runtime Stabilization `34786028178`: frontend unit tests PASS (including ZIP whole-task progress contract) and full Real Chrome runtime regressions PASS.
- Active v19 ZIP UI truth is now one monotonic whole-task scale: browser upload `0..35`, upload/validation baseline `38`, backend processing phase projected to `38..99`, terminal success only `100`. Raw backend phase progress is no longer allowed to overwrite the whole-task percentage and cause `38 -> 8` regressions.
- Backend v19 processing phase semantics were not changed; this closure fixes the frontend projection boundary only.
- `VERSION.txt` remains exactly `42.24.0`; no main merge, tag, release, A800 RC, or genuine 10k acceptance was performed.

## 2026-10-13 VNext review-fix audit

- Retired `setPage('模型检测')` calls are absent from the quality workspaces. Both scenario buttons route through the current Quality Center detect tab, and a Real Chrome regression asserts that the destination DOM exists.
- Training detail tab clicks no longer rebuild the dialog; selection, roving tabindex, focus, ArrowLeft/Right, Home/End, `aria-controls` and `aria-labelledby` stay inside the existing runtime.
- The existing evaluation image modal owns both A/B panes. Zoom/reset is synchronized, scroll position is ratio-synchronized, and each pane has independent fullscreen; no nested modal or duplicate image state exists.
- Frontend evidence: Node 24.14 952/952 and focused Real Chrome 7/7. Full Chrome first run was 140/149; after the VNext contract fixes and isolated reruns, 3 original failures pass and 6 legacy-fixture/environment cases remain red. The screenshots are fixture-labelled; production imagery is not implied.

## 2026-10-13 VNext final differential audit

- The clean detached `30f83c48` browser baseline completes 142/148 with six failures. VNext has the same six deterministic failures at the same assertions; login passes 2/2 under its dedicated auth config, while model/conversion and action-fencing failures are stale fixture contracts with preserved traces.
- A seventh VNext full-suite failure counted two label-schema GETs because the fixture navigated away after request start but before successful cache commit. It now waits for the existing cache timestamp and passes repeat 5/5 plus the 22-test material slice. The baseline-reproducible service-node isolated startup race now sets the existing advanced preference before navigation and passes repeat 3/3. No timeout, retry, cache wrapper, production owner, or weakened business assertion was added.
- Node 24.19 direct frontend selection is 952/952 and the VNext quality/recovery Chrome slice is 7/7. The equal-request 1000/720 benchmark is `40×full=11.3042 MiB` versus `1×full+39×compact=0.2985 MiB`, including initial history.
- Final VNext Node 24 full Chrome is 143/149, leaving only the same six baseline failures. `docs/VNEXT_FINAL_DIFFERENTIAL_AUDIT_2026_10_13.md` owns the per-test evidence. Production imagery, OSS, GPU and GitHub Ubuntu remain `NOT VERIFIED`.

> **2026-10-30 / 42.24.430**：429 `a3cee98c` Chrome refresh-error 回归发现原窗隐藏仍需关联列表失败通知；430 只更正 `refreshCreatedLists` 同原 DOM/任务 ID 归属，不恢复旧提示污染新窗，Node 59/59。准确 SHA CI 待验，生产未部署。详见 [P0 台账](performance/2026-10-29-p0-followup.md)。

> **2026-10-31 / 42.24.451 AI 审核前端 Owner 边界**：只更新原 `static/app.js` 任务列表展示、唯一 `annotation-task-view.js` 统计投影、`styles.css` 短屏密度和同一 Playwright 用例；不新增 review renderer、分页或轮询 owner。当前候选结果与真实 GT owner 完全保留，Node 1427/1427，本批真实 Chrome/精确 SHA CI 待核。详见 [AI 专项](superpowers/plans/2026-10-16-ai-annotation-cleaning-scope.md)，不将历史 GT 日志冒充当前态。

