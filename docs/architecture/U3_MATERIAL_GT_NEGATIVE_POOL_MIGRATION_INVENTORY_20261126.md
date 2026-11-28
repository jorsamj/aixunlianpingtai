# U3 素材 + 正式 GT + 负样本池 迁移清单与跨库合同（2026-11-26）

> **状态：`INVENTORY_ONLY` / `DESIGN_ONLY` / `NOT_IMPLEMENTED` / `NOT_VERIFIED`**
> 本文只做现状清点与迁移合同设计。**未修改任何源码、未修改任何表结构、未迁移任何数据、未启用任何 Provider、未访问生产数据。**
>
> 每个断言都带 `文件:行`。凡是代码里没有的能力，一律写在“明确未实现”（§7）或“开放问题”（§9），不靠推测补齐。
>
> 上游依据：`docs/architecture/F1_PERFORMANCE_AND_MIGRATION_DESIGN_20261122.md:202` 把 U3 定义为 `materials.sqlite3` + `annotations.sqlite3` + negative pool + 投影/标签引用，风险“高（跨库 ATTACH、GT 唯一权威）”，顺序“最后批次，必须联合”；`:213-218` 列出必须显式处理的三个 ATTACH 点。`docs/architecture/AI_DEVELOPMENT_HANDOFF.md:14` 记 U3“未开始”。

## 1. 数据面总览

### 1.1 三个持久文件 + 两类任务级文件

| 存储 | 物理位置 | 权威内容 | 定义处 |
|---|---|---|---|
| 素材库 | `<project>/materials.sqlite3` | `materials`、`material_labels`、`material_annotation_scopes`、`material_meta`、`material_migrations`、`material_storage_audit`、`material_retirements`、`material_cleanup_deferred`、`material_assignment_receipts`、全部 `negative_pool_*` | `material_repository.py:411-414,69-154`；`negative_pool.py:23-33` |
| 正式 GT | `<project>/annotations.sqlite3` | `annotations`、`annotation_label_references`、`annotation_meta`、`annotation_delete_backup`、`annotation_negative_reviews`、`annotation_candidate_commits`、`task_negative_confirmations` | `annotation_repository.py:131,141,219-256,1450-1462,1521-1522` |
| 任务库 | `<DATA_DIR>/task_runtime/tasks.sqlite3` | `training_material_usage`、`training_usage_tokens`、`training_usage_coverage`、`training_usage_meta`、`training_usage_token_schema`（另有任务/租约表，属 U5） | `training_material_usage.py:22-38,40-71` |
| 任务级选材清单 | `<task artifacts>/selection.sqlite3` | `selection`、`counters`、`meta`、`assignment_evidence` | `material_batches.py:49,2218-2244` |
| 任务级 rescan 清单 | 任务产物内的 rescan manifest（同一 SQLite 文件被 `ATTACH` 为 `rescan`） | `rescan_baseline`、`rescan_objects`、`rescan_meta`、`rescan_annotation_deltas` | `storage/import_candidates.py:706-729` |

### 1.2 关键结构性事实（决定了整个迁移难度）

**事实 A：三库之间没有任何 SQL 外键。** 引擎级 FK 只存在于 `materials` 内部：

- `material_labels.material_id REFERENCES materials(id) ON DELETE CASCADE`（`material_repository.py:110`）
- `material_annotation_scopes` 同上（`:117`）
- `negative_pool_members.material_id REFERENCES materials(id) ON DELETE CASCADE`（`negative_pool.py:24`）
- `negative_pool_links` 双 FK 级联（`:27`）；`negative_pool_algorithm_members` FK 级联（`:29`）
- 写连接显式 `PRAGMA foreign_keys=ON`（`material_repository.py:426`），所以上述级联**真实生效**。

而 `annotations.*` 对 `materials` **没有** FK（不同文件），`training_usage_*` 对两者也没有 FK。跨库完整性完全由应用层保证。

**事实 B：跨库一致性靠三种机制，不是靠事务**：

1. 同一 SQLite 连接的 `ATTACH` + 单事务（§3.1、§3.2）；
2. 单连接多库只读事务 + 在事务内读取双方 revision 再与调用方期望比对（§3.3）；
3. 生命周期文件锁 `material_annotation_lifecycle_fence`（`material_repository.py:190-219`）串行化“素材提交”与“GT 提交”这类跨库写。

**事实 C：素材侧存在“派生投影”，不是第二权威**：

- `material_labels` / `material_annotation_scopes` 由 `_write_row` **整行重写**（`material_repository.py:627-657`），而 `_write_row` 被 `upsert/upsert_many/patch/patch_annotation_projections/mutate*` 统一调用。
- GT 投影写回素材库时下界受版本约束（`patch_annotation_projections`，`:1666-1697`），冲突抛 `AnnotationProjectionConflictError`（`:1679-1682`）。

**事实 D：`materials.sqlite3` 没有 Provider 抽象。** `MaterialRepository._connect` 直接 `sqlite3`（`:418-427`），`open_readonly` 只校验 `user_version ∈ {5,6,7,8}`（`:400-408`）。这与算法域（`algorithm_repository.require_authoritative_sqlite`，`algorithm_repository.py:124`）和存储源域不同。

## 2. 逐表 / 逐权威清单

> 模板：**唯一写入 Owner** / **键** / **revision 或 CAS** / **事务边界** / **跨库连接** / **热路径索引** / **历史格式** / **删除·恢复** / **未知结果与幂等回执**

### 2.1 `materials`（素材索引，唯一权威行）

- **Owner**：`MaterialRepository`（`material_repository.py:398`）。所有插入/更新最终经 `_write_row`（`:588-658`）；删除只有 `remove`（`:1766-1784`）与 `retire_many`（`:1733-1764`）两条。
- **键**：主键 `id TEXT`（`:76`）；自然键候选 `(storage_source_id, object_key)`（`ix_materials_reference`，`:92`），但**不是**唯一约束（代码里只有普通索引，没有 UNIQUE）。
- **revision**：`material_meta.revision` 单调 +1，由 `_bump_revision`（`:584-586`）在**所有**写事务末尾调用：`upsert`（`:1589`）、`upsert_many`（`:1611`）、`patch`（`:1631`）、`patch_annotation_projections`（`:1699`）、`legacy migrate`（`:702`）、`reconcile_storage_batch`（`:1877`）、`retire_many`（`:1759`）、`remove`（`:1779`）。
  - **注意**：`upsert`/`upsert_many` 无论内容是否变化都会 bump（`:1589,1611`），`patch`/`patch_annotation_projections` 只有实际变更才 bump（`:1631,1698-1699`）。这个不对称必须原样保留，否则依赖 revision 变化的缓存会失效或永不过期。
- **事务边界**：每方法一个 `BEGIN IMMEDIATE` … `COMMIT`，异常 `ROLLBACK`（例：`:1582-1593`）。
- **跨库连接**：`material_assignment_receipts`（同库）；被 `annotations.upsert_many` 读来准入（`annotation_repository.py:1339-1345`）。
- **热路径索引**：`ix_materials_source`、`ix_materials_status`、`ix_materials_source_status`、`ix_materials_filename`(NOCASE)、`ix_materials_created`、`ix_materials_import_batch`（表达式）、`ix_materials_content_sha256`(+normalized)、`ix_materials_dataset`、`ix_materials_dataset_delete_claim`、`ix_materials_stored_name`（`material_repository.py:91-108`）。`_REQUIRED_OBJECTS` 把 `ix_materials_import_batch`/`ix_materials_source_status`/`material_assignment_receipts`/`ix_materials_stored_name` 列为“跳过初始化前必须存在”（`:432-444`）。
- **历史格式**：①旧 `images.json` 一次性迁移，带 `material_migrations(source,signature,imported_count,imported_at)` 幂等台账（`:128-133,660-711`）；②缺 `stored_name` 的旧 payload 只能有界补查（`_LEGACY_STORED_NAME_SCAN_LIMIT = 200`，`:33-39`；超限抛 `MaterialEvidenceIncomplete`，`:42-53`）；③`MATERIAL_READ_SCHEMA_VERSIONS = {5,6,7,8}`（`:31`）+ 夹具 `tests/fixtures/material_repository_schema5.sql`。
- **删除 / 恢复**：
  - `remove()` 真删行（`:1766-1784`），`material_labels`/`scopes`/负样本池成员随 FK 级联消失；
  - `retire_many()` 先把 payload 与 GT 备份写入 `material_retirements`，再删行（`:1744-1760`）；**这是单向的**：仓内所有 `material_retirements` 引用都是写入/读取/审计/物理回收（`material_repository.py:139-148,1728-1731`；`local_material_reclamation.py:213,245,383`；`material_batches.py:791`；`tools/reclaim_retired_original.py:32`），**没有**“从 retirements 还原材料行”的路径。
  - 数据集删除用“声明字段”而不是删除：`_dataset_delete_claim` / `_material_batch_delete_claim`（`:55-56`），并有专门索引与孤儿声明清理（`:100-103,817-861`）。
