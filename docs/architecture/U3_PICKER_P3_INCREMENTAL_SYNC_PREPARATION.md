# U3-P3-A 增量同步前置准备（2026-11-28）

> 本文记录现有代码对应的事实、P3-B 实施合同及 B1–B4 实际落地情况。P3-B1/B2 先落地，
> B3/B4 在 B1/B2 独立审计收口后实施；未启用生产 Picker 读取。

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
| `upsert_many` / `upsert`（GT 新增/更新/覆盖） | `BEGIN IMMEDIATE` + `material_annotation_lifecycle_fence` | `annotation_meta.revision` +1；证据 generation 触发 | 版本 CAS（调用方校验 `version`）；引用表重建 |
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

P3-A 本身未新增 Schema/表、未实现 Worker/队列/定时同步、未改 Owner 写入路径、未改
VERSION。P3-B1/B2/B3/B4 的实施见第 8–12 节；生产 Picker 读取仍未启用。

## 6. 审计补充合同

1. **事件 payload 与摘要**：事件必须携带完整投影快照及 `payload_digest`；实体后续变化产生新的
   `(stream, sequence)`，不复用旧摘要。
2. **基线与 high-water mark 同快照**：初始化快照必须在**同一 SQLite 只读事务**内读取各流
   `change_sequence`，导出数据也来自该事务；发布 READY 后增量从 `hwm+1` 开始消费，避免“导出期间
   写入丢失”。
3. **跨流依赖与 READY**：`picker_snapshot_state.status=READY` 仍由完整导入产生；增量消费不得在
   流未对齐（如 GT 先于其素材、确认先于其 GT）时推进全局 READY，按流独立游标 + 依赖检查，
   任一依赖缺失即暂停并保留旧 READY 快照。
4. **幂等/缺口/失败/重建**：`(stream, sequence)` + 摘要幂等；序缺口、摘要不一致或 Owner 结构
   未认证 → 停止增量、标记重建；重建复用现有完整导出/导入，不清空 PG 投影掩盖异常；Owner 数据
   永不因同步失败被修改。

## 7. 事件内容与 READY 原子发布（最终收口）

1. **不可变投影事件**：事件必须携带该实体的**完整投影快照**（material/GT/pool 行的规范化
   字段 + `payload_digest`），而不是只带主键或“旧摘要”。消费者按 `(stream, sequence)` 写入
   事件所描述的那一版实体；实体后续变化会产生更高 sequence 的新事件，禁止用旧摘要去读取已
   变化的实体。
2. **增量期间的可见性**：消费批次在 PG 事务内应用事件并推进该流游标；批次提交前
   `picker_snapshot_state.status=STALE`（或保留旧 READY 但不得改变其 `snapshot_id` 指向的内容）。
   只有所有流游标与 `revision_vector` 对齐、依赖检查通过后，才在同一事务内发布新的 READY
   身份；禁止“旧 READY 身份指向已变化的投影”。
3. 保持：每 Owner 同事务日志、单调 sequence、tombstone、幂等重放、缺口检测与完整重建；
   增量失败不改 Owner，不用清空投影掩盖异常。

## 8. P3-B1 已实施（`platform_core/u3_owner_change_log.py`）

1. 每个 Owner 数据库新增 `owner_change_log` / `owner_change_meta`；`materials.sqlite3`
   承载 `materials` 与 `negative_pool` 两个独立 sequence，`annotations.sqlite3` 承载
   `annotations`。事件表为 append-only（UPDATE/DELETE 触发器拒绝）。
2. `append_events` 在调用方现有 `BEGIN IMMEDIATE` 事务内分配连续 sequence、计算并持久化
   `payload_digest` 与 envelope `event_digest`；业务回滚时日志与 sequence 一起回滚。
3. 事件 payload 是写入事务内生成的完整投影快照：material 含行字段、payload、labels、
   annotation_scope；annotation 含 boxes/scope 与 `annotation_label_references`；
   negative pool 含 member/links/algorithms 或 category；确认回执与历史证据事件独立携带
   原表行内容。删除/退役/移除写 tombstone，后续实体变化不会重写旧事件。
4. 实际写入入口：`MaterialRepository._write_row` / `remove` / `retire_many` /
   `reconcile_storage_batch` / `record_*` / assignment receipts、batch 模块的
   `_persist_batch` 与批量 remove/mutate、`NegativePool._mutate`（members/category/
   restore）及 `AnnotationRepository.upsert_many` / `confirm_task_negatives` /
   delete/restore/remove。旧库由 `_initialize` 幂等补建，P0 证据结构认证不变。
5. 明确未做：没有 Worker、队列、定时器、自动清理、生产开关。

## 9. P3-B2 已实施（`platform_core/u3_incremental_sync.py`）

1. `apply_incremental_batch(connection, project_dir=..., project_id=..., stream=...,
   limit=...)` 按流读取 `sequence > cursor` 的有界事件，校验 project/stream/schema/
   digest/实体身份与连续性。
