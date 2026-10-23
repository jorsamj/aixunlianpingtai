# 场景算法准确性工作台、素材页及标注UI治理（2026-10-22）

## 2026-10-23｜P2 模型深度评测与迭代优化（唯一接续记录）

用户正式授权在本专项增量实施P2-A1→A2→B→C；下文历史“P2不在本轮”仅指2026-10-22的P0/P1范围。基线a0885f6fe38348deaa6389773e36b8286ce73110 / VERSION42.24.378，fetch后0/0；5944e1a5为祖先，两份未跟踪训练模板测试保留，其他worktree不动。应用会话清单未见其他活动同仓开发，不据此保证不存在外部并行写入；每次推送前再次fetch。

### 需求、审计与最小设计

- 已有：training_evaluation正式盲测/类指标/混淆/阈值曲线、build_evaluation_benchmark_scope、compare_evaluations、iteration_decision、feedback_adoption_outcome、hard_sample_mining和Candidate/Adoption链路。原场景三栏/SVG/同步AB/报告身份读取直接复用；不新增评测引擎、数据库、调度器或素材副本。
- 部分：错误证据只保留严重程度前200图/每层120框；正确图片缺席不能被解释为正确。现有比较只覆盖指标，缺逐样本改善/退步证据。原split已有SHA/component防漏，清洗已有dHash；不新增ImageHash/Supervision依赖。
- A1：聚焦只读分析模块读取冻结Snapshot与正式Evaluation，不用当前素材GT替换历史。重建Benchmark身份、核模型/任务/协议/冻结摘要；按SHA与既有source/group查跨划分及内部重复、同SHA不同GT；正式GT状态/类别覆盖显式区分风险、证据不足、未检查。缺少冻结dHash/时间/审核版本不得宣称通过。明细有界分页，不自动删合素材或GT。
- A2：只在原正式匹配循环补匹配索引/IoU与样本证据；历史仅已存证据可诊断，截断/缺失明确未知。复用原三栏框显示、图片身份API；显示过滤不重算指标。
- B：复用compare_evaluations前置资格；同一可信GT/图片身份且双方完整匹配证据才能判改善/退步/持续错误/持续正确。缺席样本保持未知，不从旧top200集合差集猜测。AB同步图层复用原组件。
- C：只接现有复核/挖掘/CandidateSet/Adoption/训练创建/lineage/outcome；冻结Test的image_id与SHA保持服务端拦截。automatic_execution=false、requires_confirmation=true。测试GT更正可复核，不能直接补训后沿用原基准宣称独立提升。

替代方案与风险：否决前端另算TP/FP/FN、全图常驻JSON及新候选表；选择冻结证据只读投影和原正式匹配增强。旧历史无证据无法补造；dHash已有但未冻结时仅未检查；真实NAS/OSS/GPU/生产均NOT VERIFIED，原Ultralytics许可边界不变。

### 阶段清单与验证计划

| 编号 | 状态 | 涉及模块/剩余工作 | 提交及证据 |
|---|---|---|---|
| P2-A 审计 | 已验收 | 原Owner及缺口已核；存储/GT/Worker不重建 | 基线a0885f6f及本节实绩 |
| P2-A1 数据可信度 | 已完成待验收 | 冻结身份/泄漏/GT/覆盖API和Tab；时间/dHash等缺证据明确未知 | 21e0d816，见下文RED/GREEN；最终CI待核 |
| P2-A2 逐框诊断 | 已完成待验收 | 原匹配IoU/索引、全体轻量outcomes、最多200图框证据和分页 | 7b12c789；未保存/截断不补造 |
| P2-B 深度对比 | 已完成待验收 | 同基准/同GT逐图配对与同步AB；无证据明确未知 | e6fb1a8c；最终CI待核 |
| P2-C 复核迭代衔接 | 已完成待验收 | 原反馈/CandidateSet/训练入口及Test保护；无自动训练 | d4aec96c；原反馈/CandidateSet/训练草稿定向通过 |
| P2-F 最终验收 | 进行中 | VERSION379/静态缓存425；Chrome28/Node82+版本9及分批Python通过；推送/CI待核 | 不借旧CI |

