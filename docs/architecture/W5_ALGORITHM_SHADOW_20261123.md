# W5 U1 算法域 PostgreSQL 只读影子（2026-11-23）

> SQLite `algorithms.sqlite3` 仍是唯一正式事实源。本模块只读导出并写入隔离 PostgreSQL schema `w5_shadow`，不双写、不切 Provider、不迁移 GT/Task/GPU。

## 1. 代码

- `platform_core/algorithm_shadow.py`
- `docs/architecture/w5_algorithm_shadow_schema.sql`
- `tests/unit/test_algorithm_shadow.py`

能力：

- `export_snapshot(store)`：`file:...?mode=ro` + `PRAGMA query_only=ON` + 单读事务；不初始化、不迁移、不建文件；
- 同一事务读取 `algorithm_store_meta`、algorithms、versions、external_analyses；`algorithm_revision` 与数据同快照；
- 稳定排序（project/id、algorithm/id、algorithm/external_analysis_id）；
- PG 读取使用 REPEATABLE READ 单事务，metadata/行/摘要同一快照；
- 非空闲连接只有在当前事务已是 REPEATABLE READ/SERIALIZABLE 时允许读取，否则 `ALGORITHM_SHADOW_TRANSACTION_ISOLATION_UNSUPPORTED`；不提交/回滚调用方事务；
- canonical JSON SHA256；`captured_at` 不参与 digest，重复导出 digest 稳定；
- `write_snapshot` / `load_snapshot`；
- `import_snapshot(connection, snapshot)`：PostgreSQL 事务导入，项目隔离，同 revision+digest 幂等，同 revision 不同 digest 冲突，旧 revision 拒绝回退；
- `load_shadow_snapshot` / `reconcile(source, shadow)`：同 revision/digest 才做逐行对账，区分缺失/多余/字段变化；
- 未知字段保留在原始 `payload_json`（JSONB 行）中。

## 2. 使用

```python
from platform_core.algorithm_sql_store import AlgorithmSqlStore
from platform_core.algorithm_shadow import export_snapshot, write_snapshot, import_snapshot

store = AlgorithmSqlStore(Path("/data/projects/p1/algorithms.json"))
snapshot = export_snapshot(store)
write_snapshot(snapshot, "/tmp/p1-algorithm-shadow.json")

import psycopg
with psycopg.connect("postgresql://.../shadow_dev") as connection:
    import_snapshot(connection, snapshot)
```

先执行 `docs/architecture/w5_algorithm_shadow_schema.sql`，或由 `import_snapshot` 幂等建表。
该连接必须是独立开发/临时数据库，不允许指向生产。

## 3. 对账

```python
from platform_core.algorithm_shadow import load_shadow_snapshot, reconcile
shadow = load_shadow_snapshot(connection, "p1")
result = reconcile(snapshot, shadow)
```

- `reason=SOURCE_REVISION_CHANGED`：SQLite 已变化，必须重新导出，不能把不同 revision 当失败；
- `SNAPSHOT_DIGEST_MISMATCH`：快照摘要不一致；
- `DATA_MISMATCH`：同摘要但行内容不同（人工/异常修改影子）；
- `SHADOW_MISSING`。

## 4. 验证状态

| 项 | 状态 |
|---|---|
| SQLite 只读快照/稳定摘要/空项目/源缺失 | `TARGETED_TEST_PASS` |
| 快照完整性验证/防篡改/counts/关联/合同 | `TARGETED_TEST_PASS` |
| 未知字段保留 | `TARGETED_TEST_PASS` |
| 对账纯逻辑 | `TARGETED_TEST_PASS` |
| PostgreSQL DDL/导入/幂等/advisory lock | `CODE_COMPLETE` |
| 真实 PostgreSQL 隔离实例 | **`POSTGRESQL_INTEGRATION_PASS`**（本机 pgserver + psycopg3） |
| 正式 SQLite Owner 切换 | 未发生 |

真实 PG 验证覆盖：

- 首次导入、同快照幂等、新 revision 替换、旧 revision 拒绝、同 revision 不同 digest 冲突；
- 首次两个并发客户端导入只成功一个；
- 项目 A/B 隔离；
- PostgreSQL JSONB 与源 canonical 对账；
- 读取元数据与行数据一致。

仍未验证：生产 PG、权限受限只读角色、异常注入 rollback、超大 payload、PG 崩溃恢复。CLI 入口见 `platform_core/algorithm_shadow_cli.py`。
