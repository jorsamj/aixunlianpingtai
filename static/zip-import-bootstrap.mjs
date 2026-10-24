import {installZipImportRuntime} from './modules/zip-import-runtime.js?v=4226368';

const runtime = installZipImportRuntime({
  getState: () => state,
  projectId: () => state.project?.id,
  notify: message => window.toast?.(message),
});

if (runtime) {
  // The view loads on demand; this original runtime remains the transport owner.
  window.openUppyZipUpload = async () => {
    const chooser=document.getElementById('up426Zip');
    if (!state.project?.id) await window.__v53InitPromise;
    if (!state.project?.id) { window.toast?.('当前项目尚未加载完成，请稍后重试'); return null; }
    const projectId=state.project.id;
    const current=()=>state.project?.id===projectId&&(!chooser||chooser.isConnected);
    try {
      const {openUppyZipView} = await import('./modules/uppy-zip-view.js?v=4226366');
      if(!current())return null;
      const layer=chooser?.closest?.('.modal');
      if(layer){
        const top=[...document.querySelectorAll('.modal:not(.hidden)')].at(-1);
        if(top!==layer)return null;
        window.closeModalLayer424?.(layer);
      }
      return await openUppyZipView({runtime,projectId});
    } catch (error) {
      if(!current())return null;
      window.toast?.('ZIP组件加载失败，已回退原文件选择');
      document.getElementById('up426Zip')?.click();
      return null;
    }
  };

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
    return (async () => {
      // The bridge can be invoked programmatically before the first canonical
      // project snapshot has painted. Join that single readiness promise rather
      // than rejecting a valid file selection as "当前项目未加载".
      if (!state.project?.id) {
        const ready = window.__v53InitPromise || window.__clInit?.();
        if (ready) await ready;
      }
      if (!state.project?.id) {
        window.toast?.('当前项目尚未加载完成，请稍后重试');
        return null;
      }
      return runtime.uploadBatch(input).catch(error => {
        window.toast?.(`ZIP 批次处理失败：${error?.message || error}`);
        return null;
      });
    })();
  };
  durableUploadFromImportModal.__zipImportRuntimeBridge = true;
  window.doImportUploadV19 = durableUploadFromImportModal;

  window.ZipImportRuntimeLegacyBridge = Object.freeze({
    beforeStart: claimLegacyImportPolling,
    async afterStart() {
      await runtime.reconcile?.('legacy-start');
      claimLegacyImportPolling();
    },
  });
}

if (runtime && window.PlatformCore?.runtime) {
  window.PlatformCore.runtime.zipImportRuntime = runtime;
}
