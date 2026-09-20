import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

import {
  normalizePublishConfig,
  publicationActionLabel,
  publicationPreflight,
} from '../../static/modules/external-algorithm-publish.js';

test('publish config normalizes storage, compute mappings and recovery paths', () => {
  const config = normalizePublishConfig({
    config: {
      storage_source_id: 'oss-models',
      public_base_url: 'https://algorithm.example.com',
      publish_original_model: true,
      target_mappings: {
        rockchip: {compute_platform_id: 'cp-rk', chip_code: 'RK3568', enabled: true},
      },
    },
    storage_sources: [{id: 'oss-models', name: '模型 OSS', type: 'oss'}],
    compute_platforms: [{computePlatformId: 'cp-rk', computePlatformName: '瑞芯微'}],
  });
  assert.equal(config.storageSourceId, 'oss-models');
  assert.equal(config.publicBaseUrl, 'https://algorithm.example.com');
  assert.equal(config.publishOriginalModel, true);
  assert.equal(config.targetMappings.rockchip.compute_platform_id, 'cp-rk');
  assert.equal(config.targetMappings.rockchip.chip_code, 'RK3568');
  assert.equal(config.versionListByProduct, '/internal/algorithm/algorithm-version/listByProduct/{productId}');
  assert.equal(config.weightListByVersion, '/internal/algorithm/algorithm-weight/listByVersion/{algoVersionId}');
  assert.equal(config.storageSources.length, 1);
  assert.equal(config.computePlatforms.length, 1);
});

test('publish UI leaves model asset storage ownership to ModelArtifactRuntime', () => {
  const source = readFileSync(
    new URL('../../static/modules/external-algorithm-publish.js', import.meta.url),
    'utf8',
  );
  assert.match(source, /ModelArtifactRuntime is the single owner of model asset storage/);
  assert.match(source, /storage_source_id:\s*''/);
  assert.doesNotMatch(source, /storage_source_id:\s*config\?\.storageSourceId/);
});


test('version publish action reflects durable publication state', () => {
  assert.equal(publicationActionLabel({}), '同步到新畅联');
  assert.equal(publicationActionLabel({external_publish_requested_at: '2026-09-17T12:00:00Z'}), '待同步');
  assert.equal(publicationActionLabel({external_publish_status: 'failed'}), '重新同步');
  assert.equal(publicationActionLabel({external_publish_status: 'unknown'}), '重新同步');
  assert.equal(publicationActionLabel({external_publish_status: 'published'}), '已同步');
});


test('publish UI keeps manual sync primary and stale compute mappings visible', () => {
  const source = readFileSync(
    new URL('../../static/modules/external-algorithm-publish.js', import.meta.url),
    'utf8',
  );
  assert.match(source, /data-external-publish-automation="1"/);
  assert.match(source, /高级设置 · 自动发布/);
  assert.match(source, /算力环境来自最近一次新畅联主数据同步/);
  assert.match(source, /同步到新畅联/);
});


test('manual publish preflight blocks stale product and analysis identity before artifacts', () => {
  const stale = publicationPreflight({
    identity_ready: false,
    identity_issues: [{code: 'EXTERNAL_MASTER_DATA_STALE'}],
    conversion_active: false,
  });
  assert.equal(stale.ready, false);
  assert.match(stale.message, /立即同步/);

  const analysis = publicationPreflight({
    identity_ready: false,
    identity_issues: [{code: 'EXTERNAL_VERSION_ANALYSIS_STALE'}],
    conversion_active: false,
  });
  assert.equal(analysis.ready, false);
  assert.match(analysis.message, /分析方式已失效/);
  assert.match(analysis.message, /不会自动改挂/);

  const inactive = publicationPreflight({
    identity_ready: false,
    identity_issues: [{code: 'EXTERNAL_ALGORITHM_INACTIVE'}],
    conversion_active: false,
  });
  assert.equal(inactive.ready, false);
  assert.match(inactive.message, /已在新畅联下架/);
});

