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
  externalSyncOperationActive,
  externalSyncOperationHtml,
  externalSyncOperationPhaseText,
  isExternalAlgorithm,
  normalizeExternalPlatformConfig,
  safeExternalPlatformConfigSnapshot,
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
  assert.deepEqual(local.autoSyncScheduleLocalTimes, ['08:00', '12:00', '15:00']);
  assert.equal(local.autoSyncTimezone, 'Asia/Shanghai');
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

test('persisted external platform snapshot is explicitly redacted', () => {
  const normalized = normalizeExternalPlatformConfig({
    config: {
      mode: 'external',
      provider: 'changlian',
      base_url: 'https://example.test',
      credentials: {
        configured: true,
        masked: 'AK-****1234',
        available: true,
        backend: 'encrypted_file',
        writable: true,
        access_key: 'plain-ak-must-not-persist',
        access_secret: 'plain-secret-must-not-persist',
        token: 'bearer-must-not-persist',
      },
      cache: {product_count: 5, master_data_digest: 'digest-1'},
      last_sync: {status: 'success', counts: {products: 5}},
    },
  });
  const snapshot = safeExternalPlatformConfigSnapshot(normalized);
  const serialized = JSON.stringify(snapshot);
  assert.equal(snapshot.baseUrl, 'https://example.test');
  assert.equal(snapshot.credentials.configured, true);
  assert.equal(snapshot.credentials.masked, 'AK-****1234');
  assert.equal(snapshot.cache.master_data_digest, 'digest-1');
  assert.doesNotMatch(serialized, /plain-ak-must-not-persist/);
  assert.doesNotMatch(serialized, /plain-secret-must-not-persist/);
  assert.doesNotMatch(serialized, /bearer-must-not-persist/);
  assert.equal(Object.hasOwn(snapshot.credentials, 'access_key'), false);
  assert.equal(Object.hasOwn(snapshot.credentials, 'access_secret'), false);
  assert.equal(Object.hasOwn(snapshot.credentials, 'token'), false);
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
  assert.doesNotMatch(source, /auto_sync_interval_seconds: 60/);
  assert.match(source, /每天 08:00、12:00、15:00（北京时间）各主动拉取一次主数据/);
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
  assert.match(source, /PLATFORM_CONFIG_SNAPSHOT_KEY = 'cl_external_platform_config_snapshot_v1'/);
  assert.match(source, /PLATFORM_CONFIG_SNAPSHOT_MAX_AGE_MS = 24 \* 60 \* 60 \* 1000/);
  assert.match(source, /restoreConfigSnapshot\(\);/);
  assert.match(source, /persistConfigSnapshot\(\);/);
  assert.match(source, /const hasSnapshot = paintCachedPage\(\)/);
  assert.match(source, /function patchExternalPlatformPage\(view, html, \{preserveConfigDraft = false\} = \{\}\)/);
  assert.match(source, /view\.replaceChildren\(nextRoot\)/);
  assert.match(source, /currentNode\.replaceWith\(nextNode\)/);
  assert.match(source, /preserveConfigDraft: configEditing && !refreshConfigPanel/);
  assert.match(source, /input\.dataset\.externalDirtyBound === '1'/);
  const renderStart = source.indexOf('async function render({reload = true, force = false, refreshConfigPanel = false} = {})');
  const renderEnd = source.indexOf('  const detachAlgorithmListProvider', renderStart);
  assert.ok(renderStart >= 0 && renderEnd > renderStart);
  assert.doesNotMatch(source.slice(renderStart, renderEnd), /view\.innerHTML = configFormHtml\(config\)/);
  assert.match(source, /if \(config && \(!reload \|\| \(!force && fresh\)\)\) return true/);
  assert.match(source, /先配置并测试连接，再手动同步算法品目、算法产品、分析方式和算力环境/);
  assert.doesNotMatch(source, /联调准备状态 · 主数据 \/ 训练准备状态/);
  assert.match(source, /除人员登录参考外，内部算法接口均已进入 Provider contract/);
  assert.match(source, /\/readiness\?project_id=/);
  assert.match(source, /loadReadiness/);
  assert.match(source, /external-master-data-stale/);
  assert.match(source, /trainingReadiness/);
});


