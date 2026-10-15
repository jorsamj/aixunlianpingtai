## 2026-10-12｜版本转换弹窗来源默认值缓存一致性回归

- 旧版版本详情缓存可能不含 conversion_defaults，本次仅对缺字段的历史缓存补请求；具有完整不可变版本训练默认值时复用原历史响应，转换资源仍每次打开实时刷新，避免额外重复 GET。
- 加强现有 Remote Conversion Runtime Chrome 用例：历史请求仍须恰好 1 次、资源请求按次 2 次，同时核验 FP32 / 800 的源训练参数真正在转换创建弹窗展示；不跳过旧断言、不伪造转换成功。

修复前一笔总览变更触发的两条 CI 合同回归：前端/Remote Cleaning Runtime 的 clean-task-view 测试静态校验 main.mjs 旧缓存键 .363；本轮只将严格断言更新为真实入口 .364，不改清洗业务或删断言。

## 2026-10-12｜自动转换也继承源 PT 的训练配置

原 `_v48_auto_convert_version` 自动转换仍把 precision 写死为 FP16；本次移除该硬编码，统一由既有版本转换任务创建入口按训练 lineage、实际 runtime_precision 与目标资源能力决议。手工转换的精度/尺寸显式覆盖不变；自动转换与手动转换共用同一来源合同，避免默认不一致。

## 2026-10-12｜转换默认跟随正式 PT 版本训练参数

- 版本转换 API 从冻结的 `training_lineage.parameters.actual.imgsz` 读取图片尺寸，从源训练任务 `runtime_precision`（包括离线 AMP 回退结果）或 lineage 实际精度读取默认 FP32/FP16；无事实时不从 PT 权重 dtype、请求 AMP 开关猜测运行精度。转换前端以所选版本原始参数填充（800/640 等），历史未记精度则告知未知。
- RKNN 资源能力白名单原样保留：训练 FP32、RKNN 仅支持 FP16 时，前端可见兼容性提示，转换选择 FP16；切换到允许 FP32 的格式恢复默认训练精度（未被手动改写时）。手动更改精度/尺寸可覆盖默认值。后端补齐省略参数，存档原训练精度与尺寸，不让默认精度冒充训练实际精度。
- 复用已有转换弹窗、资源检测、任务入口、Worker 与版本 Owner；不改变 INT8 校准、部署芯片白名单、训练配置或数据库。增量 unit/frontend 验收；仅长期分支，VERSION 不变，未部署生产。

## 2026-10-12｜总览两 Tab 三击隔离演示数据（UI Only）

- 当前实际总览为「算法一张图 / 算力一张图」两个 Tab；算力 Tab 标题/按钮统一保持「算力一张图」，不存在面向用户的「算力总览」旧名。
- 两个 Tab 各自在 2 秒内连续点击 3 次可切换 UI 演示模式；切 Tab、切项目、退出演示、刷新均恢复实际数据。每个演示视图含醒目的「演示数据模式」提示，算法演示覆盖资产、质量、策略、排行、单位运行、生产任务；算力演示复用已有节点/GPU/容量趋势纯前端 fixture。
- 演示时算法页不调用真实生产看板 Owner，不叠加真实指标；fixture 不进入平台 state、REST API、Worker、调度器、质量快照或长期缓存；无演示状态的真实数据及未知态保持原契约。新增 unit 与真实 Chrome 双 Tab 三击/退出验证，保留原浏览器断言。仅长期分支，不改 VERSION.txt，不部署生产；CI 必须按最终 HEAD 核验。

## 2026-10-12｜P1 YOLO 困难样本挖掘第一批（未完成完整验收）

- 最新阶段沿用 `TaskKind.AI_ANNOTATION` + 原 Worker / CandidateStore / AnnotationRepository：只支持显式选已有素材、普通图片上传选择版本后自动排队两种入口；同一套审核 UI 新增困难信号筛选，没有第二套任务或标注 Owner。
- `platform_core/hard_sample_mining.py` 为无状态计算：全项目历史快照 Test ID 和 SHA 禁入；YOLO 推理仅输出低置信度/小目标/密集目标/无检测待核查，绝不把无 GT 直接断言为真实 FP/FN。已有训练 PT + 训练快照 label_schema + 内容哈希冻结，Worker 再次校验数据/模型/标签，需 `mining.ultralytics` 能力及真实 CUDA；远端无模型或无 GPU 不假成功。
- 后端统一创建入口：`POST /api/v64/projects/{project_id}/algorithms/{algorithm_id}/versions/{version_id}/hard-sample-mining`；普通图片上传可选 `mining_algorithm_id/mining_version_id`，上传与挖掘结果独立，挖掘失败不谎称已撤销上传；同批 upload receipt 重试幂等。
- 现有独立评测 UI 一键选择未标注素材前 100 张；上传 UI 一项可选版本；原人工审核卡片展示困难信号和未确认原因，仍需人工接受、修改或拒绝后才入正式 GT。
- 安全与缺口：冻结 Test 快照/内容防护在任务创建、Worker 启动、审核 commit 前三次执行；暂不提供 ZIP 导入自动触发、Remote Agent 权重分发、模型间增强/严格基准续训闭环；未完成真实 GPU、20k 压力或浏览器实机验收。这个批次不能宣称 P1 fully delivered / CI passed。
- `VERSION.txt=42.24.350` 不改，只长期分支；本轮不合并 main、tag、release 或部署生产。GitHub Actions `queued` 不等于 success，最终 HEAD 需重新核验。

## 2026-10-12｜P0 审计修复：类别指标与逐图框证据使用相同的匹配规则

- 复核 HEAD 76407cf 发现：类别 TP/FP/FN 使用置信度优先的一对一匹配，逐图问题框却使用 IoU 全局优先；重叠目标可能导致类别指标报告 FN/FP、但问题图片没有错误，直接影响困难样本定位。
- 修正 `evaluate_blind_detection` 逐图匹配为与 `_match_flags` 相同的「置信度降序、同类且 IoU>=0.5、选择未匹配 GT 中最大 IoU」；不改变 mAP 统计、不读预测阶段的隐藏 GT、不新增 Owner。
- 添加双重叠 GT + 两个预测框的对抗性回归，要求类别 TP1/FP1/FN1 与逐图证据一致，匹配标志一致。
- 该修复只代表已提交源代码和测试；精确新 HEAD Actions 未达到 completed/success 前绝不可写作 CI 通过。真实 GPU、2,982/2,338/283 张评测数据和 20k 压力 UAT 未完成；不部署生产。

## 2026-10-12｜独立评测 P0 质量诊断与问题图片工作台（CI / 真机场景验收待核实）

- 用户实测三类问题：person Recall 64% / FN4491、fire1 Recall 70.4% vs smoke1 83%、No_helmet TP0 / FN85；旧平台一律显示“需补充数据”，存在误导。本批只改善诊断与只读核验，未自动补样、未改训练数据冻结、不部署。
- `platform_core/training_evaluation.py`：全部图片先执行预测，完成后才读取隐藏 GT；收集完整 FP/FN 计数、图片尺寸、真实框/预测框/置信度/匹配状态，按 FN→FP 排序仅保留最严重 200 张（超 200 的真实图片数量仍计入 `error_sample_count`）；仅为 top200 生成框明细，防 20k 内存膨胀；历史无框记录不伪造框。零 TP 且 GT>0 的类别优先 `review_required`，附具体诊断 action 与未确认原因，不得假定“缺数据”。
- `app.py`：新增严格只读 `.../versions/{version_id}/evaluation/images/{image_name}`，核验算法版本、评测问题图片白名单、冻结 Snapshot 身份及所属素材 SHA256；只读返回图像，禁止任意路径、训练回流；历史版本额外返回不持久化的 `evaluation_class_advisory`，不改旧 Decision ID。
- `static/app.js` + `static/styles.css`：现有独立评测 owner 增加分类异常、严重错误列表、FN/FP 排序与 24 张/页、图片/GT/预测框独立显示；手机端字号及横向表格体验改善；图像无法验证时明确空态。旧版 critical + needs_data 的补样按钮被只读诊断提示替代，原持久化结果不重写。
- 测试：`tests/unit/test_training_evaluation.py` 新增严重程度排序、205 张计数、框证据、No_helmet 0TP/fire1 差异；`tests/api/test_evaluation_diagnostic_image.py` 预览拒绝非法路径、非 test 图片、重复名和快照/摘要漂移；`tests/browser/training-evaluation-diagnostics.spec.mjs` Chrome 图层开关和历史无框退化。已接入 Remote Training Runtime 和 Frontend Runtime Stabilization workflows，确保跑到新增测试。
- VERSION.txt 保持 `42.24.350`，不得合并 main/tag/release/生产部署。最终 HEAD 的 Actions `queued` 不等于通过，需 completed/success 后才确认；真正生产数据 GT 精度、图像存储兼容、A800/Worker 训练及 10k/20k 压力依旧待现场 UAT。
- 详细方案与验收限制：`docs/EVALUATION_DIAGNOSTICS_P0_2026_10_12.md`。

