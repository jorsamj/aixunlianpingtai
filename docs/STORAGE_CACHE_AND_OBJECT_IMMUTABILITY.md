# OSS / S3 素材缓存与对象不可变契约

**适用阶段：** v42.25 技术债关闭 / 全 OSS 素材生产准备  
**正式 VERSION：** 仍为 `42.24.0`，本文不代表发布版本变更。

## 1. 目标

远程素材进入训练链路后，必须同时满足：

1. 不在每次训练时重复下载已经验证过的远程素材；
2. 不让节点热缓存无限增长直至挤满磁盘；
3. `MC_TRAIN_DATA_DIR` 即使使用 NFS / 共享盘，也不能把“共享目录”误报成“Worker 本地缓存”；
4. 不允许平台自己把同一个 OSS / S3 `object_key` 静默覆盖成另一份内容；
5. 不为了验证远端是否变化，在每次 1 万张训练前额外发起 1 万次 HEAD 请求；
6. 外部绕过平台直接改远端对象时，必须通过重新扫描 / 恢复流程确认变化，再更新平台素材真值；
7. 多 Worker / 多节点观测必须复用现有 Worker Runtime Truth，不能新增第二套 heartbeat / registry / Scheduler；
8. 前端不能把“未知”显示成 `0 B`，也不能把无法证明物理独立的节点缓存简单求和成“集群总容量”。

## 2. 当前真实链路

```text
OSS / S3 / Remote
        |
        | 首次或内容缓存 miss
        v
MaterialCache
  ├─ MC_MATERIAL_CACHE_DIR（推荐：节点本地 SSD / NVMe）
  └─ 未配置时兼容回退：<data_dir>/cache/materials
        |
        v
训练任务 portable bundle
        |
        v
TrainingBundleCache
<data_dir>/cache/training-bundles/<project>/<snapshot_id>
        |
        v
YOLO / 训练 Worker
```

因此目前仍是两层复用：

- **MaterialCache**：按素材 SHA256 复用远程原始文件；
- **TrainingBundleCache**：按完整训练 Snapshot 复用已经验证的训练 Bundle。

同一批完整 Snapshot 再次训练时，可以直接命中 TrainingBundleCache；训练素材发生局部变化、Bundle Cache miss 时，未变化素材仍可从 MaterialCache 复用，只下载新增或本地缺失的内容。

MaterialCache 路径现在与业务数据根目录解耦。生产环境若 `MC_TRAIN_DATA_DIR` 为 NFS / 共享盘，应显式设置：

```text
MC_MATERIAL_CACHE_DIR=/node-local-ssd/changlian/material-cache
```

这样业务数据可以共享，而远程素材热点缓存留在每个 Worker 节点的本地 SSD / NVMe。

## 3. MaterialCache 生命周期

### 3.1 路径与默认值

缓存根目录解析顺序：

```text
1. MC_MATERIAL_CACHE_DIR
2. <MC_TRAIN_DATA_DIR>/cache/materials  （兼容回退）
```

对应真值：

```text
MC_MATERIAL_CACHE_DIR
  cache_scope       = configured_cache_dir
  cache_root_source = MC_MATERIAL_CACHE_DIR

兼容回退
  cache_scope       = data_dir_cache
  cache_root_source = data_dir
```

`data_dir_cache` 只表示缓存位于数据目录下，**不代表它一定是节点本地盘**。如果数据目录实际来自 NFS，该缓存也可能被多节点共享，因此平台不会再把它固定描述成 `worker_local`。

当前生命周期默认：

- 最大逻辑容量：`128 GiB`；
- TTL：`30 天`；
- 生命周期维护间隔：`5 分钟`；
- 最近访问保护窗口：`10 分钟`。

可通过环境变量覆盖：

```text
MATERIAL_CACHE_MAX_BYTES
MATERIAL_CACHE_TTL_SECONDS
MATERIAL_CACHE_MAINTENANCE_INTERVAL_SECONDS
MATERIAL_CACHE_RECENT_ACCESS_GRACE_SECONDS
```

