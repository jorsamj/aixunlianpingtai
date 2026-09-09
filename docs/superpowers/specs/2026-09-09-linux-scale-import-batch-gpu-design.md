# Linux 大规模素材导入、批处理与 GPU 训练设计

## 目标

在现有 `feat/windows-p0` / `42.23.0` 架构上收口 Linux/NVIDIA 真实生产链路：服务器本地 YOLO 数据集导入、统一大批量素材后台任务、GPU 资源调度与吞吐优化、训练数据只读隔离、外部存储变更恢复，以及启动刷新与 Worker 实例管理。继续保持统一素材池、精确图片 ID 训练、多存储来源索引不复制和算法版本迭代规则。

本轮以 2 万张真实素材稳定运行作为最低生产基线，所有全量流程按 10 万级保持流式、分页、分批和可恢复；100 万级只对明确完成 SQLite 化的索引、选择清单与任务状态承诺架构可扩展性，不把“列表可分页”误报为“完整百万级训练平台已经验证”。

## 不变约束

1. 素材来源只表示物理存储位置，不引入训练数据集分组。
2. 新版训练合同只使用 `train_image_ids`、`test_image_ids` 和明确的 `split_mode`。
3. Local、OSS、S3/MinIO、Remote 素材导入时只建立索引；只有训练、标注或清洗实际需要文件时才通过 `StorageManager` 解析或缓存。
4. 已有素材 ID、标注、算法版本和存储引用不迁移、不重编号。
5. Windows 与 Linux 使用同一套 Python 代码、`pathlib.Path` 和 durable task 协议，不写死盘符或固定挂载点。
6. 用户显式选择 GPU 后，任何环节都不得静默回退 CPU。

## 总体架构

在现有 `TaskRepository`、`ArtifactStore`、`Scheduler` 和 Worker Registry 上扩展，不引入第二套队列系统。

```text
Browser
  ├─ 提交目录/ZIP扫描请求
  ├─ 提交标签映射确认
  ├─ 提交批处理 selection_spec
  └─ 提交 train_image_ids/test_image_ids + device
        │
FastAPI（只校验、计数、建任务、读状态）
        │
TaskRepository + ArtifactStore
  ├─ MATERIAL_IMPORT
  ├─ MATERIAL_BATCH
  └─ TRAINING
        │
Workers
  ├─ Import: 扫描 → 质量分析 → 待确认 → 索引/标注写入
  ├─ Batch: 固化选择 → 分批执行 → checkpoint/恢复
  └─ Training: 设备复核 → 素材快照 → Ultralytics
```

## 一、YOLO 数据集导入

### 1. 扫描识别

`StorageImportHandler` 在普通图片扫描之外增加 `import_format`：

- `auto`：存在可解析的 `data.yaml` 时识别为 YOLO，否则按普通图片。
- `images`：只导入图片。
- `yolo`：必须找到并解析 YOLO 数据结构，否则任务失败。

YOLO 解析顺序：

1. 扫描请求显式给出的相对 `dataset_yaml`；
2. 扫描 prefix 根目录的 `data.yaml`、`dataset.yaml`；
3. 仅在唯一候选存在时自动采用；多个 YAML 候选要求用户重新指定。

YAML 的 `train`、`val`、`test` 引用必须最终解析到当前 Storage Source 根目录内。Local Storage 的 `path` 可以是相对路径，也可以是绝对路径；绝对路径经 `resolve()` 后只要仍位于该存储源根目录内就允许，并在平台内部转换为相对 `object_key`。OSS/S3/Remote 不接受主机绝对路径。第一版支持目录路径和图片清单文本；不执行 YAML 自定义标签或 Python 对象。

图片与标注映射以 YAML 引用和实际扫描结构为准，不写死单一目录形态。至少支持 `images/train` ↔ `labels/train`、`train/images` ↔ `train/labels`、其他 split 同构目录、图片清单文件，以及图片和 TXT 同目录的同 stem 结构。无法唯一匹配时记录为扫描异常，不猜测文件。

### 2. 持久候选结构

继续使用每任务独立的 `scan/candidates.sqlite3`，新增表而不是把标注放入巨大 JSON：

