import test from 'node:test';
import assert from 'node:assert/strict';

import {
  formatCacheBytes,
  materialCacheNodeRuntimeView,
  materialCacheStatusView,
  storageCacheSummary,
  storageCacheTruth,
} from '../../static/modules/storage-cache-runtime.js';

test('remote object storage exposes two-layer cache truth and immutable platform writes', () => {
  const truth = storageCacheTruth({type: 'oss', config: {}});
  assert.equal(truth.remote, true);
  assert.equal(truth.protectedWrites, true);
  assert.match(truth.cacheLabel, /SHA256/);
  assert.match(truth.cacheLabel, /Bundle/);
  assert.match(truth.protectionLabel, /禁止原地覆盖/);
  assert.match(truth.protectionLabel, /重新扫描/);
});

test('explicit legacy overwrite configuration is surfaced as unsafe instead of hidden', () => {
  const truth = storageCacheTruth({type: 's3', config: {protect_existing_objects: false}});
  assert.equal(truth.protectedWrites, false);
  assert.match(truth.protectionLabel, /允许原地覆盖/);
  assert.match(storageCacheSummary({type: 's3', config: {protect_existing_objects: false}}), /不建议/);
});

test('local storage does not pretend to use remote material cache', () => {
  const truth = storageCacheTruth({type: 'local', config: {}});
  assert.equal(truth.remote, false);
  assert.equal(truth.externalMutationRequiresRescan, false);
  assert.match(truth.cacheLabel, /本地直读/);
});

test('cache status projection exposes maintained bytes files quota and ttl', () => {
  const view = materialCacheStatusView({
    after_bytes: 3 * 1024 * 1024 * 1024,
    max_bytes: 128 * 1024 * 1024 * 1024,
    ttl_seconds: 30 * 86400,
    scanned_files: 100,
    evicted_files: 4,
    over_budget_bytes: 0,
    generated_at: '2026-09-16T00:00:00+00:00',
  });
  assert.equal(view.available, true);
  assert.equal(view.usage, '3.00 GB');
  assert.equal(view.files, '96');
  assert.equal(view.limit, '128 GB');
  assert.equal(view.ttl, '30 天');
  assert.equal(view.overBudget, false);
  assert.equal(formatCacheBytes(0), '0 B');
});

test('missing maintenance snapshot is explicit rather than rendered as zero usage', () => {
  const view = materialCacheStatusView(null);
  assert.equal(view.available, false);
  assert.equal(view.usage, '未知');
  assert.equal(view.files, '-');
});

test('multiple workers on one node collapse into one cache node without byte summation', () => {
  const snapshot = {
    after_bytes: 5 * 1024 * 1024,
    max_bytes: 100 * 1024 * 1024,
    ttl_seconds: 86400,
    scanned_files: 20,
    evicted_files: 2,
    over_budget_bytes: 0,
    generated_at: '2026-09-16T01:00:00+00:00',
  };
  const report = {
    reporter_worker_id: 'worker-background',
    cache_scope: 'configured_cache_dir',
    cache_root_source: 'MC_MATERIAL_CACHE_DIR',
    reported_at: '2026-09-16T01:00:10+00:00',
    snapshot_generated_at: '2026-09-16T01:00:00+00:00',
    snapshot,
  };
  const view = materialCacheNodeRuntimeView([
    {
      worker_id: 'worker-training', node_id: 'node-a', hostname: 'host-a', online: true,
      heartbeat_at: '2026-09-16T01:00:11+00:00', material_cache: report,
    },
    {
      worker_id: 'worker-background', node_id: 'node-a', hostname: 'host-a', online: true,
      heartbeat_at: '2026-09-16T01:00:12+00:00', material_cache: report,
    },
  ]);

  assert.equal(view.aggregation, 'per_node_only_no_sum');
  assert.equal(view.knownNodeCount, 1);
  assert.equal(view.onlineNodeCount, 1);
  assert.equal(view.snapshotNodeCount, 1);
  assert.equal(view.unknownSnapshotNodeCount, 0);
  assert.equal(view.nodes[0].workerCount, 2);
  assert.equal(view.nodes[0].onlineWorkerCount, 2);
  assert.equal(view.nodes[0].snapshot.usage, '5.00 MB');
  assert.equal(view.nodes[0].scopeLabel, '独立缓存目录');
  assert.equal(view.nodes[0].state, '已上报');
});

test('cache report becomes stale when its reporter worker is no longer online', () => {
  const view = materialCacheNodeRuntimeView([
    {
      worker_id: 'worker-live', node_id: 'node-a', hostname: 'host-a', online: true,
      heartbeat_at: '2026-09-16T01:01:00+00:00',
      material_cache: {
        reporter_worker_id: 'worker-gone',
        cache_scope: 'data_dir_cache',
        cache_root_source: 'data_dir',
        reported_at: '2026-09-16T00:59:00+00:00',
        snapshot: {
          after_bytes: 1024,
          max_bytes: 2048,
          ttl_seconds: 0,
          scanned_files: 1,
          evicted_files: 0,
          generated_at: '2026-09-16T00:58:00+00:00',
        },
      },
    },
  ]);

  assert.equal(view.nodes[0].reporterFresh, false);
  assert.equal(view.nodes[0].state, '上报已过期');
  assert.equal(view.snapshotNodeCount, 0);
  assert.equal(view.unknownSnapshotNodeCount, 1);
  assert.equal(view.nodes[0].scopeLabel, '数据目录兼容缓存');
});
