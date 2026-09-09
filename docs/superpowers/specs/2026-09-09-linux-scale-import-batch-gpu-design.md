# Linux 大规模素材导入、批处理与 GPU 训练设计

## 目标

在现有 `feat/windows-p0` / `42.23.0` 架构上收口四条真实生产链路：服务器本地 YOLO 数据集导入、统一大批量素材后台任务、Linux/NVIDIA GPU 训练设备传递，以及启动刷新与 Worker 实例管理。继续保持统一素材池、精确图片 ID 训练、多存储来源索引不复制和算法版本迭代规则。

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

YAML 只接受存储源内部相对引用。`path`、`train`、`val`、`test` 解析后必须仍位于当前存储源允许根目录内。第一版支持目录路径和图片清单文本；不执行 YAML 自定义标签或 Python 对象。

图片与标注按 YOLO 目录规则匹配：`images/<split>/<stem>.<ext>` 对应 `labels/<split>/<stem>.txt`。对于没有标准 `images/labels` 目录但图片和 TXT 同目录的来源，也支持同 stem 匹配。无法唯一匹配时记录为扫描异常，不猜测文件。

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
- 框与图片有有效交集，且每边越界不超过图像对应维度的 5%：裁剪到 `[0,1]`，记 `CLIPPED_MINOR_OVERFLOW`。
- 越界超过 5%：跳过，记 `SEVERE_BOX_OVERFLOW`。
- 空 TXT：保留图片，写入平台空标注并标记 `annotation_state=confirmed_empty`、`negative_sample=true`。
- 缺少 TXT：作为未标注图片保留，不等同于负样本。
- 类别 ID 不在 YAML `names`：跳过该框并记 `UNKNOWN_CLASS_ID`。

扫描报告展示图片数、带标注图片、确认负样本、缺少标注、有效框、裁剪框、跳过框及按错误码聚合的示例。严重异常不阻止用户导入其余有效图片，但确认页必须明确显示；YAML 无法解析、类别表缺失或路径逃逸会使整个任务失败。

### 5. 确认与索引

确认 API 只写入：素材选择、标签映射、质量确认和摘要，然后通过 `resume_after_confirmation()` 把任务原子放回队列。

Worker 分批执行：

1. 为素材候选分配稳定 image ID；
2. 通过 `MaterialRepository.upsert_many()` 建立物理存储索引；
3. 将已确认映射后的框写入平台 annotation JSON；
4. 同步素材的 `annotated`、`box_count`、`labels`、`annotation_state`；
5. 每批提交候选 indexed/annotation_written checkpoint。

Worker 重启时已生成的 image ID 不改变，已写成功的标注按 image ID 和内容摘要幂等复用，不创建第二份素材。原图片和外部 TXT/YAML 均不复制到平台上传目录。

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

API 使用同一筛选构造器执行 `COUNT(*)`，返回本次预计处理数。创建任务时若 revision 已改变，返回 409 并要求页面重新确认数量，避免用户看到的数量与任务范围不一致。

### 2. Durable 执行

Worker 首先把 selection 固化到任务 SQLite manifest。`FILTERED` 使用 keyset cursor 流式写 ID；`CURRENT_PAGE/SELECTED` 分批校验 ID。之后根据 operation 调用统一执行器：

- `MARK_CLEAN_SKIPPED`：集合式更新处理状态。
- `CLEAN`：复用现有清洗分析器，逐批 materialize，结果写任务 artifact。
- `DELETE_INDEX` / `DELETE_SOURCE`：先批量删除平台索引；只有显式二次确认才逐对象删除源文件。
- `ADD_LABELS` / `REMOVE_LABELS`：批量更新素材标签关系和 payload 摘要。
- `AI_ANNOTATE`：转交现有 AI Annotation 服务使用同一 manifest，不在 HTTP 线程推理。
- 其他简单状态操作复用集合式 patch executor。

状态使用现有 `QUEUED/RUNNING/SUCCEEDED/FAILED/CANCEL_REQUESTED/CANCELLED`。checkpoint 保存 total、processed、succeeded、failed、current image ID 和失败示例。每批提交，Worker lease 过期后从 manifest 未完成行继续。

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

## 四、GPU 训练设备链路

### 1. 设备发现和选择

新增只读训练设备接口，从已确认的 Ultralytics Python 环境缓存与一次轻量实时 probe 返回：

```json
{
  "items": [
    {"value":"cuda:0","label":"NVIDIA A800-SXM4-40GB / GPU 0","available":true},
    {"value":"cpu","label":"CPU","available":true}
  ],
  "recommended":"cuda:0"
}
```

存在 CUDA GPU 时前端默认 GPU 0；无 CUDA 时默认 CPU。页面使用 select，不再使用自由文本输入。

