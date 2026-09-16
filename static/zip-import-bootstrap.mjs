import {installZipImportRuntime} from './modules/zip-import-runtime.js?v=422530';

const runtime = installZipImportRuntime({
  getState: () => state,
  projectId: () => state.project?.id,
  notify: message => window.toast?.(message),
});
if (runtime && window.PlatformCore?.runtime) {
  window.PlatformCore.runtime.zipImportRuntime = runtime;
}