## 2026-10-11｜Worker 离线 AMP / FP16 决议与 AI 底座 iframe 点击保护（真实 A800 验收待执行）

- 保持 VERSION.txt=42.24.350、唯一长期分支；控制端、本地 Worker、远程 Agent 均复用 `train_worker.py` 和已有 `platform_core/training_precision.py`。实际 CUDA Worker 在训练开始前预检：本地存在 yolo26n.pt 时先验证模型、执行 Ultralytics 8.4.127 原生 check_amp；无模型时执行无额外权重的 CUDA FP16 前向/反向/GradScaler 数值检查；失败自动回退 FP32。检查只允许读取本地资源，限定作用域拦截 AMP asset downloader 与 Trainer check_amp，finally 恢复；不得将跳过检查误记为通过。
- 保留原 yolo11n.pt 母模型路径、冻结资源与模型 SHA256 合同；保留 requested / resolved / runtime precision 及 amp_preflight、检查结果、回退原因，并经已有 Agent 结果与训练归档链传递。Trainer on_train_start 核验实际 AMP 后才写 runtime_resources.actual_precision。
- AI 底座 iframe 在菜单收放时禁用父容器 margin-left 过渡，防止目标在 pointerdown / click 期间位移；Chrome 真点击回归保留。
- 已对齐 Ultralytics CI 版本（原 8.4.143 → requirements.txt 8.4.127），增加离线/损坏模型/CPU/回退/Scoped patch 恢复/结果归档等测试。完整 CI、真实 A800 离线训练与前端现场 UAT 必须精确最终 HEAD 再验收；不得因 queued 或 mock 测试宣布完成。本轮未合并 main、tag、release 或部署。
- 详细设计、风险和 UAT：`docs/AMP_OFFLINE_COMPATIBILITY_2026_10_11.md`。

## 2026-10-10｜场景算法实测检测框回退预览

精确 HEAD `032641d2` 的 34/34 Actions、95/95 Check Runs 已核验成功。进一步源码审查发现无 `result_image_url` 时旧结果组件只显示检测列表而不显示真实框。现优先保留服务端结果图；仅在原图 URL 可用而结果图缺失时，按已有推理 `x1/y1/x2/y2` 坐标绘制 SVG 预测框，图片加载失败明确提示、不伪造框、不触碰 Durable Task/模型身份/训练调度。Chrome 场景检测测试新增真实 BMP 与非空坐标断言，静态资源 `app.js`/`styles.css` 缓存键同步递增，`VERSION.txt` 不变。本提交产生的新 HEAD 必须重新验收自己的 CI；真实 GPU 推理与生产数据仍需现场验证。

## 2026-10-10｜训练任务弹窗自动化调度标识

为精确匹配 UI 文案需求，将徽标文字固定为“智能自动化调度”（包含“自动化调度”），保留原有 CSS 和调度器运行逻辑；将原前端训练弹窗正式测试升级为断言确实渲染此徽标。只改视觉文案不增加第二套资源调度。

## 2026-10-10｜训练继承版本浏览器用例状态一致性

在 `995a6f78761088e983fca55d7d4a117f9b28a574` 反馈的两个单测失败中，BaseModal 原拥有者仍只有一套，导入最小化只是 decorater；更新严格断言覆盖旧 BaseModal + 装饰器调用、最小化 CSS 状态清理。版本缓存检测改为与已更改的 ZIP 启动脚本 `4226353` 严格相等。训练版本化用例仍要求“继承当前有效模型版本”、锁定原有模型、80 Epoch 和独立切分，但测试原先仅 mock 算法 GET，Bootstrap 首屏仍无版本，现补齐同一正式成功版本的启动快照响应，防止两个事实源互相矛盾。未改变训练/标签/存储核心或 VERSION.txt。

## 2026-10-10｜UI 合同与精确码映射 Chrome 回归对齐
按 HEAD `cf4c85443798b71470eda9b5faf4c58d70fb0ba7` 的失败日志，仅更新与本轮明确要求冲突的旧浏览器断言：场景来源按钮改名、模型检测抽检动作名、隐藏 legacy patience 控件改为不存在断言、YOLO/COCO/VOC 外部英文标签与已有 canonical code 精确一致时自动预选且最终确认 payload 必须保持 classId→code。保留原先抽检持久化、映射最终 POST、数据模式及按钮功能断言；未删除测试。label-normalization 与 ZIP 工作流仍断言静态缓存键精确等于实际已加载版本，补 assert 现有 source-label 手动入口；不改变调度或标签 Owner。剩余训练继承身份错配另行审计。

## 2026-10-10｜ZIP 精确同码映射浏览器合同同步

原 `zip-import-refresh-recovery.spec.mjs` 两处旧断言要求同码存在时仍保持空映射，与用户要求“外部英文编码和平台英文相同直接导入”冲突。已更新为：首次读取匹配有效 canonical code 时显示“编码一致”、自动填入目标选择，不产生新的标签 POST；显式创建 source code 并刷新后应继续自动恢复同码映射。确认并启动 ZIP 的服务器 POST 与持久化身份断言仍保留，未跳过测试。

## 2026-10-10｜场景算法实测真实浏览器验收纳入主 CI

`tests/browser/quality-detection-workbench.spec.mjs` 之前存在但不在 `frontend-runtime-stabilization.yml` 显式 Chrome 运行清单内。现将该规格加入已有导航工作流，不新建 CI Owner，也未删除/跳过/放宽其他测试。验收包括场景算法实测、模型版本选择、检测批次详情及原始推理工作流；以精确 HEAD 的 Chrome result 为准。

## 2026-10-10｜控制端展示不依赖 Agent 注册列表

补强算力一张图：若 Service Node API 超时或失败，仍可以独立显示已有的控制端本机 CPU/内存/磁盘/GPU 快照。Agent 节点数量与在线 GPU 不得被误标为 0，明确显示未知；保留请求错误。无新 Agent、无额外轮询或调度逻辑。新增定向测试，更新静态缓存数字版本，VERSION.txt 未变。

## 2026-10-10｜算法总览重复质量请求回归修复

合并算法总览和原生产看板后，发现两个 Owner 同时 GET `/api/v42/.../quality-overview`，导致已有页面性能合同失败。Overview Tabs 现在优先复用原生产 DashboardExtras 按项目隔离的 `dashboard422ExtrasRefreshPromise` 与 `state.v42.quality`，对于该 Owner 读取失败不即时再打第二个 GET；在无原生产 Owner 的单元环境保留本身 GET，保持异步 A→B→A 项目隔离。严格 DOM 测试模拟器实现真实 insertAdjacentHTML 行为，并模拟原生产 owner 对 view 的覆盖；新增单 GET 复用契约。未新增轮询、未删除或放宽测试。

## 2026-10-10｜两张总览/场景检测/导入交互与本机统计补强

本次合并「算法生产总览」与「算法一张图」为算法总览，实测数据优先显示，后段保留业务运行指标空态；算力一张图新增复用 Node Agent 的本机控制端只读 CPU/内存/磁盘/GPU 采样，不将本机直接加入可调度 Agent；训练弹窗显示智能自动调度，不修改调度参数；场景算法实测以单模型为默认，额外可加对比模型，只允许预训练原始 YOLO 模型及正式算法版本 best.pt，沿用真实推理、批次和结果带框图；ZIP/存储导入使用英文 code 完全匹配既有标签，其余仍需手动创建/映射及确认，原图预览放右侧；上传/导入弹窗可最小化且保留原 DOM 上传任务。同步旧测试期望和入口缓存版本，无测试放宽，无 VERSION.txt 变更。最终 CI/真实浏览器状态必须精确 HEAD 核验后认定，不部署生产。

## 2026-10-10｜缓存版本与清洗回归断言对齐

