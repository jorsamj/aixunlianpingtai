# AI 开发接续入口

> **2026-11-27 / U3 P0 负样本池证据版本收口（e0de1c83）**：只修两个问题，不重写 U3、
> 不新增 V5、不改历史 DDL/checksum、VERSION 仍 42.24.592。
> ① `negative_pool_operations` 纳入 materials evidence generation 触发器覆盖：两次合法
> `NegativePool.members()` 回执操作会产生不同回执但结构不变，generation 必须前进，否则会被
> “同结构、同 generation、不同摘要”误判为 `U3_SNAPSHOT_REVISION_DIVERGED`；懒建表在
> `negative_pool._mutate` 同一事务安装触发器，已有库由快速探针“现有证据表是否都已有 insert
> 触发器”强制进入 `_initialize` 补装；`negative_pool_meta.revision` 语义不变。
> ② 导出结束复核补齐 **materials** structure generation（此前只比较 annotations 的版本）。
> 定向用例：真实 PostgreSQL **57 passed / 0 skipped**（schema 17 + material/GT 40），
> 另有 negative_pool/schema5 定向 40、w10 定向 22 passed。P1 Provider 未启动。
> 合同见 [U3 Picker P0 Schema V4](U3_PICKER_P0_SCHEMA_V4_20261127.md)。

> **2026-11-27 / U3 P0 结构生命周期整改（d72153a5）**：只修独立审计发现的“结构变化后旧快照
> 回放”漏洞，不新增 Schema V5、不改历史 DDL/checksum、VERSION 仍 42.24.592。
> Owner 侧新增持久化结构版本（`annotation_meta`/`material_meta` 的 `evidence_structure` +
> `evidence_structure_generation`）：首次观察为基线 0，之后表创建/删除/重建都 +1；
> 触发器安装入口与懒建表同步认证，另提供显式 `reconcile_evidence_structure()`；绕过 Owner 的
> 原始 DDL 未认证时**导出失败关闭**（`U3_OWNER_STRUCTURE_UNVERIFIED`）。
> 快照 `evidence_streams` 增加 `structure_generation`/`structure_certified` 并进入
> `snapshot_id`/`revision_vector`；导入侧结构版本更低拒绝（`U3_SNAPSHOT_STRUCTURE_REGRESSION`），
> 同版本不同表集合或无法证明时拒绝（`U3_SNAPSHOT_STRUCTURE_UNVERIFIED`），之后才比较行
> generation 与摘要。确认投影与证据行同进退（缺表两者都保留，空表清空）。V4 结构核验补上
> `u3_shadow_import` 主键与 CHECK 允许值集合严格相等。
> 定向用例：真实 PostgreSQL **55 passed / 0 skipped**（schema 17 + material/GT 38），
> 另有受影响单元/API 定向 **186 passed**。P1 Provider 未启动；远端未推送（按要求）。
> 合同见 [U3 Picker P0 Schema V4](U3_PICKER_P0_SCHEMA_V4_20261127.md)。

> **2026-11-27 / U3 Picker P0 审计整改（293543be）**：按独立审计只修三项，不新增 Schema V5。
> ① **Owner 侧单调 generation**：`annotations.sqlite3` 新增 `task_negative_confirmation_generation`
> 与 `evidence_generation`，`materials.sqlite3` 新增 `evidence_generation`，由同事务 SQLite
> Trigger 覆盖 INSERT/UPDATE/DELETE，旧库打开时原地补装（不升 user_version）；
> `confirm_task_negatives()` 与导出共用 `material_annotation_lifecycle_fence`（锁序统一为
> 生命周期锁 → SQLite），导出读取并复核 generation。快照 `evidence_streams`（generation +
> 重算摘要 + 表结构）进入 `snapshot_id`/`revision_vector`；低 generation 或同 generation
> 不同摘要一律拒绝，`negative_confirmation_revision` 仍是 COUNT 兼容语义。
> ② **full 导入前置完整性**：普通项目也必须在任何写入前通过 contract/project/lifecycle/
> 必需表/十张证据表/table_state/counts/digests/content_digest/三项 revision/snapshot_id
> 校验，否则 `U3_SNAPSHOT_INCOMPLETE`（pending 保留原错误码）。
> ③ **V4 结构核验补强**：四张 V4 表真实主键、列类型、NOT NULL、status/outcome CHECK、
> 索引所属表与列顺序全部对 catalog 校验，篡改一律 `U3_SCHEMA_STRUCTURE_INVALID`，不自动修复。
> 定向用例：真实 PostgreSQL **50 passed / 0 skipped**（schema 17 + material/GT 33）。
> V1–V3 历史 DDL/checksum、VERSION 42.24.592 未改；P1 Provider 未启动。
> 合同见 [U3 Picker P0 Schema V4](U3_PICKER_P0_SCHEMA_V4_20261127.md)。

## 统一剩余任务台账（架构阶段）

| 状态 | 单元 | 说明 |
|---|---|---|
| 已完成代码 | U2 完整性（SIGKILL/回滚/删除证据） | 真实子进程终止三窗口；反向回滚含切后 create/update/delete；删除需完整跨域证据（收集器仅实现素材侧） |
| 已完成代码 | 素材热点（C） | v12/v20/v44/video 改为 id 快照 + 500 批 GT/素材读取；合成 1201 行 v12 GT 快照 4271ms→15ms |
| 已完成代码 | 转换 BMODEL 门禁（D） | BMODEL 交付要求 ONNX↔BMODEL 数值/检测均 consistent，否则 `BMODEL_EVIDENCE_NOT_ELIGIBLE`；L0–L5 矩阵文档 |
| 已完成代码 | U3 证据/约束/升级修复 | 证据按 (project,store,table) 同步、真实主键身份；池唯一名+双外键；必需字段 fail-closed；v1→v2 校验 |
| 已完成代码 | U3 目标一致性 | read_target_snapshot 显式 REPEATABLE READ/READ ONLY，拒绝调用方事务；并发中途提交不可见（实测） |
| 已完成代码 | U5 readiness 修正 | 用真实 stage（cancelling/recovery_blocked_*）、真实 UTC now、租约三类、SQL 失败 fail-closed |
| 已完成代码 | SmartAudit 写锁 | create/review/cancel/retry 统一在 finally 释放；复核后锁外刷新；新增前端合同测试 |
| 已完成代码 | U3 快照/证据/完整导入 | 生命周期栅栏+修订复核；必需表 fail-closed；10 张历史证据表逐行为证据；full 快照删除；schema v2 校验 |
| 已完成代码 | U5 只读 readiness | 只读诊断权威库/版本/租约/停止未证明/GPU 预留/阻断原因 |
| 未开发 | U3 Picker PG 等价读 | Provider/查询/历史过滤未实现；P0（V4 快照身份、revision 保护、台账、投影、索引）已落地，见 `U3_PICKER_P0_SCHEMA_V4_20261127.md` |
| 未开发 | 模型转换 G1 | 类别身份与 BMODEL 证据绑定仍未实现 |
| 未开发 | Vue 母模型管理 | v63 安装/取消/登记页面未实现 |
| 已完成代码 | U3 影子迁移（核心） | `u3_shadow.py`：materials/GT/负样本池 Schema + 确定性快照 + 单事务幂等导入 + 对账 + CLI；真实 PG 3 项合同 |
| 已完成代码 | U2 身份链 | finish/abort 全身份核验 + 条件化 UPDATE；删除证据绑定 scope/source/config/operation |
| 已完成代码 | 素材缓存 | materialize 冷启动单次哈希；取消/中断不再遗留 .part 临时文件 |
| 已完成代码 | Vue 原生 | 质量中心智能审计面板（真实 v62 接口）；深链带返回路径；`view=iteration`、`?back=` 生效 |
| 未开发 | 转换（本轮） | 仅完成门禁调用者审计，未改代码；类别身份/硬件合同未实现 |
| 未开发 | U5 前置 | 未实施 Provider 可观测/readiness 诊断 |
| 未开发 | U3 ATTACH 替代 | 未实现 Picker 的 PG 等价读合同 |
| 设计完成 | U5 ADR / U3 清单（F/B1） | 十问答案 + Owner 图 + 状态机 + 事务边界 + 迁移/回滚 + 测试矩阵；U3 逐表清单与三个 ATTACH 合同 |
| 未开发 | U3 影子迁移工具（B2/B3） | 仅有清单与设计；未实现导出/导入/对账代码 |
| 未开发 | Vue 业务补齐（E） | 本轮未开工；等待与后端接口能力一起排期 |
| 未开发 | 跨域删除证据来源（A3 剩余） | 产物引用 Owner、NAS/OSS/S3 退役探测未实现，生产删除仍阻断 |
| 安全设计阻塞 | U2 生产切换/回滚演练 | 需授权与隔离真实部署；`STORAGE_SOURCE_PROVIDER` 仍默认 sqlite |
| 已完成代码 | U2 CI 覆盖 | storage 单元 Job 装 psycopg[binary]；新增 `storage-source-postgres` Job（PG16 service，10 项真实 PG 合同，JUnit+无 skip 守卫） |
| 已完成代码 | U2 切换锁统一 | `storage_source_switch_lock_path` 统一 DB/记录/标记三种入参为同一锁；写者、admit、finish、abort 共享 |
| 已完成代码 | U2 顶层事务 | admit 要求 IDLE 连接、单事务内 advisory 锁+generation+import+reconcile+cutover_state；COMMIT 后校验 IDLE 才写准入记录 |
| 已完成代码 | U2 恢复语义 | 提交前失败移除标记；提交后失败保留标记，finish（已发布）/abort（未发布）恢复；损坏/未知状态 fail-closed |
| 已完成代码 | 准入 Provider 严格校验 | 缺失/未知 Provider 视为无效记录：写者拒绝、`cutover_status` 报 INCONSISTENT；合法 sqlite/postgresql 不变 |
| 已完成代码 | U1 revision 证明 | `require_revision_token`：revision 不可用即证据不完整（409），不再以 None==None 证明稳定 |
| 已完成代码 | 素材旧数据补查 | 命中 200 行上限即 `MaterialEvidenceIncomplete`（409），不再当作"不存在" |
| 未完成开发 | U3 素材+GT+负样本池 | 需联合边界设计（batch ATTACH、rescan manifest、picker usage/GT，ATTACH、负样本池同库事务），未开始 |
| 未完成开发 | 训练准备与缓存 | Prepare/Cache 复用依据、取消回收与磁盘占用仍需治理 |
| 未完成开发 | 转换 L0–L5 | 数值/检测/板端合同补齐与算能 BModel 误检根因待现场证据 |
| 未完成开发 | 任务执行架构 | 正式 Runner、进程句柄、恢复与 Legacy 退役条件 |
| 安全设计阻塞 | U5 任务库迁移 | 必须与执行权威、Lease、资源预留、恢复联合设计 |
| 安全设计阻塞 | 存储源回滚（rollback） | 反向切换需目标侧新写后的回滚证据，当前只阻断不自动回滚 |
| 安全设计阻塞 | 存储源跨域删除 | 需素材引用证据与存储退役证明，Provider 已声明能力缺口并对普通配置放行 |
| 安全设计阻塞 | 整算法删除/凭据轮换/发布回退 | 缺原引用与持有者证明，保持原保护 |
| CI 待确认 | 本轮业务提交 | 推送后单次查询 |
| 真实环境待验证 | 20 万素材、2 万批选、NAS/OSS | 需生产级隔离环境，未执行 |
| 真实环境待验证 | BModel/RKNN/昇腾 实机 | 无授权硬件，未执行 |
| 用户授权待确认 | 生产库切换、默认入口切换、supervisor-required | 均未启用 |

## 第十四批：evidence 命名空间校验下沉到导入边界（2026-11-27，本批）

- 起始 `19265f18f50c8c5fa82e763cc058cd36ec40ae3a`。VERSION 42.24.592 未改。
- 原全局检查只在 `pending_clear_eligible()`（pending + full）中执行，普通 full / incremental 仍可写入未知 evidence 命名空间。现提取 `evidence_namespace_error(snapshot)`，在 `import_project_snapshot()` 的 advisory lock 之后、任何 DELETE/INSERT/UPDATE 之前对所有模式与所有项目执行：允许集合严格为 `EVIDENCE_TABLES` 十张表的 `store.evidence.table`；`counts`/`digests` 中任何集合外 `*.evidence.*` 键拒绝；stores 中未知 store 携带 `evidence`（含空字典）拒绝；已知 store 的 evidence 必须是 dict、值必须是 list；非字典 store payload 不被静默跳过。pending 项目抛 `U3_PENDING_IMPORT_INCOMPLETE`，其他项目抛 `U3_EVIDENCE_NAMESPACE_INVALID`；未知 evidence 无法进入 `evidence_row`。十张表的 absent 保留/empty 清空语义不变。
- 新增真实 PostgreSQL 矩阵用例：pending 与非 pending × full 与 incremental，覆盖未知 store 携带证据、未知 store 的 `evidence={}`、非字典 store payload；每次拒绝后 stores/table_state/revisions（及 pending 标记）完全不变；合法快照在两种模式下仍正常导入。
- 验证：`test_u3_schema_upgrade_postgres.py` 10 项 + `test_u3_material_gt_postgres.py` 16 项 = **26 passed**（真实 PostgreSQL，0 skip）。

## 第十三批：全局 evidence 命名空间校验（2026-11-27，本批）

- 起始 `d9c0e5d6d55337c1a965cc69c382a59714305972`。VERSION 42.24.592 未改。
- 原检查只遍历 `EVIDENCE_TABLES` 的 materials/annotations，`other.evidence.unknown_table` 形式或未知 store 携带 evidence 可绕过。现建立允许集合 `store.evidence.table`（10 张历史证据表），对 `counts`/`digests` 中所有含 `.evidence.` 的键做全局比对（任何集合外键即拒绝），并扫描 `stores` 中所有 store 的 `evidence` 子结构（未知 store 或未知 evidence 表拒绝）。十张正常证据表与 absent 保留/empty 清空语义不变。
- 定向用例在同一 pending 场景下再增三种非法快照（未知 store 的 counts 键、未知 store 的 digests 键、未知 store 携带 evidence 数据），均重算 `content_digest` 后仍被 `U3_PENDING_IMPORT_INCOMPLETE` 拒绝，且每次拒绝前后 stores/evidence/table_state/revisions/pending 完全一致；原始完整快照随后正常清除标记。
- 验证：`test_u3_schema_upgrade_postgres.py` 10 项 + `test_u3_material_gt_postgres.py` 15 项 = **25 passed**（真实 PostgreSQL，0 skip）。

## 第十二批：evidence absent 状态严格校验（2026-11-27，本批）

- 起始 `f3e08978119f5ab3a9e9661cc2dc5ef3f1384859`。VERSION 42.24.592 未改。
- `pending_clear_eligible()` 收紧 evidence 合同：`table_state.present` 必须严格为 bool（`None`/`1` 拒绝）；absent 时 `row_count` 必须实际存在、为 int（非 bool）、值为 0；`stores.evidence` 中不得出现该表键（即使值为 `None`），`counts`/`digests` 也不得出现该表键；未知 evidence 表除 `stores.evidence` 外，还覆盖 `counts`/`digests` 中 `*.evidence.*` 的未知键。absent 保留历史、empty 清空的既有语义不变。
- 新增真实 PostgreSQL 用例：10 种非法快照（present=None/int、absent 缺 row_count、row_count=bool/1、evidence 值为 None、counts/digests 残留键、counts/digests 未知 evidence 键）在 pending 项目上全部 `U3_PENDING_IMPORT_INCOMPLETE` 拒绝，且每次拒绝后 `stores`/`table_state`/`revisions`/pending 标记与拒绝前完全一致；随后原始完整快照正常清除标记。
- 验证：`test_u3_schema_upgrade_postgres.py` 10 项 + `test_u3_material_gt_postgres.py` 15 项 = **25 passed**（真实 PostgreSQL，0 skip）。

## 第十一批：证据表逐表校验、revision 完整性与外键有效性（2026-11-27，本批）

- 起始 `5a6a5e5ab02173a93f0ce44d871d58ce708b8a0c`。VERSION 42.24.592 未改。
- P1-1：`pending_clear_eligible()` 原先只遍历快照中已存在的 evidence 项，整张表连同 counts/digests 一起缺失仍可能通过。现在遍历 `EVIDENCE_TABLES` 全部 10 张：每张必须有 `table_state`；present=True 时 evidence 键存在、为 list、counts==长度、digests==重算摘要、`table_state.row_count`==长度；present=False 时 `row_count` 必须为 0，且不得出现伪造的 evidence/counts/digests 键；未知 evidence 表直接拒绝。absent/empty 业务语义未变。
- P1-2：新增真实 pending+evidence 回归（先导入真实 evidence 行→设 pending→删一张表的数据/table_state/counts/digests 并重算 content_digest→full 导入被 `U3_PENDING_IMPORT_INCOMPLETE` 拒绝，前后 stores/table_state/revisions/pending 完全一致；原始完整快照随后成功并清除标记）；另加 pending 下"源表 absent"合法用例：present=False 不阻断，目标历史 evidence 保留、reconcile 报 `retained_target_evidence` 且 same=true。
- P2-1：revision 要求 `materials`/`annotations`/`negative_pool` 三项均存在且为非负整数；新增缺 `negative_pool` 的拒绝用例。
- P2-2：外键校验读取 `pg_constraint.convalidated`，列映射正确但 `NOT VALID` 的外键同样 `U3_SCHEMA_STRUCTURE_INVALID`；新增真实 PostgreSQL 用例。
- 验证：`test_u3_schema_upgrade_postgres.py` 10 项 + `test_u3_material_gt_postgres.py` 14 项 = **24 passed**（真实 PostgreSQL，0 skip）。

## 第十批：pending 前置门槛、来源信任边界与结构补强（2026-11-27，本批）

- 起始 `5d2df928564c8fbca39abc0459eff9f9f586e1dd`。VERSION 42.24.592 未改。
- P1-1：pending 项目的 full 导入此前先删后判，可能留下"标记还在、数据已被部分覆盖"。现在在 advisory lock 之后、任何 DELETE/INSERT/UPDATE 之前检查 `legacy_reference_pending_import`：若存在且 `pending_clear_eligible()` 不成立，抛 `U3_PENDING_IMPORT_INCOMPLETE`，事务内不修改该项目的业务行、`table_state`、revision、evidence（测试用前后 `read_target_snapshot` 全量对比 `stores/table_state/revisions/pending` 证明）。合格快照仍按原 full 语义导入并在同一事务清除标记；incremental 永不清除；非 pending 项目的 full 语义未变。
- P1-2：明确区分"完整性"与"来源真实性"。`pending_clear_eligible()` 现已按数据内容核对 evidence（列表类型、counts、逐表 digest），不再只看键存在。CLI `command_import` 明确记录信任边界：文件按原样读取，import 只能证明结构完整与内容自洽，不能证明来源；该入口是内部受控运维路径，快照应来自 `u3_shadow_cli export`，本构建没有签名/密钥管理，也不宣称密码学保证。
- P2 结构校验：`_assert_target_structure()` 增加 `annotation_label_reference` 主键列顺序必须为 `(project_id,image_id,label_code)`、`project_id` 列存在，以及 `negative_pool_link` 两个外键的**本地列→远端列映射**（member：project_id,material_id→project_id,material_id；category：project_id,category_id→project_id,id）与 `ON DELETE CASCADE`；不匹配即 `U3_SCHEMA_STRUCTURE_INVALID`。新增"缺主键"和"存在外键但列映射错误（NOT VALID 构造）"两种定向用例。
- P2 测试数据：`test_u3_schema_upgrade_postgres.py` 的 `scope_ref=2` 改为业务语义允许的 `1`，全文仅 0/1。
- 验证：`test_u3_schema_upgrade_postgres.py` 9 项 + `test_u3_material_gt_postgres.py` 11 项 = **20 passed**（真实 PostgreSQL，0 skip）。

## 第九批：pending 清除条件、历史错误结构识别与测试真实性（2026-11-27，本批）

- 起始 `468636d8c64cbbcaf81876c5aa5425e1f630a816`。VERSION 42.24.592 未改。
- pending 标记：原实现仅在 `mode="full"` 时无条件清除，手工构造的不完整 Mapping 也能清除。现新增 `pending_clear_eligible()`：要求 contract_version/project_id 匹配、`consistency` 来自生命周期栅栏导出、必需表的 `table_state.present=True`、typed 数据键为列表且 `counts`/`digests` 与内容逐表一致、evidence 计数/摘要存在、`content_digest` 等于按表摘要重算值、revisions 含 materials/annotations；满足才清除，否则记录 `legacy_pending_cleared=0` 与 `legacy_pending_retained=<原因>`。incremental 永不清除；清除与导入同一事务。可信调用链明确为 `export_project_snapshot`（SQLite Owner + 生命周期栅栏 + revision 复核）→ `import_project_snapshot`；自报摘要只证明内容一致，不单独证明来源可信。
- 历史错误结构：`ensure_schema` 现在每次打开都执行 `_assert_target_structure()`（同一事务内），用 `information_schema.columns` 核对 `annotation_label_reference` 七字段、用 `pg_constraint` 核对 `negative_pool_link` 的成员/分类双外键且均 CASCADE；不满足即 `U3_SCHEMA_STRUCTURE_INVALID`，detail 明确要求从权威 SQLite 导出重建 w3_material_gt，不自动修复、不删旧数据、不新增 v4、不改历史 DDL/checksum。
- 测试真实性：legacy JSON 用例改为真实 `AnnotationRepository.rebuild_reference_index()` 生成投影（m1 正式 GT 优先、m2 legacy JSON 有框按 owner 规则得 fire 3/1 与 smoke 1/1、m3 无框不产生行），`scope_ref` 仅 0/1；并断言 pending 时 `reconcile.same=false` 且含 `legacy_reference_pending_import`、不完整 full 快照不清除、真实完整快照清除后 same=true；升级用例构造"已记录 v3 但缺 source_kind"和"缺分类外键"两种历史坏结构，均被 `U3_SCHEMA_STRUCTURE_INVALID` 阻断（detail 含缺失项与重建指令）。
- 验证：`test_u3_schema_upgrade_postgres.py` 8 项 + `test_u3_material_gt_postgres.py` 11 项 = **19 passed**（真实 PostgreSQL，无跳过）。v1/v2/v3 checksum 未变。

## 第八批：v1 升级后 source_kind 合同修复（2026-11-27，本批）

- 起始 `e078b451876c1b01ca1d6d87b02731a0d1ce2dfd`。VERSION 42.24.592 未改。
- 根因：v1→v2 的临时表 `annotation_label_reference_v2` 漏了 `source_kind`，而 `_SCHEMA_V2`、`REQUIRED_COLUMNS`、`import_project_snapshot`、`read_target_snapshot` 都要求该字段；`CREATE TABLE IF NOT EXISTS` 无法修补已存在但缺列的表，于是升级后正式表无法导入/读取（测试只查行数，未走真实读写 SQL）。
- 修复：临时表增加 `source_kind TEXT NOT NULL`，从 `annotation_label_reference_legacy` 原样复制；`source_kind` 不进入主键、不参与冲突去重，仍保留为正式业务字段；多 source_kind 冲突检测与 `U3_UPGRADE_REFERENCE_CONFLICT` 不变。迁移后新增 `information_schema.columns` 实际列校验（缺任一 REQUIRED_COLUMNS 即 `U3_UPGRADE_REFERENCE_SCHEMA_INVALID` 并回滚），不再依赖 DDL 的 IF NOT EXISTS。
- P1 legacy JSON 语义：v1 的 `box_count/scope_ref=0` 与 `COALESCE(annotation_state,'unannotated')` 只能作为过渡默认值，不能声称等于 SQLite 真值。现升级后写入 `store_revision(project_id,'legacy_reference_pending_import')` 标记，`read_target_snapshot` 暴露 `legacy_reference_pending_import`，`reconcile` 将其列为阻断（目标未完成）；只有 authoritative 全量导入（`mode="full"`，来自 SQLite 导出，含 `_reference_rows()` 计算的正式/legacy JSON 投影）才清除标记并返回 `legacy_pending_cleared=1`。未新增第二套 legacy JSON 解析或迁移机制。
- 验证：`test_u3_schema_upgrade_postgres.py` 6 项（真实 v1→v3 后 source_kind 列与值一致、升级后 `read_target_snapshot`/`import_project_snapshot` 走真实业务 SQL、导入前后 box_count/scope_ref/state/source_kind 一致、全量导入清除 pending 标记、重复 ensure_schema 幂等、原有冲突/悬空/双外键/级联/篡改/更高版本保留）；`test_u3_material_gt_postgres.py` 11 项（新增 legacy JSON 投影测试：正式 GT 优先、legacy JSON 有 boxes 计算 3/1、无 boxes 不伪造行；导入后逐字段一致且 reconcile same）。共 **17 passed**（真实 PostgreSQL，无跳过）。v1/v2/v3 checksum 未变。
- 未完成（不在本轮范围）：U3 Picker PostgreSQL 等价读、U5 实际迁移、Vue、模型转换；U5 仍 DESIGN_ONLY / NOT_IMPLEMENTED / NOT_VERIFIED。

## 第七批：v1→v2 数据保真迁移与 stop_proof 可信性（2026-11-27，本批）

