# W4 存储冷路径与缓存优化（2026-11-22）

> 隔离 loopback RemoteStorageProvider + MaterialCache；不是阿里云 OSS / MinIO / NAS 生产延迟。
> 未连接生产 Bucket、未修改正式素材/GT、未切换训练 Bundle 路线。

## 1. 调用链审计

| 路径 | 事实 |
|---|---|
| `StorageManager.materialize()` | 通过 StorageProvider + `MaterialCache.materialize()`；远程有 expected SHA 时冷路径 GET + 缓存 SHA 发布 |
| `StorageManager.thumbnail()` | 缩略图缓存命中直接返回；miss 时 `materialize(row, read_only=True)` 再解码 |
| `LocalStorageProvider` | `stat()` 每次计算整文件 SHA；本地 `materialize()` 返回源路径，不经 MaterialCache |
| `OSSStorageProvider` | 下载用 `get_object_to_file` 写目标文件；原 `materialize_to_local` 在 GET 后显式调用 `stat()`；SDK 内部是否 HEAD 未实测 |
| `S3StorageProvider` | `download_fileobj` 写文件；boto3 1.43.89 / botocore 1.43.89 / s3transfer 0.19.2；SDK 默认在下载前 `head_object`（checksum/size/etag），原代码在 GET 后**再**显式 `stat()` |
| `RemoteStorageProvider` | 1 MiB 分块流式写临时文件 + fsync + `os.replace`；原 GET 后显式 meta 请求 |
| `MaterialCache.materialize` | 目标按内容 SHA 命名；per-target FileLock；临时文件校验 SHA 后 `os.replace`；失败清理 |
| `MaterialCache.thumbnail` | pointer + 派生 JPEG；pointer/target 均校验 SHA；独立锁 |
| 训练准备 | `TrainingPrepareHandler` 用 `storage.materialize(row)` 取每张素材，构建 portable dataset/bundle，再上传对象存储；Worker 走 Bundle 路线 |

关键结论：

- 同一对象的并发冷读取由目标 SHA 的 `FileLock` 串行化；第一个下载，其余等待后命中，**不会重复 GET**（测试覆盖）。
- Remote/loopback：原为 **GET + meta**；本轮去掉显式 meta，实测 meta=0。
- S3：`download_fileobj` 内部仍会 HEAD；本轮只去掉我们显式 `self.stat()`。因此 S3 的真实请求数不是“0 HEAD”，必须标 `NOT_VERIFIED`，且**没有关闭 checksum 验证**。
- OSS：只可确认去掉了显式 `stat()`；SDK 内部 HEAD 未实测。
- 热路径 0 远程请求；但每次命中会重新计算缓存文件 SHA（大文件有本地 I/O 成本）。
- 缓存写入是原子发布：临时文件完整、SHA 正确后才 `os.replace`；失败不留下可误用的完整缓存。
- `download()` 与 `open_reader()` 均为有界流式路径：Remote 1 MiB/调用方分块；OSS/S3 SDK 写文件。
- 本地素材读取每次 `stat()` 会整文件 SHA；未缓存，属于后续候选，但本轮未改。
- 训练 Bundle 当前仍有控制端下载素材后重新打包上传的路径；本轮保留为默认，未切 Worker 直达。

## 2. W4-B 隔离测量

`tests/performance/test_remote_cache_cold_w4.py`（`RUN_W4_REMOTE=1`）：

真实 loopback HTTP RemoteStorageProvider，12 次独立冷缓存、30 次热命中、10 并发同对象。

| 场景 | 冷 P50/P95 | 热 P50/P95 | 冷 GET / meta | 热 GET / meta | 10 并发 |
|---|---:|---:|---:|---:|---:|
| 64 KB | 47.02 / 149.17 ms | 2.72 / 4.15 ms | 12 / 0 | 0 / 0 | 341.50 ms，GET=1，meta=0 |
| 8 MB | 147.86 / 165.59 ms | 32.46 / 43.21 ms | 12 / 0 | 0 / 0 | 650.38 ms，GET=1，meta=0 |

此表为 nearest-rank P95 修正后的单次运行；早先 40.68/50.62 与 142.94/166.72 的 P95 是 floor 下标，已废弃。

说明：

- 冷值包含 12 个不同缓存目录的完整 GET+落盘+SHA；不是单个缓存实例的重复。
- P95 使用 nearest-rank：`ceil(n*0.95)-1`。
- Remote loopback 优化前为 GET + meta，优化后 GET only（meta=0）；HEAD/meta 的独立 P50/P95 未测。
- 该结果不能外推为 OSS/S3 真实请求数；S3 SDK 内部 HEAD 仍存在。
- 热值仍包含缓存 SHA 校验（大文件 39 ms）；未优化。
- 并发只发生 1 次 GET，其余等待后命中；无 meta 请求。
- 真实 OSS/MinIO/NAS 网络、首字节、RSS、SHA 次数：`NOT_VERIFIED`。

