## 2026-10-23｜P1跨标签负样本与首次训练兼容性（进行中）

本节为本轮唯一需求、设计、任务与接续记录。基线d915bd26805ea1d867dbdfdf67794b64496179b0 / VERSION42.24.381，fetch0/0；保留5944及两份未提交训练模板测试，不生产部署/修改素材或数据库/GPU训练。

用户确认：首次训练以明确选择的训练标签（例vest）构造YOLO连续类别，不猜算法名/母模型；可选择person/car等跨标签候选，但只有正式GT审核范围覆盖全部有效训练标签、且无目标框的素材可作为负样本。未审核的跨标签图应显示待审核，不能自动确认或删除已有框。首次训练必须有真正目标正样本。混合正样本沿用原像素保护投影；新任务已审核纯负样本保留图像内容、输出空标签，源图与源GT框不变。原AnnotationRepository记录范围、操作者、时间和版本，CAS阻止复用过期审核。Train/Val/Test内容隔离、原Worker按需准备/回收不变。

审计：scope校验本身正确，不应删除；现有project_training_rows将excluded-only已审核图转为任务负样本，但materializer仍遮挡全部排除目标。原picker仅显示通用已标注/待标注，与任务有效标签角色不一致。已有scope补审、分页/缩略图/SVG/标注编辑、正式annotation CAS和最终submit准入可复用。

设计取舍：拒绝自动扩scope和全局关闭遮挡。采用原合同新增版本化V3策略，只对新任务严格已审核纯负样本保留原像素；缺新策略字段的历史合同继续V1/V2。原picker扩展任务角色页/SQL聚合/选中统计和有限批次显式审核，原GT保存链承载版本与审计，不新建GT/任务系统。打开弹窗仅轻量统计，正式创建才执行全量准入。数量比例只提示，不自动丢弃选择。

| 阶段 | 需求与模块 | 优先级 | 状态 | 已完成/剩余 | 证据/风险 |
|---|---|---|---|---|---|
| A | 现状/合同审计 | P1 | 已完成待验收 | 共享scope与投影根因已核验；完成正式记录 | 尚无真实GPU精度结论 |
| B | 训练标签/三角色/V3投影与历史兼容 | P1 | 进行中 | 原training_label_tasks/training_tasks修改及RED→GREEN | 新旧策略不得混用 |
| C | 原picker角色分页/轻量统计 | P1 | 进行中 | 原API/前端扩展；必要规模回归 | 禁止全素材前端加载 |
| D | 正式范围批审/原图GT保护/CAS审计 | P1 | 进行中 | 原save_annotation链复用，有限显式确认 | 过期GT/源内容必须拒绝 |
| E | 真实Chrome/必要回归/版本/提交/CI | P1 | 未开始 | 只运行受影响测试，不全仓重复 | 最终SHA独立核验 |

实施步骤：先共享分类/V3及单元RED/GREEN，再角色页与审核API、原picker，接原创建摘要/准入错误，隔离真实浏览器走vest+person审核/保留框/空标签；审查后版本递增一次、普通提交/推送、记录准确CI。A–H安全场景通过核心单元/相关API/必要浏览器组合覆盖，不为相同合同重复建多套测试。分文件委派由subagent-driven-development技能执行，根任务负责GT审计接线/摘要/浏览器/Git，避免交叉覆盖。

测试与提交：尚未最终验收，后续追加真实命令、数量、失败修正、准确SHA。生产真实NAS/OSS/GPU与模型准确率收益仍NOT VERIFIED；负样本增多未必提升准确率，需要同可信独立Test评测后判断。

### P1本地实现与验证回执（代码完成待准确SHA CI）

- B：training_label_tasks共享三角色分类，canonical显式类别、真实正样本证据与新策略冻结；training_tasks V3已审核纯负样本保留原字节、空YOLO，混合图按V2保护正框。无V3字段的历史合同仍按旧策略。审核不创建background类别；来源不可用/复核标志/图片摘要漂移不显示已确认。
- C：原picker增加role-page/原始标签与角色分离筛选、计数；SQL临时表做一次逐候选分类，浏览器最多原60/120条。原selection-summary保留通用摘要，明确选本次标签后才追加任务角色计数；首次无标签时仍可读取素材标签，不形成循环依赖。打开只轻量预览，不能借客户端字段关闭正式准入。
- D：每批最多50张人工逐项勾选/二次确认；原save_annotation校验源SHA/版本/生命周期、保留所有person框，空GT保留已有具体审核范围。AnnotationRepository同事务新增审计表annotation_negative_reviews（仅审核证据，不是第二套GT），绑定原版本/新版本/digest/源SHA/实际登录actor/具体标签/时间。用户不能通过请求指定私有actor。旧版本精确重放仅当当前GT仍等于该审核结果时成功，修订后409。原工作台补框继续复用；不自动确认未查看图片。
- 创建摘要增加任务正/负/待审核数及>3:1比例提示，不裁减素材。打开不跑全量准入，正式提交继续原检查，审核缺口提示具体数量/有效标签。
- 只读双阶段审查未发现阻塞项。正式审核本身不以Test/活动租约一概拒绝新GT修订；历史冻结证据不可变，下一轮训练仍由原冻结/最终准入执行SHA去重与Train/Val/Test隔离，不能声称此接口独自完成全部租约检查。

必要验证（非全仓重复）：核心原标签/负样本/标注准入组合72通过；新增核心随后扩充到16通过（包含真实PNG字节一致、零字节vest标签、混合像素、历史V2、伪造标记、无正样本、可信预览、5种漂移及无排除目标正样本不重新编码），不是相加成87。picker API原/新增12通过，规模用例再扩500vest+3000person/10000候选后定向1通过，原摘要/挂载16通过1旧断言失败，挂载准确补入审核与actor回调断言后1通过；真实审核API2+事务证据1共3通过。Node picker16、摘要15及相关选择/labels组合48首47通过1旧cache断言，准确同步后版本/submit75通过。Chrome原分页性能+实际vest/person审核+原创建摘要3/3通过，无浏览器造假评测数据。

真实RED与修正：缺审计参数/缺新summary export先失败后实现；轻量role-page最初复用了要求正样本的正式resolver，通过仅函数内部可信参数拆分预览，客户端无绕过；无标签摘要避免正式解析循环；新审核挂载回调与cache需要同步旧精确守卫。规模fixture误一次写3500GT触发原500安全上限，改为原上限分批写入，不降低限额。旧有5条依赖弃用warning保留。

复现入口：tests/unit/test_reviewed_negative_projection.py、test_negative_sample_contract.py、test_training_label_contract.py及annotation admission；tests/api/test_training_material_picker_api.py/test_training_negative_review.py/test_training_material_selection_summary_api.py/test_runtime_router_app_mount.py；tests/frontend/training-material-picker*、training-material-summary-runtime、training-labels、training-submit、version-marker-owner；tests/browser/training-material-picker-performance.spec.mjs和training-page-material-summary.spec.mjs。原受影响Training Material Picker工作流扩入新增安全测试，不新建CI体系。

修改文件：app.py（仅原正式保存参数与审核回调接线）、AnnotationRepository（事务审计）、training_label_tasks/training_tasks（共享分类/版本化投影）、training_material_picker_api、原picker/summary/submit、main/index精确缓存、VERSION、上述测试/原工作流及现有交接文档。VERSION一次递增42.24.382。B–E当前已完成待验收；提交与最终CI待普通推送后追加，不能把本地通过写成远端绿色。

生产边界：未部署/未写生产素材或GT/未物理清理/未训练。不能保证负样本数量越多越准确；需生产前只读核验真实类别/范围/来源，再在同可信冻结Test上比较误检、召回与mAP。NAS/OSS/GPU实际效果仍NOT VERIFIED。下一会话从本节与上述原Owner继续，禁止重建GT、素材、调度或副本生命周期，保留5944和两份模板测试。

## 2026-10-23｜P2模型深度评测（代码及隔离CI已验收，生产未验证）

唯一需求/进度/限制：[场景评测专项P2](SCENARIO_MODEL_EVALUATION_UI_GOVERNANCE_2026_10_22.md)。A1只读冻结信任、A2正式匹配证据和有界框、B同基准逐图变化、C原反馈/已审核候选/训练草稿衔接已提交；VERSION42.24.379。原场景Chrome28、Node82及必要Python分批通过，未跑全仓；dHash/连续帧/审核版本缺历史证据保持未检查或未知，框证据上限200图/每层120。5944和两份未跟踪模板测试保留，不部署/不生产写入/不自动训练。代码9280实际21/21 Actions、55/55 Checks通过，Node1311/1311、Chrome248/248；本次文档自身SHA交付前另核CI，不借旧绿；不重建存储、GT、Task或Candidate Owner。

## 2026-10-22 训练创建按需准入变更入口

用户确认仅“开始训练”触发正式检查，覆盖此前打开/草稿变化自动诊断。唯一需求、实际修改、RED→GREEN及最终SHA回执见[生命周期专项第十一节](TRAINING_MATERIAL_LIFECYCLE_GOVERNANCE_2026_10_21.md)。后端与GT/删除/冻结合同保留，Uppy/TaskCenter实现不改；实现c0163347实际41/41 Actions、114/114 Checks通过（Chrome207/207），最终文档HEAD自身另验，生产未操作。

## 2026-10-22 训练准入与当前素材删除统一治理入口

本轮GOV-01–11唯一需求和进度为[GT生命周期专项第十节](TRAINING_MATERIAL_LIFECYCLE_GOVERNANCE_2026_10_21.md)：全部已登录且可访问项目用户同权，无管理员白名单/RBAC；诊断、全部问题选择、GT整组删除、清空、队列重冻结及真实结果复检。代码d207ba57已通过31/31 Actions、81/81 Checks、Chrome184/184及Node1209/1209；Python合同迁移已完成，本地合并356通过3个Windows symlink跳过，Linux相应边界已通过。最新接续和最终文档自身CI规则见唯一专项10.13；生产未操作，单份存储/Bundle回收未冒称完成。

## 2026-10-21 综合治理补充验收入口

Loading覆盖矩阵、成功训练计数/PARTIAL_SUCCESS证据、报告耗时范围和生产只读性能方案见[综合专项第10节](FRONTEND_STARTUP_REPORT_UX_GOVERNANCE_2026_10_21.md)。本地限定测试已完成，最终CI须按本轮SHA，未覆盖和未知提交恢复限制不隐藏；Annotorious后续独立实施。

## 2026-10-21｜页面启动、报告与训练任务交互综合治理（代码及CI验收完成）

唯一接续依据：[综合专项](FRONTEND_STARTUP_REPORT_UX_GOVERNANCE_2026_10_21.md)。八项代码需求已实现：Snapshot增量/概要与核心先返回、有界恢复；正常报告/评测弹窗、共享Loading/Tooltip及真实曲线无恢复控件；创建成功立即仅关原窗，完整成功训练次数和排序缓存一致。VERSION42.24.370；实现/修正f0f3010d实际21/21 Actions、55/55 Checks、Chrome128/128通过，本地Python104/Frontend Node1108通过。首提交两条旧夹具失败及修复已留痕。本次仅补记文档，自身新SHA须独立CI，见专项第9节与GitHub提交Checks。生产未部署，现场12.08秒仍需分解核验；取消临时需求已全部撤销，无发布字段改造混入。

## 2026-10-21｜报告交互、确定性ChatGPT材料与参数继承专项（本地限定验收完成 / 最终SHA CI待验收）

