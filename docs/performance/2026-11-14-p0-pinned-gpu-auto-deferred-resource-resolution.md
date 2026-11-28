# P0：固定 GPU + 自动配置，训练资源执行时决议

- 日期：2026-11-14；仓库：`jorsamj/aixunlianpingtai`
- 唯一开发分支：`feature/external-algorithm-publishing`
- 审计基线：`ba051cb24f39a2f153d12a0b1b3a3cfa988e64fe`，版本 `42.24.592`
- 状态：**源码与定向回归已提交；准确代码 SHA 的 GitHub CI 待核**。不代表 A800 / 4070 生产验收。

## 根因及场景

`TRAINING_PREPARE` 之前仅在 `resource_strategy=auto + device=auto` 时生成最低显存准入合同并延后资源决议。选择自动配置、指定 `cuda:0` 或 `cuda:1`，则在准备阶段读取当前 GPU/CPU/RAM 并冻结 Batch、Workers、Cache。指定 GPU 暂忙时，可能在训练正式排队之前 FAILED；资源变动后也无法在实际训练节点上重新计算。生产使用的节点级 GPU 预约器 `NodeScopedGPUResourceManager` 同样只将 `device=auto` 当作延期资源合同，训练 Handler 拒绝固定 GPU 的延期合同。

## 修复（保留既有机制，不重构）

1. `platform_core/remote_training_tasks.py`：`resource_strategy=auto` 且 GPU 自动或显式 CUDA 都生成 `gpu_memory_floor_bytes` 和 `resource_resolution_deferred`；按指定 CUDA 过滤诊断候选。当前 GPU 忙碌或缺少遥测不再导致准备阶段提前失败；CPU 保持原路径。
2. `platform_core/gpu_reservations_v2.py`：真实节点级 GPU 准入支持指定 CUDA 的延期 AUTO；继续检查指定 Worker 的 CUDA 可见索引、节点级真实 GPU、最新遥测、显存下限、独占性与租约；不足时仅保持 `QUEUED/resource_waiting`，不切换至其他 GPU。
3. `platform_core/gpu_resources.py`：旧版 GPU 预约器采用相同延期判定，防止双轨行为。
4. `platform_core/training_tasks.py`：执行 Worker 在取得有效租约/设备后，支持 `AUTO+cuda:N` 使用原有 `_freeze_deferred_resource_contract` 计算 Batch/Workers/Cache；`AUTO+CPU` 与 `MANUAL+CUDA` 伪延期合同仍拒绝。
5. 不改 GT、素材任务、训练产物、GPU 租约身份校验、启动前显存/RAM 漂移检查与手动配置；训练中不改 Batch。

## 回归测试矩阵

- `tests/unit/test_local_auto_resource_admission.py`：固定 GPU0、GPU1、指定 GPU 无遥测时准备阶段不决议完整资源；候选按指定 GPU 可见索引过滤；训练 Handler 放行 GPU AUTO、拒绝 CPU / 手动伪延期。
- `tests/unit/test_gpu_node_scoped_reservations.py`：指定 GPU0 或 GPU1 空闲只有 1GiB、其他卡仍空闲时必须等待、不得预留任何卡；同一指定卡恢复 20GiB 后允许同一排队任务取得正确 GPU 身份和内存预约。
- 原有自动 GPU、手动模式、远程 Agent 和内存漂移保护测试不改既有断言。

使用隔离 SQLite / 伪 GPU 遥测，不能等同真实 20k/30k GT、A800/双4070 排队和跨节点现场验收。本轮不做生产部署/重启/训练中断。

## 待核与结案界限

- 只有准确代码 SHA 的 Linux/Windows 合同、Remote Training Runtime、全仓 GitHub Actions 全部成功后，才可称**代码级验收完成**。
- 资源非常紧张时允许排队；真实执行时仍不能通过最低 Batch=1 或启动前安全校验的任务可显式失败，并保留可诊断的错误原因；本次不增加无限重试/跨节点迁移。
