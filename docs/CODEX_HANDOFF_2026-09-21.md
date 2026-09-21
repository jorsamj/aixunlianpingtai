# Codex 接手交接 — 2026-09-21

> **用途：这是 2026-09-21 当前开发现场的最高优先级交接文档。**
>
> 新 Codex / 新 AI 接手 jorsamj/aixunlianpingtai 时，先重新读取 GitHub 真实远端状态，再读本文件。本文记录的是“文档提交前的代码/测试 HEAD”，文档提交本身会继续推进 branch HEAD，因此不得把本文中的 SHA 直接当成远端仍未变化的事实。
>
> 本文件优先于旧文档中的历史 NEXT、Current priority、历史 acceptance SHA、历史部署建议。旧文档仍然保留作为架构与历史证据，但若与本文件及实时 GitHub 冲突，以 **实时 GitHub → 本文件 → 当前 owner 代码** 为准。

## 0A. 2026-09-21 全站 cache-first 性能最小闭环（最新覆盖）

本轮没有拆掉 v53 snapshot，也没有建立第二套 cache/polling/truth。真实根因和收口如下：

~~~text
旧启动：prepared snapshot → browser cached snapshot → loadCore412(refresh=true) → full rebuild
新启动：prepared snapshot → browser cached snapshot → immediate target shell/cache
                                      ↘ page runtime authoritative refresh when stale

旧数据集：broad snapshot → current 48 + status totals → paint
新数据集：cached shell → current 48 → paint → status totals incremental patch
~~~

- `9fff42df` — 后端 snapshot 普通缓存命中直接返回；authoritative rebuild 的 project counts 使用 request-local map，每项目最多一次；新 snapshot 写回 `_V53_BOOTSTRAP_SNAPSHOT`。标签 schema GET 使用 `MaterialRepository.label_usage()` 聚合既有 material summary，不再 `load_images()`、逐图 `read_annotation()` 或 GET 时 patch。
- `2e3a726b` — `loadCore412({authoritative:false})` 默认不带 `refresh=true`；启动移除第二次 broad refresh；显式刷新仍 authoritative。snapshot 中已有的 jobs/model_configs 不再由 `extras412()` 重复请求；jobs 实时性继续由现有 TrainingTask/Algorithm runtime 与 PollRegistry 负责。v61 分页当前页先绘制，辅助 totals 后补，并保留 epoch/single-flight stale guard。

修复前后同一 Playwright Network 采样：

| 场景 | 修复前 | 修复后 |
|---|---:|---:|
| 冷启动 | 10 请求；2 snapshot；含 `refresh=true`；约 998ms | fresh cache：4 请求、约 542ms；snapshot 过期触发页面 owner SWR：8 请求、约 353ms；两者均仅 1 snapshot 且无 `refresh=true` |
| 算法列表 | 0 新请求；约 35ms | 命中新 snapshot cache 时 0；约 32ms；过期后由 AlgorithmListRuntime SWR |
| 训练任务 | 1 jobs；约 144ms | 1 jobs；约 147ms；无 broad snapshot |
| 数据集 | 6 请求；约 145ms | 4 请求；约 27–30ms；当前 48 条优先可见 |
| 服务节点 | 1 请求；约 126ms | 1 请求；约 48ms；只请求 service-nodes |

标签读取 10,000 条临时 SQLite 素材的简单计时：全量 material 对象水合约 `86.9ms`，仓库内 label 聚合约 `30.5ms`；更重要的是普通 GET 的 annotation 文件读取次数从“缺 summary 时最多 N 次”降为 0。

验收：API 定向 `5 passed`；前端定向 `12 passed`；Network + 数据集分页/缓存 + 服务节点 owner browser smoke `4 passed`。未跑 1200+ 全量 pytest、完整 integration 或等待 Actions。`VERSION.txt = 42.24.0` 未改；未 merge/tag/release/deploy。

接手不要根据下面旧 NEXT 重复 broad refresh/owner 改造。下一步只需核对 live remote 是否包含 `9fff42df`、`2e3a726b` 与随后文档提交；若要推送或等待 Actions，需按用户当时指令执行。

更新时间：2026-09-21  
仓库：jorsamj/aixunlianpingtai  
长期开发分支：feature/external-algorithm-publishing  
正式版本：VERSION.txt = 42.24.0  
本文档写入前的最新代码/测试 HEAD：bc88fcdfd7a5097499a67596741b8f13018f7645

---

# 0. 2026-09-21 P0 产品可用性最小 owner 收口（最新，覆盖本文旧 NEXT）

本轮在隔离 worktree 的 `feature/external-algorithm-publishing` 上完成四项最小闭环；没有全面重构，没有改变 `VERSION.txt = 42.24.0`，没有 merge / tag / release / deploy，也没有等待全量 Actions。

当前本地提交链：

- `249a8b89` — 训练创建仅接受正式 durable task identity；`TaskRepository.create()` 原本已经在 SQLite commit 后才返回，因此后端无需新增第二套确认 truth。前端校验 `task_id / kind / task_type / status`，随后同步合并到唯一 `TrainingTaskRuntime`。
- `e92d6c00` — `NavigationStability` 增加正式 page owner registry；服务节点由 `ServiceNodeRuntime` 在同一次 navigation commit 直接接管。`#title.textContent` 和 MutationObserver 不再承担路由职责，未知页面只能显示中性 skeleton。
- `89c04070` — 创建训练先同步显示 modal shell，再并行 hydration 训练配置、推荐配置和外部算法 preflight；复用现有 open epoch / shell identity stale guard，关闭、切换算法、连续打开均不能被旧响应覆盖。
- 当前 handoff 提交包含训练素材标注框收口：列表 API 仅对当前分页 IDs 调用一次 `AnnotationRepository.get_many()`；返回 `image_id / width / height / annotation_state / boxes`；前端使用 `object-fit: contain + SVG viewBox=原图坐标`，并严格区分 `annotated / confirmed_empty / unannotated`。

本轮关键验收合同：

~~~text
durable create response
→ validate task_id/kind/task_type/status
→ TrainingTaskRuntime.acceptCreatedTask
→ success toast
→ 当前 owner 的一次并行列表刷新（不是 durable 轮询确认）

setPage
→ state.page
→ NavigationStability page owner
→ target shell/cache

click create training
→ immediate modal shell
→ parallel hydration + stale guards

current picker page IDs
→ one AnnotationRepository.get_many
→ contain image + source-coordinate SVG
~~~