起点ba6e9c3497c04e69a2e80c3f7dbf07d52fb391c2/VERSION42.24.368；fetch完成，首次无代理pull连接重置，随后代理pull --ff-only成功且最新一致，工作树干净；唯一同库活跃会话为本任务，其他WIP/worktree不动。上轮最终22/22 Actions、57/57 Checks回执已核验，不替代本轮。

完整需求来源：用户附件03c25113-b573-4524-9fd9-5dc2f05f31a9及其后ChatGPT分析材料强制修订。六项范围：原训练报告/溯源UI；真实曲线交互；冻结FP/FN有界代表样本；确定性复制材料与4项可选现场描述；请求/决议/实际Optimizer/LR/资源事实；BM1688检测复核及转换/迭代训练参数继承。补充修订覆盖原AI定位：不调用模型/API、不生成AI结论、不要求Key；同输入事实+现场描述文本一致。Person/Car只有用户提供配置/基础合成板端PASS，无mAP/FPFN/业务验收，不补造。

已读现状：TrainingRecoveryRuntime拥有详情/按需历史/轮询，reports.js为静态SVG；app.trainingReportCore425调用唯一v44报告API，build_version_report/TaskRecord result拥有报告事实；training_evaluation已有冻结评测身份/Top200/真实预览与GT预测叠加；training_metrics记录LR/损失/资源但未持久化实际Optimizer类型；sophon_runtime已完整版本识别及1.30.2 BM1688 F16/F32能力规则；compute_platform_catalog的precision默认值仍优先模板，training-submit模式预设覆盖imgsz。未将现场全部问题当作仍存在。

采用writing-plans方法，在原文档记录最小实施顺序，用户已授权自主执行，无重复审批/设计确认：
- [x] A 先新增reports生成材料纯函数及报告HTTP身份测试RED：Person/Car未知项、相同输入稳定、任务版本错配、敏感数据、请求/实际与协议分开；在原reports事实投影内补齐来源、转换和有界错误样本引用，不另建报告Owner/评分引擎。
- [x] B reports.js内确定性文本序列化固定模板A-H、4现场字段及复制/预览；原报告入口只接线该模块，不叠wrapper。请求迟到校验绑定task/project/version，错误保留在当前视图。
- [x] C 按官方ECharts容器/resize/dispose合同评估本地静态依赖及许可证；原report/TrainingRecovery渲染调用同一图表实现，旧SVG保留无JS可读降级，不轮询重建；按需载入、缺失断线、tooltip/legend/zoom/reset、关闭释放。
- [x] D 复用冻结evaluation和预览选择最多8/上限12个分层代表样本，固定身份/seed，不复制原图或修改GT/Test；复用现有预览，图片失败隐藏叠加，人工按权限导出，不自动回流训练或外传AI。
- [x] E 先RED精度/尺寸继承及实际Optimizer记录，再原位置最小修复；仅真实Trainer对象给实际Optimizer/LR；BM1688版本能力已有则测试复用，不硬编码扩容；模式保护显式/继承尺寸及精度，保持resume区别与安全校验。
- [x] F 定向Python reports/metrics/直接继承API、Node reports/直接draft-submit、Chrome报告/冻结预览及4分辨率；不跑全仓/无关素材清洗训练。核验同输入、未知不为0、无Key/敏感URL、无AI请求、无重复事件/实例/迟到串数据。
- [ ] G 更新本tracker与既有转换/Sophon专项、CODEX_CURRENT_STATE/AGENTS、完整生成文本示例；最终fetch后版本一次递增、必要缓存一致，普通push唯一长期分支、核验实际最终SHA Actions/Checks。

生产边界：不部署/重启、不创建真实训练或转换、不修改生产DB/配置/GT/Test/历史报告、不操作OSS或真实新畅联Weight；隔离Person/Car验收数据必须标记测试夹具，不能伪称现场指标。

### 实现、根因及事实边界

- 原报告/TaskRecord result/Snapshot/ModelArtifact仍唯一事实来源；原v44 GET增加可选algorithm_id+version_id明确绑定，冲突409；冻结标签复用model_metadata，版本/血缘任务冲突不能混用。无新报告API、数据库、推理、评分、执行器或AI调用。
- 原reports.js固定专业指令+A-H数据章节，4现场字段可空且标注未独立验证；同输入结果一致，忽略生成时间；未知/0、请求/实际Optimizer与LR、Train/Val/Test及不同协议分开。不用Workers=0判定I/O瓶颈，不用高mAP确诊业务合格。最终复制文本统一过滤凭证、URL、Windows/UNC/私有路径，JSON/camelCase token也覆盖；剪贴板失败仍可预览/选择复制。
- API投影本次冻结input_quality/class_coverage来源及负样本事实，原曲线/遥测范围有限且不根据created_at替代真实运行时间；原报告缺失时旧elapsed=0不再作为真实耗时。完成Epoch保留显式0。转换摘要只读本版本已有ModelArtifact，不触发转换/上传/发布。
- 默认8、最多12个冻结FP/FN引用：错误/类别分层+确定性哈希顺序，保留Top200边界，不复制图片、不改GT、不回流Test。审查发现Durable评测与当前版本评测同名异SHA缩略图风险；原图片GET扩展expected_evaluation_id/expected_image_id/expected_sha256，有期望身份时严格核验，变化409 EVALUATION_IDENTITY_CHANGED，图片隐藏且停止无意义重试。原无参数访问保持原严格Snapshot/Bundle/SHA检查。
- 原报告和训练详情共用本地ECharts交互实现：质量、Train/Val Loss、LR、Epoch耗时、吞吐和有记录的资源曲线，tooltip/图例/缩放/恢复，null不连线、不造Epoch；按需导入、ResizeObserver、同实例增量更新、关闭dispose。保留静态SVG加载失败降级。原报告冻结分布/下载/素材入口与可信度展示保留，技术JSON折叠，报告/溯源卡片统一风格。删除原三个已无调用的旧展示函数，没有render包装链。
- ECharts 6.1.0从官方npm registry离线打包，Apache-2.0 LICENSE/NOTICE随static/vendor/echarts保留；bundle SHA256 b66b25aeb4df84e33199dc21694014d336d222cbd9deb0e5a7c14bd6aa0d0fd0。运行不访问CDN，遵守官方容器resize/dispose合同 https://echarts.apache.org/handbook/en/concepts/chart-size/ 。
- 真正Trainer.optimizer类型、param_groups初始LR与AMP仅在on_train_start观测后写入原training-metrics summary；Checkpoint best_epoch从真实Trainer读取，历史缺失不回填。未把optimizer=auto请求lr0包装成实际LR。
- 转换默认曾受模板FP16覆盖：原resolve改为源训练实际精度优先，受所选真实SDK允许集合约束；不支持时显示“已根据芯片能力调整转换精度”，显式非法值继续拒绝。原矩形尺寸/Batch1/FP16/FP32/独立资源/产物校验不改。
- 迭代精度/imgsz只取当前可训练、归档验证版本的actual参数，不取requested猜测；原创建/算法初始化/模式提交三处曾覆盖imgsz，分别原位修正，用户显式值保留；断点续训原冻结合同未改变。新增首训SDK默认1280用例再复现初始化640误当显式值，创建时无继承尺寸保留null直至原算法合同决议；该场景RED→GREEN且迭代800复验通过，避免引入默认值回归。Sophon完整1.30.2版本解析及BM1688能力已在最新代码存在，本轮复用并定向验证，没有重复开发探测器。

### 精准RED→GREEN与限定验收

- RED：材料函数缺失5项；报告显式身份参数缺失2项；代表样本函数缺失1项；JSON/UNC敏感串泄漏1项；版本job_id与lineage.task_id冲突1项；实际Batch/Workers遗漏及AMP重复1项；完成Epoch0被99覆盖1项；原无报告耗时未知变0的API1项；实际Optimizer/LR未记录1项；FP32源默认FP16与模式imgsz覆盖；原图片接口不接受冻结期望身份3项。均在原实现修复后GREEN，不删除/弱化安全断言。最后补强同一身份校验同时保护报告UI和复制文本（先RED Missing expected exception，再10项GREEN）。
- Chrome首次图表悬停用例落在绘图区右边界，移入2px后真实鼠标tooltip/滚轮/恢复/实例保持/dispose通过；没有改为假dispatch代替悬停。继承浏览器用例真实复现trainAlg二次覆盖800→640，修正后GREEN。新增错误码未在旧UI映射中展示具体原因，已原映射补齐，未降低错误断言。
- Python命令：`python -m pytest tests/unit/test_reports.py tests/api/test_training_metric_credibility_report.py tests/unit/test_training_metrics_fd.py tests/unit/test_dynamic_conversion_catalog.py -q`（首批54 passed，已有Linux /proc FD用例在Windows 1 skipped；后续新增API一例及受影响精确复验通过）；`python -m pytest tests/api/test_evaluation_diagnostic_image.py -q` 36 passed；`python -m pytest tests/unit/test_sophon_conversion.py -q -k 'preserves_full_v_prefixed_version or official_cli_uses_version'` 5 passed。最终唯一用例合计97 passed/1既有平台限定skip，未新增skip；不执行真实SDK/模型/训练。
- Node：仅training-analysis-material、metric-credibility-report、quality-charts、training-draft、training-submit、training-recovery-runtime、version-marker-owner九个直接相关文件，分批去重118用例通过。旧模式断言“无论显式320都覆盖640”按本次已确认业务变更为显式320保留，并新增“无显式值仍使用模式默认”强断言；其余资源/安全断言全部保留。
- Chrome限定：报告Person/Car在1920/1440/1366/375布局/复制/补充/未知/不串任务；真实图表tooltip/缩放/恢复/关闭释放；迟到响应/剪贴板拒绝；冻结缩略图精确身份/失败隐藏/重复进出只读一次；原停止目标报告、四模式精度；新增迭代800/FP32及手工640保持；原成功和运行详情（四视口/运行事实/刷新稳定/键盘/关闭）。去重16场景通过。旧成功详情仅锁两条静态SVG的断言升级为三组真实交互canvas及GPU80原采样、排除结束后0值，不放宽断言。
- 代码审查两轮确认无第二Owner/队列/轮询、无包装链/重复绑定；报告单根AbortController、迟到结果归属、图片读取Abort、chart实例释放；原API、Task/ArtifactStore及版本事实复用。官方vendor静态资源为唯一新增运行依赖；没有新增UI框架。普通操作均有反馈，输入和视图状态不互相覆盖。
- 完整生成文本示例：[Person隔离材料](examples/TRAINING_CHATGPT_MATERIAL_PERSON_2026_10_21.md)，由正式纯函数生成约3200字，含全部固定指令与A-H、未知证据、人工描述区，可直接复制给ChatGPT；明确为隔离结构，不冒用生产ID/指标。

### 本轮修改文件清单