精确 HEAD `fc40336` frontend 单测结果 908/909，唯一红灯为 `clean-task-view.test.mjs` 仍静态断言旧的 main.mjs 缓存标识 `42.25.349`；已仅将精确期望改为当前页面 `42.25.350`，保留原有完整严格断言和 app.js、cleaning.js 缓存防回退核验，不修改清洗业务实现，也不修改 VERSION.txt。

## 2026-10-10｜Chrome 用例接入既有 CI

检查 `frontend-runtime-stabilization.yml` 发现浏览器导航工作流显式枚举 spec 文件，新建 `tests/browser/overview-tabs.spec.mjs` 不会自动运行。现将总览真实 Chrome 用例加入该已有 `browser-navigation` 测试列表；保留原有所有测试，未跳过任何断言，也没有新建第二套 CI owner。是否通过须依据精确 HEAD 对应 job 的 completed/success。

## 2026-10-10｜总览三 Tab Chrome UI 回归用例

新增 `tests/browser/overview-tabs.spec.mjs`：真实 Chrome 路由合同样例检查原生产总览不回退、两张图 Tab 切换、质量指标与算法版本计数、GPU 采样缺预约时的未知态、离线节点风险/非实时资源隔离、中心边缘过滤、1366×768/1920×1080 Tab 可见、节点接口失败后不再展示旧资源。该用例必须由最终 HEAD 的真实 Chrome CI 成功后方可标记通过。

## 2026-10-10｜三 Tab 静态资源缓存版本合同

6bd7384 精确 HEAD 前端 CI 报 material-upload-runtime.test.mjs 断言主入口缓存标记必须为数值点分版本；改为既有规则的 `main.mjs?v=42.25.350`，同时将总览 CSS 与 Runtime 模块查询版本设为 `4226350`。这只是静态缓存键，不修改 VERSION.txt，也不放宽测试。其他已观察到的 training-create patience 控制断言与 GitHub 安装 oss2 依赖不完整问题需与总览修复区分，按最终精确 HEAD 单独审定。

## 2026-10-10｜三 Tab 验收 CI 修正

第一次精确 HEAD `50b7615` 的 frontend 测试 908/909 通过，唯一失败为早期 GPU 测试在缺少预约/调度政策字段时仍期待 candidate=1；已将该测试 fixture 显式提供 active_tasks/reserved_bytes/max_concurrent_per_gpu/memory_safety_bytes，使正向准入断言仍被覆盖，新缺数据 fail-closed 测试保持不变。更新 index 与 main.mjs 的局部静态资源缓存键，不修改 VERSION.txt。需要重新核实本次最终 HEAD 全部 CI。

## 2026-10-10｜三 Tab 首轮验收补强（保持版本 42.24.349）

在长期开发分支核实 a1bb67a970201297afe4c3ebc06f72bb40cad812：21/21 GitHub Actions 成功；未改 main、tag、release、生产部署。确认现有唯一 Overview Tabs Runtime、质量接口、服务节点 Agent、GPU runtime、存储源接口。针对 GPU runtime 仅提供采样、不包含 active_tasks/reserved_bytes/准入阈值这一真实合同，修复缺字段默认为 0 导致的虚假“候选空闲 GPU”：没有真实预约证据时显示 —，绝不把低利用率当成可调度。算法视图改为按当前项目请求 /api/v12/.../algorithms，不依赖可能跨项目滞留的全局缓存；异步请求增加 cache identity fence，阻断 A→B→A 老请求回填；失败清除旧响应并展示错误，返回结构无效不转成零。服务器列表保留在线/超时/禁用/未连接，并禁止离线节点旧采样冒充实时；可按中心/边缘筛选；算法版本数量与模型评测覆盖率分开统计，模型排行可打开已有算法详情；提高核心字号。阈值统计称“资源风险节点”，不冒充历史告警事件。

待接事实源：1）生产推理调用计数：须从业务推理网关/外部平台得到 algorithm_id、调用时间及去重计数；2）策略准确率：须业务判断结果与复核标签及分母；3）单位排行/运行状态：须单位 ID、部署实例、算法 ID 和运行态关联；4）OSS/S3 Bucket 真实容量：须 provider 可审计只读用量接口，暂无则显示未知；5）精确 GPU 调度候选：须现有 Scheduler/Reservation Owner 提供只读准入投影，当前 /api/v62/gpu-runtime 不含预约账本、不能推断。

已增回归：GPU 预约证据缺失、离线节点占用隔离、版本数、项目 A→B→A 迟到响应与失败清空旧算法。精确 HEAD CI 与真实浏览器结果须以后续实际执行为准；未执行/未完成不得标绿。

## 2026-10-10｜总览指标全量与预警口径

模型质量列表涵盖所有算法资产，包括尚无评测记录的算法；其策略准确率和真实模型评测指标缺失时均显示 —，避免错误的全 0 或训练成功率混淆。资源预警按节点去重，分母仅纳入在线或心跳超时的被监测节点，未连接和禁用的节点不被当作预警。每张质量表内部滚动避免长列表撑坏页面。修正失败加载永远显示 loading 的问题。

## 2026-10-10｜总览三 Tab CI 契约补强

恢复前端历史导航静态断言依赖的 `['总览', 'renderDashboardCanonical422']` 映射，保留新 `overviewTabsRuntime` 注册的最终唯一执行 owner（注册顺序由已存在的 NavigationStability Map 覆盖规则保证）；仅修改缓存版本相应的测试期望，不放宽测试。新增算法类型、精度与策略隔离、中心边缘显式位置、离线节点过滤、调度数据失联 fail-closed 的纯函数测试；修正 bytes KB/MB 单位及生产总览上无需交互的刷新按钮。针对 CI 已查实未触碰旧训练创建控制问题，维持其红灯以供后续修复。

## 2026-10-10｜总览三 Tab（42.24.349）

按用户要求，在既有「总览」页中增加「算法生产总览 / 算法一张图 / 算力一张图」三 Tab。复用原生产总览，不重造任务和指标 owner；通过现有 API GET /api/v12/.../algorithms（缓存态）、/api/v42/.../quality-overview、/api/v63/service-nodes、/api/v62/gpu-runtime、/api/v61/storage-sources 展示真实数据。独立视图模块 `static/modules/overview-tabs.js` 为现有总览页面唯一导航 owner，异步 60 秒 TTL、按 project 隔离、真实空态。算法类型和行业排名、模型评测质量；策略准确率、生产调用频率、单位运行状况缺少可信事实源时必须为缺数，不得用训练数冒充。算力展示在线 GPU、中心/边缘/未分类分布、GPU 显存与使用率、CPU/内存/磁盘节点占用、配置的存储源、阈值预警占比；云 Bucket 容量无真实采样时显示未接入。服务节点显式 placement 元数据用于中心/边缘分类，连接模式绝不可代替部署位置；旧数据迁移默认 unclassified。无第二套采集器、无假数据、不开额外后台轮询。仍需 CI 和浏览器验收，仅长期分支，不合并 main/tag/release/deploy。

## 2026-10-10｜企业 Logo 临时替换（42.24.348）

按用户上传的“贵州高速 / 贵州中南交通科技有限公司”透明横版 Logo，临时替换登录封面左上角、系统侧边栏左上角原 CL 占位；移动端登录同样替换。单一 `static/company-logo.png` 保留企业文字与品牌配色，修剪透明边、压缩成 825×96 PNG；深色登录封面加白色底牌使深灰公司名可见；侧边栏收起时使用同图左端标识的裁切显示。修改范围仅 CSS/HTML/静态资源与相关回归，不改登录认证、导航和业务。仅在长期开发分支提交，需精确 HEAD CI/Chrome 验证；不合并 main/tag/release/部署生产。

## 2026-10-10｜RKNN/ONNX 环境兼容性预检（42.24.347）

现场 RKNN-Toolkit2 2.3.2 的 load_onnx 因 onnx.mapping 缺失异常。统一在平台已有 rknn_runtime.probe_rknn_toolkit 中检查*相同 RKNN Python* 的 ONNX 版本及 mapping 属性；不兼容时 Agent 不上报 conversion.rknn、远程部署资源不标记 rockchip 可用，传统 Worker 在导出模型前以 RKNN_ONNX_DEPENDENCY_INCOMPATIBLE 阻断并提供修复命令，runner 自身也做最后一道检查；Agent 失败记录优先使用 job.json 的可读错误而非堆栈。只在长期开发分支修改代码与定向测试，不自动 pip 改生产 venv，不影响平台自身 ONNX、训练/转换 owner，也不部署生产。当前 HEAD CI 与真实 RKNN 转换仍需验收。

