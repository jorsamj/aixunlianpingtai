# 全平台性能审计与分阶段轻量优化（2026-10-28）

唯一专项。基线长期分支远端/本地46d8fb8f266b222b98f9c6b5cf5df0c52e51f862、VERSION42.24.398，fetch一致且工作区干净；5944/其他工作树和训练模板WIP保留。上一转换专项及其41/115、文档21/57 CI已通过，不重复开发，不代表本轮验收。

## 需求与实施边界

1. 先全平台代码审计及轻量计时。重点训练/jobs查询（历史、旧队列、索引、数据库）及训练素材分页（角色/历史/分页/缓存/版本）。
2. 仅实测证实且不改变调度/隔离语义的明显重复开销可最小修复。队列检查、旧任务恢复、SSE/UNKNOWN、幂等/fencing/GPU独占不删除；全局统计、跨页全选和正负样本语义不裁剪。
3. 其他登录/算法/素材/设备/转换/上传/创建超时模块只列风险、证据和优先级，等待用户确认后实施。
4. 不引入Redis/APM/新任务系统/新缓存框架。详细诊断默认关闭；仅关键链路计时和匿名计数，不记凭据、原图、SQL参数或完整路径。
5. 不做生产扫描、部署、数据库更改、真实GPU或大规模压测；隔离测试数据不能当生产实测。

## 阶段进度

|阶段|状态|证据/剩余|
|---|---|---|
|A 基线和调用链|已验收|已核对最新与已有增量/SSE/缓存；其余模块审计继续|
|B 两条链轻量计时|已验收|小规模隔离、冷/热/筛选/算法/数据版本；真实SQLite，无图片解码|
|C 已证实问题最小修复|已验收|先依据B证据确定范围|
|D 定向兼容验证和报告|已验收|复用原测试，最终SHA CI独立核验|

## 初始代码事实（不是生产根因）

/jobs：list_jobs先_v48_dispatch_training_queues再sync_jobs_index，二者各调用_training_history_context。该函数已有job.json按文件签名复用，但每次都逐页读取全部durable TRAINING记录。sync已复用终态投影、不重复写未变化index；enrich对需更新行仍按原Task读取真状态。SSE健康覆盖时10秒安全补查，异常2秒回退，无活动任务不排训练轮询。

素材：_cached_role_index(max8)冷缓存对筛选候选读取payload/GT后逐条判角色，_role_material_page才截页，截页后get_many实际只拿当前页明细。_cached_usage_pool(max4)按素材/算法/历史revision等对全processed素材分500关联历史索引；query_filter内部按200 token查询。全局角色/筛选总数与排除规则仍必要，不能简单LIMIT60。

## 待补证据

请求耗时、阶段计数、SQL执行/连接数量、JSON解析、缓存命中、实际处理数量及执行计划；无独立生产网络/锁等待测量时写NOT VERIFIED，不用0替代。接续从本文件和原Owner继续，不全站重构。

## 已确认范围与最小实施计划

隔离Windows真实仓库，220条Task+job（返回50）冷1650.85ms、热73.00/70.37ms；每次两轮history/6分页读440Task，冷229连接。1000素材/60当前页，冷104.54ms、热28.99/28.87ms，冷角色1000/历史1060张次；筛选44.26ms、切算法106.78ms、数据revision变更146.76ms。计时包含诊断开销，历史使用关联表为空的基线不代表繁忙生产历史，独立锁等待/网络NOT VERIFIED。

使用writing-plans与TDD；本文件为用户偏好唯一计划位置，不另造重复专项。

- [x] 在原/jobs旧队列检查完成且没有任何legacy行时，将同次请求上下文交给原sync；出现legacy行或异常时保持原重新读取。原enrich允许使用该次已验证project/kind的Task，消除N+1；默认其他调用行为不变。
- [x] TrainingMaterialUsage在原只读事务内读取revision一次，保留旧无表/不完整覆盖与所有token/祖先/同源判定。不改角色全局扫描、不改数据库结构。
- [x] 默认关闭的轻量诊断：只针对两条API，生成匿名request ID、Server-Timing、阶段和处理计数。SQLite诊断只记录计数，不记录语句/参数/路径；缺失的锁/外部进程数据明确未知。
- [x] 复用现有安全合同做定向验证、同一隔离样本对比与一次浏览器核心冒烟；其余模块只审计建议。

