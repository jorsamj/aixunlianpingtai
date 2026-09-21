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

test('training polling is a PollRegistry-managed one-shot that follows latest backend state', async () => {
  const state = {
    page: '训练任务',
    project: {id: 'p1'},
    jobs: [{id: 'j1', status: 'running'}],
  };
  const timeouts = new Map();
  const intervals = new Map();
  let nextTimer = 100;
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
  globalThis.clearTimeout = id => timeouts.delete(id);
  globalThis.setInterval = (callback, delay) => {
    const id = ++nextTimer;
    intervals.set(id, {callback, delay});
    return id;
  };
  globalThis.clearInterval = id => intervals.delete(id);
  globalThis.window = {
    TrainingTaskRuntime: {refresh: async ({source}) => {
      assert.equal(source, 'poll');
      refreshes += 1;
      state.jobs = refreshes === 1
        ? [{id: 'j1', status: 'running', current_epoch: 4, progress_percent: 4}]
        : [{id: 'j1', status: 'completed', current_epoch: 100, progress_percent: 100}];
    }},
  };

  let runtime;
  try {
    runtime = installPollRegistry({getState: () => state});
    assert.deepEqual(runtime.snapshot().find(row => row.key === 'training-jobs'), {
      key: 'training-jobs', owners: ['训练任务'], active: true, managed: true, delay: 2000,
    });
    assert.equal(intervals.size, 0);
    const firstTimer = Math.max(...timeouts.keys());
    await timeouts.get(firstTimer).callback();
    assert.equal(refreshes, 1);
    assert.equal(runtime.snapshot().some(row => row.key === 'training-jobs'), true);

    const secondTimer = Math.max(...timeouts.keys());
    assert.notEqual(secondTimer, firstTimer);
    await timeouts.get(secondTimer).callback();
    assert.equal(refreshes, 2);
    assert.equal(runtime.snapshot().some(row => row.key === 'training-jobs'), false);
  } finally {
    runtime?.destroy();
    globalThis.setTimeout = originalSetTimeout;
    globalThis.clearTimeout = originalClearTimeout;
    globalThis.setInterval = originalSetInterval;
    globalThis.clearInterval = originalClearInterval;
    delete globalThis.window;
  }
});

test('paused-only and every supported terminal training state leave no pending timer', () => {
  const originalSetTimeout = globalThis.setTimeout;
  const originalClearTimeout = globalThis.clearTimeout;
  let nextTimer = 400;
  const timeouts = new Map();
  globalThis.setTimeout = (callback, delay) => {
    const id = ++nextTimer;
    timeouts.set(id, {callback, delay});
    return id;
  };
  globalThis.clearTimeout = id => timeouts.delete(id);
  globalThis.window = {};

  const stoppedStatuses = ['paused', 'done', 'finished', 'completed', 'failed', 'stopped', 'cancelled', 'canceled'];
  let runtime;
  try {
    const state = {page: '训练任务', project: {id: 'p1'}, jobs: []};
    runtime = installPollRegistry({getState: () => state});
    for (const status of stoppedStatuses) {
      state.jobs = [{id: status, status}];
      runtime.replaceTrainingJobTimer();
      assert.equal(
        runtime.snapshot().some(row => row.key === 'training-jobs'),
        false,
        `${status} must not keep training polling alive`,
      );
    }
  } finally {
    runtime?.destroy();
    globalThis.setTimeout = originalSetTimeout;
    globalThis.clearTimeout = originalClearTimeout;
    delete globalThis.window;
  }
});

test('a transient training refresh failure re-arms while last-known state is still dynamic', async () => {
  const originalSetTimeout = globalThis.setTimeout;
  const originalClearTimeout = globalThis.clearTimeout;
  let nextTimer = 450;
  const timeouts = new Map();
  globalThis.setTimeout = (callback, delay) => {
    const id = ++nextTimer;
    timeouts.set(id, {callback, delay});
    return id;
  };
  globalThis.clearTimeout = id => timeouts.delete(id);
  const state = {page: '训练任务', project: {id: 'p1'}, jobs: [{id: 'j1', status: 'running'}]};
  globalThis.window = {
    TrainingTaskRuntime: {async refresh() { throw new Error('temporary network failure'); }},
  };

  let runtime;
  try {
    runtime = installPollRegistry({getState: () => state});
    const firstTimer = Math.max(...timeouts.keys());
    await timeouts.get(firstTimer).callback();
    assert.equal(runtime.snapshot().some(row => row.key === 'training-jobs'), true);
    assert.notEqual(Math.max(...timeouts.keys()), firstTimer);
  } finally {
    runtime?.destroy();
    globalThis.setTimeout = originalSetTimeout;
    globalThis.clearTimeout = originalClearTimeout;
    delete globalThis.window;
  }
});

