const TRAINING_PAGE = '训练任务';
const ACTIVE_STATUSES = new Set(['queued', 'running', 'waiting', 'pending', 'paused']);
const DONE_STATUSES = new Set(['done', 'finished', 'completed', 'failed', 'stopped', 'cancelled', 'canceled']);

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

async function jsonResponse(response) {
  if (!response?.ok) {
    const raw = await response?.text?.() || '';
    let body = {};
    try { body = JSON.parse(raw); } catch (_) { body = {detail: raw}; }
    throw new Error(String(body.message || body.detail || `刷新失败（HTTP ${response?.status || '-'})`));
  }
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

  const previousRefreshJobsOnly = window.refreshJobsOnly;
  const previousRefreshTrainPage428 = window.refreshTrainPage428;
  const previousRefreshTrain423 = window.refreshTrain423;
  let inflight = null;
  let destroyed = false;
  let lastRefreshAt = 0;

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

  async function refresh({render = true} = {}) {
    if (destroyed) throw new Error('训练任务模块已销毁');
    if (inflight) return inflight;
    const pid = projectId?.();
    if (!pid) throw new Error('当前项目不可用，请刷新页面后重试');

    const startPage = String(state().page || '');
    const startEpoch = Number(state().__navigationEpoch || 0);
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
      if (render) patchFinalTrainingTable();
      return {stale: false, jobs};
    })();

    try {
      return await inflight;
    } finally {
      inflight = null;
    }
  }

  const focusedRefresh = () => refresh({render: true});
  focusedRefresh.__trainingTaskRuntime = true;
  focusedRefresh.__trainingTaskOriginal = previousRefreshJobsOnly;
  window.refreshJobsOnly = focusedRefresh;
  window.refreshTrainPage428 = focusedRefresh;
  window.refreshTrain423 = focusedRefresh;

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
    void refresh({render: true}).then(
      result => { if (!result?.stale) notify?.('训练任务已刷新'); },
      error => notify?.(error?.message || error),
    ).finally(() => {
      if (button?.isConnected !== false) button.disabled = false;
    });
  };
  doc?.addEventListener?.('click', onClickCapture, true);

  const runtime = {
    build: 'training-task-runtime-422501',
    refresh,
    patch: patchFinalTrainingTable,
    state() {
      return {inflight: Boolean(inflight), lastRefreshAt};
    },
    destroy() {
      destroyed = true;
      doc?.removeEventListener?.('click', onClickCapture, true);
      if (window.refreshJobsOnly === focusedRefresh) window.refreshJobsOnly = previousRefreshJobsOnly;
      if (window.refreshTrainPage428 === focusedRefresh) window.refreshTrainPage428 = previousRefreshTrainPage428;
      if (window.refreshTrain423 === focusedRefresh) window.refreshTrain423 = previousRefreshTrain423;
      if (window.TrainingTaskRuntime === runtime) window.TrainingTaskRuntime = null;
      window.__trainingTaskRuntimeInstalled = false;
    },
  };

  window.TrainingTaskRuntime = runtime;
  window.__trainingTaskRuntimeInstalled = true;
  return runtime;
}
