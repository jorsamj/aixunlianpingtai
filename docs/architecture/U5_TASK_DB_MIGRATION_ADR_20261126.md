# U5 任务运行时数据库迁移 ADR（2026-11-26）

> **状态：`DESIGN_ONLY` / `NOT_IMPLEMENTED` / `NOT_VERIFIED`**
> 本文只做架构决策与合同记录。**本轮未修改任何生产源码、未修改任何生产表、未新增第二套任务库、未连接 PostgreSQL、未访问 4070/A800、未切换任何 Provider。**
>
> 文中每个断言都带 `文件:行` 证据。凡是**没有**代码证据的内容，一律放在“拟议变更”或“未决问题”里，并明确标记，不得当作现状。

## 0. 上游依据与范围

- 迁移单元定位：`docs/architecture/F1_PERFORMANCE_AND_MIGRATION_DESIGN_20261122.md:204` 把 U5 定义成 `tasks.sqlite3` + worker instances + lease/attempt/fencing + formal bulk，风险“最高”，顺序“最后，独立授权 + 排空窗口”。
- 阻塞定性：`docs/architecture/AI_DEVELOPMENT_HANDOFF.md:18` 记为“安全设计阻塞：必须与执行权威、Lease、资源预留、恢复联合设计”；`:14` 记 U3 未开始。本文只解决 U5 的设计部分。
- 已有框架约束：`F1...md:217-218` 要求“同一事务需要的表放入同一 database/schema，经原 Repository 查询；禁止把 JOIN 改成跨库 HTTP 或多次无一致性读”。

### 0.1 本文不做什么

1. 不提出第二个任务存储（不存在“SQLite 与 PostgreSQL 同时权威”的设计）。任何时刻只有一个权威 Provider，见 §7。
2. 不修改 `tasks` 等生产表的 DDL（本文没有新列、新表、新索引建议落到现有 SQLite 上）。目标侧 DDL 属于后续独立变更，不在本文批准范围。
3. 不重写 Scheduler / Worker / Agent / Supervisor（`AGENTS.md` 长期约束），只描述“迁移不得改变它们的合同”。
4. 不给实现状态结论。本文所有“拟议变更”都是待授权、待实现、待验证。

## 1. 结论摘要（十问的一句话答案）

| # | 问题 | 一句话答案 | 现状证据 |
|---|---|---|---|
| 1 | 任务唯一身份 | `tasks.task_id` 是调用方铸造的稳定主键，插入是纯 INSERT（不是 upsert），被 `task_tombstones` 永久禁止复用；幂等靠“先写不可变回执文件，再提交行”，重放读回收据返回 `ALREADY_APPLIED` | `repository.py:58,378-414,584-594` |
| 2 | Lease/Attempt 防双领 | 同一 `BEGIN IMMEDIATE` 里 `UPDATE ... WHERE task_id=? AND status='QUEUED'`，`rowcount!=1` 即继续下一个候选；`lease_token` 是 fencing token，`attempt` 是执行代次，两者都必须匹配 | `repository.py:1307-1373`；`fenced_repository.py:29-41,107-126` |
| 3 | 心跳与进程真值 | 进程真值三列（pid/create_time/command_hash）只在持有 lease 时写入；续租要求 `owner_token` 且 `expires_at>now`；检查不到状态一律 `unknown`，绝不因此判定进程已死 | `repository.py:1431-1460`；`worker_instances.py:284-298,60-69`；`fenced_repository.py:417-431` |
| 4 | 节点消失恢复 | 过期租约由 claim 事务内回收（`claim_recovers_expired=True`）：清 owner → `QUEUED`，下次 claim 才 `attempt+1`；远端 Agent 过期**不**自动重排，转 `recovery_blocked_remote_agent_unverified` 并保留 GPU 预留 | `repository.py:249,1143-1200`；`fenced_repository.py:452-542` |
| 5 | 旧 Worker 排空 | `CANCEL_REQUESTED` 只是请求；真正终态要求“进程停止已证明”，否则保留 status/lease/GPU 并进入 `cancelling_unverified`；formal bulk 不走通用 finish | `scheduler.py:131-219`；`repository.py:1925`；`scheduler.py:333-337` |
| 6 | 预留与租约同事务 | 资源准入回调在 claim 的写事务内部被调用，`gpu_reservations` 行就在该事务里 INSERT；预留生命周期由 SQLite 触发器绑到任务行 | `repository.py:1343-1349`；`gpu_resources.py:601-605,76-87` |
| 7 | 结果与 ArtifactStore 对账 | Payload/结果都是内容寻址不可变文件，行里只放相对 ref；文件先落、行后提交（**没有**跨文件与行的原子事务），因此必须“可对账”而非“事务一致” | `payload_publications.py:1-6,284-341`；`repository.py:380-382` |
| 8 | 中断切换与反向迁移 | 任务域今天**没有任何**切换协议；可复用的既有范式是算法域的 transition marker + 准入记录 + rollback 评估 | `algorithm_cutover.py:533-617,620-642,645+,918+` |
| 9 | 历史 SQLite 兼容 | 任务库没有“只读旧版本”模式，打开即**就地迁移**（幂等语句、`user_version` 最后推进），版本超前直接拒绝启动 | `repository.py:33,277-368` |
| 10 | C2-B 正式 GT 防重复执行 | 每任务跨进程文件锁 + `formal_bulk_execution.active_batch` 身份/顺序校验穿住 GT 提交；“完成”只能由 GT 回执 + 候选日志证明，任务行本身不算证据；自动重领上限 5 次后转持久阻塞 | `repository.py:38,1001-1004`；`fenced_repository.py:148-177`；`annotation_bulk_commit.py:32-152` |

## 2. 现有执行拓扑：谁在写同一个文件

U5 迁移最容易被低估的事实：`tasks.sqlite3` **不是**一个进程独占，也不是一个类独占。

| 写入者 | 构造位置 | 使用的类 | 说明 |
|---|---|---|---|
| HTTP 控制面 | `app.py:270` `_SHARED_TASK_REPOSITORY = TaskRepository(DATA_DIR / "task_runtime" / "tasks.sqlite3")` | `TaskRepository`（**非** fenced） | 取消、评审完成、恢复、删除、队列查询 |
| 本地 Worker | `task_worker.py:119` `AssignmentAwareFencedTaskRepository(runtime_dir / "tasks.sqlite3")` | `AssignmentAwareFencedTaskRepository` → `FencedTaskRepository` → `TaskRepository`（`task_node_assignments.py:1708`） | claim/heartbeat/bind/finish |
| 远端 Agent 控制面 | `agent_execution.py:711` `self.fenced = FencedTaskRepository(repository.path)` | `FencedTaskRepository` | `start_execution`/`record_stop_proof`/`finish_execution` |
| Worker 实例租约 | `task_worker.py:158-168` | `WorkerInstanceService`（`worker_instances.py:146`） | `worker_instances` |
| GPU 资源 | `task_worker.py:252-259`（`NodeScopedGPUResourceManager`） | `gpu_resources.py`/`gpu_reservations_v2.py` | `gpu_*` |
| 训练历史 | `training_material_usage.py:22-38`（`self.path` = 任务库） | `TrainingMaterialUsage` | `training_usage_*` |
| 中心分配器 | `task_node_assignments.py:981-1000` | `CentralTaskAllocator` | `task_node_assignments`/`task_preemptions` |

直接推论（迁移硬约束）：

- **C1**：同一个数据库文件同时存在“带代次校验”的写路径（`FencedTaskRepository.finish`，`fenced_repository.py:323-382`）与“只校验 lease_token”的写路径（`TaskRepository.finish`，`repository.py:1889-1956`）。两者都在生产路径上。任何 Provider 抽象必须同时满足两种语义，不能只实现其中一种。
- **C2**：`repository.py:1097-1104` 的 docstring 明确“HTTP 控制面使用 plain `TaskRepository`”，所以控制面**不能**被强制要求持有代次。
- **C3**：`app.py:270` 是进程级单例（模块全局），迁移期必须能找到“这个进程当前用哪个 Provider”，否则无法冻结写入。当前没有这种可观测点（见 §10 未决问题 Q-3）。

## 3. 十个问题的现有合同

### 3.1 任务唯一身份如何保持

**现有合同**

