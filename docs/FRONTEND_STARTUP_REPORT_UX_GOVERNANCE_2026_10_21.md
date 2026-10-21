# 页面启动、训练报告与训练任务交互综合治理（2026-10-21）

本文件为本专项唯一需求、进度、问题及验收依据。与 GT 素材生命周期专项分开维护。

## 1. 基线、授权与验收边界

起始实际 HEAD `db676bbfe6e6641466025822a38754697e79333f`，长期分支 `feature/external-algorithm-publishing`，VERSION `42.24.369`。已 fetch，远端与本地一致、工作区干净；其他工作树及未完成修改不覆盖。允许代码、隔离测试、文档、正常提交和推送；禁止生产部署、生产数据库修改、正式素材删除、历史 Bundle 清理和真实 GPU 训练。

用户现场 snapshot 200 耗时 12.08 秒，其他 cache/config/session/status 为 590/364/347/331ms；这只是现场证据，尚未取得现场完整 URL、字节数、TTFB、下载、JSON 解析或服务端分解，不能冒充本地复现。热启动核心交互目标约 2 秒，最终须分别列真实隔离测量和现场未核验条件。

## 2. 已确认需求与实现约束

| 编号 | 优先级 | 正式需求 | 当前状态 |
|---|---|---|---|
| PERF-01 | P0 | 审计 Snapshot/历史任务扫描，核心数据优先，按需历史报告，复用有效快照且任务与算法版本真实 | 已完成待验收 |
| UX-01 | P1 | 科技蓝、浅色、柔和骨架、小 Spinner、平滑淡入；后台保留数据，提交防重，长任务真实进度 | 已完成待验收 |
| REPORT-01 | P0/P1 | 即刻弹窗、骨架、真实报告、有界等待、明确错误与重试、请求/版本隔离、关闭清理 | 已完成待验收 |
| MODAL-01 | P1 | 报告和独立评测居中正常弹窗，约1120px/86dvh，固定标题独立滚动，保留全部功能 | 已完成待验收 |
| HOVER-01 | P1 | 操作图标统一高亮及跟随指针、边缘避让提示，键盘/Esc/触屏可用，装饰图标不加无意义提示 | 已完成待验收 |
| CHART-01 | P1 | 保留真实曲线/采样/Legend/DataZoom/Resize/Dispose及真实悬停，彻底删除报告恢复视图 | 已完成待验收 |
| TRAIN-01 | P1 | 服务端可靠确认独立TRAINING任务身份后接入Runtime、立刻仅关原创建弹窗、成功反馈、后台刷新 | 已完成待验收 |
| TRAIN-02 | P1 | 只计可信正式成功独立训练任务；去重，不计失败/取消/排队/运行/转换/评测/导入；卡片排序概要一致 | 已完成待验收 |

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
| A | 全部，P0/P1见第2节 | 已完成待验收 | 最新基线、Owner审计、动态RED、性能基线与独立审查 | 生产现场只读分解未取得，不是本地验收 | `bcf738e9dc46a0744c49fa11eae05b54238701d9` |
| B | PERF-01 | 已完成待验收 | 增量读、单次索引同步、核心提前返回、概要瘦身 | 元数据仍线性检查；现场12.08s须部署后另验 | `bcf738e9dc46a0744c49fa11eae05b54238701d9` |
| C | TRAIN-01/02 | 已完成待验收 | 立即正确关闭、未知恢复、防重、权威成功次数、排序缓存联动 | 生产不执行训练；无代码阻塞 | `bcf738e9dc46a0744c49fa11eae05b54238701d9` |
| D | REPORT/MODAL | 已完成待验收 | 报告有界请求/恢复、旧响应隔离、正常弹窗和原生命周期 | 生产真实报告需部署后核验 | `bcf738e9dc46a0744c49fa11eae05b54238701d9` |
| E | UX/HOVER/CHART | 已完成待验收 | 统一样式/骨架/提示、真实曲线、恢复移除 | 全平台既有任务Owner保持；无代码阻塞 | `bcf738e9dc46a0744c49fa11eae05b54238701d9` |
| F | 全部 | 进行中 | 本地Python/Node/Chrome及版本/语法检查 | 正常推送及最终实际SHA CI待完成 | 待最终SHA |

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

本轮代码完成后剩余为最终提交/CI和文档验收；不得重建Owner或重复实现已测功能。生产部署未授权/未执行，生产数据库/素材/Bundle/外部Weight/GPU均未操作。现场应在独立部署授权后读取真实Network全URL/字节/Server-Timing/TTFB，核验真实报告、算法版本与任务状态、连续10刷新和大量历史。生产12.08秒不能用隔离数据冒充关闭。