所有值必须是非负整数。`0` 的含义：

- `MATERIAL_CACHE_MAX_BYTES=0`：不按容量淘汰；
- `MATERIAL_CACHE_TTL_SECONDS=0`：不按 TTL 淘汰；
- `MATERIAL_CACHE_MAINTENANCE_INTERVAL_SECONDS=0`：每次 materialize 都允许触发维护；
- `MATERIAL_CACHE_RECENT_ACCESS_GRACE_SECONDS=0`：取消最近访问保护窗口。

生产环境不建议同时关闭容量和 TTL 约束。

### 3.2 淘汰策略

生命周期维护遵循：

1. 先淘汰超过 TTL 的旧缓存；
2. 若剩余逻辑容量仍超过上限，再按最后访问时间做 LRU；
3. 正在使用相同对象锁的文件不会被强删；
4. 当前 materialize 的目标文件作为 protected path，不参与该轮清理；
5. 最近访问保护窗口内的文件不清理；
6. 生命周期维护失败只影响清理，不得让素材读取或训练因为“清缓存失败”而失败。

缓存命中仍执行 SHA256 完整性校验；发现本地缓存损坏后会丢弃损坏副本并重新从源端获取。

### 3.3 状态快照

MaterialCache 每次完成维护后，原子更新：

```text
<resolved-material-cache-root>/status.json
```

当前快照 schema 为：

```text
schema_version = 2
cache_kind = remote_material_content
cache_scope = configured_cache_dir | data_dir_cache
cache_root_source = MC_MATERIAL_CACHE_DIR | data_dir
```

并保存非敏感运行指标，例如：

- `after_bytes`
- `scanned_files`
- `max_bytes`
- `ttl_seconds`
- `evicted_files`
- `over_budget_bytes`
- `generated_at`

打开前端页面不会重新遍历缓存目录，也不会扫描每个缓存对象。

## 4. Node-scoped MaterialCache Runtime Truth

### 4.1 单一 heartbeat owner

缓存观测不创建自己的 timer、线程、Worker registry、Scheduler 或任务队列。

真实链路：

```text
WorkerInstanceService.acquire()
        ↓
已有 Worker instance lease
        ↓
Scheduler.serve_forever() 原 heartbeat renew
        ↓
WorkerInstanceLease renew hook
        ↓
MaterialCacheRuntimeReporter.report()
```

Worker 启动时先做一次 best-effort report；之后报告搭车已有 Worker heartbeat。

缓存报告失败不能导致本来健康的 Worker lease 失败；但报告本身仍受当前 `instance_key + owner_token` fencing 约束。失去 Worker lease 后，旧执行不能继续发布新缓存状态。

### 4.2 节点级持久真值

缓存报告持久化到已有 Task Runtime SQLite 中的：

```text
node_cache_runtime
```

唯一身份：

```text
PRIMARY KEY(node_id, cache_kind)
```

因此同一机器上的 training Worker 与 background Worker 不会被当成两个物理缓存节点。

报告包含：

- `node_id`
- `cache_kind`
- `reporter_worker_id`
- `hostname`
- `cache_scope`
- `cache_root_source`
- `snapshot_generated_at`
- `snapshot_json`
- `reported_at`

### 4.3 复用 `/api/v62/workers`

平台没有新增第二套全局 runtime API owner。

现有：

```text
GET /api/v62/workers
```

继续由 Worker Runtime Truth 提供 Worker 信息，并在对应 Worker 项中附加同一 `node_id` 的 `material_cache` 报告。

read path 不扫描缓存目录，也不写 Scheduler / task 状态。若旧数据库还没有 `node_cache_runtime` 表，读取路径返回“无缓存报告”，不会为了 GET 请求偷偷创建运行状态。

### 4.4 fresh / stale / unknown

前端按 `node_id` 去重后判断：

