export const STORAGE_TYPE_LABELS = Object.freeze({
  local: '本地存储',
  oss: '阿里云 OSS',
  s3: 'S3 兼容对象存储',
  remote: '其他服务器素材源',
});

export function enabledStorageSources(sources) {
  return (sources || []).filter(source => source && source.enabled !== false);
}

export function defaultStorageSource(sources) {
  const enabled = enabledStorageSources(sources);
  return enabled.find(source => source.is_default) || enabled.find(source => source.id === 'default_local') || enabled[0] || null;
}

export function storageSourceLabel(source) {
  if (!source) return '未知来源';
  return String(source.name || STORAGE_TYPE_LABELS[source.type] || source.id || '未知来源');
}

export function sourceMatches(material, sourceId) {
  const selected = String(sourceId || 'all');
  if (selected === 'all') return true;
  return String(material?.storage_source_id || 'default_local') === selected;
}

export function buildStorageSourcePayload(values) {
  const type = String(values?.type || 'local');
  if (!(type in STORAGE_TYPE_LABELS)) throw new Error('不支持的素材存储类型');
  const config = {};
  const credentials = {};
  const copy = (target, key, value) => {
    const text = String(value ?? '').trim();
    if (text) target[key] = text;
  };
  if (type === 'local') copy(config, 'root', values.root);
  if (type === 'oss') {
    copy(config, 'endpoint', values.endpoint); copy(config, 'bucket', values.bucket); copy(config, 'prefix', values.prefix);
    copy(credentials, 'access_key_id', values.access_key_id); copy(credentials, 'access_key_secret', values.access_key_secret);
    if (Boolean(credentials.access_key_id) !== Boolean(credentials.access_key_secret)) {
      throw new Error('AccessKey ID 和 AccessKey Secret 必须同时填写');
    }
  }
  if (type === 's3') {
    copy(config, 'endpoint', values.endpoint); copy(config, 'region', values.region); copy(config, 'bucket', values.bucket); copy(config, 'prefix', values.prefix);
    config.use_ssl = values.use_ssl !== false;
    copy(credentials, 'access_key_id', values.access_key_id); copy(credentials, 'secret_access_key', values.secret_access_key);
    if (Boolean(credentials.access_key_id) !== Boolean(credentials.secret_access_key)) {
      throw new Error('Access Key 和 Secret Key 必须同时填写');
    }
  }
  if (type === 'remote') {
    copy(config, 'base_url', values.base_url); copy(config, 'namespace', values.namespace); copy(config, 'root', values.root);
    copy(credentials, 'token', values.token);
  }
  const payload = {name: String(values?.name || '').trim(), type, config, enabled: values?.enabled !== false};
  // PATCH 时不发送空 credentials。后端把显式 credentials={} 解释为“清除凭据”，
  // 因此编辑已配置存储源且密钥留空时必须省略该字段，才能真正保留原密钥。
  if (Object.keys(credentials).length) payload.credentials = credentials;
  return payload;
}

export function buildLabelRemapPayload(externalClassId, currentTargetLabelId, nextTargetLabelId) {
  const classId = Number(externalClassId);
  if (!Number.isInteger(classId) || classId < 0) throw new Error('外部类别编号无效');
  const next = String(nextTargetLabelId ?? '').trim();
  return {
    external_class_id: classId,
    action: next ? 'map' : 'ignore',
    target_label_id: next || null,
    expected_current_label_id: currentTargetLabelId || null,
  };
}

export function isLabelRemapTerminal(status) {
  return ['SUCCEEDED', 'PARTIAL_SUCCESS', 'FAILED', 'CANCELLED',
    'BLOCKED_BY_ENVIRONMENT', 'BLOCKED_BY_HARDWARE'].includes(String(status || ''));
}
