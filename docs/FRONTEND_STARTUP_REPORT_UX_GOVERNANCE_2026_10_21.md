2026-10-29平台性能第一阶段审计与两链轻量修复以[本轮唯一专项](PLATFORM_PERFORMANCE_AUDIT_2026_10_28.md)为准。原Bootstrap/UI/GPU既有能力保留；其他模块仅审计，下一阶段须用户确认。

> 2026-10-21后续训练准入诊断/草稿恢复/删除复检UI由[生命周期一体治理专项第十节](TRAINING_MATERIAL_LIFECYCLE_GOVERNANCE_2026_10_21.md)维护；本文件保留综合前端原验收，不重复记录GOV进度。

# 页面启动、训练报告与训练任务交互综合治理（2026-10-21）

本文件为本专项唯一需求、进度、问题及验收依据。与 GT 素材生命周期专项分开维护。

## 10. 综合治理偏差补充验收（2026-10-21，限定范围已验收）

补充基线：远端与本地 `36aff61874596530a9ab3823dea077b817e9f3b3`，VERSION `42.24.370`，fetch 后一致且专项工作树干净。原始 D 盘 WIP 和其他工作树不修改；本次不是重新实现八项功能。前次最终文档 HEAD 的 CI 已独立核验 21/21 Actions、55/55 Checks、Chrome 128/128；该结果仅属于前次 HEAD，不作为本次验收。

| 补充任务 | 状态 | 验收要求 | 本次证据/剩余 |
|---|---|---|---|
| 全平台 Loading 覆盖矩阵 | 已验收 | ZIP、清洗、GT审计、人工保存、训练创建、报告、独立评测、转换、发布、批量删除逐项核查 | 区分代码审计、动态实测和未覆盖，不再用共享样式已存在代替全平台验收 |
| 正式成功训练口径 | 已验收 | 追踪 SUCCEEDED/PARTIAL_SUCCESS/旧done、成果合同、评测失败、去重和项目算法隔离 | 不以失败任务 Checkpoint 当成功；不擅自扩大成功标准 |
| 算法报告指标范围 | 已验收 | 次数、累计/平均耗时和任务列表名称与范围一致 | 核查是否包含失败、截断或重复任务 |
| 生产只读性能方案 | 已验收 | 完整URL、字节、TTFB、Server-Timing、历史数量、冷/热和10刷新 | 本轮不访问生产；空隔离库0.42–0.58秒不代表生产首屏 |
| 最小修复与最终验收 | 已验收 | 仅修确定偏差；相关Python/Node/真实Chrome；正常提交及最终SHA CI | 本次测试与准确SHA CI见10.6；未声明全平台所有接口/生产通过 |

用户已确认：本次验收完成后，再单独实施附件 Annotorious v3；该集成不混入本专项，另建其自身需求与接续记录，也不因此改变本专项的标注/GT合同。生产部署、数据库/素材/Bundle修改和真实GPU训练继续禁止。

## 1. 基线、授权与验收边界

起始实际 HEAD `db676bbfe6e6641466025822a38754697e79333f`，长期分支 `feature/external-algorithm-publishing`，VERSION `42.24.369`。已 fetch，远端与本地一致、工作区干净；其他工作树及未完成修改不覆盖。允许代码、隔离测试、文档、正常提交和推送；禁止生产部署、生产数据库修改、正式素材删除、历史 Bundle 清理和真实 GPU 训练。

用户现场 snapshot 200 耗时 12.08 秒，其他 cache/config/session/status 为 590/364/347/331ms；这只是现场证据，尚未取得现场完整 URL、字节数、TTFB、下载、JSON 解析或服务端分解，不能冒充本地复现。热启动核心交互目标约 2 秒，最终须分别列真实隔离测量和现场未核验条件。

## 2. 已确认需求与实现约束

| 编号 | 优先级 | 正式需求 | 当前状态 |
|---|---|---|---|
| PERF-01 | P0 | 审计 Snapshot/历史任务扫描，核心数据优先，按需历史报告，复用有效快照且任务与算法版本真实 | 已验收 |
| UX-01 | P1 | 科技蓝、浅色、柔和骨架、小 Spinner、平滑淡入；后台保留数据，提交防重，长任务真实进度 | 已验收 |
| REPORT-01 | P0/P1 | 即刻弹窗、骨架、真实报告、有界等待、明确错误与重试、请求/版本隔离、关闭清理 | 已验收 |
| MODAL-01 | P1 | 报告和独立评测居中正常弹窗，约1120px/86dvh，固定标题独立滚动，保留全部功能 | 已验收 |
| HOVER-01 | P1 | 操作图标统一高亮及跟随指针、边缘避让提示，键盘/Esc/触屏可用，装饰图标不加无意义提示 | 已验收 |
| CHART-01 | P1 | 保留真实曲线/采样/Legend/DataZoom/Resize/Dispose及真实悬停，彻底删除报告恢复视图 | 已验收 |
| TRAIN-01 | P1 | 服务端可靠确认独立TRAINING任务身份后接入Runtime、立刻仅关原创建弹窗、成功反馈、后台刷新 | 已验收 |
| TRAIN-02 | P1 | 只计可信正式成功独立训练任务；去重，不计失败/取消/排队/运行/转换/评测/导入；卡片排序概要一致 | 已验收 |

创建失败保留弹窗；网络不确定按原task_id查询，不盲目重建；列表刷新失败不能改写创建成功。旧异步不能关闭新弹窗，禁止延迟关闭定时器。次数不能依据列表分页低估、不能遍历全部历史文件来计算、不能删除失败历史。旧done/finished必须有后端可信合同与成果证据。

首次加载按真实布局提供标题/筛选/卡片/表格/指标/图表占位；快速请求减少闪烁，300–800ms轻反馈、超过800ms骨架、3秒真实说明、10秒持续等待与适用恢复；不得假进度。动画约1.4–1.8秒、过渡120–220ms、CSS优先、无外部CDN/大库、支持减少动态效果。

