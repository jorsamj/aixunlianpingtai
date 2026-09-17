import test from 'node:test';
import assert from 'node:assert/strict';
import {
  installTrainingCreateHydrationRuntime,
  trainingCreationInputsReady,
  trainingOptionsHydrated,
} from '../../static/modules/training-create-hydration.js';

test('training create inputs require complete ready target and recommendation', () => {
  assert.equal(trainingOptionsHydrated([{status: 'ready'}]), false);
  assert.equal(trainingOptionsHydrated([{status: 'ready', algorithms: [], base_models: []}]), false);
  assert.equal(trainingOptionsHydrated([{status: 'ready', algorithms: [{key: 'yolo11n'}], base_models: []}]), true);
  assert.equal(trainingCreationInputsReady({
    targets: [{status: 'ready', algorithms: [{key: 'yolo11n'}], base_models: []}],
    rec: null,
  }), false);
});

test('first training open hydrates minimal configuration before legacy modal owner runs', async () => {
  const originalWindow = globalThis.window;
  const calls = [];
  let previousStartCalls = 0;
  const state = {
    targets: [{id: 'stale', status: 'ready'}],
    rec: null,
  };
  globalThis.window = {
    startAlgorithmTraining429: aid => {
      previousStartCalls += 1;
      assert.equal(aid, 'alg-1');
      assert.equal(state.targets[0].id, 'gpu-a800');
      assert.equal(state.rec.device, 'cuda:0');
      return 'opened';
    },
  };
  try {
    const runtime = installTrainingCreateHydrationRuntime({
      getState: () => state,
      projectId: () => 'project-1',
      request: async url => {
        calls.push(url);
        if (url.startsWith('/api/training_options')) return {
          targets: [{
            id: 'gpu-a800',
            status: 'ready',
            algorithms: [{key: 'yolo11n'}],
            base_models: [{value: 'yolo11n.pt'}],
          }],
        };
        if (url === '/api/system/recommendation') return {device: 'cuda:0'};
        throw new Error(`unexpected request ${url}`);
      },
    });
    const result = await runtime.start('alg-1');
    assert.equal(result, 'opened');
    assert.equal(previousStartCalls, 1);
    assert.deepEqual(calls, [
      '/api/training_options?project_id=project-1',
      '/api/system/recommendation',
    ]);
  } finally {
    globalThis.window = originalWindow;
  }
});

test('subsequent training open reuses hydrated configuration', async () => {
  const originalWindow = globalThis.window;
  let requests = 0;
  let opens = 0;
  const state = {
    targets: [{status: 'ready', algorithms: [{key: 'yolo11n'}], base_models: []}],
    rec: {device: 'cuda:0'},
  };
  globalThis.window = {startAlgorithmTraining429: () => { opens += 1; }};
  try {
    const runtime = installTrainingCreateHydrationRuntime({
      getState: () => state,
      projectId: () => 'project-1',
      request: async () => { requests += 1; return {}; },
    });
    await runtime.start('alg-1');
    await runtime.start('alg-1');
    assert.equal(requests, 0);
    assert.equal(opens, 2);
  } finally {
    globalThis.window = originalWindow;
  }
});
