# U3 Picker P0：Schema V4 基础合同（2026-11-27，审计整改后）

> 本轮只实施《U3 Picker PostgreSQL 等价只读查询技术设计 V1.0》的 P0：
> 快照身份、Owner 侧证据版本、严格导入前置校验、导入台账、投影游标、
> 负样本确认查询投影、查询索引与结构核验。
> 不实现 Provider、不实现跨库历史过滤、不启用生产读取、不改前端与任务执行权。
> 定向用例：真实 PostgreSQL 16，**50 passed / 0 skipped**（§7）。

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
没有任何业务运行时调用方。SQLite 的两个 Owner 只增加“证据版本计数器 + 触发器”这一处
兼容性增量，不改变任何既有表结构、业务字段或 revision 语义。

## 2. Schema V4

`SCHEMA_VERSION=4`；`_SCHEMA_V3` 冻结为历史 DDL，`_SCHEMA_UPGRADES[4]` 为纯增量语句，
新建库直接执行 V4 DDL，V1/V2/V3 的历史 DDL 与 checksum 未改。

| 对象 | 主键 | 用途 |
|---|---|---|
| `picker_snapshot_state` | `project_id` | 已发布快照：`snapshot_id`、`content_digest`、三条 revision、三条投影摘要、Owner 确认 COUNT/`generation`/摘要、`revision_vector`、`status` |
| `u3_shadow_import` | `import_id` | 导入台账：`snapshot_id`、摘要、`revision_vector`、模式、`outcome`、错误码 |
| `u3_projection_cursor` | `(project_id, store)` | 每个 revision 流独立游标；P0 写 `source_revision`，`last_applied_seq` 留 NULL（P3 才定义序号） |
| `task_negative_confirmation` | `(project_id, receipt_id)` | 由 verbatim 回执派生的查询投影 |

`status`：`READY`（完整 full 导入，且通过完整性/完整性门槛）、`STALE`（READY 后又发生
incremental 应用）、`INCOMPLETE`（其余）。P0 起 full 导入必须先证明完整，因此 full 导入
只可能发布 `READY`；`INCOMPLETE` 只出现在 incremental 兼容路径。

索引（按 Picker 实际访问方向，全部为普通索引）：
`material(project_id, processing_status, created_at, id)`、`material(project_id,
storage_source_id, processing_status, created_at, id)`、`material_label(project_id,
label_code, material_id)`、`material_annotation_scope(project_id, label_code,
material_id)`、`annotation_label_reference(project_id, label_code, image_id)`
（label-first，原 PK 是 image-first）、`annotation(project_id, annotation_state,
image_id)`、`negative_pool_member(project_id, joined_at, material_id)`、
`negative_pool_link(project_id, category_id, material_id)`、
`task_negative_confirmation(project_id, context_key, image_id)`、
`u3_shadow_import(project_id, snapshot_digest, outcome)`。

`idx_picker_pool_algorithm` **不建**：`negative_pool_algorithm_member` 的主键已经是
`(project_id, algorithm_id, material_id)`。文件名 `pg_trgm` 索引未启用（不把安装扩展当
作未经批准的操作）。

### 2.1 结构核验（不是只对名字）

`ensure_schema()` 每次都对真实 catalog 校验 V4 合同，任何不符返回
`U3_SCHEMA_STRUCTURE_INVALID`，不自动修复：

- 四张表的**真实主键**（列与顺序）；
- 关键列的 `udt_name`（`text`/`bpchar`/`int8`/`jsonb`/`timestamptz`）；
- 必须 `NOT NULL` 的列；
- `status` / `outcome` 的 CHECK 约束仍存在且**全部允许值**都在；
- 每个索引的**所属表**、**列与顺序**、以及“不应是唯一索引”；
- 原有 v3 合同（reference 列/主键、池双外键与 CASCADE、分类唯一折叠）继续校验。

## 3. 快照身份与 Owner 侧证据版本

