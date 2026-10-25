## 2026-10-25｜创建 Loading 与异常恢复专项（进行中）

本节是本轮唯一接续记录。用户授权：只修改已证实的训练创建异常；复用 TrainingSubmitRuntime、原 Modal、withRequestDeadline、原 TaskRepository 和 task_id 幂等；不改变训练参数、数据划分、GT/冻结、GPU独占或 Worker；不部署生产。其他模块只轻量排查，共享缺陷才修复。

### 需求基线与实施计划

| 阶段 | 需求与模块 | 状态 | 已有证据／剩余 |
|---|---|---|---|
| A | 真实代码、最新分支、持久化与幂等审计 | 已完成待验收 | 远端243858b9/VERSION386；原工作区4个标注提交和未提交文件全部保留，新隔离工作树基于远端 |
| B | 提交全过程异常保护；最终DOM恢复；单一真实阶段 | 已完成待验收 | Chrome新增2例RED：try外异常未释放锁、finally异常按钮aria-busy仍true；修复后17项浏览器通过，最终组合待验 |
| C | 首次准备请求截止时间、错误/重试、迟到结果隔离 | 已完成待验收 | 原缓存继续复用；资源/推荐/外部算法核验有界，超时单元已GREEN，真实浏览器待验 |
| D | 创建结果核验、稳定UNKNOWN、原ID查询、后端业务码 | 已完成待验收 | 原30秒截止含JSON读取；新增VERIFYING；未知结果停止动画/保留ID/只查询不POST；后端幂等锁及指纹原有，机器码验证进行中 |
| E | 最小Node/Python/Chrome、版本、正常提交/准确SHA CI | 进行中 | 尚未推送，无本轮CI结论 |

必须覆盖：成功即结束创建，不等GPU/Worker/列表；400/409/422/500、业务错误、非法JSON、网络/超时；初始渲染及finally异常；成功响应丢失；核验超时保持UNKNOWN而非盲目重建；重复点击；关闭/重新打开/草稿修改/切项目迟到隔离；初始化失败/超时可重试；保留配置与错误；真实DOM按钮/aria-busy/动画/错误及POST数量；无未处理Promise。后端持久任务是唯一成功依据，404查询不能证明并发请求永远未创建，不据此开放新ID重试。

### 已确认根因、设计和取舍

1. submitting=true之后的setSubmitStage/updateReadiness在try外，直接异常跳过finally。将所有启动更新移入同一try，finally先释放内部锁，再尽力正常更新，最后仅针对原Modal DOM执行不读取业务数据的恢复；异常记录console，不用空catch隐藏。
2. finally原来只调用updateReadiness；该方法依赖草稿、诊断和其他runtime，异常会遗留DOM禁用/动画。最终恢复独立于这些依赖，但仍在原提交Owner内，不建第二套Loading。明确未知结果保留禁用和查询动作。
3. 创建请求异常后的核验仍显示posting。沿原lastStage增加verifying；查询失败回到稳定failed/uncertain，不伪造成功；任务ID保留，查询按钮只GET。后台刷新失败不得推翻持久创建成功。
4. hydration原请求没有自身截止时间；复用现有withRequestDeadline，含响应解码。沿原项目/epoch/Modal检查，并阻止超时或销毁后结果发布；缓存快开保持原路径。
5. 后端已有同ID锁、请求SHA指纹、202持久化回执及父/准备子任务中断恢复；不重建幂等表。兼容性错误detail有业务code但原HTTP handler只投影通用CONFLICT，本轮限训练入口透传正式业务码；锁竞争应提示结果核验而非明确失败。

### 保护与边界

原工作区 `8ba6ce1a` 及4个标注提交、全部标注WIP、5944祖先和两份未跟踪训练模板测试未覆盖。独立修复工作树 training-create-recovery；本轮不将未交付标注增量推送为训练修复。无生产访问/素材/GT修改/真实训练。最终提交与CI仍待实际执行。


### 轻量相同问题排查（静态核查，不冒充动态验收）

| 操作 | 现有Owner与观察 | 本轮处置 |
|---|---|---|
| ZIP导入 | zip-import-runtime.confirmLabels有原finally，但submittingLabelJobs.add之后、try之前仍执行mappingReview/DOM更新；潜在同步异常可留下提交集合 | OPEN，未复现、未扩改；原轮询/上传不重建 |
| 普通图片上传 | material-upload-runtime.uploadFiles原finally释放activeProjects；activeProjects.add至try之间仍有ID生成/任务中心/渲染操作，潜在同步异常会遗留集合 | OPEN，未复现，不宣称已修复 |
| 清洗、批量标注、标签统一、素材审计 | 共用material-batches原提交Promise/finally，30秒请求截止与UNKNOWN查询；禁用按钮的同步属性更新在Promise外 | 本轮未发现与训练共用的已复现底层问题；运行期异常仍NOT VERIFIED |
| AI标注创建 | 原页面/TaskRuntime仍是Owner；另有标注闭环WIP在原工作区，尚未交付 | 本轮不混入该WIP，不扩大AI业务改造 |
| 模型转换创建 | 原submitConvert428有防重/unknown查询和finally；未替换转换Owner | 仅静态审查，未执行真实转换 |

