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
}

const OWNER_FUNCTIONS = {
  '训练任务': [
    'refreshTrainPage428', 'promoteTrain428', 'pauseTrain428', 'resumeTrain428',
    'stopTrain428', 'deleteTrain428', 'refreshTrain425', 'refreshTrain423',
    'refreshJobsOnly'
  ],
  '素材接入': [
    'refreshSources422', 'saveSource422', 'runSourceNow422', 'toggleSource422', 'deleteSource422'
  ],
  '自动标注及清洗': [
    'refreshAuto422', 'stopAutoTask422', 'retryAutoTask422', 'createAutoTask422',
    'retryAiTask60', 'showAiTask60'
  ],
  '视频切帧': ['refreshVideoTasksOnly', 'refreshVideo424Delta', 'stopVideo424'],
  '部署转换': ['loadDeployData', 'refreshDeployTasks'],
};

const PAGE_RENDERERS = {
  '算法列表': ['renderAlgorithms', 'renderAlgorithms423', 'renderAlgorithms428', 'renderAlg412'],
  '训练资源': ['renderResources'],
  '数据集': ['renderDatasets', 'renderDatasets412', 'renderDatasets424', 'renderDatasets426'],
  '训练任务': ['renderTraining', 'renderTraining423', 'renderTraining425', 'renderTraining428', 'renderTrainPage428'],
  '素材接入': ['renderSources422'],
  '自动标注及清洗': ['renderAutoLabel422', 'renderAutoLabel424', 'renderOps427'],
  '视频切帧': ['renderVideoFrameTasks', 'renderVideo424'],
  '部署转换': ['renderDeployTasks', 'renderDeploymentTasks'],
};

function ownersFor(page) {
  if (page === '自动标注及清洗') return ['自动标注', '自动标注及清洗'];
  if (page === '训练任务') return ['训练任务', '检测台'];
  return [page];
}

export function installNavigationStability({getState, notify, requestScope, pollRegistry} = {}) {
  if (typeof window === 'undefined' || typeof document === 'undefined') return null;
  if (window.__navigationStabilityInstalled) return window.NavigationStability;
  window.__navigationStabilityInstalled = true;

  const state = getState?.();
  const guard = new NavigationEpochGuard(state?.page || '');
  const pending = new Map();
  const rebindTimers = [];
  let tokenSeq = 0;
  let destroyed = false;

  function currentState() { return getState?.() || state || {}; }
  function adoptCurrentPageTimers(ownerPages) {
    const page = String(currentState().page || '');
    const owners = new Set(Array.isArray(ownerPages) ? ownerPages : [ownerPages]);
    if (owners.has(page)) pollRegistry?.afterNavigate?.(page);
  }

  const originalSetPage = window.setPage;
  if (typeof originalSetPage === 'function') {
    window.setPage = function stableSetPage(page, ...args) {
      const requested = String(page || '');
      requestScope?.navigate?.(requested);
      pending.clear();
      guard.navigate(requested);
      const s = currentState();
      s.__navigationEpoch = guard.epoch;
      if (pollRegistry?.beforeNavigate) pollRegistry.beforeNavigate(requested);
      else clearPageTimers(s, requested);
      const result = originalSetPage.call(this, page, ...args);
      const actualPage = String(s.page || requested);
      if (actualPage !== guard.page) guard.page = actualPage;
      requestScope?.alignPage?.(actualPage);
      pollRegistry?.afterNavigate?.(actualPage);
      const currentView = document.getElementById('view');
      if (currentView) currentView.dataset.navigationPage = actualPage;
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
      const currentPage = String(s.page || '');
      const owner = owners.has(currentPage) ? currentPage : [...owners][0];
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
        adoptCurrentPageTimers([...owners]);
        return result;
      }
      return Promise.resolve(result).finally(() => {
        pending.delete(itemId);
        adoptCurrentPageTimers([...owners]);
      });
    };
    wrapped.__navigationStabilityWrapped = true;
    wrapped.__navigationStabilityOriginal = original;
    window[name] = wrapped;
  }

  function wrapRenderer(name, ownerPages) {
    if (destroyed || typeof window === 'undefined') return;
    const original = window[name];
    if (typeof original !== 'function' || original.__navigationOwnerWrapped) return;
    const owners = new Set(Array.isArray(ownerPages) ? ownerPages : [ownerPages]);
    const wrapped = function (...args) {
      const currentPage = String(currentState().page || '');
      if (!owners.has(currentPage)) return false;
      const result = original.apply(this, args);
      if (result && typeof result.then === 'function') {
        return Promise.resolve(result).finally(() => adoptCurrentPageTimers([...owners]));
      }
      adoptCurrentPageTimers([...owners]);
      return result;
    };
    wrapped.__navigationOwnerWrapped = true;
    wrapped.__navigationOwnerOriginal = original;
    window[name] = wrapped;
  }

  function wrapKnownFunctions() {
    if (destroyed || typeof window === 'undefined') return;
    Object.entries(OWNER_FUNCTIONS).forEach(([page, names]) => {
      const owners = ownersFor(page);
      for (const name of names) wrapAsyncOwner(name, owners);
    });
    Object.entries(PAGE_RENDERERS).forEach(([page, names]) => {
      const owners = ownersFor(page);
      for (const name of names) wrapRenderer(name, owners);
    });
  }

  // app.js contains historical override layers; some functions are assigned late.
  // Re-check briefly so the final implementation, not an earlier override, is guarded.
  wrapKnownFunctions();
  for (const delay of [50, 250, 800, 1800]) {
    rebindTimers.push(setTimeout(() => wrapKnownFunctions(), delay));
  }

  const api = {
    guard,
    pending,
    isCurrent(token) {
      return guard.isCurrent(token, currentState().page);
    },
    token(ownerPage) {
      return guard.token(ownerPage || currentState().page);
    },
    wrapKnownFunctions,
    repairCurrentPage() {
      notify?.('旧页面结果已被拦截');
      return false;
    },
    destroy() {
      destroyed = true;
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
