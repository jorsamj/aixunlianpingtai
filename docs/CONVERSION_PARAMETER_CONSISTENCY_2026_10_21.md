# Tags、转换参数、AMP 与 SDK 检测一致性验收

## 需求与安全边界

2026-10-21，基线 b74a3866cc85dd5f169d5be8bee1916172e67a26 / 42.24.365，远端 fetch/pull 一致、工作树干净。其他可见会话无同库活动；其他工作区不动。前轮字典修复最终 Actions 48/48、Checks 131/131，独立回执 catalog-reference-edit-ci-final-20261021.json，不能替代本轮验收。

本轮要求：冻结标签贯穿实际 add/edit JSON、确认回执及远端读回；可选信息缺失非阻断。转换选择值、后端决议、Worker 命令与历史事实一致；Sophon 依据实际资源支持 FP16/FP32，固定项和调用侧预处理明确；RKNN 不将非量化误称产物 FP16；训练 Auto/FP16 AMP/FP32 在全部模式保留选择并校验实际 AMP。SDK 芯片状态依据选中资源，重检和异步响应归属安全。现有页面统一组件、主字段清楚、高级信息折叠，无重复 Owner/包装/轮询/事件绑定。

只复用 ExternalAlgorithmPublishService、ModelArtifact、原转换 resolve/create/Worker、training_precision、现有 SDK 探测与页面。禁止生产写入、部署、真实训练/转换、OSS、远端 Weight 写接口。定向测试仅修改范围及直接依赖 Python/API、Node、Chrome；不全仓测试、不删断言、不扩 CI。最终版本按整合后远端一次递增，普通推送并核验实际 SHA。

## 已证实与待核验

- 已证实代码：空 prepared weight_metadata 会过滤 canonical tags；训练 quick/full/complex 构建精度时丢弃显式选择；提交转换时在异步资源刷新后把旧 resolve params 覆盖当前输入。先新增 RED，再改原实现。
- 后端 create 已对厂商目标重新探测并 resolve，保留此安全边界，不能再建立第二预检 Owner。
- 生产只读 SSH `ssh -o BatchMode=yes -o ConnectTimeout=8 a800-server pwd` 连接被拒绝（banner exchange / Connection refused），未执行服务器命令。17 个历史 Weight / 7 个缺回执及真实网页 tags 本轮仍 NOT VERIFIED，不以隔离测试冒充现场。
- 官方 ATC 文档提供 force_fp32 与 allow_fp32_to_fp16 模式，但编译请求不等于逐算子/产物 dtype；实际硬件结果必须单独标记。

## 执行与验收进度

本地 A-D 完成；限定测试通过，版本42.24.366一次递增。E最终提交/推送CI待执行，不能提前标绿。

## 真实根因与最小修复

