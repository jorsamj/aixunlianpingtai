## 2026-10-20｜动态字典与SDK参数整合接续

本轮统一验收见 [动态厂商/真实转换能力专项](DYNAMIC_CONVERSION_CATALOG_ACCEPTANCE_2026_10_20.md)。正式VERSION42.24.359，一次递增；Sophon复用原探测/Worker/远程Durable任务，以TPU-MLIR1.30.2官方芯片浮点矩阵与实际探测交集解析，BM1684 F32，原BM1684X/BM1688 F16；版本变化不复用该版本约束。真实芯片命令、矩形Batch1、SHA/唯一芯片检查与原硬件验证边界保留。最终限定Python262、Node70、Chrome8通过，最终SHA CI见新专项指定独立附件；本轮无真实SDK/板卡新验收、无生产部署。

# Sophon BMODEL转换验收｜2026-10-20

## 2026-10-20｜Sophon资源与页面一致性（A-D测试通过 / E待推送及最终CI / 生产未部署）

- 完整fetch/prune与pull --ff-only，起始a36b9cdec1cd4aa07c9cde2d9c84bc98bb66b479，远端一致、初始干净；该历史SHA22/22 Actions、59/59 Checks已核验附件并归档，不当作本轮CI。VERSION42.24.358。
- 用户现场新证据：A800 TPU-MLIR1.30.2、两chip YOLO11 FP16真实编译、8030服务鉴权health、远程BM1684X转换done/converted_unverified、本机probe available。此为用户提供的现场事实；本轮不重跑生产转换，不把它解释为实机HARDWARE_VERIFIED。
- 现有链路复核：扫描和plugins调用远程探测时未解析secret_ref；扫描新状态未持久化，转换弹窗仍只读资源列表；本机工具组件与远程能力分离但缺少明确来源说明；版本正则在v1.30.2中错误从30.2匹配。local auto-detect已有保留独立Python配置逻辑，不重复开发。
- 计划：先RED；复用资源detect原入口统一鉴权、保存与公共投影，修正版本提取；本机组件明确本机范围，Sophon总能力按有效资源汇总；原UI增加来源/版本事实，复用现有弹窗与轮询。限定相关Python/Node/Chrome，VERSION不变，缓存仅按必要调整。
- 不修改生产密钥、不连接生产执行写操作、不重装环境、不调用真实新畅联接口、不增加调度器。
- B RED：后端8 failed/1 passed/41 deselected（扫描/插件未鉴权、未持久化、错误服务版本、无资源计数、v前缀被截断）；独立Python保留原本通过。Node新用例1 failed/10 passed，转换详情漏版本；Chrome新用例1 failed，能力卡不显示本机/远程事实说明。日志均位于C:/Users/jorsam/.codex/tmp/sophon-state-{red,node-red,chrome-red}.log。不是生产调用，无测试删除/跳过/降低断言。
- C：扫描/插件统一调用现有v39_detect_deploy_resource，解析原secret_ref、保存结果、返回公共投影，保持密钥隔离；GET资源列表与弹窗随后读取同一保存事实。Sophon health必须同时报告target/chip/FP16；鉴权或SDK失败清空能力，恢复后重新登记能力。远程卡版本取工具probe.version而非平台服务版本。共享版本正则完整保留v1.30.2-20260831。
- C：本机三工具卡明确“本机”并显示本机未配置/失败原因，不能填远程路径；calibration只反映实际calibration_available且说明FP16不依赖。总Sophon能力统计有效资源数/配置资源数，展示本机和远程来源、真实芯片/FP16/版本；本机SDK失败不覆盖健康远程资源。未新增探测器/调度器/轮询或弹窗。
- D GREEN：限定Python7文件136 passed/0 failed/0 skipped，12.57s（5项原依赖弃用警告）；Node2文件20 passed/0 failed/0 skipped；Chrome原component-scan-performance与model-and-conversion两规格10 passed/0 failed/0 skipped，19.6s。最后增加本机SDK失败但远程健康边界，再跑同一限定Python集合136通过。py_compile、node --check、git diff --check、原Remote Conversion永久守卫通过。日志sophon-state-python-final2.log、sophon-state-node-green.log、sophon-state-chrome-green.log。
- E：VERSION42.24.358、main404/styles402不变；仅实际变动app.js缓存404→405，并同步精确版本断言。普通FF推送后核验完整SHA全部实际Actions/Checks，独立附件C:/Users/jorsam/.codex/visualizations/2026/10/20/01a156ca-1ca0-7b70-8497-bd255da4345e/sophon-resource-state-ci-final-20261020.json，下一受验证提交归档，不为写入自引用SHA制造新HEAD。
- F：本轮未修改现场服务、密钥、Python或依赖，未操作生产GPU/OSS/S3/新畅联写接口。用户确认的真实FP16编译/远程done属于现场提供证据；本轮隔离测试不冒充新增实编译或板卡实测。上线后的网页展示/实际资源登记效果需用户部署后复验，硬件HARDWARE_VERIFIED仍未提供。


