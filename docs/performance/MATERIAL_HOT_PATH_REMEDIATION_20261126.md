# 素材热路径 O(N) 治理（2026-11-26）

> 范围：`app.py` / `platform_core/material_governance_service.py` / `platform_core/quality_analysis_service.py` /
> `platform_core/video_tasks.py` / `platform_core/remote_execution_transport.py` 的既有素材调用链。
> 本轮**未**改 VERSION、AGENTS.md、vendor、存储 Provider、PostgreSQL 迁移、Task/Worker/GT/负样本/冻结/回执 Owner，
> 未访问生产数据，未运行 200k 合成基准。
>
> 依据：[F1_PERFORMANCE_AND_MIGRATION_DESIGN_20261122.md](../architecture/F1_PERFORMANCE_AND_MIGRATION_DESIGN_20261122.md)
> 第 2.1/2.6 节的调用点清单与阻塞结论，
> [PLATFORM_SCALE_ACCEPTANCE_20261121.md](PLATFORM_SCALE_ACCEPTANCE_20261121.md) 的素材规模边界。

## 1. 审计结论

| # | 调用链 | 原问题类型 | 本轮结论 |
|---|---|---|---|
| 1 | `POST /api/v12/projects/{pid}/datasets/{dataset_id}/auto_split` → `app.v12_auto_split` → `MaterialGovernanceService.v12_auto_split` | 全目录 `read()` + 逐图 GT `get()`（N+1）+ 全表 `mutate()` 写事务 | **已修复**：id-only 快照 + 每 500 条 GT 批量读 + `mutate_dataset(dataset_id, ...)` 定向写 |
| 2 | `POST /api/v44/projects/{pid}/jobs/{job_id}/supplement` → `app.v44_supplement_training_data` → `QualityAnalysisService.v44_supplement_training_data` | `load_images` 全目录 + 逐图 `read_annotation`（N+1）+ 全表 `mutate()` | **N+1 已修复**：每 500 条 `read_annotations_many`；全目录读取与全表写事务按合同保留 |
| 3 | `POST /api/v20/projects/{pid}/images/batch_split`（`scope=filtered`）→ `MaterialGovernanceService.v20_batch_image_split` | `load_images` 全目录（marked/unmarked）+ 全表 `mutate()` | **已修复**：`list_all_ids()` + 500 条 GT 批量；有 `dataset_id` 时写事务收敛到 `mutate_dataset`；无 `dataset_id` 时保留全表事务 |
| 4 | `app.load_images` 及其余调用者 | 全目录 `read()` | **保留**；见 §5.4，按合同需要全目录或仅低频管理/导出路径 |
| 5 | `remote_execution_transport.build_rknn_calibration_snapshot` | `repository.read()` 全目录 | **保留**；见 §5.3，分页会破坏单语句快照一致性，需 revision 围栏设计 |
| 6 | `video_tasks.VideoFrameHandler._already_committed` | `repository.read()` 全目录 | **已修复**：`get_many(result image_ids)` |
| 7 | `training_prepare*` 素材读取 | 本文件无素材读取 | **无需修改**；见 §5.5 |

### 1.1 为什么 v12 的快照边界可以不变

原 v12 的顺序是：

1. 事务外读全目录：`load_images()` → `MaterialRepository.read()`；
2. 事务外逐图读正式 GT：`read_annotation()` → `AnnotationRepository.get()`；
3. 事务内全表扫描并重算最新 dataset 成员：`MaterialRepository.mutate()`。

新实现保持同一顺序与同一 GT 时点：

1. 事务外 `MaterialRepository.list_all_ids()`：单条语句、只读 id 列，仍覆盖全部身份；
2. 事务外 `AnnotationRepository.get_many()`：每 500 个 id 一批，仍是**写入前**的正式 GT 快照；
3. 事务内 `MaterialRepository.mutate_dataset(dataset_id, ...)`：`BEGIN IMMEDIATE` 内按最新
   dataset 成员读取候选行，回调仍执行原来的精确 `img.get("dataset_id", "default") == dataset_id`
   谓词与按 id 排序、train/val/test 计数。

因此“请求期间被改到目标 dataset 的行仍使用事务外已读 GT”的行为保持不变
（`tests/api/test_material_selection_atomicity.py::test_auto_split_rechecks_latest_membership_and_sorts_by_id`
覆盖）。GT 读取仍在写事务之外，没有把 Annotation Owner 拉进 Material 写锁。

### 1.2 为什么 filtered marked/unmarked 的 GT 仍必须覆盖全量身份

`matched`/`unmarked` 的判定依赖请求开始时的正式 GT 快照。一个在快照之后才被移入目标
dataset 的行，旧实现会以“快照中不存在该 id ⇒ 视为未标注”参与过滤，而不是重新读 GT。
所以本轮仍先取全部身份（只读 id），再批量读 GT；被移除的只是 200k 级别的逐图 repository
打开和整份 payload 反序列化。该语义由 `test_v12_auto_split_*` 与
`test_v20_filtered_marked_*` 的 old/new 并跑结果相等断言固定。