1. **Tags**：`_weight_metadata_payload()` 误把空 `weight_metadata={}` 当作标签不可信，过滤已有可信 canonical tags。允许空准备映射复用有效 canonical 类别；显式 UNKNOWN/CONFLICT 或有准备字段却无类别仍不回填，未知绝不发送 `[]`。冻结 class_id 顺序、Snapshot/lineage、防冲突、真实目标字节 SHA/大小原功能保留。Requests Adapter 捕获真实序列化 JSON；不是只检查待发送 Python dict。
2. **请求与回执**：沿用 IntegrationAuditRepository，按版本/Artifact读取最后一次真实 HTTP add/edit 记录；详情分别展示冻结、本地、准备、HTTP请求状态、确认回执、远端 tags 与读回时间。网络 UNKNOWN 仍标 UNKNOWN；远端未返回 tags 不声称已持久化。恢复回执不伪装成发送记录。
3. **训练精度**：quick/full/complex 重建 preset 时丢弃 precision；高级设置还固定 amp=true。保留明确精度，FP32发送AMP=false、FP16发送true；Auto保留后端Worker实测/安全回退。四模式共享一个Draft，精度放在原训练模式卡片中，修复旧高级CSS隐藏。离线AMP、无参考权重不下载、实际AMP不匹配必须报错等原安全策略未修改。
4. **转换表单**：submit在异步刷新后合并旧resolve参数，覆盖用户宽高/预处理；改为await前固定当前输入，后端原create实时resolve仍为准。单次提交锁、POST已成功但历史刷新失败不允许重复创建。旧项目/旧form/旧成功或失败响应不污染新界面。检测单个资源失败仅影响该资源，不能清空其他资源或恢复旧选择。
5. **Worker**：全部目标采用validated target参数；Ascend FP32明确`force_fp32`、FP16默认`allow_fp32_to_fp16`，冲突拒绝；既有显式keep-origin/mix合法策略保留，不能假称纯FP32。TensorRT FP32明确`--noTF32`，FP16仍`--fp16`；真实SDK拒绝时保留错误。Sophon固定opset12/simplify=false改为冲突即明确报错，不静默改写；固定项来自原模板并在高级区只读。一次Worker预检交给builder复用，直接builder调用仍预检。
6. **ONNX/Agent**：原导出未使用precision；原portable ONNX丢弃precision。PT导出显式half、FP16/FP32有实际张量核验，不允许SDK忽略FP16仍假成功；厂商中间ONNX保持FP32，由编译器决定部署精度。已有ONNX保留原图，隐藏不适用的导出控件；后端只根据真实源后缀标记复用，客户端不能伪造该标志。实际ONNX Shape与厂商声明静态Shape不符时在编译前失败。
7. **执行事实**：原job/manifest增加同一份`execution_evidence`，区分源训练、后端决议、编译模式、产物精度未核验和ONNX复用。Agent经原有受限runtime_result传回，严格类型/大小/Shape校验并拒绝伪称产物dtype；Controller核对compiler事实与准入参数，保留原SHA/大小/generation/Lease保护。原Agent manifest补齐统一job/source/outputs/tool事实，使ModelArtifact仅在真实输出和源SHA匹配后导入。复用ONNX尺寸取已绑定manifest实际图Shape，不填导出默认值。
8. **SDK与UI**：芯片初始检测中，完成后按选中资源的后端chip_options展示；无资源、鉴权/SDK失败不能停留假检测中。检测当前资源复用一个原detect POST，resolve是其后不同目的的合同读取；无第二探测器。训练、转换、发布详情使用原卡片/表单/折叠区，Sophon编译完成始终保留未实机验证提示；冻结类别/证据收纳详情，专业参数默认折叠。

## 统一参数矩阵与事实边界

| 路径 | 已生效/强校验 | 固定或推理端合同 | 未核验边界 |
|---|---|---|---|
| Sophon BM1684X/BM1688 | 实际资源支持矩阵；默认FP16，可验证SDK允许时FP32；F16/F32真实命令；独立Python/完整版本 | Batch1/Core1/static/opset12/simplify=false；NCHW、调用端RGB/Mean0/Scale1/255/Letterbox/Pad114；解码NMS外置，不重复fuse | BMODEL结构与chip检查不等于板端运行或全算子dtype |
| Sophon BM1684 | 1.30.2实际工具与芯片证据允许的FP32/真实chip flag | 同原Sophon Adapter，不从训练batch/precision猜测 | 本轮无真实板卡编译/精度性能验收 |
| RKNN | 原chip/SDK/版本检测；Mean/Std传runner；非量化或冻结INT8；Shape一致性 | `do_quantization=false`只表示非量化；版本INT8仍需冻结校准合同，未开放的不能绕过 | 不把非量化自动写为已证实FP16；RKNNLite硬件验证独立 |
| Ascend | SoC/InputName/Shape/Batch/AIPP配置/precision_mode真实ATC命令 | AIPP启用才生成并传配置；legacy keep-origin/mix显式保留 | `force_fp32`仍受官方算子实现限制，不承诺每层纯FP32 |
| TensorRT | Workspace版本参数、Batch导出、目标GPU/CUDA/TRT环境、FP16/FP32 flags | FP32禁TF32；真实trtexec失败不伪成功 | Engine绑定实际硬件；仅命令选择不是产物dtype或性能证据 |
| PT→ONNX | 矩形Shape、Batch、opset/dynamic/simplify、显式half；Checker+ORT | 架构/标签来自训练版本；无未验证BF16/INT8选项 | 不以训练AMP推导ONNX或部署精度 |
| 已有ONNX | 保留原图、真实Checker/ORT与实际输入Shape | 隐藏不能应用的导出选项；保留原请求留痕 | 未重新导出、未重新应用opset/simplify/precision，不冒充生效 |
| 训练 | Auto AMP、FP16 AMP、FP32；原Worker预检与最终AMP一致性 | 模式preset只确定epochs/imgsz等，不能丢精度；不下载参考模型 | 本轮无真实GPU训练，实测AMP/性能待现场 |

