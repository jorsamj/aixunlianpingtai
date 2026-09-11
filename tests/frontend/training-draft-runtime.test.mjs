import test from 'node:test';
import assert from 'node:assert/strict';

import {
  createTrainingDraft,
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
  return {createTrainingDraft, trainingInheritanceFromAlgorithm};
}

function cleanup(runtime) {
  runtime?.destroy();
  delete globalThis.window;
  delete globalThis.document;
}

test('canonical draft ignores stale retired mirror-shaped fields without mutating them', () => {
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
  assert.deepEqual([...state.trainSplitV3.train], ['legacy-wrong']);
  assert.deepEqual([...state.trainingLabelSelected], ['legacy-label']);
  assert.equal(state.train428AlgorithmId, 'legacy-alg');
  assert.deepEqual([...state.train429Selected], ['legacy-wrong']);
  assert.equal(state.train428Config.device, 'cpu');
  assert.equal(window.fetch, originalFetch);
  assert.equal(runtime.state().networkOwner, false);
  assert.equal(runtime.state().initializationCount, 0);

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

test('material selection helpers mutate only canonical materialIds', () => {
  setupDom();
  const state = {
    train429Selected: new Set(['legacy-only']),
    trainingDraft: createTrainingDraft({
      algorithmId: 'alg-1', materialIds: ['a', 'b'],
      splitMode: 'random_test_from_training_pool', experimentPercent: 20,
      validationPercent: 20, newLabelCodes: ['fire'],
    }),
    algorithms: [{id: 'alg-1', versions: []}],
  };
  globalThis.window = {fetch: async () => ({ok: true})};

  const runtime = installTrainingDraftRuntime({getState: () => state, ...dependencies()});
  assert.deepEqual(runtime.materialIds(), ['a', 'b']);
  runtime.toggleMaterialId('b');
  assert.deepEqual(runtime.materialIds(), ['a']);
  runtime.toggleMaterialId('c');
  assert.deepEqual(runtime.materialIds(), ['a', 'c']);
  runtime.setMaterialIds(['x', 'x', 'y']);
  assert.deepEqual(state.trainingDraft.materialIds, ['x', 'y']);
  assert.deepEqual([...state.train429Selected], ['legacy-only']);

  cleanup(runtime);
});

test('missing draft initializes empty canonical state and ignores retired mirror-shaped fields', () => {
  setupDom({tr429Priority: '40'});
  const state = {
    train428AlgorithmId: 'legacy-alg',
    train429Selected: new Set(['legacy-a', 'legacy-b']),
    train428Config: {device: 'cpu', batch: 8},
    algorithms: [{id: 'legacy-alg', versions: []}],
  };
  globalThis.window = {fetch: async () => ({ok: true})};

  const runtime = installTrainingDraftRuntime({getState: () => state, ...dependencies()});
  assert.equal(state.trainingDraft.algorithmId, '');
  assert.deepEqual(state.trainingDraft.materialIds, []);
  assert.equal(state.trainingDraft.priority, 40);
  assert.equal(state.trainingDraft.resource.device, 'auto');
  assert.equal(runtime.state().initializationCount, 1);

  state.train429Selected = new Set(['changed-legacy']);
  state.train428AlgorithmId = 'changed-legacy-alg';
  state.train428Config = {device: 'changed-legacy-device'};
  runtime.sync();

  assert.equal(state.trainingDraft.algorithmId, '');
  assert.deepEqual(state.trainingDraft.materialIds, []);
  assert.equal(state.trainingDraft.resource.device, 'auto');
  assert.equal(runtime.state().initializationCount, 1);

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

test('canonical draft subscribers receive update intent and can unsubscribe deterministically', () => {
  setupDom();
  const state = {
    trainingDraft: createTrainingDraft({
      algorithmId: 'alg-1', materialIds: [],
      splitMode: 'random_test_from_training_pool', experimentPercent: 20,
      validationPercent: 20, newLabelCodes: [],
    }),
    algorithms: [{id: 'alg-1', versions: []}],
  };
  globalThis.window = {fetch: async () => ({ok: true})};

  const runtime = installTrainingDraftRuntime({getState: () => state, ...dependencies()});
  const events = [];
  const unsubscribe = runtime.subscribe(event => events.push(event));

  runtime.update({materialIds: ['a', 'b'], newLabelCodes: ['fire']});
  assert.equal(events.length, 1);
  assert.equal(events[0].type, 'update');
  assert.deepEqual(events[0].patch, {materialIds: ['a', 'b'], newLabelCodes: ['fire']});
  assert.deepEqual(events[0].draft.materialIds, ['a', 'b']);
  assert.equal(runtime.state().subscribers, 1);

  runtime.sync();
  assert.equal(events.length, 2);
  assert.equal(events[1].type, 'sync');

  unsubscribe();
  assert.equal(runtime.state().subscribers, 0);
  runtime.update({materialIds: ['c']});
  assert.equal(events.length, 2);
  assert.equal(runtime.state().classicWrapperOwner, false);

  cleanup(runtime);
});