`content_digest` 覆盖全部数据表与证据表的逐表摘要；`snapshot_id` 是
`uuid5(project, contract, content_digest, revisions, evidence_streams)` 的确定性值，
导出仍可逐字节重复。

三种“没有 Owner revision”的可变证据由 **Owner 侧单调 generation** 保护（SQLite Trigger
写入同一事务，INSERT/UPDATE/DELETE 都递增；旧库在打开时原地补装，不升 schema 版本）：

| 流 | Owner 计数器 | 覆盖 |
|---|---|---|
| `negative_confirmation` | `annotation_meta.task_negative_confirmation_generation` | `task_negative_confirmations` |
| `annotations_evidence` | `annotation_meta.evidence_generation` | delete backup / candidate commits / negative reviews / confirmations |
| `materials_evidence` | `material_meta.evidence_generation` | migrations / storage audit / retirements / deferred cleanup / assignment receipts / **negative_pool_operations** |

`negative_pool_operations` 也属于历史证据：两次合法的成员操作会产生不同回执而**不改变表结构**，
只靠 `negative_pool_meta.revision` 不足以让行 generation 前进，会被“同结构、同 generation、
不同摘要”误判为 `U3_SNAPSHOT_REVISION_DIVERGED`。因此该表纳入 materials 的 evidence
generation 触发器覆盖：懒创建表在 `negative_pool._mutate` 的同一事务里安装触发器；已有数据库
由 `_read_schema_version_fast` 的“现有证据表是否都有 insert 触发器”探测强制进入 `_initialize`
补装，不会被快速路径跳过。`negative_pool_meta.revision` 的原有语义保持不变。

快照里每条流记录 `{generation, structure_generation, structure_certified, digest, tables(+revision)}`；
导入端的概念同名流由快照行重算 digest 与表集合，只信任 Owner 的 generation/结构版本。

### 3.1 表生命周期版本（结构变化必须可证明）

行 generation 只证明“内容变了”，不能证明“表的结构变了”：`DROP TABLE` 不触发行触发器。
因此每个 Owner 额外持久化两个键（`annotation_meta` / `material_meta`，不新增表、不改 DDL）：

- `evidence_structure`：最近一次由 Owner 认证的证据表集合（排序 JSON 数组）；
- `evidence_structure_generation`：该集合的单调版本；首次观察为基线 0，此后**任何**创建、
  删除、重建导致的集合变化都 +1。

维护入口：

- `AnnotationRepository._ensure_generation_objects` / `MaterialRepository._ensure_evidence_generation`
  在安装触发器时同步认证结构（新库基线、旧库原地补装、懒建表创建时）；
- 显式运维入口 `reconcile_evidence_structure()`（两个 Owner 各一个）：用于绕过 Owner 的
  DDL（原始 SQL、外部迁移）之后重新认证结构。`MaterialRepository` 的进程级 init 缓存会
  让第二次构造成为 no-op，所以结构认证**不依赖构造**，以显式入口为准。

导出侧：读取 Owner 的结构版本与认证表集合，并与实际观察到的集合比较。

- 一致 → 快照携带该版本与 `structure_certified=true`；
- 不一致（Owner 未认证的 DDL）→ **导出直接失败** `U3_OWNER_STRUCTURE_UNVERIFIED`，
  不猜测其安全；
- 从未记录过结构（升级前的老库）→ `structure_certified=false`、版本 0。

导入侧：结构版本与行 generation 是两条独立门禁（见 §4）。

## 4. 导入规则（写入前全部校验）