执行：每阶段新增必要安全RED→最小实现→对应现有Python/Node及少量Chrome→独立正常提交并更新本节。相同代码已通过测试不重复执行；只复用受影响原CI，不扩大全仓测试。生产部署、GT/模型/素材写入和真实训练禁止。本节持续追加实际命令/通过失败跳过/缺口，不把设计当实现。

### P2-A1 本地阶段实绩

新增只读evaluation_analysis.py及原v12 evaluation/trust路由，服务端复用resolve_scenario_model强制成功成果资格；原质量中心增加高级评测，不重构导航。冻结SHA跨/内部重复、同SHA不同GT、group/source交叉和类别覆盖有界明细；不伪造质量分。历史dHash/视频时间/人工审核版本未冻结，明确not_checked/insufficient_evidence，不宣称这些检查已完成。现有Benchmark/模型身份校验不等于生产字节重新审计。

RED：新增Python2项因缺模块失败，Node缺新模块失败。GREEN：原test_training_evaluation.py完整33通过；test_evaluation_diagnostic_image.py的P2资格/只读/分页1通过；scenario-evaluation.test.mjs17通过；真实Chrome新增1场景通过（3桌面宽度、风险/未知、500重试、返回原场景）。浏览器截图由testInfo.outputPath生成p2-before-scenario及p2-trust-1920/1440/1366，1920已人工查看。缺失报告不显示假指标；未跑GPU/生产/全仓。该阶段提交后回填实际SHA；A2/B/C尚未实现，不将禁用Tab当完成。

A1实际提交21e0d816e76f7e4cfd84061efeb0ed1b4fbcfdd6（本地，远端CI未验）。

### P2-A2 本地阶段实绩

原正式confidence-first同类匹配循环记录pair/IoU，逐图轻量outcomes包含正确/空图，固定GT内容摘要；同一预测只匹配一次。sample_evidence保留前200严重错误及剩余容量正确图、每层120框，截断明确。新合同校验计数、身份、引用界限、完整性后纳入原evaluation_id；历史缺失字段保持缺失。辅助类别/定位/重复标签不改变正式统计。全部图片SHA需额外顺序读取；全部轻量结果O(n)保存在原Evaluation，前端独立report概要不序列化全量outcomes，samples接口最多50/页，无新存储Owner。

高级评测错误诊断复用原QualityDetectionWorkbenchRuntime/SVG/缩放/GT图层/图片鉴权与生命周期；完整逐图与局部框证据范围分开说明。原图片API允许新已冻结样本，仍执行原Snapshot/模型/字节读取校验；不永久复制整个原图集，回收后缺原图可明确不可读。

RED→GREEN：新增分页API先AttributeError；原scorer新增outcome合同先KeyError，最终原单测34通过。图片API39通过；新report概要投影后相关1项复验通过。Node原场景/图表28通过。Chrome新2场景首轮失败：重叠GT框被上层预测框命中（改选择可见最上层实际框，不force）；重试断言早于请求完成（改等真实请求计数和按钮完成）。修正后2通过，未降低功能断言；新诊断截图p2-diagnostics.png。真实GPU/NAS/OSS/大规模内存与生产未验，远端CI未验。A2阶段提交后回填SHA；B/C继续。

A2实际提交7b12c78976ba9c7babbe76635abd952654ef8f37（本地，远端CI未验）。

### P2-B 本地阶段实绩

深度对比复用compare_evaluations，双版本再核原成功成果资格及模型/任务关联；冻结身份不完整或已证实SHA/GT泄漏风险不计算提升。其余未检查风险单独列trust_warnings，不宣称业务适合发布。逐图按同image_id/SHA/尺寸/完整GT摘要与原正式TP/FP/FN分类：错误→无错为改善，无错→错误为退步，均错/均正确分别持续；缺席/GT不同为unknown，不从错误Top200差集推测。全体轻量结果只线性遍历，框证据只合并当前最多50图；无第二套匹配器。类指标复用原比较，TP/FP/FN与Micro F1仅由已存正式类别计数派生，未覆盖不造值。

UI主动添加旧版后显示第二选择器，分页/类别变化、百分点差异、同图AB与同步视角复用原SVG。API新同基准/漂移/双模型绑定1通过，信任门槛补充后P2 trust/deep2通过；原评测新增深度比较1项先ImportError RED再GREEN（验证四类型、缺席未知、GT漂移和Benchmark拒绝）。真实Chrome新增同基准AB/三桌面截图/不同Benchmark不显示提升1通过。最终生命周期小修（重绘前dispose旧SVG/图表）待收尾相关冒烟；C继续。未推送，远端CI未验。