报告保留概览、曲线、冻结证据、异常、溯源和分析材料；评测保留混淆矩阵、类别指标、FP/FN、Confidence、错误样本、图片、版本比较。缺失证据不造值。截图/测量未经执行不得写验收。

只复用 Bootstrap/Snapshot、TaskRepository、TrainingTaskRuntime、TrainingSubmitRuntime、NavigationStability、PageRequestScope、PollRegistry、Modal Stack、ECharts及现有Tooltip/Loading；禁止第二套Owner/API Client/任务库。调度、GT冻结、权限和身份校验不得削弱。

## 3. 架构、确定根因、实际修改与技术取舍

| 编号 | 已验证根因 | 实际修改与复用链 | RED→GREEN / 剩余 |
|---|---|---|---|
| PERF-01 | 每次Snapshot sync读取全部历史job.json并enrich；jobs接口两次sync后又逐项读/enrich；首屏先等非关键Bootstrap ready；作业报告重证据进入Snapshot | `app.py`原sync/list/dispatcher/Bootstrap与`platform_core/training_history_projection.py`进程内只读投影：签名变更才读JSON、活动任务每次Durable覆盖；Snapshot仅复制轻概要；原`static/app.js`启动先核心Snapshot、503再等待、20秒deadline；真实Server-Timing含序列化 | 新Python动态历史/分页/实时/冷启动/完整报告测试通过；240历史及Chrome10次测量见第6节；生产12.08s分解仍未现场核验 |
| UX-01 | `.loading`、Spinner和骨架样式分散，首屏只显示准备卡片，等待无统一反馈 | `static/modules/modal.js`扩展原呈现能力loadingSkeleton，`main.mjs`接入原PlatformCore；`styles.css`统一现有loading/skeleton/spinner；首屏/报告复用结构骨架，3/10秒实际等待、20秒可恢复；后台原Owner保留数据，长任务原真实进度Owner保留 | 首屏/报告及提交真实DOM、失败结束、reduced-motion原回归通过；没有改写长任务进度或造百分比 |
| REPORT-01 | 原api无deadline，报告仅序号+isConnected，pending永不结束；成功后全局querySelector可误挂旧底层报告 | `static/app.js`原trainingReportCore425增加20秒race+abort/3与10秒说明/同窗重试/项目任务算法版本fence；原closeModalCore hook清理；成功仅本layer挂载 | Node生命周期及Chrome5场景覆盖正常慢/404409500502504/永久pending/缺历史证据/重试/close迟到/版本切换；全部通过 |
| MODAL-01 | CSS明确强制quality-workspace 100vw/100dvh/无留白 | `styles.css`原规则改1120px/86dvh/12px以上留白、标题不滚动、正文独立滚动；原`static/app.js`Modal栈补焦点返回/Tab约束，保留关闭链 | 四尺寸真实DOM边界通过；原评测分页、比较、图片/GT/FP/FN及报告曲线等回归通过，无第二管理器 |
| HOVER-01 | 原操作已有title/aria原生说明，缺统一跟随/避让 | 扩展`modal.js`现呈现层为唯一委托title/aria/SVG title提示，body顶层popover、防裁剪、指针跟随/边缘避让、focus/Esc/out/scroll/关闭清理，销毁abort统一监听 | 真实Chrome跟随/键盘/Esc/关闭清理通过，单个tooltip节点，无每图标全局mousemove；装饰无说明不处理 |
| CHART-01 | reports.js含data-chart-reset按钮、toolbox.restore和委托监听 | 原`static/modules/reports.js`移除三者；真实axis tooltip位置跟随+边缘限制；原DataZoom/Legend/null缺口/Resize/Dispose保留；main/recovery必要缓存同步 | 实际ECharts option、DOM无恢复控件，hover真实0.6、缺点null、Legend/DataZoom及dispose Chrome通过 |
| TRAIN-01 | 成功先await列表刷新，再520ms定时关闭；恢复分支无原Modal保护；旧created反馈可遮挡新表单 | 原`training-submit.js`校验task_id/类型/合法状态/项目必有且匹配/可用算法身份；accept→仅原root+栈顶close→toast→后台刷新；原task_id冻结项目恢复、不确定禁止重POST；反馈限定submissionRoot、新form清idle | 新行为RED（慢刷新/迟到/未知重复/项目缺失与冲突/新表单遮罩）后GREEN；Node相关62/62、Chrome隔离7/7+原真实app流程1/1通过 |
| TRAIN-02 | state.jobs只取关联长度，包含失败/排队且本身仅50终态窗口；双层30秒缓存使训练成功后仍旧值 | 后端原历史/TaskRepository完整分页聚合successful_training_count，v12算法/Snapshot/算法报告summary共源；原algorithm-list-runtime卡片/排序读此值，缺合同显示—；原task刷新使Snapshot失效，main页面返回minAgeMs=0绕过Owner短缓存 | Python成功/非成功/重复/重试/归档/本地远程/项目算法隔离/151成功大于50窗口通过；真实DOM双缓存返回更新、Node排序与项目切换通过 |

索引不是任务数据库：原TaskRepository、Worker调度、版本归档及磁盘job仍唯一事实。替代的逐请求全量JSON扫描已退役；每次仍逐文件stat（mtime_ns/size/inode），不宣称O(1)。终态缓存由文件及Durable修订双重失效，活动行总是enrich真实状态。legacy首次/变更保留幂等归档，Durable由原Handler归档。保留原异常降级磁盘index；异常路径不能宣称实时。

次数口径：Durable TRAINING且SUCCEEDED/PARTIAL_SUCCESS并有result_ref；PARTIAL_SUCCESS在原合同为训练完成、后评测非致命警告，非失败训练。历史done/finished/completed/success等必须artifact_verified为true；未知证据不自动当成功。按task_id/id去重，同ID重试不增次数；归档无job时用任务所属payload恢复算法身份；SDK算法引擎名不能替代业务算法ID。失败历史不删除，手工导入/转换/评测不计。没有第二统计DB或前端猜增计数。

