# 模型版本转换模块专项（2026-10-28）

本文件为附件b7318d04本轮唯一需求/实现/验收依据；不替代既有RGB/BGR颜色适配与SDK真实性专项。基线2c5311c6 / VERSION42.24.397已fetch一致，原负样本任务最终CI收尾独立提交92203c8c，原未提交训练模板/5944与其他工作树保留。不开生产、不删模型/缓存，不扩到训练配置或素材管理。

## 需求与审计

目标：正式转换弹窗立即展示；目录/资源/历史独立截止、错误及重试；读取已有检测与主动SDK检测解耦；最终创建仍权威核验。原卡片/任务/幂等/队列/Worker/ModelArtifact/下载/血缘继续使用；增加明确的详情与状态/设备/芯片/精度/CSC/日期筛选和有界分页。

已有：RGB/BGR ONNX Gather入口适配及数值校验、原SDK检测、厂商/芯片动态目录、目标专属参数、原任务快照/manifest、单资源手动检测、原PollRegistry只轮询活动任务。不得把RGB/BGR或训练augmentation当YUV CSC。

真实缺口：openNewConvertCore416在资源+历史+目录Promise.all后才打开；历史窗口同样等待网络。打开资源force读取、resolve反复主动检测，远程单次timeout12秒；catalog/resolve缺局部截止与精确Modal失效。高级值跨目标共用；资源检测失败可能静默选另一个资源。版本历史先扫描全项目job.json再截100，逐条durable查询，老版本可能被截断；缓存无TTL。四CSC/device_default/none在转换端均未实现。

## 设计与边界

沿原Owner渐进加载，分源状态/重试保留编辑；精确项目/源版本/表单/config epoch、局部Abort/截止。复用ResourceCache按选中资源配置指纹缓存/合并检测，转换表单使用只读资源查询，不开启全节点SDK检测；显式检测与最终创建校验分开。历史只维护可重建派生投影/按需分页，不建立第二套转换任务真相。

CSC仅处理明确原始8位Y'CbCr输入NV12/I420/平面YUV444，四预设对应601 Kr=.299/Kb=.114或709 Kr=.2126/Kb=.0722，Limited为Y16/219、C128/224，Full为Y0/255、C128/255；输出实际RGB/BGR uint8，限定nearest chroma与量化规则。不是RGB编码/同逆变换、HSV或改文件metadata。none不适配；device_default不猜实际矩阵；历史缺失显示历史未记录。

现平台不能控制外部业务BMCV/VPP调用，四预设先明确为contract_only：生成参数合同/可执行参考解码器/说明，applied=false、device_observed=unknown、board NOT VERIFIED。需显式接受推理端配合；要求模型产物独立完成而平台不支持时拒绝。禁止将编译成功视作板端验证。保留原通道适配，分别记录requested CSC、参考数值验证、真实执行位置和板端证据。未知Adapter不给“四模式已支持”承诺。

