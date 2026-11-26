export const storageSourcesUrl = '/api/v61/storage-sources';
export const storageSourceUrl = (id: string) => `${storageSourcesUrl}/${encodeURIComponent(id)}`;

export interface StorageSource {
  id: string;
  name: string;
  type: string;
  config: Record<string, unknown>;
  enabled: boolean;
  is_default: boolean;
  secret_configured: boolean;
  health_status: string;
  last_checked_at?: string;
}

export function storageResponseUnknown(error: unknown) {
  const status = (error as {httpStatus?: number})?.httpStatus;
  return !status || status >= 500 || status === 408;
}

// Provider error bodies can contain credential-bearing URLs or SDK diagnostics.
// Only expose explicitly known action results and HTTP status on this page.
export function storageError(error: unknown, message: string) {
  const status = (error as {httpStatus?: number})?.httpStatus;
  const code = (error as {code?: string})?.code;
  if (code === 'STORAGE_SOURCE_ACTIVE_TASK_DEPENDENCY') return '存储源正被活动任务使用。';
  return status ? `${message}（HTTP ${status}）` : message;
}

// These URL fields are displayed as text and never forward userinfo or queries.
export function storageAddress(value: unknown) {
  const text = typeof value === 'string' ? value : '';
  if (text.includes('@')) return '地址含认证信息';
  return text.split(/[?#]/, 1)[0] || '—';
}