## 2026-10-10｜训练创建弹窗大屏双栏与标签前置（42.24.346）

训练弹窗由 868px 单列改为最大 1280px、94dvh 双栏：算法信息跨顶部，左侧素材和四模式，右侧正式训练标签。标签列表内部滚动；1050px 以下变成算法→素材→标签→模式。只修改 CSS 视图及缓存键、Chrome 几何合同，不改 TrainingLabelRuntime/TrainingDraftRuntime/Material/Benchmark/TrainingSubmit 等业务 owner。待当前精确 HEAD 的 CI/浏览器验收，不合并 main/tag/release/deploy。

## 2026-10-10｜CI 定点修复 42.24.345（精确 HEAD 待验证）

按上一轮训练创建四模式改造的真实失败 Job 日志修复：修正 TrainingDraft 输出 gpu_policy=exclusive，阻止旧 auto 覆盖；自定义设备选择不再暴露兼容自动隔离；浏览器训练创建使用正式统一标题、独立数据划分 disclosure、自定义专属高级设置；普通上传的缓存键测试校验版本单调递增而不锁死旧版本。保留 TrainingLabelRuntime 正式标签、Exact Material、版本继承、唯一 Submit、GPU Reservation，未新建 Owner。当前提交仍须完整 GitHub Actions 和真 GPU UAT，禁止 main/tag/release/deploy。

# Repository Agent Handoff

## 2026-10-10｜训练创建 UX（代码已提交，CI/Chrome 待验收）

四模式训练弹窗：快速/完整/复杂/自定义，默认完整；标签必须沿用 TrainingLabelRuntime 的正式选择合同、素材 exact image ID、迭代继承、Benchmark；每张 GPU 独占；非自定义 Worker 启动前 Auto freeze、自定义 Manual fail closed。见 `docs/TRAINING_CREATE_FOUR_MODES_UI_2026_10_10.md`。尚未做真实 Chrome/GPU 验收，不合并 main/tag/release/deploy。


## 2026-10-10｜训练默认性能与独占优化（PENDING CI/UAT）

首训 150 / 续训 80 Epoch，Auto Performance，单卡独占，多卡节点允许不同物理卡并行；小数据集 Batch 保护、RAM/CPU Workers 预算、早停默认关闭。任务 canonical owner 与本地/Agent 资源决议保持一致。本批详细修复记录：`docs/TRAINING_PERFORMANCE_EXCLUSIVE_2026_10_10.md`。Actions 和真机验收尚未完成，不合并 main/tag/release/deploy。


## 2026-10-08 live override — unified pagination phase 2A

- VERSION `42.24.305` migrates the dataset MaterialRepository page, the canonical training-task view, and AI candidate review to the only shared pagination presentation.
- Dataset `/api/v61/.../materials` now accepts true `page/page_size`, validates both server-side, returns authoritative page metadata, and preserves the legacy cursor response shape for existing consumers. Page 50 is one bounded query; the browser never walks pages 1–49.
- Training-task pagination remains a pure view over `TrainingTaskRuntime`'s existing authoritative durable queue snapshot. AI review converts a requested page directly to CandidateStore's existing numeric offset and retains its request-epoch stale-response fence.
- No Ground Truth, Task, Material, Candidate, cache, poller, or global Page Manager owner was added. Cleaning/import/model and phase-3 entries remain explicitly pending in the inventory; production deployment remains `PENDING USER UAT`.

## 2026-10-08 live override — pagination phase 1 CI contract follow-up

- VERSION `42.24.304` updates two exact cache-key guards after phase 1 intentionally moved `main.mjs` and the canonical training picker module to new cache-busted URLs. Product behavior and safety assertions are unchanged.
- `42.24.303` exact HEAD reached 842/844 frontend assertions before failing only these stale literals; the dedicated Windows contract jobs failed on the same `main.mjs?v=42.25.294` expectation. This follow-up does not restore old cache keys or relax owner checks.
- Exact `42.24.304` pushed-HEAD CI remains required before phase 2 begins.

## 2026-10-08 live override — unified pagination phase 1

- VERSION `42.24.303` adds the only shared result-set pagination UI at `static/modules/pagination.js`; it renders controls and emits validated page changes but owns no business rows, API, cache, or poller.
- Training material picker now has true numbered server paging while its cursor contract remains available. Stable order remains `created_at, id`; count and page rows come from one SQLite read transaction.
- Training compatibility UI page/filter requests reuse a bounded, disposable projection keyed by the complete selection/algorithm request, Material and Annotation revisions, label-schema digest, and dataset metadata digest. Final admission and AUDIT-148 Snapshot validation still recompute canonical truth and never trust this UI projection.
- Training picker, compatibility issues, and persisted task input issues use the shared controls. Lightweight 1k/10k/20k checks prove two page reads invoke canonical compatibility evaluation once and return only one bounded page.
- This is phase 1 only. The complete classified inventory and later migration status live in `docs/PAGINATION_INVENTORY_V42_24_303.md`; do not claim full-platform completion until its pending result-set owners are migrated in later independently versioned batches.
- Exact pushed-HEAD CI remains mandatory. Real production-scale data and deployment behavior are `PENDING USER UAT`.

## 2026-10-08 live override — Storage Source active-task lifecycle

- VERSION `42.24.302` implements AUDIT-178 on the existing Storage Source, Secret, Task, Material, and task-artifact owners; it adds no dependency registry or second task/source owner.
- Destructive Source changes (disable, runtime config, credential replacement/clear) and final task admission share a short cross-process Source lifecycle fence. Import/Rescan, MaterialBatch CLEAN/AI, AI Annotation, TRAINING/PREPARE, and RKNN calibration references are derived from canonical active task truth in bounded pages. Name-only PATCH remains allowed.
- Credential replacement uses a new versioned Secret reference and publishes its SQLite pointer only after Secret write; failed publication leaves the prior generation intact. Credentials are never copied into task artifacts.
- External storage/model staging stays outside the fence. Import/Rescan and RKNN final publication revalidate the Source runtime generation after staging. Terminal tasks release dependencies; queued/recovered/cancel-requested tasks retain them until terminal.
- Exact pushed-HEAD CI is still mandatory. Real OSS, production Keyring, Agent/RKNN, GPU, and long-running mixed-source behavior remain `PENDING USER UAT`.

## 2026-10-08 live override — Active task material dependency fence

- VERSION `42.24.301` implements the code-level closure for AUDIT-084 and AUDIT-168 on the existing MaterialRepository, TaskRepository, MaterialBatch, Training, and MODEL_CONVERSION owners.
- Training/RKNN calibration admission and destructive MaterialBatch publication now share the existing project Material lifecycle fence. Active dependency truth is derived from canonical task status/artifacts; no dependency table, manager, scheduler, or second owner was added.
- `DELETE_SOURCE` records a Material-owned short destructive claim immediately before provider deletion, performs storage I/O outside the fence/DB transaction, then completes canonical GT/index removal without a cancellation gap. Ambiguous provider outcomes retain the claim and original task tombstone for retry/recovery.
- Active RKNN INT8 calibration references are protected by both `image_id` and storage source/object identity. Final conversion admission revalidates source, object key, size, SHA, availability, and delete state after remote snapshot/staging work.
- Focused local tests are recorded in `docs/codex-handoff.md`. Exact pushed-HEAD CI remains mandatory; real OSS/RKNN/GPU behavior is `PENDING USER UAT`.

## 2026-10-08 live override — Material / Annotation lifecycle + monotonic projection

- VERSION `42.24.300` closes the code-level residuals of AUDIT-149/157/173 and AUDIT-102 on the canonical owners; it also preserves explicit empty Ground Truth during deferred structured imports and locks the new Material-before-GT/versioned-projection batch contract.
- Formal Annotation writes now run under the project-scoped cross-process Material/Annotation lifecycle fence and prove Material existence, no delete claim, source availability, optional frozen content SHA, Annotation version CAS, and active labels before commit.
- Dataset delete claim/finalize and Storage Rescan H1→H2 commit use the same short fence. File staging and remote/model I/O remain outside SQLite writer transactions.
- Material Annotation projection now persists `annotation_version`; newer wins, older is ignored, equal digest is idempotent, equal version with a different digest fails closed. AnnotationRepository remains GT authority.
- Manual save now requires `expected_version + source_content_sha256`; AI candidate commit carries its frozen source hash into the final commit-time guard. Do not restore unversioned generic Material projection writes.
- Local focused verification and exact HEAD CI status are recorded in `docs/codex-handoff.md`; no main merge/tag/release/deploy is authorized.

