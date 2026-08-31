import {actionRegistry, invokeAction, registerAction} from './modules/actions.js?v=421800';
import {messageFromApiError} from './modules/api.js?v=421800';
import {createModalStack} from './modules/modal.js?v=421800';
import {applyAnnotationResult} from './modules/annotation.js?v=421800';
import {applyCleanConfirmation} from './modules/cleaning.js?v=421800';
import {activeLabelOptions} from './modules/labels.js?v=421800';
import {filterByAnyLabel, labelDisplay, labelsFromReferences, replaceMaterial} from './modules/materials.js?v=421800';
import {uploadBatchFromResponse} from './modules/upload.js?v=421800';
import {unwrapAlgorithmResponse} from './modules/algorithms.js?v=421800';
import {buildTrainingPayload, iterationBasePresentation, projectedRandomSplit} from './modules/training.js?v=422000';
import {qualityChartModel} from './modules/quality.js?v=421800';
import {reportPresentation} from './modules/reports.js?v=421800';
import {isActiveVideoTask, normalizeVideoTask, videoTaskFormValues} from './modules/video-tasks.js?v=421900';


const modalStack = createModalStack();

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
  cleaning: {applyCleanConfirmation},
  labels: {activeLabelOptions},
  materials: {filterByAnyLabel, labelDisplay, labelsFromReferences, replaceMaterial},
  upload: {uploadBatchFromResponse},
  algorithms: {unwrapAlgorithmResponse},
  training: {buildTrainingPayload, iterationBasePresentation, projectedRandomSplit},
  quality: {qualityChartModel},
  reports: {reportPresentation},
  video: {isActiveVideoTask, normalizeVideoTask, videoTaskFormValues}
};