test('leaving training clears its timer and resume lifecycle can restore it from refreshed state', () => {
  const originalSetTimeout = globalThis.setTimeout;
  const originalClearTimeout = globalThis.clearTimeout;
  let nextTimer = 500;
  const timeouts = new Map();
  globalThis.setTimeout = (callback, delay) => {
    const id = ++nextTimer;
    timeouts.set(id, {callback, delay});
    return id;
  };
  globalThis.clearTimeout = id => timeouts.delete(id);
  const state = {page: '训练任务', project: {id: 'p1'}, jobs: [{id: 'j1', status: 'running'}]};
  globalThis.window = {};

  let runtime;
  try {
    runtime = installPollRegistry({getState: () => state});
    assert.equal(runtime.snapshot().some(row => row.key === 'training-jobs'), true);

    state.page = '检测台';
    runtime.beforeNavigate('检测台');
    assert.equal(runtime.snapshot().some(row => row.key === 'training-jobs'), false);

    state.page = '训练任务';
    state.jobs = [{id: 'j1', status: 'paused'}];
    runtime.afterNavigate('训练任务');
    assert.equal(runtime.snapshot().some(row => row.key === 'training-jobs'), false);

    state.jobs = [{id: 'j1', status: 'running'}];
    runtime.afterNavigate('训练任务');
    assert.deepEqual(runtime.snapshot().find(row => row.key === 'training-jobs'), {
      key: 'training-jobs', owners: ['训练任务'], active: true, managed: true, delay: 2000,
    });
  } finally {
    runtime?.destroy();
    globalThis.setTimeout = originalSetTimeout;
    globalThis.clearTimeout = originalClearTimeout;
    delete globalThis.window;
  }
});

test('video polling is a direct PollRegistry-managed one-shot and re-arms only while a task is active', async () => {
  const state = {
    page: '视频切帧',
    project: {id: 'p1'},
    jobs: [],
    video424: [{id: 'v1', status: 'RUNNING'}],
    video424Timer: null,
  };
  const timeouts = new Map();
  const clearedTimeouts = [];
  let nextTimer = 200;
  let refreshes = 0;
  const originalSetTimeout = globalThis.setTimeout;
  const originalClearTimeout = globalThis.clearTimeout;
  globalThis.setTimeout = (callback, delay) => {
    const id = ++nextTimer;
    timeouts.set(id, {callback, delay});
    return id;
  };
  globalThis.clearTimeout = id => {
    clearedTimeouts.push(id);
    timeouts.delete(id);
  };

  let runtime;
  globalThis.window = {
    PlatformCore: {video: {isActiveVideoTask: task => String(task?.status).toUpperCase() === 'RUNNING'}},
    refreshVideo424Delta: async () => {
      refreshes += 1;
      runtime.replaceVideo424Timer();
    },
  };

  runtime = installPollRegistry({getState: () => state});

  const firstManaged = state.video424Timer;
  assert.equal(timeouts.get(firstManaged)?.delay, 2000);
  assert.deepEqual(runtime.snapshot().find(row => row.key === 'video-frames'), {
    key: 'video-frames', owners: ['视频切帧'], active: true, managed: true, delay: 2000,
  });

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
  delete globalThis.window;
});

test('clean task polling is a direct PollRegistry-managed one-shot and stops at terminal truth', async () => {
  const state = {
    page: '自动标注及清洗',
    project: {id: 'p1'},
    jobs: [],
    v427OpsTab: 'clean',
    clean427: [{id: 'c1', status: 'queued', status_text: '等待资源'}],
  };
  const timeouts = new Map();
  let nextTimer = 240;
  let refreshes = 0;
  const originalSetTimeout = globalThis.setTimeout;
  const originalClearTimeout = globalThis.clearTimeout;
  globalThis.setTimeout = (callback, delay) => {
    const id = ++nextTimer;
    timeouts.set(id, {callback, delay});
    return id;
  };
  globalThis.clearTimeout = id => timeouts.delete(id);

  let runtime;
  globalThis.window = {
    PlatformCore: {cleaning: {isActiveCleanTask: task => ['queued', 'running'].includes(String(task?.status || '').toLowerCase())}},
    refreshCleanOps427Delta: async () => {
      refreshes += 1;
      runtime.replaceCleanTaskTimer();
    },
  };

  runtime = installPollRegistry({getState: () => state});
  const first = runtime.snapshot().find(row => row.key === 'clean-tasks-v47');
  assert.deepEqual(first, {
    key: 'clean-tasks-v47', owners: ['自动标注及清洗'], active: true, managed: true, delay: 2200,
  });
  const firstTimer = [...timeouts.keys()][0];
  await timeouts.get(firstTimer).callback();
  assert.equal(refreshes, 1);
  assert.equal(runtime.snapshot().some(row => row.key === 'clean-tasks-v47'), true);

  state.clean427 = [{id: 'c1', status: 'awaiting_confirmation'}];
  const secondTimer = [...timeouts.keys()][0];
  await timeouts.get(secondTimer).callback();
  assert.equal(refreshes, 2);
  assert.equal(runtime.snapshot().some(row => row.key === 'clean-tasks-v47'), false);

  runtime.beforeNavigate('数据集');
  assert.equal(runtime.snapshot().some(row => row.key === 'clean-tasks-v47'), false);

  runtime.destroy();
  globalThis.setTimeout = originalSetTimeout;
  globalThis.clearTimeout = originalClearTimeout;
  delete globalThis.window;
});