已完成的轻量证据：

- 训练 durable response / runtime 定向前端测试与创建 API durable commit 测试通过。
- Navigation owner 定向测试通过；浏览器 `服务节点 → 训练任务 → 数据集 → 服务节点` 无错误业务页闪现。
- Training create hydration 定向测试通过；延迟配置接口时 modal shell 仍在 1 秒内可见。
- Training material picker API 5 tests、前端 8 tests 通过；浏览器可见真实框、contain 与原图 viewBox。
- 创建训练浏览器 smoke 证明正式 `task_id` 立即进入 `TrainingTaskRuntime`，成功阶段没有新增轮询链，并在 F5 启动快照后仍存在。

接手时不要根据本文后面的旧 NEXT 重复这四项。下一步只需要先读取真实远端 HEAD，并确认这些本地提交是否已 push；未获授权不要自行部署。Actions 未在本轮等待，不能宣称最终 HEAD CI 全绿。

---

# 1. Codex 接手后的第一条规则：先重新读取真实状态

**不要一上来改代码。不要仅凭本文 SHA 假定远端没有变化。**

接手时必须先确认：

1. feature/external-algorithm-publishing 当前真实远端 HEAD；
2. VERSION.txt；
3. 最近至少 15 个 commits；
4. 当前 GitHub Actions / workflow 状态；
5. git diff / 工作树是否干净；
6. 本轮相关测试是否已经由服务器在最新 HEAD 上重新执行；
7. 本文件、docs/PROJECT_HANDOFF_CURRENT.md、docs/CODEX_CURRENT_STATE.md；
8. 如果准备部署，再重新确认服务器 /data/platform/current，不要沿用旧会话中的 symlink 结论。

本文记录的 bc88fcd... 是**文档提交前最后一个代码/测试提交**。后续若只是 handoff 文档提交，生产代码可能仍等价于 bc88fcd...；但仍必须用 GitHub compare 确认。

---

# 2. 绝对约束

这些约束目前都没有取消：

- 不 merge main。
- VERSION.txt 必须保持 42.24.0。
- 不 tag。
- 不 release。
- 未完成最终验收前，不切 /data/platform/current。
- Windows 11 开发端 + NVIDIA Linux 生产端必须同时兼容。
- 禁止硬编码 Windows 本机路径。
- 禁止为了通过测试：
  - 删除测试；
  - 放宽断言；
  - 降低阈值；
  - 增加无依据 timeout；
  - 恢复已经废弃的 legacy owner；
  - 把真实并发问题用 Python 全局粗锁掩盖。
- 前后端必须使用一致的数据结构、状态枚举和真实 API。
- 生产页面不能使用假数据冒充真实状态。
- 现有单一 owner 必须继续复用：
  - TaskRepository
  - Scheduler / Central Assignment
  - Agent execution lease
  - Worker runtime
  - PollRegistry
  - Navigation owner
  - GPU admission / reservation truth
  - Storage Provider
  - MaterialRepository
  - AnnotationRepository
  - AlgorithmSqlStore
  - Training Runtime
  - Conversion Runtime
- 不建立第二套任务状态机、第二套 SQLite truth、第二套前端 polling owner。

用户对 Actions 的明确要求：**不要因为几十个 workflow 排队就停工等待**；可以继续做有价值的工作，但最终不能把 queued/pending 写成 passed，也不能在最终 HEAD 相关 gate 没完成时宣称 deploy-ready。

---

# 3. 当前阶段：不是重新设计架构

平台当前阶段是：

> **产品可用性 + 训练真实性 + 新畅联对接 + 性能 + UI/runtime owner 收尾**

不是重新设计中央主控、多节点、训练架构。

已有架构继续使用：

~~~text
中央 TaskRepository
→ Scheduler / CentralTaskAllocator
→ Node Assignment
→ Agent Execution Lease
→ Worker / Agent Runtime
→ server-confirmed result/artifact
→ durable finalization
~~~

远端 Agent 不直接访问中央 SQLite / NFS；不要把现有 portable execution 退回共享文件系统模式。

---

# 4. 当前最新测试现场：最重要

## 4.1 最近一次完整 integration 实跑

用户在服务器 release：

~~~text
/data/platform/releases/0fc6acd5261ddc2a5c4ee81f1f2444a53d15aa11
~~~

执行 integration 后得到：

~~~text
2 failed
45 passed
1 skipped
6 warnings
~~~

失败：

~~~text
tests/integration/test_storage_import_progress_truth.py::
  test_confirmed_storage_import_reports_monotonic_indexing_progress

tests/integration/test_training_completed_job_recovery.py::
  test_completed_training_job_recovers_without_retraining
~~~

这两个失败随后确认都属于 **测试 fixture / test control 已落后于正式生产合同**，没有证据要求修改生产代码。

### 失败 1：Storage Import indexing progress

旧测试：

~~~python
monkeypatch.setattr(import_tasks, "BATCH_SIZE", 1)
~~~

但当前真实索引 owner 已经是：

~~~python
INDEX_BATCH_SIZE = 50
batch = store.pending_index_batch(INDEX_BATCH_SIZE)
~~~

BATCH_SIZE 只控制扫描 / Provider 分页，不控制确认后的 indexing batch。

因此测试只能捕获一个 indexing progress：

~~~text
[99.0]
~~~

而测试本意是强制两个 batch 验证中间进度。

已修为：

~~~python
monkeypatch.setattr(import_tasks, "INDEX_BATCH_SIZE", 1)
~~~

相关提交：

~~~text
31728b54e143826989d126070bf14fb43c36b68a
test(storage): drive confirmed indexing with index batch size
~~~

严格断言没有降低：

~~~python
assert len(indexing_progress) >= 2
assert indexing_progress == sorted(indexing_progress)
assert indexing_progress[0] > 50
assert indexing_progress[-1] == 99
~~~

### 失败 2：Completed Training Recovery 仍伪造旧 snapshot

旧 integration fixture 只写：

~~~text
snapshot.json
  schema_version = 3
  snapshot_id
  counts...
~~~

但缺：

~~~text
dataset_revision_id
dataset_revision_schema_version
canonical_annotation_schema_version
~~~

同时 portable bundle 仍使用：

~~~text
manifest.json
  schema_version = 2
~~~

而当前正式 TrainingHandler._finalize_completed_job() 明确 fail closed：

~~~python
dataset_revision_id = str(snapshot.get("dataset_revision_id") or "")
if not dataset_revision_id:
    raise RuntimeError(
        "completed training is missing its durable dataset revision"
    )