1. 主键：`tasks.task_id TEXT PRIMARY KEY`（`repository.py:58`）。`task_id` 由调用方铸造，是唯一身份；`TaskRecord` 里没有第二身份列（`models.py:43-70`）。
2. 禁止复用：`create()` 在事务外先查一次 `task_tombstones`（`repository.py:378-379`），进入 `BEGIN IMMEDIATE` 后再查一次（`:400-402`），命中即 `ValueError('TASK_ID_RETIRED: ...')`。删除终态任务时 tombstone 与 `DELETE FROM tasks` 在同一事务（`:1270-1277`）。
3. 创建不是幂等 upsert：`create()` 是普通 `INSERT`（`:403-406`），重复创建同 ID 会以主键冲突失败，不会被静默覆盖。
4. 派生子身份是确定性的、且被强校验：
   - `trainprep_{parent}` / `{parent}-prepare`（`repository.py:476,539,608`；`app.py:7042`）；
   - `_commit_payload_publication` 在事务内重新推导子身份并与实际行比对（`repository.py:608-611`）；
   - `bind_preparation_input` 先校验 `lease.task.task_id == expected_id`（`repository.py:476-479`）。
5. 回执（幂等的真实载体，全部是“业务回执”，不是任务行）：
   - Payload 发布回执：`payload-publications/v1/{operation_id}.json`，`operation_id = sha256(canonical identity)`（`payload_publications.py:103-114,415-431`）；读取时“必须正好一份”，缺失或多份都拒绝（`:370-382`）。
   - 发布重放：`_confirm_payload_publication` 命中则返回 `ALREADY_APPLIED` 且不复活租约（`repository.py:584-594`；`:612-618`）。
   - 候选提交回执：`annotation_candidate_commits(task_id, image_id)` 存 `receipt_json`（`annotation_repository.py:1351-1353`），按 `operation_id` 读取（`:1246-1260`；`annotation_task_service.py:722-729`）。
   - 素材分配回执：`material_assignment_receipts(task_id, image_id)`（`material_repository.py:70-74,1907-1918`）。
   - 资源等待回执：写在 `task_node_assignments.resolved_execution_config.resource_wait_receipt`，按 (task, assignment generation, node) 读（`agent_execution.py:3399-3411`）。
   - 负样本池操作回执：`negative_pool_operations(operation_id)`（`negative_pool.py:80-81`）。
6. `request_id` 不是任务库概念。任务库里没有请求去重表；请求级幂等由调用层用 `request.json` 内容相等来判定（例：`material_batches.py:503-506` 不一致即 `BATCH_TASK_ID_CONFLICT`）。

**拟议变更（不实施）**

- 目标库必须原样保留：`task_id` 单列主键、`task_tombstones` 的存在性与唯一性语义、以及“创建失败不回退到 upsert”。
- 回执域**不随任务库迁移**（§4.3）。因此迁移校验必须证明“任务行指向的回执在目标库之外仍可读”，而不是把回执搬进 PostgreSQL。
- 不新增 `request_id` 去重表。若未来需要请求级幂等，应在上层（创建服务）设计，不在 U5 内偷偷引入。

**风险**：如果把“创建”实现成 `INSERT ... ON CONFLICT DO NOTHING` 以便重试，就会悄悄打开同 ID 双语义，`TASK_ID_RETIRED` 与 `BATCH_TASK_ID_CONFLICT` 两条防线同时失效。

### 3.2 Lease 与 Attempt 如何阻止双领

**现有合同**

1. 租约三列：`worker_id` / `lease_token` / `lease_expires_at`（`repository.py:79-81`）。`task_id` + `lease_token` 是对外暴露的凭证对（`TaskLease`，`models.py:95-101`）。
2. `claim_next` 的全过程（`repository.py:1289-1378`）：
   - 先在**只读连接**里准备候选（`:1300-1303`），注释明确“无写锁、无 artifact I/O”；
   - 再开 `BEGIN IMMEDIATE`（`:1307`），事务内先做过期回收（`:1311`）；
   - 逐候选**语义重校验**：`SELECT ... WHERE task_id=? AND status='QUEUED'`，并把当前行与候选快照的 `SEMANTIC_FIELDS` 逐字段比对（`:1313-1317`，字段集来自 `claim_candidates.py`）；
   - 资源互斥在事务内查（`:1330-1338`）；
   - 最后 CAS：`UPDATE tasks SET status='RUNNING', worker_id=?, lease_token=?, lease_expires_at=?, attempt=attempt+1 ... WHERE task_id=? AND status='QUEUED'`，`rowcount!=1` 就 `continue`（`:1350-1366`）。
3. `attempt` 就是执行代次，不另设 generation 列：`FencedTaskRepository` 类注释与 `_generation_clause`（`fenced_repository.py:29-41`），`WorkerContext.execution_generation` 直接返回 `lease.task.attempt`（`worker.py:176-180`）。
4. 所有所有权写都含 `task_id=? AND lease_token=?`，fenced 版本再加 `attempt=?` 与 `lease_expires_at > now`：`assert_execution`（`fenced_repository.py:107-126`）、`heartbeat`（`:238-284`）、`bind_process`（`:286-321`）、`finish`（`:323-382`）。
5. Worker 侧在每次 DB 操作前后都校验所有权：`_lease_operation` 装饰器 + `assert_current_execution`（`worker.py:22-39,197-216`），artifact 发布也在前后各校验一次（`worker.py:71-120`）。
6. 远端 Agent 的“领取”是另一条同构路径：`start_execution` 在 `BEGIN IMMEDIATE` 内做 `UPDATE ... WHERE task_id=? AND status='QUEUED'` 并 `attempt=attempt+1`（`agent_execution.py:1185-1208`），同时把 Assignment `CLAIMED→RELEASED`（`:1211-1241`）。`rowcount!=1` → `EXECUTION_START_RACE`。
7. 过期不靠后台线程兜底：`claim_recovers_expired = True`（`repository.py:249`）说明 claim 自带回收；`release_expired()` 仍是独立入口（`:1280-1287`），Scheduler 在必要时显式调用（`scheduler.py:109-116`）。

**拟议变更（不实施）**

- PostgreSQL 侧必须复刻“条件 UPDATE + rowcount 判定”的 CAS，**不能**用 `SELECT ... FOR UPDATE SKIP LOCKED` 单独替代：`SKIP LOCKED` 只解决“两个领取者不同时看到同一行”，不解决“旧持有者在锁释放后继续写”。代次与 lease_token 的谓词必须留在每条写语句的 `WHERE` 里。
- 保留“单一代次计数器”结论：不得同时引入 `generation` 与 `attempt`。
- 领取事务必须仍把“候选准备”留在事务外，否则会把 payload 读取与 JSON 解析塞进写锁内（`repository.py:1300` 的注释是现状约束）。

### 3.3 心跳与进程真值如何保持一致

**现有合同**

1. 两层租约是分开的、且语义不同：
   - **Worker 实例租约**（`worker_instances`，`repository.py:102-118`）：`instance_key = sha256(data_dir,node_id,roles,slot)`（`worker_instances.py:27-41`），带 `owner_token`；
   - **任务租约**（`tasks.lease_*`）。
2. 重复实例拒绝：`acquire()` 在同一 `BEGIN IMMEDIATE` 内查 `instance_key` 或 legacy key（`worker_instances.py:190-201`），只有“已过期 **或** pid 确定已死”才允许接管。`_pid_is_definitely_dead` 对 `AccessDenied/OSError/ValueError` 返回 `False`（`:60-69`）——即“查不到”不等于“死了”。
3. 续租不能被复活：`renew()` 的 WHERE 是 `instance_key=? AND owner_token=? AND expires_at>?`（`worker_instances.py:288-297`），过期后必须重新 `acquire`。
4. 任务心跳：写 `updated_at`、`lease_expires_at=now+30s`，`progress=MAX(progress,?)`（单调，`repository.py:1388-1393`），stage 有 `paused/cancelling` 保护（`:1395-1400`），并对远端 Agent 加双重限制：租约未过期且不在 `recovery_blocked_remote_agent_unverified`（`:1408-1423`）。fenced 版本用可配置 `lease_seconds` 并附加代次（`fenced_repository.py:250-278`）。
5. 进程真值：`bind_process` 只在持有 lease 时写 `process_pid/process_create_time/process_command_hash`（`repository.py:1431-1460`；fenced 版加代次与未过期，`fenced_repository.py:286-321`）。`command_hash = sha256(argv JSON)`（`process_control.py:18-25`），Windows 上用 `GetProcessTimes` 取创建时间（`process_control.py:46-62`）。
6. 三态判定：`_process_recovery_state` 返回 `alive`/`gone`/`unknown`（`fenced_repository.py:417-431`）。`ProcessIdentityMismatchError`（PID 被复用或命令改变）判 `gone`，`PermissionError` 判 `unknown`。
7. 未知即阻塞：`unknown` → stage `recovery_blocked_process_inspection`，并**保留** GPU 预留（`fenced_repository.py:489-495`）；`alive` → `lease_expired_process_alive` 同样保留（`:482-488`）。
8. 清理与领取分离：`reap_expired_processes` 在 claim 之前执行，且只对“三列齐全”的行按精确身份终止（`fenced_repository.py:544-581`；`scheduler.py:109-112`）。
9. Worker 侧失败即自断：续租任何异常都 `mark_lease_lost()` 并终止子进程（`scheduler.py:56-77`）；SQLite busy 导致无法证明续租时同样自断（`worker.py:31-38`，`scheduler.py:379-389`）。

