import {trainingTaskRow} from './training-task-runtime.js?v=422522';

const TRAINING_PAGE = '训练任务';
const ACTIVE_STATUSES = new Set([
  'queued',
  'waiting',
  'pending',
  'starting',
  'running',
  'pausing',
  'paused',
  'resuming',
  'stopping',
  'cancel_requested',
]);
const TERMINAL_STATUSES = new Set([
  'done',
  'finished',
  'completed',
  'succeeded',
  'failed',
  'stopped',
  'cancelled',
  'canceled',
  'blocked_by_environment',
  'blocked_by_hardware',
]);

function statusOf(job) {
  return String(job?.status || '').trim().toLowerCase();
}

function priorityValue(job) {
  const raw = Number(job?.queue_priority ?? 50);
  if (job?.priority_scheme === 'lower_number_first') {
    return Math.max(1, Math.min(999, Number.isFinite(raw) ? raw : 50));
  }
  const legacy = {100: 1, 80: 20, 50: 50};
  return legacy[raw] ?? Math.max(1, Math.min(999, 101 - (Number.isFinite(raw) ? raw : 50)));
}

function activeRank(status) {
  if (['running', 'starting', 'resuming'].includes(status)) return 0;
  if (['pausing', 'paused', 'stopping', 'cancel_requested'].includes(status)) return 1;
  if (status === 'queued') return 2;
  return 3;
}

function visibleJobs(jobs, tab) {
  const rows = Array.isArray(jobs) ? jobs : [];
  const filtered = tab === 'history'
    ? rows.filter(job => !ACTIVE_STATUSES.has(statusOf(job)))
    : rows.filter(job => ACTIVE_STATUSES.has(statusOf(job)));
  return [...filtered].sort((a, b) => {
    const aStatus = statusOf(a);
    const bStatus = statusOf(b);
    const aRank = activeRank(aStatus);
    const bRank = activeRank(bStatus);
    if (aRank !== bRank) return aRank - bRank;
    if (aRank === 2) return priorityValue(a) - priorityValue(b);
    return String(b?.started_at || b?.created_at || '').localeCompare(
      String(a?.started_at || a?.created_at || ''),
    );
  });
}

function counts(jobs) {
  const rows = Array.isArray(jobs) ? jobs : [];
  let active = 0;
  let history = 0;
  for (const job of rows) {
    if (ACTIVE_STATUSES.has(statusOf(job))) active += 1;
    else history += 1;
  }
  return {active, history};
}

