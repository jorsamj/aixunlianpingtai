import {installZipImportRuntime} from './modules/zip-import-runtime.js?v=422530';

const runtime = installZipImportRuntime({
  getState: () => state,
  projectId: () => state.project?.id,
  notify: message => window.toast?.(message),
});

if (runtime) {
  const originalLoadImportJobs = window.loadImportJobs;
  const originalOpenImportDock = window.openImportDock;
  const originalStartImportJobV19 = window.startImportJobV19;
  const LEGACY_IMPORT_POLL_SENTINEL = -1;
  let openingImportDock = false;

  const claimLegacyImportPolling = () => {
    const existing = state.importPollTimer;
    if (existing && existing !== LEGACY_IMPORT_POLL_SENTINEL) clearInterval(existing);
    state.importPollTimer = LEGACY_IMPORT_POLL_SENTINEL;
  };

  const syncLegacyImportJobsFromRuntime = () => {
    const snapshot = runtime.snapshot?.() || {};
    state.importJobs = Array.isArray(snapshot.jobs) ? [...snapshot.jobs] : [];
    window.updateImportDock?.();
    return state.importJobs;
  };

  // Durable ZIP runtime is the only completion/poll owner.  Keep the classic
  // timer slot truthy so legacy startImportPolling() cannot create a second
  // interval that would repeat completion side effects (labels/material refresh).
  claimLegacyImportPolling();

  if (typeof originalLoadImportJobs === 'function' && !originalLoadImportJobs.__zipImportRuntimeBridge) {
    const bridgedLoadImportJobs = async function(...args) {
      // Only the modal's initial open may reuse the already-fetched durable
      // snapshot.  A later user-triggered "刷新" must hit the backend again.
      if (openingImportDock) return syncLegacyImportJobsFromRuntime();
      return originalLoadImportJobs.apply(this, args);
    };
    bridgedLoadImportJobs.__zipImportRuntimeBridge = true;
    window.loadImportJobs = bridgedLoadImportJobs;
  }

  if (typeof originalOpenImportDock === 'function' && !originalOpenImportDock.__zipImportRuntimeBridge) {
    const bridgedOpenImportDock = async function(...args) {
      openingImportDock = true;
      try {
        return await originalOpenImportDock.apply(this, args);
      } finally {
        openingImportDock = false;
      }
    };
    bridgedOpenImportDock.__zipImportRuntimeBridge = true;
    window.openImportDock = bridgedOpenImportDock;
  }

  if (typeof originalStartImportJobV19 === 'function' && !originalStartImportJobV19.__zipImportRuntimeBridge) {
    const bridgedStartImportJobV19 = async function(...args) {
      claimLegacyImportPolling();
      const result = await originalStartImportJobV19.apply(this, args);
      await runtime.reconcile?.('legacy-start');
      claimLegacyImportPolling();
      return result;
    };
    bridgedStartImportJobV19.__zipImportRuntimeBridge = true;
    window.startImportJobV19 = bridgedStartImportJobV19;
  }
}

if (runtime && window.PlatformCore?.runtime) {
  window.PlatformCore.runtime.zipImportRuntime = runtime;
}