**拟议变更（不实施）**

- `process_pid/process_create_time/process_command_hash` 三列语义必须原样迁移；目标库不得用“连接是否存活”替代进程真值。
- `worker_instances` 的“查不到不等于死”必须保留。PostgreSQL 侧如果改用 advisory lock 做实例互斥会**丢失**这一性质（锁随连接消失、且无法从别的节点检查 pid），因此拟议：实例租约继续用表行表达，advisory lock 最多作为加速手段。
- 心跳的 30 秒续租在 plain `TaskRepository` 里是**硬编码**（`repository.py:1390`），而 fenced 版是可配置（`fenced_repository.py:248`）。拟议：迁移前先把这一处语义统一（属于 U5 前置条件，见 §10 Q-1）。

### 3.4 节点消失后的恢复

**现有合同**

1. 回收入口：`release_expired()`（`repository.py:1280-1287`）与 claim 内部调用（`:1311`），实际逻辑在 `_release_expired_in`（`:1143-1200`；fenced 覆盖版 `fenced_repository.py:452-542`）。
2. 本地行：`status IN ('RUNNING','CANCEL_REQUESTED') AND lease_expires_at<=now`（`repository.py:1173-1174`）→ `QUEUED`（或取消语义下 `CANCELLED`），`worker_id/lease_token/lease_expires_at=NULL`，stage `recovered`（`:1160-1179`）。
3. **attempt 不在回收时自增**：回收只清所有者；自增发生在下一次 claim（`repository.py:1360`）。所以“代次单调”由“领取”保证，不由“回收”保证。
4. 远端 Agent 特殊：expired lease **绝不**按 TTL 重排。fenced 版对 `worker_id LIKE 'agent:%'` 只写 `recovery_blocked_remote_agent_unverified` 并延长 GPU 预留（`fenced_repository.py:464-479`；`_hold_gpu_reservation` `:398-415`），注释写明“central SQLite 无法证明远端进程死亡”。
5. `MATERIAL_IMPORT` 有专用阶段回退（`indexing` → `indexing_queued`，`repository.py:1166-1168`；fenced `:506-511`）。
6. formal bulk 走专属重排，带尝试上限：`MAX_FORMAL_BULK_ATTEMPTS = 5`（`repository.py:38`），`_requeue_expired_formal_bulk`（`:1034-1095`）。
7. 取消先到 + 租约过期 → `CANCELLED` 且 `finished_at=now`（`repository.py:1163-1170`）。
8. 安全重投递：结果 ref 按代次命名（`remote-results/{generation}/result.json`，`agent_execution.py:60-69`），执行锚点按代次命名（`execution-inputs/v1/attempt-{attempt}.json`，`payload_publications.py:358-368`），因此新一代不会撞上一代的产物。
9. GPU 预留清理用“排除仍持有者”的 DELETE（`repository.py:1182-1193`；fenced `:530-541`），而不是全表清空。

**拟议变更（不实施）**

- 目标库必须能在一个事务里完成“查过期 → 分类（本地/远端/formal bulk）→ 条件更新”，并且该分类结果不能被并发领取者读到半成品。现有实现靠“单写者 BEGIN IMMEDIATE”，PG 下需要显式行锁或 `FOR UPDATE` 才能达到同等效果。
- 远端 Agent 的“过期不等于死亡”必须保留。这条规则使“排空窗口”无法只靠时间推进（§7 阶段 3 的直接依据）。

### 3.5 旧 Worker 如何排空

**现有合同**

1. 取消只是请求：`request_cancel` 把 `RUNNING` 改 `CANCEL_REQUESTED` + stage `cancelling`（`repository.py:1755-1767`）；`QUEUED`/`AWAITING_CONFIRMATION` 直接 `CANCELLED`（`:1746-1754`）。
2. Worker 必须在**证明进程已停**之后才能写终态：`_finish_cancel_if_safe`（`scheduler.py:131-162`）先 `_cleanup_bound_process_if_needed`（`:174-219`）。若无法证明停止，则保留 status/lease/GPU，并把 stage 推进到 `cancelling_unverified`（超过宽限）或 `cancelling`（`:203-215`），宽限常量来自 `training_tasks`（`:190-200`）。
3. 进程终止的失败语义是 fail-closed：`terminate_bound_process` 对 `PermissionError` 返回 `False`（`worker.py:391-393`），即“查不到”不放行。
4. formal bulk 禁止走通用 finish：`scheduler.py:142-145` 直接返回 False；`:262-265` 只记日志；`:333-337` 由专属 handler 发布终态。原因写在注释里：“Generic finish cannot certify this task's GT journal”。
5. 提交与取消的先后由 `begin_finalization` 一次性裁定：已持久化 `CANCEL_REQUESTED` 者获胜；一旦进入 `finalizing_commit`，之后停止请求被拒绝（`repository.py:1585-1648`，其中 `:1610-1612`、`:1706-1708`）。
6. 排空期的“不再接新活”目前只有进程级手段：Scheduler 的 `service_stop` 触发 `fence_active()`（`scheduler.py:307-311,408-412`），以及 `serve_forever` 退出时 `fence_active()`（`:474-475`）。**没有**跨节点的“停止领取”开关。

**拟议变更（不实施）**

- 排空窗口必须由“可证明的空闲”定义，而不是由停机时长定义：条件是 `tasks` 中不存在 `status IN ('RUNNING','CANCEL_REQUESTED')`，且不存在 `stage IN ('cancelling_unverified','lease_expired_process_alive','recovery_blocked_process_inspection','recovery_blocked_remote_agent_unverified','formal_bulk_blocked','formal_bulk_attempt_limit')` 的行。
- 拟议为排空期增加**只读**的“阻止领取”判据（复用既有 `resource_waiting` 机制的表达能力，不新增表），具体实现需独立授权。

### 3.6 资源预留与租约如何同事务

**现有合同**

1. 准入回调在 claim 的写事务内执行：`claim_next` 在 `BEGIN IMMEDIATE` 里调用 `admission(database, admitted, worker_id, token, expires_at, now)`（`repository.py:1343-1344`），传入的是**同一个 connection**。
2. 资源行就在该事务内插入：`GPUResourceManager.admit` 最后执行 `INSERT INTO gpu_reservations VALUES(...)`（`gpu_resources.py:601-605`），事务由调用方提交（`repository.py:1373`）。
3. 准入失败不改状态、只标等待：`UPDATE tasks SET stage='resource_waiting', resource_wait_reason=?`（`repository.py:1346-1349`）；失败原因也在同一事务里落库。
4. 阻塞判定也在事务内：资源键被活跃任务占用（`repository.py:1330-1338`）、恢复栅栏占用（`fenced_repository.py:55-73`）、训练 slot 占用（`gpu_resources.py:493-495`）。
5. 预留与任务行的生命周期由触发器绑定（`gpu_resources.py:76-87`）：
   - `gpu_task_heartbeat`：任务 `lease_expires_at` 更新 → 同步预留 `expires_at/heartbeat_at`；
   - `gpu_task_release`：任务状态/lease 变化 → 删除不属于新所有者的预留。