## 2026-09-23 permanent architecture constraint — one owner, one truth, one call chain

一个能力一个 final owner，一份状态一个 canonical truth，一条正式调用链。修改功能前必须先确认 final owner、canonical truth、现有 wrapper 的必要性以及是否已经存在同功能实现；已有 final owner 时直接修改它，或让调用方直接路由到它。

前端禁止同功能 page owner / wrapper runtime / legacy helper / fallback 并存，禁止重复 shell、renderer、patcher 和多份状态 truth。兼容层只允许 `normalize / redirect / delegate`，不得重新实现业务逻辑。页面视觉层级保持 `Page → Surface → Content`，不做卡片、容器和组件套娃。

后端禁止无意义的 API/service/adapter/helper/repository 重复包装、同一任务的并行 handler/scheduler/repository、旁路写入，以及 Task、JSON、SQLite、缓存之间的多份业务 truth。ModelArtifact、Annotation、Durable Task、External Publication 必须继续使用各自 canonical truth。历史套娃只在调用关系和 fallback 责任已证实时逐步收口，不做无证据的大重构。

## 2026-09-21 live override — OSS 第二批 Connection / Artifact Binding 收口

第二批已完成：`StorageSource` 持有 endpoint、bucket、`public_base_url` 与 Secret Store 引用；Artifact Binding 只持有 `storage_source_id + root_prefix`。算法产物统一 builder 生成最终 Bucket-relative `object_key`，上传时不再叠加素材 Provider `prefix`。存储测试执行 PUT→STAT→READ→DELETE，并在配置长期地址时做 Range GET；DELETE 或 URL 校验失败均 fail closed。畅联发布在任何远端 Version/Weight mutation 前验证实际 artifact URL。

定向证据：Python 20 passed、frontend 9 passed、Real Chrome storage smoke 1 passed。真实 OSS/畅联生产 E2E 仍 OPEN。下一步第三批前必须先给字段 owner/migration 表，禁止直接 DROP、长期 dual-write，`external_weight_id` 仍属于 provider-specific publication mapping。`VERSION.txt` 仍为 `42.24.0`。

## 2026-09-21 live override — OSS/新畅联第一批 Version/Weight 合同收口

当前工作仍在 `feature/external-algorithm-publishing`。远端紧急修复 `2ff431a7` 已先安全同步；该修复只隔离 keyring DBus 测试中的既有 Headless Secret fallback，不得重复修改生产 Keyring 逻辑。

OSS + 新畅联 durable publish 第一批只收紧 Version/Weight 合同：`versionNo` 来自本地 durable `version_no`；UNKNOWN 恢复必须同时匹配 `versionName + versionNo + 已绑定 analysisId`，product/analysis list 只作为查询路径；候选多条或字段不完整时置 UNKNOWN 并禁止 POST。Weight 创建五字段缺一不可；恢复严格匹配 `fileName + computePlatformId + 非空 chipCode`，远端有 `filePath` 时还要匹配长期 URL。Weight 前置字段在远端 Version 创建前检查，避免留下空 Version。`code=0` 是主合同，`code=200/SUCCESS` 继续保留为 legacy compatibility / OPEN。

最小验证：新增合同 15 passed（含 product/analysis 同 ID 去重与 FAILED 修复后重试）；直接影响回归 9 passed；AST/whitespace 检查通过。未跑全量 pytest、integration、浏览器或 Actions。第二批状态以上方最新覆盖为准；第三批仍受字段 owner/migration gate 约束。

最高优先级细节见 `docs/CODEX_HANDOFF_2026-09-21.md` 顶部最新节；`VERSION.txt` 仍为 `42.24.0`。

## 2026-09-21 live override — cache-first page loading closed locally

当前长期分支是 `feature/external-algorithm-publishing`；接手时仍需先核对远端 HEAD。最新性能闭环提交：

- `9fff42df`：`/api/v53/bootstrap/snapshot` 普通缓存命中不再计算 project counts；authoritative rebuild 同一请求每项目只计算一次 counts 并替换 `_V53_BOOTSTRAP_SNAPSHOT`。标签管理 GET 改为 `MaterialRepository.label_usage()` 对既有 `label_counts` 做 SQLite 只读聚合，不再全量水合素材、逐图读 annotation 或在 GET 中 patch。
- `2e3a726b`：启动只消费一次预构建 snapshot；仅显式刷新使用 `refresh=true`。`extras412()` 不再重复 jobs/model_configs；算法、训练任务、数据集、服务节点继续由各自 runtime/PollRegistry 刷新。数据集 v61 当前 48 条先提交并绘制，状态 totals 后补；不加载全量素材。

浏览器同场景实测：冷启动 `10 requests / 2 snapshots / refresh=true / ~998ms` → fresh cache `4 / 1 / false / ~542ms`，snapshot 过期触发页面 owner SWR 时 `8 / 1 / false / ~353ms`；数据集 `6 requests / ~145ms` → `4 / ~27–30ms`；服务节点保持单一 `/api/v63/service-nodes`。定向 API 5/5、前端 12/12、Network/分页/导航 browser smoke 4/4 通过。未跑全量 pytest/integration，未等待 Actions，未 merge/tag/release/deploy，`VERSION.txt` 仍为 `42.24.0`。

本节与 `docs/CODEX_HANDOFF_2026-09-21.md` 顶部最新节优先于本文后面的历史 branch/NEXT。不要恢复普通导航的 broad snapshot refresh，也不要新增第二套 cache/polling/truth。

本仓库由 Codex、ChatGPT 和人工开发共同维护。开始修改前必须先读取实际分支/HEAD，不得只根据 README 或 `VERSION.txt` 推断开发状态。

## 必读顺序

1. `docs/TECH_DEBT_CLOSURE_V42_25.md` — 当前技术债关闭总账 / 第一权威来源。
2. `docs/CODEX_CURRENT_STATE.md` — 当前代码验收点、owner、下一批准确范围。
3. `docs/frontend-legacy-audit.md` — classic `static/app.js` override / owner 审计。
4. `docs/FRONTEND_OWNER_MAP_V42_25.md` — 前端 owner map。
5. 其余历史 handoff/spec；冲突时以实际代码 + 上述当前文档为准。

修改前确认 live branch/HEAD、`git diff main...HEAD` / `git log main..HEAD` 或等价 GitHub API。

## 当前开发状态

```text
stable branch:               main
active branch:               refactor/frontend-runtime-stabilization
latest full code acceptance: 60305921402204e77b8e7ed4ec8e576d9f857c4b
Frontend Runtime run:        34733035739
formal VERSION.txt:          42.24.0
frontend badge:              v42.24.0
app.js cache:                42.25.95
main.mjs cache:              42.25.92
NavigationStability:         422512
```

`34730512607` 已通过 syntax、永久 owner/navigation guards、全量 frontend unit tests、Real Chrome runtime regressions；Real Chrome 33/33。Navigation Action Fencing 永久 workflow `34730512602` 全绿；Resource Discovery SQLite 永久 workflow `34700900542` 继续保持 Ubuntu + Windows 双平台通过。

**技术债清理主线已按用户要求暂停；后续优先真实功能、性能、数据完整性与生产验收。A800 RC 是否推进由后续任务决定。** 未取得用户明确授权，不得 merge `main`、修改正式 `VERSION.txt`、tag 或 release。

## 当前前端 owner 状态

### Training

```text
train-v3 UI
→ state.trainingDraft
→ TrainingDraftRuntime
→ TrainingSubmitRuntime
→ /api/v12/projects/{project_id}/train/start
```

历史 mirror `trainingLabelSelected / trainSplitV3 / train429Selected / train428AlgorithmId / train428Config / trainingDraftFromLegacyState` 已退休，不得恢复。

### Polling

```text
training-jobs → PollRegistry + TrainingTaskRuntime
AutoLabel      → AutoLabelPollRuntime + PollRegistry
video          → PollRegistry(video-frames)
sources        → PollRegistry(sources)
```

旧 timer、`setupPagePolling` shell、creation-wrapper/adoption compatibility 均已退休。

### Navigation — CLOSED

`static/app.js` 的 classic `setPage` owner family 已清零。以下均已物理退休：

```text
set423Base / setBase424
V37 duplicate baseSetPage
oldSetV39 / oldSet42 / set422Base
v34/v35/v42.4 direct setPage
v42.7 direct alias setPage
setPageReady414
baseSetPage417
initial bootstrap function setPage(p){state.page=p;render()} / window.setPage=setPage
```

