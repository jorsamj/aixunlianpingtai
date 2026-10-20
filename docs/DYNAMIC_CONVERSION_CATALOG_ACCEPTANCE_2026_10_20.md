## 2026-10-20｜厂商与芯片完整CRUD及质量治理（A-D限定验收通过 / E待最终SHA CI）

基线ed946c9b43ba7c5e014c60076d5539b6cbdf20b8 / VERSION42.24.362；已fetch/prune及pull --ff-only，干净且唯一同仓库活动会话。前轮40/40 Actions、112/112 Checks、Node1037/Chrome112绿色回执已核验归档，仅为历史。本轮升级上次简化需求，不再把短弹窗视为完整管理。

完整产品合同：部署资源页内正式“厂商与芯片管理”区域，不加一级菜单；旧字典按钮只定位同一区域，移除旧独立编辑保存实现。厂商/芯片真实列表、名称搜索、SDK/启停筛选、分页/排序、数量、查看/新增/编辑/删除/启停；独立短表单，自动稳定ID/可信配置建议，高级折叠，已有身份保护。物理删除须确认且后端核对关联芯片、全部历史转换任务、ModelArtifact、发布记录及外部映射/业务引用；有引用明确拒绝并可停用，不能隐去/级联删除或伪造归档成功。保留历史ID、任务快照、模型/Weight/SHA、外部分类及全部记录。

SDK合同：列表按每个资源分别展示名称/位置/实际版本/芯片/精度/最后检测时间/错误及建议；显式检测复用原resources/{id}/detect和原probe，零新探测器/轮询。由原SDK版本矩阵及真实探测自动决议有效constraint；手工选错constraint不得阻止已有充分证据的合法转换，但未知SDK/芯片/精度严格拒绝。配置约束和有效决议分开，执行参数与日志/Manifest取有效结果，绝不改历史快照或默认假可用。

架构与最小实施方案（writing-plans，沿用用户指定文档位置）：
- 唯一ModelArtifactRepository/conversion_catalog继续存储；保留GET/PUT整体合同和防误删保护。增加原catalog命名空间records查询/详情、operations单条变更及操作读回、chip检测合同；明确code/revision/operation_id、确认、原子性与幂等。
- Repo在原artifacts.sqlite3添加必要操作回执/审计ledger（不是第二字典表/数据库），成功保存前后行及动作；相同operation_id相同请求可安全重放，异请求冲突；单条变更由最新完整catalog生成，不能丢隐藏项。未引用才允许受控DELETE，整体PUT仍不能删。
- 删除只读扫描原任务payload/两种job目录、算法版本快照、model_artifacts、原发布表及config；支持local ID精确匹配和旧target+SDK身份匹配。损坏/无法核验来源fail closed并列明原因，不能吞错。删除与原转换准入复用同一catalog生命周期锁，避免先预检后删除的并发竞态；不创建执行器/队列。
- 前端将原app.js字典Owner迁至一个专用模块（移除原实现），在renderDeployResources直接挂载正式管理区，主导航直接清理生命周期。单一事件委托/AbortController和请求代次保护；只刷新本区域/当前表格，不调用页面render造成循环；短表单/查看/删除确认只开一层modal。搜索/筛选只查后端，不从DOM拼全量提交。
- 只用原模板/可信建议/真实probe作SDK判定；SDK有效约束由共享resolve_chip_capability决议，未知保守、多个资源独立，不增加另一套适配规则。

实施与限定测试清单：
- [x] B RED：原Repo/API无安全单条CRUD、未引用不能物理删除、SDK手错约束阻止充分证据转换；补必要Python复现。Node覆盖一次提交/幂等重试/迟到响应/退出清理；Chrome正式管理区域、CRUD/详情/搜索筛选分页/确认删除与引用拒绝/失败重试/刷新/前后端一致。
- [x] C：原Repo/SDK模块/原API最小增量，安全引用核验和事务审计；前端退役旧弹窗实现并直接维护页面Owner，不加wrapper、重复注册、重复请求或平行状态机。
- [x] D：只跑变更模块与直接依赖的最小Python/API/Node/Chrome；通过且未受新修改影响不重跑。旧合同确与新业务冲突时迁移到新事实源并保留或加强业务断言，禁止删/skip/降标准。
- [x] 质量审查：实际检查唯一Owner、无覆盖链/循环调用/渲染循环、单次事件绑定/写请求、异步取消及结果归属、无无用模块/硬编码业务结果、历史/事务/幂等保护及UI桌面/窄屏；整改后提交。
- [ ] E：提交前再fetch按最终版本一次递增、必要缓存与七版本入口一致；普通push长期分支，核验最终实际SHA既有CI，不加大型工作流/触发范围或重跑无关CI。最终外部回执catalog-crud-ci-final-20261020.json，下一受验证提交归档。
- [x] F：同步本专项、CODEX_CURRENT_STATE/Owner/技术债摘要、真实测试/接口/文件/剩余风险/生产未验证，不只在聊天记录。

永久工程约束补充：原始入口/Owner/调用链先读清再改；禁止wrapper叠加、多套实现/覆盖、循环渲染、重复事件/请求/提示/任务、重复observer/轮询或嵌套弹窗；单事实源和既有执行Owner，清除本范围旧实现。字段/默认/校验/状态/日志/产物/Worker必须同后端事实，异常明确可恢复，禁止静默吞错/无限重试/假成功。UI复用企业风格变量/组件，表格/短表单/对齐/可滚动响应式，加载/空/错/成功/禁用齐全。相关旧技术债可安全消除则消除，否则记影响和后续，不无界重构。所有修改必须历史安全、定向测试/实际审查/最终CI；不得新增技术债或用mock冒充生产SDK验收。

本轮仍不授权生产数据库/配置/密钥/OSS/Weight变更、生产删除迁移/真实转换/部署重启。仅隔离数据验收；真实现场仍NOT VERIFIED。

本轮实际实施与诊断（2026-10-20）：
- 原有能力：正式部署资源Owner、整体GET/PUT及revision、SDK工具探测、共享resolve、ModelArtifact/历史任务/发布Repository均存在。真实缺口是没有安全的单条CRUD/物理删除/审计回执/服务端分页，旧前端仍全量PUT；配置的constraint也会误拒绝实际可用SDK。
- 原ModelArtifactRepository增加mutate_conversion_catalog/records查询/引用核验/操作回执，沿用conversion_catalog同表；同一SQLite增加operations审计账本，将字典变更+before/after+回执原子提交。服务端UUID，完整字典候选不因筛选损失。已引用身份拒绝改挂或物理删除，未引用允许；停用保留所有历史。整体PUT继续不可误删/改身份。
- 引用扫描为只读叶子函数conversion_catalog_references.py；所有状态及全部SQL游标，覆盖两个job目录、durable payload/job_dir、算法版本、ModelArtifact、发布记录及外部映射。损坏证据明确409。显式本地ID仅在单条合同作用域优先；旧SDK回退不跨兄弟版本失效，也不把他厂商明确归属误绑定。版本→catalog→durable原准入锁顺序保留，外部配置保存仅加同一catalog fence以避免引用写入竞争，不改变映射合同/Weight行为。
- 原renderDeployResources直接mount新conversion-catalog-runtime，main原导航退出直接leave；已删除app旧整表编辑实现及无用catalog428 CSS。一个嵌入区、短表单/详情/确认单层弹窗、专用事件属性及单次委托，无第二UI/Owner/轮询/Observer/全局覆盖链。列表局部更新，请求ticket+epoch+项目归属+AbortSignal，表单归属阻止迟到请求关闭新草稿。
- SDK列表与resolve同源，实际probe版本与可信矩阵自动选择有效constraint，不写回历史配置；每资源独立版本/位置/芯片/精度/时间/真实错误与建议。显式检测只调用原资源detect一次，无新探测器；未知芯片仍不可转换。未引用的待配置芯片高级SDK可编辑，有引用保持锁定。

