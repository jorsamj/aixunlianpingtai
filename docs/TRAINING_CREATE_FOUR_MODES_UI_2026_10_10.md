## 2026-10-28｜三步训练工作台、素材历史与跨设备增强（本地限定验收完成，最终SHA CI待核验）

这是用户本轮附件及全部补充要求的唯一进度入口，旧节仅代表原版本。基线远端6df8cf0e / VERSION42.24.395，原a741075c退役WIP与5944/模板/其他工作树不动；本轮复用干净targeted-upload-tabs-ui工作树，只向长期分支正常推送，不生产部署/训练/改GT或原图。用户最后指令覆盖早先广泛测试要求：仅必要语法、少量核心安全合同及实际浏览器冒烟；保留已有测试，不扩大框架。

### 审计与设计基线

- 打开链：trainingCreationInputsReady旧合同依赖资源+recommendation，start Promise.all等待两者及外部preflight后再开正式表单；system/recommendation每次独立Torch探测最长8秒。生产究竟阻塞资源/网络/SQLite还是远端尚未现场测量，不把代码风险当生产已证实根因。
- 标签链：checkbox→唯一Draft.update→Submit/readiness与其他UI→summary.innerHTML→body MutationObserver→label.refresh→panel.innerHTML。label-only订阅保护不足以阻止跨区域重建。改仅明确挂载/目录/继承身份变化刷新；选择/计数差量更新，搜索与panel稳定，页内最多24真实checkbox。
- Picker：open清空selected，cache-hit先于请求序号/abort，旧响应可覆盖命中页；role-page每请求全候选JSON+GT分类并重建TEMP。复用原分页/Repo/GTclassifier/缩略图，按Material+GT+usage+contract版本有界缓存，跨页bulk同过滤合同，保持50000显式上限。
- 历史：原training_history_projection仅内存JSON缓存，不是逐素材使用索引；Snapshot是冻结/角色证据，Task SUCCEEDED/FAILED不是逐图使用证据。原first_batch及epoch执行事实用于新可重建usage投影，selected/possible/used/evaluation/unknown严格区分，旧缺证据保持unknown。父模型暴露来源不得当新独立Test；普通历史val/test可以重新划分，原固定Benchmark仍受保护。
- 划分：继续原SHA/同源组件+固定seed+分组Test/Val机制，新增source_root/derived来源关联。先资格再随机，不拆同组凑比例，保存真实counts/ratios。已有历史冻结重放不变。
- UI：原Modal内部重组为数据模型→方案→确认，保留同一Draft/Submit；右侧只读摘要、单滚动内容/固定footer，7组高级参数原位编辑，模式/精度/参数唯一入口。异步输入独立状态和重试，正式表单先出现，资源未就绪不能提交；推荐失败只提示、不伪装实时建议，提交前原准入/preflight/幂等/UNKNOWN仍强制。
- 增强：平台全局默认关闭、任务继承或显式启停；新请求在正式Task受理前解析并冻结global revision，旧None不改变旧任务hash。原冻结/缓存/portable materialize后只生成train派生PNG及相同YOLO标签，原图/GT/val/test不变；ratio/count/manual、1–3总副本、四preset固定seed，任务专属目录、派生清单/hash与恢复幂等。矩阵范围误配仅模拟设备差异，不宣称具体摄像头标定。

### 阶段进度

| 阶段 | 内容 | 状态 | 证据/待办 |
|---|---|---|---|
| A | Owner、业务合同及旧UI审计 | 已完成待验收 | 原四视口before截图已存docs/images/training-workbench-20261028；生产耗时未测 |
| B | 立即打开、独立加载/缓存、稳定标签和草稿 | 已完成待验收 | 原Owner已接线；独立加载/失败重试/1000标签/10次开关真实Chrome通过 |
| C | Picker性能、统一过滤/恢复/批选与历史 | 已完成待验收 | API与Node定向通过；100–50000条隔离性能4/4，50k冷555ms/缓存19ms；生产未验 |
| D | 可信使用投影、祖先/同源资格及冻结 | 已完成待验收 | 原Task库可重建投影/执行事实/fencing；缺祖先证据禁止新独立Test，可信固定Benchmark仍复用原Owner |
| E | CPU train-only颜色增强及全局/任务策略 | 已完成待验收 | 四预设金值、原图/空标签/重试/原准备提交链通过；实际GPU/设备效果NOT VERIFIED |
| F | 三步布局/截图/最小回归/文档提交 | 进行中 | VERSION396；本地限定验收及截图完成，尚未提交/推送，最终SHA CI待核验 |