Snapshot概要瘦身不改worker job/index/v44完整证据；算法版本/评测仍沿用原完整合同，避免破坏当前直接评测消费者。本轮未新增版本详情API或重建消费者。

Loading覆盖：初次核心页面标题/筛选/指标卡/图表/表格骨架、报告弹窗、既有全平台`.loading`、`.skeleton-line`、`.tiny-spinner`、按钮aria-busy/is-loading；既有模型配置、素材分页、任务后台刷新保留真数据。300ms轻动画延迟、800ms骨架流光延迟、1.6秒transform shimmer、160–180ms交互过渡和reduced-motion；不引入CDN/动画库。ZIP、清洗、审计、训练、转换、删除继续由既有真实任务进度驱动，本轮没有替换Owner或生成进度。

Tooltip盘点：Modal关闭.icon、报告下载/复制/模型溯源/异常/帮助等带aria/title控件、图片缩放及前后切换已有title、评测矩阵button与Confidence SVG点title。纯文字操作保留可见文字，装饰图标无提示；矩阵保留真实类→预测类→数量，曲线使用真实Threshold/存在的指标。SVG和图表不造缺失采样。

## 4. 阶段进度、优先级与提交

| 阶段 | 需求 | 状态 | 已完成 | 剩余 / 阻塞 | 关联Commit |
|---|---|---|---|---|---|
| A | 全部，P0/P1见第2节 | 已验收 | 最新基线、Owner审计、动态RED、性能基线与独立审查 | 生产现场只读分解未取得，不是本地验收 | `bcf738e9dc46a0744c49fa11eae05b54238701d9` |
| B | PERF-01 | 已验收 | 增量读、单次索引同步、核心提前返回、概要瘦身 | 元数据仍线性检查；现场12.08s须部署后另验 | `bcf738e9dc46a0744c49fa11eae05b54238701d9` |
| C | TRAIN-01/02 | 已验收 | 立即正确关闭、未知恢复、防重、权威成功次数、排序缓存联动 | 生产不执行训练；无代码阻塞 | `bcf738e9dc46a0744c49fa11eae05b54238701d9` |
| D | REPORT/MODAL | 已验收 | 报告有界请求/恢复、旧响应隔离、正常弹窗和原生命周期 | 生产真实报告需部署后核验 | `bcf738e9dc46a0744c49fa11eae05b54238701d9` |
| E | UX/HOVER/CHART | 已验收 | 统一样式/骨架/提示、真实曲线、恢复移除 | 全平台既有任务Owner保持；无代码阻塞 | `bcf738e9dc46a0744c49fa11eae05b54238701d9` |
| F | 全部 | 已验收 | 本地Python/Node/Chrome及版本/语法检查 | 实现及修正已正常推送，f0f3010d实际21/21 Actions、55/55 Checks通过；本次文档提交独立核验 | 待最终SHA |

每项实际文件、完成内容、剩余与验收证据对应第3及第6节；禁止用聊天记录代替本文件。CI出来后在第9节补准确Commit。源码/文档同提交，后续文档提交必须重新核验其自身CI。

## 5. Bug、审查与修复记录

1. 原慢扫描、created等待刷新/延迟误关、非成功训练计数、无限报告、全屏规则及恢复控件：均已动态复现并按第3节修复，回归通过。
2. 独立审查P1：创建响应缺project_id仍通过→要求项目必有且匹配；新增RED后相关Node/Chrome通过。
3. 独立审查P1：只失效Snapshot仍命中algorithm Owner30秒缓存→页面返回minAgeMs=0；真实先刷新算法→训练成功→30秒内返回计数更新通过。
4. 完整Chrome回归发现新表单继承旧created遮罩→限定submissionRoot并清理新form idle；原完整素材选择/筛选/确认/创建/后续失败流程8场景通过，未force click或删除断言。
5. 原legacy归档不可因性能去掉→冷/变更保留原幂等归档；动态回归版本仍一份、热请求不重复归档通过。
6. 测试适配记录：全量Frontend首次1106通过2失败，旧源码守卫未适配新增Abort signal和原Modal焦点接入；仅更新精确新合同，四尺寸Chrome增加实际焦点圈Tab/Shift+Tab，1/1通过。旧priority fixture只mock已退役file-list入口，改真实隔离jobs目录，35回归通过；联合Chrome首轮44通过2失败，其中一项为新增计数夹具未等待启动旧inflight，修正夹具后4/4通过；Tooltip测试曾移动到圆角按钮之外及Esc关闭后聚焦旧节点，改为真实控件内部移动与重新打开焦点流程，产品跟随/退出行为不削弱。上述失败均如实留痕，不计为未修复产品缺陷。

## 6. 实际测试与性能证据

性能原始数据持久化：[测量JSON](evidence/FRONTEND_STARTUP_REPORT_UX_2026_10_21.json)。生产截图12.08秒只有请求名，未取得现场完整URL/TTFB/下载/处理分解，不能宣称现场问题已被实测关闭。

| 测量范围 | 修改前 | 修改后 | 条件 |
|---|---:|---:|---|
| _v53_live_jobs 240历史、10调用中位 | 1815.73ms | 40.22ms | 同组实际JSON，无注入sleep；热中位39.59ms |
| 冷首次同fixture | 6583.39ms | 1576.70ms | 磁盘缓存有差异，不单凭冷值作生产承诺 |
| 每次历史job.json读取 | 240 | 冷240、后9次0 | Durable始终重新读真实状态 |
| 可见50作业序列化体积 | 1009739B | 14689B | 98.545%减少，仅jobs部分，非全部Snapshot |
| Chrome10刷新核心可交互 | 无同口径旧浏览器基线 | 418–578ms，中位484ms | 空隔离库，不能代替大生产库 |
| Chrome Snapshot | 无同口径旧浏览器基线 | 48.6–77.8ms，中位58ms | URL http://127.0.0.1:8011/api/v53/bootstrap/snapshot |
| TTFB / 下载 / JSON.parse | 无 | 45.6–74.2ms / 0.4–0.7ms / 0–0.2ms | parse在body.text后单独计时；分辨率使0可出现 |
| Snapshot字节 / 服务器处理 | 无 | 1314B / 42.66–70.63ms | Server-Timing含序列化，每次仅1个Snapshot，无refresh=true |