```text
.github/workflows/training-create-first-open.yml
.github/workflows/training-recovery-guard.yml
AGENTS.md
VERSION.txt
app.py
docs/CODEX_CURRENT_STATE.md
docs/CONVERSION_PARAMETER_CONSISTENCY_2026_10_21.md
docs/SOPHON_BMODEL_CONVERSION_ACCEPTANCE_2026_10_20.md
docs/TRAINING_QUALITY_REMEDIATION_TRACKER_2026_10_18.md
docs/examples/TRAINING_CHATGPT_MATERIAL_PERSON_2026_10_21.md
platform_core/compute_platform_catalog.py
platform_core/reports.py
platform_core/training_metrics.py
static/app.js
static/index.html
static/main.mjs
static/modules/reports.js
static/modules/training-draft.js
static/modules/training-recovery-runtime.js
static/modules/training-submit.js
static/styles.css
static/vendor/echarts/LICENSE
static/vendor/echarts/NOTICE
static/vendor/echarts/README.md
static/vendor/echarts/echarts.min.js
tests/api/test_evaluation_diagnostic_image.py
tests/api/test_training_metric_credibility_report.py
tests/browser/training-analysis-material.spec.mjs
tests/browser/training-evaluation-diagnostics.spec.mjs
tests/browser/training-quality-reports.spec.mjs
tests/browser/training-recovery.spec.mjs
tests/frontend/metric-credibility-report.test.mjs
tests/frontend/training-analysis-material.test.mjs
tests/frontend/training-draft.test.mjs
tests/frontend/training-legacy-owner-retirement.test.mjs
tests/frontend/training-quality-owner-retirement.test.mjs
tests/frontend/training-submit.test.mjs
tests/frontend/version-marker-owner.test.mjs
tests/unit/test_dynamic_conversion_catalog.py
tests/unit/test_reports.py
tests/unit/test_training_metrics_fd.py
```

### 版本、未验证与接续

提交前再次fetch，远端仍ba6e9c3497c04e69a2e80c3f7dbf07d52fb391c2，无覆盖其他成果。本轮VERSION42.24.368→42.24.369一次变更；app/main/styles缓存42.25.416；draft422512/submit422601/recovery4226390，reports两处同URL20261021r1，避免同一有状态模块双实例。正式前端版本继续读后端VERSION，未嵌静态显示版本；既有恢复workflow仅同步build守卫，不改触发/测试范围。

首推f22a501c589108249093c42c143ed9ab4133a4b6 CI实测：训练创建/报告Chrome15通过，Node1083通过/2失败，另lineage中文标签断言失败、FirstOpen文案源码guard仍查app旧位置。已保留原断言强度：guard只移到原reports模块的真实Owner，核心签名增加selection并强化唯一赋值；恢复阶段质量检查/非独立Test协议及原中文溯源字段，未删除或跳过用例。随后browser-navigation实际109通过/3失败（包括同一lineage）；保留旧历史报告“未保存完整训练任务”边界及场景实测入口，修正原浏览器夹具精确匹配新增algorithm/version查询，三条静态曲线断言升级为三组交互canvas/20个原Epoch而非跳过。相应Node8+视图14、原lineage Chrome1及冻结评测/四视口Chrome2通过；新增缺失run_dir误读当前目录results.csv的RED→GREEN1，明确目录正例仍能读取。VERSION369不二次递增，无CI扩范围。最终SHA在后续提交后核验，独立回执 `training-report-materials-ci-final-20261021.json` 保存实际SHA、Actions/Checks/关键Jobs，位置为既有Codex visualizations附件目录；本仓文档不自引用未被CI覆盖的追加提交。不得沿用基线22/57绿色。

**NOT VERIFIED**：Person/Car真实完整mAP、FP/FN、现场图片和业务验收、GPU/真实SDK编译及板卡性能、本轮新UI生产上线。用户既有合成/基础板端PASS不等于真实检测精度；源训练FP32/编译FP16/I/O dtype分开。冻结类别仍取已有schema/data合同/ModelArtifact tags；本轮未读取实际PT/ONNX/BMODEL或生产data.yaml，不伪称板端插件类别映射已核验，也未按未知插件格式生成或替换标签文件。板端仍需用版本冻结person/Car核对插件标签，不能默认COCO80。生产17项元数据/历史Weight及其他前轮待办保持原文，不执行本轮外部写入。

不部署、不重启、不修改生产数据/配置/密钥/OSS/Weight，不重训/重转换。下一会话先读本节与最终CI独立回执，再按明确授权现场验收；不要重跑已通过且未受新修改影响的测试。

# 畅联云算法训练平台｜训练质量与模型评测可信度专项问题追踪（2026-10-18）

## 接手信息

### 2026-10-19 P0 批量 GT 冲突辅助治理（本轮 / 最终 SHA CI 待验收）

同步起点 `9e0d330ac653502b5ec22a67ee1327cd208fa336`，实际长期工作树与 origin 一致。正式 VERSION=42.24.356；此前只读工具 stash 保留、不混入。用户授权普通快进推送和必要 CI 修复；禁止生产连接、标注覆盖、素材删除和部署。

实施顺序：①原 TrainingCompatibility 纯诊断 RED→GREEN；②原审计 SQLite 增加可废弃派生分类、原 MaterialBatch 只读 API 与正式来源校验；③两个既有入口共享 GT 差异/叠加组件、人工来源审核进入原冻结计划；④API→Worker、Node、真实 Chrome、安全复核；⑤文档、fetch/FF、最终 SHA 全部实际 CI 验收。没有第二套 GT、引用系统、删除执行器、任务 Owner 或轮询。

- 分类只证明标签/范围/数量/坐标/角色差异，不把差异自动叫漏标、多标或错误。原 ZIP class_id 不等于项目类别 ID；明确 canonical_project_class_id 与当前 schema 冲突才记录其错误证据。
- 导入映射追溯必须有同项目 MATERIAL_IMPORT Task、accepted 确认、同源类别表和已选/已入库候选清单；当前正式 GT 的类别、坐标、完整数量和范围必须与原确认吻合。只读复用 ImportCandidateStore 现有 SQLite，mode=ro，不调用创建/迁移构造器。历史来源缺失、外项目 Task、仅字段相似不产生确定根因或整批候选。
- IoU 是固定参考身份到其他成员的一对一贪心候选比较，包含跨类别、未匹配数量、像素偏差、直方图及无法核验项；不是质量评测 AP，不证明哪个 GT 正确。每组计算预算10万对，超预算明确未核验。全量统计来自原服务端审计范围，成员/组分页不冒充全量。
- 两个入口共用 TrainingMaterialSummaryRuntime 的真实图、A/B 叠加、框坐标/IoU、来源与保护视图。保留身份建议仅沿用原 protected/keeper 排序，不自动推荐正确 GT。来源批次整批审核须明确人工确认，服务端解析全筛选并冻结；未知/多候选组不入整批计划。原人工逐组决策可跨分页保存。
- 仍通过原冻结预览、二次凭证、MaterialBatch DELETE_INDEX、执行与 Worker 重验处理；GT/素材/schema 变化拒绝旧审核。历史/Test/Snapshot/模型保护仍优先，保留保护身份及 keeper，不改历史 GT，不删共享物理文件。训练预检、准入、冻结仍使用原正式 GT 合同，无训练热路径额外诊断。
- 本地 Python/API/训练请求/保护/导入存储组合341 passed；Node24完整995 passed。新增26组真实 PNG/API→Worker 回归只读取1组可见页，仍冻结/治理完整26组，保留26身份及全部原始物理字节。真实 Chrome 两个旧计数断言与新增叠加图冲突，已分别锁定2个原图及1个叠加图，未放宽业务检查。只读复核发现迟到 review 请求会重开已关闭弹窗，已用真实 Chrome RED 复现并按发起内容身份修复；最终 Chrome/CI 结果见最终附件。

最终本地 Chrome 专项11/11通过；最终中文分类筛选和重合A/B标签错开后新增核心真实链路再次1/1通过（与11重叠，不相加），Node最终995/995重跑通过。Windows测试服务有一次客户端断开产生的Proactor ConnectionReset日志，但全部11用例业务断言实际通过；未屏蔽异常或据此替代Linux CI验证。四视口真实截图已检查。未执行完整pytest，不宣称其全绿。

生产结论边界：629复合组中映射原因数、172组实际 IoU 分布、155组实际根因、可按证据整批审核数/逐组人工数，目前均 NOT VERIFIED，不能用隔离样例外推为0或960。新增 conflict-review 接口按实际新审计给出 cohort、来源和完整统计；旧审计缺诊断版本要求重新审计，不篡改旧证据。412保护是去重并集、不能与其他原因简单相加。本轮没有读取生产私有数据；生产治理效果须另行授权部署后只读复验。

最终完整 SHA、实际推送列表、全部 Actions/Jobs/跳过/未触发以及截图统一归档：`C:/Users/jorsam/.codex/visualizations/2026/10/19/gt-conflict-assisted-review/CI_FINAL_ACCEPTANCE.md`。不继承前一 SHA 的绿色，不为记录本提交 SHA 再制造未经 CI 的文档提交。

### 2026-10-19 P0 远程清理同步锁误保护（精准修复 / 最终 CI 待验收）

同步基线 `9ab88ad88a64a370ad50d58b0413e3488a1345a0`，长期分支与 origin 一致、工作区干净。上一阶段只读诊断工具和文档单独保留在本地 stash，不混入本次提交。正式 VERSION 保持 42.24.356。

用户已提供真实生产只读诊断：项目 `f1fb1e6fa373`、审计 `104cb1c3b2a1466b839c62b379f7f66f`，2531 张/1041 组、可删除0。以下引用计数有重叠，不相加，不等于修复后可删除数量：

| 训练任务 | 引用图片 | 用户提供的现场证据 | 处理边界 |
| --- | ---: | --- | --- |
| train_9a0d5368da0945ed8c641316 | 2369 | attempt0、无冻结/进程/结果，额外文件仅精确清理同步锁 | 仅消除锁的误判，仍逐项复验其他依赖 |
| train_3b9c105816b0409b88e11a16 | 2369 | 同上 | 同上 |
| train_bae0c8e07e9b41068f45250b | 1560 | 同上 | 同上 |
| train_06337f34acc84801bfb4af69 | 162 | 同上 | 同上 |
| train_8945092dee564300bdc6698d | 162 | 同上 | 同上 |
| train_0e5d1e30e3da460db579d262 | 162 | attempt1、有效冻结及大量实际产物 | 必须保留历史保护 |

实施与验收计划（不新增业务 Owner）：

1. 先通过真实 `RemoteExecutionStagingLifecycle.cleanup_task()` / FileLock 触发 NO_OBJECTS，调用原历史引用函数稳定复现误保护；不是手工放置同名文件。
2. 在原 FAILED TRAINING/no-freeze 分支的允许列表中，只新增精确相对路径 `remote-material/staging-cleanup.json.lock`。原有 symlink 拒绝、Payload 递归依赖、其他任务关联、attempt/进程/结果等检查不变。
3. 真实台账 `staging-cleanup.json`、其他路径/名称的 .lock、Snapshot、Bundle、Checkpoint、冻结、恢复/重试、模型/Test、活动及成功任务继续保护；API 预览、执行和 Worker 仍使用同一函数重验。
4. 实际持锁期间进行 API 安全计划，再执行隔离 DELETE_INDEX，验证保留一张、共享源字节不变、原始任务状态/Payload/历史证据不改；运行相关 Python/API、完整 Node24 和真实 Chrome。
5. 独立只读复核、更新原验收文档、fetch/FF 检查、普通推送；按最终完整 SHA 查询全部实际 Actions/Jobs 并等待终态。

已验证根因：原函数在清理 NO_OBJECTS 的真实锁存在时错误返回 `{'a','b'}`，期望空保护集合，RED 在业务断言处失败。Windows FileLock 在 release 时移除锁且持锁不可读；测试在真实持锁回调中检查，Linux 同样执行该路径并在释放后再次复验。只对历史 Payload/产物读取字节断言，不尝试读取 Windows 独占锁字节。

