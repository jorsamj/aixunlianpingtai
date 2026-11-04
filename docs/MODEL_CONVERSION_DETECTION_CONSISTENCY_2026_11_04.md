# 模型转换数值与检测结果一致性治理（42.24.526）

## 42.24.526 四个历史红灯的浏览器回归合同接续（2026-11-04）

准确 525 远端提交 `320cb6cf92ede2679204ad99dd643e6a3494b34a` 的 37 个工作流已完整结束：33 success，4 failure；两组 Remote Conversion Runtime 均 success。4 个失败工作流与原 523 相同：Training Material Picker、Training Create First Open、ZIP Import Durable Runtime、Frontend Runtime Stabilization。逐项日志证据：

- 训练旧同步用例继续假设无需用户确认就自动 POST / 弹出负样本确认窗口；新生产默认改为**显式人工确认范围后后台准入**。把专测历史同步确认的用例显式设置 `MC_TRAIN_ADMISSION_MODE=synchronous`，保持这一 API 分支的真实回归，默认 UI 的反馈候选与 Benchmark 提交用例则按实际勾选明确授权和 Benchmark 按需查询后提交。原有默认流程及业务安全门禁未放松。
- 训练素材角色页首次只查分页数据、总数按需统计，待用户选择角色过滤才查询完整角色投影。修正旧用例在首次打开就等待角色投影/精确总数的不合理前提，不重新引入 20 万素材全量首查。
- ZIP 新原图治理把 `data.yaml` **视作候选类别提示而不是标注证据**。修改旧浏览器测试中所有本应测试“正式标注 ZIP”的夹具，明确生成对应的非空 YOLO `labels/train/*.txt`；独立原图测试反而验证 `RAW_UNANNOTATED` 默认无需生成正式 GT 或强制确认。
- 重复治理任务的短时 Toast 被最终删除成功提示覆盖。测试改为验证原页面持久的 `.integrity-stale-note`，并保留成功、进度与失效三个独立事实断言，不反向改变成功提示。
- 训练准入治理的模拟 CPU 目标漏填现有必需 `status=ready`，导致开始训练一直 disabled；修正真实合同夹具，并显式运行其原本要测的同步诊断分支。

以上是按现行产品语义修复**过时测试**，没有修改生产数据、正式 GT、权限、训练/ZIP 写入行为或用户默认交互；浏览器 CI 尚需以 526 精确 SHA 验证。若仍红灯，必须继续查真实回归，不允许直接跳过测试。

## 42.24.525 远端转换 CI 回归修复（2026-11-04）

准确 524 提交 `786dd821a3a19fac5d7842dd2d3aab690b8725f0` 的 `Remote Conversion Runtime` control-plane 出现 7 个失败：5 个旧任务远端恢复因新插值参数对旧 manifest 直接严格比较而失败、1 个旧 CSC 转换合同无法通过结构检查、1 个旧 `model_validation_status=incomplete` 兼容断言被错误改为 `unavailable`。旧分支此前的该工作流通过，属于本轮引入的回归，不能当成旧失败掩盖。

本版修复：对于**冻结于 524 前**且尚未显式含插值/LetterBox 模式字段的任务，采用现有 `validate_target` 校验历史字段并只补齐唯一且无歧义的默认值；对于**已经显式冻结新字段**的任务，远端 target/parameters/structure 任一缺少证据或值不一致仍失败关闭，不能降级绕过。`model_validation_status` 保持旧的 `incomplete`（没有现场/硬件闭环），新增独立 `compiler_numeric_status` 承载 `passed_synthetic_reference` 或 `unavailable`，兼容旧代码、避免误称模型整体已验证。新增旧任务恢复、显式冻结拒绝及精确匹配通过三项回归，SDK 数值测试断言也分离这两层状态。

524 基线的 `Training Create First Open` Chrome 四个失败在父提交 523 上已逐一出现，非本期转换回归，仍须单独训练页面专项处理。525 全套 CI 以准确新 SHA 重新核验，不在本地冒称已通过。生产仍未改动。

## 42.24.524 接续修复（2026-11-04）

起点：长期分支 `dd6533f0d2e42aeff0bd9715eeebddbf28ddb097`（42.24.523）。保留 523 的阈值跨越、NMS、ONNX 旧产物保护，不重建任何任务中心、转换 Owner、质量中心或业务弹窗。本次继续落实 P0 及有限 P1：

