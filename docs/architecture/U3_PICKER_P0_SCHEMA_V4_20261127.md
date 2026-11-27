# U3 Picker P0：Schema V4 基础合同（2026-11-27）

> 本轮只实施《U3 Picker PostgreSQL 等价只读查询技术设计 V1.0》的 P0：
> 快照身份、revision 保护、导入台账、投影游标、负样本确认查询投影、查询索引。
> 不实现 Provider、不实现跨库历史过滤、不启用生产读取、不改前端与任务执行权。
> 所有断言都有真实 PostgreSQL 16 定向用例（39 passed / 0 skip，见 §7）。

## 1. 数据归属（未改变）

| 数据 | Owner | PostgreSQL V4 |
|---|---|---|
| 素材 / 素材标签 / 标注范围 | `materials.sqlite3` | 只读投影（原有表） |
| 正式 GT / GT 标签引用 | `annotations.sqlite3` | 只读投影（原有表） |
| 负样本池 | `materials.sqlite3` | 只读投影（原有表） |
| 训练历史 / tasks / Lease / GPU Reservation | Task Owner | **未迁入**（P2 再定） |
| 冻结选择清单 | 任务级 `selection.sqlite3` 文件 | **不变** |
| 负样本确认回执 | `annotations.sqlite3` 的 `task_negative_confirmations` | `task_negative_confirmation` 仅查询投影 |

`u3_shadow.py` 仍只读 SQLite、只写 `w3_material_gt` 影子 Schema；CLI 仍是受控运维入口，
没有任何业务运行时调用方（`git grep u3_shadow` 仅 CLI 与测试）。

## 2. Schema V4

从 V3 显式升级到 V4：`SCHEMA_VERSION=4`，`_SCHEMA_V3` 冻结为历史 DDL，
`_SCHEMA_UPGRADES[4]` 为纯增量语句；新建库直接执行 V4 DDL。
历史 V1/V2/V3 的 checksum 与 DDL 未改（`schema_checksum_for(1..3)` 校验各自版本）。

新增对象：

| 对象 | 主键 | 用途 |
|---|---|---|
| `picker_snapshot_state` | `project_id` | 当前可读快照身份：`snapshot_id`、`content_digest`、三条 revision、三条投影摘要、负样本确认 COUNT/`generation`/摘要、`revision_vector`、`status` |
| `u3_shadow_import` | `import_id` (BIGSERIAL) | 导入台账：`snapshot_id`、摘要、`revision_vector`、模式、`outcome`、错误码 |
| `u3_projection_cursor` | `(project_id, store)` | 每个 revision 流独立游标；P0 写 `source_revision`，`last_applied_seq` 留 NULL（P3 变更日志才定义序号） |
| `task_negative_confirmation` | `(project_id, receipt_id)` | 由 verbatim 回执派生的查询投影（`context_key`、`image_id`、`evidence`） |

`status ∈ {READY, STALE, INCOMPLETE}`：

- `READY`：完整 full 导入且通过 `pending_clear_eligible`（全部必需表、逐表计数/摘要、
  `content_digest`、三条 revision 全部自洽，且没有旧 Schema 待补导标记）。
- `STALE`：此前 READY，但之后发生过 incremental 应用（目标只被证明“包含”该快照，
  不能被证明“等于”该快照）。
- `INCOMPLETE`：其余情况（含从 V3 升级后尚未做过一次完整 full 导入的目标）。

索引只加 Picker 实际会用到的方向：

`material(project_id, processing_status, created_at, id)`、
`material(project_id, storage_source_id, processing_status, created_at, id)`、
`material_label(project_id, label_code, material_id)`、
`material_annotation_scope(project_id, label_code, material_id)`、
`annotation_label_reference(project_id, label_code, image_id)`（label-first，原 PK 是 image-first）、
`annotation(project_id, annotation_state, image_id)`、
`negative_pool_member(project_id, joined_at, material_id)`、
`negative_pool_link(project_id, category_id, material_id)`、
`task_negative_confirmation(project_id, context_key, image_id)`。

设计稿里的 `idx_picker_pool_algorithm` **未创建**：`negative_pool_algorithm_member`
的主键已经是 `(project_id, algorithm_id, material_id)`，再建一个是无用索引。
文件名 `pg_trgm` 索引未启用：不把“安装扩展”当作未经批准的操作，留待 P1/P4 按可用性处理。

## 3. 快照身份

- `content_digest`：对 `digests`（逐表规范行摘要）再摘要，导出/导入两端都重算。
- `snapshot_id`：`uuid5(NAMESPACE_URL, u3-shadow:{project,contract,content_digest,revisions})`，
  **确定性**。同一 owner 状态必然同名，所以 `export` 仍然字节级可重复（原有
  `first == second` 断言保留），重放也不需要随机令牌。
- `revision_vector`：`{store: {revision, digest}}`，其中 store 摘要只覆盖受 revision 约束的投影表。

## 4. 导入规则