6. Worker slot 唯一性由列级 `worker_slot TEXT NOT NULL UNIQUE` 保证（`gpu_resources.py:70`）。
7. 推理许可走同一模式：`acquire_inference_permit` 在事务内先校验任务所有权再插许可（`inference_resources.py:47-83`）。
8. 远端双槽 Hold 在 `start_execution` 的同一事务里插入（`agent_execution.py:1127-1287`，`execution_resource_holds` 定义在 `repository.py:119-129`）。

**拟议变更（不实施）**

- PostgreSQL 没有等价于上述两个触发器的“随任务行更新而联动”的免维护机制。拟议：把触发器表达的约束显式化为“同一事务内的第二条语句”，并把“预留必须与任务所有权同一事务”写成 Provider 合同的强制条款；任何“先领任务、再异步补预留”的实现都必须被拒绝。
- `worker_slot UNIQUE` 必须保留为目标侧的唯一约束，不能退化成“应用层先查后写”。

### 3.7 任务结果如何与 ArtifactStore 对账

**现有合同**

1. 身份与位置分离：`tasks.payload_ref` / `result_ref` 只是相对于 `task_runtime/artifacts/{task_id}/` 的路径（`models.py:51-53`；`artifacts.py:68-93` 做路径安全校验）。
2. 不可变 Payload：`payload-versions/v1/{operation_id}/sha256-{digest}.json`（`payload_publications.py:27,421`）；写入用 hard link 且不覆盖（`:305-311`），已存在但字节不同 → `PUBLICATION_OPERATION_CONFLICT`（`:310-311`）；读取强制校验摘要（`:327-341`）。
3. 证据与执行锚点：`evidence-versions/v1/sha256-{digest}.json`（`:343-356`）、`execution-inputs/v1/attempt-{attempt}.json`（`:358-368`）。
4. 顺序是“文件先落、行后提交”，且这是显式设计：`create()` 注释 “Persist the real artifact before exposing its reference in a task row”（`repository.py:380-382`）；模块 docstring 明确不承诺跨文件系统与 SQLite 掉电原子性（`payload_publications.py:1-6`）。
5. 发布提交的幂等：先按 `operation_id` 读回执（`repository.py:544`），`_confirm_payload_publication` 命中即 `ALREADY_APPLIED`（`:584-594`），否则在事务里做条件 UPDATE（`:642-646`），**失败即抛**而不是假装成功（`:645-646,650-655`）。
6. 结果的执行栅栏：Worker 的 artifact 写读都包在 `FencedArtifactStore` 里（`worker.py:56-120`），替换文件前二次校验所有权（`:112-120`）。
7. 远端结果的确认链：状态文件按代次存放，`_confirmed_remote_result` 校验 `execution_generation` 与 `result_ref` 一致（`agent_execution.py:1917-1939`）；`finish_execution` 还要 Hold 与上传回执（`:3539-3634`）。
8. 终态写 `result_ref` 的唯一点是 `finish`（`repository.py:1911-1922`），formal bulk 例外（由 `publish_formal_bulk_progress` 写，`fenced_repository.py:207-237`）。

**拟议变更（不实施）**

- `ArtifactStore` 不迁入关系库（`F1:207` 已判定）。因此迁移后仍存在“两个存储、两种失败模式”：
  - 行已提交但文件不可读 → 任务必须可被发现为坏证据（现状：读取抛 `PAYLOAD_*` 错误码，`payload_publications.py:266-272`）；
  - 文件已落但行未提交 → 孤儿文件，由幂等回执“认领”（现状：`read_payload_publication_receipt`，`:370-413`）。
- 拟议：迁移校验必须包含“结果可读性抽样”，即从目标库取 `result_ref`/`payload_ref` 并按现有 API 读回，而不是只比行数。

### 3.8 切换中断与反向迁移如何恢复

**现状（先说清楚：任务域什么都没有）**

- `tasks.sqlite3` 只有一个 Provider（本地 SQLite）。没有准入记录、没有 transition marker、没有 rollback 评估。任何“任务库切换到 PostgreSQL”的能力都是**不存在**的。
- 可复用的既有范式（算法域，已实现且已验证）：
  - `cutover_transition`：在权威变更**之前**发布 marker，只有在“正文正常返回 **且** 持久准入记录已指向目标 Provider”时才删除；任何异常都保留 marker，使两侧都不可写（`algorithm_cutover.py:533-594`）。
  - marker 与正式维护窗口互斥，避免 legacy marker 覆盖未完成窗口（`:552-567`）。
  - 准入记录原子写 + 目录 fsync（`:620-642`）；`_admission_provider_is` 用“记录 + revoked 状态”而不是文件存在性证明目标权威（`:597-617`）。
  - 反向迁移需要证据评估：`assess_rollback` / `rollback`（`:645+`、`:918+`）。
  - 维护窗口有 phases 与 `recover_maintenance`（`:1458+`、`:1613+`、`:1651+`、`:1685+`、`:1869+`、`:2125+`）。
- 存储源（U2）有同构的切换协议，状态为 `CUTOVER_NOT_READY`（`docs/architecture/AI_DEVELOPMENT_HANDOFF.md:65,70,78`）。本文不复述其实现细节，也不声称它可用于任务域。

**拟议变更（不实施）**

任务域不能照抄“marker 就够”的方案，原因有代码依据：

1. 写入者是多进程多角色（§2），marker 只能挡住“检查 marker 的写者”；
2. 远端 Agent 的过期租约按设计**不**自动重排（`fenced_repository.py:464-479`），所以“等到没有 RUNNING 任务”可能永远等不到；
3. formal bulk 的阻塞态需要**人工复核**才能解除（`repository.py:1097-1141`），不是自动可清的空闲态。

因此拟议的切换协议必须是“排空 + 冻结 + 单写 + 对账”，见 §7。中断恢复规则：

- 冻结后、切换前中断：marker 存在，两侧都拒绝写入，运维执行 `abort`（撤销准入，对齐 `algorithm_cutover.py:732-912` 的 `revoke_admission` / `:918+` 的 `rollback` 语义）。
- 切换提交后、准入记录前中断：marker 保留，必须由“目标侧已提交 + 源侧无新写”的证据判定是 finish 还是 abort；不得只看文件是否存在。
- 回退：仅当目标侧**没有新写**时允许直接回旧 Provider；否则必须反向导出并对账（`F1:226` 的既有结论）。

### 3.9 历史 SQLite 任务如何保持兼容

**现有合同**

1. 版本号：`_SCHEMA_VERSION = 8`（`repository.py:33`）。
2. 打开即就地迁移（`:277-368`）：`user_version` 命中即快速返回（`:278-279`）；否则取 `FileLock`（`:280-283`）、校验不超前（`:289-292`）、强制 WAL（`:293-299`）、`executescript(SCHEMA)`（`:300`）、逐版本幂等补齐（`:305-368`），**最后**才推进 `user_version`（`:368`）。
3. 幂等性来源被明确写出：`executescript` 不是单事务，因此恢复依赖“每条语句幂等 + user_version 只在全部成功后推进”（`:301-304`）。
4. 加列用 `_add_column_if_missing`（`:223-243`），并且 `worker_instances` 的新列一次性补齐（`:347-364`）。
5. 版本超前直接拒绝：`RuntimeError("task repository schema {version} is newer than supported")`（`:289-292`）。这意味着**旧构建不能打开新库**——与素材库不同（素材库有 `MATERIAL_READ_SCHEMA_VERSIONS = frozenset({5,6,7,8})`，`material_repository.py:31`，并有 schema-5 夹具 `tests/fixtures/material_repository_schema5.sql`）。
6. Tombstone 参与读路径：发布确认与提交都会 join tombstone，以便“任务已被删除但发布已生效”仍能被证明（`repository.py:588-594,604-605`）；`deleted_task_identity` 明确只作审计查询、**不**作为可调度任务返回（`:1207-1212`）。
7. 旧删除路径：`record_legacy_deletion` 在事务内先确认任务不存在再写 tombstone（`repository.py:1226-1236`）。

**拟议变更（不实施）**

- 因为任务库**没有**只读旧版本模式，U5 不能采用“新旧双读”作为常规能力。拟议的双读仅限：
  - **审计只读**：切换后旧 SQLite 文件以只读方式保留，供对账与回放，不参与任何调度判断；
  - **回退只读**：只有目标侧被证明无新写时，旧文件才重新成为可写权威。