- **未知结果 / 幂等**：`material_assignment_receipts(task_id,image_id)` 记 `outcome/error`（`:70-74`），读取 `assignment_receipts`（`:1907-1918`）；负样本池操作回执在 `negative_pool_operations`（`negative_pool.py:80-81`）。

### 2.2 `material_labels`（派生投影）

- **Owner**：只有 `MaterialRepository._write_row` 写（`material_repository.py:627-644`）；外部无直接写路径。
- **键**：`PRIMARY KEY(material_id, label_code)`（`:113`）；索引 `ix_material_labels_code(label_code, material_id)`（`:115`）——这是“按标签筛素材”的入口。
- **CAS**：无独立版本；跟随 `materials` 的整行重写与 `material_meta.revision`。
- **删除**：随素材 FK 级联；`_write_row` 每次先 `DELETE FROM material_labels WHERE material_id=?`（`:627`）再插入，因此**行级全量替换**。
- **迁移含义**：迁移后必须有等价唯一约束 + `(label_code, material_id)` 索引，否则训练选材按标签过滤会退化。

### 2.3 `material_annotation_scopes`（派生投影）

- 结构、Owner、替换方式同 2.2（`material_repository.py:116-122,645-657`）；`annotation_scope` 来源是 payload 的 `annotation_scope` 排序去重集合。
- 训练侧“缺类别/部分审核”判定依赖它（`training_material_picker_api.py` 的 scope 子句族，`:560-565`）。

### 2.4 `material_meta`（revision 权威）

- **Owner**：`_bump_revision`（写）与 `_revision`（读）（`material_repository.py:580-586`）。
- **键**：`key TEXT PRIMARY KEY`，只使用 `'revision'`；初值 `0`（`:123-127`）。
- **迁移含义**：这是素材域唯一的高水位。任何导入必须重建它并**不得**回退（§6.7）。

### 2.5 `material_migrations`（旧格式台账）

- 主键 `source`，内容 `signature/imported_count/imported_at`（`material_repository.py:128-133`）。
- 语义：`('images.json', '<size>:<mtime_ns>')` 写过即不再重读（`:678-706`）。
- **迁移含义**：属于“历史证据”，必须迁移但不能被新系统用来判断“还要不要迁移”。

### 2.6 `material_storage_audit`（storage rescan 幂等账）

- 主键 `(task_id,image_id)`，列 `action/old_sha256/new_sha256/recorded_at`（`material_repository.py:134-138`）。
- 写入者：`_reconcile_storage_batch_locked`（`:1874`）与 `record_physical_reclamation_audit`（`:1717-1726`）。
- 幂等语义：同一 `task_id` 已有任意行则整批拒绝（`:1842-1843`，`LEGACY_COMPATIBILITY_TASK_CONFLICT`）；物理回收用 `INSERT OR IGNORE` + 冲突校验（`:1720-1726`）。
- **迁移含义**：这是“任务级一次性写”的证明，必须整表迁移，且 `(task_id,image_id)` 唯一性保留。

### 2.7 `material_retirements` / `material_cleanup_deferred`

- `material_retirements` 主键 `(task_id,image_id)`，保存 `payload_json/annotation_json` 与 `reclamation_state`，并带 `CHECK(reclaimed_bytes=0)`（`material_repository.py:139-148`）——即“逻辑退休、物理未回收”是被 schema 强制的。
- `material_cleanup_deferred` 主键 `cleanup_id`，`identity = sha256(owner + ':' + payload)`（`:1707-1715`），重复记录只更新 `last_error`。
- **迁移含义**：退休记录是**证据**，不是可重建的缓存；丢失即永久丢失原图引用与 GT 备份。
- **重要后果**：素材行删除会级联清掉 `negative_pool_*` 成员（§2.9），但 `material_retirements.annotation_json` 只备份 GT，**不备份池成员关系**。这是 U3 迁移与恢复设计必须显式面对的缺口（§9 Q-2）。

### 2.8 `material_assignment_receipts`

- 主键 `(task_id,image_id)`，`outcome/error`（`material_repository.py:70-74`），`WITHOUT ROWID`。
- **唯一写入者**：`MaterialRepository.apply_assignment_batch`（`:1920-1972`），docstring 明确“Commit material changes and their idempotency receipts in the same database”（`:1922`）。
- **事务边界**：`BEGIN IMMEDIATE` → 读已有回执 → 逐条判定（`MATERIAL_NOT_FOUND` / `MATERIAL_IDENTITY_CHANGED` / `MATERIAL_DELETE_PENDING` / `DATASET_CHANGED_OR_UNAVAILABLE` / `MATERIAL_ASSIGNMENT_CHANGED` / `unchanged` / `updated`）→ 写素材行 → 写回执 → `commit_guard()` → `COMMIT`（`:1928-1971`）。
- **幂等合同**：已有回执的 `image_id` 直接 `continue`（`:1938-1939`），所以**重放不重算、不重写**；`unchanged` 也是一个持久结局（`:1954-1955`），不是“没做”。
- **批量上限**：`1..500`（`:1923`）。
- 读取：`assignment_receipts` / `_assignment_receipts`（`:1907-1918`），调用方见 `material_batches.py:4687`。
- **迁移含义**：这是“素材变更 + 回执”同库同事务的**唯一**样例，也是 U3 要保住的关键性质之一。它与任务库的 `tasks` 只有概念关联（`task_id`），**没有** FK；迁移后不得把回执搬到另一个库，否则“变更与回执原子”立即失效。

### 2.9 `negative_pool_*`（5 张声明表 + 1 张运行期回执表，物理上都在素材库）

| 表 | 键 | 说明 | 证据 |
|---|---|---|---|
| `negative_pool_members` | `material_id` PK，FK→`materials` CASCADE | 池成员 | `negative_pool.py:24` |
| `negative_pool_categories` | `id` PK，`name` UNIQUE COLLATE NOCASE | 分类 | `:26` |
| `negative_pool_links` | `(material_id,category_id)` PK，双 FK CASCADE | 成员↔分类 | `:27` |
| `negative_pool_algorithm_members` | `(algorithm_id,material_id)` PK，FK CASCADE | 算法级成员 | `:29` |
| `negative_pool_meta` | `id=1`，`revision` | 池高水位 | `:31-32` |
| `negative_pool_operations`（**运行期建表**） | `operation_id` PK | 幂等回执 | `:80-81,130` |

- **Owner**：`NegativePool`（`negative_pool.py:38`）。写入口统一收口在 `_mutate`（`:55-86`）与 `restore_members`（`:105-135`），两者都在 `material_annotation_lifecycle_fence` + `BEGIN IMMEDIATE` 内。
- **CAS 合同**：`_mutate(member_receipt=...)` 先查 `negative_pool_operations`，命中且 `identity` 相同则**直接返回旧结果**（`:60-66`）；否则校验 `expected_revision` 相等（`:70-73`），不等抛 `MemberOperationConflict`。写成功后 `revision+1` 并写回执（`:74-81`）。
- **热路径索引**：`ix_negative_pool_joined`、`ix_negative_pool_category`、`ix_negative_pool_material_algorithm`（`:25,28,30`）；选材侧用 `EXISTS` 子查询命中它们（`training_material_picker_api.py:433-442`）。
- **分类与资格分离（重要）**：池成员**不**证明“缺目标”。资格由 GT 现算 `negative_pool_qualification`（`negative_pool.py:398-429`），并在读前后各取一次 `annotations.current_revision()`，不一致即抛 `ValueError('formal annotations changed; refresh the pool')`（`:406,427-428`）。
- **迁移含义**：
  1. `negative_pool_meta.revision` 必须单调重建；
  2. 成员/链接/算法级成员必须在同一导入事务里完成（否则“成员存在但分类缺失”会短暂可见）；
  3. 由于 FK CASCADE 到 `materials`，导入顺序必须是 `materials` → pool，且**不得**在 pool 导入后重放 `materials` 的删除。