export function installTrainingTaskVisibilityRuntime({
  getState,
  trainingTaskRuntime,
  pollRegistry,
  notify,
} = {}) {
  if (typeof window === 'undefined') return null;
  if (window.__trainingTaskVisibilityRuntimeInstalled) {
    return window.TrainingTaskVisibilityRuntime;
  }

  const doc = typeof document !== 'undefined' ? document : null;
  const state = () => getState?.() || {};
  const runtime = trainingTaskRuntime || window.TrainingTaskRuntime;
  if (!runtime || typeof runtime.refresh !== 'function') return null;

  const legacyLoadRelated = typeof window.loadRelated === 'function' ? window.loadRelated : null;
  const legacyRender = window.renderTraining425
    || window.renderTraining424
    || window.renderTraining423;
  const previous = {
    loadRelated: window.loadRelated,
    renderTraining423: window.renderTraining423,
    renderTraining424: window.renderTraining424,
    renderTraining425: window.renderTraining425,
    setTrainTab428: window.setTrainTab428,
    refreshJobsOnly: window.refreshJobsOnly,
    refreshTrainPage428: window.refreshTrainPage428,
    refreshTrain423: window.refreshTrain423,
    promoteTrain428: window.promoteTrain428,
    pauseTrain428: window.pauseTrain428,
    resumeTrain428: window.resumeTrain428,
    stopTrain428: window.stopTrain428,
    deleteTrain428: window.deleteTrain428,
    runtimeRefresh: runtime.refresh,
  };

  let destroyed = false;
  let jobsProjectId = String(state().project?.id || '');
  let refreshSequence = 0;
  let appliedSequence = 0;

  function sameProject(projectId) {
    return String(state().project?.id || '') === String(projectId || '');
  }

  function ensureShell() {
    if (!doc || String(state().page || '') !== TRAINING_PAGE) return null;
    let root = doc.querySelector?.('.train428-page');
    if (!root && typeof legacyRender === 'function') {
      legacyRender();
      root = doc.querySelector?.('.train428-page');
    }
    return root || null;
  }

  function renderOwned() {
    if (destroyed || !doc || String(state().page || '') !== TRAINING_PAGE) return false;
    const root = ensureShell();
    const body = root?.querySelector?.('.train428-table tbody');
    if (!root || !body) return false;

    const jobs = Array.isArray(state().jobs) ? state().jobs : [];
    const tab = String(state().train428Tab || 'active');
    const summary = counts(jobs);
    const buttons = root.querySelectorAll?.('.train428-tabs button') || [];
    const activeButton = buttons[0];
    const historyButton = buttons[1];
    const activeCount = activeButton?.querySelector?.('span');
    const historyCount = historyButton?.querySelector?.('span');
    if (activeCount) activeCount.textContent = String(summary.active);
    if (historyCount) historyCount.textContent = String(summary.history);
    activeButton?.classList?.toggle?.('on', tab !== 'history');
    historyButton?.classList?.toggle?.('on', tab === 'history');

    const visible = visibleJobs(jobs, tab);
    body.innerHTML = visible.map(trainingTaskRow).join('')
      || '<tr><td colspan="8" class="empty-row">暂无记录</td></tr>';
    return true;
  }

  async function refreshOwned(options = {}) {
    const sequence = ++refreshSequence;
    const requestedRender = options.render !== false;
    const result = await previous.runtimeRefresh({...options, render: false});
    if (destroyed || result?.stale) return result;
    if (sequence < appliedSequence) return {...result, stale: true};
    appliedSequence = sequence;
    jobsProjectId = String(state().project?.id || jobsProjectId || '');
    if (requestedRender) renderOwned();
    return result;
  }

  runtime.refresh = refreshOwned;

  const focusedRefresh = () => refreshOwned({render: true, source: 'poll'});
  focusedRefresh.__trainingTaskRuntime = true;
  focusedRefresh.__trainingTaskVisibilityRuntime = true;
  window.refreshJobsOnly = focusedRefresh;
  window.refreshTrainPage428 = () => refreshOwned({render: true, force: true, source: 'manual'});
  window.refreshTrain423 = window.refreshTrainPage428;

  if (legacyLoadRelated) {
    const guardedLoadRelated = async (...args) => {
      const current = state();
      const projectId = String(current.project?.id || '');
      if (String(current.page || '') === TRAINING_PAGE) {
        return refreshOwned({render: true, force: true, source: 'related'});
      }

      const preserveJobs = jobsProjectId === projectId;
      const snapshot = preserveJobs && Array.isArray(current.jobs) ? current.jobs : null;
      try {
        return await legacyLoadRelated(...args);
      } finally {
        if (!destroyed && sameProject(projectId)) {
          if (snapshot) state().jobs = snapshot;
          else state().jobs = [];
        }
      }
    };
    guardedLoadRelated.__trainingJobsPreserved = true;
    window.loadRelated = guardedLoadRelated;
  }

  const renderTraining = () => {
    const rendered = renderOwned();
    if (!rendered && typeof legacyRender === 'function') {
      legacyRender();
      renderOwned();
    }
    pollRegistry?.replaceTrainingJobTimer?.();
    void refreshOwned({render: true, force: true, source: 'render'}).catch(error => {
      notify?.(error?.message || error);
    });
  };
  renderTraining.__trainingTaskVisibilityRuntime = true;
  window.renderTraining423 = renderTraining;
  window.renderTraining424 = renderTraining;
  window.renderTraining425 = renderTraining;

  window.setTrainTab428 = tab => {
    state().train428Tab = tab === 'history' ? 'history' : 'active';
    renderOwned();
    pollRegistry?.replaceTrainingJobTimer?.();
  };

  for (const name of ['promoteTrain428', 'pauseTrain428', 'resumeTrain428', 'stopTrain428', 'deleteTrain428']) {
    const mutation = window[name];
    if (typeof mutation !== 'function') continue;
    const wrapped = async (...args) => {
      const result = await mutation(...args);
      if (String(state().page || '') === TRAINING_PAGE) renderOwned();
      return result;
    };
    wrapped.__trainingTaskRuntime = true;
    wrapped.__trainingTaskVisibilityRuntime = true;
    window[name] = wrapped;
  }

  const visibilityRuntime = {
    build: 'training-task-visibility-422523',
    activeStatuses: Object.freeze([...ACTIVE_STATUSES]),
    terminalStatuses: Object.freeze([...TERMINAL_STATUSES]),
    render: renderOwned,
    refresh: refreshOwned,
    state() {
      return {
        jobsProjectId,
        refreshSequence,
        appliedSequence,
        page: String(state().page || ''),
      };
    },
    destroy() {
      destroyed = true;
      runtime.refresh = previous.runtimeRefresh;
      for (const [name, fn] of Object.entries(previous)) {
        if (name === 'runtimeRefresh') continue;
        if (fn === undefined) delete window[name];
        else window[name] = fn;
      }
      if (window.TrainingTaskVisibilityRuntime === visibilityRuntime) {
        window.TrainingTaskVisibilityRuntime = null;
      }
      window.__trainingTaskVisibilityRuntimeInstalled = false;
    },
  };

  window.TrainingTaskVisibilityRuntime = visibilityRuntime;
  window.__trainingTaskVisibilityRuntimeInstalled = true;
  if (window.PlatformCore?.runtime) {
    window.PlatformCore.runtime.trainingTaskVisibilityRuntime = visibilityRuntime;
  }

  if (String(state().page || '') === TRAINING_PAGE) {
    renderOwned();
    void refreshOwned({render: true, force: true, source: 'install'}).catch(error => {
      notify?.(error?.message || error);
    });
  }

  return visibilityRuntime;
}

if (typeof window !== 'undefined') {
  installTrainingTaskVisibilityRuntime({
    getState: () => state,
    trainingTaskRuntime: window.PlatformCore?.runtime?.trainingTaskRuntime || window.TrainingTaskRuntime,
    pollRegistry: window.PollRegistryRuntime,
    notify: message => window.toast?.(message),
  });
}