### 1.3 default dataset 的历史身份不被放宽

v12 的旧谓词是严格 `dataset_id == dataset_id`（缺失字段按 `"default"`），并不接受
`null/""/0/0.0/false` 等历史表示。`mutate_dataset("default")` 的 SQL 候选会包含这些历史行，
但回调保留原严格谓词，未匹配行不会被解码写回。`test_v12_auto_split_default_dataset_keeps_historical_strict_membership`
证明结果与旧实现逐字节一致，历史选择不被扩大。

## 2. 实施的修改

### 2.1 v12_auto_split（`platform_core/material_governance_service.py`）

调用链：

```
HTTP POST /api/v12/projects/{pid}/datasets/{dataset_id}/auto_split
→ platform_core/material_governance_api.create_material_governance_router_3
→ app.v12_auto_split
→ _material_governance_service()
→ MaterialGovernanceService.v12_auto_split
→ MaterialRepository.list_all_ids()
→ AnnotationRepository.get_many()  (≤500 ids / batch, only when include_unannotated=False)
→ MaterialRepository.mutate_dataset(dataset_id, apply_auto_split)
```

使用的既有有界 API：`MaterialRepository.list_all_ids()`、`AnnotationRepository.get_many()`、
`MaterialRepository.mutate_dataset()`。没有新增存储路径，没有新增第二个任务/缓存系统。

### 2.2 v20_batch_image_split（filtered）

```
HTTP POST /api/v20/projects/{pid}/images/batch_split
→ app.v20_batch_image_split
→ MaterialGovernanceService.v20_batch_image_split
→ (filtered marked/unmarked) MaterialRepository.list_all_ids()
→ AnnotationRepository.get_many()  (≤500 ids / batch)
→ MaterialRepository.mutate_dataset(dataset_id, apply_split)   # dataset_id 非空
   MaterialRepository.mutate(apply_split)                       # dataset_id 为空，保留原语义
```

API 的 `selected` 分支、`scope=dataset` 分支未改；当 `dataset_id` 为空时仍走原来的
全表事务，因为该模式必须在写事务内按“最新 split/标注快照”重算整个库的匹配集合。

### 2.3 v44_supplement_training_data（N+1 修复）

```
HTTP POST /api/v44/projects/{pid}/jobs/{job_id}/supplement
→ app.v44_supplement_training_data
→ QualityAnalysisService.v44_supplement_training_data
→ MaterialRepository.read() via load_images()      # 身份 + split 快照，保留
→ QualityAnalysisDependencies.read_annotations_many()  (≤500 ids / batch)
→ MaterialRepository.mutate(apply_supplement)      # 单个写事务，保留
```

`eligible` 仍按 `load_images()` 的规范顺序（`created_at, id`）逐块累积；写回调仍只取前
`limit` 个仍为 `unassigned` 的行，并继续在 `BEGIN IMMEDIATE` 内复查最新 split。

### 2.4 video_tasks._already_committed

```
VideoFrameHandler.run()
→ VideoFrameHandler._already_committed(context)
→ context.artifacts.read_json(task_id, "result.json")
→ MaterialRepository.get_many(result["materials"][].image_id)  (≤500 ids / batch)
→ StorageManager.materialize(row) / _sha256(path) 校验
```

只读取 durable result 里实际列出的素材身份。缺失身份、文件缺失或 SHA 不一致仍返回
`None`（fail-closed），不修改 revision、不写回素材。

## 3. 合同保持论证

- **正式 GT**：只读 `AnnotationRepository`；v12/v20/v44 均未写 GT，未改 annotation version/digest。
  新增测试在修改前后比较全部相关 `(version, content_digest)` 一致。
- **revision/CAS**：v12/v20 的实际写入仍由 `MaterialRepository` 事务内的 `_write_row` +
  `_bump_revision` 完成；只有实际 payload 变化才 +1。新测试比较新旧项目 revision 与逐行
  `payload_json` 字节一致。
- **freeze/历史选择**：v12 的 dataset 谓词、排序、train/val/test 计数逐行保持；v44 的
  eligible 顺序与 `limit` 截取保持；v20 `filtered` 的 marked/unmarked、split 重查保持。
  未引入 mtime identity，未改 Bundle 兼容合同，未新增 truncation。
- **receipt/history**：v44 仍在同一次 `mutate` 后写 `job.json` 的 `supplemented_image_ids/at`
  并 `sync_jobs_index`；v12/v20 的返回结构与错误 400/409 契约未变。

## 4. 验证（本地，synthetic）

新增 `tests/unit/test_material_hot_paths_scale.py`：7 个用例，覆盖
v12（含 1,201 行、>500 批边界、default 历史身份）、v20 filtered（有/无 dataset_id）、
v44（30 个 unassigned）、video（result ids=2）。每个用例都并跑旧算法作为 oracle，并在新路径上
monkeypatch `MaterialRepository.read()`（以及 v12 的逐图 `AnnotationRepository.get()`）为失败，
证明没有回退到全目录读取/逐图读取。

## 5. 剩余项（未改及原因）

