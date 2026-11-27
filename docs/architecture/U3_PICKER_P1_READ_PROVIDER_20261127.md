# U3-P1 Picker PostgreSQL 只读读取层（2026-11-28 收口版）

> 一个内部读取合同 + 两个 Provider（SQLite 基准、PostgreSQL 投影）。SQLite 仍是唯一业务
> Owner；PostgreSQL 只读；现有 Picker API/UI/训练链路未切换、未修改。
> 真实 PostgreSQL 16 定向用例 **39 passed / 0 skipped**（§6）。

## 1. 模块与边界

| 模块 | 作用 |
|---|---|
| `platform_core/training_material_picker_read.py` | Provider 合同、DTO、SQLite 基准 Provider、PostgreSQL Provider、项目绑定的 Owner 版本源、内部 cursor、**可复用读取会话** |
| `platform_core/training_material_picker_api.py` | **未修改**；SQLite 基准 Provider 直接复用 `_gt_material_filter_page` / `_picker_filter_sql` |
| `platform_core/u3_shadow.py` | **未修改**；PostgreSQL 只读 `w3_material_gt`（V4），不导入、不写 |

合同：`read_page` / `iter_candidates` / `get_many` / `get_annotations` / `get_pool_relations` /
`get_task_negative_receipts` / `revision_vector` / `snapshot_context`，外加
`PostgresPickerReadProvider.read_session(project_id)` 上下文管理器。

**项目身份合同（P0 收口）**

- `SQLitePickerReadProvider(project_path, project_id=...)` 必须显式绑定项目；每个公开方法
  核验请求 `project_id`，不一致抛 `PICKER_PROJECT_MISMATCH`，不靠目录名或素材 ID 猜测。
- `sqlite_owner_revision_source(project_path, project_id)` 返回的 callable **也绑定项目**：
  传入其它项目直接拒绝；返回的 `OwnerRevisionVector` 携带 `project_id`，Provider 再核对一次。
- 相同 revision、相同素材 ID 的不同项目永远不会被视为等价；PG 读取自身按请求项目的
  `picker_snapshot_state` 进行。
- `verify_owner=False` 允许按请求项目读取独立投影（诊断/快照内比较），但
  `owner_equivalent=False`，不得描述为当前 Owner 权威数据。

## 2. 支持矩阵

### 已实现（P1）

| 能力 | 说明 |
|---|---|
| 项目隔离 | 所有查询强制 `project_id`；Provider/Owner 源双向绑定 |
| 处理状态 | 沿用既有合同：`processing_status='processed'`（其它值显式 `PICKER_FILTER_UNSUPPORTED`） |
| 文件名关键字 | ASCII 大小写折叠（`translate` 双向，`ESCAPE ''`），与 SQLite `LIKE ... COLLATE NOCASE` 的通配符/无转义语义一致 |
| 存储源 | 单/多来源；重复参数归一化 |
| 创建时间 | `created_from`/`created_to`；纯日期 `to` 补 `T23:59:59.999999+00:00`；非法历史时间用 `pg_input_is_valid` 跳过而不是报错；**仅声明 ISO-8601 等价** |
| 标签 | 单/ANY/ALL/重复归一化；判据为正式 GT 引用（`annotation_state='annotated' AND box_count>0`） |
| 正式 GT | `require_ground_truth`、`annotation_state`（annotated/confirmed_empty/unannotated） |
| 显式 ID | `image_ids`（去重，项目内） |
| 负样本池 | `negative_pool_only`、分类、算法（算法单独不激活，沿用既有合同）；JSONB `deleted`/claim/`deleted_at` 与 SQLite `json_extract` 的 NULL 语义一致 |
| 排序 | `(created_at, id)` 稳定排序 + `COLLATE "C"` + NULLS 与 SQLite 对齐 |
| 分页 | page/page_size（1..120）与 keyset cursor（`limit+1`）；cursor 绑定查询指纹 + `snapshot_id` |
| 统计 | exact = SQL `COUNT(*)`；deferred 不执行 COUNT |
| 候选流 | keyset 分批；`batch_size` 为上限，内部页 ≤120；不执行 COUNT；支持从 `read_page` 的 cursor 续读；不支持 page 模式 |
| 批量读取 | 单次 ≤5000 ID，内部 500 一批；SQLite 同样分块（避免 SQLite 变量上限） |
| 读取会话 | `read_session()` 在 ONE `REPEATABLE READ, READ ONLY` 事务内组合 page/count/annotations/池/回执；会话关闭时执行 Owner 后置复核 |
| 快照 | READY 门禁、snapshot_id、revision_vector、MVCC 读身份；Owner 版本前后复核 |
| 确认回执 | 公共 DTO；区分 `absent` / `present_empty` / `present`；仅 present 且 Owner 一致时权威；缺表保留历史但不作为现行确认 |

### 暂不支持（显式失败）

- 训练历史 / usage 过滤、样本角色、数据集/训练/验证划分；
- `processing_status` 除 `processed` 以外的取值；
- `iter_candidates` 的 page 模式；回执读取未给显式 `image_ids`；
- 非 ISO-8601 的历史时间格式（不宣称与 `julianday` 全部等价）。

### 无法证明等价（显式标记）

- `source_kind='legacy'` 引用无正式 GT 行 → `unproven_legacy_ids`（过滤可用，不伪造内容）。
- Owner 版本缺失/非法/负数/布尔、结构未认证、证据表集合变化 → `PICKER_OWNER_UNVERIFIABLE`。
- 已发布快照缺字段、`revision_vector` 为空、顶层列与向量不一致、结构未认证 →
  `PICKER_SNAPSHOT_STALE`。

### 后续阶段

P2（历史/角色/用途/资格）、P3（变更日志）、P4（200k、双端差分）、P5（生产切换，未启用）。

