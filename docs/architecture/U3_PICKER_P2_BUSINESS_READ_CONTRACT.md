# U3-P2 训练素材业务读取合同（2026-11-28）

> 在 P1 只读 Provider 之上组合 SQLite 业务权威，形成“可执行”的训练素材读取合同。
> SQLite 仍是唯一业务 Owner；PostgreSQL 只读；未切换生产入口；未新增 Schema V5。
> 定向：真实 PostgreSQL 16 + 真实 SQLite Owner，**55 passed / 0 skipped**（P1 41 + P2 14）。

## 1. 分层与模块

| 层 | 模块 | 职责 |
|---|---|---|
| 基础候选 | `training_material_picker_read.py`（P1） | 项目隔离、基础筛选、稳定排序、keyset、GT hydration、池关系、回执、快照 |
| 业务合同 | `training_material_business_read.py`（新增） | 训练历史、样本角色、训练用途、确认有效性、最终分页/统计、冻结集合等价 |
| 历史权威 | `training_material_usage.TrainingMaterialUsage.query_filter` | token/coverage/Task 状态；`_relation_tokens` 唯一关系规则 |
| 角色权威 | `training_label_tasks.training_material_role` + 两个 confirmable | 正式 GT/scope/legacy 判定 |
| 确认权威 | P1 `get_task_negative_receipts` + `AnnotationRepository` | generation/表存在/行，单只读事务 |

执行顺序：PG 基础筛选 → 有界候选流 → 批量 material/GT hydration → 池关系（基础筛选内）→
SQLite 历史 → 角色/用途 → 最终过滤 → 分页/统计。SQLite 权威判断不做 PG 等价改写。

## 2. 支持矩阵

**已实现**
- 历史：`history_policy`（`new_for_algorithm` 默认 / `include_history`）、`history_scope`
  （`current_only` / `other_only`）、`usage_state`（`used` / `possible` / `selected` /
  `unused` / `unknown` / `eval_only` / `test_reserved`）、`usage_role`（`train` / `test`）、
  `browse_only`。
- 角色：`positive` / `confirmed_negative` / `pending_negative` / `pending_review`，复用
  `training_material_role` 与 `task_negative_confirmable` / `task_partial_scope_confirmable`。
- 用途：`usage_role=test` 排除已暴露训练/验证样本；`eval_only` / `test_reserved` 直接采用既有
  状态；不生成新的 split。
- 复合筛选：基础（标签/GT/池/来源/时间/ID）+ 历史 + 角色 + 用途 + 排序，全部在分页前生效。
- 统计：exact 由完整候选流累计（不重复 COUNT、不加载全项目）；deferred 不 COUNT、`total=None`、
  `limit+1` 判 `has_more`。
- 冻结等价：`selection_digest(ids)` 与 `compare_candidate_sets(a, b, query)` 只读比较；
  两流完整消费且各自快照/历史校验通过后才发布结论。

**显式限制**
- 不支持非 `processed` 状态、未知历史维度组合、page 与 cursor 同时使用。
- 角色判定要求调用方提供目标标签合同（`label_codes`）；无合同时仅返回 `pending_review`。
- `legacy` GT 只使用 SQLite 权威内容；PG 仅有 legacy 引用时标记 `legacy_unproven`，
  不据此伪造 boxes/scope（角色保守落入 `pending_review` 或既有安全状态）。
- 冻结等价仅覆盖候选集合/数量/摘要；正式冻结入口、selection_id、TTL、手工排除、摘要算法不变。

## 3. 一致性

- **PG**：P1 `read_session` 的 `REPEATABLE READ, READ ONLY` 事务；页面/COUNT/GT 同 MVCC。
- **SQLite**：每个 Owner 一个只读事务（材料/GT/回执/历史分别固定）；SQLite 回执
  generation + 表存在 + 行同事务读取。
- **Owner/Owner 版本**：P1 前置/后置复核（3 revision + 3 generation + 2 structure +
  证据表集合 + 确认结构/表存在交叉核验）；任何不一致 `PICKER_SNAPSHOT_STALE` /
  `PICKER_OWNER_UNVERIFIABLE`。
- **历史版本**：读取前后 `training_usage_meta.revision` 比较；对已评估 ID 重跑 `query_filter`
  比较 `state/protected/current/other`；变化 → `PICKER_HISTORY_CHANGED`。Task 状态变化通过
  同一分类结果体现，不扫描全部历史任务。
- **Cursor**：绑定 project、查询指纹（含基础+业务+目标标签合同）、P1 snapshot_id、usage
  revision；任一变化拒绝续读，不静默返回部分结果。
- **确认回执有效性**：仅 `authoritative` 且 `owner_equivalent` 的回执参与判断；逐条校验
  `context_key`、`source_content_sha256`、`annotation_version`、`annotation_hash` 与当前
  GT/素材一致；absent/present-empty 不产生当前确认。

## 4. 错误码（新增）

`PICKER_HISTORY_UNAVAILABLE`、`PICKER_HISTORY_INCOMPLETE`（保留）、`PICKER_HISTORY_CHANGED`、
`PICKER_CONFIRMATION_UNAVAILABLE`、`PICKER_CANDIDATE_MISMATCH`；其余复用 P1 错误码。
任何异常都不会被转换为空页、`unused` 或 `confirmed_negative`。