| 情形 | 行为 |
|---|---|
| full 导入未声明 `counts`/`digests`/`content_digest` | 拒绝 `U3_SNAPSHOT_INTEGRITY_FAILED`（`reason=metadata_missing`） |
| 声明了但与自己行不一致 | 拒绝 `U3_SNAPSHOT_INTEGRITY_FAILED`（`reason=count|digest|content_digest|snapshot_id`） |
| **任何** full 导入（普通项目或 pending 项目）不完整：contract/project/lifecycle/必需表/十张证据表/table_state/counts/digests/content_digest/三项 revision/证据命名空间/snapshot_id | 普通项目拒绝 `U3_SNAPSHOT_INCOMPLETE`；pending 项目保持原 `U3_PENDING_IMPORT_INCOMPLETE`。**都在任何 DELETE/INSERT/UPDATE 之前** |
| 目标 revision 更高 | 拒绝 `U3_SNAPSHOT_REVISION_REGRESSION` |
| revision 相同、投影摘要不同 | 拒绝 `U3_SNAPSHOT_REVISION_DIVERGED` |
| 某证据流**结构版本更低** | 拒绝 `U3_SNAPSHOT_STRUCTURE_REGRESSION` |
| 某证据流结构版本相同、表集合不同 | 拒绝 `U3_SNAPSHOT_STRUCTURE_UNVERIFIED`（无法证明） |
| 目标已有结构版本、来源没有可证明的结构迁移（老快照/未认证） | 拒绝 `U3_SNAPSHOT_STRUCTURE_UNVERIFIED` |
| 结构版本更高（已认证的 create/drop/rebuild） | 放行结构门禁，再执行行 generation 门禁 |
| 目标已有行 generation 更高 | 拒绝 `U3_SNAPSHOT_REVISION_REGRESSION`（`detail: stream=...`） |
| 结构相同、generation 相同、摘要不同 | 拒绝 `U3_SNAPSHOT_REVISION_DIVERGED` |
| 完全相同且当前 READY | `ALREADY_APPLIED`：只追加台账，不动业务行/状态/游标 |
| `negative_confirmation_revision`（COUNT(*)） | 保留兼容语义，允许增减；不计入单调规则 |
| 任何写入中途失败 | 整事务回滚：业务行、`store_revision`、`table_state`、`evidence_row`、状态、游标、台账全部不变 |

`U3_SNAPSHOT_*` 策略拒绝在回滚后用独立事务补记 `outcome=REFUSED` 台账（完整性失败与结构/
版本拒绝都算）；其他失败（例如外键冲突）不写台账，这正是“失败即整体回滚”的证据。
测试分别断言“业务状态不变”和“台账只多一条 REFUSED”，不把两者混为一谈。

缺表语义保持不变：**物理缺表**（`table_state.present=false`）保留目标历史证据；
**空表**（present=true、0 行）清空目标该表；投影与证据行同进退（缺表时两者都保留，
不会出现“证据行在、确认投影被清空”）。

V3→V4 边界：升级前目标只有 `store_revision` 高水位、没有摘要。首次 V4 full 导入沿用
“源 revision 不得低于目标高水位”，相同 revision 允许导入并在此刻建立摘要身份；
从第二次导入起执行完整的同 revision 摘要比较，证据流从第一次起即按 Owner generation 比较。

## 5. 负样本确认投影

`task_negative_confirmation` 由快照中 `annotations.task_negative_confirmations` 的 verbatim
证据行派生：`receipt_id`/`context_key` 必须非空，`evidence` 保留原始对象，`image_id` 缺失
写 NULL（不伪造）；畸形回执 `U3_NEGATIVE_CONFIRMATION_INVALID` fail-closed。
原始行仍完整保存在 `evidence_row`，本表不是第二个确认 Owner。**full 导入只在源表存在
（present=true）时重建投影**：空表清空、缺表保留，与 `evidence_row` 完全同进退，不会出现
“证据行被保留、确认投影却被清空”。incremental 只 upsert；状态的 COUNT/generation 取
**Owner 值**（源表缺失时 COUNT=0），结构版本与表集合记录在 `revision_vector` 中，供 P1
Picker 判定投影是否仍然权威。

## 6. Owner 写入与导出的互斥

