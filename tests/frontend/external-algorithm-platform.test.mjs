import test from 'node:test';
import assert from 'node:assert/strict';

import {
  algorithmSourceLabel,
  externalAnalysisOptions,
  isExternalAlgorithm,
  normalizeExternalPlatformConfig,
} from '../../static/modules/external-algorithm-platform.js';

test('external algorithm source is explicit and provider-labelled', () => {
  const algorithm = {
    source_type: 'EXTERNAL',
    provider_type: 'CHANG_LIAN',
    source_name: '新畅联',
  };
  assert.equal(isExternalAlgorithm(algorithm), true);
  assert.equal(algorithmSourceLabel(algorithm), '新畅联');
  assert.equal(algorithmSourceLabel({id: 'local'}), '本平台');
});

test('external platform config keeps local as safe default and normalizes endpoints', () => {
  const local = normalizeExternalPlatformConfig({});
  assert.equal(local.mode, 'local');
  assert.equal(local.provider, 'changlian');
  assert.equal(local.endpoints.token, '/internal/auth/token');
  assert.equal(local.autoSyncIntervalSeconds, 600);
  assert.equal(local.authMode, 'test_sign_bridge');

  const external = normalizeExternalPlatformConfig({
    config: {
      mode: 'external',
      provider: 'changlian',
      base_url: 'https://example.test',
      credentials: {configured: true, masked: 'ak-****1234'},
      cache: {product_count: 5},
      endpoints: {product_list: '/custom/products'},
    },
  });
  assert.equal(external.mode, 'external');
  assert.equal(external.baseUrl, 'https://example.test');
  assert.equal(external.credentials.configured, true);
  assert.equal(external.cache.product_count, 5);
  assert.equal(external.endpoints.product_list, '/custom/products');
  assert.equal(external.endpoints.category_tree, '/algorithm-category/tree');
});

test('external analysis options preserve all synced analysis methods', () => {
  const options = externalAnalysisOptions({
    external_analyses: [
      {analysis_id: 'a1', analysis_name: '视觉分析 A'},
      {analysis_id: 'a2', analysis_name: '视觉分析 B'},
    ],
  });
  assert.deepEqual(options.map(row => row.id), ['a1', 'a2']);
  assert.deepEqual(options.map(row => row.name), ['视觉分析 A', '视觉分析 B']);
});
