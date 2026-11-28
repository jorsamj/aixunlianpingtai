# U3-P2 业务读取合同 + P3-A 前置准备｜实施计划

**目标**：在 P1 只读 Provider 之上建立统一业务读取合同：PG 基础候选流 + SQLite 权威训练历史/角色/用途判断，最终分页/计数正确，冻结集合可只读等价验证；P3-A 形成增量同步准备文档。

**架构**：新增 `platform_core/training_material_business_read.py`，组合 `PickerReadProvider`（P1）、`TrainingMaterialUsage.query_filter`（历史权威）、`training_label_tasks.training_material_role`（角色权威）、`AnnotationRepository`（确认回执）。不新增第二套历史/角色规则，不双写，不切换生产。

**计划文档**：`docs/plans/2026-11-28-u3-p2-business-read.md`（本文件）

## 全局约束

- 分支 `feature/external-algorithm-publishing`；VERSION `42.24.592` 不变；四份受保护未跟踪文档不提交。
- SQLite 仍是业务 Owner；PG 只读；不新增 Schema V5；不改历史 DDL/checksum。
- 只跑 P2 新增/直接受影响定向测试；不跑全仓/Playwright/构建/20 万级测试。

## 任务

### T1 P2-0 前置收口（P1 补丁）
- `PickerReadSession.candidates()` 消费 cursor、拒绝 page 模式、与 `iter_candidates` 共用实现。
- 确认合同：Owner/快照的 `negative_confirmation` 结构版本、认证、表集合、顶层 revision/generation、`table_state.present` 交叉核验；SQLite 回执 generation/presence/rows 单事务读取。
- `Storage Cache Governance` paths 增加 Picker Provider 与 P2 相关模块。
- 测试：P1 套件全通过 + 新增 3 个 P2-0 用例（session cursor、确认交叉核验、absent 回执）。

### T2 P2-A 历史合同（`training_material_business_read.py`）
- `BusinessFilter.history_policy/history_scope/usage_state/algorithm_asset_id/usage_role/browse_only`，语义映射 `TrainingMaterialUsage.query_filter` 的 `state/excluded/benchmark_protected/current_algorithm_trained/other_algorithm_trained`。
- 复用 `_relation_tokens`（经 `query_filter`），不新建哈希/关联。
- 失败关闭：`index_health` 不可用/损坏 → `PICKER_HISTORY_UNAVAILABLE`；coverage 不完整 → 只可能 `unknown`，不伪造 `unused`。

### T3 P2-B 角色
- `training_material_role(row, contract)` + `pending_negative`/部分正样本提升（`task_negative_confirmable` / `task_partial_scope_confirmable`），与 picker 角色页一致。
- 正式 GT 优先；legacy 无原文时保持 `pending_review` 并标记 `legacy_unproven`。

### T4 P2-C 用途/数据集
- `usage_role=train|test` 传给 `query_filter`；`eval_only`/`test_reserved` 直接采用既有状态；不做新的 split。

### T5 P2-D 确认回执消费
- 每批通过 P1 `get_task_negative_receipts` 读取（权威且 owner 等价才使用）；校验 `image_id/source_content_sha256/annotation_version/annotation_hash/context_key` 与当前素材+GT 一致；不满足则不作为当前确认。

### T6 P2-E 复合筛选/统计
- `BusinessReadProvider.iter_candidates()`：有界候选流 → 批量 hydration（材料/GT/回执/历史）→ 角色/用途 → 过滤。
- `read_page()`：最终分页（skip/limit）、exact（全流计数，不重复 COUNT）、deferred（`total=None`，`limit+1` 判 has_more）、cursor 绑定业务指纹+快照+历史版本。
- 同一流内不因某批无匹配而停止。

### T7 P2-F 冻结等价
- `selection_digest(ids)` 复用冻结清单摘要规则（排序后 `id+"\0"` sha256）。
- `compare_candidate_sets(a, b, query)`：完整消费两流后比较 ID 集合/数量/摘要；流未完成或 Owner 变化 → 失败关闭，不输出部分成功。

### T8 P2-G 版本一致性
- 前后 `training_usage_meta.revision` 复核；对已评估 ID 重跑 `query_filter` 比较 `state/protected/current/other`；Task 状态变化影响资格时 → `PICKER_HISTORY_CHANGED`。
- PG 侧单 `REPEATABLE READ` 事务（P1 会话），SQLite 侧只读事务；不宣称全局原子。

### T9 P3-A 文档
- `docs/architecture/U3_PICKER_P3_INCREMENTAL_SYNC_PREPARATION.md`：Owner 写入入口清单、事务边界、Change Log 合同、基线与增量衔接、失败恢复、最小实施范围。

## 测试

`tests/integration/test_u3_picker_business_postgres.py`（真实 PG16 + SQLite fixture）：历史策略、角色、确认回执、复合筛选分页/计数/cursor、Task 状态一致性、冻结等价、既有 SQLite API 未变。P2-0 用例加入 P1 文件。目标 25–30 用例，不重复同义。

## 完成标准

P2-0 定向通过 → A–G 实现 → P3-A 文档 → 定向测试全绿 → 文档/接续入口 → commit → 快进 push → 查询一次 CI。
