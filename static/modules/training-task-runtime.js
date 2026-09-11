const TRAINING_PAGE = '训练任务';

function rowsFrom(body) {
  if (Array.isArray(body)) return body;
  return Array.isArray(body?.items) ? body.items : [];
}

async function jsonResponse(response) {
  if (!response?.ok) {
    const raw = await response?.text?.() || '';
    let body = {};
    try { body = JSON.parse(raw); } catch (_) { body = {detail: raw}; }
    throw new Error(String(body.message || body.detail || `刷新失败（HTTP ${response?.status || '-' }）`));
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
  let inflight = null;
  let destroyed = false;
  let lastRefreshAt = 0;

  function isCurrent(startPage, startEpoch) {
    const s = state();
    return !destroyed
      && String(s.page || '') === startPage
      && Number(s.__navigationEpoch || 0) === startEpoch;
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
      if (render && typeof window.updateTrainingJobTable === 'function') {
        window.updateTrainingJobTable();
      }
      return {stale: false, jobs};
    })();

    try {
      return await inflight;
    } finally {
      inflight = null;
    }
  }

  const refreshJobsOnly = () => refresh({render: true});
  refreshJobsOnly.__trainingTaskRuntime = true;
  refreshJobsOnly.__trainingTaskOriginal = previousRefreshJobsOnly;
  window.refreshJobsOnly = refreshJobsOnly;

  function isOwnedRefreshButton(button) {
    if (!button || String(state().page || '') !== TRAINING_PAGE) return false;
    if (button.id === 'refreshBtn') return true;
    if (!button.closest?.('#view')) return false;
    const label = String(button.textContent || '').trim();
    return label === '刷新状态' || label === '完整刷新';
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
    build: 'training-task-runtime-422500',
    refresh,
    state() {
      return {inflight: Boolean(inflight), lastRefreshAt};
    },
    destroy() {
      destroyed = true;
      doc?.removeEventListener?.('click', onClickCapture, true);
      if (window.refreshJobsOnly === refreshJobsOnly) window.refreshJobsOnly = previousRefreshJobsOnly;
      if (window.TrainingTaskRuntime === runtime) window.TrainingTaskRuntime = null;
      window.__trainingTaskRuntimeInstalled = false;
    },
  };

  window.TrainingTaskRuntime = runtime;
  window.__trainingTaskRuntimeInstalled = true;
  return runtime;
}