- Python：9文件104通过、0失败0跳过（5warnings）；覆盖新统计/历史projection、旧visibility/bootstrap labels/priority/recovery/terminal/metric credibility。命令见下。
- Node：相关173例通过后，按既有Frontend CI入口全量1108/1108通过、0失败0跳过；首次1106通过2失败为旧源码守卫固定期待未带signal的请求和未插入焦点生命周期的调用，原位更新到实际精确新合同，身份/Owner保护断言保留。涵盖报告/Submit/计数/算法/任务/Startup/Cache/Version及共享呈现影响。
- Chrome：8个相关文件46个独立场景；首轮44通过2失败，修复后原真实训练流程+7矩阵8/8、startup/presentation/cache4/4通过；并集46场景均分别通过。最终waitReady(signal)恢复后4/4场景复验通过，不把重复次数累加。
- 四尺寸1920×1080/1440×900/1366×768/375×812报告与评测边界通过；原评测图层、分页、混淆矩阵、Confidence与版本比较、报告真实曲线/空证据/资源采样不造值均保留。
- 语法检查、git diff --check、`python -m platform_core.build_identity --check-version-file VERSION.txt`通过，VERSION42.24.370；app/main/styles缓存417及必要模块缓存一致。

```powershell
python -m pytest tests/api/test_training_success_counts.py tests/unit/test_training_history_projection.py tests/api/test_training_job_visibility.py tests/api/test_bootstrap_label_snapshot_truth.py tests/unit/test_training_job_projection.py tests/api/test_training_priority.py tests/unit/test_training_recovery_api.py tests/api/test_training_terminal_runtime.py tests/api/test_training_metric_credibility_report.py -q --basetemp C:/t/perf-count-final
npx playwright test tests/browser/startup-report-presentation.spec.mjs tests/browser/training-submit-lifecycle.spec.mjs tests/browser/training-report-request-lifecycle.spec.mjs tests/browser/training-quality-reports.spec.mjs tests/browser/training-evaluation-diagnostics.spec.mjs tests/browser/training-label-selector.spec.mjs tests/browser/algorithm-list-performance.spec.mjs tests/browser/page-loading-performance.spec.mjs
```

既有Frontend CI仅增加本次3个真实浏览器spec到原Job，Training Visibility CI加入本次2个Python合同文件；无新工作流、无跳过或削弱关键断言。

## 7. 接续与生产边界

本轮代码及隔离验收完成，最终文档补提仍绑定其自身CI；不得重建Owner或重复实现已测功能。生产部署未授权/未执行，生产数据库/素材/Bundle/外部Weight/GPU均未操作。现场应在独立部署授权后读取真实Network全URL/字节/Server-Timing/TTFB，核验真实报告、算法版本与任务状态、连续10刷新和大量历史。生产12.08秒不能用隔离数据冒充关闭。

## 8. 中断及恢复检查点（本专项继续，未提交）

2026-10-21曾被紧急指令短暂中断；用户现已明确撤销该临时需求并要求继续本专项。临时专项所有13个未提交文件仅在独立工作树修改，已逐文件git restore并确认diff/status干净，无commit、无push、无冲突；随后清理该独立工作树。本专项原有成果未受影响。中断时：本专项代码保留在原长期分支工作树，未commit、未push、未核验本轮CI；本地VERSION已改42.24.370但未发布，后续整合须按届时远端版本重算。不得把本地通过当远端验收。

实际已实现：增量历史JSON投影和实时Durable覆盖；核心snapshot先于后台ready，20秒deadline与恢复；Snapshot作业报告概要瘦身；权威完整成功训练次数及排序；创建可靠身份后立即仅关原Modal；报告20秒有界等待、重试与迟到隔离；报告与评测1120px/86dvh居中；共享Loading/Skeleton及委托Tooltip；移除恢复控件。源码改动见工作树git diff，尚未提交。

本地证据：Python9文件104通过、0失败0跳过；最终相关Node173通过、0失败0跳过。联合Chrome46项首轮44通过2失败：计数新夹具未等启动旧inflight（夹具修正）、新训练表单继承旧success遮罩（产品修正，submissionRoot限定并清理新form状态）。后续原完整训练页面+7矩阵8/8，startup/presentation/cache4/4通过；原其余44场景无需重复计数。全部测试并集46项已分别通过；最终waitReady(signal)小改恢复后Chrome4/4通过。CI尚未执行。

独立审查修正：响应缺project_id仍接受→严格匹配；成功次数双层30秒缓存→任务刷新失效Snapshot且页面入口minAgeMs=0；legacy归档仅冷/变更保留幂等收尾；新表单不继承旧反馈。真实JSON缓存仍逐文件stat，不宣称O(1)；异常fallback为原磁盘index，不能宣称异常仍实时。算法版本/评测详情仍原合同，无第二Owner。

同240真实历史10次_v53_live_jobs中位1815.73ms→40.22ms、热39.59ms；每次240 JSON→首次240后续0。可见50作业体积1009739B→14689B，减少98.545%，完整v44保留1200Epoch/1000错误样本测试。Chrome空隔离库10刷新Snapshot48.6–77.8ms、核心418–578ms、中位484ms；纯JSON.parse0–0.2ms，TTFB45.6–74.2ms，下载0.4–0.7ms。详见[evidence](evidence/FRONTEND_STARTUP_REPORT_UX_2026_10_21.json)。生产12.08秒没有现场分解，不得冒充已现场修好。

