# 42.24.518｜算法版本转换工作台、历史记录与数值一致性验证

日期：2026-11-04；开发分支：`feature/external-algorithm-publishing`。

## 需求与边界（已冻结）

用户反馈：转换弹窗、历史列表层级过多且重点不清；PT 检测基本正常而算能 BMODEL 部署后误报，原链路只检查 ONNX 能否运行与 BMODEL 芯片结构，缺少可重复的**真实图片数值一致性证据**。用户明确要求：

1. 转换窗口和版本转换列表重新整理，视觉清爽、重要信息突出，不套娃弹窗、不新增第二套转换资源／任务中心。
2. 转换记录新增「数值验证」操作；「质量中心 → 场景算法实测」新增相关独立模式，可选择真实图片，查看逐图报告；复用快速检测已选图片。
3. **本阶段不做新增实机验证 UI。** PT/ONNX/BMODEL 的数值误差与现场识别准确率严格区分。没有模型、缺 SDK、型号/输出结构不兼容时如实报告不可比较，不模拟成功。
4. 后端必须使用现有 `TaskKind.MODEL_CONVERSION` durable Task Runtime、能力/队列/Lease/取消/恢复机制。验证与原转换记录分目录，不能修改模型产物、正式训练/评测 GT 或生产数据。

## 实现清单

| 范围 | 实现 | 验收方式 |
| --- | --- | --- |
| 转换列表 | 统一列式任务行，主操作、状态、资源、结果优先；高级筛选默认收起；旧完整证据仍可展开 | 前端回归，历史页 DOM 稳定 |
| 创建窗口 | 主配置、厂商格式选择与右侧实时配置摘要；高级 CSC／模板参数折叠；新建前关闭原历史层，返回历史不再套娃 | 原创建/资源/幂等 tests |
| 质量中心 | 场景实测第三个「转换一致性」页签：选择转换记录、上传 1–12 张真实图片、复用快速图片检测文件、提交、轮询并回看历史 | 前端回归、真实 multipart API 隔离测试 |
| 数值后端 | 冻结本次源 PT SHA、ONNX SHA（有清单则验证）、实际上传图片；RGB 统一 Letterbox 输入；Torch PT 与 ONNX Runtime 同输入直接比原始输出张量，留存逐图均值绝对误差、P95、最大误差、归一化 MAE、余弦相似度 | 新纯数值单测；缺文件/NaN/shape 冲突拒绝 |
| 算能扩展 | 若任务本地存在 BMODEL 且配置了可用 Sophon SDK Python，则**选择性尝试官方 TPU-MLIR `tools.model_runner.model_inference`**，在隔离进程中比较 ONNX 与 BMODEL 数值。SDK/模拟器不可用则明确 `unavailable`，不改变 PT/ONNX 结果 | 自动化仅覆盖模拟器不可用边界，真实 SDK 需环境验收 |
| 持久任务 | `MODEL_CONVERSION` 同一个 Handler 根据 `execution_mode=numeric_verification` 进入只读比较分支；回执文件和 TaskRuntime 结果双存；创建请求稳定 `request_id` 避免重复排队；异常上传清理本次未提交文件 | API 创建重试及项目隔离负例 |

## 真实比较协议

```
已完成的同项目转换（源 PT + 冻结 ONNX）
    → 用户挑选同一批图片并提交一次任务
    → 审核输入/大小/源权重SHA/ONNX SHA/BMODEL SHA
    → 按导出尺寸生成同一 RGB Letterbox/NCHW 0–1 张量
    → PT forward 与 ONNX Runtime 输出逐图数值比较
    → [Sophon SDK 本机可用且有 BMODEL] ONNX 与 BMODEL 官方离线模拟器对照
    → 持久化报告（通过/发现差异/不可比较/运行失败）
```

- 容忍度仅作为人工排查阈值：FP32 归一化 MAE ≤0.005，FP16 ≤0.05，BF16 ≤0.07，余弦相似度 ≥0.999，全部逐张达标才判一致；不是统计学准确率，也不是生产合格证。
- 严格 **不计算** 无 GT 图片的 Precision/Recall/mAP、TP/FP/FN。原始输出张量相似也不能代替解码、NMS、类别映射、调用方预处理、RTSP 多帧/事件规则的验证。
- 对 `input_color_order!=rgb` 的图适配模型当前返回无法比较；要在后续支持同色彩调用方输入才能执行可靠比较，不能用默认 RGB 假测成功。
- 模拟器与真实 BM1688 芯片结果可能不同；`bmodel_numeric_status=consistent` **不等于** `hardware_verified`。任何缺少官方工具链的场景必须原样记录 SDK 未就绪。
- 模型转换产物会长期留存，验证原图位于独立 `deployment/numeric-validations/<id>/images`，禁止未经项目存储治理策略自动删除仍有历史审计价值的真实图片；后续应纳入统一容量/保留期治理。

## 验收记录