## 第一阶段报告（2026-10-29接续，隔离软件验收）

### 环境与数据范围

本地为原隔离detached工作树，位于长期分支最新基线，不新建分支/覆盖其他树；推送仅普通fast-forward。可见同仓库活动会话仅本会话（另一次只读代码审查，无修改/测试）；原其他工作树、5944和两份训练模板WIP保留。本轮VERSION42.24.399，只改本专项共享读路径和诊断，不部署。

只创建隔离SQLite/JSON元数据：220个FAILED历史Task与job（正式列表默认返回50个终态），1000个processed素材/正式GT角色记录，每页60；不解码原图或运行模型。Task使用索引关系为空的性能夹具不代表生产高密度历史；有关系/同源/祖先/负样本语义由既有针对性合同验证。冷=进程级缓存冷，未清操作系统磁盘缓存；阶段为inclusive，不能相加当总耗时。

### 训练状态查询：实测和修复

|指标|修改前|最终隔离函数链样本|
|---|---:|---:|
|冷缓存总耗时|1650.85ms|758.77ms|
|热缓存（2次）|73.00 / 70.37ms|41.73 / 40.59ms|
|一次history读取|2|1（仅all-Durable）|
|Task分页查询/读取对象|6 / 440|3 / 220|
|冷连接/SQL语句|229 / 687|6 / 18|
|热连接/SQL语句|9 / 27|6 / 18|
|冷JSON解析|884|442|
|返回条数/历史条数|50 / 220|50 / 220|

[修改前](artifacts/platform-performance-20261028/before-jobs.json)与[最终函数链原始数据](artifacts/platform-performance-20261028/after-jobs.json)记录history、queue、index、enrich、SQL执行、JSON解析等阶段。修改前history合计467.31ms、旧队列443.90ms、index1206.89ms（互相嵌套）；最终history468.12ms、旧队列469.50ms、index353.87ms。首轮冷历史文件读取没有神奇消失，主要减少重复Task重建/连接与第二轮元数据扫描。此为小样本描述，不承诺生产百分比。

另用原handler挂载隔离FastAPI/ASGI（不含正式登录/真实网络），[完整响应](artifacts/platform-performance-20261028/after-jobs-http.json)：缓存冷455.22ms、热31.70/47.68ms，50条90001字节。与上表是不同测量层，不能混合计算前后比。真实Chrome原空测试项目GET另为34.5ms、2字节/0条，Server-Timing29.893ms，只验证Network/Request ID接通，不作为大历史性能结论。

修复仅同次请求复用：原dispatcher完整检查后，只有**没有任何legacy行**才返回已有上下文；任意legacy行或异常均保留原后读。sync只对已明确SUCCEEDED/PARTIAL_SUCCESS/FAILED/CANCELLED的Task用已读对象，活动/未知/新收编身份仍fresh get。原权限、索引终态50条、所有活动任务、归档、TaskRepository/Worker/lease/fencing/GPU队列不变；没有跨请求TTL缓存。终态可以原位retry，不能说永久不变；下一请求依revision/status重新读。

SSE代码及原Node合同：完整覆盖正常时10秒安全补查，异常2秒回退，未知/终态事件合并原canonical查询；无活动任务不建定时器，后台不可见暂停。频率是代码+虚拟时钟验证，不是生产流量统计。真实生产断网/SSE代理行为NOT VERIFIED。

### 训练素材分页：实测和限制

[原函数链](artifacts/platform-performance-20261028/before-picker.json)与[最终函数链](artifacts/platform-performance-20261028/after-picker.json)，以及[原路由完整ASGI响应](artifacts/platform-performance-20261028/after-picker-http.json)分别留存；无认证/网络/缩略图解码开销，不假装生产首开。