- Tombstone 必须迁移，且迁移后 `create()` 的 `TASK_ID_RETIRED` 语义不变。任何“tombstone 只是历史、可以丢弃”的方案都必须被拒绝：它会让已删除任务的身份被重新使用，并使 `_confirm_payload_publication` 的 tombstone join 失效。
- `user_version` 的“超前拒绝”语义必须在目标库以等价形式保留（例如显式 schema 版本行 + 拒绝启动），否则无法阻止旧构建写入新结构。

### 3.10 如何防止正式 GT（C2-B）任务被重复执行

**现有合同**

1. 任务种类：`TaskKind.ANNOTATION_FORMAL_BULK`（`models.py:27`）。
2. 通用终态/重试路径对它一律关闭：
   - `fail_queued_precondition` 带 `kind<>'ANNOTATION_FORMAL_BULK'`（`repository.py:1866`）；
   - `finish` 带 `kind<>'ANNOTATION_FORMAL_BULK'`（`:1925`）；
   - `retry` 带同样排除（`:2168`）；
   - Scheduler 对它的取消/失败/完成都另行处理（`scheduler.py:142-145,262-265,333-337`）。
3. 跨进程互斥：每任务一把文件锁，锁名 `sha256(task_id)`（`repository.py:1001-1004`），并在 GT 提交期间**持续持有**（`fenced_repository.py:148-177`，注释 “Keep only this task's cross-process lock through the GT commit”）。
4. 已准入批次的持久证据与身份校验：`formal_bulk_execution.active_batch` 存整批描述；重新进入时校验 `identity/operation_id/manifest_ref` 一致，且批次号只能是当前或当前+1，首批必须是 0（`fenced_repository.py:162-169`）。
5. 批次身份是确定性摘要：`batch_operation_id = digest(["bulk-formal-batch:v1", operation_id, manifest_digest, batch_number, ids])`（`annotation_bulk_commit.py:88-94`）。因此“同一批次重放”幂等，“不同批次冒充”被拒。
6. 完成证明只认回执 + 日志：`_proof_state` 同时读候选、GT、候选日志、GT 回执（`annotation_bulk_commit.py:98-108`），并显式拒绝“GT 属于另一个操作”（`:109-110`）；对账状态机 `complete/pending/journal_pending/unproven`（`:32-79`）。
7. 提交侧的幂等回执：`commit_candidate_decisions` 先用 `operation_id` 读已有回执，命中则按证据校验后转为“恢复”而不是重写（`annotation_task_service.py:812-819,893-909`）；`formal_write_barrier` 包住真正写 GT 的那一段（`:1061`）。
8. 自动重领有界：达到 5 次即写持久 blocked 账本，之后不再自动重排（`repository.py:1034-1082`）；账本损坏视为 blocked 而不是“无阻塞”（`:1006-1032`）。
9. 解除阻塞只能由运维复核后调用 `resume_blocked_formal_bulk`，它**从不**发布 SUCCEEDED、**从不**写 GT（`repository.py:1097-1141`）。
10. 零写入取消可被证明：仅当 `QUEUED` 且 `attempt=0` 且无 active batch 时直接 CANCELLED 并写 `zero_gt_proof`（`repository.py:1709-1735`）。

**拟议变更（不实施）**

- PostgreSQL 侧必须提供“跨进程、跨连接丢失仍有效”的互斥。拟议分两层：
  1. **持久层（权威）**：`active_batch` 的条件 UPDATE（CAS）+ 每批次唯一回执。这一层不依赖锁，崩溃后仍能判定；
  2. **加速层（非权威）**：`pg_advisory_xact_lock(hash(task_id))` 只用于减少冲突重试，**不得**作为“唯一执行者”的证明。
- 现有文件锁不得被直接删除：它同时挡住“读取 payload 与候选准备”的并发（`repository.py:1083-1085` 注释说明为何用 `timeout=0` 且在写者持锁时绝不等待）。拟议保留文件锁直到持久层证据被证明足以独立成立。

## 4. Owner / 表数据所有权地图

### 4.1 今天：SQLite（单文件，多类写入）

文件：`{DATA_DIR}/task_runtime/tasks.sqlite3`（`app.py:270`；`task_worker.py:119`）。

| 表 | 主键 / 自然键 | 关键索引 | 唯一写入 Owner（模块/类） | 迁移归属 |
|---|---|---|---|---|
| `tasks` | `task_id` | `idx_task_claim(status,priority,created_at,task_id)`；`idx_task_resource(resource_key,status,lease_expires_at)`；`idx_task_project_list`；`idx_task_claim_pipeline`；`idx_task_annotation_search_pending` | `TaskRepository` 及其子类（`repository.py:374-2247`） | **U5 核心** |
| `task_tombstones` | `task_id` | `idx_task_tombstone_project` | `delete_terminal` / `record_legacy_deletion`（`repository.py:1226-1278`） | **U5 核心（必须迁）** |
| `formal_bulk_execution` | `task_id` | 无（主键） | `FencedTaskRepository`（`fenced_repository.py:148-237`）+ `repository.py:1006-1141` | **U5 核心** |
| `annotation_task_statistics` | `task_id`（REFERENCES tasks） | 无 | `set_annotation_statistics`（`repository.py:667-707`） | U5（派生投影） |
| `worker_instances` | `instance_key` | `idx_worker_instances_expiry` | `WorkerInstanceService`（`worker_instances.py:146-308`） | U5（节点真值） |
| `execution_resource_holds` | `task_id` | 无 | `AgentExecutionService`（`agent_execution.py:1248-1287,3300-3392`） | U5（远端双槽） |
| `gpu_reservations` | `task_id`；`worker_slot` UNIQUE | `idx_gpu_reservations(gpu_uuid,expires_at)` | `GPUResourceManager.admit`（`gpu_resources.py:479-606`）+ 触发器 | U5（资源预留） |
| `gpu_inventory` / `gpu_samples` / `worker_gpu_visibility` | `(node_id,gpu_uuid)` / 自增 / `(worker_id,node_id,gpu_uuid)` | `:53-66` | `GPUResourceManager.refresh` / `sample_gpus`（`gpu_resources.py:250-450`） | U5（遥测，可后置） |
| `task_node_assignments` | `(task_id,generation)`；活跃唯一索引 `idx_task_node_assignment_active` | `:62-66` | `CentralTaskAllocator`（`task_node_assignments.py:981-1705`） | U5（中心分配） |
| `task_preemptions` | `(incoming_task_id,victim_task_id)` | `idx_task_preemptions_state` | `CentralTaskAllocator.preempt_for`（`:1040-1110`） | U5 |
| `inference_permits` | `(permit_id,domain)` | `idx_inference_domain_expiry` | `InferenceResourceMethods`（`inference_resources.py:34-99`） | U5（配额） |
| `inference_domain_state` | `domain` | — | 同上（`:101-113`） | U5 |
| `training_material_usage` / `_tokens` / `_coverage` / `_meta` / `_token_schema` | 见 `training_material_usage.py:43-61` | `training_usage_scope`、`training_usage_token_task` | `TrainingMaterialUsage`（`training_material_usage.py:84-260`） | **本文只登记；是否随 U5 由 §10 Q-2 决定** |

### 4.2 未来：PostgreSQL（同一批表，同一批键）

拟议（不实施）：单一 schema，表名、主键、唯一约束与上表一致；`FileLock` 类互斥改为“持久 CAS + advisory lock 加速”。DDL 属于后续独立变更，**不在本文批准范围**。

### 4.3 不迁移的部分（明确写死）

| 资产 | 位置 | 为什么不迁 |
|---|---|---|
| Payload/证据/回执/执行锚点 | `task_runtime/artifacts/{task_id}/...`（`artifacts.py:16-93`；`payload_publications.py:27-28`） | 内容寻址不可变文件，关系库不是它的正确载体（`F1:207`） |
| 任务日志 | `artifacts/{task_id}/logs/task.log`（`models.py:53`；`task_logs.py`） | 同上 |
| 候选/草稿 | 每任务 `candidates/items.sqlite3`（`F1:203`） | 任务级事务与回执，`F1:203` 已裁定可先保留 |
| 冻结选材清单 | `trainselection_*/selection.sqlite3`（`F1:205`） | 不可变证据；PG 只存引用与摘要 |
| 正式 GT | `annotations.sqlite3`（`annotation_repository.py:131,141`） | 属于 U3（`F1:202`） |

## 5. 任务状态机

### 5.1 状态集

