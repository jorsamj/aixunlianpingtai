// Dedicated read-only ChangLian provider page; do not move its API/GT owners.
export function installLazyChangLianDataBrowserRuntime({
  getState = () => ({}),
  request,
  notify = () => {},
  modal,
  closeModal,
  document: doc = globalThis.document,
  host = globalThis.window,
  navigationOwner = () => host?.NavigationStability?.action?.('畅联云数据'),
  // A new URL on retry avoids a browser-cached failed ES module evaluation.
  load = attempt => import('./changlian-data-browser.js?v=63002&load_attempt=' + attempt),
} = {}) {
  const page = '畅联云数据';
  let runtime = null;
  let loadedModule = null;
  let pending = null;
  let generation = 0;
  let loadAttempt = 0;
  let destroyed = false;
  const state = () => getState?.() || {};
  const active = () => !destroyed && String(state().page || '') === page;

  function leave() {
    generation++;
    runtime?.leave?.();
  }
  function destroy() {
    if (destroyed) return;
    destroyed = true;
    generation++;
    runtime?.destroy?.();
  }

  function render() {
    if (!active()) return false;
    const invocation = ++generation;
    const projectId = String(state().project?.id || '');
    const owner = navigationOwner?.();
    const current = () => active() && invocation === generation
      && String(state().project?.id || '') === projectId
      && (!owner || owner.isCurrent());
    const mount = module => {
      if (!current()) return false;
      if (!runtime) runtime = module.installChangLianDataBrowserRuntime({
        getState, request, notify, modal, closeModal, document: doc,
      });
      return runtime.render();
    };
    if (runtime) return current() ? runtime.render() : false;
    if (loadedModule) return mount(loadedModule);

    const view = doc?.getElementById?.('view');
    if (view) view.innerHTML = '<section class="panel" data-cldb-lazy-loading><p role="status">正在打开畅联云数据…</p></section>';
    if (!pending) {
      pending = Promise.resolve().then(() => load(++loadAttempt))
        .then(module => {
          if (!module || typeof module.installChangLianDataBrowserRuntime !== 'function')
            throw new Error('远端数据模块缺少初始化入口');
          loadedModule = module;
          return module;
        }).finally(() => { pending = null; });
    }
    return pending.then(mount).catch(() => {
      if (!current()) return false;
      const liveView = doc?.getElementById?.('view');
      if (!liveView) return false;
      liveView.innerHTML = '<section class="panel" data-cldb-lazy-error><h3>畅联云数据暂不可用</h3><p>页面模块加载失败，请重试。</p><button type="button" class="btn" data-cldb-lazy-retry>重试</button></section>';
      const retry = liveView.querySelector?.('[data-cldb-lazy-retry]');
      if (retry) retry.onclick = () => { if (current()) void render(); };
      return false;
    });
  }

  const facade = {
    build: 'changlian-data-browser-lazy-13c03',
    page,
    render,
    leave,
    destroy,
    refresh() {
      if (!runtime) throw new Error('请先打开畅联云数据页面');
      return runtime.refresh();
    },
    snapshot: () => runtime?.snapshot?.() || {loaded:false,loading:false,products:[]},
    detailSnapshot: () => runtime?.detailSnapshot?.() || null,
    openWeightDetails(...args) { return runtime?.openWeightDetails?.(...args); },
  };
  if (host) host.ChangLianDataBrowserRuntime = facade;
  return facade;
}