最终 owner：

```text
NavigationStability
  → normalizeNavigationPage
  → PageRequestScope / navigation epoch
  → PollRegistry before/after
  → waitForNavigationReady
  → beforeInvokeNavigation
  → performNavigation(page): state.page=page; render()
  → persistNavigationState
```

永久 CI 禁止 `static/app.js` 再出现 `window.setPage=` classic owner。Real Chrome 已验证 inline 菜单与 programmatic `window.setPage`、readiness、sidebar、polling、alias、persistence 均正常。

## 当前边界：技术债清理 PAUSED

除非出现真实功能故障、明显性能问题、数据完整性风险或发布验收阻断，不再继续 dead-code / zero-point / 命名 / cache-busting 类清理。剩余债务保留为 OPEN/DEFERRED，不影响当前功能使用时不主动扩展。

### 当前产品主线 — ZIP 10k import scalability CLOSED

Technical-debt cleanup remains paused by user request. Product productionization is the active line.

- **Deployment Artifact E2E CLOSED** — successful conversion jobs surface only verified, existing deployment artifacts. Product `b75b7d09780f691b01e4207c3107977b0500d8aa`, focused run `34726749756`, cleanup `8f3d3e394ceed73e5f522cba512622286fead7a5`.
- **Unified Task Truth API Phase 1 CLOSED** — `/api/v62/projects/{project_id}/tasks` remains the durable public truth for queue/resource/worker/progress metadata. Product `aa5b82ebd2140d3a9f03dc6ae6754c9b7a55afcc`, focused run `34727100684`, cleanup `6de0758e9f0c0cd45d79c48bf7fb022dde8f9ca6`.
- **Unified Task Progress Phase 2 CLOSED** — model conversion, AI annotation and cleaning/material-batch business surfaces expose durable waiting-resource/queue/worker/progress truth without parallel polling owners. Products `9817f450b3fbd20256279c3c861b0938ffdcef16` and `ff31f879b6d501a501188fed8bc78426d9eb31ea`.
- **SSE/event stream evaluation DEFERRED** — current page-scoped polling remains lifecycle-managed; no EventSource/replay/reconnect base is introduced without demonstrated need.
- **Training Progress v2 CLOSED** — existing `training-metrics.sqlite3` persists truthful latest-epoch duration, rolling ETA, throughput, losses, trainer metrics/mAP when supplied, LR and elapsed time; Worker mirrors the compact snapshot into `job.json` without extra list requests. Product `70110f9668e593215bc77c8614dd9d6dd55b7601`, focused run `34730431744`.
- **ZIP 10k import scalability CLOSED — hot-state/candidate split + live v19 owner**: baseline proved the final v36 visible ZIP action still delegated to synchronous `doImportData()` / `/api/v18/.../import`, and a synthetic 10,000-candidate v19 `job.json` was **1,370,177 bytes**. The product now routes final v36 ZIP upload through existing v19 background jobs and stores the full candidate manifest once in `scan-images.json`; hot `job.json`, running list polling and detail polling no longer carry the 10k candidate array. Create response is bounded to 500 candidates for the picker; selecting-job list preview is bounded to 300; running/terminal task state stays O(1) in candidate count. Selected-path validation reads the cold manifest. Product `b4875ada5ff084fd4e21d7c5f026f5b09128033b`, focused run `34731027723`, cleanup `e819a35c71f6aa20f7739281ddfc75e8502104ce`.
- **ZIP 10k acceptance**: focused CI created a real ZIP with **10,000 image members** and passed the v19 create/scalability contract plus existing server-import/storage regressions. The permanent legacy unit guard was migrated, not weakened (`27654cba1fb3406567a40754904531c2b53aa53f`), and the permanent Chrome material/import contract was migrated to the real v19 sequence (`60305921402204e77b8e7ed4ec8e576d9f857c4b`): create → start → list polling → terminal done → labels/current paged-material scoped refresh, with an explicit assertion that no `/api/v18/` request or broad reload occurs. Final Frontend Runtime `34733035739` passed all frontend unit guards and Real Chrome **33/33 PASS (53.9s)**; Action Fencing `34733035761` PASS.
- **Release boundary unchanged** — formal `VERSION.txt` remains `42.24.0`; visible version remains `v42.24.0`; classic `app.js` cache is `42.25.95`; `main.mjs` cache remains `42.25.92`. No merge/tag/release.

**Current next product scope: ZIP 10k processing-phase scalability audit. The UI/background-state amplification is closed, but this does not yet prove that importing 10,000 valid images with annotations is fast enough. Benchmark the real worker path and inspect per-image image decode/copy, AnnotationRepository writes, progress cadence, v50 buffered material commit, label/project writes and finalization. Optimize only measured hotspots; preserve YOLO/COCO/VOC semantics, project serialization, data integrity and cross-platform behavior.**

### R20n — shadowed Model Config generations retirement CLOSED / 技术债主线暂停

Source-order 与删除前/后的同一套 M4 Real Chrome 合同证明：旧 v35 / v426 / v427 `openModelConfigModalV35 → saveModelConfigV35/saveModelConfig426/saveModelConfig427` generations 已被最终 M4 owner 覆盖，运行时不可达。R20n 仅物理删除这 3 套历史 modal/save generation；最终 `saveVisionModelM4`、`testModelConfigV35`、M4 capture/final activation、模型配置字段与 API 语义均保持不变。

```text
baseline + migration run: 34725790087
product:                  9acaa534e596464a1ebe129e435916ed7dd9cdf2
cleanup:                  fce8034a861e1f9c5c0d37568891717309845794
contract alignment / accepted HEAD: b83b2bf360b891265157e602f622d409d1d2332f
Frontend Runtime:         34725907423
full Real Chrome:         33/33 PASS
Navigation Action Fencing:34725907404 PASS
formal VERSION.txt:       42.24.0 unchanged
app.js cache:                42.25.95
main.mjs cache:              42.25.92
```

永久 source contract：`tests/frontend/shadowed-model-config-generations-r20n.test.mjs`；最终 M4 行为继续由 `tests/browser/navigation-action-fencing-r2.spec.mjs` 与现有 Action Fencing workflow 覆盖。一次性 R20n migration helper/workflow 已物理删除。

**按用户要求，从 R20n 起技术债清理主线 PAUSED。** 剩余 R20 global reload/request zero-point、stale-async final scan、cache-busting、历史 dead code、命名/结构归一化、Resource Lifecycle production soak 等均保持 OPEN/DEFERRED，不宣称 CLOSED；除非出现真实功能故障、明显性能问题、数据完整性风险或发布验收阻断，否则不得为了“代码更干净”继续展开技术债批次。

### R20m — shadowed v423 algorithm CRUD generation retirement CLOSED

Source-order + Real Chrome 已证明旧 v423 create/edit generation 从运行时不可达：删除前 `algorithm-list-performance.spec.mjs` 已完整通过，真实 UI 一直解析到后面的 stable 414 owner。R20m 因此没有“迁移 broad refresh”，而是物理删除旧 `openNewAlgorithm423(async) / saveNewAlgorithm423 / editAlgorithm423(old modal) / saveEditAlgorithm423` generation；后面的 `saveNewAlgorithm414 / saveEditAlgorithm414` authoritative local-state owner 保持不变。

```text
baseline:                  243bcb1b17074848d91c2c9c64d47dbed54e5e9b
baseline + migration run: 34724242632
product:                   71cdb2ad192ec99b0e21bfe3c1f70bffca0f586e
cleanup / acceptance:      40a87bf70402dccfc0387950b6856a561ce1ebe1
Frontend Runtime:          34724354775
full Real Chrome:          33/33 PASS
Navigation Action Fencing: 34724354790 PASS
formal VERSION.txt:        42.24.0 unchanged
app.js cache:                42.25.95
main.mjs cache:              42.25.92
```

永久 source contract：`tests/frontend/shadowed-algorithm-crud-r20m.test.mjs`；行为合同复用现有 `tests/browser/algorithm-list-performance.spec.mjs`。一次性 migration helper/workflow 已物理删除。**R20m CLOSED；R20 全局 reload/request zero-point 仍为 IN PROGRESS。**

### R20l — source-import terminal completion scoped refresh CLOSED

最终 live `refreshSourceImportTasksV36()` 在地址读取任务进入 terminal 状态后，已从 broad `loadRelated()` 改为只刷新标签 schema 和当前可见的数据集分页素材。任务 active 期间的 1.8s polling cadence、source-import API 和任务列表 UI 均保持不变。

