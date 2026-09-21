import {installZipImportRuntime} from './modules/zip-import-runtime.js?v=422533';

const runtime = installZipImportRuntime({
  getState: () => state,
  projectId: () => state.project?.id,
  notify: message => window.toast?.(message),
});

if (runtime) {
  const originalStartImportJobV19 = window.startImportJobV19;
  const LEGACY_IMPORT_POLL_SENTINEL = -1;

  const claimLegacyImportPolling = () => {
    const existing = state.importPollTimer;
    if (existing && existing !== LEGACY_IMPORT_POLL_SENTINEL) clearInterval(existing);
    state.importPollTimer = LEGACY_IMPORT_POLL_SENTINEL;
  };

  // Durable ZIP runtime is the only completion/poll owner. Keep the classic
  // timer slot truthy so legacy startImportPolling() cannot create a second
  // interval that would repeat completion side effects (labels/material refresh).
  // The classic import-task modal deliberately keeps its own direct list request:
  // app.js calls loadImportJobs() through a lexical binding on open, so trying to
  // bridge only window.loadImportJobs would leave the bootstrap snapshot unconsumed
  // until the first user refresh and could serve stale state. Open/refresh therefore
  // always read the backend, while background polling stays exclusively runtime-owned.
  claimLegacyImportPolling();

  const durableUploadFromImportModal = () => {
    const input = document.getElementById('importFile');
    if (!input?.files?.length) {
      window.toast?.('请选择压缩包');
      return null;
    }
    return runtime.upload(input).catch(() => null);
  };
  durableUploadFromImportModal.__zipImportRuntimeBridge = true;
  window.doImportUploadV19 = durableUploadFromImportModal;

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