### 2.10 `annotations`（正式 GT 唯一权威行）

- **Owner**：`AnnotationRepository`（`annotation_repository.py:125`）。写入口：`upsert_many`（`:1292-1472`）、`upsert`（`:1474-1481`）、`remap_labels_if_digests`（`:982+`）、`repair_candidate_commit_projections`（`:1205-1232`）、删除族（`:1577-1712`）。
- **键**：`image_id TEXT PRIMARY KEY`；`annotation_state` 受 CHECK 限制 `('unannotated','annotated','confirmed_empty')`（`:220-228`）。
- **revision / CAS 合同（三层）**：
  1. `annotation_meta.revision` 由**触发器**在每次 insert/update 时 +1（after-insert 触发器 `:258-294`，after-update 触发器 `:295+`），读取 `current_revision()`（`:730-735`）；
  2. 行级 CAS：`expected_version`（必须等于当前 `version`，否则 `AnnotationConflictError`，`:1361-1371`；`version=0` 表示“必须不存在”）；
  3. 内容 CAS：`expected_content_digest`（不等即 `ValueError("formal GT content changed")`，`:1372-1377`）。
- **版本推进规则**：`ON CONFLICT ... version=annotations.version+1`，但仅在 `content_digest` 改变或 `force_version_advance` 时执行（`:1403-1426`）；`force_version_advance` 走 `_validate_protected_candidate_write` 且写后回读校验（`:1355-1357,1435-1440`）。
- **事务边界**：`label_governance_fence`（`labels.py:144`）→ `material_annotation_lifecycle_fence` → 素材准入（`assert_formal_annotation_admission`）→ `BEGIN IMMEDIATE`（`:1292-1347`）。GT 与素材投影**不在同一事务**：GT 提交在 `:1465`，投影写回在 `:1469-1471`（另一个连接、另一个事务）。
- **跨库连接**：读素材做准入（`:1327-1345`）；写素材投影（`:1469-1471`）。
- **历史格式**：`<project>/annotations/{image_id}.json` 逐图 JSON 作为**影子读**：SQLite 命中优先，未命中回落 legacy（`:445-475,496-507`）；`iter_records` 也把 legacy 目录里“SQLite 未覆盖”的文件一并产出（`:786-789`）。
- **删除 / 恢复**：`prepare_delete(token)` 快照进 `annotation_delete_backup`（`:1577-1603`）→ `finalize_delete(token)` 仅在 `content_digest` 与备份一致时删除（`:1605-1646`，不一致即 `RuntimeError`）→ `restore_delete(token)` 回填缺失行并**拒绝复活已被治理下线的标签**（`:1648-1703`）→ `complete_delete(token)` 清备份（`:1705-1711`）。
- **未知结果**：`source_kind` 在 `annotation_label_references` 中区分 `sqlite`/`legacy`（`:241-249`），使“这条索引来自哪”可审计。

### 2.11 `annotation_label_references`（触发器维护的派生索引）

- **Owner**：只有 `annotations` 上的两个触发器写（`annotation_repository.py:258-294` after-insert、`:295+` after-update）；`rebuild_reference_index`（`:683-728`）可全量重建。
- **键**：`(image_id,label_code)` PK；索引 `ix_annotation_label_references_code(label_code, image_id)`（`:250-251`）。
- **复合语义**：`box_count`（框数）+ `scope_ref=1`（审核范围声明）+ `annotation_state`（`:280-290` 的 UPSERT 把 scope 行与 box 行合并）。
- **迁移含义**：**这是训练选材的热路径核心**（`training_material_picker_api.py:750-760,1179-1183`）。迁移后必须：①同结构唯一键；②同索引；③触发器语义用等价机制保证；④`annotation_meta.index_rebuilt_at`（`:174-177`）的就绪标记必须有等价物，否则启动会走重建。

### 2.12 `annotation_meta`（GT revision 权威）

- `key/value`，只使用 `'revision'`（初值 0，`annotation_repository.py:252-257`）与 `'index_rebuilt_at'`（`:174-177`）。
- 写入者是触发器，**不是**应用代码。这是 U3 里唯一“revision 由数据库自己维护”的域——迁移到 PostgreSQL 时必须显式改成应用/触发器二选一，并保证并发下单调。

### 2.13 `annotation_delete_backup`

- 键 `(token,image_id)`，带 `token` 索引（`annotation_repository.py:231-240`）；`token` 有严格校验（`:1557-1567`）。
- 语义：**删除前快照**，是 restore 的唯一依据；`prepare_delete` 用 `INSERT OR IGNORE` 保证幂等（`:1586-1594`）。

### 2.14 `annotation_negative_reviews`（运行期建表）

- 首写时才 `CREATE TABLE`（`annotation_repository.py:1450-1455`），PK 是 `(image_id,source_version,actor_id,reviewed_scope_json,source_content_sha256)`。
- 写入条件严格：`actor` 非空、`labels` 非空且不含 `*`、`expected_version` 必须给出（`:1444-1449`）。
- 读取仅审计：`negative_review_evidence` 明确“current GT remains the training authority”（`:1541-1548`）。
- **迁移含义**：这是“运行期 DDL”表，迁移工具必须能处理“表可能不存在”。

### 2.15 `annotation_candidate_commits`（运行期建表，GT 写入回执）

- 建表：首写时 `CREATE TABLE IF NOT EXISTS annotation_candidate_commits(task_id,operation_id,image_id,receipt_json,PRIMARY KEY(task_id,image_id))`（`annotation_repository.py:1351-1353`）。
- 读取：`candidate_commit_receipts(task_id, operation_id, image_ids)`（`:1246-1260`）、`candidate_committed_ids`（`:1233-1244`）。
- **迁移含义**：这是 §3.10（U5 文档）里 formal bulk 幂等的**唯一 GT 侧证据**。U3 与 U5 必须联合迁移，不能只迁一侧（否则 `_proof_state` 会把已提交批次判成未提交）。

### 2.16 `task_negative_confirmations`（运行期建表，任务级负样本回执）

- 首写时建表：`(receipt_id PK, context_key, evidence_json)` + `task_negative_context_idx(context_key)`（`annotation_repository.py:1521-1522`）。
- 读取：`task_negative_receipts(context_key, image_ids)`（`:1500-1515`）、`task_negative_confirmation_revision()`（`:1494-1498`）。该 revision 的**实际口径是 `COUNT(*)`**：选材页面直接 `SELECT COUNT(*) FROM annotation_gt.task_negative_confirmations` 作为“确认修订”（`training_material_picker_api.py:800-807`），没有任何单调计数器。
- 语义：`context_key` 绑定“算法 + 有效标签”，所以别的算法的确认不能被复用（`training_material_picker_api.py:390-419` 的注释与实现）。
- **迁移含义**：用 `COUNT(*)` 当 revision 是**弱合同**（删除会改变计数、并发插入会跳变）。迁移时必须原样保留这个“弱 revision”语义，还是升级为真 revision，属于开放问题（§9 Q-4）。

### 2.17 `training_usage_*`（物理在任务库，业务属训练历史）

- **Owner**：`TrainingMaterialUsage`（`training_material_usage.py:22`）；写连接对任务库 `connect_sqlite(self.path)`（`:30-38`）。
- **表与键**：`training_material_usage` PK `(task_id,image_id,role)`；`training_usage_tokens` PK `(project_id,token_kind,token_value,task_id,image_id,role)`；`training_usage_coverage` PK `(project_id,algorithm_id)`；`training_usage_meta(id=1,revision)`（`:43-61`）。
- **revision**：由 4 个触发器维护（insert/update/insert token/insert coverage，`:63-70`），读 `read_revision`（`:258-296`）。
- **执行栅栏**：`_check_owner` 校验 `tasks` 行的 status/lease_token/attempt/未过期，失败抛 `PermissionError('training usage evidence execution is fenced')`（`:73-82`）——**这是跨域写：训练历史写必须引用任务真值**。
- **历史格式**：`training_usage_token_schema(version)` 只有版本 1，且只在表为空时写入（`:55-57`），注释说明“只有存在 token 索引时才加 revision 表”（`:435-438`）。
- **迁移含义**：由于它在任务库，U5 的切换窗口天然覆盖它；但业务上属 U3。这个“物理归属 vs 业务归属”冲突必须在迁移前定案（§9 Q-1）。