- 起始 `933dfe8d34ba691736914bfa9fc050738c784c23`。VERSION 42.24.592 未改。
- P0-1A annotation_label_reference：原 v1→v2 直接 `DROP TABLE ... CASCADE` 后重建，v1 的 (project,image,label,source_kind) 行被整体丢弃。现迁移为：①把 v1 行原样写入 `annotation_label_reference_legacy`（保留 source_kind 与完整主键）；②建立 v2 typed 表；③按 (project,image) 关联正式 `annotation` 取可信 `annotation_state`（无 GT 时用 `unannotated`，为明文历史兼容规则），`box_count/scope_ref` 取 v1 从未持久化的历史默认 0；④同一 (image,label) 在 v1 存了多个 source_kind 时，唯一主键冲突被转换为稳定错误码 `U3_UPGRADE_REFERENCE_CONFLICT` 并整体回滚（不静默去重/丢弃）；⑤迁移后比对 legacy 与 typed 行数，不一致即 `U3_UPGRADE_REFERENCE_LOSS`。
- P0-1B negative_pool_link：原迁移仅 `CREATE TABLE IF NOT EXISTS`，旧表的外键不会被修改。现 v1→v2 建立 `negative_pool_link_v2`（成员 + 分类两组外键，均 ON DELETE CASCADE），复制旧关联，校验通过后替换旧表；存在悬空分类引用时外键冲突转为 `U3_UPGRADE_LINK_ORPHAN` 并回滚，不静默删除关联。v2→v3 保持 v3 唯一索引（`lower(name COLLATE "C")`）并为 v2 直建库补建 legacy 表。
- 版本与 checksum 不变：v1 `20eadb1b13ca742a5f2665975156d46812f27f66509f78dfd5ed3d971604b1ed`（9628234e）、v2 `20f294c74be4a2aeaf4ab8ff6046034a49dcd564bcd6e19b62d6404cde2e6923`（c6a94215）、v3 `f7d563f684b3b3c5b26b2fdb3183c8377f7455db6fe2b0f8145bc48a07344735`（当前 DDL，未因本轮改动而变化，legacy 表仅由迁移创建）。
- P0-2 stop_proof：仓库只有**按任务**的远端 Agent 停止证明（`node_agent_settlement.stop_proof_digests` / `STOP_VERIFIED`），不能证明所有 Worker 服务与节点已排空；`claim_next` 只收 worker_id，未登记 Worker 仍可领取。因此 readiness 不再接受调用者传入的任意字典/字符串（原先 `workers_stopped=true` + 任意文本即可放行）：`stop_proof_status` 只有 `MISSING` / `UNVERIFIED` 两种，分别阻断 `external_worker_stop_proof_required` / `external_worker_stop_proof_unverified`；本轮**没有**可信验证器，所以即使 tasks/租约/GPU/Worker 全空，`ready_for_cutover` 也恒为 false。未来证明合同已写入常量：nodes、worker_services、process_identities、observed_at、expires_at、source、verifier_signature。
- 定向验证：`test_u3_schema_upgrade_postgres.py` 5 项（真实 v1→v3 保真：legacy 保留两种 source_kind、typed 计数为零默认值+GT 状态；v1 冲突/悬空分类分别拒绝并回滚；真实 v2→v3 两组外键、删分类/删素材级联；v1/v2/v3 篡改与更高版本拒绝；重复执行幂等）、`test_u3_material_gt_postgres.py` 10 项、`test_task_store_readiness.py` 12 项 = **27 passed**。未跑全仓 pytest / Playwright。
- 未完成（不在本轮范围）：U3 Picker PostgreSQL 等价读、U5 实际迁移、Vue、模型转换；U5 ADR 仍为 DESIGN_ONLY / NOT_IMPLEMENTED / NOT_VERIFIED，readiness 通过不等于具备真实切换条件。

## 第六批：U5 readiness fail-closed、U3 Schema v3 与证据读取区分（2026-11-27，本批）

- 起始 `cbf0bfb188705dea9375e3a7ef415598ee45718c`（25/25 CI 通过）。VERSION 42.24.592 未改。
- P0-1 readiness fail-closed：删除 `_scalar()`/`_columns()` 把 `sqlite3.Error` 变成 0/空集合的兜底；任何 SQLite 查询或 PRAGMA 异常都向外传播并包装为 `TaskStoreReadinessError`。`tasks`、`worker_instances`、`gpu_reservations` 现在都是**必要表**（分别来自基础任务 Schema 与 `ensure_gpu_runtime_schema`），缺失或关键字段缺失返回结构阻断（`<table>_table_missing` / `<table>_incomplete:...`）并 `ready_for_cutover=false`；未知状态不再可能被报告为可切换。
- Worker 注册合同（只读核实）：`TaskRepository.claim_next(worker_id, ...)` 只接受一个 `worker_id` 字符串，**不要求** `worker_instances` 中存在对应实例；因此"数据库里没有活动实例"不能证明所有 Worker 已停止。readiness 新增 `external_stop_proof` 入参（需 `{workers_stopped: true, evidence: <非空>}`），未提供即阻断 `external_worker_stop_proof_required`，并把切换前置条件明确为"外部服务停止/节点排空证明 + 无活动/未知租约 + 无未证明停止 + 无 GPU 预留"。
- P0-2 Schema v3：`SCHEMA_VERSION=3`。v1/v2 的 DDL 现为**真实历史字面量**并各自保留 checksum：v1 取自 `9628234e`（3326 字符，`20eadb1b13ca…`）、v2 取自 `c6a94215`（4212 字符，`20f294c74be4…`）、v3 为当前含 `lower(name COLLATE "C")` 的唯一索引（4526 字符，`f7d563f684b3…`）。新增显式 v2→v3 迁移（仅重建唯一索引），v1→v3 按 v1→v2→v3 路径执行；每个已执行版本都以**自身** checksum 写入迁移行，历史行按各自版本校验（不再动态用当前 DDL 覆盖）。删除历史迁移行规避校验仍会被缺版本/校验失败拒绝。
- P1-3 证据表读取异常：`_sqlite_columns()` 不再把 `sqlite3.Error` 当作空集合；表不存在仍由空列集合表示（PRAGMA 对缺失表不报错），元数据读取异常则经外层包装为 `U3_OWNER_UNREADABLE` 失败关闭，不会被误判为"表不存在→保留证据"。十张证据表的主键身份、摘要、重放与项目隔离合同未改。
- 定向验证：`tests/integration/test_u3_material_gt_postgres.py` 10 项（含元数据异常 fail-closed）、`tests/integration/test_u3_schema_upgrade_postgres.py` 3 项（真实 v1→v3、真实 v2→v3、篡改 v1/v2/v3 与更高版本拒绝，升级后素材/标签/GT/负样本关联完整、索引为 C collation、ASCII 冲突拒绝而非 ASCII 不折叠）、`tests/unit/test_task_store_readiness.py` 12 项（含 tasks 查询失败、worker/gpu 表缺失与字段缺失、PRAGMA 异常、stop proof 缺失/存在）= **25 passed**。未跑全仓 pytest / Playwright。
- 未完成（不在本轮范围）：U3 Picker PostgreSQL 等价读、模型转换 G1、Vue 母模型管理；真实环境验收均未执行。
- 保护边界：VERSION、AGENTS.md、vendor、四份未跟踪保护文档未改。

## 第五批：第四批交付的五项定向核验与最小修复（2026-11-27，本批）

- 起始 `c6a942159fcb72f828a7385f2c5e0cf448270911`（CI_PASS）。VERSION 42.24.592 未改。本轮先只读核验，再只修真实缺陷。
- 核验 1（NOCASE 等价）：SQLite `name COLLATE NOCASE` 只折叠 ASCII A–Z；PostgreSQL `lower()` 跟随集群 locale，在 UTF-8 集群上会连非 ASCII 一起折叠 → **不与 SQLite 等价**（会拒绝 SQLite 允许的名字）。修复：唯一索引改为 `(project_id, lower(name COLLATE "C"))`（C collation 仅 ASCII 折叠，与集群 locale 无关）。实测：`FIRE`/`fire` 冲突被拒；`Ä`/`ä` 两行都允许；业务名（如「火焰」）不受影响。注意此改动改变 shadow v2 DDL 与 checksum（无任何部署依赖，升级测试动态取 checksum）。
- 核验 2（十张证据表）：原测试只覆盖 4 张。现按真实 DDL 构造并覆盖全部 10 张（material_migrations / material_storage_audit / material_retirements / material_cleanup_deferred / material_assignment_receipts(WITHOUT ROWID) / negative_pool_operations / annotation_delete_backup / annotation_negative_reviews / annotation_candidate_commits / task_negative_confirmations），逐表核对读取、写入、主键身份（同内容不同主键不合并）、部分删除、摘要对账与重放幂等。**源表存在但为空** → 该表目标清空；**源表不存在** → 保留目标历史（`retained_target_evidence` 非阻断，显式保留合同），两种情形分别断言。
- 核验 3（v1 真实性）：发现上一轮的 `_SCHEMA_V1` 是从当前代码派生的（3327 字符，checksum `dbde9fcf…`），并非历史版本。真实 v1 取自首次引入 U3 的提交 `9628234e`（3326 字符，checksum `20eadb1b…`），已以字面量内嵌；升级测试用该真实 v1 建库、升到 v2 并校验篡改/更高版本拒绝。
- 核验 4（活动 Worker 阻断）：活动 Worker 仍可领取 SQLite 任务、续租、写状态与结果；项目没有 OS 级隔离合同可用于切换期间冻结它们。因此 readiness 新增 `active_worker_instances_require_drain` 阻断（活动与过期实例分别报告），切换前置条件明确为"worker 实例全部停止/过期 + 无活动租约 + 无未证明停止"。另外发现 `tests/unit/test_task_store_readiness.py` **未在**任何 workflow 中执行：已加入 `task-runtime-truth.yml` 的 pytest 列表与 paths（`platform_core/task_store_readiness.py`、该测试文件），未新建测试体系。
- 核验 5：本轮只运行修改涉及的定向测试；未跑全仓 pytest / Playwright / 完整构建。
- 验证：U3 真实 PostgreSQL 11 项（主文件 9 + 升级 2）+ U5 单测 8 项 = **19 passed**；两个 workflow YAML 解析通过。
- 未完成（不在本轮范围）：U3 Picker PostgreSQL 等价读、模型转换 G1/BMODEL 证据绑定、Vue 母模型管理。真实环境（20 万素材、2 万批选、缓存磁盘、NAS/OSS/S3、BM 系列/RKNN/昇腾、U2 生产切换演练、U3 真实项目对账）均未验证。
- 保护边界：VERSION、AGENTS.md、vendor、四份未跟踪保护文档未改。

## 第四批：U3 证据/Schema/快照与 U5 readiness 复核整改（2026-11-27，本批）

- 起始 `78379728cd3f8d006d816f9c3fd9aab715aff101`。VERSION 42.24.592 未改；未启用 PostgreSQL 生产 Provider、未迁移真实数据、未连接 4070/A800。提交：`f2c16994`（U3）、`36af96b7`（U5）、本文档。
- 证据导入缺陷（已修）：原逻辑用 `(store, table_name)` 作 keep 键、却拿 `row_key` 与 `k1` 比较，多张证据表连续导入时会把先前表清空。现在每 `(project_id, store, table_name)` 只同步自己的行：源表存在→按行集合删除不在快照中的行并 upsert；源表存在但为空→清空该表；源表不存在→保留目标已有行（显式历史保留合同，不伪装为空）。证据身份改为**真实主键**（无主键表才用整体内容），相同 payload 不同主键仍是两行；两侧证据列表按该身份排序，摘要稳定。
- 池约束（已修）：`negative_pool_category` 增加 `(project_id, lower(name))` 唯一索引（等价 SQLite `COLLATE NOCASE`）；`negative_pool_link` 同时具备成员外键与分类外键且均为 `ON DELETE CASCADE`；实测大小写冲突被拒绝、删分类级联删关联、删素材级联删成员/关联/算法成员。
- Owner 字段合同（已修）：每张必需表声明必需字段（materials.id/storage_source_id/object_key/content_sha256/payload_json、annotations.image_id/annotation_state/version/content_digest/boxes_json、material_labels.material_id/label_code、annotation_label_references 六字段等），缺字段即 `U3_OWNER_INCOMPLETE`；源端 schema 版本按支持范围校验（素材 5–8、GT 3）；必需表为空是合法空数据，结构异常不是。
- v1→v2 升级（已修）：历史迁移行按**其自身版本**的预期 checksum 校验（新增 `schema_checksum_for(version)` 与真实 v1 DDL 常量），不再用 v2 checksum 校验 v1；真实 v1 Schema 可升级到 v2（新表/新字段/唯一索引齐全，旧素材行保留），篡改 checksum 与更高版本均被拒绝。CI U3 步骤现跑两份文件（10 项，守卫 ≥10、0 skip、0 fail）。
- 目标快照一致性（已修）：`read_target_snapshot` 要求空闲连接、显式 `SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY`，多表读取同一快照，并在结果中记录 `snapshot={isolation,read_only,identity}`；调用方已开事务时拒绝（`U3_TARGET_SNAPSHOT_TRANSACTION_BUSY`）。并发实测：读取中途另一连接提交的新 label 不出现在本次快照，下一次读取才可见。
- U5 readiness（已修）：`cancelling_unverified`/`recovery_blocked_*` 实为**stage** 而非 TaskStatus，改查 `status='CANCEL_REQUESTED'`+`stage='cancelling'` 与 `stage LIKE 'recovery_blocked%'`/`process_cleanup_blocked`/`lease_expired_process_alive`；时间默认真实 UTC（可注入）；活动/过期/缺失租约三类分别报告，RUNNING/CANCEL_REQUESTED 无到期时间计为 `unproven_lease_window` 阻断；校验任务库 schema 版本（仅 8）与必需列；SQL 读取失败抛 `TaskStoreReadinessError` 而不是返回 0；过期 worker 实例报告并阻断，活动实例仅报告；不修改任何任务状态。
- 验证：U3 真实 PostgreSQL **10 项**（8 主 + 2 升级）、U5 单测 **7 项**、SmartAudit 合同 **2 项**（上批，保留）；`py_compile`、`git diff --check` 通过。未跑全仓 pytest/Playwright/完整构建。
- 未完成（本轮明确不做）：U3 Picker PG 等价读、模型转换 G1/BMODEL 证据绑定、Vue 母模型管理。真实环境（20 万素材、2 万批选、缓存磁盘、NAS/OSS/S3、BM 系列/RKNN/昇腾、U2 生产切换演练、U3 真实项目对账）均未验证。
- 保护边界：VERSION、AGENTS.md、vendor、四份未跟踪保护文档未改。

## 第三批：SmartAudit 写锁、U3 正确性收口、U5 只读诊断（2026-11-27，本批）

- 起始 `9628234e79f8f06147c8d5dca013e334b9320e1e`。VERSION 42.24.592 未改；未启用 PostgreSQL 生产 Provider、未迁移真实数据、未连接 4070/A800。提交：`f942bf26`（SmartAudit）、`5e2f0198`（U3）、`edc74183`（U5 readiness）、本文档。
- SmartAudit：`writeBusy` 此前在 create/review/cancel/retry 设置后无人释放（异常/未知结果后整页永久 busy），且复核回调在仍持锁时调用 `loadFindings()`，刷新被 `writeBusy` 直接短路丢弃。现统一 `writeOnce()`：设置锁 → `reads.run` → `finally` 清锁；复核刷新改到**成功后且锁已释放**的钩子。create/cancel/retry 的错误经 `reads.errors` 展示，原 `request_id`/`generation`/`review_token` 回执与“未知结果保留原 request_id”不变。新增 `tests/frontend/smart-audit-write-lock.test.mjs`（2 项，源码合同：统一包装 + 锁外刷新）。
- U3 快照一致性（重要修正）：导出改为在 `material_annotation_lifecycle_fence` 内进行，两个 SQLite 库各自单读事务，导出后**重新读取**素材/负池/GT 的 revision 高水位，任一变化即 `U3_SNAPSHOT_SOURCE_CHANGED`；快照显式声明 `consistency=MATERIAL_ANNOTATION_LIFECYCLE_FENCE+REVISION_RECHECK`，不再宣称"两个读事务=全局原子快照"。未加该栅栏的写入者由 revision 复核检测而非静默混入。
- U3 Owner 完整性：必需表按 store 强制（缺失即 `U3_OWNER_INCOMPLETE`），每张表记录 present/schema_version/row_count；`annotation_label_reference` 恢复 `box_count/scope_ref/annotation_state/source_kind` 与 `PRIMARY KEY(image_id,label_code)`；10 张历史证据表（material_migrations、material_storage_audit、material_retirements、material_cleanup_deferred、material_assignment_receipts、negative_pool_operations、annotation_delete_backup、annotation_negative_reviews、annotation_candidate_commits、task_negative_confirmations）以 verbatim 行进入 `evidence_row`（rowid 表按 rowid、WITHOUT ROWID 表按复合主键分页），`table_state` 记录存在性与版本；对账验证必需表与表存在性。
- U3 完整快照导入：`import_project_snapshot(mode="full"|"incremental")`，默认 full 在单事务内先删后写（子表先于父表、仅当前 `project_id`），replay 幂等、失败整体回滚、非法规模式拒绝；标注/标注引用/素材/标签/作用域/负池链接/成员/分类均覆盖删除场景。Shadow schema 升至 v2，校验已应用版本的 checksum、拒绝高于工具的版本、提供显式升级路径。
- U5 只读前置：`platform_core/task_store_readiness.py`（`PRAGMA query_only=ON`）报告权威库、schema user_version、任务/排队数、活动与过期租约、停止未证明（`CANCEL_REQUESTED`/`cancelling_unverified`）、`recovery_blocked`、GPU 预留、worker 实例与明确 blocker 列表；不写、不领、不改租约、不切换 Provider。3 项单测（缺失库、只读不变、未证明停止阻断）。
- 验证：U3 真实 PG **4 项**、U5 单测 **3 项**、前端合同 **2 项**（node --test）、`vue-tsc --noEmit` 0 错误、SmartAudit SFC 编译通过、`py_compile` 与 `git diff --check` 通过。未跑全仓 pytest/Playwright/完整构建/规模测试。
- 未完成（本轮明确）：U3 Picker 的 PostgreSQL 等价读（ATTACH 替代）未实现；模型转换 G1 类别身份与 BMODEL 证据绑定未改代码；Vue 母模型管理（v63 安装/取消/登记）未实现。原因：均需与对应 Owner 合同一并设计，且本轮优先级给了 P0 正确性；不把审计当实现。
- 真实环境待验证：20 万素材、2 万批选、缓存冷热/磁盘回收、NAS/OSS/S3、BM 系列/RKNN/昇腾实机、U2 生产切换与回滚、U3 真实项目数据对账。
- 保护边界：VERSION、AGENTS.md、vendor、四份未跟踪保护文档未改。

## 第二批多工作流：U2 身份链、U3 影子迁移、缓存与 Vue（2026-11-27，本批）

- 起始 `6a3d7463d1946cee7e74ee1b97e5cfdf383ec631`（31/31 CI SUCCESS）。VERSION 42.24.592 未改；未启用 PostgreSQL 生产 Provider、未迁移真实数据、未操作 NAS/OSS/S3、未连接 4070/A800。提交：`68faa189`（U2 身份链）、`2ae5f3ea`（缓存）、`397e1d7d`（Vue），U3 与本文档为后续提交。
- U2 身份链：`finish_cutover` 不再只凭目标摘要恢复——marker 的 scope/operation_id/direction/previous_admission_id/generation、durable 行、准入记录形成可验证链；rollback 恢复必须同时满足"marker 属于该 durable 操作"且"本地记录是该操作的前驱或已发布结果"，否则 `STORAGE_SOURCE_CUTOVER_STATE_UNKNOWN`。所有 durable `UPDATE` 都带 `scope+admission_id+generation+phase` 条件并校验 rowcount；`abort` 按相位判定（已发布 forward 需 rollback；冻结 rollback 需连接恢复 `POSTGRES_ACTIVE`；未发布尝试直接释放 marker）。真实 PG 合同 22 项（新增错误 operation_id / 错误 scope / 错误前驱 / 错误 generation / 方向不符 / 重复 finish、abort / `SQLite→PG→SQLite→PG` 第二轮正向中断恢复）。
- U2 删除证据身份：证据新增 `scope/source_id/config_digest/operation_id`，Provider 逐项比对当前行（含配置摘要），跨 scope/跨源证据一律 `EVIDENCE_STALE`；收集器拒绝空/不可证明的项目集合与不存在的项目目录。产物引用 Owner 与 NAS/OSS/S3 退役探测仍未实现 → 生产删除继续阻断。
- U3（本轮主交付，`platform_core/u3_shadow.py` + `u3_shadow_cli.py`）：PostgreSQL schema `w3_material_gt`（material / material_label / material_annotation_scope / annotation / annotation_label_reference / negative_pool_* / store_revision，负样本成员对 material 为真实 `ON DELETE CASCADE`）；导出在**单个 SQLite 读事务**内按键集分页（复合键，页 ≤500），保留 NULL/''/0/false、JSON 原样、GT version 与 content_digest、素材与负池 revision 高水位；导入在**一个 PostgreSQL 事务**内 upsert（重放不改变任何行），失败整体回滚；对账比较表计数、ID 集合、逐表摘要、revision 高水位，并交叉检查（负池成员必须有素材、算法成员必须在池内；GT 无素材只报告不阻断，符合既有历史状态）。CLI：`status/export/import/report`。真实 PG 合同 3 项：确定性导出、导入+对账+重放、源变更检测、FK 级联、完整性失败整批回滚。**未实现** Picker 的 PG 等价读合同（ATTACH 替代）。
- 素材缓存：`MaterialCache.materialize` 冷启动只做一次内容哈希（原子 rename 后只校验长度），取消/中断（`BaseException`）不再遗留 `.part-*.tmp`；新增 3 项单测。训练准备重复 materialize/Bundle 经审计未发现，`training_workspace_lifecycle` 未改，RKNN 校准快照与 v20 无 dataset 全表写保留（会改变选择/摘要或缺少原子仓库 API）。
- Vue：质量中心新增"智能审计"面板，复用 `platform_core/smart_material_audit` 的真实 v62 接口（status/estimate/create/findings/review/retry，服务端分页 25，`request_id` 持久回执，无伪造进度）；问题行链接人工标注（`?back=`）与素材详情；训练行链接 FP/FN 真实样本子页与困难样本迭代面板；`NativeEvaluation` 支持 `?view=iteration`，`FormalAnnotations` 支持 `?back=`。`vue-tsc --noEmit` 0 错误，四个改动/新增 SFC 全部通过 `@vue/compiler-sfc` 编译；仅导航，不移动样本、不把 Test 样本送入训练。
- 未完成：转换（只完成"门禁唯一执行路径 `model_artifacts.delivery_artifact_quality_preflight` 及其调用者"审计，未改代码；类别顺序 G1 与硬件证据合同仍未实现）；U5 前置（Provider 可观测/readiness 诊断）未实施；U3 ATTACH 替代未实施；母模型管理（E1）未实施；批量暂停/恢复/停止确认**无**服务端批量 API，未做前端假批量。
- 验证：定向 46 项（U2 PG 22 + U2 unit 18 + U3 PG 3 + 缓存 3）；`vue-tsc` 0 错误 + 4 SFC 编译通过；`py_compile`、`git diff --check` 通过。未跑全仓 pytest/Playwright/完整构建/20 万压力测试。
- CI：`storage-cache-governance.yml` 的 PostgreSQL Job 增加 U3 合同步骤（JUnit 守卫 ≥3、0 skip、0 failure），paths 增加 `platform_core/u3_*.py` 与该测试文件。
- 真实环境待验证：20 万素材、2 万批选、缓存冷热与磁盘回收、NAS/OSS/S3、BM 系列/RKNN/昇腾实机、U2 生产切换与回滚演练、U3 真实项目数据对账。

## 多工作流批次：U2 完整性、素材热点、转换门禁、U3/U5 设计（2026-11-26/27，当前）

- 起始 `2bc8a01f40339924830b5563c4c73517abad7008`（该 SHA CI 24/24 SUCCESS）。VERSION 42.24.592 未改；未启用 PostgreSQL Provider、未迁移真实数据、未操作 NAS/OSS/S3、未连接 4070/A800。
- 提交边界：`5bb49655`（A1/A2/A3 合同与 SIGKILL/回滚）、`dada39ac`（A3 删除证据收集器）、`afd4fc8d`（D 门禁 + 矩阵）、`9b0928dc`（F/B1 设计文档）、`bbc6066b`（C 热点），本记录为文档提交。
- U2（A）：
  - A1 真实 SIGKILL：新增 `tests/integration/_storage_source_crash_probe.py`（子进程在三个协议点自终止，POSIX=SIGKILL、Windows=TerminateProcess），父进程用全新连接验证 durable 行、marker、准入记录、两侧写权限、generation 单调与"重新准入不重复导入"。三项测试 `test_sigkill_*`。
  - A2 反向回滚：`rollback_cutover` 冻结 PostgreSQL（advisory 锁 + `FOR UPDATE` + `SWITCHING`），独立只读事务导出当前权威快照，`import_snapshot_sqlite` 单事务 upsert/删除缺失行/原子切换默认源并拒绝"SQLite 行更新"，重新对账后发布 `ROLLBACK_APPLIED`（generation+1）、再写 SQLite 准入、最后删 marker；发布前失败恢复 `POSTGRES_ACTIVE`，发布后失败保留 marker 由 `finish_cutover` 按 durable 相位分派恢复；`abort_cutover` 在 durable 冻结时必须提供连接，否则拒绝。**所有 PostgreSQL 读取都放在各自事务内**，避免后续 `transaction()` 退化为 SAVEPOINT。CI 真实 PG 合同从 10 项增至 **18 项**（Job 守卫要求 ≥18、0 skip、0 failure）。
  - A3 删除证据：Provider 要求"当前 revision + 素材引用 0 + 产物引用 0 + 物理退役 RETIRED proof"；新增 `storage_source_delete_evidence.collect_delete_evidence` 用真实 `MaterialRepository.reference_count` 按有界项目列表统计素材引用。**产物引用与 NAS/OSS/S3 退役探测未实现**，因此生产删除仍阻断；零引用不等于对象已退役。
- C（素材热点）：`material_governance_service` 的 v12 自动划分与 v20 filtered、`quality_analysis_service` 的 v44 补数候选、`video_tasks` 幂等检查改为"id 快照 + 500 条批量 GT/素材读取"，有 dataset 作用域时写走 `mutate_dataset`；无 dataset 的 filtered 路径保留原全表事务（回调必须重算全库），v44 写事务与 Bundle 合同未动。合成 1201 行：v12 GT 快照 4270/4690ms→15/18ms（P50/P95），video 9.7ms→4.5ms；**合成数据不代表生产规模**。新增 `tests/unit/test_material_hot_paths_scale.py`（7 项）与 `docs/performance/MATERIAL_HOT_PATH_REMEDIATION_20261126.md`。
- D（转换）：`assert_delivery_quality_eligibility` 对 BMODEL 交付物（`bmodel_expected` 或 target 为 sophon/bmodel）新增硬门禁：ONNX↔BMODEL 数值与检测必须均 `consistent`，否则 `BMODEL_EVIDENCE_NOT_ELIGIBLE`（此前只看 PT↔ONNX 即放行）。证据文件/指标/产物仍可读，未改比较算法与容差；历史证据不被重写，恢复方式是到有离线 BMODEL 运行器的节点重跑。新增 L0–L5 证据矩阵（`CONVERSION_L0_L5_EVIDENCE_MATRIX_20261126.md`），逐级标注真实 Owner、错误码、证据位置、CI 与 **HARDWARE_PENDING**。
- F/B1（设计）：`U5_TASK_DB_MIGRATION_ADR_20261126.md`（十问、Owner 图、状态机、事务边界、迁移/回滚、测试矩阵）与 `U3_MATERIAL_GT_NEGATIVE_POOL_MIGRATION_INVENTORY_20261126.md`（逐表 Owner/键/revision/事务/索引/删除恢复、三个 ATTACH 的 PG 等价合同、影子迁移设计与未实现清单）。两份均为 `DESIGN_ONLY`，未落地任何表或代码。
- 未开工：B2/B3（U3 影子迁移工具——只有清单与设计，没有导出/导入/对账代码）、E（Vue 业务补齐）。
- 验证（本轮定向）：U2 真实 PG 18 项 + U2 unit 18 项；C 新测试 7 项 + 关联 28/35 项；D 新测试 4 项 + `test_conversion_numeric_consistency`/`test_model_artifacts` 145 项 + 转换 API 62 项 + 真实 PT→ONNX→准入 1 项；`py_compile`、`git diff --check` 通过。未跑全仓 pytest/Playwright/前端构建/20 万压力测试。
- 真实环境待验证：20 万素材与 2 万批选、训练准备冷热缓存、NAS/OSS/S3、BM1684/BM1684X/BM1688、RKNN 板端、昇腾运行期、生产切换与回滚演练。
- 保护边界：VERSION、AGENTS.md、vendor、四份未跟踪保护文档未改；未连接 4070/A800。