持久状态来自 `TaskStatus`（`models.py:8-18`）：`QUEUED`、`RUNNING`、`AWAITING_CONFIRMATION`、`PARTIAL_SUCCESS`、`SUCCEEDED`、`CANCEL_REQUESTED`、`CANCELLED`、`FAILED`、`BLOCKED_BY_ENVIRONMENT`、`BLOCKED_BY_HARDWARE`。

终态集合在代码里显式定义（`repository.py:133-140`）：`PARTIAL_SUCCESS/SUCCEEDED/CANCELLED/FAILED/BLOCKED_BY_ENVIRONMENT/BLOCKED_BY_HARDWARE`。

对外的派生状态（**不是**持久状态，迁移不得当成列值）：`WAITING_RESOURCE`（QUEUED + stage `resource_waiting`）、`PAUSED`（RUNNING + stage `paused`）（`public.py:10-15`）。

### 5.2 迁移表（每个边都带守卫与 Owner）

| From → To | 守卫 | 实现（file:line） |
|---|---|---|
| ∅ → QUEUED | ID 未在 tombstone；插入不覆盖 | `repository.py:374-414`、`:417-435`（成对创建） |
| QUEUED → RUNNING | `status='QUEUED'` CAS + 语义字段一致 + 资源准入通过；`attempt+1` | `repository.py:1289-1378` |
| QUEUED → RUNNING（远端） | Assignment 已 `CLAIMED` + token 比对 + 节点在线 + 能力允许 + slot 可用；`attempt+1` | `agent_execution.py:1026-1288` |
| QUEUED → CANCELLED | 直接取消 | `repository.py:1746-1754` |
| QUEUED → CANCELLED（formal bulk 零写证明） | `attempt=0` 且无 active batch | `repository.py:1709-1735` |
| QUEUED → FAILED/BLOCKED_* | 仅 QUEUED，且非 formal bulk | `repository.py:1829-1887` |
| QUEUED → FAILED/BLOCKED_*（准备子任务失败） | 子任务终态 + 能力闸门 | `repository.py:1774-1827` |
| RUNNING → CANCEL_REQUESTED | 已持久取消；`finalizing_commit` 例外 | `repository.py:1755-1767` |
| RUNNING → AWAITING_CONFIRMATION | 合法 finish 状态之一 | `repository.py:1898-1907` |
| RUNNING → 终态 | `lease_token` 匹配 + 状态匹配（+ fenced 版：代次、未过期） | `repository.py:1889-1956`；`fenced_repository.py:323-382` |
| AWAITING_CONFIRMATION → SUCCEEDED/PARTIAL_SUCCESS | 评审完成；同值重放幂等，异值冲突 | `repository.py:1958-2013` |
| AWAITING_CONFIRMATION → QUEUED | 仅 MATERIAL_IMPORT（`accepted!=False`） | `repository.py:2015-2100` |
| AWAITING_CONFIRMATION → QUEUED（评审续跑） | 仅 AI_ANNOTATION / MATERIAL_BATCH | `repository.py:2102-2154` |
| AWAITING_CONFIRMATION → CANCELLED | 直接取消 | `repository.py:1746-1754` |
| RUNNING/CANCEL_REQUESTED → QUEUED | 租约过期 + 本地进程 `gone` + 非 formal bulk | `repository.py:1160-1179`；`fenced_repository.py:496-526` |
| RUNNING/CANCEL_REQUESTED → CANCELLED | 租约过期 + 已请求取消 | `repository.py:1163-1170` |
| RUNNING/CANCEL_REQUESTED → QUEUED（formal bulk，有界） | `attempt < 5` 且非 corrupt 且非 blocked | `repository.py:1034-1095` |
| 终态 → QUEUED | 通用重试，排除 formal bulk | `repository.py:2156-2177` |
| 终态 → QUEUED（AI 生成续跑，保留候选） | 仅 AI_ANNOTATION 且未评审 | `repository.py:2179-2217` |
| 终态 → AWAITING_CONFIRMATION（恢复候选） | 仅 AI_ANNOTATION | `repository.py:2219-2247` |
| 任意终态 → 删除 | 必须终态 + kind/project 匹配 + 写 tombstone | `repository.py:1238-1278` |

### 5.3 “阻塞阶段”不是状态（迁移必须保留这个设计）

以下 stage 值让任务**停在** `RUNNING`/`CANCEL_REQUESTED`，从而继续持有资源与所有权：

| stage | 含义 | 证据 |
|---|---|---|
| `recovery_blocked_remote_agent_unverified` | 远端可能仍在算，禁止重排/终态 | `repository.py:1150-1151`；`fenced_repository.py:470-477` |
| `lease_expired_process_alive` | 进程仍在 | `fenced_repository.py:483-486` |
| `recovery_blocked_process_inspection` | 无法证明 | `fenced_repository.py:490-493` |
| `cancelling_unverified` | 取消未证明停止 | `scheduler.py:189,203-212` |
| `formal_bulk_blocked` / `formal_bulk_attempt_limit` | 证据阻塞 / 达上限 | `repository.py:1061-1062` |
| `finalizing_commit` | 提交已裁定，取消不再生效 | `repository.py:1635-1643` |

## 6. 必须同事务的写路径

| # | 写路径 | 事务内必须一起提交的内容 | 证据 |
|---|---|---|---|
| 1 | 任务领取 | 过期回收 + 语义重校验 + 资源互斥判定 + 准入 + `gpu_reservations` 插入 + 任务 CAS（status/worker/lease/attempt）+ resource_waiting 标记 | `repository.py:1306-1373`；`gpu_resources.py:601-605` |
| 2 | 任务创建 | tombstone 检查 + 插入（+ 成对创建的两行） | `repository.py:399-414,427-434` |
| 3 | Payload 发布提交 | 父行 `payload_ref` 条件更新 + activation 字段更新（+ 幂等确认读） | `repository.py:596-656` |
| 4 | 任务取消（formal bulk） | `formal_bulk_execution.cancel_requested` + 任务状态更新 | `repository.py:1689-1772` |
| 5 | 终态提交裁定 | 取消与提交只能一方获胜 + stage 推进 | `repository.py:1585-1648` |
| 6 | 删除终态任务 | tombstone 插入 + `gpu_reservations` 删除 + 任务行删除 | `repository.py:1251-1277` |
| 7 | 过期回收 | 远端 hold 标记 + GPU 预留延长 + 本地重排/取消 + formal bulk 专属重排 + 过期预留清理 | `repository.py:1143-1200`；`fenced_repository.py:452-542` |
| 8 | 远端执行开始 | 任务 CAS + Assignment `CLAIMED→RELEASED` + Hold 插入 + 双槽冲突检查 | `agent_execution.py:1026-1288` |
| 9 | Worker 实例租约 | 查重 + 删除旧行 + upsert（同一事务） | `worker_instances.py:189-236` |
| 10 | 中心分配 | 生成 `generation=max+1` + 插入 Assignment（+ 抢占记录） | `task_node_assignments.py:1550-1597`、`:1040-1110` |
| 11 | formal bulk 批次准入 | `active_batch` upsert 必须在 GT 提交**之前**独立提交，并在 GT 提交期间持有文件锁 | `fenced_repository.py:148-177` |
| 12 | 训练历史登记 | `training_usage_*` 写入 + revision 触发器（与任务库同文件） | `training_material_usage.py:103-123` |

**注意**：`heartbeat`、`bind_process`、`set_stage`、`finish` 在 plain `TaskRepository` 里是**单条 UPDATE**（没有显式 `BEGIN`），事务边界等于语句边界（`repository.py:1409-1423,1438-1454,1467-1473,1908-1950`）。迁移时不能把它们“顺手”包进更大的事务，否则会改变锁持有时间（会直接影响 `sqlite_busy` 的既有预算，`sqlite_busy.py:35-66`）。

## 7. 迁移方案（六阶段，每阶段都有退出判据）

> 前置：U1/U2 的切换协议已验证；U5 单独授权；有排空窗口；有可回滚的备份。
> 全部阶段只在隔离环境执行。生产切换另需授权。

### 阶段 0：dry-run（不接触权威）