- `dataset_manifest`：格式、YAML object key、原始 split、类别表和解析告警。
- `candidate_annotations`：candidate key、行号、external class ID、class name、归一化框、修复动作、错误码。
- `label_mapping`：external class ID/name、建议平台 label code、确认后的目标 code、状态。

`scan/result.json` 只保存汇总、质量统计、失败示例和 manifest 引用，不保存完整框列表。

### 3. 标签映射

外部 `class_id` 只能先通过当前 YOLO YAML 的 `names` 转成外部类别名称，不能直接映射到平台 `class_id`。

建议匹配顺序：

1. 与平台标签 `code` 完全一致；
2. 与 `code` 大小写无关一致；
3. 与 `display_name` 完全一致；
4. 唯一别名一致。

自动匹配只是建议。存在未匹配、多个候选或名称冲突时，任务保持 `AWAITING_CONFIRMATION`，用户必须为每个外部类别选择现有平台标签或明确创建新标签。新标签以用户确认的英文 code 为稳定标识，中文名可同时填写。重复确认按映射摘要幂等。

### 4. 框容错规则

每行必须是有限数值的 `class cx cy width height`，分割、多边形等非检测格式第一版明确报 `UNSUPPORTED_ANNOTATION_SHAPE`。

- `width <= 0` 或 `height <= 0`：跳过该框，记 `ZERO_AREA_BOX`。
- 非数字、NaN、Infinity、字段不足：跳过，记录文件 key 和行号。
- 归一化框完全位于图片外：跳过，记 `BOX_OUTSIDE_IMAGE`。
- 框与图片仍有有效交集：统一裁剪到 `[0,1]`；越界较大时同时记 `SEVERE_BOX_OVERFLOW` 质量告警，但不能仅因超过固定百分比丢弃仍有有效面积的 Ground Truth。
- 裁剪后宽或高为零：跳过，记 `ZERO_AREA_AFTER_CLIP`。
- 空 TXT：保留图片，写入平台空标注并标记 `annotation_state=confirmed_empty`、`negative_sample=true`。
- 缺少 TXT：作为未标注图片保留，不等同于负样本。
- 类别 ID 不在 YAML `names`：跳过该框并记 `UNKNOWN_CLASS_ID`。

扫描报告展示图片数、带标注图片、确认负样本、缺少标注、有效框、裁剪框、跳过框及按错误码聚合的示例。严重异常不阻止用户导入其余有效图片，但确认页必须明确显示；YAML 无法解析、类别表缺失或路径逃逸会使整个任务失败。

### 5. 确认与索引

确认 API 只写入：素材选择、标签映射、质量确认和摘要，然后通过 `resume_after_confirmation()` 把任务原子放回队列。

Worker 分批执行：

1. 先按 `storage_source_id + object_key` 批量匹配已有素材；命中时保留既有 image ID，只补写/更新标注；
2. 仅为尚未建立索引的素材候选分配稳定 image ID；
3. 通过 `MaterialRepository.upsert_many()` 建立或更新物理存储索引；
4. 将已确认映射后的框写入平台 AnnotationRepository；
5. 同步素材的兼容字段、`box_count`、`labels`、`annotation_state`；
6. 每批提交候选 indexed/annotation_written checkpoint。

Worker 重启时已生成的 image ID 不改变，已写成功的标注按 image ID 和内容摘要幂等复用，不创建第二份素材。原图片和外部 TXT/YAML 均不复制到平台上传目录。

### 6. 正式标注状态

平台以 `annotation_state` 表示 Ground Truth 是否已经确认：

- `unannotated`：没有已确认 Ground Truth；
- `annotated`：存在一个或多个有效框；
- `confirmed_empty`：已由人工或可信数据集确认没有目标，是可训练负样本。

旧数据继续兼容：存在有效框的旧记录惰性解释为 `annotated`；旧 `annotated=true` 且存在明确空标注文件/记录的解释为 `confirmed_empty`；其他情况解释为 `unannotated`。训练资格基于 `annotation_state in {annotated, confirmed_empty}`，不能再以 `box_count > 0` 排除负样本。

## 二、统一素材批处理

### 1. 任务类型与选择协议

新增 `TaskKind.MATERIAL_BATCH`，请求包含操作和不可变 `selection_spec`：

