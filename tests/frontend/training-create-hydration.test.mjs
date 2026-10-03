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

test('first training open paints a shell before parallel hydration and then runs the canonical form owner', async () => {
  const originalWindow = globalThis.window;
  const calls = [];
  let formOpenCalls = 0;
  const shellCalls = [];
  let releaseOptions;
  let releaseRecommendation;
  const optionsGate = new Promise(resolve => { releaseOptions = resolve; });
  const recommendationGate = new Promise(resolve => { releaseRecommendation = resolve; });
  const state = {targets: [{id: 'stale', status: 'ready'}], rec: null};
  globalThis.window = {};
  const openTrainingForm = aid => {
    formOpenCalls += 1;
    assert.equal(aid, 'alg-1');
    assert.equal(state.targets[0].id, 'gpu-a800');
    assert.equal(state.rec.device, 'cuda:0');
    return 'opened';
  };
  try {
    const runtime = installTrainingCreateHydrationRuntime({
      getState: () => state,
      openTrainingForm,
      projectId: () => 'project-1',
      request: async url => {
        calls.push(url);
        if (url.startsWith('/api/training_options')) {
          await optionsGate;
          return {targets: [{id: 'gpu-a800', status: 'ready', algorithms: [{key: 'yolo11n'}], base_models: [{value: 'yolo11n.pt'}]}]};
        }
        if (url === '/api/system/recommendation') {
          await recommendationGate;
          return {device: 'cuda:0'};
        }
        throw new Error(`unexpected request ${url}`);
      },
      openShell: (aid, token) => shellCalls.push({aid, token}),
      isShellCurrent: () => true,
      closeShell: () => shellCalls.push({closed: true}),
    });
    const pending = runtime.start('alg-1');
    assert.equal(formOpenCalls, 0);
    assert.equal(shellCalls.length, 1);
    assert.equal(shellCalls[0].aid, 'alg-1');
    assert.deepEqual(calls, ['/api/training_options?project_id=project-1', '/api/system/recommendation']);
    releaseRecommendation();
    releaseOptions();
    const result = await pending;
    assert.equal(result, 'opened');
    assert.equal(formOpenCalls, 1);
    assert.deepEqual(shellCalls.at(-1), {closed: true});
  } finally {
    globalThis.window = originalWindow;
  }
});


test('focused training resource hydration publishes options before recommendation finishes', async () => {
  const originalWindow = globalThis.window;
  let releaseOptions;
  let releaseRecommendation;
  const optionsGate = new Promise(resolve => { releaseOptions = resolve; });
  const recommendationGate = new Promise(resolve => { releaseRecommendation = resolve; });
  const state = {targets: [], rec: null};
  globalThis.window = {};
  try {
    const runtime = installTrainingCreateHydrationRuntime({
      getState: () => state,
      projectId: () => 'project-1',
      openTrainingForm: () => 'opened',
      request: async url => {
        if (url.startsWith('/api/training_options')) {
          await optionsGate;
          return {targets: [{id: 'focused-gpu', status: 'ready', algorithms: [], base_models: []}]};
        }
        if (url === '/api/system/recommendation') {
          await recommendationGate;
          return {device: 'cpu'};
        }
        throw new Error(`unexpected request ${url}`);
      },
    });
    const focused = runtime.hydrateCommon();
    releaseOptions();
    await focused;
    assert.equal(state.targets[0]?.id, 'focused-gpu');
    assert.equal(state.rec, null);
    releaseRecommendation();
    await Promise.resolve();
    runtime.destroy();
  } finally {
    globalThis.window = originalWindow;
  }
});


test('shared training truth requests carry their own signal so page navigation cannot suspend them', async () => {
  const originalWindow = globalThis.window;
  const state = {targets: [], rec: null};
  const seen = [];
  globalThis.window = {};
  try {
    const runtime = installTrainingCreateHydrationRuntime({
      getState: () => state,
      projectId: () => 'project-1',
      openTrainingForm: () => 'opened',
      request: async (url, options = {}) => {
        seen.push({url, signal: options.signal});
        if (url.startsWith('/api/training_options')) {
          return {targets: [{id: 'shared-target', status: 'ready', algorithms: [], base_models: []}]};
        }
        if (url === '/api/system/recommendation') return {device: 'cpu'};
        throw new Error(`unexpected request ${url}`);
      },
    });
    await runtime.hydrate({requireTrainable: false});
    assert.equal(seen.length, 2);
    assert.ok(seen.every(item => item.signal instanceof AbortSignal));
    assert.equal(state.targets[0]?.id, 'shared-target');
    assert.equal(state.rec?.device, 'cpu');
    runtime.destroy();
  } finally {
    globalThis.window = originalWindow;
  }
});

test('subsequent internal training open reuses hydrated configuration without a loading shell', async () => {
  const originalWindow = globalThis.window;
  let requests = 0;
  let opens = 0;
  let shells = 0;
  const state = {
    targets: [{status: 'ready', algorithms: [{key: 'yolo11n'}], base_models: []}],
    rec: {device: 'cuda:0'},
  };
  globalThis.window = {};
  const openTrainingForm = () => { opens += 1; };
  try {
    const runtime = installTrainingCreateHydrationRuntime({
      getState: () => state,
      openTrainingForm,
      projectId: () => 'project-1',
      request: async () => { requests += 1; return {}; },
      openShell: () => { shells += 1; },
      isShellCurrent: () => true,
      closeShell: () => {},
    });
    await runtime.start('alg-1');
    await runtime.start('alg-1');
    assert.equal(requests, 0);
    assert.equal(opens, 2);
    assert.equal(shells, 0);
  } finally {
    globalThis.window = originalWindow;
  }
});