## 5074e795 收口：U2 PostgreSQL Job 的 requests 依赖（2026-11-26，当前）

- 起始 `5074e7951c06660880a4871acdd0309ab0db83b1`。两个 Storage Cache Governance 失败（push 45845036597 / PR 45845050654）根因：`ModuleNotFoundError: No module named 'requests'`。
- 调用链：`tests/integration/test_storage_source_postgres.py → platform_core.storage.source_repository → platform_core/storage/__init__.py → platform_core/storage/remote.py → import requests`（OSS/S3 SDK 为惰性导入，故只缺 requests）。
- 修复：仅在 `storage-source-postgres` Job 的 `Install U2 PostgreSQL contract dependencies` 追加 `requests` 并注释依赖链；未改生产代码、未改 SQLite 逻辑、未 mock/skip/删断言、未扩大依赖集合。
- 本地验证：`tests/integration/test_storage_source_postgres.py` + `tests/unit/storage/test_storage_source_provider.py` + `test_source_repository.py` 共 39 项通过（含 10 项真实 PostgreSQL）。
- U2 状态不变：`PROVIDER_SCHEMA_MIGRATION_IMPLEMENTED + CUTOVER_PROTOCOL_IMPLEMENTED / CUTOVER_NOT_READY`；未启用 PostgreSQL 模式、未做真实迁移。

## 062553d6 CI 收尾：Storage Cache Governance 与 U2 真实 PostgreSQL 覆盖（2026-11-26，当前）

- 起始本地及远端 `062553d61381b2aad0ce7a2e62451b0499cee5a0`。VERSION 42.24.592 未改。状态 `CODE_COMPLETE（CI 收尾与证据修正）/ CI_PENDING / U2: PROVIDER_SCHEMA_MIGRATION_IMPLEMENTED + CUTOVER_PROTOCOL_IMPLEMENTED + CUTOVER_NOT_READY`。
- Storage Cache Governance 两个失败（根因与修复）：`tests/unit/storage/test_storage_source_provider.py` 的准入事务用例导入 `psycopg.pq.TransactionStatus`（真实的 idle/INTRANS 枚举），而该 focused Job 未安装驱动。仅在 focused 依赖中追加 `"psycopg[binary]"`，未改生产依赖、未 skip/mock/删断言、SQLite 业务逻辑未动。
- U2 PostgreSQL 集成测试进入 CI：`storage-cache-governance.yml` 新增独立 Job `storage-source-postgres`（`postgres:16` service + healthcheck、最小依赖 pytest/psycopg[binary]/filelock、`MC_TEST_POSTGRES_DSN`、`MC_REQUIRE_POSTGRES=1`、`--confcutdir=tests/integration`、只跑 `tests/integration/test_storage_source_postgres.py`、`--junitxml` 并**拒绝任何 skip/失败、要求至少 10 项**、上传报告）；paths 触发补 `platform_core/storage_source_*.py` 与 `tests/integration/test_storage_source_postgres.py`（push 与 PR 两侧）。
- 并发证据修正：原 `test_admit_waits_for_an_in_flight_writer_and_sees_its_commit` 是测试外部**手动持锁**再等待，且 `owner.create()` 已返回——只证明"持锁等待"，未证明"未提交写入"。现改为 `test_admit_cannot_pass_an_uncommitted_repository_write`：用仓库自身写路径中的时间戳辅助函数作**窄屏障**，让真实 `repository.create` 在**仍持 switch 锁、SQLite 事务尚未 COMMIT** 时暂停；此时启动 `admit_cutover`，断言 0.5s 内未返回；释放后断言写入已提交且准入目标**包含该行**。屏障位于仓库内部，未在测试外部加锁。
- 崩溃恢复表述修正：三个中断用例改为异常注入命名与文档（`test_import_failure_before_commit_rolls_back_and_releases_the_marker`、`test_exception_after_commit_before_record_is_recovered_by_abort`、`test_exception_after_record_is_recovered_by_finish_cutover`），明确指出**不是 SIGKILL 实测**：提交前异常由代码清理移除 marker（真实进程终止则保留 marker，属同一状态的 fail-closed 变体，由 abort 恢复）；提交后/记录前与记录后/marker 前两种窗口下，标记与记录顺序保证真实进程终止留下相同的磁盘状态，恢复分别由 abort 与 finish 完成。`abort_cutover` 文档明确：abort **不是** PostgreSQL 数据回滚，目标侧可能保留未准入的行（无本地准入记录时 Provider 拒绝一切写，后续准入会重新导入并对账）。
- 验证（本轮）：`tests/integration/test_storage_source_postgres.py` 10 项真实 PostgreSQL 通过；`tests/unit/storage/test_storage_source_provider.py` + `test_source_repository.py` 29 项通过；`py_compile` 与 `git diff --check` 通过。未跑全仓 pytest/Playwright/前端构建/20 万素材压力测试。
- 未启用：`STORAGE_SOURCE_PROVIDER` 仍默认 sqlite；未做生产切换/迁移，未操作 NAS/OSS/S3；未启动 U3/U5。U2 = **CUTOVER_NOT_READY**（CI 通过不等于生产就绪）。
- 保护边界：VERSION、AGENTS.md、vendor、四份未跟踪保护文档未改；未连接 4070/A800。

## 141026b1 安全复审整改：切换锁、PG 顶层事务、Provider 与 revision fail-closed（2026-11-26，当前）

- 起始本地及远端 `141026b1ef9f6190d6d51ada9108637c131ac163`（上一轮 51/51 CI SUCCESS）。VERSION 42.24.592 未改。状态 `CODE_COMPLETE（本轮四项）/ CI_PENDING / U2: PROVIDER_SCHEMA_MIGRATION_IMPLEMENTED + CUTOVER_PROTOCOL_IMPLEMENTED + CUTOVER_NOT_READY / PRODUCTION_NOT_VERIFIED`。
- P0-1 切换锁路径不一致（根因与修复）：`storage_source_switch_lock` 原按传入路径的 **parent** 建锁——SQLite 写者传 `storage_sources.sqlite3`（锁在 `storage/`），而 admit/finish/abort 传准入记录（锁在 `storage/storage_source_migration/`），两侧根本不是同一把锁，切换无法等待已通过 authority check 的写者。新增 `storage_source_switch_lock_path()` 作为**唯一**锁身份解析：数据库文件、准入记录、转换标记、锁文件本身都归一到 `<storage>/.storage-source-switch.lock`；写者与 admit/finish/abort 现在共享同一把 FileLock；保留同线程重入、跨进程互斥、lifecycle→switch 顺序，普通 SQLite 业务行为不变。
- P0-2 PostgreSQL 事务边界（根因与修复）：`admit_cutover` 原在 `connection.transaction()` **之前** 调 `_durable_generation()`，该 SELECT 在非 autocommit 连接上开启隐式事务，使随后的 `transaction()` 变成 SAVEPOINT；于是本地准入记录与 marker 删除可能发生在 PostgreSQL 真正 COMMIT 之前。现在：入口 `require_idle_connection`（已开启事务直接 `STORAGE_SOURCE_CUTOVER_TRANSACTION_BUSY`，不接管调用者事务）；`_lock_cutover_scope`（`pg_advisory_xact_lock`）→ `_next_generation`（同一事务内读 durable generation，`max(本地, durable)+1`）→ import → reconcile → cutover_state 全在**一个顶层事务**；事务退出后再次校验 `transaction_status == IDLE` 才原子写准入记录，记录成功后才重写/删除 marker。CLI `_ensure_schema` 以只读 `rollback` 回到 IDLE。失败清理按阶段区分：提交前失败移除标记（SQLite 恢复可写）；提交后失败**保留**标记（两侧阻断，需 finish/abort）。
- P1 准入 Provider 严格校验：`load_storage_source_admission_record` 仅接受 `sqlite`/`postgresql`，缺失或未知即 `STORAGE_SOURCE_ADMISSION_RECORD_INVALID`；`_refuse_stale_sqlite` 不再对未知 Provider 放行；`cutover_status` 捕获该错误并报告 `INCONSISTENT`（`admission_error` 随附）；合法 SQLite 权限模式与合法 PostgreSQL 准入模式不变。
- P1 revision 证明：新增 `require_revision_token`（revision 为 None 即 `ALGORITHM_HISTORY_REVISION_UNAVAILABLE`）；转换目录引用投影改用该严格形式，扫描前后各取一次，变化或不可用均 → 409 `CATALOG_REFERENCE_CHECK_FAILED`；5000 条上限、键集分页与原匹配逻辑不变。
- 验证（本轮新增定向，未跑全仓）：`tests/integration/test_storage_source_postgres.py` **10 项真实 PostgreSQL**——锁身份一致、admit 等待持锁写者且快照包含其提交、admit 返回时 `IDLE`、第二连接在准入记录发布前已读到 `POSTGRES_ACTIVE` durable 行且 marker 仍在、提交前中断无 durable 行、提交后/记录前中断为 SWITCHING 且两侧阻断（finish 拒绝、abort 恢复、Provider 无准入不可写）、记录后/marker 前中断由 finish 恢复、generation 单调；`test_storage_source_provider.py` 16 项（含 BUSY 事务、未知 Provider、INCONSISTENT、锁重入/互斥）；`test_algorithm_provider_boundary.py` 24 项（含 revision 不可用）；路由守卫 13 项；受影响 storage-owner 与素材查找 37 项。`git diff --check` 干净，`py_compile` 通过；本轮无 SFC 变更。
- 未启用：`STORAGE_SOURCE_PROVIDER` 仍默认 sqlite；未做生产切换、未操作 NAS/OSS/S3。U2 仍为 **CUTOVER_NOT_READY**（需真实部署演练与用户授权）。
- 保护边界：VERSION、AGENTS.md、vendor、四份未跟踪保护文档未改；未连接 4070/A800。

## 80514712 审计整改：CI、U2 准入安全、U1 引用一致性与素材证据（2026-11-26，上一批）

- 起始本地及远端 `805147121db7693c1f736d56b80359673c65ac36`（业务 `271d807a`，文档 `80514712`）。VERSION 42.24.592 未改。状态 `CODE_COMPLETE（本轮缺陷）/ CI_PENDING / U2: PROVIDER_SCHEMA_MIGRATION_IMPLEMENTED + CUTOVER_PROTOCOL_IMPLEMENTED / CUTOVER_NOT_READY（未在任何真实部署启用）/ PRODUCTION_NOT_VERIFIED`。
- CI 四项根因与修复：
  1. `algorithm_postgres_store.py` 中 `PostgresAlgorithmRepository.capabilities()` 被重复定义（历史证据方法旁边的第二个定义遮蔽第一个），Ruff F811。删除旧定义、保留含 `CORE_OPERATIONS + _PORTED_PRESENTATION + HISTORY_EVIDENCE_OPERATIONS` 的单一实现；AST 扫描全仓改动类无重复方法。
  2. `algorithm-postgres-runtime.yml` 的 focused 依赖缺少 `psutil`（转换目录引用投影经 `performance_diagnostics` 间接导入）。补依赖，未跳过测试、未 mock。
  3. `tests/api/test_core_productization_views.py` 仍断言路由数为 2；实际为 `tasks`、`tasks/summary`（起始 SHA 即存在）、`tasks/{task_id}` 三条合法 GET。改为按路径+方法精确断言的三条集合，未删除 summary、未改接口。
  4. ZIP 失败用例 `one ZIP session failure stays visible and the next queued file still uploads`：注入的 503 以"第一个 POST"为目标，但双槽 FIFO 会并发创建前两个文件的会话，"第一个请求"不是稳定身份（失败现象正是 503 落到第二个文件：第二个缺失、第三个存在）。本地单用例连续 5 次通过，CI 失败日志同构；改为按 `file_name===filenames[0]` 注入，未加 timeout、未删断言、未跳过。
- U2 准入安全（新增 `storage_source_cutover.py`，扩展 schema v2）：共享切换锁 `storage_source_switch_lock`（**所有** SQLite 写者——含构造时的默认源引导与 `record_health`——在"准入检查→写入"全程持有；与既有 lifecycle fence 固定顺序 lifecycle→switch；跨线程互斥、同线程可重入）；PostgreSQL `_write` 在同一事务内 `FOR UPDATE` 校验 `w4_storage_source.cutover_state`（admission_id/generation/phase），并在写前拒绝转换标记；`admit_cutover` 在锁内重导当前 SQLite（非操作者旧快照，可用 `expected_source_digest` 拒绝源变化）→ 单事务 import+对账+写 durable cutover_state → 原子写准入记录（`os.replace`，含 source/target/content 摘要、`operation_id`、`previous_admission_id`）→ 移除标记；`finish_cutover` 仅在已发布准入时，校验 durable 行、目标摘要、冻结源摘要后释放标记；`abort_cutover` 仅在未发布准入时移除标记（SQLite 恢复可写，PostgreSQL 因缺本地准入记录仍不可写）；`writer_generation` = max(本地记录, durable 行)+1 单调；损坏标记/标记+记录并存一律 fail-closed。CLI 新增 `finish`/`abort`，`admit` 走上述协议，`status` 输出 `STEADY_SQLITE/STEADY_POSTGRES/SWITCHING/INCONSISTENT`。
- U1 引用一致性（`conversion_catalog_references.py`）：每个项目的分页扫描前后各取一次权威 `revision_token`，不一致抛 `ALGORITHM_HISTORY_CHANGED_DURING_SCAN` 并转 409（detail 带 Provider 错误码），绝不再以"扫描了一部分"为无引用；5000 条上限与原有匹配逻辑不变。
- 素材旧数据补查（`material_repository.py`）：legacy 补查命中 200 行上限时抛 `MaterialEvidenceIncomplete`（`MATERIAL_STORED_NAME_EVIDENCE_INCOMPLETE`），业务文件解析映射为 409 而非 404；低于上限的未命中仍是完整证据（空结果）。索引与有界查询不变，未恢复 `read()`，未做启动全表回填。
- 验证（本地定向，未跑全仓）：`test_algorithm_provider_boundary.py` 23 项（含新增 revision 变化）、`test_material_history_index.py`、`test_training_material_usage.py`、`test_conversion_catalog_crud.py`、`test_core_productization_views.py` 13 项、storage provider 14 项、素材查找 10 项、业务文件 27 项、`tests/integration/test_storage_source_postgres.py` **4 项真实 PostgreSQL**（含准入→双写者阻断→崩溃恢复 finish/abort→单调 generation→源变化拒绝→损坏标记）。ZIP 单用例本地 5 次通过。前端无 SFC 变更，故未重跑编译。
- 已知本地环境差异：`tests/unit/test_algorithm_repository_readiness.py::test_barrier_uses_the_same_switch_lock_as_a_custom_admission` 断言"锁文件在释放后仍存在"，本机 filelock 3.29.3 会在释放时删除锁文件（CI 为 4.3.1，该用例在 80514712 的 CI 中未失败）。本轮未修改该用例，行为合同（同一锁身份）未变。
- 未启用：`STORAGE_SOURCE_PROVIDER` 仍默认 sqlite；未在生产切换、未操作 NAS/OSS/S3、未做真实迁移。U2 = **PROVIDER_SCHEMA_MIGRATION_IMPLEMENTED / CUTOVER_PROTOCOL_IMPLEMENTED，CUTOVER_NOT_READY**（仍需真实部署演练与用户授权）。
- 保护边界：VERSION、AGENTS.md、vendor、四份未跟踪保护文档未改；未连接 4070/A800。

## A/B/C/D 批次：前端安全、U1 兼容、U2 迁移与素材热点（2026-11-26，上一批）

- 起始本地及远端 `99f9ba26895bf657e8a5f60a5c35a6afba39e410`。目录 `D:\lab\p2b2-backend`，分支 `feature/external-algorithm-publishing`，VERSION 42.24.592（未改）。状态 `CODE_COMPLETE（A/B/C/D 首批）/ CI_PENDING / VISUAL_PENDING / UAT_PENDING / SCALE_NOT_VERIFIED / HARDWARE_NOT_VERIFIED / PRODUCTION_NOT_VERIFIED`。**本批仅为授权范围内首批，不代表平台完成。**
- A 前端数据安全（`NegativePoolCategories.vue`、`AlgorithmNegativePool.vue`、`NativeTrainingReport.vue`、`NativeEvaluation.vue`）：未知写入的待核记录改为结构化 `{operation,targetId,targetName,submitted,at}`，存在未核记录时拒绝再次提交，读取错误与写入错误分列（父级 `categoryError` 作为 `readError` 传入），只有“写入之后成功完成的一次读取”才启用“已核对分类列表”，`enabled` 回执按显式值（兼容 SQLite 的 1/0）判定而非缺失即启用。报告溯源以 `algorithmId/versionId` 作用域存储、切换即清除、迟到响应按 token+作用域丢弃；版本路由复用已取回的版本详情不重复请求；`?tab=trace` 深链自动触发一次有界读取；样本诊断改为 TP/FP/FN 直达 `?tab=evaluation&view=samples&issue=…`（保留 `back`）。未新增组件/依赖，未改 API。
- B U1 三个旧读取者真正 Provider 化：新增 `platform_core/algorithm_history_evidence.py`（`open_history_repository`、`revision_token`、`iter_history_payloads`），并由 `SqliteAlgorithmStore` 与 `PostgresAlgorithmRepository` 提供等价合同——只读 revision（不初始化目录）、三态存在性探针（`None`=无法证明为空）、按 id 键集分页的 payload（每页 ≤500，总量 ≤5000，超限 `ALGORITHM_HISTORY_EVIDENCE_UNBOUNDED`）。`material_history_index` 的签名改由 Provider 的 `(provider, revision)` 组成；`training_material_usage._empty_project_history` 用 Provider 存在性探针且失败即“不新鲜”；`conversion_catalog_references` 用 Provider 分页读取并把 `AlgorithmRepositoryError` 纳入原 409 `CATALOG_REFERENCE_CHECK_FAILED`（此前 `AlgorithmSqliteAttachRefused` 会逃逸为 500）。`HISTORY_EVIDENCE_OPERATIONS` 已纳入 `_KNOWN_READ_OPERATIONS`、`capabilities()` 与切换准入记录的 capabilities 列表。旧 `require_authoritative_sqlite` 守卫保留。
- C U2 存储源元数据实际迁移：新增 `storage_source_postgres_schema.py`（`w4_storage_source`，v1；`(scope,id)` 主键、名称唯一、`WHERE is_default` 部分唯一索引、revision≥1 约束）、`storage_source_postgres_store.py`（`list/get/default/create/update/set_default/record_health/migration_status` 与 SQLite 同合同；scope 级 advisory 事务锁；`default_local` 幂等引导；`A→B→A` 仍 bump `runtime_revision`，仅改名不 bump；健康消息走 `redact_storage_error`；唯一冲突翻译为 `StorageSourceConflictError`（ValueError 子类，API 维持 409））、`storage_source_migration.py`（确定性导出、幂等导入、逐行更新而非全表写、目标更新代次更新时拒绝回退、对账区分身份差异与健康证据）、`storage_source_migration_cli.py`（status/export/import/report/admit，`admit` 仅在目标完全对账时写准入记录）。`storage/source_repository.py` 新增 Provider 选择、准入记录与 `open_storage_source_repository`；**所有 SQLite 写路径（含构造时的默认源引导）在准入后 fail-closed**，转换标记阻断两侧。`StorageManager` 与 `app.py::storage_source_repository` 已切换到工厂。跨域删除保持阻断（`STORAGE_SOURCE_DELETE_REQUIRES_CROSS_DOMAIN_EVIDENCE`），普通配置读写可用；凭据仍只在 SecretStore。
- D 素材热点首个闭环：`MaterialRepository.find_by_stored_name` + schema 8（新增 `ix_materials_stored_name` 表达式索引，`MATERIAL_READ_SCHEMA_VERSIONS` 增 8，`_REQUIRED_OBJECTS` 纳入该索引）；`app.py::_business_material_by_name` 由“全量 `read()` 后按名过滤”改为有界索引查找（`limit=2`，≥2 仍判定不唯一）。无 `stored_name` 的旧行通过一次有界补查（≤200 行，超出即视为不存在，绝不返回错误行）。本地合成实测：217,000 行时 `read()` 中位 1485.1ms，`find_by_stored_name` 命中 0.9ms／未命中 0.8ms；50,000 行 311.3ms → 2.1ms／0.8ms；查询计划使用 `ix_materials_stored_name`。
- 验证（本地定向，未跑全仓）：`tests/unit/test_algorithm_provider_boundary.py` + `test_material_history_index.py` 24 项；`test_training_material_usage.py` 相关 24 项；`tests/unit/test_conversion_catalog_crud.py` 47 项；`tests/unit/storage/test_source_repository.py`+`test_manager.py` 18 项；`tests/unit/storage/test_storage_source_provider.py` 10 项；`tests/api/test_storage_sources.py`+`test_storage_source_lifecycle.py` 11 项；`tests/integration/test_storage_source_postgres.py` 2 项（**真实 PostgreSQL**，pgserver）；素材仓库/业务文件 45 项；素材 schema 与查找 18 项；治理/交付/NAS 17 项；`vue-tsc --noEmit` 0 错误，四个改动 SFC 均通过 `@vue/compiler-sfc` 模板编译；`git diff --check` 干净。CI 侧新增：`storage-cache-governance.yml` 加 `test_storage_source_provider.py`，`algorithm-sql-store.yml` 的 PG 步骤加 `test_storage_source_postgres.py`（仅新增测试路径，未改触发/并发）。
- 未完成/下一步：U3 联合迁移设计；U5 任务库；训练准备与缓存治理；转换 L0–L5 与实机；任务执行架构；Smart Audit；VLM 参考图；剩余生命周期能力（整算法删除、凭据轮换、发布回退、存储源跨域删除证据）。存储源 Provider 尚未在生产启用（`STORAGE_SOURCE_PROVIDER` 默认 sqlite，未授权切换）。
- 保护边界：VERSION、AGENTS.md、vendor、四份未跟踪保护文档未改；未连接 4070/A800，未改真实数据库，未切换生产 Provider。


## 架构阶段开工：CI 修复与 U1 Provider 边界收口（2026-11-26，当前）

- 起始本地及远端 `bdb705b2ea072a593014d5eb30c4ee86e2417a69`。目录 `D:\lab\p2b2-backend`，分支 `feature/external-algorithm-publishing`，VERSION 42.24.592（未改）。业务候选 `4dafd1f8`、`245be439`，含本记录的最终 HEAD 为其后的文档提交。状态 `CODE_COMPLETE（部分单元）/ CI_PENDING / VISUAL_PENDING / UAT_PENDING / SCALE_NOT_VERIFIED / HARDWARE_NOT_VERIFIED / PRODUCTION_NOT_VERIFIED`。**本阶段仅局部推进，不代表平台开发完成。**
- 开工 CI（`bdb705b2`）：Frontend Runtime Stabilization 失败，`Build opt-in Vue catalog preview` 与三个 `Build standalone Vue app` 同因。根因是 `NegativePoolCategories.vue` 待核验行的 `@click="pendingWrite=''"` 单引号在被脚本化替换时丢失，表达式截断（`Unterminated string constant`），`vue-tsc` 与单文件 SFC 编译检查当时未覆盖该行。已改为具名处理器 `clearPending`，并对其余改动 SFC 全部执行 `@vue/compiler-sfc` 编译检查；本机 `npm run build:app` 复现通过（99 个本地资源校验）。
- U1（算法域）本轮实际收口：审计发现三个读投影仍以 SQL `ATTACH` 直接打开项目 `algorithms.sqlite3`（`material_history_index`、`training_material_usage`、`conversion_catalog_references`），绕过 `open_algorithm_repository` 的 Provider 边界，切换后可能读到过期 SQLite 行。新增 `algorithm_repository.require_authoritative_sqlite()` 与 `AlgorithmSqliteAttachRefused`，复用既有 transition marker、authority barrier 与 admission record 判定，使这些读取在 PostgreSQL 权威下 fail-closed；并以此作为相关项目进入切换的准入前提。回归测试覆盖“无记录 / 已准入 / 已撤销”三种情形，`tests/unit/test_algorithm_provider_boundary.py` 18 项通过。
- 已确认无需重做的能力：`algorithm_cutover` 已含 admission、maintenance freeze/verify/switch/resume、recovery、rollback 评估与 transition/barrier；`algorithm_migration` 已含 v2 快照、内容摘要、自然键、目标侧回执保留与清理行；`open_algorithm_repository` 在 PG 准入下拒绝过期 SQLite 且不回退。本轮未重写这些模块。
- 未开始（本阶段后续单元）：U2 存储源元数据 PostgreSQL Provider/Schema/迁移；U3 素材+正式GT+负样本池联合迁移设计与代码；素材全量读取/写入热点整改；训练准备与缓存治理；转换 L0–L5 合同补齐与算能 BModel 误检根因；任务执行架构与生命周期收口。以上均需独立设计或真实环境，未在本轮冒称完成。
- 验证：受影响 Python 文件 AST 与导入通过；provider 边界专项 18 项通过；三个改动 SFC 编译检查通过；`npm run build:app` 本地通过。未运行全仓 pytest/Playwright，未做 20 万素材压力测试。
- 保护边界：VERSION、AGENTS.md、vendor、四份未跟踪保护文档与用户文件未改；未连接 4070/A800，未切换生产数据库，未改远端。

## 训练报告工作台与状态计数口径（2026-11-26，上一批）