接口（原catalog命名空间，错误统一PlatformError）：
| 方法/路径 | 合同 |
|---|---|
| GET /api/v39/deploy/catalog/records | entity/query/vendor_id/template_id/enabled/page/page_size/sort，真实items/total/revision/templates及每芯片能力 |
| GET /api/v39/deploy/catalog/records/{entity}/{id} | 当前item/revision、完整引用数量与最多50条证据样本、能力明细 |
| POST /api/v39/deploy/catalog/operations | create/update/delete/enable/disable；operation_id/expected_revision；delete必须confirm_delete=true |
| GET /api/v39/deploy/catalog/operations/{operation_id} | 可追溯回执及before/after；同ID同请求重放，不同请求409 |
| POST /api/v39/deploy/catalog/chips/{id}/detect | 可选resource_ids，同SDK资源去重检测，返回各资源真实事实 |

限定测试证据（分批、不重复累计，不代表生产验收）：
- Python RED catcrud-python-red.log：14失败；API/fence RED3失败；实际probe版本RED1失败；损坏算法证据RED3失败；兄弟版本引用作用域RED1失败。均已最小修复/对应GREEN，未删skip或弱化断言。
- 后端仅原字典unit/API与新增CRUD单元：首个直接合同集48通过2失败，旧业务升级的2处测试迁移后各通过；随后新边界4通过，检测/引用修正6通过；最终受影响引用范围13通过、检测真实错误1通过。后端代码未再变化的通过项不重跑。>500资产和>100 durable任务后段引用、job_dir缺失、坏JSON、跨厂商同SDK、历史SDK与兄弟版本、并发revision、重复回执、物理删除/引用拒绝已覆盖。
- Node新Owner接线1项、生命周期/HTTP无randomUUID/唯一操作ID/离开和重挂4项通过；必要版本缓存断言1项通过（8项未选中）。旧浏览器自造recordID/建议/全表草稿断言迁移到后端事实源测试，未知别名前缀、模板隔离、稳定身份和隐藏数据无损断言保留/加强。
- 真实Chrome只选本文件4个相关流程：正式菜单/BM1684 FP32矩形640×384提交、完整CRUD/引用拒绝/刷新返回/并发revision、迟到保存保留新表单/专用动作、服务端搜索筛选分页/503业务码未知结果同ID重放。全部通过；首次菜单测试因异步列表尚三行时strict locator失败，增加先等待一行而不削弱内容断言后通过。修改样式后仅复验受影响CRUD；最后1通过。
- 本轮只做上述必要Python/Node/Chrome、语法和diff检查；未执行全仓库测试，未新增或扩大CI工作流。日志在本机.codex/tmp/catcrud-*，桌面/窄屏截图归档既有visualizations目录catalog-crud-desktop.png / catalog-crud-narrow.png；实际截图已人工检查，稳定ID移至详情与高级配置，表格内部滚动避免窄屏压缩。
- 实际差异审查发现并整改：JSON损坏误放行、localID跨版本作用域漏引用、通用动作重复分发、迟到POST关闭新表单、检测读回后生命周期、未引用SDK不可编辑、5xx业务码误清幂等ID。没有新增重复Owner/wrapper/注册/请求或外部写入路径。未证明现场SDK/生产数据行为，不能用隔离fixture冒充。

正式版本及待交付：再次fetch远端仍ed946c9b43ba7c5e014c60076d5539b6cbdf20b8/VERSION362；本轮一次递增42.24.363。后端七个正式版本入口一致、前端显示仍读后端；必要缓存app411/main410/styles409，新增catalog模块v1。未修改生产环境/字典/密钥、OSS、Weight、训练转换或服务。待安全提交/普通推送及最终实际SHA CI。CI回执写上述外部catalog-crud-ci-final-20261020.json（不能借用历史绿色）；下一会话先核对该回执、最新远端SHA/VERSION及工作树。部署后仍需授权现场真实资源多SDK及生产引用规模/性能、实际用户权限与字典交互复验；本轮不授权部署。

## 2026-10-20｜字典管理UI/UX简化（A-D限定验收通过 / E待最终SHA CI）

基线6f34efd3ef09741147f90dadadb37591751c3c41 / VERSION42.24.361，fetch/prune及pull --ff-only一致且工作树干净；唯一同仓库活动会话为本会话。其他worktree/WIP不变。上一轮21/21 Actions、55/55最新Checks、Chrome112/112已按独立回执核验并归档为历史，不借用本轮CI。

用户确认的产品需求：原正式入口及renderDeployResources保留；字典默认简洁厂商/芯片列表，搜索/选择厂商查看芯片，展示模板、数量、启停与真实SDK记录状态/精度，编译与板卡验证独立。新增厂商仅名称/现有模板，新增芯片仅厂商/型号；随机合法稳定ID自动生成，已知五型号按已确认模板合同建议SDK/约束，未知芯片可保存待配置且不得准入转换。高级字段默认折叠，历史身份只读且不重编；支持编辑与启停，无删除。读取完整原数据并全量revision保存，搜索/折叠不丢历史；冲突明确要求刷新，不静默覆盖。五SDK模板是模板不是预置厂商；无Adapter显示暂未适配。字典/外部映射、ModelArtifact、历史转换和Weight Owner严格独立，不修改生产。

设计决策：
- 同一原modal内切换列表/单记录短表单，不叠弹窗、不加框架/页面/管理API。草稿包含完整vendors/chips，筛选只影响显示；保存单记录后仍回同一列表，立即用原PUT持久化完整草稿+revision。
- ID由浏览器crypto.randomUUID生成，编辑不再生成。模板的可信芯片建议由现有compute_platform_catalog统一提供；未知sdk_code/constraint_id留空，code独立生成，不推测编译目标。历史vendor/template及chip/vendor/code/sdk锁定；如确需变更走停用+新身份。
- 现有resolve的芯片/SDK兼容部分提取为单一共享判断，GET /api/v39/deploy/catalog附带建议和检测记录投影；转换预检/准入仍用同一函数及原现场检测。状态不冒充模型/板卡验证，不新增扫描或轮询。
- 新增/编辑技术字段经原后端格式/关系/唯一性校验，未知字段不绕过SDK探测；不写外部发布配置。现有revision、不可删、不可改挂及转换Job校验保留。

实施计划（writing-plans，按本专项指定位置持久化）：
- [x] B：在现有unit/API增加未知芯片待配置、可信建议/真实能力一致、ID/模板不可改挂、revision/隐藏记录无损测试；Node/Chrome补短表单/搜索/保存恢复及并发冲突RED，记录真实失败。
- [x] C：compute_platform_catalog/ModelArtifact原校验最小增量，app.py原GET投影；app.js原字典Owner替换长表单为列表与短表单，styles沿用现有风格并限制滚动/响应式；不改转换执行/发布机制。
- [x] D：仅运行字典unit/API、相关Node和必要Chrome；验证既有ID、未知/停用阻断、已有BM1684矩形精度断言、无Adapter及无资源。修复实际失败，不降断言。
- [ ] E：再次fetch核对并整合其他会话，按最终最新VERSION一次递增；七版本入口、必要缓存、语法/diff/只读审查，普通push唯一长期分支。最终SHA实际Actions/Checks及关键Jobs回执另存catalog-ui-simplification-ci-final-20261020.json，下一受验证提交归档，避免未CI自引用提交。
- [x] F：更新本专项、CODEX_CURRENT_STATE及Owner/技术债摘要，列出实际文件/测试/生产未验证与接续步骤。

