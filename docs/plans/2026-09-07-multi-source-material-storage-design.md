# 多来源素材存储设计

**状态：** 已确认  
**目标版本：** 42.22.0  
**原则：** 统一素材池、精确图片 ID 训练、非破坏升级、真实存储操作、跨平台运行。

## 1. 目标与边界

本次只扩展素材文件的物理存储位置，不增加数据集分组概念。素材库仍是统一素材池，标签只用于筛选，训练任务只能保存 `train_image_ids` 与 `test_image_ids`。

禁止在上传、预览、标注、清洗、训练和部署测试代码中分别判断本地、OSS、S3 或远程类型。所有文件操作必须经过统一的 `StorageManager` 和 `StorageProvider`。

## 2. 已确认的现状

- 项目素材索引由每个项目的 `images.json` 保存，任意修改会整体读取并重写。
- 真实项目 28,899 张素材时，索引已达到约 36.7 MB，本机完整解析约 2.85 秒，列表 API 返回约 28.4 MB。
- 上传、删除、清洗、人工/AI 标注、视频切帧、导出和训练 Worker 中存在多处 `project/uploads/stored_name` 直接路径拼接。
- 训练请求和 Worker 仍残留 `train_dataset_ids`、`test_dataset_ids` 及按数据集回退逻辑。
- 已有 `SecretStore`、`KeyringSecretStore` 和 `secret_ref` 可用于保存存储凭据。
- 已有任务仓库使用 SQLite WAL、事务和 busy timeout，可复用其数据库模式。

## 3. 总体架构

采用分阶段兼容方案：

```text
平台级 StorageSourceRepository
             |
             v
项目级 MaterialRepository
             |
             v
StorageManager -> StorageProviderFactory
             |       |       |       |
           Local    OSS      S3    Remote HTTP
             |
             v
MaterialResolver / MaterialCache
```

业务服务只传递素材记录或 `image_id`。Provider 类型分派只能存在于 Provider 工厂中。

## 4. 数据模型

### 4.1 存储源

平台级 SQLite 表 `storage_sources` 保存：

- `id`、`name`、`type`；
- Endpoint、Region、Bucket、Prefix、根目录、命名空间等非敏感配置；
- `secret_ref`、是否已配置凭据；
- 是否启用、是否默认；
- 最近检测时间、检测状态和脱敏错误；
- 创建、更新时间。

系统启动时幂等创建不可删除的 `default_local`（平台本地存储）。本地根目录由运行时数据目录与项目 ID 解析，不写死 Windows 或 Linux 路径。

### 4.2 素材索引

每个项目使用 `materials.sqlite3`，核心表保存：

- 素材业务字段：`id`、`filename`、尺寸、处理状态、来源类型、时间；
- 存储引用：`storage_source_id`、`storage_type`、`object_key`；
- 完整性字段：`content_sha256`、`size_bytes`、`etag`；
- 标注摘要与兼容扩展 JSON。

`material_labels` 独立建表并为 `label_code`、`material_id` 建索引，实现多标签 OR 查询。文件名、存储源、处理状态和创建时间均建立查询索引。

### 4.3 旧数据迁移

首次访问项目时，在事务中把旧 `images.json` 导入 SQLite：

```text
storage_source_id = default_local
storage_type = local
object_key = uploads/<stored_name>
```

迁移幂等且记录源文件签名。原 `images.json` 和 `project/uploads` 不移动、不删除；升级前索引保留为只读安全备份。素材文件缺失会记录明确状态，不会伪造成功。

## 5. Provider 契约

统一能力包括：

- `health_check`
- `stat`
- `exists`
- `open_reader`
- `download`
- `upload`
- `delete`
- `list_objects`
- `generate_preview_url`
- `generate_upload_url`
- `materialize_to_local`

实现包括 `LocalStorageProvider`、`OSSStorageProvider`、`S3StorageProvider`、`RemoteStorageProvider`。SDK 或运行环境缺失时返回结构化环境错误，不返回假成功。