## 2026-10-20｜model_tool官方CLI兼容修复（A-D测试通过 / E待推送CI / 现场依赖待只读核验）

- 已完整fetch/prune及pull --ff-only，起始HEAD c44752934524dcfc86f89d8cf24fc34f32cee011，远端一致、工作树干净，VERSION42.24.358。上轮最终48/48 Actions、131/131 Checks通过已核验独立附件并归档于本节；仅为历史证据。
- 现场用户报告：Ubuntu22.04 x86_64，Python3.10.22，TPU-MLIR1.30.2，setuptools80.9.0，psutil6.1.1；解释器/opt/sophon-mlir/env/bin/python，工具/opt/sophon-mlir/env/bin。transform/deploy --help退出0，deploy --version正常；model_tool --help打印Usage退出1。
- 官方v1.30.2源码tools/model_tool/model_tool.cpp main明确支持--version并打印MLIR_VERSION，未知选项走usage/exit(-1)。现有共享probe统一对三个工具执行--help是误判根因，旧协议fixture错误模拟help退出0。
- 最小计划：先真实子进程CLI协议RED，再仅将model_tool探测改为--version，要求退出0且有合理版本输出；transform/deploy/calibration及Python/chip/FP16合同不放松，编译后--info真实BMODEL结构与芯片检查保留。
- 范围仅共享probe、现有Sophon测试、进度文档及必要CI；不安装依赖，不改训练环境，不部署、不调用真实新畅联接口、不执行生产转换。
- 服务器依赖：现有信息证明上述已安装版本与CLI行为，尚无pip check/完整导入错误或明确Sophon服务器访问资料；不能据此编造“实际缺失包”。已请求只读访问或诊断输出，待核验项明确NOT VERIFIED。
- B RED：仅原Sophon测试文件probe/model_tool用例，11 failed / 6 passed / 18 deselected。旧fixture改为官方行为help退出1、version退出0后复现误判；同时捕获原探测对“help退出0但输出垃圾”的错误放行。日志C:/Users/jorsam/.codex/tmp/sophon-cli-red.log。非零现场退出1和源码exit(-1)都不能当作工具损坏。
- C 最小修复：仅sophon_runtime.py共享probe改model_tool --version，退出0且输出匹配合理三段版本（可含version/TPU-MLIR前缀及构建后缀），保留错误退出码与输出诊断；不改Worker --info、Task、API、UI、芯片白名单或FP16约束。测试仍是真实子进程协议夹具，不冒充真实SDK编译。
- D GREEN：限定5文件test_sophon_conversion/test_conversion/test_sophon_remote_durable/test_remote_conversion_transport/test_sophon_remote_admission，98 passed / 0 failed / 0 skipped，10.57s（5项已有依赖弃用警告）。首轮96通过后只增补2项产物--info失败/错误芯片保护；最终98覆盖。日志C:/Users/jorsam/.codex/tmp/sophon-cli-final.log。py_compile、git diff --check通过。本轮无前端修改，不本地扩跑Node/Chrome/硬件。
- E：待普通FF推送长期分支；最终SHA CI不能借用上轮48/131。本轮独立验收附件为C:/Users/jorsam/.codex/visualizations/2026/10/20/01a156ca-1ca0-7b70-8497-bd255da4345e/sophon-cli-ci-final-20261020.json，下一次受验证提交归档。
- F：未连接Sophon现场服务器、未安装/升级任何依赖，未部署/调用真实新畅联/转换模型。版本信息为用户现场报告；实际完整依赖缺口与修复后的服务器health均NOT VERIFIED。可由明确的只读现场会话运行 `/opt/sophon-mlir/env/bin/python -m pip check`，并提供失败traceback；ONNX/ONNX Runtime、PT导出解释器的Ultralytics等应按各自执行环境核验，不因包名猜测安装到训练环境。
- 官方证据：[v1.30.2 model_tool.cpp](https://github.com/sophgo/tpu-mlir/blob/v1.30.2/tools/model_tool/model_tool.cpp)，main的--version与未知选项分支。未提供Sophon SSH目标，不能将已有a800-server别名当作本次Sophon服务器。


## 2026-10-20｜Sophon BMODEL正式转换（阶段A-D测试通过 / 最终CI待提交 / 生产与硬件未验证）

- 分支feature/external-algorithm-publishing，完整fetch/pull后起始HEAD62647aeea258a26ba423f0a9db23d8f6f8ba3b1a、远端一致、初始工作树干净；VERSION42.24.358。
- 上轮tags最终CI23/23 Actions、59/59 Checks已归档到原tags专项；不能当作本轮绿色。
- 已有Sophon选项、基础PT→ONNX→MLIR→BMODEL脚本、远程服务、Durable转换Handler、ModelArtifact与发布Owner；真实缺口待RED：静默默认芯片、无Sophon参数门禁、工具仅文件检测、远程转换绕过Durable线程、宽高导出不一致、发布芯片必要性及工具/硬件状态边界。
- 方案沿用用户已明确架构：首期BM1684X/BM1688、FP16、Batch1、静态输入；远程部署服务编译，纳入现有Durable MODEL_CONVERSION Owner；不建立第二执行器或扩展Agent并行链路。INT8沿用冻结校准保护，未具备可靠版本校准时继续阻止；CV186X/多核/实机质量不冒充已验证。
- 本轮唯一进度与设计/实施清单：docs/SOPHON_BMODEL_CONVERSION_ACCEPTANCE_2026_10_20.md；禁止部署生产、生产GPU/OSS/S3、真实新畅联写入及生产转换。


## A 现状核验（完成）

已有Sophon插件/选项、prepare_onnx/build_sophon基础脚本、远程部署服务、ModelArtifact按chip/SHA分离、转换完成发布通知与Weight add/edit。已核验真实入口：v39_create_deploy_job→local进入MODEL_CONVERSION/ConversionHandler→deployment_worker；remote原先直接启动API线程_sync_remote_deploy_job，不属于Durable；Agent只具备现有ONNX/RKNN可移植合同。

方案按用户批准设计：Sophon remote使用现有ConversionHandler，新增纯传输函数而非Task/数据库/Owner；其他非Sophon远程旧路径保留。Web仅创建Durable任务，编译仍由选定远程服务或显式隔离本机TPU-MLIR执行，Agent不新增并行Sophon执行器。

官方只读核验：TPU-MLIR model_deploy.py使用--chip（--processor兼容别名），F16和num_core；YOLOv11_det README指向YOLOv8_plus_det共用推理/编译例程。来源：[TPU-MLIR](https://github.com/sophgo/tpu-mlir)、[YOLO11编译样例](https://github.com/sophgo/sophon-demo/blob/release/sample/YOLOv8_plus_det/scripts/gen_fp16bmodel_mlir.sh)。不复制其隐式默认chip；产品强制用户明确选择。

## 实施设计与计划

1. 复用conversion.validate_target增加显式芯片/精度/静态batch合同；原PT导出修正真实宽高，ONNX Checker/Runtime及实际shape必须匹配。
2. 单一Sophon工具探测模块同时供Worker/资源/远程health使用；在配置Python中执行有界工具自检、报告缺失项/版本/工具路径/芯片能力。无安装/下载操作。
3. 优先复用既有remote_deploy_server；将选定Sophon远程路径纳入现有ConversionHandler与MODEL_CONVERSION，不用API线程执行长任务。安全Key与请求幂等、取消/Lease/恢复保留。
4. 原版本转换UI只增量完善芯片、尺寸、FP16及预处理/工具状态；按资源能力白名单，不新增弹窗或轮询Owner。
5. 原ModelArtifact/Publish追加BMODEL，目标芯片必须匹配，扩展字段仍可选；增加两个芯片同Version共存的真实JSON隔离验收。
6. 各项先RED后最小修复；限定conversion/API/Worker/publish相关Python、相关Node和Chrome；hardware无真实环境SKIP/NOT VERIFIED。保持既有RKNN等功能。

## B RED（真实复现并关闭）

- 芯片/精度/batch/static门禁、矩形默认值、导出宽高/路径插值、ONNX shape错配及实际shape记录：首轮12 failed。根因分别是Sophon未在validate_target单独验证、导出只读input_size、ONNX验证只按自身shape运行不对照编译形状。日志sophon-red-1020.log。
- 工具缺失未分类、空BMODEL仍成功：3 failed（sophon-red2-1020.log）。修复后真实subprocess协议夹具验证空产物、失败退出与Manifest，但不能冒充真实编译。
- 发布缺失/瑞芯微/未开放chip可被接受，以及BM1684X/BM1688映射未贯穿：4 failed（sophon-publish-red-1020.log）。同SHA两芯片各自Weight和原ID edit已GREEN。
- UI无实际上报芯片仍开放/展示CV186X及非FP16：Node 2 failed（sophon-node-red-1020.log）。
- remote/API子任务记录11个独立RED；只读规格复核发现首次恢复误跳上传、临POST失Lease仍可发写，两项P1补充23项RED（含18项Manifest错配拒绝、历史knownID只读恢复）。均已修复并复核，不把重复运行累计为额外业务缺口。
- 中途夹具问题如实区分：Windows默认GBK读UTF8的3个失败、Node插入字段变量名initialSize错误、长本地provider路径导致PARTIAL（改短隔离根，不改OSS键或断言）、旧Chrome未打开高级参考/旧审核标题/旧引用自动改标签语义。仅升级夹具到当前已确认交互，保留人工审核与标签不自动变化断言，未改AI业务。
- 一次工具工作目录状态丢失导致命令落到旧D工作区，文件收集失败且0用例执行，不计验收；后续固定绝对工作树。

## C 实现（完成，待最终SHA CI）

- conversion.py：仅BM1684X/BM1688、FP16、batch1/num_core1/static，精确矩形尺寸；preprocessing为显式caller合同（RGB/BGR、mean/scale、Letterbox/Pad114、外部NMS），不在ONNX/BMODEL隐式重复融合。
- sophon_runtime.py：唯一只读工具探测，必须显式python_path；配置解释器运行transform/deploy/calibration自检，model_tool实际可运行，deploy版本与chip choices交集才能报告能力。未下载/安装TPU依赖，不混装A800训练环境。
- deployment_worker.py：原Ultralytics导出用独立argv读取已存在源文件，矩形尺寸一致；真实ONNX Checker/Runtime与编译shape对照；安全argv调用MLIR/F16编译，非空文件+SHA+model_tool唯一chip结构证据后才交付。版本来源/工具/shape/预处理进入Manifest；无板卡保留converted_unverified。
- app.py + ConversionHandler + remote_conversion_runtime.py：Sophon实时检测对应资源/芯片，Durable唯一Owner管理排队、Lease、取消、超时、恢复。远程确定ID在POST前持久化，已提交未知结果只读原ID，未提交恢复可首次POST；临POST/临替换均Fence，下载ZIP有界解压并完整核验source/shape/参数/结构/hash。
- remote_deploy_server.py：空Key拒绝、config鉴权、同client_job_id与请求身份幂等、持久化进程身份用于取消；本地配置初始化Key，不通过未认证网络首次设置。
- 发布：原芯片字典加BM1684X/BM1688，Sophon芯片为必要条件、按真实子分类绑定；原Repository/通知/ModelArtifact/Weight receipt复用，元数据未知仍省略不阻断。
- 原版本转换UI：资源上报芯片交集、宽/高、固定batch1/FP16、折叠预处理配置、工具缺失与真实Task/成果/待硬件状态；无新弹窗或轮询。app/main缓存404，styles402不变，发布模块64008；VERSION42.24.358不变。
- 原remote-conversion-runtime工作流增补新模块触发与现有control-plane测试，并将Sophon Chrome用例接入现有筛选，不新建工作流。


## D GREEN（测试通过）

- 限定Python11文件：313 passed / 0 failed / 0 skipped，64.42s；5项已有FastAPI/Starlette弃用警告。命令范围：test_conversion、test_sophon_conversion、test_conversion_tasks、test_sophon_remote_durable、test_remote_conversion_transport、test_sophon_remote_admission、test_conversion_jobs、test_conversion_unified_task_truth、test_conversion_portable_contract、test_external_algorithm_publish、test_external_algorithm_platform。日志C:/Users/jorsam/.codex/tmp/sophon-python-final-1020.log。
- 最后增强BMODEL原ID edit断言后仅重跑Sophon发布4项，4 passed / 0 failed / 0 skipped（115 deselected）；sophon-pub-final-1020.log。
- Node4文件：40 passed / 0 failed / 0 skipped（rknn-conversion-resource-live、external-algorithm-publish、conversion-unified-task-truth、version-marker-owner）；sophon-node-final2-1020.log。缓存断言同步实际新版本，不降低强度。
- Chrome两份现有规格：model-and-conversion与external-algorithm-publish，10 passed / 0 failed / 0 skipped，20.1s；sophon-chrome-final-1020.log。包括新Sophon矩形真实HTTP提交fixture、资源缺失、两chip筛选、FP16/INT8边界、BMODEL尚未实机验证，保留RKNN板验和已有发布用例。
- hardware/test_vendor_conversion：2 skipped / 0 passed / 0 failed，未配置显式授权/真实SDK设备。增加Sophon真实编译合同，以及同图片经PT/ONNX/SAIL BMODEL三者的检测框/类别/置信度/NMS/耗时及一致性precision/recall验收；不是仅比较shape，且一致性不冒充GT mAP。
- 独立规格复核确认两P1关闭并通过；最终只读质量复核无新增确认P0/P1，可普通提交推送。未运行无关本地全仓库测试。
- 工作流YAML解析与原永久Remote Conversion守卫通过。预提交守卫首次因旧execution_mode文本断言失败；更新为真实resource_mode及Sophon唯一remote路由/remote_connection三条精确断言后通过，未降低业务测试。


## E Git/CI（待提交 / CI未运行）

本文件为提交前可追溯快照；普通FF推送唯一长期分支，VERSION42.24.358不变。最终完整SHA全部实际触发Actions/Checks独立验收，不借用上轮23/59绿色。

按既定避免自引用新HEAD规则，提交后最终SHA/远端HEAD/运行与Checks清单记录在独立附件C:/Users/jorsam/.codex/visualizations/2026/10/20/01a156ca-1ca0-7b70-8497-bd255da4345e/sophon-ci-final-20261020.json；下一次受验证提交先归档该结果再继续。若CI有失败先在本专项记录真实原因再最小修复，不能宣称全绿。

## F 验收边界（生产未验证）

真实TPU-MLIR编译、BM1684X/BM1688设备加载、同图检测/NMS/精度比较、INT8质量退化及生产发布均NOT VERIFIED；不能用Mock编译结果冒充真实编译/实机通过。

只读质量复核记录：远端服务启动进程至process.json落盘之间仍有窄崩溃窗口，属已知可靠性边界；不将其描述为无条件恢复保证。持有已落盘身份的取消/重启恢复已由隔离测试覆盖。


## 下一会话接续与现场合同

先读CODEX_CURRENT_STATE顶部→本专项→最终SHA独立CI附件，并核对远端。没有真实编译或芯片证据时，只能称“代码与隔离验收通过”；实际部署/生产资源/新畅联写入均需另行授权。

独立TPU-MLIR资源需本地初始化非空API Key、配置tool_root/python_path及PT导出用ultralytics_python；运行实际health检查，不能凭Sophon插件目录列表放行。首期FP16/Batch1，INT8算法版本仍因冻结校准尚未闭环保留原409保护，CV186X/多核未开放。

真实硬件合同变量：XJALGO_SOPHON_HARDWARE_TEST=1、XJALGO_VENDOR_TARGET=sophon、XJALGO_VENDOR_TEST_ONNX、XJALGO_SOPHON_CHIP、XJALGO_SOPHON_PYTHON、XJALGO_SOPHON_TOOL_ROOT；板验另需SOPHON_BMODEL/SOPHON_MANIFEST/SOPHON_PT/SOPHON_IMAGE_DIR及可选DEVICE_ID（均以XJALGO_为前缀）。未授权时不执行。至少3张真实代表图片，SAIL真实加载，PT/ONNX/BMODEL同输入与类映射，框IoU/置信度与precision/recall门槛检查；GT mAP与INT8质量退化另验。当前全部真实SDK/板卡/生产证据NOT VERIFIED。
