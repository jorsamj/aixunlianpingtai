# F1 性能治理与迁移实施设计（2026-11-22）

> 继承并校准：
> - [PLATFORM_ARCHITECTURE_AUDIT_20261121.md](PLATFORM_ARCHITECTURE_AUDIT_20261121.md)（H1–H13）
> - [PLATFORM_EVOLUTION_ROADMAP_20261121.md](PLATFORM_EVOLUTION_ROADMAP_20261121.md)
> - [F0_PLATFORM_MIGRATION_BASELINE_20261122.md](F0_PLATFORM_MIGRATION_BASELINE_20261122.md)
> - [P2_DATA_OWNERS_AND_POSTGRESQL_PREPARATION_20261117.md](P2_DATA_OWNERS_AND_POSTGRESQL_PREPARATION_20261117.md)
> - [DISTRIBUTED_WORKER_CLUSTER_ARCHITECTURE_2026_10_10.md](../DISTRIBUTED_WORKER_CLUSTER_ARCHITECTURE_2026_10_10.md)
>
> 本轮只做隔离测量、R6 上传收口和设计；**未切换数据库、未改存储 Provider、未改 GPU 调度、未访问生产**。

## 1. F1-A 已取得的测量证据

### 1.1 素材库 20 万行元数据（隔离 SQLite，无图片字节）

`tests/performance/test_material_workbench_200k.py`，Windows 11 / Python 3.12.7，21 次采样，
fixture 合成 200,000 行：

| 查询 | P50 | P95 |
|---|---:|---:|
| 首页（无筛选） | 5.310 ms | 26.134 ms |
| 深页（page≈4166） | 30.259 ms | 42.777 ms |
| 来源 + 标签（source_label） | 4.232 ms | 5.985 ms |
| 文件名 LIKE（filename） | 4.232 ms | 7.866 ms |

结论：**200k 元数据分页本身不是灾难**；深页 P95 42.8ms 是当前最大的已测读尾延迟，但未包含真实 GT EXISTS、历史反连接和浏览器图片解码。
此结果只适用于该合成分布，不代表生产 P95。

### 1.2 `MaterialRepository.read()` / `mutate()` 全表成本

50,000 行同一仓库，seed 3.12s，7 次采样（可重复脚本：
`RUN_MATERIAL_READ_SCALE=1 pytest tests/performance/test_material_read_mutate_scale.py -s`）：

| 操作 | P50 | P95 |
|---|---:|---:|
| `read()` 全表反序列化 | **556.7 ms** | **662.1 ms** |
| `mutate(no-op)` BEGIN IMMEDIATE 全表规范化+diff | **1644.6 ms** | **1846.6 ms** |

DB 文件约 55.8MB。`mutate` 即使回调不修改任何行，仍持有写事务并全表 normalize/serialize；
这是 H2/H3 的**实测确认**。200k 的线性外推只能作为风险提示，未实测。

### 1.3 上传任务中心回执请求风暴（R6-2 已优化）

50 个历史会话（48 个 1 片、1 个活动、1 个 150 片）测试：

| 指标 | 旧路径（按代码计算） | 新路径（实测） |
|---|---:|---:|
| 首轮 v55 回执 GET | 149 | **120**（预算上限） |
| 第二轮（约 3–4s 后） | 149（每个会话重读） | **121**（仅活动会话 1 次） |
| 150 片会话终态 | 只读前 100 片但可能显示完成 | **UNKNOWN + “超过 100 个分片”**，不显示已入库 |

新增：per-session TTL 缓存、活动/待确认/历史分级、每轮全局 120 次上限、4 并发分块、重入锁；
历史完成会话 60s 内不重复请求，待确认 15s，活动 2.5s；部分回执不写 DONE。
该优化同时属于 F1-A 第 5 项（上传任务中心请求风暴）。

### 1.4 尚未测量

