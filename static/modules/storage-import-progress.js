import {isTaskActive, taskProgress} from './task-poller.js?v=422001';
import {canonicalTaskPhase, canonicalTaskStatus, exactTaskQueuePosition} from './task-runtime-truth.js';

const POLL_KEY = 'storage-import-scan-v61';
const OWNER_PAGE = '素材存储配置';
const POLL_DELAY = 1200;

export function storageImportProgressText(task = {}) {
  const status = canonicalTaskStatus(task);
  const stage = (canonicalTaskPhase(task) || status || 'SCANNING').toUpperCase();
  const current = String(task.current_item || '').trim();
  const {percent} = taskProgress(task);
  const queuePosition = exactTaskQueuePosition(task);
  const priority = Number(task.priority || 0);
  const worker = String(task.worker_id || task.task_worker_id || '').trim();
  const waitReason = String(task.resource_wait_reason || '').trim();
  if (status === 'WAITING_RESOURCE') {
    return ['等待资源', queuePosition ? `队列第 ${queuePosition} 位` : '', waitReason].filter(Boolean).join(' · ');
  }
  if (status === 'QUEUED') {
    return ['排队中', queuePosition ? `队列第 ${queuePosition} 位` : '', priority > 0 ? `优先级 ${priority}` : ''].filter(Boolean).join(' · ');
  }
  if (stage === 'FINALIZING') return percent > 0 ? `正在整理扫描结果 · ${percent.toFixed(0)}%` : '正在整理扫描结果';
  const parts = [stage];
  if (percent > 0) parts.push(`${percent.toFixed(0)}%`);
  if (current) parts.push(current);
  if (worker) parts.push(`执行节点 ${worker}`);
  if (parts.length === 1) parts.push('正在扫描对象');
  return parts.join(' · ');
}

async function responseJson(response) {
  if (response.ok) return response.json();
  const text = await response.text();
  let body = {};
  try { body = JSON.parse(text); } catch (_error) { body = {detail: text}; }
  throw new Error(body.message || body.detail || `HTTP ${response.status}`);
}

export function installStorageImportProgressRuntime({pollRegistry, getState} = {}) {
  if (typeof window === 'undefined' || typeof document === 'undefined') return null;
  if (window.StorageImportProgressRuntime?.build === 'storage-import-progress-422520') {
    return window.StorageImportProgressRuntime;
  }

  const registry = pollRegistry || window.PollRegistryRuntime;
  if (!registry?.startTimeout || !registry?.clear) return null;

  let trackedTaskId = '';
  let currentTask = null;
  let settle = null;
  let rejectCurrent = null;

  const state = () => getState?.() || {};

  function statusElement() {
    return document.getElementById('si61Status');
  }

  function render(task) {
    currentTask = task || currentTask;
    if (!currentTask) return;
    const status = statusElement();
    if (status) status.textContent = storageImportProgressText(currentTask);
    if (typeof window.renderStorageImportTask61 === 'function') {
      window.renderStorageImportTask61(currentTask);
    }
  }

  function finish(task) {
    const resolve = settle;
    settle = null;
    rejectCurrent = null;
    trackedTaskId = '';
    currentTask = task || currentTask;
    registry.clear(POLL_KEY);
    resolve?.(currentTask);
  }

  function fail(error) {
    const reject = rejectCurrent;
    settle = null;
    rejectCurrent = null;
    trackedTaskId = '';
    registry.clear(POLL_KEY);
    reject?.(error);
  }

  function schedule() {
    if (!trackedTaskId || !isTaskActive(currentTask)) return finish(currentTask);
    return registry.startTimeout(POLL_KEY, OWNER_PAGE, async () => {
      if (!trackedTaskId) return;
      const s = state();
      const projectId = String(s.project?.id || '');
      if (!projectId) return fail(new Error('当前项目不可用'));
      try {
        const task = await responseJson(await fetch(
          `/api/v62/projects/${encodeURIComponent(projectId)}/tasks/${encodeURIComponent(trackedTaskId)}`,
        ));
        if (!trackedTaskId) return;
        render(task);
        if (isTaskActive(task)) schedule();
        else finish(task);
      } catch (error) {
        fail(error);
      }
    }, POLL_DELAY);
  }

  function stop() {
    registry.clear(POLL_KEY);
    trackedTaskId = '';
    const resolve = settle;
    settle = null;
    rejectCurrent = null;
    const last = currentTask;
    currentTask = null;
    resolve?.(last || null);
    return true;
  }

  function track(taskId, initialTask = null) {
    stop();
    trackedTaskId = String(taskId || '').trim();
    currentTask = initialTask || null;
    if (!trackedTaskId) return Promise.resolve(null);
    render(currentTask || {task_id: trackedTaskId, status: 'QUEUED'});
    const promise = new Promise((resolve, reject) => {
      settle = resolve;
      rejectCurrent = reject;
    });
    if (isTaskActive(currentTask || 'QUEUED')) schedule();
    else finish(currentTask);
    return promise;
  }

  const runtime = Object.freeze({
    build: 'storage-import-progress-422520',
    track,
    stop,
    current: () => currentTask,
  });
  window.StorageImportProgressRuntime = runtime;
  return runtime;
}
