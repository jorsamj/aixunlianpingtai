import test from 'node:test';
import assert from 'node:assert/strict';

import {
  createTrainingDraft,
  trainingDraftFromLegacyState,
  trainingInheritanceFromAlgorithm,
} from '../../static/modules/training-draft.js';
import {installTrainingDraftRuntime} from '../../static/modules/training-draft-runtime.js';

function setupDom(values = {}) {
  const listeners = new Map();
  const controls = {tr429Priority: '30', ...values};
  globalThis.document = {
    addEventListener(type, handler) { listeners.set(type, handler); },
    removeEventListener(type, handler) { if (listeners.get(type) === handler) listeners.delete(type); },
    getElementById(id) { return Object.hasOwn(controls, id) ? {value: controls[id]} : null; },
    querySelectorAll() { return []; },
  };
  return {listeners, controls};
}

function dependencies() {
  return {createTrainingDraft, trainingDraftFromLegacyState, trainingInheritanceFromAlgorithm};
}

function cleanup(runtime) {
  runtime?.destroy();
  delete globalThis.window;
  delete globalThis.document;
}

test('canonical draft wins over stale legacy mirrors and retired mirrors stay deleted', () => {
  setupDom({tr429Priority: '25'});
  const state = {
    train428AlgorithmId: 'legacy-alg',
    train429Selected: new Set(['legacy-wrong']),
    trainSplitV3: {mode: 'independent_test_set', train: new Set(['legacy-wrong'])},
    trainingLabelSelected: new Set(['legacy-label']),
    train428Config: {device: 'cpu', batch: 99},
    trainingDraft: createTrainingDraft({
      algorithmId: 'alg-1', materialIds: ['img-1', 'img-2'],
      splitMode: 'random_test_from_training_pool', experimentPercent: 20,
      validationPercent: 15, newLabelCodes: ['person'],
      resource: {device: '0', batch: 16, workers: 4, cache: false},
    }),
    algorithms: [{id: 'alg-1', versions: [{
      id: 'v1', training_status: 'SUCCEEDED', artifact_verified: true, trainable: true,
      created_at: '2026-09-10T00:00:00Z',
      label_schema: [{class_id: 0, code: 'fire'}, {class_id: 1, code: 'smoke'}],
    }]}],
  };
  const originalFetch = async () => ({ok: true});
  globalThis.window = {fetch: originalFetch};

  const runtime = installTrainingDraftRuntime({getState: () => state, ...dependencies()});
  const draft = runtime.sync();

  assert.equal(draft.algorithmId, 'alg-1');
  assert.deepEqual(draft.materialIds, ['img-1', 'img-2']);
  assert.equal(draft.baseVersionId, 'v1');
  assert.deepEqual(draft.inheritedLabelCodes, ['fire', 'smoke']);
  assert.deepEqual(draft.effectiveLabelCodes, ['fire', 'smoke', 'person']);
  assert.equal(draft.priority, 25);
  assert.equal(Object.hasOwn(state, 'trainSplitV3'), false);
  assert.equal(Object.hasOwn(state, 'trainingLabelSelected'), false);
  assert.equal(state.train428AlgorithmId, 'legacy-alg');
  assert.deepEqual([...state.train429Selected], ['legacy-wrong']);
  assert.equal(state.train428Config.device, 'cpu');
  assert.equal(window.fetch, originalFetch);
  assert.equal(runtime.state().networkOwner, false);
  assert.equal(runtime.state().legacyBootstrapCount, 0);

  cleanup(runtime);
});

