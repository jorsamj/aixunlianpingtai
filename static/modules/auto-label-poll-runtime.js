const AUTO_LABEL_PAGE = '自动标注及清洗';
const POLL_KEY = 'auto-label-v60';
const ACTIVE_TAB = 'label';

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[char]);
}

function formatTime(value) {
  if (!value) return '-';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '-' : date.toLocaleString();
}

function formatElapsed(task = {}) {
  const start = Date.parse(task.created_at || '');
  const end = Date.parse(task.finished_at || task.updated_at || '');
  if (!Number.isFinite(start) || !Number.isFinite(end)) return '-';
  let seconds = Math.max(0, Math.floor((end - start) / 1000));
  const hours = Math.floor(seconds / 3600);
  seconds -= hours * 3600;
  const minutes = Math.floor(seconds / 60);
  seconds -= minutes * 60;
  if (hours) return `${hours}小时${minutes}分${seconds}秒`;
  if (minutes) return `${minutes}分${seconds}秒`;
  return `${seconds}秒`;
}

function labelName(state, code) {
  const row = (state?.labels || []).find(item => String(item?.code || '') === String(code));
  return row?.display_name || row?.display_name_zh || row?.name || code;
}

export function renderAutoLabelTaskRow(task, {state = {}, annotationTaskView} = {}) {
  const view = typeof annotationTaskView === 'function' ? annotationTaskView(task) : {};
  const labels = (task?.requested_labels || []).map(code => labelName(state, code)).join('、') || '-';
  const statusClass = view.active
    ? 'run'
    : view.status === 'AWAITING_CONFIRMATION'
      ? 'warn'
      : view.status === 'SUCCEEDED'
        ? 'ok'
        : view.status === 'FAILED'
          ? 'err'
          : '';
  const percent = Number(view.percent || 0);
  return `<tr data-task-id="${esc(task?.id)}"><td><b>${esc(task?.name || task?.id)}</b><div class="muted-line">${esc(labels)}</div></td><td><span class="pill ${statusClass}">${esc(view.statusText || view.status || '-')}</span></td><td><div class="op427-progress"><i><em style="width:${percent}%"></em></i><span>${esc(view.progressText || '-')} · ${percent.toFixed(1)}%</span></div></td><td>${Number(view.boxes || 0)}</td><td>${esc(formatTime(task?.created_at))}<div class="muted-line">${esc(formatElapsed(task))}</div></td><td><div class="row"><button class="btn mini" onclick="showAiTask60('${esc(task?.id)}')">详情</button>${view.canReview ? `<button class="btn mini primary" onclick="reviewAiLabel427('${esc(task?.id)}')">审核</button>` : ''}${view.canRetry ? `<button class="btn mini" onclick="retryAiTask60('${esc(task?.id)}')">重试</button>` : ''}</div></td></tr>`;
}

export function renderAutoLabelTaskRows(tasks, options = {}) {
  return (tasks || []).map(task => renderAutoLabelTaskRow(task, options)).join('')
    || '<tr><td colspan="6">暂无AI标注任务</td></tr>';
}

export function hasActiveAutoLabelTask(tasks, annotationTaskView) {
  return (tasks || []).some(task => Boolean(annotationTaskView?.(task)?.active));
}

async function requestTasks(projectId) {
  const response = await window.fetch(`/api/v60/projects/${encodeURIComponent(projectId)}/annotation-tasks?limit=50`);
  if (!response.ok) {
    const raw = await response.text();
    let body = {};
    try { body = JSON.parse(raw); } catch (_) { body = {detail: raw}; }
    throw new Error(String(body.message || body.detail || `AI标注任务刷新失败（HTTP ${response.status}）`));
  }
  const body = await response.json();
  return Array.isArray(body?.items) ? body.items : [];
}