### 补充根因与验收过程

- 扩展真实Chrome发现：关闭训练表单后，设备读取迟到仍会更新trainingDraft、缓存及renderSplit。新增用例先RED；对设备/迭代起点/固定Benchmark准备沿原PlatformCore.withRequestDeadline绑定截止时间，并校验原项目与Modal DOM身份，不写新窗口。
- 第一轮三文件Chrome共42例：41通过、1失败（旧409污染已编辑草稿），未隐瞒。修正错误展示的草稿身份保护，定向3/3通过；后续最终组合另记。
- Node76/76通过；Python7/7通过、48未选中，无跳过（旧同ID并发/父子恢复/GT冲突及新增锁竞争）。前置RED：Chrome渲染2失败；Python业务码3失败；设备迟到1失败。未运行全仓Python/Node/Chrome。
- 404查询不是“确定没有创建”的原子证明，仍保留UNKNOWN和原ID查询；不自动重发POST。既有持久ID/请求指纹不变。
- VERSION一次386→387；styles/app/main缓存435，submit模块422608，hydration422557。此时未推送，最终准确提交CI待核验。

### 本地最终验收（远端CI未核验）

- Python `tests/api/test_training_request.py -k 'duplicate_original_gt_conflict or create_lock_timeout or concurrent_same_training_id or prepare_child_creation_failure or parent_insert_crash or final_admission_rejects_stale'`：7 passed / 0 failed / 0 skipped，48 deselected。
- Node submit/validation/hydration/version四文件86 passed / 0 failed；最后仅submit改动再定向54 passed，不重复累计。
- 三份用户指定Chrome文件最终组合45 passed / 0 failed（含真实草稿、GT诊断、原Modal与受控API）；随后新增“UNKNOWN关闭重开新ID不可绕过防重”和“手动查询失败展示真实原因”分别通过，共47个不同场景已通过。最后身份变化定向5/5与query定向3/3，重叠不累计。请求全部隔离，不是实际GPU训练证据。
- 三份正式浏览器文件覆盖：成功/排队无需等待GPU、慢/失败刷新、4xx/5xx、网络断开、请求永挂超时、非法JSON、初始/finally异常、成功响应丢失、核验超时、重复点击、关闭重开、项目/草稿变化、准备失败/超时重试、保留配置、回调异常。新增用例断言真实DOM的按钮/aria-busy/阶段提示/无活动动画/POST次数，pageerror检查不产生未处理拒绝。
- 语法、py_compile、diff check通过；未执行全仓测试或真实训练。前后端业务码、202正式任务ID和查询同ID校验一致，未修改Worker或训练参数。
- 修改：原submit/hydration、app训练准备3处、app.py训练错误投影/锁错误、原样式及缓存版本、以上必要测试、VERSION及专项入口文档。当前提交将正常推送，准确SHA与CI回执在此节后续补充。

### 首推CI及守卫适配

代码提交 `b6fe43e8b9ca3ddcf843dd64839a705a342c3cd8` 已正常推送，远端从243858b9快进；该SHA启动49个原有Actions，未新建/扩展CI。首轮两个系统的device-probe contract及frontend Node发现同一旧守卫：必须字面匹配无signal的直接api请求。实际请求现由原withRequestDeadline约束，网络Owner未改变；更新原守卫以继续检查先开Modal再后台探测、缓存复用和过期重验，新增currentPreparation限制断言。单文件3/3通过。未删除测试或降低业务断言，不宣称首SHA全绿；后续修正SHA自身必须重新验收。

### 持久化与执行终态分离／第二次CI守卫

修正守卫提交 `6711b861f00554d47680db3f5ea0572ff76c52f5` 的Training Create First Open在Permanent guard阶段发现工作流还硬编码同一无signal请求。原检查改为精确检查带signal请求，并增加原Modal归属检查；其他CI条件/安全断言/触发范围不变。