B实际提交e6fb1a8c7a4a4d3d552b72b67e7983a01604cdad（本地，远端CI未验）。

### P2-C 本地阶段实绩与安全边界

- 冻结Test“加入复核/保存意见”复用OnlineFeedbackRepository原表和幂等stage/finalize，source_channel=evaluation，明确原Evaluation/图片身份；模型错误、GT错误、模型正确、暂不确定、困难样本均是人工意见，不改正式GT、不复制原图。暂不确定仍待复核；原反馈列表可追溯到高级评测，普通抽检确认入口不能把此类来源写成GT。build_supplement_candidate对evaluation来源一律FROZEN_EVALUATION_TEST。显式更正GT仍打开原Annotation/CAS工作台，不改旧Snapshot。
- 非Test挖掘使用原v64/AI_ANNOTATION/Worker/CandidateStore，用户明确选择已有eligible范围，稳定request_key防重复。任务详情/审核使用原入口，无第二套队列或轮询。候选预览要求最终SUCCEEDED、模型/任务/素材SHA关联、已accept及原commit journal与当前Annotation事实匹配；旧预览遇GT漂移拒绝。原journal没有GT hash/version的历史限制未伪造，当前GT摘要被冻结进预览；缺少journal/索引则拒绝，不重建历史事实。
- 原CandidateStore的框可能已被人工编辑，因此来源适配明确prediction_evidence_status不可用，绝不把审核后框当原模型预测。确认后在原反馈Owner记录真实hard_sample_review来源，再调用原build_supplement_candidate/Set及原freeze锁、既有Adoption/Snapshot/lineage/outcome。无需新schema/表/任务库。需当前版本原supplement_data已确认建议，其他建议不能伪装补数据动作。
- 原assert_not_frozen_test在预览、采纳及训练最终选取处按image_id/SHA保护；新入口不能把Test转训练后继续沿用同基准宣称独立提升。新“用于下一轮训练”只读取当前服务器版本/CandidateSet，再调用原startAlgorithmTraining429和TrainingDraftRuntime预填，基础版本v2实测保持，无train/start请求。automatic_execution=false，requires_confirmation=true；单个已确认版本不可覆盖另一CandidateSet的原限制保留。
- 发现并修正原training-submit对过期迭代动作静默降级为普通训练：当前算法/版本、草稿基版本、持久action、decision/evaluation/source任一不符明确阻断且保留草稿。原普通无action训练不变。

必要证据：scorer原34整体通过，B比较/身份计数漂移增量分别1通过；身份计数漂移新增断言先实际RED（错误passed）后GREEN。hard_sample_mining/online_feedback原unit26通过（新增来源/未审核/漂移/journal/Test先RED再GREEN）；training-submit Node先RED后54通过，收尾原场景/图表/submit共82通过。API新增真实CandidateStore+原反馈SQLite预览/幂等采纳/GT漂移/Test/活动保护1通过；评测复核只写意见、幂等和身份漂移1通过；受影响P2/原训练iteration/supplement定向12通过，原线上反馈API17通过。框筛选缺证据范围及低置信度0.5只过滤真实已存预测，补充原分页API1通过。

Chrome原场景工作台/分析两文件28通过（含4个P2综合场景），训练基础版本及候选预填追加断言后单项1通过；不是额外29种场景。C首测暴露隐藏modal shell被当作弹窗，改为原#modal:not(.hidden)；隔离训练资源fixture缺algorithms/base_models/rec造成hydrate失败，补完整原合同，不绕过正式资源校验。随后真实原创建窗成功打开；未点击开始训练。截图p2-iteration-original-training已查看。独立只读审查未发现确定P0/P1；提出旧supplement动作未来同版本重评时应加身份复验，未证实当前可触达，作为后续硬化记录而非已修复Bug。


C实际提交d4aec96cb45aca8f669c78554b846082a7d827db。收尾VERSION42.24.379，index app/main/styles425、原训练submit422606、原场景组件20261023p2；版本Owner9项通过，build_identity核验379。原28场景通过后，新增训练基础版本v2断言单场景复验1通过。生产仍未操作。最终实际HEAD以本文件所在提交及GitHub Checks为准，不能以d4/a088代替；CI完成后补代码提交的实际回执，再对任何文档新提交自身独立核查。