本地已执行：Python/API/Worker/训练请求/保护与远程清理组合191/191；追加训练冲突/删除原子性/标注作用域27/27；Node24完整994/994；真实Chrome清理夹具最终复跑10/10；保护与远程清理按CI confcutdir命令46/46（与191重叠）。独立只读复核无确认问题，另验证27保护单元和19 API（重叠不相加）。全部0失败/跳过，未宣称完整pytest全绿。最终SHA CI待结果，最终准确统计归档 `C:/Users/jorsam/.codex/visualizations/2026/10/19/cleanup-lock-p0/CI_FINAL_ACCEPTANCE.md`。不新增或放宽CI条件，现有Remote Training Ubuntu/Windows矩阵执行新增单元，Atomicity/Release执行真实API，Frontend执行真实Chrome。

生产边界：本轮未连接生产、未删除锁或素材、未重写历史任务。用户提供证据已定位跨模块根因，但修复部署后的现场最终分类、全量交叉引用和真实可删数量仍需用户授权部署后只读复验。独立 Test、其他有效历史依赖、GT 冲突人工判断、每组 keeper 仍会阻止或减少删除，不承诺2531张全部释放。

### 2026-10-19 P0 素材重复治理闭环（本地验收完成，最终 SHA CI 待核验）

基线 `5a8d559faf20c46a4ceeca172b792920f1f86f57`，fetch 核实远端一致、工作区干净、VERSION=42.24.356。此项覆盖附件完整指令和用户补充，不继续开发已完成 TQ-04。

- [x] 引用分类 RED→GREEN：原 `_historical_material_references` 对 FAILED/no-freeze 无条件保护；先检查真实持久化依赖，再决定是否仅为可追溯请求引用。活动任务、冻结、Test、模型和恢复依赖始终保护。
- [x] 计划 RED→GREEN：原 `MULTIPLE_PROTECTED_REFERENCES` 整组跳过；同 GT 仅保留所有保护项与 keeper，安全处理其余候选；不同 GT 仍需人工决定且不能绕过保护。复用原计划与 DELETE_INDEX 执行前复验。
- [x] 两入口联调：训练冲突分页选择和全部筛选结果由服务端解析冻结；共用治理预览/执行/MaterialBatchRuntime62，不将训练问题 ID 直接交给不兼容审计接口。
- [x] 服务端真实分类与终态刷新：待治理、历史保留、已治理证据不混淆；删除完成失效旧审计及训练选择，失败保留选择和准确计数。
- [x] Python/API/Node/真实 Chrome 验证：单张、多选、99页、2531全保护、GT/引用漂移、Test/历史保护、共享源文件、部分失败、桌面/手机截图。
- [ ] 更新既有治理文档，独立安全复核，重新 fetch 后普通 FF 推送；按最终 SHA 查询全部实际 Actions/Jobs 并等待终态，不继承旧绿色。

本地验收：Node24完整994/994；Python/API组合122/122，追加原子性及最终API25/25（有重叠，不相加）；真实Chrome两规格10/10，追加迟到预览不得覆盖标注工作台1/1。全部0失败、0跳过，Python有5条既有弃用warning。两轮独立安全/规格复核无剩余可确认P0/P1/P2。新增分类只读模式不写计划文件；0计划服务端拒绝空任务；2531全保护保留数量真实为2531。截图、原始日志及最终准确SHA的CI列表统一归档在 `C:/Users/jorsam/.codex/visualizations/2026/10/19/p0-material-governance/`；提交推送后的 `CI_FINAL.json` / `CI_FINAL_ACCEPTANCE.md` 记录完整SHA、实际提交、所有Actions/Jobs终态和未触发清单，避免文档自引用SHA或借用旧绿色。

本段此前验收时尚无现场只读证据；后续用户已提供具体任务与同步锁证据，最新诊断/修复以顶部精准修复节为准。部署后实际分类仍需只读复验；不执行生产删除，不修改历史证据或正式VERSION。

### 2026-10-19 接续执行计划（TQ-04 类别指标边界）

基线 `e1d4582187e0d405df14caaa9db0bde11a08519c`，已重新 fetch，长期分支工作树纯快进同步且干净；准确 SHA 的22次 Actions均success。执行采用现有 Owner 内最小修复，不重做已完成的总体指标/Val优先级/绑定。

- [x] RED：扩展 `tests/unit/test_training_metric_credibility.py`，对四类 per_class 指标的 NaN/Inf/越界/bool/非法字符串要求成功评测拒绝，失败/旧缺失保留 null，真实0保留；明确 evaluated 行缺关键指标不得归档为完整评分。
- [x] GREEN：`training_evaluation.py::build_evaluation_truth` 在同一标准化入口共用有界数值校验，不新增评测器。no_test_ground_truth 保持null与FP证据，不读写旧Snapshot/历史结果。
- [x] API：在 `test_training_metric_credibility_report.py` 将真实标准化结果交给现有报告API，断言null/0与Val/Test源保持一致。
- [x] Chrome RED→GREEN：`training-evaluation-diagnostics.spec.mjs` 覆盖无GT/旧缺失/真实零的F1；仅调整原页面已有F1投影，必要时同步既有资源缓存合同。
- [x] 类别指标批次已完成定向Python/API/bundle/Worker、完整Node、真实Chrome、范围审查、普通推送及准确SHA CI；后续metadata提交独立按最终HEAD验收，不借用首批绿色。生产97%模型、OSS/A800/摄像头证据仍待现场只读验收。

### 本批已证明的缺陷与本地验收

- **复现**：逐类指标仍用 `_finite(...,0)`，首轮定向32 failed/2 passed（30 deselected），成功非法值未拒绝、缺失伪0、显式evaluated缺关键项；Chrome首轮在布尔值被显示为100%处稳定失败。沿调用链再复现2项：无GT诊断的Recall/AP被伪造为0，类别缺证据仍可建议ready_for_business_validation。
- **最小修改**：既有evaluation标准化入口的总体/类别共用同一有界分数检查；明确evaluated成功行必须四项完整，未声明的旧行保留legacy_unknown和null。失败状态不改变；真实0保留；noGT保持N/A及FP。现有iteration decision的未知值不再用0比较，增加class_metrics_unavailable人工复核；真实GT零TP诊断仍优先。已归档旧报告只读展示，不批量重算。
- **前端**：原pct429在本IIFE统一校验单位分数，保留合法历史数值字符串，拒绝bool/数组/空白/非有限/越界；F1缺任一值保持不可用，不把null算成零。沿用原诊断卡片展示“类别指标证据缺失”。正式accuracy写入源为Ultralytics单位mAP，未发现需要0..100猜测式兼容的正式合同。仅app.js入口缓存改为42.25.391，main/styles仍42.25.390，VERSION仍42.24.356。
- **测试与原始日志**：7份Python单元/API/真实bundle/盲测/Worker测试111 passed（5条既有弃用warning），`C:/Users/jorsam/.codex/tmp/tq04-class-python-final-20261019.log`；完整Node991 passed/0 failed/0 skipped，`tq04-class-node-20261019.log`；真实Chrome两规格最终结果见`tq04-class-chrome-green-20261019.log`。未删除失败用例或放宽断言。两条旧模拟夹具自称evaluated却仅给AP，现提供完整模拟Precision/Recall/AP50/AP50-95，而非回退生产门禁。
- **独立复核**：只读审查未发现剩余P0/P1/P2；确认唯一正式评测生产者始终提供四项分数，旧行兼容与Production/failed/zero优先级不被破坏。
- **范围**：本批关闭类别分数、诊断及F1的已证实缺口；总体分数前置修复和正式Val优先级不重复修改。Snapshot v3/manifest/图像/隐藏GT的既有verifier及训练最终归档调用保持不变，真实文件/篡改与Worker回归通过，不把静态连线检查当成全部实测。相机来源/近重复、协议现场输入及97%生产模型尚不能宣告验收。
- **提交/CI**：提交后记录实际代码SHA；只以最终HEAD的全部实际触发Actions/Jobs为验收。CI原始证据位于 `C:/Users/jorsam/.codex/visualizations/2026/10/19/tq04-class-boundaries/`，它是本文的测试附件，不是另一份专项问题清单。

### 同批 P0-3：Snapshot/YAML 冻结合同补缺

- **首批代码提交**：`2f6a19bfce1605baca6fa4e92606bf9149178328`；类别指标与报告展示的代码及本地验收已完成，后续提交不借用该SHA的CI结果。
- **真实缺陷**：用现有 `test_portable_dataset::_source` 创建真实JPEG/YOLO包，修改Snapshot类别而不更新manifest SHA，完整verifier仍通过（远端resolver会拒绝）；修改data.yaml的names或Train/Val路径时，两入口均误通过。训练最终归档只调用完整verifier，存在冻结身份与实际执行类别/划分不一致风险。定向先跑12场景为11 failed/1 passed；没有操作真实素材。
- **修复位置**：只改 `training_tasks.py` 已有construction/full verifier；完整验证补Snapshot SHA与身份检查，同文件私有YAML合同片段由原两入口共享。对manifest≥3且Snapshot≥3核对冻结类别目录、原生成器path/train/val布局及禁止Test进入训练YAML。仍逐文件验证图片/隐藏GT；不创建第二验证器、Owner或并行绑定字段，不改变划分、GT、Snapshot及调度。
- **历史兼容**：严格YAML合同仅适用已有v3冻结证据；旧Snapshot/manifest保留原布局与缺字段语义，不偷偷重写或升级。独立复核实际验证manifest2缺Snapshot SHA与schema2自定义布局继续通过；这些旧数据不因此获得bundle_verified新证明。
- **新增/复用测试**：同一原测试文件增加6种真实篡改×本地/远端2入口；原17项portable测试通过。短路径运行portable、bundle cache/isolation、Worker、input-integrity chain、metric credibility/evaluation、报告API八文件：150 passed/3 skipped，日志 `C:/Users/jorsam/.codex/tmp/tq04-bundle-metadata-final-20261019.log`；全部新篡改场景实际执行。3跳过不计通过，待对应Ubuntu测试执行核验。
- **如实保留本地差异**：扩大初跑为43 passed/2 failed/2 skipped（`tq04-bundle-metadata-green-20261019.log`），两失败分别为既有Windows手动8 Workers超过4上限，以及默认长临时目录WinError206。原资源代码/用例本轮未修改，不为全绿取消限制；改用新短目录后cache/chain通过，手动8 Workers差异沿用既有审计且不冒充本地全仓通过。该Linux专项以最终Ubuntu CI为准。
- **独立复核**：确认v3问题关闭，旧格式兼容；无剩余可报告P0/P1/P2。本轮未访问生产，实际97%任务、A800、相机邻帧/未知来源仍待现场。

### 本轮准确提交与验收证据索引（2026-10-19）

