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
  }
  if (type === 's3') {
    copy(config, 'endpoint', values.endpoint); copy(config, 'region', values.region); copy(config, 'bucket', values.bucket); copy(config, 'prefix', values.prefix);
    config.use_ssl = values.use_ssl !== false;
    copy(credentials, 'access_key_id', values.access_key_id); copy(credentials, 'secret_access_key', values.secret_access_key);
  }
  if (type === 'remote') {
    copy(config, 'base_url', values.base_url); copy(config, 'namespace', values.namespace); copy(config, 'root', values.root);
    copy(credentials, 'token', values.token);
  }
  return {name: String(values?.name || '').trim(), type, config, credentials, enabled: values?.enabled !== false};
}