- reporter Worker 在线，并且 cache `reported_at` 与 reporter 最新 heartbeat 保持同步：有效上报；
- reporter 已离线：`上报已过期`；
- reporter 仍在线，但 Worker heartbeat 已继续推进、cache report 没有继续推进：`上报已过期`；
- Worker 在线但还没有有效 maintenance snapshot：`等待维护快照`；
- 没有可证明的快照：`未知`，不显示为 `0 B`；
- `over_budget_bytes > 0`：`超出缓存配额`。

当前前端允许约 `5 秒` heartbeat / report 执行偏差，用于避免同一 heartbeat 周期内因执行顺序产生瞬时假 stale。

### 4.5 不伪造“集群总缓存”

当前 UI 明确：

```text
aggregation = per_node_only_no_sum
```

原因是：不同 `node_id` 仍可能配置到同一个 NFS / 共享目录。仅凭 Node ID 无法证明底层文件系统物理独立，因此：

- 可以按节点展示各自最近报告；
- 可以展示在线节点数 / 有效快照节点数 / 未知或过期节点数；
- **不把各节点 `after_bytes` 相加成所谓“集群总占用”**。

未来若要做全局容量聚合，必须先引入可证明的 cache volume identity / storage identity，而不是简单求和。

## 5. OSS / S3 对象不可变策略

### 5.1 默认策略

OSS / S3 存储源默认：

```text
protect_existing_objects = true
```

平台后端上传同一 `object_key` 时必须采用条件写入：

- OSS：`x-oss-forbid-overwrite: true`；
- S3：`If-None-Match: *`。

如果对象已经存在，平台返回结构化错误：

```text
STORAGE_OBJECT_EXISTS
```

不允许把旧素材静默替换成新内容。

只有历史兼容场景显式设置：

```text
protect_existing_objects = false
```

才允许继续使用可覆盖写法。前端会把该状态明确显示为“允许原地覆盖（不建议）”，不会隐藏风险。

### 5.2 推荐 object_key

生产建议采用不可变 key：

```text
materials/<content_sha256>.<ext>
```

或：

```text
materials/<uuid>/<version>.<ext>
```

内容变化时产生新的 key / 新版本，而不是覆盖原对象。

## 6. 外部直接修改 OSS / S3 的边界

平台缓存按已经确认的 `content_sha256` 工作。为了保证训练启动性能，缓存命中时不会在每次训练前再对每张远端素材执行 HEAD。

如果有人绕过平台，在 OSS 控制台、其他程序或同步工具里直接覆盖已有 object_key，平台不会把这种外部操作当成已确认素材版本。

正确流程：

```text
外部源发生变化
      ↓
素材存储配置
      ↓
重新扫描 / 恢复
      ↓
系统识别 changed / missing / new
      ↓
人工确认变化
      ↓
更新素材 SHA256 / size / etag 真值
      ↓
后续训练形成新的 Snapshot / 缓存键
```

不要通过“每次训练全量 HEAD”替代这套流程，否则大规模 OSS 素材会产生明显启动延迟和请求成本。

## 7. Presigned PUT 边界

Provider 层已经具备**不可覆盖的 presigned PUT 契约**，但当前平台仍未启用正式浏览器 / 客户端直传入口。

### 7.1 受保护契约

当 `protect_existing_objects = true` 时：

- OSS `generate_upload_contract()` 把 `Content-Type` 与 `x-oss-forbid-overwrite: true` 一起签入 PUT URL，并返回客户端必须原样发送的 Header；
- S3 `generate_upload_contract()` 使用 SigV4，并把 `Content-Type` 与 `If-None-Match: *` 纳入签名；
- 返回结构同时包含 `url`、`method=PUT`、`headers`、`expires_seconds`、`overwrite_protected=true`；
- `generate_upload_url()` 继续作为兼容 URL-only 方法存在，但 URL 由同一受保护契约生成。

S3 Provider 显式使用：

```text
signature_version = s3v4
```

避免由 SDK / Region 默认行为生成不能明确证明条件 Header 已签入的旧式 presigned URL。

### 7.2 legacy opt-out

