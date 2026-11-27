# U3-P3-A 增量同步前置准备（2026-11-28）

> 本文只记录**现有代码对应的事实**与 P3-B 的最小实施合同；本轮不新增 Change Log Schema、
> 不写同步 Worker、不建队列/定时任务/清理任务、不启用生产开关、不改 VERSION。

## 1. Owner 写入入口（影响 Picker 投影的路径）

### Material — `platform_core/material_repository.py`

| 入口 | 事务 | 版本效果 | 幂等/围栏 |
|---|---|---|---|
| `upsert` / `upsert_many` | 单 SQLite 写事务 | `material_meta.revision` +1；内容变化时 `evidence_generation` +1（触发） | 主键 + `INSERT OR REPLACE`；`material_annotation_lifecycle_fence` 外层的导出/GT 写入 |
| 删除/退役（删除 claim、`material_retirements`） | 单写事务 | revision +1；`evidence_generation` +1（触发） | `_dataset_delete_claim`/`_material_batch_delete_claim`、retirement 记录 |
| 标签/标注范围（`material_labels`、`material_annotation_scopes`） | 单写事务 | revision +1 | 主键覆盖 |
| 存储源变化（`material_storage_audit`/字段更新） | 单写事务 | revision +1；审计行插入 bump evidence | 审计 `id` 唯一 |
| 证据写入（`material_migrations`/`material_storage_audit`/`material_retirements`/`material_cleanup_deferred`/`material_assignment_receipts`/`negative_pool_operations`） | 与业务写同事务 | `evidence_generation` +1（每表触发器） | 各自主键/操作键 |

### Annotation — `platform_core/annotation_repository.py`

| 入口 | 事务 | 版本效果 | 幂等/围栏 |
|---|---|---|---|
| `save_annotation`（GT 新增/更新/覆盖） | `BEGIN IMMEDIATE` + `material_annotation_lifecycle_fence` | `annotation_meta.revision` +1；证据 generation（`annotation_delete_backup` 等）触发 | 版本 CAS（调用方校验 `version`）；引用表重建 |
| GT 删除/回滚（`annotation_delete_backup`） | 同事务 | revision +1；证据 generation +1 | 备份行 |
| 标注范围变化 | 随 GT 写入 | revision +1 | — |
| `commit_candidate_decisions` / candidate commit | 单写事务 | revision +1；`annotation_candidate_commits` 触发 | 候选 ID 幂等 |
| negative review | 单写事务 | revision +1；`negative_reviews` 触发 | 审核键 |
| `confirm_task_negatives` | `material_annotation_lifecycle_fence` + `BEGIN IMMEDIATE` | `task_negative_confirmations` 行；`task_negative_confirmation_generation` +1（触发器）；证据 generation +1 | `receipt_id` 主键 + `INSERT OR IGNORE`（幂等） |

### Negative Pool — `platform_core/negative_pool.py`

| 入口 | 事务 | 版本效果 | 幂等/围栏 |
|---|---|---|---|
| `members` / `categories` / `links` / `algorithm_scope` 变更 | 单写事务（`_mutate`） | `negative_pool_meta.revision` +1；`negative_pool_operations` 触发 evidence generation | `operation_id` + `operation_kind` + 原始 `expected_revision` 幂等重放 |

**共性**：所有入口都在各自 SQLite 文件的单事务内完成业务写 + 版本/证据触发更新；没有跨库双写；
导出/导入额外持有 `material_annotation_lifecycle_fence` 防止导出期间写入。绕过统一入口直接
`sqlite3` 写文件不属于受支持路径（P0 导入会以 revision/digest/structure 门禁拒绝）。

## 2. Change Log 合同（P3-B 实施约束）

1. 每个 Owner 文件新增 `owner_change_log(stream, sequence, event_kind, entity, tombstone_json, payload_digest, schema_version)`；
   与业务写**同一 SQLite 事务**提交，业务回滚则日志回滚。
2. `stream` = `materials` / `annotations` / `negative_pool`；`sequence` 每流单调递增，
   由流内 `meta.change_sequence` 在事务内自增，不依赖毫秒时间戳。
