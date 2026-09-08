# NVIDIA/Linux 服务器本地素材目录与大体积 ZIP 导入设计

日期：2026-09-08  
基线版本：42.22.4  
目标分支：`feat/windows-p0`  
状态：已确认，采用方案 A

## 1. 目标与边界

本轮在现有多来源素材存储架构上补齐两条真实导入链路：

1. 扫描管理员配置的 Local Storage Source 下已有图片并建立素材索引；
2. 读取服务器允许导入目录中的大体积 ZIP，安全解压到指定 Local Storage Source 后扫描并建立索引。

本轮不新增数据集分组，不改变训练素材协议。训练任务继续只提交：

- `train_image_ids`
- `test_image_ids`

标签仍只用于业务分类和素材筛选；Storage Source 只表示物理文件位置。

不得移动现有素材、改变 `image_id`、清空标注、破坏算法版本关系，或把服务器本地素材复制到项目 `uploads`。

## 2. 已确认方案

采用方案 A：扩展现有 `MATERIAL_IMPORT` durable task，使同一种任务支持：

- `directory_scan`：扫描 Local Storage Source 已有目录；
- `server_zip`：校验并解压服务器 ZIP，然后扫描目标目录。

历史请求未提供 `mode` 时继续按现有通用 `storage_scan` 处理，OSS、S3/MinIO 和 Remote Storage Source 的扫描能力不得回退。`storage_scan` 继续使用 Provider cursor；`directory_scan` 和 `server_zip` 才强制要求 Local source。

不新增平行的导入任务系统，也不使用进程内临时线程承载服务器 ZIP 导入。

任务采用同一生命周期：

```text
QUEUED
  -> RUNNING / validating
  -> RUNNING / extracting       # 仅服务器 ZIP
  -> RUNNING / scanning
  -> AWAITING_CONFIRMATION
  -> QUEUED / indexing_queued    # 用户确认后重新入队
  -> RUNNING / indexing
  -> SUCCEEDED
```

失败、取消和环境阻断继续使用现有 Task Runtime 状态。

## 3. 配置与路径边界

### 3.1 Local Storage Source

Local Storage Source 的 `config.root` 是管理员配置的物理安全边界，可使用跨平台绝对路径：

- Linux 示例：`/data/datasets`
- Windows 示例：`D:/datasets`

应用内部统一使用 `pathlib.Path`。业务记录只存相对于 root 的 POSIX 风格 `object_key`，不得存绝对物理路径。

例如：

```text
root=/data/datasets
physical=/data/datasets/fire/sub/a.jpg
object_key=fire/sub/a.jpg
```

### 3.2 服务器 ZIP 允许目录

新增环境变量：

```text
MC_SERVER_IMPORT_DIR
```

未配置时默认使用：

```text
<data_dir>/imports
```

API 不允许读取该目录以外的任意服务器文件。ZIP 请求中的路径经解析后必须仍位于允许目录内；拒绝符号链接或路径归一化导致的越界。

代码不得写死 `/data`、盘符、反斜杠路径或平台专用 shell 命令。

## 4. API 设计

复用现有入口：

```text
POST /api/v61/projects/{project_id}/storage-imports/scan
GET  /api/v61/projects/{project_id}/storage-imports/{task_id}
POST /api/v61/projects/{project_id}/storage-imports/{task_id}/confirm
```

扫描请求增加模式字段，保持旧请求兼容：

```json
{
  "mode": "directory_scan",
  "storage_source_id": "a800_local",
  "prefix": "fire/2026",
  "recursive": true
}
```

旧版请求：

```json
{
  "storage_source_id": "minio_01",
  "prefix": "incoming",
  "recursive": true
}
```

继续解释为 `mode=storage_scan`，不得因本轮改动失效。

服务器 ZIP 请求：

```json
{
  "mode": "server_zip",
  "zip_path": "fire.zip",
  "storage_source_id": "a800_local",
  "target_prefix": "fire",
  "recursive": true
}
```

`zip_path` 对外采用相对于 `MC_SERVER_IMPORT_DIR` 的路径。即使前端展示绝对路径，后端也必须重新解析并验证边界，不能信任浏览器提交值。

确认接口不直接执行大批量数据库写入。它负责：

