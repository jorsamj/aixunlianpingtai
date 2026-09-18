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

## 6. 已关闭：HTTP Agent Executor Control Protocol

控制面已经把“中央 assignment”安全转换成唯一真实 execution lease，不要求远端 Agent 访问中央 SQLite / NFS。

核心文件：

- `platform_core/agent_execution.py`
- `platform_core/service_nodes.py`
- `platform_core/training_recovery_api.py`
- `tests/unit/test_agent_execution.py`
- `tests/api/test_agent_executor_api.py`
- `.github/workflows/node-agent-executor.yml`

已实现协议：

```text
Task QUEUED
→ CentralTaskAllocator 选择 node
→ Agent 用 Node Token claim 自己的 assignment
→ 控制面签发 Assignment Lease Token
→ Agent start
→ 控制面在 BEGIN IMMEDIATE 内再次验证：
   Node Token / enabled / heartbeat / capability / Assignment Lease
→ 唯一 QUEUED → RUNNING
→ tasks.attempt + 1 作为 execution generation
→ 签发 Execution Lease Token
→ assignment RELEASED(reason=execution_started)
→ Agent heartbeat / log / begin-finalization / finish
→ 中央 TaskRepository 继续作为唯一任务 truth
```

三个 token / fence 的职责不可混用：

1. **Node Token**：证明请求来自哪个已登记服务节点；支持 rotate，旧 token 立即失效。
2. **Assignment Lease Token**：只允许该节点启动这一条已 claim assignment；不能重复 start。
3. **Execution Lease Token + generation**：只允许当前执行代 heartbeat / log / finalization / finish；旧 generation 永久失效。

关键生产语义：

- start 的 `QUEUED → RUNNING` 与 assignment 释放在同一个 `BEGIN IMMEDIATE` 事务。
- Node Token 在 start 事务内再次对照最新 `token_hash`，堵住“前置鉴权后刚好 rotate”的并发窗口。
- 启动前必须先证明 task payload 可读；payload 缺失/损坏时 task 仍保持 QUEUED。
- 节点 disabled 后不再 claim/start 新任务，但已有有效 execution 仍可 heartbeat/finish，避免只能等 lease 超时。
- RUNNING task 的 cancellation truth 仍由中央 TaskRepository 决定；`CANCEL_REQUESTED` 只能 finish 为 `CANCELLED`。
- `begin_finalization` 沿用现有 finalization/cancel 原子语义。
- remote log 只能追加到 task 自己的服务端 `log_ref`，单次 64 KiB 限制，并受 execution fence。
- 控制面不会接受远端 PID 作为本机进程 PID；远端进程树后续由 Agent 本机负责终止。
- start 响应明确声明：
  - `shared_sqlite_required = false`
  - `shared_nfs_required = false`
  - 大型 artifact 使用后续 object-storage transport。

控制面 API：

- `POST /api/v63/node-executor/{node_id}/assignments/claim`
- `POST /api/v63/node-executor/{node_id}/assignments/{task_id}/start`
- `POST /api/v63/node-executor/{node_id}/executions/{task_id}/heartbeat`
- `POST /api/v63/node-executor/{node_id}/executions/{task_id}/logs`
- `POST /api/v63/node-executor/{node_id}/executions/{task_id}/begin-finalization`
- `POST /api/v63/node-executor/{node_id}/executions/{task_id}/finish`

永久 CI：

`.github/workflows/node-agent-executor.yml`

验证 run：

`35288805083`

结果：

- API：success
- Ubuntu 24.04 contract：success
- Windows latest contract：success

覆盖了单次原子 start、错误/重复 assignment token、跨节点冒领、disabled 节点收尾、取消优先、finalization、remote log、lease expiry 后 generation fencing、Node Token rotate race、payload 缺失不启动、非法 generation 422、以及 VERSION / source guards。

临时 CI 草稿 PR #7 已关闭，未 merge。

## 7. 已关闭：Remote Portability Gate + Production Runtime Mount

为防止“中央绝对路径任务被误发到远程 Agent”，中央调度现在区分：

- `connection_mode=local`：允许现有 legacy/path-bound task，适用于控制面与 Worker 共机或明确共享本地运行环境。
- `connection_mode=agent`：只有任务显式携带版本化 `remote_execution` portable contract 才能成为调度候选。

当前 contract：

```json
{
  "version": 1,
  "task_kind": "<TaskKind.value>",
  "transport": "object-storage-v1 | agent-artifact-v1"
}
```

关键约束：

- 不根据旧 payload 中的路径“猜测”任务是否可远程执行；无 contract 一律 fail closed。
- contract 的 `version`、`task_kind`、`transport` 必须全部匹配。
- Scheduler 的 `resolved_execution_config.remote_execution` 只保存白名单字段，不复制 signed URL、凭据、中央绝对路径或任意嵌套数据。
- legacy task 在只有 agent 节点时保持 `QUEUED`，不会制造一个必失败的远程 assignment。
- local 节点仍保持旧任务兼容能力。
- HTTP Agent executor 测试任务已经显式使用 portable contract，避免测试绕过真实生产语义。

Portability gate 验收：

- Central Node Assignment run `35290891091`：API / Ubuntu / Windows 全绿。
- Node Agent Executor run `35290891208`：API / Ubuntu / Windows 全绿。

同时修复了一个实际生产挂载缺口：此前 v62/v63 runtime 子路由只在 focused test 中直接实例化，生产 `app.py` 没有挂载组合 router。现在生产 app 只挂载一次：

```python
app.include_router(training_recovery_router(
    get_project, shared_task_repository, shared_task_artifacts,
))
```

由 `platform_core/training_recovery_api.py` 继续单一拥有：

- training recovery
- training material picker
- service nodes
- central scheduler
- node executor