### 2. 单一规范值

API 接受 `cpu` 或 `cuda:<index>`，兼容读取旧任务中的 `0` 并规范化为 `cuda:0`。Task payload、resource key、job JSON 和任务详情保存 `requested_device`。

Training Worker 使用其实际训练 Python 再验证：

- `torch.cuda.is_available()`；
- index 小于 `torch.cuda.device_count()`；
- 获取 GPU 名称和 CUDA 版本。

失败立即将任务标为 `FAILED`，错误明确指出请求设备、训练 Python、Torch/CUDA 状态和处理建议。禁止替换为 CPU。

调用 Ultralytics 时只在边界将 `cuda:0` 转为其接受的 `0`；`train_worker.py` 启动后再次验证并写入：`actual_device`、`gpu_name`、`cuda_version`、`torch_version`、`training_pid`。任务详情显示请求设备和实际设备。

### 3. 训练入口统一

最新创建训练任务页面提交：

- `split_mode=random_test_from_training_pool` + `train_image_ids` + `experiment_percent`；或
- `split_mode=independent_test_set` + `train_image_ids` + `test_image_ids`。

不再提交 `selected_image_ids`。`/api/v12/.../train/start` 因此进入 `_enqueue_explicit_training()`，素材快照、StorageManager materialize、版本迭代和训练执行都由 durable Training Worker 完成。旧同步路径仅用于读取历史任务，不再由新版 UI 调用。

## 五、Worker 实例和任务竞争

TaskRepository 新增 `worker_instances` 表，主键由 `hostname + resolved data_dir + sorted roles` 的摘要组成，记录 owner token、PID、started/heartbeat/expires 时间。

Worker 启动时原子注册：

- 同一实例键存在有效租约时，第二个进程退出并打印已有 PID/worker ID；
- 租约过期或 PID 已不存在时允许接管；
- Scheduler 循环续租，正常退出释放；异常退出由 TTL 回收；
- `--allow-parallel` 是显式运维开关，生成不同 slot；按角色拆分的 Worker 因 roles 不同可并存。

任务层现有 lease 和 resource key 继续负责单任务所有权，实例租约只阻止无意重复的同机全角色 Worker。

## 六、刷新和首屏性能

`/api/v53/bootstrap/snapshot` 不再返回完整素材数组，只返回项目、标签、算法、资源摘要、任务摘要和素材聚合数量。普通数据页仍由 cursor API 加载 48 张首屏。

训练素材选择、批处理、自动标注等原 full-material 页面逐步改用服务端分页、筛选计数和 manifest selection，不再通过 `state.images` 保存全部素材。刷新按钮只更新当前页面依赖和 revision；后台额外配置继续惰性加载。启动等待只用于数据库迁移/必要恢复，不因扫描全量素材而阻塞页面。

## 七、错误与可观测性

所有新任务错误包含稳定错误码、中文说明、当前阶段和处理建议。公开 API 不返回服务器绝对路径或密钥。服务端日志保留 task ID、worker ID、批次和原始异常。

重点错误码包括：

- `YOLO_YAML_NOT_FOUND`
- `YOLO_YAML_AMBIGUOUS`
- `YOLO_LABEL_MAPPING_REQUIRED`
- `YOLO_PATH_OUTSIDE_SOURCE`
- `MATERIAL_SELECTION_REVISION_CHANGED`
- `MATERIAL_BATCH_PARTIAL_FAILURE`
- `CUDA_UNAVAILABLE`
- `CUDA_DEVICE_INDEX_INVALID`
- `DUPLICATE_WORKER_INSTANCE`

## 八、兼容和发布边界

- 旧图片-only 导入任务继续可恢复，新增表采用惰性迁移。
- 旧 `scan/result.json` candidates 兼容读取。
- 旧训练任务和 job JSON 继续展示，但新版页面不再产生 `selected_image_ids`。
- 现有 StorageManager、SecretStore、TaskRepository lease 和算法版本选择逻辑不替换。
- 第一版只对 YOLO 标注导入报告真实支持；COCO/VOC 显示“尚未支持”，后续可通过同一 parser 接口增加。

## 九、验证范围

按本轮要求优先代码正确性：

1. 所有受影响 Python 文件通过 `py_compile`，JavaScript 文件通过 `node --check`。
2. 只有发现具体失败信号或关键纯函数行为无法静态确认时，才增加和运行最小定向测试。
3. 不重复运行无关全量回归。
4. 当前 Windows 环境无法证明 A800 真实占用；交付时提供 Linux 最小验收：任务 argv、train_worker Torch/CUDA 记录和 `nvidia-smi` 进程/利用率三项必须同时吻合。
5. 未接入的真实 OSS/S3/Remote 环境明确标记未验证，不以模拟 Provider 代替真实结果。