Python可复现命令：`python -m pytest tests/api/test_training_success_counts.py tests/unit/test_training_history_projection.py tests/api/test_training_job_visibility.py tests/api/test_bootstrap_label_snapshot_truth.py tests/unit/test_training_job_projection.py tests/api/test_training_priority.py tests/unit/test_training_recovery_api.py tests/api/test_training_terminal_runtime.py tests/api/test_training_metric_credibility_report.py -q --basetemp C:/t/perf-count-final`。Node相关文件173例命令/日志保存在当前会话visualizations目录frontend-governance-node.txt；Chrome新增startup-report-presentation、training-submit-lifecycle、training-report-request-lifecycle及原quality/evaluation/label/performance相关8文件。本专项已经恢复，从最终waitReady(signal)回归、需求文档收尾、正常提交推送及最终SHA CI继续。已取消临时需求没有发布提交，也不加入本专项任务清单；不得夹带其字段映射改动。

## 9. 最终提交与CI（代码验收完成）

实现及本文件基线提交：`bcf738e9dc46a0744c49fa11eae05b54238701d9`，VERSION42.24.370，已普通git push到唯一长期分支，工作树提交后干净。该SHA触发48个Actions（28 push/20 pull_request）及131个Checks，当前129通过、1失败、1运行中，不能先标全绿。最终结果补记后，本文件会产生验收文档提交，该新SHA仍须独立核验；不得用实现SHA绿色替代最终文档HEAD。

首提交CI失败留痕：Training Create First Open run39582203268 / job119162256613，15个Chrome场景14通过1失败；失败`frozen feedback candidates stay aligned with training submit provenance`的旧Mock创建响应缺少正式Task DTO必返project_id，被新安全校验拒绝。修复仅给该场景及同文件固定Benchmark夹具补实际project.id，任务接入/请求次数/溯源及重载断言全部保留；本地先复现同一RED，再两场景2/2 GREEN。无修改产品校验，无跳过测试。首提交不能作为最终全绿，后续修正提交必须独立核验。

首提交主Frontend Chrome job119162256145实际127通过1失败（128场景）。唯一失败navigation-readiness旧测试强制核心Snapshot已成功后仍轮询后台ready，与本轮核心优先合同冲突；已先在本地复现同一RED，夹具改为第一次Snapshot明确503（核心确未可用），保留原10%→60%→100%真实mock进度、同card/bar identity、scaleX及无错误断言，并新增Snapshot精确2次断言。正常核心不等待后台由本轮新Chrome测试覆盖，未删除原恢复分支测试或引入虚假进度。

接续夹具提交`943006d6776b67ef322355db6825fa78501f656b`已推送，只补Task项目身份及进度记录；该SHA在导航旧夹具修正前，不能被当作最终验收。VERSION保持370，不重复递增。


最终实现/夹具验收SHA：`f0f3010df1d00948fe60db164c8aa347b547e3a7`，21/21 Actions及55/55 Checks全部success；主Frontend Chrome job119167489279（run39583766130）实际128/128通过，0失败0跳过。准确SHA逐项证据持久化于[CI回执](evidence/FRONTEND_STARTUP_REPORT_UX_CI_2026_10_21.json)，不是沿用首提交绿色。首实现bcf738e9的两条旧夹具失败均记录并修正，943006d6不是最终验收。

本文件、当前状态、AGENTS及上述回执的验收补提仅更新文档，VERSION仍42.24.370、代码树不变。此文档补提的新SHA必须独立核验：通过本文件Git History定位其最后提交，再查看该提交Checks；不能把上述f0f3010d结果冒充新SHA。交付以文档提交本身的实际检查全部成功为条件；GitHub提交所附Checks持续保存该SHA和结果，下一会话可直接从仓库核验，无需聊天记录。正文不写入自身提交哈希以避免循环生成新提交。

本轮全部八项代码需求已验收（隔离开发/测试范围）。生产未部署，生产12.08秒现场链路、真实大库/报告仍是部署前后独立核验条件；没有把生产空间、生产模型质量或现场性能写成已达成。取消的临时权重字段专项所有改动已撤销，没有进入本轮提交。


### 10.1 生产部署前性能只读核验方案（尚未执行）

本轮不访问生产、不部署。现场12.08秒仍未按相同条件复测；第6节空隔离项目0.42–0.58秒仅为开发回归，不是生产首屏承诺。以下方案供获得独立现场只读授权后执行。

1. 使用已登录的同一测试账号，在Chrome Network启用Preserve log。记录部署域名、提交SHA、VERSION、浏览器版本、网络条件、项目ID及算法数量；不在仓库保存Cookie、Authorization或带凭据HAR。完整URL以实际请求为准：`https://<生产域名>/api/v53/bootstrap/snapshot?preferred_project_id=<项目ID>`（若现场没有此参数则记录实际URL），禁止添加`refresh=true`来改变普通刷新口径。Bootstrap `/api/v53/bootstrap/status`、算法 `/api/v12/projects/<项目ID>/algorithms`、训练任务 `/api/projects/<项目ID>/jobs` 的实际版本/参数须由Network和当前路由再确认，不把请求名当URL。
2. 分别记录响应状态、Content-Length（可缺）、Chrome encodedBodySize/decodedBodySize/transferSize、请求发出至首字节TTFB、下载responseEnd-responseStart、独立JSON.parse耗时、完整Server-Timing值和服务端日志同请求处理时间。压缩体积、解压体积及代理等待分别记录，不把fetch总耗时全部归于后端。若跨域拿不到ResourceTiming细项，使用DevTools Timing/Size，不用0表示缺失。
3. 普通首次登录或浏览器新会话标为“客户端冷缓存”；相同浏览器项目连续正常刷新10次，每次保留首屏可交互定义（项目选择、算法卡片及核心操作可响应），并记录Snapshot次数、算法/任务重复请求次数和是否发生后台ready等待。服务器冷启动只有在另行授权的实际重启或自然启动窗口才能观测；本次只读方案不能为制造冷启动重启服务。未知时标NOT VERIFIED，不能把浏览器冷缓存当服务器冷启动。
4. 从现有只读任务仓库统计/运维只读查询确认该项目全部TRAINING历史任务数量、活动/成功/失败数量、分页总数及算法数；不能从仅含50条的Snapshot推断完整历史。不在每次刷新追加全盘job.json扫描。现场若无可用只读总数接口，由运维提供受控查询结果；不得为测量修改生产数据库。
5. 检查真实算法ID/版本/当前版本、卡片成功次数与任务列表（含失败记录）一致；活动任务状态与现有TaskRepository投影一致。选择真实历史报告按需打开，记录报告API耗时/缺证据提示；不发起训练/评测/转换或删除。
6. 每次一行保存：时间、SHA、VERSION、项目、历史数来源、客户端/服务端冷暖条件、URL、HTTP、请求次数、TTFB、下载、JSON解析、压缩/解压字节、Server-Timing、核心交互时间、算法数、活动任务数及异常。十次分别列原始值，再汇总min/median/p95/max；缺项写未知及原因。若仍慢，比较代理TTFB与Server-Timing，再定位真实调用链，不能仅因隔离回归快就关闭现场问题。

