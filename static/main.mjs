import {actionRegistry, invokeAction, registerAction} from './modules/actions.js?v=421800';
import {messageFromApiError} from './modules/api.js?v=421800';
import {createModalStack} from './modules/modal.js?v=421800';
import {applyAnnotationResult} from './modules/annotation.js?v=422500';
import {installNegativeSampleRuntime} from './modules/negative-samples.js?v=422544';
import {installTrainingLabelRuntime} from './modules/training-labels.js?v=422514';
import {installNavigationStability} from './modules/navigation-stability.js?v=422514';
import {persistUiState} from './modules/ui-state.js?v=422500';
import {installPageRequestScope} from './modules/page-request-scope.js?v=422502';
import {installPollRegistry} from './modules/poll-registry.js?v=422521';
import {installAlgorithmListRuntime} from './modules/algorithm-list-runtime.js?v=422504';
import {installExternalAlgorithmPlatformRuntime} from './modules/external-algorithm-platform.js?v=63018';
import {installExternalAlgorithmPublishRuntime} from './modules/external-algorithm-publish.js?v=64003';
import {installModelArtifactRuntime} from './modules/model-artifact-runtime.js?v=65005';
import {installTrainingRecoveryRuntime} from './modules/training-recovery-runtime.js?v=422506';
import {installTrainingMaterialPickerRuntime} from './modules/training-material-picker-runtime.js?v=422547';
import {installTrainingMaterialSummaryRuntime} from './modules/training-material-summary-runtime.js?v=422500';
import {installTrainingTaskRuntime} from './modules/training-task-runtime.js?v=422548';
import {installTrainingProgressStream} from './modules/training-progress-stream.js?v=422500';
import {createTrainingDraft, trainingDraftToRequest, trainingInheritanceFromAlgorithm} from './modules/training-draft.js?v=422507';
import {installTrainingDraftRuntime} from './modules/training-draft-runtime.js?v=422516';
import {TRAINING_DRAFT_CONTROL_IDS, installTrainingDraftControls} from './modules/training-draft-controls.js?v=422501';
import {buildTrainingEngineParameters, buildTrainingStartPayload, installTrainingSubmitRuntime, trainingSubmitReadiness, validateTrainingDevice} from './modules/training-submit.js?v=422506';
import {installTrainingCreateHydrationRuntime} from './modules/training-create-hydration.js?v=422550';
import {installAutoLabelPollRuntime} from './modules/auto-label-poll-runtime.js?v=422503';
import {createAnnotationWorkbench, queueWindow} from './modules/annotation-workbench.js?v=422549';
import {createTaskPoller, isTaskActive, taskProgress, waitForTaskTerminal} from './modules/task-poller.js?v=422002';
import {annotationTaskView, buildCandidateDecisions} from './modules/annotation-task-view.js?v=422002';
import {applyCleanConfirmation, cleanExecutionChoices, cleanExecutionMode, cleanTaskView, isActiveCleanTask} from './modules/cleaning.js?v=422518';
import {deploymentTaskView} from './modules/deployment-tests.js?v=422518';
import {activeLabelOptions} from './modules/labels.js?v=421800';
import {filterByAnyLabel, labelDisplay, labelsFromReferences, replaceMaterial} from './modules/materials.js?v=421800';
import {uploadBatchFromResponse} from './modules/upload.js?v=421800';
import {unwrapAlgorithmResponse} from './modules/algorithms.js?v=421800';
import {applyMaterialSelection, buildTrainingPayload, filterTrainingMaterials, iterationBasePresentation, projectedRandomSplit} from './modules/training.js?v=422101';
import {qualityChartModel} from './modules/quality.js?v=421800';
import {reportPresentation} from './modules/reports.js?v=421800';
import {isActiveVideoTask, normalizeVideoTask, videoTaskFormValues} from './modules/video-tasks.js?v=421900';
import {buildStorageSourcePayload, defaultStorageSource, enabledStorageSources, sourceMatches, storageSourceLabel} from './modules/storage.js?v=422202';
import {FULL_MATERIAL_PAGES, buildMaterialQuery, installMaterialPaginationRuntime, requiresFullMaterialPool} from './modules/material-pagination-runtime.js?v=422214';
import {installStorageImportProgressRuntime, storageImportProgressText} from './modules/storage-import-progress.js?v=422525';
import {installUploadTaskCenter} from './modules/upload-task-center.js?v=66008';
import {buildServerImportRequest, buildImportConfirmation, serverImportView} from './modules/server-material-import.js?v=422526';
import {installResourceDiscoveryRuntime} from './modules/resource-discovery.js?v=422401';
import {installServiceNodeRuntime} from './modules/service-node-runtime.js?v=422548';
import {installMaterialBatchRuntime} from './modules/material-batches.js?v=422402';

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