test('live controls update only canonical draft and do not backfill compatibility mirrors', () => {
  setupDom({
    tr429Priority: '7', trV3Experiment: '35', trV3Validation: '18',
    trV3ResourceStrategy: 'manual', trV3Device: '0', trV3GpuPolicy: 'exclusive',
  });
  const state = {
    train428AlgorithmId: 'legacy-alg',
    train429Selected: new Set(['legacy']),
    train428Config: {resource_strategy: 'auto', device: 'cpu', gpu_policy: 'auto', queue_priority: 50},
    trainingDraft: createTrainingDraft({
      algorithmId: 'alg-1', materialIds: ['img-1', 'img-2'],
      splitMode: 'random_test_from_training_pool', experimentPercent: 20,
      validationPercent: 20, newLabelCodes: ['fire'],
      resource: {batch: 16, workers: 4, cache: false},
    }),
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
  assert.equal(state.train428Config.resource_strategy, 'auto');
  assert.equal(state.train428Config.device, 'cpu');
  assert.equal(state.train428Config.queue_priority, 50);
  assert.deepEqual([...state.train429Selected], ['legacy']);

  cleanup(runtime);
});

test('runtime update changes canonical draft without writing remaining compatibility mirrors', () => {
  setupDom();
  const state = {
    train428AlgorithmId: 'legacy-alg',
    train429Selected: new Set(['legacy']),
    train428Config: {device: 'cpu', resource_strategy: 'auto'},
    trainingDraft: createTrainingDraft({
      algorithmId: 'alg-1', materialIds: ['a', 'b'],
      splitMode: 'random_test_from_training_pool', experimentPercent: 20,
      validationPercent: 20, newLabelCodes: ['fire'],
    }),
    algorithms: [{id: 'alg-1', versions: []}],
  };
  globalThis.window = {fetch: async () => ({ok: true})};

  const runtime = installTrainingDraftRuntime({getState: () => state, ...dependencies()});
  const draft = runtime.update({
    materialIds: ['b', 'c'], newLabelCodes: ['smoke'],
    resource: {device: '0', strategy: 'manual'},
  });

  assert.deepEqual(draft.materialIds, ['b', 'c']);
  assert.deepEqual(draft.newLabelCodes, ['smoke']);
  assert.equal(draft.resource.device, '0');
  assert.equal(draft.resource.strategy, 'manual');
  assert.deepEqual([...state.train429Selected], ['legacy']);
  assert.equal(state.train428AlgorithmId, 'legacy-alg');
  assert.equal(state.train428Config.device, 'cpu');
  assert.equal(state.train428Config.resource_strategy, 'auto');

  cleanup(runtime);
});

test('legacy state is consumed once only when canonical draft is absent', () => {
  setupDom({tr429Priority: '40'});
  const state = {
    train428AlgorithmId: 'alg-1',
    train429Selected: new Set(['legacy-a', 'legacy-b']),
    train428Config: {device: 'cpu', batch: 8, workers: 0, cache: false},
    algorithms: [{id: 'alg-1', versions: []}],
  };
  globalThis.window = {fetch: async () => ({ok: true})};

  const runtime = installTrainingDraftRuntime({getState: () => state, ...dependencies()});
  assert.deepEqual(state.trainingDraft.materialIds, ['legacy-a', 'legacy-b']);
  assert.equal(runtime.state().legacyBootstrapCount, 1);

  state.train429Selected = new Set(['stale-after-bootstrap']);
  state.train428AlgorithmId = 'stale-alg';
  state.train428Config = {device: 'stale-device', batch: 99};
  runtime.sync();

  assert.equal(state.trainingDraft.algorithmId, 'alg-1');
  assert.deepEqual(state.trainingDraft.materialIds, ['legacy-a', 'legacy-b']);
  assert.notEqual(state.trainingDraft.resource.device, 'stale-device');
  assert.equal(runtime.state().legacyBootstrapCount, 1);

  cleanup(runtime);
});

test('TrainingDraftRuntime never intercepts train-start fetches', async () => {
  setupDom();
  const state = {
    trainingDraft: createTrainingDraft({
      algorithmId: 'alg-1', materialIds: ['canonical'],
      splitMode: 'random_test_from_training_pool', experimentPercent: 20,
      validationPercent: 20, newLabelCodes: ['fire'],
    }),
    algorithms: [{id: 'alg-1', versions: []}],
  };
  let body;
  const originalFetch = async (_input, init) => { body = init?.body; return {ok: true}; };
  globalThis.window = {fetch: originalFetch};

  const runtime = installTrainingDraftRuntime({getState: () => state, ...dependencies()});
  const raw = JSON.stringify({algorithm_asset_id: 'alg-1', train_image_ids: ['caller-owned']});
  await window.fetch('/api/v12/projects/p1/train/start', {method: 'POST', body: raw});

  assert.equal(window.fetch, originalFetch);
  assert.equal(body, raw);
  assert.equal(runtime.state().networkOwner, false);

  cleanup(runtime);
});