验收证据表（本轮均未执行）：

| 范围 | 实际URL/项目/数据规模 | 原始10次/冷暖 | Server-Timing与Network分解 | 状态 |
|---|---|---|---|---|
| 生产Snapshot与首屏 | 待现场只读授权确认 | 待测 | 待测 | 未开始 |
| 生产算法列表与当前版本 | 待现场确认 | 待测 | 待测 | 未开始 |
| 生产训练列表/完整历史数量 | 待现场确认，不用50条代总量 | 待测 | 待测 | 未开始 |
| 服务器真实冷启动 | 本轮禁止为测量重启 | 自然窗口或独立授权 | 待测 | 未开始 |


### 10.2 Loading覆盖矩阵、确定偏差与实际修复

本表将正常/异常动态证据和未覆盖条件分开。共享样式存在不等于全平台验收。原Owner、真实任务阶段/计数、已有数据和权限保持；`api.js.withRequestDeadline`只是给Owner的一次异步操作加截止/取消，不发请求、不重试，不是第二API Client或Loading系统。默认30秒含JSON/Blob读取；请求超时不代表服务端任务失败。报告原20秒合同保持。所有进度均来自后端真实stage/processed/total或上传字节，无补造训练或任务百分比。

| 真实操作 | 原Owner与等待反馈 | 本轮确认/最小修复 | 动态证据与未覆盖 |
|---|---|---|---|
| ZIP | zip-import-runtime、upload-task-center；真实上传字节、服务端合并/校验/队列阶段，transform原位更新 | 分片已有180秒界限；任务列表/状态GET补30秒界限，不清已显示任务；原提交观察/恢复合同保留 | 原Chrome14场景：3/5/10 ZIP、两槽、取消、失败放行、刷新/迟到/项目；Node确认列表和状态signal。大ZIP实际长时合并、会话创建/标签样本接口永久Pending未逐个注入，不宣称100%覆盖 |
| 素材清洗 | submitClean427、clean-task/MaterialBatch、PollRegistry；真实扫描进度 | 原按钮busy统一spinner、每项目单flight、30秒提交/查询；未知结果只查原列表不重POST；项目和原form fence | remote-cleaning原6场景，新增真实DOM Pending及422两场景；保留进度行/条DOM不闪动。真实Agent网络断连和自然长时扫描未现场测试 |
| GT审计 | startMaterialIntegrityAudit47、原审计窗及MaterialBatch真实阶段/组计数 | 前置latest/提交/恢复查询有界；删除错误的“没有创建新任务”结论；先冻结旧ID，只有实际未知POST可恢复；原latest不能冒认新创建；项目/窗隔离 | 原完整性Chrome8场景；Node新审计unknown/旧latest/前置读取失败；并非本轮所有审计接口均已做Chrome永久Pending注入 |
| 人工标注保存 | saveAnnotationCore420/saveAnn、AnnotationWorkbench、原CAS API | silent/手动共用单flight和busy；30秒；冻结项目/图片/ann/SHA；期间新编辑不清dirty；网络/5xx/解码/超时后下次先GET，不自动POST；原版未变可再次保存、已提交同boxes/scope/state可确认、冲突保留修改 | 原material-workflows11场景；新Node20场景；新增Chrome Pending/422两场景。归一化比较真实坐标round2、source=manual与key顺序，不自动合并他人更改；额外未知持久字段保守冲突 |
| 训练创建 | TrainingSubmitRuntime、TaskRepository/TrainingTaskRuntime；三阶段真实提交反馈 | 原防重和立即仅关原窗保持；POST/JSON与原task_id恢复GET/JSON补30秒；未知不重POST | 原7场景+新Pending已受理/未找到2场景，列表慢/失败仍立即关闭、关闭重开迟到保护；成功表示创建，不表示训练完成。Compatibility准入接口永久Pending未逐个注入 |
| 训练报告 | trainingReportCore425、原Modal/Report/ECharts | 本轮无需重做：原20秒、3/10秒说明、同窗重试、身份/迟到fence保持 | 原5Chrome及Node异常矩阵，HTTP404/409/500/502/504、永久Pending、关闭/版本切换已测 |
| 独立评测 | openVersionEvaluation429同步呈现已载入权威结果；原缩略图/原图证据Owner | 不能把同步打开误写成真实评测计算；图片fetch+Blob/错误JSON补30秒，保留原controller、错误码、retry和隐藏旧overlay | 原8Chrome场景及新增缩略图/原图永久Pending→真实retry；真实计算Worker/GPU不在本次授权 |
| 模型转换 | submitConvert428、原资源/版本历史与PollRegistry | 原form锁增强为项目/算法/版本pending锁，关闭重开不重POST；busy统一；资源/历史/创建有界；未知只查现有记录，4xx可修正后提交 | model-and-conversion14原场景+新Pending/422两场景。仅隔离SDK能力/任务回执，不执行真实转换/GPU；未知任务无关联请求ID时不能自动断言是哪条历史 |
| 发布 | ExternalAlgorithmPublishRuntime原preflight→publish→readback | 原requestJson有界，按钮busy、版本实体singleflight；未知下次只查状态，PUBLISHED且requires_sync=false可解除；明确4xx可修正再提交 | 原5Chrome+新增Pending/422两场景；所有外部接口被隔离route，未写OSS/Weight。远端长时SDK/状态未知需现场只读核验 |
| 批量删除 | MaterialBatchRuntime62、原estimate/confirm/create/poll | 单flight及触发按钮busy；estimate/create/get30秒；未知写入本地持久查询锁，失败不清素材、不假定未创建；仅查同操作后台任务并沿原poll观察 | 原完整性Chrome覆盖迟到成功/失败、冻结分页、失败/重复、真实隔离仓库删除；新Node unknown/永久Pending/持久防重。后端尚无请求ID幂等合同，不能安全将某条历史认作本次提交；未知锁目前需人工核验，未宣称自动恢复闭环 |