## 5. 测试

`tests/integration/test_u3_picker_business_postgres.py`：
- A 历史策略：默认/包含历史/current_only/other_only/used/possible/selected/unused/unknown/
  test_reserved/eval_only/browse，两端一致；
- B 角色：positive/confirmed_negative/pending_negative/pending_review 与既有分类器一致，
  默认历史策略先于角色过滤；
- C 回执消费：仅有效回执参与判断，过期 hash/version/context/source 与非权威读取全部拒绝
  （不创建任何测试回执）；
- D 复合分页：前几批被大量排除仍能正确填页；exact/deferred；cursor 全量无重无漏；
- E 一致性：usage revision 变化拒绝旧 cursor；PG 快照变化拒绝旧 cursor；coverage 不完整
  → `unknown` 而非 `unused`；历史不可用显式报错；
- F 冻结等价：两端候选/摘要一致，不同查询不冒充相同。

## 6. 明确未做

未切换生产读取、未改现有 Picker API/UI/训练创建/冻结入口、未新增持久缓存/第二历史镜像、
未做 P3 增量同步、未做 20 万级性能测试；VERSION `42.24.592` 不变。

## 7. 审计整改（2026-11-28）

- **显式业务读取会话**：`BusinessReadProvider.read_session()` 统一候选流、PG GT、回执与实际快照
  身份；PG 复用同一个 P1 `read_session` 事务，SQLite 由 picker 固定快照并在会话关闭复核 token。
  `read_page` 的 deferred 提前结束仍执行 `session.verify()`（usage revision、Task 状态证据、
  已评估 ID 的历史事实重读、picker 快照），失败即不返回结果。
- **Task 历史一致性**：`_task_evidence_digest()`（按状态聚合，不加载历史行）+ 会话内逐 Task
  `_task_statuses()` 前后比较；usage revision 只作为其中一项，不单独宣称覆盖状态变化。
- **中央 Task Owner**：默认 `<DATA_DIR>/task_runtime/tasks.sqlite3`，禁止项目目录第二任务库；
  注入的 picker/repository 必须与 `project_id`/`project_path` 同属一个项目。
- **历史/Test 资格**：正式选择始终执行原策略排除（`test_reserved`/used/possible 不因显式
  usage_state 或 scope 绕过）；浏览模式才展示这些行；`include_history` 保留原语义。
- **GT/确认**：`task_partial_scope_confirmable` 只表示可确认，不再提升为 positive；回执校验外层
  `receipt_id/context_key/image_id`、重算身份、目标合同、当前 GT 与素材身份；真实回执链路用
  原 `confirm_task_negatives` 隔离夹具验证，GT 变化后立即失效。
- **分页/统计/冻结**：移除普通扫描 50,000 硬上限（仅比较报告保留上限）；cursor + exact 显式拒绝
  （剩余数量不得冒充总量）；冻结等价对照原 `training_selection_reference` 的
  `freeze_selection`/`read_selection`（ID、数量、摘要、手工排除）。

## 8. 第三轮收口（2026-11-28）

- 历史一致性改为**可证明版本**：`training_usage_meta.revision`（全部 usage 表触发器）
  + **活跃 Task 身份摘要**（`(task_id,status)` 对 `QUEUED/RUNNING/CANCEL_REQUESTED/
  AWAITING_CONFIRMATION` 的有界查询，sha256）。不使用按状态计数；两个任务状态互换、任务进出
  活跃集、活跃状态变化都会改变摘要。cursor 绑定两者，任一变化拒绝续读。
- 会话不再累积 `_facts`/payload/历史事实，不再逐素材查询 Task 状态，`verify()` 只做三次有界
  比较（usage revision、Task 摘要、picker 快照），不重跑全量 `query_filter`。
- `iter_candidates` 与 `read_page` 共用业务 cursor 校验/续读。
- 浏览模式仍消费权威回执（角色不因 `browse_only` 改变）；`verify_owner=False` 仅诊断，
  正式 `read_page` 显式拒绝，且不用于回执权威性。
- SQLite 回执增加同事务结构认证（`evidence_structure` 与表存在一致）。
- `compare_candidate_sets` 必须同时证明：两端 owner 版本子集（revision/generation/
  structure）、usage revision、活跃 Task 摘要一致，且两端 `owner_equivalent=True`。

## 9. 最终读取事务收口（2026-11-28）

- `BusinessReadProvider.read_session()` 在中央 Task 库上开启**一个只读事务**（`BEGIN`），
  所有批次的 `query_filter`（usage/tokens/coverage/status）复用该连接；初始 usage revision 与
  活跃 Task 身份摘要也来自同一事务。`TrainingMaterialUsage` 仅新增 `_borrowed_connection`
  借用机制（复用原 `query_filter` 与分类逻辑，无业务复制）。
- 批次结束后关闭该事务，用**新连接**复核当前 usage revision 与活跃 Task 摘要，成功后才发布结果；
  deferred 提前结束同样执行。
- `BusinessSnapshot.read_identity` 与 owner 版本取自会话打开时捕获的 picker 上下文，不再重新
  `snapshot_context()`。
- 正式候选流与冻结比较禁止 `verify_owner=False`；诊断读取继续使用原 P1 Provider。

