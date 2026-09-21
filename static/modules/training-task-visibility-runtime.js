import {trainingTaskRow, visibleTrainingJobs} from './training-task-runtime.js?v=422525';

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
  'success',
  'failed',
  'stopped',
  'cancelled',
  'canceled',
  'blocked_by_environment',
  'blocked_by_hardware',
]);

function counts(jobs) {
  return {
    active: visibleTrainingJobs(jobs, 'active').length,
    history: visibleTrainingJobs(jobs, 'history').length,
  };
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
  const renderedRows = new Map();

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

  function createTrainingRow(html) {
    if (!doc?.createElement) return null;
    const holder = doc.createElement('tbody');
    holder.innerHTML = String(html || '').trim();
    return holder.firstElementChild || null;
  }

  function patchProgressCell(currentCell, nextCell) {
    const currentTrack = currentCell?.querySelector?.('.progress424');
    const nextTrack = nextCell?.querySelector?.('.progress424');
    const currentBar = currentTrack?.querySelector?.('i');
    const nextBar = nextTrack?.querySelector?.('i');
    const currentText = currentCell?.querySelector?.('.train428-progress-txt');
    const nextText = nextCell?.querySelector?.('.train428-progress-txt');
    if (!currentTrack || !nextTrack || !currentBar || !nextBar || !currentText || !nextText) {
      currentCell.innerHTML = nextCell.innerHTML;
      return;
    }

    currentBar.dataset.progress = nextBar.dataset.progress || '';
    currentBar.style.transform = nextBar.style.transform;
    currentText.textContent = nextText.textContent;

    const currentMetrics = currentCell.querySelector?.('.train428-metrics');
    const nextMetrics = nextCell.querySelector?.('.train428-metrics');
    if (currentMetrics && nextMetrics) {
      currentMetrics.textContent = nextMetrics.textContent;
    } else if (currentMetrics && !nextMetrics) {
      currentMetrics.remove();
    } else if (!currentMetrics && nextMetrics) {
      currentCell.appendChild(nextMetrics.cloneNode(true));
    }
  }

  function patchTrainingRow(currentRow, nextRow) {
    if (!currentRow || !nextRow || currentRow.cells?.length !== nextRow.cells?.length) return nextRow;
    for (let index = 0; index < nextRow.cells.length; index += 1) {
      const currentCell = currentRow.cells[index];
      const nextCell = nextRow.cells[index];
      if (index === 5) {
        patchProgressCell(currentCell, nextCell);
      } else if (currentCell.innerHTML !== nextCell.innerHTML) {
        currentCell.innerHTML = nextCell.innerHTML;
      }
    }
    return currentRow;
  }

  function patchRows(body, visible) {
    const canPatch = Boolean(
      doc?.createElement
      && typeof body?.querySelectorAll === 'function'
      && typeof body?.insertBefore === 'function'
      && body?.children,
    );
    if (!canPatch) {
      body.innerHTML = visible.map(trainingTaskRow).join('')
        || '<tr><td colspan="11" class="empty-row">暂无记录</td></tr>';
      renderedRows.clear();
      for (const job of visible) renderedRows.set(String(job?.id || ''), trainingTaskRow(job));
      return;
    }

    if (!visible.length) {
      if (!body.querySelector?.('.empty-row')) {
        body.innerHTML = '<tr><td colspan="11" class="empty-row">暂无记录</td></tr>';
      }
      renderedRows.clear();
      return;
    }

    body.querySelector?.('.empty-row')?.remove?.();
    const existingRows = new Map(
      [...body.querySelectorAll('tr[data-job-id]')]
        .map(row => [String(row.dataset?.jobId || ''), row]),
    );
    const wanted = new Set();

    visible.forEach((job, index) => {
      const id = String(job?.id || '');
      const html = trainingTaskRow(job);
      wanted.add(id);
      let row = existingRows.get(id) || null;
      if (!row) {
        row = createTrainingRow(html);
        if (!row) return;
      } else if (renderedRows.get(id) !== html) {
        const nextRow = createTrainingRow(html);
        if (nextRow) row = patchTrainingRow(row, nextRow);
      }

      const reference = body.children[index] || null;
      if (row && reference !== row) body.insertBefore(row, reference);
      renderedRows.set(id, html);
    });

    for (const [id, row] of existingRows) {
      if (!wanted.has(id)) row.remove?.();
    }
    for (const id of [...renderedRows.keys()]) {
      if (!wanted.has(id)) renderedRows.delete(id);
    }
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

    const visible = visibleTrainingJobs(jobs, tab);
    patchRows(body, visible);
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
    if (String(options.source || '') !== 'poll') {
      pollRegistry?.replaceTrainingJobTimer?.();
    }
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
    build: 'training-task-visibility-422524',
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
      renderedRows.clear();
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
