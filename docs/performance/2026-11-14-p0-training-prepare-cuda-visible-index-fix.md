# P0｜训练准备 GPU 0 / CUDA 可见设备索引精准修复

- 日期：2026-11-14
- 唯一提交分支：`feature/external-algorithm-publishing`
- 审计基线：`5791e5c86ed10e0bb23e887ab185a73ad04f6b06`（上一轮准确 Actions 37/37 success，包含 Chrome 失败分片重跑成功）
- 范围：`platform_core/remote_training_tasks.py:TrainingPrepareHandler._resolve_local_resources` 和对应 Python 回归；**不改** `task_worker.py`、GPU 调度租约、TRAINING_PREPARE 数据/GT、训练资源决议算法或生产服务器
- 状态：修复代码提交 `bed687dde99f49b42618f03362d65118c1269d28`；该准确 SHA 的 GitHub Actions **22/22 工作流完成且成功**（0 失败，0 未完成）。Linux/Windows 训练准备合同、两组 Remote Training Runtime、Ultralytics DataLoader、前端 Chrome 全部成功；**不代表生产部署或真实 GPU/GT 现场验收**

## 已确认的两条确定性 Bug

1. **固定 GPU 0 误判缺少遥测**：旧分支使用 `int(row.get("logical_cuda_index") or row.get("physical_index") or -1)` 选择显式 `cuda:N`。NVML/nvidia-smi 原始记录常只有 `physical_index=0`，Python 的 `0 or -1` 结果是 `-1`，合法 GPU0 被错误判为不可用，触发 `RESOURCE_GPU_TELEMETRY_UNAVAILABLE`。
2. **自动设备的保守决议选错 GPU**：非延迟资源路径将采样列表中空闲显存最少的 GPU 作为保守基准，但通过 `selected_gpu.get('logical_cuda_index') or 0` 解析 CUDA 索引。正常 NVML/nvidia-smi 记录缺少该字段时，无论选中物理 1 还是其他卡，都误映射为 `cuda:0`，资源计算与采样 GPU UUID 不对应。

此外，旧路径没有排除当前 `CUDA_VISIBLE_DEVICES` 掩码之外的 GPU，可能将不可见卡误纳入资源候选。此处一并按**已有调度器身份合同**处理，未添加第二套映射。

## 精准修改

`TrainingPrepareHandler._resolve_local_resources` 直接复用 `platform_core.gpu_resources._cuda_index(row)`：

- 显式保留索引 `0`；优先采样内已有 `logical_cuda_index`，其余按已有物理编号与 `CUDA_VISIBLE_DEVICES`（数字列表或 GPU UUID）映射到真实可见 CUDA ordinal；
- 只有遥测可用、且当前训练进程可见的 GPU 才进入资源候选；
- 自动设备的保守 GPU 选择与最终 `resolution_device` 保持同一 GPU 身份；指定 `cuda:N` 则严格匹配映射后的 ordinal；
- 不可见或无可信遥测继续 fail-closed，不增加 CPU 退化回退、不改 GPU 预约策略、不宽松处理设备 UUID。

## 有界回归矩阵

在现有 `tests/unit/test_local_auto_resource_admission.py` 内新增真实 `_resolve_local_resources` 调用（模拟 NVML 数值、隔离 SQLite/Artifacts，拦截资源决议器；**不执行 GPU 训练**），覆盖：

| 场景 | 期望 |
|---|---|
| 单卡原始 `physical_index=0`，指定 `cuda:0` | GPU-0 正常解析 |
| 双卡无掩码，指定 `cuda:1` | GPU-1 正常解析 |
| 双卡非延迟 `device=auto`，GPU-1 空闲显存较小 | 按 GPU-1 计算，决议设备 `cuda:1` |
| `CUDA_VISIBLE_DEVICES=1,0` 指定 `cuda:0` | 使用物理 GPU-1 |
| 同一掩码指定 `cuda:1` | 使用物理 GPU-0 |
| `CUDA_VISIBLE_DEVICES=1`、`device=auto` | 只能使用可见 GPU-1，决议 `cuda:0` |
| `CUDA_VISIBLE_DEVICES=GPU-1,GPU-0` | GPU UUID 正确重映射 |
| `CUDA_VISIBLE_DEVICES=1`、显式 `cuda:1` | 拒绝不可见的指定设备 |

所有场景都对照 `resource-context.json` 的 `resolution_device` / `resolution_gpu_uuid`；同时保留原有“自动设备 + AUTO 策略”延迟资源决议的回归。

## 后续边界与证据

- **单独后续专项**：固定 GPU + AUTO 策略当前仍在准备阶段而不是最终调度分配后做资源计算；虽然 Worker 启动前有资源漂移保护，但这不完全满足“排队后按真实分配资源重新决议”。不能在本次索引 Bug 修复中直接改 GPU 预约/调度。
- **CI**：本文件与代码、测试一次性原子提交后，需查询准确 SHA 的 GitHub Actions，失败时先读日志而不宣称通过。
- **生产**：未访问/重启/部署 A800、4070；未修改训练任务、GT、数据库或真实模型；真实 GPU、队列/Agent 场景与 20k 正式 GT 端到端仍为待验收。

## 代码提交准确 CI 结案（2026-11-14）

- **代码与回归提交**：[`bed687dde99f49b42618f03362d65118c1269d28`](https://github.com/jorsamj/aixunlianpingtai/commit/bed687dde99f49b42618f03362d65118c1269d28)。
- 同一代码 SHA 的 GitHub Actions：**22/22 completed/success，0 failed，0 pending**，并非其他历史提交的 CI。实际前端 Chrome 三分片全部成功。
- [Remote Training Runtime（第一组）](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43471880154) 和 [Remote Training Runtime（第二组）](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43471893806)：Windows / Ubuntu 准备合同、API、Ultralytics Loader 成功；Ubuntu 新增回归所在测试批次 **123 passed**。
- [Frontend Runtime Stabilization](https://github.com/jorsamj/aixunlianpingtai/actions/runs/43471880097)：4/4 Job 成功。
- 本轮按“**源码修复 + Python 回归 + 准确 CI 完成**”关闭；**A800/4070 实际版本、真实 GPU 排队与 AUTO 资源重新决议、正式 GT/20k 端到端验证**仍未验收。
- 本结案补充是单独的**文档提交**；文档提交自身的准确 SHA/CI 需要另行核验，不能冒充上述代码 CI。