2. 一个 PostgreSQL 事务内：将既有 READY 标记为 STALE、应用 material/annotation/
   confirmation/negative-pool/evidence 事件、写 `u3_applied_owner_event`、推进
   `u3_projection_cursor`。任一步失败整批回滚，SQLite Owner 不被反向修改。
3. 已处理幂等重放（同 sequence 同 digest 跳过）、同身份摘要冲突拒绝、sequence 缺口拒绝、
   旧 annotation 事件不覆盖更高 version、删除 tombstone 与项目隔离。
4. 新增 B2-only 表 `u3_applied_owner_event` 仅保存消费摘要凭据；未改历史迁移/P0 表。
5. 未实现自动 Worker、定时同步、队列、自动重建或生产读取切换。

## 10. P3-B3 已实施：基线、依赖与 READY 发布

1. `export_project_snapshot` 在每个物理 SQLite 库的既有固定读事务内读取
   `owner_change_meta`，输出 `change_high_water_marks`、`change_log_present` 和
   `baseline_id`；同一库的 `materials`/`negative_pool` 两流共用一次读取。导出后再次读取
   revision/evidence generation/证据结构/高水位，任一变化即拒绝快照。
2. 全量导入在同一事务内写业务行、`picker_snapshot_state`、`u3_projection_cursor`
   （`last_applied_seq=HWM`）及新增 `u3_projection_baseline`；导入失败四者一起回滚。
   无 Change Log 的老项目记录 `present=false`、HWM 0，仍以完整快照建立可信基线。
3. `apply_incremental_batch` 要求存在 baseline；无 baseline 不再默认从 0 消费。
   Owner 高水位与事件读取在同一 SQLite 只读事务；`read_events` 为空但 HWM 领先时
   返回 `U3_INCREMENTAL_LOG_TAIL_MISSING`，不把日志尾部缺失当作追平。
4. 增量消费、完整导入、READY 发布、受控重建共享 `u3_import:{project_id}` PG
   advisory transaction lock；游标推进使用 `GREATEST`，不倒退。
5. `publish_ready` 在生命周期围栏内重新导出 Owner 快照，要求三流 baseline/cursor
   与 HWM 对齐，使用现有 `reconcile`/`read_target_snapshot` 校验投影、证据和关联；
   确认回执必须能解析到对应 annotation。随后在同一 PG 事务中写 READY 状态、
   `snapshot_id`、`content_digest`、revision_vector、`store_revision` 和发布账本。
   任一步失败保持 STALE 或旧 READY 身份，不部分发布。
6. `diagnose_project` 只读返回状态、快照身份、各流 Owner HWM/游标/待消费差值、
   gap 及 `needs_rebuild`；Owner 不可用返回 `UNAVAILABLE`，不报告积压 0。

## 11. P3-B4 已实施：恢复、重建与诊断

1. `apply_incremental_batch` 的“事件应用 + applied 记录 + 游标推进”仍在同一 PG
   事务；`u3_applied_owner_event` 为 insert-only，同身份同摘要幂等，摘要不同拒绝。
2. B2 已覆盖中断回滚、重复批、连续更新、删除 tombstone、项目隔离；B3/B4 增加
   cursor 不倒退、applied 凭据不可覆盖、Owner/PG 不可用失败关闭。
3. `rebuild_project`：在生命周期围栏内导出可信快照 → 复用 `import_project_snapshot`
   全量原子导入并以 STALE 发布 → 通过 `synchronize_project` 消费重建期间新增事件 →
   全部对齐后由 `publish_ready` 发布 READY。导入失败保留旧投影；重建期间事件由
   HWM 后增量衔接，不先清空 PG。
4. `synchronize_project` 以有界批次按流消费，批次上限返回 `INCOMPLETE`；真实
   sequence 缺口/摘要冲突直接失败关闭，不跳过、不推进游标、不自动清理日志。
5. 未实现自动 Worker、定时同步、队列、自动重建或生产读取切换。

## 12. B1/B2 审计收口

1. 证据 `row_key` 复用 P0 真实主键规范化哈希（`EVIDENCE_KEY_COLUMNS`）；事件携带完整
   证据行；确认回执拆为导出投影事件与证据行事件，不再以 `receipt_id` 冒充 evidence
   row_key。B2 对证据表首次出现补 `table_state.present/row_count/schema_version`。
2. 事件信封升级为 schema_version 2，`event_digest` 绑定 stream/sequence/event_kind/
   entity_type/entity_id/project/schema_version/payload；v1 旧日志保留 payload-only
   校验，不修改历史行。B2 拒绝未知 event_kind/entity_type、实体身份不一致和证据主键
   不一致。
3. 完整导入/增量消费/READY 发布共享项目级 advisory lock；baseline 与游标不再默认
   从 0；游标不回退；applied 凭据 insert-only。
