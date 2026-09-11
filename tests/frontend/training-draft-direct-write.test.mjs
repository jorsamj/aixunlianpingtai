import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

import {
  createTrainingDraft,
  trainingInheritanceFromAlgorithm,
} from '../../static/modules/training-draft.js';
import {installTrainingDraftRuntime} from '../../static/modules/training-draft-runtime.js';

function dependencies() {
  return {
    createTrainingDraft,
    trainingInheritanceFromAlgorithm,
  };
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

test('redundant classic callbacks are no longer wrapped by TrainingDraftRuntime because app.js owns canonical writes', () => {
  setupDom();
  const state = {
    trainingDraft: createTrainingDraft({algorithmId: 'alg-1', materialIds: ['a'], newLabelCodes: ['fire']}),
    algorithms: [{id: 'alg-1', versions: []}],
  };
  const original = {
    startAlgorithmTraining429() {},
    confirmTrainMaterialPickerV3() {},
    setTrainSplitModeV3() {},
    saveTrainSettings428() {},
  };
  globalThis.window = {fetch: async () => ({ok: true}), ...original};

  const runtime = installTrainingDraftRuntime({getState: () => state, ...dependencies()});
  assert.notEqual(window.startAlgorithmTraining429, original.startAlgorithmTraining429);
  assert.equal(window.confirmTrainMaterialPickerV3, original.confirmTrainMaterialPickerV3);
  assert.equal(window.setTrainSplitModeV3, original.setTrainSplitModeV3);
  assert.equal(window.saveTrainSettings428, original.saveTrainSettings428);

  const app = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
  const confirmAt = app.lastIndexOf('window.confirmTrainMaterialPickerV3=function(){');
  const splitAt = app.lastIndexOf('window.setTrainSplitModeV3=mode=>{');
  const saveAt = app.lastIndexOf('window.saveTrainSettings428=function(){');
  assert.ok(confirmAt >= 0 && app.slice(confirmAt, confirmAt + 1400).includes('TrainingDraftRuntime.update(patch)'));
  assert.ok(splitAt >= 0 && app.slice(splitAt, splitAt + 800).includes('TrainingDraftRuntime.update({splitMode'));
  assert.ok(saveAt >= 0 && app.slice(saveAt, saveAt + 1800).includes('TrainingDraftRuntime?.update?.({config:c})'));

  cleanup(runtime);
});

test('opening a different algorithm resets canonical training selection before legacy start runs', async () => {
  setupDom();
  const state = {
    train428AlgorithmId: 'alg-old',
    trainSplitV3: {mode: 'random_test_from_training_pool', train: new Set(['stale']), test: new Set(), experiment: 99, validation: 99},
    train428Config: {},
    trainingDraft: createTrainingDraft({
      algorithmId: 'alg-old', materialIds: ['old-a'], testMaterialIds: ['old-test'],
      splitMode: 'independent_test_set', validationPercent: 25, newLabelCodes: ['fire'],
    }),
    algorithms: [{id: 'alg-old', versions: []}, {id: 'alg-new', versions: []}],
  };
  let observedInsideLegacy;
  globalThis.window = {
    fetch: async () => ({ok: true}),
    async startAlgorithmTraining429() {
      observedInsideLegacy = {
        algorithmId: state.trainingDraft.algorithmId,
        materials: [...state.trainingDraft.materialIds],
        tests: [...state.trainingDraft.testMaterialIds],
        mode: state.trainingDraft.splitMode,
      };
    },
  };

  const runtime = installTrainingDraftRuntime({getState: () => state, ...dependencies()});
  await window.startAlgorithmTraining429('alg-new');

  assert.deepEqual(observedInsideLegacy, {
    algorithmId: 'alg-new', materials: [], tests: [], mode: 'random_test_from_training_pool',
  });
  assert.equal(state.trainingDraft.algorithmId, 'alg-new');
  assert.equal(state.train428AlgorithmId, 'alg-old');
  assert.deepEqual([...state.trainSplitV3.train], ['stale']);
  assert.equal(state.trainSplitV3.experiment, 99);
  assert.equal(runtime.state().directWrites, 1);

  cleanup(runtime);
});