test('source polling is a direct PollRegistry-managed interval and stops on leave', async () => {
  const state = {
    page: '素材接入',
    project: {id: 'p1'},
    jobs: [],
  };
  const callbacks = new Map();
  const cleared = [];
  let nextTimer = 300;
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
    refreshSources422: async () => { refreshes += 1; },
  };

  const runtime = installPollRegistry({getState: () => state});
  const managed = runtime.snapshot().find(row => row.key === 'sources');

  assert.deepEqual(managed, {
    key: 'sources', owners: ['素材接入'], active: true, managed: true, delay: 2500,
  });
  const timerId = [...callbacks.keys()][0];
  assert.equal(callbacks.get(timerId)?.delay, 2500);

  await callbacks.get(timerId).callback();
  assert.equal(refreshes, 1);

  runtime.beforeNavigate('数据集');
  assert.equal(callbacks.has(timerId), false);
  assert.equal(runtime.snapshot().some(row => row.key === 'sources'), false);

  runtime.destroy();
  globalThis.setInterval = originalSetInterval;
  globalThis.clearInterval = originalClearInterval;
  delete globalThis.window;
});


test('returning to a visible training tab immediately resyncs canonical truth and re-arms polling', async () => {
  const originalSetTimeout = globalThis.setTimeout;
  const originalClearTimeout = globalThis.clearTimeout;
  const timeouts = new Map();
  let nextTimer = 700;
  globalThis.setTimeout = (callback, delay) => {
    const id = ++nextTimer;
    timeouts.set(id, {callback, delay});
    return id;
  };
  globalThis.clearTimeout = id => timeouts.delete(id);

  const listeners = new Map();
  globalThis.document = {
    visibilityState: 'hidden',
    addEventListener(type, handler) { listeners.set(type, handler); },
    removeEventListener(type, handler) {
      if (listeners.get(type) === handler) listeners.delete(type);
    },
  };
  const state = {
    page: '训练任务',
    project: {id: 'p1'},
    jobs: [{id: 'j1', status: 'running', progress_percent: 10}],
  };
  const refreshCalls = [];
  globalThis.window = {
    TrainingTaskRuntime: {
      async refresh(options) {
        refreshCalls.push(options);
        state.jobs = [{id: 'j1', status: 'running', progress_percent: 42}];
      },
    },
  };

  let runtime;
  try {
    runtime = installPollRegistry({getState: () => state});
    runtime.clear('training-jobs');
    assert.equal(runtime.snapshot().some(row => row.key === 'training-jobs'), false);

    globalThis.document.visibilityState = 'visible';
    listeners.get('visibilitychange')?.();
    await Promise.resolve();
    await Promise.resolve();

    assert.equal(refreshCalls.length, 1);
    assert.deepEqual(refreshCalls[0], {render: true, force: true, source: 'visibility'});
    assert.equal(state.jobs[0].progress_percent, 42);
    assert.equal(runtime.snapshot().some(row => row.key === 'training-jobs'), true);
  } finally {
    runtime?.destroy();
    globalThis.setTimeout = originalSetTimeout;
    globalThis.clearTimeout = originalClearTimeout;
    delete globalThis.window;
    delete globalThis.document;
  }
});

test('visibility resync skips hidden documents instead of spending background requests', async () => {
  globalThis.document = {
    visibilityState: 'hidden',
    addEventListener() {},
    removeEventListener() {},
  };
  const state = {
    page: '训练任务',
    project: {id: 'p1'},
    jobs: [],
  };
  let refreshes = 0;
  globalThis.window = {
    TrainingTaskRuntime: {async refresh() { refreshes += 1; }},
  };

  const runtime = installPollRegistry({getState: () => state});
  try {
    assert.equal(await runtime.resyncVisiblePage(), false);
    assert.equal(refreshes, 0);
  } finally {
    runtime.destroy();
    delete globalThis.window;
    delete globalThis.document;
  }
});