1. **可复现的场景阈值对照**：原质量中心「转换一致性」同页增加用户指定的置信度与 NMS IoU（均严格处于 0～1），随真实图片冻结到 Durable 任务回执；同请求 ID 修改阈值拒绝隐式复用。`compare_yolo_detections` 输出逐图 class_id、confidence、XYXY 检测框（UI 单图内联展开，最多展示前 20 个）；比较使用全部未截断的有效 NMS 框，超过安全上限不得判通过。检测结构不支持时总体 `not_comparable`，保留单独 `raw_verdict`，避免张量通过误称检测一致。不使用无 GT 图片冒充 FP/FN。
2. **模型与标签身份**：从现有 `model_metadata` 的冻结版本/可信 Snapshot 获取标签；相互冲突/缺少历史证据不自动造标签。导出器同时记录真实 PT `names`，在 Sophon 编译前与可信版本的 code/class_id 逐项比对，不一致拒绝编译（旧导出器无名称证据则保持 unknown，不能标为配置完整）；转换后真实图片数值任务也复核此顺序，错误时 `contract_mismatch`。转换 manifest 扩展同一份 `inference_contract`，记录 BMODEL SHA、输入参数、类别映射哈希及外部输出解码/NMS/阈值的待确认状态。`caller_acknowledged` 明确为 false，**不冒称中台已按合同部署**。
3. **冻结真实产物身份**：数值任务优先按原 manifest `outputs` 的唯一 ONNX/BMODEL 相对路径、SHA256 与 size 锁定；不再从 glob 取字母序第一个。旧 manifest 没有完整哈希时，只允许唯一文件并明确标记 unverified。源 PT SHA 不一致直接拒绝。
4. **官方 TPU-MLIR 编译对照**：检测 SDK `model_transform --test_input/--test_result` 和 `model_deploy --test_input/--test_reference` 全套能力；仅能力齐备时使用可复现的合成归一化输入生成 Top-MLIR 参考，再启用官方编译数值比较，失败不交付 BMODEL；支持 `--compare_all` 的 SDK 同时启用详细对照。精确记录输入/reference SHA 及 `passed_synthetic_reference`。旧 SDK 不提供完整能力则保持 `unavailable`，不把普通编译成功称作数值通过。**合成输入只能证明有限编译自检，不代表真实图片或设备实机质量。**
5. **明确的插值前处理**：新增 `opencv_linear` + 固定尺寸居中 LetterBox/拉伸模式合同。数值任务使用 OpenCV `INTER_LINEAR`，缺 OpenCV 报错而不是默默以 PIL 近似代替。旧合同缺少插值证据时 `deployment_preprocessing_aligned=false`。
6. **Val 错误抽样**：训练后自动错误分析不再取文件名前 200 张；改为稳定 SHA256 次序、按冻结 Val 标注类别和空标注分层，轮流覆盖稀有类，写入本次 `error_analysis_sampling` 样本总体和方法证据，默认分析上限仍 200/可配置最高 500。没有可靠摄像头、时间、光照元数据，不推断对应分层。冻结独立 Test、真实场景实测与正式 GT 均未更改。

### 本轮执行证据与边界

- `node --test tests/frontend/conversion-numeric-workbench.test.mjs`：**5/5 通过**；排除未安装的 Uppy/Annotorious 供应商依赖用例后，相关全体 Node **1466/1466 通过**；完整 Node 受缺依赖阻断，不能计为全绿。
- Python `py_compile`、`git diff --check`、原始张量阈值跨越/标签顺序纯函数、模拟 SDK 官方参数/参考 NPZ 路径以及 Val 分层抽样隔离检查均已通过。当前容器缺 pytest、filelock、FastAPI、OpenCV、ONNX Runtime 与 Ultralytics，故所有新增 Python pytest、真实 SDK、真实 PT/ONNX、Chrome、生产性能与中台现场 **NOT VERIFIED**，必须等准确提交 SHA 的 CI 再判断。
- 中台视觉智能分析源码与真实 BM1688 运行数据仍未提供，无法在本仓库修复事件触发、轨迹过期、现场 BGR、NMS 和输出解码实现。要求中台对接者按照同一 manifest 给出原始检测/跟踪/规则证据；没有这份证据就不能声称四类误报已经解决。
- 未运行训练、未触碰生产数据库、素材、正式 GT、模型权重、OSS、GPU 或 Web/Worker；不部署，不 merge main，不 release，不 force push。

### 后续验收（未完成）

- 用 A800/独立 SDK 对 1～12 张真实、同源、含硬负样本图片核对 PT→ONNX→BMODEL 数值、类别/NMS 框差异，分别确认 SDK 的 reference 脚本/`compare_all` 与 BMODEL simulator 的可用性，并保存输入与产物 SHA。
- 从中台取得同图前处理、BMODEL 输出张量、解码、标签、区域、持续帧数、跟踪 ID 与事件状态流，落实 `caller_acknowledged` 的外部可信回执；无人徘徊必须检查轨迹/旧事件清除。此步骤依赖中台仓库或可核验回放证据，**不在本仓库凭空实现**。
- 针对正式冻结独立 Test/现场回放样本做各类别阈值曲线与推荐策略、误报回流；保留现有线上反馈与难样本 Owner，不自动将 Test 样本投训练。

---

## 42.24.523 历史记录

日期：2026-11-04。分支：`feature/external-algorithm-publishing`。仅开发候选；生产尚未部署、现场 BM1688/中台推理链路尚未核验。

## 背景与需求

