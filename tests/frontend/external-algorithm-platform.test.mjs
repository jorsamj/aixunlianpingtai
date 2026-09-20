import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

import {
  algorithmSourceLabel,
  externalAlgorithmMapping,
  externalAlgorithmTrainingReadiness,
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
      credentials: {configured: true, masked: 'ak-****1234', available: true, backend: 'encrypted_file', writable: true},
      cache: {product_count: 5},
      endpoints: {product_list: '/custom/products'},
    },
  });
  assert.equal(external.mode, 'external');
  assert.equal(external.baseUrl, 'https://example.test');
  assert.equal(external.credentials.configured, true);
  assert.equal(external.credentials.backend, 'encrypted_file');
  assert.equal(external.credentials.writable, true);
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

test('external training readiness mirrors backend master-data fencing', () => {
  const current = {
    source_type: 'EXTERNAL',
    provider_type: 'CHANG_LIAN',
    external_active: true,
    external_master_data_digest: 'digest-current',
  };
  assert.deepEqual(externalAlgorithmTrainingReadiness(current, 'digest-current'), {
    ready: true, status: 'current', reason: '', message: '',
  });

  const stale = externalAlgorithmTrainingReadiness(current, 'digest-new');
  assert.equal(stale.ready, false);
  assert.equal(stale.status, 'stale');
  assert.equal(stale.reason, 'external-master-data-stale');
  assert.match(stale.message, /立即同步/);

  const missingDigest = externalAlgorithmTrainingReadiness(
    {...current, external_master_data_digest: ''},
    'digest-current',
  );
  assert.equal(missingDigest.ready, false);
  assert.equal(missingDigest.status, 'stale');

  const inactive = externalAlgorithmTrainingReadiness(
    {...current, external_active: false},
    'digest-current',
  );
  assert.equal(inactive.ready, false);
  assert.equal(inactive.status, 'inactive');

  assert.equal(externalAlgorithmTrainingReadiness({id: 'local'}, '').ready, true);
});

test('external mapping exposes provider ids and sync state', () => {
  const mapping = externalAlgorithmMapping({
    source_type: 'EXTERNAL',
    provider_type: 'CHANG_LIAN',
    external_product_id: 'p-1',
    external_category_id: 'c-1',
    external_active: false,
    external_last_synced_at: '2026-09-17T06:30:00Z',
    external_analyses: [
      {analysis_id: 'a-1', analysis_name: '视觉分析 A'},
      {analysis_id: 'a-2', analysis_name: '视觉分析 B'},
    ],
  });
  assert.equal(mapping.source, '新畅联');
  assert.equal(mapping.productId, 'p-1');
  assert.equal(mapping.categoryId, 'c-1');
  assert.deepEqual(mapping.analysisIds, ['a-1', 'a-2']);
  assert.equal(mapping.active, false);
  assert.equal(mapping.syncedAt, '2026-09-17T06:30:00Z');
});


test('connection test uses draft form without saving credentials first', () => {
  const source = readFileSync(new URL('../../static/modules/external-algorithm-platform.js', import.meta.url), 'utf8');
  const start = source.indexOf('async function testConnection()');
  const end = source.indexOf('async function runDiagnostics()', start);
  assert.ok(start >= 0 && end > start);
  const block = source.slice(start, end);
  assert.doesNotMatch(block, /await save\(/);
  assert.match(block, /const payload = collectForm\(\)/);
  assert.match(block, /JSON\.stringify\(payload\)/);
  assert.match(source, /id="externalSecretToggle"/);
  assert.match(source, /id="externalConnectionResult"/);
  assert.match(source, /credentialBackendText/);
  assert.match(source, /MC_SECRET_MASTER_KEY/);
  assert.match(source, /安全存储不可用/);
  assert.match(source, /data-external-automation-settings="1"/);
  assert.match(source, /先配置并测试连接，再手动同步算法品目、算法产品、分析方式和算力环境/);
  assert.match(source, /联调准备状态/);
  assert.match(source, /人员网页登录账号不参与机器接口调用/);
  assert.match(source, /\/readiness\?project_id=/);
  assert.match(source, /loadReadiness/);
  assert.match(source, /data-external-stale/);
  assert.match(source, /external-master-data-stale/);
  assert.match(source, /trainingReadiness/);
});


test('external algorithm decorator is DOM-idempotent under mutation observers', () => {
  const source = readFileSync(new URL('../../static/modules/external-algorithm-platform.js', import.meta.url), 'utf8');
  const start = source.indexOf('function decorateAlgorithmCards()');
  const end = source.indexOf('function installAlgorithmDecorator()', start);
  assert.ok(start >= 0 && end > start);
  const block = source.slice(start, end);

  assert.match(block, /externalCategorySignature/);
  assert.match(block, /if \(select\.dataset\.externalCategorySignature !== optionSignature\)/);
  assert.match(block, /if \(create\.textContent !== '↻ 同步新畅联'\) create\.textContent = '↻ 同步新畅联'/);
  assert.doesNotMatch(block, /select\.innerHTML = options\.join\(''\)/);
  assert.doesNotMatch(block, /title\?\.querySelector\('\[data-external-stale\]'\)\?\.remove\(\);/);
  assert.match(block, /else if \(trainingState\.status === 'stale'\)/);
  assert.match(block, /if \(!staleBadge\)/);
});


test('platform page keeps explicit save-test-sync semantics and productized flow', () => {
  const source = readFileSync(new URL('../../static/modules/external-algorithm-platform.js', import.meta.url), 'utf8');
  assert.match(source, /external-platform-steps/);
  assert.match(source, /测试连接不保存|只测试当前填写内容，不自动保存/);
  assert.match(source, /当前配置有未保存修改，请先保存配置/);
  const syncStart = source.indexOf('async function syncNow()');
  const syncEnd = source.indexOf('function bindPage()', syncStart);
  assert.ok(syncStart >= 0 && syncEnd > syncStart);
  const syncBlock = source.slice(syncStart, syncEnd);
  assert.doesNotMatch(syncBlock, /await save\(/);
  assert.match(syncBlock, /credentials\?\.configured !== true/);
  assert.match(source, /id="externalPlatformTest"/);
  assert.match(source, /id="externalPlatformSave"/);
  assert.match(source, /id="externalPlatformSync"/);
});
