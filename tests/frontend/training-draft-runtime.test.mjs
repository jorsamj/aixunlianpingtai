import test from 'node:test';
import assert from 'node:assert/strict';

import {
  createTrainingDraft,
  trainingDraftFromLegacyState,
  trainingDraftToRequest,
  trainingInheritanceFromAlgorithm,
} from '../../static/modules/training-draft.js';
import {installTrainingDraftRuntime} from '../../static/modules/training-draft-runtime.js';

function setupDom(values = {}) {
  const listeners = new Map();
  const controls = {
    tr429Priority: '30',
    ...values,
  };
  globalThis.document = {
    addEventListener(type, handler) { listeners.set(type, handler); },
    removeEventListener(type, handler) { if (listeners.get(type) === handler) listeners.delete(type); },
    getElementById(id) {
      return Object.hasOwn(controls, id) ? {value: controls[id]} : null;
    },
  };
  return {listeners, controls};
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

test('runtime maps legacy structural state while keeping labels canonical', () => {
  setupDom({tr429Priority: '25'});
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
    trainingDraft: {newLabelCodes: ['person']},
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
  assert.equal(Object.hasOwn(state, 'trainingLabelSelected'), false);

  cleanup(runtime);
});

test('live train-v3 controls override stale legacy state and are mirrored back', () => {
  setupDom({
    tr429Priority: '7',
    trV3Experiment: '35',
    trV3Validation: '18',
    trV3ResourceStrategy: 'manual',
    trV3Device: '0',
    trV3GpuPolicy: 'exclusive',
  });
  const state = {
    train428AlgorithmId: 'alg-1',
    trainSplitV3: {
      mode: 'random_test_from_training_pool',
      train: new Set(['img-1', 'img-2']),
      test: new Set(),
      experiment: 20,
      validation: 20,
    },
    train428Config: {
      resource_strategy: 'auto', device: 'cpu', gpu_policy: 'auto',
      batch: 16, workers: 4, cache: false, queue_priority: 50,
    },
    trainingDraft: {newLabelCodes: ['fire']},
    algorithms: [{id: 'alg-1', versions: []}],
  };
  globalThis.window = {fetch: async () => ({ok: true})};

  const runtime = installTrainingDraftRuntime({getState: () => state, ...dependencies()});
  const draft = runtime.sync();

  assert.equal(draft.experimentPercent, 35);
  assert.equal(draft.validationPercent, 18);
  assert.equal(draft.priority, 7);
  assert.deepEqual(draft.resource, {
    strategy: 'manual', device: '0', gpuPolicy: 'exclusive', batch: 16, workers: 4, cache: false,
  });
  assert.equal(state.trainSplitV3.experiment, 35);
  assert.equal(state.trainSplitV3.validation, 18);
  assert.equal(state.train428Config.resource_strategy, 'manual');
  assert.equal(state.train428Config.device, '0');
  assert.equal(state.train428Config.gpu_policy, 'exclusive');
  assert.equal(state.train428Config.queue_priority, 7);
  assert.equal(Object.hasOwn(state, 'trainingLabelSelected'), false);

  cleanup(runtime);
});

test('runtime update writes canonical draft and structural compatibility mirrors without recreating label mirror', () => {
  setupDom();
  const state = {
    train428AlgorithmId: 'alg-1',
    trainSplitV3: {
      mode: 'random_test_from_training_pool', train: new Set(['a', 'b']), test: new Set(),
      experiment: 20, validation: 20,
    },
    train428Config: {device: 'cpu', batch: 8, workers: 0, cache: false},
    trainingDraft: {newLabelCodes: ['fire']},
    algorithms: [{id: 'alg-1', versions: []}],
  };
  globalThis.window = {fetch: async () => ({ok: true})};

  const runtime = installTrainingDraftRuntime({getState: () => state, ...dependencies()});
  runtime.sync();
  const draft = runtime.update({
    materialIds: ['b', 'c'],
    newLabelCodes: ['smoke'],
    resource: {device: '0', strategy: 'manual'},
  });

  assert.deepEqual(draft.materialIds, ['b', 'c']);
  assert.deepEqual(draft.newLabelCodes, ['smoke']);
  assert.equal(draft.resource.device, '0');
  assert.equal(draft.resource.strategy, 'manual');
  assert.deepEqual([...state.trainSplitV3.train], ['b', 'c']);
  assert.deepEqual([...state.train429Selected], ['b', 'c']);
  assert.equal(Object.hasOwn(state, 'trainingLabelSelected'), false);
  assert.equal(state.train428Config.device, '0');
  assert.equal(state.train428Config.resource_strategy, 'manual');

  cleanup(runtime);
});

test('train start POST is canonicalized from TrainingDraft before it reaches the previous fetch chain', async () => {
  setupDom({
    tr429Priority: '35',
    trV3Validation: '17',
    trV3ResourceStrategy: 'manual',
    trV3Device: '0',
    trV3GpuPolicy: 'exclusive',
  });
  const state = {
    train428AlgorithmId: 'alg-1',
    trainSplitV3: {
      mode: 'independent_test_set',
      train: new Set(['img-1', 'img-2']),
      test: new Set(['img-3']),
      validation: 20,
    },
    train428Config: {
      resource_strategy: 'auto', device: 'cpu', gpu_policy: 'auto',
      batch: 16, workers: 4, cache: false,
    },
    trainingDraft: {newLabelCodes: ['person']},
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
  assert.equal(sent.validation_percent, 17);
  assert.equal(sent.resource_strategy, 'manual');
  assert.equal(sent.device, '0');
  assert.equal(sent.gpu_policy, 'exclusive');
  assert.equal(sent.batch, 16);
  assert.equal(sent.workers, 4);
  assert.equal(sent.cache, false);
  assert.equal(sent.queue_priority, 35);
  assert.equal(sent.framework, 'ultralytics');
  assert.equal(Object.hasOwn(state, 'trainingLabelSelected'), false);

  cleanup(runtime);
});

test('runtime refuses iteration when versions exist but none is successful and trainable', async () => {
  setupDom();
  const state = {
    train428AlgorithmId: 'alg-1',
    trainSplitV3: {train: new Set(['a', 'b']), test: new Set(), mode: 'random_test_from_training_pool', experiment: 20, validation: 20},
    trainingDraft: {newLabelCodes: ['fire']},
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
  assert.equal(Object.hasOwn(state, 'trainingLabelSelected'), false);

  cleanup(runtime);
});
