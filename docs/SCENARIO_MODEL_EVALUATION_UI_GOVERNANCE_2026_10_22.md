# 场景算法准确性工作台、素材页及标注UI治理（2026-10-22）

> 本轮唯一综合需求/进度/问题与接续依据。既有VNext、素材性能与Annotorious文档保留历史，仅增加入口，不复制本轮进度。基线c376be7d5d54cca838dc8456ae2e6906815a5335 / VERSION42.24.376；2026-10-22已重新fetch，远端与本地一致、长期工作树干净。应用会话列表查询超时，未宣称已读取全部其他会话；现存其他worktree不动，推送前再次核验远端与差异。

## 已确认需求和边界

用户授权本轮前后端代码、隔离测试、必要文档及长期feature/external-algorithm-publishing正常提交推送。禁止生产部署、素材/GT/训练数据/权重修改、真实GPU训练、强推及覆盖其他开发。P2重新评测/新泄漏分析/大图组件/导出不在本轮。

- 场景P0：仅真正成功训练且有已验证产物和可信任务/算法版本关联的模型；前后端同时校验，不改其他页面通用模型能力；算法→有效版本、默认最新，可选第二模型。准确性评测默认最近可信独立报告，无报告明确为空；快速单/多/文件夹检测无GT不显示准确率/TP/FP/FN。首个完成结果直接进入三栏工作台，缩略图/列表、预测/正式GT图层、类别/置信度/缩放/错误筛选/框详情。原任务/队列/轮询/批次历史/人工反馈Owner保留，历史收纳二级区域，失败反馈/防重/迟到隔离。
- 素材UI独立P0：统一统计、上传/ZIP、操作与筛选层级；网格/列表/缩略图/多标签/长名称/选择态/分页；稳定占位、真实坏图和重试；已有预览、清洗、异常审核等弹窗视觉一致，保留API、懒加载、分页与所有业务操作。1920×1080/1440×900/1366×768前后截图及交互，单独提交。
- 标注UI独立P0：删除顶部重复ann420ConfirmEmpty及失效绑定，右侧审核为唯一显式确认入口；空图需用户明确选择审核类别，confirmed_empty/annotation_scope/GT版本/负样本合同保留。颜色以正式标签code/稳定身份及管理颜色为唯一来源，选中/重载/改色一致；fit按缩放尺寸居中横竖方图，切换/适应重新居中、resize合理且不无故重置手动视角。工具栏/三栏/类别对象审核清楚，三桌面分辨率、画改删/保存/撤销重做/快捷键/加载错误及前后截图，单独提交。
- 场景P1仅P0验收后：复用真实ECharts混淆矩阵点击→样本、类别PR/AP、阈值曲线、TP/FP/FN与图层/框联动、A/B同图同步。未覆盖类显示未覆盖；比较必须同可信基准/指标协议/兼容映射，否则禁止提升百分比。

## 当前代码核验与最小设计

1. static/app.js:8243原v64场景Owner包含文件队列、批次及弹窗；detectionModels64放行builtin且best.pt名字兜底。app.py:13060 _testable_version_pt_path通用模型能力只核PT存在/非last，不能代表新场景资格。新增场景专用合同复用任务/产物校验，通用列表维持兼容，不能只信浏览器flag。PARTIAL_SUCCESS必须审计真实“训练产物已正式提交、随后独立评测失败”事实，不扩展为任意失败checkpoint。
2. 原v61 DEPLOYMENT_TEST、PollRegistry及v64 detection-batches继续唯一任务/结果Owner；页面展示代码从大型app.js原位迁出到聚焦模块，原benchPredictOne/接口/轮询复用，禁止新控制器/数据库或复制训练素材。
3. 原training_evaluation.py及独立评测API已有冻结身份、TP/FP/FN、空间混淆、阈值采样、问题图片及严格comparison；新准确性工作区按需加载原版本/报告/验证图片，历史缺证据明确降级。不用快检预测或人工主观复核反推正式指标。
4. 素材实际Owner为material-pagination-runtime.js serverPagedDatasets + app.js card412增量卡片；现卡片/预览无统一坏图处理。使用原Owner与受限作用域CSS，不叠大量important、不改上传/删除/清洗控制器。
5. Annotorious原Editor只管交互，保存/审核在原GT内核；fit目前tx=ty=0，顶部重复确认与右侧审核并存。修正原Editor定位/颜色与原UI，拒绝第二套标注器或自动确认负样本。

