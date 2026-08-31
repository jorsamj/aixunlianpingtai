const ACTIVE = new Set(['QUEUED', 'RUNNING', 'CANCEL_REQUESTED']);

const STATUS_TEXT = {
  QUEUED: '排队中',
  RUNNING: '处理中',
  AWAITING_CONFIRMATION: '待确认',
  PARTIAL_SUCCESS: '部分成功',
  SUCCEEDED: '已完成',
  CANCEL_REQUESTED: '正在停止',
  CANCELLED: '已停止',
  FAILED: '失败',
  BLOCKED_BY_ENVIRONMENT: '缺少运行环境',
  BLOCKED_BY_HARDWARE: '缺少硬件',
};

function positive(value, field) {
  const number = Number(value);
  if (!Number.isFinite(number) || number <= 0) throw new Error(`${field} 必须大于 0`);
  return number;
}

export function videoTaskFormValues(mode, values = {}) {
  const payload = {mode};
  if (mode === 'interval_seconds') payload.interval_seconds = positive(values.intervalSeconds, '时间间隔');
  else if (mode === 'fps') payload.extract_fps = positive(values.extractFps, '抽帧率');
  else if (mode === 'fixed_count') payload.fixed_count = Math.trunc(positive(values.fixedCount, '固定帧数'));
  else throw new Error('不支持的切帧方式');
  if (Number(values.maxFrames) > 0) payload.max_frames = Math.trunc(Number(values.maxFrames));
  return payload;
}

export function isActiveVideoTask(task) {
  return ACTIVE.has(String(task?.status || '').toUpperCase());
}

export function normalizeVideoTask(task = {}) {
  const status = String(task.status || '').toUpperCase();
  let samplingText = '未知方式';
  if (task.mode === 'fixed_count') samplingText = `固定抽取 ${Number(task.fixed_count || 0)} 帧`;
  else if (task.mode === 'fps') samplingText = `每秒 ${Number(task.extract_fps || 0)} 帧`;
  else if (task.mode === 'interval_seconds') samplingText = `每 ${Number(task.interval_seconds || 0)} 秒 1 帧`;
  return {
    ...task,
    status,
    statusText: STATUS_TEXT[status] || status,
    samplingText,
    extractedFrames: Number(task.result?.extracted_frames ?? task.extracted_frames ?? 0),
  };
}
