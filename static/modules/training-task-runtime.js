const TRAINING_PAGE = '训练任务';
const ACTIVE_STATUSES = new Set(['queued', 'running', 'waiting', 'pending', 'paused']);
const DONE_STATUSES = new Set(['done', 'finished', 'completed', 'failed', 'stopped', 'cancelled', 'canceled']);
const REFRESH_DEDUP_WINDOW_MS = 120;

function rowsFrom(body) {
  if (Array.isArray(body)) return body;
  return Array.isArray(body?.items) ? body.items : [];
}

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[char]);
}

function duration(value) {
  const total = Math.max(0, Number(value || 0));
  if (!Number.isFinite(total) || total <= 0) return '-';
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = Math.floor(total % 60);
  if (hours) return `${hours}h ${minutes}m`;
  if (minutes) return `${minutes}m ${seconds}s`;
  return `${seconds}s`;
}

function dateText(value) {
  if (!value) return '-';
  return String(value).replace('T', ' ').replace('Z', '').slice(0, 19);
}

function statusText(status) {
  return ({
    queued: '排队中', running: '训练中', waiting: '等待中', pending: '等待中', paused: '已暂停',
    done: '已完成', finished: '已完成', completed: '已完成', failed: '失败', stopped: '已停止',
    cancelled: '已取消', canceled: '已取消',
  })[status] || status || '-';
}

function statusClass(status) {
  if (['done', 'finished', 'completed'].includes(status)) return 'ok';
  if (['failed', 'stopped', 'cancelled', 'canceled'].includes(status)) return 'err';
  if (['running', 'queued', 'waiting', 'pending', 'paused'].includes(status)) return 'warn';
  return '';
}

function resourceName(job) {
  return job?.execution_resource?.name
    || job?.resource_name
    || job?.server_name
    || job?.resource_key
    || '-';
}

function priorityValue(job) {
  const raw = Number(job?.queue_priority ?? 50);
  if (job?.priority_scheme === 'lower_number_first') return Math.max(1, Math.min(999, Number.isFinite(raw) ? raw : 50));
  const legacy = {100: 1, 80: 20, 50: 50};
  return legacy[raw] ?? Math.max(1, Math.min(999, 101 - (Number.isFinite(raw) ? raw : 50)));
}

function actions(job) {
  const id = esc(job.id);
  if (job.status === 'queued') return `<button class="btn mini" onclick="promoteTrain428('${id}')">插队</button><button class="btn mini danger" onclick="stopTrain428('${id}')">停止</button><button class="btn mini danger" onclick="deleteTrain428('${id}')">删除</button>`;
  if (job.status === 'running') return `<button class="btn mini" onclick="showTrainLog423('${id}')">日志</button><button class="btn mini" onclick="pauseTrain428('${id}')">暂停</button><button class="btn mini danger" onclick="stopTrain428('${id}')">停止</button><button class="btn mini danger" onclick="deleteTrain428('${id}')">删除</button>`;
  if (job.status === 'paused') return `<button class="btn mini" onclick="showTrainLog423('${id}')">日志</button><button class="btn mini primary" onclick="resumeTrain428('${id}')">继续</button><button class="btn mini danger" onclick="stopTrain428('${id}')">停止</button><button class="btn mini danger" onclick="deleteTrain428('${id}')">删除</button>`;
  return `<button class="btn mini" onclick="showTrainLog423('${id}')">日志</button>${job.auto_version_id ? `<button class="btn mini primary" onclick="trainingReport425('${id}')">训练报告</button>` : ''}<button class="btn mini danger" onclick="deleteTrain428('${id}')">删除</button>`;
}

export function trainingTaskRow(job) {
  const percent = Math.max(0, Math.min(100, Number(job?.progress_percent || 0)));
  const totalEpochs = job?.total_epochs || job?.epochs || '-';
  return `<tr data-job-id="${esc(job.id)}"><td><div class="train428-taskname"><b>${esc(job.asset_algorithm_name || job.algorithm_name || job.id)}</b><span>${esc(job.id)}</span>${job.auto_version_name ? `<em>版本 ${esc(job.auto_version_name)}</em>` : ''}</div></td><td><span class="pill ${statusClass(job.status)}">${esc(statusText(job.status))}</span><small class="queuepriority428">优先级 ${priorityValue(job)}</small></td><td><div class="train428-resource"><b>${esc(resourceName(job))}</b><span>${esc(job.framework === 'paddle' ? 'PaddleDetection' : 'Ultralytics / YOLO')}</span></div></td><td><div class="progress424"><i style="width:${percent}%"></i></div><span class="train428-progress-txt">${job.current_epoch || 0}/${esc(totalEpochs)} · ${percent.toFixed(0)}%</span></td><td>${esc(duration(job.elapsed_seconds))}</td><td>${esc(duration(job.eta_seconds))}</td><td>${esc(dateText(job.started_at || job.created_at))}</td><td><div class="row wrap">${actions(job)}</div></td></tr>`;
}