替代方案：不重写评测引擎/任务库、不部署FiftyOne/CVAT；不以隐藏母模型按钮替代后端校验；不把旧详情弹窗再包一层；不以固定红框或!important掩盖身份/样式问题。保留旧独立评测弹窗作为辅助完整报告，不强迫普通图片核验打开弹窗。

## 阶段计划与任务状态

每子任务先RED→最小修改→GREEN→规格/质量审查→独立提交。P0全部可验收后实施P1。状态仅未开始/进行中/已完成待验收/已验收/阻塞。

| 任务 | 优先级与模块 | 状态 | 已完成/剩余与风险 | 提交/验收 |
|---|---|---|---|---|
| SCN-A 现有合同及重复Owner审计 | P0 app.py/algorithms/training_evaluation/inference_tasks | 已验收 | 已确认资格及UI缺口；补完整产物/任务/冻结API映射 | 基线c376be7d，未新增提交 |
| SCN-01 正式模型资格及后端强制 | P0 原test_models与v61/Worker/Agent | 已完成待验收 | 专用资格、来源/字节/持久分类复验完成；通用目录不改；固有TOCTOU限制见记录 | 1f606d30；场景54、相关145通过；最终CI待验 |
| SCN-02 两模式和内联检测工作台 | P0 原v64 UI/原任务API | 已完成待验收 | 原Task/Poll/历史/反馈复用，项目/迟到/未知锁与真实SVG回归通过 | 1f606d30；Chrome11通过，最终CI待验 |
| MAT-UI 素材视觉与必要反馈 | 独立P0 原素材Owner/CSS | 已完成待验收 | grid/list同DOM、原比例媒体面、坏图重试及三视口截图；原GT/API不改 | 13c70368；Node28/Chrome4及原治理/分页/上传通过；最终CI待验 |
| ANN-UI 原标注交互规范 | 独立P0 原Editor/review/NegativeSample | 已完成待验收 | 唯一显式审核、正式色即时同步、居中/手动视角、坏图原重试；GT/CAS保留 | b8d04f04；原workbench23、最终14/15组合通过；最终CI待验 |
| SCN-03 真实指标与交互分析 | P1 原reports/ECharts/evaluation合同 | 已完成待验收 | 原真实matrix/curves、未覆盖类、只读诊断、同基准pp及同图AB，组件单URL/单Owner | 新Chrome12及AB同步补测通过；最终CI待验 |
| SCN-F 最终回归、版本及精确CI | P0/P1 原工作流/接续文档 | 进行中 | VERSION377；Node1295/Python212通过，完整Chrome352正在执行；原CI补新用例 | 最终推送SHA/全部Actions与Checks待验 |

### 执行检查清单

- [x] 审计原资格/TaskRepository/ModelArtifact/Version关系，记录可复用函数；建立前后端非法资格RED。
- [x] 专用模型范围只从服务端已验证成果投影；原v61受场景合同约束，Worker执行前继续核验来源；动态API测合法/伪造/跨项目/漂移/历史。
- [x] 原v64展示迁出并安装同一Owner；原api与benchPredictOne复用；两模式、选择/内联图片/列表/历史、取消/失效/防重与无GT明确呈现；Node真实DOM与Chrome走原任务链。
- [x] 素材坏图、间距/网格列表/toolbar及相关弹窗在原Owner修复；先截图/失败断言，后3分辨率回归，独立提交。
- [x] 标注先fit/颜色/重复确认RED，修原Editor与审核；3分辨率截图与GT保存/并发/负样本/快捷键回归，独立提交。
- [ ] P0实际通过后接真实报告P1：身份、原矩阵/曲线、错误样本/GT层、版本同基准比较；任何缺失不造值，样本按需分页/取消。
- [ ] 记录实际测试命令/通过失败跳过、RED修复与遗留；一次版本升级、必要缓存与守卫同步；更新AGENTS及四份handoff，推送后最终SHA逐条CI核验。

## 开源与许可证核验