| 情形 | 行为 |
|---|---|
| 快照声明了 `counts`/`digests`/`content_digest`，但与自身行不一致 | 拒绝 `U3_SNAPSHOT_INTEGRITY_FAILED`（`reason=count|digest|content_digest|snapshot_id`），不写任何行 |
| full 导入完全没有完整性元数据 | 拒绝 `U3_SNAPSHOT_INTEGRITY_FAILED`（`reason=metadata_missing`） |
| incremental 且无完整性元数据（历史最小快照） | 允许，保持旧兼容；状态只能是 `INCOMPLETE`/`STALE` |
| 目标 revision 更高 | 拒绝 `U3_SNAPSHOT_REVISION_REGRESSION` |
| revision 相同、投影摘要不同 | 拒绝 `U3_SNAPSHOT_REVISION_DIVERGED` |
| revision 相同、摘要相同、`content_digest` 相同、当前 READY | `ALREADY_APPLIED`：只追加台账，不动业务行、状态、游标 |
| revision 更高（或相同但仅证据表变化） | 通过完整性校验后导入 |
| `negative_confirmation_revision`（COUNT(*)） | 不套用单调规则；允许增减 |
| `negative_confirmation_generation` | 投影内容摘要变化才 +1，用于识别“数量不变但内容变了” |
| 任何写入中途失败 | 整事务回滚：业务行、`store_revision`、`table_state`、`evidence_row`、状态、游标、台账全部不变 |

拒绝记录：`U3_SNAPSHOT_*` 三类策略拒绝会在回滚后用独立事务补记一条 `outcome=REFUSED`
台账；其他失败（例如外键冲突）不写台账——那正是“失败即整体回滚”的证明。

V3→V4 边界：升级前的目标只有 `store_revision` 高水位、没有摘要。首次 V4 full 导入
沿用“源 revision 不得低于目标高水位”，相同 revision 允许导入并在此刻建立摘要身份
（旧目标无法证明摘要相等，不能凭空拒绝）；从第二次导入起执行完整的同 revision 摘要比较。

## 5. 负样本确认投影

`task_negative_confirmation` 由快照里 `annotations.task_negative_confirmations` 的
verbatim 证据行派生：

- `receipt_id`/`context_key` 必须是非空字符串，否则 `U3_NEGATIVE_CONFIRMATION_INVALID`（fail-closed）；
- `evidence` 是原始 `evidence_json` 解析出的对象，原样保留；
- `image_id` 取 `evidence.image_id`，缺失写 NULL（不伪造）；
- 原始行仍完整保存在 `evidence_row`，本表只是查询投影，不是第二个确认 Owner；
- full 导入按项目重建、incremental 只 upsert；计数值是**目标表**的 `COUNT(*)`
  （与 `task_negative_confirmation_revision()` 语义一致）。

## 6. 错误码（本轮新增）

`U3_SNAPSHOT_INTEGRITY_FAILED`、`U3_SNAPSHOT_REVISION_REGRESSION`、
`U3_SNAPSHOT_REVISION_DIVERGED`、`U3_NEGATIVE_CONFIRMATION_INVALID`。
结构缺失仍是 `U3_SCHEMA_STRUCTURE_INVALID`（现在同时核对 V4 的四张表与十个索引）。

## 7. 测试证据（真实 PostgreSQL，本机 pgserver）

```
tests/integration/test_u3_schema_upgrade_postgres.py   13 passed
tests/integration/test_u3_material_gt_postgres.py      26 passed
合计 39 passed, 0 failed, 0 skipped
```

覆盖：V3→V4 升级保留业务/证据行、V4 新建、迁移 checksum（1..4 篡改均拒绝）、
重复导入 `ALREADY_APPLIED`、revision 回退拒绝、同 revision 不同摘要拒绝、
快照自身身份篡改拒绝、full 导入缺失元数据拒绝、跨项目隔离、
中途外键失败后行/游标/状态/台账全回滚且游标不提前推进、
确认投影内容与 `COUNT(*)`/`generation` 联动、畸形回执 fail-closed 回滚、
`captured_at` 之前的 CLI export/import/report 闭环。

CLI 顺带修复：`read_target_snapshot` 的 `pg_current_snapshot()` 读取原先按元组下标访问，
而 CLI 连接使用 `dict_row`，导致 `u3_shadow_cli import/report` 一直 `KeyError: 0`。
本轮只把该游标固定为 `tuple_row`（不改快照语义）。

## 8. 未实施（不得当成能力）

- P1：`PickerReadProvider` / PostgreSQL 查询 SQL / 分页与精确计数。
- P2：训练历史跨库过滤、Task 状态 revision 触发器、角色等价。
- P3：Owner 变更日志与增量同步（`last_applied_seq` 尚未有语义）。
- P4：双端差分、`EXPLAIN (ANALYZE, BUFFERS)`、20 万素材性能、生产切换评估。
- 索引是否恰好匹配 P1 的最终 SQL 仍需在 P4 用真实查询计划复核。