官方依据：[BM1688 BMCV接口](https://doc.sophgo.com/bm1688_sdk-docs/v1.8/docs_latest_release/docs/bmcv/bmcv_demo/bmcv_api/bmcv_image_vpp_basic.html)、[ITU-R BT.709](https://www.itu.int/dms_pubrec/itu-r/rec/bt/r-rec-bt.709-6-201506-i!!pdf-e.pdf)。文档中的默认值不推广为所有设备/摄像头实测。

## 阶段与实际进度

|阶段|状态|实际实现|验收证据|
|---|---|---|---|
|A 审计/最小方案|已验收|原Owner调用链、颜色适配、SDK/历史瓶颈及边界已确认|代码审计及下述受控对比|
|B 渐进加载/检测|已完成待验收|正式表单立即展示，源/目录/资源独立状态和重试；单资源检测、300秒TTL及同配置并发合并；预览不探测|资源合同、API及Chrome；最终SHA CI待核验|
|C CSC统一合同/产物|已完成待验收|四预设、none/default、显式接受外部预处理；原本地/远程/Agent任务传递、Worker、manifest、参考包和下载接通|真实微型ONNX Worker与参考CLI、远程真实性/提交失败回滚；板端未验证|
|D 记录卡片/筛选/历史性能|已完成待验收|详情折叠、6种服务端筛选、20条分页、全版本总数、增量文件投影及仅活动任务overlay|1000条隔离记录、历史API及Chrome分页/展开保持|
|E 必要自测/截图/CI|进行中|本地必要检查已通过，VERSION42.24.398；提交/准确SHA CI待完成|不借用03728393或其他提交绿色|

## 实现与选择

- 前端仍为原转换表单和Modal Owner、Page/表单epoch、原API与PollRegistry。加载失败保持表单，独立重试；资源失败不偷偷切换另一资源。厂商/芯片响应、resolve均有局部截止/取消/迟到隔离。高级参数按目标保存，已编辑输入尺寸、精度、RGB/BGR不被异步默认值覆盖。
- GET resources使用`detect_missing=false`，catalog只读观察；原默认接口兼容。资源状态包含检测时间、TTL及可用/检测中/未检测/过期/不可用/失败。手动检测只运行选中资源；配置指纹变化使结果失效，保存前校验updated_at防止晚响应覆盖新配置。原创建接口和Worker的SDK/模型/硬件权威检查保留，缓存不代替最终校验。resolve返回分段timings_ms，不记录凭据。
- 版本历史复用原job.json和durable Task，不建新表。最多16项目派生投影，目录元数据TTL不超过1秒，文件签名变化才重读JSON；只对活动任务查真实状态。首次冷读仍需读取现有记录；不可读记录明确complete=false，不伪装全量成功。投影只保留源身份，不保留冻结GT/Snapshot大正文。
- 原通用v39任务列表合同（最后100条）保留，本轮优化的是v42版本历史视图；不能声称通用列表已全面优化。旧source_meta/source_id记录与日期结束日兼容。
- 已有ONNX复用与原验证保留；新增的只是预览shape的有界文件签名缓存，最终创建仍重新读取。未新增跨任务PT导出缓存：现有export工具版本与完整配置身份不足以证明安全复用，避免错用中间成果。未关闭原源SHA、ONNX/ORT、SDK和产物验证。
- CSC派生合同由后端从请求重算，不能伪造csc_contract。远程Sophon必须与冻结请求、manifest和可信参考包逐字节哈希相符。Agent结果由服务端原提交Owner重建参考包；SQLite/job持久提交失败会回滚本次新增或覆盖的两个参考文件。原模型/审计不动。
- 辅助产物为`csc_deployment_contract.json`和`csc_deployment_reference.zip`；ZIP含参考Python、README及合同，文件哈希可追溯。通过原登记ZIP下载，不扩宽.py/.md业务文件权限，不执行远端提供的未知Python。

### CSC能力与数学约定

Sophon/RKNN/Ascend/TensorRT/ONNX当前均仅具备**生成外部部署约定和可执行参考解码器**的能力，四模式须明确选择原始YUV布局并勾选推理端接入确认。Paddle或未知自定义适配器不开放四模式；要求嵌入模型独立完成时明确拒绝。不能将此能力误称为设备SDK已经应用。

输入为紧密排列8位Y′CbCr，NV12=Y+UV、I420=Y/U/V、YUV444=平面Y/U/V；420尺寸须为偶数，色度nearest repeat，不假设SDK色度位置/stride；无gamma/传递函数转换。输出HWC uint8 RGB或原模型合同要求的BGR，float64计算，乘255、裁剪、floor(x+0.5)。后续resize/mean/scale/布局仍由原预处理合同处理，不能对已经解码RGB再重复CSC。

|预设|系数|范围|同一Y=100,Cb=90,Cr=240的实际RGB|
|---|---|---|---|
|BT.601 Limited|Kr=.299,Kb=.114|Y=(Y-16)/219,C=(C-128)/224|[255,22,21]|
|BT.601 Full|Kr=.299,Kb=.114|Y=Y/255,C=(C-128)/255|[255,33,33]|
|BT.709 Limited|Kr=.2126,Kb=.0722|Y=(Y-16)/219,C=(C-128)/224|[255,46,18]|
|BT.709 Full|Kr=.2126,Kb=.0722|Y=Y/255,C=(C-128)/255|[255,55,29]|

矩阵R=Y+2(1-Kr)Cr、B=Y+2(1-Kb)Cb，G按Kg=1-Kr-Kb推导。相同原始YUV分别解码，未通过RGB编码/匹配逆变换抵消；不是HSV。三种布局、黑白端点、RGB/BGR、输入不变、重复结果一致均有必要断言。

none明确不额外适配；device_default不推测设备矩阵；历史缺失显示“历史未记录”。requested preset、参考数学实现、device_observed分开记录；所有新合同仍`applied=false`、`device_observed=unknown`、板端`NOT VERIFIED`。原用户A800/BM1688数值仅作问题背景，本轮没有其原始帧/张量，不声称重现该设备结果。

## 性能与视觉证据

[原始受控记录](artifacts/conversion-modal-controlled-20261028/timing.json)：同一隔离Chrome与源版本，资源GET固定等待1200ms，旧2c5311c6 app在内存route提供；旧弹窗1380ms、新36ms，资源/历史/目录各1请求。原[修改前](artifacts/conversion-modal-controlled-20261028/baseline.png)及[修改后](artifacts/conversion-modal-controlled-20261028/progressive.png)保留。后续CI测试读取已记录旧基线（不依赖浅克隆旧commit，不重新声称测量旧代码），当前实时检查见[current-timing-check.json](artifacts/conversion-modal-controlled-20261028/current-timing-check.json)，79ms且资源响应前表单已经出现。

1000条隔离Windows job记录：首次1000 JSON、10活动overlay、3146.527ms；紧接热读0 JSON/0元数据扫描、10 overlay、1.448ms；一条变化后1 JSON/999复用、11 overlay、28.994ms。含临时磁盘/测试观察开销；这些不是生产延迟或提升百分比。真实A800/OSS/NAS、生产源模型大小和编译耗时仍NOT VERIFIED。

1366×768补验仅运行CSC用例1次通过：真实wheel滚到底部，提交可见可点击、无横向溢出，见[小屏截图](artifacts/conversion-modal-controlled-20261028/current-csc-create-1366.png)。

当前[CSC配置](artifacts/conversion-modal-controlled-20261028/current-csc-create-1920.png)与[历史详情](artifacts/conversion-modal-controlled-20261028/current-history-details-1920.png)为真实Chrome隔离接口截图（1920×1440），不冒充生产真实业务记录。

## 必要测试、问题与修复

只执行受影响检查，不在本地全仓回归。相同状态通过项不因等待重复执行，以下分组有重叠，不相加作虚假总数：

|检查|实际结果|
|---|---|
|CSC/资源/1000记录历史三个新模块最终检查|20 passed，0 failed，0 skipped|
|原conversion、remote conversion、color adapter、portable API相关回归|81 passed（后续ZIP修改另行定向验证）|
|动态目录/resolve API|16 passed；新增真实旧job分页API另1 passed|
|实际微型ONNX Worker、参考CLI、远程可信ZIP、Agent成功/回滚|最终6 passed，0 failed；无GPU|
|最终本地创建CSC兼容、板端truth投影、资源TTL|4 passed；BGR继承单项1 passed|
|最终受影响Node与版本入口|41 passed，0 failed，0 skipped|
|真实Chrome|渐进失败重试、原Sophon矩形FP32/BGR、当前受控时间、CSC提交、历史筛选分页/展开保持分别通过；末三项3/3通过|
|语法/工作流|py_compile通过，workflow YAML解析3 jobs，git diff --check通过|

发现问题均记录真实过程：API首次7项失败为resolve_chip_capability漏导入，已修复后16通过；审查发现旧Sophon preprocessing BGR未传入CSC输出顺序，已修复并新增最小边界验证；异步resolve曾重置用户BGR，原编辑标识已补齐并用原Chrome回归；直接发布.py/.md不符合原文件安全后缀，改为已有ZIP登记，不降低权限；Agent提交失败辅助文件回滚已验证。未通过删除测试、跳过断言或放宽真实硬件验证获得绿色。

## 文件与接续

实际业务文件：static/app.js、static/styles.css、static/index.html、app.py、deployment_worker.py、platform_core/conversion.py、conversion_csc.py、conversion_resource_detection.py、conversion_history.py、remote_conversion_runtime.py、node_agent_conversion_runtime.py、remote_execution_transport.py；相应原测试与现有remote-conversion工作流接线。VERSION.txt仅本轮递增398。

首次提交ea213f1fdc384cffce63c60c81ed4f89b8ba4dc4已正常推送，但CI检出三项需修正：精简传输环境顶层导入NumPy、原启动Owner禁止新MutationObserver、原RKNN板端验证按钮被详情折叠。已将NumPy延迟至像素解码（不扩CI依赖），清理沿原Modal beforeClose且精确form/ticket处理，板端验证/停止等操作保持卡片直接可用；不削弱原测试。修正后Python24通过，standalone无site-packages合同/参考ZIP生成通过，Node50通过，原RKNN板端完整流程及慢资源Chrome2/2通过。最初-S直接导入包会因原filelock依赖失败，改runpy单独验证CSC依赖边界，不宣称整个平台无第三方依赖。VERSION398不二次递增。最终修正SHA和CI待核验。03728393（上一负样本文档）已21/21 Actions、57/57 Checks成功，与本轮无关，不能用作本轮验收。

接续仅处理准确SHA CI真实失败或本专项剩余验证；不重建训练、GT、任务、缓存或Modal。生产SDK/远程Agent/板端/BMCV接入、真实母模型大文件、生产接口耗时和用户给定A800/BM1688帧尚未验证，需授权环境独立实测。关闭或不选CSC不依赖参考模块执行；原模型与下载保留。未生产部署、安装依赖、转换真实模型或删除用户文件。

### 后续CI兼容性修正

b763105cd41387a86981d583b4697fea4f96e509保留首轮修复。后续CI发现旧history源码守卫与Chrome route仅接受无query地址，分页请求落入真实404；现仅将原夹具更新为query-keyed缓存、force/signal及分页地址，保留并增强节点稳定、并发去重、只刷新活动任务、终态自动显示产物/下载和UNKNOWN防重断言，未删或跳过测试。定向Node21/21、原进度/缓存/产物Chrome3/3、原pending/rejected恢复Chrome2/2通过。额外只读检查发现ZIP create_system会随Windows/Linux不同，原用例追加断言先RED再固定为3，最小ZIP与远程篡改验证2/2 GREEN，LF/时间/权限同样固定。此变更不影响原始模型及旧无CSC任务；新CSC远程执行要求兼容的同版参考合同，不能混用未升级Worker并宣称成功。
