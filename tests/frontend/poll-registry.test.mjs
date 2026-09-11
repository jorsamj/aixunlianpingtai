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

test('legacy page timers are adopted and references are cleared when navigating away', () => {
  const state = {
    jobPollTimer: 1,
    source422Timer: 2,
    auto422Timer: 3,
  };
  const cleared = [];
  const originalClearInterval = globalThis.clearInterval;
  globalThis.clearInterval = id => cleared.push(id);
  globalThis.window = {
    __videoFramePollTimer: 4,
    __prelabelPollTimer: 5,
  };

  const runtime = installPollRegistry({getState: () => state});
  runtime.beforeNavigate('数据集');

  assert.deepEqual(cleared.sort((a, b) => a - b), [1, 2, 3, 4, 5]);
  assert.equal(state.jobPollTimer, null);
  assert.equal(state.source422Timer, null);
  assert.equal(state.auto422Timer, null);
  assert.equal(globalThis.window.__videoFramePollTimer, null);
  assert.equal(globalThis.window.__prelabelPollTimer, null);
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
    auto422Timer: null,
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
      // Represents the final legacy creator. The runtime must immediately retire this timer.
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

test('video frame polling creation is replaced by a PollRegistry-managed interval and cleared on leave', async () => {
  const state = {
    page: '视频切帧',
    project: {id: 'p1'},
    jobs: [],
    jobPollTimer: null,
    source422Timer: null,
    auto422Timer: null,
  };
  const callbacks = new Map();
  const cleared = [];
  let nextTimer = 200;
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
    __videoFramePollTimer: null,
    refreshVideoTasksOnly: async () => { refreshes += 1; },
    setupPagePolling() {
      window.__videoFramePollTimer = setInterval(() => {}, 9999);
    },
  };

  const runtime = installPollRegistry({getState: () => state});
  const managed = window.__videoFramePollTimer;
  assert.equal(callbacks.get(managed)?.delay, 2500);
  assert.deepEqual(runtime.snapshot().find(row => row.key === 'video-frames'), {
    key: 'video-frames', owners: ['视频切帧'], active: true, managed: true, delay: 2500,
  });

  window.setupPagePolling();
  const replacement = window.__videoFramePollTimer;
  assert.notEqual(replacement, managed);
  assert.equal(callbacks.get(replacement)?.delay, 2500);
  assert.ok(cleared.includes(managed));
  assert.ok(cleared.some(id => id !== managed && id !== replacement), 'legacy video timer should be cleared');

  await callbacks.get(replacement).callback();
  assert.equal(refreshes, 1);

  runtime.beforeNavigate('数据集');
  assert.equal(window.__videoFramePollTimer, null);
  assert.equal(callbacks.has(replacement), false);

  runtime.destroy();
  globalThis.setInterval = originalSetInterval;
  globalThis.clearInterval = originalClearInterval;
  delete globalThis.window;
});