1. 验证任务处于 `AWAITING_CONFIRMATION`；
2. 原子写入确认 artifact；
3. 通过 `TaskRepository.resume_after_confirmation()` 将同一任务原子转换回 `QUEUED`；
4. 由 Storage Worker 完成批量索引。

该状态转换是 TaskRepository 的正式方法，不能由 `app.py` 直接执行 SQL，也不能复用语义不同的 `complete_review()`。它只能执行 `AWAITING_CONFIRMATION -> QUEUED`，同时写入 `accepted=true`、`stage=indexing_queued`、`finished_at=NULL`，并清空 `worker_id`、`lease_token`、`lease_expires_at`。重复确认必须幂等；冲突的第二次确认必须返回明确错误。

## 5. Durable Worker 与恢复

`StorageImportHandler` 按请求模式执行阶段。

### 5.1 directory_scan

1. 解析 Storage Source；
2. 必须为已启用且健康的 Local source；
3. 校验 prefix 不越过 root；
4. 流式遍历支持的图片；
5. 持续写入候选记录和 checkpoint；
6. 扫描结束进入 `AWAITING_CONFIRMATION`；
7. 用户确认后分批建立素材索引。

### 5.2 server_zip

1. 校验 ZIP 源路径位于允许目录；
2. 校验目标是健康、已启用的 Local source；
3. 校验 ZIP 格式、成员路径、成员类型和声明大小；
4. 校验目标磁盘可用空间；
5. 流式解压并记录真实文件/字节计数；
6. 扫描实际解压目录；
7. 进入 `AWAITING_CONFIRMATION`；
8. 用户确认后分批建立索引。

任务 checkpoint 至少记录：

- 当前阶段；
- 已完成 ZIP 成员；
- 已解压文件数和字节数；
- 已扫描文件数；
- 当前对象；
- 候选、重复、损坏、失败计数；
- 是否已收到确认；
- 已完成索引批次。

Worker 重启后依据 checkpoint 和实际文件状态恢复。未完成的 `.part` 文件应清理或重新写入；已经完整写入且校验一致的成员不重复解压。

## 6. 候选素材持久化与规模

不得把 10 万或 100 万条候选永久保存在一个 JSON 数组，也不得一次性返回浏览器。

每个导入任务使用独立的 SQLite candidate store，候选至少包含：

- `object_key`
- `filename`
- `content_sha256`
- `size_bytes`
- `etag`
- `width`
- `height`
- `duplicate`
- `error`
- `selected`
- `indexed`
- `image_id`
- `indexed_at`

候选记录使用 `object_key` 唯一约束和 `INSERT OR IGNORE` 防止恢复时重复写入。扫描按批次提交，建立素材索引时使用 `MaterialRepository.upsert_many()` 分批写入。`image_id` 必须在首次索引写入之前持久化到 candidate store；Worker 重试必须复用同一 ID。每批索引完成后再更新 `indexed` checkpoint，确保安全重跑不会产生重复素材。

任务公开结果只返回聚合计数、`manifest_ref` 和必要状态，不返回全量候选数组。若后续需要候选明细，必须使用 cursor pagination。读取历史任务时仍兼容旧版小型 `scan/result.json.candidates`，但新任务不得继续写该数组。

## 7. Local 文件流式扫描

现有 `LocalStorageProvider.list_objects()` 会对整个子树执行 `list()` 和全量 `sorted()`，重复分页会反复扫描目录，不适合大规模导入。

本轮增加局部的流式遍历能力：

- 以 Provider capability 方式提供，不在业务代码散布 `if local`；
- Local Provider 使用稳定的目录遍历，一次任务只遍历一次；
- 内存占用与单目录宽度或当前批次相关，不与素材总数线性增长；
- 远程 Provider 继续复用现有 cursor pagination；
- 恢复扫描允许从 checkpoint 继续，候选唯一约束保证幂等。

现有通用 `list_objects` 合同继续保留，避免重构 OSS、S3 和 Remote Provider。

## 8. ZIP 安全与磁盘保护

解压前必须检查全部 ZIP 成员，拒绝：

- `../` 或任何父目录逃逸；
- POSIX 绝对路径；
- Windows drive/UNC 路径；
- 反斜杠归一化后的逃逸；
- NUL；
- 符号链接和特殊文件；
- 解析后越过目标 prefix；
- 多个成员归一化到同一目标路径。

