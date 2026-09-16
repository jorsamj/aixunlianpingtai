import test from 'node:test';
import assert from 'node:assert/strict';

import {
  formatCacheBytes,
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
  assert.equal(view.usage, '尚无维护快照');
  assert.equal(view.files, '-');
});
