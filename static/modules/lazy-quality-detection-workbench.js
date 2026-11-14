// 13C-04D: Quality Center detection bench is first needed on its 'detect' tab.
// Keep the classic synchronous render entry and the original bench task owners.
export function installLazyQualityDetectionWorkbench({
  getState,
  api,
  toast,
  modal,
  closeModal,
  esc,
  doc = globalThis.document,
  host = globalThis.window,
  navigationOwner = () => host?.NavigationStability?.action?.('质量中心'),
  load = attempt => import('./quality-detection-workbench.js?v=42.24.525&load_attempt=' + attempt),
} = {}) {
  let runtime = null;
  let module = null;
  let pending = null;
  let generation = 0;
  let attempt = 0;
  const currentState = () => getState?.() || {};
  const active = () => currentState().page === '质量中心'
    && currentState().qualityCenterTab411 === 'detect';

  function deactivate() {
    ++generation;
    runtime?.deactivate?.();
  }

  function placeholder(html) {
    const view = doc?.getElementById?.('view');
    if (!view) return null;
    let root = view.querySelector?.('[data-quality-detection-lazy]');
    if (!root) {
      // Classic renderQualityCenter424 prepends the existing quality tabs
      // directly after calling this synchronous presentation entry.
      view.innerHTML = '<section class="panel" data-quality-detection-lazy><div class="panel-body" data-quality-detection-lazy-body></div></section>';
      root = view.querySelector?.('[data-quality-detection-lazy]');
    }
    const body = root?.querySelector?.('[data-quality-detection-lazy-body]');
    if (body) body.innerHTML = html;
    return body || root;
  }

  function render() {
    if (!active()) return false;
    const ticket = ++generation;
    const projectId = String(currentState().project?.id || '');
    const owner = navigationOwner?.();
    const current = () => ticket === generation && active()
      && String(currentState().project?.id || '') === projectId
      && (!owner || owner.isCurrent());
    const mount = loaded => {
      if (!current()) return false;
      if (!runtime) runtime = loaded.installQualityDetectionWorkbench({
        getState, api, toast, modal, closeModal, esc,
      });
      if (!current()) return false;
      // The legacy quality-center caller prepends its tab bar synchronously.
      // On first lazy load, the real workbench replaces #view asynchronously;
      // reattach that exact tab bar so overview/detection navigation survives.
      const view = doc?.getElementById?.('view');
      const tabs = view?.querySelector?.('[data-quality-tabs="1"]');
      const rendered = runtime.render();
      if (tabs && current() && view === doc?.getElementById?.('view')
          && !view.querySelector?.('[data-quality-tabs="1"]')) {
        view.insertAdjacentElement('afterbegin', tabs);
      }
      return rendered;
    };

    if (runtime) return current() ? runtime.render() : false;
    if (module) return mount(module);

    placeholder('<p class="muted-line" role="status">正在打开场景算法实测…</p>');
    if (!pending) {
      pending = Promise.resolve().then(() => load(++attempt))
        .then(loaded => {
          if (!loaded || typeof loaded.installQualityDetectionWorkbench !== 'function')
            throw new Error('场景算法实测模块缺少初始化入口');
          module = loaded;
          return loaded;
        })
        .finally(() => { pending = null; });
    }
    return pending.then(mount).catch(() => {
      if (!current()) return false;
      const body = placeholder(
        '<h3>场景算法实测暂不可用</h3><p class="muted-line">页面模块加载失败，请重试。</p><button class="btn" type="button" data-quality-detection-retry>重试</button>'
      );
      const retry = body?.querySelector?.('[data-quality-detection-retry]');
      if (retry) retry.onclick = () => { if (current()) void render(); };
      return false;
    });
  }

  // Legacy app.js continues calling window.renderQualityDetectionBench64()
  // synchronously. The actual workbench may replace it after first import.
  const facade = {
    render, deactivate, destroy: deactivate,
    mountEvaluationEvidence(...args) {
      return runtime?.mountEvaluationEvidence?.(...args);
    },
    currentEvaluationSample() {
      return runtime?.currentEvaluationSample?.() || null;
    },
  };
  if (host) host.renderQualityDetectionBench64 = () => render();
  return facade;
}
