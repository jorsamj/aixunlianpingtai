import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

import {
  normalizeModelArtifactConfig,
  auditStatusPresentation,
  operationLabel,
  diagnosticText,
} from '../../static/modules/model-artifact-runtime.js';


test('model artifact config uses backend field names without frontend-only aliases leaking', () => {
  const config = normalizeModelArtifactConfig({
    config: {
      storage_source_id: 'oss-prod',
      object_prefix: 'algorithm-models',
      auto_upload_enabled: true,
    },
    storage_sources: [{id: 'oss-prod', name: '生产 OSS'}],
    summary: {total: 8, uploaded: 7, failed: 1, pending: 0},
  });

  assert.equal(config.storageSourceId, 'oss-prod');
  assert.equal(config.objectPrefix, 'algorithm-models');
  assert.equal(config.autoUploadEnabled, true);
  assert.equal(config.summary.failed, 1);
});


test('audit presentation distinguishes success failure and unknown', () => {
  assert.equal(auditStatusPresentation('SUCCESS').label, '成功');
  assert.equal(auditStatusPresentation('FAILED').label, '失败');
  assert.equal(auditStatusPresentation('UNKNOWN').label, '状态未知');
  assert.equal(operationLabel('weight_create'), '创建权重记录');
});


test('diagnostic copy contains local and remote correlation ids for AI troubleshooting', () => {
  const text = diagnosticText({
    status: 'FAILED', operation: 'weight_create', method: 'POST', endpoint: '/algorithm-weight/add',
    algorithm_id: 'a1', version_id: 'v1', artifact_id: 'artifact-1', external_algo_version_id: 'av-1',
    external_weight_id: '', request_id: 'remote-r1', correlation_id: 'local-c1', error_message: 'bad platform',
    request: {computePlatformId: 'cp-bad'}, response: {code: 400},
  });
  assert.match(text, /algorithm_id：a1/);
  assert.match(text, /version_id：v1/);
  assert.match(text, /artifact_id：artifact-1/);
  assert.match(text, /algoVersionId：av-1/);
  assert.match(text, /Correlation ID：local-c1/);
  assert.match(text, /失败原因：bad platform/);
});


test('runtime source exposes storage test, auto upload and interaction log UI', () => {
  const source = fs.readFileSync(new URL('../../static/modules/model-artifact-runtime.js', import.meta.url), 'utf8');
  assert.match(source, /算法与转换结果存储/);
  assert.match(source, /畅联云交互日志/);
  assert.match(source, /storage-test/);
  assert.match(source, /modelArtifactPublicBaseUrl/);
  assert.match(source, /存储配置/);
  assert.match(source, /run-auto/);
  assert.match(source, /interaction-logs/);
  assert.match(source, /复制诊断信息/);
});
