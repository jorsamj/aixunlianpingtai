import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

import {
  createTrainingDraft,
  trainingInheritanceFromAlgorithm,
} from '../../static/modules/training-draft.js';
import {installTrainingDraftRuntime} from '../../static/modules/training-draft-runtime.js';

function dependencies() {
  return {createTrainingDraft, trainingInheritanceFromAlgorithm};
}

function setupDom() {
  globalThis.document = {
    addEventListener() {},
    removeEventListener() {},
    getElementById() { return null; },
  };
}

function cleanup(runtime) {
  runtime?.destroy();
  delete globalThis.window;
  delete globalThis.document;
}

test('TrainingDraftRuntime is wrapper-free and leaves classic entrypoints untouched', () => {
  setupDom();
  const state = {
    trainingDraft: createTrainingDraft({algorithmId: 'alg-1', materialIds: ['a'], newLabelCodes: ['fire']}),
    algorithms: [{id: 'alg-1', versions: []}],
  };
  const originalStart = function startAlgorithmTraining429() {};
  const originalConfirm = function confirmTrainMaterialPickerV3() {};
  const originalSplit = function setTrainSplitModeV3() {};
  const originalSave = function saveTrainSettings428() {};
  globalThis.window = {
    fetch: async () => ({ok: true}),
    startAlgorithmTraining429: originalStart,
    confirmTrainMaterialPickerV3: originalConfirm,
    setTrainSplitModeV3: originalSplit,
    saveTrainSettings428: originalSave,
  };

  const runtime = installTrainingDraftRuntime({getState: () => state, ...dependencies()});
  assert.equal(window.startAlgorithmTraining429, originalStart);
  assert.equal(window.confirmTrainMaterialPickerV3, originalConfirm);
  assert.equal(window.setTrainSplitModeV3, originalSplit);
  assert.equal(window.saveTrainSettings428, originalSave);
  assert.equal(runtime.state().classicWrapperOwner, false);
  assert.equal(runtime.state().networkOwner, false);

  const source = readFileSync(new URL('../../static/modules/training-draft-runtime.js', import.meta.url), 'utf8');
  for (const token of ['wrapLegacyMutation', 'directMutationFor', 'mutationWrappers', 'startAlgorithmTraining429']) {
    assert.equal(source.includes(token), false);
  }

  cleanup(runtime);
});

test('app.js visible training entrypoint owns canonical reset before rendering the modal', () => {
  const app = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
  const canonicalOwner = app.indexOf('window.startAlgorithmTraining429=function(aid){const a=');
  const earlyAlias = app.indexOf('window.startAlgorithmTraining423=window.startAlgorithmTraining429;', canonicalOwner);
  assert.ok(canonicalOwner >= 0 && earlyAlias > canonicalOwner);
  const ownerSource = app.slice(canonicalOwner, earlyAlias);
  const canonicalWrite = ownerSource.indexOf('window.TrainingDraftRuntime?.update?.({algorithmId:String(aid),materialIds:[],testMaterialIds:[],splitMode:\'random_test_from_training_pool\',experimentPercent:20,validationPercent:20,newLabelCodes:[]})');
  const modalOpen = ownerSource.indexOf('modal(`训练 · ${a.name}`');
  assert.ok(canonicalWrite >= 0 && modalOpen > canonicalWrite);

  const stableCards = app.lastIndexOf('window.renderAlg412=function(){');
  const stablePage = app.lastIndexOf('window.renderAlgorithms423=function(){');
  assert.ok(stableCards >= 0 && stablePage > stableCards);
  const cardSource = app.slice(stableCards, stablePage);
  assert.match(cardSource, /startAlgorithmTraining429\('\$\{a\.id\}'\)/);
  assert.equal(cardSource.includes("startAlgorithmTraining423('${a.id}')"), false);
});

test('final classic picker split and settings actions own their canonical writes directly', () => {
  const app = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
  const confirmAt = app.lastIndexOf('window.confirmTrainMaterialPickerV3=function(){');
  const splitAt = app.lastIndexOf('window.setTrainSplitModeV3=mode=>{');
  const saveAt = app.lastIndexOf('window.saveTrainSettings428=function(){');
  assert.ok(confirmAt >= 0 && app.slice(confirmAt, confirmAt + 1400).includes('TrainingDraftRuntime.update(patch)'));
  assert.ok(splitAt >= 0 && app.slice(splitAt, splitAt + 800).includes('TrainingDraftRuntime.update({splitMode'));
  assert.ok(saveAt >= 0 && app.slice(saveAt, saveAt + 1800).includes('TrainingDraftRuntime?.update?.({config:c})'));
});
