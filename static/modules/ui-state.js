export const UI_STATE_STORAGE_KEY = 'mc_train_ui_state_v34';

function readExisting(storage, key) {
  try {
    const raw = storage?.getItem?.(key);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
  } catch (_) {
    return {};
  }
}

const validNavigationId=value=>typeof value==='string'&&/^[A-Za-z0-9_.-]{1,128}$/.test(value);
export function safeVueNavigation(value,projectId){
  if(!value||!validNavigationId(projectId)||value.project_id!==projectId)return null;
  const result={project_id:projectId},selection=value.selection,report=value.report;
  if(validNavigationId(selection?.algorithmId)&&validNavigationId(selection?.versionId))result.selection={algorithmId:selection.algorithmId,versionId:selection.versionId};
  if(validNavigationId(report?.jobId)){
    result.report={jobId:report.jobId,returnPage:['tasks','assets','workbench'].includes(report.returnPage)?report.returnPage:'tasks'};
    if(validNavigationId(report.algorithmId))result.report.algorithmId=report.algorithmId;
    if(validNavigationId(report.versionId))result.report.versionId=report.versionId;
  }
  return result;
}
export function readVueNavigation(projectId,{storage=globalThis.localStorage,key=UI_STATE_STORAGE_KEY}={}){return safeVueNavigation(readExisting(storage,key).vueNavigation,projectId)}

export function persistUiState(state, {storage = globalThis.localStorage, key = UI_STATE_STORAGE_KEY, now = Date.now,vueNavigation} = {}) {
  if (!storage?.setItem) return null;
  const current = readExisting(storage, key);
  delete current.projectId;
  const next = {
    ...current,
    page: String(state?.page || current.page || ''),
    datasetId: String(state?.datasetId || current.datasetId || ''),
    imageFilter: String(state?.imageFilter || current.imageFilter || 'all'),
    ts: Number(now()),
  };
  if(vueNavigation!==undefined){const navigation=safeVueNavigation(vueNavigation,state?.project?.id);if(navigation)next.vueNavigation=navigation;else delete next.vueNavigation;}
  try {
    storage.setItem(key, JSON.stringify(next));
    return next;
  } catch (_) {
    return null;
  }
}