只有显式：

```text
protect_existing_objects = false
```

生成的上传契约才会返回：

```text
overwrite_protected = false
```

并且不会附加 OSS / S3 条件写 Header。

### 7.3 当前仍未开放的产品边界

本批**没有新增正式 Web API，也没有把浏览器直传接入前端上传页面**。因此不能描述成“浏览器直传功能已经上线”。正式启用前仍需完成：

1. 服务端短时效上传契约 API 与权限校验；
2. 前端严格使用返回的 URL + Headers；
3. 真实 Bucket CORS 允许条件 Header；
4. 真实 OSS / S3 上验证首传成功、同 key 二次上传被拒绝、过期 URL 被拒绝；
5. 上传完成后的对象 SHA256 / size / etag 回写及素材确认流程；
6. 必要时采用不可变 key / Bucket versioning 作为第二层保护。

## 8. 前端真实展示

“素材存储配置”页面当前展示：

- 本地源：`本地直读 · 训练 Bundle 缓存`；
- OSS / S3 / Remote：`SHA256 素材内容缓存 · 训练 Bundle 缓存`；
- OSS / S3 默认：`平台写入禁止原地覆盖 · 外部变更需重新扫描`；
- 显式 legacy 覆盖模式：`允许原地覆盖（不建议）`；
- `Worker 节点素材缓存` 面板：按 `node_id` 去重显示状态、占用、文件数、容量上限、TTL、快照时间与上报时间；
- 汇总只显示在线节点数、有效快照节点数、未知/过期节点数；不显示未经证明的“集群总缓存 GB”。

前端不能显示“OSS 已实时同步”“当前集群缓存为 X GB”或把缺失快照表示为 `0 B` 等没有后端真值支撑的状态。

## 9. 生产建议

即使平台默认禁止自身覆盖，生产 Bucket 仍建议：

- Bucket / IAM 权限最小化；
- 禁止无关账号直接覆盖训练素材前缀；
- 对关键素材前缀开启版本化或审计日志；
- Worker 使用同地域 / 同 VPC Endpoint，避免跨公网拉取训练素材；
- `MC_TRAIN_DATA_DIR` 可承担共享业务数据；
- 当 `MC_TRAIN_DATA_DIR` 使用 NFS / 共享盘时，显式设置每个节点的 `MC_MATERIAL_CACHE_DIR` 到节点本地 SSD / NVMe；
- 多 Worker 时按 `node_id` 观察缓存，而不是按 Worker PID 重复统计；
- 若未来需要真实“集群缓存总量”，先建立底层 cache volume 唯一身份再聚合。

## 10. 永久验证范围

永久测试 / guard 覆盖：

- MaterialCache 首次 miss、再次 hit、并发同 SHA 只下载一次；
- 本地缓存损坏重新下载；
- TTL / LRU 容量清理；
- protected / locked 文件不被强删；
- 生命周期环境变量；
- `MC_MATERIAL_CACHE_DIR` 与共享 data dir 分离；
- 未配置时兼容回退路径与 `data_dir_cache` 真值；
- schema v2 状态快照；
- Worker cache report 必须持有当前 Worker lease；
- lease 释放后旧 reporter 不能继续发布；
- 同一 `node_id` 的多个 Worker 只产生一份 node cache report；
- observability hook 失败不破坏 Worker heartbeat；
- 前端按 node 去重且明确 `per_node_only_no_sum`；
- reporter 离线时报告 stale；
- reporter 仍在线但 heartbeat 继续前进、report 不前进时报告 stale；
- 缺失快照显示未知而不是 0；
- 前端禁止回退到 `/data/cache/materials/status.json` 单 Web 节点读法；
- OSS 默认禁止覆盖与 `STORAGE_OBJECT_EXISTS`；
- S3 默认 `If-None-Match: *`；
- legacy 覆盖必须显式 opt-out；
- OSS presigned PUT 签入 `x-oss-forbid-overwrite: true`；
- S3 presigned PUT 强制 SigV4，`X-Amz-SignedHeaders` 包含 `content-type` 与 `if-none-match`；
- 真实 `boto3` / `oss2` SDK 离线签名路径。