export function visibleTrainingJobs(jobs, tab = 'active') {
  const rows = Array.isArray(jobs) ? jobs : [];
  const filtered = tab === 'history'
    ? rows.filter(job => DONE_STATUSES.has(job.status) || !ACTIVE_STATUSES.has(job.status))
    : rows.filter(job => ACTIVE_STATUSES.has(job.status));
  const rank = status => status === 'running' ? 0 : status === 'paused' ? 1 : status === 'queued' ? 2 : 3;
  return [...filtered].sort((a, b) => {
    const ar = rank(a.status), br = rank(b.status);
    if (ar !== br) return ar - br;
    if (ar === 2) return priorityValue(a) - priorityValue(b);
    return String(b.started_at || b.created_at || '').localeCompare(String(a.started_at || a.created_at || ''));
  });
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

export function installTrainingTaskRuntime({getState, projectId, notify, fetchImpl} = {}) {
  if (typeof window === 'undefined') return null;
  if (window.__trainingTaskRuntimeInstalled) return window.TrainingTaskRuntime;

  const doc = typeof document !== 'undefined' ? document : null;
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

  function isCurrent(startPage, startEpoch) {
    const s = state();
    return !destroyed
      && String(s.page || '') === startPage
      && Number(s.__navigationEpoch || 0) === startEpoch;
  }

  function patchFinalTrainingTable() {
    if (!doc || String(state().page || '') !== TRAINING_PAGE) return false;
    const root = doc.querySelector?.('.train428-page');
    const body = root?.querySelector?.('.train428-table tbody');
    if (!root || !body) {
      if (typeof window.updateTrainingJobTable === 'function') {
        window.updateTrainingJobTable();
        return true;
      }
      return false;
    }
    const jobs = state().jobs || [];
    const active = jobs.filter(job => ACTIVE_STATUSES.has(job.status));
    const history = jobs.filter(job => DONE_STATUSES.has(job.status) || !ACTIVE_STATUSES.has(job.status));
    const buttons = root.querySelectorAll?.('.train428-tabs button') || [];
    const activeCount = buttons[0]?.querySelector?.('span');
    const historyCount = buttons[1]?.querySelector?.('span');
    if (activeCount) activeCount.textContent = String(active.length);
    if (historyCount) historyCount.textContent = String(history.length);
    const visible = visibleTrainingJobs(jobs, state().train428Tab || 'active');
    body.innerHTML = visible.map(trainingTaskRow).join('') || '<tr><td colspan="8" class="empty-row">暂无记录</td></tr>';
    return true;
  }

  async function refresh({render = true, force = false, source = 'direct'} = {}) {
    if (destroyed) throw new Error('训练任务模块已销毁');
    if (inflight) return inflight;
    const pid = projectId?.();
    if (!pid) throw new Error('当前项目不可用，请刷新页面后重试');

    const startPage = String(state().page || '');
    const startEpoch = Number(state().__navigationEpoch || 0);
    const age = Date.now() - lastRefreshAt;
    const crossSourceDuplicate = (source === 'manual' && lastRefreshSource === 'poll')
      || (source === 'poll' && lastRefreshSource === 'manual');
    if (!force
        && startPage === TRAINING_PAGE
        && lastRefreshAt > 0
        && age >= 0
        && age <= REFRESH_DEDUP_WINDOW_MS
        && crossSourceDuplicate) {
      if (render) patchFinalTrainingTable();
      return {stale: false, jobs: state().jobs || [], reused: true};
    }
    const encoded = encodeURIComponent(pid);

    inflight = (async () => {
      const response = await nativeFetch(`/api/projects/${encoded}/jobs`, {
        headers: {'Accept': 'application/json'},
      });
      const body = await jsonResponse(response);
      if (!isCurrent(startPage, startEpoch) || startPage !== TRAINING_PAGE) {
        return {stale: true, jobs: state().jobs || []};
      }
      const jobs = rowsFrom(body);
      state().jobs = jobs;
      lastRefreshAt = Date.now();
      lastRefreshSource = String(source || 'direct');
      if (render) patchFinalTrainingTable();
      return {stale: false, jobs};
    })();

    try {
      return await inflight;
    } finally {
      inflight = null;
    }
  }

  async function refreshAfterMutation() {
    if (inflight) {
      try { await inflight; } catch (_) {}
    }
    if (String(state().page || '') !== TRAINING_PAGE) return {stale: true, jobs: state().jobs || []};
    return refresh({render: true, force: true, source: 'mutation'});
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

  const focusedRefresh = () => refresh({render: true, source: 'poll'});
  focusedRefresh.__trainingTaskRuntime = true;
  window.refreshJobsOnly = focusedRefresh;
  window.refreshTrainPage428 = focusedRefresh;
  window.refreshTrain423 = focusedRefresh;

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
    if (typeof window.confirm === 'function' && !window.confirm('确认停止这个训练任务？已经开始过的任务会按当前训练结束时间自动形成一个算法版本。')) return false;
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
      if (job && ['running', 'paused', 'queued'].includes(job.status)) {
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

  function isOwnedRefreshButton(button) {
    if (!button || String(state().page || '') !== TRAINING_PAGE) return false;
    if (button.id === 'refreshBtn') return true;
    if (!button.closest?.('#view')) return false;
    const label = String(button.textContent || '').trim();
    return label === '刷新状态' || label === '完整刷新' || label === '刷新';
  }

  const onClickCapture = event => {
    const button = event?.target?.closest?.('button');
    if (!isOwnedRefreshButton(button)) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    if (button.disabled || inflight) return;
    button.disabled = true;
    void refresh({render: true, source: 'manual'}).then(
      result => { if (!result?.stale) notify?.('训练任务已刷新'); },
      error => notify?.(error?.message || error),
    ).finally(() => {
      if (button?.isConnected !== false) button.disabled = false;
      window.PollRegistryRuntime?.replaceTrainingJobTimer?.();
    });
  };
  doc?.addEventListener?.('click', onClickCapture, true);

  const runtime = {
    build: 'training-task-runtime-422503',
    refresh,
    patch: patchFinalTrainingTable,
    state() {
      return {inflight: Boolean(inflight), lastRefreshAt, lastRefreshSource, mutations: mutationLocks.size};
    },
    destroy() {
      destroyed = true;
      doc?.removeEventListener?.('click', onClickCapture, true);
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
