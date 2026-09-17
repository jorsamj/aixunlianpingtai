const ACTIVE_CLEAN = new Set(['queued', 'running']);

const CLEAN_STAGE_TEXT = {
  materializing: '正在读取素材',
  analyzing: '正在分析图片',
  evaluating: '正在判断清洗规则',
  duplicate_lookup: '正在检查重复图片',
  saving_clean_result: '正在保存清洗结果',
  saving_clean_error: '正在记录异常结果',
  cleaning: '正在清洗',
};

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
  const queuePositionExact = task.resource_queue_position_exact === true;
  const waitReason = String(task.resource_wait_reason || '').trim();
  const workerId = String(task.worker_id || '').trim();
  const stage = String(task.phase || task.task_stage || task.stage || '').trim();
  const currentItem = String(task.current_item || task.current_image_id || task.current || '').trim();

  let runtimeText = '';
  if (status === 'queued') {
    const parts = [];
    if (queuePositionExact && queuePosition > 0) parts.push(`资源队列第 ${queuePosition} 位`);
    if (waitReason) parts.push(waitReason);
    runtimeText = parts.join(' · ');
  } else if (status === 'running') {
    const parts = [];
    if (CLEAN_STAGE_TEXT[stage]) parts.push(CLEAN_STAGE_TEXT[stage]);
    if (currentItem) parts.push(`当前 ${currentItem}`);
    if (workerId) parts.push(`Worker ${workerId}`);
    runtimeText = parts.join(' · ');
  }

  return {
    ...task,
    status,
    statusText,
    percent,
    processed,
    total,
    flagged,
    stage,
    currentItem,
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
