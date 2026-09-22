import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

import {
  algorithmSourceLabel,
  externalAlgorithmListFilterMatch,
  externalAlgorithmMapping,
  externalAlgorithmTrainingReadiness,
  externalAnalysisOptions,
  externalCategoryMatches,
  externalCategoryTreeRows,
  externalCategoryVisibleRows,
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
  assert.equal(local.autoSyncIntervalSeconds, 60);
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
  assert.equal(external.endpoints.category_tree, '/internal/base/category/tree');
});

test('external analysis options require exact status=1 and analysisType=1', () => {
  const options = externalAnalysisOptions({
    external_analysis_ids: ['legacy-id-must-not-bypass-detail'],
    external_analyses: [
      {analysis_id: 'vision-on', analysis_name: '视觉智能分析', analysis_type: '1', status: '1'},
      {analysis_id: 'missing-status', analysis_name: '视觉智能分析', analysis_type: '1'},
      {analysis_id: 'missing-type', analysis_name: '视觉智能分析', status: '1'},
      {analysis_id: 'name-only', analysis_name: '视觉智能分析'},
      {analysis_id: 'reserved-on', analysis_name: '预留分析', analysis_type: '2', status: '1'},
      {analysis_id: 'llm-on', analysis_name: '大模型智能分析', analysis_type: '3', status: '1'},
      {analysis_id: 'vision-off', analysis_name: '停用视觉分析', analysis_type: '1', status: '0'},
    ],
  });
  assert.deepEqual(options.map(row => row.id), ['vision-on']);
});

test('external analysis options exclude LLM and disabled visual modes', () => {
  const algorithm = {
    external_analyses: [
      {analysis_id: 'vision-on', analysis_name: '视觉智能分析', analysis_type: '1', status: '1'},
      {analysis_id: 'llm-on', analysis_name: '大模型智能分析', analysis_type: '3', status: '1'},
      {analysis_id: 'vision-off', analysis_name: '停用视觉分析', analysis_type: '1', status: '0'},
    ],
  };
  assert.deepEqual(externalAnalysisOptions(algorithm).map(row => row.id), ['vision-on']);

  const blocked = externalAlgorithmTrainingReadiness({
    source_type: 'EXTERNAL',
    provider_type: 'CHANG_LIAN',
    external_active: true,
    external_master_data_digest: 'digest-current',
    external_analyses: [
      {analysis_id: 'llm-on', analysis_name: '大模型智能分析', analysis_type: '3', status: '1'},
    ],
  }, 'digest-current');
  assert.equal(blocked.ready, false);
  assert.equal(blocked.status, 'no-visual-analysis');
  assert.equal(blocked.reason, 'external-visual-analysis-missing');

  const unverified = externalAlgorithmTrainingReadiness({
    source_type: 'EXTERNAL',
    provider_type: 'CHANG_LIAN',
    external_active: true,
    external_master_data_digest: 'digest-current',
    external_analysis_ids: ['legacy-visual'],
    external_analyses: [],
  }, 'digest-current');
  assert.equal(unverified.ready, false);
  assert.equal(unverified.reason, 'external-visual-analysis-missing');
});

test('algorithm list supports multi-category source and training-status filters', () => {
  const categories = [
    {categoryId: 'root-a', parentId: '', categoryName: 'A'},
    {categoryId: 'child-a', parentId: 'root-a', categoryName: 'A-1'},
    {categoryId: 'root-b', parentId: '', categoryName: 'B'},
  ];
  assert.equal(externalCategoryMatches('child-a', ['root-a'], categories), true);
  assert.equal(externalCategoryMatches('root-b', ['root-a', 'root-b'], categories), true);
  assert.equal(externalCategoryMatches('child-a', ['root-b'], categories), false);

  const internal = {id: 'internal-1', source_type: 'LOCAL', versions: []};
  const external = {
    id: 'external-1',
    source_type: 'EXTERNAL',
    external_category_id: 'child-a',
    versions: [{id: 'v1'}],
  };
  assert.equal(externalAlgorithmListFilterMatch(internal, {source: 'internal'}), true);
  assert.equal(externalAlgorithmListFilterMatch(internal, {source: 'external'}), false);
  assert.equal(externalAlgorithmListFilterMatch(external, {
    source: 'external',
    selectedCategoryIds: ['root-a'],
    categories,
    trainingStatus: 'trained',
    readiness: {ready: true},
  }), true);
  assert.equal(externalAlgorithmListFilterMatch(external, {
    trainingStatus: 'blocked',
    readiness: {ready: false},
  }), true);
  assert.equal(externalAlgorithmListFilterMatch(external, {
    trainingStatus: 'training',
    jobs: [{asset_algorithm_id: 'external-1', status: 'running'}],
  }), true);
});

