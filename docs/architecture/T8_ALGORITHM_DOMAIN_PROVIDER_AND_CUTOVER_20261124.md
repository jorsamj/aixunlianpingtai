# T8 算法域 Provider 抽象、单域迁移工具与隔离切换（2026-11-24）

> 范围仅算法域（U1）。`app.py` 未修改，Provider 由主 Agent 接入；Task/GPU/GT/素材/模型/发布域不动，
> 不双写、不新建微服务/Redis/K8s，默认仍为 SQLite。真实 PostgreSQL 验证使用本机隔离
> `pgserver`（PostgreSQL 16.2）+ `psycopg` 3，非生产库。

## 1. 既有资产与本次新增

既有（本轮未重写）：

- `platform_core/algorithm_shadow.py`：SQLite 只读一致快照、canonical 摘要、`w5_shadow` 只读影子导入/对账；
- `platform_core/algorithm_shadow_cli.py`：影子 export/validate/import/reconcile/inspect；
- `docs/architecture/w5_algorithm_shadow_schema.sql`：`w5_shadow` 影子 DDL；
- `tests/unit/test_algorithm_shadow.py`、`tests/integration/test_algorithm_shadow_postgres.py`：现有影子验证。

上述资产继续独立工作，本轮回归 9 项通过；`w5_shadow` 与 `w5_algorithm` 并存：前者是只读对账影子，
后者是切换目标的关系模型。

本次新增：

| 文件 | 作用 |
|---|---|
| `platform_core/algorithm_repository.py` | Provider 合同（Protocol）、SQLite 适配器、受准入约束的工厂 |
| `platform_core/algorithm_postgres_schema.py` | `w5_algorithm` 版本化 schema、校验和、显式升级 |
| `platform_core/algorithm_postgres_store.py` | 同一合同在 PostgreSQL 上的完整实现（SQL 仅在此） |
| `platform_core/algorithm_migration.py` | 导出/导入/幂等/断点续跑/试运行/报告/反向恢复 |
| `platform_core/algorithm_cutover.py` | 准入条件、单写者代次、回退安全证据 |
| `platform_core/algorithm_migration_cli.py` | 上述能力的 CLI 入口 |
| `tests/unit/test_algorithm_provider_boundary.py` | 无 PG 的边界/报告/密钥/校验和合同（12 项） |
| `tests/integration/test_algorithm_migration_postgres.py` | 真实 PostgreSQL 全链路（7 项） |

## 2. Provider 合同与方言边界

合同版本 `algorithm-repository-v1`，`CORE_OPERATIONS`：`ensure_ready`、`revision`、
`migration_status`、`read_all`、`read_one`、`exists`、`training_version_refs`、`replace_all`、
`create_algorithm`、`patch_algorithm`、`delete_algorithm`、`attach_version`、
`attach_version_if_current`、`patch_version`、`rollback_version`、`delete_version_with_operation`、
`update_version_operation`、`sync_external_algorithms`。

- SQLite Provider 是 `AlgorithmSqlStore` 的**透传适配器**，行为与错误码不变；`library_algorithms`、
  `asset_*`、`bootstrap_summary`、`training_display_refs` 等展示投影继续原样工作。
- PostgreSQL Provider 实现全部核心操作；展示投影未移植，`capabilities()` 明确少这 7 项，
  调用时抛 `ALGORITHM_PROVIDER_OPERATION_UNSUPPORTED`，**绝不回退读 SQLite**。
- SQL 只存在于 `algorithm_sql_store.py`（SQLite）与 `algorithm_postgres_store.py` /
  `algorithm_postgres_schema.py`（PostgreSQL）；`algorithm_repository.py` 不含 SQL，
  业务模块（`app.py`、`algorithms.py`、发布/产物/训练模块）不 import `psycopg`、不出现
  `w5_algorithm.`/`%s::jsonb`，由单测源码守卫断言。

选择与失败关闭：

```python
from platform_core.algorithm_repository import open_algorithm_repository

repo = open_algorithm_repository(algorithms_json_path)             # 默认 sqlite，行为不变
repo = open_algorithm_repository(algorithms_json_path,
                                 provider="postgresql", dsn=dsn)   # 需要准入记录，否则拒绝
```

| 环境变量 | 含义 |
|---|---|
| `ALGORITHM_STORE_PROVIDER` | `sqlite`（默认）/`postgresql` |
| `ALGORITHM_STORE_POSTGRES_DSN` | PostgreSQL DSN |
| `ALGORITHM_STORE_ADMISSION_RECORD` | 准入记录路径；默认 `<project_dir>/algorithm_migration/cutover_admission.json` |

失败关闭规则：

- 选 `postgresql` 但缺 DSN → `ALGORITHM_POSTGRES_DSN_MISSING`；缺准入记录 →
  `ALGORITHM_POSTGRES_ADMISSION_REQUIRED`；连接/查询失败**不**回退 SQLite；