`confirm_task_negatives()` 与 `export_project_snapshot()` 使用同一个
`material_annotation_lifecycle_fence`（进程/线程可重入，跨进程 FileLock）。锁顺序统一为
“生命周期锁 → SQLite”，没有任何路径反向获取；导出在读取后复核三项 revision、三个行
generation、**materials 与 annotations 两个结构版本**以及两侧实际表集合，任何变化即
`U3_SNAPSHOT_SOURCE_CHANGED`。

## 7. 测试证据（真实 PostgreSQL，本机 pgserver）

```
tests/integration/test_u3_schema_upgrade_postgres.py   17 passed
tests/integration/test_u3_material_gt_postgres.py      40 passed
合计 57 passed, 0 failed, 0 skipped
```

覆盖：V1/V2/V3→V4 升级保留数据与证据、V4 新建、checksum 1..4 篡改拒绝、四张 V4 表主键
（含 `u3_shadow_import`）/类型/NOT NULL/CHECK（**允许值集合严格相等**，加宽或收窄都拒绝）/
索引表/索引列顺序的篡改拒绝、重复导入 `ALREADY_APPLIED`、revision 回退、同 revision 不同
摘要、快照身份篡改、full 缺元数据、三种“自洽但不完整”full 快照在任何写入前拒绝
（业务状态与台账分别断言）、跨项目隔离、中途外键失败全回滚、确认投影与 COUNT/generation
联动、INSERT/UPDATE/DELETE generation 递增、同 COUNT 不同内容仍递增、旧确认快照重放被拒且
投影/状态/游标/台账不变、被重新封装的“同 generation 不同内容”被拒、确认写入等待导出
生命周期锁、material 证据（无 revision 写入）同样保护、畸形回执回滚；
**结构生命周期**：未认证 DDL 导出失败关闭、认证后 S2 导入且旧 S1 被
`U3_SNAPSHOT_STRUCTURE_REGRESSION` 拒绝（证据/table_state/revision vector/游标/状态不变，
台账只多一条 REFUSED）、删表→重建→写入新证据后 S1/S2 均被拒、空表清空与缺表保留语义、
annotation 侧（含 `task_negative_confirmations`）缺表时 evidence_row 与确认投影同时保留、
伪造的未认证结构变化在导入侧被 `U3_SNAPSHOT_STRUCTURE_UNVERIFIED` 拒绝；
**负样本池回执**：连续两次真实 `NegativePool.members()` 回执操作各自导出/full 导入均成功
（结构不变、generation +1），重放旧快照被拒，同 `operation_id` 幂等重放不推进 generation；
导出期间仅 materials 结构版本变化也会被 `U3_SNAPSHOT_SOURCE_CHANGED` 拒绝。

## 8. 未实施 / 已知边界

- P1：`PickerReadProvider`、PG 查询 SQL、分页与精确计数；P2：训练历史跨库过滤与角色等价；
  P3：Owner 变更日志与增量同步（`last_applied_seq` 尚无业务语义）；P4：双端差分、
  `EXPLAIN (ANALYZE, BUFFERS)`、20 万素材性能、生产切换评估。
- 索引是否恰好匹配 P1 的最终 SQL 仍需在 P4 用真实查询计划复核。
- 结构变化必须由 Owner 认证：绕过 Owner 的原始 DDL 之后，导出会失败关闭，必须先调用
  `MaterialRepository.reconcile_evidence_structure()` / `AnnotationRepository.reconcile_evidence_structure()`
  （`MaterialRepository` 的进程级 init 缓存使第二次构造成为 no-op，不能依赖构造触发认证）。
- 从未被新版本 Owner 打开过的老库没有结构记录（`structure_certified=false`）：若其表集合与
  已发布结构不同，导入会被拒绝；这是 fail-closed 的预期行为。
- 旧导出的快照（无 `evidence_streams`）generation 与结构版本视为 0；对已有 READY 状态会被
  拒绝，需要重新导出。
- 本轮 V4 DDL 未变（结构版本走 Owner meta 与 `revision_vector` JSONB），因此不需要 V5，
  也不需要改动已记录的 v4 checksum。
