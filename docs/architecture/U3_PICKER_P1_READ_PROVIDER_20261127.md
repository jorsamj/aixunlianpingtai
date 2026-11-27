# U3-P1 Picker PostgreSQL 只读读取层（2026-11-27）

> 本轮实现 P1：一个内部读取合同 + 两个 Provider（SQLite 基准、PostgreSQL 投影）。
> SQLite 仍是唯一业务 Owner；PostgreSQL 只读；现有 Picker API/UI/训练链路未切换、未修改。
> 真实 PostgreSQL 16 定向用例 **23 passed / 0 skipped**（§6）。

## 1. 模块与边界

| 模块 | 作用 |
|---|---|
| `platform_core/training_material_picker_read.py` | Provider 合同、DTO、SQLite 基准 Provider、PostgreSQL Provider、Owner 版本源、内部 cursor |
| `platform_core/training_material_picker_api.py` | **未修改**；SQLite 基准 Provider 直接复用 `_gt_material_filter_page` / `_picker_filter_sql` |
| `platform_core/u3_shadow.py` | **未修改**；PostgreSQL 只读 `w3_material_gt`（V4），不导入、不写 |

Provider 合同（`PickerReadProvider`）：

```
read_page(query) -> PickerPage          # items + total/has_more/next_cursor + snapshot info
iter_candidates(query, batch_size)      # keyset 分批，默认 500，上限 500
get_many(project_id, ids)               # 有界批量，输入顺序，缺失不发明
get_annotations(project_id, ids)        # 正式 GT + legacy 不可证明标记
get_pool_relations(project_id, ids)     # 成员/分类/算法归属（只读关系）
get_task_negative_receipts(project_id, context_key, ids)
revision_vector(project_id)
snapshot_context(project_id)
```

- `SQLitePickerReadProvider`：包装现有 Picker 查询引擎（不是第二套 SQLite 引擎），并在读取前后复核 Owner 版本；它是语义基准。
- `PostgresPickerReadProvider`：独立 SQL、单事务 `REPEATABLE READ, READ ONLY`、`SET LOCAL TIME ZONE '+00:00'`、`statement_timeout`；不继承 `MaterialRepository`、不读全量快照、不做 Python 全量筛选、不回退 SQLite、不执行 `ensure_schema`/导入。

## 2. 支持矩阵

### 已实现（P1）

| 能力 | 说明 |
|---|---|
| 项目隔离 | 所有查询强制 `project_id` |
| 处理状态 | 沿用既有合同：`processing_status='processed'`（其它值显式 `PICKER_FILTER_UNSUPPORTED`） |
| 文件名关键字 | ASCII 大小写折叠（`translate` 双向，`ESCAPE ''`），与 SQLite `LIKE ... COLLATE NOCASE` 的通配符/无转义语义一致 |
| 存储源 | 单/多来源 `IN`/`= ANY` |
| 创建时间 | `created_from`/`created_to`；纯日期 `to` 补 `T23:59:59.999999+00:00`；非法历史时间用 `pg_input_is_valid` 跳过而不是报错 |
| 标签 | 单标签、ANY、ALL、重复参数归一化；判据为**正式 GT 引用**（`annotation_state='annotated' AND box_count>0`） |
| 正式 GT | `require_ground_truth`（正框或 `confirmed_empty AND scope_ref=1`）、`annotation_state` 的 annotated/confirmed_empty/unannotated |
| 显式 ID | `image_ids`（去重，项目内） |
| 负样本池 | `negative_pool_only`、分类、算法归属、组合；**算法 ID 单独不激活池过滤**（与既有 `_pool_filters` 合同一致，只在池过滤激活后收窄） |
| 排序 | `(created_at, id)` 稳定排序，ASC/DESC，相同时间用 id 决胜；NULL 与 SQLite 一致（ASC 前、DESC 后） |
| 分页 | page/page_size（1..120，越界/超末页显式错误）与 keyset cursor（`limit+1` 判断 has_more） |
| 统计 | exact = SQL `COUNT(*)`（全部 EXISTS 谓词，无 JOIN 重复）；deferred = `total=None`，不执行 COUNT |
| 批量读取 | 单次 ≤5000 ID，内部 500 一批；无 N+1 |
| 快照 | READY 门禁、snapshot_id、revision_vector、MVCC 读身份；Owner 版本前后复核 |
| 确认回执 | 只在源表 present 且 Owner generation 一致时权威；否则 `authoritative=False`、`receipts=()`，不删除历史 |

### 暂不支持（显式失败）

- 训练历史 / `usage_*` 过滤、样本角色、`browse_only` 以外的历史策略；
- 数据集 / 训练集 / 验证集划分过滤；
- 全部素材处理状态（仅 `processed`）；
- 公开 cursor 格式变更（P1 cursor 仅内部使用）。

### 无法证明等价（显式标记）

- `annotation_label_reference.source_kind='legacy'` 且无 `annotation` 行：过滤可用，但
  `get_annotations` 返回 `unproven_legacy_ids`，不伪造 boxes/scope/version/digest，也不当作“未标注”。
- Owner 结构版本未认证、所有者版本缺失或投影缺表：`PICKER_OWNER_UNVERIFIABLE`，绝不报告当前等价。

### 后续阶段

