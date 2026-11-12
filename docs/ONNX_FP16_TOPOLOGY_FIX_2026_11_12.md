# P0 ONNX FP16 拓扑修复记录｜2026-11-12

## 背景与已知证据

转换任务 f94ef19780625bb608e60b9a：YOLO11n/person、ONNX FP16、640×640、batch=1、opset12、simplify=true，Ultralytics 8.4.127，在 CPU 导出。

用户提供的生产证据：321 个节点，Conv（序号0）消费 graph_input_cast_0，Cast（序号319）产生这个张量；生产者存在但节点顺序无效。用户曾在单独副本把 Cast 提前，Checker 和 Runtime CPU 推理通过，输出 [1,5,8400]。这些是用户先前验证，不能作为本次 CI 测试成绩。

用户先前合成输入 PT/ONNX 数值比较：全零 MAE=0.04176696、相对 MAE=0.00023607、余弦=0.99999996；随机 MAE=0.03925148、相对 MAE=0.00025315、余弦=0.99999996；最大绝对差分别为 0.80749512、0.51306152。很高的整体余弦相似度不代表所有框和置信度都一致。

日志显示先 slimming 再 converting to FP16，无法仅凭此将原因唯一归咎于 onnxslim。保留 Ultralytics 8.4.127 既有 half=True 调用，不未经测试切换 quantize=16。

## 真实代码审计

原有 deployment_worker.export_pt_to_onnx() 已检查新文件证据、模型来源和 SHA256。
原有 prepare_onnx() 会直接进入颜色适配，之后才进行 Checker 和 Runtime 验证，因此不具备纯拓扑错误的安全恢复能力。
TensorRT、Sophon、Rockchip、Ascend 共享 ONNX 准备入口；本次仅改公共 ONNX 图预处理及状态证据，不修改厂商编译流程。

## 修复内容｜42.24.588

- 新增 platform_core/onnx_topology.py：为顶层图建立生产者依赖与消费者索引，检查图输入、Initializer、SSA 唯一性、图输出完整性，基于原位置优先的 Kahn 稳定拓扑排序。多个 Cast 和普通算子都能处理，不针对 graph_input_cast_0 硬编码。
- 如果图本来排序正确且 Checker 通过，直接返回原文件，不重新序列化。
- 如果依赖缺失、重复生产者、循环、控制流或嵌套图、外部/稀疏权重，拒绝自动修复。
- 只改变 NodeProto 的排列顺序，其他元数据、图形输入输出、原权重和 Opset 不变。先 Checker，再保存独立拓扑副本，再 Checker。原始 .pt 和原始导出证据保留。
- prepare_onnx() 在颜色输入适配前完成必要的安全重排；后续继续使用 ONNX Runtime 进行真正的 CPU 推理校验，失败不得成功登记转换产物。
- 通过原有 ConversionError 系统区分 ONNX_GRAPH_TOPOLOGY_INVALID、ONNX_GRAPH_REPAIR_FAILED、ONNX_RUNTIME_LOAD_FAILED、ONNX_RUNTIME_INFERENCE_FAILED 和其他契约问题。
- execution_evidence 记录 topology 状态、节点数、移动数量、Checker 和 Runtime 状态，并明确 pt_onnx_numeric_validation=not_performed。不将可加载 Runtime 验证冒充 PT/ONNX 精度一致。

## 验收与限制

- tests/unit/test_onnx_topology.py 用真实 protobuf/Checker/Runtime 覆盖 640、800、FP16、FP32、多 Cast、普通节点、非法输入、重复输出、循环、子图、外部权重、正常图不改变与失败拒绝旧产物复用。测试接入既有 Remote Conversion CI control-plane 任务（安装了 onnx 和 onnxruntime）。
- 必须继续验证同一 YOLO11n 在真实 Ultralytics 8.4.127、Torch、onnxslim 环境下的导出；没有隔离生产源 PT 时不能声称复现已通过。
- 真实图片仍须测试坐标通道、person 置信度、阈值穿越、匹配框 IoU、误检漏检。当前没有这部分证据，必须保持未验证。
- ONNX Checker/Runtime 成功不证明 TensorRT、BMODEL、RKNN、OM 的编译或设备验证通过。
- CI 最终结果以 GitHub 对准确提交的返回值为准。

## 安全边界和进度

代码修复提交只涉及长期分支 feature/external-algorithm-publishing，不触碰 A800 运行任务、数据库、GT、训练权重、生产服务和生产运行环境；绝不部署生产服务器。