- 起始本地及远端 `bacf4f10e384baee341f33f77436f70670d54e24`。目录 `D:\lab\p2b2-backend`，分支 `feature/external-algorithm-publishing`，VERSION 42.24.592。业务候选 `add2bf9e`、`60f31ea8`，含本记录的最终 HEAD 为其后的文档提交。状态 `CODE_COMPLETE（部分单元）/ CI_PENDING / VISUAL_PENDING / UAT_PENDING / SCALE_NOT_VERIFIED / PRODUCTION_NOT_VERIFIED`。
- 负样本分类：父级共享来源保留；新增写入排队刷新（读取进行中不再丢弃刷新）、创建/编辑核验真实 ID 与请求字段、未知结果保留待核记录并回读不重试、读取失败与上次成功列表分别提示；项目级成员分类仍走公共池 v2 合同，算法级不新增分类关系。
- 训练报告：`NativeTrainingReport` 扩为五个分区——训练概况（原概况内容保留）、训练过程（原曲线/分页）、独立评测（原 NativeEvaluation）、**样本诊断**（已记录失败/警告/质量门禁 + 指向真实 FP/FN 与困难样本入口，明确“无 Test 评测则无 Test 侧证据”、正式 Test 不被困难样本回流）、**训练溯源**（打开时一次有界版本详情读取，父/基础版本按 ID 直达其报告，冻结数据/评测基准/转换/交付深链；未记录时显示未记录，不按名称推断）。Tab 仍走 `?tab=`，返回与深链合同未变。
- 状态计数口径：`tasks/summary` 现分列训练任务与准备任务（`counts`/`total` 与 `prepare_counts`/`prepare_total`），总览与质量中心文案改为“近 7 天训练任务 N 条（另有准备任务 M 条，不计入训练次数）”并说明只统计仍在任务表中、created_at 在窗口内的记录，已删除任务不计入；不冒充历史趋势。
- 未完成：质量中心异常样本联动与检查结果详情、Smart Audit 专项；P2 母模型安装/取消/发现登记、训练批量暂停/恢复/停止、算法卡片可信最佳评测摘要。
- 验证：`vue-tsc --noEmit` 0 错误；`NativeTrainingReport.vue` `@vue/compiler-sfc` 模板编译通过；`tests/api/test_training_job_visibility.py` 12 项通过（含 summary 路由）。未运行全仓 pytest/Playwright，未重复构建。
- 视觉 `VISUAL_PENDING`；四份保护文档、AGENTS.md、VERSION、vendor 与用户文件未改；无生产环境操作。下一轮先按最终 SHA 核对 CI，再做质量中心联动与 P2 批量/安装能力。

## 分类来源、血缘与有界统计（2026-11-26，上一批）

- 起始本地及远端 `7e702bc526d4ba8f126fac71d5d8381e53ac3637`。目录 `D:\lab\p2b2-backend`，分支 `feature/external-algorithm-publishing`，VERSION 42.24.592。业务候选 `4195fe7b`、`4c2c2bf1`、`4270683e`，含本记录的最终 HEAD 为其后的文档提交。状态 `CODE_COMPLETE（部分单元）/ CI_PENDING / VISUAL_PENDING / UAT_PENDING / SCALE_NOT_VERIFIED / PRODUCTION_NOT_VERIFIED`。
- 负样本分类：`NegativePoolCategories` 原来写入时复用 loading 标志，自身 reload 被短路导致不刷新；现拆分为 saving/loading，写成功后实际刷新。分类列表上移到工作台父级（`AlgorithmNegativePool.vue`）单一来源，管理面板与成员筛选共用，改名/启停后筛选器同步；独立 legacy 挂载仍保留有界回退。写入区分明确拒绝（400/404/409/422）与未知：未知时回读分类状态、不自动重试；名称唯一性仍由服务端判定。分类删除保留原引用保护未暴露。
- 成员分类调整证据：`negative_pool.members` 对带 `algorithm_id` 的算法级成员操作显式拒绝 `categories/categories_only`（仅项目级 `negative_pool.members.v2` 允许 action=set + categories_only），因此算法级页不提供该操作；项目公共池 `PublicNegativePool.vue` 已有 `categories/assign` 成员分类设置，200 张上限与正式 GT/训练资格分离合同未变。
- 算法血缘：版本详情按真实 `base_version_id`/`parent_version_id` 在展开时最多两次有界读取解析名称，解析失败保留“未在当前页或未提供”，不按名称推断；详情新增训练报告、独立评测、转换记录、交付记录四个深链，各自沿用原路由与 Owner。
- 有界统计：`TaskRepository.summary()` 对单项目、`created_at` 窗口内的训练/训练准备任务做一次 GROUP BY，经 `GET /api/v62/projects/{p}/tasks/summary?days=1..30` 暴露；总览与质量中心展示近 7 天真实状态计数并标注范围，不扫描历史报告或全量任务。
- 未完成：训练报告深层分析的新增分区（现有概况/训练过程/独立评测/FP-FN 诊断已具备，本轮未扩展）；质量中心异常样本联动与 Smart Audit 仍独立；P2 母模型安装/取消/登记、训练批量暂停/恢复/停止、算法卡片可信最佳评测摘要未实施（仅 batch-delete 有批量端点；最佳评测需同基准同协议+独立性证据的有界方案）。
- 验证：`vue-tsc --noEmit` 0 错误；`Algorithms.vue`、`ModelVersionDetails.vue` `@vue/compiler-sfc` 模板编译通过；`tests/api/test_training_job_visibility.py` 12 项通过（含新路由后 OpenAPI 守卫）。未运行全仓 pytest/Playwright，未重复构建。
- 视觉 `VISUAL_PENDING`；四份保护文档、AGENTS.md、VERSION、vendor 与用户文件未改；无生产环境操作。下一轮先按最终 SHA 核对 CI，再推进训练报告分区、质量中心联动与 P2 批量生命周期。

## CI 精准修复与负样本分类、血缘落地（2026-11-26，上一批）

- 起始本地及远端 `dd9b93dded153a364db1ac58102100842b9b9c33`。目录 `D:\lab\p2b2-backend`，分支 `feature/external-algorithm-publishing`，VERSION 42.24.592。业务候选 `92359c91`、`fae64321`、`0e1f732b`，含本记录的最终 HEAD 为其后的文档提交。状态 `CODE_COMPLETE（部分单元）/ CI_PENDING / VISUAL_PENDING / UAT_PENDING / SCALE_NOT_VERIFIED / PRODUCTION_NOT_VERIFIED`。
- StorageRescan 编译失败根因：上一轮插入的返回素材库链接含字面反引号且插在 `v-if`/`v-else-if` 之间，破坏相邻结构。已恢复原链，链接改为链结束后的独立 `v-if="collected"`，仅在 `SUCCEEDED/PARTIAL_SUCCESS` 且实际应用了图片或标注（`applied`/`annotation_applied` > 0）时显示；失败与取消不再表达为导入成功。用 `@vue/compiler-sfc` 对受影响 SFC 做最小编译检查通过。
- 批量删除收口：恢复双向互斥（批量写前检查单任务生命周期/停止/恢复是否进行中）；单任务删除只与覆盖该任务的待核批量冲突；核对捕获操作者、项目、待核身份，账号或作用域变化后旧响应不写入新作用域；操作者切换清理旧核对结果；结束核验必须有可信逐项结果 + 明确确认 + 持久清除成功，否则保持保护；`writePendingBatch(null)` 失败不再冒充解除。
- 负样本分类：新增 `NegativePoolCategories.vue` 挂载在算法级负样本池页，复用 v61 categories 的 GET/POST/PATCH 完成列表（含引用数量）、新增、改名、启停；分类删除保留原引用保护，未暴露。项目公共池原分类管理与成员分类设置保持，200 条成员写入限制未变。
- 算法血缘：版本详情新增“版本关联与血缘”，父/基础版本名称由已加载的版本页解析（不在当前页时显示原始 ID 或“未在当前页”），显式声明血缘、冻结快照、独立评测、困难样本与转换/交付为独立证据链并指向版本行入口；服务端未记录血缘时显示“未记录”，不按名称推断父子关系。
- 未完成（含证据）：质量中心与总览的补充分析（本轮未实施）；负样本成员分类调整在算法级页仍走公共池入口、审核为只读投影（v61 无池级审核写入端点）；母模型安装/取消/发现登记、训练批量暂停/恢复/停止、算法卡片最佳评测投影仍待专项（仅 batch-delete 存在批量端点）。
- 验证：`vue-tsc --noEmit` 0 错误；三个改动 SFC 的 `@vue/compiler-sfc` 模板编译通过；改动 Python 文件未涉及（本轮无后端改动）。未运行全仓 pytest/Playwright，未重复构建。
- 视觉 `VISUAL_PENDING`；四份保护文档、AGENTS.md、VERSION、vendor 与用户文件未改；无生产环境操作。下一轮先按最终 SHA 核对 CI，再推进质量中心/总览与安装、批量生命周期专项。

## 回执合同整改与普通业务原生化（2026-11-26，上一批）

- 起始本地及远端 `c781334607e6533e05d6d2cc267a7636f3c76e26`。目录 `D:\lab\p2b2-backend`，分支 `feature/external-algorithm-publishing`，VERSION 42.24.592。业务候选 `3bda1731`、`30beb6ca`，含本记录的最终 HEAD 为其后的文档提交。状态 `CODE_COMPLETE（部分单元）/ CI_PENDING / VISUAL_PENDING / UAT_PENDING / SCALE_NOT_VERIFIED / PRODUCTION_NOT_VERIFIED`。
- 批量删除回执：不再过滤非法 ID；四类集合各自唯一、两两互斥、并集等于原提交集合、`audit_retained_ids ⊆ deleted_ids`、数量与明细一致，任一异常进入“结果待核验”。只读核对逐项校验 job_id、状态枚举、唯一性、完整范围与汇总一致，不再凭 `counts.deleted` 解锁。待核记录在提交前写入，写入失败即拒绝提交；记录绑定已确认操作者与项目，异步回执只更新本作用域；核验后可显式“结束本次核验”，保留未确认明细且不宣称全部删除成功，不自动重试。仅 `batch-delete` 的 400/404/422 视为明确未执行；恢复校验等写操作按记录归属互斥，未知批量删除不再永久阻塞整个工作台。
- 训练环境合同：节点清单改读真实 `items`；母模型状态使用真实枚举（UNVERIFIED/CHECKING/VERIFIED/INVALID/INCOMPATIBLE/SANDBOX_UNAVAILABLE/FAILED/INTERRUPTED）；校验按 `accepted/asset_id/validation_status` 验证，未知时读取原资产而不重复提交；上传按 `asset_id/sha256/reused/validation_status` 呈现，官方固定摘要可直接校验通过，其余仍须校验；安装任务接入 `next_cursor` 有界分页并展示同代回执；不展示服务器物理路径。
- 负样本分类：确认 `/api/v61/projects/{p}/negative-pool/categories`（GET/POST/PATCH）与 `/categories/assign` 已存在，算法级负样本池的分类筛选改为按名称选择并显示引用数量与停用状态，不再输入裸 ID。项目公共池原有分类管理保持。未开放分类删除。
- 存储：核对 `StorageRescan` 已覆盖扫描创建（images/YOLO/COCO/VOC 标注确认）、执行资源预检、任务进度、计数、确认应用、取消与未知处理；本轮补充“返回素材库查看归集结果”。未新建导入引擎。
- 算法卡片：SQLite 与 PostgreSQL 的算法库查询新增有界 `latest_created_version`（`created_at DESC, sort_index, id` 与版本分页一致），卡片展示“最新创建版本”，不逐卡读取 v49。
- 证据：标签快捷预设原能力不存在（旧前端仅有颜色鲁棒性与节点预设，后端 `presets` 属 CSC/鲁棒性），未虚构；批量暂停/恢复/停止无批量 API（仅 batch-delete），未用浏览器循环；算法血缘深层只读、总览历史趋势、最佳评测投影仍待后续专项。
- 验证：`vue-tsc --noEmit` 0 错误；改动 Python 文件 AST 通过；定向 pytest 4 项通过（算法库投影 3 项 + 既有版本分页断言）。未运行全仓 pytest/Playwright，未重复构建。
- 视觉 `VISUAL_PENDING`；四份保护文档、AGENTS.md、VERSION、vendor 与用户文件未改；无生产环境操作。下一轮先按最终 SHA 核对 CI，再做血缘深层只读、总览趋势与批量生命周期（需先证明批量服务端合同）。

## 训练批量删除安全收口与训练环境原生化（2026-11-26，上一批）

- 起始本地及远端 `645fdd6725c06420b69b779b7713c0d8d2181801`（业务代码 `1247dd01`）。目录 `D:\lab\p2b2-backend`，分支 `feature/external-algorithm-publishing`，VERSION 42.24.592。本轮业务代码候选见 `c9f9cd73`、`e6a58ef5`、`b5c0d063`，含本记录的最终 HEAD 为其后的文档提交。状态 `CODE_COMPLETE（部分业务单元）/ CI_PENDING / VISUAL_PENDING / UAT_PENDING / SCALE_NOT_VERIFIED / PRODUCTION_NOT_VERIFIED`。
- 开工 CI（`645fdd67`）：GPT 核验 30 成功、0 失败、1 运行中；未重复整改历史已通过项。
- 批量删除：前端按所选集合校验回执（`requested`、`deleted/skipped/missing/failed` 与 id 集合、类别互斥、`audit_retained_ids ⊆ deleted_ids`），按“记录删除 / 按原证据保留 / 跳过执行中 / 未找到 / 失败”分列，不再承诺全部产物保留。提交前写入待核验记录（项目、操作者、任务 ID），4xx 明确拒绝即清除，网络/5xx/未知保留；新增只读 `GET /api/v48/projects/{p}/jobs/deletion-status?job_ids=`（≤200，不删除不重试）用于核对，全部 `deleted` 才确认，其余保留未知并允许人工重试。批量与单项生命周期写操作互斥，选择只含 `TRAINING` 终态记录（准备任务不入批）。浏览器 abort 不代表服务端撤销。
- 评测收尾：`compare_evaluations` 复用共享身份投影且历史独立性规则不变，原因码由断言锁定；严格排名要求 `verified_independent`；单个合格版本显示“唯一合格版本，未进行多版本比较”；v49 最新创建改为与版本分页 Owner 相同的 `created_at DESC, sort_index, id` 口径。
- 节点：中央持久任务与 Agent 上报任务分别计数，不再合并为精确执行总数；GPU 使用、中央预留与调度资格仍分开。
- 训练环境原生化：新增 `TrainingEnvironments.vue`（路由 `/projects/:projectId/nodes/environments`，节点页入口，菜单未改）。训练解释器探测只在点击“读取训练环境”时执行；母模型资产列表含身份/大小/来源/校验状态/SHA256，支持既有安全校验与显式 `.pt` 上传登记；节点已发现权重与安装任务只读展示，均标注“未校验/不代表可训练”。
- 未完成（含证据）：标签快捷预设与负样本分类/审核无对应 HTTP API（`negative_pool.py` 有分类能力但仅 v61 列表/回执端点暴露）；训练批量暂停/恢复/停止无批量服务端 API（仅 `batch-delete`），按纪律未用浏览器逐任务循环；存储扫描导入创建、算法血缘深层只读、总览历史趋势、算法卡片最新/最佳投影未实施。
- 验证：`vue-tsc --noEmit` 0 错误；改动 Python 文件 AST 通过；定向 pytest 6 项通过（批量删除与只读核对、保留证据、严格排名与历史原因码、既有比较）。未运行全仓 pytest/Playwright，未重复构建。
- 视觉 `VISUAL_PENDING`；四份保护文档、AGENTS.md、VERSION、vendor 与用户未跟踪文件未改；无生产环境操作。下一轮先按最终 SHA 核对 CI，再推进存储扫描导入与负样本分类（需先补最小只读/写入端点）及算法卡片投影。

## 评测语义收尾、工作台专业化与批量原生（2026-11-26，上一批）

- 起始本地及远端 `e976a646e5455874d09e4d04036fa05fb96a6c86`（业务代码 `2f8ff419`）。目录 `D:\lab\p2b2-backend`（上一节写作 `D:\p2b2-backend` 系笔误，实际 Git Root、origin 与分支均未变）。分支 `feature/external-algorithm-publishing`，VERSION 42.24.592。本轮业务代码候选见 `0bfa4c5b`、`7eaa841f`、`33c6e91d`、`1247dd01`，含本记录的最终 HEAD 为其后的文档提交。状态 `CODE_COMPLETE / CI_PENDING / VISUAL_PENDING / UAT_PENDING / SCALE_NOT_VERIFIED / PRODUCTION_NOT_VERIFIED`。
- 开工 CI（`e976a646`）：GPT 核验 16 成功、0 失败、9 运行中（Algorithm SQL Store、Online Feedback Runtime push 已成功）。未重复整改历史 Schema 7、AI 单图审核与训练报告问题。
- A 版本身份与可比性：`training_evaluation.evaluation_benchmark_identity` 统一投影五项基准摘要与 `bundle_verified` 输入绑定；`evaluation_strict_rank_evidence` 追加“verified_independent 历史独立性 + 协议 + 类别身份不歧义”才给排名 key，并把协议并入 key；`compare_evaluations` 复用同一身份投影但保留原历史独立性规则（旧比较行为不变）。v49 报告改为调用该共享函数，不再自持一份规则。算法库与算法报告的“当前/最新创建”改为两个独立条件，可同时显示。最新创建版本身份改由版本分页 Owner（SQLite `asset_versions` 与 PostgreSQL Provider）以单行有界查询返回 `latest_created_version`，翻页不再触发完整报告读取。
- B 语义整改：节点任务统计按 `task_id` 去重中央持久任务与 Agent 上报，无身份时分别计数，不推断可调度；视频切帧概览改为互斥业务分类（取消请求计入“正在停止”而非失败/已停止）；标签概览区分未读取与真实 0。
- C 工作台：AI 创建第一步显示实际已选、冻结引用、手动排除与当前页/筛选总数；清洗工作台新增互斥任务概览、状态标签、选中任务待处理数量、返回素材库入口并令牌化面板样式。
- D 转换：创建与详情改用工作区令牌（去除蓝色/石板色与 12px 卡片），详情明确“转换结果 → 结构验证 → 张量与检测框一致性 → 板端验证 → 交付准入”证据分层。
- E 原生补齐：训练任务墙新增基于既有 v48 `/jobs/batch-delete` 的批量删除（≤200 条、服务端跳过执行中、保留算法版本与产物、回执分列删除/跳过/未找到/失败），选择项沿用原资格投影。
- 未完成：算法卡片列表的“最新创建/最佳评测”有界投影（需在 SQLite 与 PostgreSQL 两个 Owner 同步增加相关子查询）；标签快捷预设（后端无该 API，需先产品确认，未新建）；节点训练环境/母模型/诊断的完整原生入口；有界历史趋势。AiCreate/NativeCleaning 未重建任何引擎，参考图多图入模仍属独立专项。
- 验证：`vue-tsc --noEmit` 0 错误；四个改动 Python 文件 AST 通过；定向 pytest 4 项通过（新增严格排名回归、两个既有比较回归、版本分页投影断言）。未运行全仓 pytest/Playwright，未重复构建。
- 视觉 `VISUAL_PENDING`。四份保护文档、AGENTS.md、VERSION、vendor 与用户未跟踪文件未改；无生产环境操作。下一轮先按最终 SHA 核对 CI，再做算法卡片投影与节点环境原生入口。

## 算法版本身份与评测可比性收口（2026-11-26，上一批）

- 起始本地及远端 `38c0ea534c6fc397416cdc7e1b70b0f7e97a6228`（GPT 独立核验 23/23 workflow 成功：PR 22/22、push 1/1，Frontend Runtime Stabilization run 45774436074 全 6 Job 成功，P1Z Job 139757446845 成功）。目录 `D:\lab\p2b2-backend`，分支 `feature/external-algorithm-publishing`，VERSION 42.24.592。本轮业务代码候选见提交 `Algorithms`/`AlgorithmReport`/`training_evaluation_service` 的提交；含本记录的最终 HEAD 为其后的文档提交。状态 `CODE_COMPLETE / CI_PENDING / VISUAL_PENDING / UAT_PENDING / SCALE_NOT_VERIFIED / PRODUCTION_NOT_VERIFIED`。
- 算法报告可比性：`TrainingEvaluationService._v49_evaluation_comparability` 复用 `compare_evaluations` 的严格口径（五项 benchmark_scope 摘要 + `bundle_verified` 绑定 + 历史独立性 + `evaluation_protocol_id`）生成同口径 key，无法证明时返回原因码；v49 轻量报告的 `version_quality` 行新增 `evaluation_id/benchmark_scope_id/evaluation_protocol_id/comparability_key/comparability_reason`，仍是同一 40 版本有界窗口，无新增扫描。
- `AlgorithmReport.vue`：移除跨全部近期版本的单一 `highestTest`，改为按同口径 key 分组、组内取最高并在界面标注“基准 + 协议 + 该口径版本数”；不可比的成功 Test 按原因计数提示；明确窗口“仅最近 N/M 个版本，不是全历史最佳”；版本表新增“可比性”列。不新建最佳版本权威，不跨基准排名，不填 0。
- `Algorithms.vue`：删除“分页第一条即最新创建”的错误标记，改为展开时读取现有 v49 轻量报告的 `latest_created_version`（全算法服务端身份），当前版本与最新创建各自独立、可同时成立；读取失败时只提示不显示标签，不影响版本表。
- 未做：算法卡片列表的“最新创建/最佳评测”投影（需在 `AlgorithmSqlStore`/Postgres 两个 Owner 增加有界相关子查询，属下一轮，避免 N+1 与跨基准排名）；AiCreate/NativeCleaning 的页面级专项优化本轮未实施，既有三步表单、冻结选材、试跑、范围预检、后台执行、停止/重试、逐图处理与确认链路未改。
- 静态检查：`vue-tsc --noEmit` 0 错误；Python AST 通过；新增可比性投影用脚本逐项验证（有效→key、缺协议/缺绑定/历史独立性未验/缺基准证据/评测未成功→对应原因码、key 稳定、协议变化改变 key）。未运行全仓 pytest/Playwright，运行期交给 CI。
- 视觉 `VISUAL_PENDING`（本机无 GitHub 令牌，制品 15096021961、15095377753、15095019996、15096530190、15095119973 未下载）。四份保护文档、AGENTS.md、VERSION、vendor 与用户未跟踪文件未改；无生产环境操作。下一轮先按最终 SHA 核对 CI，再做算法卡片有界投影与 AiCreate/NativeCleaning 工作台优化。

## 资源与交付工作台产品化及审核状态定位（2026-11-26，上一批）

- 起始本地及远端 `8b98878b0c0ca52f6cccb88464656534610708fd`，工作区仅有四份未跟踪保护文档。目录 `D:\lab\p2b2-backend`，分支 `feature/external-algorithm-publishing`，VERSION 42.24.592。代码候选见本记录提交前的 `git rev-parse HEAD`，验收以含本记录的远端最终 HEAD 为准。状态 `CODE_COMPLETE / CI_PENDING / VISUAL_PENDING / UAT_PENDING / SCALE_NOT_VERIFIED / PRODUCTION_NOT_VERIFIED`。
- 开工 CI（`8b98878b`）：Frontend Runtime Stabilization run 45770839855 唯一失败为 P1Z isolated real-entry acceptance Job 139745204550 的 “Native AI single-image review against the real API”，其余 Job（frontend、browser-navigation 1/2/3）成功；Material Annotation Atomicity 在 `d3075b56` 已成功。
- 审核状态定位根因：`tests/browser/native-ai-review-decision.spec.mjs` 用 `inspector.getByRole('heading',{level:4})` 读取审核状态，而上一轮 UI 已把图片名放入 h4、状态移入 `.review-inspector-state`。修复给状态元素加 `role="status" aria-label="审核状态"`（真实业务语义、可访问、稳定），测试改用 `inspector.getByRole('status',{name:'审核状态'})`，并一次性替换该文件全部 6 处状态断言，保留原请求 ID、单图范围、刷新恢复、未知结果、原回执、候选隔离、GT 不提前写入、请求次数与防重复提交断言。未恢复旧标题结构，未改审核状态机。
- 局部问题：`TaskStatusTag` 的 `PARTIAL_SUCCESS` 改为 warning 语义；训练任务耗时改为只依据服务端 `started_at/finished_at/status`：终态有结束时间为“终态 X”，运行中为“自然 X”（标注含等待与暂停、非有效训练时长），排队为“尚未开始”，终态缺结束时间显示“缺少结束时间”而不再用 `Date.now()` 推算；抽屉附口径说明，无新增轮询。算法版本面板新增“最新创建”标签（服务端按创建时间倒序）与“最佳评测版本不在列表内跨基准比较”的说明，未新增后端投影，未跨基准排名。
- 六页产品化：算力与节点新增机群概览（节点/在线/心跳超 5 分钟/已上报 GPU/CUDA 可用/执行中）与节点卡摘要（心跳时长、CUDA、GPU 占用、Worker、执行中），明确“在线与心跳不等于可调度”；模型转换环境新增检测汇总、厂商/检测状态筛选、卡片“环境与工具链/检测证据”分组及“检测通过→转换成功→数值一致→硬件验证→交付资格”证据层级；存储管理新增存储源概览、健康状态标签、逻辑占用/清理任务分组与“逻辑量不等于物理释放”说明；平台对接新增对接状态条、连接配置与业务执行分组、同步结果四态标签与“未知结果先核对原任务”说明，并把 API 路径从标题移入高级说明；畅联云数据新增当前浏览层级与权重本地筛选（仍为 int64 字符串身份、分层读取）；AI 辅助配置新增模型概览与验证状态标签。
- 其余页面：标签管理新增标签概览（有效/历史停用/当前筛选/引用统计）并令牌化样式；视频切帧新增本页任务概览、状态语义标签与“切帧成功≠素材正式入库”说明；AI 标注任务状态改用语义标签；AI 审核三栏压缩左侧筛选宽度、扩大右侧检查区（`clamp(320px,29vw,560px)`），状态改为可视标签样式。
- 未做页面级专项优化：自动标注及清洗（AiCreate/NativeCleaning 仅复核未改）、转换创建/详情、算法报告深层归因。算法卡片“最佳评测版本”仍需一处有界列表投影（按评测基准分组），本轮仅按证据边界如实显示，未虚假排名。
- 静态检查：`vue-tsc --noEmit` 通过（0 错误）；`.vue` 已按 `.gitattributes` 保持 LF；`git diff --check` 通过。本轮未运行全仓 pytest、Playwright 或大型构建，运行期交给 CI；P0 为浏览器用例定位修改，需 CI 的 “Native AI single-image review against the real API” 复核。
- 视觉仍为 `VISUAL_PENDING`（本机无 GitHub 令牌，制品 15094506447、15094935118 未下载）。四份保护文档、AGENTS.md、VERSION、vendor 与用户未跟踪文件未改；无生产环境操作。下一轮先按最终 SHA 核对 CI，再推进自动标注创建/清洗与转换创建详情页。

## 核心生产链路工作台与 CI 精准收口（2026-11-26，上一批）