- 原冷总104.54ms，usage pool40.73ms、role build26.82ms、role page47.57ms，19连接/75语句、3062次JSON解析。
- 原热28.99/28.87ms，两个缓存均命中，11连接/32语句、60次JSON解析。
- 冷角色判定1000条；历史关联1000候选+60当前页=1060张次（3个query_filter调用，内部token分200批）；当前页payload只读60条。热缓存只关联当前页60条，不重建角色。
- 更换文件名筛选只判100个候选且usage缓存命中；相同目标类别切算法可复用角色但需重建usage；素材revision变化两个缓存均失效。热重复2/2命中。非通用生产命中率。
- 已移除query_filter内事务外重复revision连接。revision现在与tokens读取同一只读事务，旧无表/覆盖未知分支保留；强制meta表异常仍显式报错。连接冷19→16、热11→10；全局角色与候选数不变；最终语句冷75→69、热32→30。完整ASGI冷186.97ms、热74.73/73.91ms，60条58147字节（仅最终路由测量，不能与原函数链当作前后比）。**未测出稳定整体耗时下降，不宣称素材页面已提速**。最新各阶段和完整ASGI耗时/字节见原始JSON，不能选最好样本替代波动。
- [EXPLAIN计划](artifacts/platform-performance-20261028/usage-query-plan.json)：1 token用project/kind/value完整索引；200个OR条件只使用project前缀，并有DISTINCT临时B-tree。仅结构/空关系表计划，未证明生产高密度关系超时。未新增索引/DDL/临时状态表；下一轮应先在有代表性历史关联密度下比较原token查询，再决定是否改写。

角色全候选计算仍承担全局正负样本、筛选总数、历史排除，不能LIMIT60掩盖。第一阶段没有重写投影/分页/选择模型；100000素材、高框数GT、频繁版本变化及缓存淘汰成本仍NOT VERIFIED。

### 其他模块审计与建议（本轮均未专项修改）

|模块/位置|已经存在的优化|代码风险与证据等级|建议/优先级|
|---|---|---|---|
|登录：changlian_login_auth；首页v53|签名会话本地校验；核心先开、有界启动；Snapshot只概要，不读全素材|首次登录外部服务timeout12秒；Snapshot live counts与jobs分别调用history上下文，仍有重复读取；仅代码事实，生产TTFB/网络未知|P1：先用Network/Server-Timing分段采样真实登录/刷新，再按版本合并必要历史读取；需用户确认|
|算法列表：algorithm-list-runtime|成功训练次数后端统一；页面缓存/只刷当前Owner|刷新仍并发请求algorithms与jobs；服务端counts可能与Snapshot再次读历史；未证明同一页面请求风暴或外部平台阻塞|P1：请求瀑布+历史密度采样；保留当前版本与权限实时性|
|素材管理：MaterialRepository.list_page/thumbnail|服务端分页、正式GT、懒缩略图和原文件锁|每页COUNT总量；复杂筛选/首次缩略图锁存在成本，未测生产大库与NAS|P1：全库/过滤计数分段与EXPLAIN、缩略图冷/热测量；不改GT/删除规则|
|训练配置：training-create-hydration/training_devices|正式表单先开、推荐独立；资源5分钟、推荐60秒前端缓存，按项目/epoch防迟到|后端training-devices仍每次子进程probe torch；recommendation也可启动Torch子进程（timeout8秒），后端无同源合并证据|P1：授权后测进程启动/读取CUDA与真实占用，考虑分开硬件静态与动态资源；不绕最终资源校验|
|转换插件/历史|上一专项已渐进、单资源300秒缓存与并发合并、版本历史分页/增量|显式手动检测/最终校验仍可能等待远程SDK；生产SDK/模型规模未知|P2：直接复用已验收能力，只补真实环境计时；本轮不改CSC/转换语义|
|训练创建超时：TrainingSubmitRuntime|稳定task_id、结果可靠校验、UNKNOWN原ID核验、创建成功立即仅关所属Modal|仍需真实生产长准备/SQL等待/传输拆分；未复现当前版本重复创建|P1：用同请求身份关联后端trace；不重建状态机、不盲目重发|
|上传任务中心：upload-task-center|唯一Owner、稳定DOM/顺序、进度合帧、500ms保存、关键状态即存、后台恢复|终态历史有界100（活动全部保留）；localStorage失败旧代码静默捕获、设备/浏览器/项目隔离会影响展示，未复现用户现场消失|P1：先采样持久化失败/项目切换与服务端ZIP/UploadBatch记录，再明确历史查询/保留政策；清展示不删素材；不新建任务中心|

后续建议均需用户确认，不在本轮继续改登录、算法/素材列表、GPU检测、转换插件或上传历史。共享sync读路径的减少N+1可能惠及原调用者，但未据此宣称这些页面已经优化验收。

### 诊断开关与接续

