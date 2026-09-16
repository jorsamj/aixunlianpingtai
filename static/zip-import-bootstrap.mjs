import {installZipImportRuntime} from './modules/zip-import-runtime.js?v=422530';

const runtime = installZipImportRuntime({
  getState: () => state,
  projectId: () => state.project?.id,
  notify: message => window.toast?.(message),
});

if (runtime) {
  const originalLoadImportJobs = window.loadImportJobs;
  const originalOpenImportDock = window.openImportDock;
  let reuseRuntimeSnapshot = true;

  const syncLegacyImportJobsFromRuntime = () => {
    const snapshot = runtime.snapshot?.() || {};
    state.importJobs = Array.isArray(snapshot.jobs) ? [...snapshot.jobs] : [];
    window.updateImportDock?.();
    return state.importJobs;
  };

  if (typeof originalLoadImportJobs === 'function' && !originalLoadImportJobs.__zipImportRuntimeBridge) {
    const bridgedLoadImportJobs = async function(...args) {
      if (reuseRuntimeSnapshot) {
        reuseRuntimeSnapshot = false;
        return syncLegacyImportJobsFromRuntime();
      }
      return originalLoadImportJobs.apply(this, args);
    };
    bridgedLoadImportJobs.__zipImportRuntimeBridge = true;
    window.loadImportJobs = bridgedLoadImportJobs;
  }

  if (typeof originalOpenImportDock === 'function' && !originalOpenImportDock.__zipImportRuntimeBridge) {
    const bridgedOpenImportDock = async function(...args) {
      reuseRuntimeSnapshot = true;
      return originalOpenImportDock.apply(this, args);
    };
    bridgedOpenImportDock.__zipImportRuntimeBridge = true;
    window.openImportDock = bridgedOpenImportDock;
  }
}

if (runtime && window.PlatformCore?.runtime) {
  window.PlatformCore.runtime.zipImportRuntime = runtime;
}