- 真实 20 万素材 + 真实 GT 分布的首页/深页/筛选；
- 缩略图冷路径在 OSS/NAS 下的 I/O 与慢客户端锁；
- 训练选材 usage/role 全池缓存在 20 万真实历史下的内存与首查；
- 2 万冻结/提交真实图片端到端；
- TaskRuntime 队列位置在其他端点的 N+1；
- 多进程/Worker 并发写下的 SQLite `busy`/锁等待。

这些是 F1 后续测量门槛，不能用本文数字替代。

## 2. F1-A 优化判断

| 热点 | 判断 | 本轮动作 |
|---|---|---|
| 上传任务中心回执风暴 | 已由 50 会话测试证明 | **已优化**（缓存+预算+并发，见 1.3） |
| H2 `read()` 全表 | 50k 实测 557ms | 不直接改；下一步把具体调用者迁到分页/`mutate_ids`，先列调用点与合同 |
| H3 `mutate()` 全表写锁 | 50k no-op 1.65s | 不直接在兼容层“猜”未变更；按调用者迁 `mutate_ids`/`patch_filtered` |
| H8 深分页 | 200k P95 42.8ms | 前端选材仍传 page；切已有 `next_cursor` 是有证据的低风险候选，但需先保留排序/筛选语义测试 |
| H10 缩略图 | 仅源码，无测量 | 先测 OSS/NAS 冷路径，不做 mtime 替代 SHA 的破坏性改动 |
| H6/H7 选材缓存 | 历史隔离有数据 | 需 20 万真实历史内存测量后再定 |

**结论**：本轮只合并已由测量证明收益的任务中心优化；不把 `read/mutate` 改成未经调用者审计的“快路径”。

### 2.1 W2 调用点清单（已审计）

| 调用点 | 类型 | 范围 | 当前接口 | 判断 |
|---|---|---|---|---|
| `PATCH /api/v12/projects/{pid}/images/{id}` dataset 分支 | HTTP 用户触发 | 单条 | 旧 `read()+mutate()` → 本次改为 `get()+mutate_ids()` | **已优化** |
| 同端点 split 分支 | HTTP 用户触发 | 单条 | `patch({id:...})` | 已定点，无需改 |
| `v20_batch_image_split` selected | HTTP 用户触发 | 选中集合 | `patch` | 已定点 |
| `v20_batch_image_split` filtered/dataset | HTTP 用户触发 | 筛选/全数据集 | `load_images` + `mutate` | 需按 filter 走 `mutate_ids`/批处理，暂未改 |
| `v12_auto_split` | HTTP 用户触发 | 数据集 | `load_images` + `mutate` + 逐图 GT | 高成本，需按数据集 id 先取候选再定点 |
| `v49_mark_processed` | HTTP 用户触发 | 显式 ids | `mutate_ids()`（<=5000）/`mutate()`（更大） | **W2.2 已优化并设阈值** |
| `v44_supplement_training_data` | HTTP 用户触发 | weak-label 候选 | `load_images` + 逐图 GT + `mutate` | 低频但高成本，下一批 |
| `_v50_end_image_batch` ZIP 导入提交 | Worker/导入 | 全批次 | `mutate(commit)` | 导入路径，需保留批次回执 |
| `_v50_restore_dataset_delete_rows` | 恢复 | 数据集删除恢复 | `mutate` | 低频运维 |
| `create_project` 清空 | 管理 | 全量 | `mutate(clear)` | 低频 |
| `load_images()` | 旧 API/Worker | 全表 | `read()` | 旧全量接口，保留兼容；新接口必须走分页 |
| `_business_material_by_name` | 路径解析 | 全表按名 | `read()` | 可用 `list_page`/摘要，待审计 |
| `remote_execution_transport` 素材 Bundle | Worker | 全量 | `read()` | 训练准备，B 阶段 |
| `video_tasks` 读素材 | Worker | 全量 | `read()` | 视频任务 |

