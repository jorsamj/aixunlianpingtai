# OSS / S3 素材缓存与对象不可变契约

**适用阶段：** v42.25 技术债关闭 / 全 OSS 素材生产准备  
**正式 VERSION：** 仍为 `42.24.0`，本文不代表发布版本变更。

## 1. 目标

远程素材进入训练链路后，必须同时满足：

1. 不在每次训练时重复下载已经验证过的远程素材；
2. 不让 Worker 本地缓存无限增长直至挤满磁盘；
3. 不允许平台自己把同一个 OSS / S3 `object_key` 静默覆盖成另一份内容；
4. 不为了验证远端是否变化，在每次 1 万张训练前额外发起 1 万次 HEAD 请求；
5. 外部绕过平台直接改远端对象时，必须通过重新扫描 / 恢复流程确认变化，再更新平台素材真值；
6. 前端必须说明当前真实缓存语义，不能把“缓存命中”描述成“每次都实时向 OSS 校验”。

## 2. 当前真实链路

```text
OSS / S3 / Remote
        |
        | 首次或本地内容缓存 miss
        v
MaterialCache
<data_dir>/cache/materials/<sha256-prefix>/<sha256>.<ext>
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

因此目前是两层复用：

- **MaterialCache**：按素材 SHA256 复用远程原始文件；
- **TrainingBundleCache**：按完整训练 Snapshot 复用已经验证的训练 Bundle。

同一批完整 Snapshot 再次训练时，可以直接命中 TrainingBundleCache；训练素材发生局部变化、Bundle Cache miss 时，未变化素材仍可从 MaterialCache 复用，只下载新增或本地缺失的内容。

## 3. MaterialCache 生命周期

### 3.1 默认值

当前默认：

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

MaterialCache 每次完成维护后，会原子更新：

```text
<data_dir>/cache/materials/status.json
```

快照只保存非敏感运行指标，例如：

- `after_bytes`
- `scanned_files`
- `max_bytes`
- `ttl_seconds`
- `evicted_files`
- `over_budget_bytes`
- `generated_at`
- `cache_scope = worker_local`

前端“素材存储配置”读取该快照展示**最近一次维护时**的当前节点占用，不会为了打开页面重新遍历所有缓存文件。

该状态是节点级，不是未来多 GPU Worker 集群的全局汇总。多节点部署时，每个 Worker 节点仍拥有自己的本地热缓存；后续如需统一观测，应汇总各 Worker 的节点指标，而不是把某一节点状态冒充集群状态。

## 4. OSS / S3 对象不可变策略

### 4.1 默认策略

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

### 4.2 推荐 object_key

生产建议采用不可变 key：

```text
materials/<content_sha256>.<ext>
```

或：

```text
materials/<uuid>/<version>.<ext>
```

内容变化时产生新的 key / 新版本，而不是覆盖原对象。

## 5. 外部直接修改 OSS / S3 的边界

平台缓存是按已经确认的 `content_sha256` 工作的。为了保证训练启动性能，命中缓存时不会在每次训练前再对每一张远端素材执行 HEAD。

因此如果有人绕过平台，在 OSS 控制台、其他程序或同步工具里直接覆盖已有 object_key，平台不会把这种外部操作当成已确认素材版本。

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

## 6. Presigned PUT 边界

当前平台正式 Web 上传链路使用后端 Provider 写入，因此 OSS / S3 的条件写保护可以由后端强制执行。

现有 Provider 仍保留 `generate_upload_url()` 能力，但**当前不可把普通 presigned PUT 视为已经具备与后端条件写完全相同的不可覆盖契约**。如果以后启用浏览器 / 客户端直传，必须满足以下任一条件后才能作为正式写入路径：

- 使用唯一、不可复用的 object_key；
- 由服务端签发带等价条件写约束的上传契约；
- 使用对象存储版本化并把具体版本 ID 纳入素材真值。

在此之前，直传能力不能绕过后端不可变写策略。

## 7. 前端真实展示

“素材存储配置”页面应展示：

- 本地源：`本地直读 · 训练 Bundle 缓存`；
- OSS / S3 / Remote：`SHA256 本地内容缓存 · 训练 Bundle 缓存`；
- OSS / S3 默认：`平台写入禁止原地覆盖 · 外部变更需重新扫描`；
- 显式 legacy 覆盖模式：`允许原地覆盖（不建议）`；
- 当前节点 MaterialCache 最近维护快照：占用、缓存文件数、容量上限、TTL。

前端不能显示“OSS 已实时同步”之类没有后端真值支撑的状态。

## 8. 生产建议

即使平台默认禁止自身覆盖，生产 Bucket 仍建议额外配置对象存储侧保护，例如：

- Bucket / IAM 权限最小化；
- 禁止无关账号直接覆盖训练素材前缀；
- 对关键素材前缀开启版本化或审计日志；
- Worker 使用同地域 / 同 VPC Endpoint，避免跨公网拉取训练素材；
- Worker 本地 NVMe / SSD 作为 MaterialCache 和 TrainingBundleCache 热缓存盘；
- 多 Worker 时按节点监控缓存占用，不把缓存目录放到低性能共享盘上。

## 9. 验证边界

本批永久测试覆盖：

- MaterialCache 首次 miss、再次 hit、并发同 SHA 只下载一次；
- 本地缓存损坏重新下载；
- TTL 清理；
- LRU 容量清理；
- protected / locked 文件不被强删；
- 环境变量配置；
- 状态快照；
- OSS 默认禁止覆盖；
- OSS 冲突映射 `STORAGE_OBJECT_EXISTS`；
- S3 默认 `If-None-Match: *`；
- legacy 覆盖必须显式 opt-out；
- 前端两层缓存、对象保护、占用快照语义。

真实 OSS Bucket / 多节点 GPU 缓存命中率属于生产环境验收，不得用 mock 测试结果替代。