新增 AST 永久契约，禁止漏挂载、重复挂载或把 v63 子路由重新散落到 `app.py`。

Production mount 验收：

- Central Node Assignment run `35291195275`：API / Ubuntu / Windows 全绿。
- Node Agent Executor run `35291195262`：API / Ubuntu / Windows 全绿。
- 临时 CI PR #9 / #10 均已关闭，未 merge。

## 8. 已关闭：Portable Deployment Transport

部署测试已经成为第一个具备真实 portable transport contract 的 task kind。

当前 durable task 只保存对象存储引用和完整性证据，不保存临时签名 URL：

- 测试图片：`storage_source_id / object_key / sha256 / size_bytes / content_type`
- 项目模型：复用统一 `ModelArtifactService` 的 OSS / S3 / MinIO 资产。
- 官方模型：仅保存 allow-listed model reference。
- 输出：只保存 durable storage ref；Agent start 不再收到中央 `input_path / model_path / runner_path / python_path`。

`start` 仅为输入/模型生成短期 GET；输出使用 `prepare-after-local-hash-v1`，不在 start 阶段提前签 PUT。

验收：

- Portable Deployment run `35292400487`：production API / Ubuntu / Windows 全绿。
- 同批 Agent run `35292068629`、Central run `35292068610` 全绿。
- 临时 CI PR #11 已关闭，未 merge。

## 9. 已关闭：Hash-bound Remote Result Publication

远程部署测试的结果发布已经进入 execution fencing，不再接受“Agent 上传一个文件后直接说成功”。

真实链路：

```text
Agent 本地推理完成
→ Agent 本地计算 output SHA256 + size
→ POST result-upload/prepare
→ 控制面验证 Node Token + Execution Lease + generation
→ 控制面生成 generation-scoped object key
→ 签发绑定 Content-Length + SHA256 metadata + 禁止覆盖的短期 PUT
→ Agent PUT
→ POST result-upload/confirm
→ 控制面 stat 对象并核对 size + SHA256 metadata
→ durable finalization transaction 原子决定 cancellation 或 commit
→ 写 remote-results/<generation>/result.json
→ /finish(SUCCEEDED) 强制使用服务端 confirmed result_ref
```

关键 fencing：

- 实际结果 key 为 `.../output/generation-N/result.jpg`，旧 generation 的 signed PUT 不会占用新 generation 的对象。
- S3 / MinIO 签名绑定 `Content-Type`、`Content-Length`、`x-amz-meta-sha256`、`If-None-Match: *`。
- OSS 签名绑定 `Content-Type`、`Content-Length`、`x-oss-meta-sha256`、`x-oss-forbid-overwrite: true`。
- signed PUT URL 只返回给当前 Agent，不写 Scheduler truth，也不写 durable upload state。
- `remote-results/<generation>/upload.json` 只保存 hash / size / storage ref / node / generation。
- 已上传但 confirm 前断线时，只要对象现有 size/hash 完全一致，prepare 可幂等恢复；冲突对象 fail closed。
- confirm 时对象缺少 SHA256 metadata、size 不符、hash 不符均禁止成功。
- confirm 在对象验证后复用 `begin_finalization()` 的数据库事务作为 commit gate，cancel 与 result publication 不能同时获胜。
- portable deployment 未 confirm 前禁止 `begin-finalization`，也禁止 `finish(SUCCEEDED/PARTIAL_SUCCESS)`。
- Agent 自报的 `result_ref` 不可信；成功 finish 强制使用当前 generation 的服务端 confirmed result_ref。

新增控制面 API：

- `POST /api/v63/node-executor/{node_id}/executions/{task_id}/result-upload/prepare`
- `POST /api/v63/node-executor/{node_id}/executions/{task_id}/result-upload/confirm`

验收：

- Node Agent Executor run `35295427105`：API / Ubuntu / Windows 全绿。
- Portable Deployment run `35295427110`：production API / Ubuntu / Windows 全绿。
- Central Node Assignment run `35295427100`：API / Ubuntu / Windows 全绿。
- 临时 CI PR #12 已关闭，未 merge。

## 10. OPEN：Agent-side Real Deployment Runtime

**不能因为控制面协议已完成，就宣称“真实跨机器任务执行 CLOSED”。**

下一步必须让 `node_agent.py` 真正消费上述 HTTP 协议，并在远端节点本机执行任务。目标链路：

```text
Node Agent heartbeat
→ poll /assignments/claim
→ /start 获取 Execution Lease + resolved execution config
→ 准备对象存储输入 / task-local 工作目录
→ 本机启动对应 task handler / 子进程
→ 周期 heartbeat + progress + log
→ cancel 时本机终止精确进程树
→ 上传结果/模型/素材到对象存储或统一模型资产存储
→ /begin-finalization
→ /finish
→ 清理本机临时目录、进程、GPU reservation / execution state
```

下一阶段硬约束：

1. Agent 客户端不得 import / 打开中央 `TaskRepository` 或 `tasks.sqlite3`。
2. Agent 不依赖共享 NFS 才能 claim/execute。
3. 输入/输出大文件通过对象存储或明确的 artifact transport，不把中央绝对路径直接当远端路径使用。
4. Agent lease 丢失后必须停止本机执行并清理子进程树，禁止旧 generation 继续训练。
5. cancel 必须能从中央 truth 下发到 Agent 并实际停止本机任务。
6. Windows Agent 与 NVIDIA Linux Agent 都需要协议级验证；正式 GPU 训练仍以 NVIDIA Linux 为生产目标。
7. 素材导入节点最终负责解压/解析/清洗/标签转换并上传 OSS；模型训练/转换输出走统一模型资产存储。
8. Agent-side runtime + 至少一个真实 task kind 跑通前，不能宣称跨机器执行关闭。