本轮真实证据与进度：
- B RED：Python新增4失败（未知芯片无法保存、metadata建议/检测投影缺失、历史厂商模板可改挂、API投影缺失）；Node新合同3失败。HTTP无randomUUID又3通过1失败；“定制BM1684X”不得误匹配已知型号又3通过1失败。修复前Chrome以正确命令恢复基线原app，列表仍展开3个SDK输入而期望0，真实失败；恢复自身工作代码后继续。
- C：原resolve芯片/SDK分支提为resolve_chip_capability单一事实，未放宽BM1684/FP32、FP16/芯片约束；GET/PUT附带原检测记录投影与5条配置建议（非业务厂商、非SDK白名单）。未知sdk/constraint可空，local code独立生成，未配置永不准入。原Repo保留revision、不可删除、芯片身份防改挂，并保护已有厂商模板身份。原字典Owner单modal列表/短表单、搜索、启停、完整数据PUT；高级默认折叠，已有技术身份只读；无需手填ID。
- D发现并关闭：revision后“重新读取”曾叠第二modal，改同root原位刷新，浏览器明确单dialog/零layer；pending_configuration原预检chip_options缺状态名导致500，补为待配置，Job现400且零staging。初次浏览器关闭按钮因基础弹窗×同名，定位限定footer；首次baseline命令未选中测试不算RED，正确PowerShell命令日志才是RED。未删测试、放宽SDK或其他保护。
- 最终本地：Python现有字典unit/API两文件33 passed；Node字典/导航/Owner/版本4文件32 passed；Chrome仅原formal字典用例和新增管理用例2 passed，0失败0跳过。真实隔离GET/PUT验证名称+模板新增、已知RK3568建议、BM1684/BM1684X显示及BM1684 F32矩形原断言；未知无SDK/无Adapter记录、搜索隐藏行无损、启停、只读身份、名称变更ID不变、revision冲突保留服务器值及刷新恢复。无SDK/无资源/无Adapter Job均在暂存前拒绝。外部config隔离哨兵未改变。七版本入口均362；语法/diff检查通过。
- 正式VERSION42.24.361→42.24.362一次递增，app410/styles408缓存必要更新，main409不变；前端显示仍从后端bootstrap取得正式版本。只读审查完成，原Repo事务/身份/共享SDK判定/单modal及异步保护未发现实质问题；桌面/窄屏截图已检查，提交前再fetch并核验最终SHA CI。详细修改：platform_core/compute_platform_catalog.py、model_artifacts.py、app.py、static/app.js/styles.css/index.html、VERSION、对应unit/API/Node/Chrome及现有文档。
- 本地日志根C:/Users/jorsam/.codex/tmp：catui-python-red.log、catui-node-red.log、catui-node-http-red.log、catui-suggestion-red.log、catui-browser-red-corrected.log、catui-python-green3.log、catui-node-final.log、catui-browser-final.log、catui-version-final.log。截图最终回执附件目录catalog-ui-simplification/，只代表隔离环境。
- 最终截图补验：首提交27202972的CI已47/48成功时，发现新表单沿用上次“已保存”提示；新增浏览器断言真实RED（应为空、实际已保存），进入短表单即清空反馈后定向GREEN。VERSION仍362、不重复递增，仅app缓存410；最终SHA必须重新CI，不借用首提交绿色。
- 接续：先核对最终SHA回执（catalog-ui-simplification-ci-final-20261020.json）及远端VERSION，再处理真实现场数据；部署/生产写入需独立授权。字典检测状态仅现有资源记录，正式转换仍走原实时检测和Durable MODEL_CONVERSION，硬件验证未执行。

未验证边界：不访问或修改生产数据库、字典、SDK环境、OSS、外部Weight；不部署/重启/真实转换。生产既有数据和真实SDK可用性待独立现场验收。

## 2026-10-20｜正式部署资源入口补修（A-D完成 / E待推送最终SHA CI）

本轮用户完整要求：从正式菜单进入部署资源，复用renderDeployResources和原Owner体系，正常展示厂商与芯片字典/检测本机工具/新增部署资源；模型配置保持独立。进入/返回/刷新状态一致；字典GET/PUT仍使用/api/v39/deploy/catalog，新增与已有BM1684/BM1684X/RK3568保存后重载、转换选择可见；不改/清空生产字典，不建页面/模块/Owner封装，不扩跑无关测试，更新文档与正式版本，安全推送唯一长期分支并验收最终SHA，不部署生产。

- A：完整fetch/prune及pull --ff-only，基线8366b4edf79e8a4231fe5033a8c86ec92858bd80，VERSION42.24.360，初始工作树干净；可见同仓库只有本会话active/一历史notLoaded，无其他在线待合并需求。其他工作树不修改。上轮转换Weight最终23/23 Actions、59/59 Checks及10关键Jobs已按独立附件读回核验，属于上轮，不借用为本轮。
- 原页面、字典弹窗、GET/PUT、持久化与转换读取已存在，不重复开发。根因明确四处：normalizeNavigationPage将部署资源误重定向；最终renderNav没有该菜单；启动RESTORABLE_PAGES及恢复逻辑排除/改写该页面；main canonical map没注册现有renderer。
- B：Node修改旧错误别名期望并新增单菜单/独立Owner/恢复合同，17通过2失败；Chrome原动态字典用例改为菜单点击，真实在“部署资源”按钮缺失处超时失败（deploy-nav-red.log、deploy-nav-chrome-red-corrected.log）。未删除/跳过/减弱断言。
- C：仅补原正式菜单（展开高级功能后的现有配置项组）、原canonicalWindowPageRenderers中的renderDeployResources、启动白名单与恢复条件、导航别名；模型配置仍指向renderModelConfigPageV35，部署插件旧别名不变。无第二页面/轮询/包装。
- D：浏览器使用隔离本地字典API，保留原BM1684矩形F32提交断言并补普通菜单打开、BM1684/BM1684X显示、UI新增厂商/芯片RK3568、真实GET/PUT保存、刷新恢复、模型配置返回、保存后转换字典选项。SDK/资源接口夹具只验证UI合同，不冒充SDK或生产验证。最终Node导航/恢复/版本4文件29通过；Chrome限定3项通过（原模型配置、正式字典导航及原页面Owner用例；部署资源从旧别名升为正式页面并保留具体renderer断言），字典/API限定8通过18未选中；0失败0跳过。BM1684X/BM1684/RK3568显示，新增RK3568可选，原BM1684 F32矩形提交断言保留。首次浏览器夹具重复厂商ID被后端拒绝，修正夹具后通过，未改后端校验。日志deploy-nav-node-final.log、deploy-nav-chrome-final.log、deploy-nav-python-final.log均在本机.codex/tmp。
- CI补验：CI首提交2df5d413的frontend Job实际1031通过/2失败：render-owner-retirement仍将部署资源列为退役且固定旧菜单；按本轮明确产品合同改为唯一正式Owner/包含部署资源菜单，其余退役页面保护保留。两条定向用例GREEN（39条未选中，未修改skip）；日志deploy-nav-ci-contract-fix.log。正式版本仍361，不重复递增。
- E：提交前fetch确认远端仍为上述基线；VERSION以最新42.24.360一次递增42.24.361，后端/health/app-info/OpenAPI/远程服务共七入口均为361；前端从bootstrap读正式版本，必要app408/main409/nav422518缓存更新，styles407不变。语法与git diff --check通过；限定只读代码审查确认canonical Owner/启动桥接/缓存一致，无可操作问题。完整最终SHA/CI保存独立附件deployment-catalog-navigation-ci-final-20261020.json（此前各轮附件同visualizations目录），下一受验证提交归档，避免自引用另造未验收HEAD。
- F：未连接或修改生产数据库/厂商芯片字典/OSS/新畅联Weight，未部署/重启/重转换。现场已有三芯片实际记录显示仍需用户部署后只读核验，不能用隔离测试宣称已读取生产字典。

# 动态厂商字典、SDK目标与转换参数整合｜2026-10-20

## A 需求与现状（本地实现与验收完成）
唯一分支 feature/external-algorithm-publishing。fetch/prune、pull --ff-only 后基线 7a2492b24de5d6259bf792ed074f1548e66d6eda，工作树干净；其他工作树保留，未发现同范围活动会话。上一轮39/39 Actions、109/109 Checks成功已核验，不能作为本轮CI。
用户完整V2及第十八条为已确认合同：动态本地厂商/芯片，与SDK编码和外部分类分离；现有Adapter/Worker/Durable MODEL_CONVERSION/ModelArtifact复用；后端统一默认/校验，BM1684合法F32、原BM1684X/BM1688 FP16；真实结构/SHA/IO证据和硬件验证分离。未知或未经证明的组合保持不可提交。厂商无Adapter显示暂未适配。不操作生产/密钥/OSS/历史Weight，不部署、不安装SDK。
现有链路：PT导出、RKNN/ATC、TPU-MLIR、远程鉴权、durable调度和产物检查已有。复核缺口：本地业务字典尚未实现；绑定候选、产品芯片、Sophon FP16参数/文件名及前端均固定；探测截断目标，缺芯片级精度合同。