远程服务器第一版采用版本化 HTTP 素材协议，包含健康检测、对象查询、流式上传下载、删除、分页列举和可选签名 URL。不会假定 Web/API 进程可以直接访问另一台服务器的文件系统。

## 6. 密钥处理

数据库和普通配置文件不得保存 AccessKey Secret、Secret Key 或 Token。凭据以 `secret_ref` 写入 `SecretStore`。API 只返回是否配置、脱敏值和引用，不返回真实值。

Windows 开发环境使用系统 Keyring；Linux Worker 支持 Keyring 或环境变量注入的只读 Secret 引用。

## 7. 素材访问与预览

前端统一使用平台内容端点：

```text
/api/v61/projects/{project_id}/materials/{image_id}/content
```

本地素材由平台流式返回；OSS/S3 优先重定向到短期签名 URL；不支持签名的远程源由平台代理流。永久凭据不进入浏览器。

清洗、AI 标注、训练和部署测试需要本地路径时，调用 `MaterialResolver.materialize(image_id)`。

## 8. 内容寻址缓存

远程文件缓存位于：

```text
<data_dir>/cache/materials/<sha256-prefix>/<sha256>.<ext>
```

缓存写入使用每哈希文件锁、临时文件、SHA256 校验和原子替换。缓存命中仍校验文件。远程文件不存在、下载超时、文件为空或哈希不一致时，当前业务任务明确失败，不跳过所选素材。

## 9. 上传、远程导入和删除

上传弹窗增加“保存位置”。普通图片批量上传通过后端流式传递给 Provider，成功写入并完成校验后才建立素材索引。

“从存储导入素材”由持久化后台任务分页扫描，支持前缀和递归选项。确认后只建立 `image_id -> storage_source_id -> object_key` 映射，不复制外部源文件。

删除操作明确区分：

- 只移除平台索引；
- 删除平台索引并删除源文件。

外部存储默认只移除索引。源文件删除失败时保留索引并返回真实错误。仍有素材引用的存储源不可删除，只能停用。

## 10. 查询与前端

“展开高级功能”的资源配置中增加“素材存储配置”，沿用现有页面结构。

素材列表改为 SQLite 服务端分页，支持文件名、处理状态、来源、标注状态和多标签 OR 筛选。来源仅作轻量筛选和标识，不替代标签，也不形成数据集分组。

训练素材选择仍默认 0 张，并保留逐张选择、当前筛选批量选择、反选、全不选。提交和持久化结果始终为确定的图片 ID 列表。

## 11. 训练链路

训练 API、任务 payload、快照和 Worker 只接受：

```text
train_image_ids
test_image_ids
```

彻底移除 `train_dataset_ids`、`test_dataset_ids`、`dataset_id` 训练选择和 Worker 数据集回退。

Worker 按图片 ID 读取素材仓库，通过 `MaterialResolver` 获取本地可用文件，校验快照 SHA256，再构建可移植 YOLO bundle。任何一张所选素材不可获取都会终止任务并返回具体素材 ID、存储源和错误原因。

算法版本迭代仍由现有严格最新版本选择逻辑决定，不受存储来源影响。

## 12. 发布和验证策略

实现顺序：

1. 先写兼容、迁移、Provider、缓存和训练协议失败测试；
2. 实现 SQLite 仓库和默认本地 Provider；
3. 接入上传、预览、删除、清洗、标注、视频和训练 Worker；
4. 实现 OSS、S3、远程 Provider 与远程索引；
5. 接入配置页、上传位置和来源筛选；
6. 执行 API、Worker、浏览器和旧功能回归。

本地与远程 HTTP 源可在当前 Windows 环境真实验证。S3 优先使用真实 MinIO 服务验证。阿里云 OSS 的成功链路必须使用真实测试 Bucket 与凭据；环境不可用时标为 `BLOCKED_BY_ENVIRONMENT`，不得当作通过。

## 13. 非目标

- 不新增数据集分组训练；
- 不重做配置中心 UI；
- 不移动历史素材；
- 不在第一版本承诺所有浏览器直传、分片和断点能力；
- 不用模拟成功替代真实 Provider、Worker 或模型运行。
