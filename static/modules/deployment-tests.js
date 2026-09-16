import {isTaskActive, normalizeTaskStatus, taskProgress} from './task-poller.js';
import {canonicalTaskPhase, exactTaskQueuePosition} from './task-runtime-truth.js';

function statusFallback(status) {
  return ({
    ACCEPTED: '已受理',
    QUEUED: '排队中',
    WAITING_RESOURCE: '等待资源',
    PREPARING: '准备中',
    RUNNING: '测试中',
    PAUSING: '暂停中',
    PAUSED: '已暂停',
    RESUMING: '恢复中',
    CANCEL_REQUESTED: '取消中',
    RETRYING: '重试中',
    SUCCEEDED: '已完成',
    FAILED: '失败',
    CANCELLED: '已取消',
    BLOCKED_BY_ENVIRONMENT: '环境阻塞',
    BLOCKED_BY_HARDWARE: '硬件阻塞',
  })[status] || status || '-';
}

export function deploymentTaskView(task = {}) {
  const status = normalizeTaskStatus(task);
  const progress = taskProgress(task);
  const queuePosition = exactTaskQueuePosition(task);
  const waitReason = String(task.resource_wait_reason || '').trim();
  const workerId = String(task.worker_id || task.task_worker_id || '').trim();
  const phase = canonicalTaskPhase(task);
  const currentItem = String(task.current_item || '').trim();
  const runtime = [];

  if ((status === 'QUEUED' || status === 'WAITING_RESOURCE') && queuePosition) {
    runtime.push(`资源队列第 ${queuePosition} 位`);
  }
  if (status === 'WAITING_RESOURCE' && waitReason) runtime.push(waitReason);
  if (status === 'RUNNING' && workerId) runtime.push(`Worker ${workerId}`);
  if (currentItem) runtime.push(currentItem);

  return {
    ...task,
    status,
    statusText: String(task.status_text || statusFallback(status)),
    percent: progress.percent,
    phase,
    runtimeText: runtime.join(' · '),
    active: isTaskActive(task),
  };
}