未覆盖与生产前条件：ZIP会话/合并写入、清洗/转换/发布真实外部网络、所有长任务自然超长/客户端断电恢复没有全面实测；UI统一骨架不意味着每个业务配置窗口都改成骨架，本轮保持已有进度布局。已验证的后台刷新不清已有数据、ZIP/清洗/审计节点identity保留；其他流程不泛称全平台无闪动。未知提交锁（清洗/转换/发布为当前会话、批量任务为持久存储）不等于服务端取消；重新加载页面不代表写入未发生。没有请求关联ID的批量提交，自动解除未知锁属于尚未完成的安全恢复条件，应后续单独沿原TaskRepository补幂等/查询合同后验收，不能删除锁制造“可恢复”假象。

### 10.3 正式成功次数的业务定义与证据

- **维持既有口径，不扩大成功标准。** Durable TRAINING `SUCCEEDED` 或 `PARTIAL_SUCCESS` 且有 `result_ref`；非Durable旧 `done/finished/completed/success/succeeded/partial_success` 必须 `artifact_verified is True`。FAILED即使有Checkpoint、metrics或result_ref也不计；QUEUED/RUNNING/CANCELLED/转换/独立评测/导入均不计。
- **PARTIAL_SUCCESS（TRAINING）的实际含义**：`platform_core/training_tasks.py` 的 `_training_completion_error` 先要求任务/项目/Snapshot、done、artifact_verified、完成时间、成功outcome和非空best/last；`_finalize_completed_job` 再验证Manifest，复制模型/计算SHA、进入finalization、提交算法版本及committed checkpoint。仅因独立 `test_result.status=='failed'` 返回PARTIAL_SUCCESS（原2615附近）。远程 `node_agent_training_runtime.py` 先等控制面成果提交，再用同条件设PARTIAL；`remote_execution_transport.py`保留同语义。因此建议继续计数：训练已经真正完成，后续独立评测失败不抹除训练完成事实；该状态不表示模型质量或业务验收合格。没有将其他任务类型通用“部分成功”自动套入训练。
- `result_ref` **本身不充分证明文件当前仍物理存在/哈希一致**。计数函数仅识别已由受控finalization提交的成功回执，不在每次算法列表GET重新遍历/hash历史模型。可信终态来源是现有TaskRepository；完整性归于原成果/报告合同。人为构造成功终态+missing.json仍能满足这一投影门槛，不应写成“已核验该物理文件”。隔离finalization握手、失败finalization、terminal及count回归与此分层分别验收。
- 分页：按project+TRAINING完整100条游标读取Durable，非Snapshot50条/页面20条统计。同task_id优先canonical行去重；retry保持task_id且清result_ref，重试中不计，重新成功只计一次。算法归属只用asset_algorithm_id/algorithm_asset_id，不能用SDK算法引擎名；显式异项目历史行排除，缺project_id旧记录以所属项目目录兼容。无job的成功任务沿原不可变payload恢复。
- 口径限制：已有job的算法ID目前没有和canonical payload逐条交叉核验；正常创建链有冻结业务算法ID，本轮没有发现其产生错归属的证据。旧job缺ID/人工损坏ID可能漏计或错误归属，不能把缺证据自动当成功，也不在本轮擅自迁移历史数据。该条件列为历史只读治理待核验，不说已修复。

### 10.4 算法报告指标一致性

原bug：成功次数被权威聚合覆盖，但耗时/平均和trend仍来自所有job.json，含失败/重复/非TRAINING；页面显示成功X/X，分母其实也是成功数，“完成后准确率”亦可能包含失败Checkpoint指标。

实际修复：`app.py.v49_algorithm_report`复用原增量history/context及Durable分页/payload，不再该请求全量glob读取/enrich；同任务去重、项目/算法/类型隔离，补无job的各状态Durable身份。training_count与successful_count继续为成功数；新增attempt_count在页面称“训练任务数”，指独立task数而非重试次数。累计耗时覆盖全部这些任务（含失败及运行中当前已记录耗时）；平均仅按有限非负真实elapsed记录计算，0有效，缺失/NaN/负值不以0参与平均。返回duration_scope、duration_record_count、duration_unknown_count。列表trend仍完整，jobs字段维持最近20条兼容，补jobs_total/limit/truncated；页面标明全部任务含失败，不删除失败审计。标签汇总也是所展示全部训练任务的累计观测，不当作去重素材总量。

RED→GREEN：混合成功/失败/运行/未知耗时、重复别名、异项目/非训练、25+记录/20窗口元数据两例先因缺范围元数据RED，修后计数文件15/15；新增Node报告文案动态fixture1/1；Chrome真实空项目API及明确标记混合历史夹具1/1。失败指标仍是任务观测，成功业务趋势与其含义分开。