### 5.1 v20 filtered 无 `dataset_id`

保留全表 `mutate()`。`match_latest` 必须在写事务内按最新 split/标注事实重算整个库，
现有 `mutate_ids`/`mutate_dataset` 都无法在不改变并发语义的前提下表达“按 split/GT 谓词
在事务内重查”。需要 Repository 层的 `mutate_filtered`（SQL 谓词 + 事务内 PG/GT 快照）
新合同；`platform_core/material_repository.py` 不在本轮可修改文件内。

### 5.2 v44 全表写事务

`eligible` 可能很大，且旧合同是“在事务内按规范顺序取前 limit 个仍 unassigned 的行”。
直接改成 `mutate_ids(eligible)` 会：(a) 超过实测 5,000 的 `mutate_ids` 收益边界；
(b) 并发 split 变化时不再顺延到下一个 eligible 行，改变历史选择语义。因此保留原写事务。

### 5.3 remote_execution_transport 的 RKNN calibration snapshot

`build_rknn_calibration_snapshot` 仍是 `read()` 后按 dataset/split 取前 `limit` 个。改成
`iter_filtered_ids()` + `get_many()` 分页可降低内存，但跨页读取不再是一个 SQLite 语句快照；
并发导入/删除会改变候选集合与最终 snapshot digest。需要先设计 revision 围栏
（例如结束后校验 `current_revision()`，变化则 409）并补转换合同测试；本轮不猜。

### 5.4 `load_images` 剩余调用者

`MaterialRepository.read()` 仍是兼容的全目录 API。当前调用者分为：

- 合同需要全目录：`dataset_export_service`（构建完整数据集快照/导出）、`material_catalog_service`
  的若干汇总/重建入口、`app._v53_rebuild_*`（返回完整刷新结果）；
- 低频管理/Worker：标签文件导入（按 stem 匹配全库）、预标注/清洗扫描、v36 源导入的
  before/after id 差集；
- 后续可安全定点：显式 `image_ids` 的预标注/清洗入口可换 `get_many`，v36 的 before/after
  可换 `list_all_ids`，但需各自的行为/回执测试，未在本批扩大范围。

### 5.5 training prepare 素材读取

本文件所有权内的 `platform_core/training_prepare_child.py` 只创建 durable
`TRAINING_PREPARE` 子任务（TaskRepository/ArtifactStore），不读取素材目录；因此没有可改的
O(N) 素材读取。实际训练选材/usage 读在 `training_material_picker_api.py`、
`training_material_usage.py` 等文件，本轮仅审计、未修改（不在可修改文件清单内）。

### 5.6 存储缓存

`platform_core/storage/cache.py`、`material_cache_runtime.py` 未发现与本调用链相关的缺陷；
未用 mtime 替代 SHA256，未改缓存身份。

## 6. 小样本合成测量（非生产、非 200k）

环境：Windows 11，Python 3.12.7；隔离 SQLite，1,201 行素材元数据、401 行正式 GT、无图片字节；
7 次采样。**这些数字只说明该合成夹具上的调用次数差异，不代表生产 P50/P95。**

v12 `include_unannotated=False` 的 GT 存在性快照（1,201 行）：

| 路径 | P50 | P95 |
|---|---:|---:|
| 旧：`read()` 全目录 + 逐图 `AnnotationRepository.get()` | 4,270.76 ms | 4,690.73 ms |
| 新：`list_all_ids()` + `get_many(≤500)` | 14.84 ms | 18.11 ms |
| 参考：`read()` 本身（全 payload） | 11.62 ms | 13.40 ms |
| 参考：`list_all_ids()` 本身 | 4.93 ms | 5.32 ms |

video `_already_committed`（1,201 行目录，result 只列 2 个 id）：

| 路径 | P50 | P95 |
|---|---:|---:|
| 旧：`read()` 全目录 | 9.74 ms | 11.22 ms |
| 新：`get_many(2)` | 4.51 ms | 4.79 ms |

小样本下 `get_many` 的连接/PRAGMA 固定成本占比高，但读取行数已从“整个目录”变为
“result 实际引用的身份”；v12 的主要收益来自去掉 1,201 次 repository 打开。

## 7. 验证命令与结果

```text
python -m pytest -q tests/unit/test_material_hot_paths_scale.py -p no:cacheprovider
7 passed

python -m pytest -q tests/api/test_material_selection_atomicity.py \
  tests/api/test_material_response_performance.py \
  tests/integration/test_video_task_worker.py tests/unit/test_video_commit_fencing.py \
  tests/api/test_material_reader_views.py \
  "tests/api/test_training_ground_truth_gate.py::test_remaining_model_inference_effective_http_contract" \
  -p no:cacheprovider
35 passed

python -m py_compile platform_core/material_governance_service.py \
  platform_core/quality_analysis_service.py platform_core/video_tasks.py \
  tests/unit/test_material_hot_paths_scale.py
# exit 0

git diff --check
# exit 0
```

未运行 200k/生产基准；未部署；未改 VERSION/AGENTS.md/vendor/受保护未跟踪文档。