### 首轮最终 SHA CI 与定向修正（2026-10-23）

正常推送 e3a373edd1b804743a048f9f0e17989667c403b2 后按该 SHA 核验，未借基线绿色。首轮49个Actions中发现2处失败（其余等待完成）：Frontend Runtime Stabilization 原导航源码守卫要求保留原精确接线；Node Agent Executor 的 Windows 成功用例在固定1.2秒模拟阶段窗口中偶发漏过1秒采样的first_batch心跳，其余模型/成果/清理断言通过，同文件372通过1失败。原日志与官方Checks保留，不将该SHA写成通过。

修正仅恢复原导航守卫表达式并保留新增高级评测deactivate；模拟Worker在原heartbeat实际记录first_batch后才继续，15秒有界失败，不修改Agent生产逻辑，不降低或删除任何原断言。Agent成功目标1通过、相邻失败/取消/独立Test失败合同3通过。另补原SVG检查器的定位几何候选IoU，调用现有sampleEvidenceDiagnostics，不改变正式匹配或指标；原诊断Chrome目标1通过（10.8秒）。main语法及git diff --check通过。下一修正提交必须按其自身SHA再核CI，e3失败不隐瞒、也不代替后续结果。

首轮工作流：https://github.com/jorsamj/aixunlianpingtai/actions/runs/39929197461 、https://github.com/jorsamj/aixunlianpingtai/actions/runs/39929204108 。

### 必须保留的未覆盖项与接续

1. 历史Snapshot未冻结dHash、摄像头时间窗口、完整逐图人工审核版本：近重复未执行，连续帧/审核版本证据不足；不应把本次A1验收理解为已排除这些风险。未来如补充采集，应复用原cleaning.dHash并绑定真实来源SHA及冻结身份，不补造历史。
2. 所有新评测保留逐图轻量正式结果；可视框仍有200图/每层120框上限，框相关筛选显示仅覆盖已存证据。超出范围、旧正确图/旧缺失证据保持未知，不能宣称全量逐框覆盖或完整历史复评。无需为P2复制原图。
3. NAS/OSS/GPU、生产97%实际可信度、大量历史/内存/IO性能和真实挖掘质量仍NOT VERIFIED；未生产部署、数据写入、训练或模型发布。Ultralytics许可独立，未新增ImageHash/Supervision或CDN。
4. 后续从本节、evaluation_analysis.py、原training_evaluation和advanced-evaluation开始，不能重建Owner。最终CI必须检查本轮实际最终HEAD，不能借a088或各阶段本地测试结论。用户两份未跟踪训练模板测试和5944祖先继续保留。

> 本轮唯一综合需求/进度/问题与接续依据。既有VNext、素材性能与Annotorious文档保留历史，仅增加入口，不复制本轮进度。基线c376be7d5d54cca838dc8456ae2e6906815a5335 / VERSION42.24.376；2026-10-22已重新fetch，远端与本地一致、长期工作树干净。应用会话列表查询超时，未宣称已读取全部其他会话；现存其他worktree不动，推送前再次核验远端与差异。

