import {exactTaskQueuePosition} from './task-runtime-truth.js';
import {isTaskActive, normalizeTaskStatus, taskProgress} from './task-poller.js';

const LABELS = {
  QUEUED: '排队中', WAITING_RESOURCE: '等待资源', RUNNING: 'AI标注中', CANCEL_REQUESTED: '正在取消',
  AWAITING_CONFIRMATION: '等待确认', PARTIAL_SUCCESS: '部分成功', SUCCEEDED: '已完成',
  CANCELLED: '已取消', FAILED: '失败', BLOCKED_BY_ENVIRONMENT: '环境不可用',
  BLOCKED_BY_HARDWARE: '硬件不可用'
};

export function annotationTaskView(task = {}) {
  const status = normalizeTaskStatus(task);
  const progress = taskProgress(task);
  const summary = task.summary || {};
  const total = progress.total || Number(summary.total) || 0;
  const completed = progress.completed || Math.max(0, Number(summary.total) || 0);
  const queuePosition = exactTaskQueuePosition(task) || 0;
  const waitReason = String(task.resource_wait_reason || '').trim();
  const workerId = String(task.worker_id || '').trim();
  const attempt = Math.max(0, Math.trunc(Number(task.attempt || 0)));
  const queuedRuntime = queuePosition
    ? `资源队列第 ${queuePosition} 位${waitReason ? ` · ${waitReason}` : ''}`
    : (waitReason ? `等待资源 · ${waitReason}` : '');
  const recoveryRuntime = (
    attempt > 1
    && ['RUNNING', 'CANCEL_REQUESTED'].includes(status)
  ) ? `恢复执行 · 第 ${attempt} 次执行${workerId ? ` · Worker ${workerId}` : ''}` : '';
  const runtimeText = ['QUEUED', 'WAITING_RESOURCE'].includes(status)
    ? queuedRuntime
    : (recoveryRuntime || (workerId ? `Worker ${workerId}` : ''));
  return {
    status,
    statusText: LABELS[status] || status || '未知',
    percent: progress.percent,
    completed,
    total,
    failed: progress.failed || Number(summary.failed) || 0,
    boxes: Number(summary.boxes) || 0,
    progressText: `${completed} / ${total}`,
    queuePosition,
    waitReason,
    workerId,
    attempt,
    runtimeText,
    active: isTaskActive(status),
    canCancel: isTaskActive(status),
    canReview: status === 'AWAITING_CONFIRMATION',
    canRetry: new Set(['PARTIAL_SUCCESS', 'SUCCEEDED', 'CANCELLED', 'FAILED', 'BLOCKED_BY_ENVIRONMENT', 'BLOCKED_BY_HARDWARE']).has(status),
    accepted: task.accepted,
    error: String(task.error || '')
  };
}

export function buildCandidateDecisions(items = [], {commit = true} = {}) {
  return {
    decisions: items
      .filter(item => item && item.status !== 'failed' && typeof item.accepted === 'boolean')
      .map(item => ({image_id: String(item.image_id), accepted: item.accepted})),
    reject_unmentioned: true,
    commit: Boolean(commit)
  };
}
