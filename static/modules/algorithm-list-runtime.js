const ALGORITHM_PAGE = '算法列表';

async function fetchJson(url) {
  const response = await window.fetch(url, {headers: {'Accept': 'application/json'}});
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

export function installAlgorithmListRuntime({getState, projectId, notify} = {}) {
  if (typeof window === 'undefined') return null;
  if (window.__algorithmListRuntimeInstalled) return window.AlgorithmListRuntime;

  const state = () => getState?.() || {};
  const doc = typeof document !== 'undefined' ? document : null;
  let destroyed = false;
  let inflight = null;
  let lastRefreshAt = 0;
  const originalToggle412 = window.toggleAlgorithm412;
  const originalToggle428 = window.toggleAlgorithm428;

  function renderCards() {
    if (String(state().page || '') !== ALGORITHM_PAGE) return false;
    if (typeof window.renderAlg412 !== 'function') return false;
    window.renderAlg412();
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

    inflight = (async () => {
      const encoded = encodeURIComponent(pid);
      const [algorithmBody, jobBody] = await Promise.all([
        fetchJson(`/api/v12/projects/${encoded}/algorithms`),
        fetchJson(`/api/projects/${encoded}/jobs`),
      ]);
      const s = state();
      s.algorithms = listFrom(algorithmBody);
      s.jobs = listFrom(jobBody);
      lastRefreshAt = Date.now();
      if (render && String(s.page || '') === ALGORITHM_PAGE) renderCards();
      return {algorithms: s.algorithms, jobs: s.jobs, cached: false};
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
      () => notify?.('算法列表已刷新'),
      error => notify?.(error?.message || error),
    ).finally(() => { target.disabled = false; });
  };

  window.toggleAlgorithm412 = toggle;
  window.toggleAlgorithm428 = toggle;
  doc?.addEventListener?.('click', onRefreshCapture, true);

  const runtime = {
    build: 'algorithm-list-runtime-422501',
    toggle,
    refresh,
    renderCards,
    state() {
      return {inflight: Boolean(inflight), lastRefreshAt};
    },
    destroy() {
      destroyed = true;
      doc?.removeEventListener?.('click', onRefreshCapture, true);
      if (window.toggleAlgorithm412 === toggle) window.toggleAlgorithm412 = originalToggle412;
      if (window.toggleAlgorithm428 === toggle) window.toggleAlgorithm428 = originalToggle428;
      if (window.AlgorithmListRuntime === runtime) window.AlgorithmListRuntime = null;
      window.__algorithmListRuntimeInstalled = false;
    },
  };
  window.AlgorithmListRuntime = runtime;
  window.__algorithmListRuntimeInstalled = true;
  return runtime;
}