```json
{
  "operation": "MARK_CLEAN_SKIPPED",
  "selection_spec": {
    "scope": "FILTERED",
    "filters": {
      "query": "",
      "storage_source_ids": [],
      "processing_status": "unprocessed",
      "labels": [],
      "annotated": null
    },
    "repository_revision": 123
  },
  "options": {}
}
```

三个范围语义：

- `CURRENT_PAGE`：只提交当前页已展示的最多 1000 个 ID。
- `SELECTED`：只提交用户逐项勾选的 ID；不通过额外接口暗中扩展。
- `FILTERED`：提交筛选条件和 MaterialRepository revision，不提交全部 ID。

API 使用同一筛选构造器执行 `COUNT(*)`，返回本次预计处理数。repository revision 只用于“估算数量 → 用户确认创建任务”之间的乐观检查；确认请求到达时 revision 已改变才返回 409 并要求页面重新确认数量。任务一旦创建，Worker 应优先固化不可变 selection manifest，此后无关素材变化不得使任务失败。

### 2. Durable 执行

Worker 首先把 selection 固化到任务 SQLite manifest。`FILTERED` 使用任务创建时保存的筛选条件和边界 revision，通过短事务/keyset cursor 流式写 ID；`CURRENT_PAGE/SELECTED` 分批校验 ID。manifest 固化后只以其中的不可变 image ID 集合执行和恢复，不再用全局 revision 中止任务。之后根据 operation 调用统一执行器：

- `MARK_CLEAN_SKIPPED`：集合式更新处理状态。
- `CLEAN`：复用现有清洗分析器，逐批 materialize，结果写任务 artifact。
- `DELETE_INDEX`：只删除平台索引。
- `DELETE_SOURCE`：只有显式二次确认后才执行。先在任务 manifest 写入包含完整存储引用的 tombstone，再逐对象删除源文件；源文件成功删除后才删除对应平台索引。部分失败保留索引、tombstone、错误和重试状态，不能先丢失恢复信息。
- `ADD_LABELS` / `REMOVE_LABELS`：批量更新素材标签关系和 payload 摘要。
- `AI_ANNOTATE`：转交现有 AI Annotation 服务使用同一 manifest，不在 HTTP 线程推理。
- 其他简单状态操作复用集合式 patch executor。

状态使用现有 `QUEUED/RUNNING/SUCCEEDED/FAILED/CANCEL_REQUESTED/CANCELLED`。checkpoint 保存 total、processed、succeeded、failed、current image ID 和失败示例。每批提交，Worker lease 过期后从 manifest 未完成行继续。

所有 durable task 在创建数据库记录的同一业务步骤中创建实际日志 artifact。Worker 自身阶段日志及训练/转换/清洗等子进程 stdout、stderr 追加到该 task ID 对应日志；写入 task 的 `log_ref` 前必须确认文件已经创建。日志打开失败使任务明确失败，禁止存在指向不存在文件的 `log_ref`。

### 3. 前端交互

批量工具栏明确显示三个入口：“当前页”“全部筛选结果”“当前已选”。点击操作后先调用 count/estimate，确认框显示操作名称和准确数量；用户确认后只创建 durable task。

任务抽屉显示真实后端状态、已处理/总数、成功/失败、当前素材和错误。关闭弹窗只停止轮询，不取消任务。刷新后根据 task ID 恢复。

## 三、MaterialRepository 大数据能力

新增并统一复用：

- `current_revision()`
- `count_filtered(filters)`
- `iter_filtered_ids(filters, cursor, limit)`
- `patch_many(ids, patch, batch_size=500)`
- `patch_filtered(filters, patch, expected_revision, batch_size=500)`
- `add_labels_many/remove_labels_many`
- `remove_many(ids, batch_size=500)`

筛选 SQL 与素材分页使用同一 `_filters()`，保证页面数量、任务估算和 Worker 实际选择一致。简单状态和标签更新不得调用 legacy `mutate()`。每批事务最多 500 行；不构造超大 `IN`，不把全表 payload 读进 Python。

由于当前 SQLite 的 `payload_json` 仍是兼容事实来源，集合式更新会同时维护结构化列、`material_labels` 和规范化后的 payload。复杂历史数据集删除事务保留旧实现，除非本轮调用链直接触发。

