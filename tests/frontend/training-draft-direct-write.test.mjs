import test from 'node:test';
import assert from 'node:assert/strict';

import {
  createTrainingDraft,
  trainingDraftFromLegacyState,
  trainingDraftToRequest,
  trainingInheritanceFromAlgorithm,
} from '../../static/modules/training-draft.js';
import {installTrainingDraftRuntime} from '../../static/modules/training-draft-runtime.js';

function dependencies() {
  return {
    createTrainingDraft,
    trainingDraftFromLegacyState,
    trainingDraftToRequest,
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

test('train-v3 material confirmation updates canonical draft before legacy callback runs', () => {
  setupDom();
  const state = {
    train428AlgorithmId: 'alg-1',
    trainSplitV3: {
      mode: 'independent_test_set',
      train: new Set(['old-train']),
      test: new Set(['shared', 'old-test']),
      validation: 20,
    },
    train428Config: {},
    trainingLabelSelected: new Set(['fire']),
    algorithms: [{id: 'alg-1', versions: []}],
    trainMaterialPickerV3: {role: 'train', selected: new Set(['new-a', 'shared'])},
  };
  let observedInsideLegacy;
  globalThis.window = {
    fetch: async () => ({ok: true}),
    confirmTrainMaterialPickerV3() {
      observedInsideLegacy = {
        materialIds: [...state.trainingDraft.materialIds],
        testMaterialIds: [...state.trainingDraft.testMaterialIds],
      };
    },
  };

  const runtime = installTrainingDraftRuntime({getState: () => state, ...dependencies()});
  runtime.sync();
  window.confirmTrainMaterialPickerV3();

  assert.deepEqual(observedInsideLegacy.materialIds, ['new-a', 'shared']);
  assert.deepEqual(observedInsideLegacy.testMaterialIds, ['old-test']);
  assert.deepEqual(state.trainingDraft.materialIds, ['new-a', 'shared']);
  assert.deepEqual(state.trainingDraft.testMaterialIds, ['old-test']);
  assert.deepEqual([...state.train429Selected], ['new-a', 'shared']);
  assert.equal(runtime.state().directWrites, 1);

  cleanup(runtime);
});

test('split mode writes canonical draft before legacy callback runs', () => {
  setupDom();
  const state = {
    train428AlgorithmId: 'alg-1',
    trainSplitV3: {
      mode: 'random_test_from_training_pool',
      train: new Set(['a']),
      test: new Set(),
      experiment: 20,
      validation: 20,
    },
    train428Config: {},
    trainingLabelSelected: new Set(['fire']),
    algorithms: [{id: 'alg-1', versions: []}],
  };
  let observedMode;
  globalThis.window = {
    fetch: async () => ({ok: true}),
    setTrainSplitModeV3() { observedMode = state.trainingDraft.splitMode; },
  };

  const runtime = installTrainingDraftRuntime({getState: () => state, ...dependencies()});
  runtime.sync();
  window.setTrainSplitModeV3('independent_test_set');

  assert.equal(observedMode, 'independent_test_set');
  assert.equal(state.trainingDraft.splitMode, 'independent_test_set');
  assert.equal(state.trainSplitV3.mode, 'independent_test_set');
  assert.equal(runtime.state().directWrites, 1);

  cleanup(runtime);
});

test('opening a different algorithm resets canonical training selection before legacy start runs', async () => {
  setupDom();
  const state = {
    train428AlgorithmId: 'alg-old',
    trainSplitV3: {
      mode: 'independent_test_set',
      train: new Set(['old-a']),
      test: new Set(['old-test']),
      validation: 25,
    },
    train428Config: {},
    trainingLabelSelected: new Set(['fire']),
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
  runtime.sync();
  await window.startAlgorithmTraining429('alg-new');

  assert.deepEqual(observedInsideLegacy, {
    algorithmId: 'alg-new',
    materials: [],
    tests: [],
    mode: 'random_test_from_training_pool',
  });
  assert.equal(state.trainingDraft.algorithmId, 'alg-new');
  assert.equal(runtime.state().directWrites, 1);

  cleanup(runtime);
});
