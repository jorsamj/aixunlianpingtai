const STATUS_ALIASES = Object.freeze({
  WAITING: 'WAITING_RESOURCE',
  PENDING: 'QUEUED',
  DONE: 'SUCCEEDED',
  FINISHED: 'SUCCEEDED',
  COMPLETED: 'SUCCEEDED',
  STOPPED: 'CANCELLED',
  CANCELED: 'CANCELLED',
  CANCELLING: 'CANCEL_REQUESTED',
});

const ACTIVE = new Set([
  'ACCEPTED', 'QUEUED', 'WAITING_RESOURCE', 'PREPARING', 'RUNNING',
  'PAUSING', 'PAUSED', 'RESUMING', 'CANCEL_REQUESTED', 'RETRYING',
]);

const TERMINAL = new Set([
  'AWAITING_CONFIRMATION', 'PARTIAL_SUCCESS', 'SUCCEEDED', 'CANCELLED',
  'FAILED', 'BLOCKED_BY_ENVIRONMENT', 'BLOCKED_BY_HARDWARE',
]);

function clampPercent(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return 0;
  return Math.max(0, Math.min(100, number));
}

export function canonicalTaskStatus(value) {
  const raw = value && typeof value === 'object'
    ? (value.task_status ?? value.status)
    : value;
  const normalized = String(raw || '').trim().toUpperCase();
  return STATUS_ALIASES[normalized] || normalized;
}

export function canonicalTaskPhase(task = {}) {
  return String(task?.phase ?? task?.task_stage ?? task?.stage ?? '').trim().toLowerCase();
}

export function canonicalTaskProgressPercent(task = {}) {
  if (task?.progress_percent !== null && task?.progress_percent !== undefined && task?.progress_percent !== '') {
    return clampPercent(task.progress_percent);
  }
  // Explicit compatibility only. Unified durable-task payloads must provide
  // progress_percent; never derive a percentage from item counts in the browser.
  if (task?.progress !== null && task?.progress !== undefined && task?.progress !== '') {
    return clampPercent(task.progress);
  }
  return 0;
}

export function isCanonicalTaskActive(value) {
  return ACTIVE.has(canonicalTaskStatus(value));
}

export function isCanonicalTaskTerminal(value) {
  const status = canonicalTaskStatus(value);
  return Boolean(status) && TERMINAL.has(status);
}

export function trainingDisplayStatus(task = {}) {
  const status = canonicalTaskStatus(task);
  if (status === 'WAITING_RESOURCE') return 'waiting';
  if (['ACCEPTED', 'QUEUED', 'PREPARING', 'RETRYING'].includes(status)) return 'queued';
  if (['RUNNING', 'PAUSING', 'RESUMING', 'CANCEL_REQUESTED'].includes(status)) return 'running';
  if (status === 'PAUSED') return 'paused';
  if (status === 'SUCCEEDED' || status === 'PARTIAL_SUCCESS') return 'completed';
  if (status === 'CANCELLED') return 'cancelled';
  if (['FAILED', 'BLOCKED_BY_ENVIRONMENT', 'BLOCKED_BY_HARDWARE'].includes(status)) return 'failed';
  if (status === 'AWAITING_CONFIRMATION') return 'pending';
  return String(task?.status ?? status ?? '').trim().toLowerCase();
}

export function taskRuntimeTruth(task = {}) {
  const position = Number(task?.resource_queue_position);
  return {
    task_id: String(task?.task_id ?? task?.id ?? ''),
    status: canonicalTaskStatus(task),
    persisted_status: String(task?.persisted_status ?? '').trim().toUpperCase(),
    phase: canonicalTaskPhase(task),
    progress_percent: canonicalTaskProgressPercent(task),
    current_item: String(task?.current_item ?? '').trim(),
    resource_queue_position: Number.isFinite(position) && position > 0 ? position : null,
    resource_queue_position_exact: task?.resource_queue_position_exact === true,
    resource_pool_key: String(task?.resource_pool_key ?? '').trim(),
    resource_pool_label: String(task?.resource_pool_label ?? '').trim(),
    resource_wait_reason: String(task?.resource_wait_reason ?? '').trim(),
    worker_id: String(task?.worker_id ?? task?.task_worker_id ?? '').trim(),
    error: String(task?.error ?? '').trim(),
  };
}