### 2.18 任务级 `selection.sqlite3`（冻结选材清单）

- 结构：`selection(image_id PK, state CHECK(pending|running|succeeded|failed), error, tombstone_json, source_deleted, attempts)`、`counters`（由 3 个触发器维护）、`meta`、`assignment_evidence`（`material_batches.py:2218-2244`）。
- 连接设置：`journal_mode=WAL` + `synchronous=FULL`（`:2251-2254`）。
- **冻结语义**：`meta['frozen']` 存在即冻结（`BatchSelection.frozen`，`:2260-2261`）；冻结值来自 `meta['repository_revision']`（§3.1）。
- **迁移含义**：这是**任务级文件**，不迁入关系库（`F1:205` 已裁定先保留）。

### 2.19 任务级 rescan manifest

- 结构见 `storage/import_candidates.py:706-729`；`RescanCandidateStore` 在构造时就 `executescript` 建表（`:709-729`），即**首次触摸即定型**。
- 关键语义：`rescan_meta['scan_complete']` 才能确认策略（`:791-798`）；`finish_inventory` 用 baseline 反推 `MISSING`（`:775-780`）；`restart_rescan_inventory` 只清 `rescan_objects` 与 `scan_complete`，**保留**已核对的候选（`:764-768`）。
- **迁移含义**：任务级文件，随任务产物走；但 baseline 是“素材库某一时刻的投影”，所以在 U3 切换后 baseline 的 `payload_json` 会与新材料行不同版本——迁移校验必须允许这种差异并记录基线时刻（§9 Q-6）。

## 3. 三条 ATTACH 链 + 一条只读依赖链

### 3.1 链 A：批量选材冻结（`material_batches.py`，**写**链）

**形状**（`material_batches.py:524-578`）：

```sql
ATTACH DATABASE ? AS batch_selection            -- :525
PRAGMA batch_selection.synchronous=FULL         -- :526
BEGIN IMMEDIATE                                 -- :527
-- revision CAS（素材库权威在 main）
SELECT value FROM material_meta WHERE key='revision'   -- :528 与 selection.repository_revision 比对
INSERT INTO batch_selection.selection(image_id)
  SELECT m.id FROM main.materials m WHERE <predicate>   -- :533-536（FILTERED）
INSERT INTO batch_selection.selection(image_id) VALUES (?) -- :540-543（SELECTED）
SELECT COUNT(*) FROM batch_selection.selection s JOIN main.materials m ON m.id=s.image_id -- :544-547
INSERT INTO batch_selection.assignment_evidence SELECT ... FROM selection JOIN main.materials -- :564-571
INSERT INTO batch_selection.meta(key,value) VALUES ('frozen',...),('repository_revision',...) -- :574-577
COMMIT                                          -- :578
```

同类第二条写链（标签变换批处理）：`material_batches.py:2535-2573`（`ATTACH` → `BEGIN IMMEDIATE` → 取 revision → 分批插入 → 缺失校验 → 写 `meta(frozen/repository_revision/selection_kind)` → `COMMIT`）。

**方向**：读 `main`（素材库），写 `batch_selection`（任务级文件），**同一事务**。

**为什么必须原子**：`selection` 行是“这台任务的输入清单”。若清单已写但 `meta['frozen']` 未写，任务会被判“未冻结”（`material_batches.py:508-509`）；若 `frozen` 已写但清单只写了一部分，任务会处理一个不完整集合。两者都是数据错误，不是可重试的瞬态。

**PostgreSQL 等价合同**（拟议）：
1. **必须原子**：`selection`/`meta`/`assignment_evidence` 与“素材 revision 校验”在同一事务；素材行只读，不需要锁（但 revision 必须在该事务内读取并与调用方期望相等，不等即整批拒绝）。
2. **可以是任务级文件**：`selection` 本身（大清单、不可变证据）可继续作为任务产物；PG 只存 `selection_ref` + `selection_digest` + `repository_revision`。
3. **绝不能变成多请求读**：当前 `SELECT ... FROM main.materials WHERE <predicate>` 是**服务端一次性集合运算**。改成“先 HTTP 分页取 ID 再逐个确认”会引入 TOCTOU（素材在分页之间变化）且破坏 revision CAS 的意义。
4. 若 `selection` 迁入 PG：必须有 `UNIQUE(task_id, image_id)` 与 `UNIQUE(task_id)` 的 frozen 标记，且冻结写与素材 revision 校验同事务。

### 3.2 链 B：rescan manifest 基线快照（`material_repository.py`，**写**链）

**形状**（`material_repository.py:1790-1803`）：

```sql
ATTACH DATABASE ? AS rescan          -- :1793（任务产物文件）
BEGIN IMMEDIATE                       -- :1794
DELETE FROM rescan.rescan_baseline    -- :1796
INSERT INTO rescan.rescan_baseline SELECT id,object_key,payload_json
  FROM materials WHERE storage_source_id=?   -- :1797-1798
INSERT OR REPLACE INTO rescan.rescan_meta VALUES('baseline_complete','true') -- :1799
commit                                -- :1800
```

**方向**：读 `main`，写 `rescan`，同一事务。注释写明目的：“Copy only index metadata to the task DB in a consistent SQLite snapshot”（`:1791`）。

**为什么必须原子**：baseline 是“变更前状态”的唯一证据。之后 `finish_inventory` 用它反推 `MISSING`（`storage/import_candidates.py:775-780`）。基线不完整 → 所有“已消失对象”判定失效；`baseline_complete` 与 baseline 不同步 → 重扫会拿到半份基线却以为完整。

**PostgreSQL 等价合同**（拟议）：
1. **必须原子**：`baseline_complete` 标记与 baseline 行插入同事务；素材侧只读 + `storage_source_id` 过滤。
2. **可以是任务级文件**：manifest 文件本身（同上，PG 只存引用 + `baseline_digest` + `source_id` + `material_revision`）。
3. **绝不能变成多请求读**：baseline 必须是“一个时间点的投影”。分页导出会在页与页之间漏掉/重复对象，直接破坏 MISSING/CHANGED 判定的正确性。

### 3.3 链 C：训练选材（`training_material_picker_api.py`，**读**链，三库同语句）

**形状**（主查询 `:769-869`）：

```sql
-- 连接：main = materials.sqlite3
ATTACH DATABASE ? AS annotation_gt          -- :774-777（annotations.sqlite3）
ATTACH DATABASE ? AS usage_index            -- :596-597（tasks.sqlite3，只读 URI ?mode=ro）
BEGIN                                        -- :779（读事务）
SELECT revision FROM usage_index.training_usage_meta WHERE id=1 ...        -- :782-785 与期望比对
SELECT value FROM material_meta WHERE key='revision'                       -- :786-788
SELECT value FROM annotation_gt.annotation_meta WHERE key='revision'       -- :789-796
SELECT COUNT(*) FROM annotation_gt.task_negative_confirmations             -- :800-807
SELECT revision FROM negative_pool_meta WHERE id=1                         -- :808-815（在 main）
-- 之后整个页面查询与 COUNT 都在该事务内：
FROM materials m ... EXISTS(SELECT 1 FROM annotation_gt.annotation_label_references ...)
      ... NOT EXISTS(... usage_index.training_usage_tokens t ...)
      ... EXISTS(SELECT 1 FROM negative_pool_members np WHERE np.material_id=m.id)   -- :430-442,460-500
```

第二个只读入口（角色索引）：`:1187-1215`，同一三库形态，并显式要求 `(material_revision, annotation_revision)` 等于调用方快照（`:1198-1201`），不等即 `ValueError("素材或标注已更新，请重试")`。

