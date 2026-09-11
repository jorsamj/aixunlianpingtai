import test from 'node:test';
import assert from 'node:assert/strict';

import {
  createTrainingDraft,
  trainingDraftFromLegacyState,
  trainingDraftToRequest,
  trainingInheritanceFromAlgorithm,
} from '../../static/modules/training-draft.js';
import {installTrainingDraftRuntime} from '../../static/modules/training-draft-runtime.js';
import {TRAINING_DRAFT_CONTROL_IDS} from '../../static/modules/training-draft-controls.js';

function dependencies() {
  return {
    createTrainingDraft,
    trainingDraftFromLegacyState,
    trainingDraftToRequest,
    trainingInheritanceFromAlgorithm,
  };
}

test('direct train-v3 controls bypass legacy generic sync sampling', async () => {
  const listeners = new Map();
  globalThis.document = {
    addEventListener(type, handler) { listeners.set(type, handler); },
    removeEventListener(type, handler) { if (listeners.get(type) === handler) listeners.delete(type); },
    getElementById() { return null; },
    querySelectorAll() { return []; },
  };

  const state = {
    train428AlgorithmId: 'alg-1',
    trainSplitV3: {
      mode: 'random_test_from_training_pool',
      train: new Set(['img-1']),
      test: new Set(),
      experiment: 20,
      validation: 20,
    },
    train428Config: {queue_priority: 50},
    trainingDraft: {newLabelCodes: ['fire']},
    algorithms: [{id: 'alg-1', versions: []}],
  };
  globalThis.window = {fetch: async () => ({ok: true})};

  const runtime = installTrainingDraftRuntime({
    getState: () => state,
    directControlIds: TRAINING_DRAFT_CONTROL_IDS,
    ...dependencies(),
  });
  runtime.sync();
  runtime.update({experimentPercent: 35});
  assert.equal(state.trainingDraft.experimentPercent, 35);

  // Simulate a stale historical renderer mutating its compatibility mirror. The direct
  // control event must not cause TrainingDraftRuntime to sample that stale value back.
  state.trainSplitV3.experiment = 99;
  listeners.get('input')({
    target: {
      id: 'trV3Experiment',
      closest() { return {}; },
    },
  });
  await Promise.resolve();

  assert.equal(state.trainingDraft.experimentPercent, 35);
  assert.equal(runtime.state().directControlSkips, 1);
  assert.equal(Object.hasOwn(state, 'trainingLabelSelected'), false);

  runtime.destroy();
  delete globalThis.window;
  delete globalThis.document;
});