test('external training readiness mirrors backend master-data fencing', () => {
  const current = {
    source_type: 'EXTERNAL',
    provider_type: 'CHANG_LIAN',
    external_active: true,
    external_master_data_digest: 'digest-current',
    external_analyses: [
      {analysis_id: 'vision-on', analysis_type: '1', status: '1', analysis_name: '视觉智能分析'},
    ],
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
      {analysis_id: 'a-1', analysis_name: '视觉分析 A', analysis_type: '1', status: '1'},
      {analysis_id: 'a-2', analysis_name: '视觉分析 B', analysis_type: '1', status: '1'},
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
  assert.match(source, /data-external-sync-settings="1"/);
  assert.doesNotMatch(source, /id="externalAutoPublish"/);
  assert.doesNotMatch(source, /训练成果自动发布/);
  assert.doesNotMatch(source, /<b>训练与发布<\/b>/);
  assert.match(source, /auto_publish_enabled: mode === 'external'/);
  assert.match(source, /auto_sync_interval_seconds: 60/);
  assert.match(source, /每 60 秒主动拉取一次主数据/);
  assert.match(source, /\/internal\/base\/category\/tree/);
  assert.match(source, /\/internal\/base\/compute-platform\/listAll/);
  assert.match(source, /\/internal\/algorithm\/product-ai\/listAll/);
  assert.match(source, /\/internal\/algorithm\/algorithm-analysis\/listByProduct\/\{productId\}/);
  assert.match(source, /\/internal\/algorithm\/algorithm-version\/add/);
  assert.match(source, /\/internal\/algorithm\/algorithm-weight\/add/);
  assert.match(source, /businessAuthMode: config\.business_auth_mode \|\| 'authorization_bearer'/);
  assert.match(source, /product_list: endpoints\.product_list \|\| '\/internal\/algorithm\/product-ai\/listAll'/);
  assert.match(source, /data-changlian-api-contract="1"/);
  assert.match(source, /external-contract-summary muted-line/);
  assert.doesNotMatch(source, /panel-title">新畅联接口契约<\/div><div class="subline"/);
  assert.match(source, /连接测试只调用鉴权和只读查询，不会自动执行新增、修改或删除/);
  assert.match(source, /完整 OpenAPI 已锁定正式 Method \/ Path \/ Bearer 鉴权/);
  assert.doesNotMatch(source, /data-external-endpoint=/);
  assert.doesNotMatch(source, /高级接口路径/);
  assert.match(source, /已保存并锁定，后续将持续使用此配置/);
  assert.match(source, /配置保存成功后会自动锁定并持续使用/);
  assert.match(source, /id="externalPlatformEdit"/);
  assert.match(source, /id="externalPlatformCancelEdit"/);
  assert.match(source, /const configLocked = savedConnectionReady && !configEditing/);
  assert.match(source, /配置已锁定，请先点击“编辑配置”再修改/);
  assert.match(source, /if \(reload\) configEditing = false/);
  assert.match(source, /PLATFORM_PAGE_CACHE_TTL_MS = 60 \* 1000/);
  assert.match(source, /const hasSnapshot = paintCachedPage\(\)/);
  assert.match(source, /if \(config && \(!reload \|\| \(!force && fresh\)\)\) return true/);
  assert.match(source, /先配置并测试连接，再手动同步算法品目、算法产品、分析方式和算力环境/);
  assert.doesNotMatch(source, /联调准备状态 · 主数据 \/ 训练准备状态/);
  assert.match(source, /除人员登录参考外，内部算法接口均已进入 Provider contract/);
  assert.match(source, /\/readiness\?project_id=/);
  assert.match(source, /loadReadiness/);
  assert.match(source, /data-external-stale/);
  assert.match(source, /external-master-data-stale/);
  assert.match(source, /trainingReadiness/);
});


test('external algorithm decorator is DOM-idempotent under mutation observers', () => {
  const source = readFileSync(new URL('../../static/modules/external-algorithm-platform.js', import.meta.url), 'utf8');

  const pickerStart = source.indexOf('function renderAlgorithmCategoryPicker(');
  const decoratorStart = source.indexOf('function decorateAlgorithmCards()');
  const decoratorEnd = source.indexOf('function installAlgorithmDecorator()', decoratorStart);
  assert.ok(pickerStart >= 0 && decoratorStart > pickerStart && decoratorEnd > decoratorStart);

  const pickerBlock = source.slice(pickerStart, decoratorStart);
  const decoratorBlock = source.slice(decoratorStart, decoratorEnd);

  assert.match(decoratorBlock, /data-algorithm-source-filter/);
  assert.match(decoratorBlock, /内部算法/);
  assert.match(decoratorBlock, /外部算法/);
  assert.match(decoratorBlock, /data-algorithm-training-status-filter/);
  assert.match(decoratorBlock, /全部训练状态/);
  assert.match(decoratorBlock, /renderAlgorithmCategoryPicker/);

  assert.match(pickerBlock, /data-category-picker-toggle/);
  assert.match(pickerBlock, /data-category-select/);
  assert.match(pickerBlock, /data-category-search/);
  assert.match(pickerBlock, /categoryPickerSignature/);
  assert.match(pickerBlock, /categoryBar\.dataset\.categoryPickerSignature === pickerSignature/);

  assert.match(decoratorBlock, /data-external-list-sync/);
  assert.match(decoratorBlock, /同步畅联云/);
  assert.doesNotMatch(decoratorBlock, /removeAttribute\('data-action'\)/);
  assert.doesNotMatch(decoratorBlock, /legacyIndustry\.hidden = true/);
  assert.match(decoratorBlock, /else if \(trainingState\.status === 'stale'\)/);
  assert.match(decoratorBlock, /if \(!staleBadge\)/);
});


test('platform page keeps a simple persistent save-test-sync flow', () => {
  const source = readFileSync(new URL('../../static/modules/external-algorithm-platform.js', import.meta.url), 'utf8');
  assert.match(source, /external-platform-steps/);
  assert.match(source, /<b>保存配置<\/b>/);
  assert.match(source, /<b>测试连接<\/b>/);
  assert.match(source, /<b>同步主数据<\/b>/);
  assert.match(source, /配置状态/);
  const formStart = source.indexOf('function configFormHtml');
  const collectStart = source.indexOf('function collectForm', formStart);
  const formBlock = source.slice(formStart, collectStart);
  assert.doesNotMatch(formBlock, /readinessHtml\(\)/);
  assert.doesNotMatch(formBlock, /训练准备|版本\/权重发布/);
  assert.match(source, /使用当前页面填写的 API 地址和凭据临时测试，不会自动保存或覆盖已保存凭据/);
  assert.match(source, /使用服务器已保存的 API 地址和凭据测试连接/);
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


test('algorithm list keeps search and base filters while adding source filters', () => {
  const appSource = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
  const externalSource = readFileSync(new URL('../../static/modules/external-algorithm-platform.js', import.meta.url), 'utf8');
  assert.match(appSource, /id="alg412Q" class="input" placeholder="搜索算法名称、编码或说明"/);
  assert.match(appSource, /id="alg412Industry"/);
  assert.match(appSource, /id="alg412Type"/);
  assert.match(externalSource, /dataset\.algorithmSourceFilter/);
  assert.match(externalSource, /dataset\.algorithmTrainingStatusFilter/);
  assert.match(externalSource, /algorithmListRuntime\?\.filterState\?\.\(\)/);
  assert.match(externalSource, /algorithmListRuntime\?\.setFilters\?\.\(patch, options\)/);
  assert.doesNotMatch(externalSource, /let selectedSource = 'all'/);
  assert.doesNotMatch(externalSource, /let selectedTrainingStatus = 'all'/);
  assert.doesNotMatch(externalSource, /const selectedCategoryIds = new Set\(\);/);
  assert.match(appSource, /external_product_id/);
  assert.match(appSource, /product_code/);
});

test('sync settings enforce 60-second automatic pull without claiming webhook support', () => {
  const source = readFileSync(new URL('../../static/modules/external-algorithm-platform.js', import.meta.url), 'utf8');
  assert.match(source, /自动同步已启用/);
  assert.match(source, /每 60 秒主动拉取一次主数据/);
  assert.match(source, /没有 Webhook、订阅或推送接口/);
  assert.match(source, /auto_sync_enabled: mode === 'external'/);
  assert.match(source, /auto_sync_interval_seconds: 60/);
  assert.doesNotMatch(source, /id="externalAutoSyncInterval"/);
});


test('category picker derives arbitrary parent depth and search paths from real parentId data', () => {
  const categories = [
    {categoryId: 'root', categoryName: '安全治理', parentId: ''},
    {categoryId: 'vehicle', categoryName: '车辆', parentId: 'root'},
    {categoryId: 'parking', categoryName: '违停', parentId: 'vehicle'},
    {categoryId: 'fire', categoryName: '烟火', parentId: 'root'},
  ];
  const tree = externalCategoryTreeRows(categories);
  const parking = tree.find(row => row.id === 'parking');
  assert.equal(parking.depth, 2);
  assert.deepEqual(parking.ancestorIds, ['root', 'vehicle']);
  assert.equal(parking.path, '安全治理 / 车辆 / 违停');

  assert.deepEqual(
    externalCategoryVisibleRows(categories, {expandedIds: []}).map(row => row.id),
    ['root'],
  );
  assert.deepEqual(
    externalCategoryVisibleRows(categories, {expandedIds: ['root', 'vehicle']}).map(row => row.id).sort(),
    ['fire', 'parking', 'root', 'vehicle'],
  );
  assert.deepEqual(
    externalCategoryVisibleRows(categories, {query: '违停'}).map(row => row.id),
    ['root', 'vehicle', 'parking'],
  );
});
