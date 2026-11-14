# P0-06B｜正样本自动增强到训练包一致性：回归与证据

- 日期：2026-11-14
- 仓库：`jorsamj/aixunlianpingtai`
- 唯一分支：`feature/external-algorithm-publishing`
- 审计基线：`99d9bd9e387d49e9e9149184fc72bdbf76e4818c`（其准确 SHA **22/22 Actions completed/success**）
- 状态：本次新回归已提交，**本次新代码 SHA 的 CI 仍需单独核验**；真实生产 A800/4070 与 20k～30k 正式 GT 现场尚未验收。
- 变更边界：**只扩展现有 Python 训练输入回归测试与文档，不改业务算法、模型、资源调度、GT、数据结构或生产任务**。

## 一、已核实的代码合同

1. `training_tasks.materialize_portable_dataset` 根据冻结 Snapshot 的 `train/validation/test` ID 创建目录、YOLO 标签及 portable `manifest.json`；先写原始分组，再调用 `training_robustness.augment_bundle`，把衍生图只追加到 `splits['train']`。
2. 已实现的跨设备增强是 RGB/YUV 解码标准/范围差异的 **颜色增强（CSC）**，不是多分辨率/不同视频输入裁剪或补边；当前像素几何不变，因此派生图复制训练原图的 YOLO TXT 标签，保留 `derived_from_image_id`、`source_root_id`、`source_group_id`、变换参数、SHA256。
3. `dataset/data.yaml` 中 `train: images/train`、`val: images/validation`，没有独立 Test 的训练入口；独立 Test 真值存放在 `evaluation/ground_truth/test` 并由独立评测使用。
4. `verify_portable_dataset` 逐个核验图片与标签哈希，`resolve_remote_training_bundle` 复核可搬迁训练包。
5. 既有 20k 冻结引用单元测试 `test_streaming_frozen_20k_ids_keep_digest_retry_and_worker_identity` 核对 count、SHA256、幂等重放、Worker 引用 ID 一致；浏览器 20k/30k 流程使用**模拟的冻结后端响应**验证前端不下载全量 ID。**不能据此声称真实 20k/30k 图片都进入了训练进程**。

## 二、本次新增正样本完整回归

`tests/unit/test_training_robustness.py::test_positive_multiclass_train_only_augmentation_reaches_verified_bundle` 用独立临时目录的 4 张真实 JPEG 构建一套标注数据：

| 输入 | person | smoke | 训练角色 |
|---|---|---|---|
| person-train | 1 个有框正样本 | 0 | Train |
| smoke-train | 0 | 1 个有框正样本 | Train |
| person-val | 1 个有框正样本 | 0 | Validation |
| smoke-test | 0 | 1 个有框正样本 | Test |

固定 `copies=2`、选择全部两张 Train，预期 **2 Train 原图 + 4 Train 派生图 + 1 Validation + 1 Test = 8 个可验证图片**。

测试在真实 Python `materialize_portable_dataset` 中执行，验证：

- 训练及两个保留分组的实际文件数、无衍生跨组；Train 每张增强 PNG 的尺寸与像素确实改变；
- 多类别 `person=0`、`smoke=1` 的 YOLO 文本坐标精确核对，派生标签逐字节等于对应原始训练标签，`label_sha256` 一致；
- 派生源 ID、源组、原始训练图哈希、`robustness_summary` 全部正确；
- `data.yaml` 只引用 Train / Validation，**不暴露 Test**；
- `verify_portable_dataset` 与 `resolve_remote_training_bundle` 校验 8 个文件，原始上传源字节不被修改；
- 同一 Snapshot 再建包时派生路径、图像和标注哈希完全一致；篡改一个派生标注后，验证器 fail-closed。

本测试**不启动真实 Ultralytics 训练、不要求 GPU**；结论只能证明分组、派生文件和 Worker 可消费的 portable bundle 合同，不宣称实际 epoch 训练已使用这些数据。

## 三、CI 验收与现场待办

- 本测试已包含在现有 `.github/workflows/training-input-integrity.yml` 的 Linux/Windows `Focused CSC and indexed consumption evidence contracts` pytest 命令中；不新增工作流、不做大规模图像压测。
- 提交后查询**新测试提交 SHA** 的实际 Actions；如果失败，针对失败根因单独修复并在同一文档写证据。
- **20k～30k 真实任务只读对账**仍需核对冻结 ref/count/digest → POST 展开 → `input-request-selection.json` → `input-freeze.json` → Snapshot 分组 ID/GT → portable Train 图片/标签与衍生计数 → 实际 Worker 配置和运行记录。只展示聚合计数、摘要及差异，不导出正式图片/GT。
- 不同分辨率、画面裁剪/补边等视频输入规格增强功能暂不归入“已完成”。

## 四、准确代码 SHA 的回归结果与用户决定（2026-11-14）

- **被测代码提交**：`e625ace894badefe9a37ddc18fc3c8d10df81404`；Linux/Windows 的 `Training Input Integrity` 均为 `success`；两端 `Focused CSC and indexed consumption evidence contracts` 均为 **33 passed**，新增 person/smoke 正样本回归被真实执行。
- **本次核查时的全仓状态**：准确代码 SHA 的 GitHub Actions **21/22 success，1 项仍在执行，0 failure**；未结束工作流：`Frontend Runtime Stabilization`。这只是**本次检查时点**，不能把未结束的工作流当作已通过；文档提交本身的 CI 也需按它自己的 SHA 核对。
- **用户决定**：将 **P0-06C 真实 20k～30k 训练任务只读对账延后**。当前不连接 A800/4070、不读取生产任务、不跑训练、不部署、不更改正式 GT。不得因自动化测试通过就把 P0-06C 标成完成。
- 后续若用户明确允许重新启动 P0-06C，先读取实际部署版本、现有任务与只读证据，再按照冻结引用 count/digest → 任务提交 → `input-request-selection.json` → `input-freeze.json` → Snapshot → portable bundle → Worker 真实启动配置与分组清单的顺序核对；只输出聚合计数、匿名摘要和差异原因，不暴露正式素材内容。
- **下一独立专项**：P1 训练素材选择器 200k 规模下的交互与性能**证据审计优先**；范围、现有工具和准入门槛见 [接续计划](./2026-11-14-p0-06c-deferred-p1-picker-performance-next.md)。