test('external platform exposes truth provider and never decorates algorithm-list DOM', () => {
  const source = readFileSync(new URL('../../static/modules/external-algorithm-platform.js', import.meta.url), 'utf8');
  assert.match(source, /algorithmListRuntime\?\.setExternalProvider\?\.\(algorithmListProvider\)/);
  assert.match(source, /snapshot:\s*\(\) =>/);
  assert.match(source, /categories:\s*cacheData\?\.categories/);
  assert.match(source, /matches:\s*\(algorithm, filters/);
  assert.doesNotMatch(source, /function decorateAlgorithmCards\(/);
  assert.doesNotMatch(source, /registerDecorator\('external-algorithm-platform'/);
  assert.doesNotMatch(source, /data-external-category-filter/);
});


test('platform integration page exposes focused settings tabs', () => {
  const source = readFileSync(new URL('../../static/modules/external-algorithm-platform.js', import.meta.url), 'utf8');
  assert.match(source, /external-platform-tabs/);
  assert.match(source, /'overview', 'connection', 'sync', 'vendor', 'api', 'history'/);
  assert.match(source, /tabButton\('vendor', '厂商对应表'/);
  assert.match(source, /data-platform-tab-panel="overview"/);
  assert.match(source, /state\(\)\.externalPlatformTab64 = next/);
});

test('platform page keeps a simple persistent save-test-sync flow', () => {
  const source = readFileSync(new URL('../../static/modules/external-algorithm-platform.js', import.meta.url), 'utf8');
  assert.match(source, /external-platform-steps/);
  assert.match(source, /<b>保存配置<\/b>/);
  assert.match(source, /<b>测试连接<\/b>/);
  assert.match(source, /<b>同步主数据<\/b>/);
  assert.match(source, /external-platform-status external-platform-status-v2/);
  assert.match(source, /<b>配置<\/b><em>\$\{escapeHtml\(savedStatus\)\}<\/em>/);
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
  assert.match(source, /sync-operation\?project_id=/);
  assert.match(syncBlock, /ensureSyncOperationPolling/);
  assert.match(source, /document\.querySelectorAll\('\[data-algorithm-sync\]'\)/);
  assert.doesNotMatch(source, /data-external-list-sync/);
  assert.match(source, /id="externalPlatformTest"/);
  assert.match(source, /id="externalPlatformSave"/);
  assert.match(source, /id="externalPlatformSync"/);
});


test('algorithm list keeps search and base filters while adding source filters', () => {
  const appSource = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
  const listSource = readFileSync(new URL('../../static/modules/algorithm-list-runtime.js', import.meta.url), 'utf8');
  const externalSource = readFileSync(new URL('../../static/modules/external-algorithm-platform.js', import.meta.url), 'utf8');
  assert.match(listSource, /placeholder="搜索算法名称 \/ 算法ID"/);
  assert.match(listSource, /data-algorithm-industry-filter/);
  assert.match(listSource, /data-algorithm-type-filter/);
  assert.match(listSource, /data-algorithm-source-filter/);
  assert.match(listSource, /data-algorithm-training-status-filter/);
  assert.match(appSource, /window\.renderAlgorithms423=function\(\)\{return window\.AlgorithmListRuntime\?\.render\?\.\(\)\}/);
  assert.match(appSource, /window\.renderAlg412=function\(\)\{return window\.AlgorithmListRuntime\?\.renderRows\?\.\(\)\}/);
  assert.doesNotMatch(externalSource, /dataset\.algorithmSourceFilter/);
});

test('sync settings expose the fixed 08 12 15 China-time schedule without claiming webhook support', () => {
  const source = readFileSync(new URL('../../static/modules/external-algorithm-platform.js', import.meta.url), 'utf8');
  assert.match(source, /自动同步已启用/);
  assert.match(source, /每天 08:00、12:00、15:00（北京时间）各主动拉取一次主数据/);
  assert.match(source, /没有 Webhook、订阅或推送接口/);
  assert.match(source, /auto_sync_enabled: mode === 'external'/);
  assert.doesNotMatch(source, /auto_sync_interval_seconds: 60/);
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


test('external training preflight exposes freshness without weakening the authoritative refresh window', () => {
  const source = readFileSync(new URL('../../static/modules/external-algorithm-platform.js', import.meta.url), 'utf8');
  assert.match(source, /function trainingPreflightFresh\(algorithmId, \{maxAgeMs = 30000\} = \{\}\)/);
  assert.match(source, /Boolean\(cached\?\.algorithm\) && age >= 0 && age < Math\.max\(0, Number\(maxAgeMs\) \|\| 0\)/);
  assert.match(source, /trainingPreflightFresh,/);
  assert.match(source, /async function preflightTraining\(algorithmId, \{request, force = false, maxAgeMs = 30000, signal\} = \{\}\)/);
});


test('sync operation UI reports real phase and counters without inventing a percentage', () => {
  const operation = {
    operation_id: 'sync-1',
    status: 'running',
    current_phase: 'fetch_analyses',
    started_at: '2026-09-28T04:00:00Z',
    processed_products: 37,
    total_products: 126,
    last_request_duration_ms: 420,
    success_count: 37,
    error_count: 0,
  };

  assert.equal(externalSyncOperationActive(operation), true);
  assert.equal(externalSyncOperationPhaseText(operation.current_phase), '核验产品分析详情');
  const html = externalSyncOperationHtml(operation);
  assert.match(html, /37 \/ 126/);
  assert.match(html, /420 ms/);
  assert.match(html, /成功 \/ 错误/);
  assert.doesNotMatch(html, /%/);
});


test('sync operation UI exposes listAll optimization source without changing progress into a fake percent', () => {
  const html = externalSyncOperationHtml({
    operation_id: 'sync-list-all',
    status: 'running',
    current_phase: 'fetch_analyses',
    processed_products: 2,
    total_products: 9,
    analysis_list_source: 'list_all',
    success_count: 2,
    error_count: 0,
  });
  assert.match(html, /listAll 一次读取/);
  assert.match(html, /2 \/ 9/);
  assert.doesNotMatch(html, /%/);
  assert.equal(externalSyncOperationPhaseText('fetch_analysis_index'), '读取分析方式索引');
});


test('deletion presentation distinguishes suspected, confirmed, running, failure and complete without false success',async()=>{
  const {externalDeletionPresentation}=await import('../../static/modules/external-algorithm-platform.js');
  assert.equal(typeof externalDeletionPresentation,'function');
  for(const [state,label,busy] of [['SUSPECTED_DELETED','待核实',false],['CONFIRMED_DELETED','已确认删除',false],['CLEANUP_PENDING','等待安全清理',true],['CLEANUP_RUNNING','安全清理中',true],['CLEANUP_FAILED','清理失败',false],['CLEANUP_COMPLETED','清理已完成',false]]){
    const actual=externalDeletionPresentation({external_deletion_status:state});
    assert.equal(actual.label,label);assert.equal(actual.busy,busy);
  }
});

test('sync summary displays genuine deletion counts and no invented cleanup percentage',()=>{
  const html=externalSyncOperationHtml({status:'success',counts:{suspected_deleted:2,cleanup_pending:1,cleanup_failed:0}});
  assert.match(html,/待核实/);assert.match(html,/待清理/);assert.match(html,/清理失败/);
  assert.doesNotMatch(html,/\d+%/);
});

test('cleanup details preserve suspected evidence and only permit failed safe retry', async () => {
  const {externalCleanupOperationHtml}=await import('../../static/modules/external-algorithm-platform.js');
  assert.equal(typeof externalCleanupOperationHtml,'function');
  const suspected=externalCleanupOperationHtml({operation_id:'suspect:a',state:'SUSPECTED_DELETED',phase:'verification',counts:{processed:3},evidence:{reason:'分页不完整'}});
  assert.match(suspected,/待核实/);assert.match(suspected,/已有任务继续/);assert.match(suspected,/新发布暂缓/);assert.match(suspected,/重新核实/);assert.doesNotMatch(suspected,/data-cleanup-retry/);
  const failed=externalCleanupOperationHtml({operation_id:'op1',state:'CLEANUP_FAILED',phase:'assets',counts:{processed:3,total:9},error:'文件被占用'});
  assert.match(failed,/data-cleanup-retry="op1"/);assert.match(failed,/文件被占用/);assert.doesNotMatch(failed,/已有任务继续/);assert.match(failed,/恢复副本/);assert.match(failed,/3/);assert.doesNotMatch(failed,/\d+%/);
  assert.doesNotMatch(externalCleanupOperationHtml({state:'CLEANUP_RUNNING'}),/data-cleanup-retry/);
});

async function isolatedExternalRuntime(t, fetcher) {
  const {installExternalAlgorithmPlatformRuntime}=await import('../../static/modules/external-algorithm-platform.js');
  const saved={window:globalThis.window,document:globalThis.document,MutationObserver:globalThis.MutationObserver};
  const state={page:'',project:{id:'A'}};
  const json=body=>({ok:true,status:200,text:async()=>JSON.stringify(body)});
  globalThis.document={body:{},getElementById:()=>null,querySelector:()=>null,querySelectorAll:()=>[]};
  globalThis.MutationObserver=class {observe(){} disconnect(){}};
  globalThis.window={fetch:async(url,options)=>{
    if(url.endsWith('/config')) return json({config:{mode:'external',base_url:'https://example.invalid',credentials:{configured:true}}});
    if(url.endsWith('/cache')) return json({cache:{}});
    if(url.includes('/cleanup-operations?')) return json({items:[],total:0,offset:0,limit:25,has_more:false});
    return fetcher(url,options,json);
  }};
  const runtime=installExternalAlgorithmPlatformRuntime({getState:()=>state,projectId:()=>state.project.id});
  t.after(()=>{runtime.destroy();for(const [key,value] of Object.entries(saved)){if(value===undefined)delete globalThis[key];else globalThis[key]=value;}});
  await runtime.loadConfig({silent:true});
  return {runtime,state,json};
}

for(const aba of [true,false]) test(`sync status rejects ${aba?'ABA':'older same-project'} reads before they can block a new POST`,async t=>{
  let releaseOld,reads=0,posts=0;
  const {runtime,state,json}=await isolatedExternalRuntime(t,async(url,options,json)=>{
    if(options.method==='POST'){posts+=1;return json({operation:{operation_id:'created',status:'success'}});}
    reads+=1;
    if(reads===1)return new Promise(resolve=>{releaseOld=resolve});
    return json({operation:{operation_id:`new-${state.project.id}`,status:'success'}});
  });
  const old=runtime.loadSyncOperation({silent:true});await new Promise(resolve=>setImmediate(resolve));
  if(aba){state.project.id='B';await runtime.loadSyncOperation({silent:true});}
  state.project.id='A';await runtime.loadSyncOperation({silent:true});
  releaseOld(json({operation:{operation_id:'old-A',status:'running'}}));
  assert.equal((await old).operation_id,'new-A');
  await runtime.syncNow();assert.equal(posts,1);
});

test('malformed successful JSON status response preserves running operation and reports parse failure',async t=>{
  let malformed=false;
  const {runtime}=await isolatedExternalRuntime(t,async(url,options,json)=>malformed?{ok:true,status:200,text:async()=>'{broken'}:json({operation:{operation_id:'running-original',status:'running'}}));
  await runtime.loadSyncOperation({silent:true});malformed=true;
  await assert.rejects(runtime.loadSyncOperation({silent:true}),error=>error.name==='ParseError'&&error.code==='INVALID_JSON_RESPONSE');
  assert.equal((await runtime.syncNow()).operation_id,'running-original');
});


test('stale status errors cannot replace a newer same-project read',async t=>{
  let rejectOld,reads=0;
  const {runtime}=await isolatedExternalRuntime(t,async(url,options,json)=>{
    if(++reads===1)return new Promise((resolve,reject)=>{rejectOld=reject});
    return json({operation:{operation_id:'new-current',status:'running'}});
  });
  const old=runtime.loadSyncOperation({silent:true});await new Promise(resolve=>setImmediate(resolve));
  await runtime.loadSyncOperation({silent:true});rejectOld(new Error('stale network failure'));
  assert.equal((await old).operation_id,'new-current');
});

test('an old POST receipt cannot overwrite the new A scope after A to B to A',async t=>{
  let releasePost,posts=0;
  const {runtime,state,json}=await isolatedExternalRuntime(t,async(url,options,json)=>{
    if(options.method==='POST'){
      if(++posts===1)return new Promise(resolve=>{releasePost=resolve});
      return json({operation:{operation_id:'duplicate',status:'success'}});
    }
    return json({operation:{operation_id:`new-${state.project.id}`,status:'running'}});
  });
  const old=runtime.syncNow();await new Promise(resolve=>setImmediate(resolve));
  state.project.id='B';await runtime.loadSyncOperation({silent:true});
  state.project.id='A';await runtime.loadSyncOperation({silent:true});
  releasePost(json({operation:{operation_id:'old-post-A',status:'success'}}));await old;
  assert.equal((await runtime.syncNow()).operation_id,'new-A');assert.equal(posts,1);
});
