import test from 'node:test';
import assert from 'node:assert/strict';

import {
  normalizePublishConfig,
  publicationActionLabel,
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
  assert.equal(config.versionListByProduct, '/algorithm-version/listByProduct/{productId}');
  assert.equal(config.weightListByVersion, '/algorithm-weight/listByVersion/{algoVersionId}');
  assert.equal(config.storageSources.length, 1);
  assert.equal(config.computePlatforms.length, 1);
});

test('version publish action reflects durable publication state', () => {
  assert.equal(publicationActionLabel({}), '同步到新畅联');
  assert.equal(publicationActionLabel({external_publish_requested_at: '2026-09-17T12:00:00Z'}), '待同步');
  assert.equal(publicationActionLabel({external_publish_status: 'failed'}), '重新同步');
  assert.equal(publicationActionLabel({external_publish_status: 'unknown'}), '重新同步');
  assert.equal(publicationActionLabel({external_publish_status: 'published'}), '已同步');
});