已读取用户给定Supervision官方仓库与Benchmark文档（2026-10-22）。官方仓库标MIT，评测指导包含显式类别重映射、IoU及mAP/F1定义；不能据此宣称与本仓宏平均/阈值/插值方式相同。先对照现有scorer与确定性隔离fixtures，未确认需要前不加生产依赖。既有ECharts/Annotorious本地制品及实际LICENSE继续核查；不增加CDN、打包体系或云依赖。Ultralytics AGPL/企业许可独立列出，MIT评测库不会消除原Ultralytics许可义务。官方来源：https://github.com/roboflow/supervision 、https://supervision.roboflow.com/latest/how_to/benchmark_a_model/ 。

## 生产与接续边界

本轮全部测试仅隔离数据与本地/CI，不运行真实GPU训练，不改生产模型或GT。旧历史缺模型产物/冻结图/报告字段时明确不可验证，不补造历史事实。新会话先读本文、原Owner和真实测试证据，不能凭聊天或旧绿色SHA宣布完成；不得将本轮与之前按需准入、Uppy/TaskCenter已验收成果混改。


## 2026-10-22 开发实绩（未提交、未最终验收）

### 审计和SCN-01

- 原模型条件已通过真实API RED复现：model_scope=scenario仍返回4个混合模型而非1个正式成果。新增场景隔离fixture走真实TrainingHandler finalizer与TaskRepository；错误YAML/schema fixture两次未当作业务RED。
- 当前原GET test_models增加model_scope=scenario，原v61表单同名范围；默认通用功能保留。platform_core/scenario_models.py核本地完成事实/结果引用/版本lineage，远程则用原generation committed manifest、training-models/upload确认，不要求不存在的服务端job.json、不造副本。PARTIAL_SUCCESS仅有明确独立盲测失败、训练成果正式提交时允许；validation_error等未证实成功不放行，不改别处训练次数定义。
- 初始限定65通过（场景41/原deployment+Worker+rollback+恢复24）；排队来源/framework/完成状态漂移3项、staging漂移4项、同一task冒名多个version均真实RED→GREEN。旧恢复测试发现冻结label_schema空但YAML fire不符，单例确认原training_tasks未变，只补隔离fixture正式schema/空Test列表，未放松准入或旧恢复断言。
- 审查又发现两个确定P1，仍在修复，不能写成已验收：远程Agent payload领取/刷新绕过场景验证；删除可变request.model_scope使local verifier直接退出。方向是在原远程Owner复核，并以TaskRecord受保护payload_ref保留场景身份，不新建数据库或重复事实；补真实Agent链RED。大权重列表重复全hash读放大也纳入审查，执行时不以缓存替代新鲜验证。

### SCN-02

- 原v64展示从static/app.js原位迁至static/modules/quality-detection-workbench.js，原benchPredictOne/v61/PollRegistry/v64批次仍为唯一执行与持久化链。static/modules/scenario-evaluation.js仅只读投影，不重算正式指标。
- 默认准确性评测；算法→版本、只主动添加B；若所选版本无可信报告，明确标出该算法最近可信报告的真实版本，不把旧报告归于新模型。缺任务/模型/冻结Benchmark/协议/图片数量证据显示尚未独立评测。快速检测不计算准确率/TPFPFN；独立报告原完整入口保留。
- 真实Chrome原工作台RED为缺少准确性评测tab，三个桌面before截图C:/tmp/scenario-before-*.png。原有A/B、A-only、B-only、folder、人工复核、历史和稳定加载次数流程改为内联核验，1/1 GREEN（17.4s，C:/tmp/scenario-workbench-p0-green3.log）；还不是所有P0验收，新case正在追加。
- Node动态只读投影5项通过，缺协议ID/零测试图片误作可信的新增RED已修正；迁出Owner与原缓存/任务/反馈守卫更新后定向40/40通过（C:/tmp/scenario-node-p0-green.log）。未删除断言来让测试通过，原“放行母模型/best文件名”守卫按用户新合同退役。
- 补原创建30s截止与未知结果查询锁、固定run/project/models后原执行；普通进度只更新文本，不频繁重建操作按钮。正在验项目切换/历史迟到/坏图/真实SVG可见性；截图发现SVG hidden属性可能未移除，已交Chrome建立RED，尚未宣称修复。

### ANN-UI内核准备（独立提交待整体完成）

