import {
  canonicalTaskProgressPercent,
  canonicalTaskStatus,
  exactTaskQueuePosition,
  isCanonicalTaskActive,
} from './task-runtime-truth.js';

const STATUS_TEXT = {
  ACCEPTED: '已受理',
  QUEUED: '排队中',
  WAITING_RESOURCE: '等待资源',
  PREPARING: '准备中',
  RUNNING: '处理中',
  PAUSING: '暂停中',
  PAUSED: '已暂停',
  RESUMING: '恢复中',
  RETRYING: '重试中',
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
  return isCanonicalTaskActive(task);
}

export function normalizeVideoTask(task = {}) {
  const status = canonicalTaskStatus(task);
  const progressPercent = canonicalTaskProgressPercent(task);
  let samplingText = '未知方式';
  if (task.mode === 'fixed_count') samplingText = `固定抽取 ${Number(task.fixed_count || 0)} 帧`;
  else if (task.mode === 'fps') samplingText = `每秒 ${Number(task.extract_fps || 0)} 帧`;
  else if (task.mode === 'interval_seconds') samplingText = `每 ${Number(task.interval_seconds || 0)} 秒 1 帧`;
  const queuePosition = exactTaskQueuePosition(task);
  const waitReason = String(task.resource_wait_reason || '').trim();
  const queuedRuntime = queuePosition
    ? `资源队列第 ${queuePosition} 位${waitReason ? ` · ${waitReason}` : ''}`
    : (waitReason ? `等待资源 · ${waitReason}` : '');
  const attempt = Math.max(0, Math.trunc(Number(task.attempt || 0)));
  const recoveryRuntime = (
    attempt > 1
    && ['RUNNING', 'RESUMING', 'RETRYING', 'CANCEL_REQUESTED'].includes(status)
  ) ? `恢复执行 · 第 ${attempt} 次执行` : '';
  const runtimeText = ['QUEUED', 'WAITING_RESOURCE'].includes(status)
    ? queuedRuntime
    : recoveryRuntime;
  return {
    ...task,
    status,
    progress: progressPercent,
    progress_percent: progressPercent,
    statusText: STATUS_TEXT[status] || status,
    queuePosition,
    waitReason,
    attempt,
    runtimeText,
    samplingText,
    extractedFrames: Number(task.result?.extracted_frames ?? task.extracted_frames ?? 0),
  };
}