官方依据：[Ultralytics pinned exporter](https://github.com/ultralytics/ultralytics/blob/v8.4.127/ultralytics/engine/exporter.py)、[ATC precision_mode](https://www.hiascend.com/doc_center/source/en/CANNCommunityEdition/910/devaids/atctool/atlasatcparam_16_0068.html)。add/edit的原生tags数组与可选字段合同沿用现有新畅联OpenAPI；真实provider持久化另行现场核验。

## RED → GREEN 与受控测试

- 初始RED：preset精度丢失1；canonical空准备tags1；Ascend模式缺失2/Sophon固定参数覆盖2；旧弹窗覆盖1；矩形预处理被旧resolve覆盖1；Worker执行证据缺失2；ONNX half未传3；HTTP请求事实投影缺失1；Agent运行事实sanitizer丢弃1；portable ONNX精度丢弃2；SDK失败长期检测中1；旧失败响应/单资源失败清空其他资源2。均由真实原代码路径复现，再修改原实现。
- 夹具与修复期间失败如实保留：新Tags测试首轮未seed算法的IndexError（修正夹具后得到缺request_tags的实际RED）；一条PowerShell引号命令未执行成功；旧未知标签测试揭示不能无条件复用历史标签，恢复UNKNOWN/CONFLICT保护后3项定向及发布全文件180通过。Node异步测试首次暴露忙标记未写入，修复后通过；两个旧资源刷新用例因新归属校验需要稳定DOM对象夹具，并保留原断言。未删测试、弱化断言或跳过失败。
- Python批次：`test_conversion.py test_sophon_conversion.py test_training_precision_contract.py test_dynamic_conversion_catalog.py test_remote_conversion_transport.py`首批145通过；实际受后续改动影响部分再定向复测。发布`test_external_algorithm_publish.py`180通过；API动态字典/远程Sophon31通过；Worker/Agent最终三文件78通过；transport/sanitizer仅conversion相关22通过；最终模型资产/manifest/远程恢复/direct builder投影6通过；可选执行证据/身份保护参数化扩展5通过，旧用例标识按当前参数化替换去重。JUnit分批去重403例全部通过；不是全仓测试。
- Node：training-submit38、external-publish18、conversion-unified7、rknn-resource22、training-submit-validation12、training-draft-runtime6、version-marker9，分批通过；只在对应修改后重验直接影响项，不相加重复运行次数。
- Chrome：首次7场景5通过2失败，分别为真实旧CSS隐藏训练精度、Sophon缺少硬件边界提示；原位置修复后失败2项通过。随后受UI精度位置/AMP和ONNX复用影响的3场景通过。最终9个不同相关场景通过，包含4个发布、矩形FP16、FP32+SDK重检、四训练模式、训练配置提交、已有ONNX只读控件。页面使用真实Chrome；provider/SDK写入为隔离协议夹具，不是生产或真实硬件。
- 没有执行全仓、训练业务实跑、素材/清洗大规模测试；原混合文件中的源码守卫不触发其业务执行。CI仅既有工作流正常触发，无新增大型CI。

本地JUnit汇总、截图和生产只读诊断统一位于既有visualizations目录，文件：`tags-parameters-local-tests-20261021.json`、`sophon-precision-form.png`、`sophon-precision-evidence.png`、`training-precision-20261021.png`、`tags-production-readonly-diagnostic-20261021.json`。已实际查看Chrome截图，精度控件整合进原模式卡片，非再叠一个配置页。

## 质量审查与发布进度

直接审查原Owner/事件生命周期/请求归属/实际参数/历史保护；独立只读review发现历史请求迟到与检测恢复旧选择两项P2，已修复并补动态测试；末轮复核另发现可选执行证据诊断误用身份错误字段的P2：新增RED 1失败/1通过，改为独立execution_evidence_note、保留原身份门禁，5项GREEN关闭。复核无遗留必修P0/P1/P2。后续同链路错误响应回归也已RED→GREEN。无新Service/Repository/Worker/数据库/队列/轮询/监听器/全局wrapper；无重复事件注册。请求为一次明确操作，必要探测与resolve/读回各有职责；单个SDK失败不污染整个资源集合。旧app中无关历史包装与旧页面债未无边界重构，不声称全仓零历史技术债。

VERSION从最终整合基线365一次递增366，后端/可见版本仍读唯一VERSION；app/main/styles必要缓存413，training-create CSS4226354，training-submit422600，publish64013。没有只改显示版本；VERSION读取/runtime/FastAPI元数据/system/health/UI/app_info等8项实际投影均为42.24.366。提交前再次fetch核对远端；最终实际SHA/Actions/Checks/关键Jobs写独立 `tags-parameters-ci-final-20261021.json` 回执并在交付中报告。本节提交时CI待推送核验，不借用基线绿色、不制造自引用SHA文档提交循环；下一次受验证提交归档实际回执。

## 生产未验证与下一步

1. SSH连接被拒绝；生产真实HEAD/VERSION、17项/7缺失回执、当前自动发布日志、getInfo/listByVersion tags及新畅联网页仍未核验。不能据此把最新代码空映射问题认定为七个历史故障的唯一根因。
2. 恢复只读连接后，先核对生产运行SHA/版本、执行原`audit_weight_metadata.py`默认dry-run、读取原HTTP审计/确认回执、对应Weight查询响应与真实网页。按7缺失/10对照分组，不改DB/OSS/Weight。远端未返回tags记NOT_RETURNED，错误或冲突保留真实原因。
3. 如需历史补齐，先给出逐Artifact/Weight/旧新参数/身份核验/风险及回滚报告；另行授权后才用原Owner原ID edit与查询读回。不得直接SQL批量修状态、重复add或删除历史。
4. 独立SDK环境/真实Sophon F16/F32、TensorRT、ATC、RKNN与GPU AMP、性能及板端推理仍需现场验证；本轮没有安装环境、真实编译、训练或硬件测评。旧Agent/远程Worker未返回执行证据时显示未记录，不凭任务精度标签补造证据。
5. 未部署、未重启服务、未改生产密钥/配置/数据库、未上传删除OSS、未调用真实新畅联写接口。本轮代码验收与生产现场交付明确分开。

## 修改文件清单

- `AGENTS.md`
- `VERSION.txt`
- `app.py`
- `deployment_worker.py`
- `docs/AMP_OFFLINE_COMPATIBILITY_2026_10_11.md`
- `docs/CODEX_CURRENT_STATE.md`
- `docs/CONVERSION_PARAMETER_CONSISTENCY_2026_10_21.md`
- `docs/DYNAMIC_CONVERSION_CATALOG_ACCEPTANCE_2026_10_20.md`
- `docs/SOPHON_BMODEL_CONVERSION_ACCEPTANCE_2026_10_20.md`
- `docs/WEIGHT_TAGS_SYNC_ACCEPTANCE_2026_10_20.md`
- `platform_core/agent_execution.py`
- `platform_core/compute_platform_catalog.py`
- `platform_core/conversion.py`
- `platform_core/external_algorithm_publish.py`
- `platform_core/integration_audit.py`
- `platform_core/model_artifacts.py`
- `platform_core/node_agent_conversion_runtime.py`
- `platform_core/remote_conversion_runtime.py`
- `platform_core/remote_execution_transport.py`
- `static/app.js`
- `static/index.html`
- `static/main.mjs`
- `static/modules/external-algorithm-publish.js`
- `static/modules/training-submit.js`
- `static/styles.css`
- `static/training-create-modal.css`
- `tests/api/test_dynamic_conversion_catalog.py`
- `tests/api/test_sophon_remote_admission.py`
- `tests/browser/model-and-conversion.spec.mjs`
- `tests/browser/training-quality-reports.spec.mjs`
- `tests/frontend/conversion-unified-task-truth.test.mjs`
- `tests/frontend/external-algorithm-publish.test.mjs`
- `tests/frontend/rknn-conversion-resource-live.test.mjs`
- `tests/frontend/training-submit.test.mjs`
- `tests/frontend/version-marker-owner.test.mjs`
- `tests/unit/test_agent_execution.py`
- `tests/unit/test_conversion.py`
- `tests/unit/test_external_algorithm_publish.py`
- `tests/unit/test_model_artifacts.py`
- `tests/unit/test_node_agent_conversion_runtime.py`
- `tests/unit/test_remote_execution_transport.py`
- `tests/unit/test_sophon_conversion.py`
