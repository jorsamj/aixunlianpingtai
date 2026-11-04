# 模型转换数值与检测结果一致性治理（42.24.523）

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