**方向**：三库**只读**；唯一写入是缓存（进程内 `lru_cache`/dict，`:1165-1230`、`:632-646`）。

**为什么必须单事务**：页面结果由“素材行 + GT 状态 + 历史占用 + 负样本池成员 + 负样本确认数”共同决定。任一维度在两次查询之间变化，页面就会出现“总数与行不一致”“同一图既在又不在”的自相矛盾结果。

**PostgreSQL 等价合同**（拟议）：
1. **必须原子**：页面 + 总数 + 四个 revision 读取在**一个** `REPEATABLE READ`（或 `SERIALIZABLE`）事务内。三个域应是同一数据库的三个 schema，用普通 JOIN；**禁止**拆成三个跨 schema 的独立查询或三次 HTTP。
2. **可以是任务级文件**：`usage_index` 的 token 索引若未来独立存储，必须带 `revision` 高水位并在开页前校验；否则宁可留在同一库。
3. **绝不能变成多请求读**：`NOT EXISTS (usage tokens)` 与 `EXISTS (annotation refs)` 是**集合谓词**。改成“先取候选 ID 再逐个问 GT/历史”会让 20 万素材的页面退化为 N+1，并让缓存键失去意义（现状缓存键已包含 material+annotation 路径/inode/revision，`:620-631`）。
4. `usage_index` 现在用 `?mode=ro` 打开（`:596`）——这是“读别人库不许写”的显式声明，PG 侧对应只读事务或只读角色。

### 3.4 链 D：存储源依赖检查（`app.py`，只读 JOIN，非三方）

**形状**（`app.py:1929-1943`）：

```sql
-- 连接：selection.sqlite3 以 ?mode=ro 打开
ATTACH DATABASE ? AS material_index        -- :1931-1934（materials.sqlite3，?mode=ro）
SELECT 1 FROM selection s JOIN material_index.materials m ON m.id=s.image_id
 WHERE m.storage_source_id=? LIMIT 1       -- :1935-1940
```

**语义**：判断“某个存储源是否被活跃任务引用”。**失败即 fail-closed**：`sqlite3.DatabaseError` 被捕获后返回 `True`（视为有依赖，`:1941-1942`）；选择文件缺失也返回 `True`（`:1925-1928`）。

**迁移含义**：这是一条**跨库 JOIN 的安全判据**。PG 化后必须保持“查不到/出错 ⇒ 视为有依赖”的方向；把 `True` 改成 `False` 会允许删除仍被引用的存储源。

## 4. 跨库不变量：必须原子 / 可以是任务级文件 / 绝不能多次读

| # | 不变量 | 判定 | 依据 |
|---|---|---|---|
| I1 | `selection` 行集合 + `meta['frozen']` + `meta['repository_revision']` 三者同事务 | **必须原子** | `material_batches.py:524-578,2535-2573` |
| I2 | `rescan_baseline` + `baseline_complete` 同事务 | **必须原子** | `material_repository.py:1790-1803` |
| I3 | 页面行 + 总数 + material/annotation/usage/negative-pool 四个 revision 同一读快照 | **必须原子** | `training_material_picker_api.py:769-844` |
| I4 | GT 行写入 + `annotation_label_references` 派生 | **必须原子**（现状由触发器保证） | `annotation_repository.py:258-294` |
| I5 | GT 行写入 + `annotation_candidate_commits` 回执 | **必须原子** | 同事务 `:1403-1443` |
| I6 | GT 版本 CAS + 负样本审核证据 | **必须原子** | `:1444-1460` |
| I7 | 负样本池成员 + 分类链接 + `revision+1` + 操作回执 | **必须原子** | `negative_pool.py:55-86` |
| I8 | 素材行 + `material_labels` + `material_annotation_scopes` + `revision` | **必须原子** | `material_repository.py:603-657,1589` |
| I9 | 素材退休证据 + 素材行删除 | **必须原子** | `:1744-1760` |
| I10 | GT 删除前快照（`prepare_delete`）先于实际删除（`finalize_delete`） | **必须顺序，非原子**（两事务） | `:1577-1646` |
| I11 | GT 行 + 素材投影（`patch_annotation_projections`） | **允许最终一致**（不同库、不同事务，中间态由版本下界保护） | `:1465,1469-1471`；`:1666-1697` |
| I12 | `selection.sqlite3` 内容 | **可以是任务级文件** | `F1:205` |
| I13 | rescan manifest 内容 | **可以是任务级文件** | 同 I2 + `F1:207` |
| I14 | 选材页面 / 计数 / 角色索引 | **绝不能变成多请求读** | §3.3 |
| I15 | 基线与变更判定（MISSING/CHANGED） | **绝不能变成分页拼接** | §3.2 |

## 5. 冻结选择为什么不可变（以及它到底靠什么成立）

现状不是靠“写保护”，而是靠**四层约束叠加**：

1. **任务身份 ⇒ 文件位置**：`SELECTION_REF = "selection.sqlite3"`（`material_batches.py:49`），路径由 `artifacts.artifact_path(task_id, ...)` 派生，`task_id` 是唯一身份（`artifacts.py:68-93` 做路径安全校验）。
2. **冻结标记一次性**：`meta['frozen']` 与 `repository_revision` 同事务写入（`material_batches.py:574-578`），之后读取只判断“存在即冻结”（`:2260-2261`）。
3. **任务 ID 冲突即拒绝**：同一 `task_id` 已存在但 `request.json` 不同 → `BATCH_TASK_ID_CONFLICT`（`:503-506`）；已有 `assignment_request_digest` 但请求摘要不同 → 同样拒绝（`:516-519`）。
4. **重放时只重校验、不重写**：已冻结则直接写 `request.json`/`CHECKPOINT_REF` 并返回（`:520-523`），不再 `INSERT` 清单。

训练侧再叠一层：`assert_frozen_formal_test` / `admit_history_selection` 用冻结引用与 revision 做准入（`training_material_usage.py:571-643`）。

**迁移要求**：PostgreSQL 化后必须保留“冻结是一次性、不可改写”的性质。若 `selection` 进入 PG，必须有 `UNIQUE(task_id)` + `frozen_at` 非空后禁止 UPDATE 的约束；仅靠应用层判断不够（现状的“不可改”其实只靠代码路径，没有 DB 级禁止——这一点必须诚实记录，属开放问题 §9 Q-5）。

## 6. 影子迁移设计（可在切换前实施并对账）

> 目标：在任何切换之前，能反复导出、导入、对账，并给出可人工判断的差异报告。全部步骤**只读源库**。
> 复用既有范式：`algorithm_shadow.py`（确定性快照 + `snapshot_digest` + 校验 + 幂等导入 + `reconcile`），见 `algorithm_shadow.py:23-73,133-226,238-435,507-592,681-705`。

### 6.1 确定性快照

- 快照单位是**项目**（因为 `materials`/`annotations` 是 `<project>/*.sqlite3`，`material_repository.py:414`；`annotation_repository.py:141`）。
- 快照体（拟议结构，对齐 `algorithm_shadow.py:91-226`）：

```
{
  "contract_version": "u3-material-gt-negative-pool-shadow-v1",
  "project_id": "...",
  "material_revision": <int>,
  "annotation_revision": <int>,
  "negative_pool_revision": <int>,
  "usage_revision": <int|null>,          # 来自 tasks.sqlite3，可能不可用
  "tables": { "<name>": [ {<canonical row>}, ... ] },
  "row_counts": { "<name>": <int> },
  "snapshot_digest": "<sha256 of canonical body>"
}
```

- 规范化：`json.dumps(..., ensure_ascii=False, sort_keys=True, separators=(",",":"))`（与 `algorithm_shadow.py:83-88` 同法）；**所有行按自然键排序**（不是按物理顺序）。
- 敏感字段：不导出任何凭据（素材表本身不含凭据；`storage_source_id` 是引用，不是密钥）。
- **不做**：不导出图片字节、不读 OSS/NAS、不读 `task_runtime/artifacts` 里的大文件（只记录引用）。

### 6.2 分页导出