test('external preflight starts in parallel with training options and recommendation', async () => {
  const originalWindow = globalThis.window;
  const started = [];
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  const state = {
    algorithms: [{id: 'external-1', source_type: 'EXTERNAL', provider_type: 'CHANG_LIAN'}],
    targets: [],
    rec: null,
  };
  globalThis.window = {};
  const openTrainingForm = () => 'opened';
  try {
    const runtime = installTrainingCreateHydrationRuntime({
      getState: () => state,
      openTrainingForm,
      projectId: () => 'project-1',
      request: async url => {
        started.push(url);
        await gate;
        if (url.startsWith('/api/training_options')) return {targets: [{status: 'ready', algorithms: [{key: 'yolo'}], base_models: []}]};
        return {device: 'cpu'};
      },
      preflight: async aid => { started.push(`preflight:${aid}`); await gate; },
      openShell: () => started.push('shell'),
      isShellCurrent: () => true,
      closeShell: () => {},
    });
    const pending = runtime.start('external-1');
    await Promise.resolve();
    assert.deepEqual(new Set(started), new Set(['shell', '/api/training_options?project_id=project-1', '/api/system/recommendation', 'preflight:external-1']));
    release();
    await pending;
  } finally {
    globalThis.window = originalWindow;
  }
});

test('closed or superseded shell cannot open a stale training dialog', async () => {
  const originalWindow = globalThis.window;
  const opened = [];
  const currentTokens = new Set();
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  const state = {targets: [], rec: null};
  globalThis.window = {};
  const openTrainingForm = aid => opened.push(aid);
  try {
    const runtime = installTrainingCreateHydrationRuntime({
      getState: () => state,
      openTrainingForm,
      projectId: () => 'project-1',
      request: async url => {
        await gate;
        if (url.startsWith('/api/training_options')) return {targets: [{status: 'ready', algorithms: [{key: 'yolo'}], base_models: []}]};
        return {device: 'cpu'};
      },
      openShell: (_aid, token) => currentTokens.add(token),
      isShellCurrent: token => currentTokens.has(token),
      closeShell: token => currentTokens.delete(token),
    });
    const first = runtime.start('alg-1');
    currentTokens.clear();
    const second = runtime.start('alg-2');
    release();
    await Promise.all([first, second]);
    assert.deepEqual(opened, ['alg-2']);
  } finally {
    globalThis.window = originalWindow;
  }
});


test('prewarm hydrates shared training inputs before click and coalesces external preflight', async () => {
  const originalWindow = globalThis.window;
  const calls = [];
  const state = {
    algorithms: [{id: 'external-1', source_type: 'EXTERNAL', provider_type: 'CHANG_LIAN'}],
    targets: [],
    rec: null,
  };
  globalThis.window = {};
  try {
    const runtime = installTrainingCreateHydrationRuntime({
      getState: () => state,
      projectId: () => 'project-1',
      openTrainingForm: () => 'opened',
      request: async url => {
        calls.push(url);
        if (url.startsWith('/api/training_options')) return {targets: [{status: 'ready', algorithms: [{key: 'yolo'}], base_models: []}]};
        return {device: 'cpu'};
      },
      preflight: async aid => { calls.push(`preflight:${aid}`); },
      preflightFresh: () => false,
    });
    await Promise.all([
      runtime.prewarm('external-1'),
      runtime.prewarm('external-1'),
    ]);
    assert.equal(calls.filter(row => row.startsWith('/api/training_options')).length, 1);
    assert.equal(calls.filter(row => row === '/api/system/recommendation').length, 1);
    assert.equal(calls.filter(row => row === 'preflight:external-1').length, 1);
    const before = calls.length;
    await runtime.prewarm('', {includePreflight: false});
    assert.equal(calls.length, before);
    runtime.destroy();
  } finally {
    globalThis.window = originalWindow;
  }
});

test('recent external preflight opens the canonical training form without a preparation flash', async () => {
  const originalWindow = globalThis.window;
  let preflights = 0;
  let shells = 0;
  let opens = 0;
  const state = {
    algorithms: [{id: 'external-1', source_type: 'EXTERNAL', provider_type: 'CHANG_LIAN'}],
    targets: [{status: 'ready', algorithms: [{key: 'yolo11n'}], base_models: []}],
    rec: {device: 'cuda:0'},
  };
  globalThis.window = {};
  try {
    const runtime = installTrainingCreateHydrationRuntime({
      getState: () => state,
      projectId: () => 'project-1',
      openTrainingForm: () => { opens += 1; return 'opened'; },
      preflight: async () => { preflights += 1; },
      preflightFresh: () => true,
      openShell: () => { shells += 1; },
      isShellCurrent: () => true,
      closeShell: () => {},
    });
    const result = await runtime.start('external-1');
    assert.equal(result, 'opened');
    assert.equal(opens, 1);
    assert.equal(shells, 0);
    assert.equal(preflights, 0);
  } finally {
    globalThis.window = originalWindow;
  }
});