## 四、GPU 资源调度与训练吞吐

### 1. 设备发现和选择

新增只读训练设备接口，从已确认的 Ultralytics Python 环境缓存与一次轻量实时 probe 返回 `auto`、`cpu` 和每个 `cuda:<index>`。存在 CUDA GPU 时 `auto` 推荐 GPU；没有 CUDA 时才推荐 CPU。页面使用 select，不再使用自由文本输入。

API 兼容读取旧任务中的 `0` 并规范化为 `cuda:0`。Task payload、调度记录、job JSON 和任务详情分别保存 `requested_device`、`assigned_device`、`actual_device`，三者不能互相覆盖。用户显式选择 CUDA 后，任何阶段失败都必须明确报错，禁止回退 CPU。

### 2. GPU Resource Manager

在现有 TaskRepository/Scheduler 上增加统一 GPU Resource Manager，不新建第二套队列。每张 GPU 的持久状态至少包含：index、UUID、型号、总/空闲显存、近期平均利用率、已预留显存、当前任务、并发数量、采样时间、Worker 心跳。运行时指标优先通过 NVML 获取；不可用时使用结构化 `nvidia-smi` 查询，Torch probe 只负责环境和设备身份复核。

调度流程：

1. Worker/Scheduler 周期刷新本机 GPU 快照；
2. `auto` 任务按可用性、未预留显存、近期利用率和任务数评分，优先分散到空闲 GPU；
3. 显式 `cuda:N` 只等待该设备；
4. 原子写入带 TTL 的 reservation 后才能 claim/启动训练；
5. 资源不足保持 `QUEUED/resource_waiting`，绝不能自动改为 CPU；
6. Worker 异常退出后 reservation 随 lease 过期回收，正常完成主动释放。

### 3. 独占和受控共享

任务支持 `gpu_policy=auto|exclusive|shared`，默认 `auto` 且首选独占。第一版不做 MIG 或 GPU 虚拟化。

- `exclusive`：设备有其他训练 reservation 时不接纳。
- `shared`：仍必须通过 admission control；不是强制塞入。
- `auto`：先独占；只有小模型历史/探测指标显示显存余量、低平均 GPU 利用率且 CPU/IO 无明显瓶颈时才允许第二个任务共享。

每张 GPU 配置最大并发任务数、显存安全余量和最大可预留比例。预估占用 + 已预留 + 安全余量超过可用显存，或者缺少足够证据时，任务排队。真正并行必须由显式训练 Worker slot 和 Scheduler 管理，不能依赖误启动多个 `--roles all` 进程。

### 4. 自动资源策略

训练默认 `resource_strategy=auto`，用户展开高级配置后可切换 `manual`。自动策略综合 GPU 总/空闲显存、模型规模、`imgsz`、数据量、CPU 核数、当前并发任务、数据源与本地缓存状态：

- `batch`：优先使用 Ultralytics/PyTorch 的安全 autobatch 或短时显存探测，并保留可配置显存余量；不能按 A800 型号写死。仅在确认 OOM 时按阶梯降低并重新准备，达到最小 batch 后失败，不无限重试。
- `workers`：按 CPU 可用核数、同机训练并发、存储类型和数据加载压力分配，Linux/GPU 不再继承 `workers=0`；Windows 保留进程兼容上限。
- `cache`：根据数据集大小、可用 RAM、磁盘空间和远程素材内容缓存命中率选择 `ram|disk|false`，不能因追求速度挤占 GPU 安全显存或系统内存。

任务在启动前持久化 `resolved_batch`、`resolved_workers`、`resolved_cache` 和每项决策依据；手动值只做边界校验，不被后台偷偷重写。

### 5. 持续指标与诊断

训练期间以低频采样（默认 5 秒）写入任务指标 SQLite/Artifact：GPU 利用率与显存、CPU 利用率、实际 batch/workers、images/sec、epoch 耗时和总训练耗时。指标保留聚合值和有界时间序列，不把高频样本塞进任务主 JSON。

