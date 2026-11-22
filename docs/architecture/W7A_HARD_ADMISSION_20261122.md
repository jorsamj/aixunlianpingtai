# W7-A 中央硬资源准入试点（2026-11-22）

> 只改中央分配准入；未启用 Node Agent 多任务并发，未接触生产 GPU，未新增 Scheduler/TaskRepository/GPU 事实库。

## 1. 现有缺口

| 项 | 现状 |
|---|---|
| 槽位 | `_has_idle_agent_slot()` / `_node_active_work_count()` 以“有活动任务”判断，未按 CPU/RAM/GPU 预算 |
| GPU 身份 | `_selected_gpu()` 以 `cuda:N` 为主，跨节点同索引可能混淆；UUID 未作为主身份 |
| GPU 预留 | `_assigned_gpu_ids()` 只收集 `cuda:N`，未收集 UUID |
| 资源需求 | 训练 payload 没有统一的 CPU/RAM/scratch/显存/GPU 需求合同 |
| 未知占用 | 旧活动 assignment 没有冻结需求，新任务无法证明剩余容量 |
| 排队原因 | 无持久等待原因，只有 QUEUED |

## 2. 已实现

文件：`platform_core/task_node_assignments.py`

新增：

- `_task_resource_requirements()`：opt-in `payload.resource_requirements` 解析/验证；
- `_active_assignment_configs()`：读 ASSIGNED/CLAIMED + RUNNING/CANCEL_REQUESTED 的最新 resolved config；
- `_hard_admission()`：在分配事务内计算 CPU/RAM/scratch/GPU 预算并返回原因；
- `_gpu_identity` 语义：UUID 优先，`cuda:N` 只是节点内设备索引；
- `_assigned_gpu_ids()` 同时记录 UUID 与 id；
- `CentralTaskAllocator._assign_next_candidates()` 在 `BEGIN IMMEDIATE` 内先硬准入再评分；
- `resolved_execution_config` 记录 `resource_requirements` 和 `hard_admission=verified|legacy`。

### 2.1 需求合同

```json
{
  "resource_requirements": {
    "gpu_count": 1,
    "gpu_uuids": ["GPU-..."],
    "min_gpu_memory_bytes": 8589934592,
    "cpu_cores": 2,
    "ram_bytes": 4294967296,
    "scratch_bytes": 1073741824,
    "storage_source_ids": ["nas-a"]
  }
}
```

- 缺失 `resource_requirements` → 旧任务兼容，原分配路径；
- 存在但格式非法 → 不分配，任务保持 QUEUED；
- `gpu_count > 1` 当前拒绝 `MULTI_GPU_REQUIREMENT_UNSUPPORTED`（W7-B 才启用）；
- 显存不足、GPU 利用率达到现有训练候选阈值、CPU/RAM/scratch 不足、存储源未上报 → 拒绝；
- `storage_source_ids` 要求节点 `resources.storage.source_ids` 明确上报，否则 fail-closed；
- 旧活动任务无冻结需求 → 新 opt-in 任务返回 `ACTIVE_RESOURCE_UNKNOWN`，不超卖。

### 2.2 拒绝原因

`CPU_INSUFFICIENT`、`RAM_INSUFFICIENT`、`SCRATCH_INSUFFICIENT`、`GPU_INSUFFICIENT`、
`DUPLICATE_GPU_IDENTITY`、`MULTI_GPU_REQUIREMENT_UNSUPPORTED`、
`STORAGE_REACHABILITY_UNVERIFIED`、`ACTIVE_RESOURCE_UNKNOWN`、`RESOURCE_REPORT_UNKNOWN`。

任务保持 QUEUED；不创建 assignment、不占 GPU、不产生执行租约。

### 2.3 事务与并发

- 需求解析在分配事务外读取 payload，但**最终准入、资源读取、assignment 插入都在同一 `BEGIN IMMEDIATE` 内**；
- `_hard_admission` 读取最新 `task_node_assignments`/`tasks`，包含 ASSIGNED/CLAIMED/RUNNING/CANCEL_REQUESTED；
- 并发两个 Allocator 串行化，只允许一个 assignment 使用同一 GPU；
- 旧 generation/lease 不因新试点改变，Agent claim/start 的原 fencing 未改；
- release 后才允许复用 GPU；过期但 active 的 assignment 仍被计入，不立即重派。

## 3. 隔离测试

`tests/unit/test_w7a_hard_admission.py`：**12 passed**。

覆盖：

- 单 GPU 空闲 + CPU/RAM/scratch 预算准入；
- 显存不足；
- 显存充足但利用率 95% 拒绝；
- `gpu_count=2` 与未知字段需求保持 QUEUED，不产生 assignment；
- 两 GPU 独立 UUID，指定 GPU-1 后另一任务只能取 GPU-0；
- 不同节点相同 `cuda:0` 由 UUID 区分；
- 重复 UUID fail-closed；
- 旧活动 assignment 无需求 → 新 opt-in 拒绝，旧任务仍可分配；
- ASSIGNED/release 复用、过期 active lease 不重派；
- CPU/RAM/scratch 单独不足；
- 存储源未上报拒绝；
- 并发两个 Allocator 只产生 1 个 assignment；
- 心跳过期不分配。

现有 `tests/unit/test_task_node_assignments.py`：**73 passed**（未启用 hard admission 的旧任务路径保持）。

## 4. 边界

- **W7-A 只证明分配条件与持久状态**，不等于两个真实 GPU 训练进程已并行；
- NodeAgentExecutorLoop 仍是单任务；未改多槽；
- `gpu_count > 1` 拒绝；
- CPU 预算按逻辑核心减 active 冻结需求，不检测宿主机平台外进程；
- RAM/scratch 使用节点 heartbeat 的 available/free 减去 active 冻结需求；
- GPU 外部进程列表未作为逐 UUID 的硬占用，只使用现有 free/util 阈值；
- 等待原因尚未持久化到 UI/任务表，仅函数返回；
- W6 NAS node_id 认证/超时未接入本准入；`storage_source_ids` 只检查节点是否上报，不等于 W6 实测。

## 5. W7-B 前置

- Agent 执行槽（独立 Runner/workspace/UUID→CUDA_VISIBLE_DEVICES）；
- 真实双 GPU 节点并行两任务、第三任务排队；
- 外部进程/显存真实占用；
- 任务取消/租约过期/孤儿进程；
- Supervisor/fencing 端到端；
- 真实 Linux/NVIDIA 验收前不启用生产多槽。
