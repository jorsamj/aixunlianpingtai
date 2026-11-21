// Advanced evaluation is only required by the Quality Center's advanced tab.
// Preserve the original mount/deactivate contract; real evaluation, GT and API
// owners remain in advanced-evaluation.js.
export function installLazyAdvancedEvaluation({
  getState,
  api,
  load = () => import('./advanced-evaluation.js?v=20261102-history'),
  doc = globalThis.document,
  navigationOwner = () => globalThis.window?.NavigationStability?.action?.('质量中心'),
} = {}) {
  let runtime = null;
  let pending = null;
  let generation = 0;
  const state = () => getState?.() || {};
  const active = () => state().page === '质量中心'
    && state().qualityCenterTab411 === 'advanced';

  function deactivate() {
    generation++;
    runtime?.deactivate?.();
  }

  function mount() {
    if (!active()) return false;
    const invocation = ++generation;
    const projectId = String(state().project?.id || '');
    const owner = navigationOwner?.();
    const current = () => invocation === generation && active()
      && String(state().project?.id || '') === projectId
      && (!owner || owner.isCurrent());
    if (runtime) return current() ? runtime.mount() : false;

    // Build the root synchronously so classic Quality Center can prepend its
    // existing tab row before the asynchronously loaded renderer starts.
    const view = doc?.getElementById('view');
    if (view && !view.querySelector('[data-advanced-evaluation]')) {
      view.innerHTML = '<div class="advanced-evaluation" data-advanced-evaluation><p class="muted-line" role="status">正在打开高级评测…</p></div>';
    }

    if (!pending) {
      pending = Promise.resolve().then(load)
        .then(module => {
          runtime = module.installAdvancedEvaluation({getState, api});
          return runtime;
        })
        .finally(() => { pending = null; });
    }
    return pending.then(loaded => {
      if (!current()) return false;
      loaded.mount();
      return true;
    }).catch(() => {
      if (!current()) return false;
      const root = doc?.querySelector?.('[data-advanced-evaluation]');
      if (!root) return false;
      root.innerHTML = '<section class="panel"><h3>高级评测暂不可用</h3><p class="muted-line">页面模块加载失败，请重试。</p><button type="button" class="btn" data-advanced-load-retry>重试</button></section>';
      const retry = root.querySelector('[data-advanced-load-retry]');
      if (retry) retry.onclick = () => { if (current()) void mount(); };
      return false;
    });
  }

  return {mount, deactivate};
}