## 架构决策
1. 扩展现有compute_platform_catalog模块和ModelArtifactRepository，在原artifacts.sqlite3增加本地转换字典配置表（非第二模型资产表/数据库）。预置五类SDK模板，不自动创建五个厂商。显式CRUD维护稳定厂商/芯片ID、SDK编码、启用及证据约束引用；revision并发校验。历史任务保存独立参数快照，不受字典后改影响。
2. 模板是Adapter字段合同，不存任意命令；SDK探测保留全部声明目标，再按版本相关官方证据计算芯片精度能力，绝不作芯片×全局精度笛卡尔积。BM1684在现场探测确认且版本证据匹配时开放F32；INT8仍不开放。原两chip FP16保留。
3. 在原版本转换弹窗及部署资源配置入口维护字典；源模型/字典/资源通过后端resolve接口生成统一参数、来源和错误；POST任务再次用当前数据库与实时检测重验。SDK目标经Adapter显式映射，Worker再次自检；远程节点同合同。
4. 原ModelArtifact保存本地ID、SDK目标、模板版本、资源/SDK、有效参数与验证证据；原外部对应表读取同一本地芯片字典。可选发布元数据及tags机制保持。
5. 正式VERSION本轮一次42.24.358→42.24.359；后台/health/bootstrap读取同VERSION.txt，UI显示读取后端，不嵌入另一个正式版本；必要app/main静态缓存递增。

## B-D 实施与限定验收计划
- [x] 字典持久化/并发/启停/非法SDK参数、空字典与两厂商可见性 RED→GREEN。
- [x] 官方版本证据与live probe的BM1684/F32、非法FP16、原两chip FP16、未知目标/精度及工具失败 RED→GREEN。
- [x] 后端resolve/任务提交/远程Worker一致；矩形、训练800、训练Batch75不继承、未知模型合同诊断；真实命令和目标校验。
- [x] 同一弹窗动态厂商/芯片/状态与参数来源，字典维护及外部绑定读取；Node和原转换Chrome限定回归。
- [x] ModelArtifact参数快照、不同chip共存、tags/身份安全定向回归。
- [x] 正式版本、必要缓存、语法/diff与当前改动对应工作流；不跑无关全仓库测试、不删跳/弱化断言。
- [ ] 安全普通FF提交推送，最终完整SHA全量实际Actions/Checks及关键Jobs验收。

## 官方证据与实机边界
TPU-MLIR v1.30.2 regression/chip.py精度/格式矩阵：https://github.com/sophgo/tpu-mlir/blob/v1.30.2/regression/chip.py
同版本model_deploy参数：https://github.com/sophgo/tpu-mlir/blob/v1.30.2/python/tools/model_deploy.py
BM1684 F32/INT8与FP16禁止有官方矩阵证据，但本次尚无现场bm1684 SDK编译或板卡推理证据。用户给出的BM1684X/BM1688现场FP16成功属于历史用户证据。本轮隔离测试不得冒充实际SDK/硬件验收。

## E-F 当前进度
本地实现与限定验收完成；普通FF提交推送与最终SHA CI为下一步。实际SDK编译、模型质量比较、真实硬件均NOT VERIFIED。最终CI保存独立附件，由下一受验证提交归档，避免为写入自身SHA再制造未经CI的新HEAD。


## 阶段C/D进度更新（本地验收进行中）
- 原ModelArtifactRepository的conversion_catalog表保存单一字典JSON/revision，五个SDK模板只为模板；业务厂商/芯片初始为空。启停可维护，旧ID不可删/改挂SDK，CAS保护并发。原外部对应表读取同一字典，不自动建外部分类。
- 原resolve接口统一厂商/芯片/Adapter/节点/版本能力/精度/输入与预处理；原POST再次实检，自动转换也复用同一合同。BM1684 F32、原X/88 F16、字典可添加同SDK有官方矩阵证据的新chip；未知组合待确认。RKNN本机候选实际SDK config检测，旧Agent的已声明芯片范围仍是安全前提，不凭字典伪造远程能力。
- 原Worker按SDK --chip/--processor及F32/F16映射，文件名反映真参数，编译后model_tool --info检查唯一芯片；声明/编译/模型IO与质量/板卡证据分开。ModelArtifact保存本地ID、SDK编码、模板版本、资源、有效参数和真实Manifest绑定的IO（明确ONNX与compiled_model未知）；原SHA/上传/tags Owner不变。
- 输入继承384×640/800、原训练Job运行事实、ONNX真实Shape优先；训练Batch/AMP不作转换参数。冻结预处理继承，非法Pad/NMS/融合等明确拒绝。SDK精度与训练精度独立，缺可选发布信息仍不阻断。
- 原弹窗动态厂商与完整芯片状态、多芯片明确选择，读取后端推荐、参数来源/模板字段；迟到Shape覆盖及切到ONNX的旧vendor响应各补Node RED，修复ticket/脏输入保护。原CSS覆盖hidden导致Sophon显示ONNX/TensorRT字段，Chrome RED后加转换弹窗限定hidden规则。
- 首轮受控Python12文件258通过/1失败（旧远程幂等夹具缺chip_precisions）；补真实合同形状保持幂等/409/仅一次launch断言后该模块通过。输入合同与审查2项另补RED→GREEN，合并最终集合待复验，不将旧结果冒充最终。
- 首轮限定Chrome7项5通过2失败（旧多chip默认断言、真实异步高度覆盖），修复后受影响2通过；加入BM1684双厂商/真实本地字典API用例后全规格8通过。截图复核确认hidden问题单独RED，最后样式后完整复验待执行。Node8文件70通过，新增输入一致性后仍须最后验收。
- 限定只读审查确认训练Job尺寸回退与远程Atlas SoC字段两项P1，已各补RED→GREEN；未发现额外可确认P0/P1。未运行额外审查测试、未连接生产。
- 正式VERSION本轮已一次递增42.24.359；app/main/styles必要缓存统一42.25.407，发布模块64010。正式UI版本仍读后端/VERSION.txt；内部UI build标识是独立开发标识，不另写显示版本。未部署。
- 下一步：最终限定Python/Node/原Chrome规格、版本与原永久守卫，更新A-F结果后普通推送；完整最终SHA CI独立附件，不连续改版本。

## D 最终限定验收与证据（提交前）

| 范围 | 本轮状态 / 边界 |
| --- | --- |
| 五SDK模板 | rockchip/rknn、ascend/atlas-atc、sophon/tpu-mlir复用原Adapter；huawei/cambricon暂无Adapter明确暂未适配；模板不自动创建厂商 |
| 本地字典 | 原artifacts.sqlite3单表、CAS、稳定ID、启停；空字典不伪造可用项；需管理员显式配置 |
| Sophon目标 | 1.30.2官方矩阵∩真实探测；BM1684 F32，X/88保留F16；其他浮点组合仅证据与实检均满足时可选，SDK版本变动不沿用1.30.2证据 |
| 输入与执行 | ONNX真实Shape优先、可信训练Job/冻结配置继承、矩形640×384、Batch1；训练精度不决定部署精度；未知/不支持语义明确错误 |
| 产物与IO | 真目标命令/文件名、实际SHA/大小/唯一芯片；可信Manifest绑定ONNX IO，compiled_model IO与数值比较未提供则明确不完整，不冒充板卡验证 |
| RKNN/Atlas/远程 | RKNN字典候选实际config探测；Atlas local/remote SoC同一合同；原Agent/资源声明能力继续为前提，不凭字典扩展远程能力 |
| 外部发布 | 同一本地字典供对应表使用，原tags/edit/UNKNOWN/核心身份与上传Owner保持，可选元数据非阻断 |

