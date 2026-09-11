import test from 'node:test';
import assert from 'node:assert/strict';

import {
  createTrainingDraft,
  trainingDraftFromLegacyState,
  trainingDraftToRequest,
  trainingInheritanceFromAlgorithm,
} from '../../static/modules/training-draft.js';
import {installTrainingDraftRuntime} from '../../static/modules/training-draft-runtime.js';

function setupDom(priority = '30') {
  const listeners = new Map();
  globalThis.document = {
    addEventListener(type, handler) { listeners.set(type, handler); },
    removeEventListener(type, handler) { if (listeners.get(type) === handler) listeners.delete(type); },
    getElementById(id) { return id === 'tr429Priority' ? {value: priority} : null; },
  };
  return listeners;
}

function dependencies() {
  return {
    createTrainingDraft,
    trainingDraftFromLegacyState,
    trainingDraftToRequest,
    trainingInheritanceFromAlgorithm,
  };
}

function cleanup(runtime) {
  runtime?.destroy();
  delete globalThis.window;
  delete globalThis.document;
}

test('runtime mirrors legacy train-v3 state into one canonical draft', () => {
  setupDom('25');
  const state = {
    train428AlgorithmId: 'alg-1',
    trainSplitV3: {
      mode: 'random_test_from_training_pool',
      train: new Set(['img-1', 'img-2']),
      test: new Set(),
      experiment: 20,
      validation: 15,
    },
    train428Config: {device: '0', batch: 16, workers: 4, cache: false},
    trainingLabelSelected: new Set(['person']),
    algorithms: [{
      id: 'alg-1',
      versions: [{
        id: 'v1', training_status: 'SUCCEEDED', artifact_verified: true, trainable: true,
        created_at: '2026-09-10T00:00:00Z',
        label_schema: [{class_id: 0, code: 'fire'}, {class_id: 1, code: 'smoke'}],
      }],
    }],
  };
  globalThis.window = {fetch: async () => ({ok: true})};

  const runtime = installTrainingDraftRuntime({getState: () => state, ...dependencies()});
  const draft = runtime.sync();

  assert.equal(state.trainingDraft, draft);
  assert.equal(draft.algorithmId, 'alg-1');
  assert.equal(draft.baseVersionId, 'v1');
  assert.deepEqual(draft.materialIds, ['img-1', 'img-2']);
  assert.deepEqual(draft.inheritedLabelCodes, ['fire', 'smoke']);
  assert.deepEqual(draft.newLabelCodes, ['person']);
  assert.deepEqual(draft.effectiveLabelCodes, ['fire', 'smoke', 'person']);
  assert.equal(draft.priority, 25);

  cleanup(runtime);
});

test('train start POST is canonicalized from TrainingDraft before it reaches the previous fetch chain', async () => {
  setupDom('35');
  const state = {
    train428AlgorithmId: 'alg-1',
    trainSplitV3: {
      mode: 'independent_test_set',
      train: new Set(['img-1', 'img-2']),
      test: new Set(['img-3']),
      validation: 20,
    },
    train428Config: {
      resource_strategy: 'manual', device: '0', gpu_policy: 'exclusive',
      batch: 16, workers: 4, cache: false,
    },
    trainingLabelSelected: new Set(['person']),
    algorithms: [{id: 'alg-1', versions: []}],
  };
  let sent;
  globalThis.window = {
    fetch: async (_input, init) => {
      sent = JSON.parse(init.body);
      return {ok: true};
    },
  };

  const runtime = installTrainingDraftRuntime({getState: () => state, ...dependencies()});
  await globalThis.window.fetch('/api/v12/projects/p1/train/start', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      algorithm_asset_id: 'alg-1',
      train_image_ids: ['stale-old'],
      test_image_ids: [],
      train_labels: ['stale-label'],
      framework: 'ultralytics',
    }),
  });

  assert.deepEqual(sent.train_image_ids, ['img-1', 'img-2']);
  assert.deepEqual(sent.test_image_ids, ['img-3']);
  assert.deepEqual(sent.train_labels, ['person']);
  assert.equal(sent.split_mode, 'independent_test_set');
  assert.equal(sent.device, '0');
  assert.equal(sent.batch, 16);
  assert.equal(sent.workers, 4);
  assert.equal(sent.cache, false);
  assert.equal(sent.queue_priority, 35);
  assert.equal(sent.framework, 'ultralytics');

  cleanup(runtime);
});

test('runtime refuses iteration when versions exist but none is successful and trainable', async () => {
  setupDom();
  const state = {
    train428AlgorithmId: 'alg-1',
    trainSplitV3: {train: new Set(['a', 'b']), test: new Set(), mode: 'random_test_from_training_pool', experiment: 20, validation: 20},
    trainingLabelSelected: new Set(['fire']),
    algorithms: [{
      id: 'alg-1',
      versions: [{id: 'bad', training_status: 'FAILED', artifact_verified: false}],
    }],
  };
  let called = false;
  globalThis.window = {fetch: async () => { called = true; return {ok: true}; }};

  const runtime = installTrainingDraftRuntime({getState: () => state, ...dependencies()});
  await assert.rejects(() => globalThis.window.fetch('/api/v12/projects/p1/train/start', {
    method: 'POST',
    body: JSON.stringify({algorithm_asset_id: 'alg-1'}),
  }), /不会回退母算法/);
  assert.equal(called, false);

  cleanup(runtime);
});
