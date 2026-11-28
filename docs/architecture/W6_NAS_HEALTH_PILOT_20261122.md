# W6 NAS 跨节点可达性最小试点（2026-11-22）

> 只读合同试点。未自动挂载、未修改宿主机、未改既有 OSS/S3 合同、未切换生产存储。
> 复用 `StorageManager` / `LocalStorageProvider` / `StorageSourceRepository` / `StorageHealth`。

## 1. 入口

新增模块：`platform_core/storage/nas_health.py`

- `check_nas_source(source, *, node_id, data_dir, project_dir, object_key="", expected_sha256="", expected_size=None)`
- `read_mount_info(path)`：解析 Linux `/proc/self/mountinfo`，返回最长包含目标路径的挂载点、文件系统类型、挂载源、major:minor。
- `StorageManager.check_nas_source(source_id, ...)`：通过既有 StorageSourceRepository 解析 source，不新增存储事实源。

## 2. 存储源配置

NAS 仍使用既有 `local` Provider，不新增 StorageType：

```json
{
  "root": "/mnt/nas/train",
  "nas": {
    "mount_point": "/mnt/nas",
    "expected_fs_types": ["nfs", "nfs4"],
    "expected_mount_sources": ["nas.example:/train"],
    "node_ids": ["gpu-node-a", "gpu-node-b"]
  }
}
```

- `root`、`mount_point`、`expected_mount_sources`、允许节点都来自 **StorageSource 配置**，不是任务 payload。
- `expected_mount_sources` 必须显式配置；缺失时 fail-closed，不能只凭目录存在或 fs type 猜 NAS。
- NFS 来源按精确字符串/尾部斜杠归一；CIFS/SMB 额外做分隔符与大小写归一，规则固定，不做模糊包含。
- 实际/预期来源在输出前脱敏；含 `user:pass@host` 时只保留 `***@host`。
- `object_key` 必须是相对 root 的正斜杠对象键；`LocalStorageProvider._path` 拒绝绝对路径、`..`、Windows drive、反斜杠和越界 symlink。
- 没有 `nas.mount_point`、`expected_fs_types` 或 `expected_mount_sources` 时 **fail-closed**，不会把普通本地目录当 NAS。

## 3. 检查顺序与结果

1. source 启用且为 local Provider；
2. 节点在 `node_ids` 允许集内；
3. root 存在、是目录、可 `scandir`（证明读/执行权限）；
4. 读取 mountinfo，比较实际挂载点与预期；
5. 比较实际 `fs_type` 与预期；
6. `shutil.disk_usage` 读取容量；
7. 可选测试对象：大小 + SHA256 必须匹配；缺失/读失败不判定永久不存在；
8. 任何无法证明的环节返回 `StorageHealth.unavailable`，`details.reason` 明确。

失败原因枚举：

`SOURCE_DISABLED`、`NOT_LOCAL_PROVIDER`、`MOUNT_EXPECTATION_MISSING`、`NODE_NOT_ALLOWED`、
`ROOT_MISSING`、`READ_PERMISSION_DENIED`、`ROOT_IO_UNAVAILABLE`、`MOUNT_INFO_UNAVAILABLE`、
`MOUNT_POINT_MISMATCH`、`FS_TYPE_MISMATCH`、`CAPACITY_UNAVAILABLE`、`INVALID_OBJECT_KEY`、
`TEST_OBJECT_EVIDENCE_MISSING`、`TEST_OBJECT_MISSING`、`TEST_OBJECT_SIZE_MISMATCH`、
`TEST_OBJECT_SHA_MISMATCH`、`TEST_OBJECT_IO_UNAVAILABLE`。

`retryable=true` 只用于临时 I/O/挂载信息不可读/对象暂时不可达；不把网络短断解释为对象永久不存在。

## 3.1 证据等级

`StorageHealth.details` 明确：

- `evidence=MOUNT_HEALTH_VERIFIED`：挂载点、文件系统、配置来源、基础读取和容量通过；`object_evidence=NOT_CHECKED`，**不能**被任务准入当成对象已校验。
- `evidence=OBJECT_EVIDENCE_VERIFIED`：额外通过指定对象的相对路径、大小和 SHA256；`object_evidence=OBJECT_EVIDENCE_VERIFIED`。
- `evidence=MOUNT_HEALTH_UNVERIFIED` 或 `object_evidence=OBJECT_EVIDENCE_UNVERIFIED`：未验证/失败，保持 fail-closed。

仅挂载成功时消息为“NAS 挂载与读取权限验证通过（未验证对象）”，不再声称数据身份已验证。

## 4. 隔离验证

`tests/unit/test_nas_health.py`：**11 passed, 1 skipped**（Windows 跳过 mountinfo 解析）。

覆盖：

- 正确挂载 + 正确来源 + SHA/大小 → OBJECT_EVIDENCE_VERIFIED；
- 仅挂载检查 → MOUNT_HEALTH_VERIFIED / object NOT_CHECKED；
- 同一挂载点/fs type 但不同来源 → MOUNT_SOURCE_MISMATCH；
- 未配置来源身份 → MOUNT_SOURCE_EXPECTATION_MISSING；
- CIFS 分隔符/大小写归一；
- 普通本地目录无挂载预期 → fail-closed；
- 文件系统类型不符；
- 挂载点不符；
- 权限不足；
- SHA 不符；
- 路径穿越 `../outside.bin`；
- 临时 `OSError` → `ROOT_IO_UNAVAILABLE` + retryable；
- StorageManager 集成入口；
- Linux mountinfo 最长匹配解析（Linux CI）。

## 5. 未验证项

- 真实 NFS/CIFS NAS 跨机挂载、断网/重连、stale handle、ACL → `NOT_VERIFIED`。
- Windows/macOS 节点：无 `/proc/self/mountinfo`，当前 fail-closed，未提供替代 mount identity 探测。
- Node Agent 自动上报该健康结果：本轮只提供可复用函数，不新增 Agent/任务调度链路。
- 大目录/慢 NAS 的 `scandir` 延迟、容量精度、测试对象选择策略：`NOT_VERIFIED`。
- 未改训练 Bundle 回退路线；未改 OSS/S3 Provider。