### 10.5 补充测试、问题留痕与接续（最终CI待本次提交）

- 进行过的基线Chrome：64/64通过（4.0分钟），8个真实app文件，包含ZIP14、清洗6、素材11、完整性8、创建7、报告5、评测8及发布5；这是受控临时后端/显式接口夹具，不是生产数据。后续受实际修改影响的集合继续复验。
- Python实际相关5文件55/55通过，0失败0跳过，5warnings（约27秒），覆盖计数、增量history、finalization握手、终态、指标可信度。新报告文件15例包含在55内，不重复累计。
- Node首次全量1129通过4失败：两例conversion VM未注入新增pending闭包/截止utility，两条源码守卫固定期待无signal调用/旧await文本；保留真实断言，原位接入闭包和utility、更新带signal精确合同。随后全量1140/1140通过；缓存标识升级后两条旧固定标识守卫失败，按真实入口/模块版本同步（包括ZIP bootstrap本身），最终全量1141/1141通过，0失败0跳过。新增标注20例、截止utility、批量/GT审计及报告均有动态RED→GREEN。
- Chrome首次扩大转换24项23通过1失败：旧夹具要求BF16选项存在且disabled，但当前正式precision列表已无该项；改验证enabled BF16数量为0，仍禁止用户选用，不添加无效产品选项。复测原转换14场景通过。新增Loading首轮26项25通过1失败为自定义按钮被侧栏遮挡，调整夹具固定可见区域；再32项31通过1失败为模拟“新form”复制了旧busy属性，改为真实新form初始空闲属性，同时继续断言pending实体锁不产生第二POST。均未force click或删除业务断言。
- 审查修复：标注非timeout网络异常也先GET、恢复核对annotation_state；发布4xx不能永久queryOnly；GT前置GET失败不能冒认旧latest；转换跨新form实体锁。各自回归已加入，不用审查意见本身当测试结果。
- VERSION本轮一次递增42.24.371，静态入口418及必要模块缓存更新；无新Owner/任务库，无生产写入/部署/GPU。
- 后续：按最终实际HEAD核对CI；所有未覆盖条件及未知提交无法自动匹配的限制须带入部署前检查。完成本次正文验收后，按用户确认**另行推进Annotorious v3专项**，其原始需求、PoC/适配器/GT合同与接续文档单独维护，不将本文件写为标注内核集成已完成。


补充最终本地结论（已完成待验收）：Python55/55、Frontend Node1141/1141；Chrome并集90个独立场景分别通过（原64、转换14、报告范围1、新Loading8、训练Pending2、新评测Pending1），0最终未解失败/0跳过，不将复测重复次数累加。最后受ZIP/评测/Loading/完整性改动影响的39项38通过1失败：ZIP观察请求计数夹具固定sleep200ms时原reconcile仍busy，按原防重合同不会再发GET，得到0；新增只读snapshot.busy观察，夹具等待真实空闲后清poll再精确测一次，原1次GET断言保留，单例1/1复验通过，未增加重复轮询或删除断言。隔离证据不代表生产覆盖。

本次关联提交通过本节Git History定位，CI必须读取该提交Checks；当前提交前未声称CI通过。补记CI文档产生新SHA时也须重新核验自身。正式交付条件为最终SHA全部相关CI成功；全平台未覆盖项目、物理成果只读核验、无请求ID未知提交恢复限制仍保留，不将本次限定验收写成生产可部署结论。


最终审查补正：f081d408720dd902931de93597dfb8c9e1d4d7e4为本次主体实现，尚在CI（已有36个工作流成功，不能当最终全绿）。ZIP原isCurrentProject未检查destroyed，销毁后待返list/get可重新upsert/render；新增真实Runtime动态测试先RED复现upsert1，再仅补!destroyed为GREEN，ZIP文件32/32通过。静态ZIP入口/模块标识同步4226364，VERSION仍本轮371。最终SHA应以后续包含该修正提交为准，其自身CI独立核验；不使用f081d408替代。

销毁修正后最终全量Frontend Node1142/1142通过、0失败0跳过（6.6秒），Python55及Chrome90既有结论不重复累计；最终CI回执待本修正准确SHA。


### 10.6 准确实现SHA CI与最终文档接续

最终补充代码验收SHA **`bbb4950d8aee4dc3acf51bcf30760a9c8420d619`**，VERSION **42.24.371**，正常推送长期分支；实际 **35/35 Actions、98/98 Checks全部success**。主Frontend run39593145176 / job119198831386，真实Chrome **140/140通过，0失败0跳过（7.9分钟）**。完整逐项SHA、结论及链接持久化于[补充CI回执](evidence/FRONTEND_STARTUP_REPORT_UX_SUPPLEMENT_CI_2026_10_21.json)。本地Python55、Node1142及Chrome90独立场景分别通过，不能把本地90与CI140累加为234。主体f081d408中一条旧Remote Material Import因新推送取消，不作为最终全绿；最终bbb4950d全部35已独立核验，没有沿用旧SHA。

本次补提只保存验收回执、专项状态与入口，运行代码和VERSION371保持。文档提交自身的SHA由本文件Git History定位，CI由该提交附加Checks持久记录；必须等自身检查全部成功才完成文档交付，不把bbb4950d结果替代文档提交检查。文件不内嵌自身哈希以避免哈希循环。

正文五项补充任务的限定验收已完成：矩阵包含明确未覆盖/未知恢复限制，成功口径证据与报告名称一致，生产只读方案仅整理未执行。生产12.08秒未实测关闭，生产未访问/部署/修改。下一步按用户确认单独实施Annotorious v3，须创建其唯一专项、先隔离PoC，再正式切入口；本专项的标注保存安全修正应继承，不得被新内核覆盖。GT清空/待标注的新业务合同归Annotorious专项审计与验收，不提前写为此处已支持。