`MaterialStore.upsert/upsert_many/patch/remove` 在 SQLite delegate 已走定点实现；只有显式 `mutate` 才是全表。

### 2.2 W2 已优化调用路径

`v12_patch_image` 的 dataset 迁移分支原本：

1. `material_store.read()` 全表反序列化找当前行；
2. 在 dataset 锁内 `mutate(apply_dataset_patch)` 全表 normalize/compare。

改为：

1. `material_store.get(image_id)` 主键查询；
2. 在相同 dataset 锁内 `material_store.mutate_ids([image_id], apply_dataset_patch)`；
3. 回调仍校验 latest `dataset_id == source_dataset_id`，CAS 冲突仍抛 `_V50DatasetSourceChanged` 并重试；
4. revision 仍由 `_bump_revision` 递增，只更新目标行。

### 2.3 W2 前后性能（50,000 行，30 次采样）

`RUN_MATERIAL_PATCH_SCALE=1 pytest tests/performance/test_material_single_patch_scale.py -s`：

| 路径 | P50 | P95 |
|---|---:|---:|
| 旧 `read()+mutate()` | **1972.69 ms** | **2197.66 ms** |
| 新 `get()+mutate_ids()` | **13.55 ms** | **27.18 ms** |

约为 **145× P50 / 81× P95** 的隔离元数据收益。样本 30；30 次 P95 仍是小样本估计，不是生产 P99。
SQL：旧路径一次全表 `SELECT` + 全表 normalize + 定点 UPDATE；新路径一次主键 `SELECT` + 一次 UPDATE + revision 更新。
数据一致性：API 测试验证仅目标行改变、第二行字节级不变、revision +1、split-only 路径不变、404/400 合同保留；
`tests/api/test_dataset_deletion_recovery.py` 12 项数据集锁/删除恢复测试通过。

> P95 口径：nearest-rank 的下取整位置 `floor(n*0.95)-1`，并保留原始样本；30 次样本仍只是小样本估计。

### 2.4 W2.2 `v49_mark_processed`

`POST /api/v49/projects/{pid}/images/mark-processed` 只接受显式 image_ids，原实现全表 `mutate`。

优化：显式集合 `<= 5000` 时使用 `MaterialStore.mutate_ids()`；更大集合保留 `mutate()`。阈值来自实测：

| 目标 ID 数 | 旧 mutate P50 / P95 | 新 mutate_ids P50 / P95 |
|---:|---:|---:|
| 1 | 1722.32 / 1746.78 ms | 10.21 / 11.48 ms |
| 100 | 1715.07 / 1774.34 ms | 29.94 / 33.70 ms |
| 1,000 | 1917.91 / 1957.21 ms | 192.86 / 215.65 ms |
| 2,000 | 2284.04 / 2308.79 ms | 413.44 / 433.91 ms |
| 5,000 | 2173.27 / 2237.86 ms | **1331.55 / 1491.03 ms** |
| 10,000 | 2942.99 / 3001.59 ms | 3453.19 / 3681.48 ms |
| 50,000 | 5921.42 / 6198.48 ms | 22574.00 / 23559.27 ms |

样本各 3 次，**50,000 行**素材库；P95=样本最大值，不是稳定 P95。5k 是实测收益边界，10k 已反转；因此**不把大集合强切到定点接口**。
业务合同：只更新显式存在的 ID；重复 ID 去重；缺失 ID 不计入 changed；只改 `processing_status/cleaned_at`；GT/负样本/split/dataset 不变；revision 仅在实际 payload 变化时递增；异常回滚由 Repository 事务保证。

### 2.5 W2.4 `v20_batch_image_split` dataset 原子事务

新增 `MaterialRepository.mutate_dataset(dataset_id, fn)`：

