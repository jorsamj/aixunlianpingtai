import {actionRegistry, invokeAction, registerAction} from './modules/actions.js?v=421800';
import {messageFromApiError} from './modules/api.js?v=421800';
import {createModalStack} from './modules/modal.js?v=421800';
import {applyAnnotationResult} from './modules/annotation.js?v=422500';
import {installNegativeSampleRuntime} from './modules/negative-samples.js?v=422500';
import {installTrainingLabelRuntime} from './modules/training-labels.js?v=422502';
import {installNavigationStability} from './modules/navigation-stability.js?v=422500';
import {createAnnotationWorkbench, queueWindow} from './modules/annotation-workbench.js?v=422000';
import {createTaskPoller, isTaskActive, taskProgress} from './modules/task-poller.js?v=422000';
import {annotationTaskView, buildCandidateDecisions} from './modules/annotation-task-view.js?v=422000';
import {applyCleanConfirmation} from './modules/cleaning.js?v=421800';
import {activeLabelOptions} from './modules/labels.js?v=421800';
import {filterByAnyLabel, labelDisplay, labelsFromReferences, replaceMaterial} from './modules/materials.js?v=421800';
import {uploadBatchFromResponse} from './modules/upload.js?v=421800';
import {unwrapAlgorithmResponse} from './modules/algorithms.js?v=421800';
import {applyMaterialSelection, buildTrainingPayload, filterTrainingMaterials, iterationBasePresentation, projectedRandomSplit} from './modules/training.js?v=422101';
import {qualityChartModel} from './modules/quality.js?v=421800';
import {reportPresentation} from './modules/reports.js?v=421800';
import {isActiveVideoTask, normalizeVideoTask, videoTaskFormValues} from './modules/video-tasks.js?v=421900';
import {buildStorageSourcePayload, defaultStorageSource, enabledStorageSources, sourceMatches, storageSourceLabel} from './modules/storage.js?v=422202';
import {FULL_MATERIAL_PAGES, buildMaterialQuery, installMaterialPaginationRuntime, requiresFullMaterialPool} from './modules/material-pagination-runtime.js?v=422203';
import {installStorageImportProgressRuntime, storageImportProgressText} from './modules/storage-import-progress.js?v=422400';
import {buildServerImportRequest, buildImportConfirmation, pollServerImport, serverImportView} from './modules/server-material-import.js?v=422400';
import {installResourceDiscoveryRuntime} from './modules/resource-discovery.js?v=422400';
import {installMaterialBatchRuntime} from './modules/material-batches.js?v=422400';


const modalStack = createModalStack();

for (const page of ['测试发布', '部署测试', '自动迭代']) FULL_MATERIAL_PAGES.add(page);

registerAction('algorithm.create', () => {
  if (typeof window.openNewAlgorithm423 !== 'function') {
    throw new Error('创建算法功能尚未加载，请刷新页面后重试。');
  }
  return window.openNewAlgorithm423();
});

document.addEventListener('click', async event => {
  const target = event.target.closest('[data-action]');
  if (!target) return;
  event.preventDefault();
  try {
    await invokeAction(target.dataset.action, {event, target});
  } catch (error) {
    const message = messageFromApiError(error);
    if (typeof window.toast === 'function') window.toast(message);
    else console.error(message);
  }
});

window.PlatformCore = {
  actions: actionRegistry,
  modalStack,
  messageFromApiError,
  annotation: {applyAnnotationResult},
  annotationWorkbench: {createAnnotationWorkbench, queueWindow},
  taskPoller: {createTaskPoller, isTaskActive, taskProgress},
  annotationTasks: {annotationTaskView, buildCandidateDecisions},
  cleaning: {applyCleanConfirmation},
  labels: {activeLabelOptions},
  materials: {filterByAnyLabel, labelDisplay, labelsFromReferences, replaceMaterial},
  upload: {uploadBatchFromResponse},
  algorithms: {unwrapAlgorithmResponse},
  training: {applyMaterialSelection, buildTrainingPayload, filterTrainingMaterials, iterationBasePresentation, projectedRandomSplit},
  quality: {qualityChartModel},
  reports: {reportPresentation},
  video: {isActiveVideoTask, normalizeVideoTask, videoTaskFormValues},
  storage: {buildStorageSourcePayload, defaultStorageSource, enabledStorageSources, sourceMatches, storageSourceLabel},
  materialPaging: {buildMaterialQuery, requiresFullMaterialPool},
  storageImport: {storageImportProgressText},
  serverMaterialImport: {buildServerImportRequest, buildImportConfirmation, pollServerImport, serverImportView}
};

const notify = message => {
  if (typeof window.toast === 'function') window.toast(message);
  else {
    const toast = document.getElementById('toast');
    if (toast) {
      toast.textContent = message;
      toast.classList.remove('hidden');
      setTimeout(() => toast.classList.add('hidden'), 2600);
    }
  }
};

installNegativeSampleRuntime({
  getState: () => state,
  notify,
});
installTrainingLabelRuntime({
  getState: () => state,
  notify,
});
installMaterialPaginationRuntime();
installMaterialBatchRuntime({
  projectId: () => state.project?.id,
  currentPageIds: () => window.materialCurrentPageIds61?.() || [],
  selectedIds: () => window.materialSelectedIds61?.() || [],
  filteredSpec: () => window.materialBatchFilters61?.() || {},
  notify: message => window.toast?.(message),
  refresh: async () => {
    state.data412Selected?.clear?.();
    state.data412DeleteMode = false;
    if (state.page === '数据集') await window.reloadMaterialPage61?.();
  },
});
installStorageImportProgressRuntime();
window.installServerMaterialImport61?.();
installResourceDiscoveryRuntime(window.__resourceDiscoveryDependencies || {});

// Install last: legacy app.js contains multiple historical render/router layers.
// This fence makes the current route authoritative and repairs stale async DOM writes
// before they can leave the user on a visually different page.
installNavigationStability({
  getState: () => state,
  notify,
});

for (const delay of [80, 500, 1800, 3600]) {
  setTimeout(() => {
    const badge = document.getElementById('versionBadge');
    if (badge) badge.textContent = 'v42.24.0';
    const footer = document.querySelector('.nav-footer b');
    if (footer) footer.textContent = 'v42.24.0';
  }, delay);
}