## 3. W4-C 已实施优化

原问题：三个 Provider 的 `materialize_to_local` 在内容 GET 成功后显式调用 `stat()`，产生我们代码主动发出的额外 HEAD/meta。

修复：

- `download(..., include_metadata=False)` 供 `materialize_to_local` 使用；
- 返回本地文件大小构造的 `ObjectMetadata`（仅 key/size_bytes）；
- 普通 `download()` 默认仍 `include_metadata=True`，保留原 API 的远程元数据；
- `MaterialCache` 仍计算 SHA 并校验 expected，不降低完整性；
- S3 SDK 内部 checksum/HEAD 未关闭；详见第 3.1 节。
- 失败清理、临时文件、原子 rename、缓存 SHA 校验均未变。

效果：

- 明确去掉我们代码主动发出的 1 次 HEAD/meta；
- 内容 GET 次数不变；
- 热缓存/并发去重不变；
- Remote loopback：cache cold content=1/meta=0；hot 0/0；直接 `provider.download` 仍 meta=1；
- S3/OSS 真实请求数：`NOT_VERIFIED`。

### 3.1 materialize_to_local 返回值合同

全仓调用方只有 `MaterialCache.materialize()`，它**完全忽略返回值**，只读取临时文件计算 SHA。
`include_metadata=False` 返回的 key/size_bytes 没有 SHA/ETag/Content-Type/Last-Modified，当前不会影响调用方。
普通 `download()` 默认仍返回完整远程 metadata；没有其他调用方被静默改变。
如果未来新增调用方，必须显式选择 `include_metadata=True` 或自行校验 SHA。

### 3.2 Remote open_reader 流式修复

原 `RemoteStorageProvider.open_reader()` 使用 `BytesIO(response.content)`，整文件进内存。
现改为 `requests.get(..., stream=True)` + `_RemoteResponseReader`（`RawIOBase`）：

- `read(size)` / `readinto()` 直接读 `response.raw`；
- `raw.decode_content=True`，与旧 `response.content` 的 Content-Encoding 解码字节语义一致；
- `close()` 关闭 HTTP response，`with` 自动关闭；关闭后读取抛 ValueError；
- 状态错误时先关闭 response，再走原 `_raise` 映射；
- 认证/超时/对象键安全不变；
- `download()` 和 MaterialCache SHA 校验未变。

隔离 loopback 测试：2 MB 内容先读 16 字节再读完，非 BytesIO，关闭后 `reader.closed=True`。
真实 OSS/MinIO 内存/RSS：`NOT_VERIFIED`。

### 3.3 S3/OSS SDK 内部请求

- boto3 1.43.89 / botocore 1.43.89 / s3transfer 0.19.2；
- s3transfer `DownloadSubmissionTask` 默认会 `head_object` 获取 size/ETag 做 response checksum validation；只有显式 `response_checksum_validation="when_required"` 才跳过，本轮**未设置**，不能为减少 HEAD 关闭校验；
- OSS `get_object_to_file` 是否内部 HEAD 未实测；
- 因此 S3/OSS 的 HEAD 数量只报告源码推断，`NOT_VERIFIED`。

没有改 Provider API、StorageManager、ArtifactStore、缓存路径或训练 Bundle。

## 4. Worker 直达存储的前提

未来 GPU Worker 直接从 OSS/NAS 读取，至少需要：

1. 冻结的 image_id + content_sha256 + size + object_key/source revision；
2. Worker 认证节点身份与 source 权限，不能信任调用方传入的 node_id；
3. NAS 挂载身份/可达性合同 + 有界超时 + 独立探测执行；不能把阻塞文件系统调用放在中央调度热路径；
4. 最小权限短期凭据（OSS/S3 presign 或节点 token），不把长期密钥写入任务 payload；
5. 本地 SSD/NVMe 内容寻址缓存，SHA/Revision 验证，原子发布与 GC；
6. 任务取消/重试/租约失效时缓存和临时文件可回收，不产生双主人；
7. 失败可回退 Bundle 路线；
8. 真实跨节点端到端验证通过前，禁止切换默认训练数据传输路径。

W6 当前 `node_id` 由调用参数提供，尚未接入 Node Agent 认证；这是未来准入前置，不是已实现能力。

## 5. 未验证

- 真实阿里云 OSS/S3/MinIO 冷/热延迟、首字节、带宽、重试；
- 真实 NAS stale handle/断网/ACL；
- 大文件 RSS、缓存 SHA 次数、磁盘 I/O；
- Worker 直达/SSD 缓存/GC；
- 控制端 Bundle 下载+重传的真实传输量；
- 生产 20 万/百万素材。