> **当前结论：P0与P1代码、隔离验收及代码SHA CI已验收，生产未验证。** VERSION42.24.377。业务最终代码42bf33b2bfcc46279c1360632e063f3336f7821e实际23/23 Actions、60/60 Checks通过，CI Chrome239/239。本次文档/旧fixture补提不修改业务；其新HEAD仍须按自身GitHub Checks独立核验，不能继承42bf绿色。下文早期“进行中/未提交”是历史执行留痕，以本段、任务表及末尾最终验收为准。

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
| SCN-01 正式模型资格及后端强制 | P0 原test_models与v61/Worker/Agent | 已验收 | 专用资格、来源/字节/持久分类复验完成；通用目录不改；固有TOCTOU限制见记录 | 1f606d30；场景54、相关145通过；42bf最终代码CI通过 |
| SCN-02 两模式和内联检测工作台 | P0 原v64 UI/原任务API | 已验收 | 原Task/Poll/历史/反馈复用，项目/迟到/未知锁与真实SVG回归通过 | 1f606d30；Chrome11通过，42bf最终代码CI通过 |
| MAT-UI 素材视觉与必要反馈 | 独立P0 原素材Owner/CSS | 已验收 | grid/list同DOM、原比例媒体面、坏图重试及三视口截图；原GT/API不改 | 13c70368；Node28/Chrome4及原治理/分页/上传通过；42bf最终代码CI通过 |
| ANN-UI 原标注交互规范 | 独立P0 原Editor/review/NegativeSample | 已验收 | 唯一显式审核、正式色即时同步、居中/手动视角、坏图原重试；GT/CAS保留 | b8d04f04；原workbench23、最终14/15组合通过；42bf最终代码CI通过 |
| SCN-03 真实指标与交互分析 | P1 原reports/ECharts/evaluation合同 | 已验收 | 原真实matrix/curves、未覆盖类、只读诊断、同基准pp及同图AB，组件单URL/单Owner | 新Chrome12及AB同步补测通过；42bf最终代码CI通过 |
| SCN-F 最终回归、版本及精确CI | P0/P1 原工作流/接续文档 | 已验收 | VERSION377；Node1297/Python213通过；广泛Chrome339通过13失败及逐项fresh关闭完整留痕 | 42bf33b2代码CI23/23 Actions、60/60 Checks、Chrome239/239；本次补提自身Checks另核 |

### 执行检查清单

- [x] 审计原资格/TaskRepository/ModelArtifact/Version关系，记录可复用函数；建立前后端非法资格RED。
- [x] 专用模型范围只从服务端已验证成果投影；原v61受场景合同约束，Worker执行前继续核验来源；动态API测合法/伪造/跨项目/漂移/历史。
- [x] 原v64展示迁出并安装同一Owner；原api与benchPredictOne复用；两模式、选择/内联图片/列表/历史、取消/失效/防重与无GT明确呈现；Node真实DOM与Chrome走原任务链。
- [x] 素材坏图、间距/网格列表/toolbar及相关弹窗在原Owner修复；先截图/失败断言，后3分辨率回归，独立提交。
- [x] 标注先fit/颜色/重复确认RED，修原Editor与审核；3分辨率截图与GT保存/并发/负样本/快捷键回归，独立提交。
- [x] P0实际通过后接真实报告P1：身份、原矩阵/曲线、错误样本/GT层、版本同基准比较；任何缺失不造值，样本按需分页/取消。
- [x] 记录实际测试命令/通过失败跳过、RED修复与遗留；一次版本升级、必要缓存与守卫同步；更新AGENTS及四份handoff，推送后最终SHA逐条CI核验。

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

### 第二次CI及广泛浏览器运行的真实结果（未隐藏失败）

- ab883bfc399d6cd687552cdef49f1649f49a7df8实际22个Actions中21通过、前端浏览器工作流失败；其Node job通过，Chrome235通过2失败（13.9m）。精简依赖问题已关闭。
- 两个CI失败：旧navigation用例仍默认显示上传按钮，按新“默认准确性评测→主动快速图片检测”补原tab操作与隐藏断言，保留multiple/folder及按钮可见/无pageerror；另一SCN测试点击包含文字的SVG g联合bbox中心，Linux字体下空白落点被底图拦截，改为点击真实rect绘制区域，无force click，保留详情联动。未更改产品资格或降低安全断言。
- 收尾新增确定停止边界：A完成后用户已停止后续时仍保留running及未显示结果。原函数真实RED2失败→相关Node19/19、最终全Node1297/1297；A-only完成计数保持，compare显示A已完成/B未提交，后续未创建任务明确标记未提交，不篡改Task状态。新Chrome两模式实际通过。
- local广泛运行352用例终态339通过13失败（31.5m），不是全部通过。包括认证2（原有专用auth config待核）、旧clean/AI fencing2、旧row-menu3、上述navigation1、已退役restore控件旧测试1、Uppy前4个项目初始化等待失败。它们逐项追踪，不能通过改鉴权/Uppy业务/删断言掩盖。相关旧report测试已改为断言无恢复控件并保留真实DataZoom范围/同实例/销毁，而非恢复已被用户删除的按钮。其余既有用例正在只读核验是否环境/原基线问题。
- 本轮相关修正后fresh Chrome5/5通过（20.1s）：默认两模式导航、正式SVG框点击、A-only/compare停止后续保留A结果、原报告真实zoom保持且无restore；新P0/P1其他定向及原相关通过记录保持，不把339/13写成352全绿。接下来正常提交修正核新SHA。