新增3个真实Chrome先RED：网络结果未知后，按原ID查到FAILED/BLOCKED_BY_ENVIRONMENT/SUCCEEDED任务，旧验证器只接受创建时的队列/运行态，导致已持久化任务仍报UNKNOWN。仅正式仓库GET核验允许原TaskStatus持久状态；直接POST成功回执仍保持原严格状态约束，不把FAILED放宽成训练成功。TaskRuntime接收原状态，反馈只说明“创建已确认”，不伪造训练成功或仍排队。Node新增一个循环合同验证7种终态/阻塞状态仅在lookup可用；3个Chrome状态用例GREEN，query等6/6通过。原正式任务类型/项目/ID校验仍保留。

当前本地不同用例合计：Node90（原86+device3+lookup1），Python7，Chrome50（原47+3）；分批验证不重复累计。尚未将后续SHA CI标为通过。

---

## 2026-10-24｜P1 创建训练弹窗滚动修复（代码及隔离CI已验收）

基线b429f120b954455a29ca63c0d39ecbde1430c464 / VERSION42.24.382，已fetch0/0；5944及两份未跟踪训练模板测试保护。仅前端样式/必要交互与浏览器回归，不改变参数、母模型、划分、调度或后端，不生产部署。

用户合同：固定标题/底部按钮，中间唯一配置滚动区；标签上滚轮不中断外层操作；四模式/高级展开/异步标签/缩放与重开/窗口变化均可访问最后配置。不得增加important或全局滚轮拦截，不重建Modal。

审计风险：training-create-modal.css内旧/新三轮card高度与响应式覆盖，标签slot独立overflow+overscroll contain、body overflow auto、sticky footer同处滚动内容。先用真实Chrome轮事件复现，不能只凭源码确认全部根因。

最小设计：推荐CSS内收敛同类高度规则，原body/root作为受限flex框架，原train-create-layout为唯一滚动区，标签自然展开，原footer静态flex尾部占位；无JS搬节点或新增状态。备选保留嵌套滚动并移除contain仍有滚轮竞争；继续sticky+追加padding易随按钮高度失效，不采用。提交进度按真实证据更新。

计划：A 新增一个聚焦Playwright文件，指定五视口/四模式/实际wheel RED；B 原CSS收敛/唯一滚动及原footer，精确缓存；C 必要Chrome+现有Node，不跑Python全仓；D VERSION一次递增、更新本专项/接续、正常push并核验最终SHA CI。测试仅在隔离项目创建配置，不启动训练。状态A–D代码及隔离CI已验收；完整记录如下。

### 最终代码验收与接续回执

