import test from 'node:test';
import assert from 'node:assert/strict';

import {
  createTrainingDraft,
  trainingInheritanceFromAlgorithm,
} from '../../static/modules/training-draft.js';
import {installTrainingDraftRuntime} from '../../static/modules/training-draft-runtime.js';
import {TRAINING_DRAFT_CONTROL_IDS} from '../../static/modules/training-draft-controls.js';

function dependencies() {
  return {
    createTrainingDraft,
    trainingInheritanceFromAlgorithm,
  };
}

test('direct train-v3 controls bypass generic sampling from retired mirror-shaped fields', async () => {
  const listeners = new Map();
  globalThis.document = {
    addEventListener(type, handler) { listeners.set(type, handler); },
    removeEventListener(type, handler) { if (listeners.get(type) === handler) listeners.delete(type); },
    getElementById() { return null; },
    querySelectorAll() { return []; },
  };

  const state = {
    train428AlgorithmId: 'alg-1',
    train429Selected: new Set(['legacy-initial']),
    train428Config: {queue_priority: 50},
    trainingDraft: createTrainingDraft({
      algorithmId: 'alg-1',
      materialIds: ['img-1'],
      splitMode: 'random_test_from_training_pool',
      experimentPercent: 20,
      validationPercent: 20,
      newLabelCodes: ['fire'],
    }),
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
  assert.deepEqual(state.trainingDraft.materialIds, ['img-1']);
  assert.deepEqual([...state.train429Selected], ['legacy-initial']);

  // Simulate stale historical data being mutated outside the canonical owner. A direct
  // control event must not sample or rewrite that retired state.
  state.train429Selected = new Set(['stale-material']);
  listeners.get('input')({
    target: {
      id: 'trV3Experiment',
      closest() { return {}; },
    },
  });
  await Promise.resolve();

  assert.equal(state.trainingDraft.experimentPercent, 35);
  assert.deepEqual(state.trainingDraft.materialIds, ['img-1']);
  assert.deepEqual([...state.train429Selected], ['stale-material']);
  assert.equal(state.train428AlgorithmId, 'alg-1');
  assert.equal(state.train428Config.queue_priority, 50);
  assert.equal(runtime.state().directControlSkips, 1);

  runtime.destroy();
  delete globalThis.window;
  delete globalThis.document;
});