1. 从**只读快照**导出（不允许在线上库直接读——`tasks` 有高频写者）。
2. 导出内容与判定：`tasks`、`task_tombstones`、`formal_bulk_execution`、`worker_instances`、`execution_resource_holds`、`gpu_*`、`task_node_assignments`、`task_preemptions`、`inference_*`。
3. 产出“身份清单 + 计数 + 每行规范 JSON 摘要”。
4. 导入空 PostgreSQL，跑同一套校验脚本，输出 diff 报告。
5. **退出判据**：身份集合一致；计数一致；`tasks.attempt` 分布一致；tombstone 集合一致；`formal_bulk_execution.active_batch` 逐字节一致；历史 `payload_ref/result_ref` 抽样读回成功。
6. **失败即停**：任何差异都不允许进入阶段 1。

### 阶段 1：shadow（影子读，不写目标）

1. 目标库只读影子：用同一快照导入，按既有范式计算并保存 `snapshot_digest`（对齐 `algorithm_shadow.py:23-73,133-226,238-435`）。
2. 影子读对账：定时从源取“同一 revision/同一快照”再比较（`algorithm_shadow.py:681-705` 的 `reconcile` 语义）。
3. **退出判据**：连续 N 次对账 `same=true`；无 `SOURCE_REVISION_CHANGED`；差异报告为空。
4. 此阶段**不**写目标库，**不**改任何 Provider 选择。

### 阶段 2：freeze（停止领取，不停止写入终态）

1. 所有 Worker/Agent 停止领取（`Scheduler.service_stop` → `fence_active`，`scheduler.py:408-412,474-475`）。
2. 等待“可证明空闲”（定义见 §3.5 拟议变更）。此阶段**允许**在跑的任务继续心跳与提交终态。
3. 发布 transition marker（复用 `algorithm_cutover.py:533-594` 的 marker 语义：异常即保留、只有“目标已持久权威”才删除）。
4. **退出判据**：`status IN ('RUNNING','CANCEL_REQUESTED')` 为 0；所有阻塞 stage 为 0；marker 已持久。
5. **不允许**在还有 `cancelling_unverified` / `recovery_blocked_remote_agent_unverified` 时进入阶段 3——这些状态只能靠人工证据解除（`repository.py:1097-1141`；`fenced_repository.py:464-479`）。

### 阶段 3：switch（单写切换）

1. 最终增量导出（自阶段 0 快照以来的差异），并在事务内导入。
2. 写入准入记录（原子写 + 目录 fsync，对齐 `algorithm_cutover.py:620-642`），声明唯一权威 Provider。
3. 切换所有写入者构造点到目标 Provider（§2 的 6 个位置）。
4. 移除 marker（仅当准入记录已证明目标权威）。
5. **退出判据**：所有写入者进程报告的 Provider 一致；目标库可见阶段 2 之后的全部行；源库无新写（用 `updated_at` 高水位 + 行数双重证明）。

### 阶段 4：verify（读回与业务真值）

1. 任务 API 读回：`list`/`get`/`summary` 与切换前逐字段一致（`repository.py:658-918`；`public.py:18-67`）。
2. 终态真值：同一批任务的状态/进度/`result_ref` 与 artifact 读回一致（§3.7 抽样）。
3. formal bulk：`formal_bulk_execution_snapshot` 与 GT 回执/候选日志三方一致（`repository.py:979-999`；`annotation_bulk_commit.py:32-79`）。
4. 资源：`gpu_reservations`/`execution_resource_holds` 无孤儿、无跨节点重复。
5. 队列：`resource_queue_position` 与 claim 顺序抽样一致（`repository.py:752-828`）。
6. **退出判据**：以上全部通过 + 至少一个完整的“领取→心跳→终态”真实小任务在目标库上跑通（本地 Worker 与远端 Agent 各一）。

### 阶段 5：rollback（可执行、有条件）

见 §8。原则：只有“目标侧零新写”才允许直接回退；否则必须先反向导出 + 对账。

## 8. 回退条件（任一命中即必须回退或阻断）

| # | 条件 | 为什么不可继续 |
|---|---|---|
| R1 | 目标库出现 `task_id` 主键冲突或重复身份 | 身份唯一性已被破坏（§3.1） |
| R2 | 任一任务 `attempt` 回退或出现两个不同 `lease_token` 同时有效 | 代次单调是防双领的唯一依据（§3.2） |
| R3 | tombstone 集合与源不一致，或已删除 ID 可被重新创建 | 会让历史身份被复用（§3.1/§3.9） |
| R4 | `worker_instances` 出现两个未过期同 `instance_key` 行 | 节点真值分裂（§3.3） |
| R5 | `gpu_reservations` 出现与任务所有权不匹配的行，或 slot 唯一约束缺失 | 预留与租约不再同事务（§3.6） |
| R6 | formal bulk 的 `active_batch` 丢失或与 GT 回执不一致 | 可能重复写正式 GT（§3.10） |
| R7 | 任一终态任务的 `result_ref` 无法读回（摘要不符/缺失） | 结果真值不可证明（§3.7） |
| R8 | 目标侧在阶段 3 之后出现任何新写，却要求回退 | 需先反向导出（`F1:226`） |
| R9 | marker 存在但准入记录的 Provider 与“实际写入者”不一致 | 中断窗口未收敛（§3.8） |
| R10 | 旧构建（schema 版本认知落后）可能连到目标库 | `user_version` 超前拒绝语义会导致启动失败或数据损坏（§3.9） |

回退动作的最小集合（拟议，不实施）：

1. marker 保留、两侧拒绝写入；
2. 证明目标零新写，或反向导出并对账；
3. 准入记录改回源 Provider；
4. 旧 SQLite 恢复为可写权威；
5. 复核 §8 R1–R7 的反向版本（tombstone、attempt、预留、formal bulk）。

## 9. 测试矩阵

> `EXISTING` = 本仓库已有测试（文件已确认存在）；`PROPOSED` = 尚未实现。
> 本表**不**声称任何 PROPOSED 项已存在。

| # | 层 | 覆盖点 | 状态 | 依据 / 拟议落点 |
|---|---|---|---|---|
| T1 | unit | claim CAS、`attempt+1`、语义重校验、资源 busy 拒绝 | EXISTING | `tests/unit/task_runtime/test_repository.py`、`test_resource_fencing.py` |
| T2 | unit | 过期回收：本地重排、取消转终态、远端 hold、GPU 预留保留 | EXISTING | `tests/unit/task_runtime/test_fencing.py`、`test_gpu_recovery_fencing.py` |
| T3 | unit | 代次栅栏：`assert_execution`/`finish`/`heartbeat` 拒绝旧代次 | EXISTING | `tests/unit/task_runtime/test_fencing.py`、`test_control_stage_fencing.py` |
| T4 | unit | 进程真值三态（alive/gone/unknown）与 PID 复用 | EXISTING | `tests/unit/task_runtime/test_process_control.py`、`test_fencing.py` |
| T5 | unit | Worker 实例租约：重复拒绝、过期接管、renew 不可复活 | EXISTING | `tests/unit/task_runtime/test_worker_runtime_truth.py`、`test_worker_instance_connection_lifecycle.py` |
| T6 | unit | schema 迁移幂等、超前版本拒绝、加列 | EXISTING | `tests/unit/task_runtime/test_repository.py` |
| T7 | unit | tombstone 禁复用、删除终态、发布 tombstone join | EXISTING | `tests/unit/task_runtime/test_repository.py` |
| T8 | unit | Payload 发布幂等：`ALREADY_APPLIED`、摘要校验、`operation_id` 冲突 | EXISTING | `tests/unit/task_runtime/test_artifacts.py`、`test_artifact_fencing.py` |
| T9 | unit | Scheduler 排空与 fail-closed 续租 | EXISTING | `tests/unit/task_runtime/test_scheduler.py` |
| T10 | unit | SQLite busy 下的自断与不误判失败 | EXISTING | `tests/unit/task_runtime/test_sqlite_busy_recovery.py` |
| T11 | integration | 双 Agent HTTP 回环、双槽、启动/停止/完成响应丢失 | EXISTING | `tests/integration/test_two_agent_http_loopback.py`、`test_agent_dual_slot_http_e2e.py`、`test_formal_training_runner_http_e2e.py` |
| T12 | integration | 真实进程崩溃恢复（远端） | EXISTING | `tests/integration/_real_agent_crash_recovery_support.py` |
| T13 | api | formal bulk：同批幂等、跨批顺序、崩溃续跑、外部 GT 变更、阻塞不自动重排、零写取消、阻塞取消对账 | EXISTING | `tests/api/test_ai_review_workbench.py`（如 `test_bulk_formal_execution_start_is_idempotent_and_concurrent`、`test_formal_bulk_permanent_block_stops_requeue_and_needs_reverified_resume`、`test_formal_bulk_queued_cancel_is_proven_zero_write`、`test_formal_bulk_gt_barrier_serializes_independent_worker_and_cancel`） |
| T14 | api | 中心调度 API 的分配/释放 | EXISTING | `tests/api/test_central_scheduler_api.py` |
| T15 | performance | claim 流水线、热路径预算 | EXISTING | `tests/performance/test_platform_hot_paths.py` |
| P1 | unit（目标侧） | 同一套 T1–T10 在 PostgreSQL Provider 上重跑，断言不变 | PROPOSED | 需新增 Provider 抽象与双实现 |
| P2 | real PostgreSQL | 两个并发领取者对同一 `QUEUED` 行只能有 1 个成功，且失败方不得改写 | PROPOSED | 需真实 PG（对齐 `tests/integration/test_storage_source_postgres.py` 的既有做法：真实 service + 禁 skip） |
| P3 | real PostgreSQL | 旧持有者在锁释放后写入被代次/lease 谓词拒绝 | PROPOSED | 同上 |
| P4 | real PostgreSQL | 预留与租约同事务：准入失败不得留下 `gpu_reservations` 行 | PROPOSED | 同上 |
| P5 | real PostgreSQL | 事务中断（COMMIT 前异常）后无半成品行；COMMIT 后进程终止可恢复 | PROPOSED | 同上 |
| P6 | process-crash | Worker 被强杀：租约过期后回收可证明、GPU 预留不提前释放 | EXISTING（本地）/PROPOSED（远端多节点） | 本地：`test_sqlite_busy_recovery.py`、`test_scheduler.py`；远端多节点：未实现 |
| P7 | process-crash | 切换窗口内强杀（marker 保留、两侧拒写、可恢复） | PROPOSED | 需先有 marker + 准入记录 |
| P8 | real PostgreSQL | formal bulk 双执行者：文件锁缺席时仅靠持久 CAS 仍只有一方能写 GT | PROPOSED | 需先实现 §3.10 拟议的两层互斥 |
| P9 | 对账 | 影子快照 digest 与 `reconcile` 差异报告 | PROPOSED（范式 EXISTING） | 范式见 `algorithm_shadow.py`；任务域实现未开始 |
| P10 | 回退 | §8 R1–R10 的每条都有可执行且可判定的检测 | PROPOSED | 未实现 |