相关实现文件、测试回执及问题关闭证据随阶段补充。不得用文档描述代替代码实现；未验证历史coverage/实际GPU/NAS/OSS与生产性能都保留NOT VERIFIED。

参考技术合同：[Ultralytics当前配置](https://docs.ultralytics.com/usage/cfg/)、[BT.601官方标准](https://www.itu.int/rec/r-rec-bt.601/)、[BT.709官方标准](https://www.itu.int/dms_pubrec/itu-r/rec/bt/R-REC-BT.709-6-201506-I!!PDF-E.pdf)。当前官方页面已含更新版参数，不自动把全部参数加进本项目：以当前实际Runner允许参数为准，不新增未经验证BGR/CutMix/fraction等能力。Ultralytics许可边界不因本轮增强改变。

### 实际实现与兼容取舍（2026-10-28）

- 前端：`static/app.js` 重组原Modal为真实三步，仅最后一步可创建；模式和参数单一编辑入口，7组高级参数、只读有效参数摘要。`training-create-modal.css` 收敛旧布局，0条`!important`。`training-labels.js` 删除body全局观察与旧注入样式，稳定搜索/选择DOM，每页24真实输入，继承标签分离。`training-draft.js`/`training-submit.js` 保持原状态与幂等/UNKNOWN核验。
- 加载：`training-create-hydration.js` 在任何非关键远程请求之前打开正式表单，资源/推荐/preflight独立状态、独立重试；资源5分钟、推荐1分钟项目隔离缓存及并发合并。资源未确认禁止提交，preflight仍由原提交准入强制。诊断含URL/次数/耗时/缓存/JSON重序列化字节数（不是压缩网络字节数），不含凭据。没有为本轮增加全站缓存框架。
- Picker：原runtime/API共享过滤，左筛选/右网格或列表/固定确认；恢复草稿，12页有界缓存、修订核验、超时/取消/过期隔离；保留跨页全选/反选/全可用/清除及显式50000上限。role分类8项版本缓存，普通页批查历史；不在打开时补建全部旧任务索引。
- 历史：`training_material_usage.py` 在原Task SQLite库添加可丢弃投影表/索引及修订触发器，不改原Task表业务语义；selected/possible/used/evaluation/unknown由原Snapshot与真实first-batch/epoch/validation事实形成，失败不抹除已经暴露的事实。当前算法/其他算法过滤与批量选择一致。`training_usage_maintenance.py`及CLI默认dry-run，有限批次/持久游标/中断重放，只写投影，未运行生产补建。
- 划分：原`training_splits.py`/`snapshots.py`继续固定种子与SHA/来源组机制；新增父子来源身份统一、祖先暴露不可成为新独立Test。未知父模型历史默认报`TRAINING_TEST_ANCESTRY_UNKNOWN`，只有原后端已验证固定Benchmark复用可例外；不静默猜测未训练。历史无新字段请求保持原hash/冻结合同。UI默认新素材策略，明确允许用户改用历史素材；固定Test保护不随此选项关闭。
- Worker：原local/Agent materialize完成划分后生成train增强；`training_tasks.py`/`remote_training_tasks.py`/`train_worker.py`/`node_agent_training_runtime.py`/`remote_execution_transport.py`沿原lease/fence/报告Owner记录真实使用事实。`agent_execution.py`保留严格bool执行证据（字符串不冒充事实）。回收、StorageManager、AnnotationRepository与原GPU独占不重建。原模型提交报告及恢复详情分别显示原train数量、增强数量、实际输入数量，Snapshot原始划分数量不被改写。
- 全局策略：原配置目录JSON+原FileLock+原子替换/CAS修订；默认关闭，任务继承或显式启停。新任务正式受理时冻结global revision，客户端不能伪造来源；排队期间修改全局不改变已受理任务。旧任务缺字段不强行继承新策略。

### 四种CSC预设：明确输入、数学定义与验证

基准假设为Pillow解码后的8-bit非线性RGB（R′G′B′），未知摄像头YUV/传输函数/ICC标定，不能还原真实摄像头管线。本期模拟**编码矩阵/范围被接收方误解读**的设备链路差异；预设名表示编码端，接收端在本期固定为另一矩阵及另一范围。不是标准往返色彩转换，不宣称对应某台设备的精确输出。HSV保持原功能，CSC与HSV分开配置、可叠加；不修改元数据冒充增强。

归一化RGB至[0,1]：Y′=KrR′+(1−Kr−Kb)G′+KbB′；Cb=(B′−Y′)/(2(1−Kb))，Cr=(R′−Y′)/(2(1−Kr))。601使用Kr=.299/Kb=.114，709使用Kr=.2126/Kb=.0722。Limited编码Y=16+219Y′、C=128+224C；Full编码Y=255Y′、C=128+255C。编码量化使用nearest-even，Full裁剪0–255；按接收方范围还原后使用接收方矩阵反解RGB，输出nearest-even并裁剪0–255，保存PNG。没有采用相匹配逆变换，避免恒等抵消。

| 预设 | 本期编码→误解码假设 | 输入RGB(71,137,213)的实际输出 | 基本结果 |
|---|---|---|---|
| BT.601 Limited | 601 Limited→709 Full | (70,132,204) | 像素改变、尺寸不变、重放字节一致 |
| BT.601 Full | 601 Full→709 Limited | (58,138,232) | 像素改变、尺寸不变、重放字节一致 |
| BT.709 Limited | 709 Limited→601 Full | (81,135,197) | 像素改变、尺寸不变、重放字节一致 |
| BT.709 Full | 709 Full→601 Limited | (73,142,223) | 像素改变、尺寸不变、重放字节一致 |

四个输出互不相同，金值断言保存在`tests/unit/test_training_robustness.py`。饱和/灰度等个别输入可能因量化不变；实际副本若与原解码RGB完全相同，报`CSC_NO_PIXEL_CHANGE`而不计为增强。数量超过最终train可用原图报`CSC_SELECTION_COUNT_EXCEEDS_TRAIN`，不静默截断。每张选中原图总副本数1–3，按seed在已选预设中确定分配；四预设均可选择/独立验证，不意味着每张图默认生成四张。

严格顺序：素材资格/去重→冻结划分→后台train-only增强→训练。比例/数量/手动抽样只针对最终train；手选落入val/test报错。派生清单保留source_root/direct parent/source_group、变换版本/编码解码参数/seed/source与派生SHA。原图、原GT、val/test不变，原YOLO标签字节继承，已确认负样本保持空标签；未审核素材不转负样本，负样本管理分类不注册检测类别。任务重放使用同一确定身份，不重复累计。不在弹窗打开时读解码图片，前端数量是预估，报告实际数量来自校验后的manifest。

### 最小回归与失败关闭证据

未运行全仓本地测试或真实GPU训练，以下是按改动分组的实际结果，存在重叠，**不相加冒充唯一用例总数**：

| 范围 | 实际结果 | 说明 |
|---|---|---|
| 后端定向原合同与新增历史/CSC | 初轮75通过、3 Windows symlink跳过；后续受影响核心37通过、冻结14通过 | skip不算通过，Linux最终CI另核 |
| Picker API/Node | API18通过，新增同源子图查询/批选一致1通过；Node20通过 | 不读取全历史JSON |
| 维护中断/重放、未知祖先、API全局CAS/受理冻结 | 对应独立小组2、1、2通过 | 无生产补建或收费接口 |
| CSC四金值/负样本/无效副本/严格数量/真实准备提交链 | 分组3、3、2通过 | 原Trainer以隔离轻量回调验证，无GPU，无300轮训练 |
| 前端工作台/标签/提交 | Node66通过；hydrate与Draft32通过；原Owner守卫17通过 | 原幂等、UNKNOWN保留 |
| 恢复详情/Agent执行事实 | 各1通过 | 原train/aug总量分开，bool严格透传 |
| 真实Chrome | 新UI8种独立场景通过，新增1440×900布局1通过；旧关键6场景通过 | 截图/真实wheel/1000标签24DOM/10次开关/全局保存恢复；不是生产训练 |
| 最终缓存Owner | Node10/10通过 | 源build/browser/workflow与实际加载cache同步 |
| 最终语法及差异 | Python23、JS21语法检查0失败，diff --check通过 | 没有执行无关全仓测试 |

测试过程中的RED和修正：旧ready合同阻止表单先开；旧步骤测试仍在隐藏面板操作，随新三步流程显式切步后原业务断言保留；旧源码守卫依赖已退役DOM入口，迁移至唯一真实Owner。独立审查发现未知父模型Test资格和Picker来源字段缺失，已加后端拒绝及查询/批选一致回归；Agent序列化曾丢执行事实，已严格bool透传回归；CSC数量静默截断/像素恒等计数已改明确失败。缓存版本四条旧精确值守卫初次失败，更新源/Chrome/CI至新build后10/10通过。未删除安全断言或跳过旧测试以求绿色。

### 隔离性能及视觉证据

[实际测量JSON](images/training-workbench-20261028/load-measurements.json)：同一隔离Chrome推荐接口受控延迟1000ms，旧6df8cf0e正式表单1484ms，新正式表单145ms，各请求一次；最近定向复测普通隔离输入61ms、受控失败时51ms打开，推荐500后局部重试。测量对象是正式表单而非旧等待壳；早期临时计时误量等待壳已校正，不能引用该数值。生产接口/SQLite/OSS具体阻塞点NOT VERIFIED，不能将本数字当生产SLA。

隔离无框素材微基准（毫秒），对应现有performance测试4/4通过：

| 素材量 | 首次role页 | 缓存页 | bulk ID |
|---|---:|---:|---:|
| 100 | 22.59 | 13.87 | 11.34 |
| 1000 | 30.19 | 14.26 | 16.00 |
| 10000 | 112.70 | 18.92 | 13.97 |
| 50000 | 555.22 | 19.40 | 38.48 |

这些夹具不代表真实GT密度、NAS/OSS缩略图和生产性能。旧role-page全候选重复分类的确定代码路径已消除；没有相同机器同夹具旧版微基准，不编造旧耗时。

截图目录`docs/images/training-workbench-20261028`：旧版1920/1440/1366/760四张；新版1920×1080、1440×900、1366×768、1093×614（125%等效可视区）、375×812，每视口五种状态。均真实Chrome，固定头尾与真实滚轮；未把deviceScaleFactor当真实浏览器缩放。

- [布局前1366](images/training-workbench-20261028/before-1366.png) / [布局后第一步](images/training-workbench-20261028/after-1366x768-step1.png)
- [第二步基础](images/training-workbench-20261028/after-1366x768-step2-basic.png) / [自定义](images/training-workbench-20261028/after-1366x768-step2-custom.png) / [跨设备增强](images/training-workbench-20261028/after-1366x768-step2-robustness.png) / [最终确认](images/training-workbench-20261028/after-1366x768-step3-feedback.png)

### 首推CI问题及定向修正（不借旧绿色）

首推代码`b2e116bf086b7ae2c5f9208803e76d786981885a`已正常推送。CI发现原RemoteExecutionTransport允许省略TaskRepository，但新增投影无条件构造`Path(None)`，导致多个复用该测试的工作流失败；已保持原可选构造合同，仅正式存在原TaskRepository时写投影，生产generation/fencing检查不降低。原失败transport用例定向1/1通过。另两个测试适配问题：新API冻结测试的无Worker helper缺`run_owned`（补齐该预执行夹具能力，不改生产lease）；旧labels精确build仍指向422571，已更新为实际422572。API1/1、原labels Node10/10通过，未删除原断言。旧ZIP联动源码守卫还引用已删除的v2 CSS选择器及15px字号，已对应当前统一modal作用域/13px紧凑标签更新，原四模式/唯一字段/ZIP业务断言保留，5/5通过。

首推Release Regression的SQLite关闭用例出现10连接未关闭；本轮未改TaskRepository连接Owner，该用例本地单独1/1通过，尚不能认定根因或已修复。保留待后续准确SHA核验，不删断言、不缩小CI范围。


修正提交`f496882e978bbe4773d8b1517110e0d1f6c26454`已推送；当时33个Actions中31成功、1失败、1仍运行，准确94 Checks中89成功/4失败/1运行，不能标绿。新发现：设备revalidation旧字符串断言假定无条件auto，与保留用户选择冲突，改执行真实函数验证auto优先/有效手选保留/失效回退，3/3通过。旧quality-reports有7例仍访问隐藏步骤/退役第二配置弹窗，已按真实三步与inline7组更新，所有提交/划分/精度/继承断言保留；本文件9例分批通过（首6通过3导航strict冲突，限定button后只复跑失败3例全部通过）。同时修复真实缺口：资源异步返回后，空imgsz未初始化；仅为空时采用当前算法default_imgsz，保留继承800及用户640，新浏览器验证首次1280通过。app cache444。

VERSION396本轮不二次递增。后续修正SHA及CI必须独立核验，首推不能标记全绿。

### 首开永久守卫收尾

`d5615f7c852adf00683858f705760c0789e5d4d3`已推送。该SHA的Release Regression（含此前连接关闭用例）实际成功；只说明准确SHA本次通过，前一轮偶发根因仍未确认。其首开CI剩余两平台失败为永久源码守卫：旧同步preflight测试名、旧整体save的continue_threshold字符串、禁止独立patience编辑。已保持原训练语义：不新增patience入口，原checkbox请求与Worker实际决议分开，目标编辑仍强制continue_threshold=0。永久守卫仅将前两项绑定新真实Owner，保留禁止第二patience与低分停止保护。完整现有bash守卫退出0、定向Node23/23通过。对应Chrome早停用例先暴露本轮测试仍期待新增patience1个，恢复原0个断言；再暴露内联组丢失Worker执行说明，已补真实请求/实际说明，最终1/1通过。app cache445，VERSION396不二次递增。

### 准确代码SHA的CI与浏览器总任务超时

代码`6baf0037bf686ad64269e51ebaac6650fc7a3e9f`正常推送后，实际41 Actions为40成功/0失败/1取消，113 Checks为112成功/0失败/1取消。原Frontend Runtime Stabilization的303项串行Chrome因GitHub明确注解`The job has exceeded the maximum execution time of 20m0s`取消（[原运行](https://github.com/jorsamj/aixunlianpingtai/actions/runs/40668307650)）。日志无完成汇总，不能推断303项通过，也不把取消写成绿色。

仅调整原workflow执行方式：Playwright原生两个shard，各独立GitHub runner/隔离后端、各仍workers=1、20分钟上限和完整原文件清单不变；fail-fast=false保留两份结果，不新增框架/用例/范围，不增加接口超时、不跳过或降低断言。`--list`发现核对原303=分片154+149，交集0、遗漏0；这是发现检查，不冒充执行通过。此调整避免重复串行跑到20分钟被取消；必须核验新SHA实际结果。

### 浏览器分片负载与旧hydration夹具

`4a703c2d5ad2a7acc7e144be059b75953ad07b56`实际21 Actions为20成功/1取消，56 Checks为55成功/1取消；第一分片154/154通过（7.4分钟），第二分片149项再次超过20分钟取消，没有完成汇总，不宣称其通过。两个分片按文件分配的数量不等于运行耗时均衡。

定点审计只发现`training-submit-lifecycle.spec.mjs`两项first-open HTTP/timeout仍假定旧阻塞等待壳，已对应真实原hydration改为正式表单立即挂载、resources/recommendation独立错误及重试，保留HTTP500/超时恢复/只开一次，并增加编辑保留断言；只跑这两项2/2 Chrome通过。其余Submit最小DOM和admission/workspace不应机械加步骤，未改、未重跑。

原303项文件清单与20分钟/单Worker保持不变，使用原生3 shard并启用line reporter便于定位长用例。发现核对303=101+107+95，无重复/遗漏；没有运行本地全仓。三组分片的真实执行仍须核验新提交，不将分片发现数当通过数。本次只有测试/CI/本节记录变化，业务代码仍与6baf0037一致。

### line日志定位到的真实兼容回归及修复

`930ced3355f1399d23168e2f8520b3dd0cfd8201`实际21 Actions为20成功/1失败；57 Checks为55成功/1失败/1取消。分片1的101项通过，分片3为91通过4失败（2.8分钟）；分片2反复等待按钮，超时前已报告13失败，后续未完成，不将取消视为通过。

line日志纠正了此前只按总任务时限分析的不足：真实问题既有旧测试流程，也有新代码状态归属。不是单纯靠更多分片掩盖失败。

1. 三项on-demand错误重试在已处于第三步时用宽泛`[data-training-step=3]`，匹配根节点和按钮；所有导航限定button，HTTP500/断网/超时三场景3/3通过。隔离8013及默认8011的重复验证不叠加计算；未降低原断言。
2. 新资源守卫在Submit try外读取getState，异常跳过原notify/finally；移入同一try，初始异常Chrome1/1通过。未产生请求ID/POST时不会伪造UNKNOWN，原pendingOutcome保护仍优先。
3. 全局预热的资源error/loading泄漏到非workbench原Submit独立Modal，导致governance按钮永久禁用。仅新hydration状态门禁绑定真实workbenchMounted根节点，所有Modal原资源/引擎/设备与后端完整准入仍保留。38真实异常素材独立Modal1/1通过；正式工作台慢资源不可提交/推荐失败重试/编辑保留1/1通过，证明未放宽正式资源门禁。独立只读复核通过。
4. duplicate-conflicts的真实表单仍在第一步点隐藏提交按钮；仅两处入口增加第三步确认，两个受影响真实场景分批1+1通过，保留原GT、实际Worker删除、历史不可变与仅一POST断言。

业务版本仍396，entry main443、Submit422610；app445/CSS4226356不变。受影响cache Owner Node10/10通过；不重跑未变化的本地全仓。待后续准确SHA CI最终验收。

### 接续、剩余风险与交付状态

VERSION42.24.396，entry app445/main443、CSS4226356及受影响模块cache已更新。推送前fetch确认远端仍为6df8cf0e；本地未提交时不声称已有SHA。最终提交及准确SHA的CI回执在下一节追加。当前B–E为本地完成待远端验收，不借上一版绿色。

生产部署、真实NAS/OSS/远程GPU、摄像头色彩标定、模型误报/香烟召回改善、旧历史缺证据恢复都NOT VERIFIED。无生产读写、无真实训练、无原图/GT迁移。未知历史默认保守；受控CLI可后续按独立范围补建，不能自动清空未知。模型效果需后续同一冻结可信Benchmark独立评测，本次不承诺数值提升。

新会话从本节、原hydration/Draft/Submit、training_robustness、training_material_usage及Picker API继续；不得重建Task/Storage/GT/缓存/标注Owner，不扩大上一轮训练模板。原a741075c WIP、5944、两份模板测试及其他工作树保留。任何实际问题必须记录，不用文档宣称代替实现。

## 2026-10-25｜创建 Loading 与异常恢复专项（代码及隔离CI已验收）

本节是本轮唯一接续记录。用户授权：只修改已证实的训练创建异常；复用 TrainingSubmitRuntime、原 Modal、withRequestDeadline、原 TaskRepository 和 task_id 幂等；不改变训练参数、数据划分、GT/冻结、GPU独占或 Worker；不部署生产。其他模块只轻量排查，共享缺陷才修复。

### 需求基线与实施计划

| 阶段 | 需求与模块 | 状态 | 已有证据／剩余 |
|---|---|---|---|
| A | 真实代码、最新分支、持久化与幂等审计 | 已验收 | 远端243858b9/VERSION386基线；原工作区4个标注提交、全部WIP与两份模板测试保留 |
| B | 提交全过程异常保护；最终DOM恢复；单一真实阶段 | 已验收 | 原submit同一try/finally；真实DOM与回调异常回归通过 |
| C | 首次准备请求截止时间、错误/重试、迟到结果隔离 | 已验收 | 资源/推荐/外部算法有界，原缓存复用；挂起缓存取消与真实重试通过 |
| D | 创建结果核验、稳定UNKNOWN、原ID查询、后端业务码 | 已验收 | 持久化与执行终态分离；原ID收据恢复，409/5xx正文中断按UNKNOWN核验 |
| E | 最小Node/Python/Chrome、版本、正常提交/准确SHA CI | 已验收 | 最终代码382c1b95已普通推送；准确26/26 Actions、68/68 Checks成功；文档自身新HEAD另核 |

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

### 最终恢复边界补齐（待此后提交自身CI）

- 母模型缺失/未就绪/无效文件返回 `TRAINING_MOTHER_MODEL_UNAVAILABLE`，只改变错误投影，不改变母模型选择、校验或下载规则。新增API先RED后GREEN；缺失母模型不得产生任务，原预置相关必要3例也通过。本地Python不同用例11通过（原7+本组4）。
- UNKNOWN期间关闭后重新打开不同任务ID的训练草稿，必须仍能查询原任务；查询成功只解锁新草稿，不关闭它或改写它的任务ID。新增Chrome先RED后GREEN。
- 原SubmitRuntime的未确认身份按项目保存，并在发送POST前写入同标签页sessionStorage的最小请求收据（仅projectId/algorithmId/taskId，无配置、图片或凭据）。刷新后沿原GET核验，不自动重发，不增加任务状态数据库或轮询。明确4xx拒绝/验证成功才清除此收据；浏览器存储被禁用时记录错误，当前页面仍保持原ID防重，但跨刷新持久化NOT VERIFIED/不可保证。
- 同一个反馈区增加“查询任务状态”和“查看训练任务列表”。多个项目的待确认身份相互隔离，读取仍严格验证任务种类、项目、算法与原ID。新Chrome刷新恢复先RED后GREEN。
- 最终生命周期Chrome单文件29/29通过；此前首开7与按需准入16已通过，共52个不同场景，不重复累计。Node不同用例90，最后Submit/validation受影响67/67通过；Python11通过；未运行无关全仓回归。
- `c7f71bc94c81826cc95470efe640213bf91c73f5` 检查时26 Actions中25成功/1运行中、68 Checks中67成功/1运行中；这是前一代码状态，不能用于最终增量验收。后续最终SHA重新核CI。


### 只读审查发现与补齐（2026-10-25）

- 审查确认：只收到HTTP headers后，5xx或409锁竞争的正文中断/超时会丢失httpStatus/业务码，原异常路径误认为明确拒绝、清除待确认收据。新增真实Chrome先RED（500与409各一例），现在先保留headers状态，并区分正文是否完整读取；未读完不得判断未创建，沿原ID查询。完整400/409/422明确拒绝仍恢复原配置及按钮；未知结果不允许新ID绕过。
- 审查确认：外部算法核验的UI外层截止没有取消原Owner缓存中的挂起Promise，重试反复复用同一请求，迟到响应还能发布旧算法。新增真实Chrome先RED：两次超时仅1次请求且旧响应污染；修复后透传原AbortSignal，在原ExternalAlgorithmPlatformRuntime中使用现有withRequestDeadline，忽略已取消缓存、仅清除自己持有的Promise；迟到结果不能发布。没有新建缓存Owner、API客户端或轮询。
- 新增两例先RED后GREEN，随后409正文中断再RED→GREEN。最后三浏览器文件54/54通过，409补齐后的相关7/7通过；当前共55个不同Chrome场景已通过，不重复累计重跑结果。最后受影响Node四文件95/95（submit、validation、hydration、external platform）通过；此前version/device13例复用，不为等待CI重复跑；Python11例沿用无后端增量。0失败/跳过，没有真实GPU或收费调用。
- 925f3bf0的CI检查时47 Actions中46成功/1运行中、128 Checks中127成功/1运行中，未用于本次新代码验收。审查增量提交后以新完整SHA重新读取CI。已有两次过时字面守卫失败已如实记录并适配原调用合同，无删除/降级安全测试。



### 最终解析边界补齐：409损坏JSON

最终复核在同一错误解码分支确认：409正文完整返回但JSON损坏时，仍无法确定是否锁竞争，不能当作明确拒绝。真实Chrome新增409损坏JSON先RED；改为仅成功解码非空非数组JSON对象后认可拒绝正文，其余保留UNKNOWN/原ID查询。相应7项Chrome（完整400/409/422/500、409/500正文中断、409损坏JSON）7/7，Node submit/validation67/67，无失败或跳过；Chrome共56个不同场景。只读复核此最小增量无阻塞，不扩改业务规则。

7fdef286的33/33 Actions、89/89 Checks及完整Chrome290/290仍为前一代码证据；2650413e为前一文档提交。本增量正常推送后必须按新完整SHA核验CI，不能引用前一SHA替代。最终增量已验收：**[382c1b95d6067c9c18a6094f894058a84fb32c21](https://github.com/jorsamj/aixunlianpingtai/commit/382c1b95d6067c9c18a6094f894058a84fb32c21)** 已普通推送，准确 **26/26 Actions、68/68 Checks全部成功**，0失败/取消/跳过：[最终代码Checks](https://github.com/jorsamj/aixunlianpingtai/commit/382c1b95d6067c9c18a6094f894058a84fb32c21/checks)。本节回执优先于下面7fdef286的历史代码回执。文档自身后续提交不改业务代码，最终HEAD仍须单独核验CI并在交付报告列出。

### 最终代码验收、文件清单与接续

VERSION **42.24.387**。最终代码 **[7fdef28690c81104a689a06c36800874d021feac](https://github.com/jorsamj/aixunlianpingtai/commit/7fdef28690c81104a689a06c36800874d021feac)** 已正常推送 `feature/external-algorithm-publishing`，准确 **33/33 Actions、89/89 Checks全部成功**，0失败/取消/跳过：[代码Checks](https://github.com/jorsamj/aixunlianpingtai/commit/7fdef28690c81104a689a06c36800874d021feac/checks)。只读复核最终增量无阻塞；409/500正文中断独立核验实际POST→GET→created。验收回执会产生文档新HEAD，交付前另读取该HEAD自身CI；完整SHA由提交历史及交付报告定位，避免自引用循环。文档提交不重复本地测试。

本地必要验收：Python11/11；最后受影响Node四文件95/95，之后只重跑正文中断/损坏JSON影响的submit/validation67/67（不重复累计）；其他已有version/device13例复用。真实Chrome56个不同场景通过：三原文件54/54后，新增409正文中断、409损坏JSON及相关7/7通过。所有最终验收0失败/跳过；历史RED、源码字面守卫失败和修复记录保留。CI原有完整Chrome及Node也通过，没有手工重复全仓或新增工作流/跳过安全断言。

实际修改文件（基线243858b9至最终代码）：

- 业务：`static/modules/training-submit.js`、`static/modules/training-create-hydration.js`、`static/modules/external-algorithm-platform.js`、`static/app.js`、`app.py`、`static/styles.css`。
- 接入/版本：`static/main.mjs`、`static/index.html`、`VERSION.txt`。
- Python：`tests/api/test_training_request.py`。
- Chrome：`tests/browser/training-create-first-open.spec.mjs`、`tests/browser/training-submit-lifecycle.spec.mjs`；原按需准入文件未修改但定向回归。
- Node：`tests/frontend/external-algorithm-platform.test.mjs`、`tests/frontend/training-create-hydration.test.mjs`、`tests/frontend/training-modal-device-probe.test.mjs`、`tests/frontend/training-submit-validation.test.mjs`、`tests/frontend/training-submit.test.mjs`、`tests/frontend/version-marker-owner.test.mjs`。
- 原工作流只适配字面守卫：`.github/workflows/training-create-first-open.yml`，仍断言原API/Owner及准备身份保护，不改触发/跳过/安全条件。
- 持久文档：本文件、`docs/CODEX_CURRENT_STATE.md`、`AGENTS.md`。

前后端一致：v12回执与v62查询校验同一正式TRAINING task_id、项目、算法及原持久状态；恢复到FAILED/BLOCKED等终态只证明“任务已创建”，不显示“训练成功”。后端原锁/指纹/父子准备恢复仍为唯一幂等Owner，业务错误码透传；没有新增任务库或改变Worker/GPU/GT/训练参数。服务端确认持久化就结束创建Loading，刷新列表和训练执行均独立。

接续：本专项可进入**经单独授权的生产部署验收**，当前没有部署。优先在授权环境复验真实网络中断和浏览器配置，不执行GPU训练来验证Loading。真实GPU/NAS/OSS/生产网络仍NOT VERIFIED。禁用sessionStorage时当前页面防重仍有效，跨刷新恢复无法保证；不能用新ID盲目重试。ZIP/图片上传try前同步异常风险仅静态发现OPEN，未复现、未扩改，见上表；不要将本专项当作全平台故障全部关闭。

原标注工作区HEAD仍8ba6ce1a，4个本地提交及全部未提交标注增量与两份模板测试保留；5944祖先可达。本轮训练隔离工作树干净后保留接续。后续回到标注任务时，应安全合并最新远端训练修复并保留该WIP，不得reset/覆盖或把未交付标注增量误报为本轮已推送。

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