- 起始本地及远端 `b186bc237bb09e1bb890bd79c5dbc0daf07295a3`，与上一轮核验 HEAD 一致，工作区仅有四份未跟踪保护文档。目录 `D:\lab\p2b2-backend`，分支 `feature/external-algorithm-publishing`，VERSION 42.24.592。本轮代码候选见本记录提交前的 `git rev-parse HEAD`；实际验收以含本记录的远端最终 HEAD 为准，状态 `CODE_COMPLETE / CI_PENDING / VISUAL_PENDING / UAT_PENDING / SCALE_NOT_VERIFIED / PRODUCTION_NOT_VERIFIED`。
- 开工 CI 快照（`b186bc23`）：PR 工作流全部成功，push 两条失败。Material Annotation Atomicity run 45765652516 / Job 139725807382 为 215 通过、1 失败、1 跳过；Frontend Runtime Stabilization run 45765652529 / Job 139725895513 为 84 通过、1 失败。
- Schema 7 根因（本轮定位）：`platform_core/__init__.py` 导入 `material_repository_batch`，其 `_install_repository_initialization_cache` 把 `MaterialRepository.__init__` 换成进程级就绪缓存。测试先在 193 行成功构造同一项目，随后删表再构造时命中 `_MATERIAL_INIT_READY` 快路径，`_initialize` 与注入的 `_SCHEMA` 从未执行，故未抛异常。诊断脚本确认 `cached: True`、`_read_schema_version_fast() is None`、构造不抛错。生产实现无缺陷：缓存按模块注释仅保证进程内首次构造权威，进程重启即重新校验；同文件其它用例已用 `_MATERIAL_INIT_READY.discard(...)` 模拟新进程。修复只在夹具丢弃该路径的缓存并注释原因，保留 DDL 回滚、旧素材与修订号、原图 SHA256、回执补建及再次打开幂等断言。单项 pytest 通过（1 passed）。
- 训练报告旧入口断言（本轮定位）：`23e1797c` 已把第一处 `/继续训练.*LEGACY_BRIDGE/` 换成原生入口，第二处（第 96 行，`back=` 场景）漏改。源码核对：继续训练已由 `TrainingIteration.openTraining` + `readTrainingSource` 校验动作身份、评测身份、模型摘要与固定任务 ID，并带 `algorithm/source_version/evaluation/action/supplement` 进入 `TrainingCreate`，后者再次读取来源并保留固定 Test 基准；原高级评测桥仍携带 `return_to`。用例改为断言原生“困难样本与继续训练”入口存在，并沿用原高级评测桥的 `return_to` 等于来源，保留返回来源、身份不一致与版本对比断言。
- 核心生产链路 UI：全局样式把历史算法库硬编码灰阶（`#ddd/#eee/#333/#777/#888`）与 10px 圆角改为 `--workspace-*` 令牌、8px 圆角及 4/8/12/16 间距。算法库卡片明确“当前版本 mAP50”口径并新增基准不可比提示，卡片主操作改为 `primary`，版本行原流程链接降级为次级样式。素材库把 11 个并列按钮拆为常用动作组与次级链接组，保留全部入口与名称。训练任务新增算法/版本、运行设备、已运行与失败原因，状态改用共享语义标签。总览新增有界“待处理失败任务”（`status=FAILED`、limit 5）并说明不代表全量。质量中心明确本页检查范围与结果张数，训练与评测页签改用共享状态标签。
- 新增公共组件 `frontend/src/components/TaskStatusTag.vue`，统一总览、质量中心与训练任务的状态用词和语义色（仅成功/警告/失败着色），未引入第二套主题或状态机。
- 仅继承公共主题而未做页面级专项优化的菜单：算力与节点、模型转换环境、AI 辅助配置、存储管理、平台对接、畅联云数据、标签管理、视频切帧、自动标注及清洗。本轮未改其业务代码。
- 静态检查：`vue-tsc --noEmit` 仅报本机缺少 `@noble/hashes/sha2.js`（package.json 已声明 2.0.1，属本机依赖缺失，非本轮改动）；`git diff --check` 通过。补齐本机前端依赖后 `npm run build:app` 构建成功（95 个本地资源校验通过），并定向运行受影响的 6 个 Vue 用例（`app-shell`、`training-tasks-native`、`native-materials`、`native-material-datasets`、`native-ai-create`、`native-training-report`）共 16 项全部通过。未运行全仓 pytest 或其他 Playwright 集合。
- 本机无法下载 CI 制品（无 GitHub 令牌），截图未核对，视觉保持 `VISUAL_PENDING`。四份保护文档、AGENTS.md、VERSION、vendor 与用户未跟踪文件均未改动；未进行任何生产环境操作。下一轮先按最终 SHA 单次查询 CI，确认两条失败是否关闭，再继续资源与交付页面（算力与节点、存储、平台对接、转换环境、畅联云数据）的专项优化。

## Schema 7 与审核入库定向收口（2026-11-26，上一批）

- 起始本地及远端 `041f91d714d3eb104fce0e045b22cca177082ee6`。代码候选 `cc59bc0c272cf94fa547dc9349ae3f5e8598e0b0`。工作目录、分支及 VERSION 沿用下节记录。验收以含本记录的远端最终 HEAD 为准。
- 基线最后一次定向快照为 28 成功、1 失败、2 运行，当前仅已确认 Material Annotation Atomicity Job 139722844359 的 Schema 7 补建用例未触发预期异常。夹具显式提交删表，用独立连接校验 DDL 缺失、Schema 7 和快路径拒绝，并在初始化函数实际使用的模块中注入特定错误。覆盖 DDL 回滚、旧素材和修订、原图摘要、回执补建与再次打开。Schema 5 夹具与生产迁移原样保留。
- 入库弹窗用当前标签与数字分别验证 29、1 和其他既有范围。运行和结束后的弹窗只显示适用动作。原排除、请求编号、执行去重与 GT 断言保留。未修改业务执行。
- Python AST、JS 语法、Vue SFC 及 Git 差异检查通过。运行期仍由 CI 验证。继续保留 `CI_PENDING / VISUAL_PENDING`，按最终 SHA 单次查询。

## 全平台视觉收口与基线 CI 修复（2026-11-26，上一批）

- 畅联云使用 FastAPI 模块化单体、SQLite 与独立 Vue 应用。目录 `D:\lab\p2b2-backend`，分支 `feature/external-algorithm-publishing`。起始 `1893e2ee93108d62341be8cbdef4c6b63bc55771`，代码候选 `8ba383fa8691dac3243d830b7dfdaa0531796fe7`。实际验收以含本记录的远端最终 HEAD 为准，状态 `CI_PENDING / VISUAL_PENDING / PRODUCTION_NOT_VERIFIED`。
- 起始 CI 最终 43 成功、7 失败。修复提交 `23e1797c2b2db41918a2f3a9636df3983562efaf`。素材 Schema 5/7 DDL、数据升级及版本号同事务，保留全库旧数据比较、注入中断和备份恢复断言，成功后额外验证新回执表。板端未领取恢复改读真实任务租约到期字段及进程身份。相关 Jobs 139706970567、139706994573、139706995054、139706971949、139706970779。训练创建 Job 139706970987 的测试生存期内预取真实算法目录，评测 Job 139708321093 验证当前入口和原评测身份。该 Job 的数据集选择改由键盘打开原控件，原写入及回执断言保留。
- 共用主题、侧栏和项目页头、Element Plus 控件、表单、表格与弹窗使用 [前端设计规范](../FRONTEND_DESIGN_SYSTEM.md)。AI 审核三栏、素材图库、算法卡片、人工标注、训练表单与报告已做定向视觉调整。入库进度仅以已核验结果显示。图像预览按原比例显示，编辑器、GT、选择冻结和任务权威沿用。
- 本轮视觉优先，业务覆盖维持 [14 菜单矩阵](VUE_M0_FUNCTION_API_MATRIX_20261118.md) 的 2 完整、12 部分。未扩展可选功能。继续暂缓算法/资源生命周期、凭据轮换与撤销、已领取硬件及转换恢复、PostgreSQL、Smart Audit 规模重构、参考图推理及真实部署。
- 本机 Vue 类型、Vue SFC/CSS/JS/TS、Python AST 与 Git 差异检查通过。运行期留给现有 CI。截图采集复用审核、素材、算法、人工标注和训练用例，当前 SHA 尚未人工确认渲染结果。下一轮先核对实际 CI 与三档桌面截图。默认入口、VERSION 42.24.592、AGENTS、四份保护文档及 vendor 已保留。

## 大规模素材治理、后台消歧与原任务回执（2026-11-26，上一批）

- 畅联云算法训练平台采用 FastAPI 模块化单体、SQLite 权威及独立 Vue `/app/`。工作目录 `D:\lab\p2b2-backend`，分支 `feature/external-algorithm-publishing`。起始本地及远端 `c942abc864923504b6083a692b8d5ebfcd2fec77`。代码候选 `75e41e0d3fea764ca16ba55ab370ddf1746dda6c`，含交接记录的最终 HEAD 为其后的文档提交，实际 PR 和 push 工作流以远端最终 HEAD 的一次性快照为准。验收状态 `CI_PENDING / UAT_PENDING / PRODUCTION_NOT_VERIFIED`。
- 基线最终 PR 21 成功 / 1 失败，push 26 成功 / 2 失败。AI Annotation Recovery 的 push run 45755428664、Job 139692828963 为 213 通过 / 1 失败。OpenAPI 守卫补入已有的可选 `confirmed_drafts`、50,000 条上限、项模型及非必填证据，保留原断言，提交 `530e7e1498de62538e47a050683cc8e31a54b5a8`。Frontend Runtime Stabilization 的 push run 45755428783、Job 139694443335 在 Node 合同阶段为 1,838 通过 / 7 失败，测试用 data URI 无法解析新增的训练迭代相对导入。测试装载器改用真实模块及原请求替身，提交 `82858af5920bccfec7928b607a9b47296a15bd28`。
- A `76a348572e09ac94fc5776e18d88b7f8ffb42d72`。数据集保留单归属，移出专用数据集回到默认归属。用途仍为原未分配、训练、验证、评测。两项共用 v62 MaterialBatch、现有数据集锁与 MaterialRepository，支持显式跨页和筛选全选后有界排除。服务端按操作者及请求冻结范围、目标修订及素材证据。每批最多 500 张，素材字段变更与回执同库事务，Worker 续跑从原回执对账。Vue 停用旧逐图 PATCH 和同步用途入口，提供预检、刷新回执、取消、续跑及结果分页，局部刷新当前素材页。已冻结训练快照保持原 Owner。
- B `c6b54871b5688662e2d39c249035660addf5a8c3`，Windows 对照用例补充 `d62780620582a349c3811a4abb000d4f3c6979e9`。v60 单独创建后台预检和草稿保存两项现有 MaterialBatch Worker 任务，使用原审核快照、排除、CandidateStore、草稿 CAS、同操作者和源 SHA。保留旧 IoU/链式冲突/置信策略，并用原 JS 作 CI 对照。浏览器只读汇总、样例和任务身份。人工策略保存后，服务端读取成功回执并复核当前资格，交原 C2-B 预检和正式提交。自动草稿须人工复核。正式人工标注已经在 Vue 由现有 Annotorious 和 GT API 实现，视觉及真实规模仍待验。
- C1 `f2730be96c92c61e6db6765e0f570b3b2b5fda42`。困难样本使用有界素材游标和任务历史，排除冻结 Test ID 及相同 SHA，训练提交检查当前评测及决策，中央准备独立复核补数 Test 范围。C2 `55e6058032262ecd41fff25748d9215994c9ae19`。正式 Vue 素材入口复用算法级负池组件与原 v1 操作回执，公共 v2 支持跨页明确选择。原单操作 200 张上限和服务端训练资格保留。标签预设、重复冲突/Smart Audit 证据复核、深层报告和训练批量管理继续由现有入口承担。
- D2 `4fbb97f7ad94b9319889258f59e62ecedd886f2d`、`75e41e0d3fea764ca16ba55ab370ddf1746dda6c`。RKNN 首次验证绑定原请求、原版本、转换产物/样本 SHA、输入尺寸、精度、芯片和可调度板卡证据。远端文件准备在版本锁外，任务发布前重新进入原版本生命周期锁核对。Vue 刷新精确查询原任务，用户可明确选择原图后重放同一请求。只允许原任务在零领取情况下经版本生命周期锁恢复，通用 v61 retry 拒绝板端 Agent 任务。已领取板端任务和转换终态仍缺经原运行时验证的按 attempt 停止及资源释放重试合同。历史无版本的板端记录可读取原结果，新增身份化验证须有正式转换版本。
- D3 引用准入核对。首训和迭代经 `app.py::_enqueue_explicit_training` 进入 `_algorithm_version_reference_fence`，无版本时提前返回。训练准备/版本发布经 RemoteTrainingPreparer 及 AlgorithmRepository，转换和板端经 ConversionManagementService，外发经 ExternalPublicationRepository，反馈经 OnlineFeedbackRepository，负池经 v61/NegativePool。已有版本锁并未覆盖所有算法级写入和外部未知状态。整算法 DELETE 保持 409，包含空算法。下一步先统一算法级短时准入锁及引用登记，确认与版本锁的顺序后再验证空算法移除。历史算法退役仍待产品批准。
- E1 凭据源码清点。v35 模型配置保存 `secret_ref`，原 SecretStore 持有实际凭据。AnnotationRuntime 准备阶段把引用和 `inference_account_identity` 放入冻结配置，Worker 恢复及重试时按冻结引用解析和比对，缺失或变化拒绝。排队、执行、恢复和可重试历史都属于持有者。远程传输使用原存储凭据引用，独立于 AI 模型凭据。只有不可重试且无需执行的历史记录可进入无引用判定，当前缺统一持有者索引及跨任务发布窗口的删除证明。建议新凭据使用新引用并沿原 SecretStore 持有，旧引用按既定保留和撤销规则治理。保留期限、紧急撤销、原任务停止或恢复及冻结替换须另行确认，现有 v35 拒绝保留。
- E2 `c747450dd221c2084ff744bb705bb95b13dc4c0f`。视频和数值验证使用现有 Web Crypto 或同包离线锁版 SHA‑256 实现，视频按 4 MiB 读取，保留原 request ID 与服务端真实字节核验。无摘要历史请求仍只能查回执。F5 `0ea4e2a4db151296d495017814f404e9ecfb9211` 增加畅联云权重详情、标签分页补读、int64 字符串核对及证据复制。F2 `c5fce17a4b6e374a58e09162ffbeebc847aa29b4` 增加显式本机批量检测。原资源删除未证明活跃转换、历史重试与 SecretStore 引用保护，本轮保留原入口。其他剩余菜单见 [功能矩阵](VUE_M0_FUNCTION_API_MATRIX_20261118.md)。
- 本机只执行 Vue 类型核验、受影响文件语法和 Git 差异检查。未执行应用、浏览器、运行期测试或大型构建。20 万素材、2 万级批选择、真实板端、现场离线、三档视觉及生产尚未验证。VERSION 42.24.592、AGENTS、四份保护文档及 vendor 保留。下一批优先按准确 SHA 的真实失败收口，再接入原 Smart Audit 审核与大库边界、转换终态安全恢复及算法/资源生命周期。

## 训练来源、正式入库、交付与关键回执（2026-11-26，上一批）

- 畅联云算法训练平台，FastAPI 模块化单体、SQLite 权威、独立 Vue `/app/`。唯一目录 `D:\lab\p2b2-backend`，唯一分支 `feature/external-algorithm-publishing`，起始本地及远端 `9989e3ebf07144b5f8f7b3383e60397018c66e90`。代码候选 `1cd6323069a5070efeb85ea91f462fc8346f09d5`，含本记录的最终 HEAD 为其后的交接提交。推送后一次性查询准确 SHA，当前 `CI_PENDING / UAT_PENDING / PRODUCTION_NOT_VERIFIED`。
- A `18bd3113c951552eab1ea9cadcce4404d165efc3`。基线 22 个 PR 已成功，Node Agent Executor 双槽通过。28 个 push 中 27 成功，前端 run 45752895038 的 frontend Job 139686422893 唯一失败，80 通过、1 超时。失败制品 15086782881 确认强制点击已创建并完成 29 张入库，竞争的首个 locator 仍等待消失的按钮。先等实际确认按钮稳定，再对同一按钮触发两次事件，原封存排除、唯一创建、待核验进度、29 张入库与下一笔新身份断言保留。
- B `8bb6e15735725d73f4a172485ff57ee0729099c0`。NativeEvaluation 的困难样本与继续训练接入 v12 分段评测真值、原决策确认、v64 限额非 Test 矿选、v60 任务和人工审核、v12 已审核采纳、v63 补数冻结。发起和重放按原模型、素材摘要及请求核验。正式 GT 与样本角色由原 CandidateStore、AnnotationRepository、OnlineFeedbackRepository 证明。TrainingCreate 子流程在提交前重新读取源动作和当前版本，传入原继续训练动作及固定任务 ID，或显式选中的原候选集；可用的原版本固定 Test 基准保留。原默认设置沿用。历史素材入训仍受原资格与冻结拒绝。困难样本多任务历史、报告深层归因及训练批量管理仍有旧入口。
- C `729ea6910c15b66bf2a7ff4f6f72c11f7f311e70`。IoU 页按原算法有界预览，图框逐页读取，继续以 25 张一批保存候选草稿。人工指定标签并再次确认后，根据相同操作者、草稿修订和素材 SHA 精确冻结：仅已证明保存且合格的草稿交 C2-B 原封存与后台执行。保留实际确认、正式 GT 屏障、已入库排除、进度、取消和恢复。自动策略只保存候选草稿。C 的素材 `286343ce5ccfc4372f997c82e2d14fe75ecab935` 沿用 v12 数据集锁，支持最多 100 个显式跨页成员移入目标或移回默认数据集，首个失败或不确定请求后停发并读取当前素材核验。现有 v62 没有数据集批量操作或该用途的筛选排除合同，大范围需先补原冻结与回执；分类、算法级负池、标签预设及 Smart Audit 仍走原流程。
- D/E `e443d9e3bfa03b989a2fdad036af0b3a10d873bf`。ConversionDetail 接入原 v39 RK3568/RK3576 手动验证，按原板卡调度与 v62 任务投影查看状态，恢复已知任务 ID，按原报告显示板卡、模型、样本摘要与执行代数，并提供原 JSON 下载。归档下载、数值验证、硬件、正式发布独立分层。ConversionManagement 没有冻结的原转换终态重试 API；v61 通用硬件 retry 缺与版本生命周期共用的 fence，原生入口未开启。首次板端 POST 无稳定请求 ID，响应丢失保留待核验。ExternalPublish 接通 v64 用户确认发布及原规则许可的失败重试，查版本持久记录；权重选取继续由后端自动选择。PlatformIntegration 接通 v63 显式连接测试、联调诊断、手动同步与原操作查询。映射写入、实际对账和发布回退仍由原入口。
- E 数值验证在原请求中绑定顺序化样本 SHA256 和阈值，原回执缺失时允许用户在支持 Web Crypto 的浏览器按原图片内容及顺序重试，原 ID 不变，无自动重发。服务端保留原转换冻结与孤立目录保护。视频 `1cd6323069a5070efeb85ea91f462fc8346f09d5` 基于 v33/ArtifactStore/TaskRepository 识别在途、未登记、暂存、已受理、终态和退役；先写原冻结参数后发布文件，重放核对已发布 SHA。浏览器只持久保存参数与摘要，旧无摘要标记、历史无参数孤立文件或无 Web Crypto 时不能验证刷新重选，仍可查原回执或由原 Owner 核查。
- E 凭据 `36c92ae7bbe1624d9c0ec7e8f84fcf26fe679bfa`。原 v35 PUT/DELETE 对既有 secret_ref 保守拒绝原地换密或删凭据，配置可停用，给新任务的新凭据由新配置与原 SecretStore 持有。冻结 Worker 仍比对 inference_account_identity。现有接口没有覆盖排队、恢复及历史重试的可信引用清点，原地换密和清除策略、显式紧急撤销需独立产品与安全决策。整算法仍为 409，无基版本首训在 app.py 的原 `_algorithm_version_reference_fence` 分支未锁住算法级身份，仍缺跨任务、绑定、转换、外部、反馈和负池的共享生命周期。
- [14 菜单矩阵](VUE_M0_FUNCTION_API_MATRIX_20261118.md) 维持 1 完整、13 部分。五个试用入口与原 14 菜单不变。本机仅 Vue 类型、Python AST、JS/TS 用例语法及 Git 差异检查。新 SHA 需要运行期 CI，三档视觉、20 万素材、2 万冻结选择、离线部署和生产硬件均待验。VERSION、AGENTS、四份保护文档和 vendor 未改。下一阶段优先补真正的有界批量治理、标签 Smart Audit、原任务重试的版本保护、外部对账与配置安全引用清点。

## 五菜单原生预览及关键写入回执（2026-11-26，上一批）

- 畅联云算法训练平台使用 FastAPI 模块化单体、既有 SQLite 持久化权威及独立 Vue `/app/`。唯一路径 `D:\lab\p2b2-backend`，分支 `feature/external-algorithm-publishing`。本地与远端起始 `7954e1b3b8f4e381b29b0fa78c141ea42bbcad82`。代码候选 `4b932ccd0913dbf670b9a26f83eb800f55ad4e2a`，最终 HEAD 是代码候选之后的本交接提交。推送后一次性查询含本记录的实际远端 SHA。当前状态 `CI_PENDING / UAT_PENDING / PRODUCTION_NOT_VERIFIED`。
- A `c612fdc2da6fb0b9dde062d1ea543b7d1e8f7d41`。开工准确基线 21/22 PR 成功，push 27 成功、前端运行中。随后基线前端 run 45750211962 的 6 个 Job 全成功，前批 Annotorious 已有框、真实绘制、正式保存及切换和清洗的修复随该回归关闭。其余已知失败为 Node Agent Executor Ubuntu 139675913253，1 失败、1076 通过、5 跳过。实际失败在双槽两份停止证明落库后第三任务未获分配；老诊断引用不存在的字段。修正诊断列，并对测试 GPU 快照可能被真实 Agent 心跳覆盖的窗口做有界重采样，保留实际中央分配、GPU、Hold 和停止证明断言。等待新 SHA 复验。
- B `4684707c0ebacc1669b3dc73bb9dadb401047129`。五个菜单都有实质性原生操作，通过原菜单的明确试用链接进入，原完整入口保留。质量中心使用 v53 摘要、有界 v61 素材列表、v44 显式检查当前批明示 ID、离线 ECharts、v62 训练报告导航。原全局检查涉及全量读取，场景实测和高级评测仍走原流程。模型转换环境读 v39 缓存，以原共享检测读取和显式启动，编辑资源并管理厂商/芯片版本化字典。批量本机检测及资源删除保留原流程。
- B 的 AI 辅助配置经 v35/原 SecretStore 管理模型、新增编辑、启停、默认设置、Prompt CRUD 及预览，原接口主动测试与样本验证保留。已知 API Key 在原诊断输出和失败证据中脱敏。冻结任务仍持有原 secret_ref，跨任务引用保护与清除、删除留原流程或后续安全设计。存储管理保留 v61 配置、真实凭据与扫描 Owner，提供存储源创建、安全编辑、连接试验、项目引用、生命周期与最近审计读取，以及中央/Agent 扫描、终止、结果及纯图片确认。路径身份修改、删除、导入、归档写入及标注扫描确认由旧流程承担。
- B 的畅联云数据沿原 v63 provider 合同，只在用户点读取后取产品、按选中的产品取版本、按版本取权重，详情保留 int64、来源、SHA 和直接下载。同步设置与操作留平台对接原权威，旧 data 页的标签分页兜底、原始对账与复制细项留原流程。五个菜单确有功能缺口，整体开发分类 1 项 `NATIVE_COMPLETE`、13 项 `NATIVE_PARTIAL`，仍存在旧正式入口。见 [14 菜单矩阵](VUE_M0_FUNCTION_API_MATRIX_20261118.md)。
- C 整算法删除继续返回 409。缺口在 app.py 的训练准备发布（`_algorithm_version_reference_fence` 调用约 L7055）与 AlgorithmCatalogService 同名实现中，空基版本不锁定算法，且版本提交、转换、外部发布、反馈、负池属于不同写入权威。恢复空算法删除以前，需将同项目算法的新增引用入口统一纳入共同的跨进程生命周期保护，事务内重新核验所有已登记引用与真实外部权威状态，并保证失败恢复。没有安全证明前保留拒绝。有历史算法的停用、归档或退役操作仍待产品确认。本批沿用原版本操作历史、CAS 与产物清理。D 只补质量中心进入已有报告再返回的路径，困难样本、补数及带来源继续训练留下一阶段。
- E `5fd6bb98e338f16bc2b827283a829d5a7e8277f9`。数值验证按当前操作者、项目与转换任务保存会话级原请求 ID 与可算出的验证 ID，刷新或重开工作台先 GET 原持久任务。受限浏览器由新增 v39 by-request 按原映射核验。图片仅在当前表单内存中，查不到回执仍待核验，刷新不发起 POST。转换恢复、硬件验证、正式交付写入与外部发布回退仍有原入口。
- G `4b932ccd0913dbf670b9a26f83eb800f55ad4e2a`。v33 视频上传新增可选 request_id，服务端用认证提供方/操作者、项目及请求导出稳定任务 ID。输入先暂存，再在原 ArtifactStore 下跨进程锁内发布完整视频及参数到原 TaskRepository；相同请求以实际 SHA、大小和原采样参数确认重放，身份漂移拒绝。Vue 刷新 GET 精确回执，列表缺失不解除锁；已知同样的提交只允许在原视频尚在内存时显式按同一请求重试。旧客户端无 request_id 仍使用原合同，原 VIDEO_FRAMES Worker 保持。历史待核标记若无请求 ID，只能人工核对，无法追溯成精确回执。
- F 本批沿用既有清洗排除、正式 GT、AI 审核和标签审计。下一批重点是冻结困难样本到带来源训练、审核入库和标签 Smart Audit、转换恢复与交付证据，以及五个菜单的旧操作补齐。算法安全退役、默认入口及旧系统退役分别受安全或产品决策约束。
- 本机 Vue 类型、Python AST、TS 用例静态解析及 Git 差异检查通过。新增/扩展第二阶段测试包含上传内容/参数冲突、视频与数值页面刷新只读回执、AI 诊断凭据及畅联云主动读取。未执行本地运行期、浏览器或服务。三档视觉、真实 20 万素材及 2 万选择、离线部署和生产硬件待验。VERSION、AGENTS、四份保护文档和 vendor 均保留。

## 算法删除保护、核心闭环及菜单迁移（2026-11-26，上一批）