- `BEGIN IMMEDIATE` 内用 `COALESCE(CAST(json_extract(payload_json,'$.dataset_id') AS TEXT),'default') = ?` 选择最新成员；
- 只反序列化匹配行；非匹配行不进入 Python；
- 回调仍执行原 `match_latest/apply_split`，只允许更新字段，不允许增删/改身份；
- 变更才写行并 `_bump_revision`；异常回滚；
- 新增表达式索引 `ix_materials_dataset`，`EXPLAIN QUERY PLAN` 实测 `SEARCH materials USING INDEX ix_materials_dataset (<expr>=?)`；
- `dataset_id=None` 退化为原有全量语义。

`v20` 仅在 `scope == "dataset"` 使用 `mutate_dataset`；`filtered` 仍保留 `mutate`。

50k 行 / 7 样本：

| 匹配行数 | 旧 P50 / P95 | 新 P50 / P95 |
|---:|---:|---:|
| 100（少量） | 1796.58 / 2057.16 ms | **19.98 / 24.23 ms** |
| 5,000（中等） | 2220.21 / 2516.12 ms | **549.23 / 697.94 ms** |
| 44,899（大部分） | 5335.42 / 5573.16 ms | **4935.14 / 5114.01 ms** |

SQL 次数、RSS、事务精确持续时间：`NOT_VERIFIED`；函数耗时包含整个事务。

### 2.6 W2.3 filtered 阻塞边界

| 路径 | 处理 | 结果 |
|---|---|---|
| `selected` | `patch({id:...})` | 已定点；无全表 `read/mutate` |
| `filtered` marked/unmarked | `load_images` + annotation snapshot + `mutate` | **保留原实现** |
| `filtered` train/val/test/unassigned | `mutate` 内重算 latest split | **保留原实现** |
| `dataset` | `mutate_dataset` 事务内按最新 dataset 选择 | **W2.4 已迁移** |

`filtered marked/unmarked` 的候选还依赖正式 GT 快照；`filtered train/val/test` 仍要求在写事务内重算最新 split。
这些条件无法在现有 material 事务内与 GT 跨域快照保持一致，因此保留原实现，不拆成非原子批次；这是已审计的阻塞结论。

## 3. F1-B PostgreSQL 实施设计（不执行）

### 3.1 迁移单元（必须联合的范围）

| 单元 | 包含 | 风险 | 建议顺序 |
|---|---|---|---|
| U1 算法与版本 | `algorithms.sqlite3`、revision、lineage、版本引用 | 低（无执行租约） | 试点 1 |
| U2 存储源元数据 | StorageSourceRepository SQLite；credential 仅引用 | 低-中 | 试点 2 |
| U3 素材 + GT + 负样本 | `materials.sqlite3`、`annotations.sqlite3`、negative pool、投影/标签引用 | 高（跨库 ATTACH、GT 唯一权威） | 最后批次，必须联合 |
| U4 候选/草稿 | 每任务 `candidates/items.sqlite3` | 高（任务级事务、回执） | 可先保留 SQLite，单独设计 |
| U5 任务运行时 | `tasks.sqlite3`、worker instances、lease/attempt/fencing、formal bulk | 最高 | 最后，独立授权 + 排空窗口 |
| U6 冻结选择 | `trainselection_*/selection.sqlite3` | 高（不可变证据/大清单） | 先保留，PostgreSQL 仅存引用与摘要 |
| U7 产物/发布 | `model_artifacts`、external publish SQLite + config JSON | 中（外部 UNKNOWN） | 单域试点后 |
| U8 ArtifactStore | payload/log/receipt 文件 | 不迁关系库 | 保持内容寻址文件 |

### 3.2 ATTACH 与跨库读

必须显式处理的点：

- `material_batches.py` batch selection ATTACH；
- `material_repository.py` rescan manifest ATTACH；
- `training_material_picker_api.py` usage 与 annotation_gt ATTACH。

PostgreSQL 方案：同一事务需要的表放入同一 database/schema，经原 Repository 查询；
禁止把 JOIN 改成跨库 HTTP 或多次无一致性读；只读投影如独立必须定义 revision 高水位并 fail-closed。