```text
baseline + migration run: 34723694735
product:                  f260127d2d41281bc1d996a172e7d4290536f24c
permanent Chrome guard:   b17bd0c33bfb99e5557fc245a89a6c4444a8257e
cleanup / acceptance:     f8356bcf5ec1ea128fb38db2820df38146b48cfd
Frontend Runtime:         34723808299
full Real Chrome:         33/33 PASS
Navigation Action Fencing:34723808298 PASS
formal VERSION.txt:       42.24.0 unchanged
app.js cache:                42.25.95
main.mjs cache:              42.25.92
```

永久合同：`tests/frontend/source-import-completion-scope.test.mjs` + `tests/browser/source-import-completion-scope.spec.mjs`；browser spec 已进入唯一长期 `Frontend Runtime Stabilization` Chrome 清单。一次性 R20l migration helper/workflow 已物理删除。**这只关闭 source-import terminal completion；R20 全局 reload/request zero-point 仍为 IN PROGRESS。**

### Navigation Action Fencing R1 — resource/Paddle mutation completion CLOSED

真实旧代码 baseline 已在 Real Chrome 证明：训练资源页慢 `POST /api/train_servers` 发出后，用户切到数据集并打开属于新页面的 modal；旧 POST 完成会执行 `closeModal()`，把新页面 modal 关闭并清掉 sentinel。该行为不是测试推断，而是浏览器复现。

```text
baseline / focused migration run: 34701875185
old Chrome failure: stale save completion closed or rewrote the new-page modal
product:            8269eb0cca84ea310f48ee13af34ab09dd1bfeff
follow-up:          01234ef186f3e57bef2d29ac19420952beef6c36
cleanup:            7fcfcaec0b088a851dbcd580ac226b3dd892fa83
Frontend Runtime:   34702374386
full Real Chrome:   32/32 PASS
permanent Action Fencing run: 34702374346 PASS
formal VERSION.txt: 42.24.0 unchanged
app.js cache:                42.25.95
main.mjs cache:              42.25.92
NavigationStability: 422512
```

R1 新增 `NavigationStability.action(ownerPage)`，通过 navigation epoch/token 暴露 `isCurrent()` / `commit()`；后台 mutation 可以完成，但 stale completion 不得再提交 modal、DOM、state 或 render side effect。`saveServer` 在 POST 后和 scoped `training_options` refresh 后都执行 stale fence。Paddle 手动/一键激活同样有 action fence；若用户仍在训练资源页，只做当前页 render + toast，不再冗余导航回自己。

R1 还将目标范围内的 direct page write 清零：训练资源、模型配置、部署转换、训练任务以及旧“新建算法/自动迭代 → 算法列表”renderer rewrite 不再通过 `state.page='xxx'; render()` 导航；需要跳页时统一走 `NavigationStability`/`window.setPage`。

永久合同：

```text
tests/frontend/navigation-action-fencing.test.mjs
tests/frontend/training-server-refresh-owner.test.mjs
tests/browser/navigation-action-fencing.spec.mjs
.github/workflows/navigation-action-fencing.yml
```

一次性 R1 migration/follow-up helper 与 workflow 已物理删除。

**边界：Navigation Action Fencing R1 + R2 已 CLOSED，但全局 stale-async zero-point 仍为 IN PROGRESS。** R2 已关闭最终 M4 Model Config、清洗确认和 v60 AI review completion；upload/ZIP/deployment/timer-callback completion family 仍留给 final scan，不能宣称 stale async UI side effect 全局为 0。

Resource Discovery SQLite 仍保持 **CODE-LEVEL CLOSED / production soak OPEN**；30–60 分钟生产 soak 和非 SQLite resource classes 不因本批改变状态。

## 不得回退的核心合同

- Windows 开发与 NVIDIA Linux 生产必须共用跨平台代码；禁止写死盘符/Windows-only shell/process。
- 已有素材、标注、算法版本不得因升级清空、移动或重新编号。
- AnnotationRepository 是 GT authority；`unannotated` / `annotated` / `confirmed_empty` 语义必须保持。
- 0 框普通保存不得静默变负样本；负样本必须显式确认。
- 首训标签只能来自本次精确素材与用户明确选择；不得继承母模型类别。
- 迭代只继承上一成功且 artifact-verified 的 trainable version；label schema 旧 ID 不重排。
- Train/Validation/Test 按不可拆分 Component 划分并保留 leakage guard。
- 试验/评测图片送模型时不得携带任何 GT。
- Task Runtime 必须保持 lease/generation/PID-create_time-command-hash fencing。
- `batch`、`workers=0`、`cache=false` 等显式用户参数不可被 Auto 偷改。
- `state.page` 是当前页面 authority；stale async completion 不得覆盖当前页面。
- 页面 polling 必须有 lifecycle cleanup；优先局部 DOM 更新，禁止周期性全页重绘破坏交互状态。
- 不得通过降低/删除 duplicate-request、race、performance、Real Chrome 测试换绿灯。

## 当前后续优先级

```text
1. 技术债清理 PAUSED；仅在真实功能/性能/数据/发布阻断时恢复
2. Unified Task Progress + Durable Queue Runtime productionization（按后续产品任务推进）
3. Navigation Action Fencing final scan — DEFERRED，除非出现真实 stale-async 故障
4. External Algorithm Catalog read-only boundary
5. Resource Lifecycle production soak + remaining non-SQLite resource classes
6. ZIP 10k / Training Progress v2 / GPU Performance Tuner / Deployment Artifact E2E
7. app.js / app.py normalization + cache-busting / semantic naming / deterministic cleanup
8. technical-debt final zero-point + backend regression
9. A800 RC only after acceptance gates
```

## 修改与交接要求

- 每批边界清晰，不混入无关重构。
- 旧测试锁定已确认错误旧语义时，应升级合同，不得回退正确代码。
- 未真实执行的测试写 `NOT VERIFIED`。
- 一次性 audit/migration helper/workflow 批次验收后必须物理删除。
- 每批完成后同步 AGENTS.md + 四份 docs 当前 handoff 文档。
## 2026-10-13｜VNext 模型质量工作台（LOCAL VERIFIED / PRODUCTION UAT OPEN）

- 基线 `30f83c48`，唯一 owner 不变：`training_evaluation.py` 负责评测事实，`TrainingRecoveryRuntime` 负责训练详情，`trainingReportCore425` 负责训练报告；没有新增评测引擎、训练状态 owner、轮询器、素材库或标注流程。
- P0 冻结图片读取按 Evaluation → Snapshot Test ID → SHA256 → 已验证 Bundle/Storage 实际字节闭环；拒绝同名替代、Snapshot 漂移、哈希变化与悬空检测框，安全错误码区分恢复/重试。隔离环境已验证，生产历史对象与真实 OSS 尚未验证。
- 评测工作台包含总览、类别/真实混淆、Top200 错误图片、真实 Confidence 采样、严格同基准版本对比；同图并排还要求相同 Image ID 与实际字节哈希。训练详情沿用原 runtime 四 Tab，训练报告区分执行、停止、独立评测和业务验收。
- 本地证据：Python 208 passed / 1 Linux-only skipped；Node 24 frontend 947/947；Real Chrome 51/51；1920×1080、1440×900、1366×768、375×812 的评测、图片、训练详情和报告均截图核验。正式 `VERSION.txt=42.24.355` 未改；未 push、未部署、未执行 GPU 训练。
- P2 明确保留：全量错误索引、完整场景切片、全量尺寸统计、PDF 导出需要新增可靠证据或迁移；旧记录缺证据时只提示重新评测，不回算或虚构。
- 本轮交付止于本地提交；GitHub CI、生产历史数据与 GPU 训练仍为 `NOT VERIFIED`。

## 2026-10-13｜VNext 独立审查修复（LOCAL VERIFIED / CI OPEN）

