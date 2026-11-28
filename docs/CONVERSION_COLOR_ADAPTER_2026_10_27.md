本轮2026-10-28模型版本转换增量进度见[唯一专项](MODEL_VERSION_CONVERSION_GOVERNANCE_2026_10_28.md)。本文件原RGB/BGR及参数真实性合同继续有效；CSC不等于通道交换。

# 转换任务 RGB/BGR 输入颜色适配（2026-10-27）

本功能仅作用于模型转换，不修改训练、素材、标签、平台模型权重或已有转换产物。

## 行为

- 转换界面选择目标模型输入颜色 RGB（默认）或 BGR，源训练模型按 RGB 显式标识。
- 新转换参数 `source_color_order` / `input_color_order` 经原转换任务、远程/Agent 路径及产物 manifest 传递。
- 颜色不一致时，统一在 ONNX 计算图入口引入 NCHW channel Gather [2,1,0]，保持公开输入名、形状、输出不变；绝不原地改写来源模型。
- 采用 ONNX Checker 与 ONNX Runtime 的确定性浮点输入，比较改前 RGB 与改后 BGR 的全输出数组，误差超限直接失败；SDK编译与板端硬件验证仍分开记录。
- Sophon 运行时预处理约定 `pixel_format` 与目标颜色保持一致，不重复融合 BMCV/Mean/Scale。
- 当前已实现的 ONNX 中间产物厂商转换器（Sophon、Rockchip、Ascend、TensorRT）共用此逻辑。字典中未接入 Adapter/SDK 的厂商保持未适配，不允许假成功。
- Paddle Inference 直接导出不经 ONNX，对于改变颜色的请求拒绝，不宣称已经支持。
- 单输入、float32/float16、静态三通道 NCHW 才能做颜色适配；外部数据、ONNX 控制流、多输入及未知图结构 fail closed。
- 转换列表和详情读取已经记录的颜色参数；历史记录没有颜色信息时显示“未记录”。
- 对于已有 ONNX，UI 默认源色 RGB 适合平台标准 YOLO；如果来源预处理不是 RGB，需先明确源合同再通过 API 指定 source_color_order，禁止猜测。

## 重要边界

颜色适配只修复**真实目标推理输入**与训练模型所需颜色不一致的问题。
生产端声称是 RGB 时，不能仅凭一张异常检测图将新 BGR 权重直接替换生产模型。
高置信度误报还须通过实际输入张量、原始模型输出与实机测试确认。
