import {isTaskActive, normalizeTaskStatus, taskProgress} from './task-poller.js';

function statusFallback(status) {
  return ({
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

function positiveInteger(value) {
  const number = Number(value);
  return Number.isInteger(number) && number > 0 ? number : null;
}

export function deploymentTaskView(task = {}) {
  const status = normalizeTaskStatus(task.status);
  const progress = taskProgress(task);
  const queuePosition = positiveInteger(task.resource_queue_position);
  const waitReason = String(task.resource_wait_reason || '').trim();
  const workerId = String(task.worker_id || '').trim();
  const phase = String(task.phase ?? task.stage ?? '').trim();
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
    active: isTaskActive(status),
  };
}
