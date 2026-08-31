import {isTaskActive, normalizeTaskStatus, taskProgress} from './task-poller.js';

const LABELS = {
  QUEUED: '排队中', RUNNING: 'AI标注中', CANCEL_REQUESTED: '正在取消',
  AWAITING_CONFIRMATION: '等待确认', PARTIAL_SUCCESS: '部分成功', SUCCEEDED: '已完成',
  CANCELLED: '已取消', FAILED: '失败', BLOCKED_BY_ENVIRONMENT: '环境不可用',
  BLOCKED_BY_HARDWARE: '硬件不可用'
};

export function annotationTaskView(task = {}) {
  const status = normalizeTaskStatus(task.status);
  const progress = taskProgress(task);
  const summary = task.summary || {};
  const total = progress.total || Number(summary.total) || 0;
  const completed = progress.completed || Math.max(0, Number(summary.total) || 0);
  return {
    status,
    statusText: LABELS[status] || status || '未知',
    percent: progress.percent,
    completed,
    total,
    failed: progress.failed || Number(summary.failed) || 0,
    boxes: Number(summary.boxes) || 0,
    progressText: `${completed} / ${total}`,
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
