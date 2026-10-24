import {isTaskActive, taskProgress} from './task-poller.js?v=422001';
import {canonicalTaskPhase, canonicalTaskStatus, exactTaskQueuePosition} from './task-runtime-truth.js';

const POLL_KEY = 'storage-import-scan-v61';
const OWNER_PAGE = '素材存储配置';
const POLL_DELAY = 1200;
const STAGE_LABELS = {
  MAPPING_LABELS:'正在转换标签',
  WRITING_ANNOTATIONS:'正在写入标注',
  INDEXING:'正在建立素材索引',
  FINALIZING:'正在整理结果',
  SCANNING:'正在扫描素材',
  REMOTE_MATERIAL_SCANNING:'正在扫描对象存储',
  REMOTE_MATERIAL_DOWNLOADING:'正在读取素材',
  REMOTE_MATERIAL_EXTRACTING:'正在安全解包素材',
  REMOTE_MATERIAL_REVIEWING:'正在检查素材内容',
  REMOTE_MATERIAL_PREPARING_UPLOAD:'正在整理审查结果',
  REMOTE_MATERIAL_CONFIRMING_REVIEW:'正在校验审查结果',
};

export function storageImportProgressText(task = {}) {
  const status = canonicalTaskStatus(task);
  const stage = (canonicalTaskPhase(task) || status || 'SCANNING').toUpperCase();
  const stageLabel = STAGE_LABELS[stage] || stage;
  const current = String(task.current_item || '').trim();
  const {percent} = taskProgress(task);
  const queuePosition = exactTaskQueuePosition(task);
  const priority = Number(task.priority || 0);
  const worker = String(task.worker_id || task.task_worker_id || '').trim();
  const waitReason = String(task.resource_wait_reason || '').trim();
  const isAgent = String(task.execution_mode || '').toLowerCase() === 'agent'
    || worker.startsWith('agent:');
  if (status === 'WAITING_RESOURCE') {
    return [isAgent ? '等待远程素材节点' : '等待资源', queuePosition ? `队列第 ${queuePosition} 位` : '', waitReason].filter(Boolean).join(' · ');
  }
  if (status === 'QUEUED') {
    return [isAgent ? '远程素材任务排队中' : '排队中', queuePosition ? `队列第 ${queuePosition} 位` : '', priority > 0 ? `优先级 ${priority}` : ''].filter(Boolean).join(' · ');
  }
  if (status === 'AWAITING_CONFIRMATION') return '扫描完成，等待确认建立素材索引';
  if (status === 'SUCCEEDED') return '素材导入已完成';
  if (status === 'FAILED' || status === 'CANCELLED' || status === 'BLOCKED_BY_ENVIRONMENT') {
    return String(task.error || status);
  }
  if (stage === 'FINALIZING') return percent > 0 ? `正在整理扫描结果 · ${percent.toFixed(0)}%` : '正在整理扫描结果';
  const parts = [stageLabel];
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
  if (window.StorageImportProgressRuntime?.build === 'storage-import-progress-422525') {
    return window.StorageImportProgressRuntime;
  }

  const registry = pollRegistry || window.PollRegistryRuntime;
  if (!registry?.startTimeout || !registry?.clear) return null;

  let trackedTaskId = '';
  let currentTask = null;
  let settle = null;
  let rejectCurrent = null;

  const state = () => getState?.() || {};

  function publishTaskCenter(task, pollOwner = 'storage-import-progress') {
    if (!task) return;
    const currentState = state();
    const taskId = String(task.task_id || task.id || trackedTaskId || '');
    const projectId = String(currentState.project?.id || '');
    if (!taskId || !projectId) return;
    const phase = (canonicalTaskPhase(task) || '').toUpperCase();
    const progress = taskProgress(task).percent || 0;
    window.UploadTaskCenterRuntime?.upsert?.({
      id: `storage-import:${taskId}`, kind: 'storage-import',
      title: ['MAPPING_LABELS','WRITING_ANNOTATIONS','INDEXING'].includes(phase) ? '标签转换 / 素材索引' : '素材导入',
      status: canonicalTaskStatus(task), progress, stage: STAGE_LABELS[phase] || phase || '素材导入',
      detail: String(task.current_item || task.error || ''),
      serverUrl: `/api/v62/projects/${encodeURIComponent(projectId)}/tasks/${encodeURIComponent(taskId)}`,
      pollOwner,
    });
  }

  function statusElement() {
    return document.getElementById('si61Status');
  }

  function patchLiveStatus(status, task) {
    const text = storageImportProgressText(task);
    const percent = Math.max(0, Math.min(100, Number(taskProgress(task).percent || 0)));
    if (!status?.querySelector || !document?.createElement) {
      status.textContent = text;
      return false;
    }
    let shell = status.querySelector('[data-storage-import-live-shell]');
    if (!shell) {
      status.innerHTML = '<div class="storage61-live-task" data-storage-import-live-shell><div class="storage61-task-head"><b data-storage-import-live-title></b><small data-storage-import-live-meta></small></div><div class="storage61-live-progress"><i><em data-storage-import-live-bar data-progress="0.00" style="transform:scaleX(0)"></em></i><span data-storage-import-live-percent>0%</span></div></div>';
      shell = status.querySelector('[data-storage-import-live-shell]');
    }
    const title = shell?.querySelector?.('[data-storage-import-live-title]');
    const meta = shell?.querySelector?.('[data-storage-import-live-meta]');
    const bar = shell?.querySelector?.('[data-storage-import-live-bar]');
    const label = shell?.querySelector?.('[data-storage-import-live-percent]');
    if (title) title.textContent = text;
    if (meta) meta.textContent = [String(task?.status || ''), String(task?.phase || task?.stage || '')].filter(Boolean).join(' · ');
    if (bar) {
      bar.dataset.progress = percent.toFixed(2);
      bar.style.transform = 'scaleX(' + (percent / 100).toFixed(4) + ')';
    }
    if (label) label.textContent = percent.toFixed(percent % 1 ? 1 : 0) + '%';
    return true;
  }

  function render(task) {
    if (task) {
      currentTask = {
        ...(currentTask || {}),
        ...task,
        mode: task.mode || currentTask?.mode,
        execution_mode: task.execution_mode || currentTask?.execution_mode,
      };
    }
    if (!currentTask) return;
    const status = statusElement();
    const active = isTaskActive(currentTask);
    if (status) {
      if (status.dataset) status.dataset.storageImportLive = active ? '1' : '0';
      if (active) patchLiveStatus(status, currentTask);
    }
    publishTaskCenter(currentTask);
    if (!active && typeof window.renderStorageImportTask61 === 'function') {
      window.renderStorageImportTask61(currentTask);
    } else if (!active && status) {
      status.textContent = storageImportProgressText(currentTask);
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

  function stop({handoff = true} = {}) {
    registry.clear(POLL_KEY);
    trackedTaskId = '';
    const resolve = settle;
    settle = null;
    rejectCurrent = null;
    const last = currentTask;
    currentTask = null;
    if (handoff && last && isTaskActive(last)) publishTaskCenter(last, '');
    resolve?.(last || null);
    return true;
  }

  function track(taskId, initialTask = null) {
    stop({handoff: false});
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
    build: 'storage-import-progress-422524',
    track,
    stop,
    current: () => currentTask,
  });
  window.StorageImportProgressRuntime = runtime;
  return runtime;
}