- 畅联云算法训练平台采用 FastAPI 模块化单体、现有 SQLite 数据权威及独立 Vue `/app/`。工作目录 `D:\lab\p2b2-backend`，唯一分支 `feature/external-algorithm-publishing`，初始本地与远端 `5aa1c4e624cd8d50e84ff4a5a698e7eb68f7600c`。代码候选 `77035375bac317eadb39d8c18449a471c375ccd0`。含本记录的最终 HEAD 为该候选之后的交接提交，推送后按远端实际 SHA 单独查询。当前记录状态 `CI_PENDING / UAT_PENDING / PRODUCTION_NOT_VERIFIED`。
- A 基线准确 CI 为 22 项 PR 成功，push 5 成功、1 失败。Frontend Runtime Stabilization run 45746361114 / job 139663396266 为 74 通过、2 失败。制品 15084255152 显示正式框 `existing` 已出现在 32×32 图中，实际失败发生于新拖动恰在 Annotorious 快速画框面积阈值。调整真实画框手势并保留原框、尺寸、切图、正式保存断言（`99df0f5b7c612f38853e3605f057b3bacb98f4de`）。清洗改用有名称的范围选择器宿主，原组合框输入被 Element Plus 占位覆盖；附入 F 提交，原范围断言保留。ZIP、启动快照和 Benchmark 既有整改沿用。
- B/C `be306c18e19e14bf8b82639204cc3dc221f6301f`。原 DELETE 与 Vue 预检统一由 AlgorithmCatalogService 判定。对外部主数据保留原只读错误；对本地算法有版本或操作历史时明确拒绝，无明显历史时也拒绝。首训无基版本时原 version fence 空放行，未覆盖算法级任务准备、历史、负池、反馈、转换、发布及线上关系的并发准入。恢复删除须先建立共同生命周期边界并证明引用检查与退役原子一致。版本操作从原 AlgorithmRepository 持久回执读取，按原 operation_id 显式重试清理。算法卡片接入原 v49 轻量报告，区分当前版本、最新创建、近期有证据的最高 Test 版本；深层历史、标签与血缘报告保留旧入口。
- C/D `eb99eb4a0e495bd8825c39e0eae3f98122475d45`。版本新旧字段取自原评测服务，冻结 Test 单图复核沿用原 POST，按同一评测、图像及 SHA 读取 OnlineFeedbackRepository 原持久回执。未知结果不自动重发，正式 GT、Test 和训练数据保持原业务权威。训练任务管理、创建和报告保留已有实现；困难样本挖掘/补数、诊断深链、批量管理和带来源继续训练仍由原流程。
- E `69f10ac3cda6448f1257b166ce7129195e3742b1`。ConversionDetail 接入原 v39 停止及 PT/PTH→ONNX 数值验证，批量文件和阈值走原 API。停止复核原任务状态，数值未知优先读原验证 ID，验证记录、硬件验收与交付资格独立。转换恢复、硬件验证、发布确认/回退及外部同步保留对应原入口。
- A/F `99ba156a959105dd9ee371b571257268542809f0`。NativeCleaning 在按筛选跨页全选后允许有界排除 500 个图像 ID，原 v47 按库修订预检，原 v62 MaterialBatch 真正冻结同一范围。远程资源可用性只计算纳入范围，冻结前拒绝素材代际漂移。初始建议剔除 ID 仍随建议数增长。素材批量分类/目录成员、算法负池、C2-B 消歧后正式入库、标签预设及 Smart Audit 仍走原流程；AI 参考图实际入模继续留待原 Provider 能力。
- G `77035375bac317eadb39d8c18449a471c375ccd0`。视频切帧的三种采样、上传、列表、详情及停止进入 Vue，仍由 v33 和原 VIDEO_FRAMES worker 执行，响应以项目及任务身份核对。原 v33 没有按请求回执，结果未知时保留同操作者标签页标记，先查实际任务。总览接入 v53 核心快照与有界近期训练、标注，历史趋势及资源诊断保留原入口。当前 [14 菜单矩阵](VUE_M0_FUNCTION_API_MATRIX_20261118.md) 为 1 原生完整、8 部分、5 旧交接。
- Python AST、JS/TS 语法、Vue 类型与 Git 差异检查通过。实际运行由准确 SHA 的 PR 和 push 工作流验证。未在本机启动应用或运行浏览器。未验证三档视觉、真实 20 万素材/2 万选择、离线安装或生产硬件。VERSION 42.24.592、AGENTS、四份保护文档及离线 vendor 保持原样。下一步按最终 SHA 核对浏览器制品和失败 Job，再接续困难样本、交付写入、素材/标签剩余操作及 5 个旧菜单。整算法恢复删除、默认入口切换及旧系统退役需各自满足原安全及产品条件。

## 数据治理收口与版本、评测、转换（2026-11-26，上一批）

- 畅联云算法训练平台。FastAPI 模块化单体、既有 SQLite 权威及独立 Vue `/app/`。目录 `D:\lab\p2b2-backend`，唯一分支 `feature/external-algorithm-publishing`。起始本地、远端 `c299d0a056439b9874f51f46f67cffaec5519714`。代码候选 `414d0186cf9ff16b10361869927675f768e83c84`，含文档的最终 HEAD 另核。
- 起始准确 CI 为 22 项 PR 成功、15 项 push 中 14 成功、1 失败。前端 run 45742042032 已复验 ZIP 守卫及启动快照（浏览器分片 3），关闭这两条旧问题。新失败为 139650046750 的 AI 选择框遮挡、Web Locks 选项互斥、Annotorious 辅助图形被误计，以及 139650046973 上传成功后两端选区键不一致。A `0534762eca94b2f83ffd3d5e868823ee613ce49e` 修复选区键和浏览器定位，B 修复互斥。最终候选运行期复验待 CI。
- B/C `b0379740f5c0594621b605fa059e12c53dd1cc13`：AiCreate 明示参考素材只记录，通用与 WeVisOne 当前均没有参考图入模冻结合同。NativeReviewTransfer 读取 v60 同操作者服务端历史、逐项回执，已确认的部分结果可结束本地恢复而保留历史；明确素材或 GT 身份冲突与可重试失败分开。回执文件和 CandidateStore 仍是唯一权威。NativeReviewAmbiguity 预检只保留 ID、草稿版本和素材 SHA，按原冻结顺序逐页重读，最多 100 张框数据在本页、25 张一批用原 CAS 保存，正式入库继续走原屏障。
- 同一 B/C 候选在 NativeCleaning 接通原 SQLite 结果分页、问题筛选和按需标注审计。旧 v47 默认响应保持。首批仅额外读取建议剔除 ID，长度仍随建议数增长。清洗删除登记前及确认其余素材时核对原 DELETE_INDEX 计划、准确成员、清洗结果素材 SHA；呈现登记、已删及失败数，清洗确认不标记排除项。Materials 的数据集目录按现有元数据读取，避免全库统计，单张成员变更走原数据集锁与读取核对。
- D `9211e56ca83d9a9db3522ce933aaa7aa9ebf0b95`：算法卡片/版本列表接通历史版本删除、删除当前版本并回退、未知记录核验、未完成产物清理重试以及授权下载。原版本服务提供引用检查和 `expected_current_version_id`。整算法删除尚缺训练、任务及版本引用保护；训练溯源深层视图及算法级报告仍有旧入口。
- E `41f9230728f1112115ad7d40efe70d54bcb52445`：独立 Test 样本按原评测 ID、图片 ID、SHA 和尺寸读取，复用几何适配只读对比 GT 与预测，缺失历史证据保留提示。F `414d0186cf9ff16b10361869927675f768e83c84`：ConversionDetail 显示冻结源身份和按需读取最近 20 条原数值验证。验证、硬件与交付各呈现原证据，转换任务写操作及发布继续原流程。
- [14 菜单矩阵](VUE_M0_FUNCTION_API_MATRIX_20261118.md) 维持 7 项 NATIVE_PARTIAL、7 项 LEGACY_BRIDGE。下一批先核对准确最终 SHA 的浏览器证据，再在 CLEAN 原 TaskRuntime 设计冻结排除，补素材批量分类/成员、算法级负池、标签预设和 Smart Audit。批量消歧后正式入库需要原 C2-B 人工确认合同；整算法删除先补服务端引用保护。继续训练、困难样本补数、转换恢复和交付写入分阶段接入原 Owner。
- 本机 Python AST、JS/TS 语法、Vue 类型和差异检查通过。增量合同覆盖转池部分回执、清洗删除成员错绑、回退 CAS、冻结评测框和转换历史错绑。最终候选标记 `CI_PENDING / UAT_PENDING / PRODUCTION_NOT_VERIFIED`。无运行期本地执行，真实性能、三档渲染、离线安装、生产及硬件待验。VERSION 42.24.592、AGENTS、保护文档和 vendor 保留；默认入口切换及旧系统退役继续由产品确认。

## AI 审核、清洗及数据治理（2026-11-26）

- 畅联云算法训练平台，FastAPI 模块化单体、既有 SQLite 数据 Owner、独立 Vue 3 应用 `/app/`。工作目录 `D:\lab\p2b2-backend`，唯一分支 `feature/external-algorithm-publishing`。本轮起始本地及远端 `a05c2a905eeccedf66e40016803fb009ad1b801b`，代码候选 `559499596c9b2df481e22cba31299d2e4fb85e7f`。含本记录的最终 HEAD 单独核验。
- 基线开工快照 22 项 PR（18 成功、4 运行）及前端 push 运行中。定向取得前端 run 45738702659 的失败 Job。139638190368 的 ZIP 静态守卫依赖字段旧顺序，已改为核对实际声明。139638190429 的启动用例在缓存交互已就绪时读取尚未完成的后台请求，已等到核心快照性能条目再核对唯一请求，另保留交互耗时。修复 `1baa6d5aed7b25c6e29b4aec4173943dcf8a5ddc`。浏览器分片 1、2 通过，分片 3 待新 SHA 复验。上一轮正式画框及标签统一复验继续以对应 Vue 制品为准。
- `8fce8f623b366d15c8848e104d693407be3bb55e` 接通 AI 创建与单图试跑的参考图 ID、覆盖策略及现有脱敏模型配置。素材库从原选区传入同项目、同操作者的路由状态，URL 仅记录进入方式。跨新旧页回执继续读原请求 GET，未知结果不自动重发；支持 Web Locks 时更新跨标签页记录串行。旧记录没有操作者字段，仍可按原项目及请求恢复。推理适配器仍只把目标图传给模型，多图参考真实推理待单独支持。
- `ff6bf7b72264b71dd513579df4242c32a7e9c8f1` 在原三栏接通 v60 转池预检、执行、有界回执和撤销。绑定 Task、actor、review_revision、选择冻结、手动排除和原 request_id；预检仅新增服务端冲突原因汇总。读证据后可按原请求续批，撤销仍由原负池与正式 GT 校验。支持 Web Locks 的环境保存该作用域最近一笔浏览器记录，其余环境保存至当前标签页会话。IoU 共享原冲突算法，v60 每批最多 25 张保存候选草稿，需逐图审核。原批量消歧后直接正式入库入口仍由旧工作台承担。高级单图对比复用原 Annotorious 试跑、临时人工基准、v60 compare 与 JSON 导出。
- `0fc3600fe3397460d19d4d4fb37afccc9f7879cb` 接通原 v47 清洗范围预检、创建、任务进度、诊断、停止、重试、图像结果审核与标注审计。选中剔除先按 v62 DELETE_INDEX 完成原预检和任务登记，然后 v47 确认只向 `skip_image_ids` 传入原范围。未知创建使用任务列表核查，选中删除按原计划 ID 恢复。CLEAN 采用原规则扫描配置，当前规范筛选请求支持按条件在创建时冻结，未提供筛选全选后的排除引用；旧 v47 图片结果响应仍整批返回，Vue 分页为展示分页。
- `559499596c9b2df481e22cba31299d2e4fb85e7f` 接通素材已选用途调整（v20）与免清洗（v62 MARK_CLEAN_SKIPPED），后者按预检库版本冻结已选或当前支持的筛选范围。LabelAudit 接通原 v54 标签完整性诊断、历史样例、映射及投影修复，并用 v62 读取状态、日志和重试。标签历史快照用于确认影响，实际正式 GT 变更由 AnnotationRepository 与原服务重新核验。
- 三个菜单仍为 `NATIVE_PARTIAL`。下一批优先用最终 SHA 的 PR、push 及 Vue 制品验证新合同。随后补齐筛选后排除、素材分类与数据集成员、算法负池细项、旧 IoU 正式批量操作与标签 Smart Audit 等剩余操作。完整功能和验证依据见 [迁移矩阵](VUE_M0_FUNCTION_API_MATRIX_20261118.md) 与 [功能保留台账](EXISTING_FEATURE_PRESERVATION.md)。
- 本机 Vue 类型、改动 JS 与用例语法、Python AST 及差异空白通过。新增隔离浏览器场景核对转池丢响应、原冻结及撤销，以及清洗删除计划与排除确认。此记录提交时新 SHA 尚待推送后一次性查询，标记 `CI_PENDING / UAT_PENDING / PRODUCTION_NOT_VERIFIED`。真实三档布局、性能、离线安装及生产仍待验。默认入口切换和旧系统退役需产品批准，VERSION 维持 42.24.592。

## 数据治理与 AI 创建接续（2026-11-26）

- 分支 `feature/external-algorithm-publishing`，目录 `D:\lab\p2b2-backend`。起始本地及远端 `b38104f98bf7e4ac78593b9bb68eed97eb901fdd`。首次准确快照 22 项 PR（20 成功、2 运行）、7 项 push（6 成功、前端运行）。随后单次定向取得前端 Job 139631497564 和制品 15079836704。构建及离线校验通过，浏览器 70 通过、2 失败。最终 HEAD 的运行和验收以推送后快照为准。
- 上一批历史 CI 遗留已验证关闭：Training Create First Open（Linux、Windows、真实 Chrome）、Material Annotation Atomicity、ZIP Import Durable Runtime、Remote Conversion Runtime push。Benchmark 的历史触发因果仍无独立证据，当前夹具复验通过。上一节列表保留作历史记录。
- 前端 Chrome 两项修复待复验：标签统一 fixture 点击 Element Plus 隐藏 input 超时，改用可见标签并保留选中/请求/取消断言（`49f5ba238dde8f0cbf9dc9417caededaa85eab35`）。人工标注制品明确报视口 scale 只读，按原 AI 编辑器复制冻结快照（`abecbcec4d91ac30f285e962b89beaa218697fcd`）。
- 人工标注候选 `abecbcec4d91ac30f285e962b89beaa218697fcd`。确认保存或只读核对成功后刷新服务端队列，当前离开筛选时优先定位仍符合条件的后继。越界用原 v61 响应定位有效页。队列减少到零时退出当前图片。项目及图片共同参与离开确认，减少重复返回按钮。素材库批删后的多页缩减复用同一有界读取，删除预检与回执继续由原任务服务负责。正式 GT 服务与 Annotorious vendor、几何适配保持。
- AI 创建候选 `f0bf343adb6a735a16e4a5d534e779833f30dfba`。复用 AiAnnotationCreate 三步布局及新增 Vue 原生控件，正常入口为 AI 任务列表、素材库 AI 预标注、已完成的 ZIP 批次。v35 脱敏模型、模板、正式标签；v61 48 条页；v60 冻结、身份成员、排除、服务端汇总、显式单图试跑、创建和原请求 GET。文件 `frontend/src/app/AiCreate.vue`、`frontend/src/api/ai-annotation-create.ts`、`frontend/src/composables/useAiCreateMaterials.ts`。原 localStorage 项目级回执键跨新旧页面共享，超时或 404 未明状态保持核验，不自动重发创建。同一表单保留普通失败配置，实际成功进入任务列表。原试跑叠加基准编辑/导出保留在旧入口，原生提供候选只读预览。冻结接口仅支持名称、标签及标注状态，额外来源或质量条件保留逐张/本页选择，确保全选范围与原服务端过滤一致。ZIP 模式由原报告认定未标注范围。候选不直接写 GT。
- Vue 类型、合同脚本语法、浏览器用例 TS 语法及 diff 静态验证通过。真实画框和页缩减复用 native-materials 用例。AI 创建用隔离 API 夹具覆盖 20001 张冻结、排除一张后的精确范围、主动试跑及刷新只读核对，GitHub 实际运行待验。三档渲染、离线产物及生产环境按准确 SHA 和现场证据验收。
- AI 审核维持现有三栏、候选草稿及 C2-B。优先下一批：从原 negative-transfer preview/receipt/undo 接通转池及恢复，AI IoU 批量操作、清洗、标签审计修复及素材批量用途仍有明确旧入口。14 菜单分类见现有功能矩阵。默认入口切换和正式退役继续依产品授权。

## 正式人工标注接续（2026-11-26）

- `D:\lab\p2b2-backend`，分支 `feature/external-algorithm-publishing`。起始本地及远端 `981922f81357ea39ca7e53c0ab4b8d4d1b32cabb`。基线独立验收提供 24 项（22 成功、2 失败）；历史 11bec617 为 50 项 42 成功、8 失败，83b489a5 为 30 项 24 成功、6 失败。触发不足的工作流不能仅凭后续 SHA 关闭。
- 正式人工标注候选 `7368dd46afc26de5c4a67fd7a39bfe8615b876c3`。素材库按钮、卡片与详情进原生工作台，原标注台保留明确回退。队列按同项目及继承筛选查询 48 张一页，支持名称/标注状态、逐图与跨页切换、保存并继续；返回保留进入前列表查询。工作台使用原 AnnotationEditor、Annotorious 3.9.5、几何适配和原 payload builder。正式 GT 读写用原 annotations endpoint，保留完整框和元数据。原图增加可选代际绑定，写前 flush、正式版本 CAS、实际审核范围、确认无目标、只读未知回执核验、冲突后需显式重新加载。数据权威是 AnnotationRepository。
- AI 候选候选码 `eafa898c3974888e70eed19cce37eb85dd1e4da8`。候选编辑的几何错误阻止新草稿提交，原持久请求仍可核验。AiReview 三栏、筛选/冻结、C2-B 与正式入库继续使用原 CandidateStore/服务。AI 创建、清洗及其余转池等流程未在本批迁移。标签审计修复及素材批量治理仍有旧交接，数据库和训练迁移本批未推进。
- 静态验证通过：修改 Python AST、JS/TS 语法、Vue 类型和 diff 检查。既有 Vue Chrome 用例改为真实离线 Annotorious 画框，核对原像素、已有隐藏框、保存响应丢失后只读回查、切图及卸载。接口 fixture 与实画行为分开，CI 另走原正式 GT 接口及媒体代际合同。视觉、完整移动/调整尺寸产品链、实机、生产待验。
- 最终含文档 HEAD 以本节所在提交及推送后准确 SHA 快照为准。下一轮先核对下表各 Job 和准确 SHA 前端制品，再处理标签审计及修复、AI 原生创建和审核剩余能力。原在线默认入口及退役决策仍需产品授权。

|未关闭验证项|已知失败 Job|实际根因 / 候选|
|---|---|---|
|Remote Conversion Runtime|139355141231|探测替身缺 force 参数，保留逐资源次数与 SDK 证据|
|Frontend Runtime Stabilization|139355271582|母模型原子替换守卫落在旧 app.py，改查 RuntimeCatalogService、路由委派、SHA 与原子替换|
|ZIP Import Durable Runtime / Material Annotation Atomicity|139350843668 / 139350844545|守卫按旧函数边界读源码，移到实际 worker，保留委派、冻结选择传递及无第二复制入口的断言|
|Training Create First Open|139350843575|未发提交 POST；源码确认延迟算法目录可覆盖一次性版本注入。夹具已对齐启动与刷新版本，历史因果待 Chrome 验证，失败时保留定向诊断、截图及 trace|

四组候选均见 `ef02e2e4cba3982f2b7a9e7338ba63dc1049a21e`。启动前仅有基线/历史结果，新候选未通过运行验收。未触发的相关 workflow 继续列为待验证。

## 第二阶段素材库增量（2026-11-26）

- 工作目录 `D:\lab\p2b2-backend`，唯一分支 `feature/external-algorithm-publishing`。起始本地与远端均为 `83b489a530513932ee3c9a3c3e9633e1d3edeb3f`。开工快照 21 项 PR、8 项 push，合计 18 排队、11 运行、0 完成，前端 push run 45655471943 排队。该快照没有可整改的失败 Job。
- A/C 候选 `68aca9a67663a218d80178e8d7a2f9f8ba25b892`。素材卡片可直接打开指定图片的原人工标注工作台，保留身份验证及返回查询。改名由原 v47 路由和 MaterialGovernanceService 写入，持有匹配素材 ID 的回执后局部更新。名称筛选打开时读取原分页重算集合，未知回执只读核对。修正末页全删后的越界请求。素材库菜单 `NATIVE_PARTIAL`，人工 GT 编辑仍由原工作台负责。
- B 候选 `534b249f241a27f4b40db4524c6ada096b05b732`。原 reader_view 先执行一遍 public_material 再覆盖结果，现只执行 reader 投影，有界页逐行省一次旧投影（标准 48 条满页省 48 次）。删除回执集合匹配从逐项线性查找改为 Set，处理已选 ID 的时间随集合大小线性增长。SQLite 分页仍同一快照计算精确总数、旧 API 数据形态及媒体权限保持。未测大规模真实延迟。
- D 先处理核心前端能力。保留算法 U1 原 Provider、Schema、迁移及隔离验证资产，正式清理和算法库读投影的切换门槛见 [U1 记录](T8_ALGORITHM_DOMAIN_PROVIDER_AND_CUTOVER_20261124.md) 与 [数据 Owner 清单](P2_DATA_OWNERS_AND_POSTGRESQL_PREPARATION_20261117.md)。素材与负池同库，正式 GT、候选、任务、产物、发布和配置仍由各原存储负责；下一数据库单元尚未实施。
- E 复核现有 Frontend Runtime 构建及制品链、verify_vue_app_offline.mjs、package_vue_offline.py 与 production_upgrade.py 的离线收录路径。本批组件随现有 Vite 构建纳入，安装/升级/回退与三档桌面渲染仍待证据。验收需先在独立 4070 环境核对素材、标注、AI 审核、训练资源和恢复、报告评测、转换发布及离线备份/回退，再安排生产验收。
- 本机 Python AST、TS 语法、Vue 类型与 diff 静态检查通过。API 原投影和浏览器改名丢响应的合同由现有 CI 执行，当前代码候选的验收为 `CI_PENDING / UAT_PENDING / PRODUCTION_NOT_VERIFIED`。最终含文档 HEAD 按本提交和远端分支核对，交付后只取一次准确 SHA CI 快照。
- 下一步核实准确 SHA 的失败 Job 和浏览器制品，随后完成正式人工标注的原生编辑、空标注确认和冲突闭环，或标签审计/修复独立单元。默认入口切换及旧前端退役仍为待产品确认项。

项目：畅联云算法训练平台；仓库 `jorsamj/aixunlianpingtai`；唯一分支 `feature/external-algorithm-publishing`。

## 当前接续摘要（2026-11-26，Vue 产品化增量）

- 目录 `D:\lab\p2b2-backend`；分支 `feature/external-algorithm-publishing`；FastAPI 模块化单体、既有 SQLite/Repository、同工程独立 Vue `/app/`；旧 `/` 保留。当前任务为后端准确 CI 收口与 Vue 全面产品化，历史阶段停止条款不限制本次明确授权。
- 起始代码 `11bec61774dd903f01729c82350170eac1512c7b`；CI 修复提交 `89d492f8eada11ff2df3344e5ad1ee63ce5cf1f4`。本批代码候选 `53f413cd7343763aaf0bfeb08a060e6af6417735`；后续三份记录提交只维护文档，含文档最终 HEAD 以本记录所在提交及远端 SHA 为准。整个 Vue 迁移仍 `IN_PROGRESS`，不得据旧结果标作验收通过。
- 基线完整快照含 48 个 PR/push workflow：37 SUCCESS、7 FAILURE、4 IN_PROGRESS。PR 包装器仅返回 22 项，不能代替 push 前端验收。失败来自 Remote Conversion、Training Create First Open、Release Regression、Algorithm SQL Store、Material Annotation Atomicity、ZIP Import（转换在 PR/push 各一条）。准确失败 Job 已读取，修复测试注入/守卫与独立 Job fixture 范围，未放宽生产合同。其余运行中结果本次未持续等待。
- 本批实现 `FUNCTIONAL_COMPLETE`：原生标签目录维护与后台统一标签两个关联单元（既有引用预检/正式 GT/MaterialBatch Owner）；源文件 `frontend/src/app/Labels.vue`、`frontend/src/components/LabelEditor.vue`、`frontend/src/components/LabelUnify.vue`、`frontend/src/api/label-management.ts`。原菜单名/顺序及素材库标签按钮位置保持，自动配色默认保留。原预设、标签审计/修复继续明确跳转旧 Owner，所以整个标签菜单为 `NATIVE_PARTIAL`。
- 静态验证：6 个 A 包修改 Python 文件 AST、两个 Node 守卫语法、Vue `vue-tsc --noEmit`、新增浏览器用例 TS 语法、`git diff --check` 通过。未执行本机测试、应用、浏览器或构建。新增3个 Playwright 合同覆盖目录CRUD/引用拒绝、精确来源/目标/取消/刷新恢复、未知创建及错误任务拒绝；复用现有 Vue CI，不新增 workflow。三档目录与统一面板截图由同 Job 产出，当前尚无本轮渲染证据。验收 `CI_PENDING / UAT_PENDING / PRODUCTION_NOT_VERIFIED`，不是 CI_PASS。
- 工作区保留四份用户未跟踪保护文档，未纳入提交；VERSION42.24.592、AGENTS 不改。无生产、GPU、数据、执行模式或数据库切换操作。
- 当前 CI 记录：上段为真实基线快照；新代码和含文档 HEAD 的准确 PR/push 状态在统一推送后仅取一次，交付消息报告具体最终 SHA，不持续等待。未取得结果前不能写 CI_PASS，当前无新候选运行验收结论。
- 下一阶段可直接执行：按最终 SHA 一次核查实际失败 Job（特别 Frontend Runtime 的类型/双构建/离线/浏览器及截图制品）；通过后取得本轮实际渲染证据，再推进标签审计/修复或完整人工标注/AI创建中的独立单元。前者仍旧 Owner，后者不得把旧 DOM/全局 app.js 借入 `/app/`。完整14菜单及具体未完成动作见[功能矩阵](VUE_M0_FUNCTION_API_MATRIX_20261118.md)，历史产品问题及状态见[保护台账](EXISTING_FEATURE_PRESERVATION.md)。本批不继续后端机械拆分，不重复执行恢复/资源调度/GT 专项。
- 产品确认：本批未改变菜单分组/名称、核心流程或删除能力，无新增待产品经理批准项；后续重大调整仍须明确确认。

以下为历史阶段证据和决策索引，不代表当前候选验收状态。

## 当前阶段与准确提交