- 历史评测图片不再把 filename stem 当 Image ID；显式 `image_id` 严格绑定冻结成员，缺 ID 时只接受 Snapshot 中唯一 `stored_name`，重复、缺失、SHA 漂移或真实响应字节不一致均拒绝。20k Snapshot 身份索引只缓存已解析元数据（上限 8），响应仍逐次校验真实字节 SHA；24 张页由 24 次解析降为 1 次，文件变化后重新解析。
- `TrainingRecoveryRuntime` 仍是唯一训练详情 owner；完整 1000 Epoch / 720 采样仅在曲线或资源页首次需要时加载，此后 1.5s 轮询读取 summary 并合并 `latest_epoch/latest`。合成基准：296,333 B → 428 B/轮询；统一按首分钟 40 次总请求计算，旧实现 `40×全量=11.3042 MiB`，新实现 `1×全量+39×精简=0.2985 MiB`（完整历史首次加载已计入，-97.36%），SQLite SELECT 4 → 1/轮询。
- 版本比较以 `class_id` 为主键；旧数据仅在显示标签双方唯一时兼容，重复或无法对应时标记不可严格比较。缺失 delta 为“未记录”，真实 0 为 `0.0 pp`。
- 质量中心导航、A/B 双侧同步缩放/定位与单侧全屏、训练页签键盘/ARIA、完成态最佳已记录 mAP50、1366/375 布局已由真实 Chrome 验证；没有新增页面、评测引擎、轮询器或事实源。
- 最终差异审计：新鲜 Windows 全量 pytest 为 `2325 passed, 12 skipped, 62 failed`；这 62 项在独立干净 `30f83c48` 工作树中以相同异常类型/首失败位置 `62/62` 复现，VNext 新增 Python 回归为 0。旧 `64 failed` 报告没有保留可反查两项的 JUnit，不再沿用。短 basetemp 证明其中 30 项为 Windows 路径长度。旧基线全量 Chrome `142 passed, 6 failed`，与 VNext 最终 Node 24 全量 `143 passed, 6 failed` 的六项同名同断点。首轮多出的标签管理项已通过等待真实缓存写入修复夹具（repeat 5/5、相关素材集合 22/22）；服务节点旧基线独立运行竞态也以显式高级功能前置状态收敛（repeat 3/3）。两处均未改生产代码或放宽业务断言。详细证据见 `docs/VNEXT_FINAL_DIFFERENTIAL_AUDIT_2026_10_13.md`。GitHub CI、生产历史对象、真实 OSS 与 GPU 训练仍为 `NOT VERIFIED`。

## 2026-10-13｜多文件上传队列与任务中心（LOCAL VERIFIED / CI OPEN）

- 根因是 ZIP 批次先完成全批指纹，再由两槽 limiter 创建上传会话和登记任务；第 3 个及之后虽在闭包中等待，却没有任务中心身份。现改为文件选择后同步登记每个文件，再按唯一 `createZipTransferLimiter(2)` FIFO 获取浏览器传输槽；分片上传完成即释放槽位，合并、扫描与标签确认不占浏览器槽，也不新增正式导入队列或 Owner。
- 任务中心保留所有活动任务，终态历史有界；显示文件名、大小、真实进度、排队序号、错误与状态动作。排队/准备任务可单独取消，持久会话继续复用原暂停、续传和安全取消。刷新后仅浏览器 `File` 的任务明确标记“需要重新选择文件”，不得伪装可自动恢复；项目切换会隔离并停止原项目本地传输。
- 同批无效/空文件、指纹失败、会话失败和完全重复内容均逐文件可见；同名不同内容仍可受理，一个失败不阻断后续 FIFO。普通素材入口审计确认全部选择项由既有分块 Owner 接收，新增 130 文件 Node 合同和 65 文件真实 Chrome 回归，不创建第二套队列。
- 正式版本升级为 `VERSION.txt=42.24.356`；同步 app/main/ZIP bootstrap/任务中心缓存标识，健康接口、UI 版本与静态资源合同一致。
- 最终本地证据：Node.js 24 frontend `962/962`；Python ZIP/multipart/路由/健康合同 `35/35`；Chrome `16/16`（包含 3/5/10 ZIP、两槽并发、跨批次 FIFO、传输中/排队取消、失败放行、刷新、项目隔离、普通素材分块）。GitHub CI、生产 OSS/大文件网络和部署仍为 `NOT VERIFIED`；本批禁止 push、merge main 或部署。


## 2026-10-14｜训练失败智能诊断（REMOTE PUSHED / LOCAL CI FIX READY）

- 事实源保持唯一：现有 Worker 在训练进程异常退出时只执行一次有界 Kernel journal 读取，并仅保存与 PID、进程创建时间及任务时间窗匹配的结构化 OOM 摘要；详情 API 不扫描系统日志，也未新增轮询器、诊断 Owner 或自动重试。
- `training_recovery_truth` 输出后端判定的 `diagnosis`（code/certainty/title/summary/evidence/possible_causes/suggestions/checkpoint_message）。`HOST_MEMORY_OOM` 需要任务关联 Kernel 证据；cgroup 还要求同生命周期 `oom_kill_delta>0` 和 scope identity；纯 `SIGKILL/-9` 固定为 `SIGKILL_CAUSE_UNKNOWN`，CUDA OOM、租约丢失、取消、SQLite lock 等保持独立。
- 对外诊断与折叠技术详情会脱敏路径、Bearer、token/password/secret/API key。旧任务只按已有证据投影，不回写状态或原始 artifact。没有可信恢复合同固定显示“当前没有可恢复的训练断点，需要重新创建训练任务。”，不出现恢复按钮。
- 训练详情沿用现有四 Tab 和 `TrainingRecoveryRuntime`；桌面将依据/可能原因/建议紧凑分栏，窄屏回到单列。缓存标识和 Training Recovery Guard 同步，正式 `VERSION.txt=42.24.356` 不变。
- 远端 HEAD `ab470e8c` 的 44 个实际 Actions 已终态：42 success、2 failure、0 running；Training Recovery Guard 与其余训练关键工作流通过。两项失败分别为 Frontend Runtime 守卫仍硬编码旧 `upload-task-center-3`，以及 ZIP Chrome 测试在标签确认模态框拥有交互焦点时点击其后方任务中心。最小测试/工作流修复已在本地完成并复验 Node 964/964、ZIP Chrome 14/14、诊断 Python 33/33，尚未获准再次 push。真实 Linux journal 权限、生产历史任务和 GPU 训练仍为 NOT VERIFIED。

## 2026-10-14｜训练创建反馈体验（LOCAL VERIFIED / CI OPEN）

- `TrainingSubmitRuntime` 仍是唯一提交 Owner；九个原始技术阶段只投影为“配置校验 → 素材检查 → 任务提交”，不增加 API、轮询器、任务状态或虚假百分比。
- 快速响应仅显示原位按钮 Spinner；慢响应在当前训练弹窗内显示克制的居中反馈层。成功必须通过 `validateTrainingCreatedResponse`，且只表述“已创建并进入队列”；失败保留配置与真实原因。
- POST 网络中断会先按本次预生成 Task ID 查询 `/api/v62/projects/{project}/tasks/{task_id}`；仅在查到同一正式训练任务时恢复为成功，无法确认时锁住盲目重试并提示任务列表核对。
- CSS 动效支持 `prefers-reduced-motion`；1920×1080、1440×900、1366×768、375×812 均通过真实 Chrome 边界断言。新鲜证据：Node `968/968`、训练 API Python `69/69`、Chrome `1/1`。`VERSION.txt=42.24.356` 未改，GitHub CI 与生产仍为 `NOT VERIFIED`。

## 2026-10-15｜重复与异常素材全局治理（LOCAL VERIFIED / CI OPEN）

- 继续复用 Full Audit、`MaterialBatchRuntime62`、服务端 `DELETE_INDEX` 与唯一 MaterialBatch Worker；浏览器不提交全量待删 Image ID，也没有新增素材库、删除引擎、任务 Owner 或轮询器。
- 服务端计划冻结审计 ID、素材/标注 revision、完整 SHA256、正式标注摘要、每组 keeper 与删除项；自动范围仅纳入同图同标注、无扫描异常且无多重历史引用的组。同图不同标注必须人工指定 keeper，历史/活动任务、快照、模型与独立评测引用均 fail-closed 保护。
- 执行前和 Worker 删除前均重验 keeper/delete 身份与新增引用；共享物理对象不删除，部分不安全组保持失败可见，其他安全组可继续沿用原重试/恢复合同。治理终态会失效素材分页、训练素材摘要/兼容性、标签审计、质量缓存与旧素材审计。
- 新鲜本地证据：素材治理 Python `11/11`（含 5→1、501 删除、120 组跨分页、引用保护、并发漂移、幂等与凭证）；相关 MaterialBatch 回归 `19/19`；Node `970/970`；Real Chrome `1/1`，1366×768 预览、二次确认和组进度已截图核验。`VERSION.txt=42.24.356` 未改；GitHub CI、生产历史对象、真实 OSS 和大库耗时仍为 `NOT VERIFIED`。