## 3. 语义细节

1. **READY ≠ 当前等价**。`READY` 只证明某个完整快照已导入；默认 `verify_owner=True` 要求
   三项 revision、三项 generation、两个 structure generation、两侧证据表集合与认证、
   顶层列与 `revision_vector` 全部一致，任何缺失或非法类型都拒绝（不再把缺字段当 0）。
   Owner 源只读 meta 与表存在性（每个 DB 一个只读事务），不导出数据、不算 content_digest、
   不统计证据表。
2. **同一 MVCC 快照**：`read_page` 的页面/COUNT/GT，以及 `read_session` 内的多次组合查询
   共用同一 `REPEATABLE READ, READ ONLY` 事务；会话关闭时复核 Owner，变化即失败关闭。
3. **确认回执权威性**：`absent` 时保留历史但不作为现行确认；`present_empty` 时现行结果为空；
   `present` 且 Owner 一致时返回记录。`verify_owner=False` 的会话标记
   `owner_equivalent=False`。
4. **NULL/空串/0/false**：按投影原值比较；`annotation_state` 缺失按 `COALESCE 'unannotated'`；
   负样本池生命周期条件对“字段缺失 / JSON null”与 SQLite `json_extract` 一致（均为 NULL）。
5. **负样本关系 ≠ 训练资格**：P1 只读成员/分类/算法关系，不做任务级资格或角色判断。
6. **Cursor**：内部 cursor = `{created_at, id, 查询指纹, snapshot_id}`；筛选或快照不一致 →
   `PICKER_CURSOR_CONTEXT_MISMATCH`。
7. **错误不伪装**：PG 不可用 → `PICKER_PROJECTION_UNAVAILABLE`；查询失败 →
   `PICKER_QUERY_FAILED`；快照缺失/非 READY/过期 → `PICKER_SNAPSHOT_MISSING` /
   `PICKER_SNAPSHOT_NOT_READY` / `PICKER_SNAPSHOT_STALE`；项目不符 →
   `PICKER_PROJECT_MISMATCH`。不返回伪造的 `total=0`，不静默回退 SQLite。

## 4. 错误码

`PICKER_READ_FAILED`、`PICKER_PROJECTION_UNAVAILABLE`、`PICKER_QUERY_FAILED`、
`PICKER_SNAPSHOT_MISSING`、`PICKER_SNAPSHOT_NOT_READY`、`PICKER_SNAPSHOT_STALE`、
`PICKER_OWNER_UNVERIFIABLE`、`PICKER_PROJECT_MISMATCH`、`PICKER_CURSOR_CONTEXT_MISMATCH`、
`PICKER_FILTER_UNSUPPORTED`。

## 5. 性能与索引

`EXPLAIN (ANALYZE, BUFFERS)`（12 行 fixture）：基础分页走 `material_pkey` + `Sort
(created_at COLLATE "C", id COLLATE "C")`；标签 ANY 走 `idx_picker_gt_label`；负样本池走
`idx_picker_pool_joined`；执行 0.09–0.17 ms。小表计划由优化器决定，不强制索引；未发现必须
新增的索引。正式规模（200k、深页、精确计数）属 P4，不宣称 PostgreSQL 更快。

## 6. 测试

`tests/integration/test_u3_picker_read_postgres.py`（真实 PostgreSQL 16，无 skip，**39 passed**）：

- A 基础筛选等价（8 个参数组合）；B 标签与正式 GT；C 负样本池；
- D 分页：相同 created_at、ASC/DESC、页码、cursor 全量遍历、exact/deferred、非法/过期 cursor；
- E 批量与项目隔离（缺失/重复 ID、legacy unproven、两个项目互不可见）；
- F 一致性：READY/STALE、Owner revision/证据/结构变化、坏 DSN、MVCC 同快照、确认回执权威性；
- **G 项目身份绑定**：相同 revision + 相同素材 ID 的两个项目，A 的 Provider/Owner 源拒绝 B，
  跨 `get_many`/`get_annotations`/`get_pool_relations`/回执均不能串数据；
- **H Owner 等价失败关闭**（参数化）：PG 缺流 / 空向量 / 结构未认证 / 顶层列不一致 /
  Owner 缺键 / 负值 / 非整数 / 结构未认证，以及合法初始 0 与正常等价；
- **I 候选流**：默认 batch、150 条 fixture（内部页 ≤120）、cursor 续读、page 模式与非法 cursor 拒绝；
- **J DTO/回执**：include_payload 行为、get_many payload 一致、回执公共 DTO、
  absent/present_empty/present、无 ID 回执拒绝、批量上限；
- **K JSONB 生命周期**：字段缺失 / JSON null / false / 0 / true / claim / deleted_at 与 SQLite 等价；
  重复来源/分类/ID/标签归一化；非法日期与非法状态显式报错；
- **L 读取会话**：并发 PG 提交后同一会话仍读原 MVCC 快照，新会话才看到新投影；
  跨项目会话拒绝。

CI：`Storage Cache Governance` 拆成 **P0 步骤（≥50 项）** 与 **P1 步骤（≥20 项）**，各自
JUnit 报告与跳过/失败门禁，分别证明实际执行；P1 依赖补 `Pillow`/`starlette`/`psutil`
（P1 SQLite 基准复用 `training_material_picker_api` 的模块级 import chain，FastAPI 仍懒导入）。

## 7. 明确未做

- 未接入现有 Picker API 路由，未切换生产读取；`training_material_picker_api.py` 零改动。
- 未新增 Schema V5、未改历史 DDL/checksum、未装 `pg_trgm`、未引入缓存/ORM/微服务。
- 未实现 P2/P3/P4/P5，未做 20 万级性能测试。