- 选 `sqlite` 但存在未撤销的 PostgreSQL 准入 → `ALGORITHM_SQLITE_STALE_AFTER_CUTOVER`，
  只有迁移工具可显式 `allow_stale_sqlite=True`；
- PostgreSQL Provider `ensure_ready()` 每次校验 `cutover_state` 的 provider/admission_id/
  writer_generation/未撤销，不匹配 → `ALGORITHM_POSTGRES_ADMISSION_STALE`。

## 3. PostgreSQL schema（`w5_algorithm`）

表：`schema_migration`、`algorithm`、`algorithm_version`、`algorithm_external_analysis`、
`store_revision`、`migration_run`、`cutover_state`。

- 主键按项目隔离：`algorithm(project_id,id)`、`algorithm_version(project_id,id)`、
  `algorithm_external_analysis(project_id,algorithm_id,external_analysis_id)`；两个项目可保留相同
  原始 ID 而不互相覆盖；版本/分析外键 `(project_id,algorithm_id)` 级联删除。
- `payload`/`compute_platform_ids` 为 JSONB，列仍保留 SQLite 的 NULL/空串/0 语义；
  布尔列用 BOOLEAN，读出时按 SQLite 形状 `::int` 归一，保证跨引擎摘要可比。
- 版本身份显式：`SCHEMA_VERSION = 1`，`MIGRATIONS` 只追加；每条落库记录 version/name/checksum/
  applied_by/时间。已应用迁移校验和变化 → `ALGORITHM_PG_SCHEMA_CHECKSUM_MISMATCH`；
  库版本高于工具 → `ALGORITHM_PG_SCHEMA_NEWER_THAN_TOOL`（拒绝降级）；待升级但未给
  `--allow-upgrade` → `ALGORITHM_PG_SCHEMA_UPGRADE_REQUIRED`；已是最新重复执行是 no-op。
- `ensure_schema()` 只由 CLI/工具调用，应用启动不隐式迁移；`import_snapshot()` 先
  `require_current_schema()`，schema 缺失/落后直接 `ALGORITHM_PG_SCHEMA_NOT_CURRENT`。

## 4. 单域迁移工具

CLI（`python -m platform_core.algorithm_migration_cli`）：

| 命令 | 说明 |
|---|---|
| `schema-status --dsn` | 当前版本、待升级项、缺失表、校验和问题 |
| `schema-init --dsn [--allow-upgrade] [--dry-run]` | 显式建库/升级（dry-run 事务回滚） |
| `export --db DB --project ID --out FILE` | SQLite 只读一致快照 |
| `import --snapshot FILE --dsn [--dry-run] [--resume] [--actor] [--run-id]` | 幂等导入 |
| `report --snapshot FILE --dsn [--out FILE]` | 快照 vs 现有 PG 的完整报告 |
| `verify --db DB --project ID --dsn` | 现场重新导出 + 目标重读 + 报告（非 OK 退出 3） |
| `status --dsn --project ID` | 最近导入运行记录 |
| `cutover-admit / cutover-status / rollback-assess / rollback-execute` | 见第 5 节 |

导出/导入保证：

1. **原始 ID 不变**：算法、版本、外部关联 ID 原样复制；报告对比三张表主键集合，
   并把“源缺失但目标出现同内容不同 ID”标记为 `regenerated`，此时拒绝切换。
2. **对象存储引用保持字符串**：`stored_path` 与 payload 中对象键只做类型检查
   （`object_references.non_string`），不解析、不下载、不复制；报告固定 `resolved: false`。
3. **绝不导出 SecretStore 凭据**：不读取 SecretStore 文件；深度扫描 payload 中 password/secret/
   token/api_key/credential/private_key 等键，出现明文值即
   `ALGORITHM_MIGRATION_SECRET_MATERIAL` 拒绝导出/导入；`secret://`、`env:`、`${...}` 引用视为字符串保留。
4. **幂等与回退保护**：目标 revision 相同且内容摘要相同 → `noop`；同 revision 不同内容 →
   `ALGORITHM_MIGRATION_DIGEST_CONFLICT`；目标 revision 更新 → `ALGORITHM_MIGRATION_REVISION_REGRESSION`；
   只有源更新才 `apply`。
5. **断点安全**：数据写入与 revision 在单事务内；运行记录 `migration_run` 先独立提交
   （RUNNING + heartbeat）。崩溃后 `--resume` 仅在心跳超过 `stale_after_seconds`（默认 300s）
   且摘要/revision 一致时接管为 ABORTED 再重跑；无 `--resume` → `ALGORITHM_MIGRATION_RUN_IN_PROGRESS`；
   每项目最多一个 RUNNING（部分唯一索引）。
6. **dry run**：完整执行写入后回滚事务，报告将写入的动作与行数，目标 revision 不变。

