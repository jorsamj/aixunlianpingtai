import test from 'node:test';
import assert from 'node:assert/strict';

import {storageCacheSummary, storageCacheTruth} from '../../static/modules/storage-cache-runtime.js';

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