export function installAutoLabelPollRuntime({
  getState,
  pollRegistry,
  annotationTaskView,
  notify,
  pollDelay = 1800,
  retryDelay = 4000,
} = {}) {
  if (typeof window === 'undefined') return null;
  if (window.__autoLabelPollRuntimeInstalled) return window.AutoLabelPollRuntime;
  if (!pollRegistry?.startTimeout || !pollRegistry?.clear) {
    throw new Error('AutoLabelPollRuntime requires PollRegistry one-shot support');
  }
  if (typeof annotationTaskView !== 'function') {
    throw new Error('AutoLabelPollRuntime requires annotationTaskView');
  }

  const state = () => getState?.() || {};
  let destroyed = false;
  let refreshing = false;
  let originalRenderOps = null;
  let wrappedRenderOps = null;
  const rebindTimers = [];

  function ownsCurrentView(s = state()) {
    return String(s.page || '') === AUTO_LABEL_PAGE
      && String(s.v427OpsTab || ACTIVE_TAB) === ACTIVE_TAB;
  }

  function retireLegacyTimer(s = state()) {
    if (s.ai60ListTimer != null) {
      try { clearTimeout(s.ai60ListTimer); } catch (_) {}
      s.ai60ListTimer = null;
    }
  }

  function clearManaged() {
    pollRegistry.clear(POLL_KEY);
  }

  function schedule(tasks, delay = pollDelay) {
    clearManaged();
    if (destroyed || !ownsCurrentView()) return null;
    if (!hasActiveAutoLabelTask(tasks, annotationTaskView)) return null;
    return pollRegistry.startTimeout(
      POLL_KEY,
      AUTO_LABEL_PAGE,
      () => refreshRows(),
      delay,
    );
  }

  async function refreshRows() {
    if (destroyed || refreshing) return false;
    const before = state();
    if (!ownsCurrentView(before)) {
      clearManaged();
      return false;
    }
    const projectId = before.project?.id;
    const body = document.getElementById('ai60TaskRows');
    if (!projectId || !body) {
      clearManaged();
      return false;
    }

    refreshing = true;
    try {
      const tasks = await requestTasks(projectId);
      const current = state();
      if (!ownsCurrentView(current)) {
        clearManaged();
        return false;
      }
      const currentBody = document.getElementById('ai60TaskRows');
      if (!currentBody) {
        clearManaged();
        return false;
      }
      current.annotationTasks60 = tasks;
      currentBody.innerHTML = renderAutoLabelTaskRows(tasks, {state: current, annotationTaskView});
      schedule(tasks, pollDelay);
      return true;
    } catch (error) {
      notify?.(error?.message || error);
      const current = state();
      if (ownsCurrentView(current) && hasActiveAutoLabelTask(current.annotationTasks60 || [], annotationTaskView)) {
        pollRegistry.startTimeout(POLL_KEY, AUTO_LABEL_PAGE, () => refreshRows(), retryDelay);
      } else {
        clearManaged();
      }
      return false;
    } finally {
      refreshing = false;
    }
  }

  function afterLegacyRender() {
    const s = state();
    retireLegacyTimer(s);
    if (!ownsCurrentView(s)) {
      clearManaged();
      return;
    }
    schedule(s.annotationTasks60 || [], pollDelay);
  }

  function bindRenderer() {
    const current = window.renderOps427;
    if (typeof current !== 'function') return false;
    if (current.__autoLabelPollRuntimeWrapped) return true;
    originalRenderOps = current;
    wrappedRenderOps = async function (...args) {
      try {
        return await current.apply(this, args);
      } finally {
        afterLegacyRender();
      }
    };
    wrappedRenderOps.__autoLabelPollRuntimeWrapped = true;
    wrappedRenderOps.__autoLabelPollRuntimeOriginal = current;
    window.renderOps427 = wrappedRenderOps;
    if (ownsCurrentView()) queueMicrotask(afterLegacyRender);
    return true;
  }

  bindRenderer();
  for (const delay of [100, 400, 1000]) {
    rebindTimers.push(setTimeout(bindRenderer, delay));
  }

  const runtime = {
    build: 'auto-label-poll-422500',
    refreshRows,
    schedule,
    rebind: bindRenderer,
    snapshot() {
      return {
        pageOwned: ownsCurrentView(),
        refreshing,
        managed: pollRegistry.snapshot?.().find(row => row.key === POLL_KEY) || null,
      };
    },
    destroy() {
      destroyed = true;
      for (const timer of rebindTimers) clearTimeout(timer);
      rebindTimers.length = 0;
      retireLegacyTimer();
      clearManaged();
      if (wrappedRenderOps && window.renderOps427 === wrappedRenderOps) window.renderOps427 = originalRenderOps;
      if (window.AutoLabelPollRuntime === runtime) window.AutoLabelPollRuntime = null;
      window.__autoLabelPollRuntimeInstalled = false;
    },
  };

  window.AutoLabelPollRuntime = runtime;
  window.__autoLabelPollRuntimeInstalled = true;
  return runtime;
}
