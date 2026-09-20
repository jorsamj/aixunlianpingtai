const ALGORITHM_PAGE = '算法列表';

function rawFetch() {
  const scoped = window.fetch;
  return scoped?.__pageRequestScopeOriginal || scoped;
}

async function fetchJson(url, fetchImpl = rawFetch()) {
  const response = await fetchImpl(url, {headers: {'Accept': 'application/json'}});
  if (!response.ok) {
    const raw = await response.text();
    let body = {};
    try { body = JSON.parse(raw); } catch (_) { body = {detail: raw}; }
    throw new Error(String(body.message || body.detail || `刷新失败（HTTP ${response.status}）`));
  }
  return response.json();
}

function listFrom(value) {
  if (Array.isArray(value)) return value;
  return Array.isArray(value?.items) ? value.items : [];
}

export function algorithmListSearchMatch(algorithm = {}, query = '') {
  const needle = String(query || '').trim().toLowerCase();
  if (!needle) return true;
  const values = [
    algorithm?.name,
    algorithm?.code,
    algorithm?.algorithm_code,
    algorithm?.algorithmCode,
    algorithm?.product_id,
    algorithm?.productId,
    algorithm?.product_code,
    algorithm?.productCode,
    algorithm?.external_product_id,
    algorithm?.external_product_code,
    algorithm?.remark,
    algorithm?.industry,
    algorithm?.algorithm_type,
  ];
  return values.some(value => String(value ?? '').toLowerCase().includes(needle));
}