// Training owns its own paged material picker/summary and must never request the whole image pool.
FULL_MATERIAL_PAGES.delete('训练任务');
for (const page of ['自动迭代']) FULL_MATERIAL_PAGES.add(page);

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

const pageRequestScope = installPageRequestScope({getPage: () => state.page});
const pollRegistry = installPollRegistry({getState: () => state});
const trainingDraftRuntime = installTrainingDraftRuntime({
  getState: () => state,
  createTrainingDraft,
  trainingInheritanceFromAlgorithm,
  directControlIds: TRAINING_DRAFT_CONTROL_IDS,
});
const trainingDraftControlsRuntime = installTrainingDraftControls({trainingDraftRuntime});

window.PlatformCore = {
  navigation: window.PlatformCore?.navigation || {},
  actions: actionRegistry,
  modalStack,
  messageFromApiError,
  annotation: {applyAnnotationResult},
  annotationWorkbench: {createAnnotationWorkbench, queueWindow},
  taskPoller: {createTaskPoller, isTaskActive, taskProgress, waitForTaskTerminal},
  annotationTasks: {annotationTaskView, buildCandidateDecisions},
  cleaning: {applyCleanConfirmation, cleanExecutionChoices, cleanExecutionMode, cleanTaskView, isActiveCleanTask},
  deployment: {deploymentTaskView},
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
  serverMaterialImport: {buildServerImportRequest, buildImportConfirmation, serverImportView},
  runtime: {pageRequestScope, pollRegistry, trainingDraftRuntime, trainingDraftControlsRuntime},
  uiBuildVersion: UI_BUILD_VERSION,
};

const notify = message => window.toast(message);
installNegativeSampleRuntime({getState: () => state, notify});

const trainingMaterialSummaryRuntime = installTrainingMaterialSummaryRuntime({
  getState: () => state,
  projectId: () => state.project?.id,
  trainingDraftRuntime,
  notify,
});
window.PlatformCore.runtime.trainingMaterialSummaryRuntime = trainingMaterialSummaryRuntime;

const trainingLabelRuntime = installTrainingLabelRuntime({
  getState: () => state,
  notify,
  trainingDraftRuntime,
  materialSummaryRuntime: trainingMaterialSummaryRuntime,
});
window.PlatformCore.runtime.trainingLabelRuntime = trainingLabelRuntime;

const algorithmListRuntime = installAlgorithmListRuntime({
  getState: () => state,
  projectId: () => state.project?.id,
  notify,
});
window.PlatformCore.runtime.algorithmListRuntime = algorithmListRuntime;

const externalAlgorithmPlatformRuntime = installExternalAlgorithmPlatformRuntime({
  getState: () => state,
  projectId: () => state.project?.id,
  notify,
  algorithmListRuntime,
});
window.PlatformCore.runtime.externalAlgorithmPlatformRuntime = externalAlgorithmPlatformRuntime;

const externalAlgorithmPublishRuntime = installExternalAlgorithmPublishRuntime({
  getState: () => state,
  projectId: () => state.project?.id,
  notify,
  algorithmListRuntime,
});
window.PlatformCore.runtime.externalAlgorithmPublishRuntime = externalAlgorithmPublishRuntime;

const modelArtifactRuntime = installModelArtifactRuntime({
  getState: () => state,
  notify,
  pollRegistry,
});
window.PlatformCore.runtime.modelArtifactRuntime = modelArtifactRuntime;

const trainingRecoveryRuntime = installTrainingRecoveryRuntime({
  getState: () => state,
  projectId: () => state.project?.id,
  notify,
});
window.PlatformCore.runtime.trainingRecoveryRuntime = trainingRecoveryRuntime;

const trainingMaterialPickerRuntime = installTrainingMaterialPickerRuntime({
  getState: () => state,
  projectId: () => state.project?.id,
  trainingDraftRuntime,
  notify,
});
window.PlatformCore.runtime.trainingMaterialPickerRuntime = trainingMaterialPickerRuntime;

const trainingTaskRuntime = installTrainingTaskRuntime({
  getState: () => state,
  projectId: () => state.project?.id,
  notify,
  recoveryRuntime: trainingRecoveryRuntime,
});
window.PlatformCore.runtime.trainingTaskRuntime = trainingTaskRuntime;