还必须防止 Zip Bomb。限制全部由跨平台配置或环境变量提供，至少包括：

- ZIP 总 member 数上限；
- 单 member 声明解压大小上限；
- 总声明解压大小上限；
- 异常压缩比上限；
- 实际单文件和累计解压字节上限。

实际写入字节不得超过 member 声明值和任务预估安全上限。解压过程中定期复查剩余磁盘空间；异常增长或空间不足必须立即失败并报告错误码、当前剩余空间、预计需要空间、实际已写入和解决方案。

禁止调用未经保护的 `ZipFile.extractall()`。

磁盘检查使用 ZIP 中声明的非目录成员解压总大小，加可配置安全余量。空间不足时任务在写入前失败，并返回：

- 当前可用空间；
- 预计解压大小；
- 要求的安全余量；
- 处理建议。

### 8.1 Staging 与发布

ZIP 不直接解压到正式素材目录。每个任务只可写入：

```text
<local-root>/.import-staging/<task_id>/payload/
```

完整校验 ZIP、磁盘空间和全部成员后才开始流式解压到 staging。解压完成后校验文件数、字节数、CRC 和路径，再把 staging payload 在同一文件系统内原子发布为目标 prefix。

服务器 ZIP 的 `target_prefix` 必须是非空安全相对目录。若正式目标目录已经存在且非空，任务默认失败并明确提示“目标目录已存在”；本轮不支持 merge 或 overwrite。若目标目录存在但为空，可安全移除空目录后原子发布。

失败或取消只清理当前任务的 staging，绝不能删除或修改已有正式素材。Worker 异常退出时保留 staging 供恢复；受控失败、取消或成功发布后清理当前任务 staging。

Local 全根目录扫描必须排除保留目录 `.import-staging`，避免未发布文件进入素材池。

### 8.2 发布恢复

发布前在 payload 内写入只属于当前任务的发布标记。若 Worker 在目录原子发布后、checkpoint 写入前退出，恢复逻辑只能在目标目录存在匹配 task ID 的发布标记时接管该目录；否则非空目标仍按冲突失败。恢复确认发布归属后更新 checkpoint 并移除标记。

## 9. 素材去重语义

扫描去重至少按真实 `content_sha256` 判断，不按文件名判断。

- 同 SHA256 已存在于当前项目统一素材池：计为 duplicate，不新建素材记录；
- 相同 `storage_source_id + object_key` 已索引：计为 duplicate；
- 相同文件名、不同 SHA256：视为不同素材；
- 确认和任务恢复时再次执行去重，防止扫描后到确认前发生竞态。

`MaterialRepository` 增加 `content_sha256` 索引和分块查询接口，避免 SQLite 参数上限和每张素材单独查询。

新建索引的素材记录包含：

```text
filename
storage_source_id
storage_type=local
object_key
content_sha256
size_bytes
etag
```

不得产生 `projects/<project_id>/uploads/<copy>`。

## 10. 预览、标注、清洗与训练

导入后素材继续通过现有 `StorageManager` 解析：

```text
image_id
  -> MaterialRepository
  -> storage_source_id + object_key
  -> LocalStorageProvider
  -> root / object_key
```

缩略图、详情、人工标注、批量标注、AI 标注、清洗、训练选择和训练快照不得自行拼接项目 uploads 路径。

训练时允许训练快照或内容寻址缓存产生必要的临时物化文件，但源素材不会被永久复制为项目本地素材。

删除默认只删除平台索引；只有明确选择 `delete_source=true` 并通过现有二次确认后才删除源文件。

## 11. YOLO ZIP 行为

本轮服务器 ZIP：

- 正常扫描并索引支持的图片；
- `labels/*.txt`、`data.yaml` 和其他非图片文件计入跳过数，不作为失败；
- 不把标注或数据集 split 信息传给训练算法；
- 不直接复用当前与项目 uploads、dataset 分组和旧线程任务耦合的导入器。

因此本轮明确标记：服务器 ZIP 的 YOLO txt annotation import 未实现。已有浏览器 ZIP 导入保持现状，不因本轮改动回退。

## 12. 前端交互

沿用现有素材导入和存储配置 UI，不新增一级菜单。