- 原24项新增5个真实RED：无颜色解析helper、换图未fit、tx/ty未居中、无ResizeObserver、code/class冲突仍用正式色。原Editor最小修复后相关7文件Node70/70通过。
- annotation-geometry-adapter.js只读annotationColor(box,labels)严格code与显式class身份，未知/冲突/停用/非法色中性#64748b，文字不猜类别；缺class_id的只读预测按合法code。Annotorious官方3.9.5实际将style写内联，使用原setStyle同步schema，无!important。
- Editor初始/切图/fit完整居中，auto-fit才响应resize，wheel/pan/100保留手动视角，destroy断开Observer。GT保存/负样本/CAS不改。
- 顶部重复按钮/右侧审核/各app颜色投影/弹窗布局与三视口Chrome尚未改完；不能把内核70通过当整个ANN-UI完成。MAT-UI仍待实施；P1尚未开始。

### SCN P0追加证据与审查修复

- 新增真实Chrome9/9通过（47.7s，含真实30s Pending截止、500重试、旧版本/受控项目生命周期/历史迟到、原TaskPoller排队→运行→完成、冻结坏图/尺寸保护、24+1分页）；原批量工作台1/1保留A/B等旧断言并新增SVG/rect实际可见性。受控fixture仅UI合同，不是生产或GPU准确率证据。三视口截图C:/tmp/scenario-evidence-trusted-{1920,1440,1366}.png。
- 确定SVG可见性RED为SVGElement.hidden属性赋值不移除HTML hidden属性，已原位removeAttribute，实际框可见GREEN；原viewBox测试不足，已增强。小图片fit使用完整视口比例，保持等比。
- 追加审查发现未知创建后，不完整批次查询/切换其他历史能解除锁。新增真实原函数VM执行RED1失败2通过，最小修复在原run标记正在提交side、仅原批次对应item+side取得task_id方可解除未知状态；无新增POST或恢复Owner。原函数/投影/缓存/Owner定向Node43/43通过，追加Chrome尚待排队复验。未知项不计已完成，停止只停止后续图片，不谎称已提交后端任务被取消。
- MAT首轮相关Node28/28通过，原素材Owner grid/list共享同卡片与选择集、contain媒体平面/失败重试、新scoped CSS已落盘；Chrome未最终完成。ANN顶部重复确认Chrome RED已复现，内核居中在3视口先通过，UI清理中。所有以上尚未提交、未最终CI。

### 计算与组件审计补证

- 原training_evaluation scorer31/31单元测试通过（C:/tmp/scenario-evaluation-scorer-baseline.log）：同类置信度优先一对一IoU匹配、跨类混淆协议、无GT类别、真实21个阈值采样、冻结身份/模型与基准比较等原合同保持。不是Supervision计算等价证明，本轮尚无新增Python依赖理由。AP算法不可不经验证替换。
- 已读仓库static/vendor/echarts/LICENSE（Apache-2.0）和Annotorious NOTICE/实际依赖许可目录（官方3.9.5 BSD-3-Clause及Svelte MIT等），沿用已离线制品和原许可清单；本轮无新增打包/CDN/评测库。Ultralytics许可仍单独适用，闭源分发/使用需依实际AGPL或企业授权条件核验，不被其他MIT/BSD许可替代。
- 全Node中途快照1251项有6个失败，属于并行开发未最终完成与原源码位置守卫过时，不宣称全绿：5个SCN导航/项目缓存/展示迁出守卫准确更新至新单Owner位置，限定66/66通过；ANN唯一审核守卫仍在随该P0修改。最终串行全量尚待执行。

### SCN-01后端P1修复后的真实验证

- 初次独立审查两个P1已通过真实Agent链RED8失败/1合法通过复现；在原TaskRecord.payload_ref保存scenario/request.json身份，任何持久分类/冻结标记存在必须完整重验，scope/两字段删除均不能降级。Agent start/读取payload（含finish与confirmed恢复）及原RemoteTransport mint/refresh/prepare/confirm同一核验函数；未另建权限、任务和传输Owner。
- 原SCN54项（本轮新增13）及原deployment/Worker/rollback/完成恢复/RemoteTransport/Agent组合145 passed、5 warnings、62.02s；py_compile通过，未真实OSS/Agent硬件/GPU运行。最终独立复核与最终SHA CI仍待完成。
- 列表重复hash真实RED后，最多256项/5秒stat fingerprint摘要缓存仅服务目录；TaskRecord/Version每次新读，提交/staging/Worker/Agent/remote始终fresh hash。单机可变路径在最后校验与进程打开之间仍有固有TOCTOU窗口，未宣称彻底消除，也未为规避而复制权重；远程原下载合同继续SHA/size验证。

