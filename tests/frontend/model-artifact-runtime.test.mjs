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
      root_prefix: 'changlian-ai/artifacts/',
      auto_upload_enabled: true,
    },
    storage_sources: [{
      id: 'oss-prod', name: '生产 OSS',
      config: {public_base_url: 'https://models.example.com'},
    }],
    summary: {total: 8, uploaded: 7, failed: 1, pending: 0},
  });

  assert.equal(config.storageSourceId, 'oss-prod');
  assert.equal(config.rootPrefix, 'changlian-ai/artifacts/');
  assert.equal(config.publicBaseUrl, 'https://models.example.com');
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
  assert.match(source, /root_prefix:/);
  assert.match(source, /source\?\.config\?\.public_base_url/);
  assert.doesNotMatch(source, /modelArtifactPublicBaseUrl/);
  assert.doesNotMatch(source, /modelArtifactSuggestPublicUrl/);
  assert.match(source, /toLowerCase\(\) === 'oss'/);
  assert.match(source, /请选择阿里云 OSS/);
  assert.match(source, /开发兼容/);
  assert.match(source, /OSS 长期访问地址/);
  assert.match(source, /StorageSource/);
  assert.match(source, /不会与素材 Provider prefix 重复拼接/);
  assert.match(source, /自动归档已启用/);
  assert.doesNotMatch(source, /id="modelArtifactAutoUpload"/);
  assert.match(source, /存储配置/);
  assert.match(source, /run-auto/);
  assert.match(source, /interaction-logs/);
  assert.match(source, /复制诊断信息/);
  assert.match(source, /MODEL_CONFIG_CACHE_TTL_MS = 2 \* 60 \* 1000/);
  assert.match(source, /loadModelConfig\(\{force = false\} = \{\}\)/);
  assert.match(source, /let configInflight = null/);
  assert.match(source, /if \(configInflight\) return configInflight/);
  assert.match(source, /if \(configInflight === request\) configInflight = null/);
});


test('audit polling is PollRegistry-owned and audit rows patch by log id', () => {
  const source = fs.readFileSync(new URL('../../static/modules/model-artifact-runtime.js', import.meta.url), 'utf8');
  assert.match(source, /pollRegistry \|\| window\.PollRegistryRuntime/);
  assert.match(source, /registry\.startTimeout\(AUDIT_POLL_KEY, PLATFORM_PAGE/);
  assert.match(source, /function patchAuditRows\(body\)/);
  assert.match(source, /data-audit-id=/);
  assert.match(source, /build: 'model-artifacts-65003'/);
  assert.doesNotMatch(source, /window\.setInterval\(/);
  assert.doesNotMatch(source, /body\.innerHTML = auditRowsHtml\(\)/);
});


test('empty audit results are cached and concurrent audit reads are deduped', () => {
  const source = fs.readFileSync(new URL('../../static/modules/model-artifact-runtime.js', import.meta.url), 'utf8');
  assert.match(source, /const AUDIT_LOG_CACHE_TTL_MS = 10 \* 1000/);
  assert.match(source, /let logsLoadedAt = 0/);
  assert.match(source, /let logsInflight = null/);
  assert.match(source, /let logsCacheKey = ''/);
  assert.match(source, /if \(!force && logsLoadedAt > 0 && logsCacheKey === cacheKey/);
  assert.match(source, /if \(logsInflight && logsInflightKey === cacheKey\) return logsInflight/);
  assert.match(source, /logsLoadedAt = Date\.now\(\)/);
  assert.match(source, /refreshLogsOnly\(\{force: true\}\)/);
  assert.doesNotMatch(source, /if \(!logs\.length && !loading\)/);
  assert.match(source, /build: 'model-artifacts-65005'/);
});
