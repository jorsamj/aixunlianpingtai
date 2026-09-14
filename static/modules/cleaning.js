const ACTIVE_CLEAN = new Set(['queued', 'running']);

function cleanStatusFallback(status) {
  return ({
    queued: '排队中',
    running: '清洗中',
    awaiting_confirmation: '待确认',
    done: '已完成',
    failed: '失败',
    cancelled: '已停止',
    stopped: '已停止',
  })[status] || status || '-';
}

function finiteNumber(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

export function isActiveCleanTask(task) {
  const status = typeof task === 'string' ? task : task?.status;
  return ACTIVE_CLEAN.has(String(status || '').toLowerCase());
}

export function cleanTaskView(task = {}) {
  const status = String(task.status || '').toLowerCase();
  const statusText = String(task.status_text || cleanStatusFallback(status));
  const percent = Math.max(0, Math.min(100, finiteNumber(task.progress, 0)));
  const processed = Math.max(0, finiteNumber(task.processed_images, 0));
  const total = Math.max(0, finiteNumber(task.total_images, 0));
  const flagged = Math.max(0, finiteNumber(task.flagged_images, 0));
  const queuePosition = Math.max(0, Math.trunc(finiteNumber(task.resource_queue_position, 0)));
  const waitReason = String(task.resource_wait_reason || '').trim();
  const workerId = String(task.worker_id || '').trim();

  let runtimeText = '';
  if (status === 'queued') {
    const parts = [];
    if (queuePosition > 0) parts.push(`资源队列第 ${queuePosition} 位`);
    if (waitReason) parts.push(waitReason);
    runtimeText = parts.join(' · ');
  } else if (status === 'running' && workerId) {
    runtimeText = `Worker ${workerId}`;
  }

  return {
    ...task,
    status,
    statusText,
    percent,
    processed,
    total,
    flagged,
    progressText: `${processed}/${total}`,
    runtimeText,
    active: isActiveCleanTask(status),
  };
}

export function applyCleanConfirmation(materials, result) {
  const deleted = new Set((result?.deleted_images || result?.deleted_ids || []).map(String));
  const processed = new Set((result?.processed_ids || []).map(String));
  return (materials || [])
    .filter(material => !deleted.has(String(material.id)))
    .map(material => processed.has(String(material.id))
      ? {...material, processing_status: 'processed', clean_skipped: false}
      : material);
}
