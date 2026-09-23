import {canonicalTaskPhase, trainingDisplayStatus} from './task-runtime-truth.js';

const TRAINING_PAGE = '训练任务';
const REFRESH_DEDUP_WINDOW_MS = 120;
const PAGE_ENTRY_REUSE_MS = 5000;

const STAGE_LABELS = Object.freeze({
  queued: '排队等待',
  resource_waiting: '等待训练资源',
  device_admission: '验证训练设备',
  preparing_materials: '校验训练素材',
  materializing: '准备训练数据',
  starting_trainer: '启动训练进程',
  trainer_startup: '初始化训练环境',
  training: '训练中',
  paused: '已暂停',
  cancelling: '正在停止训练',
  cleaning_training_process: '释放训练进程资源',
  finalizing: '校验训练产物',
  final_validation: '独立验证最佳模型',
  recovering_checkpoint: '恢复并验证 Checkpoint',
  process_cleanup_blocked: '等待训练进程安全退出',
  finalizing_commit: '归档训练结果',
  committed: '训练完成',
  blocked_by_environment: '训练环境不可用',
  blocked_by_hardware: '训练硬件不可用',
  failed: '训练失败',
  cancelled: '已取消',
});

function rowsFrom(body) {
  if (Array.isArray(body)) return body;
  return Array.isArray(body?.items) ? body.items : [];
}

export function formatTrainingDuration(value) {
  const total = Math.max(0, Number(value || 0));
  if (!Number.isFinite(total) || total <= 0) return '-';
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = Math.floor(total % 60);
  if (hours) return `${hours}h ${minutes}m`;
  if (minutes) return `${minutes}m ${seconds}s`;
  return `${seconds}s`;
}