D2B2-C2B-F1 已实现专用正式 GT 写入屏障与取消后只读对账。详细实现、隔离验证和自动续批接入条件见 [审核工作台](../AI_REVIEW_WORKBENCH_2026_11_06.md#d2b2-c2b-f1-正式-gt-写入屏障与取消对账)。F1 以 `54e35ddb32346e368125f96a886e125f7015cd92` 为基线，最终提交及 CI 状态见交付记录。


此前 M4-D1-D2A 已实现原生 AI 跨页选择与服务端冻结，功能与 CI 分开验收。M4-D0 的范围及故障恢复见[审核工作台](../AI_REVIEW_WORKBENCH_2026_11_06.md#m4-d0-审核数据恢复与操作范围)。M4-A1 基线 `a8aedf39f455630115511605f74b00dfa3f4fa94` 的 43 项 Actions 已通过。本轮验收以交付消息中准确 SHA 的 Actions 快照为准。

- M2 起点（已核对远端）：`4c7a6d1f31c275311156fb0ab1a7a5cd9d47d7f8`，保留 M1 的数字缓存键修复与未知写入刷新保护。
- M2-A：`280ed4cfb21f80e0980c03ace18aa70877a41706`，原 AlgorithmSqlStore 新增 opt-in 全局算法库只读投影及正式版本备注写入的轻量回执。
- M2-B/C 实现：`c83c114230873f57ae9d0f9a348ffc17f9cc4307`，完整 Vue 列表/版本 UI、备注编辑、受控操作入口及定向回归；最后仅补本入口、矩阵、功能保护与当前 AGENTS 阶段说明。
- M1 原 `65ae81372555786b78284a1bc62608703c1c40d6` 的 GPT 审计结果是50工作流48成功、2失败（Frontend Runtime Stabilization 44344576655、Material Upload Chunking 44344576624），不是验收通过；已在4c7a6d1f修复。该修复 SHA 的最终 CI 本轮未查询，不借旧结果验收新代码。

## 2026-11-21 状态摘要与正式审计文档入口

- 基线：分支 `feature/external-algorithm-publishing`，HEAD 与远端一致，均为 `1fa5119b84e8721e2dc4810903471a2e37b6e862`。该 SHA 的 **48 项 check-suite 已成功**；但这只代表该提交能通过现有 workflow，**不等于每项功能都有对应覆盖，也不等于已验收**。工作区当时不干净（8 个已修改 + 5 个未跟踪）。
- C2-B（冻结选择后的后台分批正式 GT 入库）为**本地未提交候选实现**：唯一执行任务、不可变绑定、执行/查询/取消 API、CPU Handler、100 张续批、取消对账、终态与进度均已写出，但未提交、未 CI、未验收。已确认缺陷/待定项：D1 取消对账 `completed_batches` 多算并漏报最后一批准入批；D2 `unproven` 无有界重试与阻断态；D3 QUEUED 取消语义待定；D4 重复测试函数；D5 final audit 与 publish 锁域/成功语义待确认（事实已确认，风险等级 `TBD`，未定为 P0）；D6 进度含推算值。异常来源与终态可达性仍需定向核验。详见[架构审计](PLATFORM_ARCHITECTURE_AUDIT_20261121.md)第 8 节。
- 20 万素材已有**隔离**证据（200k 元数据分页、稀疏 GT、20k/30k 冻结链路、任务只读批量队列位置），**生产性能与真实图片/GT/OSS 负载全部 `NOT VERIFIED`**。历史报告中部分 `p95_ms` 实为 7 次最大值，引用时须保留该口径。
- 当前无任何阶段为 `ACCEPTED`；Vue 原生化覆盖 8 条具名业务路由（复用 7 个页面组件），其余菜单仍进入原系统。数据库仍为 SQLite，无迁移授权、无迁移动作。
- 正式文档（本轮落库，待独立审阅）：
  [架构与性能深度审计](PLATFORM_ARCHITECTURE_AUDIT_20261121.md)、
  [20 万级素材性能验收规范](../performance/PLATFORM_SCALE_ACCEPTANCE_20261121.md)、
  [架构演进路线与阶段验收](PLATFORM_EVOLUTION_ROADMAP_20261121.md)。
- 下一步：A（C2-B 安全收口）优先，但**不阻塞 B（旧接口只读性能核验）**；C 以 B 的实测证据为前置，D 按各自业务链条件分别验收，E1（AI 批量 GT 的 Vue 入口）依赖 A，E2–E6 与 F 可按独立风险推进。除"正式 GT 写入依赖 A"这一安全前置外，不设统一串联门槛。

## 架构与唯一 Owner

业务目标是素材/GT、算法训练评测、转换交付、外部平台与算力管理。当前 FastAPI 模块化单体 + SQLite，各既有 Repository 拥有领域数据；ArtifactStore保存不可变证据；Scheduler/Worker、中央Assignment、Agent Execution Lease、Supervisor负责执行。新Vue只读写原同源Session/API，不取得执行权。

最终目标为完整独立 Vue 3 / TS / Vite / Router / Pinia / Element Plus，逐步退役旧前端；当前同一frontend工程保留库构建并新增独立 `/app/#/projects/{projectId}/algorithms`，原 `/` 仍可用。新应用不加载app.js、不调用window.setPage、不移入旧DOM表单。其他工作台暂以整页交给唯一原Owner，不能宣称原生迁移完成。

## M2 已完成及接口

- 算法卡片：名称/ID、来源、行业类型、说明、当前版本、版本数、训练状态/可训练性、成功训练次数、当前mAP50、更新时间、外部产品/品目/状态；点击展开/收起不重读列表，选中项不在筛选页时仍保留独立版本详情区。
- 搜索名称/ID；来源、行业、类型、训练状态、仅可训练、多级官方品目叶子选择；组合、标签移除、重置、分页；URL为当前条件，sessionStorage按项目保存重入条件，不跨项目混用。
- 综合/最近更新/训练次数/mAP50全局排序：新 `library_view=true&asset_view=true&summary_only=true` 的v12 GET在SQL过滤排序后LIMIT/OFFSET，新App显式请求10、服务端最大50；HTTP未带page_size仍保留v12原20默认。旧asset_view的status及原默认响应行为不改，新训练语义使用training_state，浏览器不拉全算法或全历史。
- 统计从 `_training_history_context` 一次读取既有历史上下文，`_successful_training_counts`保持成功/证据/去重口径，Durable状态覆盖旧job状态；综合用旧activeJob集合，训练筛选沿原provider集合。它们存在不同的原状态集合，未擅自合并。没有新统计存储/任务权威。
- 当前指标按精确current_version_id关联，不把最新创建版本当当前；保留原指标字段优先序、比例/百分数转换，缺失/布尔/非数值不伪造0，真实0保留。
- 普通详情复用原basic_only，外部主数据只读；补充产品/品目/分析ID、同步时间/摘要等只读字段；写后GET核验、局部更新。
- 历史版本分页、当前指针、训练任务关联、配置/指标/血缘与登记产物详情；版本只可编辑原API允许的remark，版本号不变。PUT新增asset_view=true只返回确认，原默认响应不改，再用身份验证的GET核对；备注返回业务原文，不把脱敏显示值写回。
- 新建/编辑/版本备注共用原按项目sessionStorage待核格式，版本操作增versionId与remark；写前记录，确认拒绝或GET一致才清除。未知结果跨刷新/重入阻止重复写；没有创建回执ID则人工核对ID后GET，不按名字猜测。仅覆盖本标签页会话，不提供跨设备/跨会话后端幂等。
- 原Owner整页动作：训练、算法/版本报告、已有独立评测、溯源、转换、授权下载、交付、算法/版本删除、回退。先GET核验项目/算法/版本，再进入原确认；回退仍由原Owner提交expected_current_version_id并执行引用保护。外部算法删除/主数据编辑禁用；版本退役限制准确保留EXTERNAL + CHANG_LIAN，未扩大到其他提供方。交付待清理状态拦截，下载标记仅代表原stored_path记录，真实文件由下载API核验。
- 外部同步去原“平台对接”页，不自动触发同步。旧页保留“返回新版算法库”，刷新不重放交接动作。旧canonical项目限制不变，不伪造项目切换。

## 必要验证与 CI

本地 Node24.21.0 / Python3.12 / Chrome：

- `python -m pytest tests/api/test_model_asset_views.py -q`：初始5项通过；新增备注用例后仅`-k library`3项通过、3项未选。后续只对补充只读字段/原文备注分别补测受影响项，均通过。覆盖25个算法全局分页/排序、当前与较新版本区分、品目/状态组合、一次历史读取、旧asset响应兼容、真实备注PUT/GET与版本身份不变；不调用全算法hydration。
- `node --test tests/frontend/vue-app-handoff.test.mjs`：23/23，覆盖真实函数分发、项目/版本身份、外部限制、回退目标、清理状态、下载及缺Owner失败。未实际删除训练/模型或调用外部发布。
- `node node_modules/@playwright/test/cli.js test tests/app-shell.spec.ts --grep "independent cards|unknown algorithm writes|library filters"`（frontend目录）：M1 CRUD及未知恢复2项通过；M2单项修正ElementPlus选中标签的定位后通过。最终M2单项5.0秒含启动，含无列表重读、精确参数、备注核验、刷新重置与外部禁用。未全量跑Playwright。
- `node frontend/node_modules/vue-tsc/bin/vue-tsc.js --noEmit -p frontend/tsconfig.json`；`npm run build --prefix frontend`（双构建）及后续受影响SPA构建：通过；旧30、新6资源闭包。原Node缓存键失败用例2/2通过；语法、Python编译与`git diff --check`通过。构建大chunk警告仍存在，不冒称首屏性能验收。
- 新最终SHA只查询一次现有Actions；未完成时CI_PENDING，不新增Workflow/Job、不手动重跑、不持续等待。正式官方制品下载、现场离线安装、生产/GPU及真实删除/回退/外部交付端到端本轮未验。

## 未完成、实际风险与下一步

|项目|影响/优先级|下一步与确认边界|
|---|---|---|
|训练/评测/转换/交付等仍LEGACY_BRIDGE|尚非全平台Vue原生，P1|GPT复核M2后建议M3完整训练创建/标签选材/全参数/准备取消/报告；先按矩阵定位，不重审全仓，不缩减模式或默认值|
|精确历史统计仍有历史规模成本|每请求一次既有历史上下文，不逐卡扫描；SQL卡片/版本输出有界，但全历史聚合不是固定成本，P2|若真实数据证明慢，后续专项设计正式Owner上的增量投影，不能用窗口估计或新计数真相替代|
|旧canonical项目限制|非canonical旧项目交接会明确拒绝，P2|保留原政策，改变项目策略先确认|
|初始共享JS约1.08MB未压缩|首次下载成本，尚无生产P95，P2|后续有实测再按需拆包，不本轮扩大性能架构|
|待核保护只在当前标签页会话内|无ID/记录改变时须人工核对|保持明确提示，不自动重发、不过期解除保护；后端幂等另行批准|

算法库列表/版本页面开发FUNCTIONAL_COMPLETE、验收CI_PENDING；其他业务域NOT_STARTED或原试点覆盖，均不冒称ACCEPTED。原 `/` 可回退，新SPA尚不接管默认入口。保留三份原未提交Payload设计、VERSION42.24.592及所有训练/GT/lease/attempt/fencing/CAS/不可变Payload/执行锚点/删除/发布安全；不操作A800/4070/生产，不强推/合并/Release，不自动开始M3。

实际协作：gpt-6.1-sol有界核对旧动作并实现受控交接、只读复核SQL；gpt-6.2-sol实现指定Vue/API类型文件。主模型决定语义/事务边界，独立审查实际Diff，修正外部限制、当前版本/只读详情/备注原文及待核行为，统一验证、Git和交付。

## 按需必读

- [功能/API迁移矩阵与历史阶段](VUE_M0_FUNCTION_API_MATRIX_20261118.md)
- [功能保留与差异](EXISTING_FEATURE_PRESERVATION.md)
- [整体技术架构/历史实施](../TECH_FOUNDATION_P2_20261117.md)
- [原前端Owner地图](../FRONTEND_OWNER_MAP_V42_25.md)
- [专业组件复用合同](../FRONTEND_THIRD_PARTY_REUSE_POLICY.md)
- [Payload协议与边界](P2B_4A_2B_CONTINUOUS_DELIVERY_20261118.md)

## M2 CI收尾 / M3-A开始（2026-11-19）

起点e51c30c9：GPT核查50工作流48成功2失败。A修复4个资源测试文件的历史缓存硬编码，改为实际index版本的数字格式、三资源一致性与顺序检查（定向17通过）；首次预加载修正bootstrap资源/推荐被误判实时缓存的新鲜度，指定hard refresh浏览器1通过（16.5秒含服务启动），hydration合同15通过。后者缓存复用用例先执行真实prewarm再断言后续零请求，未削弱预加载。无timeout/默认参数变更。A提交后立即开始M3-A，不等CI，未宣称CI成功。三份原设计及VERSION保留。

## M3-A 原生训练创建（2026-11-19 当前）

阶段SHA：A `3e8e229185c0cc802f1216e24aab243074dec14a`（缓存合同/首次预加载）与 `d635fd1f7cdbea3e741b6d7df10dc18bb24d65f2`（严格点分数字断言）均已先推送；然后实施B，代码 `07b98d236f8dc3b45856c945938e72f98d64e8d8`。最后仅更新接续文档/矩阵/保护台账与AGENTS阶段说明，最终HEAD为包含这些文档的提交，完整SHA和一次CI快照见交付消息。A/B的CI尚未本轮终验，不能继承其他SHA成功。

入口 `/app/#/projects/{projectId}/training/create?algorithm={id}`；可从原生算法卡片“训练”或“训练任务”桥接页的原生创建入口进入。不加载app.js/main.mjs、不移入旧表单DOM。新增src/app/TrainingCreate.vue、TrainingMaterials.vue、training-api.ts及类型声明；原views/TrainingCreate.vue和TrainingMaterialPicker.vue保留服务旧试点，不冒称它们已原生化。Task列表/执行/恢复/完整报告仍LEGACY_BRIDGE。

- 普通首次/当前版本迭代创建、分页搜索算法；四种训练模式、母模型、设备/资源/profile、优先级、精度、Epochs/imgsz/Batch/Workers、学习率与优化器、增强/早停/评测等全部原参数、自动转换选项和任务级robustness配置。版本与模型归属由正式API决定，迭代仍锁定当前版本/引擎编辑。
- 将旧baseCfg428原样提取为trainingConfigurationDefaults纯函数，旧表单通过原PlatformCore命名空间调用相同工厂；曾用git旧工厂与新返回对象严格比较，完全相同。复用既有createTrainingDraft、trainingInheritedDefaults、trainingModePreset、buildTrainingStartPayload、trainingDraftToRequest，未创造新训练默认值。缓存仅数字版本42.25.628，VERSION42.24.592不改。
- 素材v62服务端40条分页，图片lazy、标签/标注状态过滤，跨页Set选择，按项目+算法session草稿保存IDs/冻结引用/资源配置。显式选择沿API上限2000，冻结Train走selection-reference，22,015张例中只传引用；请求ID同范围重试保留，成员查询每批≤100；Test与训练范围重叠阻断。
- 选择确认与创建前复核五项revision；只取正式selection-summary正样本标签，未知GT/候选框不变成训练标签。Train/Val/Test原默认随机20/20及独立Test规则保持，切换模式复用canonical归一化；历史复用、可信固定Test基准和输入冻结交给原服务。
- 正式素材诊断、服务端RESOLVE_SELECTION+二次人工确认排除，复用removeResolvedTrainingMaterials保留原Train/Test范围、排除IDs和证据修订，不改素材库/GT；泄漏不以快捷排除掩盖。显式负样本预览/人工proof确认；冻结范围不误用仅支持显式IDs的负样本计划，必须明确同意后台核验；显式范围仍先检查硬GT/重复冲突。
- 正式POST `/api/v12/projects/{p}/train/start`，先生成并保存train_随机身份，最终预览后草稿变化使确认失效；正式准入后再写。回执 `training-create-pending:{p}` 存储失败不POST；明确拒绝清除，IN_PROGRESS/5xx/丢包/非法回执保留，刷新后只GET `/api/v62/projects/{p}/tasks/{t}?reader_view=true` 核验项目/任务/算法身份，不自动重发。后端TaskRepository/Worker/调度/freeze/Payload均未改。
- 成功后保留正式task_id并提供原训练任务入口。算法/项目切换会重建页面及取消读请求，提交回执按原项目保留。

验证命令与结果（本机隔离或HTTP夹具，不是生产训练）：

1. A四个资源合同测试文件：17通过；hydration合同15通过；指定 `tests/browser/training-create-first-open.spec.mjs --grep "hard refresh algorithm list prewarms"` 1通过，提取默认工厂后补测1通过（11.6秒含启动）。没有提高timeout或修改默认参数。
2. `node --test tests/frontend/native-training-create.test.mjs`：7通过，覆盖正式body/身份、刷新未知GET恢复、资源/草稿变化、22,015引用、存储失败、硬GT冲突、权限拒绝/IN_PROGRESS、审计排除及过期证据。
3. 原纯草稿/提交合同85通过；复用的training-material-summary-runtime仅排除/跨页相关5通过。未跑全部Node测试。
4. `python -m pytest tests/api/test_training_material_selection_summary_api.py -q -k "opt_in_selection_validation or summary_only_avoids or accepts_final_training_submit_payload or resolves_current_scope" --disable-warnings`：4通过，10未选；临时FastAPI/SQLite，不是真实GPU任务。
5. 原生Chrome `frontend/tests/native-training.spec.ts`：1通过（4.4秒含启动），跨两页选材、正式标签、完整默认body、最终确认、正式Task回执；断言不加载旧app.js/main.mjs。首次仅因ElementPlus隐藏input定位失败，改点其实际可见label并保留checked断言，未放宽等待。
6. Vue类型、双Vite构建（旧30、新8资源闭包）、JS语法、git diff --check通过。共享大chunk警告仍在，未声称首屏性能专项完成。没有全仓pytest/完整Playwright，也没有真实GPU训练、生产数据、A800或4070操作。

验收边界：普通原生创建/选择/配置/提交开发完成，CI_PENDING。固定基准、负样本和robustness手工子集已接入原合同，但未逐组合进行浏览器端到端穷举；等待CI和GPT复核。已确认评测决策带来源身份的继续训练/反馈补数入口仍在原评测Owner，不能把它们改造成无来源普通创建；全局robustness默认策略编辑仍保留在原完整训练表单，未新建全局配置Owner。本轮未迁移任务列表/执行恢复/完整报告，也未验证真实Worker训练结果。

下一阶段：先按最终SHA处理已知CI失败（若有）；GPT审计通过后M3-B只做训练任务列表、队列/状态/取消/日志与原Task读取合同，不重写执行器。M3-C再处理完整报告和评测决策入口。保留三份原未提交设计、唯一分支、VERSION、全部冻结/GT/lease/attempt/fencing安全，不自动扩展。

实际分工：gpt-6.1-sol做受影响测试、原生UI与素材控件；gpt-6.2-sol做有界API合同定位和适配器；主模型独立检查实际Diff、修正身份/缓存/回执/准入/快照与默认值边界、测试并统一Git。无代理推送/部署。

Task reader_view若因证据缺失/大小限制不能提供算法身份，原生回查保留待核状态，不把普通HTTP成功当作身份确认，也不自动重发；需在原任务工作台核对证据后专项处理。

## M3-A 冻结请求审计修复

基线 37ea27a95bb3319512edb7198824592d0d990ce0。TrainingMaterials 使用 getRandomValues、UUIDv4 版本位及 RFC4122 variant 位，保留同范围失败重试身份。明确清除选择后可开始下一次冻结。隔离 FastAPI 正式冻结与同请求回执复用、selection-summary 验证 1 项通过。Chrome 夹具验证标准 UUID、失败重试、刷新恢复和 22,015 张训练仅提交引用，1 项通过。训练参数、GT、角色隔离及未知任务 GET 合同沿已有实现。CI 异步验收。

## M3-B 原生训练任务

开始基线为 `37ea27a95bb3319512edb7198824592d0d990ce0`。M3-A 冻结整改单独推送 `f71aae79260052fc26cdf399cea49416076934a9`，随后交付 M3-B。最终精确 SHA 和一次 GitHub Actions 快照见交付消息，可用 `git rev-parse HEAD` 核对包含本段的提交。

- `/app/#/projects/{projectId}/training/tasks` 接管新 SPA 的“训练任务”，创建成功可直接打开相应任务。通过 URL 保存搜索、持久状态、类型、当前游标与详情。以 v62 Task reader_view 每页最多 20 条查询，详情不重读列表。TaskRepository 提供有效状态和进度，100% 不推断终态。准备与正式任务通过原有任务身份关联，项目/类型校验在现有只读路由内执行。
- 详情显示阶段、起止时间、资源键、等待原因、Worker、执行记录和失败信息。读取不可变 Payload 由原 SHA256 校验读取器完成，继续执行列表 32 KiB 与详情 512 KiB 上限。训练日志复用原日志 GET，只显示有界文本。准备任务经关联入口进入正式训练日志。列表、详情及日志手动刷新，复用读取取消机制，无额外轮询器。
- 停止与恢复属于 LEGACY_BRIDGE。整页交接核验项目、Task ID、类型及停机准入，再由原 stopTrain428 或 openTrainingRecoveryDetail 执行原确认、恢复门禁和回执。新页不将取消请求当作安全停止。暂停、继续、提权和历史记录管理保留在原完整任务页。报告仍由原工作台承担。
- 局部验证：冻结 API 1 项及 Chrome 1 项，任务读 API/不可变读取 2 项，交接 Node 24 项，原生任务 Chrome 1 项，Vue 类型与双构建、JS/Python 语法与 diff 检查。浏览器业务请求使用隔离夹具，未运行实际停止、恢复或 GPU 训练。
- 下一阶段 M3-C 在独立审计后迁移训练报告、指标与有来源评测决策入口。训练执行、GT、租约、调度、Payload 发布、数据库 Schema 与 VERSION 合同沿原 Owner。三份未提交设计文档继续保留。

- M3-A 的 GitHub Actions 快照为 22 成功、1 失败。前端失败来自三处旧数字缓存断言、Node 用例早于 Vue 依赖安装，以及旧训练弹窗的 1920×1080 滚轮用例。已补齐前三处断言的版本格式及一致性检查并调整原工作流安装顺序，定向 Node 18 项通过，YAML 解析通过。旧弹窗用例本地 1 项通过，CI 复现差异仍待最终 SHA 验证。

模型分工。GPT-6.1 Terra（Low）实现原生任务页初稿。GPT-6.2 Sol 负责 UUID 修复、读取与旧操作身份边界、整合、审查、定向验证及 Git。当前运行环境未提供 GPT-6 Luna。

## M3-C 原生训练报告与独立评测

- 任务列表、任务详情、历史版本及版本详情可打开报告。任务 ID 或算法与版本 ID 保存在正式路由，返回仅接受同项目的训练列表或算法库路由，保留 URL 筛选、版本页及详情身份。报告内容每次从 API 读取。
- v44 `report?reader_view=true` 保持 100 条历史一页，独立显示 Val、Test、最佳和最终 Epoch、实际参数、完成原因及质量告警。配置使用既有 SHA256 核验和 512 KiB 展示边界。无任务绑定的旧版本仅展示已保存的版本证据。现有离线 ECharts 在首次打开有数据的曲线区域时模块化加载，切页和离开时释放图表及观察器。
- v12 分段评测和对比使用原版本身份与可比性规则，类别、样本和对比每页 20 条。样本预览使用同源历史证据端点，同时核验冻结评测 ID、图片 ID 与 SHA256。缺少身份时明确标记记录限制。原工作台仍处理 GT/预测的交互叠加、深度诊断、继续训练、困难样本挖掘和反馈补数。交接在旧页面加载后复核已知评测 ID，原 Owner 继续维护决策、快照和回执。
- Windows Node Agent CI **UNRESOLVED**。运行 `44450248821` 的 Windows Job `135312124779` 日志为 860 passed、1 failed、7 skipped。失败断言只打印 FAILED，没有 `outcome.error` 或进程诊断。本机定向用例通过。该测试直接构造 deployment lease，走下载和校验，不调用 M3-B 改动的 `read_payload_version(max_bytes=…)`。新增原样断言失败时显示错误原因，待同类 Runner 给出证据。
- 本地验证为报告/评测投影与 API（含 Windows 单项）20 项、旧入口和静态合同 Node 28 项、Chrome 2 项，以及 SPA 类型检查、双构建、离线闭包、Python 编译和 Diff 检查。没有提交实际训练、评测或发布任务。CI 异步验收。
- 下一步先独立审计本批导航、冻结证据及旧操作边界，按新 SHA 判断 Windows 回归。如需迁移评测决策写操作，先核对原 decision、benchmark、candidate set 和回执合同。

### M3-C 独立审计整改

- 审计基线 `d822ec1f4e01a90bbbb841f1b24506069a25f1d5`。Windows PR Run `44457940238` 的合同 Job `135337448930` 报 `NoSuchProcess`。本地强制子进程在身份采样前退出，复现于 `launch_process()` 的 `psutil.Process(pid)`。Windows 现由 Popen 持有的原始进程句柄读取内核创建时间，POSIX 和后续 PID、创建时间、命令摘要三项核验沿用原逻辑。
- Frontend Run `44457931106` 的 Job `135337505431` 制品 `14499331406` 显示 POST 和读取均返回目标配置，失败画面仍在等待列表渲染。用例现在等待目标行出现，再清空内存缓存验证原编辑回退。模型配置业务代码保留。
- v44 报告将请求配置、实际执行参数和来源未标注的历史参数分别呈现，缺失显示未提供，0 保留。旧报告和评测工作台返回新版时恢复同项目算法筛选、分页与已核验的版本详情。交接动作仍由原 Owner 一次性消费。现有冻结图片端点的评测 ID、图片 ID、Snapshot 归属及内容摘要校验保留。
- 本轮完成定向本地验证。发布与验收以交付消息中的最终 SHA 和 Actions 快照为准。M3-C 待复审和 CI 验收，不启动 M4。

## M4-A1 原生素材库

- `/app/#/projects/{projectId}/materials` 接入“素材库”菜单，复用 MaterialLibrary、MaterialPreview、v61 分页和原标注详情。列表每页 48 张，使用缩略图和有界框预览，详情按需读取。使用记录沿用 v62 的只读 history 查询。
- URL 保存筛选、页码、布局及详情。浏览器会话按账号和项目保存显式选中的 ID，过滤或翻页保留选择，可逐项移除或清空。实际批量治理在原工作台确认范围。
- 图片上传、ZIP 数据集导入、人工标注、AI 预标注、清洗、负样本池、标签管理、批量治理和删除审核保留 `LEGACY_BRIDGE`。单素材标注进入前核对项目和素材身份。返回新版时恢复浏览 URL 与项目会话选择。
- 后续采用项目公共负样本池及分类，训练使用仍须核验目标标签、正式 GT、处理状态及人工确认凭证。历史算法关联表继续保留。ZIP 文件夹归集、标注映射、Train/Val/Test 的执行核验与训练负样本选材属于后续阶段。
- 本阶段功能为 `FUNCTIONAL_COMPLETE`，现场和生产验收另行核实。停止在 M4-A1，等待 GPT 独立复审。

### M4-A1 独立审计整改

- 基线 `e41db45e` 的 Actions 为 42 项成功、1 项失败。前端 Job 的 5 项失败来自启动快照新增的项目参数及其 `URLSearchParams` 依赖。原启动请求已恢复，服务端继续决定旧页当前项目。Job 在单元测试失败后跳过构建，制品上传随之失败。
- 旧工作台当前项目与请求项目不一致时，素材交接明确拒绝。当前交接只支持服务端已选中的项目。主动打开操作需要原入口就绪，缺失时提示错误并保留新版返回链接。
- 本地验证覆盖三个启动测试文件、素材交接、原生及试点素材浏览与离线构建。最终 CI 状态以交付消息的准确 SHA 为准。

## M4-B1 项目公共负样本池

- 素材库进入项目公共池，支持分页搜索、分类和审核状态筛选、入池、替换分类和移出。成员写入采用 `negative_pool.members.v2`，复用现有事务修订号和回执表，按项目与操作身份查询未知结果。原算法级 v1 及历史关联保留。
- 新训练选材的公共池过滤使用项目成员表和分类。算法仍用于训练标签、版本、历史策略与准入。一批待移出素材如仍有历史算法关联，事务拒绝整批，保留关联和成员。
- 原生训练草稿分别保存正负样本组。显式选择去重后交给原准入。有范围引用时，现有冻结服务校验来源后生成一个 Train 引用。负样本筛选冻结只纳入当前目标下已确认的负样本。原人工确认端点仍核验身份、证据和确认摘要，正式 GT 由原 Owner 维护。
- 独立 Test 可按公共池筛选，仍执行原准入。报告只对可核验且在读取边界内的冻结快照展示正负样本分布。隔离准备夹具验证角色计数、标签文件及原 GT，实际训练和生产待现场确认。
- 本地定向验证覆盖普通池和历史回执、正式确认后的引用重绑、浏览器失联恢复、训练正负样本的两种选择顺序，以及两个 Vue 构建的离线资源。隔离夹具从冻结快照读得 Train 正 1 / 负 1、Val 正 1 / 负 1、Test 正 1 / 负 0，负样本标签文件为空。CI 以本轮交付中的远端 SHA 为准。
- 独立复审先核对真实任务准备证据及兼容边界。M4-C 的 ZIP 划分继续等待独立安排，保持现有 ZIP 上传、确认与导入 Owner。
- 独立审计整改以 `71e9531b229d5bbb70d97b585bdaa9b1c9b3c348` 为基线。冻结合并按账号、项目和算法保存最近一笔 UUIDv4，完整范围及五类修订一致时通过原服务端冻结接口重试。公共池回执按已验证账号和项目恢复，项目切换重新挂载并取消旧读取。旧项目级缓存键因无账号归属不自动恢复。
- 独立审计整改本地通过 2 项 Python 定向用例及 6 项 Chrome 用例，覆盖同范围重试、改范围冲突、过期证据拒绝、账号隔离和项目切换。Vue 类型检查及新旧构建离线闭包通过。新 SHA 的 CI 以交付快照为准。


## M4-C1 ZIP 文件夹归集与标签确认

- 基线 `7f0a01771abd12d2e37919f13efa33481c71d871`。SPA 素材库沿用旧工作台 v19 ZIP 入口。新版普通上传明确启用文件夹确认，未启用的旧客户端、历史任务及旧算法池入口保留原合同。
- `GET /api/v19/projects/{project_id}/import/jobs/{job_id}/folders` 分页返回真实图片目录、用途建议和标注汇总。识别完整中英文目录名。未知、术语需复核及冲突目录等待用户确认。确认同时复用原外部标签映射。外部类别或来源路径有冲突时需修正或拆包。
- 原 job.json 冻结实际 ZIP SHA256、扫描清单摘要、项目、任务、选择范围、文件夹规则和外部映射。正式素材内 `zip_folder_source` 保存完整来源路径、用途、摘要与归集状态。该证据随 MaterialRepository 保留，新版来源用途不写成旧 `split`。成功解析节点直接提交素材 ID 的来源证据，包含 COCO/VOC 未引用原图分支。
- 目标标签只写待标注意图。已入库外部 GT 保留原映射与正式标注权威。负样本直接进入项目公共池，分类和素材归集状态在同一事务提交。失败回执保留待归集范围，可通过原任务重试，或者在素材治理中处理。运行状态异常或归集分类已失效时应先核验任务或修复分类。正式训练、GPU 和生产仍待现场验证。
- M4-C2 需先为 `platform_core/training_splits.py` 的 `SplitRequest` 和 `build_split_manifest()` 设计明确的固定 Val 及跨角色冲突合同，再衔接 `platform_core/remote_training_tasks.py` 的 `_freeze_request_contract()` 与 `platform_core/training_tasks.py` 的 `resolve_training_input_freeze()`。用途意图仅作为来源证据，正式 GT 和隔离准入仍由现有 Owner 校验。
- 定向验证通过 ZIP API 与分类 Python 用例 23 项、ZIP Node 53 项、Chrome ZIP 路径 41 项，以及 Vue 类型、构建和离线资源核验。以交付消息记录最终提交 SHA 与对应 CI。


## M4-C2 按 ZIP 来源固定训练划分

- 基线 `535ec5497245ecea3ad43e05a1b6120c66e40209`。独立 Vue 训练创建页新增 `fixed_zip_train_val_test`，携带显式 Validation 引用和两个空随机比例。旧随机划分与独立 Test 保留默认行为。
- v62 选材接口分页列出具有持久化 C1 素材来源的 ZIP。预览从 MaterialRepository 和 AnnotationRepository 读取真实用途中已入库的成员，排除未指定，显示资格和泄漏问题。三组引用用同一确认 UUID 派生三个稳定身份，复用原选择清单的角色、修订、配额及摘要核验。草稿、冻结请求和待核验创建记录按登录账号、项目及算法隔离。旧浏览器记录因缺少账号归属不自动恢复。
- `/train/start` 校验来源、完整引用与组合限制。原 TrainingPrepare 在队列后复核引用、正式 GT、源内容身份和历史隔离，任一固定成员失效时拒绝整批。固定 Val/Test 使用正式评测 GT；Train 可使用原任务级确认。固定模式拒绝 Benchmark 复用、补数据、样本上限和会增加成员的颜色增强。
- `SplitRequest.validation_image_ids` 和 `build_split_manifest()` 保留三组固定成员，阻断 ID、内容、来源和派生关系的跨组重叠，同角色内容重复也拒绝。冻结可选字段绑定角色、来源清单摘要及原 GT，历史冻结摘要兼容。中央、Node Agent、远程结果和使用索引维护共用固定输入重放合同。
- 实际打包输出 Train/Val/Test 各自图片目录，Test 标签留在独立评测真值目录，未写进训练 YAML。报告核验冻结摘要和快照后显示实际数量及来源规则，超出摘要读取预算时明确显示证据不可用。
- 隔离验证覆盖实际 v19 导入到 v12 任务请求、中央准备、不可变冻结、精确目录、负样本空标签、Test 隔离、使用记录和只读报告。未执行真实 epochs 或 A800/4070 验收。CI 以交付消息所列准确 SHA 为准，后续等待独立复审。
- 本地通过训练核心、引用、报告、历史和准备定向 Python 用例，以及真实 ZIP 创建请求、Node Agent 冻结重放和远程结果验证。前端 41 项 Node、7 项 Chrome、Vue 类型检查和离线构建通过。

## M4-D0 AI 标注与审核安全加固

- 基线 `a4f9b4e40dd4d2522dd0a90f520119c8f21c8edf`，开发状态 `M4-D0_IMPLEMENTED`。本节所在唯一 M4-D0 提交的完整 SHA 与 Actions 快照见交付消息。
- 部分 GT 恢复、逐图补审、负样本转池和撤销复用各自正式 Owner。旧工作台与 Vue 审核投影共用选择 Owner 和服务端资格。正式 GT、训练及任务运行边界见[审核工作台](../AI_REVIEW_WORKBENCH_2026_11_06.md#m4-d0-审核数据恢复与操作范围)。
- 本地验证包括隔离 GT/转池中断、外部 GT 修改、选择排除和跨操作者拒绝；运行与实际改动相关的 Node 校验、Vue 双构建和 Python 编译。相关现有 GitHub Actions 异步验收。未操作生产或启动真实推理。
- 下一步仅复核本次准确 SHA 的 AI Annotation Recovery 与 Frontend Runtime Stabilization，按证据处理相关失败，独立复审完成后再安排 M4-D1。


## M4-D1-B 原生 AI 审核只读试点

基线 `fb9f66ac202876196d1077ff3a870798b69606b1`，该基线 22 项 Actions 成功。D1-B 试点地址为 `/app/#/projects/:projectId/ai/tasks/:taskId/review`。经现有 Session、项目列表和 v60 任务详情核验后，单一 Pinia Store 读取每页 24 张候选。切换范围或离页取消请求；切图同时取消原图详情和诊断读取。原工作台继续承接编辑、采用、拒绝、冻结、消歧、正式入库、转池、撤销和回执恢复。

新页面使用 v61 正式素材读取和既有候选框预览组件。验证使用隔离 Chrome 夹具，覆盖任务身份、20k 总量下的有界分页、图片和诊断按需读取、三个指定视口、原入口回退及读取取消。Vue 类型检查、独立 SPA 构建及离线资源检查见本阶段交付记录。准确提交 SHA 及 Actions 快照见交付消息；独立架构验收后再安排 D1-C。


## M4-D1-C 原生 AI 单图候选草稿

基线 `e0f1761187e6c8c3b4e0bde3259101dae1fbc161`，22 个基线 Actions 成功。审核试点使用相同显式路径。当前单图编辑复用 `AnnotationEditor.vue`、原 Annotorious 3.9.5 内核及正式项目标签。编辑会话记录未确认请求及其原始请求体，按账号、项目、任务、图片隔离。在 v60 草稿 PUT 中原样重放，已有 CandidateStore 完成 CAS、幂等和持久化。确认保存后重读候选及当前分页；版本冲突保留本地编辑，用户确认后采用服务端草稿。

图像取 v61 正式原图，交互与图像共享原图像素坐标。浏览器按 EXIF 显示；历史服务端尺寸与实际显示方向或尺寸不一致时，本页阻止编辑。完整处理该类素材需另行对齐服务端原图坐标合同。独立验收前仍从原入口执行正式采用、GT 入库、批量审核、转池、消歧、撤销及回执流程。准确 SHA 与 Actions 快照见交付消息。D1-D 需独立审计及后续授权。


### M4-D1-C1 草稿恢复收口

基线 `9c0bdd77b091f7e770cf2345eb154063e595c49e` 的 22 项 Actions 均成功。C1 为已有会话恢复记录校验身份、原请求和框数据，兼容同一作用域存储键中原有的未确认记录。原请求未核验时，即使工作副本与服务端一致也触发离开保护。收到成功回执后仅重读服务端，读取失败时保留已确认标记及重读入口。跨作用域取消请求时继续保留未确认身份。无效记录保留，不能进入编辑器或发送请求。

隔离 Chrome 对真实 v60 接口验证响应丢失、原请求重放、确认后重读失败、无本地差异仍提示离开、身份错配记录拒绝、409 保护和正式 GT 保持原样。C1 独立提交；准确 SHA 的 CI 通过前暂停 D1-D1，继续由原工作台提供采用与拒绝。


### M4-D1-D1A 单图审核决定合同

基线 `a7048c781c3b982d687c9b698c4f70d747359bf7` 的 22 项 Actions 均成功。原 v60 decisions 路由新增显式 `single_candidate=true`。调用必须给一张候选、稳定 `request_id` 和权威 `review_revision`，关闭两种未提及处理和正式入库开关，且不提交框或全局映射。旧请求不含该开关时保持原行为和历史回执摘要。

单图资格、标签和逐图范围核对后，在 CandidateStore 同一 SQLite 写事务中完成候选、修订和 `review_events` 持久证据。回执查询按原项目、任务、操作者、请求摘要和单图结果匹配。缺少可信事件时保持 pending，不从后续 accepted 状态推断。拒绝不声明审核范围；逐图补审采用需要显式冻结范围；未人工解歧不得采用。

实际验证比较了未选候选数据库行、正式 GT 内容和版本，并验证回执写入前后的中断、同号重放、修订冲突及旧批量、正式入库和草稿合同。A 阶段准确提交 `d4d0be1086b0f73a74546c46712cbbbde307ad68` 的 Push 26 成功、1 失败，PR 21 成功。两个 AI Annotation Recovery 批次、Material Annotation Atomicity 和 Frontend Runtime Stabilization 均成功。ZIP Import Durable Runtime 的 `real-chrome-refresh` 在 `zip-import-refresh-recovery.spec.mjs:440` 等待第二个 v19 ZIP 队列项失败，原单项在本地复跑通过。A 的改动触及 v60 与 CandidateStore，目前没有因果证据指向 A。按修正放行规则继续 B，保留 GitHub 失败记录。[ZIP 工作流](https://github.com/jorsamj/aixunlianpingtai/actions/runs/44670825120)

### M4-D1-D1B 原生单图采用和拒绝

沿用 `/app/#/projects/:projectId/ai/tasks/:taskId/review`。Pinia 从候选详情保留权威 `review_revision`，操作前复读同一候选以核对显示快照。POST 只包含单图及明确人工选择的冻结补审范围，关闭正式入库和未提及处理开关。按账号、项目、任务、图片隔离单图决定回执。未知结果仅查原请求，404 和 202 继续保留，409 刷新候选后等待用户作下一次决定。已完成回执遇到读回失败时重读详情和当前页统计，保留筛选和检查图。

现有 Frontend Runtime Stabilization 的真实入口 Job 复用该 SHA 已构建的资源运行单图决定与草稿 Chrome 用例。本地验证、准确 SHA 和 CI 快照见阶段交付。跨页冻结、批量决定、批量消歧、正式 GT 入库、转池和撤销继续由原工作台提供，原菜单入口保留。D1-D1B 分页收口基线 `dbfd4b60134f83be3b99bf532d27492cbf0274a2` 的 22 项 Actions 均成功。

### M4-D1-D2A 跨页选择与冻结

原生工作台支持显式跨页选择和 `gt` 服务端筛选快照。显式状态只保存所选 ID；冻结状态只保存数量、资格排除、快照身份和手动排除 ID。每页至多读取 24 张，使用 `selection_member` 显示成员资格。修订不一致、快照过期或找不到时丢弃冻结并要求重新选择；旧工作台需重新选择。已有真实 Chrome Job 验证跨页、空快照、身份隔离和草稿回归。D2B 的正式 GT 提交协议待独立设计。

## 2026-11-21 接续入口（C2-B 与性能阶段）

- 最新已推送 HEAD 见 `git log -1`；本阶段关键提交：`43aaa14e`（封存恢复必须幂等重放证明）、`6134bfb5`（真实批量 GT 回执/坐标/批次证据与 Worker 日志）、`b74766b9`（标签编辑仅刷新标签）。
- 真实浏览器批量证据：`tests/browser/real-bulk-formal.spec.mjs` + `tests/browser/helpers/bulk_review_worker.py`（隔离 uvicorn + 独立测试 Worker 进程，205→201 三批、跨页排除 4 张、第二笔 4 张）。
- 仍未验证：生产 Worker 监督/重启/租约重领、真实 20 万图片与存储 I/O、生产 P95、FTS5 搜索方案。

## 2026-11-21 性能与恢复分类收口（本阶段）

- C2-B 恢复证明：只有 409 摘要冲突进入 `bulkConflict`；503/超时/网络失败进入未知锁定态，保留原 request_id 与 execution_attempted。
- legacy GT：空 `annotations/` 目录不再逐图 `is_file`；隔离 20 万合成、无持久 GT 下 `/projects` 4.65s→1.75s，`/datasets` 6.5s→3.63s，`/images` 仍约 2.15s/106MB。
- 标签：正式标签页 Owner 为 `renderLabelManagement414` / `saveLabel414` / `refreshLabels414`，已具备局部刷新；`b74766b9` 的 `refreshLabelsOnly` 属历史路径，本阶段仅补项目切换与失败保护。
- 未实施：`/images` 有界化、`/datasets` 聚合重构、FTS5、生产 Worker 生命周期验收。

## 2026-11-25 P0-01C 最终定向收口

实现 SHA：`b8c61ec6d0218ee1958aee82ec9aeafec015b9e7`（起点 `8d2c7fe9486f547c6758491e8997f68959aa9707`）。开发 `FUNCTIONAL_COMPLETE` / 验收 `CI_PENDING`；本机只做语法/静态/Git 核验，运行期和生产未验。中央单槽恢复绑定原节点、Assignment、attempt、worker、GPU/CPU、ProcessIdentity；Runner 未启动证明与身份未知分开，未知不得 finish；中央结算使用单一事务快照。测试合同与边界见 [本轮记录](P0_01C_FINAL_TARGETED_CLOSEOUT_20261125.md)。准确最终 SHA 与一次性 CI 快照见交付消息。无已知源码阻断，下一步交 GPT 独立审计；本轮到此停止。

## 2026-11-25 资源准入与安全 Requeue

P0-01C 已结束：用户独立核验基线 aaeebd06c608ab58b2317767dacff2351556606b 的 22 个 PR workflow 全部 SUCCESS。新实现 13a5cecf79d3ca677929e0f77c356cab19c56e0a 补齐资源规划→Agent 未启动证明→中央原子退回→原 Assignment 幂等回执→按节点等待/其他节点选择。保留原 TaskRuntime attempt、Owner、Hold 和 job.json 栅栏，无新 schema。开发 FUNCTIONAL_COMPLETE / 验收 CI_PENDING；本机仅源码/语法/静态/Git 检查通过，运行期/生产未验。准确最终 SHA 和一次性 CI 快照见交付消息。[合同、测试及网络未知边界](RESOURCE_ADMISSION_SAFE_REQUEUE_20261125.md)。完成后停止，交 GPT 独立审计。

## 2026-11-25 资源等待重启恢复与后端模块化

基线 21fb70de23c3be40006cb27579a031ca487abf60 的 22/22 PR workflow SUCCESS 为用户独立核验结论，P0-01C/准入不重做。A：dd8ee530924e79b87ed876d309b4dc0017d650bc，原 Coordinator 消费资源等待持久请求，先查旧 Assignment 回执，明确 404 才按原 lease/attempt 精确重放，未知保留证据；见[资源记录](RESOURCE_ADMISSION_SAFE_REQUEUE_20261125.md)。

B：da45ae7a46458cad0c8ce469f6083ae6c4613c21，算法库目录与版本生命周期 14 个接口和约 900 行业务/辅助逻辑迁到 Router/Contracts/Service，原 Repository/事务/锁/权限/Owner 保持。app.py 29,124→28,264 行，直接 HTTP 330→316+新 Router 14；静态有序合同逐项一致，运行时/OpenAPI 交 CI。新模块不 import app，不复制全局状态；原 bootstrap Owner、必要兼容入口保留。开发 FUNCTIONAL_COMPLETE / 验收 CI_PENDING，准确最终 SHA 和一次性 CI 快照见交付消息。[模块边界、证据、剩余域与依赖](BACKEND_ALGORITHM_CATALOG_MODULARIZATION_20261125.md)。本轮停止，交 GPT 独立审计，不自动扩展下一域。

## 2026-11-25 算法守卫收口与素材目录模块化

后续接续（2026-11-25）：基线已推进至 6111b541d617def129ac8ed51b1841782417ee8f（用户核验 22/22 SUCCESS）。本轮 A e3764889 完成素材成员/用途/状态及旧删除准入 8 接口迁移；B 完成标签 CRUD/引用/重映射/统一和人工标注读取/保存 10 接口及关联业务迁移。原 MaterialRepository、AnnotationRepository、GT write_annotation、数据集锁、标签锁和 material_batches 回执 Owner 保留。app.py 28,001→27,303 行、直接 HTTP 304→286，原序列与模型 AST 保持。相关源码守卫转向真实 Service/Contracts，未弱化断言。开发 FUNCTIONAL_COMPLETE / 验收 CI_PENDING；只做语法/AST/符号/Git 检查，运行期交既有 CI。B/最终实现 SHA 与一次性准确 CI 快照见交付消息及提交记录；详情见[模块化记录](BACKEND_ALGORITHM_CATALOG_MODULARIZATION_20261125.md)末节。下一边界是 AI 创建/清洗/审核的完整候选 CAS、冻结、GT 屏障和 C2-B 回执编排，本轮不拆散迁移；停止等待独立审计。

基线 c183ab3d49b82346ce2866468a92fd1bb4a2b8d3 开工一次查询：22 个 PR workflow，20 SUCCESS/2 FAILURE，无其他失败；资源恢复不重复整改。A：832e168d，两项实际静态守卫跟随算法 Router/Service，保留本地创建无外部授权、LOCAL 来源、原创建调用和标签合同。

B：327023ff399263e93b261c68cf08f5c534622bfc，完成素材浏览、数据集目录管理及只读标签/质量投影单元，12 接口迁到 material_catalog_api/contracts/service，原 MaterialRepository/AnnotationRepository、StorageManager、索引生命周期及数据集元数据访问器保持。删除/引用保护、标签写入/合并、人工 GT、AI 审核和既有 material_batches/Picker/负池留原 Owner，未声称全素材域完成。app.py 28,264→28,001 行；直接 HTTP 316→304+新 Router 12，有序静态合同与 13 个业务体比对一致。开发 FUNCTIONAL_COMPLETE / 验收 CI_PENDING；本机仅语法/定向静态/Git 检查，运行期交现有 CI。准确最终 SHA/一次性 CI 快照见交付消息，详见[模块化记录](BACKEND_ALGORITHM_CATALOG_MODULARIZATION_20261125.md)。本轮停止，交独立审计。

## 2026-11-25 路由合同、AI 审核与训练业务接续

基线 47b7900b4b1dffc9594b14bff9f7e392269d132b，用户核验 22 个 PR workflow 为 21 SUCCESS / 1 FAILURE。A f68fa3669609304cad0b2a48174d372bac814ef7：两处唯一性测试使用 FastAPI iter_route_contexts，有旧版扁平路由回退；唯一注册、真实 endpoint、OpenAPI、请求模型及私有审核字段断言保留。B 7044815c295777ab335da4526c0f16ba271ca423：AI 创建/查询/草稿/冻结/审核/正式入库/转池/C2-B 33 接口及清洗全生命周期 7 接口迁入两个业务模块。C/最终实现 SHA 见本节所在提交及交付消息：训练管理 11 接口、评测/对比/意见/难样本/补充数据冻结/算法报告 14 接口迁入 training_management 与 training_evaluation。

原 CandidateStore、AnnotationRepository、TaskRuntime、Worker、冻结、GT 屏障、幂等及取消对账 Owner 保留；无新任务体系或数据库。app.py 27,303→23,708 行、直接 HTTP 286→221；112 个业务/辅助函数及 19 个模型 AST、接口有序签名与两个同名选择模型绑定保持。旧守卫和故障注入定位至真实 Owner。开发 FUNCTIONAL_COMPLETE / 验收 CI_PENDING；仅语法/符号/AST/装配/Git 检查，运行期和新增 65 接口有效路由合同交既有 CI。前端、VERSION、AGENTS、四份保护文档和生产未动。剩余与验证边界见[模块记录](BACKEND_ALGORITHM_CATALOG_MODULARIZATION_20261125.md)末节。统一推送后一次准确完整 SHA CI 快照，停止等待独立审计。

## 2026-11-25 剩余后端业务集中迁移

起点 4d98b1f7bc7de3f7ed55f2e566017532db78517b；开工准确 SHA 的 22 项 PR CI 快照为 2 SUCCESS / 20 QUEUED，无已完成失败，未据此宣称验收。A 1c5f6de615254137a6326a81c7f37fd02869bb69：转换管理/交付 27 接口、部署验证 7 接口。B 4492a17d2518a5bf0bf66107902093b4fb546332：统一素材/ZIP/上传导入 25、存储扫描/确认 10、视频 4、检测批次 3 接口。C/最终 SHA 见本节所在提交及交付消息：项目 5、存储配置 6、AI 模型/Prompt/旧服务配置 19、运行资源目录与配置 37 接口。

累计迁出 143 个接口、198 个业务/辅助函数和 30 个模型；app.py 23,708→18,503 行，直接 HTTP 221→78。原 URL/Method/operationId 输入、参数/默认值/响应、顺序、鉴权和事务保持。转换器、Worker、TaskRuntime、发布仓储、GT、ZIP 引擎、SecretStore、缓存/锁及 Session 唯一 Owner 继续复用，未新增执行模式。select_ultralytics_env 因原全局环境生命周期写入留在应用根；认证、后台恢复和共享文件/仓储访问器亦保留。迁入母模型沙箱探测的历史未绑定 logger 依赖接到原 logging，未改验证器。

开发 FUNCTIONAL_COMPLETE / 验收 CI_PENDING。本机仅语法/符号/AST/装配/守卫/Git 检查，143 接口有效路由与既有运行期合同全部交现有 CI；保护文档、VERSION、AGENTS、产品前端与生产不变。尚余旧推理/数据集构建导出、v42 编排、bootstrap、认证及生命周期等原根职责；旧 v12_test_models 的历史未定义 artifact 兼容符号仍需定向核验，不掩盖为本轮完成。详见[本批真实范围与边界](BACKEND_ALGORITHM_CATALOG_MODULARIZATION_20261125.md)末节。统一推送后只查一次最终完整 SHA CI，停止交独立审计。

## 2026-11-26 后端集中收尾与已知 CI 整改

起点 92022115750d8354e88a431416abd1c94916f980。用户独立核验：4d98b1f7 为 20 SUCCESS/2 FAILURE，92022115 为 19 SUCCESS/3 FAILURE，22 workflows 均结束。本轮直接读取三个实际失败 Job 139311756414/139311755167/139311754146，没有重查无关绿色 Job。

A dd8254b8ef00c8974a2384cc0146ecabed3f8f3b：30 项失败逐组收口（3 个 AI prepare 替身、1 个旧源码守卫；19 个评测素材 Repo 替身、1 个难样本 GT Repo/版本写入替身、2 个投影 summary 签名；4 个目录关键字委派）。保留全部原断言，生产只修兼容入口/API 的 detect_missing 关键字传递，不改模型准入或转换器。B b3b419ee347f468fd8f91df8ddc2d966039e0377：确认旧 test_models 仍被前端调用，将真实 artifact Reader 从原 Router 提为同模块共享函数，原 Router 与兼容入口共用；消除被旧 try/except 吞掉的未定义符号和产物漏项，原授权/过滤/返回字段与错误处理保持。

C/最终见本节所在提交及交付消息：推理/模型 6、数据集导出 6、活动旧 v42 编排 17、质量分析/辅助归因/补充素材 5、复用素材治理的显示名编辑 1，共迁出 35 接口、49 函数、8 模型。app.py 18,503→17,657 行，直接路由 78→43；累计 330→43（迁出 287），不以此宣称所有辅助函数均已迁出。根 43 路由完整分类及各共享 Owner 见[模块记录](BACKEND_ALGORITHM_CATALOG_MODULARIZATION_20261125.md)末节；认证、Session、文件授权、生命周期、bootstrap 与兼容拒绝不强拆，旧入口未删除或重新启用。

开发 FUNCTIONAL_COMPLETE / 验收 CI_PENDING。本机仅语法、符号、AST/接口/装配/守卫及 Git 检查，未运行 pytest、应用、服务、浏览器或构建；35 接口有效路由与原业务合同交现有 CI。VERSION/AGENTS/四份保护文档、前端和生产未改，无 Vue/正式 PostgreSQL 扩展。统一推送后只取一次完整最终 SHA CI 快照即停止，交 GPT 独立审计。