- 最终主Python：12个直接相关unit/API文件 **262 passed / 0 failed / 0 skipped**（23.96s），日志 `C:/Users/jorsam/.codex/tmp/dynamic-release-python.log`。文件：test_dynamic_conversion_catalog（unit/API）、test_sophon_conversion、test_rknn_runtime、test_conversion、test_model_artifacts、test_remote_conversion_transport、test_sophon_remote_durable、test_node_agent_conversion_runtime、test_conversion_tasks、test_sophon_remote_admission、test_conversion_portable_contract。
- 发布安全定向6项+新增本地字典绑定1项分别通过：dynamic-publish-safety.log（6通过，新用例夹具缺配置已纠正）与dynamic-binding-final.log（1通过）。旧ID edit一次、UNKNOWN、冻结标签、矩形、双chip同Version与旧映射不变均有直接断言；不冒称一次命令7全绿。
- Node原有8个相关文件 **70 passed / 0 failed / 0 skipped**，dynamic-final3-node.log。Chrome原model-and-conversion规格 **8 passed / 0 failed / 0 skipped**，dynamic-final2-chrome.log；最后厂商/通用格式分组调整后BM1684用例再1通过，dynamic-final3-bm-ui.log（同一用例不重复计数）。浏览器使用隔离API夹具，不是真SDK编译证据。
- RED→GREEN日志：dynamic-command-red（F32误成F16）、dynamic-api-red（缺resolve/禁用绕过）、dynamic-auto-red（忽略BM1684）、dynamic-review-red（训练Job尺寸/Worker旧名单）、dynamic-atlas-red（远程SoC）、dynamic-port-rect-red（矩形丢失）、dynamic-io-red（缺Manifest IO绑定）、dynamic-input-red（冻结预处理/ONNX Shape）、dynamic-sdk-version-red（版本证据错用）、dynamic-shape-red/dynamic-switch-red（迟到响应覆盖）、dynamic-hidden-red（hidden被CSS覆盖）。未删除/跳过/削弱断言。
- 首次Python与Chrome并行造成Playwright清理test-results期间pytest收集目录错误，改为顺序执行；最终上述262通过为新鲜结果，不引用失败运行冒充绿色。既有5项依赖弃用警告不影响断言。
- 语法检查、git diff --check与原永久守卫通过（dynamic-guards.log）。正式VERSION、backend、health、system、OpenAPI、remote、remote OpenAPI实测均 **42.24.359**（临时数据目录，未改生产环境）；内部UI build标识独立，正式页面仍读后端。app/main/styles缓存42.25.407，发布模块64010。
- 两轮限定只读审查，确认训练Job尺寸/远程Atlas字段P1补RED关闭；最后未发现新增可确认P0/P1。没有新增审查测试或生产连接。

## E/F 提交、CI与接续

本次修改清单以同一功能提交的git show --stat为准：共享catalog/ModelArtifact/转换参数与SDK探测/原Worker、API和remote/Agent合同、原UI/对应表、相关测试、原remote-conversion-runtime工作流、VERSION及下列文档。未建立第二套数据库、转换执行器、Owner或轮询。

最终完整SHA和全部Actions/Checks、关键Jobs保存到独立验收附件：`C:/Users/jorsam/.codex/visualizations/2026/10/20/01a156ca-1ca0-7b70-8497-bd255da4345e/dynamic-conversion-ci-final-20261020.json`。推送前该附件尚未生成，不预称CI通过。接续先核对附件SHA与实际HEAD，再fetch/pull；若不同，不沿用绿色。

同步更新：CODEX_CURRENT_STATE、AGENTS、FRONTEND_OWNER_MAP_V42_25、frontend-legacy-audit、TECH_DEBT_CLOSURE_V42_25，以及Sophon专项；完整原需求在下文。下一步仅普通FF推送/最终SHA CI，具体CI失败只修复可复现项；VERSION不再连续递增。

本轮Windows没有真实TPU-MLIR，**真实BM1684编译、BMODEL板卡加载/推理、数值精度比较与生产页面部署效果均NOT VERIFIED**。可进入经授权的现场验收准备，不能宣称实机完成。用户历史X/88 FP16成功不替代本轮BM1684证据。未部署、未改生产密钥/依赖/数据库、未调用新畅联写接口或操作OSS；历史17项/7Weight生产补齐仍未执行。

## 首次SHA CI反馈收敛

首次推送e4e723a2934da446d39403715380636c2c7d1fe1的Training Request API Job暴露原两项Rockchip自动转换夹具仍缺新字典/实检能力。补显式本地RKNN字典、资源kind/precision及原检测入口隔离夹具，不恢复固定业务芯片、不绕过实检。保留原唯一候选一次提交、歧义零提交/零job及RK3568/RK3576存在、未配置RK3588不出现的断言；错误信息由实际已就绪候选生成，并新增local_chip_id/fp16断言。针对两项本地2通过（dynamic-ci-autork2.log），共享catalog API/unit26项复验通过（dynamic-ci-catalog.log）；不扩大到无关训练测试。VERSION仍42.24.359。同时外部发布两次contract Job的文本守卫仍要求已移除固定CHIP_BINDING_DICTIONARY/旧说明文字，改为原Repository读取动态字典、校验入口及新增真实绑定回归守卫，保留全部发布/身份/UNKNOWN安全守卫；完整原两段守卫本地运行GuardExit=0（dynamic-publish-guards.log）。最终以修复后完整SHA全部CI为准。

## 已确认产品需求V2（用户原文归档，后续实现以此及第十八条为准）

# 畅联云算法训练平台｜2026-10-20 动态厂商字典、芯片真实转换能力与转换参数体系整合开发指令 V2

## 一、接手项目与基本要求

你现在接手现有正式项目：**畅联云算法训练平台**。

GitHub 仓库：`jorsamj/aixunlianpingtai`

唯一长期开发分支：`feature/external-algorithm-publishing`

2026-10-20 核验时的 HEAD：

`7a2492b24de5d6259bf792ed074f1548e66d6eda`

参考 VERSION：`42.24.358`

注意：上述 SHA 仅是本次核验快照，不允许当作后续固定 HEAD。

**执行前必须先 fetch/pull 最新长期开发分支，核对真实 HEAD、工作区、近期提交及其他 Codex 会话正在修改的内容。不得覆盖其他工作。**

这是已有正式训练、模型转换、资源调度、模型资产和外部发布系统，禁止推倒重建。

本轮继续落实之前的完整开发需求，同时重点修复一个核心缺口：

**厂商和芯片不仅要能从数据库动态选择，还必须真正决定 SDK 编译目标，让用户获得对应芯片能够使用的真实模型成果。**

这不是单纯的转换弹窗优化，而是从字典、模板、SDK 能力、任务参数到真实模型产物的完整链路治理。

---

## 二、目前核验出的真实代码状态

本次已读取长期开发分支，确认：

### 2.1 已有能力

现有系统具备：

- YOLO PT → ONNX 的转换链路。
- 算能 ONNX → MLIR → BMODEL 的真实编译执行代码。
- 瑞芯微 RKNN 转换能力。
- 华为 Atlas / Ascend 的 ATC 转换相关路径。
- 本机与远程转换资源。
- TPU-MLIR SDK 探测。
- BMODEL `model_tool --info` 结构检查。
- ModelArtifact 和 Conversion Manifest。
- 外部算法权重发布链路。
- 训练成果参数继承的部分实现。

这些必须尽量复用，禁止重新建立平行执行引擎。

### 2.2 当前明确存在的限制

**问题 A：芯片仍然硬编码。**

`platform_core/conversion.py`：

```python
SUPPORTED_SOPHON_CHIPS = frozenset({"bm1684x", "bm1688"})
```

瑞芯微也存在固定转换芯片白名单。

**问题 B：算能精度固定 FP16。**

当前：

`validate_target("sophon", ...)`

只允许 FP16。

`deployment_worker.py` 的 `build_sophon()` 也将编译精度写成固定的 `F16`。

**问题 C：SDK 能力检测受到产品白名单限制。**

`platform_core/sophon_runtime.py` 的探测结果与上述芯片白名单取交集，导致 SDK 已支持但平台未列入白名单的芯片无法直接使用。

**问题 D：算能产物命名也固定 FP16。**

即使未来放开芯片选择，若编译精度可变，现有 `_fp16.bmodel` 命名逻辑也必须同步修改。

**问题 E：本地字典仍有固定候选。**

`platform_core/compute_platform_catalog.py` 目前仍存在固定的 `CHIP_BINDING_DICTIONARY`。

必须核查当前代码中本地字典与外部新畅联算力环境的职责边界，并按此前确定的动态管理设计实施。

以上是已核查代码中的问题，不代表其他 Codex 会话没有正在修复。

请在开发前重新核查最新代码，已完成的部分直接复用，不要重复修改。

---

## 三、本轮最重要的验收目标

用户期望：