- 类别标准化/报告/API/UI代码提交：`2f6a19bfce1605baca6fa4e92606bf9149178328`。本地Python111 passed、Node991 passed、真实Chrome16 passed；准确SHA的全部41次Actions **41 success/0 failure/0 running/0 queued/0 cancelled**，114/114 Jobs success。初次停留checkout的Remote Cleaning作业最终正常完成，未取消、跳过或改CI。原始完整列表：`C:/Users/jorsam/.codex/visualizations/2026/10/19/tq04-class-boundaries/CI_CODE_2f6a19bf.json`。
- Snapshot/YAML共享校验代码提交：`02884bfe0fdc971a463dc4a416f73f8104a9d89a`。17项portable真实篡改/旧兼容通过；相关组合150 passed/3 skipped。三个Windows跳过实际是符号链接文件/目录创建权限，不是新增篡改用例跳过；最终Ubuntu必须核实这些原用例实际执行。
- **最后交接提交与CI**：本索引所在提交包含上述两个代码提交；为避免文档自引用SHA伪造，推送后按真实最终SHA导出的 `CI_FINAL.json` 和 `CI_FINAL_ACCEPTANCE.md`（同一附件目录）记录准确HEAD、全部Actions/Jobs、触发路径、关键日志与未触发清单。本段不将metadata代码未经执行的CI提前写绿，也不沿用2f6a19bf结果。该目录仅保留本文的原始验收附件，不是平行问题清单。
- 正式VERSION仍42.24.356；未修改生产GT/Test/Snapshot、服务或数据库。下一项仍按本文TQ-04持续核对成功Test完整性/推理协议与模型目录证据，以及TQ-02真实来源/邻帧/近重复；没有真实97%任务时只标记待现场只读验收，不声称泛化或事件准确率已验证。

- 仓库：`jorsamj/aixunlianpingtai`；唯一长期开发分支：`feature/external-algorithm-publishing`。
- 开发起点 HEAD：`e30a676276b741d14c30e1674edf5fc86a6e377b`；正式 `VERSION.txt`：`42.24.356`（不得擅改）。
- 本文为**跨会话持久化的唯一专项进度入口**。每一项必须写明复现证据、影响边界、修复提交、测试结果及后续事项。
- P0/P1 表示工作顺序，而不代表已有确凿生产缺陷。缺陷须经代码路径及失败测试证实；未知的生产状况必须标记“待现场核验”。
- 不重建 MaterialRepository/AnnotationRepository，不自动修改 GT、冻结 Test、Snapshot、历史模型或 103455 张生产素材；不进行生产部署。

## 问题登记与状态

| ID | 优先级 | 问题 | 初始结论 | 状态 | 主要代码 / 验收 |
| --- | --- | --- | --- | --- | --- |
| TQ-01 | P0 | Train/Val/Test 多类正样本及来源覆盖 | 现有分组隔离；完整分层不保证 | **阶段二已提交：Ubuntu/Windows 定向回归通过，生产数据待验收** | `training_splits.py`、`training_tasks.py`；按类独立图片/框/来源证据 |
| TQ-02 | P0 | 视频邻帧、近重复和缺失来源元数据导致疑似泄漏 | 已隔离 SHA/已知关系；未知来源需保留未知状态 | 待核验 | 导入扫描与 split；不可跨组，不能假装未知已安全 |
| TQ-03 | P0 | 训练选择的正式标注质量准入不统一 | CLEAN 审计不等同训练准入 | **第二阶段原始 GT/投影复核完成代码验收；生产及 UI 待验** | `annotation_quality.py` + freeze；按严重度区分阻断/人工复核 |
| TQ-04 | P0 | 97% 高 Val mAP 的真实可信度 | 无实际任务报告，不能宣告指标伪造 | **第一阶段可信度证据诊断已编码，真实 97% 任务仍待核验** | Val/Test 指标分离、分组来源、测试支持量、推理协议、人工复核 |
| TQ-05 | P0 | Ultralytics `ap_class_index` 与 `box.maps` 类别对应有潜在错配 | 已证实 compact 数组与 dense `maps` 被按位置混用、NumPy 真值判定可能失败 | **修复与 CI 已通过；历史模型报告未重算** | `train_worker.py`、定向 Python 单测；丢类、稀疏 class_id |
| TQ-06 | P0 | 无 GT 类别及独立测试结果可评估性提示 | 总体 mAP 可隐藏测试中无正样本的已声明类别 | **后端修复与 CI 已通过；页面展示待验收** | `training_evaluation.py`、质量中心；不得宣告零样本类别合格 |
| TQ-07 | P0 | Val/Test 推理 `imgsz` 等协议证据未完全统一 | 常规 Val 与双路径盲测未全显式传 imgsz | **修复与 CI 已通过；A800 实际尺寸仍待实测** | `train_worker.py`、`checkpoint_validation_worker.py`；真实推理参数留证 |
| TQ-08 | P0 | 历史受保护重复素材与 GT 训练冲突 | 2531/1041/0 为用户生产截图；仅可验证 request-only 失败引用可释放，真实依赖不解除 | **本地统一治理闭环已验收；最终SHA CI及生产引用分布另核验** | 同一MaterialBatch/DELETE_INDEX、历史 Task/Snapshot/Test保护；不删除真实素材 |
| TQ-09 | P1 | 正负与困难样本质量及补充闭环 | 现有困难样本模块；正式 GT 不自动重写 | 待设计 | `hard_sample_mining.py`；误报漏报来源及可复核证据 |
| TQ-10 | P1 | 场景、夜间、相机等分布完整性 | 依赖元数据，不可捏造 | 待设计 | 聚合统计明确已知/未知 |
| TQ-11 | P1 | best.pt→ONNX→RKNN 转换后精度与板端验证 | RKNN converted_unverified 不等于精度合格 | 待硬件核验 | 同测试集/预处理/后处理及芯片实测 |
| TQ-12 | P1 | 检测指标与睡岗/脱岗等业务告警准确率混用 | mAP 不代表事件准确率 | 待设计 | 事件规则/时长/误报每摄像头小时分别展示 |
| TQ-13 | P1 | 质量问题诊断不能直接到可治理对象 | 必须复用现有标注/质量中心 | 待设计 | 质量问题→证据→人工修复→重预检闭环 |

## 具体执行约束与顺序

1. **优先修复指标真相 TQ-05**：先证明类别失配，再最小范围修复；保留 Ultralytics 指标真相；不得补造历史指标。修复同时验收稀疏类别、多类别、缺失类别、单类别。
2. 随后 TQ-06/TQ-07：记录指标支持范围与模型推理协议，先保证评测可信。
3. 之后 TQ-01/TQ-03：以真实训练选择质量为对象，保留关联组和冻结合同；如果不可分层不得静默牺牲隔离。
4. TQ-02/TQ-04/TQ-08 需要生产和原始图像证据，不能用 Mock 或模拟断言“现场已解决”。
5. P1 按最小增量逐项收口，避免一个巨大 PR/提交改变训练数据真相。
6. 每项变更都必须追加：`提交 SHA`、`测试名称/通过数`、`CI exact SHA`、`未验证项`。失败测试不能删除或标为跳过。

## 需要现场核验的历史证据

- 重复素材截图口径：总 103455；问题 2531；问题组 1041；删除计划 0，未实际执行删除。
- 重复 GT 内容 SHA256：`0dcb43b6fa1c0678d1c4094c93403678aae9cbaac28419c2fbf4cfd9120c5e9e`。
- 冲突图片 ID：`57512edb455f4b16`、`11916bbdb5c64595`。
- 用户反馈约 97% mAP，尚无对应实际模型、Val/Test 协议、各类支持数量，不能断言是真实泛化或漏数假象。

## 本轮结果区

- 2026-10-18：登记全部 13 项，专项问题登记提交 `632447488725797f16a87e033a41b1bfb56ed0f2`。
- 2026-10-18：TQ-07 显式传递 `imgsz` 到常规 Val 和双路径盲测，新增实际推理 `predict_imgsz`、`predict_conf`、`predict_nms_iou` 的协议归档；协议 SHA 随图片尺寸变化而变化，旧报告不伪补协议参数；增加 Python AST 调用链保护及协议身份回归测试。未在 A800 上实测，等待最新 SHA CI。
- 2026-10-18：TQ-06 首轮 CI 曾有明确回归：对 no-GT 类别的 `None` 召回率执行 `float()` 导致盲测失败，Release Regression / Remote Training Runtime 实际日志均命中。现修改弱类别排序只遍历已有正 GT 的 `scored`，保留 no-GT 类别单独诊断并重跑最终 CI。
- 2026-10-18：TQ-06 补全独立测试类别覆盖合同：按模型类别目录补齐无 GT、无预测类别；无正 GT 类的 Precision/Recall/AP 标记 N/A，不再伪装为实测 0；保留 FP 证据；宏观 mAP 仍仅基于 GT 正样本类别；新版 evaluation truth 持久化 `class_coverage`，决策层将缺少 Test GT 的类别列为人工复核，不更改历史评测；已添加高分但缺少类别覆盖的回归测试，待 CI。
- 2026-10-18：TQ-05 在 `train_worker.py::build_report_from_metrics` 修复：紧凑数组按 `ap_class_index` 关联真实 class_id；`box.ap` 按位置读取，`box.maps` 仅按 class_id 索引；NumPy 数组不再使用 `or []` 真值判断。缺少身份映射时不伪造每类指标，仅保留独立总体指标与明确的 `report_error`；新增稀疏类别、无指标类别、NumPy、无映射、非法索引单测。已加入 Training Final Validation Hardening 和 Release Regression 的真实 Python 测试步骤，需以最终 SHA 验收。未处理历史版本指标重算。

## 第一批 CI 验收记录（2026-10-18）

- **被完整验收的代码 SHA**：`5a949611a00a129cebeb3670770ca3f6c6030ee5`，对应 TQ-05、TQ-06、TQ-07 的修复和针对性测试。
- GitHub Actions（该 SHA 实际触发的）：**25/25 success**、0 failure、0 in progress、0 cancelled。
- Jobs：**64/64 success**；逐次独立核验每个工作流的 Job 结果。
- 重点工作流：`v42.25 Release Regression`、`Training Final Validation Hardening`、`Remote Training Runtime`、`Frontend Runtime Stabilization` 均成功。
- TQ-05：按 `ap_class_index` 取真实 class_id；NumPy 类型安全和稀疏、未测类回归。
- TQ-06：新增 `class_coverage`，no-GT 类指标 N/A，宏观平均仍只统计可评估类别；CI 中发现并修复“弱类别排序对 None 调用 float”回归，证明跨 Ubuntu/Windows 检查。
- TQ-07：常规 Val 与双路径 Blind Test 显式传入 `imgsz`，盲测协议记录实际 `predict_imgsz`/`predict_conf`/`predict_nms_iou`，不同尺寸有不同协议 ID。
- **验收范围声明**：实际触发的 25 类工作流已通过，并不意味着未触发的其余工作流被验证。没有生产 A800 或 RKNN 板端实测；没有修改历史 GT、Test、Snapshot 或生产素材；没有部署、重启服务、改变 `VERSION.txt`。
- 第一批已完成 3/13 项“代码层 P0 修复”，**还有 10 项待办**。TQ-06 前端“无法评估”状态可读性、TQ-07 真实生产预处理/图片尺寸验收仍是后续补充项，不得宣告整体生产质量验收完成。

## TQ-01 阶段一（2026-10-18）

- 仅将可信视频/拍摄会话来源标记为来源已知；普通 group_id 与视觉近重复组只用于隔离，不冒充真实拍摄来源。
- 在训练输入冻结质量证据中加入逐类**正样本图片数**、**标注框数**、**不可拆分组件数**、各集合**confirmed_empty 负样本数**、可靠来源字段已知/未知数量。
- 对训练类别在独立 Test 缺少正样本发出不参与对应类别评测的警告；不虚构样本量、不用阈值/百分比分数冒充真实准确率。
- 新输入冻结启用 schema_version=1 的附加 `class_coverage`；老冻结仍计算旧结构，恢复校验时根据旧记录是否携带新字段判断，避免历史冻结因新版诊断新增字段而无法复验。
- **阶段二尚未实现**：真正多类别分层/抽组优化，必须结合 20k 组规模性能、固定 Test、SHA 关联组、旧快照重放、无法满足稀有类的可解释诊断，单独开发验证。
- 提交和最终 SHA 的 CI 请以本轮实际运行结果为准。没有生产数据或 OSS/A800 操作。

