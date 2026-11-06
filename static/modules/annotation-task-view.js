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
  const failed = progress.failed || Number(summary.failed) || 0;
  const remaining = Math.max(0, Number(task.remaining_count ?? (total - completed)) || 0);
  const generated = Math.max(0, Number(summary.success || 0) + Number(summary.empty || 0));
  const reviewed = Math.max(0, Number(summary.accepted || 0) + Number(summary.rejected || 0));
  const stopped = new Set(['CANCELLED', 'FAILED', 'BLOCKED_BY_ENVIRONMENT', 'BLOCKED_BY_HARDWARE']).has(status);
  // The shared cancel endpoint stores accepted=false as a cancellation marker
  // for a queued task. This is not a human review decision.
  const unreviewed = (task.accepted == null || (status === 'CANCELLED' && task.accepted === false))
    && !Number(summary.gt_committed || 0);
  const interruption = String(task.generation_interruption_code || '').trim();
  const interruptionText = interruption ? {
    MODEL_SERVICE_UNREACHABLE:'模型服务连接中断',
    MODEL_REQUEST_TIMEOUT:'模型请求连续超时',
    MODEL_NOT_LOADED:'模型服务尚未加载模型',
    MODEL_PROTOCOL_REQUIRED:'模型服务协议配置不匹配',
  }[interruption] || `模型连续异常（${interruption}）` : '';
  const queuePosition = exactTaskQueuePosition(task) || 0;
  const waitReason = String(task.resource_wait_reason || '').trim();
  const workerId = String(task.worker_id || '').trim();
  const attempt = Math.max(0, Math.trunc(Number(task.attempt || 0)));
  const phase = String(task.phase || task.stage || '').toUpperCase();
  const queuedRuntime = queuePosition
    ? `资源队列第 ${queuePosition} 位${waitReason ? ` · ${waitReason}` : ''}`
    : (waitReason ? `等待资源 · ${waitReason}` : '');
  const recoveryRuntime = (
    attempt > 1
    && ['RUNNING', 'CANCEL_REQUESTED'].includes(status)
  ) ? `恢复执行 · 第 ${attempt} 次执行${workerId ? ` · Worker ${workerId}` : ''}` : '';
  const reviewRuntime = phase === 'APPLYING_REVIEW'
    ? String(task.current_item || '正在统一标签并写入正式标注')
    : '';
  const runtimeText = reviewRuntime || (['QUEUED', 'WAITING_RESOURCE'].includes(status)
    ? queuedRuntime
    : (recoveryRuntime || (workerId ? `Worker ${workerId}` : '')));
  const statusText = phase === 'REVIEW_QUEUED'
    ? '等待标注入库'
    : phase === 'APPLYING_REVIEW'
      ? '统一标签并入库'
      : (LABELS[status] || status || '未知');
  return {
    status,
    statusText,
    percent: progress.percent,
    completed,
    total,
    failed,
    remaining,
    generated,
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
    canRetry: unreviewed && (stopped || status === 'AWAITING_CONFIRMATION')
      && (failed > 0 || remaining > 0 || (stopped && !completed)),
    canRecoverReview: stopped && unreviewed && generated > 0,
    accepted: task.accepted,
    error: String(task.error || (interruptionText ? `${interruptionText}。已完成候选框已保存，可在检查服务后补跑剩余图片，或先审核已完成部分。` : ''))
  };
}

export function annotationStageStatistics(task = {}) {
  const source = task.stage_statistics;
  if (!source || typeof source !== 'object') return null;
  const keys = ['total', 'success', 'empty', 'failed', 'accepted', 'rejected', 'unreviewed', 'boxes', 'gt_committed'];
  if (keys.some(key => !Number.isSafeInteger(source[key]) || source[key] < 0)) return null;
  const generated = source.success + source.empty;
  if (source.total !== generated + source.failed
      || generated !== source.accepted + source.rejected + source.unreviewed
      || source.gt_committed > source.accepted) return null;
  return {
    generated,
    boxes: source.boxes,
    failed: source.failed,
    pending: source.unreviewed,
    reviewed: source.accepted + source.rejected,
    accepted: source.accepted,
    rejected: source.rejected,
    gtCommitted: source.gt_committed,
    total: source.total,
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