用户反馈原始 PT 与部署 BMODEL 检测结果可能不一致，且存在单人触发打架、白色区域触发抽烟、红色区域触发烟火、空场景触发徘徊。检测与事件规则可能分别产生偏差；不能只因 BMODEL 文件生成、结构检查通过或张量整体数值接近，就宣称场景质量合格。

**本期仅修复当前仓库可证实的数值诊断盲区及过期 ONNX 选择问题，不编造中台源码，不新增实机验证、不修改任何正式素材/GT/任务/模型数据。**

## 已实现

1. `numeric_consistency.compare_yolo_detections`：仅支持明确的单输出 YOLO11 XYWH+类别概率布局；按置信度 0.25、类别分离 NMS IoU 0.7，比对 NMS 后 class/box IoU≥0.95/置信度差≤0.02，显示阈值跨越、新增或消失检测及置信度差异。其它输出布局明确不可比较，不伪造“检测一致”。每图候选上限 512，最多保留 300 框，避免异常输出造成验证任务无限运行。
2. 原有张量比较指标与独立 `raw_verdict` 保留；若检测结果已知不一致，最终 `verdict` 不能继续标为 `consistent`。可用 Sophon 官方离线模拟器时也计算 ONNX/BMODEL 检测差异；不可用保持 `unavailable`、`hardware_verified=false`。
3. `is_canonical_rgb_preprocessing` 明确核验部署合同与本次标准输入是否相同；非标准合同标示尚未验证，原始数值结论不冒充实际中台前处理结果。API 为 Durable 验证任务冻结本次转换的预处理配置。
4. 质量中心沿用既有「转换一致性」页面，增加检测阈值/NMS 差异列、单图对照结论、非标准前处理及未知布局提示；原厂商检测/转换入口、已有数据中心与用户反馈 Owner 不变。
5. `export_pt_to_onnx` 优先使用导出器本次返回的明确 ONNX 路径；对无路径的兼容情形只接受唯一一个实际变化的文件，不再因旧文件存在就优先引用旧文件；记录本次产物 SHA256。

## 代码及回归

业务：`platform_core/deployment/numeric_consistency.py`、`deployment_worker.py`、`app.py`、`static/modules/quality-detection-workbench.js`；回归：`tests/unit/test_conversion_numeric_consistency.py`、`tests/unit/test_sophon_conversion.py`。

隔离反例：原始张量中某一检测 score `0.24→0.26`、阈值 `0.25`，原平均误差/余弦门槛通过，但检测结果出现新的 NMS 框；升级后须显示差异。对 NMS 压制的无害候选跨越，仅显示提示，若最终检测集不变，不误判不一致。类别交换、未知输出布局、旧 ONNX 文件均有回归。

2026-11-04 本地验证：全量 Node `npm test` **1522/1522 通过**；相关定向 Node **15/15 通过**；`node --check`、`python -m py_compile`、`git diff --check` 和版本解析脚本均通过。`compare_yolo_detections` 隔离真实 NumPy 反例成功复现原张量通过但检测阈值跨越，并拒绝类别错配；导出函数 AST 隔离检查旧 ONNX 拒用及明确本次产物复用行为通过。此环境**缺 pytest、filelock/FastAPI 等服务端依赖**，新增 Python pytest 文件与后端 ASGI、真实 TPU-MLIR、真实 Chrome、准确提交 SHA 的 GitHub Actions 均**尚未完成验证**；不得借 Node 全绿宣称后端合格。

## 尚未解决（下一阶段）

- **P0 转换编译时官方数值证据**：当前 Sophon `model_deploy.py` 仍未自动接入冻结真实图片的 `--test_input/--test_reference`；先设计可信样本/模型哈希与 SDK 能力门禁，再决定自动阻断策略，避免破坏既有转换能力。
- **P0 中台部署证据**：`preprocessing`、输出坐标、NMS、class_id/label_codes、告警阈值与轨迹/时序规则需由独立「畅联云中台」推理代码按同图核验。本仓库不能证明现场设备检测结果。
- **P0 类别身份**：旧算法版本可能缺少可信 `label_codes`；需要兼容历史版本的独立补证流程，不能直接将旧版本全部阻断或自动补造标签。
- **P1 自动训练错误分析**：`train_worker.analyze_detection_errors` 当前只按文件名取前 200 张 Val 图片；后续应扩展来源/摄像头/时序分层抽样，并与已有冻结 Test 与难样本治理联动，不能混淆 Val 和 Test。
- **P1 质量验证完整度**：目前检测对照针对 YOLO11 原始单头输出与固定示例阈值，不覆盖所有厂商、多头/已融合 NMS、任意类别专属阈值。需以格式明确的适配器增量支持，未知结构保持不可比较。

## 上线边界

后端编译/检测与浏览器静态入口发生改变，必须以准确版本 42.24.523 的 CI、离线测试及实图样本复核为准；生产环境、正式数据库、存储、模型文件均未修改。不可宣称 BMODEL 已实机验证或场景误报已经消失。不 merge main，不 release/tag，不 force push。