export function installAlgorithmListRuntime({getState, projectId, notify} = {}) {
  if (typeof window === 'undefined') return null;
  if (window.__algorithmListRuntimeInstalled) return window.AlgorithmListRuntime;

  const state = () => getState?.() || {};
  const doc = typeof document !== 'undefined' ? document : null;
  let destroyed = false;
  let inflight = null;
  let lastRefreshAt = 0;
  let decoratorQueued = false;
  const decorators = new Map();
  const filters = {
    query: '',
    selectedCategoryIds: [],
    source: 'all',
    status: 'all',
  };
  const originalToggle412 = window.toggleAlgorithm412;
  const originalToggle428 = window.toggleAlgorithm428;

  function ensureAlgorithmShell() {
    if (destroyed || String(state().page || '') !== ALGORITHM_PAGE) return false;
    if (!doc || doc.getElementById('alg412List')) return true;
    if (typeof window.renderAlgorithms423 === 'function') {
      window.renderAlgorithms423();
    }
    return !doc || Boolean(doc.getElementById('alg412List'));
  }

  function runDecorators() {
    if (!ensureAlgorithmShell()) return false;
    for (const [name, callback] of decorators.entries()) {
      try {
        callback?.({state: state(), root: doc?.getElementById('alg412List') || null});
      } catch (error) {
        console.warn?.(`algorithm list decorator failed: ${name}`, error);
      }
    }
    return true;
  }

  function scheduleDecorators() {
    if (destroyed || decoratorQueued) return;
    decoratorQueued = true;
    queueMicrotask(() => {
      decoratorQueued = false;
      runDecorators();
    });
  }

  function filterState() {
    return {
      query: filters.query,
      selectedCategoryIds: [...filters.selectedCategoryIds],
      source: filters.source,
      status: filters.status,
    };
  }

  function setFilters(patch = {}, {render = true} = {}) {
    const next = patch && typeof patch === 'object' ? patch : {};
    if (Object.prototype.hasOwnProperty.call(next, 'query')) {
      filters.query = String(next.query || '').trim();
    }
    if (Object.prototype.hasOwnProperty.call(next, 'selectedCategoryIds')) {
      filters.selectedCategoryIds = [...new Set(
        Array.from(next.selectedCategoryIds || [], value => String(value || '').trim()).filter(Boolean),
      )];
    }
    if (Object.prototype.hasOwnProperty.call(next, 'source')) {
      const source = String(next.source || 'all');
      filters.source = ['all', 'internal', 'external'].includes(source) ? source : 'all';
    }
    if (Object.prototype.hasOwnProperty.call(next, 'status')) {
      const status = String(next.status || 'all');
      filters.status = ['all', 'trainable', 'training', 'trained', 'untrained', 'blocked'].includes(status)
        ? status
        : 'all';
    }
    if (render && String(state().page || '') === ALGORITHM_PAGE) renderCards();
    else scheduleDecorators();
    return filterState();
  }

  function matchesSearch(algorithm, query = filters.query) {
    return algorithmListSearchMatch(algorithm, query);
  }

  function registerDecorator(name, callback) {
    const key = String(name || '').trim();
    if (!key) throw new Error('算法列表扩展名称不能为空');
    if (typeof callback !== 'function') throw new Error(`算法列表扩展 ${key} 必须是函数`);
    decorators.set(key, callback);
    scheduleDecorators();
    return () => {
      if (decorators.get(key) === callback) decorators.delete(key);
    };
  }

  function renderCards() {
    if (!ensureAlgorithmShell()) return false;
    if (typeof window.renderAlg412 !== 'function') return false;
    window.renderAlg412();
    scheduleDecorators();
    return true;
  }

  function toggle(id) {
    if (destroyed) return false;
    const s = state();
    s.alg428Expanded = s.alg428Expanded || {};
    const key = String(id || '');
    s.alg428Expanded[key] = !s.alg428Expanded[key];
    renderCards();
    return s.alg428Expanded[key];
  }
  toggle.__algorithmListRuntime = true;
  toggle.__algorithmListOriginal = originalToggle412;

  async function refresh({render = true, minAgeMs = 0} = {}) {
    if (destroyed) throw new Error('算法列表模块已销毁');
    const now = Date.now();
    if (minAgeMs > 0 && now - lastRefreshAt < minAgeMs) {
      if (render) renderCards();
      return {algorithms: state().algorithms || [], jobs: state().jobs || [], cached: true};
    }
    if (inflight) return inflight;
    const pid = projectId?.();
    if (!pid) throw new Error('当前项目不可用，请刷新页面后重试');

    const navigationGeneration = window.PageRequestScopeRuntime?.stats?.().generation ?? null;
    const fetchImpl = rawFetch();
    if (typeof fetchImpl !== 'function') throw new Error('浏览器请求能力不可用');

    inflight = (async () => {
      const encoded = encodeURIComponent(pid);
      const [algorithmBody, jobBody] = await Promise.all([
        fetchJson(`/api/v12/projects/${encoded}/algorithms`, fetchImpl),
        fetchJson(`/api/projects/${encoded}/jobs`, fetchImpl),
      ]);

      const latestGeneration = window.PageRequestScopeRuntime?.stats?.().generation ?? null;
      const navigationChanged = navigationGeneration != null
        && latestGeneration != null
        && latestGeneration !== navigationGeneration;
      const sameProject = String(projectId?.() || '') === String(pid);
      const s = state();
      if (destroyed || navigationChanged || !sameProject) {
        return {algorithms: s.algorithms || [], jobs: s.jobs || [], cached: false, stale: true};
      }

      s.algorithms = listFrom(algorithmBody);
      s.jobs = listFrom(jobBody);
      lastRefreshAt = Date.now();
      if (render && String(s.page || '') === ALGORITHM_PAGE) renderCards();
      return {algorithms: s.algorithms, jobs: s.jobs, cached: false, stale: false};
    })();

    try {
      return await inflight;
    } finally {
      inflight = null;
    }
  }

  const onRefreshCapture = event => {
    const target = event?.target?.closest?.('#refreshBtn');
    if (!target || String(state().page || '') !== ALGORITHM_PAGE) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    if (target.disabled || inflight) return;
    target.disabled = true;
    void refresh({render: true}).then(
      result => {
        if (!result?.stale) notify?.('算法列表已刷新');
      },
      error => notify?.(error?.message || error),
    ).finally(() => { target.disabled = false; });
  };

  const domObserver = doc?.body ? new MutationObserver(() => {
    if (String(state().page || '') === ALGORITHM_PAGE) scheduleDecorators();
  }) : null;
  domObserver?.observe(doc.body, {childList: true, subtree: true});

  window.toggleAlgorithm412 = toggle;
  window.toggleAlgorithm428 = toggle;
  doc?.addEventListener?.('click', onRefreshCapture, true);

  const runtime = {
    build: 'algorithm-list-runtime-422504',
    toggle,
    refresh,
    renderCards,
    registerDecorator,
    runDecorators,
    filterState,
    setFilters,
    matchesSearch,
    state() {
      return {inflight: Boolean(inflight), lastRefreshAt, decorators: [...decorators.keys()]};
    },
    destroy() {
      destroyed = true;
      decorators.clear();
      domObserver?.disconnect();
      doc?.removeEventListener?.('click', onRefreshCapture, true);
      if (window.toggleAlgorithm412 === toggle) window.toggleAlgorithm412 = originalToggle412;
      if (window.toggleAlgorithm428 === toggle) window.toggleAlgorithm428 = originalToggle428;
      if (window.AlgorithmListRuntime === runtime) window.AlgorithmListRuntime = null;
      window.__algorithmListRuntimeInstalled = false;
    },
  };
  window.AlgorithmListRuntime = runtime;
  window.__algorithmListRuntimeInstalled = true;
  scheduleDecorators();
  return runtime;
}