导入弹窗提供三个入口：

1. 浏览器上传；
2. 服务器本地目录；
3. 服务器 ZIP。

目录模式字段：

- Local Storage Source；
- 相对目录 prefix；
- 是否递归；
- 扫描按钮。

ZIP 模式字段：

- 允许目录下的 ZIP；
- 目标 Local Storage Source；
- 目标 prefix；
- 开始解压并扫描按钮。

目录扫描总数未知时不显示百分比，只显示真实计数和当前路径。ZIP 解压只有在中央目录声明总字节可用时，才按实际已解压字节显示可证明的进度。

任务进入 `AWAITING_CONFIRMATION` 后展示扫描摘要和确认按钮。确认 API 只持久化选择、调用 TaskRepository 的原子重新排队方法并返回；确认后继续轮询同一任务的 indexing 状态。每批索引独立提交并保存 checkpoint。关闭弹窗只停止浏览器轮询，不发送取消请求。

## 13. Linux/NVIDIA 启动安全

调整 launcher 的 Torch 决策：

- Windows CPU：保留现有已验证 CPU wheel 安装路径；
- NVIDIA Linux：若 Torch、TorchVision 可导入且 `torch.cuda.is_available()` 为真，直接复用现有 CUDA Torch，不因固定版本不同而重装；
- Linux 已有可用 Torch：不使用 PyTorch CPU index 强制覆盖；
- Linux 缺少可用 Torch：明确报告环境缺失和安装建议，不自动修改 CUDA/Driver；
- 不执行 Windows-only shell 或进程调用。

测试必须证明 CUDA 可用探测结果会阻止 CPU Torch 安装命令执行。

## 14. 错误处理

错误响应必须包含具体原因和建议，至少覆盖：

- Storage Source 不存在、停用或不是 Local；
- root 不存在、不可读或不可写；
- prefix 越界；
- ZIP 不存在、不可读、损坏或不在允许目录；
- ZIP 成员路径不安全；
- ZIP 包含符号链接或特殊文件；
- 磁盘空间不足；
- 图片损坏或无法解析；
- SHA256 计算失败；
- SQLite 写入失败；
- Worker 恢复失败；
- 源文件在扫描后被删除或修改。

任何失败不得伪装为成功，也不得静默跳过被选中的训练素材。

## 15. 测试与验收

实现遵循测试驱动：先添加能复现缺口的失败测试，再写最小实现。

必须覆盖：

1. Local source 使用临时绝对 root；
2. recursive scan；
3. prefix scan；
4. path traversal 拒绝；
5. 10k+ 文件流式扫描；
6. SHA256 去重；
7. 同文件名不同内容；
8. 扫描不复制原文件；
9. material preview；
10. annotation read/save；
11. StorageManager materialize local；
12. training snapshot 使用 local indexed material；
13. 删除索引不删除源文件；
14. 显式确认后删除源文件；
15. ZIP 正常解压；
16. ZIP 多层目录；
17. `../` Zip Slip 拒绝；
18. absolute path 拒绝；
19. Windows drive/反斜杠逃逸拒绝；
20. symlink 拒绝；
21. 损坏 ZIP；
22. 磁盘不足；
23. task 重启恢复；
24. 关闭弹窗不取消 Worker；
25. Node frontend tests；
26. Playwright 核心流程；
27. Windows 全量 regression；
28. Linux launcher CUDA 保持测试。

有条件时执行 100k 文件压力测试，记录耗时、峰值内存、数据库条数和额外素材副本数。未在真实 Linux/NVIDIA、真实 3GB ZIP 或真实生产目录执行的项目必须明确标记“未验证”。

## 16. 完成定义

只有同时满足以下条件才可报告完成：

- 代码、API、Worker、数据库和前端状态一致；
- 服务器目录扫描真实执行并建立索引；
- ZIP 真实解压、扫描、等待确认、批量索引；
- 安全测试真实拒绝恶意 ZIP；
- 结果文件存在且数据库数据正确；
- 素材未被复制到项目 uploads；
- 预览、标注、materialize 和训练快照回归通过；
- Windows 全量测试通过；
- Linux/NVIDIA 未实测的部分如实报告；
- 最终提交已推送到 `origin/feat/windows-p0`；
- 不修改或合并 `main`。