## 8. 中断及恢复检查点（本专项继续，未提交）

2026-10-21曾被紧急指令短暂中断；用户现已明确撤销该临时需求并要求继续本专项。临时专项所有13个未提交文件仅在独立工作树修改，已逐文件git restore并确认diff/status干净，无commit、无push、无冲突；随后清理该独立工作树。本专项原有成果未受影响。中断时：本专项代码保留在原长期分支工作树，未commit、未push、未核验本轮CI；本地VERSION已改42.24.370但未发布，后续整合须按届时远端版本重算。不得把本地通过当远端验收。

实际已实现：增量历史JSON投影和实时Durable覆盖；核心snapshot先于后台ready，20秒deadline与恢复；Snapshot作业报告概要瘦身；权威完整成功训练次数及排序；创建可靠身份后立即仅关原Modal；报告20秒有界等待、重试与迟到隔离；报告与评测1120px/86dvh居中；共享Loading/Skeleton及委托Tooltip；移除恢复控件。源码改动见工作树git diff，尚未提交。

本地证据：Python9文件104通过、0失败0跳过；最终相关Node173通过、0失败0跳过。联合Chrome46项首轮44通过2失败：计数新夹具未等启动旧inflight（夹具修正）、新训练表单继承旧success遮罩（产品修正，submissionRoot限定并清理新form状态）。后续原完整训练页面+7矩阵8/8，startup/presentation/cache4/4通过；原其余44场景无需重复计数。全部测试并集46项已分别通过；最终waitReady(signal)小改恢复后Chrome4/4通过。CI尚未执行。

独立审查修正：响应缺project_id仍接受→严格匹配；成功次数双层30秒缓存→任务刷新失效Snapshot且页面入口minAgeMs=0；legacy归档仅冷/变更保留幂等收尾；新表单不继承旧反馈。真实JSON缓存仍逐文件stat，不宣称O(1)；异常fallback为原磁盘index，不能宣称异常仍实时。算法版本/评测详情仍原合同，无第二Owner。

同240真实历史10次_v53_live_jobs中位1815.73ms→40.22ms、热39.59ms；每次240 JSON→首次240后续0。可见50作业体积1009739B→14689B，减少98.545%，完整v44保留1200Epoch/1000错误样本测试。Chrome空隔离库10刷新Snapshot48.6–77.8ms、核心418–578ms、中位484ms；纯JSON.parse0–0.2ms，TTFB45.6–74.2ms，下载0.4–0.7ms。详见[evidence](evidence/FRONTEND_STARTUP_REPORT_UX_2026_10_21.json)。生产12.08秒没有现场分解，不得冒充已现场修好。

Python可复现命令：`python -m pytest tests/api/test_training_success_counts.py tests/unit/test_training_history_projection.py tests/api/test_training_job_visibility.py tests/api/test_bootstrap_label_snapshot_truth.py tests/unit/test_training_job_projection.py tests/api/test_training_priority.py tests/unit/test_training_recovery_api.py tests/api/test_training_terminal_runtime.py tests/api/test_training_metric_credibility_report.py -q --basetemp C:/t/perf-count-final`。Node相关文件173例命令/日志保存在当前会话visualizations目录frontend-governance-node.txt；Chrome新增startup-report-presentation、training-submit-lifecycle、training-report-request-lifecycle及原quality/evaluation/label/performance相关8文件。本专项已经恢复，从最终waitReady(signal)回归、需求文档收尾、正常提交推送及最终SHA CI继续。已取消临时需求没有发布提交，也不加入本专项任务清单；不得夹带其字段映射改动。

## 9. 最终提交与CI（实现已推送，验收进行中）

实现及本文件基线提交：`bcf738e9dc46a0744c49fa11eae05b54238701d9`，VERSION42.24.370，已普通git push到唯一长期分支，工作树提交后干净。该SHA触发48个Actions（28 push/20 pull_request）及131个Checks，当前129通过、1失败、1运行中，不能先标全绿。最终结果补记后，本文件会产生验收文档提交，该新SHA仍须独立核验；不得用实现SHA绿色替代最终文档HEAD。

首提交CI失败留痕：Training Create First Open run39582203268 / job119162256613，15个Chrome场景14通过1失败；失败`frozen feedback candidates stay aligned with training submit provenance`的旧Mock创建响应缺少正式Task DTO必返project_id，被新安全校验拒绝。修复仅给该场景及同文件固定Benchmark夹具补实际project.id，任务接入/请求次数/溯源及重载断言全部保留；本地先复现同一RED，再两场景2/2 GREEN。无修改产品校验，无跳过测试。首提交不能作为最终全绿，后续修正提交必须独立核验。
