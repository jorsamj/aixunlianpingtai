# 畅联云算法训练平台 — Node Control Plane / Central Assignment

更新时间：2026-09-18  
分支：`feature/external-algorithm-publishing`  
正式版本：`VERSION.txt = 42.24.0`

> 本文记录服务节点控制面与中央任务→节点分配的当前真实边界。接手时仍必须先读取远端最新 HEAD，不能把本文中的 SHA 当作固定 checkout 目标。

## 1. 已关闭：服务节点控制面

已实现真实服务节点 registry + Agent heartbeat，不是页面模拟数据。

核心文件：

- `platform_core/service_nodes.py`
- `platform_core/node_agent_runtime.py`
- `node_agent.py`
- `static/modules/service-node-runtime.js`
- `static/service-node-bootstrap.mjs`
- `static/service-nodes.css`

节点支持：

- 新增 / 编辑 / 删除 / 启用 / 禁用。
- 一次性 Agent Token；数据库只保存 hash。
- Bearer Token heartbeat 鉴权。
- `ONLINE / OFFLINE / DISABLED / NEVER_CONNECTED`。
- allowed / reported / effective capabilities 分离。
- CPU、内存、磁盘、GPU、显存、温度、利用率、Torch、CUDA、Agent 进程资源。
- Worker / durable task 投影。
- Windows / Linux 跨平台 Agent 本机探测。
- `nvidia-smi` 通过 `shell=False` 调用。

用户级节点能力：

`training`、`material-import`、`cleaning`、`annotation`、`video`、`conversion`、`deployment-test`、`model-upload`。

服务节点后端 focused CI 已通过；服务节点 UI 的 frontend + Real Chrome CI 已通过。

## 2. 已关闭：中央 durable task → node assignment

核心文件：

- `platform_core/task_node_assignments.py`
- `platform_core/training_recovery_api.py`
- `task_worker.py`
- `tests/unit/test_task_node_assignments.py`
- `tests/api/test_central_scheduler_api.py`
- `.github/workflows/central-node-assignment.yml`

中央 assignment 是控制面 truth，但**不是第二套 task 状态机**。

表：

`task_node_assignments`

关键约束：

- `(task_id, generation)` 主键。
- 对 `ASSIGNED / CLAIMED` 建 partial unique index，保证一个 task 同时最多一个 active assignment。
- 调度事务使用 `BEGIN IMMEDIATE`。
- schema 初始化发生在调度事务之前，禁止在 `BEGIN IMMEDIATE` 后执行 `executescript()`，避免 SQLite 隐式提交破坏原子性。
- resolved execution config 会持久化 node、capability、device、GPU、build、runtime snapshot。
- TRAINING 优先按可用显存，其次 RAM / CPU，并对节点现有 active assignment 施加高权重负载惩罚。
- MATERIAL_BATCH 根据真实 operation 映射到 cleaning / annotation / material-import。

当前中央调度 API：

- `GET /api/v63/scheduler/assignments`
- `POST /api/v63/scheduler/allocate-next`
- `POST /api/v63/scheduler/assignments/{task_id}/release`

中央 assignment 已经从现有单一 additive runtime-router 集成点挂入，不新增第二个 `app.py` route owner。

## 3. 已关闭：旧 Worker 自抢 fencing

`task_worker.py` 已改为：

`AssignmentAwareFencedTaskRepository`

当 queued task 已存在 active central assignment 时，legacy Worker 的 `claim_next()` 必须拒绝自抢，并保留：

`CENTRAL_NODE_ASSIGNED: waiting for Agent execution on node <node_id>`

assignment 释放后，旧 Worker 可恢复正常 claim。

这保证了迁移期不会出现：

- Central Scheduler 已把任务分给 A 节点；
- 旧 Worker 又从共享 SQLite 把同一任务抢走；

这种双执行竞争。

## 4. CI 验收

Central Node Assignment permanent workflow：

`.github/workflows/central-node-assignment.yml`

验证 run：

`35288111906`

结果：

- API：success
- Ubuntu 24.04 contract：success
- Windows latest contract：success

覆盖：

- 在线 / stale / disabled / capability mismatch 节点选择。
- TRAINING 最优节点和多 GPU 选择。
- execution snapshot 持久化。
- MATERIAL_BATCH capability 映射。
- 并发 `allocate-next` 只产生一个 active assignment。
- assignment claim / lease expiry reclaim。
- release 后 generation + 1。
- central assignment 对 legacy Worker 的永久 fencing。
- schema script 不在 assignment transaction 内执行。
- Scheduler API allocate/list/release。
- `VERSION.txt == 42.24.0`。
- `git diff --check`。

用于读取 PR-triggered Actions 详情的临时草稿 PR 已关闭，未 merge `main`。

## 5. 当前明确不做的假方案

不要让远端 Agent 直接运行现有 `task_worker.py` 去访问控制面的 SQLite / NFS，然后把它称为“多机调度”。

原因：

- SQLite over NFS 不是最终可靠控制面。
- 会把 DB 文件锁、artifact 路径、进程恢复、租约边界扩散到远端节点。
- 中央控制面无法稳定成为唯一任务 truth。

因此远端执行必须通过后续 HTTP Agent executor protocol。

## 6. 下一步唯一主线：HTTP Agent Executor Protocol

下一阶段要把“已分配”真正变成“远端执行”，但仍保持单一 durable task truth。

目标链路：

```text
Task QUEUED
→ CentralTaskAllocator 选择 node
→ Agent 使用 node token 拉取自己 assignment
→ 控制面原子创建真正 execution lease / generation
→ Agent 通过 HTTP 获取执行描述与必要 artifact/object-storage 引用
→ Agent 本机执行对应 handler
→ Agent heartbeat / progress / log / result 回传控制面
→ 控制面更新原 TaskRepository
→ finish / cancel / failure / lease expiry recovery
```

下一阶段必须满足：

1. Agent 不直接访问中央 SQLite。
2. Agent 不依赖共享 NFS 才能 claim task。
3. node token 和 assignment lease token 分离。
4. `QUEUED → RUNNING` 只能在控制面原子发生一次。
5. execution generation / lease fencing 必须沿用现有 TaskRepository 语义，不能新造第二套状态。
6. 进度、日志、取消、失败、完成全部回到中央 truth。
7. 任务结束/异常后必须清理 GPU reservation、进程、临时文件、assignment lease。
8. Windows Agent 与 NVIDIA Linux Agent 均保持可运行；GPU 训练以 Linux NVIDIA 为生产目标。
9. 素材导入节点最终通过对象存储上传结果；模型训练/转换产物继续走统一模型资产存储。
10. HTTP Agent executor 完成前，不能宣称“真实跨机器任务执行已关闭”。