| 域 | 分页键 | 依据 |
|---|---|---|
| `materials` | `(created_at,id)` 或 `id` 键集 | `ix_materials_created`（`material_repository.py:96`） |
| `material_labels` / `material_annotation_scopes` | `(material_id,label_code)` | PK（`:113,119`） |
| `negative_pool_*` | 各自 PK | `negative_pool.py:24-31` |
| `annotations` | `image_id` 键集（**已有现成实现**） | `iter_records`（`annotation_repository.py:766-789`） |
| `annotation_label_references` | `(image_id,label_code)` | PK（`:248`） |
| `annotation_delete_backup` / `annotation_negative_reviews` / `annotation_candidate_commits` / `task_negative_confirmations` | PK | 见 §2.13-2.16 |
| `training_usage_*` | PK | `training_material_usage.py:43-61` |

**规则**：
- 每页必须在**同一读事务**内取“数据页 + 该域 revision”，跨页不要求同一快照（用 6.7 的高水位收口）。
- 页大小上限沿用现有批处理上限：GT 单批 ≤500（`annotation_repository.py:477-482`）、素材准入/对账单批 ≤500（`material_repository.py:1013-1014,1814-1815`）。
- 读连接用只读 URI（`material_repository.py:400-408` 的 `open_readonly`；`annotation_repository.py:125-136` 的 `open_readonly`）。

### 6.3 身份摘要（identity digest）

- 每行身份：`(table, natural_key)`；`natural_key` 由该表 PK 序列化得到（例：`materials:id`、`material_labels:material_id|label_code`）。
- 表级身份摘要：`sha256(sorted(natural_keys))`；快照级：`sha256(concat(table_digests in fixed order))`。
- **要求**：身份摘要与内容摘要分开报告。只比内容摘要会把“ID 集合相同但内容漂移”和“内容相同但 ID 不同”混为一类，无法定位。
- 与 `algorithm_shadow.py:666-678` 的差异结构保持一致：`missing` / `extra` / `changed` 三类。

### 6.4 GT 历史与 `expected_version`（诚实说明：没有历史表）

**代码里不存在 GT 版本历史表。** 持久化的“历史证据”只有五类：

1. `annotations.version` 单调计数 + `content_digest`（`annotation_repository.py:220-228,1403-1426`）；
2. `annotation_delete_backup`（按删除 token 的快照，`:231-240`）；
3. `annotation_negative_reviews`（按 `(image_id,source_version,actor,scope,source_hash)` 的审核事件，`:1450-1460`）；
4. `annotation_candidate_commits`（按 `(task_id,image_id)` 的提交回执，含 `operation_id`/`expected_version`/`version`，`:1351-1353`、`annotation_task_service.py:1024-1030`）；
5. `annotation_gt_audit.audit_gt_commit`（**只读比较**，模块 docstring 明确“不是第二 GT 存储”，`annotation_gt_audit.py:1-6,16-75`）。

因此迁移设计必须写成：

- **导出**：`annotations` 当前行 + `annotation_label_references` + `annotation_delete_backup` / `annotation_negative_reviews` / `annotation_candidate_commits` / `task_negative_confirmations` + `annotation_meta.revision`；
- **不导出/不承诺**：已被后续编辑覆盖的中间版本内容（不存在）；
- **`expected_version` 语义**：迁移后新库的 `version` 必须等于源库 `version`，否则任何冻结引用（`frozen_annotation_versions`，`annotation_task_service.py:901-902`）与 formal bulk 的 `gt_version` 基线（`annotation_bulk_commit.py:134-139`）都会失效；
- **校验**：对每个 `image_id`，`(version, content_digest)` 必须逐字节一致；`candidate_commit_receipts` 中的 `version == 源版本+1` 关系必须保持（`:139`）。

### 6.5 负样本池成员与分类

- 导出顺序（受 FK 约束）：`materials` → `negative_pool_members` → `negative_pool_categories` → `negative_pool_links` → `negative_pool_algorithm_members` → `negative_pool_meta` → `negative_pool_operations`。
- 校验：
  - 成员集合（`material_id` 集合）逐项一致；
  - 每个成员的分类集合一致（多重集）；
  - 算法级成员 `(algorithm_id,material_id)` 集合一致；
  - `negative_pool_meta.revision` 相等或目标更大（§6.7）；
  - **孤儿检查**：目标侧不得存在 `negative_pool_members.material_id` 不在 `materials` 的行（源侧因 FK 不可能有）。
- 资格（qualification）**不迁移**：它由 GT 现算（`negative_pool.py:398-429`）。迁移只保证“算得出同样结果”，即 GT 与标签一致即可。

### 6.6 标签链接

三个层次必须同时校验，且**不能互相替代**：

| 层 | 数据 | 权威 | 证据 |
|---|---|---|---|
| 素材标签投影 | `material_labels(label_code,box_count)` | 派生 | `material_repository.py:627-644` |
| 素材审核范围投影 | `material_annotation_scopes(label_code)` | 派生 | `:645-657` |
| GT 标签引用 | `annotation_label_references(label_code,image_id,box_count,scope_ref,annotation_state,source_kind)` | **权威**（由 GT 触发器生成） | `annotation_repository.py:241-294` |

对账口径（拟议）：对每个 `(image_id,label_code)`，从 GT 的 `boxes`/`scope` 重新计算期望的 `box_count`/`scope_ref`，再与三层数据比对；不一致必须报成“派生层漂移”而不是“数据丢失”。

### 6.7 revision 高水位

> 2026-11-27 更新（P0 已实现）：以下规则已落到 `u3_shadow.py` V4 的
> `picker_snapshot_state` + 导入保护中，并按“受 revision 约束的投影表”计算摘要
> （历史证据表不参与单调比较）。证据表的可变性由 Owner 侧单调 generation 保护：
> `task_negative_confirmations` → `annotation_meta.task_negative_confirmation_generation`，
> 其余证据表 → `annotation_meta.evidence_generation` / `material_meta.evidence_generation`
> （SQLite Trigger 同事务递增）。证据表的创建/删除/重建另由 Owner 侧结构版本
> （`evidence_structure_generation`，持久化于同一 meta 表）保护：结构变化必须由 Owner 认证，
> 否则导出失败关闭；导入必须看到更高的结构版本。实现与验收见
> [U3 Picker P0 Schema V4](U3_PICKER_P0_SCHEMA_V4_20261127.md)。

- 记录四个高水位：`material_revision`、`annotation_revision`、`negative_pool_revision`、`usage_revision`（若任务库不可读则记 `null` 并显式标注 `unavailable`，对齐 `training_material_usage.py:213-228` 的 `'unknown'` 语义）。
- 导入规则：
  - 目标 `revision` **必须 ≥** 源导入时的高水位；
  - 若目标已存在更高 revision（目标侧已发生新写），**拒绝导入**并要求重新导出（对齐 `algorithm_shadow.py:546-563` 的 `same revision different digest` 拒绝）；
  - 若 `revision` 相同且 `snapshot_digest` 相同 → 幂等成功（`:551-558`）。

### 6.8 幂等导入

> 2026-11-27 更新（P0 已实现）：`u3_shadow_import` 台账、同快照返回
> `ALREADY_APPLIED`、状态/游标/数据同事务提交均已实现；本文其余部分保留为原始设计记录。

- 每张表按自然键 `INSERT ... ON CONFLICT (natural_key) DO UPDATE`，但仅在 `(revision, digest)` 允许时才更新；
- 整个导入在**一个事务**内（跨表），因为 FK 与“成员+链接”一致性要求原子；
- 导入前写 `u3_shadow_import` 台账（拟议）：`(project_id, snapshot_digest, revision_snapshot_json, imported_at, outcome)`，`outcome ∈ {APPLIED, ALREADY_APPLIED, REFUSED}`；
- 重放同一 `snapshot_digest` 必须返回 `ALREADY_APPLIED` 且不产生任何写入（对齐 `repository.py:584-594` 的 `ALREADY_APPLIED` 语义）。

### 6.9 diff 报告（必须能被人读懂）

按 `algorithm_shadow.py:681-705` 的 `reconcile` 形态输出：