function finiteNumber(value) {
  if (value === null || value === undefined || value === '') return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function metricValue(values, aliases) {
  if (!values || typeof values !== 'object') return null;
  const normalized = new Map(Object.entries(values).map(([key, value]) => [String(key).toLowerCase().replace(/\s+/g, ''), value]));
  for (const alias of aliases) {
    const value = finiteNumber(normalized.get(String(alias).toLowerCase().replace(/\s+/g, '')));
    if (value !== null) return value;
  }
  return null;
}

function metricText(value, digits = 3) {
  return value === null ? '' : Number(value).toFixed(digits);
}

export function trainingProgressView(job = {}) {
  const progress = job.training_progress && typeof job.training_progress === 'object' ? job.training_progress : {};
  const epoch = finiteNumber(progress.epoch) ?? finiteNumber(job.current_epoch) ?? 0;
  const totalEpochs = finiteNumber(progress.total_epochs) ?? finiteNumber(job.total_epochs) ?? finiteNumber(job.epochs);
  const currentBatch = finiteNumber(progress.current_batch) ?? finiteNumber(job.current_batch);
  const totalBatches = finiteNumber(progress.total_batches) ?? finiteNumber(job.total_batches);
  const elapsedSeconds = finiteNumber(progress.elapsed_seconds) ?? finiteNumber(job.elapsed_seconds);
  const etaSeconds = finiteNumber(progress.eta_seconds) ?? finiteNumber(job.eta_seconds);
  const throughput = finiteNumber(progress.images_per_second);
  const losses = progress.losses || {};
  const metrics = progress.metrics || {};
  const learningRates = progress.learning_rates || {};
  const boxLoss = metricValue(losses, ['box_loss', 'train/box_loss']);
  const clsLoss = metricValue(losses, ['cls_loss', 'train/cls_loss']);
  const dflLoss = metricValue(losses, ['dfl_loss', 'train/dfl_loss']);
  const map50 = metricValue(metrics, ['metrics/map50(b)', 'metrics/map50', 'map50']);
  const map5095 = metricValue(metrics, ['metrics/map50-95(b)', 'metrics/map50-95', 'map50-95', 'map']);
  const precision = metricValue(metrics, ['metrics/precision(b)', 'precision']);
  const recall = metricValue(metrics, ['metrics/recall(b)', 'recall']);
  const primaryLr = Object.values(learningRates).map(finiteNumber).find(value => value !== null) ?? null;
  const parts = [];
  if (precision !== null) parts.push(`Precision ${metricText(precision)}`);
  if (recall !== null) parts.push(`Recall ${metricText(recall)}`);
  if (map50 !== null) parts.push(`mAP50 ${metricText(map50)}`);
  if (map5095 !== null) parts.push(`mAP50-95 ${metricText(map5095)}`);
  if (boxLoss !== null) parts.push(`box loss ${metricText(boxLoss, 4)}`);
  if (clsLoss !== null) parts.push(`cls loss ${metricText(clsLoss, 4)}`);
  if (dflLoss !== null) parts.push(`dfl loss ${metricText(dflLoss, 4)}`);
  if (throughput !== null) parts.push(`${metricText(throughput, 1)} img/s`);
  if (primaryLr !== null) parts.push(`LR ${Number(primaryLr).toPrecision(3)}`);
  return {epoch, totalEpochs, currentBatch, totalBatches, elapsedSeconds, etaSeconds, metricLine: parts.join(' · ')};
}

function statusText(status) {
  return ({
    queued: '排队中', waiting: '等待资源', pending: '等待中', starting: '启动中',
    running: '训练中', pausing: '暂停中', paused: '已暂停', resuming: '恢复中',
    stopping: '停止中', cancel_requested: '取消中',
    done: '已完成', finished: '已完成', completed: '已完成', succeeded: '已完成', success: '已完成',
    failed: '失败', stopped: '已停止', cancelled: '已取消', canceled: '已取消',
  })[status] || status || '-';
}

export function trainingBatchActionEligible(job, action) {
  const status = trainingDisplayStatus(job);
  if (action === 'pause') return status === 'running';
  if (action === 'resume') return status === 'paused';
  if (action === 'stop') {
    return ['queued', 'waiting', 'pending', 'starting', 'running', 'pausing', 'paused', 'resuming'].includes(status);
  }
  if (action === 'delete') {
    return [
      'done', 'finished', 'completed', 'succeeded', 'success',
      'failed', 'stopped', 'cancelled', 'canceled',
      'blocked_by_environment', 'blocked_by_hardware',
    ].includes(status);
  }
  return false;
}

export function trainingStageView(job = {}) {
  const status = trainingDisplayStatus(job);
  const stage = canonicalTaskPhase(job);
  const currentItem = String(job?.current_item || '').trim();
  const message = String(job?.message || '').trim();
  let label = STAGE_LABELS[stage] || '';
  let detail = currentItem;

  if (status === 'waiting') label = '等待训练资源';
  else if (status === 'queued' && !label) label = '排队等待';
  else if (status === 'paused') label = '已暂停';

  if (stage === 'trainer_startup') {
    const actualDevice = String(job?.actual_device || '').trim();
    const resolved = job?.resolved_resources && typeof job.resolved_resources === 'object';
    if (!actualDevice) label = '验证训练设备';
    else if (!resolved) label = '加载训练模型';
    else label = '初始化训练器与数据加载器';
    if (message && !/^训练中\b/.test(message)) detail = message;
  }

  if (!label) {
    if (status === 'running') label = '运行中';
    else if (status === 'pending') label = '等待中';
    else label = statusText(status);
  }

  if (detail === label) detail = '';
  return {stage, label, detail};
}

async function responseError(response, fallback = '操作失败') {
  if (response?.ok) return null;
  const raw = await response?.text?.() || '';
  let body = {};
  try { body = JSON.parse(raw); } catch (_) { body = {detail: raw}; }
  return new Error(String(body.message || body.detail || `${fallback}（HTTP ${response?.status || '-'}）`));
}

async function jsonResponse(response) {
  const error = await responseError(response, '刷新失败');
  if (error) throw error;
  return response.json();
}

export function installTrainingTaskRuntime({getState, projectId, notify, fetchImpl, recoveryRuntime} = {}) {
  if (typeof window === 'undefined') return null;
  if (window.__trainingTaskRuntimeInstalled) return window.TrainingTaskRuntime;

  const state = () => getState?.() || {};
  const nativeFetch = fetchImpl
    || window.fetch?.__pageRequestScopeOriginal
    || (typeof window.fetch === 'function' ? window.fetch.bind(window) : null);
  if (typeof nativeFetch !== 'function') return null;

  const previous = {
    refreshJobsOnly: window.refreshJobsOnly,
    refreshTrainPage428: window.refreshTrainPage428,
    refreshTrain423: window.refreshTrain423,
    promoteTrain428: window.promoteTrain428,
    pauseTrain428: window.pauseTrain428,
    resumeTrain428: window.resumeTrain428,
    stopTrain428: window.stopTrain428,
    deleteTrain428: window.deleteTrain428,
  };
  const mutationLocks = new Set();
  let inflight = null;
  let destroyed = false;
  let lastRefreshAt = 0;
  let lastRefreshSource = '';
  let viewAdapter = null;

  function isCurrent(startPage, startEpoch) {
    const s = state();
    return !destroyed
      && String(s.page || '') === startPage
      && Number(s.__navigationEpoch || 0) === startEpoch;
  }

  function renderTrainingView() {
    return typeof viewAdapter?.render === 'function' ? viewAdapter.render() : false;
  }

  function finalizeViewRefresh(result, options = {}) {
    if (result?.stale) return result;
    if (options.render !== false) renderTrainingView();
    viewAdapter?.afterRefresh?.(result, options);
    return result;
  }

  function setViewAdapter(adapter) {
    const next = adapter && typeof adapter === 'object' ? adapter : null;
    viewAdapter = next;
    return () => {
      if (viewAdapter === next) viewAdapter = null;
    };
  }

  function acceptCreatedTask(task, {algorithmId = '', framework = '', queuePriority = 50} = {}) {
    const taskId = String(task?.task_id || '').trim();
    if (!taskId) throw new Error('训练任务响应缺少 task_id');
    const status = String(task?.status || task?.persisted_status || 'QUEUED').trim().toLowerCase();
    const row = {
      ...task,
      id: taskId,
      task_id: taskId,
      status,
      task_status: String(task?.status || '').trim().toUpperCase(),
      asset_algorithm_id: String(algorithmId || task?.asset_algorithm_id || ''),
      algorithm_asset_id: String(algorithmId || task?.algorithm_asset_id || ''),
      framework: String(framework || task?.framework || ''),
      queue_priority: Number(task?.priority ?? queuePriority ?? 50),
      priority_scheme: 'lower_number_first',
      created_at: task?.created_at || new Date().toISOString(),
      updated_at: task?.updated_at || task?.created_at || new Date().toISOString(),
    };
    const current = Array.isArray(state().jobs) ? state().jobs : [];
    state().jobs = [row, ...current.filter(item => String(item?.id || item?.task_id || '') !== taskId)];
    if (String(state().page || '') === TRAINING_PAGE) renderTrainingView();
    return row;
  }

  async function refresh({render = true, force = false, source = 'direct'} = {}) {
    if (destroyed) throw new Error('训练任务模块已销毁');
    if (inflight) {
      const pending = inflight;
      if (!force) return pending;
      try { await pending; } catch (_) {}
      if (inflight === pending) inflight = null;
    }
    const pid = projectId?.();
    if (!pid) throw new Error('当前项目不可用，请刷新页面后重试');

    const startPage = String(state().page || '');
    const startEpoch = Number(state().__navigationEpoch || 0);
    const refreshOptions = {render, force, source};
    const age = Date.now() - lastRefreshAt;
    const crossSourceDuplicate = (source === 'manual' && lastRefreshSource === 'poll')
      || (source === 'poll' && lastRefreshSource === 'manual');
    const pageEntryReuse = source === 'page-owner' && age <= PAGE_ENTRY_REUSE_MS;
    const interactionReuse = crossSourceDuplicate && age <= REFRESH_DEDUP_WINDOW_MS;
    if (!force
        && startPage === TRAINING_PAGE
        && lastRefreshAt > 0
        && age >= 0
        && (pageEntryReuse || interactionReuse)) {
      return finalizeViewRefresh(
        {stale: false, jobs: state().jobs || [], reused: true},
        refreshOptions,
      );
    }
    const encoded = encodeURIComponent(pid);

    const request = (async () => {
      const response = await nativeFetch(`/api/projects/${encoded}/jobs`, {
        headers: {'Accept': 'application/json'},
      });
      const body = await jsonResponse(response);
      let jobs = rowsFrom(body);
      if (recoveryRuntime?.hydrateJobs) jobs = await recoveryRuntime.hydrateJobs(jobs);
      if (!isCurrent(startPage, startEpoch) || startPage !== TRAINING_PAGE) {
        return {stale: true, jobs: state().jobs || []};
      }
      state().jobs = jobs;
      lastRefreshAt = Date.now();
      lastRefreshSource = String(source || 'direct');
      return finalizeViewRefresh({stale: false, jobs}, refreshOptions);
    })();
    inflight = request;

    try {
      return await request;
    } finally {
      if (inflight === request) inflight = null;
    }
  }

  async function refreshAfterMutation() {
    if (inflight) {
      try { await inflight; } catch (_) {}
    }
    if (String(state().page || '') !== TRAINING_PAGE) return {stale: true, jobs: state().jobs || []};
    return runtime.refresh({render: true, force: true, source: 'mutation'});
  }

  async function mutate(key, path, {method = 'POST', successMessage = '操作成功'} = {}) {
    if (mutationLocks.has(key)) return false;
    mutationLocks.add(key);
    try {
      const response = await nativeFetch(path, {method});
      const error = await responseError(response);
      if (error) throw error;
      let refreshError = null;
      try { await refreshAfterMutation(); } catch (errorAfterMutation) { refreshError = errorAfterMutation; }
      notify?.(refreshError ? `${successMessage}，但列表刷新失败：${refreshError.message || refreshError}` : successMessage);
      return true;
    } catch (error) {
      notify?.(error?.message || error);
      return false;
    } finally {
      mutationLocks.delete(key);
    }
  }

  async function batchAction(action, ids = []) {
    const actionName = ({pause: '暂停', resume: '继续', stop: '停止', delete: '删除'})[action];
    if (!actionName) throw new Error('不支持的批量训练操作');
    const uniqueIds = [...new Set((ids || []).map(String).filter(Boolean))];
    const jobs = Array.isArray(state().jobs) ? state().jobs : [];
    const eligible = uniqueIds
      .map(id => jobs.find(job => String(job?.id || job?.task_id || '') === id))
      .filter(job => job && trainingBatchActionEligible(job, action));
    if (!eligible.length) {
      notify?.(`所选任务当前没有可${actionName}的项目`);
      return {ok: false, action, attempted: 0, succeeded: 0, failed: 0, skipped: uniqueIds.length};
    }

    if (action === 'stop' && typeof window.confirm === 'function') {
      const confirmed = window.confirm(`确认停止选中的 ${eligible.length} 个训练任务？`);
      if (!confirmed) return {ok: false, cancelled: true, action, attempted: eligible.length, succeeded: 0, failed: 0, skipped: uniqueIds.length - eligible.length};
    }
    if (action === 'delete' && typeof window.confirm === 'function') {
      const confirmed = window.confirm(`确认永久删除选中的 ${eligible.length} 条已结束训练记录？\n\n只删除任务记录和任务运行缓存；已经生成的算法版本与模型成果不会删除。运行中、排队中、暂停中的任务不会被删除。`);
      if (!confirmed) return {ok: false, cancelled: true, action, attempted: eligible.length, succeeded: 0, failed: 0, skipped: uniqueIds.length - eligible.length};
    }

    const pid = encodeURIComponent(projectId?.() || '');
    const lockKey = `batch:${action}`;
    if (mutationLocks.has(lockKey)) return {ok: false, busy: true, action, attempted: eligible.length, succeeded: 0, failed: 0, skipped: uniqueIds.length - eligible.length};
    mutationLocks.add(lockKey);
    const failures = [];
    let succeeded = 0;
    let backendSkipped = 0;
    try {
      if (action === 'delete') {
        const response = await nativeFetch(
          `/api/v48/projects/${pid}/jobs/batch-delete`,
          {
            method: 'POST',
            headers: {'Accept': 'application/json', 'Content-Type': 'application/json'},
            body: JSON.stringify({
              job_ids: eligible.map(job => String(job?.id || job?.task_id || '')).filter(Boolean),
            }),
          },
        );
        const error = await responseError(response, '批量删除训练记录失败');
        if (error) throw error;
        const body = await response.json();
        succeeded = Math.max(0, Number(body?.deleted || 0));
        backendSkipped = Math.max(0, Number(body?.skipped_active || 0)) + Math.max(0, Number(body?.missing || 0));
        for (const item of body?.failures || []) {
          failures.push({
            id: String(item?.job_id || ''),
            message: String(item?.message || '删除失败'),
          });
        }
      } else {
        for (const job of eligible) {
          const id = String(job?.id || job?.task_id || '');
          try {
            const response = await nativeFetch(
              `/api/v48/projects/${pid}/jobs/${encodeURIComponent(id)}/${action}`,
              {method: 'POST'},
            );
            const error = await responseError(response, `${actionName}训练失败`);
            if (error) throw error;
            succeeded += 1;
          } catch (error) {
            failures.push({id, message: String(error?.message || error)});
          }
        }
      }

      let refreshError = null;
      try { await refreshAfterMutation(); } catch (errorAfterMutation) { refreshError = errorAfterMutation; }
      const skipped = uniqueIds.length - eligible.length + backendSkipped;
      const summary = [
        `批量${actionName}完成：成功 ${succeeded}`,
        failures.length ? `失败 ${failures.length}` : '',
        skipped ? `跳过 ${skipped}` : '',
      ].filter(Boolean).join(' · ');
      notify?.(refreshError ? `${summary}，但列表刷新失败：${refreshError.message || refreshError}` : summary);
      return {
        ok: failures.length === 0 && !refreshError,
        action,
        attempted: eligible.length,
        succeeded,
        failed: failures.length,
        skipped,
        failures,
        refreshError: refreshError ? String(refreshError?.message || refreshError) : '',
      };
    } catch (error) {
      notify?.(error?.message || error);
      return {
        ok: false,
        action,
        attempted: eligible.length,
        succeeded,
        failed: failures.length || 1,
        skipped: uniqueIds.length - eligible.length + backendSkipped,
        failures: failures.length ? failures : [{id: '', message: String(error?.message || error)}],
      };
    } finally {
      mutationLocks.delete(lockKey);
    }
  }

  const focusedRefresh = () => runtime.refresh({render: true, source: 'poll'});
  const manualRefresh = () => runtime.refresh({render: true, force: true, source: 'manual'});
  focusedRefresh.__trainingTaskRuntime = true;
  manualRefresh.__trainingTaskRuntime = true;
  window.refreshJobsOnly = focusedRefresh;
  window.refreshTrainPage428 = manualRefresh;
  window.refreshTrain423 = manualRefresh;

  window.promoteTrain428 = id => mutate(
    `promote:${id}`,
    `/api/v48/projects/${encodeURIComponent(projectId?.() || '')}/jobs/${encodeURIComponent(id)}/promote`,
    {successMessage: '任务已插到当前资源队列最前'},
  );
  window.pauseTrain428 = id => mutate(
    `pause:${id}`,
    `/api/v48/projects/${encodeURIComponent(projectId?.() || '')}/jobs/${encodeURIComponent(id)}/pause`,
    {successMessage: '训练已暂停'},
  );
  window.resumeTrain428 = id => mutate(
    `resume:${id}`,
    `/api/v48/projects/${encodeURIComponent(projectId?.() || '')}/jobs/${encodeURIComponent(id)}/resume`,
    {successMessage: '训练已继续'},
  );
  window.stopTrain428 = async id => {
    if (typeof window.confirm === 'function' && !window.confirm('确认停止这个训练任务？排队任务会直接取消；已开始任务仅在存在可校验训练成果时归档算法版本。')) return false;
    return mutate(
      `stop:${id}`,
      `/api/v48/projects/${encodeURIComponent(projectId?.() || '')}/jobs/${encodeURIComponent(id)}/stop`,
      {successMessage: '训练已停止'},
    );
  };
  window.deleteTrain428 = async id => {
    if (typeof window.confirm === 'function' && !window.confirm('确认删除这条训练任务记录？已经生成的算法版本不会删除。')) return false;
    const key = `delete:${id}`;
    if (mutationLocks.has(key)) return false;
    mutationLocks.add(key);
    try {
      const pid = encodeURIComponent(projectId?.() || '');
      const encodedId = encodeURIComponent(id);
      const job = (state().jobs || []).find(item => String(item.id) === String(id));
      if (job && ['running', 'paused', 'queued', 'waiting'].includes(trainingDisplayStatus(job))) {
        const stopResponse = await nativeFetch(`/api/v48/projects/${pid}/jobs/${encodedId}/stop`, {method: 'POST'});
        const stopError = await responseError(stopResponse, '停止训练失败');
        if (stopError) throw stopError;
      }
      const deleteResponse = await nativeFetch(`/api/v12/projects/${pid}/jobs/${encodedId}`, {method: 'DELETE'});
      const deleteError = await responseError(deleteResponse, '删除任务失败');
      if (deleteError) throw deleteError;
      let refreshError = null;
      try { await refreshAfterMutation(); } catch (errorAfterMutation) { refreshError = errorAfterMutation; }
      notify?.(refreshError ? `任务记录已删除，但列表刷新失败：${refreshError.message || refreshError}` : '任务记录已删除');
      return true;
    } catch (error) {
      notify?.(error?.message || error);
      return false;
    } finally {
      mutationLocks.delete(key);
    }
  };

  for (const name of ['promoteTrain428', 'pauseTrain428', 'resumeTrain428', 'stopTrain428', 'deleteTrain428']) {
    if (typeof window[name] === 'function') window[name].__trainingTaskRuntime = true;
  }

  const runtime = {
    build: 'training-task-runtime-422508',
    refresh,
    acceptCreatedTask,
    batchAction,
    setViewAdapter,
    state() {
      return {
        inflight: Boolean(inflight),
        lastRefreshAt,
        lastRefreshSource,
        mutations: mutationLocks.size,
        viewAdapter: Boolean(viewAdapter),
      };
    },
    destroy() {
      destroyed = true;
      viewAdapter = null;
      for (const [name, fn] of Object.entries(previous)) {
        if (fn === undefined) delete window[name];
        else window[name] = fn;
      }
      if (window.TrainingTaskRuntime === runtime) window.TrainingTaskRuntime = null;
      window.__trainingTaskRuntimeInstalled = false;
    },
  };

  window.TrainingTaskRuntime = runtime;
  window.__trainingTaskRuntimeInstalled = true;
  return runtime;
}
