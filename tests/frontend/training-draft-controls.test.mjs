import test from 'node:test';
import assert from 'node:assert/strict';

import {
  installTrainingDraftControls,
  trainingDraftControlPatch,
} from '../../static/modules/training-draft-controls.js';

test('control patch maps train-v3 inputs to canonical draft fields', () => {
  assert.deepEqual(trainingDraftControlPatch({id: 'trV3Experiment', value: '35'}), {experimentPercent: 35});
  assert.deepEqual(trainingDraftControlPatch({id: 'trV3Validation', value: '18'}), {validationPercent: 18});
  assert.deepEqual(trainingDraftControlPatch({id: 'tr429Priority', value: '7'}), {priority: 7});
  assert.deepEqual(trainingDraftControlPatch({id: 'trV3ResourceStrategy', value: 'manual'}), {resource: {strategy: 'manual'}});
  assert.deepEqual(trainingDraftControlPatch({id: 'trV3Device', value: '0'}), {resource: {device: '0'}});
  assert.deepEqual(trainingDraftControlPatch({id: 'trV3GpuPolicy', value: 'exclusive'}), {resource: {gpuPolicy: 'exclusive'}});
  assert.equal(trainingDraftControlPatch({id: 'unrelated', value: 'x'}), null);
});

test('installed controls update canonical runtime synchronously on input/change', () => {
  const listeners = new Map();
  globalThis.document = {
    addEventListener(type, handler) { listeners.set(type, handler); },
    removeEventListener(type, handler) { if (listeners.get(type) === handler) listeners.delete(type); },
  };
  globalThis.window = {};

  const patches = [];
  const runtime = installTrainingDraftControls({
    trainingDraftRuntime: {
      update(patch) { patches.push(patch); },
    },
  });

  listeners.get('input')({target: {id: 'trV3Experiment', value: '31'}});
  listeners.get('change')({target: {id: 'trV3ResourceStrategy', value: 'manual'}});
  listeners.get('change')({target: {id: 'trV3GpuPolicy', value: 'shared'}});

  assert.deepEqual(patches, [
    {experimentPercent: 31},
    {resource: {strategy: 'manual'}},
    {resource: {gpuPolicy: 'shared'}},
  ]);
  assert.equal(runtime.state().directWrites, 3);

  runtime.destroy();
  assert.equal(window.__trainingDraftControlsInstalled, false);
  delete globalThis.window;
  delete globalThis.document;
});