诊断基于一段稳定窗口的平均值和吞吐趋势：低 GPU/显存且 CPU 不高时提示可提高 batch；低 GPU 且 CPU 或数据等待高时提示数据加载/解码/IO 瓶颈；显存接近安全上限且 GPU 利用率合理时判定运行正常；真实 OOM 建议或自动降低 batch。页面只展示设备、有效参数、吞吐、资源摘要和一句诊断，不机械追求 100% GPU 利用率。

### 6. 训练入口和最终设备证据

最新创建训练任务页面只提交两种精确图片协议：

- `split_mode=random_test_from_training_pool` + `train_image_ids` + `experiment_percent`；或
- `split_mode=independent_test_set` + `train_image_ids` + `test_image_ids`。

不再提交 `selected_image_ids`。`/api/v12/.../train/start` 进入 `_enqueue_explicit_training()`，素材快照、StorageManager materialize、版本迭代和训练执行都由 durable Training Worker 完成。调用 Ultralytics 时只在进程边界把 `cuda:0` 转为其接受的 `0`；`train_worker.py` 在实际训练 Python 内再次验证并写入 Torch/CUDA、GPU 名称/index、PID 和有效参数。任务详情必须区分配置、分配和实际设备。

## 五、训练工作副本只读隔离

当前 `materialize_portable_dataset()` 在源文件与 bundle 位于同一文件系统时使用 hard link。该策略会让原始素材与训练副本共享 inode；Ultralytics 校验异常 JPEG 时可能重写 bundle 中的 JPEG，进而修改原始素材并使存储索引中的 size/SHA256 失效。

训练数据准备改为原子真实复制：

1. `StorageManager.materialize()` 只负责提供经过 SHA256 校验的只读来源；
2. bundle 图片先复制到同目录临时文件；
3. 对临时文件执行大小和 SHA256 校验；
4. 使用 `os.replace()` 原子发布为训练工作副本；
5. 工作副本保持可写，允许第三方框架修复副本，但不得与源文件共享 inode；
6. 已存在 bundle 文件时除校验 snapshot SHA256，还要在支持 inode/file ID 的平台检查是否与来源同一物理文件；即使 hash 相同，只要共享 inode 也必须安全重建；
7. 构建前按 manifest 总大小、临时复制峰值和安全余量预检磁盘空间；每次原子 copy 前再次检查可用空间；
8. 不使用 symlink、hard link 或无法证明隔离性的文件系统快捷方式；
9. 任务完成后按保留策略清理可重建的 work/bundle 和孤立临时文件，绝不删除 Storage Source、内容缓存或正式训练 artifact。

这一策略会增加训练快照所需磁盘空间，但以数据安全为优先。空间不足时明确失败，不能退回 hard link。定向测试必须在同一文件系统创建源文件和 bundle，覆盖已有 hardlink bundle 后证明新副本隔离；再修改 bundle，证明源文件 SHA256、大小和内容完全不变，并在支持 inode 的平台确认二者 inode 不同。

## 六、Storage Source 重扫与变更恢复

Local、OSS、S3/MinIO 和 Remote 使用现有 Provider 能力建立 durable rescan task。扫描结果落入任务 SQLite manifest，并按 `storage_source_id + object_key` 与现有索引批量比对：

- `NEW`：源端新增，可确认后建立索引；
- `MISSING`：平台有索引但源端不存在，默认只标记失联，不立即删除索引；
- `CHANGED`：object key 相同但 size/etag/SHA256 变化，展示旧/新摘要；
- `UNCHANGED`：无需写库。

用户确认后按所选策略分批更新。`CHANGED` 需要重新计算/验证 SHA256、失效对应内容缓存，并保留变更审计；如果已有正式标注，默认保留 annotation 但将素材标记为需要复核，不能静默让旧标注继续成为已确认 Ground Truth。此流程也是训练遇到 `SOURCE_CONTENT_CHANGED` 后的正式恢复入口。

## 七、AnnotationRepository 和百万级边界

新增 SQLite AnnotationRepository 作为新写入主路径，按 image ID 保存 `annotation_state`、版本、内容摘要、框数据和更新时间，并为状态/标签建立必要索引。旧 `annotations/<image_id>.json` 保留只读兼容和惰性迁移：首次读取可回退，首次更新写入 SQLite；不得一次性搬迁或删除用户旧标注。

