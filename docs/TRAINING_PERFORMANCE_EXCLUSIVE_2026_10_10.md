## 2026-10-10｜四模式训练创建 CI 修复（42.24.345，待全量复验）

- 实际核对基线 `2e01bde1ee362060c23a82be1fad2c5e44341bf3` / `42.24.344` 的 6 个失败 Workflow、对应失败 Job 的原始日志；Remote Material Import 两次触发为同一缓存键测试根因。
- Training Create First Open：训练弹窗 Browser 测试使用已删除的全局高级展开按钮和旧弹窗标题；改为现有“创建训练任务”及数据划分原生 disclosure，训练素材/固定 Benchmark/标签规则仍继续检查。
- Frontend Runtime Stabilization：对应旧标题、旧高级配置与创建提交文案、TrainingDraft 写入顺序的断言漂移，已按可见真 UI 更新；导航与标签的真实操作仍须 Chrome 复验。
- Training Task Visibility / Algorithm SQL Store：同一 `four modes freeze only training semantics` 前端测试揭露生产链缺陷：`trainingDraftToRequest` 通过 `createTrainingDraft` 把历史 `gpuPolicy:auto` 覆盖掉 builder 的 `exclusive`；现在四模式规范化统一强制独占。保留中央 TaskScheduler、GPU Reservation 和 Worker 运行前真实资源决议。
- Remote Material Import 两次：原测试把 `app.js?v=42.25.333` 当成永远不变的字面缓存版本；现在验证版本不回退到旧修复点，同时入口缓存版本实际升级至 `42.25.345`。
- 自定义模式取消“兼容自动隔离”选项；普通模式不显示 Batch/Workers 专业设置；标签搜索、勾选、正式 GT、首次母模型、续训有效版本继承、60/20/20 比例以及单一 TrainingSubmit Owner 均保留。
- 本次只修改对应最小生产文件、前端测试、Browser 测试和现有文档，不另建 Owner、不删减安全测试；最新精确 HEAD 的全量 Linux/Windows/Chrome CI 仍待核验，真实 NVIDIA 同卡阻塞/双卡并发、OSS、Agent、10k/20k 素材 UAT 仍需现场执行。**不合并 main、tag、release、部署生产。**

# 2026-10-10｜训练资源默认性能与 GPU 独占修复记录

> 仓库 `jorsamj/aixunlianpingtai`；长期分支 `feature/external-algorithm-publishing`。
> 本轮版本 `42.24.343`。状态：代码已提交，GitHub Actions 当前 HEAD 和真实 NVIDIA GPU UAT **尚须验收**。不涉及 main、tag、release 或生产部署。

## 本轮用户确认的规则

- GPU **单张物理卡独占一个训练任务**；不因利用率低而在同一物理卡追加另一训练任务。多卡节点可以按不同 GPU UUID 承载独立训练；当前不开放共享模式。
- 首训默认 **150 Epoch**；有有效上一版本的续训默认 **80 Epoch**；显式用户 Epoch 永远优先。正式训练 Auto + Performance；YOLO 图片大小仍为 640，默认自动精度（CUDA FP16）；保留手动参数。
- 智能早停 **显式开关，默认关闭**；启用后使用 Patience（建议初始 40），现有阶段达标质量门禁独立保留。必须保证本地与远程传输/执行合同一致。
- Batch/Workers/Cache 由唯一 canonical resolver `platform_core.training_metrics.resolve_resources` 在最终设备确定后冻结；大数据集尽量发挥显存和 CPU 资源；小于 512 张的训练集，自动 Batch 不超过 `ceil(train_images/4)`，在素材数量允许时至少保留四次参数更新/轮，不把 11 张图合成一轮一个更新。Workers 由实际 CPU 预算/内存预算/loader 批次数共同限制，RAM 至少保留 4GiB、每个 DataLoader Worker 预算 2GiB。
- 已有 `TrainingMetrics` 负责观测 requested/resolved/runtime Batch、Workers、Cache 与 GPU 利用率 / images_per_second / 诊断；不增加第二套监控 owner，不允许 Trainer 启动后悄悄改 Batch。

## 代码修改（本轮）

1. `app.py`：YOLO11n/s/m 目录轮次 150、API 默认轮次 150，Performance/Exclusive 默认及推荐；新增可选早停请求字段。
2. `static/modules/training-draft.js`、`static/modules/training-submit.js`、`static/app.js`：前后端训练参数统一；续训 80；训练弹窗的 Epoch、GPU 和 Performance 默认；高级设置可启用早停并编辑 Patience；手动输入值优先。
3. `platform_core/gpu_resources.py`、`platform_core/gpu_reservations_v2.py`：本地和 Node Scoped GPU 准入禁止单卡并发（含历史 auto / 配置覆盖）；默认 max_concurrent=1。
4. `platform_core/task_node_assignments.py`：中央 allocator 禁止在 Agent 的任务进入 RUNNING 后复用其 GPU；此前 assignment 释放后不能仅看 ASSIGNED/CLAIMED。
5. `platform_core/training_metrics.py`：Auto Batch 的小训练集保护，以及运行时统一的 CPU/RAM DataLoader Workers 预算；手动参数仍 fail closed；Cache 使用原有机制。
6. `platform_core/training_tasks.py`、`platform_core/remote_training_tasks.py`、`platform_core/node_agent_training_runtime.py`、`train_worker.py`：显式早停字段贯穿任务、可移植合同和实际 Ultralytics worker。
7. 重点回归测试：`tests/frontend/training-draft.test.mjs`、`tests/frontend/training-submit.test.mjs`、`tests/unit/test_training_scheduler_target.py`、`tests/unit/test_training_resource_contract.py`、`tests/unit/test_training_early_stopping_reason.py`、`tests/unit/test_task_node_assignments.py`、`tests/unit/test_gpu_node_scoped_reservations.py`。

## 剩余验收，不可宣称已完成

- GitHub Actions 精确最新 HEAD 通过；`queued` / `in_progress` 不等于通过。
- Windows CPU 兼容、本地 NVIDIA、远程 Agent、双 GPU 并行与同卡拒绝，需要针对真实硬件验收。
- 对 11 / 80 / 500 / 1000 / 10000 张图片分别验证请求 Batch、决议 Batch、实际 runtime_batch、实际 Workers、单轮批次数、OOM/缓存退化以及 mAP 收敛。
- 测量 GPU 5 秒采样、CPU/iowait、显存峰值、images/s、每轮耗时；`Performance` 的 82% 是**可用显存规划比例，不是 GPU 利用率目标**；不得声称 100% 算力负载或最佳真实吞吐已经验证。
- `train_worker_safe.py` 的历史入口默认 Worker=2 限制不属于 canonical CLI 资源决议执行路径；本轮只在 canonical resolver 合并 RAM 安全预算，后续应核实历史包装入口用途，避免二次 Owner。
- 保留长期分支及可回滚性；未经用户明确同意不部署生产。
