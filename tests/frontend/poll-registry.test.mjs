import test from 'node:test';
import assert from 'node:assert/strict';

import {PollRegistry, installPollRegistry} from '../../static/modules/poll-registry.js';

test('registry keeps polling owned by the destination page and clears the rest', () => {
  const registry = new PollRegistry();
  const cleared = [];
  registry.adopt('training', ['训练任务', '检测台'], 11, id => cleared.push(id));
  registry.adopt('sources', '素材接入', 22, id => cleared.push(id));

  registry.leave('训练任务');

  assert.deepEqual(cleared, [22]);
  assert.deepEqual(registry.snapshot().map(row => row.key), ['training']);
});

test('adopting a replacement timer clears the older timer for the same key', () => {
  const registry = new PollRegistry();
  const cleared = [];
  registry.adopt('sources', '素材接入', 10, id => cleared.push(id));
  registry.adopt('sources', '素材接入', 20, id => cleared.push(id));

  assert.deepEqual(cleared, [10]);
  assert.equal(registry.snapshot()[0].active, true);
});

test('registry can own interval creation instead of only adopting legacy timers', () => {
  const registry = new PollRegistry();
  const cleared = [];
  const created = [];
  const timer = registry.startInterval('training', '训练任务', () => {}, 2000, {
    setFn(callback, delay) {
      created.push({callback, delay});
      return 91;
    },
    clearFn: id => cleared.push(id),
  });

  assert.equal(timer, 91);
  assert.equal(created[0].delay, 2000);
  assert.deepEqual(registry.snapshot(), [{
    key: 'training', owners: ['训练任务'], active: true, managed: true, delay: 2000,
  }]);
  registry.clear('training');
  assert.deepEqual(cleared, [91]);
});

test('managed timeout unregisters itself before callback so recursive polling can re-arm cleanly', async () => {
  const registry = new PollRegistry();
  const created = [];
  const cleared = [];
  let calls = 0;
  registry.startTimeout('auto-label-v60', '自动标注及清洗', async () => {
    calls += 1;
    assert.deepEqual(registry.snapshot(), []);
  }, 1800, {
    setFn(callback, delay) {
      created.push({callback, delay});
      return 77;
    },
    clearFn: id => cleared.push(id),
  });

  assert.deepEqual(registry.snapshot(), [{
    key: 'auto-label-v60', owners: ['自动标注及清洗'], active: true, managed: true, delay: 1800,
  }]);
  assert.equal(created[0].delay, 1800);
  await created[0].callback();
  assert.equal(calls, 1);
  assert.deepEqual(registry.snapshot(), []);
  assert.deepEqual(cleared, []);
});

test('remaining legacy page timers are adopted and references are cleared when navigating away', () => {
  const state = {
    jobPollTimer: 1,
    source422Timer: 2,
  };
  const cleared = [];
  const originalClearInterval = globalThis.clearInterval;
  globalThis.clearInterval = id => cleared.push(id);
  globalThis.window = {};

  const runtime = installPollRegistry({getState: () => state});
  runtime.beforeNavigate('数据集');

  assert.deepEqual(cleared.sort((a, b) => a - b), [1, 2]);
  assert.equal(state.jobPollTimer, null);
  assert.equal(state.source422Timer, null);
  assert.deepEqual(runtime.snapshot(), []);

  runtime.destroy();
  globalThis.clearInterval = originalClearInterval;
  delete globalThis.window;
});

test('final training polling creation is replaced by a PollRegistry-managed interval', async () => {
  const state = {
    page: '训练任务',
    project: {id: 'p1'},
    jobs: [{id: 'j1', status: 'running'}],
    jobPollTimer: null,
    source422Timer: null,
  };
  const callbacks = new Map();
  const cleared = [];
  let nextTimer = 100;
  let refreshes = 0;
  const originalSetInterval = globalThis.setInterval;
  const originalClearInterval = globalThis.clearInterval;
  globalThis.setInterval = (callback, delay) => {
    const id = ++nextTimer;
    callbacks.set(id, {callback, delay});
    return id;
  };
  globalThis.clearInterval = id => {
    cleared.push(id);
    callbacks.delete(id);
  };
  globalThis.window = {
    refreshJobsOnly: async () => { refreshes += 1; },
    setupPagePolling() {
      state.jobPollTimer = setInterval(() => {}, 9999);
    },
  };

  const runtime = installPollRegistry({getState: () => state});
  const firstManaged = state.jobPollTimer;
  assert.equal(callbacks.get(firstManaged)?.delay, 2000);
  assert.equal(runtime.snapshot().find(row => row.key === 'training-jobs')?.managed, true);

  window.setupPagePolling();
  const managed = state.jobPollTimer;
  assert.notEqual(managed, firstManaged);
  assert.equal(callbacks.get(managed)?.delay, 2000);
  assert.equal(runtime.snapshot().find(row => row.key === 'training-jobs')?.managed, true);
  assert.ok(cleared.includes(firstManaged));
  assert.ok(cleared.some(id => id !== firstManaged && id !== managed), 'legacy-created timer should be cleared');

  await callbacks.get(managed).callback();
  assert.equal(refreshes, 1);

  runtime.beforeNavigate('数据集');
  assert.equal(state.jobPollTimer, null);
  assert.equal(callbacks.has(managed), false);

  runtime.destroy();
  globalThis.setInterval = originalSetInterval;
  globalThis.clearInterval = originalClearInterval;
  delete globalThis.window;
});