仅授权开发/诊断环境设置`MC_PERFORMANCE_DIAGNOSTICS=1`（取消即停记录），不修改生产配置。纯ASGI默认直接透传、不缓存请求/响应体；原认证Owner原样保留。仅/jobs与training-materials基础/page/role-page/bulk-selection产生随机X-Request-ID、Server-Timing及platform.performance INFO标量日志；固定endpoint名，无项目ID、完整路径、SQL语句/参数、图片、凭据或请求输入。系统日志若过滤INFO，需按原日志配置开放该namespace。

诊断stage为嵌套inclusive，不可求和；cache_hits按本请求请求数/构建数得到。repository SQL计数只覆盖已挂接连接（不含快速schema旁路等），**不是全部SQLite活动**；隔离benchmark额外按execute完整统计。sqlite_lock_wait_ms和external_process_ms为null=未独立测量；SQL耗时包括执行/潜在等待，不填假0。浏览器Network通过响应头request ID和后端日志关联，未新增API Client/全站监控/后台轮询。

### 实际修改与必要验证

业务：app.py（请求内复用、明确终态投影复用、阶段）、training_material_usage.py（revision只读事务）、performance_diagnostics.py（可关闭标量诊断）；MaterialRepository/AnnotationRepository/TaskRepository连接只加默认空ContextVar观测，不改SQL/事务/迁移；training_material_picker_api仅阶段/候选计数，保留原缓存与全局计算。VERSION399；无静态UI资源变更，不改其缓存标识。

原定向Python17个独立场景：首轮16通过/1测试夹具read_text默认GBK失败，改UTF-8后该例单独通过；没有业务断言失败被忽略。覆盖旧队列启动失败后重读、active lease/worker真值、job原文件不回写、负样本/GT revision、跨页历史过滤及同源排除。后续诊断/完整ASGI路由和usage边界改动仅运行受影响最小项（2、1、7分别通过，重叠不相加）。原正样本durable创建与负样本真实空YOLO导出2/2通过，不启动训练。

Node22/22（原poll-registry与training-progress-stream）通过；真实Chrome一个原Picker场景通过（前后涉及ASGI调整仅重跑此受影响例，不扩测试）：正式窗口1秒内显示、延迟页先显示骨架、60条/分页/选择/确认/异常前端行为及无控制台异常。前端分页为隔离协议夹具（10000总量/60页），只作交互冒烟；真实SQLite1000样本的后台性能由前述独立基准给出。另真实/jobs Network响应有request ID/Server-Timing。正常/断线SSE为原Node合同，未冒充生产端到端实测。

py_compile/build_identity/YAML解析/git diff --check通过。RED证据为原两轮history/重复revision连接及无诊断header，GREEN见原测试；最初性能夹具曾误以为历史返回220（真实既有50上限）及超过GT500提交上限，已改为尊重原合同，未降低生产限制。只读独立审查未发现P0/P1阻塞；明确记录终态可retry，未误称immutable。

CI与关联提交：`4cd4e3e47c3a1e65910345bb3924b2ec2ad55985`准确47/47 Actions、130/130 Checks全部success；[完整回执](artifacts/platform-performance-20261028/code-ci-4cd4e3e4.json)。不沿用任何上一专项绿色。生产锁持有者、真实大库/复杂GT、网络/浏览器CPU长任务、A800、OSS/NAS、外部服务和用户现场长时间等待尚未核验。本轮没有生产扫描/部署/数据库修改/模型覆盖/缓存清理/真实GPU训练。

## 阶段最终回执与下一步

本轮第一阶段入口审计、两条重点链实测、证实重复成本的最小修复、必要验证和代码CI均已验收，VERSION42.24.399；源代码/测试提交4cd4e3e4已普通推送长期分支。剩余素材冷缓存全候选成本未消除，不能把减少连接写成整体提速。其他模块仅代码审计/优先级，未做新改造，后续按上表由用户确认后分阶段接续。

诊断只覆盖认证后选中API业务栈；Server-Timing不代表代理/网络/认证完整链路。浏览器请求总耗时另记。开发可用开关和匿名request ID继续定位真实环境，但本轮未获生产操作授权。Task终态允许原位retry，只复用请求内快照，后续请求重新读revision/status；不能扩成跨请求旧Task缓存。

本次最终提交只补文档/索引和准确代码回执，不再修改业务。文档所在实际提交自身CI须另按GitHub Checks核对，最终交付提供该HEAD和结果，不能用代码提交绿色替代。接续必须先fetch、保护5944/两份模板/其他工作树；不得自动开展全平台重构、生产采样、部署或真实GPU训练。
