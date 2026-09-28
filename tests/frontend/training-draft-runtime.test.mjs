import test from 'node:test';
import assert from 'node:assert/strict';

import {
  createTrainingDraft,
  trainingBaseVersionFromAlgorithm,
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
  return {createTrainingDraft, trainingBaseVersionFromAlgorithm};
}

function cleanup(runtime) {
  runtime?.destroy();
  delete globalThis.window;
  delete globalThis.document;
}

test('canonical runtime keeps only base version identity and explicit label choices', () => {
  setupDom({tr429Priority: '25'});
  const state = {
    train428AlgorithmId: 'legacy-alg',
    train429Selected: new Set(['legacy-wrong']),
    trainingDraftInheritance: {codes: ['stale-label']},
    trainingDraft: createTrainingDraft({
      algorithmId: 'alg-1', materialIds: ['img-1', 'img-2'],
      validationPercent: 15, newLabelCodes: ['person'],
      resource: {device: '0', batch: 16, workers: 4, cache: false},
    }),
    algorithms: [{id: 'alg-1', versions: [{
      id: 'v1', training_status: 'SUCCEEDED', artifact_verified: true, trainable: true,
      created_at: '2026-09-10T00:00:00Z',
      label_schema: [{class_id: 0, code: 'fire'}, {class_id: 1, code: 'smoke'}],
    }]}],
  };
  globalThis.window = {fetch: async () => ({ok: true})};

  const runtime = installTrainingDraftRuntime({getState: () => state, ...dependencies()});
  const draft = runtime.sync();

  assert.equal(draft.baseVersionId, 'v1');
  assert.deepEqual(draft.newLabelCodes, ['person']);
  assert.equal('inheritedLabelCodes' in draft, false);
  assert.equal('effectiveLabelCodes' in draft, false);
  assert.equal(state.trainingDraftInheritance, undefined);
  assert.equal(state.trainingDraftBase.versionId, 'v1');
  assert.equal(runtime.state().labelInheritanceOwner, false);
  assert.equal(runtime.state().networkOwner, false);
  cleanup(runtime);
});

test('live controls update only canonical draft', () => {
  setupDom({
    tr429Priority: '7', trV3Experiment: '35', trV3Validation: '18',
    trV3ResourceStrategy: 'manual', trV3ResourceProfile: 'performance', trV3Device: '0', trV3GpuPolicy: 'exclusive',
  });
  const state = {
    trainingDraft: createTrainingDraft({
      algorithmId: 'alg-1', materialIds: ['img-1', 'img-2'],
      experimentPercent: 20, validationPercent: 20, newLabelCodes: ['fire'],
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
    strategy: 'manual', profile: 'performance', device: '0', gpuPolicy: 'exclusive', batch: 16, workers: 4, cache: false,
  });
  cleanup(runtime);
});

test('runtime update changes canonical draft and material helpers stay single-owner', () => {
  setupDom();
  const state = {
    train429Selected: new Set(['legacy']),
    trainingDraft: createTrainingDraft({algorithmId: 'alg-1', materialIds: ['a', 'b'], newLabelCodes: ['fire']}),
    algorithms: [{id: 'alg-1', versions: []}],
  };
  globalThis.window = {fetch: async () => ({ok: true})};
  const runtime = installTrainingDraftRuntime({getState: () => state, ...dependencies()});
  runtime.update({materialIds: ['b', 'c'], newLabelCodes: ['smoke'], resource: {device: '0', strategy: 'manual'}});
  assert.deepEqual(runtime.materialIds(), ['b', 'c']);
  assert.deepEqual(state.trainingDraft.newLabelCodes, ['smoke']);
  runtime.toggleMaterialId('b');
  assert.deepEqual(runtime.materialIds(), ['c']);
  runtime.setMaterialIds(['x', 'x', 'y']);
  assert.deepEqual(runtime.materialIds(), ['x', 'y']);
  assert.deepEqual([...state.train429Selected], ['legacy']);
  cleanup(runtime);
});

test('missing draft initializes empty canonical state', () => {
  setupDom({tr429Priority: '40'});
  const state = {algorithms: []};
  globalThis.window = {fetch: async () => ({ok: true})};
  const runtime = installTrainingDraftRuntime({getState: () => state, ...dependencies()});
  assert.equal(state.trainingDraft.algorithmId, '');
  assert.deepEqual(state.trainingDraft.materialIds, []);
  assert.equal(state.trainingDraft.baseVersionId, '');
  assert.equal(state.trainingDraft.priority, 40);
  assert.equal(runtime.state().initializationCount, 1);
  cleanup(runtime);
});

test('TrainingDraftRuntime never intercepts train-start fetches', async () => {
  setupDom();
  const state = {
    trainingDraft: createTrainingDraft({algorithmId: 'alg-1', materialIds: ['canonical'], newLabelCodes: ['fire']}),
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
  cleanup(runtime);
});

test('canonical draft subscribers receive update intent and unsubscribe deterministically', () => {
  setupDom();
  const state = {
    trainingDraft: createTrainingDraft({algorithmId: 'alg-1', materialIds: [], newLabelCodes: []}),
    algorithms: [{id: 'alg-1', versions: []}],
  };
  globalThis.window = {fetch: async () => ({ok: true})};
  const runtime = installTrainingDraftRuntime({getState: () => state, ...dependencies()});
  const events = [];
  const unsubscribe = runtime.subscribe(event => events.push(event));
  runtime.update({materialIds: ['a', 'b'], newLabelCodes: ['fire']});
  assert.equal(events.length, 1);
  assert.deepEqual(events[0].patch, {materialIds: ['a', 'b'], newLabelCodes: ['fire']});
  unsubscribe();
  runtime.update({materialIds: ['c']});
  assert.equal(events.length, 1);
  cleanup(runtime);
});