### MAT与ANN阶段证据（未最终验收）

- MAT新Node RED3→GREEN3，相关28/28。baseline与current Chrome各4/4（1920、1440、1366、375）；16张网格/列表/详情及before证据保存在TEMP/codex-mat-p0-evidence，待归档仓库。列表纯展示切换保持原卡片DOM/选择/分页，零新增请求；失败图片与所有覆盖框隐藏，重试恢复。原素材API/治理不改。
- 原素材组合29项当时25通过4失败，治理8、分页5、65张上传1和新MAT4通过；4失败为ANN退役顶部按钮/新增正式颜色控件后的旧定位，交ANN准确改新唯一审核合同，不能当作29全绿。
- ANN Chrome已先复现顶部重复按钮RED，三视口before C:/tmp/annotation-ui-before-*.png；右侧唯一审核、正式颜色投影、单scoped stylesheet（清旧annotation-only !important补丁）、原保存后media plane兼容已实施。相关Node66/66通过，新Chrome与原标注/素材组合仍在执行。P1尚未实施。

### 独立复核新增问题及关闭过程（真实缺口不隐藏）

- SCN-01独立复核重新跑场景54/54通过，两个远程/降级P1闭合。
- 原extras同项目不同用途test_models投影共用state.testModels，延迟顺序可双向污染通用/scenario目录。新增VM执行原extras真实RED2失败1通过后，原加载Owner将场景投影存state.scenarioTestModels，通用state.testModels保持；非第二任务/数据库/请求Owner。3/3 GREEN，跨项目旧响应原guard保持。
- 原openBenchFeedback64迟到跨项目会写lastOnlinePrediction并打开反馈，若新detail存在还可能误关新modal。原函数生命周期/原modal/row/project/导航token复核最小修复，VM真实RED6→GREEN8，相关27/27；原提交Owner和反馈数据隔离保持。
- 补审又发现无模型刷新时reportLoading旧true残留、旧history返回覆盖期间新run；已经安排原Owner RED→GREEN，未借“基本通过”掩盖。反馈POST的有界等待也在补验。
- ANN真实Chrome新增RED：小图fit超过400%后放大反向缩小；旧zoom绝对上限改为当前/fit相容上限，Node14通过1失败→15/15，Chrome原方向断言GREEN。坏图片decode缓存重试失效另有真实RED，原retry action仅重载当前失败src并重新初始化原editor，保持GT/dirty/版本身份；新ChromeGREEN。
- MAT原组合4个退役ANN定位已准确迁移右侧唯一审核与正式色，新ANN4+素材11组合15/15通过；仍在最后生命周期回归。标签管理保存后原已打开editor显式sync，无需用户额外选类才更新。所有结果为隔离本地合同，不代表生产现场。

### P0本地验收门槛（进入P1前）

- 最后合并代码全Node1273/1273通过、0失败0跳过；SCN新10+原批量1 Chrome11/11通过（1.2m），包含最后unknown不完整查询锁及正式SVG可见；SCN后端145/145与独立重跑54/54通过。原评测scorer31/31、冻结图片API36/36通过。
- ANN新4+原生命周期10最终14/14通过；新4+原素材流程11最终15/15通过，原标注工作台23项首轮全部通过；MAT新4/4 current及before4/4，素材治理8/分页5/上传1通过。统计按独立组合记录，不把重叠case重复加成唯一测试数。
- 最后反馈deadline/无模型loading/历史覆盖新增原函数执行RED3失败→相关34/34通过，5ms真实原deadline不重试；原project/sequence/unknown守卫保留。
- 三P0已达到隔离本地实现及回归门槛，开始分别阶段提交；最终整体CI/生产仍未验收。P1接着实施真实ECharts、原矩阵/曲线和严格同基准A/B，不启用P2。截图证据将存docs/evidence/scenario-ui-2026-10-22，均明确隔离fixtures/controlled推理合同，不是生产准确率。

### 阶段提交

- SCN P0：1f606d30b75eb1245224ce5fc0dd9df5b42f006b，本地独立提交正式模型资格、原Owner工作台、迟到/未知锁与真实回归；未推送/未最终CI，不宣称阶段SHA远端绿色。
- MAT P0：独立提交准备，包含原卡片/详情及保存后的media-plane兼容，未混入ANN标签/确认合同。三桌面before/grid/list/detail截图已归档docs/evidence/scenario-ui-2026-10-22。