## 10. 未决问题（需要 lead 决策，禁止靠猜推进）

- **Q-1 心跳续租时长口径**：plain `TaskRepository.heartbeat` 硬编码 30 秒（`repository.py:1390`），fenced 版可配置（`fenced_repository.py:248`）。迁移前必须决定“目标语义是哪一个”，否则 PG 下会出现与本地不一致的过期窗口。
- **Q-2 `training_material_usage` 归属**：它物理上在 `tasks.sqlite3`（`training_material_usage.py:28`），业务上属于训练历史，迁移单元在 `F1:202-204` 中未明确归属 U3 还是 U5。需要决策，且该表带 revision 触发器（`training_material_usage.py:63-70`），归属不同会影响切换窗口的长度。
- **Q-3 Provider 可观测点缺失**：今天没有“本进程正在用哪个任务库 Provider”的运行时探针（§2 的 6 个构造点各自持有实例）。冻结与验证都需要它。本文不提出实现，只登记缺口。
- **Q-4 finish 语义分叉**：plain 版 `finish` 不校验“租约未过期”（仅对 agent 前缀校验，`repository.py:1926-1933`），fenced 版校验（`fenced_repository.py:359`）。哪一个是权威语义需要 lead 裁定；两者在现状下都可达。
- **Q-5 远端 Agent 排空不可能自动完成**：`recovery_blocked_remote_agent_unverified` 需要外部证明（`fenced_repository.py:464-479`）。需要决定“排空窗口内是否允许遗留此类任务并把它们随库迁移”，以及迁移后由谁继续承担该证明。
- **Q-6 formal bulk 阻塞态的迁移策略**：`formal_bulk_blocked` / `formal_bulk_attempt_limit` 的任务迁移后是否需要重新人工复核（`repository.py:1097-1141`）。若答案是“需要”，则切换窗口内必须把它们清零。
- **Q-7 是否允许“旧库只读审计”长期存在**：§3.9 拟议只允许审计只读。若 lead 要求更长保留期，需要明确“谁有权打开它、以什么方式、如何防止被误当权威”。

## 11. 证据索引（按文件）

- `platform_core/task_runtime/models.py`：`:8-18` 状态；`:21-35` 种类；`:43-70` 记录字段；`:51-53` ref 语义；`:95-101` 租约。
- `platform_core/task_runtime/repository.py`：`:33` schema 版本；`:38` formal bulk 上限；`:44-130` DDL；`:133-140` 终态；`:223-243` 加列；`:277-368` 迁移；`:374-414` 创建；`:417-435` 成对创建；`:473-507` 绑定；`:525-656` 发布；`:752-828` 队列位置；`:979-1141` formal bulk；`:1143-1200` 过期回收；`:1202-1278` tombstone/删除；`:1289-1378` 领取；`:1380-1479` 心跳/进程/阶段；`:1585-1772` 终局裁定/取消；`:1774-1887` 准备收尾/预条件失败；`:1889-2013` 终态/评审；`:2015-2247` 恢复路径。
- `platform_core/task_runtime/fenced_repository.py`：`:29-41` 代次；`:43-105` 领取；`:107-126` 断言；`:128-237` formal bulk 栅栏/进度；`:238-382` 心跳/进程/终态；`:398-431` 预留保持/三态；`:443-542` 过期回收；`:544-581` 精确清理。
- `platform_core/task_runtime/worker.py`：`:22-39` 租约操作；`:56-120` 栅栏化 artifact；`:151-230` 上下文/代次/断言/心跳；`:370-401` 终止与取消；`:403-415` checkpoint。
- `platform_core/task_runtime/scheduler.py`：`:56-77` 续租；`:109-116` 清理前置；`:131-219` 取消与清理；`:284-399` run_once；`:401-488` serve_forever。
- `platform_core/task_runtime/worker_instances.py`：`:27-41` key；`:60-69` 死亡判定；`:150-308` 获取/续租/释放。
- `platform_core/task_runtime/artifacts.py`：`:16-21` 根；`:68-93` 路径安全；`:95-121` 原子 JSON；`:138-156` 删除保留。
- `platform_core/task_runtime/payload_publications.py`：`:1-6` 边界；`:23-29` 协议/ref；`:83-122` 身份/operation_id；`:284-341` 不可变发布/读校验；`:343-368` 证据/锚点；`:370-431` 回执/准备。
- `platform_core/task_runtime/inference_resources.py`：`:17-31` 表；`:34-99` 许可。
- `platform_core/task_runtime/sqlite_busy.py`：`:19-25` busy 识别；`:35-66` 预算。
- `platform_core/gpu_resources.py`：`:24-90` 表与触发器；`:471-606` 准入；`:608-619` 分配读取。
- `platform_core/task_node_assignments.py`：`:45-90` 表；`:981-1111` 分配器；`:1550-1705` 分配/释放/领取；`:1708-1735` 分配感知仓库。
- `platform_core/agent_execution.py`：`:60-69` 代次 ref；`:892-1319` 开始执行；`:3217-3397` 停止证明；`:3399-3443` 资源等待；`:3539-3634` 结束。
- `platform_core/annotation_bulk_commit.py`：`:15-16` 批次常量；`:32-152` 证据状态机；`:155-246` Worker 绑定/取消对账；`:329-436` 批次执行。
- `platform_core/annotation_task_service.py`：`:722-729` 操作 ID/回执；`:812-819` 幂等回放；`:1061` 写栅栏。
- `app.py:270`、`task_worker.py:119,158-168,246-263`、`worker_supervisor.py:85-152`：写入者装配。
- `docs/architecture/F1_PERFORMANCE_AND_MIGRATION_DESIGN_20261122.md:202-226`：U5 定位与 Provider 兼容层要求。
- `docs/architecture/AI_DEVELOPMENT_HANDOFF.md:14,18`：U3/U5 状态。
