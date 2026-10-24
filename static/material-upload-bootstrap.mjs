import {installImageUppyView} from './modules/uppy-image-view.js?v=20261023images';
import {installUploadConfirmationRuntime} from './modules/upload-confirmation.js?v=20261023images';
import {installMaterialUploadRuntime} from './modules/material-upload-runtime.js?v=422544';

const runtime = installMaterialUploadRuntime({
  getState: () => state,
  projectId: () => state.project?.id,
  notify: message => window.toast?.(message),
});
if (runtime && window.PlatformCore?.runtime) {
  window.PlatformCore.runtime.materialUploadRuntime = runtime;
}

const confirmation=installUploadConfirmationRuntime({
  getState:()=>state,api:(...args)=>api(...args),getContainer:()=>document.getElementById('view'),
  notify:message=>window.toast?.(message),previewImage:image=>window.previewData429?.(image.id,image),
});
installImageUppyView({getProjectId:()=>state.project?.id});
Promise.resolve(window.__v53InitPromise).then(()=>{
  if(state.page==='数据集'&&state.project?.id) return confirmation.restoreForProject(state.project.id);
}).catch(error=>window.toast?.(error.message));