真实 OSS / S3 Bucket、Bucket CORS、真实多节点 NFS/NVMe 部署与真实多节点缓存命中率仍属于生产环境验收，不得用 mock / GitHub Actions 代替。

## 11. 历史关闭证据

### 11.1 Storage Cache Governance 基础批次

```text
validated implementation HEAD:      748958541aa12eb8a6e6dc88f2be5132e3311a58
Storage Cache Governance run:        35039564474 SUCCESS
  backend focused storage tests:    26 / 26 PASS
  frontend focused storage tests:   12 / 12 PASS
Frontend Runtime Stabilization:      35039564416 SUCCESS
  full frontend unit tests:         305 / 305 PASS
  Real Chrome / Playwright:         33 / 33 PASS
Navigation Action Fencing:           35039564421 SUCCESS
formal VERSION.txt:                  42.24.0 unchanged
```

### 11.2 Presigned PUT Provider Contract

```text
validated implementation HEAD:      9abfa7b944aa0f29963e62491103010b434bbc48
Storage Cache Governance run:        35043735559 SUCCESS
  backend focused storage tests:    32 / 32 PASS
  frontend focused storage tests:   12 / 12 PASS
Frontend Runtime Stabilization:      35043735536 SUCCESS
  full frontend unit tests:         305 / 305 PASS
  Real Chrome / Playwright:         33 / 33 PASS
Navigation Action Fencing:           35043735579 SUCCESS
formal VERSION.txt:                  42.24.0 unchanged
```

该关闭只覆盖 Provider 层签名与不可覆盖契约，不表示正式浏览器直传已启用。

## 12. Node-scoped MaterialCache Runtime Truth 关闭证据 — 2026-09-16

本批代码与自动化回归已完成，可将 **Node-scoped MaterialCache Runtime Truth** 代码批次标记为 **CLOSED**。

```text
validated implementation HEAD:      4ea12eb87f590c4c60fbd945e47368644b5ea95e
initial backend implementation:      c08655fb82f845d3b787c0b690d976e765923d7d

Storage Cache Governance run:        35045635771 SUCCESS
  backend focused storage tests:    37 / 37 PASS
  frontend focused storage tests:   15 / 15 PASS
  permanent source guards:          SUCCESS

Frontend Runtime Stabilization:      35045635781 SUCCESS
  full frontend unit tests:         308 / 308 PASS
  Real Chrome runtime regressions:  SUCCESS

Navigation Action Fencing:           35045635776 SUCCESS
Training Task Visibility:            35045635788 SUCCESS

backend broad regression on c08655:  35045362724 SUCCESS
  training-data-contracts:          SUCCESS
  runtime-contracts:                SUCCESS
Training Worker Isolation on c08655: SUCCESS

formal VERSION.txt:                  42.24.0 unchanged
```

本关闭结论的准确边界：

**已经完成**：

- 缓存目录可与共享 data dir 分离；
- 现有 Worker heartbeat 上报节点缓存；
- `node_id` 去重；
- lease fencing；
- fresh / stale / unknown 真值；
- `/api/v62/workers` 复用；
- 节点级前端观测；
- 禁止伪造跨节点容量求和；
- 永久 unit / frontend / CI / Real Chrome 回归。

**仍未实机验收**：

- 两台及以上真实 Worker 节点；
- 共享 NFS `MC_TRAIN_DATA_DIR` + 各节点本地 NVMe `MC_MATERIAL_CACHE_DIR`；
- 节点重启 / Worker 切换 reporter 后的真实运行表现；
- 真实 OSS / S3 大规模素材缓存命中率、磁盘 IO 与网络收益。

因此不能把本批描述成“真实多节点生产环境已验收”或“已经得到准确集群总缓存占用”。

A800 RC 与 genuine 10k 实测继续按项目总约束保持暂停。