迁移报告 `build_report()` 覆盖：项目隔离、三表行数、主键集合（缺失/多余/重生成）、外键与关联
（版本/挂载分析孤儿、`current_version_id` 悬挂、重复键）、revision 关系、JSON 字段（可解析性、
类型、未知字段保留）、NULL vs 空串/0/false 逐列语义、对象引用类型、凭据扫描、跨引擎内容摘要
（`content_digest`，对 payload 做结构归一，与 JSONB 键序无关）、以及整体 `summary_digest`。
结论 `OK` / `MISMATCH` / `TARGET_MISSING` 与 `blocking_findings` 一并输出。

## 5. 隔离切换与回退

准入（`admit_cutover`）逐条强制，任一不满足即 `admitted=false`、CLI 退出 3：

| 条件码 | 含义 |
|---|---|
| `MIGRATION_REPORT_CLEAN` | 现场重算报告 verdict=OK（未使用旧报告） |
| `SCHEMA_AT_TARGET_VERSION` | `w5_algorithm` 处于目标版本 |
| `NO_IMPORT_RUNNING` | 无 RUNNING 导入 |
| `TARGET_CONTENT_MATCHES_SOURCE` | 目标内容摘要等于源 |
| `WRITER_GENERATION_MATCHES` | 调用方持有当前写者代次（CAS，防两个操作者同时准入） |
| `SINGLE_AUTHORITATIVE_WRITER` | 当前权威写者仍是 sqlite，不允许重复准入 |
| `OPERATOR_AND_REASON_RECORDED` | 操作者与原因进入审计 |
| `UNPORTED_OPERATIONS_ACKNOWLEDGED` | 展示投影未移植必须显式 `--acknowledge-unported` |
| `REPORT_NOT_STALE`（可选） | 传入旧报告时必须与现场重算摘要一致 |

准入事务内再次校验目标 revision/摘要（`ALGORITHM_CUTOVER_TARGET_CHANGED`），提交后立刻重读
SQLite；若源在准入窗口内被写入，则紧急把权威方退回 sqlite 并报
`ALGORITHM_CUTOVER_SOURCE_CHANGED_AFTER_ADMIT`，绝不留下两个可能写者。准入成功后写
`cutover_state`（provider=postgresql、generation+1、admission_id、内容摘要、证据 JSON），
再原子写本地准入记录（Provider 工厂据此拒绝旧 SQLite）。

回退（`rollback-assess` / `rollback-execute`）只有在以下证据齐全时允许：

- `CUTOVER_CURRENTLY_ACTIVE`：`cutover_state` 提供商为 postgresql、admission_id 匹配、未撤销；
- `TARGET_HAS_NO_NEW_WRITES`：PG 当前 revision 与内容摘要仍等于准入时值（有新写即阻断）；
- `SQLITE_COPY_MATCHES_ADMITTED_CONTENT`：现有 SQLite 仍等于准入内容（过期副本阻断）；
- `NO_IMPORT_RUNNING`。

通过后才按准入内容反向写回 SQLite（事务内逐行复制并回读校验，`ALGORITHM_ROLLBACK_ROUND_TRIP_MISMATCH`
即回滚），然后把权威方改回 sqlite、generation+1、记录撤销证据并重写本地准入记录。
`rollback-execute` 还需 `--confirm`。

## 6. 验证边界

| 项 | 证据 |
|---|---|
| Provider 默认 SQLite 行为不变、工厂准入/旧 SQLite 拒绝、方言源码守卫、报告纯逻辑、密钥拒绝、校验和 | `python -m pytest tests/unit/test_algorithm_provider_boundary.py -q` → 12 passed |
| schema 显式升级/重复执行/校验和；导入幂等/试运行/续跑/回退与摘要冲突；并发导入仅一个写者；报告 OK 与重生成 ID/NULL 差异；读写行为与 SQLite 一致（含 `summary_only`）；准入代次/单写者/旧 SQLite 拒绝；回退证据与恢复；CLI 全周期 | `python -m pytest tests/integration/test_algorithm_migration_postgres.py -q` → 8 passed（本机 pgserver PostgreSQL 16.2） |
| 既有影子未受影响 | `python -m pytest tests/unit/test_algorithm_shadow.py tests/integration/test_algorithm_shadow_postgres.py -q` → 9 passed |
| 语法 | 对全部新增/修改文件 `python -m py_compile ...` 通过 |

未验证/未完成：

- 生产/共享 PostgreSQL、权限受限角色、网络中断与大表压力未验证；
- 展示投影（算法库/资产分页等）尚未移植到 PostgreSQL，切换需显式确认；
- 导入为单事务，超大项目的中途续跑是“重跑幂等”，未做分块检查点；
- `app.py` 接线、Provider 的请求级缓存/连接池由主 Agent 负责；
- 未执行全仓测试、未部署、未改 VERSION/生产数据。

## 7. 建议提交信息

`feat(algorithm): add PostgreSQL provider port, single-domain migration tool and isolated cutover`