## 下一批严格顺序

1. TQ-01：带可信来源关系的多类别/分组划分与正样本分布合同；先做隔离失败用例，不放宽跨组保护。
2. TQ-03：针对当前训练选择而非过去 CLEAN 任务的正式标注质量检查；按错误/警告/需人工确认分类。
3. TQ-02、TQ-04、TQ-08：按真实生产来源、97% 模型实际报告和历史 2531 张保护引用做只读验收；不使用模拟数据宣称生产已解决。
4. P1：困难样本、场景覆盖、RKNN 板端实测和业务准确率专项逐项完成。


## TQ-01 阶段二｜2026-10-18 分组多标签分层代码候选

- **根因（经代码审计）**：旧 `_select_grouped` 仅以单组图片数量做精确子集和优化，未把各类别正样本/confirmed_empty 负样本纳入目标，因此能出现某一类别全部进入 Train 或缺失 Test 的情况；已有去重和关联组件隔离本身正确，不得放松。
- **修改文件**：`platform_core/training_splits.py`、`platform_core/training_tasks.py`、`tests/unit/test_training_stratification_v2.py`、`.github/workflows/v42.25-release-regression.yml`、本追踪文档。
- **实施**：新冻结采用 `multilabel_grouped_v2`，以不可拆分组件为原子单元进行稀缺类别优先覆盖与多类图片数量欠额填充，负样本纳入平衡；随机 Test 阶段在可能时为训练/验证保留两组，Val 阶段为 Train 保留至少一组；仍保留 SHA/视频/拍摄会话/近重复关联组隔离、固定独立 Test 原名单和独占 Test 的不可变约束。
- **旧任务兼容**：旧冻结无 `split_strategy` 标记时继续走 `legacy_v1`，不按新算法重排历史 Snapshot；新冻结在 digest 与恢复时记录、复核相同策略。
- **诊断**：新策略在 `input_quality.class_coverage` 下留存 `partition_diagnostics`（类别组件供给、实际覆盖集合、缺口原因）。当类组件不足、固定 Test 缺少正样本或多类耦合/配额限制时，不谎称类别已独立评测通过。
- **测试设计**：包含多类+负样本跨 Train/Val/Test、两组稀有类、同视频及已知近重复、固定 Test 不能迁移、旧策略重放、20k 不可拆分组规模。
- **提交 SHA**：算法、冻结版本化及首轮测试 `53fc6fcffd1621d90b54481454dd5e82023b6979`；将定向新测试加入 Ubuntu/Windows Training Input Integrity 的后续提交 `3c1d222550f711918cd249febd07e028ee711611`。
- **定向测试实测**：Training Input Integrity 同一 Git SHA `3c1d2225` 的 Windows、Ubuntu 24.04 均通过；每系统 split 相关测试 **23/23 passed**（包含新增 6 个分层回归），其余同一作业测试批次分别 **30/30、62/62、2/2 passed**。新测试未跳过。
- **CI 核验边界**：在代码/CI 补强提交 `3c1d2225`，GitHub Actions 连接器返回的首页 **20/20 success、0 failure、0 in progress**；该接口只返回首页 20 个工作流，未见到的其余可能触发工作流尚不能声称成功。生产 A800、真实来源分布、独立 Test 现场验收仍待完成；不得把代码通过等同真实泛化准确率已提高。
- **安全边界**：未执行生产数据修正、素材删除、Test 迁移、生产部署或 VERSION 修改；TQ-02/TQ-03/TQ-04/TQ-08 等任务保持原有待办状态。

## TQ-03 初步代码审计（暂未修复）

- `platform_core/annotation_quality.py::_audit_boxes` 已有无效/越界/极小/重复框和标签目录检查，但是 `audit_cleaning_annotations` 只针对冻结 CLEAN 选择执行，所有单图问题默认以 warning 记录，并不能自动成为当前训练选择的分级准入。
- `platform_core/training_splits.py::_valid_annotation` 只验证 annotated 非空和 confirmed_empty 无框/范围，不检查坐标是否有限、几何有效性及类别目录有效性；`freeze_training_inputs` 未复用 CLEAN 审核。
- 因此 TQ-03 **真实缺口成立**。下一阶段应复用单图审计检查，对本次选择在 Freeze 前实现“阻断/警告/人工复核”准入，并把可重放的质量证据纳入新冻结合同。完整 GT/训练投影差异需区别合法训练任务标签过滤与非法丢框，不能简单要求投影与原始 GT 完全相同。
- 保持生产只读、不得自动修改 Ground Truth。当前仅审计，**不声称 TQ-03 已修复**。

## TQ-03 第一阶段｜训练前正式标注只读质量准入（2026-10-18）

- **真实根因**：CLEAN 标注审核具有图片框校验，但没有用于本次训练输入 Freeze；旧冻结只检查标注状态/重复冲突，不提前对越界、零面积、非有限坐标、标签目录不一致做分级阻断。
- **修改文件**：`platform_core/annotation_quality.py`、`platform_core/training_tasks.py`、`tests/unit/test_training_annotation_admission.py`、`.github/workflows/training-input-integrity.yml`、`.github/workflows/v42.25-release-regression.yml`、本文件。
- **修复原则**：对当前冻结、已完成训练标签投影的正式 GT 进行只读扫描；阻断确定性无效框/标签/状态，极小框、极大框、疑似重复框及未复核标志归入人工复核，未知尺寸等归人工复核；`confirmed_empty` 明确支持合法负样本。对 `xyxy` 与 `cxcywh`（归一化或像素）按现有 YOLO 导出语义判断。不得自动删除、改写正式 GT 或修改固定 Test。
- **性能**：只遍历本次已在 Freeze 内存中的选择、不重复全项目查询；每图最多 32 框做高成本两两 IoU，超出时仍检查所有框的精确重复和非法几何，并明确记录 `box_pairwise_unchecked`，不得谎称完成全量近重检查。
- **冻结证据**：新冻结 `input_quality.annotation_admission` 留存 severity counts、issue counts、少量示例 ID、审核范围和未知尺寸数量；恢复时从相同冻结行重算证据；老冻结不具有此键时继续旧质量合同验证。
- **验收项**：越界、零面积、NaN、无效类、归一化中心宽高越界；负样本、合法框、极小/重复框人工复核；大量框降级判定；新旧输入冻结兼容。需进一步核对 GT 到投影的合法标签过滤和历史留存语义；本阶段只核查**投影后的本次训练 GT**，不宣称对被合法过滤的所有来源框完成审核。
- **待办/风险**：未在 A800/生产 103455 张素材上执行；缺失尺寸仅提示人工复核，不会假装已完成边界检查；对同 SHA 不同原始 GT 冲突仍交给现有重复安全审计；UI 阻断/警告/复核展示与实际正式数据验收尚待继续。
- **修复代码 SHA**：`ae31b946ee1acc8b107d5db808f26dd36e3170da`（Fast-forward 推送至长期开发分支，未修改 VERSION）；本轮单独代码修复涵盖 `annotation_quality`、`training_tasks`、新增 11 项冻结质量单测及两个 CI 工作流测试路径。
- **单元/回归验收**：GitHub Actions `Training Input Integrity` 的 Windows latest 与 Ubuntu 24.04 两个 Job 均为 success。各平台拆分+标注准入组合测试 **34/34 passed**，其余同一作业批次 **30/30、62/62、2/2 passed**，未使用跳过。新测试验收及此前 TQ-01 23/23 分组回归均有证据。
- **CI 范围声明**：代码 SHA `ae31b946` 最终读取的 GitHub 工作流首页 **20/20 success、0 failure、0 in progress**；Remote Training Runtime 实际 4/4 Job 成功。该检索接口只返回首页最多 20 条，未触发/未列出的其他工作流不得算作通过。完整首次 Actions、生产 A800 训练及真实素材来源还需另行验收。
- **状态**：第一阶段只读阻断/复核与冻结证据**代码已完成，定向验收通过**。TQ-03 的原始 GT 与合法标签投影完整交叉核验、前端分级展示、现场回归属于后续阶段；TQ-03 不标记“完全解决”。


## TQ-03 第二阶段：原始 GT → 任务投影一致性（2026-10-18）

- **确认根因**：第一阶段的 `_training_annotation_admission` 针对投影后的训练标签做几何准入。被任务标签筛除的原始框没有进入该检查；但这些排除框仍用于训练图片像素遮挡/擦除，非法框可延迟到 Worker 的 `_apply_training_projection` 阶段才触发错误。已有 `project_training_rows` 是唯一合法投影算法，不应该再开发一套任务投影。
- **本轮变更**：在现有 `freeze_training_inputs` 中增加 `_training_source_projection_admission`，复用现有单图审核：先对同次围栏读取的**完整来源 GT** 检查非法框、框坐标、来源类别，之后用原有 `project_training_rows` 从相同原始行重新计算合法投影并逐图片比较 `boxes`、`annotation_scope`、`source_annotation_hash`、`training_excluded_boxes`、投影政策、投影摘要、任务负样本标记及素材基本身份。禁止静默丢框或用伪造投影摘要绕过原始标注。
- **保持合法规则**：任务不需要的标签允许被排除，仍必须保留 `training_excluded_boxes` 并执行原像素擦除；仅剩排除类的图片可以成为 `negative_origin=redacted_unselected_labels` 任务本地负样本。整个过程只读，原始 GT 不被回写/删除。已存在的独立 Test 和同 SHA 重复保护不放宽。
- **新版冻结证据**：`input_quality.source_ground_truth_admission` 记录原始 GT 的审核结论，`projection_consistency` 记录核验图片数、排除框总数及任务本地负样本数。两者包含在 `input_freeze_id` 中；恢复不读取会变化的实时 GT，而是验证原始源 GT 摘要清单、审核元数据和冻结摘要。源 GT 原始框不会双份写入冻结合同，恢复时不能冒充重新审计了历史 GT。
- **兼容性**：历史冻结不含此两字段，仍走原重放逻辑。旧任务、Snapshot、版本报告和 VERSION 不修改。
- **新增测试**：原 GT 被排除框为零面积时冻结阻断；合法排除框与 task-local negative 不被误杀；伪造已选择框/排除框/政策摘要/审核范围/负样本标记无法通过；原始 GT 后来更改也不影响历史冻结重放。
- **修改文件**：`platform_core/training_tasks.py`、`tests/unit/test_training_annotation_admission.py`、本文；继续使用已存在的 Training Input Integrity、Release Regression 测试入口，无需新建架构。
- **待验收**：代码提交 SHA、定向 Python/Ubuntu/Windows、完整 GitHub CI 以及原 A800 生产数据均以实际核验为准；UI 对人工复核提示的集中展示仍需后续单独验收。

## TQ-03 第二阶段代码及 CI 最终实测（2026-10-18）

