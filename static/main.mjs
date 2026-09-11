import {actionRegistry, invokeAction, registerAction} from './modules/actions.js?v=421800';
import {messageFromApiError} from './modules/api.js?v=421800';
import {createModalStack} from './modules/modal.js?v=421800';
import {applyAnnotationResult} from './modules/annotation.js?v=422500';
import {installNegativeSampleRuntime} from './modules/negative-samples.js?v=422500';
import {installTrainingLabelRuntime} from './modules/training-labels.js?v=422508';
import {installNavigationStability} from './modules/navigation-stability.js?v=422503';
import {installPageRequestScope} from './modules/page-request-scope.js?v=422501';
import {installPollRegistry} from './modules/poll-registry.js?v=422507';
import {installAlgorithmListRuntime} from './modules/algorithm-list-runtime.js?v=422503';
import {installTrainingTaskRuntime} from './modules/training-task-runtime.js?v=422503';
import {createTrainingDraft, trainingDraftToRequest, trainingInheritanceFromAlgorithm} from './modules/training-draft.js?v=422506';
import {installTrainingDraftRuntime} from './modules/training-draft-runtime.js?v=422511';
import {TRAINING_DRAFT_CONTROL_IDS, installTrainingDraftControls} from './modules/training-draft-controls.js?v=422501';
import {buildTrainingEngineParameters, buildTrainingStartPayload, installTrainingSubmitRuntime, trainingSubmitReadiness, validateTrainingDevice} from './modules/training-submit.js?v=422504';
import {installAutoLabelPollRuntime} from './modules/auto-label-poll-runtime.js?v=422500';
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
import {FULL_MATERIAL_PAGES, buildMaterialQuery, installMaterialPaginationRuntime, requiresFullMaterialPool} from './modules/material-pagination-runtime.js?v=422205';
import {installStorageImportProgressRuntime, storageImportProgressText} from './modules/storage-import-progress.js?v=422400';
import {buildServerImportRequest, buildImportConfirmation, pollServerImport, serverImportView} from './modules/server-material-import.js?v=422400';
import {installResourceDiscoveryRuntime} from './modules/resource-discovery.js?v=422400';
import {installMaterialBatchRuntime} from './modules/material-batches.js?v=422400';

const UI_BUILD_VERSION = '42.25.0-dev';
const modalStack = createModalStack();

function fallbackToast(message) {
  const element = document.getElementById('toast');
  if (!element) return;
  element.textContent = String(message ?? '');
  element.classList.remove('hidden');
  clearTimeout(window.__toastTimer);
  window.__toastTimer = window.setTimeout(() => element.classList.add('hidden'), 2600);
}

if (typeof window.toast !== 'function') window.toast = fallbackToast;

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
    window.toast(messageFromApiError(error));
  }
});

const pageRequestScope = installPageRequestScope({
  getPage: () => state.page,
});
const pollRegistry = installPollRegistry({
  getState: () => state,
});
const trainingDraftRuntime = installTrainingDraftRuntime({
  getState: () => state,
  createTrainingDraft,
  trainingInheritanceFromAlgorithm,
  directControlIds: TRAINING_DRAFT_CONTROL_IDS,
});
const trainingDraftControlsRuntime = installTrainingDraftControls({trainingDraftRuntime});

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
  trainingDraft: {createTrainingDraft, trainingDraftToRequest, trainingInheritanceFromAlgorithm},
  trainingSubmit: {buildTrainingEngineParameters, buildTrainingStartPayload, trainingSubmitReadiness, validateTrainingDevice},
  quality: {qualityChartModel},
  reports: {reportPresentation},
  video: {isActiveVideoTask, normalizeVideoTask, videoTaskFormValues},
  storage: {buildStorageSourcePayload, defaultStorageSource, enabledStorageSources, sourceMatches, storageSourceLabel},
  materialPaging: {buildMaterialQuery, requiresFullMaterialPool},
  storageImport: {storageImportProgressText},
  serverMaterialImport: {buildServerImportRequest, buildImportConfirmation, pollServerImport, serverImportView},
  runtime: {pageRequestScope, pollRegistry, trainingDraftRuntime, trainingDraftControlsRuntime},
  uiBuildVersion: UI_BUILD_VERSION,
};

const notify = message => window.toast(message);

installNegativeSampleRuntime({
  getState: () => state,
  notify,
});
const trainingLabelRuntime = installTrainingLabelRuntime({
  getState: () => state,
  notify,
  trainingDraftRuntime,
});
window.PlatformCore.runtime.trainingLabelRuntime = trainingLabelRuntime;

const algorithmListRuntime = installAlgorithmListRuntime({
  getState: () => state,
  projectId: () => state.project?.id,
  notify,
});
window.PlatformCore.runtime.algorithmListRuntime = algorithmListRuntime;

const trainingTaskRuntime = installTrainingTaskRuntime({
  getState: () => state,
  projectId: () => state.project?.id,
  notify,
});
window.PlatformCore.runtime.trainingTaskRuntime = trainingTaskRuntime;

const trainingSubmitRuntime = installTrainingSubmitRuntime({
  getState: () => state,
  projectId: () => state.project?.id,
  trainingDraftRuntime,
  trainingDraftToRequest,
  reloadRelated: async () => {
    if (state.page === '算法列表' && algorithmListRuntime) {
      return algorithmListRuntime.refresh({render: false});
    }
    if (typeof loadRelated === 'function') return loadRelated();
    return window.loadRelated?.();
  },
  renderAlgorithms: () => {
    if (state.page === '算法列表' && algorithmListRuntime?.renderCards?.()) return true;
    if (typeof window.renderAlgorithms423 === 'function') return window.renderAlgorithms423();
    if (typeof renderAlgorithms423 === 'function') return renderAlgorithms423();
    return undefined;
  },
  closeModal: () => window.closeModal?.(),
  notify,
});
window.PlatformCore.runtime.trainingSubmitRuntime = trainingSubmitRuntime;

const autoLabelPollRuntime = installAutoLabelPollRuntime({
  getState: () => state,
  pollRegistry,
  annotationTaskView,
  notify,
});
window.PlatformCore.runtime.autoLabelPollRuntime = autoLabelPollRuntime;

installMaterialPaginationRuntime();
installMaterialBatchRuntime({
  projectId: () => state.project?.id,
  currentPageIds: () => window.materialCurrentPageIds61?.() || [],
  selectedIds: () => window.materialSelectedIds61?.() || [],
  filteredSpec: () => window.materialBatchFilters61?.() || {},
  notify,
  refresh: async () => {
    state.data412Selected?.clear?.();
    state.data412DeleteMode = false;
    if (state.page === '数据集') await window.reloadMaterialPage61?.();
  },
});
installStorageImportProgressRuntime();
window.installServerMaterialImport61?.();
installResourceDiscoveryRuntime(window.__resourceDiscoveryDependencies || {});

installNavigationStability({
  getState: () => state,
  notify,
  requestScope: pageRequestScope,
  pollRegistry,
});

function applyBuildVersion() {
  const badge = document.getElementById('versionBadge');
  if (badge) badge.textContent = `v${UI_BUILD_VERSION}`;
  const footer = document.querySelector('.nav-footer b');
  if (footer) footer.textContent = `v${UI_BUILD_VERSION}`;
  document.documentElement.dataset.uiBuild = UI_BUILD_VERSION;
}

applyBuildVersion();
for (const delay of [80, 500, 1800, 3600, 8000]) setTimeout(applyBuildVersion, delay);
