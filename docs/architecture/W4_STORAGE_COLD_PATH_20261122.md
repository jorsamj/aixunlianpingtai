# W4 存储冷路径与缓存优化（2026-11-22）

> 隔离 loopback RemoteStorageProvider + MaterialCache；不是阿里云 OSS / MinIO / NAS 生产延迟。
> 未连接生产 Bucket、未修改正式素材/GT、未切换训练 Bundle 路线。

## 1. 调用链审计

| 路径 | 事实 |
|---|---|
| `StorageManager.materialize()` | 通过 StorageProvider + `MaterialCache.materialize()`；远程有 expected SHA 时冷路径 GET + 缓存 SHA 发布 |
| `StorageManager.thumbnail()` | 缩略图缓存命中直接返回；miss 时 `materialize(row, read_only=True)` 再解码 |
| `LocalStorageProvider` | `stat()` 每次计算整文件 SHA；本地 `materialize()` 返回源路径，不经 MaterialCache |
| `OSSStorageProvider` | 下载用 `get_object_to_file` 写目标文件；原 `materialize_to_local` 在 GET 后额外 HEAD |
| `S3StorageProvider` | `download_fileobj` 写文件；原 `materialize_to_local` 在 GET 后额外 HEAD |
| `RemoteStorageProvider` | 1 MiB 分块流式写临时文件 + fsync + `os.replace`；原 GET 后额外 meta 请求 |
| `MaterialCache.materialize` | 目标按内容 SHA 命名；per-target FileLock；临时文件校验 SHA 后 `os.replace`；失败清理 |
| `MaterialCache.thumbnail` | pointer + 派生 JPEG；pointer/target 均校验 SHA；独立锁 |
| 训练准备 | `TrainingPrepareHandler` 用 `storage.materialize(row)` 取每张素材，构建 portable dataset/bundle，再上传对象存储；Worker 走 Bundle 路线 |

关键结论：

- 同一对象的并发冷读取由目标 SHA 的 `FileLock` 串行化；第一个下载，其余等待后命中，**不会重复 GET**（测试覆盖）。
- 远程冷路径原为 **GET + HEAD/meta**；HEAD 只用于返回 ObjectMetadata，`MaterialCache` 实际不使用返回值。
- 热路径 0 远程请求；但每次命中会重新计算缓存文件 SHA（大文件有本地 I/O 成本）。
- 缓存写入是原子发布：临时文件完整、SHA 正确后才 `os.replace`；失败不留下可误用的完整缓存。
- 远程流式读取有界（Remote 1 MiB chunk；OSS/S3 SDK 写文件）；未发现整文件读入内存的路径。
- 本地素材读取每次 `stat()` 会整文件 SHA；未缓存，属于后续候选，但本轮未改。
- 训练 Bundle 当前仍有控制端下载素材后重新打包上传的路径；本轮保留为默认，未切 Worker 直达。

## 2. W4-B 隔离测量

`tests/performance/test_remote_cache_cold_w4.py`（`RUN_W4_REMOTE=1`）：

真实 loopback HTTP RemoteStorageProvider，12 次独立冷缓存、30 次热命中、10 并发同对象。

| 场景 | 冷 P50/P95 | 热 P50/P95 | 冷 GET / meta | 热 GET / meta | 10 并发 |
|---|---:|---:|---:|---:|---:|
| 64 KB | 40.68 / 50.62 ms | 4.90 / 6.83 ms | 12 / 0 | 0 / 0 | 308.75 ms，GET=1，meta=0 |
| 8 MB | 142.94 / 166.72 ms | 39.23 / 46.97 ms | 12 / 0 | 0 / 0 | 714.62 ms，GET=1，meta=0 |

说明：

- 冷值包含 12 个不同缓存目录的完整 GET+落盘+SHA；不是单个缓存实例的重复。
- 优化前每个冷对象为 GET + HEAD/meta；优化后为 GET only（meta=0）。HEAD 的 P50/P95 未单独测；loopback 下约 1 RTT。
- 热值仍包含缓存 SHA 校验（大文件 39 ms）；未优化。
- 并发只发生 1 次 GET，其余等待后命中；无 meta 请求。
- 真实 OSS/MinIO/NAS 网络、首字节、RSS、SHA 次数：`NOT_VERIFIED`。

## 3. W4-C 已实施优化

原问题：`OSSStorageProvider.materialize_to_local` / `S3StorageProvider.materialize_to_local` / `RemoteStorageProvider.materialize_to_local` 在内容 GET 成功后又调用 `stat()`，产生一次不必要的 HEAD/meta。

修复：

- `download(..., include_metadata=False)` 供 `materialize_to_local` 使用；
- 返回本地文件大小构造的 `ObjectMetadata`；
- 普通 `download()` 默认仍 `include_metadata=True`，保留原 API 合同的元数据返回；
- `MaterialCache` 仍计算 SHA 并校验 expected，不降低完整性；
- 失败清理、临时文件、原子 rename、缓存 SHA 校验均未变。

效果：

- 每次远程冷读取少 1 次 HEAD/meta 请求；
- 内容 GET 次数不变；
- 热缓存/并发去重不变；
- `tests/integration/test_remote_storage_provider.py` 真实 loopback 验证：
  - cache cold：content=1, meta=0；
  - cache hot：content=0, meta=0；
  - 直接 `provider.download` 仍 meta=1（旧合同保留）。

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