3. `event_kind` ∈ `insert|update|delete`（或等价）；delete 必须写 tombstone（主键 + 删除原因 +
   原 revision/generation），供 PG 删除与幂等重放。
4. 每条事件携带 `payload_digest`（该实体投影内容的规范化摘要）与 `schema_version`；
   重放时同 `(stream, sequence)` 且摘要相同即幂等跳过，摘要不同即 `DIVERGED` 拒绝推进。
5. 多 Owner 之间**无全局顺序**；PG 消费按流独立推进，`u3_projection_cursor` 复用现有表，
   每个流一个游标，事务内“应用事件 + 推进游标”一起提交（不推进未完成数据）。
6. `revision_vector`/`picker_snapshot_state` 继续由现有 P0 导入产生，不重造；增量消费完成一批后
   由导入路径更新 revision/generation 与状态。

## 3. 初始化与增量衔接

1. 初始完整快照：现有 `export_project_snapshot` / `import_project_snapshot`（READY）。
2. 导出开始时记录各流 high-water mark（`change_sequence`），导出期间新写入会进入日志。
3. 快照发布后，增量从 high-water mark+1 开始消费；若某流尚无日志（老项目），先执行一次
   “基线事件”（把当前投影视为 insert），或直接以完整重建建立基线。
4. 老项目没有历史事件：允许 `u3_projection_cursor` 从基线位置起步；禁止把“无日志”当作
   “无数据”。
5. 重复消费：幂等键 `(stream, sequence)`；游标只在事务成功后推进。
6. 缺口/无法恢复：`sequence` 不连续或摘要不一致 → 停止增量，走受控完整快照重建；
   不允许清空整个 PG 投影来掩盖异常（P0 旧快照/证据保留合同继续有效）。
7. 中断：Worker 崩溃时 PG 事务回滚，游标不前进；SQLite 日志保留，重启后重放。
8. 失败恢复：SQLite Owner 不可用 → 暂停；PG 不可用 → 重试有界后暂停；两者都不修改 Owner 数据。
9. 日志保留：P3-B 只追加；清理需要独立授权（保留窗口 ≥ 最长快照重建周期）。

## 4. 最小实施范围（P3-B 建议）

1. 三个 Owner 的 `owner_change_log` DDL + 事务内追加函数（各一个，复用现有 `_mutate`/写事务）。
2. 每流 `change_sequence` 与 high-water mark 读取 API（只读）。
3. 一个无 Worker 的 `apply_change_batch(connection, stream, events)` 纯函数 + 单测。
4. `u3_projection_cursor` 复用与“应用+推进同事务”封装。
5. 完整重建入口复用现有导入；缺口检测 → 重建标志。
6. 暂不做：消息队列、定时器、自动清理、生产开关、跨库双写。

## 5. 明确未做

本轮未新增 Schema/表、未实现 Worker/队列/定时同步、未改 Owner 写入路径、未改 VERSION；
P3-B 代码需在 P2 审计通过后另行授权。

## 6. 审计补充合同

1. **事件 payload 与摘要**：事件只写实体主键、`event_kind`、`tombstone_json`（delete）与
   `payload_digest`；完整实体内容仍以 Owner 行为准。消费者按 `payload_digest` 幂等比对，实体后续
   变化产生新的 `(stream, sequence)`，不复用旧摘要。
2. **基线与 high-water mark 同快照**：初始化快照必须在**同一 SQLite 只读事务**内读取各流
   `change_sequence`，导出数据也来自该事务；发布 READY 后增量从 `hwm+1` 开始消费，避免“导出期间
   写入丢失”。
3. **跨流依赖与 READY**：`picker_snapshot_state.status=READY` 仍由完整导入产生；增量消费不得在
   流未对齐（如 GT 先于其素材、确认先于其 GT）时推进全局 READY，按流独立游标 + 依赖检查，
   任一依赖缺失即暂停并保留旧 READY 快照。
4. **幂等/缺口/失败/重建**：`(stream, sequence)` + 摘要幂等；序缺口、摘要不一致或 Owner 结构
   未认证 → 停止增量、标记重建；重建复用现有完整导出/导入，不清空 PG 投影掩盖异常；Owner 数据
   永不因同步失败被修改。