### 3.3 Repository 兼容层

- 每域定义最小 Protocol/端口：身份、revision/CAS、事务、分页、回执；
- SQLite Provider 与 PostgreSQL Provider 实现同一合同，业务层不直接拼 SQL；
- 不重写全部 Repository；只对试点域做 Provider 抽象；
- 迁移工具：单域导出/导入、行数/身份集合/SHA/JSON 类型/NULL/0 对账；
- 无双写；短写栅栏；回退只允许在目标库无新写时直接回旧 Provider，否则先反向导出。

### 3.4 迁移批次

1. **P0 合同与影子**：U1 算法域只读影子，读同一快照；不写 PostgreSQL。
2. **P1 算法单写试点**：维护窗口内停算法写；一致性副本；单写切换；对账；回退演练。
3. **P2 存储源元数据**：U2 试点；凭据仍 SecretStore。
4. **P3 素材+GT 联合设计**：先补 U3 的 ATTACH 替代方案与投影对账；不切生产。
5. **P4 任务运行时**：独立授权；需排空/lease 交接；最后执行。
6. **P5 旧 SQLite 只读退役**：观察窗+恢复验证后。

每批退出：同一身份集合、revision/CAS、回执、分页索引、外部 UNKNOWN、GT/冻结引用全部对账；否则回退。

## 4. F1-C OSS/NAS/S3 与大规模文件存储

### 4.1 现有能力

- `StorageManager` + Provider：local、阿里云 OSS、S3/MinIO、HTTP；素材索引只存源/对象键/SHA。
- `MaterialCache` 内容寻址缩略图、ETag/304；`ArtifactStore` 内容寻址不可变证据。
- 训练 Bundle 经 OSS/S3/MinIO 中转；远程目标 local-only 会 `REMOTE_TRAINING_STORAGE_NOT_PORTABLE`。
- NAS 目前由部署环境挂载，Agent 不能凭路径字符串自动读。

### 4.2 设计合同

**对象身份**：`(storage_source_id, object_key)` + `sha256` + `size` + 可选 ETag/version；
路径不是身份；SHA 不是素材主键。不可变快照以 SHA/Revision 绑定。

**NAS**：不新建第二套文件 API。扩展 LocalProvider 的挂载合同：

- `mount_id`、`root_path`、`node_id`、`fs_type`、`read_only`、`capacity`、`health`；
- 控制端只下发 `storage_source_id` 与挂载要求，不下发任意主机路径；
- Agent 启动时探测挂载点、inode/容量、读权限、SHA 抽样；不可达 fail-closed；
- 文件按对象键读取，禁止路径穿越；同一挂载多节点并发只读，写只由受控导入 Worker。

**OSS/S3**：分片/断点/校验和/重试/并发上限复用现有 Provider；训练数据直达 Worker 是**后续阶段**，
先保持 Bundle 兼容路线。禁止把大文件在控制端下载再上传作为长期默认。

**缓存与 GC**：内容寻址 key；只复用相同 SHA/Revision 的 immutable snapshot；缓存不成为事实源；
按引用计数/保留期回收，孤儿/过期缓存有审计；缩略图不以 mtime 替代 SHA。

**权限**：SecretStore 保存凭据，节点只拿短期/最小权限；不把密钥写入任务 payload 或日志。

### 4.3 阶段

1. 审计各 Provider 方法与配置，列能力矩阵（读/写/分片/校验/列目录/删除/预签名）。
2. NAS 挂载合同 + 健康探测 + 只读训练读取试点（不替换现有 Bundle）。
3. 对象直达 Worker 的影子传输与 SHA 对账；保留 Bundle 回退。
4. 缓存/GC 生命周期与配额；真实 OSS/NAS 延迟测量后决定默认路线。

## 5. F1-D GPU 多节点调度设计（不执行）

### 5.1 复用