- MAT独立提交13c7036898c00ea1b5626986ac0115a5d6644c69，原素材/GT/API不改，最终整体CI尚待。
- ANN独立提交准备：包含唯一右侧显式审核、正式颜色及管理保存即时sync、fit居中/resize保持手动视角/小图zoom方向、原坏图retry与GT版本保护；清除旧annotation-only覆盖，三桌面before/after六图已归档。最终全Node1273/1273与ANN相关实际Chrome组合证据如上，未借旧green。

### P1实现、审查与真实回归（最终CI待验）

- ANN独立提交b8d04f0467d0eff8070413a7142da93ecc0b8c57，三P0本地门槛通过后才进入P1；最新fetch远端仍c376be7d，其他工作树不动。
- P1 Chrome首RED为可信报告analysis空白；reports新增图表接口先7个RED，再扩展新10/原29共39通过。纯诊断5通过9失败→16/16，类别ID0/同名不同ID不串；TP/FP/FN只用正式matched/count，错类只用原矩阵protocol+images，低置信真实<0.5，定位仅同类unmatched0<IoU<0.5只读待复核，不变更正式评测值。
- 原reports.js单loader/registry/ResizeObserver/dispose扩展至evaluationChartGroups/mountEvaluationCharts；最多前20类+背景的实际cell矩阵、当前有GT类Confidence与PR最多21真实采样，非AP积分曲线，缺点不补0。未覆盖类表格明确未覆盖，不绘虚假曲线。表格100类/页，原错误证据24图/页/最多200图及每层120框的历史边界明确，不把保留样本当全测试集。
- 严格A/B只对同算法不同成功版本，原GET evaluation/compare复核基准/协议/映射，回执source/current版本必须对应；仅展示服务端delta的pp，不计算相对提升百分比。不同算法可用快检同图，不能假作同基准提升。B证据需image_id/SHA/原始尺寸都一致；缺图/未保留正确图明确缺证据，不补空框。
- P1首Chrome5通过5失败：同页返回质量概览未dispose为实际RED，已在原tab Owner显式deactivate修复；其余失败为新夹具启动未await uiReady或对缺席节点用了文字断言，修为真实启动等待与count0（不放松业务）。fresh新10/10通过；框显示层过滤后保留原index，关GT再点预测仍对应预测详情。
- 独立审查确认B图URI版本虽正确但expected_evaluation_id误用A的ID（原API严格409，旧fixture无条件200掩盖）。各panel带自身evaluation已修；强化图片route严格评测ID/image_id/SHA不符409，fresh严格AB1/1通过，不伪称此项Chrome先RED。
- 独立审查还确认旧training-recovery-runtime import reports旧query使两个ESM注册表；新增单URL测试真实10通过1失败→修后相关45/45通过，同步原recovery缓存引用及既有守卫，原恢复业务不变。reports额外loader失败/空报告迟到/脱离DOM及观察器泄漏RED已修。
- 主入口静态缓存统一423、模块缓存按改动更新，正式版本仅本轮升级一次42.24.377。最终新增12个P1 Chrome及全量Node/Chrome/相关Python/CI仍在执行，不能提前宣布全部完成。

### Ultralytics许可单独说明