在后台本地算力环境字典中添加一款芯片，例如：

- 厂商：算能
- 芯片：BM1684
- 标准 SDK 芯片编码：`bm1684`
- 关联模板：算能 TPU-MLIR

用户在转换任务中选择：

- YOLO11n `best.pt`
- 算能
- BM1684
- 合法的转换精度
- 可用转换资源

平台必须：

1. 判断本地字典有无这款芯片。
2. 判断算能转换 Adapter 是否支持该类型目标。
3. 判断当前 TPU-MLIR SDK 是否真正支持该目标。
4. 判断目标芯片允许哪些转换精度。
5. 根据源模型和厂商模板计算实际参数。
6. 将 BM1684 的标准编译编码传递给 TPU-MLIR。
7. 执行真实 ONNX → MLIR → BMODEL 编译。
8. 检查编译退出码、产物结构、实际目标芯片及必要的模型输入输出信息。
9. 为真实生成的 BM1684 BMODEL 建立 ModelArtifact。
10. 在界面明确区分编译成功、模型验证和实际硬件验证。

**绝对不允许生成 BM1684X 的 BMODEL 后，将名称改为 BM1684。**

也不允许只是在 Manifest 中填 BM1684，就声称模型已经转换成功。

### 3.1 自动扩展的真实含义

本轮希望做到：

**同一厂商的新芯片，只要现有 Adapter 能够通用处理、对应 SDK 确认支持、芯片硬性约束已经具备足够证据，就可以通过本地字典配置直接使用，而不用为该芯片再开发一份独立 Python 转换程序。**

但必须明确：

- 数据库配置不会自动生成新的 SDK 功能。
- SDK 不支持的芯片不能通过修改字典变成可转换。
- SDK 支持芯片，不代表所有模型都一定可以成功编译。
- 已能编译不代表已经通过真实板卡推理验证。
- 新厂商如果没有 Adapter，仍需要真实 SDK 适配开发。

禁止把动态配置能力理解为“任意新增芯片，系统都自动支持”。

---

## 四、厂商、芯片和转换模板保持动态设计

维持此前最终确定的设计：

### 4.1 厂商完全来自本地数据库

厂商不是固定五个。

首批只需要准备五类可关联模板：

1. 瑞芯微。
2. 华为 Atlas。
3. 华为。
4. 算能。
5. 寒武纪。

五个模板可以预置，但不能自动等同于五条厂商字典记录。

如果本地字典只有算能和瑞芯微，转换界面就只显示这两个厂商。

未来新增其他厂商，应允许关联其真实 SDK Adapter 和模板，而不需要修改前端厂商枚举。

### 4.2 芯片完全来自本地数据库

应有独立维护的芯片字典，逻辑字段包括：

- 本地芯片 ID。
- 所属厂商 ID。
- 芯片显示名称。
- 稳定芯片编码。
- SDK 目标芯片编码。
- 启用状态。
- 关联模板或厂商信息。
- 真实必要的能力约束引用。

必须区分：

**本地芯片身份、SDK 编译目标编码、外部新畅联分类 ID。**

这三个值不能混用。

外部映射缺失不得阻碍本地转换。

### 4.3 不为每款芯片复制完整模板

继续采用：

**厂商/SDK 级参数模板 + 少量芯片硬性约束。**

例如算能共用 TPU-MLIR 模板。

BM1684、BM1684X、BM1688 不需要复制三套完全相同的输入宽高、预处理和编译字段。

它们只需要拥有真实存在的兼容差异，例如精度、Batch、核心数量、动态 Shape 等限制。

新增芯片差异时，只增加被验证过的规则。

禁止提前构造复杂的多级 Profile 系统。

---

## 五、转换能力的正确判定机制

现有动态检测需要从“芯片可见性”升级为“真正能够执行的目标能力判断”。

### 5.1 区分四类信息

**第一类：本地字典**

决定用户能够看到哪些厂商和芯片。

**第二类：平台 Adapter 能力**

决定现有代码能否按照对应 SDK 生成有效的命令和参数。

**第三类：当前转换资源及 SDK 能力**

决定当前节点上的编译器、SDK 版本和必要工具是否可用，是否宣称支持该目标。

**第四类：真实转换与硬件验证证据**

决定该模型是否已经真实编译、模型级验证或经过板卡实测。

这四类信息必须独立表达。

### 5.2 芯片状态

至少区分：

- 可转换。
- 不可转换。
- 待检测。
- 暂未适配。
- 转换服务不可用。

其中“可转换”仅表示具备已确认的执行前提，不代表这个具体模型一定编译成功，更不代表通过板卡推理验证。

### 5.3 SDK 探测改造

复用现有 `probe_sophon_toolchain()`。

但不能继续将实际 SDK 支持范围直接截断为固定的 BM1684X / BM1688 列表。

应当：

1. 检查编译器真实位置与版本。
2. 获取 SDK 实际宣告的目标芯片。
3. 识别相关参数能力。
4. 检查当前 Adapter 是否具有足够的参数合同。
5. 将结果与本地芯片字典匹配。
6. 应用已确认的芯片限制。
7. 检查转换节点是否可用。
8. 输出芯片级可转换状态和原因。

注意：

**`model_deploy.py --help` 中出现某款芯片，仅能证明编译器声明接受该目标参数，不能单独证明所有精度、所有模型都能编译。**

同理，出现 F16、F32、INT8 全局选项，不代表每款芯片支持全部选项。

必须用 SDK 文档、版本相关兼容证据和必要的执行验证建立芯片/精度约束。

禁止简单将：

`SDK芯片列表 × SDK全局精度列表`

作为全部合法组合。

如果缺少充分证据，应保持待确认或不可提交，而不是乐观放行。

---

## 六、算能 BM1684 的专项改造

这是本轮必须覆盖的核心用例。

### 6.1 芯片目标

TPU-MLIR 官方工具链提供 BM1684 编译目标。

应核验当前转换节点实际安装版本是否支持 `bm1684`，不能仅引用上游最新版源码推断生产已安装 SDK 的能力。

### 6.2 精度约束

BM1684 与 BM1684X 的精度能力不同。

BM1684 不得使用 FP16 作为默认编译精度。

对于 BM1684，优先评估 F32 编译路径；INT8 只有完成真实校准数据合同和对应验证后才允许启用。

BM1684X、BM1688 原有已验证 FP16 路径必须保持可用。

不得为了支持 BM1684，破坏既有两款芯片的转换能力。

### 6.3 精度参数必须动态生成

当前：

```python
"--quantize", "F16"
```

需要改为根据最终通过验证的精度配置产生 SDK 参数。

例如经过 SDK 验证后：

```text
BM1684  → F32
BM1684X → F16
BM1688  → F16
```

这只是需要验证的典型配置场景，不是要求将三款芯片写成永久固定映射。

程序应能够根据真实能力和约束决定具体参数。

如果厂商模板默认 FP16，但用户选 BM1684：

- 自动计算并展示合法的推荐配置。
- 告知推荐精度为何改变。
- 用户显式选择非法精度时立即阻止提交。
- 后端仍需重新校验。
- 不允许执行阶段静默篡改用户最终确认的配置。

### 6.4 命令行必须传递真实芯片

例如 BM1684 的合法 F32 编译合同应能生成对应命令：

```bash
model_deploy.py \
  --mlir model.mlir \
  --quantize F32 \
  --chip bm1684 \
  --model model_bm1684_fp32.bmodel
```

这是目标合同示意。实际参数应以当前 SDK 帮助信息和兼容性验证为准。

SDK 使用 `--chip` 或 `--processor` 时，依据安装版本确定。

不能仅根据数据库自由拼接任意命令行参数。

所有参数都必须经过现有 Adapter 的显式映射与校验，禁止任意 Shell 参数注入。

### 6.5 正确生成目标产物

例如：

```text
yolo11n_bm1684_fp32.bmodel
yolo11n_bm1684x_fp16.bmodel
yolo11n_bm1688_fp16.bmodel
```

命名应反映实际芯片和实际转换精度。

但文件名只能用于展示，不可作为模型真实身份的唯一证据。

真实目标必须通过编译记录和产物结构验证确认。

---

## 七、所有厂商统一适用的芯片目标规则

不仅算能，其他厂商也必须遵守相同原则。