2 万与 10 万级导入、筛选、批任务和训练准备不得遍历百万小文件。对于 100 万级，本轮只声明已经 SQLite 化且具备分批执行的路径；真实百万素材端到端训练、备份、数据库维护和容量规划在未压测前必须标记“未验证”。

## 八、Worker 实例和任务竞争

TaskRepository 新增 `worker_instances` 表，主键由 `hostname + resolved data_dir + sorted roles` 的摘要组成，记录 owner token、PID、started/heartbeat/expires 时间。

Worker 启动时原子注册：

- 同一实例键存在有效租约时，第二个进程退出并打印已有 PID/worker ID；
- 租约过期或 PID 已不存在时允许接管；
- Scheduler 循环续租，正常退出释放；异常退出由 TTL 回收；
- `--allow-parallel` 是显式运维开关，生成不同 slot；按角色拆分的 Worker 因 roles 不同可并存。

任务层现有 lease 和 resource key 继续负责单任务所有权，实例租约只阻止无意重复的同机全角色 Worker。

## 九、刷新和首屏性能

`/api/v53/bootstrap/snapshot` 不再返回完整素材数组，只返回项目、标签、算法、资源摘要、任务摘要和素材聚合数量。普通数据页仍由 cursor API 加载 48 张首屏。

训练素材选择、批处理、自动标注等原 full-material 页面逐步改用服务端分页、筛选计数和 manifest selection，不再通过 `state.images` 保存全部素材。刷新按钮只更新当前页面依赖和 revision；后台额外配置继续惰性加载。启动等待只用于数据库迁移/必要恢复，不因扫描全量素材而阻塞页面。

## 十、错误与可观测性

所有新任务错误包含稳定错误码、中文说明、当前阶段和处理建议。公开 API 不返回服务器绝对路径或密钥。服务端日志保留 task ID、worker ID、批次和原始异常。每个 durable task 在创建时就建立实际日志文件/流，Worker 和关键子进程 stdout/stderr 与 task ID 关联；只有 artifact 真正存在后才写 `log_ref`。

重点错误码包括：

- `YOLO_YAML_NOT_FOUND`
- `YOLO_YAML_AMBIGUOUS`
- `YOLO_LABEL_MAPPING_REQUIRED`
- `YOLO_PATH_OUTSIDE_SOURCE`
- `MATERIAL_SELECTION_REVISION_CHANGED`
- `MATERIAL_BATCH_PARTIAL_FAILURE`
- `SOURCE_CONTENT_CHANGED`
- `SOURCE_DELETE_PARTIAL_FAILURE`
- `CUDA_UNAVAILABLE`
- `CUDA_DEVICE_INDEX_INVALID`
- `GPU_RESOURCE_WAITING`
- `GPU_MEMORY_INSUFFICIENT`
- `TASK_LOG_CREATE_FAILED`
- `DUPLICATE_WORKER_INSTANCE`

## 十一、兼容和发布边界

- 旧图片-only 导入任务继续可恢复，新增表采用惰性迁移。
- 旧 `scan/result.json` candidates 兼容读取。
- 旧训练任务和 job JSON 继续展示，但新版页面不再产生 `selected_image_ids`。
- 现有 StorageManager、SecretStore、TaskRepository lease 和算法版本选择逻辑不替换。
- 旧 annotation JSON 继续可读，新写入转入 SQLite；不以一次性迁移阻塞升级。
- 第一版只对 YOLO 标注导入报告真实支持；COCO/VOC 显示“尚未支持”，后续可通过同一 parser 接口增加。

## 十二、验证范围

按本轮要求优先代码正确性：

1. 所有受影响 Python 文件通过 `py_compile`，JavaScript 文件通过 `node --check`。
2. 只有发现具体失败信号或关键纯函数行为无法静态确认时，才增加和运行最小定向测试。
3. 不重复运行无关全量回归。
4. 用户已经在现有版本的 A800 环境证明 CUDA 和 GPU 训练可用；本轮新增的自动 batch/workers、调度 reservation、共享 admission 和持续指标仍必须在该 Linux/A800 环境重新验收，不能沿用旧结论冒充新功能验证。
5. 未接入的真实 OSS/S3/Remote 环境明确标记未验证，不以模拟 Provider 代替真实结果。