本轮沿用ECharts Apache-2.0、Annotorious BSD-3-Clause既有离线制品，无新增Supervision生产依赖。2026-10-22再次核验[Ultralytics官方许可说明](https://www.ultralytics.com/license)及[正式条款](https://www.ultralytics.com/legal/agpl-3-0-software-license)：其AGPL/商业许可适用性应按实际软件、模型及既有授权核验；项目未提供企业授权证明，本轮不宣称闭源部署已获许可。MIT评测库不解决此独立义务，也不改变现有Ultralytics使用事实。

### 最后本地验收执行记录（进行中）

- 新P1 Chrome最终12/12通过（1.4m）；加强A/B真实缩放和横向mouse.wheel相对滚动同步另fresh1/1通过。各版本冻结图片query严格检查、B缺image_id/SHA/尺寸分别禁止展示，非同基准/协议不显示pp、版本/受控项目迟到无污染。
- 最终当前代码Node1295/1295通过、0失败0跳过；不是早期1251/1254快照。原相关31个CI guard本地执行：30 Bash步骤通过，1个workflow明确shell:python的步骤首次被验证脚本误用Bash（import command not found），改用原Python解释器后通过；未修改业务或降低守卫。
- 新API场景54纳入原Portable Deployment的触发与API回归，四份新Chrome纳入原frontend-runtime-stabilization既有Chrome job，未新建打包/测试体系。最终SHA执行结果须逐工作流检查。
- 全部Chrome352个独立用例当前执行中，最终Python相关212预计组合当前执行中；未完成前不填写全通过。生产/真实GPU仍NOT VERIFIED。

### 可复查截图（全部隔离数据）

以下前后图验证布局与真实DOM交互，不是生产图片或模型精度证明。场景评测/模型及任务响应是明示controlled UI合同；后端资格由独立真实持久Task/Artifact测试覆盖。原素材/标注用隔离素材与正式保存API，未接触生产GT。

| 区域 | 优化前（1366） | 优化后（1366） | 其他分辨率 |
|---|---|---|---|
| 场景工作台 | [原页](evidence/scenario-ui-2026-10-22/scenario-before-1366.png) | [内联A/B框证据](evidence/scenario-ui-2026-10-22/scenario-p1-fixtures-workspace-1366.png)、[真实阈值采样](evidence/scenario-ui-2026-10-22/scenario-p1-fixtures-curves-1366.png) | 同目录1920/1440 overview、analysis/curves/workspace |
| 素材管理 | [原网格](evidence/scenario-ui-2026-10-22/material-before-1366x768-grid.png) | [网格](evidence/scenario-ui-2026-10-22/material-after-1366x768-grid.png)、[列表](evidence/scenario-ui-2026-10-22/material-after-1366x768-list.png)、[详情](evidence/scenario-ui-2026-10-22/material-after-1366x768-detail.png) | 同目录1920×1080/1440×900 |
| 标注工作台 | [原页](evidence/scenario-ui-2026-10-22/annotation-ui-before-1366.png) | [唯一审核/正式色/居中](evidence/scenario-ui-2026-10-22/annotation-ui-after-1366.png) | 同目录1920/1440 |

### 最终整体回归接续

最终相关Python组合实际212 passed、5既有deprecation warnings、0失败0跳过（96.72s，C:/tmp/scenario-final-python.log）；最终Node1295/1295（C:/tmp/scenario-final-node.log）。全Chrome352仍运行（C:/tmp/scenario-final-all-chrome.log），不能沿用子集宣布全绿。P1提交与推送后将以最终准确SHA核全部Actions/Checks，若产生修复提交或文档新HEAD，重新核新SHA。当前未生产部署、生产清理、生产模型/GT操作。

后续接续：先读本文最新阶段/问题关闭与证据，再看scenario_models.py→原v61→Worker/Agent、quality-detection-workbench.js→scenario-evaluation.js→reports.js；素材仍card412/material-pagination，标注仍原Editor及saveAnn/review。禁止另建任务/GT/图表注册表、重新复制素材、用无GT快检作准确率或把不同比较作提升。P2仍未实施；生产真实历史权重/远程OSS/GPU吞吐、大库SLA与已有Ultralytics授权状态需单独现场核验，不能凭隔离测试声明达标。

### 首推精简环境CI失败与修正（不能沿用首推绿色）

首推代码SHA57dd15c9b478a81f5dd67d5e21622fd4bffce153的Portable Deployment API job已通过，但Linux/Windows transport-contract失败；Linux实际33失败102通过，缺ModuleNotFoundError: yaml。根因为scenario_models顶层导入training_tasks，把通用Agent/传输原精简依赖边界扩大，不是合法模型核验失败。没有向精简job盲目安装整套训练依赖。

新增独立子进程MetaPathFinder明确禁止yaml/training_tasks导入的真实RED1失败，原模块改为仅实际resolve训练成果时延迟导入原训练合同；通用verify仍先核持久scene分类，scene执行资格/字节复核不削弱。修后原精简传输/Agent/NodeExecutor相关135 passed、1 Windows symlink环境skip（17.41s），场景54 passed/5既有warnings（61.08s）；新边界测试纳入原Portable工作流触发/编译/执行。相关Linux符号链接实测仍以新SHA CI为准，不借本地skip声明通过。接下来正常提交修复并核新SHA所有Checks。