### 广泛运行失败的后续差分核验

- 认证2项按原 `playwright.auth.config.mjs` 独立8012/mock登录配置实际2/2通过（12.4s）；普通352套件使用8011测试旁路，不可据此修改生产鉴权。
- Uppy原失败前4项分别fresh真实运行：UP-01/05的本地中文/正式标签映射/真实隔离JPEG入库1项通过，UP-02/03并发槽位、UP-06关闭继续、UP-04丢失complete响应共3/3通过（26.4s）。未改Uppy/TaskCenter Owner。
- row-menu三项fresh3/3通过，原<100ms性能及同DOM/焦点/分页断言保留；实测首菜单四视口16.5–32.8ms，真实pointer17.9–22.3ms。旧全套仍有共享长时启动5秒等待失败记录，不能凭fresh通过宣称相同30分钟负载已完整复验。
- clean/AI两个旧fixture用c376与当前原函数均能复现同一缺失：clean未提供正式awaiting_confirmation状态/旧按钮名，AI缺labelMapping导致POST前TypeError。仅补测试正式shape和真实按钮，不修改原业务；clean迟到确认用无删除项隔离本Owner，删除preview仍由原素材治理测试覆盖。全部新页面sentinel/迟到不可关窗/零broad GET断言保留。fresh原fencing4+row-menu3共7/7通过（31.1s）；另Uppy1+两fencing+菜单1共4/4通过（20.5s）。不重复相加为独立用例数。
- 原13个失败均已有对应fresh通过证据或本轮真实修复通过；没有重跑整套352并宣称其全绿。最终代码Python213/213（5既有warnings，76.35s）、全Node1297/1297（0跳过，27.08s），日志分别C:/tmp/scenario-final-python-after-fix.log、scenario-final-node-after-stop.log。

## 最终验收与后续接续（2026-10-22）

### 准确SHA回执