- P2：训练历史、样本角色、训练用途/数据集划分、任务级负样本资格。
- P3：Owner 变更日志与增量同步（Provider 仍消费 `picker_snapshot_state`，不建第二套版本）。
- P4：200k/百万级性能、全量双端差分、切换演练。
- P5：生产读取切换（本轮未启用任何开关）。

## 3. 语义细节（与 SQLite 基准对齐）

1. **READY ≠ 当前等价**。`READY` 只证明某个完整快照已导入；`read_page` 默认
   `verify_owner=True`，用只读 Owner 版本源核对：三项 revision、三项 evidence generation、
   两个 structure generation、两侧证据表集合与结构认证。全部一致才返回，否则
   `PICKER_SNAPSHOT_STALE` / `PICKER_OWNER_UNVERIFIABLE`。Owner 源只读 meta 与表存在性，
   不导出数据、不算 content_digest、不统计证据表。
2. **同一 MVCC 快照**：页面、COUNT、GT hydration 在同一 `REPEATABLE READ, READ ONLY` 事务内；
   测试用并发提交证明事务内计数不变、新读取才可见。
3. **确认回执权威性**：`revision_vector.negative_confirmation.tables` 为空（源表 absent）时，
   PostgreSQL 保留的投影是历史，不作为现行确认；present-but-empty 时现行结果为空。
4. **NULL / 空字符串 / 0 / false**：全部按投影原值比较；`annotation_state` 缺失按
   `COALESCE(...,'unannotated')`，与既有 Picker SQL 一致；不改写任何默认值。
5. **负样本关系 ≠ 训练资格**：P1 只读成员/分类/算法关系，不做任务级资格、冲突或角色判断。
6. **Cursor 绑定**：内部 cursor = `{created_at, id, 查询指纹, snapshot_id}`；
   筛选条件或快照不一致 → `PICKER_CURSOR_CONTEXT_MISMATCH`，不静默继续。
7. **错误不伪装**：PostgreSQL 不可用 → `PICKER_PROJECTION_UNAVAILABLE`；
   查询失败 → `PICKER_QUERY_FAILED`；快照缺失/非 READY → `PICKER_SNAPSHOT_MISSING` /
   `PICKER_SNAPSHOT_NOT_READY`。任何情况都不会返回伪造的 `total=0` 或静默回退 SQLite。

## 4. 错误码

`PICKER_READ_FAILED`、`PICKER_PROJECTION_UNAVAILABLE`、`PICKER_QUERY_FAILED`、
`PICKER_SNAPSHOT_MISSING`、`PICKER_SNAPSHOT_NOT_READY`、`PICKER_SNAPSHOT_STALE`、
`PICKER_OWNER_UNVERIFIABLE`、`PICKER_CURSOR_CONTEXT_MISMATCH`、`PICKER_FILTER_UNSUPPORTED`。

## 5. 性能与索引

小 fixture 上 `EXPLAIN (ANALYZE, BUFFERS)` 结论（详情见交付报告）：

- 基础分页：`material_pkey (project_id)` + `Sort (created_at COLLATE "C", id COLLATE "C")` + `Limit`；
- 标签 ANY：`idx_picker_gt_label`（Bitmap Index Scan on `annotation_label_reference`）；
- 负样本池：`idx_picker_pool_joined` + `material_pkey`；
- 12 行 fixture 执行时间 0.09–0.17 ms；小表 Seq/Index 选择由优化器决定，不强制索引。
- 未发现必须新增的索引；正式规模（200k、深页、精确计数）验证属 P4，不宣称 PostgreSQL 更快。

## 6. 测试

`tests/integration/test_u3_picker_read_postgres.py`（真实 PostgreSQL 16，无 skip，23 passed）：

- A 基础筛选等价：无筛选、文件名大小写、来源、时间范围、组合、显式 ID；
- B 标签与正式 GT：单/ANY/ALL/重复、`require_ground_truth`、confirmed_empty/unannotated、
  声明标签不得冒充正式 GT；
- C 负样本池：成员/分类/算法/组合、算法单独不激活、关系读取；
- D 分页：相同 `created_at`、ASC/DESC、页码、cursor 全量遍历（无重/无漏）、exact/deferred、
  非法 cursor、筛选不匹配 cursor、新快照后旧 cursor 拒绝、超末页拒绝；
- E 批量与隔离：缺失/重复 ID、GT hydration、legacy 不可证明标记、两个项目互不可见；
- F 一致性与失败关闭：REPEATABLE READ/READ ONLY 实际生效、count/page 同 MVCC 快照
  （并发提交不可见）、STALE 拒绝、Owner revision/证据 generation/结构变化拒绝、
  无 Owner 源拒绝、坏 DSN 不返回空结果、确认投影权威性（缺表保留历史但非现行）；
- G 候选流（有界、完整）与 SQLite Provider 委托证明（现有引擎仍被调用）。

CI：`Storage Cache Governance` 的 U3 步骤已加入该文件，并把“跳过后仍绿”的 JUnit 门禁改为
**跨全部 suite 汇总**（`tests < 70` 视为未收集完整）。

## 7. 明确未做

- 未接入现有 Picker API 路由，未切换任何生产读取；`training_material_picker_api.py` 零改动。
- 未新增 Schema V5、未改历史 DDL/checksum、未安装 `pg_trgm`、未引入缓存/ORM/微服务。
- 未实现 P2/P3/P4/P5，未做 20 万级性能测试。
