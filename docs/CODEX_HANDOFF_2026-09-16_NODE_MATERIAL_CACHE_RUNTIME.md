# Handoff — Node-scoped MaterialCache Runtime Truth — 2026-09-16

Repository: `jorsamj/aixunlianpingtai`  
Branch: `refactor/frontend-runtime-stabilization`  
Formal `VERSION.txt`: `42.24.0`

## Status

```text
Node-scoped MaterialCache Runtime Truth
CLOSED — CODE + AUTOMATED REGRESSION
REAL MULTI-NODE NFS/NVME ACCEPTANCE: PENDING
```

Validated implementation HEAD:

```text
4ea12eb87f590c4c60fbd945e47368644b5ea95e
```

Initial implementation commit:

```text
c08655fb82f845d3b787c0b690d976e765923d7d
```

Do not describe this as real multi-node production acceptance. A800 RC and genuine 10k acceptance remain paused by project constraint.

## Why this batch exists

Before this batch, `StorageManager` always used:

```text
<MC_TRAIN_DATA_DIR>/cache/materials
```

and MaterialCache `status.json` always claimed `cache_scope=worker_local`.

That was not a safe production statement. If `MC_TRAIN_DATA_DIR` is mounted from NFS, several Worker nodes may actually share that directory. The previous frontend also read one Web process path:

```text
/data/cache/materials/status.json
```

which could not represent multi-Worker / multi-node runtime truth.

## Final architecture

### Cache path ownership

`platform_core/storage/cache.py` now resolves MaterialCache root as:

```text
MC_MATERIAL_CACHE_DIR
    -> cache_scope=configured_cache_dir
    -> cache_root_source=MC_MATERIAL_CACHE_DIR

otherwise
<data_dir>/cache/materials
    -> cache_scope=data_dir_cache
    -> cache_root_source=data_dir
```

Recommended Linux production shape when application data is shared:

```text
MC_TRAIN_DATA_DIR=/shared/nfs/changlian-data
MC_MATERIAL_CACHE_DIR=/local/nvme/changlian/material-cache
```

Do not infer `worker_local` merely from the compatibility fallback path.

### Existing Worker Runtime remains the only owner

No second heartbeat, Worker registry, Scheduler, queue or frontend timer was introduced.

Each real Worker still acquires the existing `worker_instances` lease. `task_worker.py` creates a `MaterialCacheRuntimeReporter`, publishes once best-effort at startup, then attaches:

```python
instance_lease.add_renew_hook(cache_reporter.report)
```

The existing `WorkerInstanceLease.renew()` remains the heartbeat owner. Cache-report failures are best-effort and do not kill a healthy Worker lease.

### Execution fencing

`MaterialCacheRuntimeReporter.report()` verifies the exact current:

```text
instance_key + owner_token
```

before publishing cache runtime. Once that Worker lease is released or replaced, the stale reporter cannot continue publishing new cache truth.

### Node identity and deduplication

Reports live in:

```text
node_cache_runtime
```

with:

```text
PRIMARY KEY(node_id, cache_kind)
```

This deliberately reuses the existing stable `node_id` from Worker Runtime Truth. Training and background Worker processes on the same machine do not count as separate cache nodes.

### Public read path

No new global runtime API was added.

Existing:

```text
GET /api/v62/workers
```

returns normal Worker Runtime Truth plus optional `material_cache` node report.

The read path does not scan cache files and does not create runtime state merely because a GET occurred.

### Frontend semantics

`static/modules/storage-cache-runtime.js` now obtains cache runtime from `/api/v62/workers` instead of reading one Web-node `status.json`.

It groups Workers by `node_id` and renders `Worker 节点素材缓存`.

States include:

```text
已上报
上报已过期
等待维护快照
超出缓存配额
未知
```

Missing snapshot is `未知`, not `0 B`.

A report is fresh only when:

1. `reporter_worker_id` is still an online Worker on that node; and
2. cache `reported_at` has kept up with that reporter's latest heartbeat, allowing 5 seconds execution skew.

This prevents a cache hook that silently stopped while the Worker heartbeat continued from leaving a permanently “fresh” snapshot.

### No fake cluster total

Frontend projection explicitly returns:

```text
aggregation = per_node_only_no_sum
```

Different `node_id` values may still point to the same shared filesystem. Until the platform has a durable physical cache-volume identity, summing node byte counts could double count shared storage. Therefore the UI reports node counts and per-node metrics only.

## Core files

```text
platform_core/storage/cache.py
platform_core/storage/manager.py
platform_core/storage/material_cache_runtime.py
platform_core/task_runtime/worker_instances.py
task_worker.py
static/modules/storage-cache-runtime.js
static/index.html
tests/unit/storage/test_material_cache_lifecycle.py
tests/unit/storage/test_material_cache_runtime.py
tests/frontend/storage-cache-runtime.test.mjs
.github/workflows/storage-cache-governance.yml
docs/STORAGE_CACHE_AND_OBJECT_IMMUTABILITY.md
```

## Permanent contracts

Backend guards cover:

- `MC_MATERIAL_CACHE_DIR` separation from shared data dir;
- truthful fallback `data_dir_cache` scope;
- schema v2 maintenance snapshot;
- exact Worker lease fencing;
- same-node multi-Worker dedupe;
- stale reporter rejection after lease release;
- renew-hook best-effort behavior.

Frontend guards cover:

- missing snapshot is unknown, not zero;
- two Workers on one node collapse into one node;
- node bytes are not summed;
- reporter offline => stale;
- reporter online but heartbeat advances while report stops => stale.

Permanent workflow additionally rejects reintroduction of:

```text
/data/cache/materials/status.json
```

as frontend cluster truth.

## Validation evidence

Implementation HEAD `4ea12eb87f590c4c60fbd945e47368644b5ea95e`:

```text
Storage Cache Governance run 35045635771
  SUCCESS
  backend focused storage: 37 / 37 PASS
  frontend focused storage: 15 / 15 PASS
  permanent guards: SUCCESS

Frontend Runtime Stabilization run 35045635781
  frontend: SUCCESS
  308 / 308 frontend unit tests PASS
  Real Chrome runtime regressions: SUCCESS

Navigation Action Fencing run 35045635776
  SUCCESS

Training Task Visibility run 35045635788
  SUCCESS
```

Initial backend product commit `c08655fb82f845d3b787c0b690d976e765923d7d` also passed broad backend/runtime regression, including v42.25 Release Regression run `35045362724`, plus Training Worker Isolation. This matters because the stale-report follow-up was frontend-only.

Formal `VERSION.txt` remained `42.24.0` throughout.

## Remaining real production acceptance

Still not verified:

- two or more real Linux Worker nodes;
- shared NFS `MC_TRAIN_DATA_DIR` plus node-local SSD/NVMe `MC_MATERIAL_CACHE_DIR`;
- reporter takeover after one Worker process is restarted;
- actual OSS/S3 cache hit ratio and network/IO improvement under large datasets;
- a physical volume identity suitable for truthful cluster-wide byte aggregation.

Do not add a simple sum of `after_bytes` across node IDs as a shortcut.

## Follow-up boundary

This batch is independent from:

- GPU Runtime Truth Phase 1B;
- real A800 acceptance;
- genuine 10k ZIP acceptance;
- formal browser-direct-upload product enablement;
- training quality-gate `抽取=0张` audit.

Do not silently combine those into this closure.