`TaskRepository`（lease/attempt/fencing）、`CentralTaskAllocator`、`task_node_assignments`、
`gpu_resources`、Node Agent/ExecutorLoop、Supervisor。禁止第二套 Scheduler/任务库/状态机。

### 5.2 目标容量模型

节点心跳/注册（复用 worker instance/节点表，不新库）：

- `capabilities_allowed` / `reported` / `ready` 三列；
- `gpu_slots[]`：UUID、显存、驱动/CUDA、MIG/共享策略、当前任务；
- `cpu_cores`、`ram_bytes`、`scratch_bytes`、`data_mounts[]`；
- `running_tasks[]` 由 TaskRepository lease 推导，不另存独立事实。

任务需求（创建时冻结）：`gpu_count`、`min_gpu_memory`、`cpu_cores`、`ram_bytes`、`scratch_bytes`、
`portable_contract`、存储源/亲和。

### 5.3 分配算法

1. 硬门槛：节点启用/心跳/能力 allowed∩reported/ready/portable/存储可达/亲和；
2. 真实预算：空闲 GPU UUID 集合 + CPU/RAM/SSD；计入 ASSIGNED/CLAIMED/RUNNING/CANCEL_REQUESTED/清理/非平台进程；
3. 同一任务的所有 GPU 必须来自同一节点；`gpu_count>1` 需要连续或明确的 UUID 集合；
4. 合格节点排名（可立即执行优先，再性能/本地性/公平性）；
5. 预留与 lease 同事务边界；失败可撤销；任务结束/取消/节点上线唤醒。

### 5.4 Agent 与多 GPU

- 单 Agent 进程从单任务循环升级为**有界执行槽**：每个任务独立子进程 + 独立 workspace + GPU UUID 环境；
- 槽位数由 CPU/RAM/SSD/GPU 预算决定，不是固定无限并发；
- 双 GPU 节点可并行 2 个单 GPU 训练，第三任务排队；CPU 清洗/ZIP 与训练共享预算但独立槽；
- 旧 generation/lease 失效后禁止写结果/产物；
- 进程清理/孤儿/节点重启走 Supervisor + 原 fencing。

### 5.5 验收门槛（未来）

- 混合能力矩阵：仅合法节点领取；忙节点无容量不得假准入；弱空闲节点胜强忙节点；
- 单机双 GPU 并行 2、第三排队；GPU UUID 映射与进程隔离；
- 节点失联/重启/租约过期：唯一主人，无重复提交；
- 队列位置、等待原因、资源预算可观测；
- 真实 Ubuntu/NVIDIA 多机 UAT，不以单元测试替代。

## 6. 下一批工作包与依赖

| 工作包 | 内容 | 依赖 | 验收 |
|---|---|---|---|
| W1 | R6 全量回归 + CI（本轮） | 当前 SHA | 24+ 用例、CI 准确 SHA |
| W2 | H2/H3 调用点清单 + `mutate_ids`/分页试点 | F1-A 测量 | 行为等价、50k 对比、回退 |
| W3 | 深分页 cursor 试点（选材） | 排序/筛选语义测试 | 20 万前后 P95、结果集一致 |
| W4 | 缩略图 OSS/NAS 冷路径测量 | 真实/隔离 Provider | 冷热 P95、I/O、锁等待 |
| W5 | PostgreSQL U1 算法域影子/单写设计 | Owner/ATTACH 清单 | 只读影子对账、无写入 |
| W6 | NAS 挂载健康合同 + 读取试点 | Provider 审计 | 挂载/不可达/SHA 证据 |
| W7 | GPU 预算硬准入 + Agent 多槽 PoC | 调度设计 | 双 GPU/第三排队/预算测试 |
| W8 | 生产规模验收方案 | W2–W7 | 场景、样本、回退 |

所有 W2+ 只可在隔离环境；生产迁移/存储切换/调度替换需单独授权。
