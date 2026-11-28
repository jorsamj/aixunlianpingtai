# W7-B 真实双 GPU UAT 清单（未执行）

> 状态：`REAL_GPU_UAT_NOT_VERIFIED`。本文件仅是后续授权测试的操作清单，不代表任何真实 GPU 结果。
> 禁止在 A800/4070 生产或演示节点直接执行；必须使用另行授权的隔离双 GPU 节点。

## 1. 前置证据

- 节点仅运行一个 Node Agent 进程（state 目录 FileLock 已持有）。
- 中央该节点显式具备 `training` + `execution-slots:2`，Agent 同样上报。
- 两张 GPU 的 UUID、型号、总显存、空闲显存、驱动/CUDA 版本记录。
- Agent 本地容量确认 `max_slots=2`，生产默认仍为 1。
- 记录节点 `node_id`、Agent build_id、GPU 探测时间。

## 2. 设备映射核对

对 A/B 分别记录：

| 项目 | A | B |
|---|---|---|
| 中央 Hold GPU UUID | | |
| `nvidia-smi -L` UUID | | |
| 物理 index | | |
| 子进程 `CUDA_VISIBLE_DEVICES` | UUID，不是宿主 index | UUID，不是宿主 index |
| 训练内逻辑设备 | `cuda:0` | `cuda:0` |
| train_worker 设备证据 | | |
| 资源解析子进程可见设备 | 仅自身 UUID | 仅自身 UUID |
| Torch/Ultralytics 导入时可见设备 | 仅自身 UUID | 仅自身 UUID |

要求：

- `CUDA_VISIBLE_DEVICES` 只设置在训练/资源解析子进程环境，不修改 Agent 全局环境。
- UUID 无法匹配本地真实设备时 fail-closed，不自动改用其他 GPU。
- 禁止出现 A/B 同时指向同一物理 UUID。

## 3. 并发与排队

1. 提交 A、B、C 三个训练任务，A/B 各 1 卡，C 等待。
2. 记录 A/B 中央 task_id、assignment generation、execution attempt、PID、GPU UUID。
3. 证明 A/B 训练进程 PID 不同，PID 存活时间区间重叠。
4. 记录两个训练日志/报告/模型输出路径，验证无交叉。
5. 确认 C 在两个 Hold 释放前保持 QUEUED。
6. 记录每张 GPU 的 `nvidia-smi` 显存与利用率时间序列。

## 4. 取消与接替

1. 中央取消 A，B 继续训练。
2. A 的 Runner 停止进程及后代，提交 Stop Proof。
3. 中央 A 进入 CANCELLED，Hold RELEASED。
4. B 的 PID、心跳、GPU UUID、训练进度不中断。
5. C 仅在 A Hold RELEASED 后获得分配并启动。
6. 记录 C 实际 GPU UUID 等于 A 释放的 UUID。
7. C 不得与 B 使用同一 GPU UUID。

## 5. 异常与恢复

- Node Agent 进程 SIGKILL，训练子进程仍存活：重启后必须通过持久 ProcessIdentity 找到并安全停止，未证明前 GPU 保持隔离。
- 训练子进程 SIGKILL：Runner 必须记录失败、确认后代停止、提交对应 proof_type，再 finish。
- 中央 Stop Proof 已持久但 HTTP 响应丢失：不得重复启动训练进程；同身份重提幂等。
- 进程已退出但后代状态未知：保持 RECOVERY_BLOCKED，不释放 GPU。
- Agent 重启后旧意图已终态且 Hold RELEASED：可安全清理意图。
- A 异常时 B 的进程、GPU、HTTP Session 和控制面心跳不受影响。

## 6. 资源释放与残留

- 任务结束后检查两张 GPU 无该任务残留进程和显存。
- 检查工作目录/模型/报告归属。
- 检查 `execution_resource_holds` 最终 state=RELEASED 且 proof_sha256/proof_type 正确。
- 检查 `dual-slot-intents.json` 无未对账的旧执行。
- 同一 GPU UUID 永不被两个并发任务 Hold。

## 7. 单槽回退

- 移除 `execution-slots:2` 授权并重启 Agent。
- 验证 effective_slots=1、不再领取第二槽任务。
- 验证 TRAINING、MODEL_CONVERSION、MATERIAL_IMPORT、MATERIAL_BATCH 原路径。
- 恢复默认单槽后不得残留双槽 Slot 或 GPU Hold。

## 8. 保护边界

- 当前 CPU 阶段信任边界是认证 Agent + ProcessController 停止核验。
- 真实 GPU UAT 必须单独验证 Supervisor/cgroup 是否提供独立进程组后退见证。
- 未完成本清单前保持 `PRODUCTION_DUAL_SLOT_DISABLED`。