### 7.1 瑞芯微

继续复用 RKNN 转换路径。

用户选择 RK3568：

- 检查对应 RKNN SDK。
- 检查芯片目标编码。
- 检查芯片与精度、量化参数的兼容性。
- 执行 RK3568 对应的实际 RKNN 编译。
- 生成真实 RKNN 产物。
- 保存真实目标和完整参数。

用户选择 RK3576 等其他芯片时同理。

不可把一种芯片的产物直接当成另一款芯片通用产物。

### 7.2 算能

使用 TPU-MLIR。

支持将用户选择的真实芯片和有效精度传入工具链。

现有 BM1684X、BM1688 保持回归兼容。

BM1684 作为本轮新增验收案例。

其他算能芯片后续是否能够通过字典直接接入，由当前 SDK 和 Adapter 真实能力决定。

### 7.3 华为 Atlas

复用现有 ATC 转换路径。

用户选择的芯片/SoC 必须对应实际 ATC `soc_version`。

不能仅保存芯片名称，而没有传入真实编译目标。

### 7.4 华为

保留独立本地厂商身份。

转换 SDK、适配器和参数维度根据实际关联确定。

不能未经证实就直接复用 Atlas 适配方式。

### 7.5 寒武纪

准备动态参数模板和 Adapter 接入合同。

如果没有真实编译器和可验证适配器，显示暂未适配，不生成伪转换产物。

### 7.6 其他新增厂商

未来新增厂商时，可以通过配置关联已经存在的兼容 Adapter。

如果没有对应 Adapter，则需要专门完成一次新的 SDK 适配开发。

不得承诺仅凭字典就自动支持全新 SDK。

---

## 八、训练成果智能继承保持原需求

转换初始参数应由后端统一决议：

**厂商模板 + 模型真实输入合同 + SDK/芯片限制 + 用户合法配置。**

### 8.1 需要继承

- 输入高度和宽度。
- 模型架构。
- 框架版本。
- 类别数量。
- 真实 class_id 顺序。
- 预处理输入格式。
- Letterbox。
- Padding。
- 归一化合同。
- 输出结构。
- 后处理约定。

例如训练输入是 800×800，默认转换尺寸优先为 800×800。

若实际输入是 384×640，必须保留矩形输入。

已有 ONNX 必须优先验证真实输入 Shape。

### 8.2 不得直接继承

- Epochs。
- 训练 Batch。
- Workers。
- Optimizer。
- 学习率。
- AMP 开关。
- GPU 训练调度参数。

转换精度和训练精度必须独立。

例如 FP32 训练的模型可以转换为合法的 FP16 部署模型，不需要仅因为编译精度不同而重新训练。

### 8.3 解决冲突

厂商默认值不能覆盖真实训练事实。

训练信息不能覆盖芯片硬性约束。

用户自定义参数不能覆盖 SDK 禁止的选项。

参数改变模型输入/输出合同时，必须同步处理并验证预处理和后处理，不能只在转换命令中替换数字。

---

## 九、转换弹窗的最终设计

沿用已有转换弹窗，不创建第二套页面。

建议布局：

### 9.1 源模型

展示：

- 模型名称和版本。
- 真实源权重。
- 输入宽高。
- 实际训练精度。
- YOLO 版本及架构。
- 标签数量。

### 9.2 厂商

直接读取本地字典。

加载该厂商关联的配置模板。

### 9.3 目标芯片

显示本地字典中属于该厂商的芯片。

每个芯片展示当前真实状态及不可用原因。

不能因为某个芯片 SDK 不支持，就从字典列表中直接隐藏。

当存在多个目标芯片时，必须由用户明确选择。

### 9.4 转换资源

显示：

- 当前转换节点。
- SDK 名称及版本。
- 实际支持目标。
- 可执行状态。
- 不可执行原因。

### 9.5 转换参数

基础配置尽可能简洁，只显示必要字段。

高级配置按照厂商模板动态渲染。

精度下拉列表只能展示或允许选择当前芯片真正合法的组合。

需要明确参数来源：

- 厂商默认。
- 训练成果继承。
- SDK/芯片约束。
- 用户自定义。

### 9.6 提交

前端仅展示后端统一计算的参数和校验结果。

提交时后端重新验证：

- 本地厂商。
- 真实芯片。
- Adapter。
- SDK。
- 转换资源。
- 精度。
- 输入 Shape。
- 其他硬性约束。

禁止通过绕过前端直接提交非法芯片和精度。

---

## 十、真实模型转换与产物验收

用户选择哪个芯片，最终产物必须与该芯片保持一致。

### 10.1 执行前

核验：

- 源模型存在且身份正确。
- SHA256 一致。
- 输入合同有效。
- SDK 可用。
- 目标芯片合法。
- 转换参数合法。
- 转换资源支持对应执行方式。

### 10.2 执行中

复用现有 Worker、Agent、任务队列、Lease、取消、恢复及进度机制。

实际执行编译器。

保存：

- 真正执行的命令参数。
- SDK 版本。
- 执行资源。
- 运行日志。
- 错误码。
- 中间模型与最终产物关系。

不允许为了兼容新芯片复制一套独立 Worker。

### 10.3 执行后

需要检查：

- 编译进程真正成功。
- 输出文件存在且非空。
- 文件 SHA256。
- 文件大小。
- 工具能够读取模型结构。
- 实际芯片信息与所选目标一致。
- 预期输入和输出合同得到验证。
- 精度、Batch、Shape 等必要事实有可核验证据。

不能把“命令返回 0”单独作为全部成功条件。

如果编译器未提供充分的结构证据，应明确标记验证不足，不得臆造验证通过。

### 10.4 验证状态

必须至少区分：

- 编译失败。
- 编译成功但待验证。
- 模型级验证通过。
- 实际硬件验证通过。

对于没有真实板卡的环境，不要求伪造硬件验收。

但必须如实表明还没有完成板端加载与推理验证。

### 10.5 模型真实可用性

除编译成功外，还需要关注：

- 输入预处理是否一致。
- 输出张量语义是否正确。
- YOLO Detect Head 和 NMS 是否匹配。
- 坐标还原是否一致。
- 模型精度是否存在明显损失。

具备模型运行环境时，可以增加 ONNX 与编译后模型的输出对比。

硬件可用时，再执行真实板端加载、推理和质量验收。

---

## 十一、数据库与 ModelArtifact

必须继续使用现有 ModelArtifact 作为模型资产事实来源。

每次成功转换保存：

- 源模型 ID 和 SHA256。
- 算法及版本。
- 本地厂商 ID。
- 本地芯片 ID。
- 实际 SDK 芯片编码。
- 外部平台映射信息（如果存在）。
- 厂商模板 ID 和版本。
- 转换资源 ID。
- SDK 名称和真实版本。
- 训练真实精度。
- 转换实际精度。
- 输入高度和宽度。
- 类别及 class_id 顺序。
- 有效转换参数快照。
- 预处理合同。
- 模型输入输出信息。
- 模型文件类型。
- 产物 SHA256 和大小。
- 编译和模型验证状态。
- 硬件验证状态。
- 转换时间。
- 对应原始转换任务。

同一个训练版本允许存在：

```text
best.pt
model.onnx
model_bm1684_fp32.bmodel
model_bm1684x_fp16.bmodel
model_bm1688_fp16.bmodel
```

这些是同一个模型版本的不同部署产物，不应该因为芯片不同而重复创建算法版本。

不能把 BM1684 与 BM1684X 的模型资产覆盖成同一个。

模板后续修改不得改变历史转换任务和历史产物参数。

---

## 十二、外部新畅联对接

复用现有：

`配置中心 → 平台对接 → 厂商对应表`

本地厂商和芯片是独立业务数据。

外部平台分类只是映射关系。

如果新畅联只有一个“算能通用”分类，可以按既有业务规则将多个本地算能芯片绑定该分类。

但本地必须保留实际 BM1684、BM1684X、BM1688 身份。

**外部分类相同不代表模型文件可互相通用。**

未配置外部平台时，平台必须仍然能够：

- 维护厂商和芯片。
- 检查 SDK。
- 创建转换任务。
- 生成模型。
- 保存 ModelArtifact。
- 下载真实模型产物。