- Python 定向：`tests/api/test_conversion_numeric_validation.py`、`tests/unit/test_conversion_numeric_consistency.py`、原 `test_conversion_tasks.py`、`test_sophon_conversion.py`、`tests/api/test_conversion_jobs.py`、`test_conversion_create_idempotency.py`：**77/77** 通过。
- 本轮最终源码的完整前端 `npm test`：**1521/1521** 通过；关键 Node 定向测试 **25/25** 通过。原硬编码 `app.js/main.mjs` 旧缓存键的测试已改为比较双方同版本且不低于既有基线，正式发布版本仍独立读取 `VERSION.txt`。
- Python 语法、JS `node --check` 通过。异常上传/跨目录 ID 约束等在隔离路径测试；未对生产模型、真实 SDK 或 BMODEL 跑实测。
- **待实际环境核验**：已部署生产 Web/Worker、真实 PT/ONNX 前向、Sophon 官方模拟器/TPU-MLIR 版本、Chrome 桌面/移动端视觉截图。没有这些证据不得说“生产验证完成”，不得执行生产部署。

## 涉及文件

`app.py`、`platform_core/deployment/conversion_tasks.py`、`platform_core/deployment/numeric_consistency.py`、`conversion_numeric_verification_worker.py`、`conversion_sophon_offline_runner.py`、`static/app.js`、`static/main.mjs`、`static/index.html`、`static/conversion-workbench.css`、`static/modules/conversion-workbench-ui.js`、`static/modules/quality-detection-workbench.js`、`VERSION.txt` 与新增 API/unit/frontend 回归。

## 后续独立事项（不在本批伪报完成）

1. 转换来源是 ONNX（没有正式 PT）时需单独设计可信参考输入，不用推断缺失 PT 的等价性。
2. 对 BGR 图适配、INT8、动态输入、多输出模型实现逐项正式协议与名称/shape/scale 映射，不能放宽当前 fail-closed。
3. 针对算能误报根因，在 SDK 环境具备时对相同真实图片额外检查输出布局、类别索引、decode/NMS/置信度/事件聚合等生产端解释逻辑；这些不是当前数值验证的已完成内容。
4. 浏览器三视口和实际部署全链路验收；独立收集测试模型、真实转化时间和差异报告。不得把模拟器可用误称板端精度达标。

## 42.24.519｜转换配置主次层级修正（2026-11-04）

首次推送 `42.24.518`（远端提交 `f291250520e686185f26df613941c5ca5cbdb903`）后，20 个 Actions 中 19 个成功，`Remote Conversion Runtime` 的 `real-chrome` 失败。准确故障为 RKNN INT8 用户选择精度后，`#conv428Calibration` 虽由原业务控制解除 `hidden`，却位于默认关闭的 `.conversion560-advanced` `<details>` 内，浏览器真实不可见。进一步源码复核确认 ONNX Opset、TensorRT 目标环境与算能预处理入口同受影响；不能把失败判作纯测试夹具问题。

本轮将 `#conv428OnnxFields`、`#conv428SophonFields`、`#conv428TensorRtFields`、`#conv428Calibration` 恢复在主配置区，由原业务逻辑决定显示与否；算能 `#conv428Preprocess` 仍位于原厂商区内部可单层展开；仅非必填 CSC 设备适配置于「高级设置」。保持现有精度、Chip、资源检测、INT8 校准冻结与转换任务提交 Owner 不变。Chrome 原有 ONNX/TensorRT/Sophon 检查增加“主区不在高级折叠中”断言，RKNN INT8 断言同理；Node 增加对应防退化契约。

隔离验收：前端 `npm test` **1522/1522** 通过、JS `node --check`、`git diff --check` 通过。当前执行环境无已安装 Playwright Chromium 浏览器，**不能声明本地真实 Chrome 通过**；以本轮新提交触发的 `Remote Conversion Runtime` 等 GitHub Actions 为最终证据。PT/ONNX/BMODEL 真实模型推理、算能 SDK 及生产部署仍未做。

## 42.24.520｜返回历史与旧 Chrome 契约修正（2026-11-04）

`42.24.519`（远端 `52148e8a6d3f27c9f9504da4bbf177873c52d358`）Remote Conversion 的原三条真实 Chrome「资源 / RKNN INT8 / 算能矩形」**3/3 通过**，证明配置显隐问题已消除；其随后 `deployment-progress-performance.spec.mjs` 发生 60 秒超时，原因是旧用例假设「取消新建转换」后，旧历史弹窗仍在下层。此假设与已确定的“关闭历史再打开独立配置编辑器”交互契约冲突，不能以增加套娃弹窗通过测试。

新验收改走实际 `返回转换记录` 操作，先等待创建弹窗关闭，再恢复历史弹窗；历史缓存 / 每次资源读取的请求次数现在准确断言为首次历史两次、返回历史第三次、两次资源读取，保留 `forcedHistoryGets=0` 及无额外请求的验证。`取消` 单独验证关闭当前弹窗且不残留历史层。为避免异步竞态，返回按钮处理顺序使用 `await closeModal()` 后才执行已有 `openVersionConvert428()`。此轮只影响展示与测试，不触碰模型、GT、转换任务真实状态和 API。真实 Chrome 新一轮 CI 待跑，未通过前禁止声明全绿。
