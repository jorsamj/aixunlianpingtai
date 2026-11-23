# W7-B 节点级恢复协调与 Runner 责任边界（2026-11-23）

## 1. 已实现代码

### 1.1 `platform_core/node_agent_recovery.py`

`NodeRecoveryCoordinator`：

- 单一节点级恢复扫描入口，`prepare()` 只执行一次；
- `register_owner(task_id,generation)` / `unregister_owner` 维护当前活动槽位所有权；
- 扫描现有 `list_process_identities()` 与 `list_unverified_process_launch_intents()`；
- 被活动槽位拥有的记录跳过，不会被另一个 Runner 终止；
- 未拥有记录才尝试 `ProcessController.terminate_tree`，并仅在可信清理后删除持久身份；
- 清理失败保留持久记录并返回 fail-closed 原因；
- Windows 仍因缺少 Job Object 后代证明而拒绝清理；
- 不新增任务状态库/代数字段。

### 1.2 `AgentTrainingRunner` 责任边界

- 新增可选 `recovery_coordinator`；
- 有协调者时，Runner **不再**独立扫描/终止共享 workdir 中所有持久进程；
- 只消费协调者 verdict；无协调者时保留原单槽恢复逻辑，兼容既有行为；
- Runner 自身仍持有 lease/ProcessIdentity/workspace/stop signal，不共享可变执行状态；
- `node_agent.py` 的 TRAINING 与 MODEL_CONVERSION Runner 共享同一节点级 `NodeRecoveryCoordinator`；转换 Runner 不再独立扫描共享 workdir；
- 节点 state 目录使用跨进程独占 FileLock，第二个 Agent 进程启动会被拒绝；
- Runner `run()` 开始前注册 owner，正常完成后注销；异常/fence 不注销，保留给节点恢复；
- 同一 `(task_id,generation)` 重复注册被拒绝。

### 1.3 隔离测试

`tests/unit/test_node_agent_recovery.py`：

- 活动槽位 A 的记录不被清理；
- 未拥有 B 的记录被清理；
- 第二次 `prepare()` 不重复扫描；
- 清理失败保留身份并 fail-closed；
- unverified launch intent 阻断；
- 重复 owner 声明拒绝；
- POSIX 真实子进程：owner 注册时不误杀，未拥有时实际 terminate（Windows 跳过，Windows 仍 fail-closed）。

`tests/unit/test_node_agent_training_runtime.py`：原单槽恢复/训练路径保持。
`tests/unit/test_node_agent_conversion_runtime.py`：转换单槽路径保持。

## 2. 未完成/阻塞

- `NodeAgentExecutorLoop` 仍是单任务执行；未启用两槽。
- 未构造/接线 coordinator 到正式 `node_agent.py` 的 Runner 实例；当前是可选边界，生产仍走原单槽恢复。
- 没有真实双 GPU 子进程、CUDA_VISIBLE_DEVICES、双槽取消/恢复 E2E。
- 中央 `effective_slots` 仍默认 1；未实现双槽授权与 Agent 实际容量协商。
- 未启用生产多槽。

因此状态：

- 恢复协调器与 Runner 边界：`CODE_COMPLETE` + `TARGETED_TEST_PASS`
- 双槽执行：**`BLOCKED_BY_SAFETY`**
- 真实 GPU：`REAL_GPU_UAT_NOT_VERIFIED`

## 3. 继续实施前置

1. 在 `node_agent.py` 创建唯一 coordinator/ProcessController，注入所有 Runner；
2. Runner 启动/结束注册/注销 owner；
3. 双槽 Runner 独立 workdir/进程身份；
4. GPU UUID→CUDA_VISIBLE_DEVICES 映射；
5. 中央授权 + Agent 验证容量；
6. 真实 Linux/NVIDIA 验收前保持单槽。