test('final v42.4 video polling uses a managed one-shot and re-arms only while a task is active', async () => {
  const state = {
    page: '视频切帧',
    project: {id: 'p1'},
    jobs: [],
    jobPollTimer: null,
    source422Timer: null,
    video424: [{id: 'v1', status: 'RUNNING'}],
    video424Timer: null,
  };
  const timeouts = new Map();
  const clearedTimeouts = [];
  const intervals = new Map();
  const clearedIntervals = [];
  let nextTimer = 200;
  let refreshes = 0;
  const originalSetTimeout = globalThis.setTimeout;
  const originalClearTimeout = globalThis.clearTimeout;
  const originalSetInterval = globalThis.setInterval;
  const originalClearInterval = globalThis.clearInterval;
  globalThis.setTimeout = (callback, delay) => {
    const id = ++nextTimer;
    timeouts.set(id, {callback, delay});
    return id;
  };
  globalThis.clearTimeout = id => {
    clearedTimeouts.push(id);
    timeouts.delete(id);
  };
  globalThis.setInterval = (callback, delay) => {
    const id = ++nextTimer;
    intervals.set(id, {callback, delay});
    return id;
  };
  globalThis.clearInterval = id => {
    clearedIntervals.push(id);
    intervals.delete(id);
  };
  globalThis.window = {
    PlatformCore: {video: {isActiveVideoTask: task => String(task?.status).toUpperCase() === 'RUNNING'}},
    renderVideo424: async () => {
      state.video424Timer = setTimeout(() => {}, 9999);
    },
    refreshVideo424Delta: async () => {
      refreshes += 1;
      state.video424Timer = setTimeout(() => {}, 9999);
    },
  };

  const runtime = installPollRegistry({getState: () => state});
  await window.renderVideo424();

  const firstManaged = state.video424Timer;
  assert.equal(timeouts.get(firstManaged)?.delay, 2000);
  assert.deepEqual(runtime.snapshot().find(row => row.key === 'video-frames'), {
    key: 'video-frames', owners: ['视频切帧'], active: true, managed: true, delay: 2000,
  });
  assert.ok(clearedTimeouts.some(id => id !== firstManaged), 'legacy v42.4 timeout should be retired');

  await timeouts.get(firstManaged).callback();
  assert.equal(refreshes, 1);
  const secondManaged = state.video424Timer;
  assert.notEqual(secondManaged, firstManaged);
  assert.equal(timeouts.get(secondManaged)?.delay, 2000);
  assert.equal(runtime.snapshot().find(row => row.key === 'video-frames')?.managed, true);

  state.video424 = [{id: 'v1', status: 'SUCCEEDED'}];
  await timeouts.get(secondManaged).callback();
  assert.equal(refreshes, 2);
  assert.equal(state.video424Timer, null);
  assert.equal(runtime.snapshot().some(row => row.key === 'video-frames'), false);

  runtime.beforeNavigate('数据集');
  assert.equal(state.video424Timer, null);

  runtime.destroy();
  globalThis.setTimeout = originalSetTimeout;
  globalThis.clearTimeout = originalClearTimeout;
  globalThis.setInterval = originalSetInterval;
  globalThis.clearInterval = originalClearInterval;
  delete globalThis.window;
});

test('source page polling creation is replaced by a PollRegistry-managed interval after first render', async () => {
  const state = {
    page: '素材接入',
    project: {id: 'p1'},
    jobs: [],
    jobPollTimer: null,
    source422Timer: null,
  };
  const callbacks = new Map();
  const cleared = [];
  let nextTimer = 300;
  let refreshes = 0;
  let renders = 0;
  const originalSetInterval = globalThis.setInterval;
  const originalClearInterval = globalThis.clearInterval;
  globalThis.setInterval = (callback, delay) => {
    const id = ++nextTimer;
    callbacks.set(id, {callback, delay});
    return id;
  };
  globalThis.clearInterval = id => {
    cleared.push(id);
    callbacks.delete(id);
  };
  globalThis.window = {
    refreshSources422: async () => { refreshes += 1; },
    renderSources422: async () => {
      renders += 1;
      state.source422Timer = setInterval(() => {}, 9999);
    },
  };

  const runtime = installPollRegistry({getState: () => state});
  await window.renderSources422();

  assert.equal(renders, 1);
  const managed = state.source422Timer;
  assert.equal(callbacks.get(managed)?.delay, 2500);
  assert.deepEqual(runtime.snapshot().find(row => row.key === 'sources'), {
    key: 'sources', owners: ['素材接入'], active: true, managed: true, delay: 2500,
  });
  assert.ok(cleared.some(id => id !== managed), 'legacy source timer should be cleared');

  await callbacks.get(managed).callback();
  assert.equal(refreshes, 1);

  runtime.beforeNavigate('数据集');
  assert.equal(state.source422Timer, null);
  assert.equal(callbacks.has(managed), false);

  runtime.destroy();
  globalThis.setInterval = originalSetInterval;
  globalThis.clearInterval = originalClearInterval;
  delete globalThis.window;
});
