// Navigation presentation only; routing, lifecycle and project state stay in main.mjs.
// No listeners, timers, global registrations or new state owner.
export function createNavigationPresentation({
  getState, advancedPageInfo, advancedNavigation,
  documentRoot = globalThis.document, windowRoot = globalThis.window,
}) {
  function renderChrome() {
    const state = getState();
    const document = documentRoot;
    const window = windowRoot;
    const nav = document.getElementById('nav');
    const buttons = nav ? [...nav.querySelectorAll('.nav-btn')] : [];
    if (!nav || !buttons.length) {
      window.renderNav?.();
    } else {
      const currentPage = String(state.page || '');
      buttons.forEach(button => {
        const label = String(button.querySelector('.nav-left b')?.textContent || '').trim();
        button.classList.toggle('active', label === (advancedPageInfo(currentPage)?.title || currentPage));
      });
      const version = nav.querySelector('.nav-footer b');
      if (version) version.textContent = `v${String(state.versionInfo?.version || '—')}`;
    }
    window.renderTop?.();
    window.renderSummary?.();
    advancedNavigation.render();
  }

  function renderUnknown(page) {
    const document = documentRoot;
    renderChrome();
    const summary = document.getElementById('summary');
    const view = document.getElementById('view');
    if (summary) summary.innerHTML = '';
    if (view) view.innerHTML = `<section class="empty" data-unknown-page="${String(page || '').replace(/[&<>"']/g, '')}">当前页面不存在或已下线</section>`;
  }

  return Object.freeze({renderChrome,renderUnknown});
}
