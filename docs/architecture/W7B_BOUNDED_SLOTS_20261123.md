# W7-B 有界执行槽 CPU 协议基础（2026-11-23）

## 代码

`platform_core/node_agent_execution_slots.py`

- `BoundedExecutionSlots(max_slots=1|2)`；
- 默认调用方可用 1，显式试点最多 2；
- 每个槽位独立 `task_id`、`generation`、lease 引用、stop_event、outcome、error、线程；
- 同 `(task_id,generation)` 重复提交拒绝；
- 存活槽满时第三任务拒绝；
- `cancel` 只设置对应槽位 stop_event；
- `shutdown` 通知全部槽位并等待。

## 测试

`tests/unit/test_node_agent_execution_slots.py`（本地真实 CPU 子进程）：

- 两个 `python -c sleep` 真实进程重叠执行；
- 第三任务 `SlotCapacityError`；
- 取消 A 只终止 A，B 进程仍存活；
- 最后双槽清理，进程均退出。

## 边界

这不是生产双槽开关，也未接入中央 `effective_slots`、GPU UUID、CUDA_VISIBLE_DEVICES、Agent TLS/HTTP 领取和终态 fencing。

当前状态：

- 槽位并发协议：`CODE_COMPLETE` + `TARGETED_TEST_PASS`（本地 CPU）
- 中央授权/Agent 执行闭环：**未完成**
- 生产默认：单槽
- 真实 GPU：`REAL_GPU_UAT_NOT_VERIFIED`