~~~

随后还会执行：

~~~python
verify_portable_dataset(work/bundle/manifest.json)
~~~

因此旧 fixture 已不代表正式 Training V3。

测试现在使用正式 helper：

~~~python
from platform_core.snapshots import (
    dataset_revision_document,
    ensure_dataset_revision,
)
~~~

生成：

~~~text
snapshot.json
dataset-revision.json

work/bundle/snapshot.json
work/bundle/dataset-revision.json
work/bundle/manifest.json (schema_version = 3)
work/bundle/dataset/data.yaml
~~~

manifest 包含：

~~~text
snapshot_id
dataset_revision_schema_version
canonical_annotation_schema_version
dataset_revision_id
snapshot_ref
snapshot_sha256
dataset_revision_ref
dataset_revision_sha256
data_yaml_ref
splits
~~~

并且 completed job 现在显式携带同一个：

~~~text
snapshot_id
dataset_revision_id
~~~

最后算法版本断言也不再读取旧 algorithms.json，而是：

~~~python
from platform_core.algorithms import list_algorithms

versions = list_algorithms(project / "algorithms.json")[0]["versions"]
~~~

因为当前正式 owner 是 AlgorithmSqlStore / algorithms.sqlite3。

相关提交：

~~~text
7d5923dead4b861302d2abeb88ed06ed8780c368
test(training): upgrade completed recovery fixture to V3 dataset truth

bc88fcdfd7a5097499a67596741b8f13018f7645
test(training): keep recovered job revision lineage explicit
~~~

## 4.2 这两个修复尚未在服务器重新验收

**非常重要：截至本文档写入时，不要写成已经通过。**

下一步 Codex 第一优先动作应是，在最新 HEAD 对应 release 中先跑：

~~~bash
PYTHONPATH=. \
/home/vipuser/miniconda3/envs/mc-platform/bin/python \
  -m pytest -vv \
  tests/integration/test_storage_import_progress_truth.py \
  tests/integration/test_training_completed_job_recovery.py
~~~

要求：

~~~text
2 passed
0 failed
~~~

然后：

~~~bash
PYTHONPATH=. \
/home/vipuser/miniconda3/envs/mc-platform/bin/python \
  -m pytest tests/integration -q --tb=short
~~~

预期目标：

~~~text
47 passed
1 skipped
0 failed
~~~

只有这一阶段完成，才进入部署前检查。

---

# 5. AlgorithmSqlStore：本轮最关键真实故障与修复

## 5.1 真实故障

服务器曾出现：

~~~text
tests/unit/test_algorithms.py::
test_concurrent_training_finalizers_do_not_overwrite_versions

sqlite3.OperationalError: database is locked
~~~

完整 traceback 的真实底层：

~~~text
platform_core/algorithm_sql_store.py:39

conn.execute("PRAGMA journal_mode=WAL")
sqlite3.OperationalError: database is locked
~~~

失败只有约 0.21s，证明不是 BEGIN IMMEDIATE 等待 30 秒后失败，而是两个 finalizer 在普通连接初始化时同时触碰 persistent journal state。

旧错误实现：

