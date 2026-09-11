export class NavigationEpochGuard {
  constructor(initialPage = '') {
    this.epoch = 0;
    this.page = String(initialPage || '');
  }

  navigate(page) {
    this.epoch += 1;
    this.page = String(page || '');
    return this.epoch;
  }

  token(ownerPage = this.page) {
    return {epoch: this.epoch, ownerPage: String(ownerPage || '')};
  }

  isCurrent(token, currentPage = this.page) {
    return !!token && token.epoch === this.epoch && String(currentPage || '') === token.ownerPage;
  }
}

function clearTimer(value, clearFn = clearInterval) {
  if (value == null) return;
  try { clearFn(value); } catch (_) {}
}

function clearPageTimers(state, nextPage) {
  if (!state) return;
  if (!['训练任务', '检测台'].includes(nextPage)) {
    clearTimer(state.jobPollTimer);
    state.jobPollTimer = null;
  }
  if (nextPage !== '素材接入') {
    clearTimer(state.source422Timer);
    state.source422Timer = null;
  }
  if (!['自动标注', '自动标注及清洗'].includes(nextPage)) {
    clearTimer(state.auto422Timer);
    state.auto422Timer = null;
  }
  if (nextPage !== '视频切帧') clearTimer(window.__videoFramePollTimer);
  if (!['自动标注', '自动标注及清洗'].includes(nextPage)) clearTimer(window.__prelabelPollTimer);
}

export function installNavigationStability({getState, notify} = {}) {
  if (typeof window === 'undefined' || typeof document === 'undefined') return null;
  if (window.__navigationStabilityInstalled) return window.NavigationStability;
  window.__navigationStabilityInstalled = true;

  const state = getState?.();
  const guard = new NavigationEpochGuard(state?.page || '');
  const pending = new Map();
  const rebindTimers = [];
  let repairing = false;
  let repairQueued = false;
  let tokenSeq = 0;
  let destroyed = false;

  function currentState() { return getState?.() || state || {}; }

  function repairCurrentPage(reason = 'stale-render') {
    if (destroyed || repairing || repairQueued) return;
    const s = currentState();
    if (!s.page) return;
    repairQueued = true;
    queueMicrotask(() => {
      repairQueued = false;
      if (destroyed || repairing) return;
      repairing = true;
      try {
        if (typeof window !== 'undefined' && typeof window.render === 'function') window.render();
        else if (typeof globalThis.render === 'function') globalThis.render();
      } catch (error) {
        notify?.(`页面状态恢复失败：${error?.message || error}`);
      } finally {
        repairing = false;
      }
    });
  }

  function hasStalePending() {
    if (destroyed) return false;
    const s = currentState();
    for (const item of pending.values()) {
      if (!guard.isCurrent(item.token, s.page)) return true;
    }
    return false;
  }

  const view = document.getElementById('view');
  const observer = view && typeof MutationObserver !== 'undefined'
    ? new MutationObserver(() => {
        if (!repairing && hasStalePending()) repairCurrentPage('stale-dom-mutation');
      })
    : null;
  observer?.observe(view, {childList: true, subtree: true});

  const originalSetPage = window.setPage;
  if (typeof originalSetPage === 'function') {
    window.setPage = function stableSetPage(page, ...args) {
      const requested = String(page || '');
      guard.navigate(requested);
      const s = currentState();
      s.__navigationEpoch = guard.epoch;
      clearPageTimers(s, requested);
      const result = originalSetPage.call(this, page, ...args);
      // Some legacy aliases rewrite the requested page. Keep the guard aligned
      // with the authoritative state after the existing router has run.
      if (String(s.page || '') !== guard.page) guard.page = String(s.page || '');
      const currentView = document.getElementById('view');
      if (currentView) currentView.dataset.navigationPage = String(s.page || requested);
      return result;
    };
  }

  function wrapAsyncOwner(name, ownerPages) {
    if (destroyed || typeof window === 'undefined') return;
    const original = window[name];
    if (typeof original !== 'function' || original.__navigationStabilityWrapped) return;
    const owners = new Set(Array.isArray(ownerPages) ? ownerPages : [ownerPages]);
    const wrapped = function (...args) {
      const s = currentState();
      const owner = owners.has(String(s.page || '')) ? String(s.page || '') : [...owners][0];
      const itemId = `${name}:${++tokenSeq}`;
      const item = {token: guard.token(owner), name};
      pending.set(itemId, item);
      let result;
      try {
        result = original.apply(this, args);
      } catch (error) {
        pending.delete(itemId);
        throw error;
      }
      if (!result || typeof result.then !== 'function') {
        pending.delete(itemId);
        return result;
      }
      return Promise.resolve(result).finally(() => {
        const stale = !guard.isCurrent(item.token, currentState().page);
        pending.delete(itemId);
        if (stale) repairCurrentPage(`stale:${name}`);
      });
    };
    wrapped.__navigationStabilityWrapped = true;
    wrapped.__navigationStabilityOriginal = original;
    window[name] = wrapped;
  }

  const ownerFunctions = {
    '训练任务': [
      'refreshTrainPage428', 'promoteTrain428', 'pauseTrain428', 'resumeTrain428',
      'stopTrain428', 'deleteTrain428', 'refreshTrain425', 'refreshTrain423'
    ],
    '素材接入': [
      'renderSources422', 'refreshSources422', 'saveSource422', 'runSourceNow422',
      'toggleSource422', 'deleteSource422'
    ],
    '自动标注及清洗': [
      'renderAutoLabel422', 'refreshAuto422', 'stopAutoTask422', 'retryAutoTask422',
      'createAutoTask422'
    ],
    '视频切帧': ['refreshVideoTasksOnly', 'renderVideoFrameTasks'],
    '部署转换': ['loadDeployData', 'refreshDeployTasks'],
  };

  function wrapKnownFunctions() {
    if (destroyed || typeof window === 'undefined') return;
    Object.entries(ownerFunctions).forEach(([page, names]) => {
      for (const name of names) {
        const owners = page === '自动标注及清洗' ? ['自动标注', '自动标注及清洗'] : [page];
        wrapAsyncOwner(name, owners);
      }
    });
  }

  // app.js contains historical override layers; some functions are assigned late.
  // Re-check briefly after module installation so the final implementation is fenced.
  wrapKnownFunctions();
  for (const delay of [50, 250, 800, 1800]) {
    rebindTimers.push(setTimeout(() => wrapKnownFunctions(), delay));
  }

  const api = {
    guard,
    pending,
    repairCurrentPage,
    wrapKnownFunctions,
    destroy() {
      destroyed = true;
      observer?.disconnect();
      for (const timer of rebindTimers) clearTimeout(timer);
      rebindTimers.length = 0;
      pending.clear();
      if (typeof window !== 'undefined') {
        window.__navigationStabilityInstalled = false;
        if (window.NavigationStability === api) window.NavigationStability = null;
      }
    },
  };
  window.NavigationStability = api;
  return api;
}
