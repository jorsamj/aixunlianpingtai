import {installMaterialUploadRuntime} from './modules/material-upload-runtime.js?v=422530';

const runtime = installMaterialUploadRuntime({
  getState: () => state,
  projectId: () => state.project?.id,
  notify: message => window.toast?.(message),
});
if (runtime && window.PlatformCore?.runtime) {
  window.PlatformCore.runtime.materialUploadRuntime = runtime;
}
