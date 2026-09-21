import {installServiceNodeRuntime} from './modules/service-node-runtime.js?v=422536';

function boot() {
  if (window.__serviceNodeRuntimeInstalled) return;
  if (!document.getElementById('nav') || typeof window.setPage !== 'function') {
    window.setTimeout(boot, 50);
    return;
  }
  installServiceNodeRuntime({notify: message => window.toast?.(message)});
}

boot();