VERSION **42.24.383**，实现提交 **[f5ba61920644242973bec74056ac4e4ee9131bd0](https://github.com/jorsamj/aixunlianpingtai/commit/f5ba61920644242973bec74056ac4e4ee9131bd0)** 已普通推送长期分支。该准确SHA **36/36 Actions、99/99 Checks全部成功**，0失败/取消/跳过，证据：[代码Checks](https://github.com/jorsamj/aixunlianpingtai/commit/f5ba61920644242973bec74056ac4e4ee9131bd0/checks)。不引用旧SHA绿色。文档验收补提会产生新HEAD，交付前仍读取最终文档HEAD本身Checks，完整SHA以文件提交历史与交付报告定位，避免自引用循环；不因文档提交重复本地测试。

前后端业务规则保持：此次实际业务源码仅原创建弹窗CSS与index中的CSS缓存参数；没有修改app.py、static/app.js、训练/GT/Worker/Modal生命周期或新增事件处理。原参数、数据划分、母模型、训练创建与队列合同由原Owner继续管理。原标签/创建入口Chrome已回归；本轮浏览器只建立隔离项目并打开配置，新测试创建训练请求为0。没有生产部署、生产GT/素材/模型写入或GPU训练。

接续：本P1已完成，不再增加滚动补丁或新Modal/JS滚轮桥接。后续若有特定浏览器或真实触摸/缩放问题，先在tests/browser/training-create-scroll.spec.mjs加入准确场景，检查原CSS内单一layout滚动、grid行高与footer占位，再最小修改。保留root/body min-height:0与收敛dvh边界，不能恢复标签contain内滚动、sticky重叠或追加important。5944祖先和两份未跟踪模板测试保留，推送前核对远端无分叉；生产浏览器插件、触摸与真实缩放尚未实机验证。

### 真实根因、修复与验证

旧版1366×768/60标签：选自定义后，鼠标在标签区域连续45次真实wheel，标签滚到class_48一带，外层仍停在算法/素材上方，下方“配置更多专业参数”不可命中，原测试明确RED。原body overflow auto与标签slot overflow auto/overscroll contain形成双滚动；标签边界不能向外续滚。card高度在初始/1100/760/新版/790断点重复定义并混用vh/dvh，sticky footer位于内容内，进一步增加小屏不确定性；未查到创建弹窗上的wheel/touchmove preventDefault或透明提交遮罩为本次复现原因，不能把未证实项写成根因。

最终仅修改training-create-modal.css的创建弹窗布局：收敛card高度/dvh边界与body flex/min-height约束；原train-create-layout作为唯一有界滚动区；标签自然展开；原footer改为静态flex尾部，真实占位而不覆盖内容；头部不参与压缩。没有移动DOM、增加JS监听/新Modal/滚轮状态，styles.css全局与app.js均未修改。原文件important由65降至50，未新增important。首版单滚动改造曾在窄屏压缩Grid自动行高，标签溢出盖住后面的配置；通过实际elementFromPoint/scroll测量定位，补grid-auto-rows:max-content后恢复，不能将首版局部通过冒充最终完成。

测试夹具起初按精确标题查找而遗漏标题中的🔥，修正为原规范的标题匹配后，才取得上述有效滚轮RED；第一次新布局测试还将固定来源说明当成滚动区，已改为测量真实layout可视交集。未降低45次滚轮/实际命中/完整视口/原训练合同断言。

最终真实Chrome `node node_modules/@playwright/test/cli.js test tests/browser/training-create-scroll.spec.mjs --reporter=line`：**5/5通过，0失败/跳过，1.9分钟**。1920×1080、1366×768、1280×720、760×820、1093×614（1366×768在125%缩放下等效CSS可视区，不冒充实际浏览器缩放）逐一覆盖：首次/标签完成、从标签上滚到下方配置、第60标签、四模式、展开收起数据划分、专业参数应用返回、关闭重开、窗口再次缩小；标题/操作栏完整留在视口；最后只有train-create-layout一个真实滚动容器，pageerror为空，训练创建请求0。滚动只用mouse.wheel，不设置scrollTop或调用scrollIntoView；读scrollHeight/clientHeight用于检查Owner。原training-label-selector唯一生命周期/完整配置/唯一提交用例1/1通过（16.1秒），未修改该原用例。

Node最小相关组合：`node --test tests/frontend/zip-label-evidence-and-simple-training-ui.test.mjs tests/frontend/training-submit-validation.test.mjs tests/frontend/version-marker-owner.test.mjs`，27/27通过、0失败/跳过。源码仅CSS，无后端/参数/划分/母模型/Worker变动，未跑Python全仓或GPU训练；未删除原测试或降低原断言。新增滚轮文件接入已有Frontend Runtime Stabilization浏览器列表，不创建新工作流。

| 证据 | 修复前 | 修复后 |
|---|---|---|
| 鼠标在标签上滚轮 | 标签独立滚动封锁，最后配置不可命中 | 同一配置区滚动，标签和最后配置均可达 |
| 底部操作 | 内容内sticky，依赖滚动/高度覆盖 | flex尾部占位，完整可见，不盖输入 |
| 窄屏长标签 | 原行为受嵌套滚动影响；首版Grid压缩也实际失败 | 行高按内容排列，单列无交叠 |

[1366修复前截图](evidence/training-create-scroll-2026-10-24/before-1366x768.png) / [修复后截图](evidence/training-create-scroll-2026-10-24/after-1366x768.png)。图片均为隔离项目测试数据，非生产截图。

修改清单：static/training-create-modal.css、static/index.html（仅CSS cache4226355）、VERSION.txt（一次递增42.24.383）、tests/browser/training-create-scroll.spec.mjs、原frontend workflow列表、本专项及短接续入口/两张证据图。相关业务Owner、字段和请求合同不变。测试通过后普通提交/推送长期分支，代码准确CI已完成，回执见本节；文档最终HEAD仍单独核验。生产未部署，移动设备触摸/真实125%缩放及特殊浏览器插件仍未实机覆盖；本轮指定桌面Chrome等效视口均通过，不以CSS修改保证所有生产环境。

> 2026-10-23接续：测试遵循用户最新精简要求，仅本轮受影响合同及核心浏览器冒烟；新增存储/兼容任务以生命周期专项顶部为准，不混写业务Owner。

# 2026-10-22｜训练模式配置、创建流程与评测可信度综合治理

本轮唯一综合需求、设计、进度、问题与接续依据。历史四模式记录保留下文；场景/素材/标注既有实现证据继续引用[上一轮专项](SCENARIO_MODEL_EVALUATION_UI_GOVERNANCE_2026_10_22.md)，不复制建设或覆盖其验收口径。

## 当前基线与授权

2026-10-22已fetch长期分支`feature/external-algorithm-publishing`，远端/本地均`3cc331f2fa9b568ec27d59419d6b813a0aab7cb3`，VERSION42.24.377，工作树初始干净。可见会话列表同仓库活动仅当前会话；其余现存worktree保持原状，不声称已核验不可见会话。上一轮最终21/21 Actions、55/55 Checks、Chrome239/239回执已经实际核验，不代表本轮新代码通过。

用户本轮授权开发、隔离测试、文档、正常提交推送；禁止生产部署/生产数据或权重/GT修改/真实GPU训练/强推。不得以模拟检测、人工反馈替代正式评测。任务按P0→P1→P2，不用本轮P2提前改写上一轮未实施记录。

## 需求基线 A–E

- A1–A3：系统管理内训练模式配置；快速/完整默认/复杂/自定义；首训/迭代Epoch建议50/30、250/120、350/180，imgsz640/800/960；默认optimizer/precision/资源auto、GPU exclusive、Worker决议Batch/Workers/Cache；默认早停与目标阈值停止关闭。可编辑/默认/启停至少一模式/恢复初始模板/真实修改记录及revision，后端统一解析、完整参数验证和任务创建时不可变模板快照。960无硬件保证，复杂不等于更准确。
- B1–B6：原创建Modal内算法模型、素材/标签/划分、四模式、自动调度与可编辑优先级、真实参数摘要及固定底部；高级六分组，避免多层弹窗。审计全部epochs/imgsz/batch/workers/precision/amp/optimizer/LR/增强/资源/验证/停止参数的实际执行；不支持项不得虚假可编辑。早停显式开启才显示patience，auto optimizer不承诺手动LR生效，time与Epoch关系准确。可信负样本include_empty先核实再决定，不能盲改。独立Test禁止参与优化/阶段停止；正式测试在冻结模型后独立进行，训练/val/Test身份与SHA隔离；97%生产值原因NOT VERIFIED。保留仅点击开始训练完整准入、原Loading/防重/诊断/超时/迟到/真实任务。
- C1–C4：复用已验收成功模型资格、双模式/内联框/历史/人工反馈隔离/A-B与图表；增量核查本次要求的既有素材选择、指定可信独立冻结测试集发起评测。原报告查看不能冒充已支持重评。无可信GT不显示准确率，比较必须同基准协议/类别映射。
- D：复用原素材Owner工具/筛选/同DOM网格列表/稳定缩略图/坏图重试/选择与分页，仅发现确定偏差再修。
- E1–E3：复用原唯一右侧显式负样本审核、管理正式色、fit居中/缩放拖动/坐标准确与原保存CAS；不恢复已删除重复按钮或新增标注器。
- UI：本轮补1280×720，并复验1440×900、1920×1080；真实Chrome截图/按钮/滚动/无横向溢出，新增测试不替代原回归。闭源商用/离线/传递许可必须核验，Ultralytics授权独立列出。

## 最小设计与取舍（审计进行中）

1. 继续用TrainingDraft唯一草稿、TrainingSubmit唯一提交、原TrainReq→Durable TRAINING_PREPARE/TRAINING→Worker资源决议。新服务端训练模式配置成为唯一模板事实；浏览器仅消费其revision投影，删除竞争的硬编码默认与旧自定义参数优先级。创建时冻结模板revision、有效参数及来源，历史/排队任务执行不得重新读取最新模板。过期revision明确冲突并保留草稿，不静默换参数。
2. 配置优先沿用既有文件/持久配置设施，短跨进程锁+原子替换保存配置与修改记录为一份事实；没有适合的现有配置表时不为了模板单独建数据库。不把外部集成审计数据库挪为系统设置库。权限沿用平台现有真实登录与配置访问，不擅自新增RBAC/管理员白名单；实际入口合同待审计。
3. 预设切换不继承隐藏自定义参数，首训/迭代由后端可信算法版本判断，不能只信baseVersionId；手动覆盖只在明确自定义策略下生效并留证。auto资源仍在原Worker冻结，UI同时区分模板/提交/实际Runtime。后端最终验证不由前端显示替代。
4. 先追踪stage_gate_random_eval→data.yaml/val及最终Test链，未证实不指控97%数据泄漏。随机阶段样本必须准确注明来源/身份，必要时固定验证采样；独立Test仅模型冻结后使用。
5. 创建UI在原Owner/现有组件内收敛，原高级表单迁为同Modal分组面板，不叠新Modal管理器。不重写场景/素材/标注已验收实现；新评测入口必须先确认原TaskKind/Artifact/report合同，不能用无效按钮冒充功能。
6. 取舍：拒绝前端按钮独自决定预设、拒绝把所有请求值当可信模板、拒绝第二任务库/GT库、拒绝整套FiftyOne平台。优先原ECharts/Annotorious/SVG；候选license/离线/服务依赖审计后再决定，无价值不新增依赖。

## 分批任务与状态

| 编号 | 内容及Owner | 状态 | 证据/剩余/风险 |
|---|---|---|---|
| AUDIT | 当前代码/配置设施/参数/阶段val与Test/已有CDE | 进行中 | 基线3cc331f2；未运行新测试，97%原因未证实 |
| P0-01 | 模式权威配置、revision与快照；原TrainReq/Submit/Draft | 未开始 | 已发现rawConfig.imgsz覆盖预设、预设隐式阈值0.9/每10轮；先写RED |
| P0-02 | 阶段评估来源、数据/SHA隔离与负样本合同 | 进行中 | 已定位train_worker.py阶段入口，实际上游划分待完整核验 |
| P0-03 | 按需准入/Loading及场景成功资格增量验收 | 未开始 | 既有能力已验收，不重复重构；本轮新组合未执行 |
| P1-01 | 原训练创建Modal及高级分组/摘要/三视口 | 未开始 | 仍保持原Modal/Draft/Label/提交Owner |
| P1-02 | 管理入口、模板编辑/默认/启停/恢复/记录 | 未开始 | 持久设施及权限沿用审计后定案 |
| P1-03 | C指定可信基准/已有素材与D/E新增分辨率增量 | 未开始 | 不能把已有报告查看宣称指定集重评已实现 |
| P2-01 | 可视化/困难样本、组件审计、配置历史对比 | 未开始 | 原真实图表已具备；只补确定缺口，不建立外部平台 |
| FINAL | 相关Python/Node/Chrome/安全提交/最终SHA CI | 未开始 | VERSION377保持至实现完成按规范一次递增；新SHA CI未运行 |

### 可执行步骤与验收纪律

- [x] fetch实际远端/工作树/会话与旧专项基线；先持久化本轮需求。
- [ ] AUDIT完成后补准确调用链、文件边界、参数支持矩阵及风险结论。
- [ ] P0模式真实RED：完整模式不得遗留640、预设默认不得隐式停止、服务端不信任篡改Epoch/模式、模板revision CAS/历史冻结/至少一模式、非法值及引擎兼容；最小修复后重跑原training-submit/draft/scheduler-target与新API测试。
- [ ] P0数据链RED：独立Test从不被阶段val读取、重复SHA跨split拒绝、确认负样本按正式范围保留、缺失指标不触发停止；重跑原training_splits/evaluation/early_stopping/precision及on-demand相关测试。
- [ ] P1原创建与管理的真实DOM/隔离API/Chrome：四模式首训迭代、参数一致、模板修改与旧任务不变、慢/错/过期、防重、仅开始训练准入、三个视口截图及保留标签/母模型/GT冻结。
- [ ] CDE已验收功能不重做；按新增入口与1280视口补差距RED→GREEN，原SCN/MAT/ANN回归必须保留。
- [ ] P2只用真实原评测产物，配置历史对比不伪造效果；新组件若无必要不引入。
- [ ] 各阶段更新实际文件/Commit/测试数量及失败留痕；推送前fetch核并行，最终完整SHA逐一检查CI，生产能力另列NOT VERIFIED。

## 初始问题记录

| 问题 | 已证实事实 | 状态及下一步 |
|---|---|---|
| MODE-IMG | training-submit.js buildTrainingEngineParameters用rawConfig.imgsz优先于preset，模式切换可保留旧图尺寸 | 进行中；真实函数RED后修唯一参数解析 |
| MODE-STOP | 预设config无条件stop_threshold=.90/eval_interval=10，与用户默认关闭冲突 | 进行中；真实函数RED及后端模板默认一并治理 |
| MODE-SERVER | validate_train_request目前只验证模式资源策略，不负责权威预设参数解析 | 进行中；审计唯一正式创建入口并冻结真实revision |
| DATA-STAGE | stage_gate_random_eval按epoch改变seed并用images/val；其与正式Test的上游语义尚待审计 | 待核验；未确认生产泄漏，不能宣称已修复 |

生产/真实GPU/97%数据的实测、模板实际效果、闭源商用既有Ultralytics授权均NOT VERIFIED。

---

## 2026-10-10｜训练创建布局与标签首屏可见（42.24.346）

- 用户反馈 868px 小窗和单列堆叠使重要训练标签沉底；本次仅布局调整，保留 canonical owner。
- 宽屏：最大 1280px、94dvh，算法概要跨栏，素材左/正式标签右，训练模式位于素材下方。标签面板优先展示并独立滚动，可继续按原逻辑搜索、选择、继承。
- <=1050px：算法 → 素材 → 标签 → 训练模式；页尾提交按钮依旧固定。
- 真实 Chrome 回归增加宽屏并排、窄屏先标签后模式的几何断言；仅精确 HEAD 的实际检查成功才视为 CI 通过。

## 2026-10-10｜四模式训练创建 CI 修复（42.24.345，待全量复验）

- 实际核对基线 `2e01bde1ee362060c23a82be1fad2c5e44341bf3` / `42.24.344` 的 6 个失败 Workflow、对应失败 Job 的原始日志；Remote Material Import 两次触发为同一缓存键测试根因。
- Training Create First Open：训练弹窗 Browser 测试使用已删除的全局高级展开按钮和旧弹窗标题；改为现有“创建训练任务”及数据划分原生 disclosure，训练素材/固定 Benchmark/标签规则仍继续检查。
- Frontend Runtime Stabilization：对应旧标题、旧高级配置与创建提交文案、TrainingDraft 写入顺序的断言漂移，已按可见真 UI 更新；导航与标签的真实操作仍须 Chrome 复验。
- Training Task Visibility / Algorithm SQL Store：同一 `four modes freeze only training semantics` 前端测试揭露生产链缺陷：`trainingDraftToRequest` 通过 `createTrainingDraft` 把历史 `gpuPolicy:auto` 覆盖掉 builder 的 `exclusive`；现在四模式规范化统一强制独占。保留中央 TaskScheduler、GPU Reservation 和 Worker 运行前真实资源决议。
- Remote Material Import 两次：原测试把 `app.js?v=42.25.333` 当成永远不变的字面缓存版本；现在验证版本不回退到旧修复点，同时入口缓存版本实际升级至 `42.25.345`。
- 自定义模式取消“兼容自动隔离”选项；普通模式不显示 Batch/Workers 专业设置；标签搜索、勾选、正式 GT、首次母模型、续训有效版本继承、60/20/20 比例以及单一 TrainingSubmit Owner 均保留。
- 本次只修改对应最小生产文件、前端测试、Browser 测试和现有文档，不另建 Owner、不删减安全测试；最新精确 HEAD 的全量 Linux/Windows/Chrome CI 仍待核验，真实 NVIDIA 同卡阻塞/双卡并发、OSS、Agent、10k/20k 素材 UAT 仍需现场执行。**不合并 main、tag、release、部署生产。**

# 2026-10-10｜训练创建弹窗四模式极简改造与标签合同

> 开发分支：`feature/external-algorithm-publishing`
> 版本：`42.24.344`
> 状态：代码和定向测试已提交。GitHub Actions 当前 HEAD 以及真实浏览器/生产 NVIDIA GPU 验收须以实际结果为准。本轮未合并 main、未 tag/release、未部署生产。

## 一、需求及范围

本批仅对“创建训练任务”进行视觉与表单交互收敛，不重新实现任何 Dataset/Label/Annotation/Task/Training owner：

- 弹窗标题“创建训练任务”，算法名称只在算法区展示一次；算法身份不可编辑；仅任务优先级可改。
- 首次训练母模型仍从已就绪的 `.pt` 中选择，续训锁定当前有效版本的训练权重；任务 ID 由现有模块生成，只在内部控件保留兼容，不显示给普通用户。
- 训练素材、数据划分、标签合同仍沿用精确 image IDs、既有 train/val/test split、canonical `TrainingLabelRuntime` 和独立 Benchmark 复用流程。弹窗末尾显示独立“训练标签”区域，带搜索、原本的正式标签复选框、既有继承/新增选择状态；`train_labels` 仍必须来自显式选择；首次训练无显式标签时禁止提交；迭代由服务器维护上一有效版本标签。
- 默认显示四种训练模式：快速 / 完整 / 复杂 / 自定义；模式在已有 `TrainingDraftRuntime` 唯一草稿中保存为 `trainingMode`，下发 `training_mode`，不创建第二套表单 owner、请求 owner 或轮询。
- 非自定义模式只展示训练轮次、图片尺寸、GPU 独占及“启动前自动适配”状态；自定义时才显示 CPU/GPU、Batch、Workers、Cache、Precision 以及已有完整专业参数设置按钮。
- modal 宽度 868px 以内，普通内容字体 14～20px，标签全宽、多列、底部固定创建按钮，兼容 1366×768 和窄屏。

## 二、模式合同（首次 / 有效上一版本续训）

| 模式 | Epoch 首训/续训 | 图片尺寸 | 资源策略 | 其他 |
|---|---|---|---|---|
| 快速训练 | 30 / 20 | 640 | Auto + Performance | GPU Exclusive，Worker 启动前冻结 |
| 完整训练（默认） | 150 / 80 | 640 | Auto + Performance | GPU Exclusive，Worker 启动前冻结 |
| 复杂训练 | 250 / 150 | 800 | Auto + Performance | GPU Exclusive，Worker 启动前冻结；确保硬件兼容 |
| 自定义配置 | 显式用户设置 | 显式用户设置 | Manual | Batch/Workers/Cache 等请求保持原值；不满足预算 fail-closed |

- 模式的 Epoch、imgsz 由唯一 `static/modules/training-submit.js:trainingModePreset` 给出；非自定义预设从提交参数中过滤掉历史手动高级配置，防止切换后隐藏参数影响训练。
- `static/modules/training-draft.js` 是 draft / exact material IDs / explicit labels / split / priority 的唯一 Owner；切换非自定义时清除历史 Batch/Workers/Cache override，避免隐形手动设置。
- 现有 `platform_core/training_metrics.py` 仍是最终 Auto 资源决议 Owner，在真实 GPU 分配及节点条件核验后冻结 Batch/Workers/Cache。自定义使用原有 strict manual validator，训练时不做暗中调小。
- `app.py.TrainReq.training_mode` 为可选字段，对旧 API 调用继续兼容；新四模式的预设只允许 auto，自定义只允许 manual。后台已有 train_labels、model、priority、split、安全 preflight、版本冻结和目标评测链不变。

## 三、修改文件

- `static/app.js`：沿用 `openTrainingCreateDialog429` / `renderSplit` / `TrainingDraftRuntime`，重构弹窗 DOM 为简洁纵向布局；四模式单选；仅自定义展示资源和高级表单；保留正式训练标签容器 `trainUiLabelSlot`，通过 `trainingLabelContractPanel` 原样挂载，不复刻标签业务逻辑。
- `static/training-create-modal.css`：仅 modal 作用域内的响应式布局、字号、标签多列、模式卡及底部固定操作区。
- `static/modules/training-draft.js`：草稿单一字段 `trainingMode`，预设清理隐藏手动资源参数，保留无模式字段的历史 manual/auto 兼容。
- `static/modules/training-submit.js`：唯一训练模式预设映射；submit 仍由 `TrainingSubmitRuntime` 统一处理。
- `app.py`：可选 `training_mode` 类型及 Auto/Manual 预设硬约束。
- 定向测试：`tests/frontend/training-draft.test.mjs`、`tests/frontend/training-submit.test.mjs`、`tests/frontend/zip-label-evidence-and-simple-training-ui.test.mjs`、`tests/unit/test_training_scheduler_target.py`、`tests/browser/training-create-first-open.spec.mjs`、`tests/browser/training-label-selector.spec.mjs`。

## 四、已执行 / 待执行

- 已执行：JS 源码 V8 语法验证；纯逻辑模拟四种模式初训/续训的参数、manual 与 auto 独占隔离、首次训练无标签拒绝提交、旧 manual 草稿兼容。以上仅限静态/纯函数验证，不是浏览器或 Worker 真机测试。
- GitHub Actions exact-HEAD 全绿：**PENDING**。
- Real Chrome：创建→首次母模型→选择素材→标签勾选→划分比例→模式切换→自定义高级参数→创建 durable task→关闭弹窗，以及续训固定权重/既有标签与 benchmark 复用：**PENDING**。
- 目标训练节点上的 Batch / Workers / Cache 真机资源冻结与 GPU 独占：沿用上一批 `docs/TRAINING_PERFORMANCE_EXCLUSIVE_2026_10_10.md` 的硬件验收 OPEN 条目。

**必须保证标签、素材和任务身份真实合同；不得为了 UI 简化通过降低/删除断言换绿灯。**

### 2026-10-23中断后核验

HEAD仍3cc331f2，VERSION377。子任务额度中断，后端模板和场景新增入口未完成；tests/unit/test_training_modes.py及frontend/training-mode-policy仅为待实现RED，不可宣称GREEN。train_worker已接续阶段来源与patience=0修复，定向两个文件实际29通过/5既有warnings（1.68s，C:/tmp/training-stage-focused-green.log）；之后追加身份核验期间变化拒绝，受影响两个文件再次29通过（1.64s），不重复执行无变更全仓测试。缓存仅trainer内身份投影，不建立第二持久索引；不变来源不重复全量SHA。正式负样本include_emptyFalse合同保持，独立Test未发现用于阶段停止。

2026-10-23收口：验证身份缓存补绑定data.yaml路径，最后仅重跑受影响cache计数用例1通过（0.19s），py_compile/diff检查通过。该阶段不涉及UI，无须重复Chrome。整体模板/UI/存储迁移未完成，不宣称本轮CI或生产验收。