本轮不得破坏正在开发的 Weight tags、历史 Weight edit 补齐和模型元数据治理。

不重复创建 Version、Weight 或 OSS 对象。

---

## 十三、必须补齐的自动化测试

### 13.1 动态字典

- 字典只有算能和瑞芯微时，只显示两个厂商。
- 新增其他厂商，不需要修改前端固定枚举。
- 新增 BM1684 时，可以正确关联算能模板。
- 字典有芯片但 SDK 不支持，显示不可转换。
- SDK 声明支持但本地字典未收录，不擅自自动创建业务字典。
- 没有外部新畅联时，仍可本地转换。

### 13.2 芯片真实转换

- BM1684 选择合法 F32 后，传递 `bm1684` 和 `F32`。
- BM1684 选择 FP16 时，后端拒绝。
- BM1684X 原有 FP16 转换合同保持正常。
- BM1688 原有 FP16 转换合同保持正常。
- 切换目标芯片后，编译命令真实改变。
- 切换精度后，编译参数和产物身份保持一致。
- 错误芯片 BMODEL 不得登记成功。
- SDK 返回不支持目标时，禁止实际编译。
- `model_tool` 执行失败时，不允许伪造验证成功。

### 13.3 SDK 能力

- 工具不存在。
- SDK 版本变化。
- 工具支持目标但 Adapter 不支持。
- SDK 支持芯片但对应精度缺乏兼容证据。
- 转换资源断线。
- 远程 Worker 能力变化。
- 多个芯片同时可用。
- 工具声明支持与实际编译失败之间的状态区别。

### 13.4 模型合同

- 640×640。
- 800×800。
- 384×640。
- FP32 训练转换 FP16。
- 训练 Batch=75，转换 Batch=1。
- 正确类别顺序。
- 完整预处理和后处理信息。
- ModelArtifact 不同芯片产物共存。
- 历史产物参数不可被模板变化覆盖。

### 13.5 真实验收

必须区分：

**单元测试：** 参数校验、命令生成及流程状态。

**集成测试：** 使用实际安装 SDK 完成模型编译，确认 BMODEL 结构。

**硬件测试：** 真实目标芯片加载及推理。

没有 SDK 或板卡条件时，如实记录 NOT VERIFIED。

不能用 Mock SDK 测试通过冒充真实芯片转换成功。

---

## 十四、优先检查和复用的文件

重点检查：

```text
platform_core/conversion.py
platform_core/compute_platform_catalog.py
platform_core/sophon_runtime.py
platform_core/rknn_runtime.py
platform_core/node_agent_conversion_runtime.py
platform_core/model_artifacts.py
platform_core/external_algorithm_publish.py
platform_core/external_algorithm_platform.py

deployment_worker.py
rknn_convert_runner.py
remote_deploy_server.py
app.py

static/app.js
static/main.mjs
static/modules/
```

还应检查最新分支已经新增的动态字典、模板、能力探测、API 和对应测试文件，不限于上述文件。

按照现有架构最小化增量开发。

---

## 十五、工程限制

继续遵循以下要求：

1. 不推倒重建。
2. 不引入多层复杂嵌套。
3. 不重复建设 Adapter、Worker、Repository 或 ModelArtifact。
4. 不把五个厂商写死。
5. 不把芯片候选写死。
6. 不在数据库中存放未经验证的任意 SDK 命令。
7. 不删除真实转换准入校验。
8. 不允许前后端各自计算不同默认参数。
9. 不允许通过改文件名或 Manifest 冒充真实芯片转换。
10. 不允许 SDK 探测结果冒充真实编译或硬件验收。
11. 不允许复用错误芯片的历史产物。
12. 不擅自安装生产 SDK、修改生产数据库或重启服务。
13. 不擅自操作生产 OSS、历史 Weight、算法版本。
14. 不破坏其他 Codex 会话正在完成的开发。
15. 不因为新芯片支持而回退原有 BM1684X/BM1688/RKNN 能力。
16. 不为了测试通过删除或放宽现有重要断言。

有真实 SDK 限制时，要保留安全门禁，而不是简单删除白名单后放行所有芯片。

---

## 十六、开发与交付顺序

### 第一阶段：重新核验最新代码

读取最新长期开发分支，检查其他开发会话已经完成的工作。

输出：

- 当前 HEAD 和 VERSION。
- 动态字典完成情况。
- 厂商模板完成情况。
- SDK 能力检测情况。
- 实际编译目标传递情况。
- BM1684 支持现状。
- 可以复用的现有实现。
- 真正需要修改的缺口。

不要重复建设已完成部分。

### 第二阶段：修复实际缺口

优先完成：

1. 动态芯片字典与转换 Adapter 的可靠关联。
2. 芯片级兼容约束机制。
3. SDK 探测和产品实际准入的一致性。
4. 编译精度及目标芯片动态传递。
5. BM1684 的合法 F32 转换合同。
6. 转换弹窗、后端和 Worker 合同统一。
7. 产物真实芯片身份校验。
8. ModelArtifact 元数据持久化。
9. 原有芯片转换回归测试。

### 第三阶段：验收

至少提供：

**A. 当前状态表**

每个厂商和代表性芯片：

- 是否有 Adapter。
- 是否有 SDK。
- SDK 是否声明支持。
- 是否支持对应编译精度。
- 是否已实际编译。
- 是否已模型级验证。
- 是否已板卡验证。

**B. 算能专项证明**

明确展示：

- BM1684 的最终有效参数。
- BM1684X 的最终有效参数。
- BM1688 的最终有效参数。
- SDK 编译目标是否与用户选择一致。
- 实际命令构造是否正确。
- 实际模型文件是否具有对应目标身份。

没有实际 SDK 编译证据的，不得声称已完成真实转换。

**C. 核心工程证据**

- 变更文件。
- 回归测试结果。
- 失败测试和修复过程。
- 最终 Commit SHA。
- Git 工作区状态。
- VERSION。
- 最终 SHA 对应 CI 状态。
- 尚未验证的 SDK/硬件问题。

### 第四阶段：安全推送

在确认不存在其他开发会话冲突、已经完成必要测试后，按既有项目授权范围将本轮变更安全推送至：

`feature/external-algorithm-publishing`

禁止强推、擅自合并 main、擅自部署生产。

如果存在其他 Codex 未合并或正在开发的变更，必须先协调或隔离，不能覆盖。

---

## 十七、最终完成标准

本轮的核心验收不是“芯片下拉框可以显示 BM1684”。

而是：

**在本地字典新增 BM1684，关联已有算能 TPU-MLIR Adapter 后，平台能够确认对应 SDK 和芯片约束，使用合法精度向编译器传递真实 `bm1684` 目标，并在具有实际 SDK 环境时生成和检查 BM1684 专用 BMODEL。**

同时：

- BM1684X、BM1688 继续正常工作。
- 新芯片如果由现有 Adapter 通用支持，不需要另外开发该芯片专用转换程序。
- 不支持的芯片必须明确阻止转换。
- SDK 兼容但模型编译失败，必须报告真实失败原因。
- 没有真实编译证据不能登记为编译成功。
- 没有真实硬件证据不能登记为板卡验证通过。
- 厂商默认参数、训练成果和芯片约束由后端统一决议。
- 本地数据库持续保留真实模型参数与芯片身份。
- 系统不依赖新畅联也能独立转换。
- 不增加重复系统和技术债。

**最终要求：让厂商字典和芯片字典真正驱动已有转换引擎，而不仅仅驱动前端选项。**

请以最新代码为基准，先确认其他 Codex 已完成的工作，再进行最小必要开发、测试、提交和最终 SHA 的 CI 核验。生产部署必须另行取得用户明确授权。


## 第十八条强制工程合同归档

测试只针对实际改动，不删除/跳过失败或降低断言；前后端参数、默认值、校验、状态、错误及执行结果统一真实后端合同。禁止多层套娃、重复封装/模块/Owner和新增技术债。完整需求、架构、进度、证据和下一步进入本专项及现有handoff。正式VERSION按规范本轮一次递增，必要前后端/缓存一致。安全提交普通推送唯一长期分支，不覆盖其他会话，不部署生产；最终提供实际HEAD/VERSION/文件/文档/测试/CI/未验证事项。
