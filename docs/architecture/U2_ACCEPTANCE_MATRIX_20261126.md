# U2 存储源迁移验收矩阵（2026-11-26，多工作流批次）

本批次起点 `2bc8a01f40339924830b5563c4c73517abad7008`。VERSION 42.24.592 未改，`STORAGE_SOURCE_PROVIDER` 仍默认 sqlite，**未做任何生产切换**。

本文件只陈述代码与已执行验证的真实状态，四类标签含义：

- `CODE_COMPLETE`：实现存在且定向测试通过。
- `CI_VERIFIED`：在 GitHub Actions 真实 PostgreSQL 服务容器中执行通过。
- `NOT_IMPLEMENTED`：尚未实现。
- `PRODUCTION_NOT_VERIFIED`：没有任何生产环境证据。

## 1. 验收矩阵

| 要求 | 状态 | 证据（代码 / 测试） |
|---|---|---|
| 真实 PostgreSQL 集成 | CODE_COMPLETE | `tests/integration/test_storage_source_postgres.py`；`storage-cache-governance.yml` 的 `storage-source-postgres` Job（postgres:16 service，JUnit 无 skip 守卫） |
| SIGKILL 进程恢复（3 个窗口） | CODE_COMPLETE | 同上文件 `test_sigkill_*` 三项 + `tests/integration/_storage_source_crash_probe.py`（真实子进程自终止，非异常注入） |
| 正向切换（SQLite → PostgreSQL） | CODE_COMPLETE | `storage_source_cutover.admit_cutover`：切换锁、marker、单顶层事务、generation、原子准入记录 |
| 反向回滚（PostgreSQL → SQLite） | CODE_COMPLETE | `rollback_cutover` + `storage_source_migration.import_snapshot_sqlite`；覆盖切后 create/update/delete 再回滚、SQLite 越权更新拒绝、中断恢复 |
| 中断恢复（异常注入） | CODE_COMPLETE | 提交前 / 提交后记录前 / 记录后 marker 前三种窗口；`abort_cutover` / `finish_cutover` 分派 |
| generation 单调 | CODE_COMPLETE | `_next_generation` = max(本地记录, durable)+1，advisory 事务锁内读取；正向、回滚、回滚后再正向三处断言 |
| 引用保护 | CODE_COMPLETE（合同） | `delete_supported` 默认 False；开启后仍要求完整证据：`source_revision` 当前值、材料引用 0、模型产物引用 0、物理退役 `RETIRED` + proof；`tests/unit/storage/test_storage_source_provider.py::test_delete_requires_complete_cross_domain_evidence` |
| 双 Provider fail-closed | CODE_COMPLETE | 未知/缺失 Provider 无效记录；marker/SWITCHING/ROLLBACK_APPLIED 均阻断；`cutover_status` 报 `INCONSISTENT` |
| 真实跨域删除（素材 + 产物 + NAS/OSS/S3 退役） | NOT_IMPLEMENTED（仅合同与证据校验） | 证据由其他 Owner 提供；本批次**没有**实现素材/产物引用收集器，也没有实现对象存储退役探测。因此生产上仍无法完成删除。 |
| 生产切换 | PRODUCTION_NOT_VERIFIED | 未启用 Provider、未迁移真实数据、未操作 NAS/OSS/S3 |

## 2. 反向回滚协议（实际实现）

1. `require_idle_connection`：调用者事务未结束即拒绝（绝不把 `transaction()` 变成 SAVEPOINT）。
2. 切换锁（`<storage>/.storage-source-switch.lock`，与所有 SQLite 写者同一身份）内：
   1. 校验本地记录为已发布 PostgreSQL 准入，且状态为 `STEADY_POSTGRES`；
   2. 原子发布转换 marker（两侧写入立即阻断）；
   3. 单个顶层事务：advisory 锁 → `cutover_state FOR UPDATE` 校验 admission_id/generation/phase → 置 `SWITCHING`（冻结 PostgreSQL，等在途写者释放行锁）；
   4. 单个只读事务导出 PostgreSQL 快照（禁止隐式事务）；
   5. `import_snapshot_sqlite`：单 SQLite 事务内 upsert + 删除快照中不存在的行 + 原子切换默认源；若 SQLite 行 revision 更新则拒绝（证明切换后本地被改写）；
   6. 重新导出 SQLite 并与 PostgreSQL 快照对账，必须 `same`；
   7. 单个顶层事务把 durable 状态置 `ROLLBACK_APPLIED`、generation+1、写入双方摘要；
   8. `IDLE` 校验后原子写本地 SQLite 准入记录（provider=`sqlite`）；
   9. 删除 marker。
3. 失败恢复：durable 发布前失败 → 恢复 `POSTGRES_ACTIVE` 并删除 marker（PostgreSQL 仍是权威）；durable 发布后失败 → 保留 marker，`finish_cutover` 依据 durable 行重建本地记录；`abort` 在 durable 冻结时要求连接以恢复 `POSTGRES_ACTIVE`，否则拒绝（不猜测）。

## 3. SIGKILL 验证的真实含义

- 探针子进程在三个精确协议点自终止：PostgreSQL 提交前、提交后本地记录前、本地记录后 marker 删除前。
- 父进程用**全新连接**与磁盘状态验证：durable 行、marker、准入记录、两侧写入权限、generation 单调、重新准入不重复导入。
- 与异常注入的区别：异常注入会执行失败清理分支；SIGKILL 不执行任何清理，因此保留的是"崩溃后磁盘真实状态"。两种状态都要求可恢复，测试分别覆盖。
- Windows 上探针以 `TerminateProcess`（`SIGTERM` 语义）终止，POSIX 上为 `SIGKILL`；CI 在 Linux 执行。

## 4. 明确未完成

- 跨域删除：缺素材/产物引用收集器与对象存储退役探测（合同已存在，证据来源未实现）。
- 生产级演练：未在任何真实部署上执行正向切换或回滚。
- 回滚期间的 PostgreSQL 新写：通过 `SWITCHING` 冻结阻断，但没有"部分回滚后继续正向"的自动化决策；未知状态一律要求人工选择 `finish` 或 `abort`。
- U3/U5 未启动。