业务代码最终SHA **42bf33b2bfcc46279c1360632e063f3336f7821e**，VERSION **42.24.377**，实际全部23/23 Actions、60/60 Checks通过，无失败/待运行；原[前端工作流39768539451](https://github.com/jorsamj/aixunlianpingtai/actions/runs/39768539451)真实Chrome **239/239**（11.7m）、Node job通过。[跨平台部署39768548086](https://github.com/jorsamj/aixunlianpingtai/actions/runs/39768548086) Windows与Linux合同各136通过，导入边界各4通过；Linux另3个符号链接边界通过，API79通过/4既有warnings。此处不以本地Windows symlink skip冒充Linux通过。

本次文档与旧fencing测试夹具补提产生新HEAD，必须再次检查其全部Actions/Checks；最终绑定结果从[长期分支提交记录](https://github.com/jorsamj/aixunlianpingtai/commits/feature/external-algorithm-publishing)对应完整SHA进入，不沿用旧绿。按AGENTS.md已有最终回执规则，新HEAD回执保存于 `C:/Users/jorsam/.codex/visualizations/2026/10/21/01a15d6e-6553-7640-9e31-04ade914aca9/scenario-model-ui-20261022/CI_FINAL_HANDOFF.json`，下次受验证提交可归档；避免为写自身SHA无限产生未验证的新HEAD。最终验收以该新SHA真实Checks全通过为必要条件。

### 交付范围与证据

| 项目 | 实际结果 | 证据/限制 |
|---|---|---|
| SCN P0 | 专用正式训练资格前后端/Worker/Agent统一；默认可信准确性评测；快检无GT不显示伪准确率；内联图片/框/反馈/历史、任务真实状态及未知锁 | 1f606d30独立提交；原API/Task/Poll/Batch/反馈Owner保留；原始母模型及未验证上传/失败checkpoint拒绝 |
| MAT P0 | 同卡片Owner网格/列表、统一toolbar/filter、媒体比例/长名多标签/选中/坏图重试及原详情 | 13c70368独立提交；三桌面before/after/grid/list/detail见截图表；原API与GT不变 |
| ANN P0 | 顶部重复确认退役；右侧显式审核/选类确认空图；管理正式色唯一来源并即时同步；fit居中/手动视角/坏图原重试/统一三栏 | b8d04f04独立提交；原confirmed_empty/annotation_scope/CAS/负样本及保存Owner保留；三桌面截图 |
| SCN P1 | 原ECharts真实矩阵/类别/PR/Confidence；正式TP/FP/FN联动；GT双层；同基准版本pp及同图A/B同步 | 57dd15c9及收尾42bf；无GT未覆盖/缺失证据不补造；定位仅待复核，不改正式指标；无新数据库/任务/图表注册表 |
| Python | 当前相关213通过、0失败/0跳过、5既有warnings | 76.35s；本地精简环境另135通过/1 Windows symlink skip，最终Linux CI已实际覆盖 |
| Node | 当前全量1297通过、0失败/0跳过 | 27.08s，原函数/DOM动态用例，非仅源码断言 |
| Chrome | 本轮新P0/P1、MAT/ANN及原相关通过；最终代码CI239/239 | 本地广泛352原339通过13失败后逐项fresh通过，未再次整套352，不能写352全绿；专用认证2/2、Uppy4/4、fencing4+row3共7/7；重叠组合不累计唯一数 |

### 遗留及生产前核验

1. 本轮不部署，不连接/修改生产素材、GT、训练数据、模型权重，不执行真实GPU训练。实际生产模型准确率、历史数据覆盖、远程OSS/硬件吞吐与大库SLA均NOT VERIFIED；隔离UI fixture截图不代表生产精度。
2. 旧历史缺正式模型/冻结图片/版本身份时明确不可信/缺证据；不会为兼容补造成功或指标。现有报告最多200保留错误图、每层120框、前20类图表等边界见前文，不能把保留样本当完整测试集。类别表和样本按原分页/按需加载。
3. mutable文件系统最后资格校验至推理实际open的固有TOCTOU仍存在；已有入口/运输/Worker/Agent多次严格复核，无新权重复制或新存储Owner。
4. 广泛长时共享后端下旧启动helper5秒超时虽fresh全部通过，相同30分钟混合负载整套尚未重验；保留观察事项，不用加sleep或移除性能断言掩盖。
5. Ultralytics既有AGPL/商业授权状态未提供证明，需独立确认；ECharts/Annotorious既有本地许可证沿用，没有新Supervision依赖或许可替代。P2全部未实施，需以后独立授权。

### 新会话从哪里继续

先读本文当前结论/最终验收、精确HEAD Checks和限制。场景资格从 `platform_core/scenario_models.py`→原v61→Worker/Agent/transport；界面从 `quality-detection-workbench.js`→`scenario-evaluation.js`→原`reports.js`。素材从原card412/material-pagination及受限material-workspace.css；标注从原annotorious-editor/annotation-adapter与app原保存审核、annotation-workspace.css。全部任务已有独立提交，不重新开工；不要重建Bootstrap/API Client/Task/GT/轮询/Modal/ECharts Owner，不把人工反馈写成评测指标。生产操作与P2仍需独立授权。

### 文档补提2678的独立CI失败及测试前置加固（不借42bf绿色）

2678b5dcceaa8053639299a53188377f3e8e3502实际23个Actions中22通过、60/61 Checks通过，前端Chrome238通过1失败（13.5m），Node job通过。失败为原annotorious-lifecycle的immediate pointer→Escape用例末行：Esc后annotationEditor为null。旧测试没有断言其图片坐标点击命中检测框，因此不能据此直接认定“清空选择”业务失效，更不能写成编辑器初始化失败。旧写法本地fresh重复12/12通过，单次CI不能稳定复现根因；此不确定性保留。

仅加固测试真实前置：使用Playwright正常点击实际SVG矩形（无force），记录并断言pointerup命中原annotation，依然点击后立即Esc、不等待异步selectionChanged；两帧后明确断言同一编辑器仍存活、选择清空和工作台可见。原关闭/保存/键盘业务没有修改，也没有移除“立即”边界、加sleep或放宽断言。强化写法fresh重复12/12通过（1.0m）；原生命周期+新UI14项再整体回归后补最终记录。本次再提交产生的新SHA仍必须重新查全部CI，不沿用42bf/2678结论。

收尾强化后的标注原生命周期10+新UI4实际14/14通过（55.0s，C:/tmp/scenario-final-ann-escape.log），含20次真实开关/DOM监听增长、保存200/422、迟到和资源失败重试。当前只追加测试及记录，不修改业务或再次升级VERSION；新HEAD全部CI仍按自身核验。