test('manual publish preflight allows original model delivery while conversions are still running', () => {
  const trainingReady = publicationPreflight({
    conversion_active: true,
    transport_ready: true,
    identity_ready: true,
    discovered: [{target: 'original', publish_mapping_status: 'mapped'}],
    mapped_artifact_count: 1,
    blocked_artifact_count: 0,
    ignored_artifact_count: 0,
    publish_ready: true,
  });
  assert.equal(trainingReady.ready, true);

  assert.deepEqual(
    publicationPreflight({conversion_active: false, discovered: []}),
    {ready: false, message: '当前版本还没有可交付的训练模型或转换产物。'},
  );

  const blocked = publicationPreflight({
    conversion_active: false,
    discovered: [
      {target: 'onnx', publish_mapping_status: 'blocked'},
      {target: 'rockchip', publish_mapping_status: 'mapped'},
    ],
    mapped_artifact_count: 1,
    blocked_artifact_count: 1,
    ignored_artifact_count: 0,
    publish_ready: false,
  });
  assert.equal(blocked.ready, false);
  assert.match(blocked.message, /ONNX/);
  assert.match(blocked.message, /补齐/);
});

test('manual publish preflight blocks missing model delivery configuration', () => {
  const result = publicationPreflight({
    conversion_active: false,
    transport_ready: false,
    transport_issues: [
      {code: 'EXTERNAL_PUBLISH_CONFIG_INCOMPLETE', message: '尚未配置本平台外部访问地址'},
      {code: 'MODEL_ARTIFACT_STORAGE_NOT_CONFIGURED', message: '尚未配置模型资产存储源'},
    ],
    discovered: [{target: 'rockchip', publish_mapping_status: 'mapped'}],
    mapped_artifact_count: 1,
    blocked_artifact_count: 0,
    ignored_artifact_count: 0,
    publish_ready: false,
  });

  assert.equal(result.ready, false);
  assert.match(result.message, /存储配置 → 算法与转换结果存储/);
  assert.match(result.message, /OSS \/ CDN/);
  assert.match(result.message, /测试存储/);
});


test('manual publish preflight accepts mapped artifacts and reports intentional ignores', () => {
  const result = publicationPreflight({
    conversion_active: false,
    discovered: [
      {target: 'rockchip', publish_mapping_status: 'mapped'},
      {target: 'onnx', publish_mapping_status: 'ignored'},
    ],
    mapped_artifact_count: 1,
    blocked_artifact_count: 0,
    ignored_artifact_count: 1,
    publish_ready: true,
  });

  assert.equal(result.ready, true);
  assert.match(result.message, /同步 1 个权重/);
  assert.match(result.message, /1 个转换目标已明确关闭发布/);
});

test('manual publish fetches read-only status before write request', () => {
  const source = readFileSync(
    new URL('../../static/modules/external-algorithm-publish.js', import.meta.url),
    'utf8',
  );
  const start = source.indexOf('async function publishVersion(');
  const end = source.indexOf('function decorateVersionRows()', start);
  assert.ok(start >= 0 && end > start);
  const block = source.slice(start, end);
  const statusRead = block.indexOf('const status = await requestJson(');
  const preflight = block.indexOf('publicationPreflight(status)');
  const publishWrite = block.indexOf("/publish\`, {method: 'POST'}");
  assert.ok(statusRead >= 0);
  assert.ok(preflight > statusRead);
  assert.ok(publishWrite > preflight);
});


test('publish UI locks recovery endpoints to official OpenAPI', async () => {
  const source = await readFile(
    new URL('../../static/modules/external-algorithm-publish.js', import.meta.url),
    'utf8',
  );
  assert.match(source, /官方发布接口/);
  assert.match(source, /接口路径来自新畅联官方 OpenAPI，平台固定使用，不允许手工修改/);
  assert.doesNotMatch(source, /id="externalPublishVersionList"/);
  assert.doesNotMatch(source, /id="externalPublishWeightList"/);
  assert.match(source, /version_list_by_product: '\/internal\/algorithm\/algorithm-version\/listByProduct\/\{productId\}'/);
  assert.match(source, /weight_list_by_version: '\/internal\/algorithm\/algorithm-weight\/listByVersion\/\{algoVersionId\}'/);
});