- **根因确认**：只审核任务投影后的标签可能漏掉必须用于图片遮挡的原始排除框，导致原始无效几何直到 Worker 才失败。修复基于同次受锁保护的原始 GT 及原有投影函数，不新增 Repository。
- **修复 SHA**：`87e223b74dd34705ceb16c5a0d80aa04ed7f959d`（原始 GT 与合法投影交叉验证）；`9eabbb56a116c1c439ccb7ee9e0a7fbb89363318`（项目标签目录存在但全部 inactive 时，排除类也必须 fail-closed）。
- **代码修改**：`platform_core/training_tasks.py`，`tests/unit/test_training_annotation_admission.py`，以及本追踪文档。保留已存在的 `annotation_quality.py` 单图审计、`training_label_tasks.py::project_training_rows` 原有语义；没有添加第二套标注系统。
- **定向 Python 测试**：最终代码 SHA `9eabbb56` 的 Training Input Integrity：**Ubuntu 24.04 和 Windows latest 各 43/43 passed**（训练切分、第一阶段质量准入、原始 GT/投影篡改/重放及 all-inactive 标签目录边界）；同一两 OS 作业另三批 **30/30、62/62、2/2 passed**，没有失败和跳过。
- **GitHub CI**：在 `9eabbb56` 上通过连接器可查询的首页工作流 **20/20 success，0 failure，0 running**，只统计实际返回的前 20 个；其它未列出的工作流不作为通过证据。上一提交 `87e223b7` 的首页同样 20/20 success。
- **冻结合同兼容**：新 `input_quality.source_ground_truth_admission` 和 `projection_consistency` 参与冻结 SHA；Worker 恢复不查询可能已经变更的在线原始 GT，也不假装从冻结摘要重算全部源框；历史没有这两项的冻结继续兼容。
- **仍待解决**：正式 UI 中阻断/警告/人工复核的可视化提示；全部图片来源标签治理目录缺失时只能使用兼容回退，不能声称来源目录完整；生产历史素材与 A800 真实运行仍未验收；没有证明 97% mAP 的真实泛化效果，TQ-04 保持未完成。
- **安全**：未部署生产、未修改 VERSION、未修改或删除任何 GT/历史 Test/Snapshot/素材；Git 推送均使用 Fast-forward，未 force push。

## TQ-04 第一阶段｜高 Val mAP 可信度诊断（2026-10-19）

- **真实缺口**：`train_worker.py` 持久化的 `training_report.metrics` 属于完成后重跑的 **Validation** 指标；独立 Test 在 `training_report.test_result`，并经 `build_evaluation_truth` 冻结。这两个数不是同一统计对象，更不等于烟火等业务事件的实际告警准确率。目前在任务最终提交时尚没有联通“Val 高分→Test 正样本类别/数据来源/测试组/运行协议”的统一证据诊断。约 97% 是用户报告，尚无对应真实报告/模型可核证；不能视作伪造或真实泛化已达 97%。
- **新增后端诊断**：`platform_core/training_evaluation.py::build_training_metric_credibility`，只消费已经存在的持久化 Val、独立 Test、冻结 `input_quality.class_coverage` 和 GT 人工复核证据；**绝不重新定义/覆盖 mAP**。mAP50 ≥ 0.95 仅作为**审阅触发阈值**，不是造假判定阈值。Val–Test ≥ 10 个百分点、独立 Test 缺失或失败、类别未测、来源元数据未知、类正样本图片 < 5、独立来源组件 < 3、推理协议或不可变输入绑定缺失、需人工复核标注等都生成可解释的 `reason_codes` 和操作建议。5/3 仅为保守人工复核提示阈值，不是统计置信区间或实际精度指标。
- **决策联动**：新任务的诊断报告同时落到 `result.json` 与算法版本 `metric_credibility`。仅当高 Val 分数且存在证据风险时，既有 `build_iteration_decision` 不再建议 `ready_for_business_validation`，改为 `review_required`；不自动调参、不启动重训练、不替换独立 Test、不改 GT。历史调用/旧版本未携带 `metric_credibility` 时保持旧决策行为以便重放。
- **证据边界**：来源未知不是泄漏已证实；没有证据也不是无泄漏。即使 Val/Test 都高且覆盖完善，仅给 `held_out_evidence_present`，明确 `leakage_conclusion=not_determined` 和 `production_accuracy_verified=false`，业务准确率要另行按事件级 FP/漏报/摄像头小时验收。独立 Test 默认没有不可变 bundle binding 的历史训练版本不能静默冒充已完成严格输入绑定。
- **验收**：新增 `tests/unit/test_training_metric_credibility.py`（仅人工构造的**测试输入**，不冒充真实数据），覆盖 97% 无 Test、Val/Test 大差距、来源未知、Test 缺类、小类/少来源、缺协议/输入绑定、GT 人工复核、非法或 NaN 指标、阈值边界、历史兼容、建议联动、重复性。添加到双系统 Training Input Integrity 和 v42.25 Release Regression 的必跑测试。
- **仍待现场**：按用户那次实际 97% 训练任务获取其冻结 Snapshot、Test 真值、各类别样本/组件数与相机视频来源，核验误报漏检与模型输出；不得假设能访问生产 A800 或原始图像。前端可读性和业务事件准确率属于下一阶段。
- **版本及安全**：VERSION 保持 42.24.356；本轮仅远端长期开发分支代码和回归测试，未部署生产，未删改任何真实素材。


### TQ-04 验证证据补强

- 在定向测试第一轮 Ubuntu/Windows **均 62/62 passed** 的基础上，再补防伪证据校验：独立 Test 必须有至少一个真实参与评分的正 GT 类别（不能仅返回高分指标却没有 `scored_class_ids`）；真实盲测图片总数与本次冻结选择的已知/未知来源图片数量合计必须一致；模型 Test 类别总量与冻结的任务类目录不一致时给出明确映射复核。三者均属于诊断证据，不能臆断高分错误或自动替换标注。
- 补充回归分别覆盖：成功状态但零计分类、只跑一半 Test 图片、模型标签目录少于冻结目录。合法的高 Val + 高 Test 且类别/来源/图片数齐全情况保持有界通过。
- 注：两次代码更新之间的 CI 必须用各自 SHA 判定，不因上一 SHA 测试通过而宣布最新 SHA 已验证；后续记录最终代码 SHA 的真实 CI 结果。

## TQ-04 第一阶段｜代码提交与最终 CI 实测（2026-10-19）

- **首版代码 SHA**：`7abb8f73122aba508f6aa3dd0b0f335ac717cb3c`，补 Val/Test 分离、mAP ≥95% 审阅诊断、冻结来源和类别证据、人工复核决策、新版结果及版本的 `metric_credibility` 归档。
- **最终代码 SHA**：`acb3e999d83669899601072781690341adffcb99`，新增测试无真实计分类/只执行部分 Test/模型类别与冻结目录不一致时不能把高分归入证据完备；同期补强 `tests/unit/test_training_metric_credibility.py` 和追踪文档。
- **最终 SHA GitHub Actions 全量查询**：基于 `head_sha=acb3e999...` 的 GitHub Actions REST 列表，返回 `total_count=25`、**25/25 workflow success、0 failure、0 running**，没有把未触发的工作流算作成功。重点 `Training Input Integrity`、`v42.25 Release Regression`、`Remote Training Runtime`、`Frontend Runtime Stabilization` 均成功。
- **跨平台定向测试**：同一最终代码 SHA 的 `Training Input Integrity` 两个 Job（Ubuntu 24.04 与 Windows latest）分别 **65/65 passed**；两系统内其它测试批次分别 **30/30、62/62、2/2 passed**，未见失败。
- **运行时链路**：`train_worker.py` 仍将 Val 指标写入 `training_report.metrics`，独立 Test 写入 `test_result`。`training_tasks.py` 在版本完成时读取既有 `input_quality` 和标准化 Test 结果，不修改原指标；新任务报告/模型版本记录 `metric_credibility`。高 Val 分数证据不足时 `iteration_decision` 只给人工复核建议，旧调用没有该参数时保持回放兼容。
- **未完成/不能宣告真实验收的范围**：用户那次约 97% 的生产训练记录和 A800 原始冻结集未读取；真实来源未知的跨摄像头/相邻视频帧泄漏尚不能排除；现有训练最终提交没有对所有版本自动写入 `bundle_verified` 的独立 Test 不可变输入绑定，诊断会保留该待补证据；高分诊断 UI 独立可视化仍待开发；业务事件级的准确率/每摄像头小时误报率、RKNN 板端精度不由 mAP 代表。这是 **TQ-04 阶段一代码完成、真实泛化审计未完成**。
- **安全与部署**：未删除/改写真实素材、正式 GT、历史 Test、Snapshot、模型指标，未连接生产 GPU，未部署、未修改 VERSION（`42.24.356`）；以上所有 Git 更新均为 Fast-forward。

## TQ-04 第二阶段｜训练报告 API 与质量中心前后端真相统一（2026-10-19）

- **核验出的真实断层**：`training_tasks.py::_finalize_completed_job` 已向完成态 Task `result.json` 和算法版本写入 `metric_credibility`，但原 `app.py::v44_training_report` 只根据遗留 `job.json` 构造报告，并没有读取相应持久化结果；`static/app.js` 的训练报告/独立评测也只显示原始 mAP。因此后端判定需复核时 UI 可能展示 97% 却不告知依据和风险，构成前后端真相断裂。
- **后端唯一权威源**：`v44_training_report` 使用已校验 `_durable_training_task(project_id, job_id)` 的 TaskRecord 身份，再读取其 `result.json` 中已提交的 `training_report`、`evaluation` 与 `metric_credibility`；提交完成的 Val 数值不再被 `job.json.metrics` 的旧缓存覆盖。未关联该项目 TaskRecord 或未归档诊断的历史任务 **返回不可用**，不根据当下图片和当前状态重新生成假诊断，不重做 mAP 计算。
- **复用而非嵌套**：仅在已有 `platform_core/reports.py::build_version_report` 补充权威诊断投影；`static/modules/reports.js::metricCredibilityHtml` 是唯一前端展示函数，直接由 `static/main.mjs` 注入已有 `PlatformCore.reports`，被 `trainingReportCore425` 与 `openVersionEvaluation429` 两处原业务入口复用。没有新建平行页面、定时器、状态镜像、API、数据库表或历史数据迁移。
- **清晰区分**：训练报告指标栏明确 `Val mAP50`；可信度卡同时列 Val mAP50、独立 Test mAP50、差值（pp）、实际 Test 图片量与正式复核原因；独立评测从算法版本的原 `metric_credibility` 读取同一份证据。证据缺失明确写“历史证据缺失”，绝不填 0% 或假样本。所有动态文本 HTML 转义，避免 XSS。
- **回归合同**：Python API 单测验证同任务持久化结果覆盖过期 job.metrics、Test/Val 指标不混淆、旧任务显式缺失、版本报告不推断诊断；Node 前端单测验证共用渲染入口、97% 与 72% 的算术展示、缺失值不伪填及未知 reason code 的 HTML 转义。API 单测列入 Release Regression，前端单测走现有 Frontend Runtime Stabilization 的 `node --test tests/frontend/*.test.mjs`。
- **未验收项**：真实用户那次 97% Val 训练模型 / A800 环境仍需现场只读审计；尚未对所有历史 Report backfill 不可变 Test 输入绑定，也未验证真正业务告警准确率。TQ-04 **前后端逻辑待本次实际 CI 完成方可标记代码验收通过**。
- **严守安全**：不改生产服务、GT、Snapshot、历史独立 Test、素材、版本号 `42.24.356`，所有修改限定长期开发分支，禁止强制推送。

### 第二阶段 CI 首轮发现并明确的遗留指标冲突

