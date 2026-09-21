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
  const percent = Math.max(0, Math.min(100, Number(view.percent || 0)));
  const scale = percent / 100;
  return `<tr data-task-id="${esc(task?.id)}"><td><b>${esc(task?.name || task?.id)}</b><div class="muted-line">${esc(labels)}</div></td><td><span class="pill ${statusClass}">${esc(view.statusText || view.status || '-')}</span>${view.runtimeText ? `<div class="muted-line">${esc(view.runtimeText)}</div>` : ''}</td><td><div class="op427-progress"><i><em data-progress="${percent.toFixed(2)}" style="transform:scaleX(${scale.toFixed(4)})"></em></i><span>${esc(view.progressText || '-')} · ${percent.toFixed(1)}%</span></div></td><td>${Number(view.boxes || 0)}</td><td>${esc(formatTime(task?.created_at))}<div class="muted-line">${esc(formatElapsed(task))}</div></td><td><div class="row"><button class="btn mini" onclick="showAiTask60('${esc(task?.id)}')">详情</button>${view.canReview ? `<button class="btn mini primary" onclick="reviewAiLabel427('${esc(task?.id)}')">审核</button>` : ''}${view.canRetry ? `<button class="btn mini" onclick="retryAiTask60('${esc(task?.id)}')">重试</button>` : ''}</div></td></tr>`;
}

export function renderAutoLabelTaskRows(tasks, options = {}) {
  return (tasks || []).map(task => renderAutoLabelTaskRow(task, options)).join('')
    || '<tr><td colspan="6">暂无AI标注任务</td></tr>';
}

function createAutoLabelRow(body, html) {
  const doc = body?.ownerDocument || globalThis.document;
  if (!doc?.createElement) return null;
  const holder = doc.createElement('tbody');
  holder.innerHTML = String(html || '').trim();
  return holder.firstElementChild || null;
}

function patchAutoLabelProgressCell(currentCell, nextCell) {
  const currentBar = currentCell?.querySelector?.('.op427-progress em');
  const nextBar = nextCell?.querySelector?.('.op427-progress em');
  const currentText = currentCell?.querySelector?.('.op427-progress span');
  const nextText = nextCell?.querySelector?.('.op427-progress span');
  if (!currentBar || !nextBar || !currentText || !nextText) {
    currentCell.innerHTML = nextCell.innerHTML;
    return;
  }
  currentBar.dataset.progress = nextBar.dataset.progress || '';
  currentBar.style.transform = nextBar.style.transform;
  currentText.textContent = nextText.textContent;
}

export function patchAutoLabelTaskRows(body, tasks, options = {}) {
  if (!body) return false;
  const rows = Array.isArray(tasks) ? tasks : [];
  const canPatch = Boolean(
    (body?.ownerDocument || globalThis.document)?.createElement
    && typeof body.querySelectorAll === 'function'
    && typeof body.insertBefore === 'function'
    && body.children,
  );
  if (!canPatch) {
    body.innerHTML = renderAutoLabelTaskRows(rows, options);
    return true;
  }

  if (!rows.length) {
    if (!body.querySelector?.('.auto-label-empty-row')) {
      body.innerHTML = '<tr class="auto-label-empty-row"><td colspan="6">暂无AI标注任务</td></tr>';
    }
    return true;
  }

  body.querySelector?.('.auto-label-empty-row')?.remove?.();
  const existing = new Map(
    [...body.querySelectorAll('tr[data-task-id]')]
      .map(row => [String(row.dataset?.taskId || ''), row]),
  );
  const wanted = new Set();

  rows.forEach((task, index) => {
    const id = String(task?.id || '');
    const nextRow = createAutoLabelRow(body, renderAutoLabelTaskRow(task, options));
    if (!id || !nextRow) return;
    wanted.add(id);

    let currentRow = existing.get(id) || null;
    if (!currentRow) {
      currentRow = nextRow;
    } else if (currentRow.cells?.length === nextRow.cells?.length) {
      for (let cellIndex = 0; cellIndex < nextRow.cells.length; cellIndex += 1) {
        const currentCell = currentRow.cells[cellIndex];
        const nextCell = nextRow.cells[cellIndex];
        if (cellIndex === 2) {
          patchAutoLabelProgressCell(currentCell, nextCell);
        } else if (currentCell.innerHTML !== nextCell.innerHTML) {
          currentCell.innerHTML = nextCell.innerHTML;
        }
      }
    } else {
      currentRow.replaceWith?.(nextRow);
      currentRow = nextRow;
    }

    const reference = body.children[index] || null;
    if (reference !== currentRow) body.insertBefore(currentRow, reference);
  });

  for (const [id, row] of existing) {
    if (!wanted.has(id)) row.remove?.();
  }
  return true;
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

  function ownsCurrentView(s = state()) {
    return String(s.page || '') === AUTO_LABEL_PAGE
      && String(s.v427OpsTab || ACTIVE_TAB) === ACTIVE_TAB;
  }

  function clearManaged() {
    pollRegistry.clear(POLL_KEY);
  }

  function deactivate() {
    clearManaged();
    return true;
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

  function activate(tasks = state().annotationTasks60 || []) {
    clearManaged();
    if (destroyed || !ownsCurrentView()) return false;
    schedule(tasks, pollDelay);
    return true;
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
      patchAutoLabelTaskRows(currentBody, tasks, {state: current, annotationTaskView});
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

  const runtime = {
    build: 'auto-label-poll-422502',
    activate,
    patchRows(body, tasks = state().annotationTasks60 || []) {
      return patchAutoLabelTaskRows(body, tasks, {state: state(), annotationTaskView});
    },
    deactivate,
    refreshRows,
    schedule,
    snapshot() {
      return {
        pageOwned: ownsCurrentView(),
        refreshing,
        managed: pollRegistry.snapshot?.().find(row => row.key === POLL_KEY) || null,
        classicWrapperOwner: false,
        timerOwner: false,
      };
    },
    destroy() {
      destroyed = true;
      deactivate();
      if (window.AutoLabelPollRuntime === runtime) window.AutoLabelPollRuntime = null;
      window.__autoLabelPollRuntimeInstalled = false;
    },
  };

  window.AutoLabelPollRuntime = runtime;
  window.__autoLabelPollRuntimeInstalled = true;
  if (ownsCurrentView()) queueMicrotask(() => activate());
  return runtime;
}