```
{
  "same": bool,
  "reason": "OK|SHADOW_MISSING|SOURCE_REVISION_CHANGED|SNAPSHOT_DIGEST_MISMATCH|DATA_MISMATCH|REVISION_REGRESSION",
  "source_revision": {...}, "shadow_revision": {...},
  "differences": {
     "<table>": {"missing": [...], "extra": [...], "changed": [...]}
  },
  "label_drift": {"<image_id>": {"layer": "material_labels|material_annotation_scopes|annotation_label_references", "key": "..."}},
  "pool_orphans": [...],
  "gt_version_mismatch": [{"image_id":..., "source":..., "shadow":...}],
  "receipt_mismatch": [{"task_id":..., "image_id":..., "field":...}]
}
```

**要求**：`differences` 里每项最多列前 N（如 200）条 + 总数，避免 20 万行报告不可用。
**标识归属**：`OK` / `SHADOW_MISSING` / `SOURCE_REVISION_CHANGED` / `SNAPSHOT_DIGEST_MISMATCH` / `DATA_MISMATCH` 沿用 `algorithm_shadow.py:681-705` 的既有标识；`REVISION_REGRESSION` 与 `u3_shadow_import` 是本设计**新增拟议**标识，现有代码中不存在，不得被当成已实现的错误码。

### 6.10 完整性检查（切换前必须全绿）

1. 行数：每表源/目标相等（除白名单的运行期表可能不存在）。
2. 身份集合：每表自然键集合相等。
3. 内容：每表逐行规范 JSON 摘要相等（§6.3）。
4. GT：`(image_id, version, content_digest, annotation_state, boxes, scope)` 逐字段相等。
5. 标签三层：§6.6 的重算结果一致。
6. 池：成员/分类/算法级成员集合相等，无孤儿。
7. 回执：`annotation_candidate_commits` 的 `(task_id,image_id,operation_id,version)` 关系保持；`negative_pool_operations` 的 `operation_id|identity|result_json` 相等。
8. 退休证据：`material_retirements` 逐行相等（含 `payload_json`/`annotation_json` 的规范摘要）。
9. revision：§6.7。
10. 读回：抽样 100 张，走**现有 API**（`AnnotationRepository.get_many`、`MaterialRepository.get_many`）读回并比对，证明不是“只在 SQL 层相等”。
11. 负向证明：故意构造一条差异（测试环境），确认报告能定位到具体表/键（防止“永远绿的检查器”）。

### 6.11 失败恢复

| 情形 | 处置 | 依据 |
|---|---|---|
| 导出过程中 revision 变化 | 丢弃本次导出，重新导出（不拼接两次的页） | §6.2 规则；`training_material_picker_api.py:1198-1201` 的“变化即重试”同构 |
| 导入事务中途失败 | 整体回滚；台账不写 `APPLIED` | §6.8 |
| 导入后 `snapshot_digest` 不符 | 视为未导入，删除本次导入行（按 `u3_shadow_import` 记录的范围），重导 | 需实现（§7） |
| 目标侧已出现新写（revision 更高） | 拒绝覆盖，要求重新导出 + 人工合并决策 | `algorithm_shadow.py:556-563` |
| 源库不可读（锁/损坏） | 中止，不产生部分快照；记录具体错误码 | 现有 `PAYLOAD_*`/`MaterialEvidenceIncomplete` 的错误分级可复用（`material_repository.py:42-53`） |

## 7. 明确未实现（不得当成能力）

1. **没有**任何 U3 的 Provider 抽象。`MaterialRepository`（`material_repository.py:418-427`）与 `AnnotationRepository`（`annotation_repository.py:144-152`）直接连 SQLite。
2. **没有**U3 的切换协议（无 marker、无准入记录、无 rollback 评估）。算法域与存储源域有，素材/GT 域没有。
3. **没有**影子快照工具。`algorithm_shadow.py` 只服务算法域（其 `_TABLES` 只有 algorithms/versions/analyses，`algorithm_shadow.py:45-50`）。
4. **没有**导出/导入 CLI。`algorithm_migration_cli.py` / `storage_source_migration_cli.py` 存在，但**不**覆盖素材/GT/池。
5. **没有** `u3_shadow_import` 台账，也没有 diff 报告生成器（§6.8/§6.9 是拟议）。
   - 2026-11-27：`u3_shadow_import` 台账与 `picker_snapshot_state`/`u3_projection_cursor` 已随 V4 实现；
     §6.9 的 diff 报告生成器仍未实现（现有 `reconcile()` 只给阻塞清单，不给逐键差异表）。
6. **没有** GT 版本历史（§6.4）。任何“回放到某一版本”的需求都无法用现有数据满足。
7. **没有**素材退休后的池成员恢复（§2.7 的级联后果）。
8. **没有**跨库原子性保证：GT 与素材投影是两次提交（`annotation_repository.py:1465,1469-1471`），中间失败会留下“GT 已变、投影未变”的窗口；现状靠版本下界与重算兜住，不是靠事务。
9. **没有** `training_usage_*` 的独立迁移能力：它只在任务库内，随 U5。
10. **没有**对 ATTACH 链的 PostgreSQL 等价实现或测试。

## 8. 测试矩阵

> `EXISTING` = 仓库已有测试（文件已确认存在）；`PROPOSED` = 未实现。

| # | 层 | 覆盖点 | 状态 | 依据 |
|---|---|---|---|---|
| T1 | unit | 素材 CRUD / revision 语义 / 分页 / 过滤器 / mutate 原子性 | EXISTING | `tests/unit/test_material_repository.py`（如 `test_crud_and_revision_use_sqlite_rows`、`test_compatibility_mutate_only_rewrites_changed_rows`、`test_mutate_ids_reads_only_requested_materials_and_preserves_identity`） |
| T2 | unit | schema 版本与旧库打开（schema 5 夹具） | EXISTING | `tests/fixtures/material_repository_schema5.sql`、`tests/unit/test_material_repository.py` |
| T3 | unit | 数据集删除声明 / 恢复 | EXISTING | `tests/unit/test_material_repository_delete_claims.py` |
| T4 | unit | GT 准入（删除声明 / 复核 / 内容变化） | EXISTING | `tests/unit/test_material_annotation_lifecycle.py`（`test_formal_annotation_admission_rejects_missing_delete_claim_and_stale_content`） |
| T5 | unit | GT 版本 CAS / 提交回执 / 取消不撕裂日志 | EXISTING | `tests/unit/test_annotation_task_service.py`（`test_commit_candidate_decisions_carries_formal_version_cas`、`test_cancel_arriving_after_formal_write_cannot_split_commit_journal`） |
| T6 | unit | 负样本池 CAS / 回执 / 资格由 GT 决定 | EXISTING | `tests/unit/test_negative_pool.py`（`test_qualification_uses_formal_gt_and_scope_not_membership`） |
| T7 | unit | rescan 基线/分类/提交 CAS | EXISTING | `tests/unit/storage/test_rescan_tasks.py`（如 `test_yolo_rescan_commit_cas_preserves_manual_edit_after_precheck`、`test_rescan_apply_rejects_tampered_canonical_annotation_evidence`） |
| T8 | unit | 选材历史 SQL（usage 排除 / annotation GT 子句） | EXISTING | `tests/unit/test_training_material_picker_history_sql.py` |
| T9 | unit | 训练历史 token 语义与准入 | EXISTING | `tests/unit/test_training_material_usage.py` |
| T10 | api | 选材 API：GT 计数缓存双 revision 失效、跨页冻结、角色过滤 | EXISTING | `tests/api/test_training_material_picker_api.py`（如 `test_formal_gt_filtered_count_reused_and_invalidated_by_both_revisions`、`test_cross_page_formal_scope_plan_is_bounded_durable_and_preserves_boxes`） |
| T11 | api | 标签治理与 GT 重映射 | EXISTING | `tests/api/test_label_integrity.py`、`tests/api/test_durable_label_remap.py` |
| T12 | api | 负样本闭环（人工确认写 GT + 训练计数） | EXISTING | `tests/api/test_w10_negative_closed_loop.py`、`tests/api/test_training_negative_review.py` |
| T13 | performance | 200k 素材 / 12k GT 深页 / picker 历史过滤 | EXISTING | `tests/performance/test_material_workbench_200k.py`、`tests/performance/test_training_picker_workbench_scale.py`、`tests/performance/test_picker_history_filters_scale.py`、`tests/performance/test_picker_200k_w3.py` |
| T14 | performance | `read()`/`mutate()` 规模成本 | EXISTING | `tests/performance/test_material_repository_scale.py`、`tests/performance/test_material_read_mutate_scale.py`（命令见 `F1:31-32`） |
| P1 | real PostgreSQL | 三条 ATTACH 链的等价 JOIN 在同一事务内给出与 SQLite 相同结果集 | PROPOSED | 需先有 PG schema |
| P2 | real PostgreSQL | 页面 + 总数 + 四 revision 的读快照一致性（并发写 GT/池时不出自相矛盾页） | PROPOSED | 同 P1 |
| P3 | real PostgreSQL | 批量选材冻结：revision 冲突时整批拒绝且不留半份清单 | PROPOSED | 需先迁 `selection` 或保留文件 + 摘要 |
| P4 | real PostgreSQL | rescan 基线 + `baseline_complete` 同事务 | PROPOSED | 同 P3 |
| P5 | 导入 | 幂等重放：同 `snapshot_digest` 两次导入只有一次 `APPLIED` | EXISTING (V4) | `tests/integration/test_u3_material_gt_postgres.py`（`test_replaying_an_applied_full_snapshot_changes_no_business_row`） |
| P6 | 对账 | 差异报告能定位 `missing/extra/changed` 与标签三层漂移 | PROPOSED | §6.9 |
| P7 | 对账 | 故意注入差异必须被检出（防“恒绿检查器”） | PROPOSED | §6.10 第 11 项 |
| P8 | 一致性 | `expected_version` 迁移后冻结引用仍可用（formal bulk 重放不误判） | PROPOSED | §6.4；关联 U5 的 `annotation_bulk_commit.py:98-152` |
| P9 | 一致性 | 素材退休后池成员/分类的预期行为被显式断言 | PROPOSED | §2.7 |