const trainingProgressStreamRuntime = installTrainingProgressStream({
  getState: () => state,
  projectId: () => state.project?.id,
  trainingTaskRuntime,
  pollRegistry,
});
window.PlatformCore.runtime.trainingProgressStreamRuntime = trainingProgressStreamRuntime;

const trainingSubmitRuntime = installTrainingSubmitRuntime({
  getState: () => state,
  projectId: () => state.project?.id,
  trainingDraftRuntime,
  trainingDraftToRequest,
  trainingTaskRuntime,
  reloadRelated: async () => {
    if (state.page === '算法列表' && algorithmListRuntime) return algorithmListRuntime.refresh({render: false});
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

const trainingCreateHydrationRuntime = installTrainingCreateHydrationRuntime({
  getState: () => state,
  projectId: () => state.project?.id,
  request: api,
  preflight: algorithmId => externalAlgorithmPlatformRuntime.preflightTraining(algorithmId, {request: api}),
  preflightFresh: algorithmId => externalAlgorithmPlatformRuntime.trainingPreflightFresh(algorithmId),
  openTrainingForm: window.openTrainingCreateCanonical429,
  notify,
});
window.PlatformCore.runtime.trainingCreateHydrationRuntime = trainingCreateHydrationRuntime;

const autoLabelPollRuntime = installAutoLabelPollRuntime({
  getState: () => state,
  pollRegistry,
  annotationTaskView,
  loadTasks: () => {
    if (typeof window.refreshAnnotationTasks60 !== 'function') throw new Error('AI标注任务数据加载器尚未就绪');
    return window.refreshAnnotationTasks60();
  },
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
  pollRegistry,
  refresh: async () => {
    state.data412Selected?.clear?.();
    state.data412DeleteMode = false;
    if (state.page === '数据集') await window.reloadMaterialPage61?.();
  },
});
window.installServerMaterialImport61?.();
const uploadTaskCenterRuntime = installUploadTaskCenter({
  getState: () => state,
  projectId: () => state.project?.id,
  notify,
  pollRegistry,
  ownerPages: window.PlatformCore?.navigation?.knownPages || [],
});
window.PlatformCore.runtime.uploadTaskCenterRuntime = uploadTaskCenterRuntime;
const storageImportProgressRuntime = installStorageImportProgressRuntime({pollRegistry, getState: () => state});
window.PlatformCore.runtime.storageImportProgressRuntime = storageImportProgressRuntime;
const resourceDiscoveryRuntime = installResourceDiscoveryRuntime({...window.__resourceDiscoveryDependencies, pollRegistry});
window.PlatformCore.runtime.resourceDiscoveryRuntime = resourceDiscoveryRuntime;

function renderNavigationChrome() {
  const nav = document.getElementById('nav');
  const buttons = nav ? [...nav.querySelectorAll('.nav-btn')] : [];
  if (!nav || !buttons.length) {
    window.renderNav?.();
  } else {
    const currentPage = String(state.page || '');
    buttons.forEach(button => {
      const label = String(button.querySelector('.nav-left b')?.textContent || '').trim();
      button.classList.toggle('active', label === currentPage);
    });
    const project = nav.querySelector('.nav-project-v');
    if (project) project.textContent = state.project?.name || '默认空间';
  }
  window.renderTop?.();
  window.renderSummary?.();
}

function applyPostRenderNormalization(page) {
  if (String(state.page || '') !== String(page || '')) return;
  window.PostRenderNormalizationRuntime?.apply?.(document.getElementById('view'));
}

function renderCanonicalOwner(page, {source = 'canonical-router'} = {}) {
  const normalizedPage = String(page || state.page || '');
  renderNavigationChrome();
  const result = navigationStabilityRuntime.renderPage(normalizedPage, {source});
  if (result && typeof result.then === 'function') {
    return result.finally(() => applyPostRenderNormalization(normalizedPage));
  }
  applyPostRenderNormalization(normalizedPage);
  return result;
}

function renderUnknownPage(page) {
  renderNavigationChrome();
  const summary = document.getElementById('summary');
  const view = document.getElementById('view');
  if (summary) summary.innerHTML = '';
  if (view) view.innerHTML = `<section class="empty" data-unknown-page="${String(page || '').replace(/[&<>"']/g, '')}">当前页面不存在或已下线</section>`;
}

const PAGE_EXTRAS_CACHE_TTL_MS = 5 * 60 * 1000;
const pageExtrasLoadedAt = new Map();
const pageExtrasInflight = new Map();
const PAGE_EXTRAS_OWNERS = new Set(['训练任务', '训练资源', '部署转换', '部署产物']);

function adoptPageExtrasInflight(page, promise) {
  if (!PAGE_EXTRAS_OWNERS.has(page) || !promise || typeof promise.then !== 'function') return null;
  if (pageExtrasInflight.has(page)) return pageExtrasInflight.get(page);
  const task = Promise.resolve(promise)
    .then(() => { pageExtrasLoadedAt.set(page, Date.now()); })
    .catch(error => notify(error?.message || error))
    .finally(() => pageExtrasInflight.delete(page));
  pageExtrasInflight.set(page, task);
  return task;
}

function refreshPageExtrasInBackground(page, {force = false} = {}) {
  if (!PAGE_EXTRAS_OWNERS.has(page) || typeof window.loadPageExtras413 !== 'function') return null;
  const snapshotLoadedAt = Number(state.__coreSnapshotGeneratedAt || 0);
  const loadedAt = Number(pageExtrasLoadedAt.get(page) || snapshotLoadedAt || 0);
  const age = Date.now() - loadedAt;
  if (!force && loadedAt > 0 && age >= 0 && age < PAGE_EXTRAS_CACHE_TTL_MS) return null;
  if (pageExtrasInflight.has(page)) return pageExtrasInflight.get(page);
  const task = Promise.resolve(window.loadPageExtras413(page)).then(() => {
    pageExtrasLoadedAt.set(page, Date.now());
    if (state.page !== page) return;
    if (navigationStabilityRuntime.hasPageOwner(page)) {
      renderCanonicalOwner(page, {source: 'background-data'});
    } else {
      render();
    }
  }).catch(error => notify(error?.message || error)).finally(() => pageExtrasInflight.delete(page));
  pageExtrasInflight.set(page, task);
  return task;
}

const ALGORITHM_PAGE_ENTRY_REUSE_MS = 30 * 1000;

function refreshCurrentPageOwner(page) {
  trainingProgressStreamRuntime?.syncPage?.(page);
  void refreshPageExtrasInBackground(page);
  if (page === '存储配置') {
    const task = window.StorageCacheRuntime?.refresh?.({
      sources: window.getStorageSourcesSnapshot61?.() || [],
      force: false,
    });
    if (task && typeof task.catch === 'function') void task.catch(error => notify(error?.message || error));
  }
  if (page === '部署转换' && typeof window.refreshDeployJobsForVisitV39 === 'function') {
    void window.refreshDeployJobsForVisitV39().catch(error => notify(error?.message || error));
  }
  if (page === '数据集' || page === '自动标注及清洗') {
    window.MaterialBatchRuntime62?.resume?.();
  }
  if (page === '训练任务') {
    void trainingTaskRuntime.refresh({render: true, force: false, source: 'page-owner'}).then(result => {
      if (!result?.stale) pollRegistry?.replaceTrainingJobTimer?.();
    }).catch(error => notify(error?.message || error));
    return;
  }
  if (page !== '算法列表') return;
  const snapshotAge = Date.now() - Number(state.__coreSnapshotGeneratedAt || 0);
  if (snapshotAge >= 0 && snapshotAge < ALGORITHM_PAGE_ENTRY_REUSE_MS) return;
  void algorithmListRuntime.refresh({render: true, minAgeMs: ALGORITHM_PAGE_ENTRY_REUSE_MS}).catch(error => notify(error?.message || error));
}

const navigationStabilityRuntime = installNavigationStability({
  getState: () => state,
  notify,
  requestScope: pageRequestScope,
  pollRegistry,
  persistNavigationState: currentState => persistUiState(currentState),
  waitForNavigationReady: () => {
    if (!state.uiReady && window.__v53InitPromise) return window.__v53InitPromise;
    return null;
  },
  beforeInvokeNavigation: () => window.toggleMobileSidebarV37?.(false),
  knownPages: window.PlatformCore?.navigation?.knownPages || [],
  performNavigation: page => {
    const materialNavigation = window.MaterialPaginationRuntime61?.beforeNavigate?.(page);
    state.page = page;
    uploadTaskCenterRuntime.switchProject?.();
    if (navigationStabilityRuntime.hasPageOwner(page)) {
      renderCanonicalOwner(page, {source: 'navigation'});
    } else if (navigationStabilityRuntime.isKnownPage(page)) {
      render();
    } else {
      renderUnknownPage(page);
    }
    window.MaterialPaginationRuntime61?.afterNavigate?.(page, materialNavigation);
    refreshCurrentPageOwner(page);
  },
});
window.PlatformCore.runtime.navigationStabilityRuntime = navigationStabilityRuntime;

// Core product pages now have one navigation owner each. Historical app.js
// renderers remain compatibility entry points, but navigation no longer walks
// through the chained render() override stack.
const canonicalWindowPageRenderers = new Map([
  ['工作台', 'renderDashboardCanonical422'],
  ['质量中心', 'renderQualityCenter424'],
  ['素材接入', 'renderSources422'],
  ['标签管理', 'renderLabelManagement414'],
  ['模型配置', 'renderModelConfigPageV35'],
  ['训练资源', 'renderResources'],
  ['部署转换', 'renderDeployCenter'],
  ['部署产物', 'renderDeployArtifacts'],
  ['部署资源', 'renderDeployResources'],
  ['部署插件', 'renderDeployPluginsV41'],
  ['存储配置', 'renderStorageSources61'],
]);
const canonicalWindowPageOwners = [...canonicalWindowPageRenderers].map(([page, rendererName]) => (
  navigationStabilityRuntime.registerPageOwner(page, () => {
    const renderer = window[rendererName];
    if (typeof renderer !== 'function') throw new Error(`${page} 页面模块尚未就绪`);
    return renderer();
  })
));
const canonicalPageOwnerDisposers = [
  ...canonicalWindowPageOwners,
  navigationStabilityRuntime.registerPageOwner('算法列表', () => algorithmListRuntime?.renderCards?.()),
  navigationStabilityRuntime.registerPageOwner('训练任务', () => {
    if (window.TrainingTaskVisibilityRuntime?.render) return window.TrainingTaskVisibilityRuntime.render();
    return window.renderTraining423?.();
  }),
  navigationStabilityRuntime.registerPageOwner('数据集', () => window.renderDatasets424?.()),
  navigationStabilityRuntime.registerPageOwner('自动标注及清洗', () => {
    if (typeof window.renderOps427 === 'function') return window.renderOps427();
    return window.renderAutoLabel422?.();
  }),
  navigationStabilityRuntime.registerPageOwner('视频切帧', () => {
    if (typeof window.renderVideo424 === 'function') return window.renderVideo424();
    return window.renderVideoFrameTasks?.();
  }),
];
window.PlatformCore.runtime.canonicalPageOwners = {
  destroy() { canonicalPageOwnerDisposers.splice(0).forEach(dispose => dispose?.()); },
};

// External platform integration is a canonical business page. Own it directly
// instead of falling through the historical render override chain.
const unregisterExternalPlatformPageOwner = navigationStabilityRuntime.registerPageOwner('平台对接', () => (
  externalAlgorithmPlatformRuntime?.render?.({reload: true})
));
window.PlatformCore.runtime.externalPlatformPageOwner = {
  destroy() { unregisterExternalPlatformPageOwner?.(); },
};

// Component detection is a canonical business page. Own it directly instead of
// depending on the historical app.js render override chain racing with navigation.
const unregisterComponentPageOwner = navigationStabilityRuntime.registerPageOwner('组件检测', () => (
  window.renderComponentCheckV40?.()
));
window.PlatformCore.runtime.componentPageOwner = {
  destroy() { unregisterComponentPageOwner?.(); },
};

const serviceNodeRuntime = installServiceNodeRuntime({notify});
window.PlatformCore.runtime.serviceNodeRuntime = serviceNodeRuntime;

// Retire the historical app.js render override chain from active runtime.
// Legacy render remains only as a fallback for pages that have not migrated yet.
const legacyRenderFallback = window.render;
window.render = function canonicalRenderBridge() {
  const page = String(state.page || '');
  if (navigationStabilityRuntime.hasPageOwner(page)) {
    return renderCanonicalOwner(page, {source: 'compat-render'});
  }
  return legacyRenderFallback?.();
};
window.PlatformCore.runtime.renderRouter = {
  renderCurrent(source = 'runtime') {
    const page = String(state.page || '');
    if (navigationStabilityRuntime.hasPageOwner(page)) return renderCanonicalOwner(page, {source});
    return legacyRenderFallback?.();
  },
};

const canonicalStartupPromise = window.__clInit?.();
Promise.resolve(canonicalStartupPromise).then(() => {
  const startupPage = String(state.page || '');
  adoptPageExtrasInflight(startupPage, state.__extras412);
  if (!state.__startupCanonicalPainted && navigationStabilityRuntime.hasPageOwner(startupPage)) {
    void renderCanonicalOwner(startupPage, {source: 'startup-owner'});
    state.__startupCanonicalPainted = true;
  }
  refreshCurrentPageOwner(startupPage);
});

document.documentElement.dataset.uiBuild = UI_BUILD_VERSION;