~~~python
def _connect(self):
    conn = sqlite3.connect(self.db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn
~~~

问题：

1. 每个连接都执行 journal_mode=WAL；
2. busy_timeout 甚至在 WAL transition 之后设置；
3. 两个训练 finalizer 可以在连接阶段竞争，不等到正常 writer transaction。

## 5.2 正式修法

没有：

- 增加 timeout；
- 给 attach_version() 外层加全局线程锁；
- 把两个 finalizer 整体串行化。

而是拆分 SQLite 生命周期：

~~~text
普通 _connect()
→ busy_timeout
→ foreign_keys
→ synchronous
→ 不碰 journal_mode
~~~

~~~text
ensure_ready()
→ read-only fast probe
→ 未初始化/不确定时才进入 AlgorithmSqlStore 自己的 .init.lock
→ 检查/必要时设置 WAL
→ schema bootstrap
→ legacy algorithms.json → SQLite migration
→ schema metadata
→ release init lock
~~~

然后正常：

~~~text
Finalizer A
→ BEGIN IMMEDIATE
→ attach_version
→ commit

Finalizer B
→ busy_timeout 等待
→ BEGIN IMMEDIATE
→ attach_version
→ commit
~~~

核心提交：

~~~text
8d065526770897886fb7866116c0153ec962ee1e
fix(algorithms): isolate WAL initialization from CRUD connections

5c03bf4f38fb5e617dadd0b4ba06ffdec8750d63
test(algorithms): guard WAL lifecycle and concurrent finalizers

1df0235a408e174f26c11456a93cae700401d8f6
perf(algorithms): skip repeated schema bootstrap after init

3f7f062df2080f5fd36478bc9ec3dc8050700a1c
test(algorithms): keep schema bootstrap initialization-only
~~~

## 5.3 Algorithm Store 后续性能优化

又进一步做了：

### ready fast path 不再每次抢 FileLock

已初始化数据库先使用短时只读 probe：

~~~text
db exists
→ journal_mode == wal
→ schema_version current
→ legacy_json_migrated == 1
→ return
~~~

无法证明 ready 才拿 .init.lock。

### read_all N+1 → 固定 3 个 SQL

旧：

~~~text
1 x algorithms
N x versions
N x analyses
~~~

新：

~~~text
1 x algorithms
1 x all versions for project
1 x all analyses for project
→ Python grouping
~~~

### schema v2

Algorithm store 内部 schema 从 1 升到 2，只加索引，不重写业务数据：

~~~text
idx_algorithms_project_sort
(project_id, sort_index, created_at, id)

idx_analyses_algorithm_sort
(algorithm_id, sort_index, external_analysis_id)
~~~

核心提交：

~~~text
e18cb4808567637fbdfae136b773e26794da9587
perf(algorithms): remove init lock and N+1 reads from hot path

4d037d6ed3e61fa6859d09bcdf3ea02272c2e2bb
test(algorithms): guard lock-free readiness and constant-query listing

6fd976c6f59105b37ee5e8bf31b9fe6fa3adc831
perf(algorithms): add list-order indexes in schema v2

38450d9589c7975527a601e218cd6575e1d2b785
test(algorithms): cover in-place schema v2 index upgrade
~~~

---

# 6. SQLite 生命周期已经统一到 5 个核心 owner

AlgorithmSqlStore 暴露问题后，横向审计发现：

~~~text
AnnotationRepository
MaterialRepository
TaskRepository
~~~

也有同型问题：普通 _connect() 每次执行 PRAGMA journal_mode=WAL。

本轮已经统一改成：

~~~text
普通 _connect()
→ busy_timeout / foreign_keys / synchronous
→ 不写 journal_mode
~~~

初始化：

~~~text
PRAGMA user_version fast path
→ 未 ready 才 .init.lock
→ 检查/设置 WAL
→ schema / additive migration
→ PRAGMA user_version
~~~

当前 5 个核心 SQLite owner 的目标状态：

~~~text
AlgorithmSqlStore          ordinary _connect: no WAL write
AnnotationRepository       ordinary _connect: no WAL write
MaterialRepository         ordinary _connect: no WAL write
TaskRepository             ordinary _connect: no WAL write
ResourceDiscovery Cache    ordinary _connect: no WAL write
~~~

每个模块中的 PRAGMA journal_mode=WAL 只允许留在初始化 owner。

提交：

~~~text
779f876dc39aae13e83b8f3fd45a88bb2c22725a
fix(annotations): isolate WAL and schema initialization

6abec5c07ce652725166e64df6ed5be76e03c659
fix(materials): isolate WAL and schema initialization

f44b07d71a76c666c32bbc5ee1d18b06263f3fa3
fix(tasks): isolate WAL and schema initialization
~~~

永久测试：

~~~text
9d3b7cf04ac8ab05b8caa9018743f46073ef2e07
test(materials): guard SQLite lifecycle and migration concurrency

159f6ee626c7cffcd95a0095056d6a2762c1ee47
test(tasks): guard SQLite initialization lifecycle

4b153498e244e315e2e62c08b9ebdfbb3a877047
test(annotations): guard SQLite initialization lifecycle
~~~

---

# 7. MaterialRepository legacy migration 并发修复

原逻辑可能出现：

~~~text
Process A: 判断 materials 为空
Process B: 判断 materials 为空
A/B 同时准备 images.json → SQLite
~~~

现在：

~~~text
steady-state fast check
→ 未迁移才读 images.json
→ BEGIN IMMEDIATE
→ 事务内再次检查 migration marker + material count
→ 只有真实第一个 writer 执行 migration
~~~

这样同时启动两个进程也只迁移一次。

同时保留性能 fast path：

~~~text
已完成 migration
→ 不再每次构造 MaterialRepository 都重新读取大型 images.json
~~~

提交：

~~~text
ace0dcb9dc16540f31cb535fe32d5f23671aa694
fix(materials): serialize legacy migration at writer boundary

7c544984ff5fed8d8e9be6c3e2badd9d4cb092c8
perf(materials): keep legacy migration fast path race-safe

0fc6acd5261ddc2a5c4ee81f1f2444a53d15aa11
test(materials): guard migrated legacy fast path
~~~

---

# 8. AnnotationRepository 批量读取性能修复

旧 get_many()：

~~~text
SELECT ... WHERE image_id IN (...)
→ 对每个 SQLite miss 调 self.get()
→ 每个 miss 再开连接 + 再查 SQLite
~~~

100 个未持久化/legacy image 最坏会产生额外约 100 次 SQLite round-trip。

现在：

~~~text
一次 batch SELECT 已经证明 SQLite 不存在
→ miss 直接走 legacy JSON fallback
→ 不再二次查 SQLite
~~~

提交：

~~~text
f75f2a4a44f70a61dd8998b80809f464eb9b167f
perf(annotations): remove missing-row N+1 lookups

9d9ca86efcf8a67b8b1ea0fa57c0e50b0c489e07
test(annotations): guard batch lookup against N+1 regressions
~~~

这和用户长期反馈“标注弹框很卡”直接相关，但前端 DOM/Chrome 性能仍需后续最终验收。

---

# 9. ResourceDiscovery spawn 故障：不要再误修生产 SQLite

服务器曾出现 ResourceDiscovery 并发测试所有 spawn child：

~~~text
exitcode=1
stage=not_entered
~~~

关键 A800 证据：

~~~text
tests =>
/home/vipuser/miniconda3/envs/mc-platform/lib/python3.12/site-packages/tests/__init__.py

tests.unit => None

tests.unit.test_resource_discovery_sqlite_lifecycle
=> ModuleNotFoundError
~~~

真实根因：

> multiprocessing spawn child 尝试重新 import pytest test module，但环境中的第三方 site-packages/tests 抢占了 tests 包名；child 根本没进入 worker target。

因此当时的 _queue.Empty **不能证明 ResourceDiscovery SQLite/FileLock 有故障**。

正式修复：

新增正常可 import 的支持包：

~~~text
test_support/__init__.py
test_support/resource_discovery_spawn.py
~~~

spawn target 从测试模块移出。

严格测试语义保持：

- start method = spawn
- process count = 8
- overall result deadline = 40s
- child gate = 15s
- generation 必须精确 1..8
- journal mode 必须全是 wal
- child exit code 必须 0
- 不切 fork
- 不增加 timeout

关键提交：

~~~text
4549426deddb6b8f1a818a9db345c56566b67ca3
test(support): add importable spawn helper package

9767685c6c39d790517eeceb65b87fcc4c288bcf
test(discovery): move spawn worker to importable helper

e5a075a6ceb0c4951f4c8aeffc29f6e2c92fe303
test(discovery): use importable spawn worker target

5f8a755a8fcf915c874e0344bd45108fb3900529
ci(discovery): track importable spawn helper
~~~

**不要因为旧 stage=not_entered 症状继续修改 platform_core/resource_discovery/cache.py。**

ResourceDiscovery 本身目前已经采用：

~~~text
ordinary _connect: no WAL transition
schema/user_version fast path
FileLock only for initialization
~~~

只有新证据证明 worker 已经进入 stage >= entered 且卡在真实 cache/transaction，才考虑生产修复。

---

# 10. MaterialStore legacy JSON cache 修复

旧 MaterialStore JSON fallback 使用文件 metadata 判断缓存变化，A800 证明只比较 mtime/size 等可能漏掉“metadata 相同但内容被重写”。

现在 signature 包含 SHA-256 内容指纹：

~~~text
mtime_ns
ctime_ns
size
inode
dev
sha256
~~~

关键提交：

~~~text
f6824d565ce429e54fb76e447a6031f3a84484c5
fix(materials): fingerprint legacy JSON cache contents

53b03b77a18a47e362491bbc35b9fa7589e5d527
test(materials): cover same-metadata content rewrite
~~~

MaterialRepository SQLite 已存在时仍是正式 owner；SHA256 主要保护 legacy JSON fallback。

---

# 11. 本轮 10 个 API/ZIP 失败：共同根因与当前正确路径

服务器曾一次报告：

~~~text
FAILED tests/api/test_material_batching.py::...
FAILED tests/api/test_model_configs.py::...
FAILED tests/api/test_v19_import_failure_rollback.py::...
FAILED tests/api/test_video_tasks.py::...
FAILED tests/api/test_zip_processing_p1.py::...
FAILED tests/api/test_zip_processing_p2b_single_final_annotation.py::...
FAILED tests/api/test_zip_processing_p2c_structured_single_final_annotation.py::...
~~~

## 11.1 Annotation truth vs material projection

当时 7 个失败来自同一错误设计：

> 把 annotation truth 和 material projection 都延迟到 _v50_end_image_batch() 才一次 upsert_many。

正式合同实际上分两类。

### Structured YOLO / COCO / VOC

已经知道最终 GT：

~~~text
annotation_builder
→ final annotation
→ AnnotationRepository.upsert()
→ 每张图片一次最终 truth
~~~

禁止：

~~~text
unannotated
→ final annotation
~~~

双写。

### Plain JPG/PNG 多图上传

没有最终 GT，只需要初始占位：

~~~text
deferred unannotated placeholders
→ batch end
→ AnnotationRepository.upsert_many()
~~~

这样既保持普通多图上传性能，也不破坏 structured import 的“每图一次最终 GT”合同。

如果 batch 中某图片随后被显式写入最终 annotation，必须先移除它尚未提交的 deferred unannotated 占位，防止覆盖最终 truth。

## 11.2 rollback / save=False

新图片 annotation 已经 durable 时：

~~~text
save=False / dataset deleted / import worker failure
→ cleanup removes:
   file
   annotation SQLite truth
   legacy annotation JSON if any
~~~

material row 未 commit 则不残留。

## 11.3 model_configs bootstrap

_v53_build_snapshot() 已补 model_configs，且使用 secret sanitizer，不把真实 API key / secret_ref 暴露给前端。

## 11.4 unified task public contract

task_to_public() 现在同时保留：

~~~json
{
  "kind": "VIDEO_FRAMES",
  "task_type": "VIDEO_FRAMES"
}
~~~

task_type 是当前统一字段，kind 是既有 API 兼容字段。

## 11.5 V19 label_mapping fixture

正式 importer 已支持：

~~~python
label_mapping: Optional[Dict[str, str]] = None
~~~

旧测试 monkeypatch 不接受该参数，所以测试提前死于 unexpected keyword argument 'label_mapping'。

修测试 fixture，不在生产代码增加 TypeError fallback。

相关提交：

~~~text
e2c334f47b8e69e84dc7d5a398c4d0f4709a5a1
fix(import): keep annotation truth durable within material batches

551ce05fd6e29339c191e721664047f825f5acac
fix(tasks): preserve public kind compatibility field

4416ba5196a479283a508b168a30db38090b8373
test(import): sync rollback fixture with label mapping contract

b261bc915e19cc574e101c9fa16777a43691b98a
test(tasks): lock kind compatibility in public projection
~~~

---

# 12. 旧 13 项失败进一步收口

在后续完整测试中又暴露/回看了 rollback、conversion、dataset recovery、training control、upload batch 等问题。

当前处理原则：

## 12.1 Algorithm rollback

产品合同已明确：

> **算法回退 = 删除当前版本，再把目标历史版本设为 current。**

因此不能恢复“delete_current_version=False 只切 pointer”的旧语义。

旧测试仍调用已经移除的 save_algorithm_assets，已迁到 SQL owner：

~~~python
from platform_core.algorithms import save_algorithms
~~~

测试也改为断言：

~~~text
current v5 被删除
target v3 成为 current
~~~

外部新畅联版本回退：
- 先调用远端 delete；
- 远端删除失败/无法确认时本地 fail closed；
- 远端 UNKNOWN 时立即重查版本列表；
- 只有确认远端版本不存在才允许继续本地删除。

## 12.2 Conversion test

Rockchip 当前产品优先支持：

~~~text
RK3568
RK3578
~~~

旧测试使用 rk3588，会在 SDK preflight 之前先被 target validation 拒绝，导致预期错误码错位。

测试改用受支持 rk3568，这样才能真实验证 RKNN_TOOLKIT_NOT_FOUND。

## 12.3 Task public queue truth + FakeRepository

task_to_public() 的 exact queue position 对真实 TaskRepository 可读取 Worker runtime。

对轻量 / read-only adapter，如果无法证明 Worker claim order：

~~~text
fail closed exactness
~~~

不能调用不存在的私有 _connect()。

## 12.4 Dataset delete recovery

AnnotationRepository.finalize_delete() 现在 crash-idempotent：

~~~text
backup row exists
actual annotation row 已经不存在
→ 视为前一次 finalize 已成功
→ recovery 继续 cleanup
~~~

但如果相同 image_id 出现新的不同 digest annotation：

~~~text
→ stale conflict
→ fail closed
→ 绝不删除新 truth
~~~

测试也改成 SQLite AnnotationRepository 是主 truth，旧 annotations/<id>.json 只有原本真实存在时才作为 legacy file 恢复。

## 12.5 stopped / failed / never-started training 不得归档版本

旧 enrich_job_runtime() 读路径会对 stopped/failed 也调用 _v48_archive_training_version()，产生“读取页面触发写副作用”。

当前只允许成功终态、且非 never_started 时归档。

---

# 13. Training V3 当前正式 truth

当前训练链已经不是只依赖 snapshot_id。

正式 durable identity：

~~~text
Snapshot
+
Dataset Revision
+
Portable Bundle Manifest V3
~~~

关键文件：

~~~text
platform_core/snapshots.py
platform_core/training_tasks.py
~~~

训练 run 正常路径会：

~~~text
build Snapshot
→ ensure_dataset_revision(snapshot)
→ persist_dataset_revision(...)
→ task/snapshot.json
→ task/dataset-revision.json
→ portable bundle:
   snapshot.json
   dataset-revision.json
   manifest.json v3
→ training job:
   snapshot_id
   dataset_revision_id
~~~

finalization/recovery 会验证：

~~~text
durable task snapshot exists
dataset_revision_id exists
completed job handshake trustworthy
bundle manifest exists
snapshot identity matches
dataset revision identity matches
dataset revision SHA matches
portable image/label evidence matches
~~~

**不要为了旧 fixture 放宽这些检查。**

---

# 14. 新畅联当前合同：不要改回旧 Header / endpoint

当前正式业务 Header：

~~~http
Authorization: Bearer <accessToken>
~~~

**不是：**

~~~http
Access-Token: <token>
~~~

历史曾经因为旧文档/测试产生混淆；当前代码、文档和 guard 都以 Bearer 为准。

Canonical 主链：

~~~text
POST /internal/auth/test-sign
POST /internal/auth/token

GET  /internal/base/category/tree
GET  /internal/base/compute-platform/listAll

GET  /internal/algorithm/product-ai/listAll
GET  /internal/algorithm/algorithm-analysis/listByProduct/{productId}

POST /internal/algorithm/algorithm-version/add
GET  /internal/algorithm/algorithm-version/listByProduct/{productId}

POST /internal/algorithm/algorithm-weight/add
GET  /internal/algorithm/algorithm-weight/listByVersion/{algoVersionId}
~~~

完整 31 项 API 目录：

~~~text
docs/CHANGLIAN_APIFOX_API_CATALOG.md
~~~

主集成说明：

~~~text
docs/CHANGLIAN_CORE_INTEGRATION.md
~~~

### 同步策略

完整 OpenAPI 没有 Webhook / SSE / subscription，因此当前是主动拉取：

~~~text
auto_sync_enabled = true
auto_sync_interval_seconds = 60
~~~

对用户可以描述“准实时同步”，不能描述成服务端 push 实时同步。

### 外部算法训练资格

只允许：

~~~text
source_type = EXTERNAL
provider = ChangLian
analysis.status == 1
analysis.analysisType == 1
~~~

缺字段、status=0、analysisType=2/3、名称猜测、只凭旧 analysis id 都 fail closed。

### 成功训练与转换发布

~~~text
训练完成
→ local algorithm version
→ canonical Model Artifact Storage
→ Aliyun OSS / configured canonical storage
→ durable public URL
→ ChangLian Algorithm Version
→ ChangLian Weight
~~~

转换：

~~~text
ONNX / RKNN conversion success
→ canonical model/conversion storage
→ same external algoVersionId
→ append Weight
→ 不重复创建算法版本
~~~

回退：

~~~text
delete remote current version
→ confirmed remote deletion
→ delete local current version
→ target historical version becomes current
~~~

---

# 15. 存储配置当前产品合同

原“素材存储配置”已泛化为“存储配置”。

两个主要区域：

~~~text
素材存储
算法与转换结果存储
~~~

算法/转换产物目标主要是 Aliyun OSS，同时保持统一 storage provider abstraction。

训练成功模型和转换结果必须有 canonical durable storage truth，不能只保存 worker 本机路径。

---

# 16. 素材导入 / 标签映射合同

用户明确需求：

不同来源可能把同一真实类别写成：

~~~text
toukui1
toukui2
helmet
~~~

平台官方标签应由用户确认映射，例如：

~~~text
toukui1 → 安全头盔
toukui2 → 安全头盔
helmet  → 安全头盔
~~~

规则：

- YOLO / COCO / VOC 外部标签只是 source label；
- 不能静默当作平台官方 label；
- 批量上传后需要映射确认弹窗；
- 映射需要可批量统一修改；
- 映射过程需要真实进度；
- AI 自动标注完成后也不能直接正式入库；
- 用户二次确认后才进入正式 annotation truth；
- AI 结果同样允许批量修改标签名/映射。

当前批量 annotation 写路径务必维持第 11 节描述的 plain upload / structured import 双路径，不要重新统一成错误单路径。

---

# 17. 用户当前产品问题清单及代码状态

以下是 9 月 20 日用户提出的主要产品问题。Codex 接手时不要重新从零问需求。

## 17.1 服务节点测试联通显示未连接

目标：

- network_reachable 与 heartbeat_online 分离；
- 测试联通成功不代表 Agent 已注册在线；
- UI 要把“接口可达”和“节点心跳在线”解释清楚。

已有修复较多，仍需真实浏览器/生产节点最终验收。

## 17.2 训练成功率总是 0

成功率定义：

~~~text
成功结束训练数 / 已结束训练数
~~~

不要把正在训练/排队任务当失败计入 denominator。

核心逻辑已处理，仍应在真实训练数据验收。

## 17.3 算法列表和训练任务 UI 太丑

已多轮优化，但用户仍非常重视。

原则：

- 正式；
- 简洁；
- 普通用户能理解；
- 不堆技术字段；
- 关键状态/操作清晰；
- 前后端 truth 一致。

后续值得继续做：Real Chrome 下算法列表/训练任务的 DOM、重复请求、缓存命中和重绘性能。

## 17.4 删除最后一个框后要求“确认无目标”

正式语义：

~~~text
删除最后一个 box != confirmed_empty
~~~

必须用户显式“确认无目标”后才是：

~~~text
annotation_state = confirmed_empty
~~~

后端 fail closed。

## 17.5 标注弹框卡

已做：

- 单 workbench；
- current-only；
- 局部更新；
- 避免全页 refresh；
- AbortController；
- AnnotationRepository get_many() N+1 修复。

仍建议最终 Real Chrome profile。

## 17.6 训练控制

需要真实支持：

~~~text
开始
排队
插队
暂停
继续
停止
删除
失败恢复
完成
版本归档
实时日志
durable task truth
~~~

远程 stop 必须远端 ack 后才把本地改成 stopped，不可先改本地假成功。

## 17.7 右下角素材导入黑色气泡/弹窗

已有 UI 修复。

## 17.8 数据导入“清空”

只清：

~~~text
done
failed
cancelled / canceled
~~~

不清 active task。

## 17.9 页面感觉需要点两下/切回来又重载

当前已有：

~~~text
NavigationStability
PageRequestScope
PollRegistry
cache-first
stale request abort
~~~

但最终 owner/performance audit 仍 OPEN。

---

# 18. 训练弹窗 UI 用户明确偏好

不要重新设计成多步骤 wizard。

要求：

- 取消“步骤 1/2/3”；
- 保留“进阶配置”；
- 基础项：
  - train/val/test 比例；
  - epochs；
  - batch；
  - image size；
  - learning rate / optimizer；
  - random seed；
  - freeze layers；
- 标签选择放在原“数据集预览”区域；
- 标签只显示名称；
- 可搜索/多选；
- 不显示缩略图；
- 不显示“xx张”；
- 保留“数据质量”按钮；
- 删除预计时长；
- 删除训练完成后通知；
- 训练摘要显示：
  - 轮次；
  - 数据规模；
  - 标签数；
  - best mAP；
  - PR 曲线入口。

Rockchip 第一阶段只优先：

~~~text
RK3568
RK3578
~~~

---

# 19. Frontend owner 规则

判断前端 owner 不能只 grep 一个函数名。

必须按真实 load order：

~~~text
static/index.html
→ static/app.js
→ static/main.mjs
→ later modules
→ final window.xxx owner
~~~

重点文件：

~~~text
static/index.html
static/app.js
static/main.mjs

static/modules/task-runtime-truth.js
static/modules/training-task-runtime.js
static/modules/training-task-visibility-runtime.js
static/modules/algorithm-list-runtime.js
static/modules/navigation-stability.js
static/modules/service-node-runtime.js
static/modules/annotation-workbench.js
static/modules/upload-task-center.js
static/modules/zip-import-runtime.js
static/modules/external-algorithm-platform.js
static/modules/external-algorithm-publish.js
~~~

函数存在不代表实际 owner。必须检查最后赋值、load order、runtime decorator。

---

# 20. Backend 重点 owner

~~~text
app.py

platform_core/algorithm_sql_store.py
platform_core/algorithms.py

platform_core/annotation_repository.py
platform_core/material_repository.py
platform_core/material_store.py

platform_core/storage/import_tasks.py

platform_core/training_tasks.py
platform_core/snapshots.py
platform_core/training_job_projection.py

platform_core/task_runtime/
platform_core/service_nodes.py

platform_core/external_algorithm_platform.py
platform_core/external_algorithm_publish.py
~~~

不要新增同用途的新 repository / scheduler / poller。

---

# 21. 其它本轮已关闭/已解释问题

## 21.1 Cross-platform source guard docstring false positive

曾因 docstring 里出现 Windows drive-root literal 被 guard 误报。

只修改 prose，不放宽 guard。

提交：

~~~text
0050a09102e1abe8b867b094f46e1d9ad82371b3
~~~

## 21.2 Provider parsing fixture

正式 parser 要求 exact alias equality。旧 test 用“火”期待命中“明火”错误。

修 fixture，不把生产 parser 改成 fuzzy match。

提交：

~~~text
7a817822101c2454a499ae8aa784ac766c4fff5e
~~~

## 21.3 runtime path helper

Linux test 不再 monkeypatch 全局 os.name 导致 pathlib 试图构造 WindowsPath。

现在通过：

~~~python
def _is_windows():
    return os.name == "nt"
~~~

测试 patch helper。

提交：

~~~text
4c7185e1571b5674c043fe72092930975077fb4d
7836a55af0b85e4fd440f13d06f98e8e08957d9c
~~~

## 21.4 Training hardening stale exact-class test

当前 production owner：

~~~text
ProductionTrainingHandler
→ CheckpointResumeRecoveryHandler
→ RecoveryHardenedLabelContractTrainingHandler
→ HardenedLabelContractTrainingHandler
~~~

旧 test 不应要求精确等于旧 class，只验证 owner/inheritance/hardening。

提交：

~~~text
0efd28f43fe1ab24248aefce07d578f7e226058e
~~~

## 21.5 TaskKind stale exact-list test

生产早已增加：

~~~text
RESOURCE_DISCOVERY
MATERIAL_BATCH
TRAINING_PREPARE
~~~

旧精确 list 断言已更新。

提交：

~~~text
9babe8ffedfe1da43dec27fcfcad563747151136
~~~

## 21.6 ExternalAlgorithmAutoSyncReporter race

修了 reporter thread reserve/start race，不允许同时生成两个 auto sync thread。

关键提交：

~~~text
ec6bab42f405aba7e0c6f409b2cb9504ade3b9f9
2d44dfebe39efeece8819260ec9da091b0dce983
~~~

---

# 22. 服务器环境与部署背景

历史已知生产环境：

~~~text
Ubuntu 22.04
NVIDIA A800-SXM4-40GB
约 16 CPU
约 32 GB RAM
~~~

平台 Python：

~~~text
/home/vipuser/miniconda3/envs/mc-platform/bin/python
~~~

YOLO：

~~~text
/home/vipuser/miniconda3/envs/yolo/bin/python
~~~

正式服务名历史为：

~~~text
changlian-web.service
changlian-worker.service
~~~

Web 历史监听：

~~~text
127.0.0.1:8010
~~~

正式代码目录惯例：

~~~text
/data/platform/releases/<sha-short>
/data/platform/current
~~~

业务数据：

~~~text
/data/platform-data
~~~

**注意：不要依据旧文档直接宣称当前 symlink 仍指向某旧 SHA。部署前必须重新在服务器确认。**

最近用户的 pytest traceback 已明确来自 candidate：

~~~text
/data/platform/releases/0fc6acd5261ddc2a5c4ee81f1f2444a53d15aa11
~~~

这说明 0fc6acd... 至少被用于服务器测试，但不等于 /data/platform/current 已正式切过去。

---

# 23. 当前部署门槛

截至本文档写入：

**部署仍 BLOCKED。**

最短正确顺序：

## Phase A — 验最后两个 integration fixture

~~~bash
PYTHONPATH=. \
/home/vipuser/miniconda3/envs/mc-platform/bin/python \
  -m pytest -vv \
  tests/integration/test_storage_import_progress_truth.py \
  tests/integration/test_training_completed_job_recovery.py
~~~

必须：

~~~text
0 failed
~~~

## Phase B — 完整 integration

~~~bash
PYTHONPATH=. \
/home/vipuser/miniconda3/envs/mc-platform/bin/python \
  -m pytest tests/integration -q --tb=short
~~~

目标：

~~~text
47 passed
1 skipped
0 failed
~~~

## Phase C — 如最新 HEAD 还未验证 SQLite focused tests

建议至少确认：

~~~bash
PYTHONPATH=. \
/home/vipuser/miniconda3/envs/mc-platform/bin/python \
  -m pytest -vv \
  tests/unit/test_algorithm_sql_store.py \
  tests/unit/test_algorithms.py::test_concurrent_training_finalizers_do_not_overwrite_versions \
  tests/unit/test_annotation_repository_sqlite_lifecycle.py \
  tests/unit/test_material_repository.py \
  tests/unit/task_runtime/test_repository.py
~~~

## Phase D — worker check

integration 全绿后：

~~~bash
PYTHONPATH=. \
/home/vipuser/miniconda3/envs/mc-platform/bin/python task_worker.py --check
~~~

## Phase E — 部署前生产检查

1. 检查当前 active tasks；
2. 检查是否有 training / import / conversion 正在 finalization；
3. 生产数据备份；
4. 新建 candidate release，不覆盖现有回滚版本；
5. candidate Web / Worker 启动；
6. 健康检查；
7. GPU truth；
8. SQLite truth；
9. 新畅联：
   - test-sign
   - token
   - category
   - product
   - analysis
   - compute-platform
10. 真实训练/转换必要 smoke；
11. 最后才决定是否原子切 /data/platform/current。

---

# 24. 当前 GitHub Actions 判断规则

不要因为 workflow 没显示/还 queued 就当通过。

本文代码 HEAD bc88fcd... 是两个 integration test 修复后的 head；文档提交会再推进 HEAD。

Codex 必须重新读取最新 commit 的 workflow runs。

规则：

~~~text
queued != success
no run != success
old SHA green != new SHA green
focused test green != deploy-ready
~~~

用户允许不等待大量排队 Actions 再继续做有价值的静态/服务器验证，但最后部署判断必须基于最终 HEAD。

---

# 25. 当前明确 OPEN 的工作

按优先级：

## P0 — 重新跑两个 integration

就是第 23 节 Phase A。

## P0 — 完整 integration 0 failed

目标：

~~~text
47 passed
1 skipped
0 failed
~~~

若仍有新失败：
- 先判断 production regression 还是 stale fixture；
- 不先改 timeout；
- 不先放宽 assertion；
- 保留当前正式 Training V3 / SQLite owner / rollback contract。

## P0 — deployment preflight

integration 全绿后再做。

## P1 — Actions final-head evidence

无需停下来等几十个 queued，但部署前必须检查最终 HEAD。

## P1 — 新畅联真实 E2E

文档/代码合同已较完整，但真实 credential / permission / tenant scope 的生产 E2E 仍需最终验收。

## P1 — 前端真实性能

用户长期感知：

~~~text
页面点击偏慢
像要点两次
切回页面还重新加载
标注弹窗卡
算法列表 / 训练任务 UI 仍需要更好
~~~

下一轮如果后端 gate 全绿，再针对：

~~~text
Navigation
PollRegistry
duplicate fetch
stale request abort
cache hit
DOM redraw
algorithm list rendering
training task rendering
annotation modal
~~~

做 Chrome/Real Browser 性能收尾。

**不要在 integration 尚未闭环时继续扩大生产代码改动面。**

---

# 26. 当前不应该再做的事情

Codex 接手后以下行为大概率是重复/回退：

- 不要把新畅联业务 Header 改回 Access-Token。
- 不要把 canonical endpoint 改回旧裸路径。
- 不要把 PRAGMA journal_mode=WAL 放回普通 _connect()。
- 不要给 attach_version() 外层加大锁。
- 不要增加 SQLite timeout 来掩盖 WAL transition race。
- 不要把 ResourceDiscovery spawn 测试切成 fork。
- 不要因为旧 spawn stage=not_entered 修改 ResourceDiscovery production cache。
- 不要把 structured import annotation 改回统一 batch final upsert。
- 不要把 plain upload 改回每图 unannotated immediate upsert。
- 不要恢复 save_algorithm_assets legacy owner。
- 不要重新读取 algorithms.json 验证正式算法版本；用 list_algorithms() / AlgorithmSqlStore。
- 不要允许 rollback pointer-only；当前产品合同是 rollback-and-delete。
- 不要把 Training V3 的 Dataset Revision 检查降级为可选。
- 不要让 stopped/failed/never-started training 在 read projection 时归档版本。
- 不要让测试连接执行新畅联 create/edit/delete 副作用接口。
- 不要把 Agent 改回中央 SQLite/NFS 共享模式。
- 不要建立第二套前端 filter / scheduler / polling truth。

---

# 27. 推荐给 Codex 的接手执行模板

可以直接按下面顺序执行：

~~~text
1. fetch remote branch
2. confirm HEAD / VERSION / recent commits
3. read:
   docs/CODEX_HANDOFF_2026-09-21.md
   docs/PROJECT_HANDOFF_CURRENT.md
   docs/CODEX_CURRENT_STATE.md
4. inspect current Actions
5. compare latest HEAD against recorded code head bc88fcd...
6. if only docs changed:
   treat bc88fcd code state as implementation baseline
7. run the two focused integration tests
8. if green, run full integration
9. if green, task_worker.py --check
10. inspect active tasks + backup production data
11. candidate deployment validation
12. only after all evidence decide current symlink switch
~~~

若第 7/8 步失败：

~~~text
capture full traceback
→ locate exact current owner
→ distinguish stale fixture vs production regression
→ smallest correct fix
→ preserve current contracts
→ add/keep permanent regression guard
→ rerun focused tests
~~~

---

# 28. 文档读取顺序

接手推荐：

1. docs/CODEX_HANDOFF_2026-09-21.md — **当前最新现场**
2. docs/PROJECT_HANDOFF_CURRENT.md — 长期项目总览
3. docs/CODEX_CURRENT_STATE.md — 历史 Codex 状态与架构关闭记录
4. docs/CHANGLIAN_CORE_INTEGRATION.md
5. docs/CHANGLIAN_APIFOX_API_CATALOG.md
6. docs/NODE_CONTROL_PLANE_V42_25.md
7. docs/FRONTEND_OWNER_MAP_V42_25.md
8. docs/BUG_AUDIT_2026-09-17.md
9. docs/TECH_DEBT_CLOSURE_V42_25.md

历史文档中的旧 “NEXT” 不自动代表当前下一步。

---

# 29. 一句话当前状态

> **代码层已经完成一轮较大的真实故障收口：ResourceDiscovery spawn harness、MaterialStore cache truth、Annotation/Material/Task/Algorithm SQLite 生命周期、AlgorithmSqlStore 并发 finalizer、素材批量 annotation truth、dataset delete recovery、training archive side-effect、算法列表 SQL 性能等；最新 integration 仅剩的两个失败已确认是 stale test fixture，并已在 bc88fcd... 更新测试，但服务器尚未重新验证。当前第一优先级不是继续改生产代码，而是让最新 HEAD 的 2 个 focused integration + full integration 变为 0 failed，然后进入部署前验收。**