## 9. 开放问题（需 lead 决策）

- **Q-1 `training_usage_*` 的迁移归属**：物理在任务库（`training_material_usage.py:28`），业务属训练历史。随 U5 迁移会拉长 U5 的冻结窗口；分到 U3 则需要跨库双写协调（现在没有）。**必须二选一**，`F1:202-204` 未定。
- **Q-2 素材退休后的池成员语义**：`retire_many` 删除素材行，FK CASCADE 清掉 `negative_pool_*`（`material_repository.py:1744-1760`；`negative_pool.py:24-30`；`material_repository.py:426` 开启 FK）。当前**没有**恢复路径，也**没有**在退休证据里保存池成员。这是既有行为还是缺陷？若是缺陷，属于产品/数据安全变更，需独立批准；若是既有语义，迁移时必须原样保留并在文档声明。
- **Q-3 冻结选择是否有 DB 级不可变**：现状“冻结后不可改”只靠代码路径（`material_batches.py:507-523,2260-2261`），没有 `UNIQUE(task_id)` 之外的 DB 约束。迁移到 PG 时是否升级为硬约束（会改变“历史任务兼容”的边界）？
- **Q-4 `task_negative_confirmations` 的 revision 是 `COUNT(*)`**（`annotation_repository.py:1494-1498`）。这是弱合同：删除会改小计数、并发插入会跳变。迁移时是保留弱语义（兼容）还是升级为真 revision（更正确但不兼容）？
- **Q-5 跨库读快照的强一致性口径**：`training_material_picker_api.py:769-844` 在一个 SQLite 事务里读三个文件。多库读事务的快照据 SQLite 语义是**按文件惰性建立**的，因此“同一瞬间”不是引擎级保证（本轮未做引擎级实验验证；代码本身用“读后校验 revision + 调用方重试”兜底，见 `:782-818,1198-1201`）。PostgreSQL 单库能给真快照。是否要求迁移后**保留**“revision 变化即重试”的行为（更保守）还是改为“依赖 MVCC 快照”（更快但不兼容现有重试语义）？
- **Q-6 rescan baseline 的版本归属**：baseline 是素材库某时刻的投影（`material_repository.py:1797-1798`），但没有记录写 baseline 时的 `material_revision`。迁移后是否补记该高水位（属于 schema 变更，不在本文范围）？若不补，跨切换窗口的历史 rescan 无法证明其基线时点。
- **Q-7 `annotation_label_references` 的触发器是否必须保留**：PG 化后可用触发器、也可用应用层双写。若改应用层，就会引入“GT 已写、索引未写”的新窗口（现状不存在，因为触发器同事务，`annotation_repository.py:258-294`）。倾向保留触发器语义，但需确认 PG 版本与运维支持。
- **Q-8 存储源依赖检查的 fail-closed 方向**：`app.py:1941-1942` 把 `sqlite3.DatabaseError` 判为“有依赖”。PG 化后网络错误也应按同方向处理（更保守），但这会让“存储源不可用”直接阻断删除操作。需要确认产品上可接受。

## 10. 证据索引

- `platform_core/material_repository.py`：`:27-31` schema 与可读版本；`:33-39` 旧 stored_name 上限；`:42-53` 证据不完整异常；`:69-154` 全表 DDL；`:190-219` 生命周期锁；`:386-395` 受控写栅栏；`:398-427` 只读打开/FK/连接；`:432-444` 必需对象；`:575-586` revision 读写；`:588-658` 行写入（含标签/范围重写）；`:660-711` 旧 JSON 迁移；`:817-861` 数据集删除声明；`:997-1040` GT 准入；`:1579-1637` upsert/patch；`:1639-1705` GT 投影；`:1707-1784` 延迟清理/退休/删除；`:1790-1803` rescan 基线 ATTACH；`:1805-1882` storage 对账；`:1884-1918` 引用与回执查询；`:1920-1972` 分配回执与素材变更同事务。
- `platform_core/negative_pool.py`：`:1-4` 定位（管理关联，不写 GT）；`:23-33` DDL；`:55-86` `_mutate`（回执+revision CAS）；`:88-103` revision/快照；`:105-135` 回滚；`:219-296` 成员操作；`:398-429` 资格现算。
- `platform_core/annotation_repository.py`：`:21` schema 版本；`:125-152` 只读/连接；`:174-177` 索引就绪标记；`:219-256` 表与触发器；`:445-475` legacy 影子读；`:683-728` 索引重建；`:730-764` revision 与指纹；`:766-789` 全量遍历；`:1233-1260` 候选回执读；`:1261-1291` 保护写校验；`:1292-1472` GT 写入与 CAS；`:1450-1462` 负样本审核表；`:1494-1539` 任务级负样本回执；`:1541-1548` 审核证据只读；`:1557-1712` 删除/恢复族。
- `platform_core/annotation_gt_audit.py`：`:1-6` 非第二存储；`:16-75` 只读比较状态机。
- `platform_core/annotation_bulk_commit.py`：`:98-152` GT 证据状态机（跨域校验点）。
- `platform_core/training_material_picker_api.py`：`:362-387` 池过滤构造；`:390-419` 算法级负样本回执；`:422-500` 共享谓词（三库子查询）；`:566-576` usage revision 子句；`:592-599` usage 只读 ATTACH；`:602-646` GT 计数缓存键；`:769-869` 主页面读事务；`:1165-1215` 角色索引；`:1253-1294` 过滤快照；`:1340-1348` 池 revision 复检。
- `platform_core/training_material_usage.py`：`:22-38` 路径与连接；`:40-71` 表与 revision 触发器；`:73-82` 执行栅栏；`:84-123` 登记；`:180-203` 执行记录；`:241-258` 空历史与 revision；`:571-643` 冻结准入。
- `platform_core/material_batches.py`：`:49` 清单文件名；`:429-430` 估算要求 revision；`:502-579` 冻结写链（ATTACH）；`:2218-2292` 清单结构与连接设置；`:2499-2592` 标签变换写链（ATTACH）；`:2827-2828` 冻结 revision 复核。
- `platform_core/storage/import_candidates.py`：`:653-673` 稳定 ID 派生；`:706-729` rescan 表；`:740-839` baseline/分类/完成/策略/应用。
- `app.py`：`:1896-1943` 存储源依赖检查（跨库只读 JOIN + fail-closed）。
- `platform_core/algorithm_shadow.py`：`:23-73` 影子契约与 DDL；`:133-226` 导出；`:238-435` 校验；`:507-592` 幂等导入；`:666-705` 对账。