- 第一轮 `v42.25 Release Regression` 的训练数据合同实测 **291 passed / 1 failed**；失败仅在新增 `test_legacy_report_api_retains_real_record_but_marks_credibility_unavailable` 的历史假设：当 `job.metrics` 与 `job.training_report.metrics` 不同，旧断言要求前者。事实上 `training_report.metrics` 才是已有训练流程记录的 Val 复验结果，前端应采用后者，与 TQ-04 的 Val / Test 证据保持一致。
- 因此**保留生产代码的统一指标优先规则**，将回归断言明确为：有已完成 `result.json` 时用其中的 Val 指标；只有历史 `job.json` 时使用其 `training_report.metrics`，不回退至过期 `job.metrics`；历史不持有 `metric_credibility` 时不擅自补造。
- 此错误不是原有 291 项测试回归，不应通过跳过失败、删除测试、制造假数解决。最终 CI 应在修订后的精确 SHA 重新核验。

### 第二阶段扩展：真实独立 Test 不可变输入绑定

- **补上的最终链路**：已有 `training_evaluation.py::build_evaluation_benchmark_scope` 能将 Snapshot v3 的冻结 Test 身份与已物化的 `work/bundle/manifest.json` 的原图 SHA256、训练像素 SHA256、标签文件 SHA256 和 input policy 绑定，产生 `binding_level=bundle_verified`。以前 `TrainingHandler._finalize_completed_job` 在 `verify_portable_dataset` 成功后未调用它，导致高分诊断长期把独立 Test 输入绑定视为未知。
- **修复**：在同一训练最终归档链路，先校验 materialized bundle 对应当前 Snapshot/Revision，随后用**同一个经过验证的 manifest** 生成 benchmark scope，作为 `build_evaluation_truth(..., benchmark_scope=benchmark_scope)` 的输入并跟随版本保留。新 Snapshot v3 + 完整 manifest 采用严格 `bundle_verified` 身份；v3 Test 实际执行图片数与冻结数不符时沿用现有禁止伪成功保护。旧 Snapshot Schema < 3 返回空 scope，不伪装成完成了真实 Test 身份绑定。该补丁仅加强真实证据，不自动改变历史模型报告、不迁移 Test。
- **测试**：新增真实 bundle scope→evaluation truth→credibility 的端到端函数回归，保护最终归档确实使用已验证的 manifest；检查只改变 Train 而未改变 Test 的基准稳定性与误绑定失败，复用现有 `tests/unit/test_training_evaluation.py` 大量原合同，不重复建设计算逻辑。
- **待验收**：必须在最新 SHA 的 Release Regression/Remote Training Runtime 上确认全绿，以及后续 A800 真正执行完整 independent Test 的现场表现。


## TQ-04 补强：独立 Test 输入绑定与报告展示一致性（2026-10-19）
- **复用现有链路**：同一天另一开发提交已将 `verify_portable_dataset(manifest_path)` → `build_evaluation_benchmark_scope(snapshot, manifest)` → `build_evaluation_truth(...benchmark_scope=)` 串接到 `TrainingHandler._finalize_completed_job`。本轮不复制这套逻辑，也不重建 GT、版本或评测 API。
- **跨层合同**：在唯一后端 `build_training_metric_credibility` 增加 `independent_test_binding_level`（`bundle_verified`、`snapshot_truth`、`unavailable`），参与诊断摘要；`static/modules/reports.js::metricCredibilityHtml` 仅显示持久化的后端等级，不据高 mAP 或缺省值推定“已校验”。旧版本未包含本字段时明示“未记录”。
- **实际文件回归**：扩展已有 `tests/unit/test_portable_dataset.py`，构造真实 JPEG、任务冻结 Snapshot v3、隐藏 Test YOLO GT 及可移动数据包，先由 `verify_portable_dataset` 校验真实文件，再生成 `bundle_verified` 范围并冻结评测合同；篡改隐藏 Test 标注必须在 verifier 阶段失败，篡改 Test 图片也必须失败。无真实 GPU/生产素材参与，测试数据不得充作业务真实准确率。
- **前端及决策回归**：扩展既有 Python `tests/unit/test_training_metric_credibility.py` 和 Node `tests/frontend/metric-credibility-report.test.mjs`，覆盖三种绑定状态与旧报告缺失字段，不新增页面、数据镜像、定时器或重复评分逻辑。
- **遗留兼容**：当前线上历史没有严格绑定的报告继续保留原状，新数据的模型指标不会反写历史 Snapshot。现场 A800 与用户 97% 模型未验证；TQ-04 不标记真实泛化完成。
- **待核验**：最新 HEAD 的 CI 及各脚本均以准确 SHA 验收结论为准；如编译或测试失败只修现有函数，保持 VERSION `42.24.356`，不部署生产。

### CI 依赖镜像失败及无版本变更修复（2026-10-19）

- 在 `c361d7dd` 的 `ChangLian Login Auth / browser` Job 发现真正的外部错误：`npm ci` 从 `registry.npmmirror.com/playwright-core/-/playwright-core-1.62.1.tgz` 下载时返回 **HTTP 503**，并非业务测试失败；同工作流 `contract` Job 成功，但浏览器作业依然不能视为通过。
- 仓库 `package-lock.json` 有 4 处硬编码的第三方 npmmirror tarball 解析地址。仅改为 npm 官方 `registry.npmjs.org`，保持原依赖版本（Playwright 1.62.1、fsevents 2.3.2）以及**全部 SHA512 integrity 完全不变**，以减少第三方镜像的偶发 503。没有修改应用代码或生产依赖行为。
- 该问题应以修改后提交的 GitHub CI 真正成功为验收依据，不能把 URL 修改本身写成已完成实际验收。


## CI 轻量合同测试依赖隔离修复（2026-10-19）
- **失败事实**：本轮代码 SHA `c1d201c9` 的 `Algorithm SQL Store / contracts` Job 中，`test_finalization_passes_verified_frozen_test_bundle_into_independent_evaluation` 执行 `from platform_core.training_tasks import TrainingHandler`，触发轻量测试环境缺少 `psutil`（`ModuleNotFoundError`）；同 Job 91 项已通过，该失败发生在源码连线断言的导入阶段，不是实际训练行为异常。
- **根因修复**：此检查的目的仅是核对 `_finalize_completed_job` 的“verify → benchmark scope → evaluation”调用顺序。改为 Python 内置 `ast.parse` 定位 `TrainingHandler._finalize_completed_job` 并检查原源码片段，不导入训练运行时，也不在 SQL Store CI 增加无关运行时依赖。实际数据包/GT SHA256 行为仍由 `tests/unit/test_portable_dataset.py` 覆盖，避免只有静态断言。
- **验收状态**：依赖隔离改动须以其准确提交 SHA 的 `Algorithm SQL Store` 与训练相关回归成功为准，不把旧 SHA 的失败计为已通过。


## Remote Training Runtime 集成测试与冻结 Test 合同回归修复（2026-10-19）
- **证据**：`03e1baf11b621b066e01d8faae656e7858f551a7` 的 GitHub Actions 经准确 `head_sha` 查得 24 个工作流，22 success、2 failure，失败均为 `Remote Training Runtime` 的 Ubuntu/Windows `preparation-contract`。真实报错来自 `tests/integration/test_training_task_worker.py::test_training_prepare_then_handler_runs_and_commits_verified_result`：`ValueError: evaluation image_count does not match frozen benchmark scope`；该测试先前的 `fake_runner` 声称 Test `status=succeeded`、mAP50=0.75，但未记录 `image_count`，在 Snapshot v3 严格绑定启用后与 2 张冻结 Test 图片不匹配。
- **修复对象明确**：只调整原有集成测试的模拟训练结果，由当前任务已物化、冻结且本身进入 verifier 的 `work/bundle/manifest.json` 读取 `splits.test` 数量，并把 `image_count` 写入模拟的成功 Test 记录。不降低 `build_evaluation_truth` 对真正成功评测的数量门禁，不给生产代码加特殊路径。
- **防退化断言**：完整训练准备/训练归档一体化测试核实 `image_count=2`、`benchmark_scope.binding_level=bundle_verified`、`test_image_count=2`，以及 `result.json` 与归档算法版本使用相同 Test scope。测试使用人工生成的模拟 mAP，并不代表用户那次 97% 训练是真实精度。
- **验收**：须以包含这项修复的实际 HEAD 上 Ubuntu/Windows 的 `Remote Training Runtime` 及其他 GitHub CI 工作流结果为准。仍不部署生产、不修改或删除生产素材、GT、Snapshot、历史模型；VERSION 仍为 42.24.356。


## TQ-04 第三阶段｜独立 Test 指标数值真相门禁（2026-10-19）

- **新确认的代码缺陷**：`build_evaluation_truth` 原来对已提供但非法的 Test 指标使用 `_finite(...)` 的 0.0 默认值。即使评测结果声称 `status=succeeded`，`NaN`、`Infinity`、非法字符串或布尔值也可能被归档成看似实测的 0.0；负数或超过 1 的数值也没有阻断。此问题不能通过前端隐藏解决。
- **最小修复**：仅在现有 `platform_core/training_evaluation.py::build_evaluation_truth` 标准化入口核验 4 种总体目标检测指标；成功 Test 中如出现非有限、非数值、布尔或不在 [0,1] 的已提供指标，明确拒绝归档。失败/未请求评测则保留原状态但不再把非法值写成 0.0；合法的真实 0.0 仍保留。缺失指标继续缺失，不凭空生成。未改独立 Test 绑定、Snapshot、训练数据或旧持久化报告。
- **定向测试**：在现有 `tests/unit/test_training_metric_credibility.py` 增加 6 类非法成功指标、失败评测非法值不伪补零、真实零值保持三类回归。无新的评分模块、API、前端状态或适配层。
- **代码与测试基准 SHA**：`f950bc8390944aa2f93163282478eb067f64bc84`；该基准 SHA 的 GitHub Actions **23/23 工作流成功、61/61 Job 成功**（实际触发，非全仓所有工作流）。本次修复提交的 SHA、CI 结果须随后按远端实际提交追加，不能沿用基准的全绿结论。
- **待核验**：新修复 SHA 的 Python/Node/浏览器相关 CI，以及 A800 实际任务证据；真实 97% 训练任务仍缺独立 Test 现场输入与误报漏报证据。未部署生产、未修改 `VERSION.txt`、未动历史数据。


## TQ-04 报告数据合同补强｜正式 Val 指标优先（2026-10-19）

- **根因**：公共 `platform_core/reports.py::_metrics` 先读记录顶层 `metrics`，后读 `training_report.metrics`。历史 Job 的顶层指标可能是旧缓存（如 .80），正式已完成训练报告为 .96，这使版本报告及算法趋势可能与任务报告 API 的正式 Val 指标不一致。
- **修复**：仅调整现有 `_metrics` 的取值优先级为正式 `training_report.metrics` → 直接记录 `metrics` → 后备 `report.metrics`。版本只有直接指标时保持原结果；不重新计算任何历史 mAP，不新增 API 或前端状态。
- **新增 API/报告回归**：`tests/api/test_training_metric_credibility_report.py` 同时覆盖单版本指标、算法历史趋势和只有旧版顶层指标的兼容场景。
- **前置修复 SHA**：`b0e95b42e56de98d68e3f4d0a580395ba31bdeda`。本项代码提交及其 CI 以 GitHub 当前 HEAD 为准，旧 SHA 的绿色结论不能用于新提交。
- **剩余边界**：生产 97% 训练任务、冻结 Test 的真实样本与板端推理未现场验收；不修改 VERSION、历史结果或生产数据。
